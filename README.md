# Asha: a voice + chat agent for delivery-partner applications

A caller applies for a delivery-partner job. **On a web call** they talk about their experience, shift, area and
vehicle. **In the chat on the same page** they type or upload the things that are awkward to say aloud: name,
Aadhaar, bank IFSC, vehicle type and a licence photo. Both channels share one session. Every session ends in a
single sanitized, versioned record that is POSTed to a receiving endpoint.

- **Live app:** `https://hunar-delivery-agent.fly.dev` (each page load is a new session; add `?sessionId=…` to resume one)
- **Session timeline (debug view):** `/debug/<sessionId>`
- **Received records (stub "other service"):** `/sink/records`
- **Metrics:** `/api/metrics` (p50/p95 latency, cost per completed session)

Use headphones on the call. Browser echo cancellation is best-effort.

---

## Scenario

| Collected on the call (conversational) | Collected in chat (awkward by voice) | Optional |
|---|---|---|
| `experienceYears`: 0–40, half-year precision ("six months" → 0.5) | `fullName`: as on Aadhaar | `alternatePhone`: Indian mobile |
| `preferredShift`: morning / afternoon / evening / night / flexible | `aadhaarNumber`: 12 digits + **Verhoeff checksum** | |
| `serviceArea`: locality + city | `ifscCode`: `AAAA0XXXXXX` | |
| `hasTwoWheeler`: yes/no | `vehicleType`: choice from a list | |
| | `drivingLicence`: photo/PDF, **checked by a vision model** | |

**What counts as invalid:**
- Experience: negative, over 40, or not a number.
- Shift: "day", because it's ambiguous. The agent asks morning or afternoon.
- Name: anything other than letters and `. ' -`.
- Aadhaar: not 12 digits, starts with 0 or 1, or fails the checksum.
- IFSC: wrong shape.
- Phone: not 10 digits starting with 6–9, or all the same digit.
- Uploads: not a JPG/PNG/WEBP/HEIC/PDF (judged by magic bytes, not the file name), over 8 MB, or belonging to another session.
- Licence photo (vision check): not a licence, unreadable, or expired. Each of these makes the field invalid and the user is asked to upload again.

## Architecture

```
 Browser (React starter UI, modified)
   │  /call  WS: PCM16 16 kHz mic frames up; 24 kHz audio, transcript, stopPlayback down
   │  /chat  WS: inputRequest / inputError / inputCancel / message / record down; inputResponse / optOut up
   │  /sessions/{id}/files: multipart upload
   ▼
 FastAPI (one process)
   ├─ voice.CallBridge ──── Gemini Live (gemini-3.1-flash-live-preview): VAD, barge-in, STT, TTS, tool calls
   │        tools: save_field · request_in_chat · flag_for_review · opt_out · end_call
   ├─ runtime.Session  ◄──── the one place both channels go through (per-session asyncio.Lock)
   │        validate → append event → fold state → push to the other channel
   ├─ state.SessionState: pure fold over the event log + resolution/conflict rules
   ├─ record.py: outcome + sanitized record + fingerprint
   ├─ vision.LicenceChecker ── gemini-3.5-flash-lite (structured JSON)
   └─ workers: outbox delivery (retry with backoff) · inactivity sweeper
   ▼
 SQLite (WAL) on a Fly volume: sessions · events (append-only) · records (outbox) · sink
```

### How the two channels share state
Every change is an **event** appended to `events`: a field observed on either channel, a card requested, a
transcript line, a call started or ended, a cost, a latency sample, a record produced. `SessionState` is a pure
fold over those events, so the in-memory state after a restart is byte-for-byte what it was before. Neither
channel talks to the other directly; both call methods on `runtime.Session`:

- **Chat → call.** A valid chat submission appends an event and queues a short `[chat] …` note for the voice
  agent. The note is sent to Gemini only when nobody has spoken for 0.8 s, so the agent acknowledges it at a
  natural pause instead of talking over the caller ("got your IFSC, thanks").
- **Call → chat.** When a call starts, the **server** sends the chat-only fields to the chat as cards (shown one at a
  time). Early testing showed the model would *say* "I've sent them to your chat" without calling the tool, so this
  is deterministic and the model is only told the cards exist. If the caller says on the call something that is
  waiting as a card, the card is withdrawn (`inputCancel`).
- **The call ends → the chat carries on.** The session switches to chat mode, and the chat asks for every
  remaining field (call fields included) using the same validators.
- **A new call → full context.** The system prompt is rebuilt from the current state (what we have, what's
  missing, the last 12 lines across both channels), and the agent is told it's a resumed conversation.

### Why the server decides and the LLM only talks
The model never writes the record. It proposes values through `save_field`, and the server validates and
normalizes them, then returns errors the agent reads back ("Aadhaar fails its checksum"). The voice agent can't
skip a required field, mark the session complete, or invent an outcome. "Everything is collected" comes from the
server as a `[system]` note.

## The final record

```jsonc
{
  "schema": "delivery-partner-application/v1",
  "sessionId": "s_6faeb4e8fd",
  "revision": 1,                      // increments on every materially different record
  "supersedes": null,                 // previous revision, if any
  "outcome": "completed",             // completed | partial | optedOut | needsReview
  "outcomeReason": "all required fields collected and valid",
  "fields": {
    "experienceYears": {"value": 2.0, "source": "call", "collectedAt": "2026-11-10T19:44:16+05:30", "status": "valid", "required": true},
    "preferredShift":  {"value": {"code": "night", "label": "Night (10pm-6am)"}, "source": "call", "status": "valid", "...": "..."},
    "aadhaarNumber":   {"value": "XXXX XXXX 0124", "source": "chat", "status": "valid", "...": "..."},
    "ifscCode":        {"value": "SBIN0001234", "source": "chat", "status": "valid", "attempts": 2, "...": "..."},
    "drivingLicence":  {"value": "https://…/files/….png?exp=…&sig=…", "status": "valid",
                        "verification": {"verdict": "valid", "nameOnCard": "RAVI KUMAR", "expiry": "2038-06-13"}},
    "alternatePhone":  {"value": null, "source": null, "status": "skipped", "required": false}
  },
  "conflicts": [
    {"field": "hasTwoWheeler", "callValue": true, "chatValue": {"code": "bicycle", "label": "Bicycle"},
     "resolution": "chatValue", "reason": "vehicle chosen from the list is more specific than the yes/no answer on the call"}
  ],
  "reviewReasons": [],
  "engagement": {"calls": 1, "callSeconds": 96, "chatMessages": 6},
  "voiceLatencyMs": {"p50": 1923, "turns": 7},
  "costUsd": 0.0554,
  "startedAt": "2026-11-10T19:43:58+05:30",
  "endedAt": "2026-11-10T19:45:20+05:30"
}
```
Field `status` is `valid | invalid | missing | skipped`. An invalid field carries `reason`, and the record never
contains a value that failed validation. `attempts` appears when a field took more than one try.

### Sanitizing: validation, normalization, conflicts
- **Validation and normalization** live in `validators.py` (pure functions, unit-tested). IFSC is upper-cased,
  phone becomes `+91XXXXXXXXXX`, all-caps or all-lowercase names become title case, months become years, and the
  Hindi shift words *subah/shaam/raat* map to shift codes.
- **Every value from either channel is kept** as an observation. Resolution picks one per field:
  - **Within a channel:** the latest value wins (the user corrected themselves).
  - **Across channels, exact identifiers** (name, IDs, IFSC): **the typed value wins**, because speech recognition garbles them.
  - **Across channels, conversational fields:** the latest value wins.
  - **Cross-field:** `vehicleType` from the list overrides the spoken yes/no `hasTwoWheeler`.
  - Every disagreement is listed in `conflicts`, with its resolution and the reason.
- **Aadhaar is masked** in the record and everywhere in the debug views. Only UIDAI-authorized entities may store
  full Aadhaar numbers, and hiring only needs it for a later, consented e-KYC step. Rejected Aadhaar inputs are never stored.
- **Uploaded documents** go out as HMAC-signed links that expire after 7 days. Unsigned file URLs return 403.

### Outcomes
| Outcome | Triggered when |
|---|---|
| `completed` | All required fields are valid (optional ones valid or skipped), the licence check passed, and nothing is flagged. Produced immediately; if a call is live, after the agent says goodbye. |
| `needsReview` | All required fields are valid, **but** a human must look: the licence couldn't be verified (low-confidence read, vision outage), the name on the licence doesn't match `fullName`, or the voice agent called `flag_for_review` (e.g. the caller says they're under 18, has no licence but wants to ride a motorbike, or asks for an accommodation). |
| `optedOut` | The user explicitly stopped: told the agent on the call (it confirms once, then `opt_out`), or pressed **Stop** in chat. |
| `partial` | Nothing happened for `INACTIVITY_SECONDS` (10 min) and no socket is open, with required fields still missing or invalid. The reason lists them, e.g. `ifscCode invalid, drivingLicence missing`. |

A page that is opened but never used (no call, no answers) produces **no** record.

**Revisions.** Records are content-fingerprinted (outcome + fields + conflicts + review reasons, excluding cost
and engagement). If the session changes after a record was produced, for example a `partial` user comes back
and finishes, or an opted-out user starts answering again (which clears the opt-out), the next end state produces
`revision: n+1` with `supersedes: n`. An unchanged session never produces a new revision, however many times the
producer runs.

**Delivery.** The record is written to `records` **in the same SQLite transaction** as its `record_produced`
event (primary key `(sessionId, revision)`), then sent by an outbox worker as a `POST` to `RECORD_WEBHOOK_URL`
with `Idempotency-Key: <sessionId>:<revision>`. Failures retry with exponential backoff up to 10 minutes. The
built-in receiver `/sink/records` dedupes on that key, and records are also logged as `RECORD {...}` lines.

### Survives a restart
- Sessions are rebuilt lazily from the event log on first touch.
- A call that was live when the process died is closed as `server restart`, and the chat takes over.
- Undelivered records are retried on boot.
- The inactivity sweeper works from database timestamps, so it still fires after a restart.
- Interrupted licence checks are re-run.
- Duplicate records are impossible: the revision insert is transactional, uses a primary key, and is fingerprint-guarded.

The tests restart the app on the same database and assert all of this (`backend/tests/test_flow.py`).

## Stack choice and cost (≤150 words)
**Gemini Live (`gemini-3.1-flash-live-preview`) proxied through FastAPI.** It's a single speech-to-speech model
with built-in VAD, barge-in and transcription in both directions. Its input and output formats (16 kHz in, 24 kHz
out) match the starter exactly, so there's no resampling. It speaks Hindi and Kannada and is among the cheapest
realtime options. The browser only ever talks to my server, so the key never leaves it. A STT→LLM→TTS pipeline
would give finer control and maybe lower cost, but needs much more work to get barge-in and latency right.
**Cost per completed session: about $0.06** (measured on production: mean $0.055, across simulated sessions of 1.5–2 min). That's
summed from Gemini's per-turn `usage_metadata` by modality at list prices: audio $3/$12 per 1M tokens in/out,
text $0.75/$4.50. The vision check adds well under $0.001. A long, meandering 6-minute real call cost $0.24,
because Live re-bills the accumulated context every turn.

## Latency
**Definition:** the time from the last mic frame with speech energy (RMS > 700 on PCM16) to the first audio chunk
of the agent's reply, measured on the server for every caller turn. It includes Gemini's end-of-speech wait
(500 ms silence) and the round trip to Gemini, but not browser↔server network or playback buffering. Turns
answering an injected chat note are excluded, since nobody spoke. `/api/metrics` reports p50/p95 across all sessions.

| | p50 | p95 | turns |
|---|---|---|---|
| **Production (Fly, Singapore), simulated caller** | **1.4 s** | **2.1 s** | 8 |
| Local (India → Google), simulated caller | 2.0 s | 4.0 s | 11 |

**Where the time goes:** turns that don't call a tool reply in about 1.1–1.3 s. Turns where the model first calls
`save_field` wait for one tool round trip before speaking and take 1.9–2.5 s. I tried Live's `NON_BLOCKING`
function behaviour so it could speak while saving, but the 3.1 Live preview closed the session, so it's off (see
"next week").

**Reproduce:** `scripts/sim_call.py` synthesizes a caller with Gemini TTS, streams it into `/call` as real 20 ms
mic frames, answers the chat cards, and prints the transcript, record, latencies and cost.

## Product decisions where the brief was vague
- **Start:** the chat greets the user and offers "Prefer to type instead of a call?". The brief says the
  conversation starts on a call, but forcing a mic on someone who can't talk right now loses applicants.
- **Chat cards go out when the call starts,** so people can type while talking; the agent mentions them in its first turn.
- **Optional fields** are always offered once, and skipping is a real state (`skipped`), not `missing`.
- **A rejected licence makes the session `partial`**, not `needsReview`, if the user leaves without re-uploading:
  the fix is in the user's hands. Uncertain checks go to a human.
- **Aadhaar masked** in the record (see above). If the downstream service needs the full number, that should be a
  separate, consented, audited flow.
- **Same session, any number of calls.** Dropping and reconnecting resumes, and the agent says "welcome back"
  and doesn't re-ask anything collected.

## Edge cases
**Handled**
- Barge-in: Gemini `interrupted` → `stopPlayback` → the transcript line is closed with "—".
- The caller corrects themselves ("make that three years").
- Ambiguous answers ("day shift").
- The same field given on both channels with different values.
- The spoken yes/no contradicting the vehicle picked in chat.
- Typos caught by the Aadhaar checksum.
- Spoofed uploads (wrong magic bytes) and another session's upload URL.
- An upload that is a selfie, or an expired licence → re-upload requested on both channels.
- The vision model failing → `unchecked` → `needsReview` (the application is never blocked).
- A stale card answered after it was withdrawn → `inputCancel`.
- The page reloaded mid-session → the thread is replayed from events (ids are stable, so no duplicates).
- The call dropping → resume with context.
- A server restart mid-call.
- Two calls for one session → the older one is hung up.
- Idle sessions, and sessions that were never used.
- Opt-out from either channel, and opting back in.
- The model saying tool syntax aloud → stripped from transcripts.
- Spend caps: 12 calls per IP per hour, 5 concurrent calls, 10 min maximum call length.

**Not handled / known limitations**
- **Single instance only.** Live sockets and per-session locks live in one process. Scaling out needs sticky
  routing by `sessionId` (e.g. Fly `fly-replay`) or Postgres advisory locks.
- **Speech recognition on Indian place names.** "Koramangala" was once transcribed as "Mangala". The agent reads
  values back, but a misheard area the caller doesn't correct goes into the record. A locality autocomplete in chat would fix it.
- Echo without headphones can make the agent hear itself; this relies on browser AEC.
- No authentication: anyone with a `sessionId` can open that session. Session ids are random, the debug views
  mask Aadhaar, and file links are signed, but this is not production access control.
- The licence check is a vision model, not a call to the Sarathi/DigiLocker APIs. It catches the wrong document,
  blur and expiry, not forgeries.
- Kannada works in the voice agent but has seen little testing. Hindi was tested on a real call.

## What I trust least
**The voice agent's turn-taking around chat notes.** The model decides when to speak, and I can only influence
*when* a note arrives, by waiting for 0.8 s of mutual silence. In testing it once said goodbye while chat items
were still open, and it sometimes asks two questions in one turn. The **record** stays correct regardless,
because the server owns completion. The *conversation* can still feel slightly off. Second place: the cost
numbers rely on `usage_metadata` being complete for every turn of a preview model.

## With another week
1. **Latency:** try non-blocking tool calls again as the model matures. Otherwise, have the agent acknowledge
   first and save in the same turn, and tune VAD silence per turn type. Measure real round trip including the browser.
2. **Horizontal scale:** Postgres + sticky sessions, and move the sweeper to a single leader.
3. **Evals:** a scripted set of 30+ simulated callers (accents, Hindi/Kannada, corrections, refusals, silence),
   run on every prompt change, asserting the final record rather than the wording.
4. Locality autocomplete in chat, plus geocoding `serviceArea` to a pincode.
5. Real verification integrations (DigiLocker for the licence, penny-drop for the bank account).
6. A proper review console for `needsReview` records.

## AI tools: where they helped and where they misled
I built this with Claude Code.
- **Helped:** scaffolding, the validators and their tests, digging through the installed `google-genai` source
  for the current Live API, and writing the simulated caller that made voice testable without a microphone.
- **Misled or needed correcting:**
  - The first voice prompt *trusted the model* to send chat cards. It said it had and hadn't, which is why the server now does it.
  - google-genai 3.0 silently defaults to API `v1`, where Live 404s. It was found by inspecting the SDK's URL, not from the docs.
  - An initially suggested vision model (`gemini-2.5-flash-lite`) is closed to new users.
  - The tests caught two real bugs in generated code: an upload-ownership check missing on one entry point, and
    `"-1"` being parsed as 1 year of experience.

## Running locally
Requires Python 3.12+ and Node 20.19+.
```bash
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
(cd frontend && npm ci && npm run build)
cp .env.example .env            # put GEMINI_API_KEY in .env (gitignored, server-side only)
set -a && . ./.env && set +a
cd backend && ../.venv/bin/uvicorn app.main:app --port 8080   # open http://localhost:8080
```
- **Tests:** `cd backend && ../.venv/bin/python -m pytest` (31 tests, no network or API key needed)
- **Simulated call:** `.venv/bin/python scripts/sim_call.py --server http://localhost:8080 [--lang hi]`
- **Frontend dev with hot reload:** `cd frontend && VITE_SERVER_URL=http://localhost:8080 npm run dev`

### HTTP API for testing
| | |
|---|---|
| `POST /api/sessions` | create a session → `{sessionId, chatUrl, timelineUrl}` |
| `POST /api/sessions/{id}/inputs` `{"field","value"}` | submit a value as the user (same validators as chat) |
| `POST /api/sessions/{id}/opt-out` | opt out |
| `POST /api/sessions/{id}/end` | act as if the user walked away: produce the record now |
| `GET /api/sessions/{id}` | fields, open card, records + delivery status, full event timeline (JSON) |
| `GET /debug/{id}` | the same as a readable timeline page |
| `GET /api/metrics` | latency p50/p95, cost per completed session |
| `GET /sink/records` | what the receiving service got |

### Deploying (Fly.io)
```bash
fly apps create hunar-delivery-agent
fly volumes create agent_data --region sin --size 1 -a hunar-delivery-agent
fly secrets set GEMINI_API_KEY=... -a hunar-delivery-agent
fly deploy
```

### Code map
```
backend/app/
  scenario.py    the fields: channel, validator, chat card shape, voice hint (single source of truth)
  validators.py  pure validation + normalization (Verhoeff, IFSC, phone, …)
  store.py       SQLite: events, sessions, records outbox, sink
  state.py       fold events → state; resolution, conflicts, review reasons
  record.py      outcome rules, sanitized record, fingerprint
  runtime.py     per-session orchestrator: chat flow, voice tool handlers, finalize
  voice.py       browser ⇄ Gemini Live bridge, prompt, tools, latency + cost accounting
  vision.py      licence check (model observations → deterministic verdict)
  files.py       upload sniffing, storage, signed links
  workers.py     outbox delivery, inactivity sweeper
  main.py        routes · debug_page.py  timeline HTML
frontend/        the starter UI + same-origin server, history replay on reload, Stop button
scripts/sim_call.py  synthetic caller for end-to-end voice tests and latency measurement
```
