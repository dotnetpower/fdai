from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from fdai.delivery.azure.subscription_tag_effect import (
    AzureSubscriptionTagEffectVerifier,
)
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

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_TARGET = "scope-0123456789abcdef/subscription"


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
        idempotency_key="subscription-tag-one",
        event_id=UUID("00000000-0000-0000-0000-000000000002"),
        action_type="remediate.subscription-tag-add",
        target_resource_ref=_TARGET,
        operation=Operation.TAG,
        params={
            "target_resource_ref": _TARGET,
            "tag_name": "fdai-live-check",
            "tag_value": "issue-1623",
        },
        stop_condition=StopConditionKind.PROVIDER_API_ERROR_STREAK.value,
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.PROVIDER_API_ERROR_STREAK,
                count=3,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SNAPSHOT_RESTORE),
        blast_radius=BlastRadius(scope=BlastRadiusScope.SUBSCRIPTION, count=1),
        mode=Mode.ENFORCE,
        citing_rules=["operator.request.remediate.subscription-tag-add"],
        created_at=datetime.now(tz=UTC),
    )


async def test_subscription_tag_effect_reads_with_independent_identity() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "properties": {
                    "tags": {
                        "fdai-live-check": "issue-1623",
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verifier = AzureSubscriptionTagEffectVerifier(
            subscription_id=_SUBSCRIPTION,
            identity=_Identity(),
            http_client=client,
        )
        action = _action()
        expected = await verifier.expected(action)
        assert expected is not None
        observed = await verifier.observe(action, expected)

    assert observed is not None
    assert observed.value == 1.0
    assert requests[0].method == "GET"
    assert f"/subscriptions/{_SUBSCRIPTION}/" in requests[0].url.path
