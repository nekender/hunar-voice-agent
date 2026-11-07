import { useRef, useState, type FormEvent } from "react";
import { useFocusOnOpen } from "../../hooks/useFocusOnOpen";
import { choiceAnswer, multiSelectAnswer, singleChoices } from "../../lib/answers";
import { labelId } from "../../lib/inputs";
import { InputKind } from "../../protocol";
import type { Answer, OpenCard } from "../../state/conversation";
import { Prompt } from "../thread/Prompt";
import { ErrorLine } from "./ErrorLine";
import { SendButton } from "./SendButton";

interface Props {
  card: OpenCard;
  onAnswer: (answer: Answer) => void;
}

export function ChoiceCard({ card, onAnswer }: Props) {
  const { spec, previous } = card;
  const [error, setError] = useState(card.error);
  const [checked, setChecked] = useState<string[]>(Array.isArray(previous?.value) ? previous.value : []);
  const formRef = useRef<HTMLFormElement>(null);
  useFocusOnOpen(formRef, Boolean(card.error));

  const options = spec.options ?? [];
  const toggle = (value: string, on: boolean) =>
    setChecked((prev) => (on ? [...prev, value] : prev.filter((v) => v !== value)));

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const result = multiSelectAnswer(spec, checked);
    if (typeof result === "string") setError(result);
    else onAnswer(result);
  };

  return (
    <form ref={formRef} className="card" noValidate onSubmit={onSubmit} onChange={() => setError(null)}>
      <Prompt spec={spec} />
      <div className="bubble user pending">
        {spec.kind === InputKind.MULTI_SELECT ? (
          <>
            <div className="choices" role="group" aria-labelledby={labelId(spec)}>
              {options.map(({ value, label }) => (
                <label key={value} className="choice">
                  <input
                    type="checkbox"
                    value={value}
                    checked={checked.includes(value)}
                    onChange={(event) => toggle(value, event.target.checked)}
                  />
                  {` ${label || value}`}
                </label>
              ))}
            </div>
            <div className="composer end">
              <SendButton />
            </div>
          </>
        ) : (
          <div className="choices" role="group" aria-labelledby={labelId(spec)}>
            {singleChoices(spec).map((choice, i) => (
              <button key={`${i}:${choice.label}`} type="button" className="choice" onClick={() => onAnswer(choiceAnswer(choice))}>
                {choice.label}
              </button>
            ))}
          </div>
        )}
        <ErrorLine message={error} />
      </div>
    </form>
  );
}
