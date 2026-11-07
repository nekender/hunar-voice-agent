"""Pure validation + normalization for every field. No I/O here, so it is trivially unit-testable.

Each validator takes whatever arrived (a spoken value passed by the voice agent as a string, or a typed /
selected value from chat) and returns either a normalized value or a human-readable reason it was rejected.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Ok:
    value: Any


@dataclass(frozen=True)
class Invalid:
    reason: str


Result = Ok | Invalid


def _text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        raw = " ".join(str(x) for x in raw)
    return unicodedata.normalize("NFKC", str(raw)).strip()


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# --- conversational (call) fields --------------------------------------------------------------------------

_NUMBER_WORDS = {
    "zero": 0, "none": 0, "no": 0, "half": 0.5, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20,
}


def experience_years(raw: Any) -> Result:
    if isinstance(raw, bool):
        return Invalid("Experience must be a number of years.")
    if isinstance(raw, (int, float)):
        years = float(raw)
    else:
        text = _text(raw).lower()
        months = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:months?|mo)", text)
        number = re.search(r"-?\d+(?:\.\d+)?", text)
        if months:
            years = float(months.group(1)) / 12
        elif number:
            years = float(number.group())
        elif text in _NUMBER_WORDS:
            years = float(_NUMBER_WORDS[text])
        else:
            return Invalid("Experience must be a number of years, e.g. 2 or 0.5.")
    if years < 0 or years > 40:
        return Invalid("Experience must be between 0 and 40 years.")
    return Ok(round(years * 2) / 2)  # half-year precision is all a recruiter needs


SHIFTS = {
    "morning": "Morning (6am-2pm)",
    "afternoon": "Afternoon (12pm-8pm)",
    "evening": "Evening (4pm-12am)",
    "night": "Night (10pm-6am)",
    "flexible": "Flexible / any",
}
_SHIFT_SYNONYMS = {
    "day": None,  # ambiguous on purpose: the agent must ask morning vs afternoon
    "subah": "morning", "dopahar": "afternoon", "shaam": "evening", "raat": "night",
    "any": "flexible", "anytime": "flexible", "any time": "flexible", "flexible": "flexible",
    "late night": "night", "overnight": "night",
}


def preferred_shift(raw: Any) -> Result:
    text = _text(raw).lower()
    if text in SHIFTS:
        return Ok(text)
    if text in _SHIFT_SYNONYMS:
        mapped = _SHIFT_SYNONYMS[text]
        return Ok(mapped) if mapped else Invalid("'Day' is ambiguous; choose morning or afternoon.")
    for key in SHIFTS:
        if re.search(rf"\b{key}\b", text):
            return Ok(key)
    return Invalid(f"Shift must be one of: {', '.join(SHIFTS)}.")


def service_area(raw: Any) -> Result:
    text = _collapse(_text(raw))
    letters = sum(ch.isalpha() for ch in text)
    if letters < 3:
        return Invalid("Please give a locality or area name, e.g. 'Koramangala, Bengaluru'.")
    if len(text) > 120:
        return Invalid("Area is too long; a locality and city is enough.")
    return Ok(text)


_YES = {"yes", "y", "true", "1", "haan", "ha", "han", "yeah", "yep", "i do", "have"}
_NO = {"no", "n", "false", "0", "nahi", "nahin", "nope", "don't", "dont", "do not"}


def boolean(raw: Any) -> Result:
    if isinstance(raw, bool):
        return Ok(raw)
    text = _text(raw).lower()
    if text in _YES:
        return Ok(True)
    if text in _NO:
        return Ok(False)
    return Invalid("Please answer yes or no.")


# --- chat fields -------------------------------------------------------------------------------------------

_NAME_CHARS = re.compile(r"^[^\W\d_]+(?:[ .'\-][^\W\d_]+)*\.?$", re.UNICODE)


def full_name(raw: Any) -> Result:
    text = _collapse(_text(raw))
    if len(text) < 2 or len(text) > 80:
        return Invalid("Please enter your full name as on your Aadhaar (2-80 characters).")
    if not _NAME_CHARS.match(text):
        return Invalid("A name can only contain letters, spaces, dots, hyphens and apostrophes.")
    if sum(ch.isalpha() for ch in text) < 2:
        return Invalid("Please enter your full name.")
    if text.isupper() or text.islower():
        text = " ".join(part[:1].upper() + part[1:].lower() for part in text.split(" "))
    return Ok(text)


# Verhoeff tables (Aadhaar's checksum algorithm).
_V_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_V_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_valid(digits: str) -> bool:
    check = 0
    for i, ch in enumerate(reversed(digits)):
        check = _V_D[check][_V_P[i % 8][int(ch)]]
    return check == 0


def aadhaar_number(raw: Any) -> Result:
    digits = re.sub(r"[\s\-]", "", _text(raw))
    if not re.fullmatch(r"\d{12}", digits):
        return Invalid("Aadhaar must be exactly 12 digits.")
    if digits[0] in "01":
        return Invalid("Aadhaar numbers never start with 0 or 1; please re-check.")
    if not verhoeff_valid(digits):
        return Invalid("That Aadhaar number fails its checksum; a digit is probably mistyped.")
    return Ok(digits)


def mask_aadhaar(digits: str) -> str:
    return f"XXXX XXXX {digits[-4:]}"


IFSC_PATTERN = r"^[A-Z]{4}0[A-Z0-9]{6}$"


def ifsc_code(raw: Any) -> Result:
    code = re.sub(r"\s", "", _text(raw)).upper()
    if not re.fullmatch(IFSC_PATTERN, code):
        return Invalid("IFSC is 11 characters: 4 letters, a zero, then 6 letters/digits (e.g. SBIN0001234).")
    return Ok(code)


VEHICLES = {
    "petrol_bike": "Motorbike / scooter (petrol)",
    "electric_scooter": "Electric scooter",
    "bicycle": "Bicycle",
    "none": "No vehicle (need a rental)",
}
TWO_WHEELER_VEHICLES = {"petrol_bike", "electric_scooter"}


def vehicle_type(raw: Any) -> Result:
    text = _text(raw).lower()
    if text in VEHICLES:
        return Ok(text)
    for key, label in VEHICLES.items():
        if text == label.lower():
            return Ok(key)
    return Invalid(f"Choose one of: {', '.join(VEHICLES.values())}.")


def indian_mobile(raw: Any) -> Result:
    digits = re.sub(r"[\s\-()]", "", _text(raw))
    digits = re.sub(r"^(\+91|0091|91(?=\d{10}$)|0(?=\d{10}$))", "", digits)
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        return Invalid("Enter a 10-digit Indian mobile number starting with 6, 7, 8 or 9.")
    if len(set(digits)) == 1:
        return Invalid("That doesn't look like a real mobile number.")
    return Ok(f"+91{digits}")


def uploaded_file(raw: Any) -> Result:
    """Shape check only: the URL must point at our own upload store. Content checks happen in vision.py."""
    url = _text(raw)
    if not re.search(r"/sessions/[\w\-]+/files/[\w\-]+\.(?:jpg|jpeg|png|webp|heic|pdf)$", url):
        return Invalid("Please upload a photo (JPG/PNG) or PDF of your driving licence.")
    return Ok(url)
