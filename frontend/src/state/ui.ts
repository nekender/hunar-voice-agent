import type { ChatMessage, FinalRecord, InputRequest, InputValue, TranscriptMessage } from "../protocol";
import type { CallState } from "./conversation";

export interface Ui {
  setCall(state: CallState, text: string): void;
  setLevel(level: number): void;
  setNotice(text: string | null): void;
  addTranscript(msg: Omit<TranscriptMessage, "type">): void;
  addMessage(msg: Omit<ChatMessage, "type">): void;
  addNote(text: string): void;
  showInputCard(spec: InputRequest): void;
  rejectInputCard(id: string, message?: string): void;
  cancelInputCard(id: string, reason?: string): void;
  showRecord(record: FinalRecord): void;
}

/** Sends an answer to the agent; throw to reopen the card with the error message. */
export type SendInput = (spec: InputRequest, value: InputValue, files: File[]) => Promise<void>;

export interface CallControls {
  start(): void;
  hangUp(): void;
}
