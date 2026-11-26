"""Cost annotations remain evidence and do not change authority decisions."""

from __future__ import annotations

import asyncio
from typing import Any

from fdai.agents._framework.action_semantics import ActionSemanticsCatalog
from fdai.agents._framework.bus import InMemoryBus
from fdai.agents._framework.forseti_safeguards import execution_safeguards
from fdai.agents._framework.registry import load_pantheon
from fdai.agents.forseti import Forseti
from fdai.agents.odin import Odin
from fdai.agents.thor import Thor
from fdai.agents.var import Var
from fdai.shared.contracts.models import Autonomy


def _semantics() -> ActionSemanticsCatalog:
    return ActionSemanticsCatalog(
        irreversible_by_id={"remediate.disable-public-access": False},
        rollback_by_id={"remediate.disable-public-access": "state_forward_only"},
    )


def _measured_annotation(delta: float = 12.5) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "state": "measured",
        "source_principal": "Njord",
        "freshness_state": "fresh",
        "observed_at": "2026-10-01T00:00:00+00:00",
        "estimate": {"monthly_delta": delta, "currency": "USD"},
        "currency": "USD",
        "evidence_refs": ["cost-ref"],
        "evidence_digests": ["sha256:" + "c" * 64],
    }


def _verdict(correlation: str, annotation: dict[str, Any]) -> dict[str, Any]:
    action_type = "remediate.disable-public-access"
    action_idempotency_key = f"{correlation}:action"
    return {
        "producer_principal": "Forseti",
        "correlation_id": correlation,
        "idempotency_key": f"{correlation}:verdict",
        "action_idempotency_key": action_idempotency_key,
        "resource_id": f"{correlation}:resource",
        "action_type": action_type,
        "risk_verdict": "hil",
        "resolved_autonomy_ceiling": Autonomy.ENFORCE_HIL.value,
        "reason": "human_approval_required",
        "params": {},
        "quorum_required": 1,
        "rollback_contract": "state_forward_only",
        "initiator_principal": "Heimdall",
        "safeguards": execution_safeguards(
            action_type=action_type,
            action_idempotency_key=action_idempotency_key,
            resource_id=f"{correlation}:resource",
            rollback_contract="state_forward_only",
            event={"dry_run_receipt": f"{correlation}:dry-run"},
        ),
        "cost_annotation": annotation,
    }


def test_forseti_verdict_cost_annotation_does_not_change_judgment() -> None:
    forseti = Forseti(action_semantics=_semantics())
    base_event = {
        "event_type": "public_network_enabled",
        "resource_id": "storage-1",
        "correlation_id": "corr-cost-a",
    }
    measured = asyncio.run(
        forseti.judge({**base_event, "cost_annotation": _measured_annotation(7.0)})
    )
    unavailable = asyncio.run(forseti.judge({**base_event, "correlation_id": "corr-cost-b"}))

    assert measured["risk_verdict"] == unavailable["risk_verdict"] == "auto"
    assert measured["resolved_autonomy_ceiling"] == unavailable["resolved_autonomy_ceiling"]
    assert measured["quorum_required"] == unavailable["quorum_required"] == 1
    assert measured["cost_annotation"]["state"] == "measured"
    assert unavailable["cost_annotation"]["state"] == "unavailable"
    assert unavailable["cost_annotation"]["estimate"] is None


def test_arbitration_request_and_odin_decision_preserve_cost_annotation() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    forseti = Forseti(bus=bus, action_semantics=_semantics())
    odin = Odin(bus=bus)
    bus.subscribe("object.arbitration-request", "Odin", odin.on_typed_message)

    cost_payload = {
        "producer_principal": "Njord",
        "correlation_id": "corr-arb-cost",
        "idempotency_key": "cost-1",
        "resource_id": "resource-arb",
        "recommendation": "scale_down",
        "variance": 18.0,
        "impact": 0.9,
        "observed_at": "2026-10-01T00:00:00+00:00",
        "evidence_ref": "cost-evidence-ref",
    }
    capacity_payload = {
        "producer_principal": "Freyr",
        "correlation_id": "corr-arb-cost",
        "idempotency_key": "capacity-1",
        "resource_id": "resource-arb",
        "recommendation": "scale_out",
        "forecast_util": 0.95,
        "impact": 0.7,
        "observed_at": "2026-10-01T00:00:00+00:00",
    }

    asyncio.run(forseti.on_typed_message("object.cost-anomaly", cost_payload))
    asyncio.run(forseti.on_typed_message("object.capacity-forecast", capacity_payload))

    request = bus.messages_on("object.arbitration-request")[0].payload
    decision = bus.messages_on("object.arbitration-decision")[0].payload
    assert request["cost_annotation"]["state"] == "measured"
    assert request["cost_annotation"]["source_principal"] == "Njord"
    assert decision["cost_annotation"] == request["cost_annotation"]


def test_thor_and_var_receive_cost_annotation_without_authority_change() -> None:
    bus = InMemoryBus(registry=load_pantheon())
    thor = Thor(bus=bus, action_semantics_catalog=_semantics())
    var = Var(bus=bus, action_semantics=_semantics())
    bus.subscribe("object.action-run", "Var", var.on_typed_message)

    measured = asyncio.run(thor.dispatch_verdict(_verdict("corr-hil-a", _measured_annotation())))
    unavailable = asyncio.run(
        thor.dispatch_verdict(
            _verdict(
                "corr-hil-b",
                {
                    "schema_version": "1.0.0",
                    "state": "unavailable",
                    "reason": "cost_evidence_unavailable",
                    "source_principal": "Njord",
                    "freshness_state": "unavailable",
                    "observed_at": "",
                    "estimate": None,
                    "currency": "USD",
                    "evidence_refs": [],
                    "evidence_digests": [],
                },
            )
        )
    )

    assert measured.state.value == unavailable.state.value == "hil_pending"
    assert measured.quorum_required == unavailable.quorum_required == 1
    action_runs = [
        message.payload
        for message in bus.messages_on("object.action-run")
        if message.payload["state"] == "hil_pending"
    ]
    assert [payload["cost_annotation"]["state"] for payload in action_runs] == [
        "measured",
        "unavailable",
    ]
    assert len(var.pending_tickets()) == 2
