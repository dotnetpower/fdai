"""Core-internal raw operator_request producer receipt tests."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fdai.agents import OperatorRequestReceiptGate
from fdai.agents.huginn import Huginn
from fdai.core.incident.sre_request import (
    OperatorSreRequest,
    OperatorSreRequestCoordinator,
)
from fdai.core.investigation import Priority
from fdai.core.irp import MitigationProposal
from fdai.core.runbook.models import RunbookStep
from fdai.core.scheduler.models import ScheduledTask
from fdai.core.scheduler.service import SchedulerService
from fdai.core.scheduler.store import InMemoryScheduleStore
from fdai.delivery.irp import EventBusIrpProposalRouter
from fdai.delivery.ohl_scale_out_evidence_cli import (
    OhlScaleOutProposalConfig,
    build_scale_out_proposal,
)
from fdai.delivery.operator_request_receipt import CoreOperatorRequestReceiptIssuer
from fdai.runtime.workflow_action_dispatch import EventBusWorkflowActionDispatcher
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai_service_contracts.operator_request_receipt import (
    OperatorRequestReceipt,
    operator_request_public_key_from_seed,
)

_NOW = datetime(2026, 10, 1, tzinfo=UTC)
_SEED = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii").rstrip("=")


@dataclass(frozen=True, slots=True)
class _Principal:
    id: UUID
    roles: frozenset[str]


class _Verifier:
    def verify_operator_request_receipt(
        self,
        *,
        receipt: OperatorRequestReceipt,
        signing_bytes: bytes,
    ) -> bool:
        del receipt, signing_bytes
        return False


class _Bus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict[str, Any]]] = []

    async def publish(self, topic: str, key: str, payload: dict[str, Any]) -> PublishReceipt:
        self.published.append((topic, key, dict(payload)))
        return PublishReceipt(topic=topic, partition=0, offset=len(self.published))


def _issuer() -> CoreOperatorRequestReceiptIssuer:
    return CoreOperatorRequestReceiptIssuer(private_key_seed=_SEED, clock=lambda: _NOW)


async def _assert_huginn_accepts(payload: dict[str, Any]) -> None:
    gate = OperatorRequestReceiptGate(
        verifier=_Verifier(),
        state_store=InMemoryStateStore(),
        clock=lambda: _NOW,
        trusted_producer_public_keys={
            "core-control-plane": operator_request_public_key_from_seed(_SEED)
        },
    )
    accepted = await Huginn(operator_request_receipt_gate=gate, clock=lambda: _NOW).ingest(payload)
    assert accepted is not None
    assert accepted["operator_request_channel"] == "ingress"


async def test_scheduler_raw_operator_request_carries_valid_receipt_for_huginn() -> None:
    store = InMemoryScheduleStore()
    await store.create(
        ScheduledTask(
            task_id="task-one",
            name="restart",
            interval_seconds=300,
            event_type="ignored",
            resource_ref="resource:service/api",
            created_by="owner",
            event_payload={
                "action_proposal": {
                    "initiator_principal": "owner",
                    "action_type": "ops.restart-service",
                    "params": {"target_resource_ref": "resource:service/api"},
                }
            },
        )
    )
    bus = _Bus()
    await SchedulerService(store=store, event_bus=bus, receipt_issuer=_issuer()).run_once(now=_NOW)

    payload = bus.published[0][2]
    assert payload["operator_request_receipt"]
    await _assert_huginn_accepts(payload)


async def test_workflow_dispatcher_raw_operator_request_carries_valid_receipt_for_huginn() -> None:
    bus = _Bus()
    dispatcher = EventBusWorkflowActionDispatcher(bus, "fdai.events", receipt_issuer=_issuer())

    await dispatcher.dispatch(
        process_id="process-1",
        correlation_id="correlation-1",
        step=RunbookStep(id="restart", action_type="ops.restart-service"),
        target_resource_id="resource:service/api",
        params={"target_resource_ref": "resource:service/api"},
        context={"workflow.requester_principal": "owner"},
    )

    payload = bus.published[0][2]
    assert payload["operator_request_receipt"]
    await _assert_huginn_accepts(payload)


async def test_irp_router_raw_operator_request_carries_valid_receipt_for_huginn() -> None:
    bus = _Bus()
    router = EventBusIrpProposalRouter(bus=bus, topic="fdai.events", receipt_issuer=_issuer())

    await router.route(
        MitigationProposal(
            proposal_id="proposal-1",
            alert_id="alert-1",
            remediation_ref="appgw.scale_backend_pool",
            detail="Scale the affected backend pool.",
            priority=Priority.P1,
            approver_role="approver",
            citations=("metric:healthy_host_count",),
            requested_at=_NOW,
            target_resource_ref="appgw-1",
        )
    )

    payload = bus.published[0][2]
    assert payload["operator_request_receipt"]
    await _assert_huginn_accepts(payload)


async def test_ohl_raw_operator_request_carries_valid_receipt_for_huginn() -> None:
    payload = build_scale_out_proposal(
        OhlScaleOutProposalConfig(
            bootstrap_servers="event.example.com:9093",
            topic="fdai.events",
            target_resource_id=(
                "/subscriptions/00000000-0000-0000-0000-000000000000/"
                "resourceGroups/rg-example/providers/Microsoft.Compute/"
                "virtualMachineScaleSets/vmss-example"
            ),
            initiator_principal="00000000-0000-0000-0000-000000000001",
            campaign_id="campaign-1",
            baseline_capacity=1,
        ),
        _issuer(),
    )

    assert payload["operator_request_receipt"]
    await _assert_huginn_accepts(payload)


def test_sre_request_proposal_carries_valid_receipt() -> None:
    class _Workflow:
        pass

    class _Dispatcher:
        async def dispatch(self, proposal: dict[str, Any]) -> object:
            del proposal
            return None

    coordinator = OperatorSreRequestCoordinator(
        workflow=_Workflow(),  # type: ignore[arg-type]
        dispatcher=_Dispatcher(),  # type: ignore[arg-type]
        receipt_issuer=_issuer(),
    )
    proposal = coordinator._build_proposal(  # noqa: SLF001 - focused producer contract
        OperatorSreRequest(
            principal=_Principal(id=UUID(int=1), roles=frozenset({"Owner"})),
            session_id="session-1",
            action_type="ops.restart-service",
            resource_id="resource:service/api",
            investigation_kind="sre",
            params={"target_resource_ref": "resource:service/api"},
        ),
        incident_id=UUID(int=2),
        correlation_id="correlation-1",
        idempotency_key="operator-sre:one",
    )

    assert proposal["operator_request_receipt"]
