import { useEffect, useRef, useState, type FormEvent } from "react";
import { useFocusOnOpen } from "../../hooks/useFocusOnOpen";
import { fileAnswer, textAnswer } from "../../lib/answers";
import { prefillFileInput } from "../../lib/files";
import { INPUT_TYPES, inputId } from "../../lib/inputs";
import { InputKind } from "../../protocol";
import type { Answer, OpenCard } from "../../state/conversation";
import { ClipIcon } from "../icons";
import { ErrorLine } from "./ErrorLine";
import { SendButton } from "./SendButton";

interface Props {
  card: OpenCard;
  onAnswer: (answer: Answer) => void;
}

export function Composer({ card, onAnswer }: Props) {
  const { spec, previous } = card;
  const [error, setError] = useState(card.error);
  const [text, setText] = useState(previous?.value != null ? String(previous.value) : "");
  const [files, setFiles] = useState<File[]>(previous?.files ?? []);
  const formRef = useRef<HTMLFormElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const isFile = spec.kind === InputKind.FILE;

  useEffect(() => {
    if (isFile && inputRef.current) prefillFileInput(inputRef.current, files);
  }, []);
  useFocusOnOpen(formRef);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const result = isFile ? fileAnswer(spec, files) : textAnswer(spec, text, inputRef.current);
    if (typeof result === "string") setError(result);
    else onAnswer(result);
  };

  const names = files.map((file) => file.name).join(", ");
  return (
    <form ref={formRef} className="card composer-bar" noValidate onSubmit={onSubmit} onChange={() => setError(null)}>
      <ErrorLine message={error} />
      <div className="composer">
        {isFile ? (
          <label className="pill attach">
            <input
              ref={inputRef}
              type="file"
              id={inputId(spec)}
              multiple={Boolean(spec.multiple)}
              accept={spec.accept}
              onChange={(event) => setFiles([...(event.target.files ?? [])])}
            />
            <ClipIcon />
            <span className="names">{names || (spec.multiple ? "Attach files" : "Attach a file")}</span>
          </label>
        ) : (
          <input
            ref={inputRef}
            type={INPUT_TYPES[spec.kind] ?? "text"}
            id={inputId(spec)}
            className="pill"
            placeholder={spec.placeholder || spec.label || "Type here"}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        )}
        <SendButton />
      </div>
    </form>
  );
}
