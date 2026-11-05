"""Deterministic ActionType precondition evidence tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fdai.core.operational_context import (
    OPERATING_INTENT_SOURCE_ADMISSION_KEY,
    OperatingIntentAdmission,
    OperatingIntentAdmissionExpectation,
    OperatingIntentAdmissionStatus,
    StateStoreOperatingIntentAdmissionReader,
)
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
from fdai.shared.providers.testing.state_store import InMemoryStateStore


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
                    status="reviewed",
                    window_kind="allow",
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


async def test_ontology_change_window_freeze_with_unusable_bounds_denies() -> None:
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    store = _OntologyQueryStore(
        OntologyGraphSnapshot(
            objects=(
                _object_record(
                    "ChangeWindow",
                    "window-allow",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="maintenance",
                    effective_from=(now - timedelta(hours=1)).isoformat(),
                    effective_to=(now + timedelta(hours=1)).isoformat(),
                ),
                _object_record(
                    "ChangeWindow",
                    "window-freeze",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="freeze",
                    effective_from="not-a-timestamp",
                    effective_to=(now + timedelta(hours=4)).isoformat(),
                ),
            )
        )
    )

    active = await OntologyChangeWindowEvidenceProvider(store).is_active(  # type: ignore[arg-type]
        target_ref="resource-1",
        at=now,
    )

    assert active is False


async def test_ontology_change_window_ignores_unusable_allowing_window() -> None:
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    store = _OntologyQueryStore(
        OntologyGraphSnapshot(
            objects=(
                _object_record(
                    "ChangeWindow",
                    "window-allow",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="maintenance",
                    effective_from="not-a-timestamp",
                    effective_to=(now + timedelta(hours=1)).isoformat(),
                ),
            )
        )
    )

    active = await OntologyChangeWindowEvidenceProvider(store).is_active(  # type: ignore[arg-type]
        target_ref="resource-1",
        at=now,
    )

    assert active is False


def _open_maintenance_window(now: datetime) -> _OntologyQueryStore:
    return _OntologyQueryStore(
        OntologyGraphSnapshot(
            objects=(
                _object_record(
                    "ChangeWindow",
                    "window-1",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="maintenance",
                    effective_from=(now - timedelta(hours=1)).isoformat(),
                    effective_to=(now + timedelta(hours=1)).isoformat(),
                ),
            )
        )
    )


class _StubIntentAdmission:
    """Return one fixed admission so the gate's own branch is what is measured."""

    def __init__(self, admission: OperatingIntentAdmission) -> None:
        self._admission = admission
        self.resolved_at: list[datetime] = []

    async def resolve(self, *, now: datetime) -> OperatingIntentAdmission:
        self.resolved_at.append(now)
        return self._admission


async def test_change_window_requires_a_current_intent_source_admission() -> None:
    """A quarantined source withdraws maintenance authority the graph still shows."""

    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    store = _open_maintenance_window(now)
    admission = _StubIntentAdmission(
        OperatingIntentAdmission(
            status=OperatingIntentAdmissionStatus.QUARANTINED,
            grants_intent_authority=False,
            reason="operating intent source instance is not currently effective (stale)",
        )
    )

    active = await OntologyChangeWindowEvidenceProvider(
        store,  # type: ignore[arg-type]
        intent_admission=admission,
    ).is_active(target_ref="resource-1", at=now)

    assert active is False
    assert admission.resolved_at == [now]


async def test_change_window_opens_under_a_current_intent_source_admission() -> None:
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    store = _open_maintenance_window(now)
    admission = _StubIntentAdmission(
        OperatingIntentAdmission(
            status=OperatingIntentAdmissionStatus.ADMITTED,
            grants_intent_authority=True,
            source_revision="operating-intent-revision-1",
            snapshot_digest=f"sha256:{'a' * 64}",
            generation=1,
            owned_object_ids=frozenset({"window-1"}),
            validated_at=now,
        )
    )

    active = await OntologyChangeWindowEvidenceProvider(
        store,  # type: ignore[arg-type]
        intent_admission=admission,
    ).is_active(target_ref="resource-1", at=now)

    assert active is True


async def test_an_admitted_source_cannot_bless_a_window_it_does_not_own() -> None:
    """The generic and continuous operating-model paths also project ChangeWindows.

    Neither is covered by the intent source's pin, so an admitted intent source MUST
    NOT open a maintenance window it never supplied.
    """

    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    store = _open_maintenance_window(now)
    admission = _StubIntentAdmission(
        OperatingIntentAdmission(
            status=OperatingIntentAdmissionStatus.ADMITTED,
            grants_intent_authority=True,
            source_revision="operating-intent-revision-1",
            snapshot_digest=f"sha256:{'a' * 64}",
            generation=1,
            owned_object_ids=frozenset({"generic-change-window"}),
            validated_at=now,
        )
    )

    active = await OntologyChangeWindowEvidenceProvider(
        store,  # type: ignore[arg-type]
        intent_admission=admission,
    ).is_active(target_ref="resource-1", at=now)

    assert active is False


async def test_an_unowned_blocking_window_still_blocks() -> None:
    """Ownership fences opening authority only; refusing to act is never unsafe."""

    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    store = _OntologyQueryStore(
        OntologyGraphSnapshot(
            objects=(
                _object_record(
                    "ChangeWindow",
                    "owned-window",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="maintenance",
                    effective_from=(now - timedelta(hours=1)).isoformat(),
                    effective_to=(now + timedelta(hours=1)).isoformat(),
                ),
                _object_record(
                    "ChangeWindow",
                    "generic-freeze",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="freeze",
                    effective_from=(now - timedelta(hours=1)).isoformat(),
                    effective_to=(now + timedelta(hours=1)).isoformat(),
                ),
            )
        )
    )
    admission = _StubIntentAdmission(
        OperatingIntentAdmission(
            status=OperatingIntentAdmissionStatus.ADMITTED,
            grants_intent_authority=True,
            source_revision="operating-intent-revision-1",
            snapshot_digest=f"sha256:{'a' * 64}",
            generation=1,
            owned_object_ids=frozenset({"owned-window"}),
            validated_at=now,
        )
    )

    active = await OntologyChangeWindowEvidenceProvider(
        store,  # type: ignore[arg-type]
        intent_admission=admission,
    ).is_active(target_ref="resource-1", at=now)

    assert active is False


async def test_an_unconfigured_consumer_applies_no_ownership_fence() -> None:
    """Pre-existing generic behavior survives when no intent source is configured."""

    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    store = _open_maintenance_window(now)
    provider = OntologyChangeWindowEvidenceProvider(
        store,  # type: ignore[arg-type]
        intent_admission=StateStoreOperatingIntentAdmissionReader(
            InMemoryStateStore(), expectation=None
        ),
    )

    assert await provider.is_active(target_ref="resource-1", at=now) is True


async def test_change_window_gates_on_the_durable_admission_record() -> None:
    """The deployed wiring reads state, so a stale record must deny end to end."""

    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    store = _open_maintenance_window(now)
    state_store = InMemoryStateStore()
    expectation = OperatingIntentAdmissionExpectation(
        expected_revision="operating-intent-revision-1",
        expected_sha256=f"sha256:{'a' * 64}",
        generation=1,
    )
    await state_store.write_state(
        OPERATING_INTENT_SOURCE_ADMISSION_KEY,
        {
            "schema_version": "1.1.0",
            "status": "admitted",
            "binding_generation": 1,
            "source_revision": "operating-intent-revision-1",
            "snapshot_digest": f"sha256:{'a' * 64}",
            "owned_object_ids": ["window-1"],
            "validated_at": (now - timedelta(seconds=901)).isoformat(),
            "max_age_seconds": 900,
        },
    )
    provider = OntologyChangeWindowEvidenceProvider(
        store,  # type: ignore[arg-type]
        intent_admission=StateStoreOperatingIntentAdmissionReader(
            state_store, expectation=expectation
        ),
    )

    assert await provider.is_active(target_ref="resource-1", at=now) is False
    assert (
        await provider.is_active(target_ref="resource-1", at=now - timedelta(seconds=600))
    ) is True


async def test_change_window_denies_when_the_bound_admission_row_is_missing() -> None:
    """A configured consumer with no record has no current proof, so it denies."""

    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    provider = OntologyChangeWindowEvidenceProvider(
        _open_maintenance_window(now),  # type: ignore[arg-type]
        intent_admission=StateStoreOperatingIntentAdmissionReader(
            InMemoryStateStore(),
            expectation=OperatingIntentAdmissionExpectation(
                expected_revision="operating-intent-revision-1",
                expected_sha256=f"sha256:{'a' * 64}",
                generation=1,
            ),
        ),
    )

    assert await provider.is_active(target_ref="resource-1", at=now) is False


async def test_change_window_denies_an_admission_from_another_rollout_generation() -> None:
    """An old replica's revalidation cannot authorize the rollout that replaced it."""

    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    state_store = InMemoryStateStore()
    await state_store.write_state(
        OPERATING_INTENT_SOURCE_ADMISSION_KEY,
        {
            "schema_version": "1.1.0",
            "status": "admitted",
            "binding_generation": 1,
            "source_revision": "operating-intent-revision-1",
            "snapshot_digest": f"sha256:{'a' * 64}",
            "owned_object_ids": ["window-1"],
            "validated_at": now.isoformat(),
            "max_age_seconds": 900,
        },
    )
    provider = OntologyChangeWindowEvidenceProvider(
        _open_maintenance_window(now),  # type: ignore[arg-type]
        intent_admission=StateStoreOperatingIntentAdmissionReader(
            state_store,
            expectation=OperatingIntentAdmissionExpectation(
                expected_revision="operating-intent-revision-1",
                expected_sha256=f"sha256:{'a' * 64}",
                generation=2,
            ),
        ),
    )

    assert await provider.is_active(target_ref="resource-1", at=now) is False


async def test_ontology_precondition_providers_validate_limits_and_truncation() -> None:
    store = _OntologyQueryStore(OntologyGraphSnapshot(truncated=True))
    with pytest.raises(ValueError, match="query_limit MUST be positive"):
        OntologyOpenActionEvidenceProvider(store, query_limit=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="query_limit MUST be positive"):
        OntologyChangeWindowEvidenceProvider(store, query_limit=0)  # type: ignore[arg-type]

    provider = OntologyChangeWindowEvidenceProvider(store)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timezone-aware"):
        await provider.is_active(target_ref="resource-1", at=datetime(2026, 8, 4, 12))
    assert (
        await provider.is_active(target_ref="resource-1", at=datetime(2026, 8, 4, 12, tzinfo=UTC))
        is False
    )


async def test_ontology_open_actions_ignores_terminal_runs() -> None:
    store = _OntologyQueryStore(
        OntologyGraphSnapshot(
            objects=(
                _object_record(
                    "ActionRun",
                    "run-done",
                    target_ref="resource-1",
                    idempotency_key="other-key",
                    status="SUCCEEDED",
                ),
            )
        )
    )

    conflict = await OntologyOpenActionEvidenceProvider(store).has_conflict(  # type: ignore[arg-type]
        target_ref="resource-1",
        excluding_idempotency_key="retry-key",
    )

    assert conflict is False


async def test_ontology_change_window_handles_status_range_kind_and_timestamp_types() -> None:
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    naive = datetime(2026, 8, 4, 11)
    store = _OntologyQueryStore(
        OntologyGraphSnapshot(
            objects=(
                _object_record(
                    "ChangeWindow",
                    "w-draft",
                    scope_ref="resource-1",
                    status="draft",
                    window_kind="allow",
                    effective_from=now - timedelta(hours=1),
                    effective_to=now + timedelta(hours=1),
                ),
                _object_record(
                    "ChangeWindow",
                    "w-naive-from",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="allow",
                    effective_from=naive,
                    effective_to=now + timedelta(hours=1),
                ),
                _object_record(
                    "ChangeWindow",
                    "w-non-str-to",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="allow",
                    effective_from=now - timedelta(hours=1),
                    effective_to=12345,
                ),
                _object_record(
                    "ChangeWindow",
                    "w-naive-iso",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="allow",
                    effective_from="2026-08-04T11:00:00",
                    effective_to=(now + timedelta(hours=1)).isoformat(),
                ),
                _object_record(
                    "ChangeWindow",
                    "w-expired-range",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="allow",
                    effective_from=now - timedelta(hours=2),
                    effective_to=now - timedelta(hours=1),
                ),
                _object_record(
                    "ChangeWindow",
                    "w-unknown-kind",
                    scope_ref="resource-1",
                    status="active",
                    window_kind="advisory",
                    effective_from=now - timedelta(hours=1),
                    effective_to=now + timedelta(hours=1),
                ),
            )
        )
    )

    active = await OntologyChangeWindowEvidenceProvider(store).is_active(  # type: ignore[arg-type]
        target_ref="resource-1",
        at=now,
    )

    assert active is False
