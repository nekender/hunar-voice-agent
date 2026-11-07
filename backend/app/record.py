"""Turn session state into the single sanitized record, and decide its outcome.

Outcome rules (also in the README):
  optedOut     the user explicitly asked to stop (voice tool or the chat's Stop button), and has not resumed.
  needsReview  all required fields are valid, but something needs a human: licence not verifiable / name on the
               licence differs / the voice agent flagged something it must not decide on (e.g. says they are
               under 18, asks about an accommodation).
  completed    all required fields valid and nothing to review.
  partial      the session went idle with required fields still missing or invalid.

The fingerprint covers outcome + field values/statuses + conflicts + review reasons, not engagement or cost,
so re-running the producer on an unchanged session never creates a new revision.
"""

import hashlib
import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

from . import validators as v
from .scenario import FIELDS
from .state import SessionState

IST = timezone(timedelta(hours=5, minutes=30))
SCHEMA_VERSION = "delivery-partner-application/v1"


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, IST).isoformat(timespec="seconds") if ts else None


def decide_outcome(state: SessionState) -> tuple[str, str]:
    if state.opted_out:
        reason = state.opted_out.get("reason") or "user asked to stop"
        return "optedOut", f"{reason} (via {state.opted_out['source']})"
    missing = state.missing_required()
    if missing:
        resolved = state.resolved()
        parts = [f"{n} {resolved[n].status}" for n in missing]
        return "partial", "user stopped engaging with " + ", ".join(parts)
    review = state.review_reasons()
    if review:
        return "needsReview", "; ".join(review)
    return "completed", "all required fields collected and valid"


def export_value(name: str, value: Any) -> Any:
    """Final shaping for the downstream service. Aadhaar is masked: storing full Aadhaar numbers is restricted
    to UIDAI-authorised entities, and a hiring pipeline only needs it for a later, consented e-KYC step."""
    if value is None:
        return None
    if name == "aadhaarNumber":
        return v.mask_aadhaar(value)
    if name == "preferredShift":
        return {"code": value, "label": v.SHIFTS[value]}
    if name == "vehicleType":
        return {"code": value, "label": v.VEHICLES[value]}
    return value


def content(state: SessionState) -> dict[str, Any]:
    outcome, reason = decide_outcome(state)
    fields: dict[str, Any] = {}
    for name, r in state.resolved().items():
        entry: dict[str, Any] = {
            "value": export_value(name, r.value) if r.status == "valid" else None,
            "source": r.source,
            "collectedAt": iso(r.at),
            "status": r.status,
            "required": FIELDS[name].required,
        }
        if r.status == "invalid":
            entry["reason"] = r.reason
        if r.attempts > 1:
            entry["attempts"] = r.attempts
        if r.note:
            entry["note"] = r.note
        if name == "drivingLicence" and r.status == "valid":
            check = state.licence_checks.get(r.value)
            if check:
                entry["verification"] = {
                    "verdict": check.verdict, "nameOnCard": check.name_on_card, "expiry": check.expiry,
                }
        fields[name] = entry
    conflicts = [
        {
            "field": c.field,
            "callValue": export_value(c.field, c.call_value) if c.field != "hasTwoWheeler" else c.call_value,
            "chatValue": export_value(c.field, c.chat_value),
            "resolution": c.resolution,
            "reason": c.reason,
        }
        for c in state.conflicts()
    ]
    return {
        "outcome": outcome,
        "outcomeReason": reason,
        "fields": fields,
        "conflicts": conflicts,
        "reviewReasons": state.review_reasons() if outcome == "needsReview" else [],
    }


def fingerprint(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def render(state: SessionState, revision: int, body: dict[str, Any], ended_at: float) -> dict[str, Any]:
    latencies = state.latencies_ms
    return {
        "schema": SCHEMA_VERSION,
        "sessionId": state.session_id,
        "revision": revision,
        **body,
        "engagement": {
            "calls": state.calls,
            "callSeconds": round(state.call_seconds),
            "chatMessages": state.chat_inputs,
        },
        "voiceLatencyMs": {
            "p50": round(statistics.median(latencies)) if latencies else None,
            "turns": len(latencies),
        },
        "costUsd": round(state.cost_usd, 4),
        "startedAt": iso(state.created_at),
        "endedAt": iso(ended_at),
        "supersedes": revision - 1 if revision > 1 else None,
    }
