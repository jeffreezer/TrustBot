"""S3-compatible storage: MinIO locally, GCS or AWS S3 in the cloud.

Same adapter, different endpoint/credentials via env vars — this is the seam that
makes object storage portable across clouds.

Secure defaults:
- Objects are written **private** (no public-read ACL).
- Optional server-side encryption (S3_SSE) for clouds that support it.
- Downloads use **presigned, expiring** URLs — never long-lived public links.
"""
from __future__ import annotations

from collections.abc import Iterator
from functools import cached_property

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from ..config import settings
from .base import StorageAdapter, StorageError, safe_object_key


class S3Storage(StorageAdapter):
    def __init__(self) -> None:
        self.bucket = settings.s3_bucket
        self.sse = settings.s3_sse or None

    @cached_property
    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region or None,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self) -> None:
        """Create the bucket if absent. Best-effort: in managed clouds the bucket
        is usually pre-provisioned and the principal may lack CreateBucket."""
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return
        except ClientError:
            pass
        try:
            self._client.create_bucket(Bucket=self.bucket)
        except ClientError as exc:  # noqa: BLE001 — surface, but don't leak creds
            raise StorageError(f"bucket {self.bucket!r} missing and not creatable") from exc

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        safe_key = safe_object_key(key)
        extra: dict = {}
        if content_type:
            extra["ContentType"] = content_type
        if self.sse:
            extra["ServerSideEncryption"] = self.sse
        self._client.put_object(Bucket=self.bucket, Key=safe_key, Body=data, **extra)
        return f"s3://{self.bucket}/{safe_key}"

    def get(self, key: str) -> bytes:
        safe_key = safe_object_key(key)
        resp = self._client.get_object(Bucket=self.bucket, Key=safe_key)
        return resp["Body"].read()

    def get_object_stream(self, key: str) -> Iterator[bytes]:
        safe_key = safe_object_key(key)
        resp = self._client.get_object(Bucket=self.bucket, Key=safe_key)
        return resp["Body"].iter_chunks(chunk_size=64 * 1024)

    def exists(self, key: str) -> bool:
        safe_key = safe_object_key(key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=safe_key)
            return True
        except ClientError:
            return False

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        safe_key = safe_object_key(key)
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": safe_key},
            ExpiresIn=expires_in,
        )
