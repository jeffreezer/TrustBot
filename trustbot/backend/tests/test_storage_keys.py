"""Security tests for storage-key hardening and local-path containment.

Path traversal in object keys is the kind of bug that turns a file upload into an
arbitrary file write. These tests pin the defenses.
"""
import pytest

from app.storage.base import UnsafeKeyError, safe_object_key, sanitize_filename
from app.storage.local import LocalStorage


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a/b/c.txt", "a/b/c.txt"),
        ("/leading/slash.txt", "leading/slash.txt"),
        ("a//b/./c.txt", "a/b/c.txt"),
        ("back\\slash.txt", "back/slash.txt"),
        ("  spaced/key.txt  ", "spaced/key.txt"),
    ],
)
def test_safe_object_key_normalizes(raw, expected):
    assert safe_object_key(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "../etc/passwd",
        "a/../../b",
        "..",
        "",
        "   ",
        "ok/../../escape",
    ],
)
def test_safe_object_key_rejects_traversal(raw):
    with pytest.raises(UnsafeKeyError):
        safe_object_key(raw)


def test_sanitize_filename_strips_paths():
    assert sanitize_filename("../../evil.md") == "evil.md"
    assert sanitize_filename("/abs/path/report.pdf") == "report.pdf"
    assert sanitize_filename("..hidden") == "hidden"
    assert sanitize_filename("") == "file"


def test_local_storage_round_trip(tmp_path):
    store = LocalStorage(str(tmp_path))
    uri = store.put("org/123/evidence/a.txt", b"hello", "text/plain")
    assert uri == "file://org/123/evidence/a.txt"
    assert store.exists("org/123/evidence/a.txt")
    assert store.get("org/123/evidence/a.txt") == b"hello"


def test_local_storage_blocks_escape(tmp_path):
    store = LocalStorage(str(tmp_path))
    with pytest.raises(UnsafeKeyError):
        store.put("../escape.txt", b"x")
