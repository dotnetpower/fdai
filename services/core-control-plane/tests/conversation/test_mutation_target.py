"""Wave W2.3f - MutationTarget field on HilPendingItem + list_hil projection."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.conversation import ListHilTool, Principal, Role
from fdai.core.conversation.write_tools import _project_pending_item
from fdai.shared.providers.hil_registry import (
    HilPendingItem,
    MutationTarget,
)
from fdai.shared.providers.testing.hil_registry import InMemoryHilApprovalRegistry


def _pending(
    *,
    idempotency_key: str = "idem-1",
    approval_id: str = "appr-1",
    mutation_target: MutationTarget | None = None,
) -> HilPendingItem:
    return HilPendingItem(
        idempotency_key=idempotency_key,
        approval_id=approval_id,
        event_id="e-1",
        action_id="a-1",
        action_kind="ops.scale-out",
        target_resource_ref="rg/example/vm-a",
        reason="short",
        submitter_oid="user-sub",
        mutation_target=mutation_target,
    )


# ---------------------------------------------------------------------------
# Dataclass invariants
# ---------------------------------------------------------------------------


def test_mutation_target_defaults_to_none() -> None:
    item = _pending()
    assert item.mutation_target is None


def test_mutation_target_pr_native_round_trip() -> None:
    item = _pending(mutation_target=MutationTarget.PR_NATIVE)
    assert item.mutation_target is MutationTarget.PR_NATIVE
    assert item.mutation_target.value == "pr_native"


def test_mutation_target_direct_api_round_trip() -> None:
    item = _pending(mutation_target=MutationTarget.DIRECT_API)
    assert item.mutation_target is MutationTarget.DIRECT_API
    assert item.mutation_target.value == "direct_api"


def test_mutation_target_enum_matches_execution_path_values() -> None:
    """String values MUST match ExecutionPath so a fork can cast one to
    the other without a lookup table (contract with W2.3d)."""

    from fdai.shared.contracts.models import ExecutionPath

    assert MutationTarget.PR_NATIVE.value == ExecutionPath.PR_NATIVE.value
    assert MutationTarget.DIRECT_API.value == ExecutionPath.DIRECT_API.value


# ---------------------------------------------------------------------------
# _project_pending_item exposes the field
# ---------------------------------------------------------------------------


def test_project_pending_item_includes_mutation_target() -> None:
    item = _pending(mutation_target=MutationTarget.DIRECT_API)
    got = _project_pending_item(item)
    assert got["mutation_target"] == "direct_api"


def test_project_pending_item_mutation_target_none_when_absent() -> None:
    """Backward-compat: rows without the field render ``None`` instead
    of KeyError-ing the caller."""

    item = _pending(mutation_target=None)
    got = _project_pending_item(item)
    assert "mutation_target" in got
    assert got["mutation_target"] is None


def test_project_pending_item_shape_unchanged_otherwise() -> None:
    item = HilPendingItem(
        idempotency_key="idem-2",
        approval_id="appr-2",
        event_id="e-2",
        action_id="a-2",
        action_kind="remediate.tag-add",
        target_resource_ref="rg/x/vm",
        reason="reason",
        submitter_oid="oid",
        citing_rule_ids=("rule-1",),
        requested_at=datetime(2026, 7, 7, tzinfo=UTC),
        correlation_id="corr-1",
        mutation_target=MutationTarget.PR_NATIVE,
    )
    got = _project_pending_item(item)
    # Every documented field is present.
    for key in (
        "idempotency_key",
        "approval_id",
        "event_id",
        "action_id",
        "action_kind",
        "target_resource_ref",
        "reason",
        "submitter_oid",
        "citing_rule_ids",
        "requested_at",
        "correlation_id",
        "mutation_target",
    ):
        assert key in got, f"missing {key!r} in projection"


# ---------------------------------------------------------------------------
# list_hil surfaces the field end-to-end
# ---------------------------------------------------------------------------


def _principal(role: Role = Role.APPROVER) -> Principal:
    return Principal(id="approver-1", role=role)


def test_list_hil_surfaces_mutation_target() -> None:
    registry = InMemoryHilApprovalRegistry()
    registry.seed(
        [
            _pending(
                idempotency_key="idem-pr",
                approval_id="appr-pr",
                mutation_target=MutationTarget.PR_NATIVE,
            ),
            _pending(
                idempotency_key="idem-da",
                approval_id="appr-da",
                mutation_target=MutationTarget.DIRECT_API,
            ),
        ]
    )
    tool = ListHilTool(registry=registry)
    result = tool.call(arguments={}, principal=_principal())
    assert result.status == "ok"
    data = result.data or {}
    items = data["items"]
    by_key = {i["idempotency_key"]: i for i in items}
    assert by_key["idem-pr"]["mutation_target"] == "pr_native"
    assert by_key["idem-da"]["mutation_target"] == "direct_api"


def test_list_hil_absent_mutation_target_is_none() -> None:
    """Pre-W2.3f pending items still list; their mutation_target is None."""

    registry = InMemoryHilApprovalRegistry()
    registry.seed([_pending(mutation_target=None)])
    tool = ListHilTool(registry=registry)
    result = tool.call(arguments={}, principal=_principal())
    assert result.status == "ok"
    (item,) = (result.data or {})["items"]
    assert item["mutation_target"] is None
