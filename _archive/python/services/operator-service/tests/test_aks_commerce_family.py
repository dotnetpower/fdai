from datetime import UTC, datetime, timedelta

from fdai_operator_service.auth import OperatorAuthenticator
from fdai_operator_service.families.aks_commerce import (
    AksCommerceFamilyDependencies,
    build_aks_commerce_routes,
)
from fdai_service_contracts import (
    AksCommerceEvidenceState,
    AksCommerceProjection,
    AksCommerceSlo,
    AksCommerceStatus,
    AksCommerceWorkload,
    OperatorRole,
)
from starlette.applications import Starlette
from starlette.testclient import TestClient

NOW = datetime(2026, 9, 17, tzinfo=UTC)
HEADERS = {"Authorization": "Bearer test-token"}


class _Reader:
    def __init__(self, projection: AksCommerceProjection | None) -> None:
        self.projection = projection
        self.calls: list[str] = []

    async def read_latest(self, service_id: str) -> AksCommerceProjection | None:
        self.calls.append(service_id)
        return self.projection


def _projection() -> AksCommerceProjection:
    return AksCommerceProjection(
        assessment_id=f"sha256:{'a' * 64}",
        service_id="order-fulfillment",
        status=AksCommerceStatus.HEALTHY,
        summary="Order fulfillment is healthy for the assessed window.",
        observed_at=NOW,
        window_start=NOW - timedelta(minutes=5),
        window_end=NOW,
        complete=True,
        synthetic=False,
        dependency_path=("order-api",),
        workloads=(
            AksCommerceWorkload(
                workload_id="order-api",
                display_name="Order API",
                resource_ref="resource:order-api",
                ready=True,
                revision="revision-1",
                evidence_state=AksCommerceEvidenceState.COMPLETE,
            ),
        ),
        slos=(
            AksCommerceSlo(
                slo_id="order-fulfillment.availability",
                objective_ratio=0.99,
                observed_ratio=1,
                budget_remaining_ratio=1,
                breached=False,
                state=AksCommerceEvidenceState.COMPLETE,
                source_ref="source:synthetic",
            ),
        ),
        evidence_refs=("evidence:one",),
    )


def _client(reader: _Reader) -> TestClient:
    authenticator = OperatorAuthenticator(
        verifier=lambda token: {
            "oid": "reader-id",
            "idtyp": "user",
            "roles": [OperatorRole.READER.value],
        },
        group_ids={},
    )
    return TestClient(
        Starlette(
            routes=build_aks_commerce_routes(
                AksCommerceFamilyDependencies(
                    authenticator=authenticator,
                    projections=reader,
                )
            )
        )
    )


def test_authentication_precedes_projection_read() -> None:
    reader = _Reader(_projection())

    response = _client(reader).get("/aks-commerce/overview")

    assert response.status_code == 401
    assert reader.calls == []


def test_reader_projection_is_returned_without_reinterpretation() -> None:
    reader = _Reader(_projection())

    response = _client(reader).get(
        "/aks-commerce/overview?service_id=order-fulfillment",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json()["assessment_id"] == f"sha256:{'a' * 64}"
    assert response.json()["execution_authority"] is False
    assert reader.calls == ["order-fulfillment"]


def test_missing_projection_is_explicitly_unavailable() -> None:
    response = _client(_Reader(None)).get(
        "/aks-commerce/overview?service_id=catalog-browse",
        headers=HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "projection_unavailable"


def test_unknown_service_is_rejected_before_read() -> None:
    reader = _Reader(_projection())

    response = _client(reader).get(
        "/aks-commerce/overview?service_id=payments",
        headers=HEADERS,
    )

    assert response.status_code == 400
    assert reader.calls == []
