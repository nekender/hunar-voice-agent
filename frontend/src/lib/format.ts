// Speech RMS rarely exceeds 0.25, so scale it up to fill the meter.
const METER_GAIN = 4;

const pad2 = (n: number): string => String(Math.floor(Math.abs(n))).padStart(2, "0");

export const clockTime = (): string => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export const formatDuration = (seconds: number): string => `${pad2(seconds / 60)}:${pad2(seconds % 60)}`;

export const meterWidth = (level: number): string => `${Math.min(100, Math.round(level * METER_GAIN * 100))}%`;

export const joinList = (items: string[]): string =>
  items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;

export function isoWithOffset(date: Date): string {
  const offset = -date.getTimezoneOffset();
  const local = new Date(date.getTime() + offset * 60000).toISOString().slice(0, 19);
  return `${local}${offset >= 0 ? "+" : "-"}${pad2(offset / 60)}:${pad2(offset % 60)}`;
}

export function todayAt(time: string): string {
  const now = isoWithOffset(new Date());
  return `${now.slice(0, 11)}${time}${now.slice(19)}`;
}
