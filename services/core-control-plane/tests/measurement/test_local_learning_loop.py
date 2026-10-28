"""Azure-free proof that a verified enforce outcome reaches the T1 pattern library.

The chain runs in process: growth context recorded before dispatch, an enforce action executed
against a local resource, an independent observation, the verified-outcome audit entry, the
pattern-growth runner, and a T1 lookup. Nothing here calls a cloud, a model, or a database.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.core.control_loop import ControlLoop
from fdai.core.control_loop._growth_context import (
    GROWTH_CONTEXT_ACTION_KIND,
    record_growth_context,
)
from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.measurement.runners import PatternGrowthIntakeRunner
from fdai.core.mscp_profile import ExpectedEffect, ObservedEffect
from fdai.core.tiers.t1_lightweight.testing import (
    DeterministicEmbeddingModel,
    InMemoryPatternLibrary,
)
from fdai.core.tiers.t1_lightweight.tier import (
    T1Config,
    T1Outcome,
    T1Tier,
    event_embedding_projection,
)
from fdai.delivery.measurement.postgres_growth import (
    PostgresVerifiedOutcomeSource,
    PostgresVerifiedPatternBuilder,
    merge_growth_context,
)
from fdai.shared.contracts.models import Action, Event, Mode, Rule
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 10, 28, tzinfo=UTC)
_TARGET = "resource:example/rg/res-a"
_RULE_ID = "example.tag.required"


def _event(event_id: str, *, resource: str) -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": event_id,
            "idempotency_key": f"idem-{event_id}",
            "source": "test_source",
            "event_type": "inventory.resource_changed",
            "detected_at": _NOW.isoformat(),
            "ingested_at": _NOW.isoformat(),
            "mode": Mode.SHADOW.value,
            "payload": {
                "resource": {
                    "type": "resource-group",
                    "resource_id": resource,
                    "props": {"tags": {}, "location": "example"},
                }
            },
        }
    )


def _action(mode: Mode) -> Action:
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "example-action-1",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type": "remediate.tag-add",
            "target_resource_ref": _TARGET,
            "operation": "tag",
            "params": {"tag": "owner", "value": "team-example"},
            "stop_condition": "provider_api_error_streak",
            "stop_conditions": [{"kind": "provider_api_error_streak", "count": 3}],
            "rollback_ref": {"kind": "state_forward_only"},
            "blast_radius": {"scope": "resource", "count": 1, "rate_per_minute": 5},
            "mode": mode.value,
            "citing_rules": [_RULE_ID],
            "created_at": _NOW.isoformat(),
            "action_type_ref": {
                "kind": "action",
                "name": "remediate.tag-add",
                "version": "1.1.0",
                "catalog_digest": "sha256:" + "a" * 64,
            },
        }
    )


def _rule() -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": _RULE_ID,
            "version": "1.0.0",
            "source": "custom",
            "severity": "low",
            "category": "config_drift",
            "resource_type": "resource-group",
            "check_logic": {"kind": "rego", "reference": "policies/example/x.rego"},
            "remediation": {"template_ref": "remediations/example-x"},
            "remediates": "remediate.tag-add",
            "provenance": {
                "source_url": "https://example.com/x",
                "resolved_ref": "0" * 40,
                "content_hash": "sha256:example",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-07-21T00:00:00Z",
            },
        }
    )


class _LocalResource:
    """A local stand-in for the target; the observer reads it independently of the executor."""

    def __init__(self) -> None:
        self.tags: dict[str, str] = {}


class _Clock:
    def __init__(self) -> None:
        self._now = _NOW

    def __call__(self) -> datetime:
        current = self._now
        self._now += timedelta(seconds=30)
        return current


def _loop(audit: InMemoryStateStore, resource: _LocalResource) -> ControlLoop:
    async def execute(*, action: Action, rule: Rule, **_: Any) -> ExecutionResult:
        resource.tags[str(action.params["tag"])] = str(action.params["value"])
        return ExecutionResult(
            action_id=str(action.action_id),
            outcome=ExecutorOutcome.PUBLISHED,
            audit_context={"effect_applied": True},
        )

    async def predict(action: Action) -> ExpectedEffect:
        return ExpectedEffect(
            prediction_id="prediction-1",
            target_ref=action.target_resource_ref,
            metric="tag_present",
            acceptable_min=1.0,
            acceptable_max=1.0,
            predicted_at=_NOW,
            observation_deadline=_NOW + timedelta(minutes=5),
        )

    async def observe(action: Action, expected: ExpectedEffect) -> ObservedEffect:
        present = resource.tags.get(str(action.params["tag"])) == action.params["value"]
        return ObservedEffect(
            prediction_id=expected.prediction_id,
            target_ref=expected.target_ref,
            metric=expected.metric,
            value=1.0 if present else 0.0,
            observed_at=_NOW + timedelta(minutes=1),
        )

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=execute)
    clock = _Clock()
    builder = MagicMock()
    builder.clock = clock
    return ControlLoop(
        event_ingest=MagicMock(),
        trust_router=MagicMock(),
        t0_engine=MagicMock(),
        action_builder=builder,
        executor=executor,
        audit_store=audit,
        rules_by_id={_RULE_ID: _rule()},
        mscp_expected_effect_provider=predict,
        mscp_effect_observer=observe,
        clock=clock,
    )


def _entries(audit: InMemoryStateStore, kind: str) -> list[dict[str, Any]]:
    return [
        dict(item["entry"]) for item in audit.audit_entries if item["entry"]["action_kind"] == kind
    ]


class _Source(PostgresVerifiedOutcomeSource):
    def __init__(self, store: InMemoryStateStore, audit: InMemoryStateStore) -> None:
        super().__init__(dsn="unused-local-fake", state_store=store)
        self._audit = audit

    async def _rows(self, after_seq: int) -> list[Mapping[str, Any]]:
        return [
            {"seq": index, "entry": entry, "created_at": _NOW + timedelta(minutes=2)}
            for index, entry in enumerate(_entries(self._audit, "measurement.action_outcome.v1"), 1)
            if index > after_seq
        ]


class _Builder(PostgresVerifiedPatternBuilder):
    def __init__(self, audit: InMemoryStateStore) -> None:
        super().__init__(dsn="unused-local-fake", embedding_model=DeterministicEmbeddingModel())
        self._audit = audit

    async def _entry(self, action_id: str) -> Mapping[str, Any] | None:
        outcomes = [
            entry
            for entry in _entries(self._audit, "measurement.action_outcome.v1")
            if entry["action_id"] == action_id
        ]
        if not outcomes:
            return None
        contexts = [
            entry
            for entry in _entries(self._audit, GROWTH_CONTEXT_ACTION_KIND)
            if entry["action_id"] == action_id
        ]
        merged = merge_growth_context(outcomes[-1], contexts[-1] if contexts else {})
        return {**merged, "recorded_at": _NOW + timedelta(minutes=2)}


async def _grow(audit: InMemoryStateStore, library: InMemoryPatternLibrary) -> Any:
    return await PatternGrowthIntakeRunner(
        outcome_source=_Source(InMemoryStateStore(), audit),
        pattern_builder=_Builder(audit),
        writer=library,
        audit_store=audit,
        clock=lambda: _NOW + timedelta(days=1),
    ).run_once()


async def _enforce_run(audit: InMemoryStateStore, *, record_context: bool) -> _LocalResource:
    resource = _LocalResource()
    action = _action(Mode.ENFORCE)
    if record_context:
        await record_growth_context(
            audit,
            event=_event("00000000-0000-0000-0000-000000000001", resource=_TARGET),
            action=action,
            rule=_rule(),
            incident_id="incident-1",
        )
    await _loop(audit, resource)._dispatch_action(
        action=action, rule=_rule(), authorization_decision="auto"
    )
    return resource


@pytest.mark.asyncio
async def test_verified_enforce_outcome_becomes_a_shadow_t1_pattern() -> None:
    audit = InMemoryStateStore()
    resource = await _enforce_run(audit, record_context=True)
    assert resource.tags == {"owner": "team-example"}
    [outcome] = _entries(audit, "measurement.action_outcome.v1")
    assert outcome["execution_mode"] == "enforce" and outcome["verification_passed"] is True

    library = InMemoryPatternLibrary()
    report = await _grow(audit, library)
    assert report.accepted_count == 1

    similar = _event("00000000-0000-0000-0000-000000000002", resource="resource:example/rg/res-b")
    decision = await T1Tier(
        embedding_model=DeterministicEmbeddingModel(),
        pattern_library=library,
        config=T1Config(similarity_threshold=0.8, min_success_rate=0.9),
    ).evaluate(event=similar)
    assert decision.best_match is not None
    assert decision.best_match.score == pytest.approx(1.0)
    assert decision.best_match.action.action_type == "remediate.tag-add"
    # Growth writes shadow statistics, so reuse stays below the success-rate floor.
    assert decision.outcome is T1Outcome.ABSTAIN
    assert any("success_rate=" in reason for reason in decision.reasons)


@pytest.mark.asyncio
async def test_a_pattern_is_embedded_with_the_same_projection_t1_queries() -> None:
    audit = InMemoryStateStore()
    await _enforce_run(audit, record_context=True)
    [context] = _entries(audit, GROWTH_CONTEXT_ACTION_KIND)
    event = _event("00000000-0000-0000-0000-000000000001", resource=_TARGET)
    assert context["embedding_projection"] == event_embedding_projection(event)
    assert context["execution_authority"] is False
    assert context["incident_id"] == "incident-1"


@pytest.mark.asyncio
async def test_without_recorded_context_no_pattern_can_be_built() -> None:
    audit = InMemoryStateStore()
    await _enforce_run(audit, record_context=False)
    library = InMemoryPatternLibrary()
    report = await _grow(audit, library)
    assert report.accepted_count == 0
    assert len(library._entries) == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_shadow_actions_never_record_growth_context() -> None:
    audit = InMemoryStateStore()
    await record_growth_context(
        audit,
        event=_event("00000000-0000-0000-0000-000000000001", resource=_TARGET),
        action=_action(Mode.SHADOW),
        rule=_rule(),
        incident_id="incident-1",
    )
    assert _entries(audit, GROWTH_CONTEXT_ACTION_KIND) == []


@pytest.mark.asyncio
async def test_context_audit_failure_never_stops_the_loop() -> None:
    class _Failing:
        async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
            raise RuntimeError("audit unavailable")

    await record_growth_context(
        _Failing(),  # type: ignore[arg-type]
        event=_event("00000000-0000-0000-0000-000000000001", resource=_TARGET),
        action=_action(Mode.ENFORCE),
        rule=_rule(),
        incident_id="incident-1",
    )


def test_the_outcome_wins_over_recorded_context() -> None:
    merged = merge_growth_context(
        {"rule_id": "from-outcome"}, {"rule_id": "from-context", "params": {}}
    )
    assert merged == {"rule_id": "from-outcome", "params": {}}


def test_rollback_state_is_unknown_unless_the_effect_was_independently_verified() -> None:
    from fdai.core.control_loop._execution_effects import _rollback_state
    from fdai.core.mscp_profile import (
        EffectVerificationReason,
        EffectVerificationResult,
        EffectVerificationStatus,
    )

    plain = ExecutionResult(action_id="a", outcome=ExecutorOutcome.PUBLISHED)
    verified = EffectVerificationResult(
        EffectVerificationStatus.VERIFIED, EffectVerificationReason.WITHIN_ACCEPTABLE_RANGE
    )
    held = EffectVerificationResult(
        EffectVerificationStatus.HOLD, EffectVerificationReason.PREDICTION_UNAVAILABLE
    )
    assert _rollback_state(plain, verified) is False
    assert _rollback_state(plain, held) is None
