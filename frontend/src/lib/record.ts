import { FieldStatus } from "../protocol";

export const isPlainObject = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

export function formatValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (Array.isArray(v)) return v.map(formatValue).join(", ");
  if (typeof v === "object") return JSON.stringify(v);
  if (typeof v === "string" && /^https?:\/\//.test(v)) return v.split("/").pop() || v;
  return String(v);
}

export const fieldLabel = (name: string): string =>
  name.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/_/g, " ").toLowerCase();

export function readField(field: unknown): { value: unknown; source: unknown; status: unknown; flagged: boolean } {
  const { value, source, status } = isPlainObject(field) ? field : { value: field, source: null, status: null };
  return { value, source, status, flagged: Boolean(status) && status !== FieldStatus.VALID };
}
