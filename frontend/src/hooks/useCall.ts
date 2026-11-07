import { useCallback, useEffect, useMemo, useRef } from "react";
import * as mic from "../audio/mic";
import type { Server } from "../config";
import { errorMessage } from "../lib/errors";
import { MIC_FRAME_BYTES, MIC_FRAME_MS } from "../protocol";
import { CallState } from "../state/conversation";
import type { CallControls, Ui } from "../state/ui";
import { handleCallMessage } from "../transport/callMessages";
import { closeQuietly, socketUrl } from "../transport/socket";

// Mic audio allowed to wait in the socket's send buffer before new frames are dropped.
const MAX_SEND_BACKLOG_MS = 500;
const MAX_BUFFERED_BYTES =
  (MAX_SEND_BACKLOG_MS / MIC_FRAME_MS) * MIC_FRAME_BYTES;

export function useCall(ui: Ui, server: Server | null): CallControls {
  const wsRef = useRef<WebSocket | null>(null);
  const attempt = useRef(0);

  const release = useCallback(() => {
    attempt.current++;
    if (wsRef.current) closeQuietly(wsRef.current);
    wsRef.current = null;
    mic.stopMic();
  }, []);

  useEffect(() => release, [release]);

  const sendFrame = useCallback(
    (pcm: ArrayBuffer, level: number) => {
      ui.setLevel(level);
      const ws = wsRef.current;
      if (
        ws?.readyState === WebSocket.OPEN &&
        ws.bufferedAmount < MAX_BUFFERED_BYTES
      )
        ws.send(pcm);
    },
    [ui],
  );

  const start = useCallback(async () => {
    if (!server) return;
    const current = ++attempt.current;
    ui.setCall(CallState.CONNECTING, "waiting for microphone…");
    try {
      await mic.startMic(sendFrame);
    } catch (err) {
      if (current === attempt.current)
        ui.setCall(
          CallState.ERROR,
          errorMessage(err, "Could not start the microphone."),
        );
      return;
    }
    if (current !== attempt.current) return;

    ui.setCall(CallState.CONNECTING, "connecting…");
    let ws: WebSocket;
    try {
      ws = new WebSocket(socketUrl(server, "/call"));
    } catch (err) {
      release();
      ui.setCall(
        CallState.ERROR,
        errorMessage(err, `Could not connect to ${server.http}`),
      );
      return;
    }
    ws.binaryType = "arraybuffer";
    let connected = false;
    ws.onopen = () => {
      connected = true;
      ui.setCall(CallState.CONNECTED, "on call");
      ui.addNote("Call started");
    };
    ws.onmessage = ({ data }) => handleCallMessage(ui, data);
    ws.onclose = ({ reason }) => {
      release();
      if (connected) {
        ui.setCall(CallState.ENDED, "call ended");
        ui.addNote(`Call ended${reason ? `: ${reason}` : ""}`);
      } else {
        ui.setCall(CallState.ERROR, `Could not connect to ${server.http}`);
      }
    };
    wsRef.current = ws;
  }, [ui, server, release, sendFrame]);

  const hangUp = useCallback(() => {
    release();
    ui.setCall(CallState.ENDED, "call ended");
    ui.addNote("You hung up");
  }, [ui, release]);

  const controls = useMemo(() => ({ start, hangUp }), [start, hangUp]);

  return controls;
}
