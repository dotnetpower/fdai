"""Focused Operator route tests for Outcome Assurance read projections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.operations import PanelRoute, ProjectionQuery
from fdai_operator_service.families.operations.factory import build_operations_routes
from fdai_operator_service.family_adapters import UnavailableOperationsAdapters
from fdai_operator_service.runtime_projection_reader import (
    RuntimeProjectionReader,
    RuntimeProjectionReaderConfig,
)
from fdai_service_contracts import (
    OperatorRole,
    OutcomeAssuranceAttribution,
    OutcomeAssuranceAttributionState,
    OutcomeAssuranceConfidenceInterval,
    OutcomeAssuranceControlSummary,
    OutcomeAssuranceGuardEvaluation,
    OutcomeAssuranceGuardState,
    OutcomeAssuranceMetric,
    OutcomeAssuranceMetricState,
    OutcomeAssuranceProjection,
    OutcomeAssuranceProvenance,
    OutcomeAssuranceReadiness,
    OutcomeAssuranceReadinessFacet,
    OutcomeAssuranceReadinessState,
    OutcomeAssuranceReadState,
    OutcomeAssuranceScope,
    OutcomeAssuranceSource,
    OutcomeAssuranceSourceState,
    OutcomeAssuranceVertical,
    OutcomeAssuranceWindow,
)
from starlette.applications import Starlette
from starlette.testclient import TestClient

NOW = datetime(2026, 10, 4, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer ******"}


class _Fallback:
    async def read(self, query: ProjectionQuery) -> dict[str, object]:
        return {"operation": query.operation}


def _projection(*, expires_at: datetime, observed_at: datetime = NOW) -> OutcomeAssuranceProjection:
    return OutcomeAssuranceProjection(
        state=OutcomeAssuranceReadState.COMPLETE,
        scope=OutcomeAssuranceScope(
            scope_ref="scope.checkout",
            vertical=OutcomeAssuranceVertical.CHANGE_SAFETY,
        ),
        window=OutcomeAssuranceWindow(
            start=NOW - timedelta(days=30),
            end=NOW,
            label="30d",
        ),
        sources=(
            OutcomeAssuranceSource(
                name="outcome-assurance-measurement",
                state=OutcomeAssuranceSourceState.COMPLETE,
                observed_at=observed_at,
                expires_at=expires_at,
                evidence_refs=("measurement:change-safety",),
            ),
        ),
        readiness=(
            OutcomeAssuranceReadiness(
                facet=OutcomeAssuranceReadinessFacet.MEASUREMENT,
                state=OutcomeAssuranceReadinessState.READY,
                observed_at=observed_at,
                expires_at=expires_at,
                evidence_refs=("readiness:measurement",),
            ),
        ),
        alignment=OutcomeAssuranceAttribution(
            state=OutcomeAssuranceAttributionState.ATTRIBUTED,
            finalized_events=1,
            attributed_events=1,
            unattributed_events=0,
            coverage=1,
            objective_refs=("objective.change-failure-rate@1.0.0",),
            evidence_refs=("audit:event-1",),
        ),
        outcomes=(
            OutcomeAssuranceMetric(
                objective_ref="objective.change-failure-rate@1.0.0",
                metric="change_failure_rate",
                state=OutcomeAssuranceMetricState.MEASURED,
                current_value=0.02,
                baseline_value=0.03,
                target_value=0.025,
                unit="ratio",
                sample_size=48,
                confidence_interval=OutcomeAssuranceConfidenceInterval(low=0.01, high=0.03),
                source_time=NOW,
                evidence_refs=("measurement:change-failure-rate",),
            ),
        ),
        guards=OutcomeAssuranceControlSummary(
            state=OutcomeAssuranceGuardState.HEALTHY,
            guard_evaluations=(
                OutcomeAssuranceGuardEvaluation(
                    guard_id="policy_escape_zero",
                    threshold=0,
                    observed_value=0,
                    passed=True,
                    evidence_ref="guard:policy-escape-zero",
                ),
            ),
            evidence_refs=("promotion:change-safety",),
        ),
        provenance=OutcomeAssuranceProvenance(
            as_of=NOW,
            generated_at=NOW,
            source_names=("outcome-assurance-measurement",),
        ),
    )


def _client(reader: RuntimeProjectionReader) -> TestClient:
    authenticator = OperatorAuthenticator(
        verifier=lambda token: {
            "oid": "reader-id",
            "idtyp": "user",
            "roles": [OperatorRole.READER.value],
        },
        group_ids={},
    )
    unavailable = UnavailableOperationsAdapters()
    return TestClient(
        Starlette(
            routes=build_operations_routes(
                authenticator=authenticator,
                projection_reader=reader,
                proposal_writer=unavailable,
                replay_reader=unavailable,
                webhook_verifier=unavailable,
                panels=(
                    PanelRoute(
                        "/kpi/outcome-assurance",
                        "outcome_assurance",
                        "outcome_assurance",
                    ),
                ),
            )
        )
    )


def test_authentication_precedes_outcome_assurance_read(monkeypatch) -> None:
    calls: list[str] = []

    async def fetch_all(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, parameters
        calls.append(statement)
        return []

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch_all)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        _Fallback(),
    )

    response = _client(reader).get("/kpi/outcome-assurance")

    assert response.status_code == 401
    assert calls == []


def test_missing_projection_returns_typed_unavailable(monkeypatch) -> None:
    async def fetch_all(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, statement
        assert parameters[0].startswith("outcome-assurance:projection:v1:")
        return []

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch_all)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        _Fallback(),
    )

    response = _client(reader).get(
        "/kpi/outcome-assurance?scope_ref=scope.checkout&vertical=change_safety&window=30d",
        headers=HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "unavailable"
    assert payload["reason"] == "projection_missing"
    assert payload["outcomes"] == []
    assert payload["execution_authority"] is False


def test_stale_projection_drops_measured_values(monkeypatch) -> None:
    async def fetch_all(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [
            {
                "value": _projection(
                    expires_at=datetime(2026, 1, 1, tzinfo=UTC),
                    observed_at=datetime(2025, 12, 31, tzinfo=UTC),
                ).model_dump(mode="json")
            }
        ]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch_all)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        _Fallback(),
    )

    response = _client(reader).get("/kpi/outcome-assurance", headers=HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "stale"
    assert payload["reason"] == "source_stale"
    assert payload["outcomes"][0]["state"] == "stale"
    assert payload["outcomes"][0]["current_value"] is None
    assert payload["guards"]["state"] == "stale"


def test_complete_projection_is_returned_without_authority(monkeypatch) -> None:
    async def fetch_all(
        self: RuntimeProjectionReader,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> list[dict[str, object]]:
        del self, statement, parameters
        return [
            {
                "value": _projection(
                    expires_at=datetime(2100, 1, 1, tzinfo=UTC),
                ).model_dump(mode="json")
            }
        ]

    monkeypatch.setattr(RuntimeProjectionReader, "_fetch_all", fetch_all)
    reader = RuntimeProjectionReader(
        RuntimeProjectionReaderConfig("postgresql://example.invalid/fdai"),
        _Fallback(),
    )

    response = _client(reader).get("/kpi/outcome-assurance", headers=HEADERS)

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "complete"
    assert payload["outcomes"][0]["current_value"] == 0.02
    assert payload["principal_scoped"] is True
    assert payload["execution_authority"] is False
    assert payload["approval_authority"] is False
    assert payload["promotion_authority"] is False
