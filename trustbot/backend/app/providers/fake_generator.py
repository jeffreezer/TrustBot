"""Deterministic, grounding-only generator for tests, offline CI, and the demo.

Not an LLM: it composes a structured respond-mode draft *only* from the retrieved grounding
using documented keyword cues, so it can never fabricate — if the grounding doesn't cover
the question it returns ``needs_input``. The same inputs always yield the same draft, which
is what keeps CI offline and the suite hermetic. Production should set
``GENERATION_PROVIDER=api``/``anthropic`` to point at a real model; this stand-in exercises
the whole validate → confidence → persist path without one.

Respond posture (05 §5-§7): the vendor answers for itself and puts its best honest foot
forward. A SOC 2 exception / open finding never downgrades an affirmation — it stays
``attested`` and the report self-contains the exception. The answers layer (confidence,
validators, fail-closed review) does the real safety work regardless of generator.
"""
from __future__ import annotations

import json
import re

from .generation_base import (
    AgentRound,
    AssistantTurn,
    DraftRequest,
    GenerationProvider,
    GroundingDoc,
    ToolCall,
    ToolSpec,
)

# Relative authority for choosing which grounding doc to answer from. The canonical
# authority weights used for *confidence* live in answers/confidence.py; this is only a
# local tie-breaker for primary-source selection, so it need not match exactly.
_AUTHORITY_ORDER = {
    "policy": 5,
    "evidence": 5,
    "control": 4,
    "approved_answer": 3,
    "company_profile": 2,
}
# An affirmative must rest on a basis the answer can cite (05, reuse rule): a policy,
# control, attestation, OR a prior approved answer. Marketing copy (company_profile) is not
# a basis on its own, so the fake never affirms from it — it yields needs_input instead of
# a confident "yes" the validator would just have to downgrade.
_SUPPORTING_SOURCE_TYPES = frozenset({"policy", "control", "evidence", "approved_answer"})
# Honest-negative cues (scanned over the best-matching sentence of the primary chunk).
_NEGATIVE_CUES = (
    "not yet",
    "roadmap",
    "planned",
    "do not",
    "does not",
    "not supported",
    "not by default",
    "no public",
    "private disclosure only",
    "not offered",
    "not authorized",
)
# Vendor-scope cues → qualified (an affirmative the vendor would itself caveat — a scope,
# never an auditor finding).
_QUALIFIED_CUES = (
    "enterprise tier",
    "enterprise plan",
    "premium tier",
    "business tier",
    "add-on",
    "available on",
    "only on the",
    "upon request",
    "in the eu",
    "by region",
)
# Document-request classification (05 §7): a request to PROVIDE/SHARE an artifact.
_PROVISION_VERBS = (
    "provide",
    "share",
    "send",
    "furnish",
    "attach",
    "upload",
    "supply",
    "copy of",
    "give us",
    "make available",
    "may we obtain",
    "can we see",
)
_DOC_NOUNS = (
    "report",
    "certificate",
    "certification",
    "attestation",
    "soc 2",
    "soc2",
    "pentest",
    "penetration test",
    "audit",
    "letter",
    "aoc",
    "documentation",
    "iso 27001",
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be by do does for from how in is it of on or our that the to "
    "we what when where which who why with you your is".split()
)

# Certification subjects the fake recognizes in a QUESTION, mapped to canonical display names
# (07 §3.1). When a cert question is asked, the fake emits a structured certification claim
# alongside the prose so the offline pipeline/tests exercise the claim path (SOC 2 first, so
# "SOC 1" doesn't shadow it). The pipeline resolves the claim's basis + derives the outcome.
_CERT_SUBJECTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsoc\s*2\b|\bsoc\s*ii\b|\bsoc2\b"), "SOC 2"),
    (re.compile(r"\bsoc\s*1\b|\bssae\s*18\b"), "SOC 1"),
    (re.compile(r"\biso\s*/?\s*(?:iec\s*)?27001\b"), "ISO 27001"),
    (re.compile(r"\bpci(?:\s*dss)?\b"), "PCI DSS"),
    (re.compile(r"\bfedramp\b"), "FedRAMP"),
    (re.compile(r"\bhipaa\b"), "HIPAA"),
    (re.compile(r"\bfips\s*140\b"), "FIPS 140"),
)
# Composed prose outcome -> the polarity the cert claim DECLARES.
_OUTCOME_TO_STATUS = {
    "attested": "affirmed",
    "qualified": "qualified",
    "negative": "denied",
    "needs_input": "unknown",
}


def _terms(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2}


def _clean(text: str) -> str:
    """Drop Markdown heading/bullet markup and collapse whitespace into readable prose."""
    lines = []
    for raw in text.split("\n"):
        line = raw.strip().lstrip("#").lstrip("-").strip()
        if line:
            lines.append(line)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def _first_sentence(text: str) -> str:
    cleaned = _clean(text)
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    return parts[0].strip() if parts else cleaned


def _is_document_request(question: str) -> bool:
    low = question.lower()
    return any(v in low for v in _PROVISION_VERBS) and any(n in low for n in _DOC_NOUNS)


class FakeGenerationProvider(GenerationProvider):
    name = "fake"

    def draft(self, request: DraftRequest) -> str:
        return json.dumps(self._compose(request.question, request.grounding))

    def _compose(self, question: str, grounding: tuple[GroundingDoc, ...]) -> dict:
        requires_document = _is_document_request(question)
        if not grounding:
            return self._needs_input("No supporting evidence was retrieved for the question.")

        q_terms = _terms(question)
        # Primary = most query-term overlap; ties broken by source authority, so when
        # redundant sources cover the same fact the authoritative one wins (a policy
        # beats a vague approved answer — the Phase 3 data-classification lesson).
        order = sorted(
            range(len(grounding)),
            key=lambda i: (
                len(q_terms & _terms(grounding[i].text)),
                _AUTHORITY_ORDER.get(grounding[i].source_type, 1),
                -i,
            ),
            reverse=True,
        )
        # The answer's basis must be a citeable supporting source that addresses the
        # question; if none does, yield needs_input rather than affirm from marketing copy
        # or an off-topic chunk (the validator's anti-fabrication gate is the backstop).
        candidates = [
            i for i in order if grounding[i].source_type in _SUPPORTING_SOURCE_TYPES
        ]
        if q_terms:
            candidates = [i for i in candidates if q_terms & _terms(grounding[i].text)]
        if not candidates:
            return self._needs_input(
                "No citeable supporting evidence (policy / control / attestation / prior "
                "approved answer) addresses the question."
            )
        primary = grounding[candidates[0]]

        # Read the outcome from the PRIMARY chunk only, and from the *sentence that best
        # matches the question* — so a tangential caveat elsewhere in the chunk can't flip
        # it. An approved answer's own "A: Yes/No" takes precedence. A SOC 2 exception /
        # open finding does NOT downgrade — respond posture keeps the affirmation.
        polarity = self._approved_polarity(primary)
        answer_sentence = self._best_sentence(primary.text, q_terms)
        if polarity == "no" or (
            polarity is None and any(c in answer_sentence for c in _NEGATIVE_CUES)
        ):
            outcome, prefix = "negative", "No."
            scope = ""
        elif any(c in answer_sentence for c in _QUALIFIED_CUES):
            outcome, prefix = "qualified", "Yes, within scope."
            scope = self._sentence_with_cue(grounding, _QUALIFIED_CUES)
        else:
            outcome, prefix = "attested", "Yes."
            scope = ""

        scored = [grounding[i] for i in order]
        # Synthesize over the top-k: cite the primary plus any corroborating doc that
        # shares query terms — preferring authoritative sources — not just the #1 chunk.
        refs = [primary.ref]
        for g in scored[1:]:
            if len(refs) >= 3:
                break
            if q_terms & _terms(g.text):
                refs.append(g.ref)

        claim = _first_sentence(primary.text)
        body = _clean(primary.text)
        # When the basis is a reused approved answer, cite it explicitly so the reviewer can
        # see the source of the determination (05, reuse rule).
        basis_note = ""
        if primary.source_type == "approved_answer":
            basis_note = f"Based on prior approved answer [ref:{primary.ref}]. "
        return {
            "outcome": outcome,
            "short_answer": f"{basis_note}{prefix} {claim}".strip(),
            "answer": f"{basis_note}{prefix} {body}".strip(),
            "claim": claim,
            "scope": scope,
            "evidence_refs": refs,
            # Structured certification claim(s) declared from the composed polarity (07 §3.1).
            # Only present for certification questions; basis = the cited refs (the pipeline
            # resolves them server-side). A denial declares status 'denied' — never a "yes".
            "claims": self._cert_claims(question, outcome, refs),
            "requires_document": requires_document,
        }

    # --- adaptive retrieval loop (deterministic double, 06 §6) -------------

    def supports_tools(self) -> bool:
        return True

    def decompose(
        self, *, question: str, instructions: str, max_parts: int
    ) -> list[str]:
        """Deterministic split for offline CI: break on sentence boundaries and semicolons.
        The real model handles list-style ("X, Y, and Z?") decomposition live; this double
        just exercises the per-part control flow without a network call."""
        text = question.strip()
        parts: list[str] = []
        for sentence in re.split(r"(?<=[?.!])\s+", text):
            for seg in re.split(r"\s*;\s*", sentence):
                seg = seg.strip()
                if seg:
                    parts.append(seg if seg.endswith(("?", ".", "!")) else seg + "?")
        if len(parts) <= 1:
            return [text]  # nothing to split deterministically — answer as one
        return parts[:max_parts]

    def agent_turn(
        self,
        *,
        system: str,
        question: str,
        history: tuple[AgentRound, ...],
        tools: tuple[ToolSpec, ...],
        force_final: bool,
    ) -> AssistantTurn:
        """A scripted, offline double of an agentic model: search once, then draft from what
        came back. Exercises the loop's control flow + tool plumbing deterministically; query
        reformulation is the real model's job, not the fake's."""
        gathered = self._grounding_from_history(history)
        if not force_final and not history:
            return AssistantTurn(
                tool_calls=(
                    ToolCall(id="call-1", name="search_evidence", arguments={"query": question}),
                )
            )
        return AssistantTurn(draft_json=json.dumps(self._compose(question, gathered)))

    @staticmethod
    def _grounding_from_history(history: tuple[AgentRound, ...]) -> tuple[GroundingDoc, ...]:
        """Reconstruct the citeable grounding from the loop's tool results (data the loop fed
        back). Handles both search_evidence (`results`) and get_policy/get_control (`chunks`)."""
        docs: list[GroundingDoc] = []
        seen: set[str] = set()
        for rnd in history:
            for res in rnd.results:
                try:
                    payload = json.loads(res.content)
                except (ValueError, TypeError):
                    continue
                items = payload.get("results") or payload.get("chunks") or []
                for it in items:
                    ref = it.get("ref") if isinstance(it, dict) else None
                    if not ref or ref in seen:
                        continue
                    seen.add(ref)
                    docs.append(
                        GroundingDoc(
                            ref=ref,
                            source_type=it.get("source_type") or "evidence",
                            title=it.get("title") or "",
                            text=it.get("text") or "",
                            customer_shareable=True,
                        )
                    )
        return tuple(docs)

    @staticmethod
    def _best_sentence(text: str, q_terms: set[str]) -> str:
        """The lowercased sentence in ``text`` that best matches the question terms."""
        sentences = re.split(r"(?<=[.!?])\s+", _clean(text)) or [_clean(text)]
        if not q_terms:
            return sentences[0].lower()
        return max(sentences, key=lambda s: len(q_terms & _terms(s))).lower()

    @staticmethod
    def _cert_claims(question: str, outcome: str, refs: list[str]) -> list[dict]:
        """Emit one certification claim per cert named in the QUESTION, declaring the polarity
        from the composed outcome (07 §3.1). The cited refs are the candidate basis; the
        pipeline resolves them server-side. Empty for non-certification questions — a plain
        answer carries no claims (the lightweight common case, never a ceremony)."""
        status = _OUTCOME_TO_STATUS.get(outcome, "unknown")
        low = question.lower()
        claims: list[dict] = []
        seen: set[str] = set()
        for pattern, name in _CERT_SUBJECTS:
            if pattern.search(low) and name not in seen:
                seen.add(name)
                claims.append(
                    {
                        "subject": name,
                        "claim_type": "certification",
                        "status": status,
                        "basis": list(refs),
                        "customer_shareable": True,
                    }
                )
        return claims

    @staticmethod
    def _approved_polarity(doc: GroundingDoc) -> str | None:
        """For an approved answer, read its own 'A: Yes/No' as the outcome polarity."""
        if doc.source_type != "approved_answer":
            return None
        m = re.search(r"\ba:\s*(yes|no)\b", doc.text.lower())
        return m.group(1) if m else None

    @staticmethod
    def _needs_input(reason: str) -> dict:
        return {
            "outcome": "needs_input",
            "short_answer": "",
            "answer": "",
            "claim": "",
            "scope": "",
            "evidence_refs": [],
            "requires_document": False,
            "model_note": reason,
        }

    @staticmethod
    def _sentence_with_cue(grounding: tuple[GroundingDoc, ...], cues: tuple[str, ...]) -> str:
        for g in grounding:
            for sentence in re.split(r"(?<=[.!?])\s+", _clean(g.text)):
                low = sentence.lower()
                if any(cue in low for cue in cues):
                    return sentence.strip()
        return ""
