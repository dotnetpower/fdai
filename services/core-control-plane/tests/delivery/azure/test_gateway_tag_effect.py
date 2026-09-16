from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from fdai.delivery.azure.gateway_tag_effect import GatewayTagEffectVerifier
from fdai.shared.contracts.models import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
)
from fdai.shared.providers.workload_identity import IdentityToken

TARGET = (
    "scope-0123456789abcdef/resource-group/rg-example/"
    "providers/microsoft.storage/storageaccounts/storage-app"
)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="reader-token",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _action() -> Action:
    return Action(
        schema_version="1.0.0",
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="tag-effect-one",
        event_id=UUID("00000000-0000-0000-0000-000000000002"),
        action_type="remediate.tag-add",
        target_resource_ref=TARGET,
        operation=Operation.TAG,
        params={
            "target_resource_ref": TARGET,
            "tag_name": "environment",
            "tag_value": "dev",
        },
        stop_condition=StopConditionKind.PROVIDER_API_ERROR_STREAK.value,
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=5,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SNAPSHOT_RESTORE),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=Mode.ENFORCE,
        citing_rules=["object-storage.owner-tag.required"],
        created_at=datetime.now(tz=UTC),
    )


async def test_tag_effect_verifier_reads_exact_tag_without_executor_receipt() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "operation_id": "azure.resource.tags.read",
                "status": "succeeded",
                "result": {"matches": True, "present": True},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = GatewayTagEffectVerifier(
            base_url="https://gateway.example.com",
            audience="gateway-audience",
            identity=_Identity(),
            http_client=client,
        )
        action = _action()
        expected = await verifier.expected(action)
        assert expected is not None
        observed = await verifier.observe(action, expected)

    assert observed is not None
    assert observed.value == 1.0
    assert observed.prediction_id == expected.prediction_id
    assert requests[0].url.path.endswith("/azure.resource.tags.read")
    body = requests[0].read().decode()
    assert '"target_resource_ref":"' + TARGET + '"' in body
    assert '"tag_name":"environment"' in body
    assert '"tag_value":"dev"' in body


async def test_tag_effect_verifier_rejects_non_https_gateway() -> None:
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="HTTPS origin"):
            GatewayTagEffectVerifier(
                base_url="http://gateway.example.com",
                audience="gateway-audience",
                identity=_Identity(),
                http_client=client,
            )
