import { CallServerMessageType, ChatServerMessageType, type ChatServerMessage, type TranscriptMessage } from "../protocol";
import type { Ui } from "../state/ui";
import { parseMessage } from "./socket";

export function handleChatMessage(ui: Ui, data: unknown): void {
  const msg = parseMessage<ChatServerMessage | TranscriptMessage>(data);
  if (msg?.type === CallServerMessageType.TRANSCRIPT) {
    ui.addTranscript(msg);
    return;
  }
  switch (msg?.type) {
    case ChatServerMessageType.MESSAGE:
      ui.addMessage(msg);
      break;
    case ChatServerMessageType.INPUT_REQUEST:
      ui.showInputCard(msg);
      break;
    case ChatServerMessageType.INPUT_ERROR:
      ui.rejectInputCard(msg.requestId, msg.message);
      break;
    case ChatServerMessageType.INPUT_CANCEL:
      ui.cancelInputCard(msg.requestId, msg.reason);
      break;
    case ChatServerMessageType.RECORD:
      ui.showRecord(msg.record);
      break;
    case undefined:
      break;
    default:
      // Unknown types are ignored at runtime; this makes the compiler flag a known type left unhandled.
      msg satisfies never;
  }
}
