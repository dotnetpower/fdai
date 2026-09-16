"""Independent reader-identity verification for development tag remediation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
from fdai_service_contracts.executor_targets import resolve_azure_operation_target

from fdai.core.mscp_profile import ExpectedEffect, ObservedEffect
from fdai.shared.contracts.models import Action
from fdai.shared.providers.workload_identity import WorkloadIdentity

_ACTION_TYPE = "remediate.tag-add"
_OPERATION = "azure.resource.tags.read"
_MAX_RESPONSE_BYTES = 32_768


class GatewayTagEffectVerifier:
    """Predict and independently read back one exact tag through the dev gateway."""

    def __init__(
        self,
        *,
        base_url: str,
        audience: str,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
    ) -> None:
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("tag effect gateway base_url MUST be an HTTPS origin")
        if not audience or len(audience) > 256:
            raise ValueError("tag effect gateway audience MUST be bounded")
        self._base_url = base_url.rstrip("/")
        self._audience = audience
        self._identity = identity
        self._http = http_client

    async def expected(self, action: Action) -> ExpectedEffect | None:
        """Return an exact tag-presence prediction for the supported ActionType."""

        if action.action_type != _ACTION_TYPE:
            return None
        arguments = self._arguments(action)
        predicted_at = datetime.now(tz=UTC)
        prediction_material = (
            f"{action.action_id}\n{arguments['target_resource_ref']}\n"
            f"{arguments['tag_name']}\n{arguments['tag_value']}"
        )
        prediction_id = hashlib.sha256(prediction_material.encode("utf-8")).hexdigest()
        return ExpectedEffect(
            prediction_id=prediction_id,
            target_ref=action.target_resource_ref,
            metric="resource_tag_present",
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
        """Read through the gateway's reader identity without executor receipt input."""

        if action.action_type != _ACTION_TYPE:
            return None
        token = await self._identity.get_token(self._audience)
        async with self._http.stream(
            "POST",
            f"{self._base_url}/api/v1/operations/{_OPERATION}",
            headers={"Authorization": f"Bearer {token.token}"},
            json=self._arguments(action),
            timeout=30.0,
        ) as response:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_RESPONSE_BYTES:
                    raise ValueError("tag effect response exceeded its byte limit")
            if response.status_code >= 400:
                raise ValueError(f"tag effect reader returned HTTP {response.status_code}")
        body = json.loads(content)
        if not isinstance(body, Mapping) or body.get("operation_id") != _OPERATION:
            raise ValueError("tag effect reader returned an invalid operation")
        result = body.get("result")
        if (
            body.get("status") != "succeeded"
            or not isinstance(result, Mapping)
            or type(result.get("matches")) is not bool
        ):
            raise ValueError("tag effect reader returned an invalid result")
        return ObservedEffect(
            prediction_id=expected.prediction_id,
            target_ref=action.target_resource_ref,
            metric=expected.metric,
            value=1.0 if result["matches"] else 0.0,
            observed_at=datetime.now(tz=UTC),
        )

    @staticmethod
    def _arguments(action: Action) -> dict[str, object]:
        arguments = dict(action.params)
        arguments.setdefault("target_resource_ref", action.target_resource_ref)
        target = resolve_azure_operation_target(_ACTION_TYPE, arguments)
        if target.resource_ref != action.target_resource_ref:
            raise ValueError("tag effect target does not match the action resource")
        return target.arguments


__all__ = ["GatewayTagEffectVerifier"]
