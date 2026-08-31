"""Baseline runner + reference-agent smoke tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fdai.core.measurement.cohort_claim_policy import (
    COHORT_CLAIM_POLICY_PATH,
    load_cohort_claim_policy,
)
from fdai.shared.providers.decision_evidence_verifier import DecisionEvidenceAdmission
from fdai_service_contracts.baseline_cohort import (
    BaselineTreatmentCohortReceipt,
    baseline_treatment_cohort_receipt_digest,
    cohort_arm_fact_digest,
    cohort_arm_fact_digest_values,
)
from fdai_service_contracts.decision_evidence import decision_critical_evidence_receipt_digest
from tools.baseline_run import _run
from tools.cohort_receipt import UNTRUSTED_BUNDLE_KEYS, CohortClaimBundleError
from tools.reference_agent import AgentDecision, ReferenceAgent

REPO_ROOT = Path(__file__).resolve().parents[4]
SCENARIOS = REPO_ROOT / "services" / "core-control-plane" / "tests" / "scenarios" / "v2026.07"
COHORT_REVISION = "git:0123456789abcdef0123456789abcdef01234567"
_OTHER_REVISION = "git:fedcba9876543210fedcba9876543210fedcba98"

#: One plausible absolute value per required success metric. The numbers are
#: fixtures for the fail-closed path; the repository retains no real cohort.
_COHORT_METRIC_VALUES: dict[str, float] = {
    "auto_resolution_rate": 0.4,
    "change_lead_time_seconds": 5_400.0,
    "cost_per_unit_usd": 0.42,
    "human_touchpoints_per_100_events": 60.0,
    "mttr_seconds": 1_800.0,
}

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
    revision: str = COHORT_REVISION,
) -> dict[str, object]:
    """Build one governed cohort artifact shaped exactly like the external one.

    The artifact carries the retained receipt and nothing else: no requirement,
    no admission, no eligibility verdict. Every arm's evidence receipt is bound
    to the canonical digest of that arm's evaluated facts, which is what a
    governed producer has to do for a trusted admission to line up at all.
    """
    policy = load_cohort_claim_policy(REPO_ROOT / COHORT_CLAIM_POLICY_PATH)
    scope = policy.scenario_set_digest
    static = "sha256:" + "6" * 64
    cutoff = "2026-08-31T00:00:00+00:00"
    fresh_until = "2026-09-01T00:00:00+00:00"

    def _arm(arm: str, report: str, provenance: str) -> dict[str, object]:
        facts: dict[str, object] = {
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
                    "metric_id": metric_id,
                    "absolute_value": value,
                    "sample_size": 30,
                    "confidence_level_basis_points": 9_500,
                    "lower_bound": value * 0.8,
                    "upper_bound": value * 1.2,
                }
                for metric_id, value in _COHORT_METRIC_VALUES.items()
            ],
            "guards": [
                {
                    "guard_id": guard_id,
                    "observed_basis_points": 0,
                    "maximum_basis_points": 0,
                    "sample_size": 30,
                    "breached": False,
                }
                for guard_id in policy.required_guard_ids
            ],
        }
        evidence: dict[str, object] = {
            "schema_version": "1.0.0",
            "authority_class": policy.allowed_authority_classes[0],
            "source_identity": policy.allowed_source_identities[0],
            "authentication_evidence_digest": static,
            "scope_digest": scope,
            "purpose_id": policy.purpose_id,
            "producer_id": policy.producer_id,
            "producer_version": policy.producer_version,
            "method_id": policy.method_id,
            "method_version": policy.method_version,
            "source_revision": revision,
            "evidence_digest": cohort_arm_fact_digest_values(**facts),
            "provenance_digest": provenance,
            "event_at": "2026-08-30T22:00:00+00:00",
            "evidence_cutoff": cutoff,
            "recorded_at": "2026-08-31T00:30:00+00:00",
            "fresh_until": fresh_until,
            "freshness_policy_id": "sre-cohort-claim-freshness",
            "freshness_policy_version": "1.0.0",
            "freshness_policy_digest": policy.freshness_policy_digest,
            "freshness_ceiling_seconds": policy.freshness_ceiling_seconds,
            "completeness_basis_points": 10_000,
            "completeness_evidence_digest": static,
            "conflict_status": "clear",
            "conflict_evidence_digest": static,
            "conflict_evidence_digests": [],
            "synthetic": synthetic,
            "execution_authority": False,
        }
        evidence["receipt_digest"] = decision_critical_evidence_receipt_digest(**evidence)
        return {**facts, "evidence_receipt": evidence}

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
    return {"receipt": receipt}


class _TrustedAdmissions:
    """Stand-in for the trusted shared admission provider injected by a caller.

    It never reads the artifact for admissions; it mints one per arm from the
    canonical arm-fact digest the evaluator independently recomputes.
    """

    def __init__(self, *, evidence_digest: str | None = None) -> None:
        self.evidence_digest = evidence_digest

    def admissions_for(
        self, receipt: BaselineTreatmentCohortReceipt
    ) -> tuple[DecisionEvidenceAdmission, ...]:
        return tuple(
            DecisionEvidenceAdmission(
                receipt_digest=arm.evidence_receipt.receipt_digest,
                verification_bundle_digest="sha256:" + "7" * 64,
                evidence_digest=self.evidence_digest or cohort_arm_fact_digest(arm),
                scope_digest=arm.scenario_set_digest,
                purpose_id=arm.evidence_receipt.purpose_id,
                source_revision=arm.fdai_revision,
                verified_at=datetime.now(tz=UTC) - timedelta(minutes=5),
                valid_until=datetime.now(tz=UTC) + timedelta(hours=1),
            )
            for arm in (receipt.baseline, receipt.treatment)
        )


def _written(tmp_path: Path, bundle: dict[str, object]) -> Path:
    path = tmp_path / "cohort.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


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
    _, summary = _run(
        SCENARIOS,
        None,
        _written(tmp_path, _cohort_bundle()),
        cohort_revision=COHORT_REVISION,
        admission_provider=_TrustedAdmissions(),
    )

    assert summary["cohort_claim"]["claim_eligible"] is True
    assert summary["cohort_claim"]["artifact_origin"] == "governed_external"
    assert summary["cohort_claim"]["policy_id"] == "sre-cohort-claim"
    # The frozen set is still 12 scenarios, so the release gate keeps the
    # published claim ineligible even with a governed cohort.
    assert summary["evidence"]["claim_eligible"] is False


def test_a_governed_receipt_without_an_injected_provider_stays_ineligible(
    tmp_path: Path,
) -> None:
    _, summary = _run(
        SCENARIOS,
        None,
        _written(tmp_path, _cohort_bundle()),
        cohort_revision=COHORT_REVISION,
    )

    assert summary["cohort_claim"]["claim_eligible"] is False
    assert "evidence_not_admitted" in summary["cohort_claim"]["rejection_reasons"]


@pytest.mark.parametrize(
    "invented",
    ["sha256:" + "2" * 64, "sha256:" + "9" * 64],
)
def test_an_invented_admission_digest_cannot_make_the_claim_eligible(
    tmp_path: Path, invented: str
) -> None:
    _, summary = _run(
        SCENARIOS,
        None,
        _written(tmp_path, _cohort_bundle()),
        cohort_revision=COHORT_REVISION,
        admission_provider=_TrustedAdmissions(evidence_digest=invented),
    )

    assert summary["cohort_claim"]["claim_eligible"] is False
    assert "evidence_not_admitted" in summary["cohort_claim"]["rejection_reasons"]


@pytest.mark.parametrize("key", UNTRUSTED_BUNDLE_KEYS)
def test_an_artifact_that_carries_its_own_trust_inputs_is_refused(tmp_path: Path, key: str) -> None:
    bundle = {**_cohort_bundle(), key: []}

    with pytest.raises(CohortClaimBundleError, match="MUST NOT carry its own trust inputs"):
        _run(
            SCENARIOS,
            None,
            _written(tmp_path, bundle),
            cohort_revision=COHORT_REVISION,
            admission_provider=_TrustedAdmissions(),
        )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"synthetic": True}, "synthetic"),
        ({"origin": "repository"}, "artifact_ungoverned"),
        ({"revision": _OTHER_REVISION}, "revision_mismatch"),
    ],
)
def test_a_defective_cohort_receipt_fails_closed(
    tmp_path: Path,
    overrides: dict[str, object],
    expected: str,
) -> None:
    bundle = _written(tmp_path, _cohort_bundle(**overrides))  # type: ignore[arg-type]

    _, summary = _run(
        SCENARIOS,
        None,
        bundle,
        cohort_revision=COHORT_REVISION,
        admission_provider=_TrustedAdmissions(),
    )

    assert summary["cohort_claim"]["claim_eligible"] is False
    assert expected in summary["cohort_claim"]["rejection_reasons"]


def test_a_repository_artifact_at_a_cli_path_still_publishes_a_repository_origin(
    tmp_path: Path,
) -> None:
    """The presence of a ``--cohort-receipt`` path never governs an artifact."""
    _, summary = _run(
        SCENARIOS,
        None,
        _written(tmp_path, _cohort_bundle(origin="repository")),
        cohort_revision=COHORT_REVISION,
        admission_provider=_TrustedAdmissions(),
    )

    assert summary["cohort_claim"]["artifact_origin"] == "repository"
    assert summary["cohort_claim"]["rejection_reasons"] == ["artifact_ungoverned"]


def test_a_governed_receipt_without_a_caller_revision_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CohortClaimBundleError, match="caller-supplied revision"):
        _run(SCENARIOS, None, _written(tmp_path, _cohort_bundle()))


def test_a_cohort_receipt_for_another_frozen_set_fails_closed(tmp_path: Path) -> None:
    bundle = _written(tmp_path, _cohort_bundle(scenario_set_version="v2026.08"))

    _, summary = _run(
        SCENARIOS,
        None,
        bundle,
        cohort_revision=COHORT_REVISION,
        admission_provider=_TrustedAdmissions(),
    )

    assert summary["cohort_claim"]["claim_eligible"] is False
    assert "scenario_set_mismatch" in summary["cohort_claim"]["rejection_reasons"]


def test_an_unreadable_cohort_receipt_is_refused(tmp_path: Path) -> None:
    bundle = tmp_path / "cohort.json"
    bundle.write_text("{", encoding="utf-8")

    with pytest.raises(CohortClaimBundleError, match="unreadable"):
        _run(SCENARIOS, None, bundle, cohort_revision=COHORT_REVISION)


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
