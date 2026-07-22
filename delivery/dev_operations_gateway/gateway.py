"""Bounded development operations gateway for private Azure resources."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from delivery.dev_operations_gateway.idempotency import (
        AzureBlobIdempotencyConfig,
        IdempotencyError,
        IdempotencyLedger,
    )
elif __package__:
    from .idempotency import AzureBlobIdempotencyConfig, IdempotencyError, IdempotencyLedger
else:
    from idempotency import AzureBlobIdempotencyConfig, IdempotencyError, IdempotencyLedger

_ARM_AUDIENCE = "https://management.azure.com"
_NETWORK_API_VERSION = "2025-05-01"
_COMPUTE_API_VERSION = "2025-04-01"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.()-]{0,127}$")
_MUTATION_OPERATIONS = frozenset(
    {
        "azure.network.nsg.rule.upsert",
        "azure.network.nsg.rule.delete",
        "azure.compute.vm.start",
        "azure.compute.vm.deallocate",
    }
)


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
class _ArmSubmission:
    status_url: str


@dataclass(frozen=True, slots=True)
class PrivateProbe:
    url: str
    audience: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        hostname = parsed.hostname or ""
        try:
            ipaddress.ip_address(hostname)
            literal_ip = True
        except ValueError:
            literal_ip = False
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or hostname.casefold() == "localhost"
            or literal_ip
            or len(self.url) > 2_048
            or any(character in self.url for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("private probe URL MUST be an absolute HTTPS URL")
        if (
            not self.audience.strip()
            or len(self.audience) > 256
            or any(character in self.audience for character in ("\x00", "\r", "\n"))
        ):
            raise ValueError("private probe audience MUST be bounded")


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    subscription_id: str
    resource_groups: frozenset[str]
    contributor_group_id: str
    executor_principal_id: str
    reader_identity_client_id: str
    executor_identity_client_id: str
    idempotency_container_url: str
    private_probes: Mapping[str, PrivateProbe]
    mutations_enabled: bool = False

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
        idempotency_container_url = values.get(
            "FDAI_DEV_GATEWAY_IDEMPOTENCY_CONTAINER_URL", ""
        ).strip()
        AzureBlobIdempotencyConfig(container_url=idempotency_container_url)
        mutations_raw = values.get("FDAI_DEV_GATEWAY_MUTATIONS_ENABLED", "0").strip()
        if mutations_raw not in {"0", "1"}:
            raise ValueError("FDAI_DEV_GATEWAY_MUTATIONS_ENABLED MUST be 0 or 1")
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
            idempotency_container_url=idempotency_container_url,
            private_probes=probes,
            mutations_enabled=mutations_raw == "1",
        )
        for name, value in (
            ("subscription id", config.subscription_id),
            ("contributor group id", config.contributor_group_id),
            ("executor principal id", config.executor_principal_id),
            ("reader identity client id", config.reader_identity_client_id),
            ("executor identity client id", config.executor_identity_client_id),
            ("idempotency container URL", config.idempotency_container_url),
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
        try:
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
        except httpx.HTTPError as exc:
            raise GatewayError(
                503,
                "identity_unavailable",
                "managed identity token request failed",
            ) from exc
        if response.status_code >= 400:
            raise GatewayError(503, "identity_unavailable", "managed identity token failed")
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayError(
                503,
                "identity_unavailable",
                "managed identity token response was invalid",
            ) from exc
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
        idempotency_ledger: IdempotencyLedger | None = None,
    ) -> None:
        self._config = config
        self._reader_tokens = reader_token_provider
        self._executor_tokens = executor_token_provider
        self._http = http_client
        self._idempotency = idempotency_ledger

    async def invoke(
        self,
        operation_id: str,
        payload: Mapping[str, object],
        principal: GatewayPrincipal,
    ) -> Mapping[str, object]:
        self._authorize_read(principal)
        if operation_id == "azure.operation.plan":
            if not self._config.mutations_enabled:
                raise GatewayError(404, "operation_not_found", "operation is not registered")
            return await self._operation_plan(payload, principal)
        if operation_id == "azure.operation.status":
            if not self._config.mutations_enabled:
                raise GatewayError(404, "operation_not_found", "operation is not registered")
            return await self._operation_status(payload, principal)
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
        mutation = operation_id in _MUTATION_OPERATIONS
        if mutation and not self._config.mutations_enabled:
            raise GatewayError(404, "operation_not_found", "operation is not registered")
        if not mutation:
            result = await handler(payload)
            return {"operation_id": operation_id, "status": "succeeded", "result": result}

        idempotency_key, dry_run_receipt = self._authorize_mutation(principal, payload)
        if self._idempotency is None:
            raise GatewayError(
                503,
                "idempotency_unavailable",
                "mutation idempotency ledger is unavailable",
            )
        request_digest = _request_digest(operation_id, payload)
        try:
            replay = await self._idempotency.begin(idempotency_key, request_digest)
        except IdempotencyError as exc:
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        if replay is not None:
            return _public_response(replay)
        try:
            await self._idempotency.consume_dry_run(
                dry_run_receipt,
                _mutation_digest(operation_id, payload),
            )
        except IdempotencyError as exc:
            try:
                await self._idempotency.abort(idempotency_key, request_digest)
            except IdempotencyError as abort_error:
                exc.add_note(f"idempotency claim cleanup also failed: {abort_error.code}")
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        resource_key = self._mutation_resource_key(operation_id, payload)
        try:
            lease_id = await self._idempotency.acquire_resource(resource_key)
        except IdempotencyError as exc:
            try:
                await self._idempotency.abort(idempotency_key, request_digest)
            except IdempotencyError as abort_error:
                exc.add_note(f"idempotency claim cleanup also failed: {abort_error.code}")
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        try:
            try:
                result = await handler(payload)
            except Exception as exc:
                try:
                    await self._idempotency.abort(idempotency_key, request_digest)
                except IdempotencyError as abort_error:
                    exc.add_note(f"idempotency claim cleanup also failed: {abort_error.code}")
                raise
            if isinstance(result, _ArmSubmission):
                response: dict[str, object] = {
                    "operation_id": operation_id,
                    "status": "submitted",
                    "result": {
                        "accepted": True,
                        "status": "submitted",
                        "_provider_operation_url": result.status_url,
                    },
                }
            else:
                response = {
                    "operation_id": operation_id,
                    "status": "succeeded",
                    "result": result,
                }
            await self._idempotency.complete(idempotency_key, request_digest, response)
        except IdempotencyError as exc:
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        finally:
            active_error = sys.exception()
            try:
                await self._idempotency.release_resource(resource_key, lease_id)
            except IdempotencyError as release_error:
                if active_error is not None:
                    active_error.add_note(
                        f"resource lease cleanup also failed: {release_error.code}"
                    )
                else:
                    raise GatewayError(
                        release_error.status_code,
                        release_error.code,
                        str(release_error),
                    ) from release_error
        return _public_response(response)

    async def _operation_status(
        self,
        payload: Mapping[str, object],
        principal: GatewayPrincipal,
    ) -> Mapping[str, object]:
        self._authorize_executor(principal)
        if self._idempotency is None:
            raise GatewayError(503, "idempotency_unavailable", "operation ledger is unavailable")
        idempotency_key = _bounded(payload, "idempotency_key", maximum=512)
        try:
            record = await self._idempotency.lookup(idempotency_key)
        except IdempotencyError as exc:
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        result = record.get("result")
        status_url = result.get("_provider_operation_url") if isinstance(result, Mapping) else None
        if not isinstance(status_url, str):
            raise GatewayError(409, "operation_not_async", "operation has no asynchronous status")
        provider_status = await self._poll_arm_status(status_url)
        normalized = _normalize_provider_status(provider_status)
        return {
            "operation_id": "azure.operation.status",
            "status": normalized,
            "result": {"provider_status": provider_status, "status": normalized},
        }

    async def _operation_plan(
        self,
        payload: Mapping[str, object],
        principal: GatewayPrincipal,
    ) -> Mapping[str, object]:
        self._authorize_executor(principal)
        if self._idempotency is None:
            raise GatewayError(503, "idempotency_unavailable", "operation ledger is unavailable")
        target_operation = _bounded(payload, "operation_id", maximum=128)
        arguments = payload.get("arguments")
        if not isinstance(arguments, Mapping):
            raise GatewayError(400, "payload_invalid", "plan arguments MUST be an object")
        safety = payload.get("safety")
        if not isinstance(safety, Mapping):
            raise GatewayError(400, "safety_missing", "plan safety envelope is required")
        if target_operation not in _MUTATION_OPERATIONS:
            raise GatewayError(404, "operation_not_found", "mutation operation is not registered")
        self._validate_mutation_payload(target_operation, arguments)
        self._validate_safety(safety, require_dry_run_receipt=False)
        await self._preflight_mutation(target_operation, arguments)
        try:
            receipt = await self._idempotency.issue_dry_run(
                _mutation_digest(target_operation, {**arguments, "safety": safety})
            )
        except IdempotencyError as exc:
            raise GatewayError(exc.status_code, exc.code, str(exc)) from exc
        return {
            "operation_id": "azure.operation.plan",
            "status": "succeeded",
            "result": {
                "target_operation": target_operation,
                "status": "planned",
                "dry_run_receipt": receipt,
                "expires_in_seconds": 300,
            },
        }

    def _authorize_read(self, principal: GatewayPrincipal) -> None:
        if (
            self._config.contributor_group_id not in principal.groups
            and not principal.roles.intersection({"Contributor", "Approver", "Owner"})
            and principal.object_id != self._config.executor_principal_id
        ):
            raise GatewayError(403, "forbidden", "Contributor access is required")

    def _authorize_mutation(
        self, principal: GatewayPrincipal, payload: Mapping[str, object]
    ) -> tuple[str, str]:
        if principal.object_id != self._config.executor_principal_id:
            raise GatewayError(403, "executor_required", "Thor executor identity is required")
        safety = payload.get("safety")
        if not isinstance(safety, Mapping):
            raise GatewayError(400, "safety_missing", "mutation safety envelope is required")
        self._validate_safety(safety, require_dry_run_receipt=True)
        return str(safety["idempotency_key"]), str(safety["dry_run_receipt"])

    def _validate_safety(
        self,
        safety: Mapping[str, object],
        *,
        require_dry_run_receipt: bool,
    ) -> None:
        if safety.get("max_resources") != 1:
            raise GatewayError(400, "blast_radius_invalid", "max_resources MUST equal 1")
        required_fields = [
            "idempotency_key",
            "audit_ref",
            "stop_condition",
            "rollback_ref",
        ]
        if require_dry_run_receipt:
            required_fields.append("dry_run_receipt")
        for field in required_fields:
            value = safety.get(field)
            if not isinstance(value, str) or not value.strip() or len(value) > 512:
                raise GatewayError(400, "safety_invalid", f"safety.{field} MUST be bounded")

    def _authorize_executor(self, principal: GatewayPrincipal) -> None:
        if principal.object_id != self._config.executor_principal_id:
            raise GatewayError(403, "executor_required", "Thor executor identity is required")

    def _mutation_resource_key(
        self,
        operation_id: str,
        payload: Mapping[str, object],
    ) -> str:
        subscription, group = self._scope(payload)
        if operation_id.startswith("azure.compute.vm."):
            target = f"vm/{_identifier(payload, 'vm_name')}"
        else:
            target = (
                f"nsg/{_identifier(payload, 'nsg_name')}/rule/{_identifier(payload, 'rule_name')}"
            )
        return f"{subscription}/{group}/{target}".casefold()

    def _validate_mutation_payload(
        self,
        operation_id: str,
        payload: Mapping[str, object],
    ) -> None:
        self._mutation_resource_key(operation_id, payload)
        if operation_id == "azure.network.nsg.rule.upsert":
            _nsg_rule_body(payload)

    async def _preflight_mutation(
        self,
        operation_id: str,
        payload: Mapping[str, object],
    ) -> None:
        subscription, group = self._scope(payload)
        if operation_id.startswith("azure.compute.vm."):
            vm_name = _identifier(payload, "vm_name")
            path = (
                f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
                f"Microsoft.Compute/virtualMachines/{vm_name}"
            )
            api_version = _COMPUTE_API_VERSION
        else:
            nsg_name = _identifier(payload, "nsg_name")
            path = (
                f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
                f"Microsoft.Network/networkSecurityGroups/{nsg_name}"
            )
            api_version = _NETWORK_API_VERSION
        observed = await self._arm("GET", path, api_version=api_version)
        if not isinstance(observed, Mapping):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure mutation preflight did not return a resource object",
            )

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
        projected_rules: list[Mapping[str, object]] = []
        for collection_name, kind in (
            ("securityRules", "custom"),
            ("defaultSecurityRules", "default"),
        ):
            collection = properties.get(collection_name)
            if not isinstance(collection, list):
                continue
            for item in collection:
                if not isinstance(item, Mapping):
                    continue
                rule = item.get("properties")
                if not isinstance(rule, Mapping):
                    continue
                projected_rules.append(
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
        return {
            "name": name,
            "rules": projected_rules[:64],
            "truncated": len(projected_rules) > 64,
        }

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
            follow_redirects=False,
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
        body = _nsg_rule_body(payload)
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
        if response.status_code == 404:
            raise GatewayError(404, "azure_resource_not_found", "Azure resource was not found")
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
            self._validate_arm_status_url(status_url)
            return _ArmSubmission(status_url=status_url)
        if response.status_code == 204 or not response.content:
            return {"accepted": True}
        body = response.json()
        if not isinstance(body, (Mapping, list)):
            raise GatewayError(502, "azure_response_invalid", "Azure response was not JSON")
        return body

    async def _poll_arm_status(self, status_url: str) -> str:
        self._validate_arm_status_url(status_url)
        token = await self._executor_tokens.get_token(_ARM_AUDIENCE)
        response = await self._http.get(
            status_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
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

    def _validate_arm_status_url(self, status_url: str) -> None:
        parsed = urlparse(status_url)
        subscription_prefix = f"/subscriptions/{self._config.subscription_id}/".casefold()
        if (
            parsed.scheme != "https"
            or parsed.hostname != "management.azure.com"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not parsed.path.casefold().startswith(subscription_prefix)
        ):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure operation status URL was outside the configured subscription",
            )


def _identifier(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise GatewayError(400, "argument_invalid", f"{name} MUST be a bounded identifier")
    return value


def _request_digest(operation_id: str, payload: Mapping[str, object]) -> str:
    try:
        encoded = json.dumps(
            {"operation_id": operation_id, "payload": payload},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GatewayError(400, "payload_invalid", "request body MUST contain JSON values") from exc
    return hashlib.sha256(encoded).hexdigest()


def _mutation_digest(operation_id: str, payload: Mapping[str, object]) -> str:
    bound_payload = dict(payload)
    safety = payload.get("safety")
    if isinstance(safety, Mapping):
        bound_payload["safety"] = {
            key: value for key, value in safety.items() if key != "dry_run_receipt"
        }
    return _request_digest(operation_id, bound_payload)


def _bounded(payload: Mapping[str, object], name: str, *, maximum: int = 256) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise GatewayError(400, "argument_invalid", f"{name} MUST be bounded")
    return value


def _public_response(response: Mapping[str, object]) -> Mapping[str, object]:
    result = response.get("result")
    if not isinstance(result, Mapping) or "_provider_operation_url" not in result:
        return dict(response)
    public_result = dict(result)
    public_result.pop("_provider_operation_url", None)
    public_response = dict(response)
    public_response["result"] = public_result
    return public_response


def _normalize_provider_status(status: str) -> str:
    normalized = status.casefold()
    if normalized in {"succeeded", "success", "completed"}:
        return "succeeded"
    if normalized in {"failed", "canceled", "cancelled"}:
        return "failed"
    return "running"


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


def _nsg_rule_body(payload: Mapping[str, object]) -> Mapping[str, object]:
    rule = payload.get("rule")
    if not isinstance(rule, Mapping):
        raise GatewayError(400, "rule_invalid", "rule MUST be an object")
    return {
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
