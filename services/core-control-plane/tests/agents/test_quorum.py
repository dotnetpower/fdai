"""Irreversible-action approval quorum plumbing (Forseti -> Thor -> Var).

Closes the section-5 gap: Forseti now stamps quorum_required on the
verdict and Thor propagates it onto the ActionRun instead of hard-coding
1, so Var's existing two-approver enforcement actually receives a quorum
of 2 for an irreversible action.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest
from fdai.agents._framework.action_semantics import (
    DEFAULT_QUORUM,
    IRREVERSIBLE_QUORUM,
    ActionSemanticsCatalog,
    is_irreversible,
    outcome_result,
    quorum_for,
)
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.var import Var
from fdai.core.risk_gate.approval_profile import (
    ApprovalProfileKind,
    ApprovalProfileRevision,
    approval_profile_policy_digest,
)
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]
_OPERATOR = "operator@example.com"
_EXECUTOR = "thor-runtime-executor"


def _approval_profile() -> ApprovalProfileRevision:
    payload: dict[str, object] = {
        "revision_id": "approval-profile-r1",
        "approval_profile": "single-operator-production",
        "executor_principal": _EXECUTOR,
        "effective_from": "2026-10-05T00:00:00+00:00",
        "operator_principal": _OPERATOR,
    }
    return ApprovalProfileRevision(
        revision_id=str(payload["revision_id"]),
        approval_profile=ApprovalProfileKind.SINGLE_OPERATOR_PRODUCTION,
        executor_principal=str(payload["executor_principal"]),
        policy_digest=approval_profile_policy_digest(payload),
        effective_from=datetime.fromisoformat(str(payload["effective_from"])),
        operator_principal=str(payload["operator_principal"]),
    )


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _thor_action_run(**overrides: object) -> dict[str, object]:
    correlation_id = str(overrides.get("correlation_id") or "c-var")
    payload: dict[str, object] = {
        "producer_principal": "Thor",
        "correlation_id": correlation_id,
        "idempotency_key": f"action-run:{correlation_id}",
        "action_type": "remediate.delete-storage",
        "resource_id": "resource-1",
        "state": "hil_pending",
        "quorum_required": 2,
    }
    payload.update(overrides)
    return payload


class TestActionSemantics:
    def test_missing_catalog_fails_closed_for_action_names(self) -> None:
        assert is_irreversible("remediate.delete-storage")
        assert is_irreversible("ops.destroy-cluster")
        assert is_irreversible("ops.restart-service")
        assert is_irreversible("config.remove-tag")

    def test_quorum_for(self) -> None:
        assert quorum_for("remediate.delete-storage") == IRREVERSIBLE_QUORUM == 2
        assert quorum_for("ops.restart-service") == IRREVERSIBLE_QUORUM

    def test_catalog_can_prove_reversible_action(self) -> None:
        action_types = load_action_type_catalog(
            REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=PackageResourceSchemaRegistry(),
        )
        semantics = ActionSemanticsCatalog.from_action_types(action_types)

        assert not is_irreversible("ops.start-vm", semantics)
        assert quorum_for("ops.start-vm", semantics) == DEFAULT_QUORUM == 1

    def test_outcome_result_maps_terminal_states(self) -> None:
        assert outcome_result("succeeded") == "success"
        assert outcome_result("failed") == "failure"
        assert outcome_result("rolled_back") == "rollback"
        assert outcome_result("REVERTED") == "rollback"  # case-insensitive

    def test_outcome_result_none_for_intermediate_states(self) -> None:
        assert outcome_result("executing") is None
        assert outcome_result("hil_pending") is None
        assert outcome_result("rejected") is None  # non-execution terminal
        assert outcome_result("") is None

    def test_outcome_result_covers_every_terminal_state(self) -> None:
        """Exhaustiveness guard (#6): every terminal ActionRunState is either
        an outcome-defining state (outcome_result maps it) or an explicit
        non-execution terminal. A new terminal state added upstream without
        updating _TERMINAL_OUTCOME trips this test, rather than silently
        never being learned by the discovery loop."""
        from fdai.agents.thor import _TERMINAL_STATES, ActionRunState

        non_execution = {
            ActionRunState.REJECTED,
            ActionRunState.DENY_DROPPED,
            ActionRunState.ROLLBACK_REFUSED,
        }
        for state in _TERMINAL_STATES:
            learnable = outcome_result(str(state)) is not None
            assert learnable or state in non_execution, (
                f"terminal state {state!r} is neither learnable nor an "
                "explicit non-execution terminal - classify it in "
                "_TERMINAL_OUTCOME or extend the non_execution set"
            )


class TestForsetiStampsQuorum:
    def test_irreversible_action_gets_quorum_two(self) -> None:
        f = Forseti(bus=None)
        verdict = asyncio.run(
            f.judge({"action_type": "remediate.delete-storage", "correlation_id": "c-1"})
        )
        assert verdict is not None
        assert verdict["quorum_required"] == 2

    def test_missing_catalog_requires_irreversible_quorum(self) -> None:
        f = Forseti(bus=None)
        verdict = asyncio.run(
            f.judge({"action_type": "ops.restart-service", "correlation_id": "c-2"})
        )
        assert verdict is not None
        assert verdict["quorum_required"] == 2

    def test_catalog_irreversible_flag_overrides_name_heuristic(self) -> None:
        action_types = load_action_type_catalog(
            REPO_ROOT / "rule-catalog" / "action-types",
            schema_registry=PackageResourceSchemaRegistry(),
        )
        semantics = ActionSemanticsCatalog.from_action_types(action_types)
        f = Forseti(bus=None, action_semantics=semantics)

        verdict = asyncio.run(
            f.judge({"action_type": "ops.restart-service", "correlation_id": "c-catalog"})
        )

        assert verdict is not None
        assert verdict["quorum_required"] == IRREVERSIBLE_QUORUM
        assert verdict["rollback_contract"] == "state_forward_only"


class TestThorPropagatesQuorum:
    def test_quorum_flows_onto_action_run_and_wire(self) -> None:
        bus = _bus()
        thor = Thor(bus=bus)
        run = asyncio.run(
            thor.dispatch_verdict(
                {
                    "correlation_id": "c-3",
                    "idempotency_key": "c-3-key",
                    "action_type": "remediate.delete-storage",
                    "risk_verdict": "hil",
                    "resource_id": "sa-1",
                    "quorum_required": 2,
                }
            )
        )
        assert run.quorum_required == 2
        assert run.state is ActionRunState.HIL_PENDING
        hil = [
            m
            for m in bus.messages_on("object.action-run")
            if m.payload.get("state") == "hil_pending"
        ]
        assert hil and hil[-1].payload["quorum_required"] == 2

    def test_missing_quorum_defaults_to_one(self) -> None:
        bus = _bus()
        thor = Thor(bus=bus)
        run = asyncio.run(
            thor.dispatch_verdict(
                {
                    "correlation_id": "c-4",
                    "action_type": "ops.restart-service",
                    "risk_verdict": "hil",
                    "resource_id": "svc-1",
                }
            )
        )
        assert run.quorum_required == 1

    def test_forged_negative_quorum_is_floored_to_one(self) -> None:
        bus = _bus()
        thor = Thor(bus=bus)
        run = asyncio.run(
            thor.dispatch_verdict(
                {
                    "correlation_id": "c-5",
                    "action_type": "ops.restart-service",
                    "risk_verdict": "hil",
                    "resource_id": "svc-2",
                    "quorum_required": -3,
                }
            )
        )
        assert run.quorum_required == 1


class TestEndToEndQuorum:
    def test_malformed_initiator_is_rejected_without_ticket(self) -> None:
        var = Var()

        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                _thor_action_run(
                    correlation_id="malformed-initiator",
                    action_type="ops.scale-out",
                    initiator_principal={"principal": "operator-example"},
                ),
            )
        )

        assert var.pending_tickets() == ()
        assert var.behavior_snapshot()["ticket_invalid_initiator"] == 1

    def test_malformed_quorum_is_rejected_without_ticket(self) -> None:
        var = Var()

        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                _thor_action_run(
                    correlation_id="malformed-quorum",
                    action_type="ops.scale-out",
                    quorum_required="two",
                ),
            )
        )

        assert var.pending_tickets() == ()
        assert var.behavior_snapshot()["ticket_invalid_quorum"] == 1

    def test_irreversible_hil_needs_two_distinct_approvers(self) -> None:
        bus = _bus()
        var = Var(bus=bus)
        # Var ingests the hil_pending ActionRun carrying quorum_required=2.
        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                _thor_action_run(
                    correlation_id="c-6",
                    action_type="remediate.delete-storage",
                    resource_id="sa-9",
                    quorum_required=2,
                    initiator_principal="operator-a@example.com",
                ),
            )
        )
        # First approver: quorum not yet met, no approval published.
        first = asyncio.run(
            var.decide("c-6", approver="approver-1@example.com", decision="approve")
        )
        assert first is None
        assert bus.messages_on("object.approval") == []
        # Second distinct approver: quorum met, approval published.
        second = asyncio.run(
            var.decide("c-6", approver="approver-2@example.com", decision="approve")
        )
        assert second is not None
        assert second["state"] == "approved"
        assert len(second["approvers"]) == 2

    def test_self_approval_blocked_case_insensitively(self) -> None:
        # Azure UPNs / object ids are case-insensitive, so the initiator must
        # not be able to approve their own action by varying case.
        bus = _bus()
        var = Var(bus=bus)
        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                _thor_action_run(
                    correlation_id="c-self",
                    action_type="remediate.delete-storage",
                    quorum_required=1,
                    initiator_principal="Operator-A@Example.com",
                ),
            )
        )
        with pytest.raises(ValueError, match="no self-approval"):
            asyncio.run(var.decide("c-self", approver="operator-a@example.com", decision="approve"))
        assert bus.messages_on("object.approval") == []

    def test_single_operator_profile_allows_named_operator_but_refuses_executor(self) -> None:
        profile = _approval_profile()
        bus = _bus()
        var = Var(bus=bus, approval_profile=profile)
        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                _thor_action_run(
                    correlation_id="c-single-operator",
                    action_type="remediate.delete-storage",
                    quorum_required=1,
                    original_quorum_required=2,
                    effective_quorum_required=1,
                    initiator_principal=_OPERATOR,
                    approval_profile=profile.as_audit_dict(),
                ),
            )
        )
        approval = asyncio.run(
            var.decide("c-single-operator", approver=_OPERATOR.upper(), decision="approve")
        )
        assert approval is not None
        assert approval["state"] == "approved"
        assert approval["approvers"] == [_OPERATOR]

        var = Var(bus=_bus(), approval_profile=profile)
        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                _thor_action_run(
                    correlation_id="c-executor",
                    action_type="remediate.delete-storage",
                    quorum_required=1,
                    original_quorum_required=2,
                    effective_quorum_required=1,
                    initiator_principal=_OPERATOR,
                    approval_profile=profile.as_audit_dict(),
                ),
            )
        )
        with pytest.raises(PermissionError, match="approval profile"):
            asyncio.run(var.decide("c-executor", approver=_EXECUTOR, decision="approve"))

    def test_double_approval_blocked_case_insensitively(self) -> None:
        # The distinct-approver quorum must not be satisfiable by one human
        # approving twice under different casing.
        bus = _bus()
        var = Var(bus=bus)
        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                _thor_action_run(
                    correlation_id="c-dbl",
                    action_type="remediate.delete-storage",
                    quorum_required=2,
                    initiator_principal="initiator@example.com",
                ),
            )
        )
        first = asyncio.run(
            var.decide("c-dbl", approver="Approver-1@Example.com", decision="approve")
        )
        assert first is None  # quorum 2 not yet met
        with pytest.raises(ValueError, match="twice"):
            asyncio.run(var.decide("c-dbl", approver="approver-1@example.com", decision="approve"))
        assert bus.messages_on("object.approval") == []

    def test_unauthorized_approver_cannot_contribute_to_quorum(self) -> None:
        bus = _bus()
        var = Var(
            bus=bus,
            approver_authorizer=lambda principal, _action_type: principal == "approved@example.com",
        )
        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                _thor_action_run(
                    correlation_id="c-auth",
                    action_type="remediate.enable-encryption",
                    quorum_required=1,
                    initiator_principal="initiator@example.com",
                ),
            )
        )

        with pytest.raises(PermissionError, match="not authorized"):
            asyncio.run(
                var.decide(
                    "c-auth",
                    approver="unapproved@example.com",
                    decision="approve",
                )
            )

        assert bus.messages_on("object.approval") == []
