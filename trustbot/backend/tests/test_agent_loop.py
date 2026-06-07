"""Adaptive retrieval loop (Phase 6) — offline + deterministic.

The loop needs a tool-calling model, but CI stays offline: the deterministic fake double
(``FakeGenerationProvider.agent_turn``) issues one ``search_evidence`` call then drafts, and
``agent_tools.retrieve`` is monkeypatched to canned chunks. Pins routing, the gather loop
(search → draft, with the citeable pool + tool audit), the no-evidence → needs_input path,
and the generate_answer integration (path + audited tool calls), all without a network.
"""
import uuid
from types import SimpleNamespace

import app.answers.agent_tools as tools
import app.answers.generate as gen
from app.answers import RespondOutcome, generate_answer
from app.answers.generate import _gather_via_loop, _route_to_loop
from app.providers.fake_generator import FakeGenerationProvider
from app.retrieval import RetrievedChunk

ORG = SimpleNamespace(id=uuid.uuid4(), name="Northwind AI")


def _chunk(text, *, source_type="policy", title="HR Security Policy", source_id=None):
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_type=source_type,
        source_id=source_id or uuid.uuid4(),
        chunk_text=text,
        meta={"title": title, "customer_shareable": True, "confidentiality": "confidential"},
        fusion_score=0.03,
        rerank_score=2.0,
    )


# --- routing ----------------------------------------------------------------

def test_route_simple_question_uses_fixed_path():
    assert _route_to_loop("Do you encrypt data at rest?") is False
    assert _route_to_loop("Do you hold ISO 27001 certification?") is False


def test_route_compound_question_uses_loop():
    # Multiple sub-questions / conditional follow-up / enumeration all route to the loop.
    assert _route_to_loop("Do you encrypt at rest? Do you rotate keys?") is True
    assert _route_to_loop(
        "Are background checks performed on all employees and contractors? "
        "If yes, please attach your relevant organization's policy."
    ) is True
    assert _route_to_loop("List your controls for: 1. access 2. logging 3. backups") is True


# --- the gather loop --------------------------------------------------------

def test_loop_searches_then_drafts_and_audits(monkeypatch):
    hr = _chunk(
        "Background checks: Northwind performs pre-employment screening on all personnel "
        "where permitted by law prior to start."
    )
    monkeypatch.setattr(tools, "retrieve", lambda *a, **k: [hr])

    g = _gather_via_loop(
        None, ORG, "Are background checks performed on employees and contractors?",
        FakeGenerationProvider(), top_k=5,
    )
    assert g.path == "loop"
    assert g.draft is not None and g.draft.outcome == RespondOutcome.ATTESTED
    # The searched chunk joined the citeable pool, and the search was audited (metadata only).
    assert str(hr.chunk_id) in g.grounding_refs
    assert g.tool_audit and g.tool_audit[0]["tool"] == "search_evidence"
    assert "query" in g.tool_audit[0] and "results" not in g.tool_audit[0]


def test_loop_no_evidence_routes_to_needs_input(monkeypatch):
    monkeypatch.setattr(tools, "retrieve", lambda *a, **k: [])
    g = _gather_via_loop(
        None, ORG, "Are you FedRAMP authorized and do you have an ATO?",
        FakeGenerationProvider(), top_k=5,
    )
    assert g.path == "loop"
    assert g.draft is None  # nothing to cite → downstream emits needs_input
    assert g.reason


def test_loop_respects_tool_call_budget(monkeypatch):
    calls = {"n": 0}

    def _counting_retrieve(*a, **k):
        calls["n"] += 1
        return [_chunk("personnel security screening is performed")]

    monkeypatch.setattr(tools, "retrieve", _counting_retrieve)
    monkeypatch.setattr(gen.settings, "agent_max_tool_calls", 2, raising=False)
    monkeypatch.setattr(gen.settings, "agent_max_iterations", 4, raising=False)
    _gather_via_loop(None, ORG, "a; b; c?", FakeGenerationProvider(), top_k=5)
    assert calls["n"] <= 2  # never exceeds the budget


# --- generate_answer integration -------------------------------------------

def _patch_pipeline(monkeypatch, chunks):
    monkeypatch.setattr(tools, "retrieve", lambda *a, **k: list(chunks))
    monkeypatch.setattr(gen, "_resolve_documents_and_findings", lambda *a, **k: gen._DocResolution())
    monkeypatch.setattr(gen, "_resolve_reused_approvals", lambda *a, **k: [])
    monkeypatch.setattr(gen, "_available_certs", lambda *a, **k: set())
    monkeypatch.setattr(gen, "_freshness", lambda *a, **k: "current")


def test_generate_answer_uses_loop_for_compound_and_records_trail(monkeypatch):
    hr = _chunk(
        "Background checks: Northwind performs pre-employment screening on all personnel "
        "and contractors where permitted by law.",
        source_type="policy",
    )
    _patch_pipeline(monkeypatch, [hr])
    ga = generate_answer(
        None,
        org=ORG,
        question="Are background checks performed on employees and contractors? If yes, summarize.",
        generator=FakeGenerationProvider(),
    )
    assert ga.outcome == RespondOutcome.ATTESTED
    assert ga.retrieval_path == "loop"
    assert ga.tool_calls and ga.tool_calls[0]["tool"] == "search_evidence"


def test_generate_answer_simple_question_uses_fixed_path(monkeypatch):
    # Fixed path retrieves via gen.retrieve (not the loop's tools.retrieve).
    pol = _chunk(
        "Encryption at rest uses AES-256 across all data stores.",
        source_type="policy",
        title="Crypto Policy",
    )
    monkeypatch.setattr(gen, "retrieve", lambda *a, **k: [pol])
    monkeypatch.setattr(gen, "_resolve_documents_and_findings", lambda *a, **k: gen._DocResolution())
    monkeypatch.setattr(gen, "_resolve_reused_approvals", lambda *a, **k: [])
    monkeypatch.setattr(gen, "_available_certs", lambda *a, **k: set())
    monkeypatch.setattr(gen, "_freshness", lambda *a, **k: "current")
    # If the loop were used, tools.retrieve would be called; make it explode to prove it isn't.
    monkeypatch.setattr(tools, "retrieve", lambda *a, **k: (_ for _ in ()).throw(AssertionError("loop used")))

    ga = generate_answer(
        None, org=ORG, question="Do you encrypt data at rest?", generator=FakeGenerationProvider()
    )
    assert ga.retrieval_path == "fixed"
    assert ga.tool_calls == []
