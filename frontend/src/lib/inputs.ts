import { InputKind, type InputRequest } from "../protocol";

const CHOICE_KINDS: ReadonlySet<InputKind> = new Set([InputKind.SELECT, InputKind.MULTI_SELECT, InputKind.CONFIRM]);

export const isChoiceKind = (kind: InputKind): boolean => CHOICE_KINDS.has(kind);

export const INPUT_TYPES: Partial<Record<InputKind, string>> = {
  [InputKind.TEXT]: "text",
  [InputKind.EMAIL]: "email",
  [InputKind.PHONE]: "tel",
  [InputKind.NUMBER]: "number",
  [InputKind.DATE]: "date",
};

export const inputId = (spec: InputRequest): string => `in-${spec.id}`;
export const labelId = (spec: InputRequest): string => `lbl-${spec.id}`;
