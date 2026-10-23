"""Independent Azure readback for subscription tag actions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx
from fdai_service_contracts.executor_targets import resolve_azure_operation_target

from fdai.core.mscp_profile import ExpectedEffect, ObservedEffect
from fdai.shared.contracts.models import Action
from fdai.shared.providers.workload_identity import WorkloadIdentity

_ACTION_TYPE = "remediate.subscription-tag-add"
_AUDIENCE = "https://management.azure.com/.default"
_API_VERSION = "2021-04-01"
_SUBSCRIPTION_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_MAX_RESPONSE_BYTES = 32_768


class _TagEffectVerifier(Protocol):
    async def expected(self, action: Action) -> ExpectedEffect | None: ...

    async def observe(
        self,
        action: Action,
        expected: ExpectedEffect,
    ) -> ObservedEffect | None: ...


class AzureSubscriptionTagEffectVerifier:
    """Predict and read one subscription tag through a non-executor identity."""

    def __init__(
        self,
        *,
        subscription_id: str,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        if _SUBSCRIPTION_ID.fullmatch(subscription_id) is None:
            raise ValueError("subscription tag observer requires a valid subscription id")
        self._subscription_id = subscription_id
        self._identity = identity
        self._http = http_client

    async def expected(self, action: Action) -> ExpectedEffect | None:
        if action.action_type != _ACTION_TYPE:
            return None
        arguments = self._arguments(action)
        predicted_at = datetime.now(tz=UTC)
        material = (
            f"{action.action_id}\n{arguments['target_resource_ref']}\n"
            f"{arguments['tag_name']}\n{arguments['tag_value']}"
        )
        return ExpectedEffect(
            prediction_id=hashlib.sha256(material.encode("utf-8")).hexdigest(),
            target_ref=action.target_resource_ref,
            metric="subscription_tag_present",
            acceptable_min=1.0,
            acceptable_max=1.0,
            predicted_at=predicted_at,
            observation_deadline=predicted_at + timedelta(minutes=5),
        )

    async def observe(
        self,
        action: Action,
        expected: ExpectedEffect,
    ) -> ObservedEffect | None:
        if action.action_type != _ACTION_TYPE:
            return None
        arguments = self._arguments(action)
        token = await self._identity.get_token(_AUDIENCE)
        url = (
            f"https://management.azure.com/subscriptions/{self._subscription_id}/"
            f"providers/Microsoft.Resources/tags/default?api-version={_API_VERSION}"
        )
        async with self._http.stream(
            "GET",
            url,
            headers={"Authorization": f"Bearer {token.token}"},
            timeout=30.0,
        ) as response:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_RESPONSE_BYTES:
                    raise ValueError("subscription tag response exceeded its byte limit")
            if response.status_code >= 400:
                raise ValueError(f"subscription tag reader returned HTTP {response.status_code}")
        body = json.loads(content)
        properties = body.get("properties") if isinstance(body, Mapping) else None
        tags = properties.get("tags") if isinstance(properties, Mapping) else None
        if not isinstance(tags, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in tags.items()
        ):
            raise ValueError("subscription tag reader returned an invalid tag document")
        matches = tags.get(arguments["tag_name"]) == arguments["tag_value"]
        return ObservedEffect(
            prediction_id=expected.prediction_id,
            target_ref=action.target_resource_ref,
            metric=expected.metric,
            value=1.0 if matches else 0.0,
            observed_at=datetime.now(tz=UTC),
        )

    @staticmethod
    def _arguments(action: Action) -> dict[str, object]:
        arguments = dict(action.params)
        arguments.setdefault("target_resource_ref", action.target_resource_ref)
        target = resolve_azure_operation_target(action.action_type, arguments)
        if target.resource_ref != action.target_resource_ref:
            raise ValueError("subscription tag effect target does not match the action resource")
        return target.arguments


class TagEffectVerifierRouter:
    """Route subscription tag observation before an optional tag fallback."""

    def __init__(
        self,
        subscription: AzureSubscriptionTagEffectVerifier,
        fallback: _TagEffectVerifier | None,
    ) -> None:
        self._subscription = subscription
        self._fallback = fallback

    async def expected(self, action: Action) -> ExpectedEffect | None:
        result = await self._subscription.expected(action)
        if result is not None or self._fallback is None:
            return result
        return await self._fallback.expected(action)

    async def observe(
        self,
        action: Action,
        expected: ExpectedEffect,
    ) -> ObservedEffect | None:
        result = await self._subscription.observe(action, expected)
        if result is not None or self._fallback is None:
            return result
        return await self._fallback.observe(action, expected)


__all__ = ["AzureSubscriptionTagEffectVerifier", "TagEffectVerifierRouter"]
