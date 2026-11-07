import { useFollowBottom } from "../../hooks/useFollowBottom";
import { isChoiceKind } from "../../lib/inputs";
import type { Answer, OpenCard, ThreadItem } from "../../state/conversation";
import { ChoiceCard } from "../cards/ChoiceCard";
import { Composer } from "../cards/Composer";
import { ThreadEntry } from "./ThreadEntry";

interface Props {
  serverLabel: string;
  sessionId: string;
  items: ThreadItem[];
  card: OpenCard | null;
  onAnswer: (card: OpenCard, answer: Answer) => void;
}

export function Thread({ serverLabel, sessionId, items, card, onAnswer }: Props) {
  useFollowBottom(items, card);
  const answer = (result: Answer) => card && onAnswer(card, result);
  return (
    <main className="thread">
      <div className="log" role="log" aria-label="Conversation">
        <p className="note">
          {serverLabel} · session <code>{sessionId}</code>
        </p>
        {!items.length && !card && (
          <p className="note empty">Tap the phone icon to start the call. The agent will ask for details here.</p>
        )}
        {items.map((item) => <ThreadEntry key={item.key} item={item} />)}
      </div>
      {card &&
        (isChoiceKind(card.spec.kind) ? (
          <ChoiceCard key={card.key} card={card} onAnswer={answer} />
        ) : (
          <Composer key={card.key} card={card} onAnswer={answer} />
        ))}
    </main>
  );
}
