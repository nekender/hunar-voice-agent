from app.record import content, decide_outcome
from app.state import SessionState, names_match
from app.store import Event

from conftest import VALID_AADHAAR


class Log:
    def __init__(self):
        self.events = []
        self.t = 1_000.0

    def add(self, type_, **data):
        self.t += 1
        self.events.append(Event(len(self.events) + 1, type_, data, self.t))
        return self

    def obs(self, field, value, source, valid=True, raw=None, reason=None):
        return self.add("field_observed", field=field, value=value if valid else None, raw=raw or value,
                        valid=valid, reason=reason, source=source)

    def state(self):
        return SessionState.from_events("s1", self.events)


def complete(log: Log) -> Log:
    return (log.add("session_created")
            .obs("experienceYears", 2.0, "call").obs("preferredShift", "night", "call")
            .obs("serviceArea", "HSR Layout, Bengaluru", "call").obs("hasTwoWheeler", True, "call")
            .obs("fullName", "Ravi Kumar", "chat").obs("aadhaarNumber", VALID_AADHAAR, "chat")
            .obs("ifscCode", "SBIN0001234", "chat").obs("vehicleType", "petrol_bike", "chat")
            .obs("drivingLicence", "https://x/sessions/s1/files/a.jpg", "chat")
            .add("licence_checked", url="https://x/sessions/s1/files/a.jpg", verdict="valid", nameOnCard="RAVI KUMAR"))


def test_completed():
    st = complete(Log()).state()
    assert st.missing_required() == []
    assert decide_outcome(st)[0] == "completed"
    body = content(st)
    assert body["fields"]["aadhaarNumber"]["value"] == f"XXXX XXXX {VALID_AADHAAR[-4:]}"
    assert body["fields"]["alternatePhone"]["status"] == "missing"
    assert body["fields"]["alternatePhone"]["required"] is False


def test_partial_lists_missing_and_invalid():
    st = Log().add("session_created").obs("experienceYears", 2.0, "call").obs(
        "ifscCode", None, "chat", valid=False, raw="XX", reason="bad").state()
    outcome, reason = decide_outcome(st)
    assert outcome == "partial"
    assert "ifscCode invalid" in reason and "fullName missing" in reason
    assert content(st)["fields"]["ifscCode"]["reason"] == "bad"


def test_opt_out_wins_and_resume_clears_it():
    log = complete(Log()).add("opted_out", source="call", reason="found another job")
    assert decide_outcome(log.state())[0] == "optedOut"
    assert decide_outcome(log.add("resumed").state())[0] == "completed"


def test_chat_beats_call_for_identifiers_and_latest_wins_for_conversation():
    log = complete(Log())
    log.obs("ifscCode", "SBIN0009999", "call")  # spoken later, but typed value wins
    log.obs("serviceArea", "Indiranagar, Bengaluru", "chat")  # typed later: latest wins
    st = log.state()
    assert st.resolve("ifscCode").value == "SBIN0001234"
    assert st.resolve("serviceArea").value == "Indiranagar, Bengaluru"
    conflicts = {c.field: c for c in st.conflicts()}
    assert conflicts["ifscCode"].resolution == "chatValue"
    assert conflicts["serviceArea"].resolution == "chatValue"


def test_vehicle_overrides_two_wheeler_answer():
    log = complete(Log()).obs("vehicleType", "bicycle", "chat")
    st = log.state()
    assert st.resolved()["hasTwoWheeler"].value is False
    assert any(c.field == "hasTwoWheeler" for c in st.conflicts())


def test_rejected_licence_is_invalid_and_name_mismatch_needs_review():
    url = "https://x/sessions/s1/files/a.jpg"
    log = complete(Log()).add("licence_checked", url=url, verdict="expired", detail="expired in 2020")
    st = log.state()
    assert st.resolve("drivingLicence").status == "invalid"
    assert decide_outcome(st)[0] == "partial"

    log2 = complete(Log()).add("licence_checked", url=url, verdict="valid", nameOnCard="Suresh Patel")
    assert decide_outcome(log2.state())[0] == "needsReview"


def test_review_flag_from_call():
    st = complete(Log()).add("review_flagged", reason="says they are 17").state()
    outcome, reason = decide_outcome(st)
    assert outcome == "needsReview" and "17" in reason


def test_names_match():
    assert names_match("Ravi Kumar", "RAVI KUMAR")
    assert names_match("Ravi Kumar", "Ravi K")
    assert names_match("Ravi Kumar", "Ravi Kumar Sharma")
    assert not names_match("Ravi Kumar", "Suresh Patel")
