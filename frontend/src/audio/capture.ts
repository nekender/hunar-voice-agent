export const CAPTURE_PROCESSOR = "pcm16-capture";

export interface CaptureOptions {
  processorOptions: { targetRate: number; frameMs: number };
}

export interface CaptureFrame {
  pcm: ArrayBuffer;
  level: number; // RMS of the frame, 0..1
}
