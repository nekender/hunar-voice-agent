// Browser -> server: binary 20 ms frames of PCM16 LE mono at 16 kHz; dropped, not queued, while the socket is backed up.
export const MIC_SAMPLE_RATE = 16000;
export const MIC_FRAME_MS = 20;
export const MIC_FRAME_BYTES = (MIC_SAMPLE_RATE * MIC_FRAME_MS * 2) / 1000;

// Server -> browser: base64 PCM16 LE mono in AudioMessage.data, any rate per chunk.
export const DEFAULT_PLAYBACK_RATE = 24000;
