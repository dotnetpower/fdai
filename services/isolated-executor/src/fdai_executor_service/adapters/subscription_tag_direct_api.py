"""Direct Azure subscription-tag execution for the isolated Executor."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx
from fdai_service_contracts.executor import (
    AzureOperationTarget,
    DirectApiAuthenticationError,
    DirectApiError,
    DirectApiExecutor,
    DirectApiOutcome,
    DirectApiPermissionDeniedError,
    DirectApiPreconditionError,
    DirectApiPromotionError,
    DirectApiReceipt,
    DirectApiRequest,
    Mode,
    WorkloadIdentity,
    resolve_azure_operation_target,
)

_ACTION_TYPE = "remediate.subscription-tag-add"
_AUDIENCE = "https://management.azure.com/.default"
_API_VERSION = "2021-04-01"
_SUBSCRIPTION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_MAX_RESPONSE_BYTES = 32_768


@dataclass(frozen=True, slots=True)
class AzureSubscriptionTagConfig:
    """Exact subscription boundary for the temporary development action."""

    subscription_id: str

    def __post_init__(self) -> None:
        if _SUBSCRIPTION_ID.fullmatch(self.subscription_id) is None:
            raise ValueError("subscription tag executor requires a valid subscription id")


class AzureSubscriptionTagDirectApiExecutor:
    """Apply one reversible subscription tag through the change identity."""

    def __init__(
        self,
        *,
        config: AzureSubscriptionTagConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._identity = identity
        self._http = http_client

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name != _ACTION_TYPE:
            raise DirectApiPreconditionError("subscription tag executor received another action")
        if request.mode is Mode.ENFORCE and "enforce" not in request.labels:
            raise DirectApiPromotionError(
                "enforce-mode subscription tag call requires an explicit enforce label"
            )
        target = self._target(request)
        tag_name = target.arguments.get("tag_name")
        tag_value = target.arguments.get("tag_value")
        if not isinstance(tag_name, str) or not isinstance(tag_value, str):
            raise DirectApiPreconditionError("subscription tag action requires bounded tag text")
        prior = await self._read_tags()
        if request.mode is Mode.SHADOW:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"azure-subscription-tag-plan:{request.action_id}",
                detail="subscription tag preflight verified; no mutation submitted",
            )

        await self._write_tags(
            operation="Merge",
            tags={tag_name: tag_value},
        )
        observed = await self._read_tags()
        if observed.get(tag_name) == tag_value:
            return DirectApiReceipt(
                outcome=DirectApiOutcome.SUCCEEDED,
                receipt_ref=f"azure-subscription-tag:{request.idempotency_key}",
                rollback_succeeded=False,
                detail="subscription tag mutation independently read back",
            )

        await self._write_tags(operation="Replace", tags=prior)
        if await self._read_tags() != prior:
            raise DirectApiError(
                "rollback_failed",
                "subscription tag rollback could not restore the prior snapshot",
            )
        raise DirectApiError(
            "effect_verification_failed",
            "subscription tag readback mismatched and the prior snapshot was restored",
        )

    @staticmethod
    def _target(request: DirectApiRequest) -> AzureOperationTarget:
        try:
            target = resolve_azure_operation_target(
                request.action_type_name,
                request.arguments,
            )
        except ValueError as exc:
            raise DirectApiPreconditionError(str(exc)) from exc
        if target.resource_ref != request.resource_ref:
            raise DirectApiPreconditionError(
                "subscription tag resource_ref MUST match the canonical target"
            )
        if request.metadata.get("executor_identity_ref") != "identity/change":
            raise DirectApiPreconditionError(
                "subscription tag action requires the change executor identity"
            )
        if request.metadata.get("rollback_ref") != "snapshot_restore":
            raise DirectApiPreconditionError(
                "subscription tag action requires snapshot_restore rollback"
            )
        if request.metadata.get("max_resources") != "1":
            raise DirectApiPreconditionError("subscription tag action requires max_resources=1")
        return target

    async def _read_tags(self) -> dict[str, str]:
        body = await self._request("GET")
        properties = body.get("properties")
        tags = properties.get("tags") if isinstance(properties, Mapping) else None
        if not isinstance(tags, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in tags.items()
        ):
            raise DirectApiError(
                "invalid_response",
                "Azure subscription tag response did not contain a string map",
            )
        return dict(tags)

    async def _write_tags(self, *, operation: str, tags: Mapping[str, str]) -> None:
        body = await self._request(
            "PATCH",
            json_body={"operation": operation, "properties": {"tags": dict(tags)}},
        )
        if not isinstance(body.get("properties"), Mapping):
            raise DirectApiError(
                "invalid_response",
                "Azure subscription tag mutation returned an invalid response",
            )

    async def _request(
        self,
        method: str,
        *,
        json_body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        token = await self._identity.get_token(_AUDIENCE)
        path = (
            f"https://management.azure.com/subscriptions/{self._config.subscription_id}/"
            f"providers/Microsoft.Resources/tags/default?api-version={_API_VERSION}"
        )
        try:
            async with self._http.stream(
                method,
                path,
                headers={"Authorization": f"Bearer {token.token}"},
                json=json_body,
                timeout=30.0,
            ) as response:
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > _MAX_RESPONSE_BYTES:
                        raise DirectApiError(
                            "invalid_response",
                            "Azure subscription tag response exceeded its byte limit",
                        )
                status_code = response.status_code
        except httpx.HTTPError as exc:
            raise DirectApiError(
                "transport",
                "Azure subscription tag request failed",
            ) from exc
        if status_code == 401:
            raise DirectApiAuthenticationError("Azure rejected subscription tag authentication")
        if status_code == 403:
            raise DirectApiPermissionDeniedError("Azure denied the subscription tag executor")
        if status_code >= 400:
            raise DirectApiError(
                "azure",
                f"Azure subscription tag request returned HTTP {status_code}",
            )
        try:
            body = json.loads(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise DirectApiError(
                "invalid_response",
                "Azure subscription tag response was not JSON",
            ) from exc
        if not isinstance(body, Mapping):
            raise DirectApiError(
                "invalid_response",
                "Azure subscription tag response was not an object",
            )
        return body


@runtime_checkable
class _OperationStatusReader(Protocol):
    async def operation_status(self, request: DirectApiRequest) -> DirectApiReceipt | None: ...


class SubscriptionTagDirectApiRouter:
    """Route the subscription tag action before an optional provider fallback."""

    def __init__(
        self,
        subscription_tag: DirectApiExecutor,
        fallback: DirectApiExecutor | None,
    ) -> None:
        self._subscription_tag = subscription_tag
        self._fallback = fallback

    async def execute(self, request: DirectApiRequest) -> DirectApiReceipt:
        if request.action_type_name == _ACTION_TYPE:
            return await self._subscription_tag.execute(request)
        if self._fallback is None:
            raise DirectApiPreconditionError("direct-API action has no isolated Executor adapter")
        return await self._fallback.execute(request)

    async def operation_status(self, request: DirectApiRequest) -> DirectApiReceipt | None:
        if request.action_type_name == _ACTION_TYPE:
            return None
        if isinstance(self._fallback, _OperationStatusReader):
            return await self._fallback.operation_status(request)
        return None


__all__ = [
    "AzureSubscriptionTagConfig",
    "AzureSubscriptionTagDirectApiExecutor",
    "SubscriptionTagDirectApiRouter",
]
