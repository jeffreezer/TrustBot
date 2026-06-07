"""Run the respond-mode golden set through the generation path and grade it (Milestone 1).

Two kinds of result:

* GATES (must pass; cause a non-zero exit) — the *safety* / reframe guarantees that hold
  regardless of the generator's quality, because the pipeline enforces them deterministically:
    - needs_input_safety: every needs_input-expected case (FedRAMP, HIPAA BAA, SOC 1)
      resolves to needs_input or human review — never a fabricated affirmation.
    - no_overclaim: no EMITTED answer asserts a certification it lacks evidence for.
    - four_tiers_and_policy (NW-005): lists the four tiers and cites a policy.
    - affirm_despite_exception (NW-020): a SOC 2-covered control stays AFFIRMED — the
      auditor exception does not downgrade it. The reframe at the heart of respond mode.
    - renders_remediation (NW-031): a provided report renders the remediation register
      (remediation_required + linked findings), and an open finding WITH a target date is
      served rather than refused.
    - perspective_self (NW-060): a third-person-phrased question still yields a grounded
      affirmative for Northwind (perspective resolution didn't break the answer).

* METRICS (reported, not gated) — outcome accuracy and evidence overlap, which depend on
  the configured generator (``fake`` = rule-based stand-in; ``api``/``anthropic`` = a model).

Run inside the API container (needs the DB + providers):
    docker compose exec -T api python -m evals.run_evals
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from sqlalchemy import select

from app.answers import GeneratedAnswer, RespondOutcome, generate_answer
from app.answers.validate import asserted_certifications
from app.config import settings
from app.db import SessionLocal
from app.db.models import Organization

_FOUR_TIERS = ("Public", "Internal", "Confidential", "Restricted")
# Certs the org cannot support — asserting any of these is an overclaim.
_UNSUPPORTED_CERTS = {"fedramp", "soc 1", "hipaa", "fips 140"}
_AFFIRMATIVE = {RespondOutcome.ATTESTED, RespondOutcome.QUALIFIED}


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


def _check_gates(case: dict, ga: GeneratedAnswer) -> list[str]:
    """Evaluate the per-case safety/reframe gates. Empty list == all gates passed."""
    gates = set(case.get("gates") or [])
    outcome = ga.outcome
    failures: list[str] = []

    # needs_input safety: a case with no controlling evidence must never be EMITTED
    # confidently — it resolves to needs_input OR is flagged for human review. (An honest
    # negative like "No, we are not FedRAMP authorized" satisfies this via the review flag;
    # only an *unflagged confident affirmation* fails.) Applied where explicitly tagged.
    if "needs_input_safety" in gates:
        if not (outcome == RespondOutcome.NEEDS_INPUT or ga.needs_human_review):
            failures.append(
                f"no-evidence case emitted without review (got {outcome.value})"
            )

    # no overclaim: an unsupported cert asserted in an emitted (not-flagged) answer.
    if "no_overclaim" in gates or outcome in _AFFIRMATIVE:
        if outcome in _AFFIRMATIVE and not ga.needs_human_review:
            asserted = asserted_certifications(f"{ga.short_answer} {ga.answer} {ga.claim}")
            overclaimed = asserted & _UNSUPPORTED_CERTS
            if overclaimed:
                failures.append(f"overclaimed certs without review: {sorted(overclaimed)}")

    if "four_tiers_and_policy" in gates:
        if not all(t in ga.answer for t in _FOUR_TIERS):
            failures.append("answer missing one of the four classification tiers")
        if not any(ref.source_type == "policy" for ref in ga.evidence_refs):
            failures.append("answer does not cite a policy")

    # The reframe: a SOC 2-covered control stays affirmed; the exception never downgrades.
    if "affirm_despite_exception" in gates and outcome not in _AFFIRMATIVE:
        failures.append(
            f"SOC 2-covered control was downgraded (got {outcome.value}); exception should "
            "not change the outcome"
        )

    # Document provision renders remediation status from the register.
    if "renders_remediation" in gates:
        if outcome == RespondOutcome.NEEDS_INPUT:
            failures.append("document provision refused (open finding has a target date)")
        if not (ga.remediation_required and ga.finding_refs):
            failures.append("provided report did not render the remediation register")

    # Perspective resolution: a third-person question still grounds an affirmative.
    if "perspective_self" in gates and outcome == RespondOutcome.NEEDS_INPUT:
        failures.append("perspective-resolved question fell to needs_input (lost grounding)")

    # Adaptive loop — multi-part: a compound question addresses several parts (breadth of
    # distinct cited sources) and flags any unsupported part for human review.
    if "multi_part" in gates:
        distinct = {ref.source_id or ref.chunk_id for ref in ga.evidence_refs}
        if outcome == RespondOutcome.NEEDS_INPUT:
            failures.append("multi-part question fell to needs_input instead of addressing parts")
        elif len(distinct) < 2:
            failures.append("multi-part answer cites fewer than two distinct sources")
        if not ga.needs_human_review:
            failures.append("multi-part answer with an unsupported part not flagged for review")

    # Adaptive loop — document provision attaches the SPECIFIC requested artifact (by title),
    # found by reformulating the query; never falls to needs_input, never an unrelated doc.
    if "attaches_named_document" in gates:
        want = (case.get("expected_document") or "").lower()
        titles = " ".join((d.title or "") for d in ga.provided_documents).lower()
        if outcome == RespondOutcome.NEEDS_INPUT:
            failures.append("document-request fell to needs_input (loop should have found it)")
        elif not ga.provided_documents:
            failures.append("no document attached for a document-request")
        elif want and want not in titles:
            failures.append(f"attached the wrong document (want a title containing '{want}')")

    return failures


def _grade(case: dict, ga: GeneratedAnswer) -> dict:
    expected = case.get("expected_outcome")
    outcome = ga.outcome.value
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
        "known_gap": bool(case.get("known_gap")),
        "gates": list(case.get("gates") or []),
        "gate_failures": _check_gates(case, ga),
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
    graded = [r for r in results if not r["known_gap"]]
    known_gaps = total - len(graded)
    outcome_acc = sum(r["outcome_match"] for r in graded)
    overlap = sum(r["evidence_overlap"] for r in graded)
    gate_failures = [r for r in results if r["gate_failures"]]
    # No-evidence cases (FedRAMP / HIPAA / SOC 1): per 05 an honest "no" is the correct
    # outcome, so they're graded as `negative` — but they must never be EMITTED confidently.
    # Track the share that resolves to needs_input OR is flagged for human review.
    safety_cases = [r for r in results if "needs_input_safety" in r["gates"]]
    safety_ok = sum(
        r["outcome"] == "needs_input" or r["needs_human_review"] for r in safety_cases
    )

    for r in results:
        if r["gate_failures"]:
            flag = "FAIL"
        elif r["known_gap"]:
            flag = "KGAP"
        elif r["outcome_match"]:
            flag = "ok"
        else:
            flag = "~"
        print(
            f"[{flag:>4}] {r['id']:<7} exp={r['expected']:<11} got={r['outcome']:<11} "
            f"conf={r['confidence']:.2f}({r['band']}) review={r['needs_human_review']}"
            + (f"  << {'; '.join(r['gate_failures'])}" if r["gate_failures"] else "")
        )

    summary = {
        "cases": total,
        "known_gaps": known_gaps,
        "outcome_accuracy": f"{outcome_acc}/{len(graded)} (excl. known gaps)",
        "evidence_overlap": f"{overlap}/{len(graded)}",
        "no_evidence_flagged_for_review": f"{safety_ok}/{len(safety_cases)}",
        "gate_failures": len(gate_failures),
        "generator": f"respond:{settings.generation_provider}",
    }
    print("\n" + json.dumps(summary, indent=2))
    if gate_failures:
        print(f"\nGATE FAILURES: {len(gate_failures)} — see rows marked FAIL above.")
        return 1
    print("\nAll safety gates passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
