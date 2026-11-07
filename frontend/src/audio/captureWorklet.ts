import { CAPTURE_PROCESSOR, type CaptureFrame, type CaptureOptions } from "./capture";

declare const sampleRate: number;
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
}
declare function registerProcessor(name: string, ctor: new (options: CaptureOptions) => AudioWorkletProcessor): void;

class PCM16CaptureProcessor extends AudioWorkletProcessor {
  private readonly ratio: number;
  private frame: Int16Array<ArrayBuffer>;
  private index = 0;
  private phase = 0;
  private sum = 0;
  private count = 0;
  private energy = 0;

  constructor({ processorOptions: { targetRate, frameMs } }: CaptureOptions) {
    super();
    this.ratio = sampleRate / targetRate;
    this.frame = new Int16Array(Math.round((targetRate * frameMs) / 1000));
  }

  process(inputs: Float32Array[][]): boolean {
    const channel = inputs[0]?.[0];
    if (!channel) return true;
    for (const sample of channel) {
      this.sum += sample;
      this.count++;
      this.phase++;
      if (this.phase >= this.ratio) {
        this.phase -= this.ratio;
        this.push(this.sum / this.count);
        this.sum = 0;
        this.count = 0;
      }
    }
    return true;
  }

  private push(value: number): void {
    const s = Math.max(-1, Math.min(1, value));
    this.energy += s * s;
    this.frame[this.index++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    const { length } = this.frame;
    if (this.index === length) {
      const message: CaptureFrame = { pcm: this.frame.buffer, level: Math.sqrt(this.energy / length) };
      // Transferring the buffer detaches this.frame (its length becomes 0): always start a fresh one.
      this.port.postMessage(message, [message.pcm]);
      this.frame = new Int16Array(length);
      this.index = 0;
      this.energy = 0;
    }
  }
}

registerProcessor(CAPTURE_PROCESSOR, PCM16CaptureProcessor);
