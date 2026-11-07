import type { ChatMessage, FinalRecord, InputRequest, TranscriptMessage } from "../protocol";
import type { Answer, CallState } from "./conversation";

export enum ActionType {
  SET_CALL = "setCall",
  SET_NOTICE = "setNotice",
  ADD_NOTE = "addNote",
  ADD_TRANSCRIPT = "addTranscript",
  ADD_MESSAGE = "addMessage",
  SHOW_RECORD = "showRecord",
  SHOW_CARD = "showCard",
  REJECT_CARD = "rejectCard",
  CANCEL_CARD = "cancelCard",
  SUBMIT_CARD = "submitCard",
  ACK_ANSWER = "ackAnswer",
}

export type Action =
  | { type: ActionType.SET_CALL; state: CallState; text: string; now: number }
  | { type: ActionType.SET_NOTICE; text: string | null }
  | { type: ActionType.ADD_NOTE; text: string; key: string }
  | { type: ActionType.ADD_TRANSCRIPT; msg: Omit<TranscriptMessage, "type">; key: string; time: string }
  | { type: ActionType.ADD_MESSAGE; msg: Omit<ChatMessage, "type">; key: string; time: string }
  | { type: ActionType.SHOW_RECORD; record: FinalRecord; key: string }
  | { type: ActionType.SHOW_CARD; spec: InputRequest; key: string }
  | { type: ActionType.REJECT_CARD; id: string; message?: string; key: string }
  | { type: ActionType.CANCEL_CARD; id: string; reason?: string; key: string }
  | { type: ActionType.SUBMIT_CARD; id: string; answer: Answer; key: string; time: string }
  | { type: ActionType.ACK_ANSWER; key: string };

export type ActionOf<T extends ActionType> = Extract<Action, { type: T }>;
