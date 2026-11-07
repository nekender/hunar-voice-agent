import type { Role } from "../../protocol";
import { Stamp } from "./Stamp";

interface Props {
  role: Role;
  text: string;
  time: string;
}

export function Message({ role, text, time }: Props) {
  return (
    <div className={`bubble ${role}`}>
      {text}
      <Stamp time={time} />
    </div>
  );
}
