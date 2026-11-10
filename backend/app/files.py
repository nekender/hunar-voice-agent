"""Uploads. Files are stored in the database (the app host has no persistent disk); the record carries HMAC-signed,
expiring links to them, because the URLs point at ID documents and must not be guessable or permanent."""

import hashlib
import hmac
import secrets
import time
import uuid

from .settings import Settings
from .store import Store

# Magic-byte sniffing: never trust the browser's Content-Type or file name.
SIGNATURES: list[tuple[bytes, int, str]] = [
    (b"\xff\xd8\xff", 0, "jpg"),
    (b"\x89PNG\r\n\x1a\n", 0, "png"),
    (b"WEBP", 8, "webp"),
    (b"%PDF-", 0, "pdf"),
    (b"ftypheic", 4, "heic"),
    (b"ftypheix", 4, "heic"),
    (b"ftypmif1", 4, "heic"),
]
MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "pdf": "application/pdf", "heic": "image/heic"}
LINK_TTL_S = 7 * 24 * 3600


def sniff(head: bytes) -> str | None:
    for magic, offset, ext in SIGNATURES:
        if head[offset : offset + len(magic)] == magic:
            return ext
    return None


class FileStore:
    def __init__(self, settings: Settings, store: Store):
        self.store = store
        self.max_bytes = settings.max_upload_bytes
        self.base_url = settings.public_base_url
        # Generated once and kept in the database (never in the repo), so links survive restarts and redeploys.
        self.key = store.get_or_create_blob("file-signing-key", lambda: secrets.token_bytes(32))

    def save(self, session_id: str, data: bytes) -> str:
        """Returns the file name. Raises ValueError with a user-facing message."""
        if len(data) > self.max_bytes:
            raise ValueError(f"File is too large (max {self.max_bytes // (1024 * 1024)} MB).")
        ext = sniff(data[:16])
        if not ext:
            raise ValueError("Only JPG, PNG, WEBP, HEIC images or PDF files are accepted.")
        name = f"{uuid.uuid4().hex}.{ext}"
        self.store.put_file(session_id, name, MIME[ext], data)
        return name

    def get(self, session_id: str, name: str) -> tuple[str, bytes] | None:
        return self.store.get_file(session_id, name)

    @staticmethod
    def name_from_url(session_id: str, url: str) -> str | None:
        prefix = f"/sessions/{session_id}/files/"
        return url.split(prefix, 1)[1].split("?", 1)[0] if prefix in url else None

    def get_for_url(self, session_id: str, url: str) -> tuple[str, bytes] | None:
        name = self.name_from_url(session_id, url)
        return self.get(session_id, name) if name else None

    def exists_for_url(self, session_id: str, url: str) -> bool:
        return self.get_for_url(session_id, url) is not None

    def canonical_url(self, base: str, session_id: str, name: str) -> str:
        return f"{self.base_url or base.rstrip('/')}/sessions/{session_id}/files/{name}"

    def _sig(self, session_id: str, name: str, exp: int) -> str:
        return hmac.new(self.key, f"{session_id}/{name}/{exp}".encode(), hashlib.sha256).hexdigest()[:32]

    def signed(self, url: str, session_id: str) -> str:
        name = url.rsplit("/", 1)[-1].split("?", 1)[0]
        exp = int(time.time()) + LINK_TTL_S
        return f"{url.split('?', 1)[0]}?exp={exp}&sig={self._sig(session_id, name, exp)}"

    def verify(self, session_id: str, name: str, exp: int, sig: str) -> bool:
        return exp > time.time() and hmac.compare_digest(sig, self._sig(session_id, name, exp))
