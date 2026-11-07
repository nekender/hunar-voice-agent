export const errorMessage = (err: unknown, fallback: string): string =>
  (err instanceof Error && err.message) || fallback;
