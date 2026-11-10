"""Browser <-> Gemini Live bridge for one call.

The browser streams PCM16/16 kHz mic frames to us; we forward them to Gemini Live, which does VAD, barge-in,
transcription and speech. The API key stays on this server. Gemini's tool calls land in Session methods, and
notes from the chat channel are fed back to the model as text at a quiet moment.

Latency is measured here: per user turn, time from the last mic frame above a speech-energy threshold to the
first audio chunk of the agent's reply (so it includes Gemini's end-of-speech wait, which is what a caller feels).
"""

import array
import asyncio
import base64
import logging
import math
import re
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from .runtime import Session
from .scenario import CALL_FIELDS, CHAT_FIELDS, FIELDS
from .settings import Settings

log = logging.getLogger("voice")

MIC_RATE = 16000
OUT_RATE = 24000
SPEECH_RMS = 700  # PCM16 RMS above this counts as the user talking (headset mic, normal voice)
QUIET_BEFORE_NOTE_S = 0.8
# The native-audio model occasionally verbalizes tool-call syntax; keep it out of transcripts and the log.
TOOL_LEAK = re.compile(
    r"[\w:]*(?:save_field|request_in_chat|flag_for_review|opt_out|end_call)(?:\{(?:\w+:[\w\-]+,?)*(?:value|field|reason)?\}?)?"
)  # wait for this much silence on both sides before injecting a chat note

PERSONA = """You are Asha, a friendly recruiter at Hunar.ai, on a phone call helping someone apply for a
delivery-partner job (two-wheeler or bicycle deliveries for food/grocery/parcel apps in Indian cities).

How you talk:
- This is a phone call: short, warm sentences. One question at a time. Never read out lists of field names.
- Speak the language the caller uses (English, Hindi or Kannada) and switch when they switch, mid-call too.
  Keep field values you save in English/Latin script.
- If the caller asks about pay, timing or the company, say pay depends on city, shift and orders, and the hiring
  team will share exact details; never promise selection or amounts.

What you must collect:
- On the call, conversationally: {call_fields}.
- In the chat (they're awkward to say aloud): {chat_fields}. The app has ALREADY sent these to the caller's chat
  as the call started. In your first turn, tell them a few short things are waiting in their chat to fill
  whenever convenient while you keep talking. Use request_in_chat only to re-send something. Never ask them to
  read their Aadhaar number aloud; if they start reading out an ID, gently point them to the chat instead.
- alternatePhone is optional; it's sent to the chat, skipping is fine.

Rules:
- Never say tool names, field names or anything in braces out loud.
- Ask exactly one question per turn.
- Call save_field as soon as you hear an answer; if it returns an error, explain kindly and ask again.
  Confirm numbers back briefly ("two years, got it").
- Messages starting with [chat] or [system] come from the app, not the caller. React briefly at a natural moment
  (e.g. "got your IFSC, thanks"), never read them out verbatim, never ask again for something already received.
- If the caller clearly wants to stop the application, confirm once, then call opt_out, say goodbye, call end_call.
- Call flag_for_review (and carry on) if something needs a human decision: they say they're under 18, they have
  no licence but want to ride a motorbike, they ask for a disability accommodation, or anything else you
  shouldn't decide.
- Once your call questions are done but chat items are still open, don't say goodbye: tell them you'll wait
  while they fill the chat, and acknowledge each [chat] note as it comes. Only end early if they want to go
  (the chat will continue without you).
- When the app tells you everything is collected, thank them, say the team will contact them within 2 days,
  and call end_call.

Field notes:
{field_notes}
"""


def system_prompt(session: Session) -> str:
    notes = "\n".join(f"- {name}: {f.voice_hint}" for name, f in FIELDS.items())
    prompt = PERSONA.format(call_fields=", ".join(CALL_FIELDS), chat_fields=", ".join(CHAT_FIELDS), field_notes=notes)
    context = session.voice_context()
    resumed = session.state.calls > 0 or bool(session.state.observations)
    header = ("This is a RESUMED conversation; the caller already spoke with you or used the chat. Do not "
              "re-introduce the whole process or re-ask anything marked HAVE; pick up where things left off."
              if resumed else "This is the first contact.")
    return f"{prompt}\nSession state right now:\n{header}\n{context}"


TOOLS = [
    {
        "function_declarations": [
            {
                "name": "save_field",
                "description": "Save a value the caller gave on the call. The server validates and normalizes it.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "field": {"type": "STRING", "enum": list(FIELDS)},
                        "value": {"type": "STRING", "description": "The value as heard, e.g. '2', 'night', 'yes', 'HSR Layout, Bengaluru'."},
                    },
                    "required": ["field", "value"],
                },
            },
            {
                "name": "request_in_chat",
                "description": "Send input cards to the caller's chat for fields that are awkward to say aloud.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"fields": {"type": "ARRAY", "items": {"type": "STRING", "enum": list(FIELDS)}}},
                    "required": ["fields"],
                },
            },
            {
                "name": "flag_for_review",
                "description": "Mark the application for a human recruiter to review, with a short reason.",
                "parameters": {"type": "OBJECT", "properties": {"reason": {"type": "STRING"}}, "required": ["reason"]},
            },
            {
                "name": "opt_out",
                "description": "The caller explicitly asked to stop the application.",
                "parameters": {"type": "OBJECT", "properties": {"reason": {"type": "STRING"}}, "required": ["reason"]},
            },
            {
                "name": "end_call",
                "description": "Hang up after your goodbye has been spoken.",
                "parameters": {"type": "OBJECT", "properties": {"reason": {"type": "STRING"}}},
            },
        ]
    }
]


def clean(text: str) -> str:
    return re.sub(r"\s{2,}", " ", TOOL_LEAK.sub("", text)).strip()


def rms(frame: bytes) -> float:
    samples = array.array("h", frame[: len(frame) - len(frame) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples))


class CallBridge:
    def __init__(self, session: Session, ws: WebSocket, settings: Settings):
        self.session = session
        self.ws = ws
        self.settings = settings
        self.call_id = f"c_{uuid.uuid4().hex[:8]}"
        self.live: Any = None
        self.started = time.monotonic()
        self.closed = asyncio.Event()
        self.end_reason = "user hung up"
        self.notes: list[str] = []
        # turn bookkeeping
        self.last_voice_at = 0.0
        self.user_turn_open = False  # user spoke since the agent last started a reply
        self.agent_speaking = False
        self.agent_audio_s = 0.0  # seconds of audio sent in the current agent turn
        self.agent_turn_started = 0.0
        self.user_text = ""
        self.agent_text = ""
        self.user_line = 0
        self.agent_line = 0
        self.ending = False
        self.registered = False

    # CallLink protocol --------------------------------------------------------------------------------------

    async def notify(self, text: str) -> None:
        self.notes.append(text)

    async def hangup(self, reason: str) -> None:
        self.end_reason = reason
        self.closed.set()

    # main loop ---------------------------------------------------------------------------------------------

    async def run(self) -> None:
        # google-genai 3.x defaults to API v1, where the Live endpoint 404s; Live is served on v1beta.
        client = genai.Client(api_key=self.settings.gemini_api_key, http_options=types.HttpOptions(api_version="v1beta"))
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=system_prompt(self.session),
            tools=TOOLS,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self.settings.voice_name))
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    silence_duration_ms=500,
                    prefix_padding_ms=100,
                )
            ),
            context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        )
        try:
            async with client.aio.live.connect(model=self.settings.live_model, config=config) as live:
                self.live = live
                await self.session.call_started(self)
                self.registered = True
                opener = ("[system] The call just connected. Greet the caller as Asha from Hunar, confirm they want to "
                          "apply for a delivery-partner job, and ask your first question.")
                if self.session.state.calls > 1 or self.session.state.observations:
                    opener = ("[system] The caller is back on a new call. Welcome them back in one sentence and continue "
                              "with what's still needed.")
                await live.send_realtime_input(text=opener)
                tasks = [
                    asyncio.create_task(self._pump_mic(), name="mic"),
                    asyncio.create_task(self._pump_model(), name="model"),
                    asyncio.create_task(self._flush_notes(), name="notes"),
                    asyncio.create_task(self.closed.wait(), name="closed"),
                ]
                done, pending = await asyncio.wait(tasks, timeout=self.settings.max_call_seconds, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    self.end_reason = "max call length reached"
                for t in done:
                    if t.exception() and not isinstance(t.exception(), (WebSocketDisconnect, asyncio.CancelledError)):
                        exc = t.exception()
                        log.error("call task %s failed: %r", t.get_name(), exc)
                        self.end_reason = f"error in {t.get_name()}: {type(exc).__name__}"
                        # Keep the provider's actual message (e.g. a quota or keepalive close) in the timeline.
                        self.session.emit_soft("error", {"where": f"voice:{t.get_name()}", "message": f"{type(exc).__name__}: {str(exc)[:300]}"})
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        except Exception as exc:
            log.exception("live session failed")
            self.end_reason = f"voice provider error: {type(exc).__name__}"
            self.session.emit_soft("error", {"where": "voice", "message": str(exc)[:300]})
        finally:
            # Every step runs even if an earlier one fails: a call that ends without call_ended would leave the
            # session believing it's still on a call (no chat takeover, no inactivity record).
            try:
                self._finish_lines()
            except Exception:
                log.exception("finishing transcript lines failed")
            if self.registered:
                try:
                    await self.session.call_ended(self, time.monotonic() - self.started, self.end_reason)
                except Exception:
                    log.exception("recording call end failed; detaching call")
                    self.session.detach_call(self)
            try:
                await self.ws.close(reason=self.end_reason[:120])
            except Exception:
                pass

    async def _pump_mic(self) -> None:
        mime = f"audio/pcm;rate={MIC_RATE}"
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                self.end_reason = "user hung up"
                return
            frame = msg.get("bytes")
            if not frame:
                continue
            if rms(frame) > SPEECH_RMS:
                self.last_voice_at = time.monotonic()
                self.user_turn_open = True
            await self.live.send_realtime_input(audio=types.Blob(data=frame, mime_type=mime))

    async def _pump_model(self) -> None:
        while True:
            got_any = False
            async for msg in self.live.receive():
                got_any = True
                try:
                    await self._on_message(msg)
                except Exception as exc:  # one bad message (or a DB blip) must not end the call
                    log.exception("handling a live message failed; continuing")
                    self.session.emit_soft("error", {"where": "voice:message", "message": f"{type(exc).__name__}: {str(exc)[:200]}"})
            if not got_any:
                self.end_reason = "voice provider closed the session"
                return

    async def _on_message(self, msg: types.LiveServerMessage) -> None:
        if msg.usage_metadata:
            self._account(msg.usage_metadata)
        if msg.tool_call and msg.tool_call.function_calls:
            self._close_user_line()
            responses = []
            for call in msg.tool_call.function_calls:
                result = await self._run_tool(call.name, call.args or {})
                responses.append(types.FunctionResponse(id=call.id, name=call.name, response=result))
            await self.live.send_tool_response(function_responses=responses)
        if msg.go_away:
            log.warning("gemini go_away: %s", msg.go_away)
        sc = msg.server_content
        if not sc:
            return
        if sc.interrupted:
            await self._send({"type": "stopPlayback"})
            self._close_agent_line(interrupted=True)
        if sc.input_transcription and sc.input_transcription.text:
            self.user_text += sc.input_transcription.text
            await self._send_line("user", self.user_text, final=False)
        if sc.model_turn and sc.model_turn.parts:
            for part in sc.model_turn.parts:
                blob = part.inline_data
                if blob and blob.data and (blob.mime_type or "").startswith("audio/"):
                    await self._on_agent_audio(blob.data)
        if sc.output_transcription and sc.output_transcription.text:
            self._close_user_line()
            self.agent_text += sc.output_transcription.text
            await self._send_line("agent", self.agent_text, final=False)
        if sc.turn_complete:
            self._close_user_line()
            self._close_agent_line()
            if self.ending:
                remaining = max(0.0, self.agent_audio_s - (time.monotonic() - self.agent_turn_started))
                asyncio.get_running_loop().call_later(remaining + 0.6, self.closed.set)
            self.agent_speaking = False

    async def _on_agent_audio(self, data: bytes) -> None:
        now = time.monotonic()
        if not self.agent_speaking:
            self._close_user_line()
            self.agent_speaking = True
            self.agent_turn_started = now
            self.agent_audio_s = 0.0
            if self.user_turn_open and self.last_voice_at:
                gap_ms = (now - self.last_voice_at) * 1000
                if 150 < gap_ms < 10000:  # <150 ms means mic bleed/echo, not a turn
                    self.session.record_latency(gap_ms)
            self.user_turn_open = False
        self.agent_audio_s += len(data) / 2 / OUT_RATE
        await self._send({"type": "audio", "data": base64.b64encode(data).decode(), "sampleRate": OUT_RATE})

    # transcripts ----------------------------------------------------------------------------------------------

    async def _send_line(self, role: str, text: str, final: bool) -> None:
        n = self.user_line if role == "user" else self.agent_line
        text = clean(text)
        await self._send({"type": "transcript", "role": role, "text": text.strip(), "final": final, "id": f"{self.call_id}-{role[0]}{n}"})

    def _close_user_line(self) -> None:
        if self.user_text.strip():
            text = self.user_text
            asyncio.create_task(self._send_line("user", text, final=True))
            self.session.record_transcript("user", clean(text))
            self.user_line += 1
        self.user_text = ""

    def _close_agent_line(self, interrupted: bool = False) -> None:
        if self.agent_text.strip():
            text = self.agent_text + (" —" if interrupted else "")
            asyncio.create_task(self._send_line("agent", text, final=True))
            self.session.record_transcript("agent", clean(text))
            self.agent_line += 1
        self.agent_text = ""
        if interrupted:
            self.agent_speaking = False

    def _finish_lines(self) -> None:
        self._close_user_line()
        self._close_agent_line()

    async def _send(self, msg: dict[str, Any]) -> None:
        try:
            await self.ws.send_json(msg)
        except Exception:
            self.closed.set()

    # tools + notes ---------------------------------------------------------------------------------------------

    async def _run_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        log.info("tool %s %s", name, {k: ("…" if k == "value" and args.get("field") == "aadhaarNumber" else v) for k, v in args.items()})
        try:
            match name:
                case "save_field":
                    return await self.session.voice_save_field(str(args.get("field")), args.get("value"))
                case "request_in_chat":
                    return await self.session.voice_request_in_chat([str(f) for f in args.get("fields", [])])
                case "flag_for_review":
                    return await self.session.voice_flag(str(args.get("reason", "")))
                case "opt_out":
                    await self.session.opt_out("call", str(args.get("reason") or "asked to stop on the call"))
                    return {"ok": True, "next": "Say a short goodbye, then call end_call."}
                case "end_call":
                    self.ending = True
                    self.end_reason = f"agent ended the call: {args.get('reason') or 'done'}"
                    if not self.agent_speaking:
                        asyncio.get_running_loop().call_later(4.0, self.closed.set)  # goodbye not started yet
                    return {"ok": True}
        except Exception as exc:
            log.exception("tool %s failed", name)
            self.session.emit_soft("error", {"where": f"tool:{name}", "message": str(exc)[:300]})
            return {"ok": False, "error": "internal error, carry on"}
        return {"ok": False, "error": f"unknown tool {name}"}

    async def _flush_notes(self) -> None:
        """Deliver chat notes only when nobody is talking, so the agent can acknowledge them naturally."""
        while True:
            await asyncio.sleep(0.2)
            if not self.notes or self.agent_speaking:
                continue
            if time.monotonic() - self.last_voice_at < QUIET_BEFORE_NOTE_S:
                continue
            batch, self.notes = self.notes, []
            self.user_turn_open = False  # the reply that follows answers the note, not the caller
            await self.live.send_realtime_input(text="\n".join(batch))

    # cost -----------------------------------------------------------------------------------------------------

    def _account(self, usage: types.UsageMetadata) -> None:
        s = self.settings
        usd = 0.0
        detail: dict[str, int] = {}
        for items, kind in ((usage.prompt_tokens_details, "in"), (usage.response_tokens_details, "out")):
            for d in items or []:
                modality = str(d.modality.value if d.modality else "TEXT").upper()
                count = d.token_count or 0
                detail[f"{kind}_{modality.lower()}"] = detail.get(f"{kind}_{modality.lower()}", 0) + count
                audio = modality == "AUDIO"
                rate = (s.price_live_audio_in if audio else s.price_live_text_in) if kind == "in" else (
                    s.price_live_audio_out if audio else s.price_live_text_out)
                usd += count * rate / 1_000_000
        if not detail and usage.total_token_count:  # no modality breakdown: price conservatively as audio
            usd = (usage.prompt_token_count or 0) * s.price_live_audio_in / 1e6 + (usage.response_token_count or 0) * s.price_live_audio_out / 1e6
            detail = {"total": usage.total_token_count}
        thoughts = usage.thoughts_token_count or 0
        if thoughts:
            usd += thoughts * s.price_live_text_out / 1e6
            detail["thoughts"] = thoughts
        self.session.record_cost(usd, {"kind": "live", **detail})
