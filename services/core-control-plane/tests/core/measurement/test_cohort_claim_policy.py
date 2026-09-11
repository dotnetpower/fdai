"""Trusted cohort claim policy tests."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from fdai.core.measurement.cohort_claim_policy import (
    COHORT_CLAIM_POLICY_PATH,
    REQUIRED_SUCCESS_METRIC_IDS,
    ZERO_THRESHOLD_GUARD_IDS,
    CohortClaimPolicyError,
    frozen_scenario_set_digest,
    load_cohort_claim_policy,
    require_commit_revision,
)
from fdai_service_contracts.baseline_cohort import MINIMUM_COHORT_SAMPLE_SIZE

REPO_ROOT = Path(__file__).resolve().parents[5]
POLICY_PATH = REPO_ROOT / COHORT_CLAIM_POLICY_PATH
SCENARIO_ROOT = REPO_ROOT / "services/core-control-plane/tests/scenarios/v2026.07"
REVISION = "0123456789abcdef0123456789abcdef01234567"


def _body() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _written(tmp_path: Path, body: dict[str, Any]) -> Path:
    path = tmp_path / "config" / "policy.json"
    path.parent.mkdir()
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_the_committed_policy_separates_the_benchmark_from_operational_evidence() -> None:
    policy = load_cohort_claim_policy(POLICY_PATH)

    assert policy.benchmark_scenario_set_version == "v2026.07"
    assert policy.benchmark_scenario_set_digest == frozen_scenario_set_digest(SCENARIO_ROOT)
    assert policy.measurement_basis_kind == "prospective_operational"
    assert policy.measurement_protocol_version == "1.0.0"
    assert policy.method_id == "prospective-operational-cohort"
    policy.verify_scenario_set(SCENARIO_ROOT)


def test_the_committed_policy_pins_every_metric_guard_and_the_sample_floor() -> None:
    policy = load_cohort_claim_policy(POLICY_PATH)

    assert set(REQUIRED_SUCCESS_METRIC_IDS) <= set(policy.required_metric_ids)
    assert set(ZERO_THRESHOLD_GUARD_IDS) <= set(policy.required_guard_ids)
    assert len(ZERO_THRESHOLD_GUARD_IDS) == 4
    assert policy.minimum_sample_size >= MINIMUM_COHORT_SAMPLE_SIZE == 30
    assert policy.minimum_completeness_basis_points == 10_000
    assert policy.allowed_exporters("baseline") == ()
    assert policy.allowed_exporters("treatment") == ()


def test_the_requirement_takes_its_revision_from_the_trusted_caller() -> None:
    requirement = load_cohort_claim_policy(POLICY_PATH).requirement(expected_revision=REVISION)

    assert requirement.fdai_revision == REVISION
    assert requirement.baseline_evidence.source_revision == REVISION
    assert requirement.treatment_evidence.source_revision == REVISION
    assert requirement.policy_id == "sre-cohort-claim"
    assert requirement.required_metric_ids == tuple(sorted(REQUIRED_SUCCESS_METRIC_IDS))
    assert requirement.required_guard_ids == tuple(sorted(ZERO_THRESHOLD_GUARD_IDS))
    assert requirement.minimum_sample_size >= 30
    assert requirement.measurement_basis_kind == "prospective_operational"
    assert requirement.measurement_protocol_digest == (requirement.baseline_evidence.scope_digest)


@pytest.mark.parametrize(
    "movable",
    [
        "main",
        "HEAD",
        "v2026.07",
        "refs/heads/main",
        "git:0123456789abcdef0123456789abcdef01234567",
        "0123456789abcdef",
        REVISION.upper(),
        REVISION + "0",
    ],
)
def test_a_movable_revision_is_never_accepted_as_a_cohort_revision(movable: str) -> None:
    policy = load_cohort_claim_policy(POLICY_PATH)

    with pytest.raises(CohortClaimPolicyError, match="immutable full 40- or 64-hex"):
        policy.requirement(expected_revision=movable)
    with pytest.raises(CohortClaimPolicyError, match="immutable full 40- or 64-hex"):
        require_commit_revision(movable)


def test_a_sha256_length_commit_digest_is_accepted() -> None:
    policy = load_cohort_claim_policy(POLICY_PATH)
    sha256_revision = "a" * 64

    assert policy.requirement(expected_revision=sha256_revision).fdai_revision == sha256_revision


def test_a_policy_that_pins_another_scenario_set_fails_closed() -> None:
    policy = load_cohort_claim_policy(POLICY_PATH)
    other = dataclasses.replace(
        policy,
        benchmark_scenario_set_digest="sha256:" + "0" * 64,
    )

    with pytest.raises(CohortClaimPolicyError, match="actual benchmark scenario-set digest"):
        other.verify_scenario_set(SCENARIO_ROOT)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"schema_version": "2.0.0"}, "schema MUST be"),
        ({"minimum_sample_size": 29}, "30-sample floor"),
        ({"minimum_sample_size": "30"}, "MUST be an integer"),
        ({"benchmark_scenario_set_digest": "not-a-digest"}, "MUST be a SHA-256 digest"),
        ({"required_metric_ids": ["auto_resolution_rate"]}, "every success metric"),
        (
            {"required_guard_ids": ["policy_violation_escape_rate"]},
            "every zero-threshold guard",
        ),
        ({"required_guard_ids": []}, "non-empty array"),
        ({"policy_id": ""}, "policy_id MUST be non-empty"),
    ],
)
def test_a_weakened_policy_is_refused(tmp_path: Path, mutation: dict[str, Any], match: str) -> None:
    with pytest.raises(CohortClaimPolicyError, match=match):
        load_cohort_claim_policy(_written(tmp_path, {**_body(), **mutation}))


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("kind", "frozen_scenario_replay", "prospective_operational"),
        ("arm_design", "concurrent_dual_execution", "avoid dual execution"),
        ("baseline_source", "reference_agent_stub", "observed non-FDAI"),
        ("treatment_source", "synthetic_harness", "deployed FDAI"),
        ("dual_execution_allowed", True, "prohibit dual execution"),
        ("independence_key", "event_id", "source_cluster_digest"),
        ("minimum_samples_per_measure", 29, "sample floor MUST match"),
        ("maximum_window_seconds", 7_776_001, "between one and 90 days"),
    ],
)
def test_a_weakened_operational_protocol_is_refused(
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    body = _body()
    body["measurement_basis"][field] = value

    with pytest.raises(CohortClaimPolicyError, match=match):
        load_cohort_claim_policy(_written(tmp_path, body))


def test_a_continuous_metric_cannot_switch_to_a_rate_interval(
    tmp_path: Path,
) -> None:
    body = _body()
    body["measurement_basis"]["interval_methods"]["mttr_seconds"] = "wilson_95"

    with pytest.raises(CohortClaimPolicyError, match="mttr_seconds"):
        load_cohort_claim_policy(_written(tmp_path, body))


def test_an_exporter_cannot_be_authorized_before_its_workflow_exists(
    tmp_path: Path,
) -> None:
    body = _body()
    body["observation_import"]["allowed_exporter_workflow_paths"]["baseline"] = [
        ".github/workflows/cohort-baseline-export.yml"
    ]

    with pytest.raises(CohortClaimPolicyError, match="regular in-repository file"):
        load_cohort_claim_policy(_written(tmp_path, body))


def test_an_existing_exporter_can_be_authorized_atomically(tmp_path: Path) -> None:
    workflow = tmp_path / ".github/workflows/cohort-baseline-export.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: cohort-baseline-export\n", encoding="utf-8")
    body = _body()
    body["observation_import"]["allowed_exporter_workflow_paths"]["baseline"] = [
        ".github/workflows/cohort-baseline-export.yml"
    ]

    policy = load_cohort_claim_policy(_written(tmp_path, body))

    assert policy.allowed_exporters("baseline") == (".github/workflows/cohort-baseline-export.yml",)


def test_an_exporter_workflow_symlink_is_not_authorized(tmp_path: Path) -> None:
    outside = tmp_path / "outside.yml"
    outside.write_text("name: outside\n", encoding="utf-8")
    workflow = tmp_path / ".github/workflows/cohort-baseline-export.yml"
    workflow.parent.mkdir(parents=True)
    workflow.symlink_to(outside)
    body = _body()
    body["observation_import"]["allowed_exporter_workflow_paths"]["baseline"] = [
        ".github/workflows/cohort-baseline-export.yml"
    ]

    with pytest.raises(CohortClaimPolicyError, match="regular in-repository file"):
        load_cohort_claim_policy(_written(tmp_path, body))


def test_an_incomplete_evidence_floor_is_refused(tmp_path: Path) -> None:
    body = _body()
    body["evidence"]["minimum_completeness_basis_points"] = 9_999

    with pytest.raises(CohortClaimPolicyError, match="complete evidence"):
        load_cohort_claim_policy(_written(tmp_path, body))


def test_an_unbounded_freshness_ceiling_is_refused(tmp_path: Path) -> None:
    body = _body()
    body["freshness_policy"]["ceiling_seconds"] = 0

    with pytest.raises(CohortClaimPolicyError, match="bounded seconds"):
        load_cohort_claim_policy(_written(tmp_path, body))


def test_an_absent_policy_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CohortClaimPolicyError, match="unreadable"):
        load_cohort_claim_policy(tmp_path / "absent.json")


def test_an_empty_scenario_directory_has_no_digest(tmp_path: Path) -> None:
    with pytest.raises(CohortClaimPolicyError, match="no frozen scenarios"):
        frozen_scenario_set_digest(tmp_path)


def test_a_changed_scenario_file_changes_the_digest(tmp_path: Path) -> None:
    original = tmp_path / "one.json"
    original.write_text('{"id": "a"}', encoding="utf-8")
    before = frozen_scenario_set_digest(tmp_path)
    original.write_text('{"id": "b"}', encoding="utf-8")

    assert frozen_scenario_set_digest(tmp_path) != before


def test_an_unpinned_revision_is_refused() -> None:
    policy = load_cohort_claim_policy(POLICY_PATH)

    with pytest.raises(CohortClaimPolicyError, match="immutable full 40- or 64-hex"):
        policy.requirement(expected_revision="")
