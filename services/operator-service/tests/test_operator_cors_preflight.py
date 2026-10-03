"""Cross-origin preflight for Console mutations that carry an optimistic revision."""

from __future__ import annotations

import pytest
from fdai_operator_service.application import create_app
from fdai_operator_service.composition import ProductionOperatorComposition
from fdai_operator_service.environment import CORS_ORIGINS_ENV
from starlette.testclient import TestClient

from .test_operator_service_composition import BASE_ENV, EmptyReadModel, _verify


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/workflows/definitions"),
        ("POST", "/workflows/bindings"),
        ("DELETE", "/workflows/bindings/binding-1"),
    ],
)
def test_cors_preflight_allows_the_if_match_revision_header(method: str, path: str) -> None:
    client = TestClient(
        create_app(
            {**BASE_ENV, CORS_ORIGINS_ENV: "http://localhost:5273"},
            composition=ProductionOperatorComposition(
                verifier_factory=lambda environment: _verify,
                read_model=EmptyReadModel(),
            ),
        )
    )

    response = client.options(
        path,
        headers={
            "Origin": "http://localhost:5273",
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type,idempotency-key,if-match",
        },
    )

    assert response.status_code == 200
    allowed = {
        value.strip().casefold()
        for value in response.headers["access-control-allow-headers"].split(",")
    }
    assert {"authorization", "content-type", "idempotency-key", "if-match"} <= allowed


def test_cors_exposes_the_committed_revision_header_to_the_console() -> None:
    # Workflow draft and binding writes return the committed revision only in X-FDAI-Revision,
    # so a cross-origin Console cannot read it unless CORS exposes the header.
    client = TestClient(
        create_app(
            {**BASE_ENV, CORS_ORIGINS_ENV: "http://localhost:5273"},
            composition=ProductionOperatorComposition(
                verifier_factory=lambda environment: _verify,
                read_model=EmptyReadModel(),
            ),
        )
    )

    response = client.get("/healthz", headers={"Origin": "http://localhost:5273"})

    exposed = {
        value.strip().casefold()
        for value in response.headers["access-control-expose-headers"].split(",")
    }
    assert "x-fdai-revision" in exposed
