"""End-to-end operator SRE problem-response command path."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fdai.core.control_loop import ControlLoop, ControlLoopOutcome
from fdai.core.event_ingest import EventIngest
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.incident import (
    IncidentLifecycleWorkflow,
    IncidentRegistry,
    IncidentWorkflowForbiddenError,
    OperatorSreRequest,
    OperatorSreRequestCoordinator,
    OperatorSreRequestError,
    sre_correlation_id,
    sre_correlation_keys,
    sre_idempotency_key,
)
from fdai.core.risk_gate.gate import ActionPromotionRegistry, RiskGate
from fdai.core.risk_gate.risk_table import load_risk_table
from fdai.rule_catalog.schema.action_type import load_action_type_catalog
from fdai.shared.contracts.models import IncidentSeverity
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.operator_request import OperatorProposalDispatch
from fdai.shared.providers.testing import InMemoryStateStore
from fdai.shared.providers.testing.hil_channel import InMemoryHilChannel
from fdai.shared.providers.testing.stage_publisher import RecordingStagePublisher

REPO_ROOT = Path(__file__).resolve().parents[5]
ACTION_TYPES_ROOT = REPO_ROOT / "rule-catalog" / "action-types"
RISK_TABLE_PATH = REPO_ROOT / "rule-catalog" / "risk-classification.yaml"
ACTION_TYPE = "tool.run-investigation"
RESOURCE_REF = "resource:compute/aks/payments-prod"


@dataclass(frozen=True, slots=True)
class _Principal:
    id: str
    role: str


class _RecordingDispatcher:
    """Fake dispatcher that records proposals and returns a fixed decision."""

    def __init__(
        self,
        *,
        decision: str = "shadow",
        approval_ref: str | None = None,
        process_ref: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.proposals: list[Mapping[str, Any]] = []
        self._dispatch = OperatorProposalDispatch(
            decision=decision,
            approval_ref=approval_ref,
            process_ref=process_ref,
        )
        self._error = error

    async def dispatch(self, proposal: Mapping[str, Any]) -> OperatorProposalDispatch:
        if self._error is not None:
            raise self._error
        self.proposals.append(dict(proposal))
        return self._dispatch


class _ControlLoopDispatcher:
    """Authoritative dispatcher: normalize and govern through the control loop."""

    def __init__(self, loop: ControlLoop, channel: InMemoryHilChannel) -> None:
        self._loop = loop
        self._channel = channel
        self.proposals: list[Mapping[str, Any]] = []

    async def dispatch(self, proposal: Mapping[str, Any]) -> OperatorProposalDispatch:
        self.proposals.append(dict(proposal))
        result = await self._loop.process(dict(proposal))
        approval_ref = self._channel.sent[-1].approval_id if self._channel.sent else None
        return OperatorProposalDispatch(
            decision=result.decision or "abstain",
            approval_ref=approval_ref,
        )


def _workflow() -> tuple[IncidentLifecycleWorkflow, IncidentRegistry]:
    registry = IncidentRegistry(state_store=InMemoryStateStore())
    return IncidentLifecycleWorkflow(registry=registry), registry


def _request(*, session_id: str = "session-1") -> OperatorSreRequest:
    return OperatorSreRequest(
        principal=_Principal(id="operator-1", role="contributor"),
        session_id=session_id,
        action_type=ACTION_TYPE,
        resource_id=RESOURCE_REF,
        resource_type="aks_cluster",
        investigation_kind="latency-regression",
        params={"resource_ref": RESOURCE_REF, "resource_kind": "aks_cluster"},
        severity=IncidentSeverity.SEV2,
    )


def _control_loop(stages: RecordingStagePublisher, channel: InMemoryHilChannel) -> ControlLoop:
    action_type = next(
        item
        for item in load_action_type_catalog(
            ACTION_TYPES_ROOT,
            schema_registry=PackageResourceSchemaRegistry(),
        )
        if item.name == ACTION_TYPE
    )
    validator = JsonSchemaEventValidator(
        JsonSchemaContractValidator(PackageResourceSchemaRegistry())
    )
    state = InMemoryStateStore()
    executor = MagicMock()
    return ControlLoop(
        event_ingest=EventIngest(validator=validator),
        trust_router=MagicMock(),
        t0_engine=MagicMock(),
        action_builder=ActionBuilder(action_types_by_name={action_type.name: action_type}),
        executor=executor,
        audit_store=state,
        rules_by_id={},
        risk_table=load_risk_table(RISK_TABLE_PATH),
        action_types_by_name={action_type.name: action_type},
        risk_gate=RiskGate(registry=ActionPromotionRegistry(allow_legacy_metrics=True)),
        hil_resume_coordinator=HilResumeCoordinator(
            state_store=state,
            executor=executor,
            hil_channel=channel,
            rules_by_id={},
            action_types_by_name={action_type.name: action_type},
        ),
        stage_publisher=stages,
    )


async def test_confirmed_request_opens_one_incident_and_governs_one_proposal() -> None:
    workflow, registry = _workflow()
    stages = RecordingStagePublisher()
    channel = InMemoryHilChannel()
    dispatcher = _ControlLoopDispatcher(_control_loop(stages, channel), channel)
    coordinator = OperatorSreRequestCoordinator(workflow=workflow, dispatcher=dispatcher)

    result = await coordinator.submit(_request())

    assert result.incident_created is True
    assert len(registry.snapshot()) == 1
    assert len(dispatcher.proposals) == 1
    # The unpromoted investigation ActionType parks for a distinct approver
    # instead of auto-executing.
    assert result.dispatch is not None
    assert result.dispatch.decision == "hil"
    assert result.dispatch_error is None
    assert len(channel.sent) == 1

    # One correlation joins every published stage.
    assert stages.events
    assert {event.correlation_id for event in stages.events} == {result.correlation_id}
    assert stages.events[-1].stage.value == "audit"
    assert stages.events[-1].detail["outcome"] == ControlLoopOutcome.HIL.value

    # The response links back to the authoritative Incident, Trace, and Approval.
    assert result.links.incident.endswith(result.correlation_id)
    assert result.links.trace == f"/audit/{result.correlation_id}/trace"
    assert result.links.approval == f"/hil-queue?search={channel.sent[0].approval_id}"


async def test_retry_reuses_the_incident_proposal_identity_and_correlation() -> None:
    workflow, registry = _workflow()
    dispatcher = _RecordingDispatcher()
    coordinator = OperatorSreRequestCoordinator(workflow=workflow, dispatcher=dispatcher)

    first = await coordinator.submit(_request())
    second = await coordinator.submit(_request())

    assert first.incident_created is True
    assert second.incident_created is False
    assert second.incident.incident_id == first.incident.incident_id
    assert second.idempotency_key == first.idempotency_key
    assert second.correlation_id == first.correlation_id
    assert len(registry.snapshot()) == 1


async def test_response_returns_authoritative_incident_and_trace_links() -> None:
    workflow, _ = _workflow()
    coordinator = OperatorSreRequestCoordinator(
        workflow=workflow, dispatcher=_RecordingDispatcher()
    )

    result = await coordinator.submit(_request())

    assert result.links.incident == (
        f"/incidents?status=all&correlation_id={result.correlation_id}"
    )
    assert result.links.trace == f"/audit/{result.correlation_id}/trace"
    assert result.links.process is None
    assert result.links.approval is None


async def test_hil_decision_returns_approval_and_process_links() -> None:
    workflow, _ = _workflow()
    dispatcher = _RecordingDispatcher(
        decision="hil", approval_ref="approval-7", process_ref="process-9"
    )
    coordinator = OperatorSreRequestCoordinator(workflow=workflow, dispatcher=dispatcher)

    result = await coordinator.submit(_request())

    assert result.links.approval == "/hil-queue?search=approval-7"
    assert result.links.process == "/views/process/process-9"


async def test_non_hil_decision_drops_a_stale_approval_reference() -> None:
    workflow, _ = _workflow()
    dispatcher = _RecordingDispatcher(decision="shadow", approval_ref="approval-7")
    coordinator = OperatorSreRequestCoordinator(workflow=workflow, dispatcher=dispatcher)

    result = await coordinator.submit(_request())

    assert result.links.approval is None


async def test_failed_dispatch_keeps_the_incident_and_reports_the_failure() -> None:
    workflow, registry = _workflow()
    dispatcher = _RecordingDispatcher(error=RuntimeError("bus unavailable"))
    coordinator = OperatorSreRequestCoordinator(workflow=workflow, dispatcher=dispatcher)

    result = await coordinator.submit(_request())

    assert result.dispatch is None
    assert result.dispatched is False
    assert result.dispatch_error == "RuntimeError"
    assert len(registry.snapshot()) == 1
    assert result.links.incident.endswith(result.correlation_id)
    assert result.idempotency_key == sre_idempotency_key(
        correlation_id=result.correlation_id, action_type=ACTION_TYPE
    )


async def test_proposal_carries_the_incident_id_and_no_executor_identity() -> None:
    workflow, _ = _workflow()
    dispatcher = _RecordingDispatcher()
    coordinator = OperatorSreRequestCoordinator(workflow=workflow, dispatcher=dispatcher)

    result = await coordinator.submit(_request())

    proposal = dispatcher.proposals[0]
    assert proposal["incident_id"] == str(result.incident.incident_id)
    assert proposal["initiator_principal"] == "operator-1"
    assert proposal["operator_initiated"] is True
    forbidden = ("executor", "credential", "token", "secret", "client_id")
    assert not [key for key in proposal if any(part in key for part in forbidden)]


async def test_normalized_event_payload_retains_the_incident_metadata() -> None:
    workflow, _ = _workflow()
    dispatcher = _RecordingDispatcher()
    coordinator = OperatorSreRequestCoordinator(workflow=workflow, dispatcher=dispatcher)
    result = await coordinator.submit(_request())
    ingest = EventIngest(
        validator=JsonSchemaEventValidator(
            JsonSchemaContractValidator(PackageResourceSchemaRegistry())
        )
    )

    event = ingest.ingest(dict(dispatcher.proposals[0]))

    assert event is not None
    assert event.correlation_id == result.correlation_id
    assert event.payload["incident"]["incident_id"] == str(result.incident.incident_id)
    assert UUID(event.payload["incident"]["incident_id"]) == result.incident.incident_id


async def test_distinct_sessions_do_not_share_one_incident() -> None:
    workflow, registry = _workflow()
    coordinator = OperatorSreRequestCoordinator(
        workflow=workflow, dispatcher=_RecordingDispatcher()
    )

    first = await coordinator.submit(_request(session_id="session-1"))
    second = await coordinator.submit(_request(session_id="session-2"))

    assert first.incident.incident_id != second.incident.incident_id
    assert first.correlation_id != second.correlation_id
    assert len(registry.snapshot()) == 2


async def test_reader_role_cannot_open_a_problem_response_incident() -> None:
    workflow, registry = _workflow()
    dispatcher = _RecordingDispatcher()
    coordinator = OperatorSreRequestCoordinator(workflow=workflow, dispatcher=dispatcher)
    request = OperatorSreRequest(
        principal=_Principal(id="reader-1", role="reader"),
        session_id="session-1",
        action_type=ACTION_TYPE,
        resource_id=RESOURCE_REF,
        investigation_kind="latency-regression",
        params={"resource_ref": RESOURCE_REF, "resource_kind": "aks_cluster"},
    )

    with pytest.raises(IncidentWorkflowForbiddenError):
        await coordinator.submit(request)

    assert registry.snapshot() == {}
    assert dispatcher.proposals == []


@pytest.mark.parametrize(
    "field_name",
    ["session_id", "action_type", "resource_id", "investigation_kind"],
)
def test_blank_scope_field_is_rejected_before_any_write(field_name: str) -> None:
    kwargs: dict[str, Any] = {
        "principal": _Principal(id="operator-1", role="contributor"),
        "session_id": "session-1",
        "action_type": ACTION_TYPE,
        "resource_id": RESOURCE_REF,
        "investigation_kind": "latency-regression",
    }
    kwargs[field_name] = "   "

    with pytest.raises(OperatorSreRequestError):
        OperatorSreRequest(**kwargs)


def test_correlation_identity_is_deterministic_and_order_independent() -> None:
    keys = sre_correlation_keys(
        session_id="session-1",
        resource_id=RESOURCE_REF,
        investigation_kind="latency-regression",
    )

    assert sre_correlation_id(keys) == sre_correlation_id(tuple(reversed(keys)))
