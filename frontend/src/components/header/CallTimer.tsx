import { useElapsedSeconds } from "../../hooks/useElapsedSeconds";
import { formatDuration } from "../../lib/format";

export function CallTimer({ since }: { since: number }) {
  const seconds = useElapsedSeconds(since);
  return <span className="timer">{formatDuration(seconds)}</span>;
}
