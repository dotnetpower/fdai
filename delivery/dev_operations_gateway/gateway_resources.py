"""Scoped Azure resource reads and mutations for the development gateway."""

from __future__ import annotations

import re
from collections.abc import Mapping

import httpx

from delivery.dev_operations_gateway.gateway_arm import ArmClient, _ArmSubmission
from delivery.dev_operations_gateway.gateway_contracts import (
    _COMPUTE_API_VERSION,
    _IDENTIFIER,
    _LOGICAL_RESOURCE_REF,
    _NETWORK_API_VERSION,
    _TAG_NAME,
    _TAG_VALUE,
    _TAGS_API_VERSION,
    GatewayConfig,
    GatewayError,
    TokenProvider,
)


class GatewayResourceOperations:
    def __init__(
        self,
        *,
        config: GatewayConfig,
        reader_token_provider: TokenProvider,
        http_client: httpx.AsyncClient,
        arm_client: ArmClient,
    ) -> None:
        self._config = config
        self._reader_tokens = reader_token_provider
        self._http = http_client
        self._arm_client = arm_client

    def _mutation_resource_key(
        self,
        operation_id: str,
        payload: Mapping[str, object],
    ) -> str:
        if operation_id == "azure.resource.tags.merge":
            subscription, group, target_path = self._tag_target(payload)
            target = f"tags/{target_path.lstrip('/')}"
        else:
            subscription, group = self._scope(payload)
        if operation_id == "azure.compute.vmss.scale":
            _, _, vmss_name = self._vmss_target(payload)
            target = f"vmss/{vmss_name}"
        elif operation_id.startswith("azure.compute.vm."):
            target = f"vm/{_identifier(payload, 'vm_name')}"
        elif operation_id != "azure.resource.tags.merge":
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
        elif operation_id == "azure.resource.tags.merge":
            _tag_argument(payload, "tag_name", _TAG_NAME)
            _tag_argument(payload, "tag_value", _TAG_VALUE)
        elif operation_id == "azure.compute.vmss.scale":
            _integer(payload, "replica_count", minimum=1, maximum=1000)
            _scale_reason(payload)

    async def _preflight_mutation(
        self,
        operation_id: str,
        payload: Mapping[str, object],
    ) -> None:
        if operation_id == "azure.resource.tags.merge":
            await self._read_tag_document(payload)
            return
        subscription, group = self._scope(payload)
        if operation_id == "azure.compute.vmss.scale":
            _, group, vmss_name = self._vmss_target(payload)
            path = (
                f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
                f"Microsoft.Compute/virtualMachineScaleSets/{vmss_name}"
            )
            api_version = _COMPUTE_API_VERSION
        elif operation_id.startswith("azure.compute.vm."):
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
        observed = await self._arm_client.request("GET", path, api_version=api_version)
        if not isinstance(observed, Mapping):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure mutation preflight did not return a resource object",
            )
        if operation_id == "azure.compute.vmss.scale":
            self._validate_vmss_scale_observation(payload, observed, require_etag=False)

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
        raw = await self._arm_client.request(
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
        raw = await self._arm_client.request(
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
        if probe.result_contract == "application_database_dependency":
            if len(response.content) > 16_384:
                raise GatewayError(
                    502,
                    "probe_response_too_large",
                    "private probe response exceeded cap",
                )
            try:
                receipt = response.json()
            except ValueError as exc:
                raise GatewayError(
                    502,
                    "probe_response_invalid",
                    "private dependency probe response was not JSON",
                ) from exc
            if (
                not isinstance(receipt, Mapping)
                or receipt.get("dependency") != "database"
                or not isinstance(receipt.get("reachable"), bool)
            ):
                raise GatewayError(
                    502,
                    "probe_response_invalid",
                    "private dependency probe receipt was invalid",
                )
            return {
                "probe": alias,
                "probe_contract": probe.result_contract,
                "dependency": "database",
                "reachable": receipt["reachable"] is True and 200 <= response.status_code < 300,
                "http_status": response.status_code,
            }
        return {
            "probe": alias,
            "probe_contract": probe.result_contract,
            "reachable": 200 <= response.status_code < 300,
            "http_status": response.status_code,
        }

    async def _upsert_nsg_rule(self, payload: Mapping[str, object]) -> object:
        subscription, group = self._scope(payload)
        nsg_name = _identifier(payload, "nsg_name")
        rule_name = _identifier(payload, "rule_name")
        body = _nsg_rule_body(payload)
        return await self._arm_client.request(
            "PUT",
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
            f"Microsoft.Network/networkSecurityGroups/{nsg_name}/securityRules/{rule_name}",
            api_version=_NETWORK_API_VERSION,
            json_body=body,
            executor=True,
        )

    async def _read_resource_tag(self, payload: Mapping[str, object]) -> object:
        tag_name = _tag_argument(payload, "tag_name", _TAG_NAME)
        expected = _tag_argument(payload, "tag_value", _TAG_VALUE)
        tags = await self._read_tag_document(payload)
        return {
            "matches": tags.get(tag_name) == expected,
            "present": tag_name in tags,
        }

    async def _merge_resource_tag(self, payload: Mapping[str, object]) -> object:
        tag_name = _tag_argument(payload, "tag_name", _TAG_NAME)
        tag_value = _tag_argument(payload, "tag_value", _TAG_VALUE)
        prior = await self._read_tag_document(payload)
        target_path = self._tag_extension_path(payload)
        mutation = await self._arm_client.request(
            "PATCH",
            target_path,
            api_version=_TAGS_API_VERSION,
            json_body={
                "operation": "Merge",
                "properties": {"tags": {tag_name: tag_value}},
            },
            executor=True,
        )
        if isinstance(mutation, _ArmSubmission):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure tag merge unexpectedly returned an asynchronous operation",
            )
        observed = await self._read_tag_document(payload)
        if observed.get(tag_name) == tag_value:
            return {"verified": True}
        await self._restore_tag_snapshot(payload, prior)
        raise GatewayError(
            502,
            "effect_verification_failed",
            "Azure tag readback mismatched and the prior tag snapshot was restored",
        )

    async def _restore_tag_snapshot(
        self,
        payload: Mapping[str, object],
        prior: Mapping[str, str],
    ) -> None:
        target_path = self._tag_extension_path(payload)
        restored = await self._arm_client.request(
            "PATCH",
            target_path,
            api_version=_TAGS_API_VERSION,
            json_body={
                "operation": "Replace",
                "properties": {"tags": dict(prior)},
            },
            executor=True,
        )
        if isinstance(restored, _ArmSubmission):
            raise GatewayError(
                502,
                "tag_rollback_failed",
                "Azure tag rollback unexpectedly returned an asynchronous operation",
            )
        if await self._read_tag_document(payload) != dict(prior):
            raise GatewayError(
                500,
                "tag_rollback_failed",
                "Azure tag rollback could not restore the prior snapshot",
            )

    async def _read_tag_document(self, payload: Mapping[str, object]) -> dict[str, str]:
        raw = await self._arm_client.request(
            "GET",
            self._tag_extension_path(payload),
            api_version=_TAGS_API_VERSION,
        )
        if not isinstance(raw, Mapping):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure tag response was not an object",
            )
        properties = raw.get("properties")
        tags = properties.get("tags") if isinstance(properties, Mapping) else None
        if not isinstance(tags, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in tags.items()
        ):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure tag response did not contain a string map",
            )
        return dict(tags)

    def _tag_extension_path(self, payload: Mapping[str, object]) -> str:
        subscription, _group, target_path = self._tag_target(payload)
        return (
            f"/subscriptions/{subscription}{target_path}/providers/Microsoft.Resources/tags/default"
        )

    def _tag_target(self, payload: Mapping[str, object]) -> tuple[str, str, str]:
        target_ref = _bounded(payload, "target_resource_ref", maximum=2048)
        match = _LOGICAL_RESOURCE_REF.fullmatch(target_ref)
        if match is None:
            raise GatewayError(
                400,
                "argument_invalid",
                "target_resource_ref MUST identify one bounded logical Azure resource",
            )
        group = match.group("resource_group")
        provider_path = match.group("provider_path") or ""
        segments = provider_path.split("/")[2:] if provider_path else []
        if segments and len(segments) % 2 == 0:
            raise GatewayError(
                400,
                "argument_invalid",
                "target_resource_ref provider path is incomplete",
            )
        if group.casefold() not in {value.casefold() for value in self._config.resource_groups}:
            raise GatewayError(403, "scope_denied", "resource group is outside dev scope")
        target_path = f"/resourceGroups/{group}{provider_path}"
        return self._config.subscription_id, group, target_path

    async def _delete_nsg_rule(self, payload: Mapping[str, object]) -> object:
        subscription, group = self._scope(payload)
        nsg_name = _identifier(payload, "nsg_name")
        rule_name = _identifier(payload, "rule_name")
        return await self._arm_client.request(
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
        return await self._arm_client.request(
            "POST",
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
            f"Microsoft.Compute/virtualMachines/{vm_name}/{action}",
            api_version=_COMPUTE_API_VERSION,
            executor=True,
        )

    async def _scale_vmss(self, payload: Mapping[str, object]) -> object:
        subscription, group, vmss_name = self._vmss_target(payload)
        replica_count = _integer(payload, "replica_count", minimum=1, maximum=1000)
        path = (
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
            f"Microsoft.Compute/virtualMachineScaleSets/{vmss_name}"
        )
        observed = await self._arm_client.request("GET", path, api_version=_COMPUTE_API_VERSION)
        if not isinstance(observed, Mapping):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure VMSS pre-mutation observation was not an object",
            )
        etag = self._validate_vmss_scale_observation(payload, observed, require_etag=True)
        return await self._arm_client.request(
            "PATCH",
            path,
            api_version=_COMPUTE_API_VERSION,
            json_body={"sku": {"capacity": replica_count}},
            executor=True,
            request_headers={"If-Match": etag},
        )

    def _validate_vmss_scale_observation(
        self,
        payload: Mapping[str, object],
        observed: Mapping[str, object],
        *,
        require_etag: bool,
    ) -> str:
        sku = observed.get("sku")
        properties = observed.get("properties")
        current_capacity = sku.get("capacity") if isinstance(sku, Mapping) else None
        orchestration_mode = (
            properties.get("orchestrationMode") if isinstance(properties, Mapping) else None
        )
        if orchestration_mode != "Uniform":
            raise GatewayError(
                409,
                "orchestration_mode_unsupported",
                "development VMSS scale-out requires Uniform orchestration",
            )
        requested_capacity = _integer(payload, "replica_count", minimum=1, maximum=1000)
        if (
            not isinstance(current_capacity, int)
            or isinstance(current_capacity, bool)
            or requested_capacity != current_capacity + 1
        ):
            raise GatewayError(
                409,
                "scale_out_of_bounds",
                "development VMSS scale-out MUST increase capacity by exactly one",
            )
        if not require_etag:
            return ""
        etag = observed.get("etag")
        if (
            not isinstance(etag, str)
            or not etag
            or len(etag) > 512
            or any(ord(character) < 32 or ord(character) == 127 for character in etag)
        ):
            raise GatewayError(
                502,
                "azure_response_invalid",
                "Azure VMSS observation omitted a bounded ETag",
            )
        return etag

    def _vmss_target(self, payload: Mapping[str, object]) -> tuple[str, str, str]:
        subscription, group = self._scope(payload)
        vmss_name = _identifier(payload, "vmss_name")
        target_ref = _bounded(payload, "target_resource_ref", maximum=1024)
        expected = (
            f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
            f"Microsoft.Compute/virtualMachineScaleSets/{vmss_name}"
        )
        if target_ref.casefold() != expected.casefold():
            raise GatewayError(
                403,
                "target_mismatch",
                "VMSS target does not match the configured subscription and resource group",
            )
        return subscription, group, vmss_name


def _identifier(payload: Mapping[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise GatewayError(400, "argument_invalid", f"{name} MUST be a bounded identifier")
    return value


def _tag_argument(
    payload: Mapping[str, object],
    name: str,
    pattern: re.Pattern[str],
) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise GatewayError(400, "argument_invalid", f"{name} is invalid")
    return value


def _bounded(payload: Mapping[str, object], name: str, *, maximum: int = 256) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
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


def _scale_reason(payload: Mapping[str, object]) -> str:
    reason = payload.get("reason")
    if (
        not isinstance(reason, str)
        or not 10 <= len(reason) <= 200
        or any(ord(character) < 32 or ord(character) == 127 for character in reason)
    ):
        raise GatewayError(
            400,
            "argument_invalid",
            "reason MUST contain 10..200 characters without controls",
        )
    return reason


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
