import { useEffect, useLayoutEffect, useRef } from "react";

const FOLLOW_THRESHOLD_PX = 80;

const nearBottom = (): boolean =>
  window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - FOLLOW_THRESHOLD_PX;

export function useFollowBottom(items: readonly unknown[], footer: unknown): void {
  const follow = useRef(true);
  useEffect(() => {
    let lastY = window.scrollY;
    const onScroll = () => {
      follow.current = nearBottom() || (follow.current && window.scrollY >= lastY);
      lastY = window.scrollY;
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useLayoutEffect(() => {
    if (follow.current && (items.length || footer)) window.scrollTo(0, document.documentElement.scrollHeight);
  }, [items, footer]);
}
