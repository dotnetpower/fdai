from __future__ import annotations

from typing import Any

import pytest
from fdai_operator_service.families.workflow import (
    ProjectionProvenance,
    WorkflowProposal,
    WorkflowProposalReceipt,
    WorkflowReadRequest,
    WorkflowReadResult,
    build_workflow_family_routes,
)
from fdai_service_contracts import OperatorPrincipal, OperatorRole
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient


class Authorizer:
    async def __call__(
        self,
        request: Request,
        required_roles: frozenset[OperatorRole],
    ) -> OperatorPrincipal:
        del request, required_roles
        return OperatorPrincipal("authenticated-operator", frozenset({OperatorRole.OWNER}))


class Reads:
    async def read(self, request: WorkflowReadRequest) -> WorkflowReadResult:
        del request
        return WorkflowReadResult({}, ProjectionProvenance("test", "test"))


class Proposals:
    def __init__(self) -> None:
        self.items: list[WorkflowProposal] = []

    async def submit(self, proposal: WorkflowProposal) -> WorkflowProposalReceipt:
        self.items.append(proposal)
        return WorkflowProposalReceipt("proposal", "revision")


def _client() -> tuple[TestClient, Proposals]:
    proposals = Proposals()
    app = Starlette(
        routes=list(
            build_workflow_family_routes(
                authorize=Authorizer(),
                read_store=Reads(),
                proposal_writer=proposals,
            )
        )
    )
    return TestClient(app), proposals


@pytest.mark.parametrize(
    "extra",
    [
        {"principal_id": "forged-actor"},
        {"approver_ids": ["forged-approver"]},
        {"execution_authority": True},
    ],
)
def test_request_rejects_client_authority_fields(extra: dict[str, Any]) -> None:
    client, proposals = _client()

    response = client.post(
        "/rules/activation-changes",
        headers={"Idempotency-Key": "change-1", "If-Match": "a" * 64},
        json={
            "mode": "shadow",
            "reason": "Disable the reviewed Rule after an operational false positive.",
            "changes": [{"rule_id": "rule.alpha", "enabled": False}],
            **extra,
        },
    )

    assert response.status_code == 400
    assert proposals.items == []


def test_request_rejects_duplicate_changes() -> None:
    client, proposals = _client()

    response = client.post(
        "/rules/activation-changes",
        headers={"Idempotency-Key": "change-1", "If-Match": "a" * 64},
        json={
            "mode": "shadow",
            "reason": "Disable the reviewed Rule after an operational false positive.",
            "changes": [
                {"rule_id": "rule.alpha", "enabled": False},
                {"rule_id": "rule.alpha", "enabled": True},
            ],
        },
    )

    assert response.status_code == 400
    assert proposals.items == []
