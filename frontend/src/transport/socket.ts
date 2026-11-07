import { sessionId, type Server } from "../config";

export const socketUrl = (server: Server, path: string): string =>
  `${server.ws}${path}?sessionId=${encodeURIComponent(sessionId)}`;

const hasType = (value: unknown): value is { type: string } =>
  typeof value === "object" && value !== null && typeof (value as { type?: unknown }).type === "string";

export function parseMessage<T extends { type: string }>(data: unknown): T | null {
  if (typeof data !== "string") return null;
  try {
    const msg: unknown = JSON.parse(data);
    return hasType(msg) ? (msg as T) : null;
  } catch {
    return null;
  }
}

export function closeQuietly(ws: WebSocket): void {
  ws.onopen = null;
  ws.onmessage = null;
  ws.onclose = null;
  ws.close();
}
