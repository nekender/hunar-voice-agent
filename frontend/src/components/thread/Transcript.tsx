import type { Role } from "../../protocol";
import { Stamp } from "./Stamp";

interface Props {
  role: Role;
  text: string;
  final: boolean;
  time: string;
}

export function Transcript({ role, text, final, time }: Props) {
  return (
    <div className={`bubble spoken ${role}${final ? "" : " partial"}`}>
      <span className="text">{text}</span>
      <Stamp time={time} spoken />
    </div>
  );
}
