import { MicIcon, TicksIcon } from "../icons";

interface Props {
  time: string;
  spoken?: boolean;
  ticks?: "sending" | "sent";
}

export function Stamp({ time, spoken = false, ticks }: Props) {
  return (
    <span className="stamp">
      {spoken && <MicIcon />}
      {time}
      {ticks && <TicksIcon label={ticks} />}
    </span>
  );
}
