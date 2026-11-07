import type {
  CallServerMessageType,
  ChatClientMessageType,
  ChatServerMessageType,
  FieldSource,
  FieldStatus,
  InputKind,
  Outcome,
  Role,
} from "./enums";

export interface AudioMessage {
  type: CallServerMessageType.AUDIO;
  sampleRate?: number; // defaults to DEFAULT_PLAYBACK_RATE
  data: string;
}

export interface StopPlaybackMessage {
  type: CallServerMessageType.STOP_PLAYBACK;
}

export interface TranscriptMessage {
  type: CallServerMessageType.TRANSCRIPT;
  role: Role;
  text: string;
  final: boolean;
  id?: string;
}

export type CallServerMessage = AudioMessage | StopPlaybackMessage | TranscriptMessage;

export interface ChatMessage {
  type: ChatServerMessageType.MESSAGE;
  role: Role;
  text: string;
  id?: string;
}

export interface InputOption {
  value: string;
  label?: string;
}

export interface InputRequest {
  type: ChatServerMessageType.INPUT_REQUEST;
  id: string;
  field: string;
  kind: InputKind;
  label: string;
  help?: string;
  placeholder?: string;
  required?: boolean;
  pattern?: string; // JavaScript RegExp source, checked before sending
  options?: InputOption[]; // select, multiSelect
  accept?: string; // file: same syntax as <input accept>, e.g. "image/*,.pdf"
  multiple?: boolean; // file: value becomes an array of URLs
}

export interface InputError {
  type: ChatServerMessageType.INPUT_ERROR;
  requestId: string;
  message?: string;
}

export interface InputCancel {
  type: ChatServerMessageType.INPUT_CANCEL;
  requestId: string;
  reason?: string;
}

export interface RecordMessage {
  type: ChatServerMessageType.RECORD;
  record: FinalRecord;
}

export type ChatServerMessage = ChatMessage | InputRequest | InputError | InputCancel | RecordMessage;

export type InputValue = string | number | boolean | string[] | null;

export interface InputResponse {
  type: ChatClientMessageType.INPUT_RESPONSE;
  requestId: string;
  field: string;
  value: InputValue;
}

export interface UploadResponse {
  url: string;
}

export interface RecordField {
  value: unknown;
  source: FieldSource | null;
  collectedAt: string | null; // ISO 8601 with offset
  status: FieldStatus;
}

export interface RecordConflict {
  field: string;
  callValue: unknown;
  chatValue: unknown;
  resolution: string;
  reason: string;
}

export interface FinalRecord {
  sessionId: string;
  revision: number;
  outcome: Outcome;
  outcomeReason?: string;
  fields: Record<string, RecordField>;
  conflicts?: RecordConflict[];
  engagement?: { calls: number; callSeconds: number; chatMessages: number };
  costUsd?: number;
  endedAt?: string;
}
