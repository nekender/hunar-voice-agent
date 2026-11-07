import { Fragment } from "react";
import { fieldLabel, formatValue, readField } from "../../lib/record";

export function FieldList({ fields }: { fields: Record<string, unknown> }) {
  return (
    <dl>
      {Object.entries(fields).map(([name, field]) => {
        const { value, source, status, flagged } = readField(field);
        return (
          <Fragment key={name}>
            <dt>{fieldLabel(name)}</dt>
            <dd className={flagged ? "flagged" : undefined}>
              {formatValue(value)}
              {Boolean(source) && <span className="src">{String(source)}</span>}
              {flagged && <span className="status">{String(status)}</span>}
            </dd>
          </Fragment>
        );
      })}
    </dl>
  );
}
