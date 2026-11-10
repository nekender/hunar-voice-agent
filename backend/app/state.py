"""Session state = a pure fold over the event log, plus the field-resolution rules.

Nothing here does I/O. `SessionState.from_events(events)` rebuilds exactly the same state after a restart as
the live process had, which is what makes "survives a restart" true by construction.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from . import validators as v
from .scenario import FIELDS, REQUIRED, Channel
from .store import ACTIVITY_EVENTS, Event


@dataclass
class Observation:
    """One value the user gave for a field, on either channel. We keep all of them, not just the latest."""

    value: Any
    raw: Any
    valid: bool
    reason: str | None
    source: str
    at: float
    seq: int


@dataclass
class Resolved:
    status: str  # valid | invalid | missing | skipped
    value: Any = None
    source: str | None = None
    at: float | None = None
    reason: str | None = None
    attempts: int = 0
    note: str | None = None


@dataclass
class Conflict:
    field: str
    call_value: Any
    chat_value: Any
    resolution: str
    reason: str


@dataclass
class LicenceCheck:
    url: str
    verdict: str  # valid | not_licence | unreadable | expired | uncertain | unchecked
    name_on_card: str | None = None
    expiry: str | None = None
    detail: str | None = None


# Verdicts that make the upload unusable (user must re-upload) vs ones a human should look at.
LICENCE_REJECT = {"not_licence", "unreadable", "expired"}
LICENCE_REVIEW = {"uncertain", "unchecked"}


@dataclass
class SessionState:
    session_id: str
    created_at: float = 0.0
    observations: dict[str, list[Observation]] = field(default_factory=dict)
    skipped: set[str] = field(default_factory=set)
    pending: dict[str, str] | None = None  # {"id", "field"} of the one open chat card
    chat_queue: list[str] = field(default_factory=list)  # fields the voice agent asked for in chat
    chat_mode: bool = False  # chat drives the remaining fields itself (call ended / user prefers chat)
    active_call: str | None = None
    calls: int = 0
    call_seconds: float = 0.0
    chat_inputs: int = 0
    review_flags: list[str] = field(default_factory=list)
    licence_checks: dict[str, LicenceCheck] = field(default_factory=dict)
    opted_out: dict[str, Any] | None = None
    cost_usd: float = 0.0
    latencies_ms: list[float] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)  # final lines from calls + chat messages
    last_revision: int = 0
    last_outcome: str | None = None
    last_activity_at: float = 0.0
    ended_at: float | None = None

    # --- fold

    @classmethod
    def from_events(cls, session_id: str, events: list[Event]) -> "SessionState":
        state = cls(session_id)
        for event in events:
            state.apply(event)
        return state

    def apply(self, e: Event) -> None:
        d = e.data
        match e.type:
            case "session_created":
                self.created_at = e.at
            case "call_started":
                self.active_call = d["callId"]
                self.calls += 1
                self.chat_mode = False
            case "call_ended":
                if self.active_call == d["callId"]:
                    self.active_call = None
                self.call_seconds += float(d.get("seconds", 0))
            case "transcript":
                self.transcript.append({"channel": "call", "role": d["role"], "text": d["text"], "at": e.at})
            case "chat_message":
                self.transcript.append({"channel": "chat", "role": d["role"], "text": d["text"], "at": e.at})
            case "field_observed":
                obs = Observation(d["value"], d["raw"], d["valid"], d.get("reason"), d["source"], e.at, e.seq)
                self.observations.setdefault(d["field"], []).append(obs)
                self.skipped.discard(d["field"])
                if d["source"] == Channel.CHAT:
                    self.chat_inputs += 1
            case "field_skipped":
                self.skipped.add(d["field"])
                self.chat_inputs += 1
            case "input_requested":
                self.pending = {"id": d["requestId"], "field": d["field"]}
                if d["field"] in self.chat_queue:
                    self.chat_queue.remove(d["field"])
            case "input_closed":
                if self.pending and self.pending["id"] == d["requestId"]:
                    self.pending = None
            case "chat_queued":
                for name in d["fields"]:
                    if d.get("front"):
                        if name in self.chat_queue:
                            self.chat_queue.remove(name)
                        self.chat_queue.insert(0, name)
                    elif name not in self.chat_queue:
                        self.chat_queue.append(name)
            case "chat_mode_entered":
                self.chat_mode = True
            case "review_flagged":
                self.review_flags.append(d["reason"])
            case "licence_checked":
                self.licence_checks[d["url"]] = LicenceCheck(
                    d["url"], d["verdict"], d.get("nameOnCard"), d.get("expiry"), d.get("detail")
                )
            case "opted_out":
                self.opted_out = {"source": d["source"], "reason": d.get("reason"), "at": e.at}
            case "resumed":
                self.opted_out = None
            case "cost":
                self.cost_usd += float(d["usd"])
            case "latency":
                self.latencies_ms.append(float(d["ms"]))
            case "record_produced":
                self.last_revision = d["revision"]
                self.last_outcome = d["outcome"]
                self.ended_at = e.at
        if e.type in ACTIVITY_EVENTS:
            self.last_activity_at = e.at

    # --- resolution

    def resolve(self, name: str) -> Resolved:
        spec = FIELDS[name]
        obs = self.observations.get(name, [])
        attempts = len(obs)
        valid = [o for o in obs if o.valid and not self._licence_rejected(name, o)]
        if not valid:
            if name in self.skipped:
                return Resolved("skipped", attempts=attempts)
            if obs:
                last = obs[-1]
                reason = last.reason or self._licence_reason(name, last)
                return Resolved("invalid", raw_display(last.raw), last.source, last.at, reason, attempts)
            return Resolved("missing")
        winner = self._pick(spec.preferred, valid)
        return Resolved("valid", winner.value, winner.source, winner.at, attempts=attempts)

    @staticmethod
    def _pick(preferred: Channel, valid: list[Observation]) -> Observation:
        """Latest value from the preferred channel if there is one, else latest overall.

        Within a channel the latest value wins (the user corrected themselves). Across channels, values for
        exact-string fields (preferred = chat) come from what was typed, because transcription garbles IDs;
        conversational fields take the latest value from either channel.
        """
        if preferred == Channel.CHAT:
            typed = [o for o in valid if o.source == Channel.CHAT]
            if typed:
                return typed[-1]
        return valid[-1]

    def _licence_rejected(self, name: str, obs: Observation) -> bool:
        check = self.licence_checks.get(obs.value) if name == "drivingLicence" else None
        return bool(check and check.verdict in LICENCE_REJECT)

    def _licence_reason(self, name: str, obs: Observation) -> str | None:
        check = self.licence_checks.get(obs.value) if name == "drivingLicence" else None
        return check.detail if check else None

    def resolved(self) -> dict[str, Resolved]:
        out = {name: self.resolve(name) for name in FIELDS}
        # Cross-field rule: the vehicle picked from the list is more specific than the yes/no on the call.
        vehicle, two_wheeler = out["vehicleType"], out["hasTwoWheeler"]
        if vehicle.status == "valid":
            implied = vehicle.value in v.TWO_WHEELER_VEHICLES
            if two_wheeler.status != "valid" or two_wheeler.value != implied:
                out["hasTwoWheeler"] = Resolved(
                    "valid", implied, "chat", vehicle.at, attempts=two_wheeler.attempts,
                    note="derived from vehicleType",
                )
        return out

    def conflicts(self) -> list[Conflict]:
        out: list[Conflict] = []
        for name, spec in FIELDS.items():
            valid = [o for o in self.observations.get(name, []) if o.valid]
            call = [o for o in valid if o.source == Channel.CALL]
            chat = [o for o in valid if o.source == Channel.CHAT]
            if call and chat and not same_value(call[-1].value, chat[-1].value):
                winner = self._pick(spec.preferred, valid)
                out.append(Conflict(
                    name, call[-1].value, chat[-1].value, f"{winner.source}Value",
                    "typed value preferred over spoken for exact identifiers"
                    if spec.preferred == Channel.CHAT else "most recent answer wins (user corrected themselves)",
                ))
        two = [o for o in self.observations.get("hasTwoWheeler", []) if o.valid]
        vehicle = self.resolve("vehicleType")
        if two and vehicle.status == "valid" and two[-1].value != (vehicle.value in v.TWO_WHEELER_VEHICLES):
            out.append(Conflict(
                "hasTwoWheeler", two[-1].value, vehicle.value, "chatValue",
                "vehicle chosen from the list is more specific than the yes/no answer on the call",
            ))
        return out

    def review_reasons(self) -> list[str]:
        """Things a human should decide. Any of these turns a complete session into `needsReview`."""
        reasons = list(self.review_flags)
        licence = self.resolve("drivingLicence")
        if licence.status == "valid":
            check = self.licence_checks.get(licence.value)
            if check is None or check.verdict in LICENCE_REVIEW:
                reasons.append(f"driving licence could not be verified automatically ({check.detail if check else 'not checked'})")
            elif check.name_on_card:
                name = self.resolve("fullName")
                if name.status == "valid" and not names_match(name.value, check.name_on_card):
                    reasons.append(f"name on licence ('{check.name_on_card}') does not match '{name.value}'")
        return reasons

    # --- progress helpers used by the chat flow and the voice prompt

    def missing_required(self) -> list[str]:
        resolved = self.resolved()
        return [n for n in REQUIRED if resolved[n].status != "valid"]

    def is_settled(self, name: str) -> bool:
        return self.resolved()[name].status in ("valid", "skipped")

    def all_settled(self) -> bool:
        resolved = self.resolved()
        return all(r.status in ("valid", "skipped") for r in resolved.values())


def raw_display(raw: Any) -> Any:
    if isinstance(raw, str) and len(raw) > 200:
        return raw[:200] + "…"
    return raw


def same_value(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return _fold(a) == _fold(b)
    return a == b


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def names_match(given: str, on_card: str) -> bool:
    """Lenient: every token of the shorter name appears in the longer one (initials allowed)."""
    a = [t for t in re.split(r"[\s.]+", _ascii(given)) if t]
    b = [t for t in re.split(r"[\s.]+", _ascii(on_card)) if t]
    if not a or not b:
        return False
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return all(any(t == u or (len(t) == 1 and u.startswith(t)) or (len(u) == 1 and t.startswith(u)) for u in long_) for t in short)


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
