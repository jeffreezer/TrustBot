"""Storage adapter interface + key hardening.

Calling code only ever sees this interface and an opaque ``storage_path`` string.
Swapping LocalStorage ↔ S3Storage (MinIO / GCS / S3) is a config change, never a
code change — the same property that keeps local → GCP → AWS portable.

Security: object keys are untrusted-adjacent (they embed filenames). Every key is
normalized and checked for path-traversal before it touches a filesystem or a
bucket, so a crafted key like ``../../etc/passwd`` cannot escape its namespace.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class StorageError(Exception):
    pass


class UnsafeKeyError(StorageError):
    """Raised when an object key would escape its namespace (path traversal)."""


def safe_object_key(key: str) -> str:
    """Normalize an object key and reject traversal.

    Rejects absolute paths and any ``..`` segment; collapses ``.`` and empty
    segments; normalizes backslashes. The result is a clean relative key that
    cannot point outside its base, on either a filesystem or an S3 bucket.
    """
    if not key or not key.strip():
        raise UnsafeKeyError("empty storage key")
    normalized = key.replace("\\", "/")
    segments: list[str] = []
    for raw in normalized.split("/"):
        seg = raw.strip()
        if seg in ("", "."):
            continue
        if seg == "..":
            raise UnsafeKeyError(f"path traversal in storage key: {key!r}")
        if "\x00" in seg:
            raise UnsafeKeyError("null byte in storage key")
        segments.append(seg)
    if not segments:
        raise UnsafeKeyError(f"storage key reduces to nothing: {key!r}")
    return "/".join(segments)


def sanitize_filename(name: str) -> str:
    """Reduce an arbitrary filename to a single safe path segment."""
    leaf = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    leaf = leaf.lstrip(".") or "file"
    return "".join(c for c in leaf if c.isalnum() or c in ("-", "_", ".", " ")).strip() or "file"


class StorageAdapter(ABC):
    """Minimal object-storage contract used across the app."""

    def ensure_bucket(self) -> None:
        """Provision the backing container if needed. No-op for filesystem;
        overridden by object stores. Provisioning goes through the adapter so it
        stays portable (MinIO / GCS / S3) rather than special-cased per vendor."""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        """Store bytes under ``key``; return the canonical storage_path URI."""

    @abstractmethod
    def get(self, key: str) -> bytes:
        """Return the stored bytes for ``key``."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """A time-limited URL for downloading the object (no long-lived links)."""
