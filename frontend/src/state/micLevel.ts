let level = 0;
const listeners = new Set<() => void>();

export function setMicLevel(next: number): void {
  if (next === level) return;
  level = next;
  listeners.forEach((listener) => listener());
}

export const getMicLevel = (): number => level;

export function subscribeMicLevel(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
