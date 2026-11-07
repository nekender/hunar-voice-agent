"""The per-session orchestrator: one object both channels talk to.

The call bridge (voice.py) and the chat socket never touch each other or the database directly. They call
methods here, which validate, append events, update the folded state, and push whatever the other channel
needs to know (a new chat card, a note to the voice agent). One asyncio.Lock per session serializes
mutations, so a chat submission and a spoken answer arriving together can't interleave half-way.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Protocol

from fastapi import WebSocket

from . import record as rec
from . import validators as v
from .scenario import CHAT_ORDER, FIELDS, Channel
from .state import LICENCE_REJECT, SessionState
from .files import FileStore
from .store import Store

log = logging.getLogger("runtime")

MODE_FIELD = "_mode"  # pseudo-field for the "continue by chat instead?" card shown before any call


class CallLink(Protocol):
    call_id: str

    async def notify(self, text: str) -> None: ...
    async def hangup(self, reason: str) -> None: ...


class LicenceVerifier(Protocol):
    async def __call__(self, session_id: str, url: str) -> dict[str, Any]: ...


class Session:
    def __init__(self, hub: "Hub", session_id: str, state: SessionState):
        self.hub = hub
        self.id = session_id
        self.state = state
        self.lock = asyncio.Lock()
        self.chat_sockets: set[WebSocket] = set()
        self.call: CallLink | None = None
        self._checks: dict[str, asyncio.Task] = {}

    @property
    def store(self) -> Store:
        return self.hub.store

    @property
    def connected(self) -> bool:
        return bool(self.chat_sockets) or self.call is not None

    def emit(self, type_: str, data: dict[str, Any]) -> int:
        event = self.store.append(self.id, type_, data)
        self.state.apply(event)
        return event.seq

    async def send_chat(self, msg: dict[str, Any]) -> None:
        for ws in list(self.chat_sockets):
            try:
                await ws.send_json(msg)
            except Exception:  # a dead socket is cleaned up by its own handler
                self.chat_sockets.discard(ws)

    async def say_in_chat(self, text: str) -> None:
        seq = self.emit("chat_message", {"role": "agent", "text": text})
        await self.send_chat({"type": "message", "role": "agent", "text": text, "id": f"e{seq}"})

    async def tell_call(self, text: str) -> None:
        if self.call:
            try:
                await self.call.notify(text)
            except Exception:
                log.exception("failed to notify call %s", self.id)

    # --- chat channel ------------------------------------------------------------------------------------

    async def chat_connected(self, ws: WebSocket, fresh: bool) -> None:
        async with self.lock:
            self.chat_sockets.add(ws)
            self.emit("chat_connected", {"fresh": fresh})
            if fresh:
                await self._replay(ws)
            if not self.state.transcript and not self.state.pending and not self.state.last_outcome:
                await self.say_in_chat(
                    "Hi! I'm Asha from Hunar. I'll help you apply to be a delivery partner. Tap the call button "
                    "above to talk to me; I'll send anything that's easier to type right here in the chat."
                )
                await self._request(MODE_FIELD)
            elif self.state.pending:
                await ws.send_json(self._card(self.state.pending))
            await self._advance()

    def chat_disconnected(self, ws: WebSocket) -> None:
        self.chat_sockets.discard(ws)

    async def _replay(self, ws: WebSocket) -> None:
        """Rebuild the thread for a freshly loaded page. Ids are event-based, so the client dedupes them."""
        latest_record = None
        for e in self.store.events(self.id):
            d = e.data
            if e.type == "transcript":
                await ws.send_json({"type": "transcript", "role": d["role"], "text": d["text"], "final": True, "id": f"e{e.seq}"})
            elif e.type == "chat_message":
                await ws.send_json({"type": "message", "role": d["role"], "text": d["text"], "id": f"e{e.seq}"})
            elif (e.type == "field_observed" and d["source"] == Channel.CHAT and d["valid"]) or e.type == "field_skipped":
                answer = "(skipped)" if e.type == "field_skipped" else str(d.get("display") or d["raw"])
                await ws.send_json({"type": "message", "role": "agent", "text": FIELDS[d["field"]].label, "id": f"e{e.seq}q"})
                await ws.send_json({"type": "message", "role": "user", "text": answer, "id": f"e{e.seq}"})
            elif e.type == "record_produced":
                latest_record = d["revision"]
        if latest_record:
            row = self.store.latest_record(self.id)
            if row:
                await ws.send_json({"type": "record", "record": json.loads(row["body"])})

    async def chat_input(self, request_id: str, field: str, value: Any) -> None:
        async with self.lock:
            pending = self.state.pending
            if not pending or pending["id"] != request_id:
                await self.send_chat({"type": "inputCancel", "requestId": request_id, "reason": "This question is no longer open."})
                return
            if field == MODE_FIELD:
                await self._close(request_id)
                if value is True:
                    self.emit("chat_mode_entered", {"by": "user"})
                    await self.say_in_chat("No problem, let's do it here. A few quick questions.")
                else:
                    await self.say_in_chat("Okay! Tap the call button whenever you're ready.")
                await self._advance()
                return
            await self._resume_if_ended()
            spec = FIELDS[field]
            if value is None or value == "" or value == []:
                if spec.required:
                    await self.send_chat({"type": "inputError", "requestId": request_id, "message": "This one is required."})
                    return
                self.emit("field_skipped", {"field": field})
                await self._close(request_id)
                await self.tell_call(f"[chat] The user skipped the optional {field}. No need to ask again.")
                await self._advance()
                return
            result = self._validate(field, value)
            display = self._display(field, value, result)
            self._observe(field, value, result, Channel.CHAT, display)
            if isinstance(result, v.Invalid):
                await self.send_chat({"type": "inputError", "requestId": request_id, "message": result.reason})
                await self.tell_call(
                    f"[chat] The user submitted an invalid {field} in chat ({result.reason}). The card is still "
                    "open; if they seem stuck, briefly tell them what's wrong."
                )
                return
            await self._close(request_id)
            await self.tell_call(f"[chat] The user just submitted {field} in chat and it is valid ({display}). "
                                 "Acknowledge it briefly at a natural moment; don't ask for it again.")
            if field == "drivingLicence":
                self._start_licence_check(result.value)
            await self._advance()

    async def api_submit(self, field: str, value: Any) -> dict[str, Any]:
        """HTTP test hook: submit a chat value as the user, whether or not its card is the open one."""
        if field not in FIELDS:
            return {"ok": False, "error": f"unknown field {field}"}
        pending = self.state.pending
        if pending and pending["field"] == field:
            await self.chat_input(pending["id"], field, value)
        else:
            async with self.lock:
                await self._resume_if_ended()
                result = self._validate(field, value)
                self._observe(field, value, result, Channel.CHAT, self._display(field, value, result))
                if isinstance(result, v.Ok):
                    await self.tell_call(f"[chat] The user submitted {field} in chat and it is valid.")
                    if field == "drivingLicence":
                        self._start_licence_check(result.value)
                await self._advance()
        r = self.state.resolve(field)
        return {"ok": r.status == "valid", "status": r.status, "reason": r.reason}

    def _validate(self, field: str, value: Any) -> v.Result:
        """The one place every channel's values pass through."""
        result = FIELDS[field].validate(value)
        if FIELDS[field].kind == "file" and isinstance(result, v.Ok) and not self.hub.files.path_for_url(self.id, result.value):
            return v.Invalid("Upload not found for this session; please attach the file again.")
        return result

    @staticmethod
    def _display(field: str, raw: Any, result: v.Result) -> str:
        if isinstance(result, v.Ok):
            if field == "aadhaarNumber":
                return v.mask_aadhaar(result.value)
            if field == "drivingLicence":
                return "licence photo uploaded"
            if field in ("preferredShift", "vehicleType"):
                return (v.SHIFTS | v.VEHICLES)[result.value]
            if field == "hasTwoWheeler":
                return "Yes" if result.value else "No"
            if isinstance(result.value, float) and result.value.is_integer():
                return str(int(result.value))
            return str(result.value)
        return "invalid value" if field == "aadhaarNumber" else str(raw)[:100]

    def _observe(self, field: str, raw: Any, result: v.Result, source: str, display: str | None = None) -> None:
        ok = isinstance(result, v.Ok)
        self.emit("field_observed", {
            "field": field,
            # Never persist a rejected Aadhaar verbatim; a valid one is kept server-side and masked on export.
            "raw": raw if field != "aadhaarNumber" or ok else "[redacted]",
            "value": result.value if ok else None,
            "valid": ok,
            "reason": None if ok else result.reason,
            "source": source,
            "display": display,
        })

    async def opt_out(self, source: str, reason: str | None) -> None:
        async with self.lock:
            if self.state.opted_out:
                return
            self.emit("opted_out", {"source": source, "reason": reason})
            if self.state.pending:
                await self._close(self.state.pending["id"], cancel_reason="Application stopped.")
            await self.say_in_chat("Okay, I've stopped your application. If you change your mind, just come back to this chat.")
            await self._finalize("opt-out")
        if source == Channel.CHAT and self.call:
            await self.tell_call("[chat] The user pressed Stop in chat. Say a short goodbye and end the call.")

    async def _resume_if_ended(self) -> None:
        if self.state.opted_out:
            self.emit("resumed", {})

    # --- call channel ------------------------------------------------------------------------------------

    async def call_started(self, link: CallLink) -> None:
        async with self.lock:
            old = self.call
            self.call = link
            self.emit("call_started", {"callId": link.call_id})
            await self._resume_if_ended()
            if self.state.pending and self.state.pending["field"] == MODE_FIELD:
                await self._close(self.state.pending["id"], cancel_reason="Call started.")
        if old:
            await old.hangup("replaced by a new call")

    async def call_ended(self, link: CallLink, seconds: float, reason: str) -> None:
        async with self.lock:
            if self.call is link:
                self.call = None
            self.emit("call_ended", {"callId": link.call_id, "seconds": round(seconds, 1), "reason": reason})
            if self.state.opted_out or self.call:
                return
            if self.state.all_settled():
                await self._finalize("call ended with everything collected")
                return
            self.emit("chat_mode_entered", {"by": "call_end"})
            left = len([n for n in FIELDS if not self.state.is_settled(n)])
            await self.say_in_chat(f"Thanks for the call! Just {left} more thing{'s' if left != 1 else ''} to finish here.")
            await self._advance()

    async def voice_save_field(self, field: str, value: Any) -> dict[str, Any]:
        if field not in FIELDS:
            return {"ok": False, "error": f"Unknown field {field}. Valid: {', '.join(FIELDS)}"}
        async with self.lock:
            await self._resume_if_ended()
            result = self._validate(field, value)
            self._observe(field, value, result, Channel.CALL, self._display(field, value, result))
            if isinstance(result, v.Invalid):
                return {"ok": False, "error": result.reason}
            await self._advance()
            return {"ok": True, "saved": result.value, "stillNeeded": self._still_needed()}

    async def voice_request_in_chat(self, fields: list[str]) -> dict[str, Any]:
        async with self.lock:
            unknown = [f for f in fields if f not in FIELDS]
            have = [f for f in fields if f in FIELDS and self.state.is_settled(f)]
            todo = [f for f in fields if f in FIELDS and f not in have]
            if todo:
                self.emit("chat_queued", {"fields": todo})
                await self._advance()
            return {"sentToChat": todo, "alreadyHave": have, "unknown": unknown,
                    "note": "Cards appear one at a time in the chat. You'll get a [chat] note as each one arrives."}

    async def voice_flag(self, reason: str) -> dict[str, Any]:
        async with self.lock:
            self.emit("review_flagged", {"reason": reason[:300], "source": "call"})
        return {"ok": True}

    def voice_context(self) -> str:
        """Plain-text state summary for the voice agent's system prompt (and for resumed calls)."""
        resolved = self.state.resolved()
        lines = []
        for name, r in resolved.items():
            spec = FIELDS[name]
            if r.status == "valid":
                shown = v.mask_aadhaar(r.value) if name == "aadhaarNumber" else r.value
                lines.append(f"- {name}: HAVE ({shown}, via {r.source})")
            elif r.status == "skipped":
                lines.append(f"- {name}: skipped (optional)")
            else:
                where = "ask on the call" if spec.preferred == Channel.CALL else "request in chat"
                extra = f"; last attempt invalid: {r.reason}" if r.status == "invalid" else ""
                lines.append(f"- {name}: NEEDED, {where}{extra}")
        pending = self.state.pending
        if pending and pending["field"] != MODE_FIELD:
            lines.append(f"Chat card currently open: {pending['field']}. Queued in chat: {', '.join(self.state.chat_queue) or 'none'}.")
        recent = [t for t in self.state.transcript[-12:]]
        if recent:
            lines.append("\nMost recent conversation (oldest first):")
            lines += [f"  [{t['channel']}] {t['role']}: {t['text']}" for t in recent]
        return "\n".join(lines)

    def _still_needed(self) -> list[str]:
        return [n for n in FIELDS if not self.state.is_settled(n)]

    def record_transcript(self, role: str, text: str) -> None:
        if text.strip():
            self.emit("transcript", {"role": role, "text": text.strip()})

    def record_cost(self, usd: float, detail: dict[str, Any]) -> None:
        if usd > 0:
            self.emit("cost", {"usd": round(usd, 6), **detail})

    def record_latency(self, ms: float) -> None:
        self.emit("latency", {"ms": round(ms)})

    # --- chat flow ---------------------------------------------------------------------------------------

    def _card(self, pending: dict[str, str]) -> dict[str, Any]:
        if pending["field"] == MODE_FIELD:
            return {"type": "inputRequest", "id": pending["id"], "field": MODE_FIELD, "kind": "confirm",
                    "label": "Prefer to type instead of a call?", "required": True}
        return FIELDS[pending["field"]].input_request(pending["id"])

    async def _request(self, field: str) -> None:
        request_id = f"{field}-{uuid.uuid4().hex[:6]}"
        self.emit("input_requested", {"requestId": request_id, "field": field})
        await self.send_chat(self._card({"id": request_id, "field": field}))

    async def _close(self, request_id: str, cancel_reason: str | None = None) -> None:
        self.emit("input_closed", {"requestId": request_id, "reason": cancel_reason})
        if cancel_reason:
            await self.send_chat({"type": "inputCancel", "requestId": request_id, "reason": cancel_reason})

    async def _advance(self) -> None:
        """Decide the next chat card, or finish. Called after every state change; idempotent."""
        state = self.state
        if state.opted_out:
            return
        pending = state.pending
        if pending:
            if pending["field"] != MODE_FIELD and state.is_settled(pending["field"]):
                await self._close(pending["id"], cancel_reason="Already have this one.")
            else:
                return
        if self.call and not state.missing_required():
            # Everything required is in: make sure optional fields get offered before the agent wraps up.
            extra = [n for n in FIELDS if not state.is_settled(n) and n not in state.chat_queue]
            if extra:
                self.emit("chat_queued", {"fields": extra})
        queue = [f for f in state.chat_queue if not state.is_settled(f)]
        if state.chat_mode and not self.call:
            queue += [f for f in CHAT_ORDER if not state.is_settled(f) and f not in queue]
        if queue:
            await self._request(queue[0])
            return
        if state.all_settled() and not self._checks:
            if self.call:
                await self.tell_call("[system] Every field is collected. Thank the user, tell them the team will "
                                     "contact them within 2 days, then call end_call.")
            else:
                await self._finalize("all fields settled")  # no-op if nothing changed since the last revision

    async def _finalize(self, trigger: str) -> None:
        body = rec.content(self.state)
        now = time.time()
        produced = self.store.insert_record(
            self.id, body["outcome"], rec.fingerprint(body), lambda revision: rec.render(self.state, revision, body, now)
        )
        # insert_record appended record_produced; refresh the fold so last_revision/ended_at are current.
        self.state = SessionState.from_events(self.id, self.store.events(self.id))
        if produced is None:
            return
        log.info("record produced session=%s rev=%s outcome=%s trigger=%s", self.id, produced["revision"], produced["outcome"], trigger)
        await self.send_chat({"type": "record", "record": produced})
        if produced["outcome"] in ("completed", "needsReview"):
            await self.say_in_chat("All done, thank you! Our hiring team will contact you within 2 days.")
        self.hub.wake_delivery()

    @property
    def engaged(self) -> bool:
        """Did the user ever actually do anything? Page opens with no call and no answers produce no record."""
        return self.state.calls > 0 or bool(self.state.observations) or bool(self.state.skipped) or bool(self.state.opted_out)

    async def finalize_if_idle(self) -> None:
        async with self.lock:
            if self.connected:
                return
            if self.engaged:
                await self._finalize("inactivity")
            else:
                self.store.mark_swept(self.id)

    # --- licence verification (vision) --------------------------------------------------------------------

    def _start_licence_check(self, url: str) -> None:
        if url in self._checks or url in self.state.licence_checks:
            return
        self._checks[url] = asyncio.create_task(self._check_licence(url))

    def resume_pending_checks(self) -> None:
        """After a restart: re-run checks for uploads whose verification never finished."""
        for obs in self.state.observations.get("drivingLicence", []):
            if obs.valid and obs.value not in self.state.licence_checks:
                self._start_licence_check(obs.value)

    async def _check_licence(self, url: str) -> None:
        try:
            verdict = await self.hub.verify_licence(self.id, url)
        except Exception as exc:  # vision outage must not block the application
            log.exception("licence check failed")
            verdict = {"verdict": "unchecked", "detail": f"verification error: {type(exc).__name__}"}
        async with self.lock:
            self._checks.pop(url, None)
            usd = verdict.pop("costUsd", 0)
            self.emit("licence_checked", {"url": url, **verdict})
            self.record_cost(usd, {"kind": "vision"})
            if verdict["verdict"] in LICENCE_REJECT and self.state.resolve("drivingLicence").status != "valid":
                msg = verdict.get("detail") or "That doesn't look like a clear driving licence."
                await self.say_in_chat(f"{msg} Could you upload it again?")
                await self.tell_call(f"[chat] The licence upload was rejected ({msg}). The user has been asked to re-upload; mention it briefly.")
                self.emit("chat_queued", {"fields": ["drivingLicence"]})
            await self._advance()


class Hub:
    """Registry of live sessions. A session is loaded from the event log the first time it's touched."""

    def __init__(self, store: Store, verify_licence: LicenceVerifier, files: FileStore):
        self.store = store
        self.files = files
        self.verify_licence = verify_licence
        self.sessions: dict[str, Session] = {}
        self._delivery_wake = asyncio.Event()
        self._load_lock = asyncio.Lock()

    async def get(self, session_id: str) -> Session:
        if session_id in self.sessions:
            return self.sessions[session_id]
        async with self._load_lock:
            if session_id in self.sessions:
                return self.sessions[session_id]
            created = self.store.ensure_session(session_id)
            if created:
                self.store.append(session_id, "session_created", {})
            state = SessionState.from_events(session_id, self.store.events(session_id))
            session = Session(self, session_id, state)
            if state.active_call:
                # The process died mid-call; close it out so call counts/seconds stay truthful.
                session.emit("call_ended", {"callId": state.active_call, "seconds": 0, "reason": "server restart"})
                if not state.opted_out and not state.all_settled():
                    session.emit("chat_mode_entered", {"by": "restart"})
            session.resume_pending_checks()
            self.sessions[session_id] = session
            return session

    def wake_delivery(self) -> None:
        self._delivery_wake.set()

    async def wait_delivery_wake(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._delivery_wake.wait(), timeout)
        except TimeoutError:
            pass
        self._delivery_wake.clear()
