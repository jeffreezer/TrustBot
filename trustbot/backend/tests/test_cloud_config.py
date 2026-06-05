"""Cloud config: Cloud SQL URL composition + storage-backend validation (offline)."""
import pytest
from pydantic import ValidationError

from app import storage as storage_pkg
from app.config import Settings


def _settings(**kw):
    base = dict(app_env="production", database_url="", storage_backend="gcs", gcs_bucket="b")
    base.update(kw)
    return Settings(**base)


def test_composes_cloud_sql_url_from_parts():
    s = _settings(
        cloud_sql_instance="proj:us-central1:inst",
        db_user="trustbot",
        db_password="p@ss/word",
        db_name="trustbot",
    )
    assert s.database_url.startswith("postgresql+psycopg://trustbot:")
    assert "@/trustbot?host=/cloudsql/proj:us-central1:inst" in s.database_url
    # The password is percent-encoded so reserved chars can't corrupt the DSN.
    assert "p%40ss%2Fword" in s.database_url


def test_production_gcs_requires_bucket():
    with pytest.raises(ValidationError):
        _settings(
            gcs_bucket="",
            cloud_sql_instance="p:r:i",
            db_user="u",
            db_password="x",
            db_name="d",
        )


def test_production_requires_database_when_no_parts():
    with pytest.raises(ValidationError):
        _settings(cloud_sql_instance="")  # no parts, no URL → fail closed in production


def test_s3_credential_check_does_not_apply_to_gcs():
    # A gcs backend in production must NOT demand S3 credentials.
    s = _settings(
        cloud_sql_instance="p:r:i", db_user="u", db_password="x", db_name="d"
    )
    assert s.storage_backend == "gcs"


def test_factory_selects_gcs_without_touching_gcp():
    # GCSStorage construction reads only settings (the google client is lazy), so this
    # resolves the backend without any cloud call or the package installed.
    storage_pkg.get_storage.cache_clear()
    storage_pkg.settings.storage_backend = "gcs"
    storage_pkg.settings.gcs_bucket = "demo-bucket"
    try:
        adapter = storage_pkg.get_storage()
        assert adapter.__class__.__name__ == "GCSStorage"
    finally:
        storage_pkg.settings.storage_backend = "local"
        storage_pkg.get_storage.cache_clear()
