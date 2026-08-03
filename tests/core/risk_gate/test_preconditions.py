"""Deterministic ActionType precondition evidence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fdai.core.risk_gate import (
    EventPreconditionEvaluator,
    GovernedPreconditionEvaluator,
    OntologyChangeWindowEvidenceProvider,
    OntologyOpenActionEvidenceProvider,
)
from fdai.shared.contracts.models import (
    Action,
    ActionPrecondition,
    Event,
    OntologyActionType,
    Operation,
    PreconditionKind,
    PromotionGate,
    RollbackKind,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyObjectRecord,
)


def _action_type(*preconditions: ActionPrecondition) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.example",
        version="1.0.0",
        operation=Operation.UPDATE,
        rollback_contract=RollbackKind.PR_REVERT,
        promotion_gate=PromotionGate(
            min_shadow_days=1,
            min_samples=1,
            min_accuracy=0.9,
            max_policy_escapes=0,
        ),
        preconditions=list(preconditions),
    )


async def test_event_evaluator_checks_property_and_tag(
    valid_event: dict[str, Any], valid_action: dict[str, Any]
) -> None:
    event = Event.model_validate(valid_event).model_copy(
        update={
            "payload": {
                "resource": {
                    "props": {"public_access": "enabled"},
                    "tags": {"approved": "true"},
                }
            }
        }
    )
    action_type = _action_type(
        ActionPrecondition(
            kind=PreconditionKind.RESOURCE_PROPERTY_EQUALS,
            property="public_access",
            value="enabled",
        ),
        ActionPrecondition(
            kind=PreconditionKind.RESOURCE_TAG_PRESENT,
            tag="approved",
        ),
    )

    evaluations = await EventPreconditionEvaluator().evaluate(
        event=event,
        action=Action.model_validate(valid_action),
        action_type=action_type,
    )

    assert [(item.condition_index, item.kind, item.satisfied) for item in evaluations] == [
        (0, PreconditionKind.RESOURCE_PROPERTY_EQUALS, True),
        (1, PreconditionKind.RESOURCE_TAG_PRESENT, True),
    ]


async def test_event_evaluator_emits_false_for_known_mismatch(
    valid_event: dict[str, Any], valid_action: dict[str, Any]
) -> None:
    event = Event.model_validate(valid_event).model_copy(
        update={"payload": {"resource": {"props": {"enabled": 1}}}}
    )
    action_type = _action_type(
        ActionPrecondition(
            kind=PreconditionKind.RESOURCE_PROPERTY_EQUALS,
            property="enabled",
            value=True,
        )
    )

    evaluations = await EventPreconditionEvaluator().evaluate(
        event=event,
        action=Action.model_validate(valid_action),
        action_type=action_type,
    )

    assert len(evaluations) == 1
    assert evaluations[0].satisfied is False


async def test_event_evaluator_leaves_stateful_conditions_unresolved(
    valid_event: dict[str, Any], valid_action: dict[str, Any]
) -> None:
    event = Event.model_validate(valid_event).model_copy(
        update={"payload": {"resource": {"props": {}}}}
    )
    action_type = _action_type(ActionPrecondition(kind=PreconditionKind.MAINTENANCE_WINDOW_ACTIVE))

    evaluations = await EventPreconditionEvaluator().evaluate(
        event=event,
        action=Action.model_validate(valid_action),
        action_type=action_type,
    )

    assert evaluations == ()


class _OpenActions:
    def __init__(self, *, conflict: bool) -> None:
        self.conflict = conflict

    async def has_conflict(
        self,
        *,
        target_ref: str,
        excluding_idempotency_key: str,
    ) -> bool:
        assert target_ref
        assert excluding_idempotency_key
        return self.conflict


class _ChangeWindows:
    def __init__(self, *, active: bool) -> None:
        self.active = active

    async def is_active(self, *, target_ref: str, at: object) -> bool:
        assert target_ref
        assert at
        return self.active


async def test_governed_evaluator_resolves_conflict_and_window(
    valid_event: dict[str, Any], valid_action: dict[str, Any]
) -> None:
    action_type = _action_type(
        ActionPrecondition(kind=PreconditionKind.NO_CONFLICTING_OPEN_ACTION_ON_RESOURCE),
        ActionPrecondition(kind=PreconditionKind.MAINTENANCE_WINDOW_ACTIVE),
    )
    evaluator = GovernedPreconditionEvaluator(
        open_actions=_OpenActions(conflict=False),
        change_windows=_ChangeWindows(active=True),
    )

    evaluations = await evaluator.evaluate(
        event=Event.model_validate(valid_event),
        action=Action.model_validate(valid_action),
        action_type=action_type,
    )

    assert [(item.kind, item.satisfied) for item in evaluations] == [
        (PreconditionKind.NO_CONFLICTING_OPEN_ACTION_ON_RESOURCE, True),
        (PreconditionKind.MAINTENANCE_WINDOW_ACTIVE, True),
    ]


async def test_governed_evaluator_reports_negative_evidence(
    valid_event: dict[str, Any], valid_action: dict[str, Any]
) -> None:
    action_type = _action_type(
        ActionPrecondition(kind=PreconditionKind.NO_CONFLICTING_OPEN_ACTION_ON_RESOURCE),
        ActionPrecondition(kind=PreconditionKind.MAINTENANCE_WINDOW_ACTIVE),
    )
    evaluator = GovernedPreconditionEvaluator(
        open_actions=_OpenActions(conflict=True),
        change_windows=_ChangeWindows(active=False),
    )

    evaluations = await evaluator.evaluate(
        event=Event.model_validate(valid_event),
        action=Action.model_validate(valid_action),
        action_type=action_type,
    )

    assert all(not item.satisfied for item in evaluations)


async def test_governed_evaluator_leaves_unbound_stateful_evidence_unresolved(
    valid_event: dict[str, Any], valid_action: dict[str, Any]
) -> None:
    action_type = _action_type(
        ActionPrecondition(kind=PreconditionKind.NO_CONFLICTING_OPEN_ACTION_ON_RESOURCE),
        ActionPrecondition(kind=PreconditionKind.MAINTENANCE_WINDOW_ACTIVE),
    )

    evaluations = await GovernedPreconditionEvaluator().evaluate(
        event=Event.model_validate(valid_event),
        action=Action.model_validate(valid_action),
        action_type=action_type,
    )

    assert evaluations == ()


class _OntologyQueryStore:
    def __init__(self, snapshot: OntologyGraphSnapshot) -> None:
        self.snapshot = snapshot
        self.queries: list[dict[str, object]] = []

    async def query_objects(self, **query: object) -> OntologyGraphSnapshot:
        self.queries.append(query)
        return self.snapshot


def _object_record(object_type: str, identifier: str, **properties: object) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=identifier,
        object_type=object_type,
        properties={"id": identifier, **properties},
    )


async def test_ontology_open_actions_excludes_retry_and_detects_active_run() -> None:
    store = _OntologyQueryStore(
        OntologyGraphSnapshot(
            objects=(
                _object_record(
                    "ActionRun",
                    "run-retry",
                    target_ref="resource-1",
                    idempotency_key="retry-key",
                    status="executing",
                ),
                _object_record(
                    "ActionRun",
                    "run-conflict",
                    target_ref="resource-1",
                    idempotency_key="other-key",
                    status="hil_pending",
                ),
            )
        )
    )

    conflict = await OntologyOpenActionEvidenceProvider(store).has_conflict(  # type: ignore[arg-type]
        target_ref="resource-1",
        excluding_idempotency_key="retry-key",
    )

    assert conflict is True
    assert store.queries == [
        {
            "object_types": ("ActionRun",),
            "property_equals": {"target_ref": "resource-1"},
            "limit": 500,
        }
    ]


async def test_ontology_open_actions_treats_truncation_as_conflict() -> None:
    store = _OntologyQueryStore(OntologyGraphSnapshot(truncated=True))

    conflict = await OntologyOpenActionEvidenceProvider(store).has_conflict(  # type: ignore[arg-type]
        target_ref="resource-1",
        excluding_idempotency_key="retry-key",
    )

    assert conflict is True


async def test_ontology_change_window_requires_effective_allowing_window() -> None:
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    store = _OntologyQueryStore(
        OntologyGraphSnapshot(
            objects=(
                _object_record(
                    "ChangeWindow",
                    "window-1",
                    scope_ref="resource-1",
                    status="approved",
                    window_kind="maintenance",
                    effective_from=(now - timedelta(hours=1)).isoformat(),
                    effective_to=(now + timedelta(hours=1)).isoformat(),
                ),
            )
        )
    )

    active = await OntologyChangeWindowEvidenceProvider(store).is_active(  # type: ignore[arg-type]
        target_ref="resource-1",
        at=now,
    )

    assert active is True


async def test_ontology_change_window_freeze_overrides_allowing_window() -> None:
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    common = {
        "scope_ref": "resource-1",
        "status": "active",
        "effective_from": (now - timedelta(hours=1)).isoformat(),
        "effective_to": (now + timedelta(hours=1)).isoformat(),
    }
    store = _OntologyQueryStore(
        OntologyGraphSnapshot(
            objects=(
                _object_record(
                    "ChangeWindow",
                    "window-allow",
                    window_kind="maintenance",
                    **common,
                ),
                _object_record(
                    "ChangeWindow",
                    "window-freeze",
                    window_kind="freeze",
                    **common,
                ),
            )
        )
    )

    active = await OntologyChangeWindowEvidenceProvider(store).is_active(  # type: ignore[arg-type]
        target_ref="resource-1",
        at=now,
    )

    assert active is False
