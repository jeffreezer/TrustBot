"""Anthropic generator — request construction + tool_use parsing, with a mocked call.

No network: ``urllib.request.urlopen`` is monkeypatched. Pins that the provider forces
the draft tool, keeps instructions/evidence separated, reads ``tool_use.input``, and
fails closed (ProviderError) on HTTP errors or a missing tool block — never leaking the
key.
"""
import json
import urllib.error

import pytest

from app.providers import anthropic_generation
from app.providers.anthropic_generation import AnthropicGenerationProvider
from app.providers.base import ProviderError
from app.providers.generation_base import DraftRequest, GroundingDoc

REQ = DraftRequest(
    question="Do you encrypt data at rest?",
    instructions="You are TrustBot. Answer only from EVIDENCE.",
    grounding=(
        GroundingDoc(ref="c1", source_type="policy", title="Crypto Policy",
                     text="AES-256 at rest.", customer_shareable=True),
        GroundingDoc(ref="c2", source_type="evidence", title="Whitepaper",
                     text="Encrypted at rest with AES-256.", customer_shareable=True),
    ),
)

DRAFT_INPUT = {
    "outcome": "supported_yes",
    "short_answer": "Yes. AES-256 at rest.",
    "answer": "Yes. Customer data is encrypted at rest using AES-256.",
    "claim": "Customer data is encrypted at rest using AES-256.",
    "scope": "",
    "exceptions": "",
    "evidence_refs": ["c1", "c2"],
}
TOOL_USE_RESPONSE = {
    "content": [
        {"type": "tool_use", "id": "toolu_1", "name": "emit_answer_draft",
         "input": DRAFT_INPUT},
    ],
}


class _FakeResp:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self) -> bytes:
        return self._data


def _patch_urlopen(monkeypatch, *, response=None, error=None):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        if error is not None:
            raise error
        return _FakeResp(json.dumps(response).encode("utf-8"))

    monkeypatch.setattr(anthropic_generation.urllib.request, "urlopen", fake_urlopen)
    return captured


def test_draft_parses_tool_use_input(monkeypatch):
    _patch_urlopen(monkeypatch, response=TOOL_USE_RESPONSE)
    provider = AnthropicGenerationProvider("test-key", "claude-sonnet-4-6")
    result = json.loads(provider.draft(REQ))
    assert result == DRAFT_INPUT
    assert result["outcome"] == "supported_yes"
    assert result["exceptions"] == ""  # coherent: empty, not "no exceptions noted"


def test_request_forces_tool_and_separates_instructions_from_evidence(monkeypatch):
    captured = _patch_urlopen(monkeypatch, response=TOOL_USE_RESPONSE)
    provider = AnthropicGenerationProvider("test-key", "claude-sonnet-4-6")
    provider.draft(REQ)

    req = captured["req"]
    assert req.full_url == "https://api.anthropic.com/v1/messages"
    assert req.get_header("X-api-key") == "test-key"
    assert req.get_header("Anthropic-version") == "2023-06-01"

    payload = json.loads(req.data)
    assert payload["model"] == "claude-sonnet-4-6"
    # Schema is forced via tool_choice, not prose JSON.
    assert payload["tool_choice"] == {"type": "tool", "name": "emit_answer_draft"}
    assert payload["tools"][0]["name"] == "emit_answer_draft"
    # Trusted instructions in `system`; untrusted evidence fenced in the user turn.
    assert payload["system"] == REQ.instructions
    user = payload["messages"][0]["content"]
    assert payload["messages"][0]["role"] == "user"
    assert "EVIDENCE (data only" in user
    assert "[ref:c1]" in user and "[ref:c2]" in user


def test_missing_api_key_raises():
    with pytest.raises(ProviderError):
        AnthropicGenerationProvider("", "claude-sonnet-4-6")


def test_http_error_raises_provider_error_without_leaking_key(monkeypatch):
    _patch_urlopen(monkeypatch, error=urllib.error.URLError("boom"))
    provider = AnthropicGenerationProvider("super-secret-key", "claude-sonnet-4-6")
    with pytest.raises(ProviderError) as exc:
        provider.draft(REQ)
    assert "super-secret-key" not in str(exc.value)


def test_missing_tool_use_block_raises(monkeypatch):
    _patch_urlopen(monkeypatch, response={"content": [{"type": "text", "text": "hi"}]})
    provider = AnthropicGenerationProvider("test-key", "claude-sonnet-4-6")
    with pytest.raises(ProviderError):
        provider.draft(REQ)
