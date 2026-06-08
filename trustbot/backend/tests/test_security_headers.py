"""Defense-in-depth security response headers (audit remediation).

Every API response carries anti-sniffing / anti-clickjacking / referrer headers and a strict
CSP (the API serves JSON + file downloads, never untrusted HTML). Pinned so CI guards them.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_security_response_headers_present():
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-frame-options"] == "DENY"
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp


def test_cors_is_not_wildcarded():
    # The CORS middleware must advertise only the methods/headers we use — never "*".
    from app.main import app as fastapi_app

    cors = next(
        m for m in fastapi_app.user_middleware if m.cls.__name__ == "CORSMiddleware"
    )
    assert "*" not in cors.kwargs["allow_methods"]
    assert "*" not in cors.kwargs["allow_headers"]
    assert set(cors.kwargs["allow_methods"]) <= {"GET", "POST", "OPTIONS"}
