import base64
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.validators import _V_D, _V_P  # noqa: E402

# 1x1 JPEG
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
)


def aadhaar_with_check(prefix11: str) -> str:
    """Append the Verhoeff check digit, so tests use structurally valid (but fake) numbers."""
    inv = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9]
    c = 0
    for i, ch in enumerate(reversed(prefix11)):
        c = _V_D[c][_V_P[(i + 1) % 8][int(ch)]]
    return prefix11 + str(inv[c])


VALID_AADHAAR = aadhaar_with_check("23456789012")


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    """Build a fresh app bound to a temp data dir; calling it again simulates a server restart."""

    def build():
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("GEMINI_API_KEY", "")
        monkeypatch.setenv("RECORD_WEBHOOK_URL", "")
        for mod in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
            del sys.modules[mod]
        main = importlib.import_module("app.main")
        return main.app

    return build
