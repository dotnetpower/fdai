"""ListHilTool + ApproveHilTool contract tests (Wave W1.1 partial).

Every invariant the operator-console doc mandates on the HIL slice is
asserted here:

- Both tools require the Approver role floor.
- list_hil is side_effect_class='read' (no registry mutation).
- approve_hil is side_effect_class='approve' and writes exactly ONE
  ``console.approve_hil`` audit entry per terminal path.
- Verifier re-check: unknown action_kind is rejected.
- no_self_approval invariant: approver.id == submitter_oid is refused.
- Registry idempotency: replaying the same decision returns
  already_recorded=True and still audits the replay; conflicting
  re-decisions surface HilItemAlreadyResolvedError as status='error'.
- The registry is untouched on any rejected input (no state mutation
  when the tool returns error).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fdai.core.conversation import Principal, Role
from fdai.core.conversation.tools import SystemConsoleTool
from fdai.core.conversation.write_tools import (
    ApproveHilTool,
    AuditWriter,
    ListHilTool,
)
from fdai.shared.providers.hil_registry import (
    HilApprovalDecision,
    HilPendingItem,
)
from fdai.shared.providers.testing import (
    InMemoryHilApprovalRegistry,
    InMemoryStateStore,
)


def _principal(*, role: Role = Role.APPROVER, oid: str = "approver-oid") -> Principal:
    return Principal(id=oid, role=role, display_name="Approver")


def _item(**overrides: Any) -> HilPendingItem:
    base = {
        "idempotency_key": "ik-1",
        "approval_id": "appr-1",
        "event_id": "00000000-0000-0000-0000-000000000001",
        "action_id": "00000000-0000-0000-0000-000000000002",
        "action_kind": "remediate.disable-public-access",
        "target_resource_ref": "storage-x",
        "reason": "public access enabled",
        "submitter_oid": "submitter-oid",
        "citing_rule_ids": ("object-storage.public-access-denied",),
        "requested_at": datetime(2026, 7, 7, tzinfo=UTC),
    }
    base.update(overrides)
    return HilPendingItem(**base)  # type: ignore[arg-type]


def _build_registry(items: list[HilPendingItem]) -> InMemoryHilApprovalRegistry:
    reg = InMemoryHilApprovalRegistry()
    reg.seed(items)
    return reg


def _build_approve_tool(
    registry: InMemoryHilApprovalRegistry,
    *,
    known_kinds: set[str] | None = None,
) -> tuple[ApproveHilTool, InMemoryStateStore]:
    store = InMemoryStateStore()
    tool = ApproveHilTool(
        registry=registry,
        audit_writer=AuditWriter(audit_store=store),
        known_action_kinds=(
            frozenset(known_kinds)
            if known_kinds is not None
            else frozenset({"remediate.disable-public-access"})
        ),
    )
    return tool, store


# ---------------------------------------------------------------------------
# ListHilTool
# ---------------------------------------------------------------------------


class TestListHilTool:
    def test_satisfies_protocol(self) -> None:
        tool = ListHilTool(registry=InMemoryHilApprovalRegistry())
        assert isinstance(tool, SystemConsoleTool)

    def test_rbac_floor_is_approver(self) -> None:
        tool = ListHilTool(registry=InMemoryHilApprovalRegistry())
        assert tool.rbac_floor is Role.APPROVER

    def test_side_effect_class_is_read(self) -> None:
        tool = ListHilTool(registry=InMemoryHilApprovalRegistry())
        assert tool.side_effect_class == "read"

    def test_empty_queue_abstains(self) -> None:
        tool = ListHilTool(registry=InMemoryHilApprovalRegistry())
        r = tool.call(arguments={}, principal=_principal())
        assert r.status == "abstain"
        assert r.data["items"] == []

    def test_returns_items_with_full_detail(self) -> None:
        reg = _build_registry([_item(), _item(idempotency_key="ik-2")])
        tool = ListHilTool(registry=reg)
        r = tool.call(arguments={}, principal=_principal())
        assert r.status == "ok"
        assert len(r.data["items"]) == 2
        # Full Approver-visible detail present.
        first = r.data["items"][0]
        assert set(first.keys()) >= {
            "idempotency_key",
            "approval_id",
            "action_kind",
            "target_resource_ref",
            "submitter_oid",
            "citing_rule_ids",
            "requested_at",
        }

    def test_limit_clamped(self) -> None:
        items = [_item(idempotency_key=f"ik-{i}") for i in range(5)]
        reg = _build_registry(items)
        tool = ListHilTool(registry=reg)
        r = tool.call(arguments={"limit": 2}, principal=_principal())
        assert len(r.data["items"]) == 2
        assert r.data["limit"] == 2

    def test_limit_capped_to_100(self) -> None:
        reg = _build_registry([_item()])
        tool = ListHilTool(registry=reg)
        r = tool.call(arguments={"limit": 99999}, principal=_principal())
        assert r.data["limit"] == 100

    def test_limit_min_1(self) -> None:
        reg = _build_registry([_item()])
        tool = ListHilTool(registry=reg)
        r = tool.call(arguments={"limit": 0}, principal=_principal())
        assert r.data["limit"] == 1

    def test_bad_limit_type_errors(self) -> None:
        tool = ListHilTool(registry=InMemoryHilApprovalRegistry())
        r = tool.call(arguments={"limit": "not-an-int"}, principal=_principal())
        assert r.status == "error"

    def test_evidence_refs_cite_hil_keys(self) -> None:
        reg = _build_registry([_item(idempotency_key="ik-42")])
        tool = ListHilTool(registry=reg)
        r = tool.call(arguments={}, principal=_principal())
        assert "hil:ik-42" in r.evidence_refs


# ---------------------------------------------------------------------------
# ApproveHilTool - protocol shape
# ---------------------------------------------------------------------------


class TestApproveHilProtocol:
    def test_satisfies_protocol(self) -> None:
        reg = InMemoryHilApprovalRegistry()
        tool, _ = _build_approve_tool(reg)
        assert isinstance(tool, SystemConsoleTool)

    def test_rbac_floor_is_approver(self) -> None:
        reg = InMemoryHilApprovalRegistry()
        tool, _ = _build_approve_tool(reg)
        assert tool.rbac_floor is Role.APPROVER

    def test_side_effect_class_is_approve(self) -> None:
        reg = InMemoryHilApprovalRegistry()
        tool, _ = _build_approve_tool(reg)
        assert tool.side_effect_class == "approve"


# ---------------------------------------------------------------------------
# ApproveHilTool - argument validation
# ---------------------------------------------------------------------------


class TestApproveHilArguments:
    def test_missing_idempotency_key_errors(self) -> None:
        reg = _build_registry([_item()])
        tool, _ = _build_approve_tool(reg)
        r = tool.call(
            arguments={"decision": "approve"},
            principal=_principal(),
        )
        assert r.status == "error"

    def test_unknown_decision_errors(self) -> None:
        reg = _build_registry([_item()])
        tool, _ = _build_approve_tool(reg)
        r = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "maybe"},
            principal=_principal(),
        )
        assert r.status == "error"

    def test_missing_decision_errors(self) -> None:
        reg = _build_registry([_item()])
        tool, _ = _build_approve_tool(reg)
        r = tool.call(
            arguments={"idempotency_key": "ik-1"},
            principal=_principal(),
        )
        assert r.status == "error"


# ---------------------------------------------------------------------------
# ApproveHilTool - happy path (approve / reject) + idempotency
# ---------------------------------------------------------------------------


class TestApproveHilHappyPath:
    def test_approve_records_decision_and_audits_once(self) -> None:
        reg = _build_registry([_item()])
        tool, store = _build_approve_tool(reg)
        r = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(),
        )
        assert r.status == "ok"
        # Registry recorded exactly one receipt.
        assert len(reg.resolved) == 1
        assert reg.resolved[0].decision is HilApprovalDecision.APPROVE
        # Exactly one audit entry.
        entries = list(store.audit_entries)
        assert len(entries) == 1
        entry = _unwrap(entries[0])
        assert entry["action_kind"] == "console.approve_hil"
        assert entry["decision"] == "approve"
        assert entry["outcome"] == "ok"
        assert entry["submitter_oid"] == "submitter-oid"

    def test_reject_records_decision(self) -> None:
        reg = _build_registry([_item()])
        tool, store = _build_approve_tool(reg)
        r = tool.call(
            arguments={
                "idempotency_key": "ik-1",
                "decision": "reject",
                "justification": "risk too high",
            },
            principal=_principal(),
        )
        assert r.status == "ok"
        assert reg.resolved[0].decision is HilApprovalDecision.REJECT
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["decision"] == "reject"
        assert entry["justification"] == "risk too high"

    def test_workflow_approval_requires_declared_role(self) -> None:
        item = _item(
            action_kind="workflow.approval",
            metadata={
                "decision_route": "workflow",
                "process_id": "process-1",
                "step_id": "approval-1",
                "required_role": "Owner",
            },
        )
        reg = _build_registry([item])
        tool, _ = _build_approve_tool(reg)

        refused = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(role=Role.APPROVER),
        )
        accepted = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(role=Role.OWNER),
        )

        assert refused.status == "error"
        assert accepted.status == "ok"
        assert len(reg.resolved) == 1

    def test_malformed_workflow_approval_metadata_fails_closed(self) -> None:
        item = _item(
            action_kind="workflow.approval",
            metadata={"decision_route": "workflow"},
        )
        reg = _build_registry([item])
        tool, _ = _build_approve_tool(reg)

        result = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(role=Role.OWNER),
        )

        assert result.status == "error"
        assert reg.resolved == ()

    def test_replay_with_same_decision_returns_already_recorded(self) -> None:
        """Mid-flight replay: the caller retries after a transient audit
        write failure. get_pending is bypassed by re-seeding so the tool
        reaches record_decision and hits the idempotency ledger.
        """
        reg = _build_registry([_item()])
        tool, store = _build_approve_tool(reg)
        r1 = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(),
        )
        assert r1.status == "ok"
        # Re-seed the same key (as if the item was reintroduced or the
        # tool's existence check saw a stale snapshot); the registry
        # ledger still holds the prior receipt.
        reg.seed([_item()])
        r2 = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(),
        )
        assert r2.status == "ok"
        assert r2.data["already_recorded"] is True
        assert r2.data["receipt_ref"] == r1.data["receipt_ref"]
        # Two audit entries (one per call - replay is still audited).
        assert len(list(store.audit_entries)) == 2


# ---------------------------------------------------------------------------
# ApproveHilTool - fail-closed paths
# ---------------------------------------------------------------------------


class TestApproveHilFailClosed:
    def test_missing_item_errors_and_writes_no_audit(self) -> None:
        reg = InMemoryHilApprovalRegistry()  # empty
        tool, store = _build_approve_tool(reg)
        r = tool.call(
            arguments={"idempotency_key": "ghost", "decision": "approve"},
            principal=_principal(),
        )
        assert r.status == "error"
        assert list(store.audit_entries) == []
        assert reg.resolved == ()

    def test_verifier_rejects_unknown_action_kind(self) -> None:
        reg = _build_registry([_item(action_kind="ops.mystery-verb")])
        tool, store = _build_approve_tool(reg)
        r = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(),
        )
        assert r.status == "error"
        assert "action_kind" in r.preview
        assert list(store.audit_entries) == []
        assert reg.resolved == ()

    def test_no_self_approval_refused(self) -> None:
        reg = _build_registry([_item()])
        tool, store = _build_approve_tool(reg)
        r = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(oid="submitter-oid"),  # same as submitter
        )
        assert r.status == "error"
        assert "no_self_approval" in r.preview
        assert list(store.audit_entries) == []
        assert reg.resolved == ()

    def test_no_self_approval_refuses_recased_principal(self) -> None:
        reg = _build_registry([_item(submitter_oid="submitter-oid")])
        tool, store = _build_approve_tool(reg)

        result = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(oid="SUBMITTER-OID"),
        )

        assert result.status == "error"
        assert "no_self_approval" in result.preview
        assert list(store.audit_entries) == []
        assert reg.resolved == ()

    def test_missing_submitter_oid_fails_closed(self) -> None:
        # A pending item with no submitter identity cannot have the
        # no_self_approval invariant verified, so the approval MUST fail
        # closed (matches RbacEnforcer.no_self_approval, which raises on an
        # empty submitter_oid rather than letting the approval through).
        reg = _build_registry([_item(submitter_oid="")])
        tool, store = _build_approve_tool(reg)
        r = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(oid="some-approver"),
        )
        assert r.status == "error"
        assert "submitter_oid" in r.preview
        assert list(store.audit_entries) == []
        assert reg.resolved == ()

    def test_conflicting_re_decision_errors_and_audits_the_conflict(self) -> None:
        """The registry raises HilItemAlreadyResolvedError for a conflicting
        decision. The tool audits the conflict so the trail records the
        rejected attempt (distinct from the get_pending 'not pending'
        path which surfaces before the registry sees it)."""
        # Re-seed the item into pending AFTER marking it resolved, so
        # get_pending finds it and the registry write path is reached
        # and hits HilItemAlreadyResolvedError on the conflicting decision.
        reg = _build_registry([_item()])
        reg.mark_resolved(
            "ik-1",
            decision=HilApprovalDecision.APPROVE,
            approver_oid="first-approver",
        )
        reg.seed([_item()])
        tool, store = _build_approve_tool(reg)
        # Same key, DIFFERENT decision -> HilItemAlreadyResolvedError.
        r = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "reject"},
            principal=_principal(),
        )
        assert r.status == "error"
        # The conflict path DOES audit the attempt so the trail is
        # complete.
        assert len(list(store.audit_entries)) == 1
        entry = _unwrap(list(store.audit_entries)[0])
        assert entry["outcome"] == "error"

    def test_already_resolved_item_not_in_pending_errors_without_audit(
        self,
    ) -> None:
        """When an item was fully resolved elsewhere and is NO LONGER
        pending, the tool refuses at the existence check with no audit
        write - operators should route through list_hil first."""
        reg = _build_registry([_item()])
        reg.mark_resolved(
            "ik-1",
            decision=HilApprovalDecision.APPROVE,
            approver_oid="first-approver",
        )
        # Do NOT re-seed the pending item.
        tool, store = _build_approve_tool(reg)
        r = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "reject"},
            principal=_principal(),
        )
        assert r.status == "error"
        assert "no pending item" in r.preview
        assert list(store.audit_entries) == []

    def test_registry_race_between_get_and_record_falls_closed(self) -> None:
        """Simulate a race by seeding the item then removing it just
        before record_decision (via next_error injection) so the tool
        cannot double-write."""
        reg = _build_registry([_item()])
        tool, store = _build_approve_tool(reg)
        # Force record_decision to raise HilItemNotFoundError as if the item
        # disappeared mid-call.
        from fdai.shared.providers.hil_registry import HilItemNotFoundError

        reg.next_error(HilItemNotFoundError("ik-1"))
        r = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(),
        )
        assert r.status == "error"
        assert "disappeared" in r.preview
        # No audit written for the race path (nothing terminal happened).
        assert list(store.audit_entries) == []

    def test_generic_registry_error_bubbles_as_error(self) -> None:
        reg = _build_registry([_item()])
        tool, store = _build_approve_tool(reg)
        from fdai.shared.providers.hil_registry import HilRegistryError

        reg.next_error(HilRegistryError("transient", "network hiccup"))
        r = tool.call(
            arguments={"idempotency_key": "ik-1", "decision": "approve"},
            principal=_principal(),
        )
        assert r.status == "error"
        assert "network hiccup" in r.preview
        assert list(store.audit_entries) == []


# ---------------------------------------------------------------------------
# Registry contract sanity - shipped fake honours the Protocol.
# ---------------------------------------------------------------------------


class TestInMemoryRegistryContract:
    @pytest.mark.asyncio
    async def test_list_pending_orders_newest_first(self) -> None:
        reg = InMemoryHilApprovalRegistry()
        older = _item(
            idempotency_key="old",
            requested_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        newer = _item(
            idempotency_key="new",
            requested_at=datetime(2026, 12, 1, tzinfo=UTC),
        )
        reg.seed([older, newer])
        items = await reg.list_pending()
        assert [i.idempotency_key for i in items] == ["new", "old"]

    @pytest.mark.asyncio
    async def test_get_pending_returns_none_for_unknown(self) -> None:
        reg = InMemoryHilApprovalRegistry()
        assert await reg.get_pending("nope") is None

    @pytest.mark.asyncio
    async def test_resolved_item_disappears_from_list_pending(self) -> None:
        reg = InMemoryHilApprovalRegistry()
        reg.seed([_item()])
        await reg.record_decision(
            idempotency_key="ik-1",
            decision=HilApprovalDecision.APPROVE,
            approver_oid="approver",
        )
        assert await reg.list_pending() == ()

    @pytest.mark.asyncio
    async def test_conflicting_decision_raises_already_resolved(self) -> None:
        from fdai.shared.providers.hil_registry import HilItemAlreadyResolvedError

        reg = InMemoryHilApprovalRegistry()
        reg.seed([_item()])
        await reg.record_decision(
            idempotency_key="ik-1",
            decision=HilApprovalDecision.APPROVE,
            approver_oid="approver",
        )
        with pytest.raises(HilItemAlreadyResolvedError):
            await reg.record_decision(
                idempotency_key="ik-1",
                decision=HilApprovalDecision.REJECT,
                approver_oid="approver",
            )

    @pytest.mark.asyncio
    async def test_record_decision_on_missing_key_raises_not_found(self) -> None:
        from fdai.shared.providers.hil_registry import HilItemNotFoundError

        reg = InMemoryHilApprovalRegistry()  # empty
        with pytest.raises(HilItemNotFoundError):
            await reg.record_decision(
                idempotency_key="ghost",
                decision=HilApprovalDecision.APPROVE,
                approver_oid="approver",
            )

    @pytest.mark.asyncio
    async def test_list_pending_limit_clamped(self) -> None:
        reg = InMemoryHilApprovalRegistry()
        reg.seed([_item(idempotency_key=f"ik-{i}") for i in range(5)])
        items = await reg.list_pending(limit=0)  # gets clamped to >=1
        assert len(items) == 1


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _unwrap(record: Any) -> dict[str, Any]:
    """Mirror ``system_tools._unwrap_audit_record``: return the inner
    entry regardless of hash-chain wrapping."""
    if isinstance(record, dict):
        inner = record.get("entry")
        if isinstance(inner, dict) and ("previous_hash" in record or "entry_hash" in record):
            return inner
        return record
    return dict(record)
