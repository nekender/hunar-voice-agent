export const randomId = (): string =>
  crypto.randomUUID?.() ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;

let lastKey = 0;

export const nextKey = (): string => String(++lastKey);
