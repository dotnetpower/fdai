"""Run the independent Operator Service with automated-test identity verification."""

from __future__ import annotations

import os
from collections.abc import Mapping
from uuid import uuid4

import uvicorn
from fdai_operator_service.application import create_app
from fdai_operator_service.auth import AuthenticationError
from fdai_operator_service.composition import ProductionOperatorComposition
from fdai_operator_service.contracts import AsgiApplication
from fdai_operator_service.environment import LIVE_STAGE_CONSUMER_GROUP_ENV
from fdai_service_contracts import OperatorRole

LIVE_E2E_CONSUMER_GROUP_PREFIX = "fdai-operator-live-e2e-"


def _verify_test_token(token: str) -> Mapping[str, object]:
    if token != os.environ["FDAI_E2E_BEARER"]:
        raise AuthenticationError("invalid live E2E bearer token")
    return {
        "oid": "live-e2e-operator",
        "roles": [
            OperatorRole.READER.value,
            OperatorRole.CONTRIBUTOR.value,
            OperatorRole.APPROVER.value,
            OperatorRole.OWNER.value,
        ],
    }


def build_app() -> AsgiApplication:
    """Build production data adapters with test-only bearer verification."""
    composition = ProductionOperatorComposition(
        verifier_factory=lambda _environment: _verify_test_token,
    )
    environment = dict(os.environ)
    environment[LIVE_STAGE_CONSUMER_GROUP_ENV] = f"{LIVE_E2E_CONSUMER_GROUP_PREFIX}{uuid4()}"
    return create_app(environment, composition=composition)


if __name__ == "__main__":
    uvicorn.run(
        build_app(),
        host="::1",
        port=int(os.environ.get("FDAI_E2E_OPERATOR_API_PORT", "8020")),
        access_log=False,
    )
