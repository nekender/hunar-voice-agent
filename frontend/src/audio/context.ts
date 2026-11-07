let ctx: AudioContext | null = null;

export const currentAudioContext = (): AudioContext | null => ctx;

/** Must run synchronously inside a click: Safari/iOS only lets a context start from a user gesture. */
export function openAudioContext(): AudioContext {
  const context = new AudioContext();
  ctx = context;
  resume(context);
  return context;
}

export function closeAudioContext(): void {
  ctx?.close().catch(() => {});
  ctx = null;
}

function resume(context: AudioContext): void {
  context.resume().catch(() => {});
}

// iOS/Safari can suspend the context (e.g. after an interruption); it only resumes from a gesture.
document.addEventListener("click", () => {
  if (ctx && ctx.state !== "running" && ctx.state !== "closed") resume(ctx);
});
