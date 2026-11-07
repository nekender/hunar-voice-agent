import { ThreadItemKind, type ThreadItem } from "../../state/conversation";
import { RecordCard } from "../record/RecordCard";
import { AnswerBubble } from "./AnswerBubble";
import { Message } from "./Message";
import { Note } from "./Note";
import { Prompt } from "./Prompt";
import { Transcript } from "./Transcript";

export function ThreadEntry({ item }: { item: ThreadItem }) {
  switch (item.kind) {
    case ThreadItemKind.NOTE:
      return <Note text={item.text} />;
    case ThreadItemKind.TRANSCRIPT:
      return <Transcript role={item.role} text={item.text} final={item.final} time={item.time} />;
    case ThreadItemKind.MESSAGE:
      return <Message role={item.role} text={item.text} time={item.time} />;
    case ThreadItemKind.PROMPT:
      return <Prompt spec={item.spec} />;
    case ThreadItemKind.ANSWER:
      return <AnswerBubble spec={item.spec} answer={item.answer} acked={item.acked} time={item.time} />;
    case ThreadItemKind.RECORD:
      return <RecordCard record={item.record} />;
  }
}
