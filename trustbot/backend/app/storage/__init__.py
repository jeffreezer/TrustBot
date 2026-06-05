"""Storage factory — selects the backend from STORAGE_BACKEND, nothing else.

Callers do ``from app.storage import get_storage`` and never import a concrete
adapter, so the rest of the app stays storage-agnostic.
"""
from __future__ import annotations

from functools import lru_cache

from ..config import settings
from .base import StorageAdapter, StorageError, UnsafeKeyError, safe_object_key, sanitize_filename


@lru_cache(maxsize=1)
def get_storage() -> StorageAdapter:
    backend = settings.storage_backend.lower()
    if backend == "s3":
        from .s3 import S3Storage

        return S3Storage()
    if backend == "local":
        from .local import LocalStorage

        return LocalStorage(settings.local_storage_dir)
    raise StorageError(f"unknown STORAGE_BACKEND: {settings.storage_backend!r}")


__all__ = [
    "get_storage",
    "StorageAdapter",
    "StorageError",
    "UnsafeKeyError",
    "safe_object_key",
    "sanitize_filename",
]
