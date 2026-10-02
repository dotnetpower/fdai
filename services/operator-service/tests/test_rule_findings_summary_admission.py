"""Fail-closed admission for optional Rule-findings summaries."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
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
from fdai_service_contracts.baseline_evaluation import (
    BaselineEvaluationCompletion,
    BaselineEvaluationOutcome,
    BaselineEvaluationTerminalOutcome,
    baseline_evaluation_completion_digest,
    baseline_evaluation_outcome_digest,
)
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.testclient import TestClient

NOW = datetime(2026, 10, 2, tzinfo=UTC)
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
DIGEST_E = "sha256:" + "e" * 64
DIGEST_F = "sha256:" + "f" * 64


@dataclass(frozen=True, slots=True)
class _Record:
    key: str
    value: dict[str, object]
    updated_at: datetime = NOW


@dataclass(frozen=True, slots=True)
class _Page:
    records: tuple[_Record, ...]
    truncated: bool = False


def _request() -> WorkflowReadRequest:
    return WorkflowReadRequest(
        operation=WorkflowOperation.RULE_FINDINGS_SUMMARY,
        principal_id="operator-a",
        query={},
        path_parameters={},
    )


def _outcome(
    rule_ref: str,
    resource_ref: str,
    outcome: BaselineEvaluationTerminalOutcome,
    *,
    reason_code: str | None = None,
) -> BaselineEvaluationOutcome:
    values: dict[str, object] = {
        "generation_id": "generation:one",
        "generation_digest": DIGEST_A,
        "inventory_observation_digest": DIGEST_B,
        "resource_ref": resource_ref,
        "resource_digest": DIGEST_C,
        "catalog_revision": DIGEST_D,
        "rule_ref": rule_ref,
        "rule_revision": DIGEST_E,
        "expected_denominator": 1,
        "outcome": outcome,
        "reason_code": reason_code,
        "evaluation_receipt_ref": "evaluation:" + resource_ref.rsplit(":", 1)[-1],
        "evaluation_receipt_digest": DIGEST_F,
        "saga_audit_ref": "audit:" + resource_ref.rsplit(":", 1)[-1],
        "saga_audit_digest": DIGEST_A,
        "evaluated_at": NOW,
        "execution_authority": False,
    }
    values["outcome_digest"] = baseline_evaluation_outcome_digest(**values)
    return BaselineEvaluationOutcome.model_validate(values)


def _completion(outcomes: tuple[BaselineEvaluationOutcome, ...]) -> BaselineEvaluationCompletion:
    totals = {"compliant": 0, "violated": 0, "abstained": 0}
    for item in outcomes:
        totals[item.outcome.value] += 1
    values: dict[str, object] = {
        "generation_id": "generation:one",
        "generation_digest": DIGEST_A,
        "inventory_observation_digest": DIGEST_B,
        "catalog_revision": DIGEST_D,
        "expected_denominator": len(outcomes),
        "compliant_count": totals["compliant"],
        "violated_count": totals["violated"],
        "abstained_count": totals["abstained"],
        "outcome_set_digest": _outcome_set_digest(outcomes),
        "completion_receipt_ref": "completion:one",
        "completion_receipt_digest": DIGEST_E,
        "saga_audit_ref": "audit:completion",
        "saga_audit_digest": DIGEST_F,
        "completed_at": NOW,
        "complete": True,
        "projection_authority": False,
        "execution_authority": False,
    }
    values["completion_digest"] = baseline_evaluation_completion_digest(**values)
    return BaselineEvaluationCompletion.model_validate(values)


def _outcome_set_digest(outcomes: tuple[BaselineEvaluationOutcome, ...]) -> str:
    ordered = sorted(outcomes, key=lambda item: (item.resource_ref, item.rule_ref))
    encoded = json.dumps(
        [item.outcome_digest for item in ordered],
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def test_absent_summary_preserves_catalog_provenanced_not_evaluated() -> None:
    class MissingSummaryStore:
        async def read_state(self, key: str) -> None:
            assert key == "operator-projection:workflow:rule.findings-summary"
            return None

        async def read_state_page(
            self,
            *,
            prefix: str,
            limit: int,
            match_field: str | None = None,
            match_value: str | None = None,
        ) -> _Page:
            del prefix, limit, match_field, match_value
            return _Page(())

        async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
            assert (family, operation) == ("workflow", "rule.list")
            return {"_revision": "catalog-sha256", "rules": [], "details": {}}

    result = await PostgresWorkflowAdapters(cast(Any, MissingSummaryStore())).read(_request())

    assert result.payload == {"evaluated": False, "counts": {}}
    assert result.provenance.revision == "catalog-sha256"
    assert result.provenance.source_ref == "state_kv:operator-projection:workflow:rule.list"


async def test_complete_outcomes_derive_authoritative_summary() -> None:
    outcomes = (
        _outcome("rule:one", "resource:one", BaselineEvaluationTerminalOutcome.VIOLATED),
        _outcome("rule:one", "resource:two", BaselineEvaluationTerminalOutcome.COMPLIANT),
        _outcome(
            "rule:two",
            "resource:one",
            BaselineEvaluationTerminalOutcome.ABSTAINED,
            reason_code="missing_evidence",
        ),
    )
    completion = _completion(outcomes)

    class SummaryStore:
        async def read_state(self, key: str) -> None:
            assert key == "operator-projection:workflow:rule.findings-summary"
            return None

        async def read_state_page(
            self,
            *,
            prefix: str,
            limit: int,
            match_field: str | None = None,
            match_value: str | None = None,
        ) -> _Page:
            del limit, match_field, match_value
            if prefix == "baseline-evaluation:completions:":
                return _Page((_Record("completion", completion.model_dump(mode="json")),))
            if prefix == "baseline-evaluation:outcomes:":
                return _Page(
                    tuple(
                        _Record(item.outcome_digest, item.model_dump(mode="json"))
                        for item in outcomes
                    )
                )
            raise AssertionError(prefix)

    result = await PostgresWorkflowAdapters(cast(Any, SummaryStore())).read(_request())

    assert result.payload["evaluated"] is True
    assert result.payload["complete"] is True
    assert result.payload["counts"] == {"rule:one": 1, "rule:two": 0}
    assert result.payload["expected_denominator"] == 3
    assert result.provenance.revision == completion.completion_digest


async def test_empty_complete_inventory_derives_evaluated_zero_without_inference() -> None:
    completion = _completion(())

    class SummaryStore:
        async def read_state(self, key: str) -> None:
            assert key == "operator-projection:workflow:rule.findings-summary"
            return None

        async def read_state_page(
            self,
            *,
            prefix: str,
            limit: int,
            match_field: str | None = None,
            match_value: str | None = None,
        ) -> _Page:
            del limit, match_field, match_value
            if prefix == "baseline-evaluation:completions:":
                return _Page((_Record("completion", completion.model_dump(mode="json")),))
            if prefix == "baseline-evaluation:outcomes:":
                return _Page(())
            raise AssertionError(prefix)

    result = await PostgresWorkflowAdapters(cast(Any, SummaryStore())).read(_request())

    assert result.payload["evaluated"] is True
    assert result.payload["counts"] == {}
    assert result.payload["expected_denominator"] == 0


async def test_partial_coverage_stays_unavailable() -> None:
    outcome = _outcome("rule:one", "resource:one", BaselineEvaluationTerminalOutcome.VIOLATED)
    completion = _completion((outcome,))
    completion_payload = completion.model_dump(mode="json")
    completion_payload["expected_denominator"] = 2

    class SummaryStore:
        async def read_state(self, key: str) -> None:
            assert key == "operator-projection:workflow:rule.findings-summary"
            return None

        async def read_state_page(
            self,
            *,
            prefix: str,
            limit: int,
            match_field: str | None = None,
            match_value: str | None = None,
        ) -> _Page:
            del limit, match_field, match_value
            if prefix == "baseline-evaluation:completions:":
                return _Page((_Record("completion", completion_payload),))
            return _Page((_Record("outcome", outcome.model_dump(mode="json")),))

    with pytest.raises(HTTPException, match="completion is malformed") as error:
        await PostgresWorkflowAdapters(cast(Any, SummaryStore())).read(_request())
    assert error.value.status_code == 503


def _valid_stored_summary() -> dict[str, object]:
    return {
        "_revision": "sha256:" + "1" * 64,
        "schema_version": "1.0.0",
        "evaluated": True,
        "complete": True,
        "generation_digest": DIGEST_A,
        "catalog_revision": DIGEST_D,
        "completion_digest": "sha256:" + "1" * 64,
        "expected_denominator": 1,
        "covered_denominator": 1,
        "counts": {"rule:one": 0},
    }


async def test_prior_complete_summary_is_admitted_without_recomputing() -> None:
    class SummaryStore:
        async def read_state(self, key: str) -> dict[str, object]:
            assert key == "operator-projection:workflow:rule.findings-summary"
            return _valid_stored_summary()

        async def read_state_page(self, **kwargs: object) -> _Page:
            pytest.fail("stored complete summary must preserve prior projection")

    result = await PostgresWorkflowAdapters(cast(Any, SummaryStore())).read(_request())

    assert result.payload["evaluated"] is True
    assert result.payload["counts"] == {"rule:one": 0}


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
    with pytest.raises(
        HTTPException,
        match="authoritative Rule findings summary is malformed",
    ) as error:
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
        "error": {
            "status": 503,
            "message": "authoritative Rule findings summary is malformed",
        }
    }
    assert "x-fdai-provenance" not in response.headers
    assert "x-fdai-revision" not in response.headers


def test_stored_complete_summary_http_returns_console_status() -> None:
    class SummaryStore:
        async def read_state(self, key: str) -> dict[str, object]:
            assert key == "operator-projection:workflow:rule.findings-summary"
            return _valid_stored_summary()

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

    assert response.status_code == 200
    assert response.json()["evaluated"] is True
    assert response.json()["counts"] == {"rule:one": 0}
    assert response.headers["x-fdai-revision"] == "sha256:" + "1" * 64
