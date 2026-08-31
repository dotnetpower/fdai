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
)
from fdai_service_contracts.baseline_cohort import MINIMUM_COHORT_SAMPLE_SIZE

REPO_ROOT = Path(__file__).resolve().parents[5]
POLICY_PATH = REPO_ROOT / COHORT_CLAIM_POLICY_PATH
SCENARIO_ROOT = REPO_ROOT / "services/core-control-plane/tests/scenarios/v2026.07"
REVISION = "git:0123456789abcdef0123456789abcdef01234567"


def _body() -> dict[str, Any]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def _written(tmp_path: Path, body: dict[str, Any]) -> Path:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_the_committed_policy_pins_the_actual_frozen_scenario_set() -> None:
    policy = load_cohort_claim_policy(POLICY_PATH)

    assert policy.scenario_set_version == "v2026.07"
    assert policy.scenario_set_digest == frozen_scenario_set_digest(SCENARIO_ROOT)
    policy.verify_scenario_set(SCENARIO_ROOT)


def test_the_committed_policy_pins_every_metric_guard_and_the_sample_floor() -> None:
    policy = load_cohort_claim_policy(POLICY_PATH)

    assert set(REQUIRED_SUCCESS_METRIC_IDS) <= set(policy.required_metric_ids)
    assert set(ZERO_THRESHOLD_GUARD_IDS) <= set(policy.required_guard_ids)
    assert len(ZERO_THRESHOLD_GUARD_IDS) == 4
    assert policy.minimum_sample_size >= MINIMUM_COHORT_SAMPLE_SIZE == 30
    assert policy.minimum_completeness_basis_points == 10_000


def test_the_requirement_takes_its_revision_from_the_trusted_caller() -> None:
    requirement = load_cohort_claim_policy(POLICY_PATH).requirement(expected_revision=REVISION)

    assert requirement.fdai_revision == REVISION
    assert requirement.baseline_evidence.source_revision == REVISION
    assert requirement.treatment_evidence.source_revision == REVISION
    assert requirement.policy_id == "sre-cohort-claim"
    assert requirement.required_metric_ids == tuple(sorted(REQUIRED_SUCCESS_METRIC_IDS))
    assert requirement.required_guard_ids == tuple(sorted(ZERO_THRESHOLD_GUARD_IDS))
    assert requirement.minimum_sample_size >= 30


def test_a_policy_that_pins_another_scenario_set_fails_closed() -> None:
    policy = load_cohort_claim_policy(POLICY_PATH)
    other = dataclasses.replace(policy, scenario_set_digest="sha256:" + "0" * 64)

    with pytest.raises(CohortClaimPolicyError, match="actual frozen scenario-set digest"):
        other.verify_scenario_set(SCENARIO_ROOT)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ({"schema_version": "2.0.0"}, "schema MUST be"),
        ({"minimum_sample_size": 29}, "30-sample floor"),
        ({"minimum_sample_size": "30"}, "MUST be an integer"),
        ({"scenario_set_digest": "not-a-digest"}, "MUST be a SHA-256 digest"),
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

    with pytest.raises(CohortClaimPolicyError, match="cannot pin the expected revision"):
        policy.requirement(expected_revision="")
