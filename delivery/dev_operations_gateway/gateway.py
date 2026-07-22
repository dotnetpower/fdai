"""Bounded development operations gateway for private Azure resources."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

_ARM_AUDIENCE = "https://management.azure.com"
_NETWORK_API_VERSION = "2025-05-01"
_COMPUTE_API_VERSION = "2025-04-01"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$")


class GatewayError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class GatewayPrincipal:
    object_id: str
    groups: frozenset[str]
    roles: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class PrivateProbe:
    url: str
    audience: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username is not None:
            raise ValueError("private probe URL MUST be an absolute HTTPS URL")
        if not self.audience.strip() or len(self.audience) > 256:
            raise ValueError("private probe audience MUST be bounded")


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    subscription_id: str
    resource_groups: frozenset[str]
    contributor_group_id: str
    executor_principal_id: str
    reader_identity_client_id: str
    executor_identity_client_id: str
    private_probes: Mapping[str, PrivateProbe]

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> GatewayConfig:
        values = os.environ if env is None else env
        if values.get("FDAI_DEV_GATEWAY_ENABLED", "").strip() != "1":
            raise ValueError("development operations gateway is disabled")
        if values.get("FDAI_ENV", "").strip().casefold() != "dev":
            raise ValueError("development operations gateway requires FDAI_ENV=dev")
        groups = frozenset(
            item.strip()
            for item in values.get("FDAI_DEV_GATEWAY_RESOURCE_GROUPS", "").split(",")
            if item.strip()
        )
        probes_raw = json.loads(values.get("FDAI_DEV_GATEWAY_PRIVATE_PROBES_JSON", "{}"))
        if not isinstance(probes_raw, Mapping):
            raise ValueError("private probes configuration MUST be an object")
        probes: dict[str, PrivateProbe] = {}
        for alias, item in probes_raw.items():
            if not isinstance(alias, str) or _IDENTIFIER.fullmatch(alias) is None:
                raise ValueError("private probe aliases MUST be bounded identifiers")
            if not isinstance(item, Mapping):
                raise ValueError("private probe entries MUST be objects")
            probes[alias] = PrivateProbe(
                url=str(item.get("url", "")),
                audience=str(item.get("audience", "")),
            )
        config = cls(
            subscription_id=values.get("FDAI_DEV_GATEWAY_SUBSCRIPTION_ID", "").strip(),
            resource_groups=groups,
            contributor_group_id=values.get("FDAI_DEV_GATEWAY_CONTRIBUTOR_GROUP_ID", "").strip(),
            executor_principal_id=values.get("FDAI_DEV_GATEWAY_EXECUTOR_PRINCIPAL_ID", "").strip(),
            reader_identity_client_id=values.get(
                "FDAI_DEV_GATEWAY_READER_MI_CLIENT_ID", ""
            ).strip(),
            executor_identity_client_id=values.get(
                "FDAI_DEV_GATEWAY_EXECUTOR_MI_CLIENT_ID", ""
            ).strip(),
            private_probes=probes,
        )
        for name, value in (
            ("subscription id", config.subscription_id),
            ("contributor group id", config.contributor_group_id),
            ("executor principal id", config.executor_principal_id),
            ("reader identity client id", config.reader_identity_client_id),
            ("executor identity client id", config.executor_identity_client_id),
        ):
            if not value or len(value) > 256:
                raise ValueError(f"{name} MUST be configured")
        if not config.resource_groups:
            raise ValueError("at least one development resource group MUST be configured")
        return config


class TokenProvider(Protocol):
    async def get_token(self, audience: str) -> str: ...


class ManagedIdentityTokenProvider:
    def __init__(self, *, client_id: str, http_client: httpx.AsyncClient) -> None:
        self._client_id = client_id
        self._http = http_client

    async def get_token(self, audience: str) -> str:
        endpoint = os.environ.get("IDENTITY_ENDPOINT", "").strip()
        identity_header = os.environ.get("IDENTITY_HEADER", "").strip()
        if not endpoint or not identity_header:
            raise GatewayError(503, "identity_unavailable", "managed identity is unavailable")
        response = await self._http.get(
            endpoint,
            headers={"X-IDENTITY-HEADER": identity_header},
            params={
                "api-version": "2019-08-01",
                "resource": audience,
                "client_id": self._client_id,
            },
            timeout=10.0,
        )
        if response.status_code >= 400:
            raise GatewayError(503, "identity_unavailable", "managed identity token failed")
        payload = response.json()
        token = payload.get("access_token") if isinstance(payload, Mapping) else None
        if not isinstance(token, str) or not token:
            raise GatewayError(503, "identity_unavailable", "managed identity token was empty")
        return token


class OperationsGateway:
    def __init__(
        self,
        *,
        config: GatewayConfig,
        reader_token_provider: TokenProvider,
        executor_token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._config = config
        self._reader_tokens = reader_token_provider
        self._executor_tokens = executor_token_provider
        self._http = http_client

    async def invoke(
        self,
        operation_id: str,
        payload: Mapping[str, object],
        principal: GatewayPrincipal,
    ) -> Mapping[str, object]:
        self._authorize_read(principal)
        handlers = {
            "azure.network.nsg.read": self._read_nsg,
            "azure.network.peering.read": self._read_peerings,
            "azure.private.http.probe": self._probe_private_endpoint,
            "azure.network.nsg.rule.upsert": self._upsert_nsg_rule,
            "azure.network.nsg.rule.delete": self._delete_nsg_rule,
            "azure.compute.vm.start": self._start_vm,
            "azure.compute.vm.deallocate": self._deallocate_vm,
        }
        handler = handlers.get(operation_id)
        if handler is None:
            raise GatewayError(404, "operation_not_found", "operation is not registered")
        if operation_id in {
            "azure.network.nsg.rule.upsert",
            "azure.network.nsg.rule.delete",
            "azure.compute.vm.start",
            "azure.compute.vm.deallocate",
        }:
            self._authorize_mutation(principal, payload)
        result = await handler(payload)
        return {"operation_id": operation_id, "status": "succeeded", "result": result}

    def _authorize_read(self, principal: GatewayPrincipal) -> None:
        if (
            self._config.contributor_group_id not in principal.groups
            and not principal.roles.intersection({"Contributor", "Approver", "Owner"})
            and principal.object_id != self._config.executor_principal_id
        ):
            raise GatewayError(403, "forbidden", "Contributor access is required")

    def _authorize_mutation(
        self, principal: GatewayPrincipal, payload: Mapping[str, object]
    ) -> None:
        if principal.object_id != self._config.executor_principal_id:
            raise GatewayError(403, "executor_required", "Thor executor identity is required")
        safety = payload.get("safety")
        if not isinstance(safety, Mapping):
            raise GatewayError(400, "safety_missing", "mutation safety envelope is required")
        if safety.get("max_resources") != 1:
            raise GatewayError(400, "blast_radius_invalid", "max_resources MUST equal 1")
        for field in (
            "idempotency_key",
            "audit_ref",
            "dry_run_receipt",
            "stop_condition",
            "rollback_ref",
        ):
            value = safety.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise GatewayError(400, "safety_invalid", f"safety.{field} MUST be bounded")

    def _scope(self, payload: Mapping[str, object]) -> tuple[str, str]:
        resource_group = _identifier(payload, "resource_group")
        if resource_group.casefold() not in {
            value.casefold() for value in self._config.resource_groups
        }:
            raise GatewayError(403, "scope_denied", "resource group is outside dev scope")
        return self._config.subscription_id, resource_group

    async def _read_nsg(self, payload: Mapping[str, object]) -> object:
        subscription, group = self._scope(payload)
        name = _identifier(payload, "nsg_name")
        raw = await self._arm(
            "GET",
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
            f"Microsoft.Network/networkSecurityGroups/{name}",
            api_version=_NETWORK_API_VERSION,
        )
        if not isinstance(raw, Mapping):
            raise GatewayError(502, "azure_response_invalid", "NSG response was not an object")
        properties = raw.get("properties")
        if not isinstance(properties, Mapping):
            raise GatewayError(502, "azure_response_invalid", "NSG properties were missing")
        rules: list[Mapping[str, object]] = []
        for collection_name, kind in (
            ("securityRules", "custom"),
            ("defaultSecurityRules", "default"),
        ):
            collection = properties.get(collection_name)
            if not isinstance(collection, list):
                continue
            for item in collection[:64]:
                if not isinstance(item, Mapping):
                    continue
                rule = item.get("properties")
                if not isinstance(rule, Mapping):
                    continue
                rules.append(
                    {
                        "name": str(item.get("name", ""))[:128],
                        "kind": kind,
                        "access": str(rule.get("access", ""))[:16],
                        "direction": str(rule.get("direction", ""))[:16],
                        "protocol": str(rule.get("protocol", ""))[:16],
                        "priority": rule.get("priority"),
                        "source_address_prefix": _prefixes(
                            rule, "sourceAddressPrefix", "sourceAddressPrefixes"
                        ),
                        "source_port_range": _prefixes(rule, "sourcePortRange", "sourcePortRanges"),
                        "destination_address_prefix": _prefixes(
                            rule,
                            "destinationAddressPrefix",
                            "destinationAddressPrefixes",
                        ),
                        "destination_port_range": _prefixes(
                            rule, "destinationPortRange", "destinationPortRanges"
                        ),
                    }
                )
        return {"name": name, "rules": rules, "truncated": len(rules) >= 64}

    async def _read_peerings(self, payload: Mapping[str, object]) -> object:
        subscription, group = self._scope(payload)
        name = _identifier(payload, "vnet_name")
        raw = await self._arm(
            "GET",
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
            f"Microsoft.Network/virtualNetworks/{name}/virtualNetworkPeerings",
            api_version=_NETWORK_API_VERSION,
        )
        if not isinstance(raw, Mapping) or not isinstance(raw.get("value"), list):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "VNet peering response was not an object",
            )
        peerings: list[Mapping[str, object]] = []
        values = raw["value"]
        for item in values[:64]:
            if not isinstance(item, Mapping):
                continue
            properties = item.get("properties")
            if not isinstance(properties, Mapping):
                continue
            peerings.append(
                {
                    "name": str(item.get("name", ""))[:128],
                    "remote_vnet": _resource_name(properties.get("remoteVirtualNetwork")),
                    "state": str(properties.get("peeringState", ""))[:32],
                    "sync_level": str(properties.get("peeringSyncLevel", ""))[:32],
                    "allow_vnet_access": properties.get("allowVirtualNetworkAccess"),
                    "allow_forwarded_traffic": properties.get("allowForwardedTraffic"),
                    "allow_gateway_transit": properties.get("allowGatewayTransit"),
                    "use_remote_gateways": properties.get("useRemoteGateways"),
                    "remote_address_prefixes": _address_prefixes(
                        properties.get("remoteVirtualNetworkAddressSpace")
                        or properties.get("remoteAddressSpace")
                    ),
                }
            )
        return {
            "name": name,
            "peerings": peerings,
            "truncated": len(values) > 64 or isinstance(raw.get("nextLink"), str),
        }

    async def _probe_private_endpoint(self, payload: Mapping[str, object]) -> object:
        alias = _identifier(payload, "probe")
        probe = self._config.private_probes.get(alias)
        if probe is None:
            raise GatewayError(404, "probe_not_found", "private probe is not registered")
        token = await self._reader_tokens.get_token(probe.audience)
        response = await self._http.get(
            probe.url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        return {
            "probe": alias,
            "reachable": response.status_code < 500,
            "http_status": response.status_code,
        }

    async def _upsert_nsg_rule(self, payload: Mapping[str, object]) -> object:
        subscription, group = self._scope(payload)
        nsg_name = _identifier(payload, "nsg_name")
        rule_name = _identifier(payload, "rule_name")
        rule = payload.get("rule")
        if not isinstance(rule, Mapping):
            raise GatewayError(400, "rule_invalid", "rule MUST be an object")
        body = {
            "properties": {
                "access": _choice(rule, "access", {"Allow", "Deny"}),
                "direction": _choice(rule, "direction", {"Inbound", "Outbound"}),
                "protocol": _choice(rule, "protocol", {"Tcp", "Udp", "Icmp", "*"}),
                "priority": _integer(rule, "priority", minimum=100, maximum=4096),
                "sourceAddressPrefix": _bounded(rule, "source_address_prefix"),
                "sourcePortRange": _bounded(rule, "source_port_range"),
                "destinationAddressPrefix": _bounded(rule, "destination_address_prefix"),
                "destinationPortRange": _bounded(rule, "destination_port_range"),
            }
        }
        return await self._arm(
            "PUT",
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
            f"Microsoft.Network/networkSecurityGroups/{nsg_name}/securityRules/{rule_name}",
            api_version=_NETWORK_API_VERSION,
            json_body=body,
            executor=True,
        )

    async def _delete_nsg_rule(self, payload: Mapping[str, object]) -> object:
        subscription, group = self._scope(payload)
        nsg_name = _identifier(payload, "nsg_name")
        rule_name = _identifier(payload, "rule_name")
        return await self._arm(
            "DELETE",
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
            f"Microsoft.Network/networkSecurityGroups/{nsg_name}/securityRules/{rule_name}",
            api_version=_NETWORK_API_VERSION,
            executor=True,
        )

    async def _start_vm(self, payload: Mapping[str, object]) -> object:
        return await self._vm_action(payload, "start")

    async def _deallocate_vm(self, payload: Mapping[str, object]) -> object:
        return await self._vm_action(payload, "deallocate")

    async def _vm_action(self, payload: Mapping[str, object], action: str) -> object:
        subscription, group = self._scope(payload)
        vm_name = _identifier(payload, "vm_name")
        return await self._arm(
            "POST",
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
            f"Microsoft.Compute/virtualMachines/{vm_name}/{action}",
            api_version=_COMPUTE_API_VERSION,
            executor=True,
        )

    async def _arm(
        self,
        method: str,
        path: str,
        *,
        api_version: str,
        json_body: Mapping[str, object] | None = None,
        executor: bool = False,
    ) -> object:
        token_provider = self._executor_tokens if executor else self._reader_tokens
        token = await token_provider.get_token(_ARM_AUDIENCE)
        response = await self._http.request(
            method,
            f"https://management.azure.com{path}",
            params={"api-version": api_version},
            headers={"Authorization": f"Bearer {token}"},
            json=json_body,
            timeout=30.0,
        )
        if response.status_code >= 400:
            raise GatewayError(
                502,
                "azure_operation_failed",
                f"Azure operation returned HTTP {response.status_code}",
            )
        if response.status_code == 204 or not response.content:
            return {"accepted": True}
        body = response.json()
        if not isinstance(body, (Mapping, list)):
            raise GatewayError(502, "azure_response_invalid", "Azure response was not JSON")
        return body


def _identifier(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise GatewayError(400, "argument_invalid", f"{name} MUST be a bounded identifier")
    return value


def _bounded(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise GatewayError(400, "argument_invalid", f"{name} MUST be bounded")
    return value


def _choice(payload: Mapping[str, object], name: str, choices: set[str]) -> str:
    value = _bounded(payload, name)
    if value not in choices:
        raise GatewayError(400, "argument_invalid", f"{name} is not allowed")
    return value


def _integer(payload: Mapping[str, object], name: str, *, minimum: int, maximum: int) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise GatewayError(400, "argument_invalid", f"{name} is outside its allowed range")
    return value


def _prefixes(payload: Mapping[str, object], singular: str, plural: str) -> str:
    values = payload.get(plural)
    if isinstance(values, list):
        rendered = ",".join(item for item in values if isinstance(item, str))
        if rendered:
            return rendered[:512]
    value = payload.get(singular)
    return str(value)[:512] if value is not None else ""


def _resource_name(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    resource_id = value.get("id")
    if not isinstance(resource_id, str):
        return ""
    return resource_id.rstrip("/").rsplit("/", maxsplit=1)[-1][:128]


def _address_prefixes(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    prefixes = value.get("addressPrefixes")
    if not isinstance(prefixes, list):
        return ""
    return ",".join(item for item in prefixes if isinstance(item, str))[:512]


__all__ = [
    "GatewayConfig",
    "GatewayError",
    "GatewayPrincipal",
    "ManagedIdentityTokenProvider",
    "OperationsGateway",
    "PrivateProbe",
]
