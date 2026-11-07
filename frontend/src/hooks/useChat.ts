import { useCallback, useEffect, useMemo, useRef } from "react";
import type { Server } from "../config";
import {
  ChatClientMessageType,
  InputKind,
  type InputResponse,
} from "../protocol";
import type { SendInput, Ui } from "../state/ui";
import { handleChatMessage } from "../transport/chatMessages";
import { closeQuietly, socketUrl } from "../transport/socket";
import { uploadFiles } from "../transport/upload";

const FIRST_RETRY_MS = 1000;
const MAX_RETRY_MS = 15000;
const NOT_CONNECTED =
  "Not connected to the server. Please try again in a moment.";

export function useChat(
  ui: Ui,
  server: Server | null,
): { sendInput: SendInput; optOut: () => void } {
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!server) return;
    const url = socketUrl(server, "/chat");
    let fresh = true; // first connect of this page load: ask the server to replay the thread
    let retryDelay = FIRST_RETRY_MS;
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout>;

    const retry = () => {
      ui.setNotice(
        `Can't reach the chat server at ${url}. Retrying in ${Math.round(retryDelay / 1000)}s…`,
      );
      timer = setTimeout(connect, retryDelay);
      retryDelay = Math.min(retryDelay * 2, MAX_RETRY_MS);
    };

    const connect = () => {
      try {
        ws = new WebSocket(fresh ? `${url}&fresh=1` : url);
      } catch {
        retry();
        return;
      }
      ws.onopen = () => {
        fresh = false;
        retryDelay = FIRST_RETRY_MS;
        ui.setNotice(null);
      };
      ws.onmessage = ({ data }) => handleChatMessage(ui, data);
      ws.onclose = retry;
      wsRef.current = ws;
    };

    // Deferred so StrictMode's dev double-mount doesn't open and immediately abort a socket.
    timer = setTimeout(connect, 0);
    return () => {
      clearTimeout(timer);
      if (ws) closeQuietly(ws);
      wsRef.current = null;
    };
  }, [ui, server]);

  const sendInput = useCallback<SendInput>(
    async (spec, value, files) => {
      if (!server) throw new Error(NOT_CONNECTED);
      openSocket(wsRef.current);
      const msg: InputResponse = {
        type: ChatClientMessageType.INPUT_RESPONSE,
        requestId: spec.id,
        field: spec.field,
        value:
          spec.kind === InputKind.FILE
            ? await uploadFiles(server, files, Boolean(spec.multiple))
            : value,
      };
      openSocket(wsRef.current).send(JSON.stringify(msg));
    },
    [server],
  );

  const optOut = useCallback(() => {
    try {
      openSocket(wsRef.current).send(JSON.stringify({ type: "optOut" }));
    } catch (err) {
      ui.setNotice(err instanceof Error ? err.message : NOT_CONNECTED);
    }
  }, [ui]);

  const controls = useMemo(() => ({ sendInput, optOut }), [sendInput, optOut]);

  return controls;
}

function openSocket(ws: WebSocket | null): WebSocket {
  if (ws?.readyState !== WebSocket.OPEN) throw new Error(NOT_CONNECTED);
  return ws;
}
