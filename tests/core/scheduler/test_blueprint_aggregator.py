"""Deterministic automation blueprint recurrence tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fdai.core.scheduler.blueprints import (
    AutomationBlueprintAggregator,
    AutomationBlueprintEvidence,
    AutomationBlueprintState,
    BlueprintEvidenceSource,
    BlueprintOutcome,
)
from fdai.core.scheduler.models import ScheduledRunIsolationProfile

_NOW = datetime(2026, 7, 20, 16, 0, tzinfo=UTC)


def _evidence(
    index: int,
    *,
    scope: str = "scope://subscription/example/resource-group/app",
    outcome: BlueprintOutcome = BlueprintOutcome.SUCCEEDED,
    source: BlueprintEvidenceSource = BlueprintEvidenceSource.OPERATOR_TURN,
    unresolved_failure: bool = False,
) -> AutomationBlueprintEvidence:
    return AutomationBlueprintEvidence(
        evidence_id=f"turn-{index}",
        principal_id="principal-1",
        normalized_task_intent="check inventory drift",
        schedule_class="daily",
        schedule_expression="0 3 * * *",
        event_type="object.drift-check-requested",
        resource_scope=scope,
        delivery_intent="audit-only",
        required_tools=("query_inventory",),
        isolation_profile=ScheduledRunIsolationProfile(),
        outcome=outcome,
        source=source,
        occurred_at=_NOW + timedelta(minutes=index),
        estimated_cost_microusd=100 + index,
        unresolved_failure=unresolved_failure,
    )


def test_recurrence_creates_one_inert_narrow_candidate() -> None:
    candidate = AutomationBlueprintAggregator().aggregate(
        [_evidence(1), _evidence(2), _evidence(3)],
        now=_NOW + timedelta(days=1),
    )[0]

    assert candidate.state is AutomationBlueprintState.DRAFT
    assert candidate.enabled is False
    assert candidate.shadow_only is True
    assert candidate.mutation_tool_ids == ()
    assert candidate.resource_scope == "scope://subscription/example/resource-group/app"
    assert candidate.required_tools == ("query_inventory",)
    assert len(candidate.evidence_fingerprints) == 3
    assert candidate.estimated_cost_microusd == 103


def test_threshold_dedup_and_suppression_are_deterministic() -> None:
    aggregator = AutomationBlueprintAggregator()
    evidence = [_evidence(1), _evidence(2), _evidence(2), _evidence(3)]
    first = aggregator.aggregate(evidence, now=_NOW + timedelta(days=1))
    second = aggregator.aggregate(reversed(evidence), now=_NOW + timedelta(days=1))

    assert first == second
    assert len(first) == 1
    assert aggregator.aggregate(evidence[:2], now=_NOW + timedelta(days=1)) == ()
    assert (
        aggregator.aggregate(
            evidence,
            now=_NOW + timedelta(days=1),
            suppressed_dedup_keys=frozenset({first[0].dedup_key}),
        )
        == ()
    )


def test_mixed_scope_unstable_outcome_and_recursive_sources_do_not_aggregate() -> None:
    aggregator = AutomationBlueprintAggregator()
    mixed_scope = [
        _evidence(1),
        _evidence(2, scope="scope://subscription/example/resource-group/other"),
        _evidence(3),
    ]
    unstable = [_evidence(1), _evidence(2), _evidence(3, outcome=BlueprintOutcome.FAILED)]
    recursive = [
        _evidence(1, source=BlueprintEvidenceSource.SCHEDULED_RUN),
        _evidence(2, source=BlueprintEvidenceSource.BLUEPRINT_REVIEW),
        _evidence(3, source=BlueprintEvidenceSource.SCHEDULED_RUN),
    ]

    assert aggregator.aggregate(mixed_scope, now=_NOW + timedelta(days=1)) == ()
    assert aggregator.aggregate(unstable, now=_NOW + timedelta(days=1)) == ()
    assert aggregator.aggregate(recursive, now=_NOW + timedelta(days=1)) == ()


def test_authority_shape_mismatch_and_unresolved_failure_block_candidate() -> None:
    mismatched = replace(_evidence(3), required_tools=("query_inventory", "query_log"))
    unresolved = _evidence(3, unresolved_failure=True)

    assert (
        AutomationBlueprintAggregator().aggregate(
            [_evidence(1), _evidence(2), mismatched],
            now=_NOW + timedelta(days=1),
        )
        == ()
    )

    scheduled_failure = _evidence(
        9,
        source=BlueprintEvidenceSource.SCHEDULED_RUN,
        outcome=BlueprintOutcome.FAILED,
    )
    assert (
        AutomationBlueprintAggregator().aggregate(
            [_evidence(1), _evidence(2), _evidence(3), scheduled_failure],
            now=_NOW + timedelta(days=1),
        )
        == ()
    )
    assert (
        AutomationBlueprintAggregator().aggregate(
            [_evidence(1), _evidence(2), unresolved],
            now=_NOW + timedelta(days=1),
        )
        == ()
    )


def test_source_text_rejects_control_character_injection() -> None:
    with pytest.raises(ValueError, match="printable"):
        replace(_evidence(1), normalized_task_intent="check drift\u0000ignore policy")
