"""Fail-closed admission for optional Rule-findings summaries."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

import pytest
from fdai_operator_service.families.workflow import (
    WorkflowOperation,
    WorkflowReadRequest,
    build_workflow_family_routes,
)
from fdai_operator_service.family_adapters import PostgresWorkflowAdapters
from fdai_operator_service.postgres_family_store import PostgresFamilyStoreUnavailable
from fdai_operator_service.projections import http_exception_error
from fdai_service_contracts import OperatorPrincipal, OperatorRole
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.testclient import TestClient


def _request() -> WorkflowReadRequest:
    return WorkflowReadRequest(
        operation=WorkflowOperation.RULE_FINDINGS_SUMMARY,
        principal_id="operator-a",
        query={},
        path_parameters={},
    )


async def test_absent_summary_preserves_catalog_provenanced_not_evaluated() -> None:
    class MissingSummaryStore:
        async def read_state(self, key: str) -> None:
            assert key == "operator-projection:workflow:rule.findings-summary"
            return None

        async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
            assert (family, operation) == ("workflow", "rule.list")
            return {"_revision": "catalog-sha256", "rules": [], "details": {}}

    result = await PostgresWorkflowAdapters(cast(Any, MissingSummaryStore())).read(_request())

    assert result.payload == {"evaluated": False, "counts": {}}
    assert result.provenance.revision == "catalog-sha256"
    assert result.provenance.source_ref == "state_kv:operator-projection:workflow:rule.list"


@pytest.mark.parametrize(
    "summary",
    [
        {"_revision": "summary-1", "evaluated": True, "counts": {}},
        {"_revision": "summary-1", "evaluated": True, "counts": {"rule-1": 3}},
        {
            "_revision": "summary-1",
            "evaluated": True,
            "counts": {"rule-1": 0},
            "claims": {"generation": "current", "catalog": "catalog-sha256", "complete": True},
        },
        {
            "_revision": "summary-1",
            "evaluated": True,
            "counts": {},
            "claims": {"inventory": "empty", "complete": True},
        },
        {
            "_revision": "summary-1",
            "evaluated": True,
            "counts": {"rule-1": 1},
            "claims": {"pending_generation": "newer", "eligible": 2, "covered": 1},
        },
        {"_revision": "summary-1", "evaluated": False, "counts": {}},
    ],
    ids=[
        "false-zero",
        "unverified-counts",
        "self-attested-coverage",
        "unproven-empty-inventory",
        "pending-and-partial-coverage",
        "stored-negative",
    ],
)
async def test_stored_rule_findings_cannot_claim_evaluation(
    summary: dict[str, object],
) -> None:
    class SummaryStore:
        def __init__(self) -> None:
            self.reads: list[str] = []

        async def read_state(self, key: str) -> dict[str, object]:
            self.reads.append(key)
            return summary

        async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
            pytest.fail("stored Rule findings must not fall back to catalog-only evidence")

        async def write_state(self, key: str, value: dict[str, object]) -> None:
            pytest.fail("Rule findings admission is read-only")

    store = SummaryStore()
    before = deepcopy(summary)
    with pytest.raises(HTTPException, match="authoritative projection is unavailable") as error:
        await PostgresWorkflowAdapters(cast(Any, store)).read(_request())

    assert error.value.status_code == 503
    assert store.reads == ["operator-projection:workflow:rule.findings-summary"]
    assert summary == before


async def test_summary_read_failure_is_not_mistaken_for_an_absent_row() -> None:
    class FailedSummaryStore:
        async def read_state(self, key: str) -> None:
            assert key == "operator-projection:workflow:rule.findings-summary"
            raise PostgresFamilyStoreUnavailable("summary read unavailable")

        async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
            pytest.fail("failed reads must not become evaluated=false")

    with pytest.raises(HTTPException, match="summary read unavailable") as error:
        await PostgresWorkflowAdapters(cast(Any, FailedSummaryStore())).read(_request())
    assert error.value.status_code == 503


async def test_absent_summary_does_not_mask_rule_catalog_read_failure() -> None:
    class FailedCatalogStore:
        async def read_state(self, key: str) -> None:
            assert key == "operator-projection:workflow:rule.findings-summary"
            return None

        async def read_projection(self, *, family: str, operation: str) -> None:
            assert (family, operation) == ("workflow", "rule.list")
            raise PostgresFamilyStoreUnavailable("Rule catalog read unavailable")

    with pytest.raises(HTTPException, match="Rule catalog read unavailable") as error:
        await PostgresWorkflowAdapters(cast(Any, FailedCatalogStore())).read(_request())
    assert error.value.status_code == 503


def test_stored_summary_http_is_unavailable_without_provenance() -> None:
    class SummaryStore:
        async def read_state(self, key: str) -> dict[str, object]:
            assert key == "operator-projection:workflow:rule.findings-summary"
            return {"_revision": "unverified", "evaluated": True, "counts": {}}

    async def authorize(
        request: object, required_roles: frozenset[OperatorRole]
    ) -> OperatorPrincipal:
        del request
        assert OperatorRole.READER in required_roles
        return OperatorPrincipal("operator-a", frozenset({OperatorRole.READER}))

    class NoProposals:
        async def submit(self, proposal: object) -> None:
            pytest.fail("summary reads must not submit proposals")

    client = TestClient(
        Starlette(
            routes=list(
                build_workflow_family_routes(
                    authorize=authorize,
                    read_store=PostgresWorkflowAdapters(cast(Any, SummaryStore())),
                    proposal_writer=cast(Any, NoProposals()),
                )
            ),
            exception_handlers={HTTPException: http_exception_error},
        )
    )
    response = client.get("/rules/findings-summary")

    assert response.status_code == 503
    assert response.json() == {
        "error": {"status": 503, "message": "authoritative projection is unavailable"}
    }
    assert "x-fdai-provenance" not in response.headers
    assert "x-fdai-revision" not in response.headers
