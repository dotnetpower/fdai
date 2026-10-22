from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from fdai_executor_service.adapters.subscription_tag_direct_api import (
    AzureSubscriptionTagConfig,
    AzureSubscriptionTagDirectApiExecutor,
)
from fdai_service_contracts.executor import (
    DirectApiOutcome,
    DirectApiRequest,
    IdentityToken,
    Mode,
)

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_TARGET = "scope-0123456789abcdef/subscription"


class _Identity:
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="executor-token",
            expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
            audience=audience,
        )


def _request(mode: Mode) -> DirectApiRequest:
    return DirectApiRequest(
        action_id=UUID("00000000-0000-0000-0000-000000000001"),
        idempotency_key="subscription-tag-one",
        action_type_name="remediate.subscription-tag-add",
        rule_ids=("operator.request.remediate.subscription-tag-add",),
        resource_ref=_TARGET,
        arguments={
            "target_resource_ref": _TARGET,
            "tag_name": "fdai-live-check",
            "tag_value": "issue-1623",
        },
        labels=("enforce",) if mode is Mode.ENFORCE else ("shadow",),
        mode=mode,
        metadata={
            "audit_ref": "action:subscription-tag-one",
            "stop_condition": "provider_api_error_streak",
            "rollback_ref": "snapshot_restore",
            "max_resources": "1",
            "executor_identity_ref": "identity/change",
        },
    )


async def test_subscription_tag_executor_plans_then_verifies_mutation() -> None:
    requests: list[httpx.Request] = []
    reads = iter(
        (
            {"properties": {"tags": {"owner": "platform"}}},
            {
                "properties": {
                    "tags": {
                        "owner": "platform",
                        "fdai-live-check": "issue-1623",
                    }
                }
            },
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=next(reads))
        return httpx.Response(
            200,
            json={"properties": {"tags": {"fdai-live-check": "issue-1623"}}},
        )

    identity = _Identity()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureSubscriptionTagDirectApiExecutor(
            config=AzureSubscriptionTagConfig(subscription_id=_SUBSCRIPTION),
            identity=identity,
            http_client=client,
        ).execute(_request(Mode.ENFORCE))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert [request.method for request in requests] == ["GET", "PATCH", "GET"]
    assert all(f"/subscriptions/{_SUBSCRIPTION}/" in request.url.path for request in requests)
    assert identity.audiences == [
        "https://management.azure.com/.default",
        "https://management.azure.com/.default",
        "https://management.azure.com/.default",
    ]


async def test_subscription_tag_executor_shadow_only_reads_current_tags() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"properties": {"tags": {}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        receipt = await AzureSubscriptionTagDirectApiExecutor(
            config=AzureSubscriptionTagConfig(subscription_id=_SUBSCRIPTION),
            identity=_Identity(),
            http_client=client,
        ).execute(_request(Mode.SHADOW))

    assert receipt.outcome is DirectApiOutcome.SUCCEEDED
    assert [request.method for request in requests] == ["GET"]
