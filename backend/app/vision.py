"""Driving-licence check with a small vision model. Returns a verdict; the record decides what it means."""

import json
import logging
from datetime import date, datetime
from typing import Any

from google import genai
from google.genai import types

from .files import MIME, FileStore
from .settings import Settings

log = logging.getLogger("vision")

PROMPT = """You are checking a document uploaded to a delivery-job application in India.
Is this an Indian driving licence (card or DigiLocker/mParivahan screenshot)? Extract the holder's name and the
licence validity/expiry date (non-transport validity if several). Answer only from what is visible.
Set legible=false if it's too blurry/dark/cropped to read the name."""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "isDrivingLicence": {"type": "BOOLEAN"},
        "legible": {"type": "BOOLEAN"},
        "holderName": {"type": "STRING", "nullable": True},
        "validTill": {"type": "STRING", "nullable": True, "description": "YYYY-MM-DD"},
        "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "note": {"type": "STRING", "description": "one short sentence"},
    },
    "required": ["isDrivingLicence", "legible", "confidence"],
}


class LicenceChecker:
    def __init__(self, settings: Settings, files: FileStore):
        self.settings = settings
        self.files = files
        self.client = (genai.Client(api_key=settings.gemini_api_key, http_options=types.HttpOptions(api_version="v1beta"))
                       if settings.gemini_api_key else None)

    async def __call__(self, session_id: str, url: str) -> dict[str, Any]:
        path = self.files.path_for_url(session_id, url)
        if path is None:
            return {"verdict": "not_licence", "detail": "The uploaded file could not be found."}
        if self.client is None:
            return {"verdict": "unchecked", "detail": "vision check disabled"}
        mime = MIME.get(path.suffix.lstrip("."), "image/jpeg")
        resp = await self.client.aio.models.generate_content(
            model=self.settings.vision_model,
            contents=[types.Part.from_bytes(data=path.read_bytes(), mime_type=mime), PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=SCHEMA, temperature=0,
                thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            ),
        )
        data = json.loads(resp.text or "{}")
        usage = resp.usage_metadata
        cost = 0.0
        if usage:
            cost = ((usage.prompt_token_count or 0) * self.settings.price_vision_in
                    + (usage.candidates_token_count or 0) * self.settings.price_vision_out) / 1e6
        return {**interpret(data), "costUsd": cost}


def interpret(data: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Map the model's observations to a verdict. Deterministic, so it's unit-tested without the model."""
    today = today or date.today()
    name = (data.get("holderName") or "").strip() or None
    expiry = _parse_date(data.get("validTill"))
    base = {"nameOnCard": name, "expiry": expiry.isoformat() if expiry else None}
    if not data.get("isDrivingLicence"):
        if data.get("confidence") == "high":
            return {**base, "verdict": "not_licence", "detail": "That doesn't look like a driving licence."}
        return {**base, "verdict": "uncertain", "detail": "could not confirm it is a driving licence"}
    if not data.get("legible"):
        return {**base, "verdict": "unreadable", "detail": "The photo is too blurry or cropped to read."}
    if expiry and expiry < today:
        return {**base, "verdict": "expired", "detail": f"This licence expired on {expiry:%d %b %Y}."}
    if data.get("confidence") == "low" or not name:
        return {**base, "verdict": "uncertain", "detail": "low-confidence read of the licence"}
    return {**base, "verdict": "valid", "detail": data.get("note")}


def _parse_date(raw: Any) -> date | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(raw), fmt).date()
        except ValueError:
            continue
    return None
