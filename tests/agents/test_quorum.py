"""Irreversible-action approval quorum plumbing (Forseti -> Thor -> Var).

Closes the section-5 gap: Forseti now stamps quorum_required on the
verdict and Thor propagates it onto the ActionRun instead of hard-coding
1, so Var's existing two-approver enforcement actually receives a quorum
of 2 for an irreversible action.
"""

from __future__ import annotations

import asyncio

from fdai.agents._framework.action_semantics import (
    DEFAULT_QUORUM,
    IRREVERSIBLE_QUORUM,
    is_irreversible,
    outcome_result,
    quorum_for,
)
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.thor import ActionRunState, Thor
from fdai.agents.var import Var


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
