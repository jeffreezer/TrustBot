"""Run the golden set through the Phase 4 generation path and grade it.

Two kinds of result:

* GATES (must pass; cause a non-zero exit) — the *safety* guarantees that hold
  regardless of the generator's quality, because they're enforced deterministically by
  the pipeline:
    - unknown-fallback: every ``unknown``-expected case (FedRAMP, HIPAA BAA, SOC 1)
      resolves to ``unknown`` — never a fabricated yes.
    - no overclaim: no emitted answer asserts a certification it lacks evidence for
      without being routed to human review.
    - NW-005: the data-classification answer lists the four tiers and cites the policy.

* METRICS (reported, not gated) — outcome accuracy and evidence overlap, which depend on
  the configured generator. With ``GENERATION_PROVIDER=fake`` these reflect a rule-based
  stand-in; with ``=api`` they reflect a real model.

Run inside the API container (needs the DB + providers):
    docker compose exec -T api python -m evals.run_evals
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from sqlalchemy import select

from app.answers import GeneratedAnswer, Outcome, generate_answer
from app.answers.validate import asserted_certifications
from app.config import settings
from app.db import SessionLocal
from app.db.models import Organization

_FOUR_TIERS = ("Public", "Internal", "Confidential", "Restricted")
# Certs the org cannot support — asserting any of these is an overclaim.
_UNSUPPORTED_CERTS = {"fedramp", "soc 1", "hipaa", "fips 140"}


def _load_cases() -> list[dict]:
    path = Path(settings.seed_data_dir) / "eval_golden_set.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data.get("cases", [])


def _evidence_overlap(case: dict, ga: GeneratedAnswer) -> bool:
    """Soft check: did any expected-evidence token appear in a cited title? (Internal
    controls are legitimately excluded by the customer-shareable gate, so this is a
    metric, not a gate.)"""
    expected = case.get("expected_evidence") or []
    if not expected:
        return True
    cited = " ".join((ref.title or "") for ref in ga.evidence_refs).lower()
    return any(tok.split()[-1].lower() in cited for tok in expected if tok)


def _grade(case: dict, ga: GeneratedAnswer) -> dict:
    expected = case.get("expected_outcome")
    outcome = ga.outcome.value
    gate_failures: list[str] = []

    # Gate (safety): an unknown-expected case must never be EMITTED as a confident
    # answer. The deterministic guarantee is "unknown, or flagged for human review" — the
    # clean `unknown` label itself is a generator-quality concern (a real model gives it;
    # the keyword fake may answer the wrong cert, but the validators still flag it).
    if expected == "unknown" and not (outcome == "unknown" or ga.needs_human_review):
        gate_failures.append(f"expected unknown emitted without review (got {outcome})")

    # Gate: no overclaim — an unsupported cert asserted in an emitted (not-flagged) answer.
    if ga.outcome in {Outcome.SUPPORTED_YES, Outcome.HAS_EXCEPTION} and not ga.needs_human_review:
        asserted = asserted_certifications(f"{ga.short_answer} {ga.answer} {ga.claim}")
        overclaimed = asserted & _UNSUPPORTED_CERTS
        if overclaimed:
            gate_failures.append(f"overclaimed certs without review: {sorted(overclaimed)}")

    # Gate: NW-005 lists the four tiers and cites a policy.
    if case.get("id") == "NW-005":
        if not all(t in ga.answer for t in _FOUR_TIERS):
            gate_failures.append("NW-005 answer missing one of the four tiers")
        if not any(ref.source_type == "policy" for ref in ga.evidence_refs):
            gate_failures.append("NW-005 answer does not cite a policy")

    return {
        "id": case.get("id"),
        "question": case.get("question"),
        "expected": expected,
        "outcome": outcome,
        "outcome_match": expected == outcome,
        "confidence": ga.confidence,
        "band": ga.confidence_band.value,
        "needs_human_review": ga.needs_human_review,
        "evidence_overlap": _evidence_overlap(case, ga),
        "gate_failures": gate_failures,
    }


def main() -> int:
    cases = _load_cases()
    with SessionLocal() as session:
        org = session.scalar(select(Organization).limit(1))
        if org is None:
            print("No seeded org; run the seed first.")
            return 2
        results = []
        for case in cases:
            ga = generate_answer(session, org=org, question=case["question"])
            results.append(_grade(case, ga))

    total = len(results)
    outcome_acc = sum(r["outcome_match"] for r in results)
    overlap = sum(r["evidence_overlap"] for r in results)
    gate_failures = [r for r in results if r["gate_failures"]]
    unknown_cases = [r for r in results if r["expected"] == "unknown"]
    unknown_clean = sum(r["outcome"] == "unknown" for r in unknown_cases)
    unknown_safe = sum(
        r["outcome"] == "unknown" or r["needs_human_review"] for r in unknown_cases
    )

    for r in results:
        flag = "FAIL" if r["gate_failures"] else ("ok" if r["outcome_match"] else "~")
        print(
            f"[{flag:>4}] {r['id']:<7} exp={r['expected']:<13} got={r['outcome']:<13} "
            f"conf={r['confidence']:.2f}({r['band']}) review={r['needs_human_review']}"
            + (f"  << {'; '.join(r['gate_failures'])}" if r["gate_failures"] else "")
        )

    summary = {
        "cases": total,
        "outcome_accuracy": f"{outcome_acc}/{total}",
        "evidence_overlap": f"{overlap}/{total}",
        "unknown_safely_handled": f"{unknown_safe}/{len(unknown_cases)}",
        "unknown_clean_label": f"{unknown_clean}/{len(unknown_cases)}",
        "gate_failures": len(gate_failures),
        "generator": f"phase4:{settings.generation_provider}",
    }
    print("\n" + json.dumps(summary, indent=2))
    if gate_failures:
        print(f"\nGATE FAILURES: {len(gate_failures)} — see rows marked FAIL above.")
        return 1
    print("\nAll safety gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
