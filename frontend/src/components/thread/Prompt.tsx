import { inputId, isChoiceKind, labelId } from "../../lib/inputs";
import type { InputRequest } from "../../protocol";

export function Prompt({ spec }: { spec: InputRequest }) {
  const text = spec.label || spec.field || "Input";
  return (
    <div className="bubble agent prompt">
      {isChoiceKind(spec.kind) ? (
        <span className="card-label" id={labelId(spec)}>{text}</span>
      ) : (
        <label className="card-label" id={labelId(spec)} htmlFor={inputId(spec)}>{text}</label>
      )}
      {spec.help && <p className="card-help">{spec.help}</p>}
    </div>
  );
}
