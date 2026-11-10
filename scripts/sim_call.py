"""Simulated caller: drives a full session through the real /call and /chat sockets, no microphone needed.

Caller speech is synthesized once with Gemini TTS (cached), resampled to the browser's mic format (PCM16 mono
16 kHz, 20 ms frames) and streamed in real time, followed by silence so the agent's VAD ends the turn. The chat
side answers input cards as they arrive, like a user typing while talking. Prints the transcript, the record,
and the server-measured latency/cost. Used for the latency numbers in the README.

    GEMINI_API_KEY=... python scripts/sim_call.py [--server http://localhost:8080] [--lang en|hi]
"""

import argparse
import array
import asyncio
import hashlib
import io
import json
import os
import time
from pathlib import Path

import httpx
import websockets
from google import genai
import google.genai.errors  # noqa: F401
from google.genai import types

CACHE = Path(os.environ.get("SIM_CACHE", Path(__file__).resolve().parent / ".tts-cache"))
FRAME = 640  # 20 ms at 16 kHz, 16-bit

SCRIPTS = {
    "en": [
        "Hi! Yes, I want to apply for the delivery job.",
        "I have about two years of experience delivering food on my bike.",
        "Night shift is best for me.",
        "I can cover HSR Layout in Bengaluru.",
        "Yes, I have my own motorbike.",
        "Okay, I'm filling those in the chat now.",
        "Done, I've sent everything.",
        "No, that's all. Thank you!",
    ],
    "hi": [
        "Haan ji, mujhe delivery job ke liye apply karna hai.",
        "Mere paas do saal ka delivery ka experience hai.",
        "Mujhe raat ki shift chahiye.",
        "Main HSR Layout, Bengaluru mein deliver kar sakta hoon.",
        "Haan, meri apni bike hai.",
        "Theek hai, main chat mein bhar raha hoon.",
        "Ho gaya, sab bhej diya.",
        "Nahi, bas itna hi. Dhanyavaad!",
    ],
}

CHAT_ANSWERS = {
    "fullName": "Ravi Kumar",
    "aadhaarNumber": "234567890124",  # Verhoeff-valid test number, not a real person's
    "ifscCode": "SBIN0001234",
    "vehicleType": "petrol_bike",
    "alternatePhone": None,
    # fallbacks if the call ends before these are captured
    "experienceYears": 2, "preferredShift": "night", "serviceArea": "HSR Layout, Bengaluru", "hasTwoWheeler": True,
}


def tts(client: genai.Client, text: str) -> bytes:
    """24 kHz PCM16 from Gemini TTS, resampled to 16 kHz. Cached on disk by text."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / (hashlib.sha1(text.encode()).hexdigest()[:16] + ".pcm")
    if path.exists():
        return path.read_bytes()
    for attempt in range(6):
        try:
            resp = _tts_request(client, text)
            break
        except genai.errors.ClientError as exc:
            if exc.code != 429 or attempt == 5:
                raise
            print("TTS rate-limited (free tier is 3/min); waiting 25 s…")
            time.sleep(25)
    pcm24 = resp.candidates[0].content.parts[0].inline_data.data
    src = array.array("h", pcm24[: len(pcm24) - len(pcm24) % 2])
    out = array.array("h", (src[int(i * 1.5)] for i in range(int(len(src) / 1.5))))
    path.write_bytes(out.tobytes())
    return out.tobytes()


def _tts_request(client: genai.Client, text: str):
    return client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=f"Say naturally, like a young man from Bengaluru on a phone call: {text}",
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Puck"))),
        ),
    )


def licence_png() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (860, 540), (233, 240, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 860, 80], fill=(20, 60, 140))
    d.text((24, 22), "UNION OF INDIA - DRIVING LICENCE - KARNATAKA", fill="white", font_size=30)
    lines = ["DL No: KA01 20190012345", "Name: RAVI KUMAR", "S/W/D of: SURESH KUMAR", "DOB: 14-06-1998",
             "Valid Till (NT): 13-06-2038", "Class of Vehicle: MCWG, LMV", "Issue Date: 20-08-2019"]
    for i, line in enumerate(lines):
        d.text((260, 110 + i * 52), line, fill=(10, 10, 10), font_size=28)
    d.rectangle([30, 110, 230, 360], outline=(80, 80, 80), width=3)
    d.text((80, 220), "PHOTO", fill=(120, 120, 120), font_size=28)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class Caller:
    def __init__(self, server: str, lines: list[bytes], texts: list[str]):
        self.http = server.rstrip("/")
        self.ws = self.http.replace("http", "ws", 1)
        self.lines, self.texts = lines, texts
        self.agent_audio_at = 0.0
        self.agent_talked = False
        self.log: list[str] = []
        self.record = None
        self.call_open = True

    async def run(self) -> str:
        async with httpx.AsyncClient(timeout=30) as http:
            sid = (await http.post(f"{self.http}/api/sessions")).json()["sessionId"]
            print(f"session {sid}  timeline: {self.http}/debug/{sid}")
            chat = await websockets.connect(f"{self.ws}/chat?sessionId={sid}&fresh=1")
            call = await websockets.connect(f"{self.ws}/call?sessionId={sid}", max_size=None)
            tasks = [asyncio.create_task(self.listen_call(call)), asyncio.create_task(self.listen_chat(chat, http, sid))]
            await self.talk(call)
            for _ in range(60):  # let the chat finish and the record arrive
                if self.record:
                    break
                await asyncio.sleep(1)
            for t in tasks:
                t.cancel()
            await chat.close()
            return sid

    async def talk(self, call) -> None:
        silence = bytes(FRAME)
        for pcm, text in zip(self.lines, self.texts):
            await self.wait_for_agent_turn_end()
            if not self.call_open:
                return
            self.log.append(f"  >> caller: {text}")
            start = time.monotonic()
            for i in range(0, len(pcm), FRAME):
                await call.send(pcm[i : i + FRAME].ljust(FRAME, b"\0"))
                await asyncio.sleep(max(0, start + (i // FRAME + 1) * 0.02 - time.monotonic()))
            self.agent_talked = False
            for _ in range(75):  # 1.5 s silence so server VAD ends the turn
                await call.send(silence)
                await asyncio.sleep(0.02)
        await self.wait_for_agent_turn_end()
        # keep sending silence (like an open mic) until the agent hangs up
        deadline = time.monotonic() + 25
        while self.call_open and time.monotonic() < deadline:
            await call.send(silence)
            await asyncio.sleep(0.02)
        await call.close()

    async def wait_for_agent_turn_end(self) -> None:
        """Agent has spoken and then been quiet for 1.5 s (playback of what it sent is accounted for)."""
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and self.call_open:
            if self.agent_talked and time.monotonic() - self.agent_audio_at > 1.5:
                return
            await asyncio.sleep(0.1)

    async def listen_call(self, call) -> None:
        try:
            async for raw in call:
                msg = json.loads(raw)
                if msg["type"] == "audio":
                    # audio arrives faster than real time; estimate when its playback ends
                    secs = len(msg["data"]) * 3 / 4 / 2 / msg.get("sampleRate", 24000)
                    self.agent_audio_at = max(self.agent_audio_at, time.monotonic()) + secs
                    self.agent_talked = True
                elif msg["type"] == "transcript" and msg["final"]:
                    self.log.append(f"  [{msg['role']}] {msg['text']}")
        except websockets.ConnectionClosed as exc:
            self.log.append(f"  -- call closed: {exc.rcvd.reason if exc.rcvd else ''}")
        finally:
            self.call_open = False

    async def listen_chat(self, chat, http: httpx.AsyncClient, sid: str) -> None:
        async for raw in chat:
            msg = json.loads(raw)
            if msg["type"] == "message":
                self.log.append(f"  (chat) {msg['role']}: {msg['text']}")
            elif msg["type"] == "inputRequest":
                field = msg["field"]
                self.log.append(f"  (chat) card: {field}")
                if field == "_mode":
                    continue  # we're calling
                await asyncio.sleep(2.0)  # "typing"
                if field == "drivingLicence":
                    files = {"file": ("licence.png", licence_png(), "image/png")}
                    value = (await http.post(f"{self.http}/sessions/{sid}/files", files=files)).json()["url"]
                else:
                    value = CHAT_ANSWERS[field]
                await chat.send(json.dumps({"type": "inputResponse", "requestId": msg["id"], "field": field, "value": value}))
            elif msg["type"] == "inputError":
                self.log.append(f"  (chat) error: {msg.get('message')}")
            elif msg["type"] == "record":
                self.record = msg["record"]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="http://localhost:8080")
    ap.add_argument("--lang", default="en", choices=SCRIPTS)
    args = ap.parse_args()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(api_version="v1beta"))
    texts = SCRIPTS[args.lang]
    lines = [tts(client, t) for t in texts]
    caller = Caller(args.server, lines, texts)
    sid = await caller.run()
    print("\n".join(caller.log))
    async with httpx.AsyncClient() as http:
        view = (await http.get(f"{args.server}/api/sessions/{sid}")).json()
    print("\nlatencies (ms):", [round(x) for x in view["latencyMs"]], " cost: $", view["costUsd"])
    print("record:", json.dumps(caller.record or view["latestRecord"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
