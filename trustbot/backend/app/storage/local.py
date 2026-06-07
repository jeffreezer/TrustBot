"""Filesystem-backed storage (default for local dev / simple self-hosts).

Every resolved path is checked to stay within the base directory, so a malicious
key cannot write or read outside the storage root.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .base import StorageAdapter, StorageError, safe_object_key

_STREAM_CHUNK = 64 * 1024


class LocalStorage(StorageAdapter):
    def __init__(self, base_dir: str) -> None:
        self.base = Path(base_dir).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        safe_key = safe_object_key(key)
        target = (self.base / safe_key).resolve()
        # Defense in depth: even after sanitizing the key, confirm containment.
        if not target.is_relative_to(self.base):
            raise StorageError(f"resolved path escapes storage root: {key!r}")
        return target

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return f"file://{safe_object_key(key)}"

    def get(self, key: str) -> bytes:
        return self._resolve(key).read_bytes()

    def get_object_stream(self, key: str) -> Iterator[bytes]:
        target = self._resolve(key)

        def _iter() -> Iterator[bytes]:
            with target.open("rb") as fh:
                while True:
                    chunk = fh.read(_STREAM_CHUNK)
                    if not chunk:
                        break
                    yield chunk

        return _iter()

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        # No object server in local mode; downloads are served via the API later.
        # Returning the canonical URI keeps the interface uniform.
        return f"file://{safe_object_key(key)}"
