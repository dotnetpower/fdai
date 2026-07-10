"""Wave W2.3g - hil_pending_item_from_action + mutation_target_from_execution_path."""

from __future__ import annotations

import pytest

from fdai.shared.contracts.models import Action, ExecutionPath, OntologyActionType
from fdai.shared.providers.hil_registry import (
    HilPendingItem,
    MutationTarget,
    hil_pending_item_from_action,
    mutation_target_from_execution_path,
)


def _action() -> Action:
    return Action.model_validate(
        {
            "schema_version": "1.0.0",
            "action_id": "00000000-0000-0000-0000-000000000010",
            "idempotency_key": "example-action-1",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "action_type": "ops.scale-out",
            "target_resource_ref": "resource:example/rg/vm-a",
            "operation": "scale",
            "params": {},
            "stop_condition": "provider_api_error_streak",
            "rollback_ref": {"kind": "state_forward_only"},
            "blast_radius": {"scope": "resource", "count": 1, "rate_per_minute": 5},
            "mode": "shadow",
            "citing_rules": ["example.rule.x"],
            "created_at": "2026-07-07T00:00:00Z",
        }
    )


def _at(*, execution_path: ExecutionPath | None) -> OntologyActionType:
    from fdai.shared.contracts.models import (
        ActionBlastRadius,
        ActionInterface,
        BlastRadiusComputation,
        BlastRadiusScope,
        Operation,
        PromotionGate,
        RollbackKind,
    )

    return OntologyActionType(
        schema_version="1.0.0",
        name="ops.scale-out",
        version="1.0.0",
        operation=Operation.SCALE,
        interfaces=[ActionInterface.CONTROL_PLANE],
        rollback_contract=RollbackKind.STATE_FORWARD_ONLY,
        irreversible=True,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
        execution_path=execution_path,
    )


# ---------------------------------------------------------------------------
# mutation_target_from_execution_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "execution_path, expected",
    [
        (ExecutionPath.PR_NATIVE, MutationTarget.PR_NATIVE),
        (ExecutionPath.DIRECT_API, MutationTarget.DIRECT_API),
        # R7 collapse: pr_manual shares the pr_native execution surface.
        (ExecutionPath.PR_MANUAL, MutationTarget.PR_NATIVE),
        # tool_call maps to its own target so an approver sees a tool run.
        (ExecutionPath.TOOL_CALL, MutationTarget.TOOL_CALL),
        (None, None),
    ],
)
def test_mutation_target_from_execution_path_mapping(
    execution_path: ExecutionPath | None,
    expected: MutationTarget | None,
) -> None:
    assert mutation_target_from_execution_path(execution_path) is expected


# ---------------------------------------------------------------------------
# hil_pending_item_from_action - happy path
# ---------------------------------------------------------------------------


def test_factory_populates_from_action_fields() -> None:
    item = hil_pending_item_from_action(
        action=_action(),
        action_type=_at(execution_path=ExecutionPath.DIRECT_API),
        approval_id="appr-1",
        submitter_oid="user-sub",
        reason="short reason",
    )
    assert isinstance(item, HilPendingItem)
    assert item.idempotency_key == "example-action-1"
    assert item.approval_id == "appr-1"
    assert item.event_id == "00000000-0000-0000-0000-000000000001"
    assert item.action_id == "00000000-0000-0000-0000-000000000010"
    assert item.action_kind == "ops.scale-out"
    assert item.target_resource_ref == "resource:example/rg/vm-a"
    assert item.reason == "short reason"
    assert item.submitter_oid == "user-sub"
    assert item.citing_rule_ids == ("example.rule.x",)  # copied from action
    assert item.mutation_target is MutationTarget.DIRECT_API


def test_factory_defaults_mutation_target_from_pr_native() -> None:
    item = hil_pending_item_from_action(
        action=_action(),
        action_type=_at(execution_path=ExecutionPath.PR_NATIVE),
        approval_id="a",
        submitter_oid="u",
    )
    assert item.mutation_target is MutationTarget.PR_NATIVE


def test_factory_none_action_type_leaves_mutation_target_none() -> None:
    """Composition-root callers that don't resolve the ActionType still
    get a well-formed record."""

    item = hil_pending_item_from_action(
        action=_action(),
        action_type=None,
        approval_id="a",
        submitter_oid="u",
    )
    assert item.mutation_target is None


def test_factory_action_type_without_execution_path_leaves_target_none() -> None:
    item = hil_pending_item_from_action(
        action=_action(),
        action_type=_at(execution_path=None),
        approval_id="a",
        submitter_oid="u",
    )
    assert item.mutation_target is None


def test_factory_citing_rule_ids_override_wins_over_action() -> None:
    item = hil_pending_item_from_action(
        action=_action(),
        action_type=None,
        approval_id="a",
        submitter_oid="u",
        citing_rule_ids=("override-rule-1", "override-rule-2"),
    )
    assert item.citing_rule_ids == ("override-rule-1", "override-rule-2")


def test_factory_optional_fields_carry_through() -> None:
    from datetime import UTC, datetime

    ts = datetime(2026, 7, 7, 10, 0, 0, tzinfo=UTC)
    item = hil_pending_item_from_action(
        action=_action(),
        action_type=None,
        approval_id="a",
        submitter_oid="u",
        correlation_id="corr-1",
        requested_at=ts,
        action_hash="sha256:abc",
        metadata={"channel": "teams"},
    )
    assert item.correlation_id == "corr-1"
    assert item.requested_at == ts
    assert item.action_hash == "sha256:abc"
    assert item.metadata == {"channel": "teams"}


# ---------------------------------------------------------------------------
# Fail-closed input validation
# ---------------------------------------------------------------------------


def test_factory_empty_approval_id_rejected() -> None:
    with pytest.raises(ValueError, match="approval_id"):
        hil_pending_item_from_action(
            action=_action(),
            action_type=None,
            approval_id="",
            submitter_oid="u",
        )


def test_factory_empty_submitter_oid_rejected() -> None:
    with pytest.raises(ValueError, match="submitter_oid"):
        hil_pending_item_from_action(
            action=_action(),
            action_type=None,
            approval_id="a",
            submitter_oid="",
        )


# ---------------------------------------------------------------------------
# Registry round-trip
# ---------------------------------------------------------------------------


def test_factory_item_seeds_registry_intact() -> None:
    """A hil_pending_item_from_action item slots directly into the
    registry contract."""

    import asyncio

    from fdai.shared.providers.testing.hil_registry import (
        InMemoryHilApprovalRegistry,
    )

    item = hil_pending_item_from_action(
        action=_action(),
        action_type=_at(execution_path=ExecutionPath.DIRECT_API),
        approval_id="appr-1",
        submitter_oid="user-sub",
    )
    reg = InMemoryHilApprovalRegistry()
    reg.seed([item])

    async def _run() -> None:
        got = await reg.get_pending(item.idempotency_key)
        assert got is not None
        assert got.mutation_target is MutationTarget.DIRECT_API

    asyncio.run(_run())
