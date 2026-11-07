import { useEffect, type RefObject } from "react";

export function useFocusOnOpen(ref: RefObject<HTMLElement | null>, enabled = true): void {
  useEffect(() => {
    if (enabled) ref.current?.querySelector<HTMLElement>("input, button")?.focus({ preventScroll: true });
  }, []);
}
