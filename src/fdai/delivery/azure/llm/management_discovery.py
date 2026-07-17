"""Azure CLI management-plane discovery for direct Azure OpenAI and APIM routes."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.delivery.azure.llm.endpoint_discovery import ModelEndpointObservation
from fdai.delivery.azure.llm.request_target import COGNITIVE_SERVICES_SCOPE
from fdai.delivery.azure.llm.resolver_queries import AzureCliResolverError, _run_az
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelAuthKind,
    ModelCapacityUnit,
    ModelDiscoverySource,
    ModelEndpointCapacity,
    ModelEndpointFeatures,
    ModelProviderKind,
    ModelRouteKind,
)

CommandRunner = Callable[[Sequence[str]], str]


@dataclass(frozen=True, slots=True)
class AzureOpenAIDiscoverySpec:
    capability: str
    deployment: str
    features: ModelEndpointFeatures
    api_version: str = "2024-10-21"


@dataclass(frozen=True, slots=True)
class AzureCliOpenAIEndpointSource:
    """Verify configured capability deployments against one Azure OpenAI account."""

    resource_group: str
    account_name: str
    specs: tuple[AzureOpenAIDiscoverySpec, ...]
    runner: CommandRunner | None = None
    observed_at: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    async def list_observations(self) -> tuple[ModelEndpointObservation, ...]:
        run = self.runner or _default_runner
        account = _object(
            run(
                (
                    "az",
                    "cognitiveservices",
                    "account",
                    "show",
                    "--resource-group",
                    self.resource_group,
                    "--name",
                    self.account_name,
                    "-o",
                    "json",
                )
            ),
            "Azure OpenAI account",
        )
        if account.get("kind") != "OpenAI":
            raise AzureCliResolverError("discovered cognitive account is not Azure OpenAI")
        account_id = _required_string(account, "id", "Azure OpenAI account")
        deployments = _array(
            run(
                (
                    "az",
                    "cognitiveservices",
                    "account",
                    "deployment",
                    "list",
                    "--resource-group",
                    self.resource_group,
                    "--name",
                    self.account_name,
                    "-o",
                    "json",
                )
            ),
            "Azure OpenAI deployments",
        )
        by_name = {
            str(item.get("name")): item
            for item in deployments
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        }
        observations: list[ModelEndpointObservation] = []
        for spec in sorted(self.specs, key=lambda item: item.capability):
            raw = by_name.get(spec.deployment)
            if raw is None:
                raise AzureCliResolverError(
                    f"Azure OpenAI deployment {spec.deployment!r} is missing"
                )
            properties = _child(raw, "properties", "Azure OpenAI deployment")
            model = _child(properties, "model", "Azure OpenAI deployment model")
            sku = _child(raw, "sku", "Azure OpenAI deployment SKU")
            if properties.get("provisioningState") not in {None, "Succeeded"}:
                raise AzureCliResolverError(
                    f"Azure OpenAI deployment {spec.deployment!r} is not ready"
                )
            sku_name = _required_string(sku, "name", "Azure OpenAI deployment SKU")
            sku_capacity = _positive_int(sku.get("capacity"), "Azure OpenAI deployment capacity")
            capacity_unit = (
                ModelCapacityUnit.PTU
                if sku_name.endswith("ProvisionedManaged")
                else ModelCapacityUnit.TPM
            )
            capacity_value = (
                sku_capacity if capacity_unit is ModelCapacityUnit.PTU else sku_capacity * 1000
            )
            deployment_id = str(raw.get("id") or f"{account_id}/deployments/{spec.deployment}")
            observations.append(
                ModelEndpointObservation(
                    binding_id=spec.capability.replace(".", "-") + "-direct",
                    capability=spec.capability,
                    provider_kind=ModelProviderKind.AZURE_OPENAI,
                    route_kind=ModelRouteKind.DIRECT,
                    api_style=ModelApiStyle.AZURE_OPENAI,
                    endpoint_ref=f"azure-openai:{self.account_name}",
                    deployment=spec.deployment,
                    api_version=spec.api_version,
                    auth_kind=ModelAuthKind.ENTRA,
                    auth_audience=COGNITIVE_SERVICES_SCOPE,
                    publisher=str(model.get("format") or "OpenAI"),
                    family=_required_string(model, "name", "Azure OpenAI deployment model"),
                    version=(str(model["version"]) if model.get("version") else None),
                    capacity_unit=capacity_unit,
                    capacity_value=capacity_value,
                    features=spec.features,
                    source=ModelDiscoverySource.AZURE_MANAGEMENT,
                    provider_resource_ref=deployment_id,
                    observed_at=self.observed_at(),
                )
            )
        return tuple(observations)


@dataclass(frozen=True, slots=True)
class ApimEndpointDiscoverySpec:
    resource_group: str
    service_name: str
    api_id: str
    capability: str
    endpoint_ref: str
    deployment: str
    auth_audience: str
    publisher: str
    family: str
    version: str | None
    capacity: ModelEndpointCapacity
    features: ModelEndpointFeatures
    ptu_backend_id: str
    standard_backend_id: str
    provider_kind: ModelProviderKind = ModelProviderKind.AZURE_OPENAI
    api_style: ModelApiStyle = ModelApiStyle.OPENAI_V1
    api_version: str | None = None


@dataclass(frozen=True, slots=True)
class AzureCliApimEndpointSource:
    """Verify an APIM API, both backends, and the FDAI evidence policy."""

    spec: ApimEndpointDiscoverySpec
    runner: CommandRunner | None = None
    observed_at: Callable[[], datetime] = lambda: datetime.now(tz=UTC)

    async def list_observations(self) -> tuple[ModelEndpointObservation, ...]:
        run = self.runner or _default_runner
        base = (
            "--resource-group",
            self.spec.resource_group,
            "--service-name",
            self.spec.service_name,
        )
        api = _object(
            run(("az", "apim", "api", "show", *base, "--api-id", self.spec.api_id, "-o", "json")),
            "APIM API",
        )
        for backend_id in (self.spec.ptu_backend_id, self.spec.standard_backend_id):
            backend = _object(
                run(
                    (
                        "az",
                        "apim",
                        "backend",
                        "show",
                        *base,
                        "--backend-id",
                        backend_id,
                        "-o",
                        "json",
                    )
                ),
                "APIM backend",
            )
            if backend.get("name") != backend_id:
                raise AzureCliResolverError(f"APIM backend {backend_id!r} is missing")
        policy = _object(
            run(
                (
                    "az",
                    "apim",
                    "api",
                    "policy",
                    "show",
                    *base,
                    "--api-id",
                    self.spec.api_id,
                    "-o",
                    "json",
                )
            ),
            "APIM API policy",
        )
        policy_text = policy.get("value")
        if not isinstance(policy_text, str):
            properties = policy.get("properties")
            policy_text = properties.get("value") if isinstance(properties, Mapping) else None
        _validate_apim_policy(policy_text, self.spec)
        api_ref = _required_string(api, "id", "APIM API")
        return (
            ModelEndpointObservation(
                binding_id=self.spec.capability.replace(".", "-") + "-apim",
                capability=self.spec.capability,
                provider_kind=self.spec.provider_kind,
                route_kind=ModelRouteKind.APIM_GATEWAY,
                api_style=self.spec.api_style,
                endpoint_ref=self.spec.endpoint_ref,
                deployment=self.spec.deployment,
                api_version=self.spec.api_version,
                auth_kind=ModelAuthKind.ENTRA,
                auth_audience=self.spec.auth_audience,
                publisher=self.spec.publisher,
                family=self.spec.family,
                version=self.spec.version,
                capacity_unit=self.spec.capacity.unit,
                capacity_value=self.spec.capacity.value,
                features=self.spec.features,
                source=ModelDiscoverySource.APIM_MANAGEMENT,
                provider_resource_ref=api_ref,
                observed_at=self.observed_at(),
            ),
        )


def _validate_apim_policy(value: object, spec: ApimEndpointDiscoverySpec) -> None:
    if not isinstance(value, str):
        raise AzureCliResolverError("APIM API policy is missing")
    required = (
        spec.ptu_backend_id,
        spec.standard_backend_id,
        "authentication-managed-identity",
        "x-fdai-model-backend",
        "x-fdai-capacity-unit",
        "x-fdai-spillover",
        "StatusCode == 429",
    )
    missing = [token for token in required if token not in value]
    if missing:
        raise AzureCliResolverError(
            "APIM API policy lacks required FDAI controls: " + ", ".join(missing)
        )


def _default_runner(argv: Sequence[str]) -> str:
    return _run_az(argv, timeout=30.0)


def _object(raw: str, label: str) -> dict[str, Any]:
    value = _json(raw, label)
    if not isinstance(value, dict):
        raise AzureCliResolverError(f"{label} response MUST be an object")
    return value


def _array(raw: str, label: str) -> list[Any]:
    value = _json(raw, label)
    if not isinstance(value, list):
        raise AzureCliResolverError(f"{label} response MUST be an array")
    return value


def _json(raw: str, label: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AzureCliResolverError(f"{label} response is not JSON") from exc


def _child(value: Mapping[str, Any], key: str, label: str) -> Mapping[str, Any]:
    child = value.get(key)
    if not isinstance(child, Mapping):
        raise AzureCliResolverError(f"{label} lacks {key}")
    return child


def _required_string(value: Mapping[str, Any], key: str, label: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise AzureCliResolverError(f"{label} lacks {key}")
    return result


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 1:
        raise AzureCliResolverError(f"{label} MUST be positive")
    return int(value)


__all__ = [
    "ApimEndpointDiscoverySpec",
    "AzureCliApimEndpointSource",
    "AzureCliOpenAIEndpointSource",
    "AzureOpenAIDiscoverySpec",
]
