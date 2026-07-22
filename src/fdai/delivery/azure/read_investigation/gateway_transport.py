"""Read-only Azure investigation transport through the development gateway."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from fdai.delivery.azure.read_investigation.transport import AzureReadTransport, AzureRow
from fdai.shared.providers.read_investigation import ReadToolLimits, ResourceSelector
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MAX_RESPONSE_BYTES = 262_144


class AzureOperationsGatewayReadError(RuntimeError):
    """A registered gateway read failed without exposing raw response data."""


@dataclass(frozen=True, slots=True)
class AzureOperationsGatewayReadConfig:
    base_url: str
    audience: str
    subscription_id: str
    resource_groups: tuple[str, ...]

    def __post_init__(self) -> None:
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("operations gateway base_url MUST be an HTTPS origin")
        for name, value in (
            ("audience", self.audience),
            ("subscription_id", self.subscription_id),
        ):
            if not value or len(value) > 256 or "\x00" in value:
                raise ValueError(f"operations gateway {name} MUST be bounded")
        if not self.resource_groups or len(set(self.resource_groups)) != len(self.resource_groups):
            raise ValueError("operations gateway resource_groups MUST be unique and non-empty")
        for resource_group in self.resource_groups:
            if not resource_group or len(resource_group) > 128 or "/" in resource_group:
                raise ValueError("operations gateway resource groups MUST be bounded")


class AzureOperationsGatewayReadTransport:
    """Route fixed network reads through the gateway and delegate all other reads."""

    transport_id = "rest"

    def __init__(
        self,
        *,
        config: AzureOperationsGatewayReadConfig,
        delegate: AzureReadTransport,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if delegate.transport_id != "rest":
            raise ValueError("operations gateway delegate MUST be a REST transport")
        self._config = config
        self._delegate = delegate
        self._identity = identity
        self._http = http_client
        self._clock = clock or (lambda: datetime.now(tz=UTC))

    async def resolve_resources(
        self, selector: ResourceSelector, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        return await self._delegate.resolve_resources(selector, limits=limits)

    async def get_resource_state(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        return await self._delegate.get_resource_state(provider_ref, limits=limits)

    async def query_resource_activity(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        return await self._delegate.query_resource_activity(
            provider_ref, lookback_seconds=lookback_seconds, limits=limits
        )

    async def query_resource_health(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        return await self._delegate.query_resource_health(
            provider_ref, lookback_seconds=lookback_seconds, limits=limits
        )

    async def query_guest_shutdown_events(
        self,
        provider_ref: str,
        *,
        lookback_seconds: int,
        limits: ReadToolLimits,
    ) -> Sequence[AzureRow]:
        return await self._delegate.query_guest_shutdown_events(
            provider_ref, lookback_seconds=lookback_seconds, limits=limits
        )

    async def query_network_security(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        resource_group, name = self._resource(provider_ref, "networkSecurityGroups")
        result = await self._invoke(
            "azure.network.nsg.read",
            {"resource_group": resource_group, "nsg_name": name},
        )
        rules = result.get("rules")
        if not isinstance(rules, list):
            raise AzureOperationsGatewayReadError("gateway NSG result did not contain rules")
        observed_at = self._clock().isoformat()
        rows: list[AzureRow] = []
        for rule in rules[: limits.max_results]:
            if not isinstance(rule, Mapping):
                continue
            rows.append(
                {
                    "observed_at": observed_at,
                    "status": _text(rule.get("access"), 16),
                    "rule_name": _text(rule.get("name"), 128),
                    "rule_kind": _text(rule.get("kind"), 16),
                    "direction": _text(rule.get("direction"), 16),
                    "protocol": _text(rule.get("protocol"), 16),
                    "source_prefixes": _text(rule.get("source_address_prefix"), 512),
                    "source_ports": _text(rule.get("source_port_range"), 512),
                    "destination_prefixes": _text(rule.get("destination_address_prefix"), 512),
                    "destination_ports": _text(rule.get("destination_port_range"), 512),
                    "priority": rule.get("priority"),
                }
            )
        if bool(result.get("truncated")) or len(rules) > limits.max_results:
            rows.append({"_truncated": True})
        return tuple(rows)

    async def query_network_peerings(
        self, provider_ref: str, *, limits: ReadToolLimits
    ) -> Sequence[AzureRow]:
        resource_group, name = self._resource(provider_ref, "virtualNetworks")
        result = await self._invoke(
            "azure.network.peering.read",
            {"resource_group": resource_group, "vnet_name": name},
        )
        peerings = result.get("peerings")
        if not isinstance(peerings, list):
            raise AzureOperationsGatewayReadError("gateway peering result was incomplete")
        observed_at = self._clock().isoformat()
        rows: list[AzureRow] = []
        for peering in peerings[: limits.max_results]:
            if not isinstance(peering, Mapping):
                continue
            rows.append(
                {
                    "observed_at": observed_at,
                    "status": _text(peering.get("state"), 32),
                    "peering_name": _text(peering.get("name"), 128),
                    "remote_vnet": _text(peering.get("remote_vnet"), 128),
                    "sync_level": _text(peering.get("sync_level"), 32),
                    "allow_vnet_access": peering.get("allow_vnet_access"),
                    "allow_forwarded_traffic": peering.get("allow_forwarded_traffic"),
                    "allow_gateway_transit": peering.get("allow_gateway_transit"),
                    "use_remote_gateways": peering.get("use_remote_gateways"),
                    "remote_address_prefixes": _text(peering.get("remote_address_prefixes"), 512),
                }
            )
        if bool(result.get("truncated")) or len(peerings) > limits.max_results:
            rows.append({"_truncated": True})
        return tuple(rows)

    async def _invoke(
        self, operation_id: str, payload: Mapping[str, object]
    ) -> Mapping[str, object]:
        token = await self._identity.get_token(self._config.audience)
        request = self._http.build_request(
            "POST",
            f"{self._config.base_url.rstrip('/')}/api/v1/operations/{operation_id}",
            headers={"Authorization": f"Bearer {token.token}"},
            json=payload,
        )
        try:
            response = await self._http.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise AzureOperationsGatewayReadError("operations gateway request failed") from exc
        try:
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_RESPONSE_BYTES:
                    raise AzureOperationsGatewayReadError(
                        "operations gateway response was too large"
                    )
        except httpx.HTTPError as exc:
            raise AzureOperationsGatewayReadError("operations gateway response failed") from exc
        finally:
            await response.aclose()
        try:
            body = json.loads(content)
        except (ValueError, json.JSONDecodeError) as exc:
            raise AzureOperationsGatewayReadError(
                "operations gateway response was not JSON"
            ) from exc
        if response.status_code != 200:
            code = body.get("code") if isinstance(body, Mapping) else None
            suffix = f" ({code})" if isinstance(code, str) and len(code) <= 64 else ""
            raise AzureOperationsGatewayReadError(
                f"operations gateway returned HTTP {response.status_code}{suffix}"
            )
        if not isinstance(body, Mapping) or body.get("operation_id") != operation_id:
            raise AzureOperationsGatewayReadError(
                "operations gateway response did not match request"
            )
        result = body.get("result")
        if body.get("status") != "succeeded" or not isinstance(result, Mapping):
            raise AzureOperationsGatewayReadError("operations gateway read did not succeed")
        return result

    def _resource(self, provider_ref: str, expected_collection: str) -> tuple[str, str]:
        segments = tuple(segment for segment in provider_ref.strip("/").split("/") if segment)
        if (
            len(segments) != 8
            or segments[0].casefold() != "subscriptions"
            or segments[1].casefold() != self._config.subscription_id.casefold()
            or segments[2].casefold() != "resourcegroups"
            or segments[3].casefold()
            not in {value.casefold() for value in self._config.resource_groups}
            or segments[4].casefold() != "providers"
            or segments[5].casefold() != "microsoft.network"
            or segments[6].casefold() != expected_collection.casefold()
        ):
            raise PermissionError("network resource is outside the configured gateway scope")
        return segments[3], segments[7]


def _text(value: object, maximum: int) -> str:
    return value[:maximum] if isinstance(value, str) else ""


__all__ = [
    "AzureOperationsGatewayReadConfig",
    "AzureOperationsGatewayReadError",
    "AzureOperationsGatewayReadTransport",
]
