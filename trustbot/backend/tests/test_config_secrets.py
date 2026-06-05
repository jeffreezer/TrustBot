"""Security tests for fail-closed credential handling.

The code must not carry a hard-coded credential, and outside local/dev/test it
must refuse to start when required secrets are absent (rather than silently
falling back to a default).
"""
import pytest
from pydantic import ValidationError

from app.config import Settings


def test_no_embedded_credential_default():
    # The class default must not embed a user:pass connection string.
    assert Settings.model_fields["database_url"].default == ""


def test_local_fills_credential_free_db_fallback():
    s = Settings(app_env="local", database_url="")
    assert s.database_url  # usable default in non-prod
    assert "trustbot:trustbot@" not in s.database_url  # but no embedded credential
    assert "@" not in s.database_url.split("://", 1)[1].split("/", 1)[0]


def test_prod_missing_database_url_refuses_start():
    with pytest.raises(ValidationError):
        Settings(app_env="prod", database_url="")


def test_unknown_env_is_treated_as_production():
    # Fail-closed: an unrecognized APP_ENV must not get the local fallback.
    with pytest.raises(ValidationError):
        Settings(app_env="staging", database_url="")


def test_prod_with_database_url_and_local_storage_ok():
    s = Settings(
        app_env="prod",
        database_url="postgresql+psycopg://db.internal:5432/trustbot",
        storage_backend="local",
    )
    assert s.is_non_production is False
    assert s.debug_endpoints_enabled is False


def test_prod_s3_requires_storage_credentials():
    with pytest.raises(ValidationError):
        Settings(
            app_env="prod",
            database_url="postgresql+psycopg://db.internal:5432/trustbot",
            storage_backend="s3",
            s3_access_key_id="",
            s3_secret_access_key="",
        )


def test_prod_s3_with_credentials_ok():
    s = Settings(
        app_env="prod",
        database_url="postgresql+psycopg://db.internal:5432/trustbot",
        storage_backend="s3",
        s3_access_key_id="AKIAEXAMPLE",
        s3_secret_access_key="example-secret",
    )
    assert s.storage_backend == "s3"
