"""Durable storage: an append-only event log per session, plus a record outbox.

Everything about a session is derived by replaying its events (see state.py), so a restart loses nothing.
Final records go into `records` with PRIMARY KEY (session_id, revision) and a content fingerprint; the
transaction that inserts a record also appends its `record_produced` event, so a record is produced exactly
once no matter when the process dies. Delivery is a separate at-least-once outbox pass with an idempotency key.

SQLite in WAL mode is plenty for one instance; access is serialized with a lock because sqlite3 connections
are not safe to share across threads and each call here is sub-millisecond.
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
    created_at       REAL NOT NULL,
    last_activity_at REAL NOT NULL,
    last_record_at   REAL,
    last_outcome     TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    seq        INTEGER NOT NULL,
    type       TEXT NOT NULL,
    data       TEXT NOT NULL,
    at         REAL NOT NULL,
    UNIQUE (session_id, seq)
);
CREATE TABLE IF NOT EXISTS records (
    session_id   TEXT NOT NULL REFERENCES sessions(id),
    revision     INTEGER NOT NULL,
    outcome      TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    body         TEXT NOT NULL,
    created_at   REAL NOT NULL,
    delivered_at REAL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    next_try_at  REAL NOT NULL DEFAULT 0,
    last_error   TEXT,
    PRIMARY KEY (session_id, revision)
);
CREATE TABLE IF NOT EXISTS sink (
    idempotency_key TEXT PRIMARY KEY,
    body            TEXT NOT NULL,
    received_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS records_pending ON records (delivered_at, next_try_at);
CREATE INDEX IF NOT EXISTS sessions_idle ON sessions (last_activity_at);
"""

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


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    # --- sessions + events

    def ensure_session(self, session_id: str) -> bool:
        """Create the session row if missing. Returns True if it was created."""
        now = time.time()
        with self._tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO sessions (id, created_at, last_activity_at) VALUES (?, ?, ?)",
                (session_id, now, now),
            )
            return cur.rowcount == 1

    def append(self, session_id: str, type_: str, data: dict[str, Any], at: float | None = None) -> Event:
        at = at or time.time()
        with self._tx() as c:
            return self._append(c, session_id, type_, data, at)

    def _append(self, c: sqlite3.Connection, session_id: str, type_: str, data: dict[str, Any], at: float) -> Event:
        seq = c.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE session_id = ?", (session_id,)).fetchone()[0]
        c.execute(
            "INSERT INTO events (session_id, seq, type, data, at) VALUES (?, ?, ?, ?, ?)",
            (session_id, seq, type_, json.dumps(data, default=str), at),
        )
        if type_ in ACTIVITY_EVENTS:
            c.execute("UPDATE sessions SET last_activity_at = ? WHERE id = ?", (at, session_id))
        return Event(seq, type_, data, at)

    def events(self, session_id: str) -> list[Event]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT seq, type, data, at FROM events WHERE session_id = ? ORDER BY seq", (session_id,)
            ).fetchall()
        return [Event(r["seq"], r["type"], json.loads(r["data"]), r["at"]) for r in rows]

    def session_row(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY last_activity_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def idle_sessions(self, idle_before: float) -> list[str]:
        """Sessions with activity after their last record (or no record) that have gone quiet."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT id FROM sessions
                   WHERE last_activity_at < ?
                     AND (last_record_at IS NULL OR last_activity_at > last_record_at)""",
                (idle_before,),
            ).fetchall()
        return [r["id"] for r in rows]

    # --- records

    def latest_record(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM records WHERE session_id = ? ORDER BY revision DESC LIMIT 1", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def records(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE session_id = ? ORDER BY revision", (session_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def insert_record(
        self, session_id: str, outcome: str, fingerprint: str, build: Any
    ) -> dict[str, Any] | None:
        """Atomically produce the next revision unless the latest one has the same fingerprint.

        `build(revision) -> dict` renders the body once the revision number is known (inside the transaction).
        Returns the new record body, or None if nothing changed since the last revision.
        """
        now = time.time()
        with self._tx() as c:
            last = c.execute(
                "SELECT revision, fingerprint FROM records WHERE session_id = ? ORDER BY revision DESC LIMIT 1",
                (session_id,),
            ).fetchone()
            if last and last["fingerprint"] == fingerprint:
                # Same content: mark the session as recorded so the idle sweeper stops considering it.
                c.execute("UPDATE sessions SET last_record_at = ? WHERE id = ?", (now, session_id))
                return None
            revision = (last["revision"] if last else 0) + 1
            body = build(revision)
            c.execute(
                "INSERT INTO records (session_id, revision, outcome, fingerprint, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, revision, outcome, fingerprint, json.dumps(body), now),
            )
            c.execute(
                "UPDATE sessions SET last_record_at = ?, last_outcome = ? WHERE id = ?", (now, outcome, session_id)
            )
            self._append(c, session_id, "record_produced", {"revision": revision, "outcome": outcome}, now)
            return body

    # --- the demo receiving endpoint (stands in for "another service")

    def sink_put(self, key: str, body: dict[str, Any]) -> bool:
        with self._tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO sink (idempotency_key, body, received_at) VALUES (?, ?, ?)",
                (key, json.dumps(body), time.time()),
            )
            return cur.rowcount == 1

    def sink_list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sink ORDER BY received_at DESC LIMIT ?", (limit,)).fetchall()
        return [{"idempotencyKey": r["idempotency_key"], "receivedAt": r["received_at"], "record": json.loads(r["body"])} for r in rows]

    def mark_swept(self, session_id: str) -> None:
        """Idle session with nothing worth recording: stop the sweeper from revisiting it until new activity."""
        with self._tx() as c:
            c.execute("UPDATE sessions SET last_record_at = ? WHERE id = ?", (time.time(), session_id))

    def due_deliveries(self, now: float, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE delivered_at IS NULL AND next_try_at <= ? ORDER BY created_at LIMIT ?",
                (now, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_delivered(self, session_id: str, revision: int) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE records SET delivered_at = ?, attempts = attempts + 1, last_error = NULL WHERE session_id = ? AND revision = ?",
                (time.time(), session_id, revision),
            )

    def mark_failed(self, session_id: str, revision: int, error: str, retry_in: float) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE records SET attempts = attempts + 1, last_error = ?, next_try_at = ? WHERE session_id = ? AND revision = ?",
                (error[:500], time.time() + retry_in, session_id, revision),
            )
