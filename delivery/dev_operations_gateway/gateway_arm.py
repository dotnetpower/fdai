"""Bounded Azure Resource Manager transport for the development gateway."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

import httpx

from delivery.dev_operations_gateway.gateway_contracts import (
    _ARM_AUDIENCE,
    GatewayConfig,
    GatewayError,
    TokenProvider,
)


@dataclass(frozen=True, slots=True)
class _ArmSubmission:
    status_url: str


class ArmClient:
    def __init__(
        self,
        *,
        config: GatewayConfig,
        reader_token_provider: TokenProvider,
        executor_token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._config = config
        self._reader_tokens = reader_token_provider
        self._executor_tokens = executor_token_provider
        self._http = http_client
        self._sleep = sleep

    async def request(
        self,
        method: str,
        path: str,
        *,
        api_version: str,
        json_body: Mapping[str, object] | None = None,
        executor: bool = False,
        request_headers: Mapping[str, str] | None = None,
    ) -> object:
        token_provider = self._executor_tokens if executor else self._reader_tokens
        token = await token_provider.get_token(_ARM_AUDIENCE)
        for attempt in range(3):
            response = await self._http.request(
                method,
                f"https://management.azure.com{path}",
                params={"api-version": api_version},
                headers={
                    "Authorization": f"Bearer {token}",
                    **(request_headers or {}),
                },
                json=json_body,
                timeout=30.0,
            )
            if response.status_code != 429 or attempt == 2:
                break
            await self._sleep(_retry_after_seconds(response))
        if response.status_code == 404:
            raise GatewayError(404, "azure_resource_not_found", "Azure resource was not found")
        if response.status_code == 412:
            raise GatewayError(
                409,
                "target_revision_changed",
                "Azure resource changed after the scale-out observation",
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise GatewayError(
                503,
                "azure_temporarily_unavailable",
                f"Azure operation returned retryable HTTP {response.status_code}",
            )
        if response.status_code >= 400:
            raise GatewayError(
                502,
                "azure_operation_failed",
                f"Azure operation returned HTTP {response.status_code}",
            )
        if response.status_code == 202:
            status_url = response.headers.get("Azure-AsyncOperation") or response.headers.get(
                "Location"
            )
            if not status_url:
                raise GatewayError(
                    502,
                    "azure_response_invalid",
                    "Azure accepted the operation without a status URL",
                )
            self._validate_status_url(status_url)
            return _ArmSubmission(status_url=status_url)
        if response.status_code == 204 or not response.content:
            return {"accepted": True}
        body = response.json()
        if not isinstance(body, (Mapping, list)):
            raise GatewayError(502, "azure_response_invalid", "Azure response was not JSON")
        return body

    async def poll_status(self, status_url: str) -> str:
        self._validate_status_url(status_url)
        token = await self._executor_tokens.get_token(_ARM_AUDIENCE)
        for attempt in range(3):
            response = await self._http.get(
                status_url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=30.0,
            )
            if response.status_code != 429 or attempt == 2:
                break
            await self._sleep(_retry_after_seconds(response))
        if response.status_code == 404:
            raise GatewayError(
                404,
                "azure_operation_not_found",
                "Azure operation status was not found",
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise GatewayError(
                503,
                "azure_temporarily_unavailable",
                f"Azure operation status returned retryable HTTP {response.status_code}",
            )
        if response.status_code >= 400:
            raise GatewayError(
                502,
                "azure_operation_failed",
                f"Azure operation status returned HTTP {response.status_code}",
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure operation status was not JSON",
            ) from exc
        provider_status = body.get("status") if isinstance(body, Mapping) else None
        if not isinstance(provider_status, str) or not provider_status:
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure operation status was missing",
            )
        return provider_status[:64]

    def _validate_status_url(self, status_url: str) -> None:
        parsed = urlparse(status_url)
        subscription_prefix = f"/subscriptions/{self._config.subscription_id}/".casefold()
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "management.azure.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not parsed.path.casefold().startswith(subscription_prefix)
            or len(query) > 1
            or any(key != "api-version" or not value or len(value) > 64 for key, value in query)
        ):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure operation status URL was outside the configured subscription",
            )


def _retry_after_seconds(response: httpx.Response) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        delay = float(raw)
    except ValueError:
        return 1.0
    return min(5.0, max(0.0, delay))
