import { useMicLevel } from "../../hooks/useMicLevel";
import { meterWidth } from "../../lib/format";

export function MicMeter() {
  const level = useMicLevel();
  return (
    <span className="meter" title="Mic level" aria-hidden="true">
      <span style={{ width: meterWidth(level) }} />
    </span>
  );
}
