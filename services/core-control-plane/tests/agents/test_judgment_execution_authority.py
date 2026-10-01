"""Round 6 authority and input-validation hardening for Forseti, Thor, and Vidar."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fdai.agents._framework.action_run_identity import (
    action_run_identity_digest,
    approval_matches_action_run,
)
from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.thor import ActionRunState, Thor, _positive_quorum
from fdai.agents.var import Var
from fdai.agents.vidar import Vidar
from fdai.shared.contracts.models import Autonomy
from fdai.shared.providers.testing.state_store import InMemoryStateStore

from tests.agents.preflight_helpers import PassingPreflightSimulator


def _bus() -> InMemoryBus:
    return InMemoryBus(registry=load_pantheon())


def _reversible_semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={"test.auto": False},
        rollback_by_id={"test.auto": "state_forward_only"},
    )


def _safeguards(idempotency_key: str) -> dict[str, object]:
    return {
        "stop_condition": "stop when postcondition is false",
        "tested_rollback_contract": "state_forward_only:test-receipt",
        "blast_radius_limit": {"scope": "resource", "max_targets": 1},
        "dry_run_receipt": "sha256:" + "1" * 64,
        "logical_target_lock": "lock:resource:test",
        "stable_idempotency_key": idempotency_key,
        "two_phase_audit_intent": "audit-intent:test",
    }


def _verdict(**overrides: Any) -> dict[str, Any]:
    idempotency_key = str(overrides.get("idempotency_key") or "idem-authority")
    payload: dict[str, Any] = {
        "producer_principal": "Forseti",
        "correlation_id": "corr-authority",
        "idempotency_key": idempotency_key,
        "action_type": "test.auto",
        "risk_verdict": "auto",
        "resolved_autonomy_ceiling": Autonomy.ENFORCE_AUTO.value,
        "resource_id": "resource-authority",
        "safeguards": _safeguards(idempotency_key),
    }
    payload.update(overrides)
    return payload


def _approval_for_run(run: Any, *, approvers: list[str] | None = None) -> dict[str, Any]:
    return {
        "producer_principal": "Var",
        "kind": "action",
        "state": "approved",
        "correlation_id": run.correlation_id,
        "idempotency_key": f"approval:{run.idempotency_key}",
        "action_id": run.action_id,
        "action_type": run.action_type,
        "action_run_identity": action_run_identity_digest(run.to_dict()),
        "action_idempotency_key": run.idempotency_key,
        "resource_id": run.resource_id,
        "rollback_contract": run.rollback_contract,
        "approvers": approvers or ["approver@example.com"],
    }


def test_thor_rejects_ownerless_verdict_with_visible_terminal_outcome() -> None:
    bus = _bus()
    thor = Thor(bus=bus, action_semantics_catalog=_reversible_semantics())

    asyncio.run(
        thor.on_typed_message(
            "object.verdict",
            _verdict(correlation_id="forged-verdict", producer_principal=None),
        )
    )

    run = thor.action_runs["forged-verdict"]
    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "verdict_producer_not_forseti"
    assert thor.behavior_snapshot()["verdict:rejected_owner"] == 1
    assert "executing" not in [msg.payload["state"] for msg in bus.messages_on("object.action-run")]


def test_thor_denies_enforce_verdict_missing_wire_safeguards() -> None:
    thor = Thor(bus=_bus(), action_semantics_catalog=_reversible_semantics())

    run = asyncio.run(thor.dispatch_verdict(_verdict(correlation_id="missing-safe", safeguards={})))

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "missing_safeguards"
    assert thor.behavior_snapshot()["dispatch:missing_safeguards"] == 1


def test_thor_rederives_unknown_action_quorum_and_lowers_auto() -> None:
    thor = Thor(bus=_bus())

    run = asyncio.run(
        thor.dispatch_verdict(
            _verdict(
                correlation_id="unknown-quorum",
                idempotency_key="unknown-quorum-key",
                action_type="custom.unknown",
                quorum_required=1,
                effective_quorum_required=1,
            )
        )
    )

    assert run.state is ActionRunState.HIL_PENDING
    assert run.original_quorum_required == 2
    assert run.effective_quorum_required == 2
    assert run.quorum_required == 2
    assert thor.behavior_snapshot()["dispatch:auto_quorum_lowered"] == 1


def test_thor_rejects_approval_without_var_durable_readback() -> None:
    store = InMemoryStateStore()
    thor = Thor(
        bus=_bus(),
        action_semantics_catalog=_reversible_semantics(),
        approval_state_store=store,
        approver_authorizer=lambda _principal, _action_type: True,
        preflight_simulator=PassingPreflightSimulator(),
    )
    run = asyncio.run(
        thor.dispatch_verdict(
            _verdict(
                correlation_id="approval-readback",
                idempotency_key="approval-readback-key",
                risk_verdict="hil",
                resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL.value,
            )
        )
    )

    asyncio.run(thor.on_typed_message("object.approval", _approval_for_run(run)))

    assert run.state is ActionRunState.REJECTED
    assert run.outcome == "approval_readback_rejected"
    assert thor.behavior_snapshot()["approval:readback_rejected"] == 1


def test_thor_readback_accepts_var_approval_while_its_publication_claim_is_in_flight() -> None:
    """Var claims ``publishing`` before it publishes; a fast consumer must still read it."""

    executed: list[str] = []

    async def _executor(context: dict[str, Any]) -> bool:
        executed.append(context["run"].correlation_id)
        return True

    async def _drive() -> Any:
        store = InMemoryStateStore()
        bus = _bus()
        thor = Thor(
            bus=bus,
            executor=_executor,
            action_semantics_catalog=_reversible_semantics(),
            approval_state_store=store,
            approver_authorizer=lambda _principal, _action_type: True,
            preflight_simulator=PassingPreflightSimulator(),
        )
        var = Var(bus=bus, state_store=store, action_semantics=_reversible_semantics())
        bus.subscribe("object.action-run", "Var", var.on_typed_message)
        bus.subscribe("object.approval", "Thor", thor.on_typed_message)
        run = await thor.dispatch_verdict(
            _verdict(
                correlation_id="approval-in-flight",
                idempotency_key="approval-in-flight-key",
                risk_verdict="hil",
                resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL.value,
            )
        )
        assert run.state is ActionRunState.HIL_PENDING
        approval = await var.decide(
            run.correlation_id,
            approver="approver@example.com",
            decision="approve",
        )
        assert approval is not None
        return thor, run

    thor, run = asyncio.run(_drive())

    assert run.outcome != "approval_readback_rejected"
    assert "approval:readback_rejected" not in thor.behavior_snapshot()
    assert executed == ["approval-in-flight"]


def test_thor_rejects_original_approval_after_the_run_params_change() -> None:
    executed: list[str] = []

    async def _executor(context: dict[str, Any]) -> bool:
        executed.append(context["run"].correlation_id)
        return True

    thor = Thor(bus=_bus(), executor=_executor, action_semantics_catalog=_reversible_semantics())
    run = asyncio.run(
        thor.dispatch_verdict(
            _verdict(
                correlation_id="params-drift",
                idempotency_key="params-drift-key",
                risk_verdict="hil",
                resolved_autonomy_ceiling=Autonomy.ENFORCE_HIL.value,
                params={"replicas": 2},
            )
        )
    )
    approval = _approval_for_run(run)
    run.params["replicas"] = 10

    with pytest.raises(ValueError, match="approval identity"):
        asyncio.run(thor.on_typed_message("object.approval", approval))

    assert executed == []
    assert thor.behavior_snapshot()["approval:identity_mismatch"] == 1


def test_approval_identity_requires_var_idempotency_and_approver_evidence() -> None:
    thor = Thor(bus=_bus())
    run = asyncio.run(
        thor.dispatch_verdict(
            _verdict(
                correlation_id="approval-evidence",
                idempotency_key="approval-evidence-key",
                risk_verdict="hil",
                resolved_autonomy_ceiling=Autonomy.SHADOW_ONLY.value,
            )
        )
    )
    approval = _approval_for_run(run)
    approval.pop("approvers")

    assert not approval_matches_action_run(approval, run.to_dict())


def test_thor_rejects_oversized_params_before_persistence() -> None:
    thor = Thor(bus=_bus(), action_semantics_catalog=_reversible_semantics())

    run = asyncio.run(
        thor.dispatch_verdict(
            _verdict(
                correlation_id="oversized-params",
                idempotency_key="oversized-params-key",
                params={"blob": "x" * 20_000},
            )
        )
    )

    assert run.state is ActionRunState.DENY_DROPPED
    assert run.outcome == "invalid_params"
    assert run.params == {}
    assert thor.behavior_snapshot()["dispatch:invalid_params"] == 1


def test_vidar_rejects_failed_action_run_not_owned_by_thor() -> None:
    vidar = Vidar()

    asyncio.run(
        vidar.on_typed_message(
            "object.action-run",
            {
                "producer_principal": "Mallory",
                "correlation_id": "rollback-forged",
                "idempotency_key": "rollback-forged-key",
                "state": "failed",
            },
        )
    )

    assert vidar.records == []
    assert vidar.behavior_snapshot()["rollback:rejected_owner"] == 1


def test_forseti_rejects_generic_sensing_payload_from_wrong_owner() -> None:
    bus = _bus()
    forseti = Forseti(bus=bus)

    asyncio.run(
        forseti.on_typed_message(
            "object.event",
            {
                "producer_principal": "Mallory",
                "correlation_id": "bad-event",
                "idempotency_key": "bad-event-key",
                "event_type": "unknown",
                "resource_id": "resource:event",
            },
        )
    )

    assert bus.messages_on("object.verdict") == []
    assert forseti.behavior_snapshot()["typed_input:rejected_owner"] == 1


def test_forseti_rejects_ownerless_cost_and_capacity_advice() -> None:
    bus = _bus()
    forseti = Forseti(bus=bus)

    asyncio.run(
        forseti.on_typed_message(
            "object.cost-anomaly",
            {
                "correlation_id": "ownerless-cost",
                "idempotency_key": "ownerless-cost-key",
                "resource_id": "resource:cost",
                "recommendation": "scale_down",
            },
        )
    )
    asyncio.run(
        forseti.on_typed_message(
            "object.capacity-forecast",
            {
                "correlation_id": "ownerless-capacity",
                "idempotency_key": "ownerless-capacity-key",
                "resource_id": "resource:capacity",
                "recommendation": "scale_up",
            },
        )
    )

    assert bus.messages_on("object.arbitration-request") == []
    assert forseti.behavior_snapshot()["specialist_advice:rejected_owner"] == 2


def test_forseti_rejects_capacity_graduation_and_change_from_wrong_owner() -> None:
    class ReviewLoop:
        calls = 0

        async def evaluate(self, _payload: dict[str, object]) -> object:
            self.calls += 1
            raise AssertionError("wrong-owner change must not reach review loop")

    bus = _bus()
    loop = ReviewLoop()
    forseti = Forseti(bus=bus, architecture_review_loop=loop)  # type: ignore[arg-type]

    asyncio.run(
        forseti.on_typed_message(
            "object.capacity-graduation-recommendation",
            {
                "producer_principal": "Mallory",
                "correlation_id": "bad-graduation",
                "idempotency_key": "bad-graduation-key",
            },
        )
    )
    asyncio.run(
        forseti.on_typed_message(
            "object.change",
            {
                "producer_principal": "Mallory",
                "correlation_id": "bad-change",
                "idempotency_key": "bad-change-key",
                "id": "change-1",
            },
        )
    )

    assert loop.calls == 0
    assert bus.messages_on("object.verdict") == []
    assert forseti.behavior_snapshot()["typed_input:rejected_owner"] == 2


def test_forseti_constructor_and_binding_validation_branches() -> None:
    bus = _bus()
    forseti = Forseti()
    forseti.bind_bus(bus)
    forseti.bind_agent_availability(lambda: ("Forseti",))
    assert forseti.bus is bus

    for kwargs in (
        {"cross_vertical_timeout_seconds": 0.0},
        {"architecture_review_timeout_seconds": 0.0},
        {"change_assessment_timeout_seconds": 0.0},
    ):
        try:
            Forseti(**kwargs)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:  # pragma: no cover - assertion helper
            raise AssertionError(f"Forseti accepted invalid constructor args: {kwargs}")


def test_thor_positive_quorum_rejects_non_integer_inputs() -> None:
    for value in (True, object()):
        try:
            _positive_quorum(value)
        except TypeError:
            pass
        else:  # pragma: no cover - assertion helper
            raise AssertionError(f"Thor accepted malformed quorum {value!r}")


def test_thor_binding_and_ignored_typed_message_branches() -> None:
    thor = Thor()
    thor.set_action_semantics(_reversible_semantics())
    thor.set_approval_readback(
        InMemoryStateStore(),
        approver_authorizer=lambda _principal, _action_type: True,
    )
    thor.bind_bus(_bus())

    asyncio.run(
        thor.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "kind": "document_ingestion",
                "correlation_id": "ignored-document",
                "idempotency_key": "ignored-document-key",
            },
        )
    )
    asyncio.run(
        thor.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "kind": "architecture_review",
                "correlation_id": "ignored-architecture",
                "idempotency_key": "ignored-architecture-key",
            },
        )
    )
    asyncio.run(
        thor.on_typed_message(
            "object.verdict",
            {
                "producer_principal": "Forseti",
                "kind": "capacity_graduation",
                "correlation_id": "ignored-capacity",
                "idempotency_key": "ignored-capacity-key",
            },
        )
    )
    asyncio.run(
        thor.on_typed_message(
            "object.approval",
            {
                "producer_principal": "Var",
                "kind": "test_context_review",
                "correlation_id": "ignored-test-context",
                "idempotency_key": "ignored-test-context-key",
            },
        )
    )
    asyncio.run(
        thor.on_typed_message(
            "object.approval",
            {
                "producer_principal": "Var",
                "kind": "document_ingestion",
                "correlation_id": "ignored-document-approval",
                "idempotency_key": "ignored-document-approval-key",
            },
        )
    )
    asyncio.run(
        thor.on_typed_message(
            "object.approval",
            {
                "producer_principal": "Var",
                "kind": "not_action",
                "correlation_id": "ignored-approval",
                "idempotency_key": "ignored-approval-key",
            },
        )
    )
    asyncio.run(
        thor.on_typed_message(
            "object.rollback",
            {
                "producer_principal": "Mallory",
                "correlation_id": "bad-rollback",
                "idempotency_key": "bad-rollback-key",
            },
        )
    )

    behavior = thor.behavior_snapshot()
    assert behavior["document_verdict_ignored"] == 1
    assert behavior["architecture_review_verdict_ignored"] == 1
    assert behavior["capacity_graduation_verdict_ignored"] == 1
    assert behavior["test_context_approval_ignored"] == 1
    assert behavior["document_approval_ignored"] == 1
    assert behavior["non_action_approval_ignored"] == 1
    assert behavior["rollback:rejected_owner"] == 1
