import pytest

from app import validators as v
from app.vision import interpret
from datetime import date

from conftest import VALID_AADHAAR


def ok(result):
    assert isinstance(result, v.Ok), result
    return result.value


def bad(result):
    assert isinstance(result, v.Invalid), result
    return result.reason


@pytest.mark.parametrize("raw,expected", [("2", 2.0), (3, 3.0), ("1.3", 1.5), ("6 months", 0.5), ("three", 3.0), ("0", 0.0)])
def test_experience_ok(raw, expected):
    assert ok(v.experience_years(raw)) == expected


@pytest.mark.parametrize("raw", ["-1", "45", "lots", True])
def test_experience_bad(raw):
    bad(v.experience_years(raw))


def test_shift():
    assert ok(v.preferred_shift("Night")) == "night"
    assert ok(v.preferred_shift("raat")) == "night"
    assert ok(v.preferred_shift("I prefer the evening shift")) == "evening"
    assert "ambiguous" in bad(v.preferred_shift("day"))
    bad(v.preferred_shift("whenever my mom says"))


def test_aadhaar():
    assert ok(v.aadhaar_number(f"{VALID_AADHAAR[:4]} {VALID_AADHAAR[4:8]}-{VALID_AADHAAR[8:]}")) == VALID_AADHAAR
    wrong_check = VALID_AADHAAR[:-1] + str((int(VALID_AADHAAR[-1]) + 1) % 10)
    assert "checksum" in bad(v.aadhaar_number(wrong_check))
    assert "0 or 1" in bad(v.aadhaar_number("1" + VALID_AADHAAR[1:]))
    bad(v.aadhaar_number("12345"))
    assert v.mask_aadhaar(VALID_AADHAAR) == f"XXXX XXXX {VALID_AADHAAR[-4:]}"


def test_ifsc():
    assert ok(v.ifsc_code(" sbin0001234 ")) == "SBIN0001234"
    bad(v.ifsc_code("SBIN1001234"))  # 5th char must be 0
    bad(v.ifsc_code("SBI0001234"))


def test_name():
    assert ok(v.full_name("  RAVI   kumar ")) == "RAVI kumar"
    assert ok(v.full_name("ravi kumar")) == "Ravi Kumar"
    assert ok(v.full_name("Priya D'Souza")) == "Priya D'Souza"
    bad(v.full_name("R2D2"))
    bad(v.full_name("x"))


def test_phone():
    assert ok(v.indian_mobile("+91 98765 43210")) == "+919876543210"
    assert ok(v.indian_mobile("09876543210")) == "+919876543210"
    bad(v.indian_mobile("5876543210"))
    bad(v.indian_mobile("9999999999"))


def test_boolean_and_vehicle():
    assert ok(v.boolean("haan")) is True
    assert ok(v.boolean(False)) is False
    bad(v.boolean("maybe"))
    assert ok(v.vehicle_type("Electric scooter")) == "electric_scooter"
    bad(v.vehicle_type("helicopter"))


def test_licence_interpretation():
    today = date(2026, 11, 7)
    base = {"isDrivingLicence": True, "legible": True, "holderName": "Ravi Kumar", "confidence": "high"}
    assert interpret({**base, "validTill": "2035-01-01"}, today)["verdict"] == "valid"
    assert interpret({**base, "validTill": "2020-01-01"}, today)["verdict"] == "expired"
    assert interpret({**base, "legible": False}, today)["verdict"] == "unreadable"
    assert interpret({**base, "isDrivingLicence": False}, today)["verdict"] == "not_licence"
    assert interpret({**base, "isDrivingLicence": False, "confidence": "low"}, today)["verdict"] == "uncertain"
