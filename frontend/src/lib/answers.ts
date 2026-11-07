import { InputKind, type InputRequest, type InputValue } from "../protocol";
import type { Answer } from "../state/conversation";
import { matchesAccept } from "./files";

export type AnswerOrError = Answer | string;

export const SKIPPED_DISPLAY = "(skipped)";

export interface Choice {
  value: InputValue;
  label: string;
}

const SKIP: Choice = { value: null, label: "Skip" };

export function singleChoices(spec: InputRequest): Choice[] {
  if (spec.kind === InputKind.CONFIRM) {
    return [
      { value: true, label: "Yes" },
      { value: false, label: "No" },
    ];
  }
  const choices: Choice[] = (spec.options ?? []).map((o) => ({ value: o.value, label: o.label || o.value }));
  return spec.required ? choices : [...choices, SKIP];
}

export const choiceAnswer = (choice: Choice): Answer => ({
  value: choice.value,
  display: choice.value === null ? SKIPPED_DISPLAY : choice.label,
});

export function multiSelectAnswer(spec: InputRequest, checked: string[]): AnswerOrError {
  if (!checked.length && spec.required) return "Please choose at least one option.";
  const chosen = (spec.options ?? []).filter((o) => checked.includes(o.value));
  if (!chosen.length) return { value: null, display: SKIPPED_DISPLAY };
  return { value: chosen.map((o) => o.value), display: chosen.map((o) => o.label || o.value).join(", ") };
}

export function fileAnswer(spec: InputRequest, files: File[]): AnswerOrError {
  if (!files.length) return spec.required ? "Please choose a file." : { value: null, files: [], display: SKIPPED_DISPLAY };
  const rejected = files.find((file) => !matchesAccept(file, spec.accept));
  if (rejected) return `${rejected.name} is not an accepted file type.`;
  return { value: null, files };
}

export function textAnswer(spec: InputRequest, text: string, input: HTMLInputElement | null): AnswerOrError {
  const raw = text.trim();
  if (!raw) return spec.required ? "This field is required." : { value: null, display: SKIPPED_DISPLAY };
  if (input && !input.checkValidity()) return input.validationMessage || "Please enter a valid value.";
  const pattern = compilePattern(spec.pattern);
  if (pattern && !pattern.test(raw)) return `That doesn't look right.${spec.help ? ` ${spec.help}` : ""}`;
  return { value: spec.kind === InputKind.NUMBER ? Number(raw) : raw, display: raw };
}

function compilePattern(source?: string): RegExp | null {
  if (!source) return null;
  try {
    return new RegExp(source);
  } catch {
    return null;
  }
}
