import { isPlainObject } from "../../lib/record";
import type { FinalRecord } from "../../protocol";
import { FieldList } from "./FieldList";

export function RecordCard({ record }: { record: FinalRecord }) {
  const { outcome, revision, outcomeReason, fields, conflicts }: Partial<FinalRecord> = isPlainObject(record) ? record : {};
  return (
    <section className="record" aria-label="Final record">
      <h2>
        Final record
        {outcome && <span className={`badge outcome-${outcome}`}>{String(outcome)}</span>}
        {revision !== undefined && <span className="rev">rev {revision}</span>}
      </h2>
      {outcomeReason && <p className="reason">{String(outcomeReason)}</p>}
      {isPlainObject(fields) && <FieldList fields={fields} />}
      {Array.isArray(conflicts) && conflicts.length > 0 && (
        <p className="reason">{conflicts.length} conflict(s) resolved; see JSON</p>
      )}
      <details>
        <summary>View JSON</summary>
        <pre>{JSON.stringify(record, null, 2)}</pre>
      </details>
    </section>
  );
}
