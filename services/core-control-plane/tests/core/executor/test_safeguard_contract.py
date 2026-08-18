"""The seven safeguards are one contract, not four similar implementations.

FDAI-CONST-007 requires every safeguard on every state-changing path. The failure this
file guards against is drift: a new execution path, or a refactor of one existing path,
that quietly proves fewer safeguards than its siblings.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from fdai.core.executor.safeguards import (
    AUDIT_INTENT,
    BLAST_RADIUS,
    DRY_RUN_RECEIPT,
    IDEMPOTENCY_KEY,
    REQUIRED_SAFEGUARDS,
    ROLLBACK,
    SEVEN_SAFEGUARDS,
    STOP_CONDITION,
    TARGET_LOCK,
    SafeguardReceipt,
    SafeguardRefusal,
    evaluate_pre_dispatch,
    idempotency_lock_key,
    resource_lock_key,
)
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    Mode,
    Operation,
    RollbackRef,
)
from fdai.shared.contracts.models.enums import (
    BlastRadiusScope,
    ExecutionPath,
    RollbackKind,
    StopConditionKind,
)

PLAN_DIGEST = "0" * 64
_BAD_ROLLBACK = RollbackRef.model_construct(kind=None, reference=None)


def _action(**overrides: Any) -> Action:
    base = Action(
        schema_version="1.0.0",
        action_id=UUID("00000000-0000-0000-0000-000000000010"),
        event_id=UUID("00000000-0000-0000-0000-000000000011"),
        action_type="ops.restart-service",
        target_resource_ref="resource:example/rg/vm1",
        operation=Operation.RESTART,
        params={"cooldown_seconds": 30},
        mode=Mode.SHADOW,
        idempotency_key="example-idem",
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(kind=StopConditionKind.PROVIDER_API_ERROR_STREAK, count=3)
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rb-99"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        citing_rules=["ops.restart-service"],
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
    )
    if not overrides:
        return base
    return Action.model_construct(**{**base.__dict__, **overrides})


def test_required_safeguards_cover_every_execution_path() -> None:
    assert set(REQUIRED_SAFEGUARDS) == set(ExecutionPath)
    assert len(SEVEN_SAFEGUARDS) == 7
    assert len(set(SEVEN_SAFEGUARDS)) == 7
    for path, declared in REQUIRED_SAFEGUARDS.items():
        assert set(declared) == set(SEVEN_SAFEGUARDS), path


@pytest.mark.parametrize("path", list(ExecutionPath))
def test_a_complete_action_receives_a_receipt_on_every_path(path: ExecutionPath) -> None:
    receipt = evaluate_pre_dispatch(
        _action(),
        execution_path=path,
        plan_digest=PLAN_DIGEST,
        plan_kind="test_plan",
    )

    assert isinstance(receipt, SafeguardReceipt)
    assert receipt.execution_path is path
    assert receipt.dry_run_receipt.startswith("sha256:")
    assert receipt.idempotency_lock_key == idempotency_lock_key("example-idem")
    assert receipt.resource_lock_key == resource_lock_key("resource:example/rg/vm1")


@pytest.mark.parametrize("path", list(ExecutionPath))
@pytest.mark.parametrize(
    ("overrides", "plan_digest", "safeguard"),
    [
        ({"stop_condition": "   "}, PLAN_DIGEST, STOP_CONDITION),
        ({"rollback_ref": _BAD_ROLLBACK}, PLAN_DIGEST, ROLLBACK),
        ({"blast_radius": None}, PLAN_DIGEST, BLAST_RADIUS),
        ({"citing_rules": []}, PLAN_DIGEST, AUDIT_INTENT),
        ({"idempotency_key": "  "}, PLAN_DIGEST, IDEMPOTENCY_KEY),
        ({"target_resource_ref": ""}, PLAN_DIGEST, TARGET_LOCK),
        ({}, "   ", DRY_RUN_RECEIPT),
    ],
)
def test_pre_dispatch_refuses_each_missing_safeguard(
    path: ExecutionPath,
    overrides: dict[str, Any],
    plan_digest: str,
    safeguard: str,
) -> None:
    refusal = evaluate_pre_dispatch(
        _action(**overrides),
        execution_path=path,
        plan_digest=plan_digest,
        plan_kind="test_plan",
    )

    assert isinstance(refusal, SafeguardRefusal)
    assert refusal.safeguard == safeguard
    assert refusal.reason


def test_the_dry_run_receipt_is_deterministic_and_input_sensitive() -> None:
    def receipt_for(**kwargs: Any) -> str:
        computed = evaluate_pre_dispatch(
            kwargs.pop("action", _action()),
            execution_path=kwargs.pop("execution_path", ExecutionPath.DIRECT_API),
            plan_digest=kwargs.pop("plan_digest", PLAN_DIGEST),
            plan_kind=kwargs.pop("plan_kind", "test_plan"),
        )
        assert isinstance(computed, SafeguardReceipt)
        return computed.dry_run_receipt

    baseline = receipt_for()

    assert receipt_for() == baseline
    assert receipt_for(plan_digest="1" * 64) != baseline
    assert receipt_for(plan_kind="other_plan") != baseline
    assert receipt_for(execution_path=ExecutionPath.TOOL_CALL) != baseline
    assert receipt_for(action=_action(params={"region": "krc"})) != baseline


def test_lock_keys_are_derived_only_by_the_shared_contract() -> None:
    assert idempotency_lock_key("a") != idempotency_lock_key("b")
    assert idempotency_lock_key("a").startswith("fdai:idempotency:")
    assert resource_lock_key("resource:x") == "fdai:resource:resource:x"
    # The two namespaces never collide, so an idempotency key equal to a resource ref
    # cannot serialize unrelated work.
    assert idempotency_lock_key("resource:x") != resource_lock_key("resource:x")
