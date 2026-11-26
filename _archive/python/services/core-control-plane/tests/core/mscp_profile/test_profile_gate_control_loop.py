"""Control-loop MSCP profile lifecycle gate tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.core.control_loop import ControlLoop
from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.mscp_profile import (
    IndependentProfileReview,
    MscpCandidateKey,
    MscpProfileLifecycleReader,
    MscpReadinessPolicy,
    MscpReadinessReport,
    ReviewedEffectOutcome,
    StateStoreMscpProfileLifecycle,
    evaluate_mscp_readiness,
    readiness_digest,
)
from fdai.core.risk_gate import ActionPromotionRegistry, PromotionMetrics, RiskGate
from fdai.core.risk_gate.risk_table import RiskLevel, RiskRule, RiskTable
from fdai.shared.contracts.models import (
    Action,
    ActionBlastRadius,
    Autonomy,
    BlastRadiusComputation,
    BlastRadiusScope,
    CeilingByTier,
    CeilingRole,
    Event,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Rule,
    TierCeiling,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

pytestmark = pytest.mark.asyncio

_NOW = datetime(2026, 10, 4, 5, 0, tzinfo=UTC)
_ACTION_TYPE = "ops.scale-out"
_CANDIDATE = MscpCandidateKey(
    action_type=_ACTION_TYPE,
    effect_metric="delivery_receipt_count",
    environment="non-production",
    observer_version="observer-v1",
)


def _action() -> Action:
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "example-action-1",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type": _ACTION_TYPE,
            "target_resource_ref": "resource:example/rg/vm-a",
            "operation": "scale",
            "params": {},
            "stop_condition": "provider_api_error_streak",
            "stop_conditions": [{"kind": "provider_api_error_streak", "count": 3}],
            "rollback_ref": {"kind": "state_forward_only"},
            "blast_radius": {"scope": "resource", "count": 1, "rate_per_minute": 5},
            "mode": "enforce",
            "citing_rules": ["example.rule.x"],
            "created_at": "2026-10-04T05:00:00Z",
            "action_type_ref": {
                "kind": "action",
                "name": _ACTION_TYPE,
                "version": "1.0.0",
                "catalog_digest": "sha256:" + "a" * 64,
            },
        }
    )


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "event-1",
            "source": "example",
            "event_type": "resource.alert",
            "detected_at": "2026-10-04T05:00:00Z",
            "ingested_at": "2026-10-04T05:00:01Z",
            "mode": "enforce",
            "payload": {
                "resource": {
                    "resource_type": "compute.vm",
                    "props": {"environment": "non-prod"},
                },
            },
        }
    )


def _rule() -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "example.rule.x",
            "version": "1.0.0",
            "source": "custom",
            "severity": "low",
            "category": "config_drift",
            "resource_type": "compute.vm",
            "check_logic": {"kind": "rego", "reference": "policies/example/x.rego"},
            "remediation": {"template_ref": "remediations/example-x"},
            "remediates": _ACTION_TYPE,
            "provenance": {
                "source_url": "https://example.com/x",
                "resolved_ref": "0" * 40,
                "content_hash": "sha256:example",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-10-04T05:00:00Z",
            },
        }
    )


def _action_type() -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=_ACTION_TYPE,
        version="1.0.0",
        operation=Operation.SCALE,
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        default_mode=Mode.SHADOW,
        promotion_gate=PromotionGate(
            min_shadow_days=14, min_samples=100, min_accuracy=0.95, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
        ceiling_by_tier=CeilingByTier(
            t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.OWNER),
            t1=TierCeiling(max_autonomy=Autonomy.ENFORCE_HIL, min_role=CeilingRole.OWNER),
            t2=TierCeiling(max_autonomy=Autonomy.SHADOW_ONLY, min_role=CeilingRole.OWNER),
        ),
        description="Synthetic action for MSCP profile gate tests.",
    )


def _readiness() -> MscpReadinessReport:
    outcomes = tuple(
        ReviewedEffectOutcome(
            candidate=_CANDIDATE,
            observed_at=_NOW - timedelta(days=index % 14, seconds=index),
            reviewed=True,
            prediction_accurate=True,
            false_positive=False,
            false_negative=False,
            policy_escape=False,
            correlation_error=False,
            verified_then_rollback_or_incident=False,
            observer_available=True,
            stale=False,
            provider_failed=False,
            observation_latency_ms=100,
            rollback=False,
            human_touchpoint=False,
        )
        for index in range(200)
    )
    return evaluate_mscp_readiness(
        outcomes,
        policy=MscpReadinessPolicy(demotion_drill_passed=True),
    )


def _review(readiness: MscpReadinessReport) -> IndependentProfileReview:
    return IndependentProfileReview(
        review_id="review-one",
        reviewer_id="independent-reviewer",
        candidate=_CANDIDATE,
        readiness_digest=readiness_digest(readiness),
        reviewed_at=_NOW,
        approved=True,
    )


async def _active_lifecycle(store: InMemoryStateStore) -> StateStoreMscpProfileLifecycle:
    lifecycle = StateStoreMscpProfileLifecycle(store)
    registered = await lifecycle.register(_CANDIDATE, at=_NOW)
    readiness = _readiness()
    await lifecycle.promote(
        _CANDIDATE,
        expected_revision=registered.revision,
        readiness=readiness,
        review=_review(readiness),
        at=_NOW + timedelta(minutes=1),
    )
    return lifecycle


def _promoted_registry(action_type: OntologyActionType) -> ActionPromotionRegistry:
    registry = ActionPromotionRegistry(allow_legacy_metrics=True, clock=lambda: _NOW)
    registry.consider_promotion(
        action_type=action_type,
        metrics=PromotionMetrics(
            action_type=action_type.name,
            shadow_days=14,
            samples=100,
            accuracy=1.0,
            policy_escapes=0,
        ),
    )
    return registry


def _loop(
    *,
    audit: InMemoryStateStore,
    lifecycle: MscpProfileLifecycleReader,
    resolver: Callable[[Action], MscpCandidateKey | None] | None = lambda _action: _CANDIDATE,
    executor: MagicMock | None = None,
) -> ControlLoop:
    action_type = _action_type()

    def clock() -> datetime:
        return _NOW

    action_builder = MagicMock()
    action_builder.clock = clock
    return ControlLoop(
        event_ingest=MagicMock(),
        trust_router=MagicMock(),
        t0_engine=MagicMock(),
        action_builder=action_builder,
        executor=executor or MagicMock(),
        audit_store=audit,
        rules_by_id={_rule().id: _rule()},
        risk_table=RiskTable(
            version="test",
            owner_group="test-risk",
            rules=(
                RiskRule(
                    rule_id="test-default-auto",
                    decision=RiskLevel.AUTO,
                    reason="test",
                    is_default=True,
                ),
            ),
        ),
        action_types_by_name={action_type.name: action_type},
        risk_gate=RiskGate(registry=_promoted_registry(action_type), clock=clock),
        mscp_profile_candidate_resolver=resolver,
        mscp_profile_lifecycle=lifecycle,
        clock=clock,
    )


def _audit_entry(store: InMemoryStateStore) -> dict[str, Any]:
    return dict(store.audit_entries[-1]["entry"])


async def test_reviewed_profile_preserves_risk_approval_execution_and_audit_owners() -> None:
    store = InMemoryStateStore()
    lifecycle = await _active_lifecycle(store)
    audit = InMemoryStateStore()
    loop = _loop(audit=audit, lifecycle=lifecycle)

    unified = await loop._evaluate_and_audit(event=_event(), action=_action(), rule=_rule())
    entry = _audit_entry(audit)

    assert unified is not None
    assert unified.decision == "auto"
    assert unified.gate.effective_mode is Mode.ENFORCE
    assert unified.winning_side == "gate+authority"
    assert entry["action_kind"] == "risk_gate.unified"
    assert entry["actor"] == "fdai.core.control_loop"
    assert entry["producer_principal"] == "Forseti"
    assert entry["mscp_profile"]["state"] == "reviewed_gating"
    assert entry["mscp_profile"]["decision"] == "auto"
    assert entry["mscp_profile"]["lowered"] is False


def _missing_candidate(_action: Action) -> MscpCandidateKey | None:
    return None


async def test_missing_profile_candidate_fails_closed_to_shadow() -> None:
    store = InMemoryStateStore()
    lifecycle = await _active_lifecycle(store)
    audit = InMemoryStateStore()
    loop = _loop(audit=audit, lifecycle=lifecycle, resolver=_missing_candidate)

    unified = await loop._evaluate_and_audit(event=_event(), action=_action(), rule=_rule())
    entry = _audit_entry(audit)

    assert unified is not None
    assert unified.decision == "shadow"
    assert unified.gate.effective_mode is Mode.ENFORCE
    assert unified.winning_side == "mscp_profile"
    assert entry["mscp_profile"]["state"] == "candidate_missing"
    assert entry["mscp_profile"]["lowered"] is True


async def test_unreviewed_profile_fails_closed_until_reviewed() -> None:
    store = InMemoryStateStore()
    lifecycle = StateStoreMscpProfileLifecycle(store)
    await lifecycle.register(_CANDIDATE, at=_NOW)
    audit = InMemoryStateStore()
    loop = _loop(audit=audit, lifecycle=lifecycle)

    unified = await loop._evaluate_and_audit(event=_event(), action=_action(), rule=_rule())
    entry = _audit_entry(audit)

    assert unified is not None
    assert unified.decision == "shadow"
    assert entry["mscp_profile"]["state"] == "profile_unreviewed"
    assert entry["mscp_profile"]["lifecycle_mode"] == "shadow"


class _InvalidLifecycle:
    async def get(self, candidate: MscpCandidateKey) -> Any:
        del candidate
        raise ValueError("corrupt lifecycle state")


async def test_invalid_profile_lifecycle_fails_closed_to_shadow() -> None:
    audit = InMemoryStateStore()
    loop = _loop(audit=audit, lifecycle=_InvalidLifecycle())

    unified = await loop._evaluate_and_audit(event=_event(), action=_action(), rule=_rule())
    entry = _audit_entry(audit)

    assert unified is not None
    assert unified.decision == "shadow"
    assert unified.winning_side == "mscp_profile"
    assert entry["mscp_profile"]["state"] == "profile_invalid"
    assert entry["mscp_profile"]["lowered"] is True


async def test_lifecycle_rollback_restores_shadow_hold_without_hil_or_dispatch() -> None:
    store = InMemoryStateStore()
    lifecycle = await _active_lifecycle(store)
    active = await lifecycle.get(_CANDIDATE)
    await lifecycle.demote(
        _CANDIDATE,
        expected_revision=active.revision,
        reason="rollback_drill",
        at=_NOW + timedelta(minutes=2),
    )
    audit = InMemoryStateStore()
    executor = MagicMock()
    executor.execute = AsyncMock(
        return_value=ExecutionResult(
            action_id=str(_action().action_id),
            outcome=ExecutorOutcome.PUBLISHED,
        )
    )
    loop = _loop(audit=audit, lifecycle=lifecycle, executor=executor)

    unified = await loop._evaluate_and_audit(event=_event(), action=_action(), rule=_rule())
    entry = _audit_entry(audit)

    assert unified is not None
    assert unified.decision == "shadow"
    assert unified.requires_hil is False
    assert entry["mscp_profile"]["state"] == "profile_unreviewed"
    assert entry["mscp_profile"]["lifecycle_mode"] == "shadow"
    executor.execute.assert_not_awaited()


async def test_profile_gate_replay_is_deterministic_after_lifecycle_restart() -> None:
    store = InMemoryStateStore()
    await _active_lifecycle(store)
    first_audit = InMemoryStateStore()
    replay_audit = InMemoryStateStore()

    first_loop = _loop(
        audit=first_audit,
        lifecycle=StateStoreMscpProfileLifecycle(store),
    )
    replay_loop = _loop(
        audit=replay_audit,
        lifecycle=StateStoreMscpProfileLifecycle(store),
    )
    first = await first_loop._evaluate_and_audit(event=_event(), action=_action(), rule=_rule())
    replay = await replay_loop._evaluate_and_audit(event=_event(), action=_action(), rule=_rule())

    assert first is not None and replay is not None
    assert first.decision == replay.decision == "auto"
    assert first.level is replay.level
    assert _audit_entry(first_audit)["mscp_profile"] == _audit_entry(replay_audit)["mscp_profile"]
