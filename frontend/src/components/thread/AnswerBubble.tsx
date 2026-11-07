import type { InputRequest } from "../../protocol";
import type { Answer } from "../../state/conversation";
import { FileRow } from "./FileRow";
import { Stamp } from "./Stamp";

interface Props {
  spec: InputRequest;
  answer: Answer;
  acked: boolean;
  time: string;
}

export function AnswerBubble({ spec, answer, acked, time }: Props) {
  const files = answer.files ?? [];
  return (
    <div className={`bubble user${acked ? " acked" : ""}`}>
      <span className="caption">{spec.label || spec.field}</span>
      {files.length ? files.map((file, i) => <FileRow key={`${i}:${file.name}`} file={file} />) : answer.display}
      <Stamp time={time} ticks={acked ? "sent" : "sending"} />
    </div>
  );
}
