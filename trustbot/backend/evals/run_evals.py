"""Run the respond-mode golden set through the generation path and grade it (Milestone 1).

Two kinds of result:

* GATES (must pass; cause a non-zero exit) — the *safety* / reframe guarantees that hold
  regardless of the generator's quality, because the pipeline enforces them deterministically:
    - needs_input_safety: every no-controlling-evidence case (HIPAA BAA, SOC 1) resolves to
      needs_input or human review — never a fabricated affirmation. (FedRAMP is now a grounded
      negative cited to control CMP-04, so it is graded on outcome, not this gate — 07 §3.)
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
import os
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

    # Adaptive loop — multi-part (STRICT, restored once explicit decomposition landed): a
    # compound question must be decomposed and each SUPPORTABLE part answered with its own
    # evidence; any genuinely unsupported part is flagged (not dropped). A whole-question
    # needs_input collapse — when parts ARE supportable — is a failure again.
    if "multi_part" in gates:
        subs = ga.sub_answers
        if outcome == RespondOutcome.NEEDS_INPUT:
            failures.append(
                "multi-part collapsed to a whole-question needs_input (supportable parts exist)"
            )
        elif len(subs) < 2:
            failures.append("multi-part question was not decomposed into per-part answers")
        else:
            for s in subs:
                if s.outcome != RespondOutcome.NEEDS_INPUT and not s.evidence_refs:
                    failures.append(f"answered part has no citations: {s.sub_question[:60]!r}")
            # An unsupported part must be flagged for review, never silently dropped.
            if any(s.outcome == RespondOutcome.NEEDS_INPUT for s in subs) and not ga.needs_human_review:
                failures.append("an unsupported part was not flagged for human review")

    # Adaptive loop — the document-request surfaces the SPECIFIC requested artifact (by
    # title), found by reformulating the query; never falls to needs_input, never an unrelated
    # doc. A named-artifact request auto-attaches it; a generic request pre-selects it as the
    # recommended candidate in the analyst picker (05 §8.5) — either satisfies the guarantee.
    if "attaches_named_document" in gates:
        want = (case.get("expected_document") or "").lower()
        attached = " ".join((d.title or "") for d in ga.provided_documents).lower()
        recommended = " ".join(
            (c.title or "") for c in ga.candidate_documents if c.recommended
        ).lower()
        if outcome == RespondOutcome.NEEDS_INPUT:
            failures.append("document-request fell to needs_input (loop should have found it)")
        elif not want:
            pass
        elif want in attached or want in recommended:
            pass  # attached (named) or pre-selected in the picker (generic)
        else:
            failures.append(
                f"named document neither attached nor recommended (want a title containing '{want}')"
            )

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


def _parse_args(argv: list[str]):
    import argparse

    truthy = ("1", "true", "yes", "on")
    parser = argparse.ArgumentParser(description="Run + grade the respond-mode golden set.")
    parser.add_argument(
        "--offline",
        action="store_true",
        default=os.getenv("EVAL_OFFLINE", "").strip().lower() in truthy,
        help=(
            "CI mode: skip cases tagged requires_model (they need semantic retrieval / model "
            "reformulation the deterministic fake/hash stack can't reproduce)."
        ),
    )
    parser.add_argument(
        "--floor",
        type=float,
        default=float(os.getenv("EVAL_ACCURACY_FLOOR", "0.90")),
        help="Minimum outcome accuracy (0-1, excl. known gaps) below which the gate fails.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    cases = _load_cases()
    skipped = [c for c in cases if args.offline and c.get("requires_model")]
    run_cases = [c for c in cases if not (args.offline and c.get("requires_model"))]

    with SessionLocal() as session:
        org = session.scalar(select(Organization).limit(1))
        if org is None:
            print("No seeded org; run the seed first.")
            return 2
        results = [
            _grade(case, generate_answer(session, org=org, question=case["question"]))
            for case in run_cases
        ]

    total = len(results)
    graded = [r for r in results if not r["known_gap"]]
    known_gaps = total - len(graded)
    outcome_acc = sum(r["outcome_match"] for r in graded)
    overlap = sum(r["evidence_overlap"] for r in graded)
    gate_failures = [r for r in results if r["gate_failures"]]
    accuracy = (outcome_acc / len(graded)) if graded else 1.0
    accuracy_ok = accuracy >= args.floor
    passed = not gate_failures and accuracy_ok

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
        "mode": "offline" if args.offline else "full",
        "generator": f"respond:{settings.generation_provider}",
        "cases_run": total,
        "skipped_requires_model": len(skipped),
        "known_gaps": known_gaps,
        "graded": len(graded),
        "outcome_accuracy": f"{outcome_acc}/{len(graded)} (excl. known gaps)",
        "outcome_accuracy_pct": round(accuracy * 100, 1),
        "accuracy_floor_pct": round(args.floor * 100, 1),
        "accuracy_ok": accuracy_ok,
        "evidence_overlap": f"{overlap}/{len(graded)}",
        "gate_failures": len(gate_failures),
        "result": "pass" if passed else "fail",
    }
    print("\n" + json.dumps(summary, indent=2))
    # Single-line, machine-readable verdict the CI workflow can grep/parse.
    print(
        "EVAL_RESULT_JSON=" + json.dumps(
            {
                "result": summary["result"],
                "gate_failures": len(gate_failures),
                "outcome_accuracy_pct": summary["outcome_accuracy_pct"],
                "accuracy_floor_pct": summary["accuracy_floor_pct"],
                "accuracy_ok": accuracy_ok,
            }
        )
    )

    if gate_failures:
        print(f"\nGATE FAILURES: {len(gate_failures)} — see rows marked FAIL above.")
    if not accuracy_ok:
        print(
            f"ACCURACY BELOW FLOOR: {accuracy * 100:.1f}% < {args.floor * 100:.0f}% "
            f"({outcome_acc}/{len(graded)} graded cases matched)."
        )
    if passed:
        print("\nPASS: all safety gates passed and outcome accuracy is at/above the floor.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
