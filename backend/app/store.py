"""Durable storage: an append-only event log per session, a record outbox, and uploaded files.

Everything about a session is derived by replaying its events (see state.py), so a restart loses nothing.
Final records go into `records` with PRIMARY KEY (session_id, revision) and a content fingerprint; the
transaction that inserts a record also appends its `record_produced` event, so a record is produced exactly
once no matter when the process dies. Delivery is a separate at-least-once outbox pass with an idempotency key.

Two backends behind one tiny adapter, same SQL (written with `?` placeholders):
  - Postgres when DATABASE_URL is set (production: Neon). The app host has no persistent disk, so the event
    log *and* the uploaded files live here.
  - SQLite otherwise (local runs and tests).
Calls are synchronous and serialized by a lock: each is a single-digit-millisecond statement or two, which keeps
the session code simple (no await between "read state" and "append event").
"""

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id               TEXT PRIMARY KEY,
    created_at       {real} NOT NULL,
    last_activity_at {real} NOT NULL,
    last_record_at   {real},
    last_outcome     TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id         {serial},
    session_id TEXT NOT NULL REFERENCES sessions(id),
    seq        INTEGER NOT NULL,
    type       TEXT NOT NULL,
    data       TEXT NOT NULL,
    at         {real} NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE TABLE IF NOT EXISTS records (
    session_id   TEXT NOT NULL REFERENCES sessions(id),
    revision     INTEGER NOT NULL,
    outcome      TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    body         TEXT NOT NULL,
    created_at   {real} NOT NULL,
    delivered_at {real},
    attempts     INTEGER NOT NULL DEFAULT 0,
    next_try_at  {real} NOT NULL DEFAULT 0,
    last_error   TEXT,
    PRIMARY KEY (session_id, revision)
);
CREATE TABLE IF NOT EXISTS sink (
    idempotency_key TEXT PRIMARY KEY,
    body            TEXT NOT NULL,
    received_at     {real} NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
    session_id TEXT NOT NULL,
    name       TEXT NOT NULL,
    mime       TEXT NOT NULL,
    data       {blob} NOT NULL,
    created_at {real} NOT NULL,
    PRIMARY KEY (session_id, name)
);
CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value {blob} NOT NULL
);
CREATE INDEX IF NOT EXISTS records_pending ON records (delivered_at, next_try_at);
CREATE INDEX IF NOT EXISTS sessions_idle ON sessions (last_activity_at);
"""
SQLITE_TYPES = {"real": "REAL", "serial": "INTEGER PRIMARY KEY AUTOINCREMENT", "blob": "BLOB"}
POSTGRES_TYPES = {"real": "DOUBLE PRECISION", "serial": "BIGSERIAL PRIMARY KEY", "blob": "BYTEA"}

# Event types that count as the user (or the conversation) doing something; used for inactivity timeouts.
ACTIVITY_EVENTS = {
    "session_created", "call_started", "transcript", "field_observed", "field_skipped",
    "chat_mode_entered", "opted_out", "review_flagged", "chat_connected",
}


@dataclass(frozen=True)
class Event:
    seq: int
    type: str
    data: dict[str, Any]
    at: float


class Tx:
    """What a transaction body sees: `q` returns rows as dicts, `x` returns the affected row count."""

    def __init__(self, cursor: Any, postgres: bool):
        self._c = cursor
        self._pg = postgres

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self._pg else sql

    def q(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        self._c.execute(self._sql(sql), params)
        return [dict(r) for r in self._c.fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def x(self, sql: str, params: tuple = ()) -> int:
        self._c.execute(self._sql(sql), params)
        return self._c.rowcount


class Store:
    def __init__(self, path: Path | None = None, database_url: str = "", schema: str = ""):
        self._lock = threading.Lock()
        self.postgres = bool(database_url)
        if self.postgres:
            from psycopg.conninfo import conninfo_to_dict
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            # Validate up front: an unparseable URL would otherwise make the pool retry forever and log the
            # whole connection string, password included. This error never contains the URL.
            try:
                conninfo_to_dict(database_url)
            except Exception as exc:
                raise RuntimeError(f"DATABASE_URL is not a valid Postgres URL ({type(exc).__name__}); "
                                   "check for quotes or pasted extra text") from None

            options = f"-c search_path={schema}" if schema else ""
            # check= validates a connection before handing it out: Neon suspends idle compute and drops sockets.
            self._pool = ConnectionPool(
                database_url, min_size=1, max_size=2, open=False, check=ConnectionPool.check_connection,
                kwargs={"row_factory": dict_row, "options": options} if options else {"row_factory": dict_row},
            )
            self._pool.open(wait=True, timeout=30)  # fail the boot clearly instead of retrying in the background
            if schema:
                with self._pool.connection() as conn:
                    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            ddl = SCHEMA.format(**POSTGRES_TYPES)
            with self._tx() as t:
                for stmt in filter(str.strip, ddl.split(";")):
                    t.x(stmt)
        else:
            assert path is not None
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            with self._lock:
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA synchronous=NORMAL")
                self._conn.executescript(SCHEMA.format(**SQLITE_TYPES))

    @contextmanager
    def _tx(self) -> Iterator[Tx]:
        with self._lock:
            if self.postgres:
                with self._pool.connection() as conn, conn.transaction(), conn.cursor() as cur:
                    yield Tx(cur, True)
                return
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield Tx(self._conn.cursor(), False)
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def close(self) -> None:
        if self.postgres:
            self._pool.close()
        else:
            self._conn.close()

    # --- sessions + events

    def ensure_session(self, session_id: str) -> bool:
        """Create the session row if missing. Returns True if it was created."""
        now = time.time()
        with self._tx() as t:
            return t.x(
                "INSERT INTO sessions (id, created_at, last_activity_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (session_id, now, now),
            ) == 1

    def append(self, session_id: str, type_: str, data: dict[str, Any], at: float | None = None) -> Event:
        at = at or time.time()
        with self._tx() as t:
            return self._append(t, session_id, type_, data, at)

    def _append(self, t: Tx, session_id: str, type_: str, data: dict[str, Any], at: float) -> Event:
        seq = t.one("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM events WHERE session_id = ?", (session_id,))["n"]
        t.x(
            "INSERT INTO events (session_id, seq, type, data, at) VALUES (?, ?, ?, ?, ?)",
            (session_id, seq, type_, json.dumps(data, default=str), at),
        )
        if type_ in ACTIVITY_EVENTS:
            t.x("UPDATE sessions SET last_activity_at = ? WHERE id = ?", (at, session_id))
        return Event(seq, type_, data, at)

    def events(self, session_id: str) -> list[Event]:
        with self._tx() as t:
            rows = t.q("SELECT seq, type, data, at FROM events WHERE session_id = ? ORDER BY seq", (session_id,))
        return [Event(r["seq"], r["type"], json.loads(r["data"]), r["at"]) for r in rows]

    def session_row(self, session_id: str) -> dict[str, Any] | None:
        with self._tx() as t:
            return t.one("SELECT * FROM sessions WHERE id = ?", (session_id,))

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._tx() as t:
            return t.q("SELECT * FROM sessions ORDER BY last_activity_at DESC LIMIT ?", (limit,))

    def idle_sessions(self, idle_before: float) -> list[str]:
        """Sessions with activity after their last record (or no record) that have gone quiet."""
        with self._tx() as t:
            rows = t.q(
                """SELECT id FROM sessions
                   WHERE last_activity_at < ?
                     AND (last_record_at IS NULL OR last_activity_at > last_record_at)""",
                (idle_before,),
            )
        return [r["id"] for r in rows]

    # --- records

    def latest_record(self, session_id: str) -> dict[str, Any] | None:
        with self._tx() as t:
            return t.one("SELECT * FROM records WHERE session_id = ? ORDER BY revision DESC LIMIT 1", (session_id,))

    def records(self, session_id: str) -> list[dict[str, Any]]:
        with self._tx() as t:
            return t.q("SELECT * FROM records WHERE session_id = ? ORDER BY revision", (session_id,))

    def insert_record(self, session_id: str, outcome: str, fingerprint: str, build: Any) -> dict[str, Any] | None:
        """Atomically produce the next revision unless the latest one has the same fingerprint.

        `build(revision) -> dict` renders the body once the revision number is known (inside the transaction).
        Returns the new record body, or None if nothing changed since the last revision.
        """
        now = time.time()
        with self._tx() as t:
            last = t.one(
                "SELECT revision, fingerprint FROM records WHERE session_id = ? ORDER BY revision DESC LIMIT 1",
                (session_id,),
            )
            if last and last["fingerprint"] == fingerprint:
                # Same content: mark the session as recorded so the idle sweeper stops considering it.
                t.x("UPDATE sessions SET last_record_at = ? WHERE id = ?", (now, session_id))
                return None
            revision = (last["revision"] if last else 0) + 1
            body = build(revision)
            t.x(
                "INSERT INTO records (session_id, revision, outcome, fingerprint, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, revision, outcome, fingerprint, json.dumps(body), now),
            )
            t.x("UPDATE sessions SET last_record_at = ?, last_outcome = ? WHERE id = ?", (now, outcome, session_id))
            self._append(t, session_id, "record_produced", {"revision": revision, "outcome": outcome}, now)
            return body

    def mark_swept(self, session_id: str) -> None:
        """Idle session with nothing worth recording: stop the sweeper from revisiting it until new activity."""
        with self._tx() as t:
            t.x("UPDATE sessions SET last_record_at = ? WHERE id = ?", (time.time(), session_id))

    def due_deliveries(self, now: float, limit: int = 20) -> list[dict[str, Any]]:
        with self._tx() as t:
            return t.q(
                "SELECT * FROM records WHERE delivered_at IS NULL AND next_try_at <= ? ORDER BY created_at LIMIT ?",
                (now, limit),
            )

    def mark_delivered(self, session_id: str, revision: int) -> None:
        with self._tx() as t:
            t.x(
                "UPDATE records SET delivered_at = ?, attempts = attempts + 1, last_error = NULL WHERE session_id = ? AND revision = ?",
                (time.time(), session_id, revision),
            )

    def mark_failed(self, session_id: str, revision: int, error: str, retry_in: float) -> None:
        with self._tx() as t:
            t.x(
                "UPDATE records SET attempts = attempts + 1, last_error = ?, next_try_at = ? WHERE session_id = ? AND revision = ?",
                (error[:500], time.time() + retry_in, session_id, revision),
            )

    # --- the demo receiving endpoint (stands in for "another service")

    def sink_put(self, key: str, body: dict[str, Any]) -> bool:
        with self._tx() as t:
            return t.x(
                "INSERT INTO sink (idempotency_key, body, received_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (key, json.dumps(body), time.time()),
            ) == 1

    def sink_list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._tx() as t:
            rows = t.q("SELECT * FROM sink ORDER BY received_at DESC LIMIT ?", (limit,))
        return [{"idempotencyKey": r["idempotency_key"], "receivedAt": r["received_at"], "record": json.loads(r["body"])} for r in rows]

    # --- uploaded files + small blobs

    def put_file(self, session_id: str, name: str, mime: str, data: bytes) -> None:
        with self._tx() as t:
            t.x(
                "INSERT INTO files (session_id, name, mime, data, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, name, mime, data, time.time()),
            )

    def get_file(self, session_id: str, name: str) -> tuple[str, bytes] | None:
        with self._tx() as t:
            row = t.one("SELECT mime, data FROM files WHERE session_id = ? AND name = ?", (session_id, name))
        return (row["mime"], bytes(row["data"])) if row else None

    def get_or_create_blob(self, key: str, make: Any) -> bytes:
        with self._tx() as t:
            t.x("INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT DO NOTHING", (key, make()))
            return bytes(t.one("SELECT value FROM kv WHERE key = ?", (key,))["value"])
