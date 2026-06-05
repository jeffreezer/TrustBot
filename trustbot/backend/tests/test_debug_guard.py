"""Security tests for the debug-endpoint environment gate.

Introspection endpoints must be unreachable in production by default
(fail-closed). These tests pin both the settings predicate and the FastAPI
dependency that enforces it, without needing a database or HTTP client.
"""
import pytest
from fastapi import HTTPException

from app.config import settings
from app.main import require_debug_enabled


@pytest.mark.parametrize(
    "env,enabled",
    [
        ("local", True),
        ("dev", True),
        ("development", True),
        ("test", True),
        ("LOCAL", True),  # case-insensitive
        (" local ", True),  # surrounding whitespace tolerated
        ("prod", False),
        ("production", False),
        ("staging", False),
        ("", False),  # unrecognized -> closed
        ("anything-else", False),
    ],
)
def test_debug_enabled_predicate(monkeypatch, env, enabled):
    monkeypatch.setattr(settings, "app_env", env)
    assert settings.debug_endpoints_enabled is enabled


def test_guard_passes_in_non_prod(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "local")
    # Should not raise.
    assert require_debug_enabled() is None


def test_guard_blocks_in_prod(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "prod")
    with pytest.raises(HTTPException) as exc:
        require_debug_enabled()
    # 404 (not 403): don't disclose that the route exists.
    assert exc.value.status_code == 404
