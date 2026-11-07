export enum Role {
  USER = "user",
  AGENT = "agent",
}

export enum CallServerMessageType {
  AUDIO = "audio",
  STOP_PLAYBACK = "stopPlayback",
  TRANSCRIPT = "transcript",
}

export enum ChatServerMessageType {
  MESSAGE = "message",
  INPUT_REQUEST = "inputRequest",
  INPUT_ERROR = "inputError",
  INPUT_CANCEL = "inputCancel",
  RECORD = "record",
}

export enum ChatClientMessageType {
  INPUT_RESPONSE = "inputResponse",
}

export enum InputKind {
  TEXT = "text",
  EMAIL = "email",
  PHONE = "phone",
  NUMBER = "number",
  DATE = "date",
  SELECT = "select",
  MULTI_SELECT = "multiSelect",
  FILE = "file",
  CONFIRM = "confirm",
}

export enum Outcome {
  COMPLETED = "completed",
  PARTIAL = "partial",
  OPTED_OUT = "optedOut",
  NEEDS_REVIEW = "needsReview",
}

export enum FieldSource {
  CALL = "call",
  CHAT = "chat",
}

export enum FieldStatus {
  VALID = "valid",
  MISSING = "missing",
  INVALID = "invalid",
}
