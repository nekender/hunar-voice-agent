"""HTTP + WebSocket surface. Thin: every decision lives in runtime.Session."""

import asyncio
import json
import logging
import re
import statistics
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import validators as v
from .debug_page import render_timeline
from .files import FileStore
from .runtime import Hub
from .settings import settings
from .store import Store
from .vision import LicenceChecker
from .voice import CallBridge
from .workers import delivery_loop, sweeper_loop

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

SESSION_ID = re.compile(r"^[A-Za-z0-9_\-]{4,64}$")
FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = Store(settings.db_path)
    files = FileStore(settings)
    hub = Hub(store, LicenceChecker(settings, files), files)
    app.state.hub = hub
    tasks = [asyncio.create_task(delivery_loop(hub, settings)), asyncio.create_task(sweeper_loop(hub, settings))]
    if not settings.gemini_api_key:
        log.warning("GEMINI_API_KEY is not set: calls and licence checks are disabled")
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Hunar delivery-partner voice + chat agent", lifespan=lifespan)


def hub_of(obj: Request | WebSocket) -> Hub:
    return obj.app.state.hub


def check_session_id(session_id: str | None) -> str:
    if not session_id or not SESSION_ID.match(session_id):
        raise HTTPException(400, "sessionId must be 4-64 letters, digits, '-' or '_'")
    return session_id


def client_ip(obj: Request | WebSocket) -> str:
    fwd = obj.headers.get("fly-client-ip") or obj.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd or (obj.client.host if obj.client else "?")


# --- spend caps (in-memory; one instance) ---------------------------------------------------------------------

_call_starts: dict[str, deque[float]] = defaultdict(deque)
_live_calls = 0


def call_allowed(ip: str) -> str | None:
    now = time.time()
    starts = _call_starts[ip]
    while starts and starts[0] < now - 3600:
        starts.popleft()
    if len(starts) >= settings.max_calls_per_ip_per_hour:
        return "Call limit reached for now; please continue in chat or try again later."
    if _live_calls >= settings.max_concurrent_calls:
        return "All lines are busy; please try again in a minute or continue in chat."
    starts.append(now)
    return None


# --- channels --------------------------------------------------------------------------------------------------


@app.websocket("/chat")
async def chat_socket(ws: WebSocket, sessionId: str | None = None, fresh: str | None = None):
    await ws.accept()
    if not sessionId or not SESSION_ID.match(sessionId):
        await ws.close(code=4400, reason="bad sessionId")
        return
    session = await hub_of(ws).get(sessionId)
    await session.chat_connected(ws, fresh=fresh == "1")
    try:
        while True:
            msg = await ws.receive_json()
            match msg.get("type"):
                case "inputResponse":
                    await session.chat_input(str(msg.get("requestId")), str(msg.get("field")), msg.get("value"))
                case "optOut":
                    await session.opt_out("chat", "pressed Stop in chat")
    except (WebSocketDisconnect, json.JSONDecodeError, RuntimeError):
        pass
    finally:
        session.chat_disconnected(ws)


@app.websocket("/call")
async def call_socket(ws: WebSocket, sessionId: str | None = None):
    global _live_calls
    await ws.accept()
    if not sessionId or not SESSION_ID.match(sessionId):
        await ws.close(code=4400, reason="bad sessionId")
        return
    if not settings.gemini_api_key:
        await ws.close(code=4503, reason="voice is not configured on this server")
        return
    if denied := call_allowed(client_ip(ws)):
        await ws.close(code=4429, reason=denied)
        return
    session = await hub_of(ws).get(sessionId)
    _live_calls += 1
    try:
        await CallBridge(session, ws, settings).run()
    finally:
        _live_calls -= 1


@app.post("/sessions/{session_id}/files")
async def upload(session_id: str, request: Request, file: UploadFile = File(...)):
    check_session_id(session_id)
    data = await file.read(settings.max_upload_bytes + 1)
    try:
        name = hub_of(request).files.save(session_id, data)
    except ValueError as exc:
        raise HTTPException(415 if "accepted" in str(exc) else 413, str(exc))
    return {"url": hub_of(request).files.canonical_url(str(request.base_url), session_id, name)}


@app.get("/sessions/{session_id}/files/{name}")
async def download(session_id: str, name: str, request: Request, exp: int = 0, sig: str = ""):
    files = hub_of(request).files
    if not files.verify(session_id, name, exp, sig):
        raise HTTPException(403, "link expired or invalid")
    path = files.path(session_id, name)
    if not path:
        raise HTTPException(404)
    return FileResponse(path)


# --- HTTP access for testing + debuggability ------------------------------------------------------------------


class InputBody(BaseModel):
    field: str
    value: Any


@app.post("/api/sessions")
async def create_session(request: Request):
    sid = f"s_{uuid.uuid4().hex[:10]}"
    await hub_of(request).get(sid)
    base = str(request.base_url).rstrip("/")
    return {"sessionId": sid, "chatUrl": f"{base}/?sessionId={sid}", "timelineUrl": f"{base}/debug/{sid}"}


@app.post("/api/sessions/{session_id}/inputs")
async def submit_input(session_id: str, body: InputBody, request: Request):
    session = await hub_of(request).get(check_session_id(session_id))
    return await session.api_submit(body.field, body.value)


@app.post("/api/sessions/{session_id}/opt-out")
async def api_opt_out(session_id: str, request: Request):
    session = await hub_of(request).get(check_session_id(session_id))
    await session.opt_out("api", "opted out via API")
    return {"ok": True}


@app.post("/api/sessions/{session_id}/end")
async def api_end(session_id: str, request: Request):
    """Simulate the user walking away: produce the record now as if the inactivity timeout had fired."""
    session = await hub_of(request).get(check_session_id(session_id))
    async with session.lock:
        await session._finalize("ended via API")
    return session_view(hub_of(request), session_id)["latestRecord"]


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    hub = hub_of(request)
    if not hub.store.session_row(check_session_id(session_id)):
        raise HTTPException(404)
    await hub.get(session_id)
    return session_view(hub, session_id)


def session_view(hub: Hub, session_id: str) -> dict[str, Any]:
    session = hub.sessions[session_id]
    st = session.state
    records = hub.store.records(session_id)
    return {
        "sessionId": session_id,
        "connected": {"chat": len(session.chat_sockets), "call": session.call is not None},
        "fields": {
            n: {"status": r.status, "value": v.mask_aadhaar(r.value) if n == "aadhaarNumber" and r.value else r.value,
                "source": r.source, "attempts": r.attempts, "reason": r.reason}
            for n, r in st.resolved().items()
        },
        "pendingCard": st.pending,
        "chatQueue": st.chat_queue,
        "costUsd": round(st.cost_usd, 4),
        "latencyMs": st.latencies_ms,
        "records": [
            {"revision": r["revision"], "outcome": r["outcome"], "deliveredAt": r["delivered_at"],
             "attempts": r["attempts"], "lastError": r["last_error"]}
            for r in records
        ],
        "latestRecord": json.loads(records[-1]["body"]) if records else None,
        "timeline": [{"seq": e.seq, "at": e.at, "type": e.type, "data": redact(e.type, e.data)} for e in hub.store.events(session_id)],
    }


def redact(type_: str, data: dict[str, Any]) -> dict[str, Any]:
    if type_ == "field_observed" and data.get("field") == "aadhaarNumber":
        return {**data, "raw": "[redacted]", "value": v.mask_aadhaar(data["value"]) if data.get("value") else None}
    return data


@app.get("/api/metrics")
async def metrics(request: Request):
    """p50/p95 voice latency and cost per completed session, across all sessions on this deployment."""
    store = hub_of(request).store
    lat, costs = [], []
    for row in store.list_sessions(limit=1000):
        events = store.events(row["id"])
        lat += [e.data["ms"] for e in events if e.type == "latency"]
        if row["last_outcome"] in ("completed", "needsReview"):
            costs.append(sum(e.data["usd"] for e in events if e.type == "cost"))

    def pct(xs: list[float], p: float) -> float | None:
        return round(statistics.quantiles(xs, n=100)[p - 1]) if len(xs) >= 2 else (xs[0] if xs else None)

    return {
        "voiceLatencyMs": {"p50": pct(lat, 50), "p95": pct(lat, 95), "turns": len(lat)},
        "completedSessions": len(costs),
        "costPerCompletedSessionUsd": {"mean": round(statistics.mean(costs), 4) if costs else None,
                                       "max": round(max(costs), 4) if costs else None},
    }


@app.get("/debug/{session_id}", response_class=HTMLResponse)
async def debug_page(session_id: str, request: Request):
    hub = hub_of(request)
    if not hub.store.session_row(check_session_id(session_id)):
        raise HTTPException(404)
    await hub.get(session_id)
    return render_timeline(session_view(hub, session_id))


# --- stand-in for "another service" that receives the record ---------------------------------------------------


@app.post("/sink/records")
async def sink_receive(request: Request):
    key = request.headers.get("idempotency-key") or ""
    body = await request.json()
    new = hub_of(request).store.sink_put(key or f"{body.get('sessionId')}:{body.get('revision')}", body)
    return JSONResponse({"accepted": True, "duplicate": not new}, status_code=201 if new else 200)


@app.get("/sink/records")
async def sink_list(request: Request):
    return hub_of(request).store.sink_list()


@app.get("/healthz")
async def health():
    return {"ok": True}


if FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
