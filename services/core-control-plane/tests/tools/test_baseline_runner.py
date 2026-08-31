"""Baseline runner + reference-agent smoke tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from tools.baseline_run import _run
from tools.reference_agent import AgentDecision, ReferenceAgent

REPO_ROOT = Path(__file__).resolve().parents[4]
SCENARIOS = REPO_ROOT / "services" / "core-control-plane" / "tests" / "scenarios" / "v2026.07"

#: The frozen scenario set is deliberately fixed, so adding a scenario is a visible decision
#: that also has to regenerate `docs/baselines/v2026.07.*`. It moved from 9 to 12 when the
#: three `sre.*` scenarios landed.
_FROZEN_SCENARIO_COUNT = 12


def test_reference_agent_is_deterministic() -> None:
    """Two invocations of the reference agent yield byte-identical outputs."""
    agent_a = ReferenceAgent()
    agent_b = ReferenceAgent()
    event = {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000001",
        "source": "example_source",
        "event_type": "change_detected",
    }
    a = agent_a.decide(event)
    b = agent_b.decide(event)
    assert a == b
    assert isinstance(a, AgentDecision)
    assert a.decision == "hil"


def test_run_produces_the_expected_summary_shape() -> None:
    _, summary = _run(SCENARIOS)
    assert summary["scenario_count"] == _FROZEN_SCENARIO_COUNT
    assert summary["reference_agent"] == ReferenceAgent.VERSION
    assert "success_metrics" in summary
    assert "guard_metrics_baseline" in summary
    assert "per_domain" in summary
    assert set(summary["per_domain"]) == {"change", "dr", "finops"}
    # Stub always routes to HIL → auto rate is 0.
    assert summary["success_metrics"]["auto_resolution_rate"] == 0.0
    assert summary["success_metrics"]["hil_rate"] == 1.0


def test_run_is_reproducible() -> None:
    """Same scenario version + same agent version → same summary."""
    _, first = _run(SCENARIOS)
    _, second = _run(SCENARIOS)
    # `generated_at` timestamps differ between runs; every other key MUST match.
    first_copy = dict(first)
    second_copy = dict(second)
    del first_copy["generated_at"]
    del second_copy["generated_at"]
    assert first_copy == second_copy


def test_measured_observations_are_marked_but_small_sample_is_not_claim_eligible(
    tmp_path: Path,
) -> None:
    scenarios = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(SCENARIOS.glob("*.json"))
    ]
    observations = {
        "reference_agent": "reference-observation@example",
        "scenario_set_version": "v2026.07",
        "outcomes": [
            {
                "scenario_id": scenario["id"],
                "predicted_tier": scenario["expected"]["tier"],
                "predicted_decision": scenario["expected"]["decision"],
                "executed": False,
                "rolled_back": False,
                "policy_violation": False,
                "latency_ms": 10.0,
                "model_calls": 1 if scenario["expected"]["tier"] == "t2" else 0,
                "input_tokens": 100 if scenario["expected"]["tier"] == "t2" else 0,
                "output_tokens": 20 if scenario["expected"]["tier"] == "t2" else 0,
                "cost_usd": 0.01 if scenario["expected"]["tier"] == "t2" else 0.0,
                "verifier_outcome": (
                    "eligible" if scenario["expected"]["tier"] == "t2" else "not_invoked"
                ),
            }
            for scenario in scenarios
        ],
    }
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(observations), encoding="utf-8")

    _, summary = _run(SCENARIOS, path)

    assert summary["evidence"]["kind"] == "measured-observations"
    assert summary["evidence"]["claim_eligible"] is False
    assert (
        summary["confidence_intervals_95"]["routed_correctly_rate"]["sample_size"]
        == _FROZEN_SCENARIO_COUNT
    )
    # Derived, not pinned: the fixture above emits exactly one model call and one cost unit
    # per t2 scenario, so hardcoding a total would break every time the frozen set grows.
    t2_count = sum(1 for scenario in scenarios if scenario["expected"]["tier"] == "t2")
    assert t2_count >= 1, "the fixture proves nothing about t2 economics without a t2 scenario"
    assert summary["tier_economics"]["t2"]["model_calls"] == t2_count
    assert summary["model_economics"]["cost_usd"] == pytest.approx(0.01 * t2_count)
    assert summary["quality_evidence"]["verifier_failure_count"] == 0
    assert summary["release_gate"]["checks"]["minimum_sample_size"] is False


def test_cli_writes_report_and_json(tmp_path: Path) -> None:
    """`python -m tools.baseline_run` runs green and produces both artifacts."""
    report = tmp_path / "report.md"
    payload = tmp_path / "summary.json"

    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [
            sys.executable,
            "-m",
            "tools.baseline_run",
            "--scenarios",
            str(SCENARIOS),
            "--json",
            str(payload),
            "--report",
            str(report),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert report.exists()
    assert payload.exists()
    assert "unmeasured" in report.read_text(encoding="utf-8")

    parsed = json.loads(payload.read_text(encoding="utf-8"))
    assert parsed["scenario_count"] == _FROZEN_SCENARIO_COUNT

    # The KO sibling MUST have been emitted alongside the EN report.
    ko_sibling = report.with_name(report.stem + "-ko" + report.suffix)
    assert ko_sibling.exists()

    report_bytes = report.read_bytes()
    ko_text = ko_sibling.read_text(encoding="utf-8")
    assert report_bytes.endswith(b"\n") and not report_bytes.endswith(b"\n\n")
    assert ko_text.endswith("\n") and not ko_text.endswith("\n\n")

    recorded_sha = next(
        line.removeprefix("translation_source_sha: ")
        for line in ko_text.splitlines()
        if line.startswith("translation_source_sha: ")
    )
    expected_sha = hashlib.sha1(  # noqa: S324 - verifies Git blob compatibility
        b"blob " + str(len(report_bytes)).encode() + b"\x00" + report_bytes,
        usedforsecurity=False,
    ).hexdigest()
    assert recorded_sha == expected_sha


def test_release_gate_blocks_incomplete_small_baseline() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [
            sys.executable,
            "-m",
            "tools.baseline_run",
            "--scenarios",
            str(SCENARIOS),
            "--require-release-eligible",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 3
    assert json.loads(result.stdout)["release_gate"]["release_eligible"] is False


def test_measured_observations_require_economics_fields(tmp_path: Path) -> None:
    scenarios = [json.loads(path.read_text()) for path in sorted(SCENARIOS.glob("*.json"))]
    path = tmp_path / "observations.json"
    path.write_text(
        json.dumps(
            {
                "reference_agent": "incomplete-observation@example",
                "scenario_set_version": "v2026.07",
                "outcomes": [
                    {
                        "scenario_id": scenario["id"],
                        "predicted_tier": "t0",
                        "predicted_decision": "hil",
                        "executed": False,
                        "rolled_back": False,
                        "policy_violation": False,
                    }
                    for scenario in scenarios
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="latency_ms"):
        _run(SCENARIOS, path)


def test_committed_baseline_artifact_matches_a_fresh_run() -> None:
    """W3.4 reproducibility CI gate.

    The shipped `docs/baselines/v2026.07.json` MUST remain reproducible from
    the pinned reference agent + frozen scenario set. If a fresh run diverges
    on anything other than the wall-clock ``generated_at`` field, the
    baseline artifact is stale and has to be regenerated (or the pinned agent
    version bumped) in the same PR that caused the drift.

    This is stricter than the CI-band variant described in
    docs/roadmap/phases/phase-0-instrumentation.md § W3.4 because the
    reference agent is deterministic; we get byte-exact reproducibility, not
    a confidence interval.
    """
    committed = json.loads(
        (REPO_ROOT / "docs" / "baselines" / "v2026.07.json").read_text(encoding="utf-8")
    )
    _, fresh = _run(SCENARIOS)

    committed_copy = dict(committed)
    fresh_copy = dict(fresh)
    del committed_copy["generated_at"]
    del fresh_copy["generated_at"]

    assert committed_copy == fresh_copy, (
        "committed docs/baselines/v2026.07.json diverges from a fresh run - "
        "regenerate with `python -m tools.baseline_run --scenarios "
        "services/core-control-plane/tests/scenarios/v2026.07 --json docs/baselines/v2026.07.json "
        "--report docs/baselines/v2026.07.md` or bump the reference-agent "
        "version pin"
    )


def _cohort_bundle(
    *,
    scenario_set_version: str = "v2026.07",
    origin: str = "governed_external",
    synthetic: bool = False,
    admitted: bool = True,
) -> dict[str, object]:
    """Build one governed cohort bundle shaped exactly like the external artifact.

    The values are test fixtures for the fail-closed path; the repository never
    retains a non-synthetic cohort of its own.
    """
    from fdai_service_contracts.baseline_cohort import baseline_treatment_cohort_receipt_digest
    from fdai_service_contracts.decision_evidence import (
        decision_critical_evidence_receipt_digest,
    )

    scope = "sha256:" + "1" * 64
    static = "sha256:" + "6" * 64
    revision = "git:0123456789abcdef0123456789abcdef01234567"
    cutoff = "2026-08-31T00:00:00+00:00"
    fresh_until = "2026-09-01T00:00:00+00:00"

    def _arm(arm: str, report: str, provenance: str) -> dict[str, object]:
        evidence: dict[str, object] = {
            "schema_version": "1.0.0",
            "authority_class": "deployment_observation",
            "source_identity": "principal:sre-cohort-runner",
            "authentication_evidence_digest": static,
            "scope_digest": scope,
            "purpose_id": "sre-claim-cohort",
            "producer_id": "cohort-runner",
            "producer_version": "1.0.0",
            "method_id": "frozen-scenario-replay",
            "method_version": "1.0.0",
            "source_revision": revision,
            "evidence_digest": report,
            "provenance_digest": provenance,
            "event_at": "2026-08-30T22:00:00+00:00",
            "evidence_cutoff": cutoff,
            "recorded_at": "2026-08-31T00:30:00+00:00",
            "fresh_until": fresh_until,
            "freshness_policy_id": "cohort-daily",
            "freshness_policy_version": "1.0.0",
            "freshness_policy_digest": static,
            "freshness_ceiling_seconds": 86_400,
            "completeness_basis_points": 10_000,
            "completeness_evidence_digest": static,
            "conflict_status": "clear",
            "conflict_evidence_digest": static,
            "conflict_evidence_digests": [],
            "synthetic": synthetic,
            "execution_authority": False,
        }
        evidence["receipt_digest"] = decision_critical_evidence_receipt_digest(**evidence)
        return {
            "arm": arm,
            "scenario_set_version": scenario_set_version,
            "scenario_set_digest": scope,
            "fdai_revision": revision,
            "report_digest": report,
            "provenance_digest": provenance,
            "sample_count": 30,
            "synthetic": synthetic,
            "metrics_complete": True,
            "provenance_complete": True,
            "metrics": [
                {
                    "metric_id": "auto_resolution_rate",
                    "absolute_value": 0.4,
                    "sample_size": 30,
                    "confidence_level_basis_points": 9_500,
                    "lower_bound": 0.25,
                    "upper_bound": 0.57,
                }
            ],
            "guards": [
                {
                    "guard_id": "policy_violation_escape_rate",
                    "observed_basis_points": 0,
                    "maximum_basis_points": 0,
                    "sample_size": 30,
                    "breached": False,
                }
            ],
            "evidence_receipt": evidence,
        }

    receipt: dict[str, object] = {
        "schema_version": "1.0.0",
        "cohort_id": "sre-v2026.07-cohort",
        "scenario_set_version": scenario_set_version,
        "scenario_set_digest": scope,
        "fdai_revision": revision,
        "artifact_origin": origin,
        "baseline": _arm("baseline", "sha256:" + "2" * 64, "sha256:" + "3" * 64),
        "treatment": _arm("treatment", "sha256:" + "4" * 64, "sha256:" + "5" * 64),
        "evidence_cutoff": cutoff,
        "execution_authority": False,
    }
    receipt["receipt_digest"] = baseline_treatment_cohort_receipt_digest(**receipt)

    evidence_requirement = {
        "allowed_authority_classes": ["deployment_observation"],
        "allowed_source_identities": ["principal:sre-cohort-runner"],
        "scope_digest": scope,
        "purpose_id": "sre-claim-cohort",
        "producer_id": "cohort-runner",
        "producer_version": "1.0.0",
        "method_id": "frozen-scenario-replay",
        "method_version": "1.0.0",
        "source_revision": revision,
        "freshness_policy_digest": static,
        "freshness_ceiling_seconds": 86_400,
    }
    admissions = []
    if admitted:
        for arm in ("baseline", "treatment"):
            arm_body = receipt[arm]
            assert isinstance(arm_body, dict)
            evidence = arm_body["evidence_receipt"]
            assert isinstance(evidence, dict)
            admissions.append(
                {
                    "receipt_digest": evidence["receipt_digest"],
                    "verification_bundle_digest": "sha256:" + "7" * 64,
                    "evidence_digest": arm_body["report_digest"],
                    "scope_digest": scope,
                    "purpose_id": "sre-claim-cohort",
                    "source_revision": revision,
                    "verified_at": "2026-08-31T00:35:00+00:00",
                    "valid_until": fresh_until,
                }
            )
    return {
        "receipt": receipt,
        "requirement": {
            "scenario_set_version": scenario_set_version,
            "scenario_set_digest": scope,
            "fdai_revision": revision,
            "minimum_sample_size": 30,
            "required_metric_ids": ["auto_resolution_rate"],
            "required_guard_ids": ["policy_violation_escape_rate"],
            "baseline_evidence": evidence_requirement,
            "treatment_evidence": evidence_requirement,
        },
        "admissions": admissions,
    }


def test_a_run_without_a_cohort_receipt_is_never_claim_eligible() -> None:
    _, summary = _run(SCENARIOS)

    assert summary["cohort_claim"]["claim_eligible"] is False
    assert summary["cohort_claim"]["rejection_reasons"] == ["receipt_missing"]
    assert summary["cohort_claim"]["artifact_origin"] == "repository"
    assert summary["cohort_claim"]["minimum_sample_size"] == 30
    assert summary["evidence"]["claim_eligible"] is False


def test_the_committed_baseline_artifact_records_the_external_residual() -> None:
    committed = json.loads(
        (REPO_ROOT / "docs" / "baselines" / "v2026.07.json").read_text(encoding="utf-8")
    )

    assert committed["evidence"]["kind"] == "synthetic-harness"
    assert committed["evidence"]["claim_eligible"] is False
    assert committed["scenario_count"] == _FROZEN_SCENARIO_COUNT
    assert committed["cohort_claim"]["claim_eligible"] is False
    assert committed["cohort_claim"]["rejection_reasons"] == ["receipt_missing"]
    assert "30 samples" in committed["cohort_claim"]["external_residual"]


def test_a_governed_admitted_cohort_receipt_makes_the_claim_eligible(tmp_path: Path) -> None:
    bundle = tmp_path / "cohort.json"
    bundle.write_text(json.dumps(_cohort_bundle()), encoding="utf-8")

    _, summary = _run(SCENARIOS, None, bundle)

    assert summary["cohort_claim"]["claim_eligible"] is True
    assert summary["cohort_claim"]["artifact_origin"] == "governed_external"
    # The frozen set is still 12 scenarios, so the release gate keeps the
    # published claim ineligible even with a governed cohort.
    assert summary["evidence"]["claim_eligible"] is False


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"synthetic": True}, "synthetic"),
        ({"admitted": False}, "evidence_not_admitted"),
        ({"origin": "repository"}, "artifact_ungoverned"),
    ],
)
def test_a_defective_cohort_receipt_fails_closed(
    tmp_path: Path,
    overrides: dict[str, object],
    expected: str,
) -> None:
    bundle = tmp_path / "cohort.json"
    bundle.write_text(json.dumps(_cohort_bundle(**overrides)), encoding="utf-8")  # type: ignore[arg-type]

    _, summary = _run(SCENARIOS, None, bundle)

    assert summary["cohort_claim"]["claim_eligible"] is False
    assert expected in summary["cohort_claim"]["rejection_reasons"]


def test_a_cohort_receipt_for_another_frozen_set_is_refused(tmp_path: Path) -> None:
    from tools.cohort_receipt import CohortClaimBundleError

    bundle = tmp_path / "cohort.json"
    bundle.write_text(
        json.dumps(_cohort_bundle(scenario_set_version="v2026.08")),
        encoding="utf-8",
    )

    with pytest.raises(CohortClaimBundleError, match="frozen scenario set"):
        _run(SCENARIOS, None, bundle)


def test_an_unreadable_cohort_receipt_is_refused(tmp_path: Path) -> None:
    from tools.cohort_receipt import CohortClaimBundleError

    bundle = tmp_path / "cohort.json"
    bundle.write_text("{", encoding="utf-8")

    with pytest.raises(CohortClaimBundleError, match="unreadable"):
        _run(SCENARIOS, None, bundle)


def test_the_cli_refuses_to_publish_an_unsupported_claim() -> None:
    result = subprocess.run(  # noqa: S603 - controlled subprocess
        [
            sys.executable,
            "-m",
            "tools.baseline_run",
            "--scenarios",
            str(SCENARIOS),
            "--require-claim-eligible",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 4
    assert json.loads(result.stdout)["cohort_claim"]["rejection_reasons"] == ["receipt_missing"]
