import { useEffect, useState } from "react";

const TICK_MS = 500;

export function useElapsedSeconds(since: number): number {
  const [now, setNow] = useState(since);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);
  return Math.max(0, Math.floor((now - since) / 1000));
}
