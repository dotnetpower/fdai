from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import cast

from fdai_operator_service.families.operations.contracts import (
    EventProposal,
    ProposalConflictError,
    ProposalReceipt,
)
from fdai_operator_service.routes import _accept_incident_intervention
from fdai_service_contracts.incident_intervention import IncidentInterventionProposalBody
from fdai_service_contracts.operator import (
    IncidentPageProjection,
    IncidentQuery,
    JsonObject,
    JsonValue,
    OperatorPrincipal,
    OperatorRole,
)
from starlette.responses import Response

INCIDENT_ID = "00000000-0000-0000-0000-000000000123"


@dataclass
class _ReadModel:
    item: JsonObject | None
    queries: list[IncidentQuery] = field(default_factory=list)

    async def list_incidents(self, query: IncidentQuery) -> IncidentPageProjection:
        self.queries.append(query)
        return IncidentPageProjection(
            items=(self.item,) if self.item is not None else (),
            next_cursor=None,
            metrics={},
        )


@dataclass
class _Writer:
    conflict: bool = False
    proposals: list[EventProposal] = field(default_factory=list)

    async def propose(self, proposal: EventProposal) -> ProposalReceipt:
        if self.conflict:
            raise ProposalConflictError
        self.proposals.append(proposal)
        return ProposalReceipt(
            request_id="operator-request-1",
            correlation_id=proposal.correlation_id,
            dispatch_status="pending",
            accepted_at="2026-08-24T12:00:00Z",
        )


def _body(**overrides: object) -> IncidentInterventionProposalBody:
    values: dict[str, object] = {
        "action": "operator_guidance",
        "incident_id": INCIDENT_ID,
        "correlation_id": "correlation-1",
        "expected_state": "triaging",
        "comment": "Keep the development context for the next decision.",
    }
    values.update(overrides)
    return IncidentInterventionProposalBody.model_validate(values)


def _item(**overrides: JsonValue) -> JsonObject:
    values: JsonObject = {
        "incident_id": INCIDENT_ID,
        "correlation_id": "correlation-1",
        "lifecycle_state": "triaging",
        "target_ref": "sha256:" + "a" * 64,
    }
    values.update(overrides)
    return values


def _principal(role: OperatorRole) -> OperatorPrincipal:
    return OperatorPrincipal(subject_id="operator-1", roles=frozenset({role}))


def _json(response: Response) -> dict[str, object]:
    return cast(dict[str, object], json.loads(bytes(response.body)))


async def test_guidance_accepts_server_grounded_target_and_queues_no_effect_proposal() -> None:
    reader = _ReadModel(_item())
    writer = _Writer()

    response = await _accept_incident_intervention(
        body=_body(),
        principal=_principal(OperatorRole.CONTRIBUTOR),
        idempotency_key="idempotency-1",
        read_model=reader,  # type: ignore[arg-type]
        proposal_writer=writer,
    )

    assert response.status_code == 202
    assert reader.queries == [IncidentQuery(status="all", limit=1, correlation_id="correlation-1")]
    assert writer.proposals[0].payload["target_ref"] == "sha256:" + "a" * 64
    assert writer.proposals[0].operation == "incident.intervention"


async def test_exception_role_floor_rejects_contributor_before_durable_write() -> None:
    writer = _Writer()

    response = await _accept_incident_intervention(
        body=_body(action="create_development_exception", duration="one_week"),
        principal=_principal(OperatorRole.CONTRIBUTOR),
        idempotency_key="idempotency-1",
        read_model=_ReadModel(_item()),  # type: ignore[arg-type]
        proposal_writer=writer,
    )

    assert response.status_code == 403
    assert writer.proposals == []


async def test_stale_state_and_missing_target_fail_closed() -> None:
    for item in (_item(lifecycle_state="mitigated"), _item(target_ref=None)):
        writer = _Writer()
        response = await _accept_incident_intervention(
            body=_body(),
            principal=_principal(OperatorRole.OWNER),
            idempotency_key="idempotency-1",
            read_model=_ReadModel(item),  # type: ignore[arg-type]
            proposal_writer=writer,
        )

        assert response.status_code == 409
        assert writer.proposals == []


async def test_unknown_incident_and_idempotency_collision_are_distinct() -> None:
    missing = await _accept_incident_intervention(
        body=_body(),
        principal=_principal(OperatorRole.OWNER),
        idempotency_key="idempotency-1",
        read_model=_ReadModel(None),  # type: ignore[arg-type]
        proposal_writer=_Writer(),
    )
    collision = await _accept_incident_intervention(
        body=_body(),
        principal=_principal(OperatorRole.OWNER),
        idempotency_key="idempotency-1",
        read_model=_ReadModel(_item()),  # type: ignore[arg-type]
        proposal_writer=_Writer(conflict=True),
    )

    assert missing.status_code == 404
    assert collision.status_code == 409
    assert "idempotency" in str(_json(collision)["error"])
