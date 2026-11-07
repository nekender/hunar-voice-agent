<p align="center"><img src="../media/LogoFull.svg" alt="Hunar.ai" height="40"></p>

<h1 align="center">AI Engineer Assignment: Starter UI (optional)</h1>

**Start with [the assignment brief](../README.md)**: it describes what to build, what to submit and how it is evaluated. A [demo video](../media/demo.mp4) shows the starter's scripted flow; `?demo=1` reproduces it locally (see below).

<p align="center"><img src="../media/demo.gif" alt="Starter UI demo: a voice call and chat collecting a claim, ending in the final record"></p>

> [!CAUTION]
> **Strict requirement:** never expose secrets (API keys, tokens, credentials) to the browser or commit them to the repository. If the browser talks to a provider directly, use short-lived, scoped credentials issued by your server. See [the brief](../README.md).

## Running it

This folder is a small React + TypeScript page (Vite): a messaging-app style chat with the call button in its header and one conversation thread with the live call transcript and the agent's input cards (one at a time); each submitted input becomes a chat bubble. There is no backend; build yours with any stack. Using the starter is optional: edit it, or replace it with anything else.

Needs Node 20.19+ or 22.12+:

```sh
cd starter
npm install
npm run dev
```

Open the printed URL.

- **Demo:** `/?demo=1` runs a scripted agent in the browser (add `&pace=0.75` to run it twice as fast).
- **Your backend:** copy `.env.example` to `.env.local`, set `VITE_SERVER_URL` (e.g. `http://localhost:8080`) and restart `npm run dev`. Sockets go to `ws://<server>/call` and `ws://<server>/chat`; uploads go to `http://<server>/sessions/<id>/files`. Add `?sessionId=demo-1` to pick the session id (one is generated otherwise). `VITE_`* values are inlined into the page, so never put a secret there.
- **The contract:** every message type and field is in [`src/protocol/`](src/protocol/), all camelCase (`inputRequest`, `requestId`, ...). Change it freely on both sides.
- `npm run build` type-checks and builds to `dist/`; `npm run preview` serves the build.
- Target browsers: recent Chrome and Safari. Use headphones; browser echo cancellation is best-effort.

```text
src/
  protocol/                 the wire contract; import from "protocol"
    enums.ts                message types, roles, input kinds, record outcome/source/status
    constants.ts            audio formats: mic frames up, playback rate down
    types.ts                call + chat messages, input request/response, final record
  config.ts                 VITE_SERVER_URL, ?sessionId / ?demo / ?pace
  App.tsx                   picks demo or backend and wires it to the page
  state/                    page state, no React: reducer, actions, the `Ui` interface, mic level store
  hooks/useCall.ts          call socket: mic frames up; audio, stopPlayback, transcript down
  hooks/useChat.ts          chat socket (reconnects), uploads, inputResponse
  hooks/useConversation.ts  wraps the reducer in the `Ui` object the transports call
  transport/                socket helpers, incoming message handlers, file upload (no React)
  audio/                    mic capture (PCM16 mono 16 kHz, 20 ms frames) + gapless playback, no networking
  components/               header/, thread/, cards/ (Composer, ChoiceCard), record/
  lib/                      pure helpers: formatting, answer validation, input ids, record display
  demo/                     the ?demo=1 script only
  style.css
```

`useCall` and `useChat` are the seam to your backend: they turn socket messages into calls on the `Ui` object in `src/state/ui.ts` (`addTranscript`, `addMessage`, `showInputCard`, `rejectInputCard`, `cancelInputCard`, `showRecord`, ...), and the demo drives the same object.
