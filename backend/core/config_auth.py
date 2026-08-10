from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

# 4.8: expected/tolerance configuration changes must be password-protected.
# Default password shipped out of the box; operators can change it from the
# Configuration page once they know the current one.
_DEFAULT_PASSWORD = "admin123"


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


class ConfigAuth:
    """Persists a salted-hash password gate for the test-parameter configuration
    page. Never stores the password itself - only salt + hash, in a small JSON
    file under the writable root (same pattern as ServerConfig)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._salt: bytes = b""
        self._hash: str = ""
        self._load_or_init()

    def _load_or_init(self) -> None:
        if self._path.exists():
            data = json.loads(self._path.read_text())
            self._salt = bytes.fromhex(data["salt"])
            self._hash = data["hash"]
            return
        self.set_password(_DEFAULT_PASSWORD)

    def verify(self, password: str) -> bool:
        if not password:
            return False
        return _hash(password, self._salt) == self._hash

    def set_password(self, new_password: str) -> None:
        self._salt = os.urandom(16)
        self._hash = _hash(new_password, self._salt)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"salt": self._salt.hex(), "hash": self._hash}, indent=2))
