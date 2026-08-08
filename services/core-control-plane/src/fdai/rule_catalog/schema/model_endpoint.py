"""Provider-neutral resolved model endpoint binding contract."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,1023}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")


class ModelProviderKind(StrEnum):
    AZURE_OPENAI = "azure-openai"
    SELF_HOSTED = "self-hosted"


class ModelRouteKind(StrEnum):
    DIRECT = "direct"
    APIM_GATEWAY = "apim-gateway"


class ModelApiStyle(StrEnum):
    AZURE_OPENAI = "azure-openai"
    OPENAI_V1 = "openai-v1"


class ModelAuthKind(StrEnum):
    ENTRA = "entra"
    API_KEY_REF = "api-key-ref"
    NONE = "none"


class ModelCapacityUnit(StrEnum):
    TPM = "tpm"
    PTU = "ptu"
    GPU = "gpu"


class ModelDiscoverySource(StrEnum):
    AZURE_MANAGEMENT = "azure-management"
    APIM_MANAGEMENT = "apim-management"
    SIGNED_REGISTRATION = "signed-registration"
    STATIC_CONFIG = "static-config"


@dataclass(frozen=True, slots=True)
class ModelEndpointFeatures:
    streaming: bool = False
    embeddings: bool = False
    structured_output: bool = False
    tool_calling: bool = False


@dataclass(frozen=True, slots=True)
class ModelEndpointCapacity:
    unit: ModelCapacityUnit
    value: int

    def __post_init__(self) -> None:
        if self.value < 1:
            raise ValueError("model endpoint capacity value MUST be positive")


@dataclass(frozen=True, slots=True)
class ModelEndpointDiscovery:
    source: ModelDiscoverySource
    resource_ref_digest: str
    verified_at: datetime

    def __post_init__(self) -> None:
        if _DIGEST.fullmatch(self.resource_ref_digest) is None:
            raise ValueError("model endpoint resource_ref_digest MUST be a SHA-256 digest")
        if self.verified_at.tzinfo is None:
            raise ValueError("model endpoint verified_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class ModelEndpointBinding:
    """One capability binding without endpoint URLs or credential values."""

    binding_id: str
    capability: str
    provider_kind: ModelProviderKind
    route_kind: ModelRouteKind
    api_style: ModelApiStyle
    endpoint_ref: str
    deployment: str
    auth_kind: ModelAuthKind
    auth_audience: str | None
    publisher: str
    family: str
    version: str | None
    capacity: ModelEndpointCapacity
    features: ModelEndpointFeatures
    discovery: ModelEndpointDiscovery
    api_version: str | None = None

    def __post_init__(self) -> None:
        _require_identifier("binding_id", self.binding_id)
        _require_identifier("capability", self.capability)
        if "." not in self.capability:
            raise ValueError("model endpoint capability MUST use a dotted capability id")
        _require_reference("endpoint_ref", self.endpoint_ref)
        _require_identifier("deployment", self.deployment)
        _require_identifier("publisher", self.publisher)
        _require_identifier("family", self.family)
        if self.version is not None:
            _require_identifier("version", self.version)
        if self.api_version is not None:
            _require_identifier("api_version", self.api_version)
        if self.auth_kind is ModelAuthKind.ENTRA:
            if self.auth_audience is None or not self.auth_audience.strip():
                raise ValueError("Entra model endpoint auth requires auth_audience")
        elif self.auth_audience is not None:
            raise ValueError("non-Entra model endpoint auth MUST NOT declare auth_audience")
        if (
            self.provider_kind is ModelProviderKind.AZURE_OPENAI
            and self.route_kind is ModelRouteKind.DIRECT
            and self.api_style is not ModelApiStyle.AZURE_OPENAI
        ):
            raise ValueError("direct Azure OpenAI endpoints require azure-openai API style")
        if (
            self.provider_kind is ModelProviderKind.SELF_HOSTED
            and self.api_style is not ModelApiStyle.OPENAI_V1
        ):
            raise ValueError("self-hosted endpoints require openai-v1 API style")
        if self.capacity.unit is ModelCapacityUnit.PTU and (
            self.provider_kind is not ModelProviderKind.AZURE_OPENAI
        ):
            raise ValueError("PTU capacity requires an Azure OpenAI provider")
        if self.capacity.unit is ModelCapacityUnit.GPU and (
            self.provider_kind is not ModelProviderKind.SELF_HOSTED
        ):
            raise ValueError("GPU capacity requires a self-hosted provider")
        if self.capacity.unit is ModelCapacityUnit.TPM and (
            self.provider_kind is not ModelProviderKind.AZURE_OPENAI
        ):
            raise ValueError("TPM capacity requires an Azure OpenAI provider")

    def to_dict(self) -> dict[str, Any]:
        return {
            "binding_id": self.binding_id,
            "capability": self.capability,
            "provider_kind": self.provider_kind.value,
            "route_kind": self.route_kind.value,
            "api_style": self.api_style.value,
            "endpoint_ref": self.endpoint_ref,
            "deployment": self.deployment,
            "api_version": self.api_version,
            "auth": {
                "kind": self.auth_kind.value,
                "audience": self.auth_audience,
            },
            "model": {
                "publisher": self.publisher,
                "family": self.family,
                "version": self.version,
            },
            "capacity": {
                "unit": self.capacity.unit.value,
                "value": self.capacity.value,
            },
            "features": {
                "streaming": self.features.streaming,
                "embeddings": self.features.embeddings,
                "structured_output": self.features.structured_output,
                "tool_calling": self.features.tool_calling,
            },
            "discovery": {
                "source": self.discovery.source.value,
                "resource_ref_digest": self.discovery.resource_ref_digest,
                "verified_at": self.discovery.verified_at.isoformat(),
            },
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ModelEndpointBinding:
        auth = _mapping(raw, "auth")
        model = _mapping(raw, "model")
        capacity = _mapping(raw, "capacity")
        features = _mapping(raw, "features")
        discovery = _mapping(raw, "discovery")
        return cls(
            binding_id=str(raw["binding_id"]),
            capability=str(raw["capability"]),
            provider_kind=ModelProviderKind(raw["provider_kind"]),
            route_kind=ModelRouteKind(raw["route_kind"]),
            api_style=ModelApiStyle(raw["api_style"]),
            endpoint_ref=str(raw["endpoint_ref"]),
            deployment=str(raw["deployment"]),
            api_version=_optional_string(raw.get("api_version")),
            auth_kind=ModelAuthKind(auth["kind"]),
            auth_audience=_optional_string(auth.get("audience")),
            publisher=str(model["publisher"]),
            family=str(model["family"]),
            version=_optional_string(model.get("version")),
            capacity=ModelEndpointCapacity(
                unit=ModelCapacityUnit(capacity["unit"]),
                value=int(capacity["value"]),
            ),
            features=ModelEndpointFeatures(
                streaming=bool(features.get("streaming", False)),
                embeddings=bool(features.get("embeddings", False)),
                structured_output=bool(features.get("structured_output", False)),
                tool_calling=bool(features.get("tool_calling", False)),
            ),
            discovery=ModelEndpointDiscovery(
                source=ModelDiscoverySource(discovery["source"]),
                resource_ref_digest=str(discovery["resource_ref_digest"]),
                verified_at=datetime.fromisoformat(str(discovery["verified_at"])),
            ),
        )


def _mapping(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"model endpoint {key} MUST be an object")
    return value


def _optional_string(value: Any) -> str | None:
    return str(value) if value is not None else None


def _require_identifier(name: str, value: str) -> None:
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"model endpoint {name} is invalid")


def _require_reference(name: str, value: str) -> None:
    if _REFERENCE.fullmatch(value) is None:
        raise ValueError(f"model endpoint {name} is invalid")


__all__ = [
    "ModelApiStyle",
    "ModelAuthKind",
    "ModelCapacityUnit",
    "ModelDiscoverySource",
    "ModelEndpointBinding",
    "ModelEndpointCapacity",
    "ModelEndpointDiscovery",
    "ModelEndpointFeatures",
    "ModelProviderKind",
    "ModelRouteKind",
]
