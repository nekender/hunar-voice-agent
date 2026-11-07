import { DEFAULT_PLAYBACK_RATE } from "../protocol";
import { currentAudioContext } from "./context";

// How far ahead of "now" playback restarts after the queue ran dry, so the first chunk isn't clipped.
const PLAYBACK_LEAD_SECONDS = 0.05;

let playhead = 0;
const playing = new Set<AudioBufferSourceNode>();

export function playPcm16(
  bytes: ArrayBuffer | Uint8Array,
  sampleRate = DEFAULT_PLAYBACK_RATE,
): void {
  const ctx = currentAudioContext();
  if (!ctx) return;
  const view = bytes instanceof ArrayBuffer ? new Uint8Array(bytes) : bytes;
  const samples = new Int16Array(
    view.buffer,
    view.byteOffset,
    view.byteLength >> 1,
  );
  if (!samples.length) return;

  const floats = Float32Array.from(samples, (s) => s / 0x8000);
  const buffer = toAudioBuffer(ctx, floats, sampleRate);
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  src.connect(ctx.destination);
  playhead = Math.max(playhead, ctx.currentTime + PLAYBACK_LEAD_SECONDS);
  src.start(playhead);
  playhead += buffer.duration;
  playing.add(src);
  src.onended = () => playing.delete(src);
}

export function stopPlayback(): void {
  for (const src of playing) {
    try {
      src.stop();
    } catch {}
  }
  playing.clear();
  playhead = 0;
}

function toAudioBuffer(
  context: AudioContext,
  floats: Float32Array<ArrayBuffer>,
  rate: number,
): AudioBuffer {
  let buffer: AudioBuffer;
  try {
    buffer = context.createBuffer(1, floats.length, rate);
  } catch {
    // Older Safari rejects some buffer rates; resample to the context rate ourselves.
    floats = resample(floats, rate, context.sampleRate);
    buffer = context.createBuffer(1, floats.length, context.sampleRate);
  }
  buffer.getChannelData(0).set(floats);
  return buffer;
}

function resample(
  input: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array<ArrayBuffer> {
  const out = new Float32Array(
    Math.max(1, Math.round((input.length * toRate) / fromRate)),
  );
  const step = fromRate / toRate;
  for (let i = 0; i < out.length; i++) {
    const pos = i * step;
    const j = Math.floor(pos);
    const k = Math.min(j + 1, input.length - 1);
    out[i] = input[j] + (input[k] - input[j]) * (pos - j);
  }
  return out;
}
