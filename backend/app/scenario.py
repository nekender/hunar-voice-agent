"""The scenario: a delivery-partner job application.

This is the single source of truth for which fields exist, which channel each is best collected on, how it is
validated, and how it is rendered as a chat input card. The voice prompt, chat flow and record builder all
read from here, so adding a field is a one-place change.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from . import validators as v


class Channel(StrEnum):
    CALL = "call"
    CHAT = "chat"


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    preferred: Channel
    required: bool
    validate: Callable[[Any], v.Result]
    kind: str  # starter InputKind used when asked in chat
    voice_hint: str  # how the voice agent should ask / interpret it
    help: str | None = None
    placeholder: str | None = None
    pattern: str | None = None
    options: dict[str, str] | None = None
    accept: str | None = None

    def input_request(self, request_id: str) -> dict[str, Any]:
        msg: dict[str, Any] = {
            "type": "inputRequest",
            "id": request_id,
            "field": self.name,
            "kind": self.kind,
            "label": self.label,
            "required": self.required,
        }
        for key in ("help", "placeholder", "pattern", "accept"):
            if getattr(self, key):
                msg[key] = getattr(self, key)
        if self.options:
            msg["options"] = [{"value": k, "label": label} for k, label in self.options.items()]
        return msg


FIELDS: dict[str, Field] = {
    f.name: f
    for f in [
        # --- easy to say: collected conversationally on the call
        Field(
            "experienceYears", "Delivery or driving experience (years)", Channel.CALL, True, v.experience_years,
            kind="number", placeholder="e.g. 2",
            voice_hint="Years of delivery/driving/riding experience. 0 is fine. Convert months to years (6 months = 0.5).",
        ),
        Field(
            "preferredShift", "Preferred shift", Channel.CALL, True, v.preferred_shift,
            kind="select", options=v.SHIFTS,
            voice_hint="One of: morning, afternoon, evening, night, flexible. If they say 'day', ask morning or afternoon.",
        ),
        Field(
            "serviceArea", "Area you can cover", Channel.CALL, True, v.service_area,
            kind="text", placeholder="Locality, city",
            voice_hint="The locality and city they can deliver in, e.g. 'HSR Layout, Bengaluru'.",
        ),
        Field(
            "hasTwoWheeler", "Do you have your own two-wheeler?", Channel.CALL, True, v.boolean,
            kind="confirm",
            voice_hint="Whether they own a motorbike or scooter. Pass 'yes' or 'no'.",
        ),
        # --- awkward by voice: requested as chat cards
        Field(
            "fullName", "Full name (as on Aadhaar)", Channel.CHAT, True, v.full_name,
            kind="text", placeholder="As printed on your Aadhaar",
            voice_hint="Spelling matters, so ask for it in chat. Only save it from the call if they insist.",
        ),
        Field(
            "aadhaarNumber", "Aadhaar number", Channel.CHAT, True, v.aadhaar_number,
            kind="text", placeholder="12 digits", pattern=r"^[\s\-]*(\d[\s\-]*){12}$",
            help="12 digits; spaces are fine.",
            voice_hint="Never ask for it to be read aloud; always request it in chat.",
        ),
        Field(
            "ifscCode", "Bank IFSC code (for salary)", Channel.CHAT, True, v.ifsc_code,
            kind="text", placeholder="e.g. SBIN0001234", pattern=r"^\s*[A-Za-z]{4}0[A-Za-z0-9]{6}\s*$",
            help="Printed on your passbook or cheque: 4 letters, 0, then 6 characters.",
            voice_hint="Request in chat; letters and digits are easy to mishear.",
        ),
        Field(
            "vehicleType", "Which vehicle will you use?", Channel.CHAT, True, v.vehicle_type,
            kind="select", options=v.VEHICLES,
            voice_hint="Request the exact vehicle in chat as a list.",
        ),
        Field(
            "drivingLicence", "Photo of your driving licence", Channel.CHAT, True, v.uploaded_file,
            kind="file", accept="image/*,.pdf",
            help="A clear photo of the front side.",
            voice_hint="Request the photo in chat.",
        ),
        # --- optional
        Field(
            "alternatePhone", "Alternate mobile number (optional)", Channel.CHAT, False, v.indian_mobile,
            kind="phone", placeholder="10-digit mobile",
            voice_hint="Optional. Offer it in chat; skipping is fine.",
        ),
    ]
}

REQUIRED = [name for name, f in FIELDS.items() if f.required]
CHAT_FIELDS = [name for name, f in FIELDS.items() if f.preferred == Channel.CHAT]
CALL_FIELDS = [name for name, f in FIELDS.items() if f.preferred == Channel.CALL]
# Order used when the chat drives the rest of the session on its own (after the call, or chat-only).
CHAT_ORDER = CALL_FIELDS + CHAT_FIELDS
