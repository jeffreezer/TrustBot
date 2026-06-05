"""Google Cloud Storage backend (STORAGE_BACKEND=gcs).

Authenticates via Application Default Credentials — on Cloud Run that's the runtime
service account, so there are no static keys to manage, rotate, or leak. Objects are
written private; downloads go through v4 **signed, expiring** URLs (never public links).

Two cloud-specific notes:
- ``ensure_bucket`` is a no-op: the bucket is provisioned by deploy.sh and the runtime SA
  holds object-level access only (Storage Object Admin on the one bucket), not
  bucket get/create — so we never make a bucket-level call here.
- Keyless URL signing on Cloud Run uses the IAM SignBlob API, which needs
  ``roles/iam.serviceAccountTokenCreator`` on the runtime SA. The demo never issues
  download links, so that role is intentionally not granted; ``presigned_url`` is correct
  for when downloads are wired up.
"""
from __future__ import annotations

from datetime import timedelta
from functools import cached_property

from ..config import settings
from .base import StorageAdapter, safe_object_key


class GCSStorage(StorageAdapter):
    def __init__(self) -> None:
        self.bucket_name = settings.gcs_bucket

    @cached_property
    def _client(self):
        from google.cloud import storage  # lazy: imported only when gcs is selected

        return storage.Client(project=settings.gcs_project or None)

    @cached_property
    def _bucket(self):
        return self._client.bucket(self.bucket_name)

    def ensure_bucket(self) -> None:
        # Provisioned by deploy.sh; the runtime SA has object access only, so we make no
        # bucket-level call here (a get/create would 403 under least privilege).
        return

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        safe_key = safe_object_key(key)
        blob = self._bucket.blob(safe_key)
        blob.upload_from_string(data, content_type=content_type or "application/octet-stream")
        return f"gs://{self.bucket_name}/{safe_key}"

    def get(self, key: str) -> bytes:
        return self._bucket.blob(safe_object_key(key)).download_as_bytes()

    def exists(self, key: str) -> bool:
        return self._bucket.blob(safe_object_key(key)).exists()

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        import google.auth
        from google.auth.transport.requests import Request

        blob = self._bucket.blob(safe_object_key(key))
        creds, _ = google.auth.default()
        creds.refresh(Request())  # access token + SA email for keyless IAM signing
        return blob.generate_signed_url(
            version="v4",
            method="GET",
            expiration=timedelta(seconds=expires_in),
            service_account_email=getattr(creds, "service_account_email", None),
            access_token=creds.token,
        )
