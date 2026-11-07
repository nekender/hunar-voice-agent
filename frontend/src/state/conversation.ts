import type { FinalRecord, InputRequest, InputValue, Role } from "../protocol";

export enum CallState {
  IDLE = "idle",
  CONNECTING = "connecting",
  CONNECTED = "connected",
  ENDED = "ended",
  ERROR = "error",
}

export const isInCall = (state: CallState): boolean => state === CallState.CONNECTING || state === CallState.CONNECTED;

export interface CallStatus {
  state: CallState;
  text: string;
  connectedAt: number | null;
  disabled: boolean;
}

export interface Answer {
  value: InputValue;
  display?: string;
  files?: File[];
}

export enum ThreadItemKind {
  NOTE = "note",
  TRANSCRIPT = "transcript",
  MESSAGE = "message",
  PROMPT = "prompt",
  ANSWER = "answer",
  RECORD = "record",
}

export type ThreadItem =
  | { kind: ThreadItemKind.NOTE; key: string; text: string }
  | { kind: ThreadItemKind.TRANSCRIPT; key: string; role: Role; text: string; final: boolean; time: string }
  | { kind: ThreadItemKind.MESSAGE; key: string; id?: string; role: Role; text: string; time: string }
  | { kind: ThreadItemKind.PROMPT; key: string; spec: InputRequest }
  | { kind: ThreadItemKind.ANSWER; key: string; spec: InputRequest; answer: Answer; acked: boolean; time: string }
  | { kind: ThreadItemKind.RECORD; key: string; record: FinalRecord };

export enum CardStatus {
  QUEUED = "queued",
  OPEN = "open",
  SUBMITTED = "submitted",
  CANCELLED = "cancelled",
}

export interface CardEntry {
  spec: InputRequest;
  status: CardStatus;
  last?: Answer;
  answerKey?: string;
  promptKey?: string;
}

export interface OpenCard {
  key: string;
  spec: InputRequest;
  error: string | null;
  previous?: Answer;
}

export interface ConversationState {
  call: CallStatus;
  notice: string | null;
  items: ThreadItem[];
  transcripts: Record<string, string>;
  cards: Record<string, CardEntry>;
  queue: string[];
  active: { id: string; key: string; error: string | null } | null;
}

export function initialState(call: Partial<CallStatus> = {}, notice: string | null = null): ConversationState {
  return {
    call: { state: CallState.IDLE, text: "online", connectedAt: null, disabled: false, ...call },
    notice,
    items: [],
    transcripts: {},
    cards: {},
    queue: [],
    active: null,
  };
}

export function selectOpenCard({ active, cards }: Pick<ConversationState, "active" | "cards">): OpenCard | null {
  if (!active) return null;
  const entry = cards[active.id];
  return { key: active.key, error: active.error, spec: entry.spec, previous: entry.last };
}
