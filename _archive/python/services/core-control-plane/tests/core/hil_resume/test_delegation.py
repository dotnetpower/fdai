"""Tests for the HIL delegation gate.

Locks the fail-closed order and the delegation modes that back Scenario A
(operator A approves a HIL item surfaced to operator B, same authority).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fdai.core.executor import ExecutionResult, ExecutorOutcome
from fdai.core.executor.direct_api import (
    DirectApiExecutionOutcome,
    DirectApiExecutionResult,
)
from fdai.core.executor.tool_call import (
    ToolCallExecutionOutcome,
    ToolCallExecutionResult,
)
from fdai.core.hil_resume.approval_profile_gate import (
    MALFORMED,
    UNAVAILABLE,
    HilApprovalProfileMixin,
    approval_profile_audit_detail,
    parked_approval_profile,
)
from fdai.core.hil_resume.delegation import (
    DelegationDecision,
    DelegationMode,
    DelegationRefusal,
    evaluate_hil_delegation,
)
from fdai.core.hil_resume.dispatch import HilDispatchMixin
from fdai.core.hil_resume.results import ResolveOutcome
from fdai.core.hil_resume.rule_source import resolve_parked_rule
from fdai.core.ontology_platform.evidence_conflict import EvidenceConflictStatus
from fdai.core.risk_gate.approval_profile import (
    ApprovalProfileDecision,
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
)
from fdai.shared.contracts.models import (
    Action,
    ActionInterface,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    Category,
    CheckLogic,
    CheckLogicKind,
    ExecutionPath,
    Mode,
    OntologyActionType,
    Operation,
    PromotionGate,
    Provenance,
    Redistribution,
    Remediation,
    RollbackKind,
    RollbackRef,
    Rule,
    RuleSource,
    Severity,
    StopConditionKind,
    WorkflowActionRef,
)
from fdai.shared.providers.hil_channel import HilDecision
from fdai.shared.providers.testing import InMemoryStateStore


def _eval(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        approver_oid="user-a",
        submitter_oid="system",
        approver_can_approve_hil=True,
        assignee_oid=None,
    )
    base.update(kw)
    return evaluate_hil_delegation(**base)  # type: ignore[arg-type]


class TestRefusals:
    def test_blank_approver(self) -> None:
        d = _eval(approver_oid="  ")
        assert not d.allowed
        assert d.refusal is DelegationRefusal.BLANK_APPROVER

    def test_unknown_submitter(self) -> None:
        d = _eval(submitter_oid="")
        assert not d.allowed
        assert d.refusal is DelegationRefusal.UNKNOWN_SUBMITTER

    def test_self_approval(self) -> None:
        d = _eval(approver_oid="user-a", submitter_oid="user-a")
        assert not d.allowed
        assert d.refusal is DelegationRefusal.SELF_APPROVAL

    def test_missing_capability(self) -> None:
        d = _eval(approver_can_approve_hil=False)
        assert not d.allowed
        assert d.refusal is DelegationRefusal.MISSING_CAPABILITY

    def test_self_approval_precedes_capability(self) -> None:
        # A self-approver without the capability is refused for self-approval
        # (the harder invariant), not the softer rbac reason.
        d = _eval(approver_oid="x", submitter_oid="x", approver_can_approve_hil=False)
        assert d.refusal is DelegationRefusal.SELF_APPROVAL


class TestAllowed:
    def test_role_scoped_when_no_assignee(self) -> None:
        d = _eval(assignee_oid=None)
        assert d.allowed
        assert d.mode is DelegationMode.ROLE_SCOPED
        assert d.refusal is None
        assert not d.is_delegated

    def test_direct_when_approver_is_assignee(self) -> None:
        d = _eval(approver_oid="user-b", assignee_oid="user-b")
        assert d.allowed
        assert d.mode is DelegationMode.DIRECT
        assert not d.is_delegated

    def test_delegated_when_approver_differs_from_assignee(self) -> None:
        # Scenario A: HIL surfaced to user-b, approved by user-a (same authority).
        d = _eval(approver_oid="user-a", submitter_oid="system", assignee_oid="user-b")
        assert d.allowed
        assert d.mode is DelegationMode.DELEGATED
        assert d.is_delegated

    def test_delegation_still_refuses_self_approval(self) -> None:
        # Even with an assignee, the approver may never be the submitter.
        d = _eval(approver_oid="user-a", submitter_oid="user-a", assignee_oid="user-b")
        assert not d.allowed
        assert d.refusal is DelegationRefusal.SELF_APPROVAL

    def test_whitespace_is_trimmed(self) -> None:
        d = _eval(approver_oid=" user-a ", assignee_oid=" user-a ")
        assert d.allowed
        assert d.mode is DelegationMode.DIRECT


_OID = "00000000-0000-0000-0000-0000000000ab"
_OTHER = "00000000-0000-0000-0000-0000000000cd"


def _alternating_case(value: str) -> str:
    return "".join(c.upper() if index % 2 else c for index, c in enumerate(value))


@pytest.mark.parametrize(
    "recase",
    [str.upper, _alternating_case, lambda value: f"  {value.upper()}  "],
    ids=["upper", "alternating", "upper-with-padding"],
)
def test_recasing_an_object_id_is_not_a_second_person(recase: object) -> None:
    """An Entra object id is a GUID, and a GUID is the same value however it is
    cased. Comparing raw strings let one person appear as two and approve their
    own submission - the exact thing this floor exists to prevent.
    """
    decision = evaluate_hil_delegation(
        approver_oid=recase(_OID),  # type: ignore[operator]
        submitter_oid=_OID,
        approver_can_approve_hil=True,
    )

    assert decision.allowed is False
    assert decision.refusal is DelegationRefusal.SELF_APPROVAL


def test_a_recased_assignee_is_still_a_direct_approval() -> None:
    """Casing must not turn the assignee into someone else either; that would
    record a direct approval as a delegation and misstate the audit.
    """
    decision = evaluate_hil_delegation(
        approver_oid=_OTHER.upper(),
        submitter_oid=_OID,
        assignee_oid=_OTHER,
        approver_can_approve_hil=True,
    )

    assert decision.allowed is True
    assert decision.mode is DelegationMode.DIRECT


def test_two_genuinely_different_operators_are_still_allowed() -> None:
    decision = evaluate_hil_delegation(
        approver_oid=_OTHER,
        submitter_oid=_OID,
        approver_can_approve_hil=True,
    )

    assert decision.allowed is True


def _sample_action(*, workflow: bool = False) -> Action:
    return Action(
        schema_version="1.0.0",
        action_id="00000000-0000-0000-0000-000000000010",  # type: ignore[arg-type]
        idempotency_key="rule-source-idem",
        event_id="00000000-0000-0000-0000-000000000011",  # type: ignore[arg-type]
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/stg1",
        operation=Operation.TAG,
        params={"tag_value": "team-a"},
        stop_condition="provider_api_error_streak",
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=3,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.PR_REVERT, reference="pr-99"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1, rate_per_minute=5),
        mode=Mode.SHADOW,
        citing_rules=["object-storage.owner-tag.required"],
        created_at="2026-07-05T08:00:00Z",  # type: ignore[arg-type]
        workflow_action=(
            WorkflowActionRef(
                process_id="proc-1",
                step_id="step-1",
                proposal_ref="prop-1",
                attempt=1,
            )
            if workflow
            else None
        ),
    )


def _sample_rule(
    *,
    rule_id: str = "operator.request.remediate.tag-add",
    remediates: str = "remediate.tag-add",
    reference: str = "server-validated-operator-request",
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.CONFIG_DRIFT,
        resource_type="object-storage",
        check_logic=CheckLogic(
            kind=CheckLogicKind.REGO,
            reference=reference,
        ),
        remediation=Remediation(
            template_ref="remediation/object_storage/tag_owner.tftpl",
            cost_impact_monthly_usd=0,
        ),
        remediates=remediates,
        parameters={"tag_name": "owner", "tag_value": "unknown"},
        provenance=Provenance(
            source_url="https://example.com/rules/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def test_resolve_parked_rule_accepts_catalog_or_valid_operator_rule_only() -> None:
    action = _sample_action()
    catalog_rule = _sample_rule(
        rule_id="object-storage.owner-tag.required",
        reference="policies/object_storage/owner_tag_required.rego",
    )
    assert (
        resolve_parked_rule(
            {"rule_id": catalog_rule.id},
            action=action,
            rules_by_id={catalog_rule.id: catalog_rule},
        )
        == catalog_rule
    )
    assert resolve_parked_rule({"rule_id": "unknown.rule"}, action=action, rules_by_id={}) is None
    assert (
        resolve_parked_rule(
            {"rule_id": "operator.request.remediate.tag-add", "rule": {"invalid": True}},
            action=action,
            rules_by_id={},
        )
        is None
    )
    assert (
        resolve_parked_rule(
            {
                "rule_id": "operator.request.remediate.tag-add",
                "rule": _sample_rule(rule_id="other.rule").model_dump(mode="json"),
            },
            action=action,
            rules_by_id={},
        )
        is None
    )
    assert (
        resolve_parked_rule(
            {
                "rule_id": "operator.request.remediate.tag-add",
                "rule": _sample_rule(remediates="remediate.other").model_dump(mode="json"),
            },
            action=action,
            rules_by_id={},
        )
        is None
    )
    assert (
        resolve_parked_rule(
            {
                "rule_id": "operator.request.remediate.tag-add",
                "rule": _sample_rule(reference="custom-reference").model_dump(mode="json"),
            },
            action=action,
            rules_by_id={},
        )
        is None
    )
    valid_operator_rule = _sample_rule()
    resolved = resolve_parked_rule(
        {
            "rule_id": "operator.request.remediate.tag-add",
            "rule": valid_operator_rule.model_dump(mode="json"),
        },
        action=action,
        rules_by_id={},
    )
    assert resolved == valid_operator_rule


def _profile_revision(
    operator: str = "operator@example.com",
    *,
    revision_id: str = "profile-r1",
) -> ApprovalProfileRevision:
    payload: dict[str, object] = {
        "revision_id": revision_id,
        "approval_profile": "single-operator-production",
        "executor_principal": "thor-runtime-executor",
        "effective_from": "2026-10-05T00:00:00+00:00",
        "operator_principal": operator,
    }
    return ApprovalProfileRevision(
        revision_id=revision_id,
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal="thor-runtime-executor",
        policy_digest=approval_profile_policy_digest(payload),
        effective_from=datetime(2026, 10, 5, tzinfo=UTC),
        operator_principal=operator,
    )


class _ProfileHarness(HilApprovalProfileMixin):
    def __init__(self, store: InMemoryStateStore) -> None:
        self._approval_profile = None
        self._approval_profile_bootstrap = None
        self._approval_profile_signature_verifier = None
        self._state_store = store
        self.audits: list[dict[str, Any]] = []

    async def _audit(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Any,
    ) -> None:
        self.audits.append(
            {
                "action_kind": action_kind,
                "idempotency_key": idempotency_key,
                "approval_id": approval_id,
                "correlation_id": correlation_id,
                "detail": dict(detail),
            }
        )


async def test_approval_profile_gate_handles_malformed_binding_and_refusal_fallbacks() -> None:
    store = InMemoryStateStore()
    profile, reason = await parked_approval_profile(
        {"approval_profile": {"approval_profile": "invalid"}},
        None,
        None,
        store,
    )
    assert profile is None
    assert reason == MALFORMED

    profile_none, reason_none = await parked_approval_profile(
        {"approval_profile": "not-a-mapping"},
        None,
        None,
        store,
    )
    assert profile_none is None
    assert reason_none is None

    rev = _profile_revision()
    unauth_profile, unauth_reason = await parked_approval_profile(
        {"approval_profile": rev.as_audit_dict()},
        None,
        None,
        store,
    )
    assert unauth_profile is None
    assert unauth_reason == UNAVAILABLE

    assert approval_profile_audit_detail(None) == {}
    decision_detail = approval_profile_audit_detail(
        ApprovalProfileDecision(
            allowed=True,
            approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
            original_quorum=2,
            effective_quorum=1,
            operator_principal="operator@example.com",
            self_review=True,
        )
    )
    assert decision_detail["approval_profile"] == "single-operator-production"

    base_mixin = HilApprovalProfileMixin()
    with pytest.raises(NotImplementedError):
        await base_mixin._audit(
            action_kind="hil.test",
            idempotency_key="idem",
            approval_id="aid",
            correlation_id="cid",
            detail={},
        )

    harness = _ProfileHarness(store)
    harness.bind_approval_profile(rev)
    harness.bind_approval_profile(rev)
    with pytest.raises(RuntimeError, match="approval profile is already bound"):
        harness.bind_approval_profile(
            _profile_revision("other@example.com", revision_id="profile-r2")
        )

    bound_profile, bound_reason = await harness._parked_approval_profile(
        {"approval_profile": rev.as_audit_dict()}
    )
    assert bound_profile == rev
    assert bound_reason is None

    refused = await harness._refuse_by_profile(
        DelegationDecision(
            allowed=False,
            mode=None,
            refusal=None,
            approval_profile=None,
        ),
        idem="idem-1",
        approval_id="aid-1",
        correlation_id="cid-1",
        approver_oid="user-a",
        assignee_oid="user-c",
    )
    assert refused.outcome is ResolveOutcome.DECISION_REFUSED
    assert refused.reason == "approval_refused"
    assert harness.audits[-1]["detail"]["reason"] == "approval_refused"


def _sample_action_type(
    *,
    name: str = "remediate.tag-add",
    execution_path: ExecutionPath | None = None,
    semantic_refs: list[str] | None = None,
) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name=name,
        version="1.0.0",
        operation=Operation.TAG,
        interfaces=[ActionInterface.CONTROL_PLANE, ActionInterface.IDEMPOTENT_BY_KEY],
        rollback_contract=RollbackKind.PR_REVERT,
        promotion_gate=PromotionGate(
            min_shadow_days=14,
            min_samples=100,
            min_accuracy=0.95,
            max_policy_escapes=0,
        ),
        execution_path=execution_path,
        required_evidence_semantic_refs=semantic_refs or [],
    )


class _DispatchHarness(HilDispatchMixin):
    def __init__(self, store: InMemoryStateStore) -> None:
        self._action_types_by_name = {}
        self._direct_api_executor = None
        self._evidence_conflict_reader = None
        self._executor = MagicMock()
        self._executor.execute = AsyncMock(
            return_value=ExecutionResult(
                action_id="00000000-0000-0000-0000-000000000010",
                outcome=ExecutorOutcome.PUBLISHED,
                mode=Mode.SHADOW,
            )
        )
        self._pre_dispatch_kinetic_safety_writer = None
        self._safeguard_lifecycle_coordinator = None
        self._state_store = store
        self._tool_executor = None

    def _audit_entry(
        self,
        *,
        action_kind: str,
        idempotency_key: str,
        approval_id: str,
        correlation_id: str,
        detail: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "actor": "test",
            "action_kind": action_kind,
            "idempotency_key": idempotency_key,
            "approval_id": approval_id,
            "correlation_id": correlation_id,
            **dict(detail),
        }


async def test_dispatch_mixin_covers_conflict_safeguard_and_executor_routing_branches() -> None:
    with pytest.raises(NotImplementedError):
        HilDispatchMixin()._audit_entry(
            action_kind="hil.test",
            idempotency_key="idem",
            approval_id="aid",
            correlation_id="cid",
            detail={},
        )

    store = InMemoryStateStore()
    harness = _DispatchHarness(store)
    action = _sample_action(workflow=True)
    rule = _sample_rule(
        rule_id="object-storage.owner-tag.required",
        reference="policies/object_storage/owner_tag_required.rego",
    )
    action_type = _sample_action_type(semantic_refs=["resource.power_state"])
    harness._action_types_by_name = {action.action_type: action_type}

    failing_reader = MagicMock()
    failing_reader.active_for = AsyncMock(side_effect=RuntimeError("reader failed"))
    harness._evidence_conflict_reader = failing_reader
    res_err = await harness._dispatch(action=action, rule=rule, correlation_id="cid-1")
    assert res_err.outcome is ExecutorOutcome.REJECTED_INVARIANT
    assert res_err.reason == "evidence-conflict current state is unavailable"

    conflict_obj = MagicMock()
    conflict_obj.status = EvidenceConflictStatus.ACTIVE
    conflict_obj.target_ref = action.target_resource_ref
    conflict_obj.semantic_refs = ("resource.power_state",)
    conflict_obj.expires_at = datetime(2099, 1, 1, tzinfo=UTC)
    active_reader = MagicMock()
    active_reader.active_for = AsyncMock(return_value=(conflict_obj,))
    harness._evidence_conflict_reader = active_reader
    res_conflict = await harness._dispatch(action=action, rule=rule, correlation_id="cid-2")
    assert res_conflict.outcome is ExecutorOutcome.REJECTED_INVARIANT
    assert res_conflict.reason == "evidence conflict requires shadow-only: active_conflict"

    clear_reader = MagicMock()
    clear_reader.active_for = AsyncMock(return_value=())
    harness._evidence_conflict_reader = clear_reader
    harness._safeguard_lifecycle_coordinator = None
    res_no_coord = await harness._dispatch(action=action, rule=rule, correlation_id="cid-3")
    assert res_no_coord.outcome is ExecutorOutcome.REJECTED_INVARIANT
    assert res_no_coord.reason == "workflow safeguard pre-bundle coordinator is unavailable"

    coord = MagicMock()
    coord.prepare_pre_bundle_commitment = AsyncMock(side_effect=ValueError("bad bundle"))
    harness._safeguard_lifecycle_coordinator = coord
    res_coord_err = await harness._dispatch(action=action, rule=rule, correlation_id="cid-4")
    assert res_coord_err.outcome is ExecutorOutcome.REJECTED_INVARIANT
    assert res_coord_err.reason == "workflow safeguard pre-bundle commitment failed: ValueError"

    coord.prepare_pre_bundle_commitment = AsyncMock(return_value=None)
    direct_exec = MagicMock()
    direct_exec.execute = AsyncMock(
        return_value=DirectApiExecutionResult(
            action_id=str(action.action_id),
            outcome=DirectApiExecutionOutcome.DISPATCHED,
            mode=Mode.SHADOW,
        )
    )
    harness._direct_api_executor = direct_exec
    harness._action_types_by_name = {
        action.action_type: _sample_action_type(execution_path=ExecutionPath.DIRECT_API)
    }
    res_direct = await harness._dispatch(action=action, rule=rule, correlation_id="cid-5")
    assert res_direct.outcome is DirectApiExecutionOutcome.DISPATCHED

    tool_exec = MagicMock()
    tool_exec.execute = AsyncMock(
        return_value=ToolCallExecutionResult(
            action_id=str(action.action_id),
            outcome=ToolCallExecutionOutcome.DISPATCHED,
            mode=Mode.SHADOW,
        )
    )
    harness._tool_executor = tool_exec
    harness._action_types_by_name = {
        action.action_type: _sample_action_type(execution_path=ExecutionPath.TOOL_CALL)
    }
    res_tool = await harness._dispatch(
        action=_sample_action(workflow=False),
        rule=rule,
        correlation_id="cid-6",
    )
    assert res_tool.outcome is ToolCallExecutionOutcome.DISPATCHED

    harness._action_types_by_name = {action.action_type: _sample_action_type(execution_path=None)}
    res_pr_default = await harness._dispatch(action=action, rule=rule, correlation_id="cid-7")
    assert res_pr_default.outcome is ExecutorOutcome.PUBLISHED

    harness._action_types_by_name = {"other.action": _sample_action_type(name="other.action")}
    res_unmapped = await harness._dispatch(action=action, rule=rule, correlation_id="cid-8")
    assert res_unmapped.outcome is ExecutorOutcome.PUBLISHED


async def test_mark_resolved_covers_revision_validation_and_cas_failure_paths() -> None:
    store = InMemoryStateStore()
    harness = _DispatchHarness(store)
    with pytest.raises(ValueError, match="parked approval revision MUST be a non-negative integer"):
        await harness._mark_resolved(
            {"approval_id": "aid-bad-rev", "revision": -1},
            decision=HilDecision.REJECT,
            approver_oid="approver-a",
            action_kind="hil.rejected",
            detail={},
        )

    assert (
        await harness._mark_resolved(
            {"approval_id": "aid-missing", "revision": 1, "action": None},
            decision=HilDecision.REJECT,
            approver_oid="approver-a",
            action_kind="hil.rejected",
            detail={},
        )
        is False
    )

    await store.write_state(
        "hil_park:aid-tampered-cas",
        {
            "approval_id": "aid-tampered-cas",
            "status": "pending",
            "revision": 1,
            "action_hash": "changed-hash",
            "action": None,
        },
    )
    assert (
        await harness._mark_resolved(
            {
                "approval_id": "aid-tampered-cas",
                "status": "pending",
                "revision": 0,
                "action_hash": "original-hash",
                "action": None,
            },
            decision=HilDecision.REJECT,
            approver_oid="approver-a",
            action_kind="hil.rejected",
            detail={},
        )
        is False
    )

    always_false_store = MagicMock()
    always_false_store.compare_and_set_state_with_audit = AsyncMock(return_value=False)
    always_false_store.read_state = AsyncMock(
        return_value={
            "approval_id": "aid-exhaust",
            "status": "pending",
            "revision": 1,
            "action_hash": "same-hash",
            "action": None,
        }
    )
    harness._state_store = always_false_store
    assert (
        await harness._mark_resolved(
            {
                "approval_id": "aid-exhaust",
                "status": "pending",
                "revision": 0,
                "action_hash": "same-hash",
                "action": None,
            },
            decision=HilDecision.REJECT,
            approver_oid="approver-a",
            action_kind="hil.rejected",
            detail={},
        )
        is False
    )
    assert always_false_store.compare_and_set_state_with_audit.await_count == 3
