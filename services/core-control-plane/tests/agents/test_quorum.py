"""Irreversible-action approval quorum plumbing (Forseti -> Thor -> Var).

Closes the section-5 gap: Forseti now stamps quorum_required on the
verdict and Thor propagates it onto the ActionRun instead of hard-coding
1, so Var's existing two-approver enforcement actually receives a quorum
of 2 for an irreversible action.
"""

from __future__ import annotations

import asyncio
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
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

REPO_ROOT = Path(__file__).resolve().parents[4]


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


class TestActionSemantics:
    def test_delete_is_irreversible(self) -> None:
        assert is_irreversible("remediate.delete-storage")
        assert is_irreversible("ops.destroy-cluster")

    def test_one_way_verbs_are_irreversible(self) -> None:
        # Round 2 safety gap: these one-way verbs previously slipped through
        # is_irreversible and would have cleared HIL on a single approver.
        assert is_irreversible("ops.terminate-instance")
        assert is_irreversible("remediate.purge-cache")
        assert is_irreversible("ops.decommission-node")
        assert is_irreversible("storage.wipe-volume")
        assert quorum_for("ops.terminate-instance") == IRREVERSIBLE_QUORUM

    def test_ordinary_action_is_reversible(self) -> None:
        assert not is_irreversible("ops.restart-service")
        assert not is_irreversible("remediate.enable-encryption")
        # Ambiguous verbs stay reversible (avoid over-flagging tag ops).
        assert not is_irreversible("config.remove-tag")
        assert not is_irreversible("remediate.disable-public-access")

    def test_quorum_for(self) -> None:
        assert quorum_for("remediate.delete-storage") == IRREVERSIBLE_QUORUM == 2
        assert quorum_for("ops.restart-service") == DEFAULT_QUORUM == 1

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

        non_execution = {ActionRunState.REJECTED, ActionRunState.DENY_DROPPED}
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

    def test_reversible_action_gets_quorum_one(self) -> None:
        f = Forseti(bus=None)
        verdict = asyncio.run(
            f.judge({"action_type": "ops.restart-service", "correlation_id": "c-2"})
        )
        assert verdict is not None
        assert verdict["quorum_required"] == 1

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
                {
                    "correlation_id": "malformed-initiator",
                    "state": "hil_pending",
                    "action_type": "ops.scale-out",
                    "initiator_principal": {"principal": "operator-example"},
                },
            )
        )

        assert var.pending_tickets() == ()
        assert var.behavior_snapshot()["ticket_invalid_initiator"] == 1

    def test_malformed_quorum_is_rejected_without_ticket(self) -> None:
        var = Var()

        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                {
                    "correlation_id": "malformed-quorum",
                    "state": "hil_pending",
                    "action_type": "ops.scale-out",
                    "quorum_required": "two",
                },
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
                {
                    "correlation_id": "c-6",
                    "action_type": "remediate.delete-storage",
                    "resource_id": "sa-9",
                    "state": "hil_pending",
                    "quorum_required": 2,
                    "initiator_principal": "operator-a@example.com",
                },
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
                {
                    "correlation_id": "c-self",
                    "action_type": "remediate.delete-storage",
                    "state": "hil_pending",
                    "quorum_required": 1,
                    "initiator_principal": "Operator-A@Example.com",
                },
            )
        )
        with pytest.raises(ValueError, match="no self-approval"):
            asyncio.run(var.decide("c-self", approver="operator-a@example.com", decision="approve"))
        assert bus.messages_on("object.approval") == []

    def test_double_approval_blocked_case_insensitively(self) -> None:
        # The distinct-approver quorum must not be satisfiable by one human
        # approving twice under different casing.
        bus = _bus()
        var = Var(bus=bus)
        asyncio.run(
            var.on_typed_message(
                "object.action-run",
                {
                    "correlation_id": "c-dbl",
                    "action_type": "remediate.delete-storage",
                    "state": "hil_pending",
                    "quorum_required": 2,
                    "initiator_principal": "initiator@example.com",
                },
            )
        )
        first = asyncio.run(
            var.decide("c-dbl", approver="Approver-1@Example.com", decision="approve")
        )
        assert first is None  # quorum 2 not yet met
        with pytest.raises(ValueError, match="twice"):
            asyncio.run(var.decide("c-dbl", approver="approver-1@example.com", decision="approve"))
        assert bus.messages_on("object.approval") == []
