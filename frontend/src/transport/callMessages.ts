import * as playback from "../audio/playback";
import { CallServerMessageType, type CallServerMessage } from "../protocol";
import type { Ui } from "../state/ui";
import { parseMessage } from "./socket";

export function handleCallMessage(ui: Ui, data: unknown): void {
  const msg = parseMessage<CallServerMessage>(data);
  switch (msg?.type) {
    case CallServerMessageType.AUDIO:
      playback.playPcm16(base64ToBytes(msg.data), msg.sampleRate && msg.sampleRate > 0 ? msg.sampleRate : undefined);
      break;
    case CallServerMessageType.STOP_PLAYBACK:
      playback.stopPlayback();
      break;
    case CallServerMessageType.TRANSCRIPT:
      ui.addTranscript(msg);
      break;
    case undefined:
      break;
    default:
      // Unknown types are ignored at runtime; this makes the compiler flag a known type left unhandled.
      msg satisfies never;
  }
}

function base64ToBytes(base64: string): Uint8Array {
  try {
    return Uint8Array.from(atob(base64 || ""), (char) => char.charCodeAt(0));
  } catch {
    return new Uint8Array(0);
  }
}
