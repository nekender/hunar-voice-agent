"""Upload storage. Files live on the server's volume; the record carries HMAC-signed, expiring links to them
(the URLs point at ID documents, so they must not be guessable or permanent)."""

import hashlib
import hmac
import secrets
import time
import uuid
from pathlib import Path

from .settings import Settings

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
    def __init__(self, settings: Settings):
        self.root = settings.upload_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = settings.max_upload_bytes
        self.base_url = settings.public_base_url
        key_file = settings.data_dir / "signing.key"
        if not key_file.exists():  # generated on the volume, never in the repo
            key_file.write_bytes(secrets.token_bytes(32))
        self.key = key_file.read_bytes()

    def save(self, session_id: str, data: bytes) -> str:
        """Returns the file name. Raises ValueError with a user-facing message."""
        if len(data) > self.max_bytes:
            raise ValueError(f"File is too large (max {self.max_bytes // (1024 * 1024)} MB).")
        ext = sniff(data[:16])
        if not ext:
            raise ValueError("Only JPG, PNG, WEBP, HEIC images or PDF files are accepted.")
        folder = self.root / session_id
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.{ext}"
        (folder / name).write_bytes(data)
        return name

    def path(self, session_id: str, name: str) -> Path | None:
        candidate = (self.root / session_id / name).resolve()
        if candidate.parent != (self.root / session_id).resolve() or not candidate.is_file():
            return None
        return candidate

    def path_for_url(self, session_id: str, url: str) -> Path | None:
        prefix = f"/sessions/{session_id}/files/"
        if prefix not in url:
            return None
        return self.path(session_id, url.split(prefix, 1)[1].split("?", 1)[0])

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
