"""Runtime configuration, read once from environment variables. Secrets never leave the server."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))
    live_model: str = field(default_factory=lambda: os.environ.get("LIVE_MODEL", "gemini-3.1-flash-live-preview"))
    vision_model: str = field(default_factory=lambda: os.environ.get("VISION_MODEL", "gemini-3.5-flash-lite"))
    voice_name: str = field(default_factory=lambda: os.environ.get("VOICE_NAME", "Kore"))

    # Postgres (e.g. Neon) when set; otherwise SQLite under data_dir. DB_SCHEMA isolates test runs.
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", ""))
    db_schema: str = field(default_factory=lambda: os.environ.get("DB_SCHEMA", ""))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "./data")).resolve())
    public_base_url: str = field(default_factory=lambda: os.environ.get("PUBLIC_BASE_URL", "").rstrip("/"))

    # Where the final record is POSTed. Empty means "log only"; the built-in stub is /sink/records.
    record_webhook_url: str = field(default_factory=lambda: os.environ.get("RECORD_WEBHOOK_URL", ""))

    # A session with no activity (and no open socket) for this long is closed as `partial`.
    inactivity_seconds: float = field(default_factory=lambda: _float("INACTIVITY_SECONDS", 600))
    max_call_seconds: float = field(default_factory=lambda: _float("MAX_CALL_SECONDS", 600))
    max_upload_bytes: int = field(default_factory=lambda: int(_float("MAX_UPLOAD_BYTES", 8 * 1024 * 1024)))

    # Spend caps for the public deployment.
    max_calls_per_ip_per_hour: int = field(default_factory=lambda: int(_float("MAX_CALLS_PER_IP_PER_HOUR", 12)))
    max_concurrent_calls: int = field(default_factory=lambda: int(_float("MAX_CONCURRENT_CALLS", 5)))

    # USD per 1M tokens, for cost accounting. Defaults are the published list prices (see README).
    price_live_audio_in: float = field(default_factory=lambda: _float("PRICE_LIVE_AUDIO_IN", 3.00))
    price_live_text_in: float = field(default_factory=lambda: _float("PRICE_LIVE_TEXT_IN", 0.75))
    price_live_audio_out: float = field(default_factory=lambda: _float("PRICE_LIVE_AUDIO_OUT", 12.00))
    price_live_text_out: float = field(default_factory=lambda: _float("PRICE_LIVE_TEXT_OUT", 4.50))
    price_vision_in: float = field(default_factory=lambda: _float("PRICE_VISION_IN", 0.10))
    price_vision_out: float = field(default_factory=lambda: _float("PRICE_VISION_OUT", 0.40))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"



settings = Settings()
