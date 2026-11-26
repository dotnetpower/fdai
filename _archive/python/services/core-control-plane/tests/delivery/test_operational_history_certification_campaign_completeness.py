"""Focused regression tests for OI-16 completeness and replay-state honesty.

The campaign may not run the global inventory ontology projection, so a synthetic
checkpoint is expected to report ``valid=False``. Two invariants MUST hold anyway:
an invalid or defective checkpoint is never projected as complete, and a replay
reproduces the stored completeness state instead of promoting it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fdai.core.ontology_platform.operational_history_certification import (
    OperationalHistoryScenario,
    OperationalHistoryScenarioStatus,
)
from fdai.core.ontology_platform.operational_history_lifecycle import (
    ObservationCheckpoint,
    build_observation_checkpoint,
)
from fdai.delivery.operational_history_certification_campaign import (
    REQUIRED_CHECKS,
    ScenarioObservation,
    evaluate_scenario,
    scenario_check,
)
from fdai.delivery.operational_history_certification_campaign_fixture import (
    checkpoint_completeness_state,
    checkpoint_journal_backed,
    completeness_not_overclaimed,
    replay_evidence_checks,
    replay_state_preserved,
    unquarantined_completeness,
)

NOW = datetime(2026, 5, 1, 12, tzinfo=UTC)
PARTITION = "sha256:" + "a" * 64
DIGEST = "sha256:" + "b" * 64
EVIDENCE = "sha256:" + "e" * 64
SCOPE_REF = "synthetic/oi16-certification/campaign-a"


def _checkpoint(
    *,
    valid: bool = True,
    missing: int = 0,
    quarantined: int = 0,
    conflicted: int = 0,
    objects: int = 2,
    relationships: int = 1,
    properties: int = 3,
    watermark: int = 41,
) -> ObservationCheckpoint:
    values: dict[str, object] = {
        "partition_id": PARTITION,
        "first_watermark": watermark,
        "last_watermark": watermark,
        "scope_ref": SCOPE_REF,
        "object_count": objects,
        "relationship_count": relationships,
        "property_count": properties,
        "source_digest": DIGEST,
        "schema_digest": DIGEST,
        "ontology_release_digest": DIGEST,
        "projection_digest": DIGEST,
        "projection_watermark": watermark,
        "graph_digest": DIGEST,
        "missing_count": missing,
        "quarantined_count": quarantined,
        "conflicted_count": conflicted,
        "tombstoned_count": 0,
        "valid": valid,
        "created_at": NOW,
    }
    return build_observation_checkpoint(**cast(Any, values))


DEFECTIVE = (
    pytest.param({"missing": 1}, id="missing"),
    pytest.param({"quarantined": 1}, id="quarantined"),
    pytest.param({"conflicted": 1}, id="conflicted"),
)


def test_a_valid_defect_free_checkpoint_is_the_only_complete_checkpoint() -> None:
    assert unquarantined_completeness(_checkpoint()) is True


def test_an_invalid_checkpoint_is_never_complete() -> None:
    """Regression: an invalid checkpoint MUST NOT be exempted into completeness."""

    assert unquarantined_completeness(_checkpoint(valid=False)) is False


@pytest.mark.parametrize("defect", DEFECTIVE)
def test_a_defective_checkpoint_is_never_complete(defect: dict[str, int]) -> None:
    assert unquarantined_completeness(_checkpoint(**cast(Any, defect))) is False


@pytest.mark.parametrize("defect", DEFECTIVE)
def test_an_invalid_defective_checkpoint_is_never_complete(defect: dict[str, int]) -> None:
    assert unquarantined_completeness(_checkpoint(valid=False, **cast(Any, defect))) is False


def test_a_missing_checkpoint_is_unobserved_rather_than_complete() -> None:
    assert unquarantined_completeness(None) is None
    assert completeness_not_overclaimed(None, claimed_complete=None) is None
    assert checkpoint_completeness_state(None) is None
    assert checkpoint_journal_backed(None) is None


@pytest.mark.parametrize(
    ("checkpoint", "expected"),
    [
        pytest.param(_checkpoint(), True, id="valid"),
        pytest.param(_checkpoint(valid=False), True, id="invalid"),
        pytest.param(_checkpoint(missing=1), False, id="missing"),
        pytest.param(_checkpoint(valid=False, quarantined=2), True, id="invalid_quarantined"),
        pytest.param(_checkpoint(conflicted=3), False, id="conflicted"),
    ],
)
def test_completeness_is_never_claimed_without_grounding(
    checkpoint: ObservationCheckpoint,
    expected: bool,
) -> None:
    """Whenever completeness is projected it MUST be grounded in the stored state."""

    assert completeness_not_overclaimed(checkpoint, claimed_complete=checkpoint.valid) is expected


def test_an_invalid_checkpoint_still_reports_its_own_state() -> None:
    checkpoint = _checkpoint(valid=False, missing=1, quarantined=2, conflicted=3)
    assert checkpoint_completeness_state(checkpoint) == (False, 1, 2, 3)


def test_an_empty_checkpoint_is_not_journal_backed() -> None:
    empty = _checkpoint(valid=False, objects=0, relationships=0, properties=0)
    assert checkpoint_journal_backed(empty) is False


def test_a_replay_that_reproduces_an_invalid_state_preserves_it() -> None:
    stored = _checkpoint(valid=False)
    replay = _checkpoint(valid=False)
    assert replay_state_preserved((stored, replay)) is True


def test_a_replay_that_promotes_validity_is_a_replay_defect() -> None:
    stored = _checkpoint(valid=False)
    replay = _checkpoint(valid=True)
    assert replay_state_preserved((stored, replay)) is False


@pytest.mark.parametrize("defect", DEFECTIVE)
def test_a_replay_that_drops_a_defect_count_is_a_replay_defect(defect: dict[str, int]) -> None:
    stored = _checkpoint(valid=False, **cast(Any, defect))
    replay = _checkpoint(valid=False)
    assert replay_state_preserved((stored, replay)) is False


def test_an_absent_replay_arm_is_unobserved_rather_than_preserved() -> None:
    assert replay_state_preserved((_checkpoint(valid=False), None)) is None
    assert replay_state_preserved(()) is None


def test_replay_evidence_checks_ground_an_invalid_but_real_replay() -> None:
    stored = _checkpoint(valid=False)
    checks = {
        item.code: item.satisfied
        for item in replay_evidence_checks("checkpoint_", (stored, stored))
    }
    assert checks == {
        "checkpoint_journal_backed": True,
        "checkpoint_completeness_not_overclaimed": True,
    }


def test_replay_evidence_checks_refuse_an_empty_replay() -> None:
    empty = _checkpoint(valid=False, objects=0, relationships=0, properties=0)
    checks = {
        item.code: item.satisfied for item in replay_evidence_checks("checkpoint_", (empty, empty))
    }
    assert checks["checkpoint_journal_backed"] is False


def _warm(**overrides: bool | None) -> ScenarioObservation:
    checks = {code: True for code in REQUIRED_CHECKS[OperationalHistoryScenario.WARM_REPLAY]}
    return ScenarioObservation(
        scenario=OperationalHistoryScenario.WARM_REPLAY,
        checks=tuple(
            scenario_check(code, cast(Any, overrides.get(code, satisfied)))
            for code, satisfied in checks.items()
        ),
        evidence_digests=(EVIDENCE,),
    )


def test_warm_replay_certifies_a_deterministic_invalid_replay() -> None:
    """An invalid but non-empty deterministic replay is real evidence, not a pass on nothing."""

    result = evaluate_scenario(OperationalHistoryScenario.WARM_REPLAY, _warm())
    assert result.status is OperationalHistoryScenarioStatus.PASSED


@pytest.mark.parametrize(
    "code",
    [
        "checkpoint_journal_backed",
        "checkpoint_completeness_not_overclaimed",
        "replay_state_preserved",
        "replay_digest_matches",
        "replay_watermarks_match",
        "replay_graph_digest_matches",
    ],
)
def test_warm_replay_never_certifies_a_defective_precondition(code: str) -> None:
    result = evaluate_scenario(OperationalHistoryScenario.WARM_REPLAY, _warm(**{code: False}))
    assert result.status is OperationalHistoryScenarioStatus.FAILED
    assert result.reason_codes == (code,)


@pytest.mark.parametrize(
    "code",
    [
        "checkpoint_journal_backed",
        "checkpoint_completeness_not_overclaimed",
        "replay_state_preserved",
    ],
)
def test_warm_replay_never_certifies_an_unobserved_precondition(code: str) -> None:
    result = evaluate_scenario(OperationalHistoryScenario.WARM_REPLAY, _warm(**{code: None}))
    assert result.status is OperationalHistoryScenarioStatus.UNAVAILABLE
    assert result.reason_codes == (f"{code}_unavailable",)


def test_no_false_completeness_is_a_required_provider_failure_check() -> None:
    assert "no_false_completeness" in REQUIRED_CHECKS[OperationalHistoryScenario.PROVIDER_FAILURE]


def test_provider_failure_never_certifies_an_unobserved_completeness_projection() -> None:
    observation = ScenarioObservation(
        scenario=OperationalHistoryScenario.PROVIDER_FAILURE,
        checks=(
            scenario_check("failure_isolated", True),
            scenario_check("partial_evidence_marked_incomplete", True),
            scenario_check(
                "no_false_completeness",
                completeness_not_overclaimed(None, claimed_complete=None),
            ),
        ),
        evidence_digests=(EVIDENCE,),
    )
    result = evaluate_scenario(OperationalHistoryScenario.PROVIDER_FAILURE, observation)
    assert result.status is OperationalHistoryScenarioStatus.UNAVAILABLE
    assert result.reason_codes == ("no_false_completeness_unavailable",)
