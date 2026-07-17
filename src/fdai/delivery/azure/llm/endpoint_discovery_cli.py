"""Discover verified Azure/APIM model routes into protected resolved-models JSON."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fdai.delivery.azure.llm.endpoint_discovery import (
    ModelEndpointObservationSource,
    discover_model_endpoints,
)
from fdai.delivery.azure.llm.management_discovery import (
    ApimEndpointDiscoverySpec,
    AzureCliApimEndpointSource,
    AzureCliOpenAIEndpointSource,
    AzureOpenAIDiscoverySpec,
)
from fdai.rule_catalog.schema.llm_resolver import ResolvedModels
from fdai.rule_catalog.schema.model_endpoint import (
    ModelApiStyle,
    ModelCapacityUnit,
    ModelEndpointBinding,
    ModelEndpointCapacity,
    ModelEndpointFeatures,
    ModelProviderKind,
)

DISCOVERY_CONFIG_SCHEMA = "fdai.model-endpoint-discovery.v1"
_MAX_INPUT_BYTES = 4 * 1024 * 1024


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class FeatureConfig(_ConfigModel):
    streaming: bool = False
    embeddings: bool = False
    structured_output: bool = False
    tool_calling: bool = False

    def contract(self) -> ModelEndpointFeatures:
        return ModelEndpointFeatures(**self.model_dump())


class AzureCapabilityConfig(_ConfigModel):
    capability: Annotated[str, Field(pattern=r"^(t1|t2)\.[a-z][a-z0-9._-]{1,63}$")]
    deployment: Annotated[str, Field(min_length=1, max_length=256)]
    api_version: Annotated[str, Field(min_length=1, max_length=64)] = "2024-10-21"
    features: FeatureConfig


class AzureAccountConfig(_ConfigModel):
    resource_group: Annotated[str, Field(min_length=1, max_length=90)]
    account_name: Annotated[str, Field(min_length=1, max_length=64)]
    capabilities: Annotated[tuple[AzureCapabilityConfig, ...], Field(min_length=1)]


class CapacityConfig(_ConfigModel):
    unit: ModelCapacityUnit
    value: Annotated[int, Field(ge=1)]


class ApimRouteConfig(_ConfigModel):
    resource_group: Annotated[str, Field(min_length=1, max_length=90)]
    service_name: Annotated[str, Field(min_length=1, max_length=64)]
    api_id: Annotated[str, Field(min_length=1, max_length=256)]
    capability: Annotated[str, Field(pattern=r"^(t1|t2)\.[a-z][a-z0-9._-]{1,63}$")]
    endpoint_ref: Annotated[str, Field(min_length=1, max_length=1024)]
    deployment: Annotated[str, Field(min_length=1, max_length=256)]
    auth_audience: Annotated[str, Field(min_length=1, max_length=1024)]
    publisher: Annotated[str, Field(min_length=1, max_length=64)]
    family: Annotated[str, Field(min_length=1, max_length=128)]
    version: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    capacity: CapacityConfig
    features: FeatureConfig
    ptu_backend_id: Annotated[str, Field(min_length=1, max_length=256)]
    standard_backend_id: Annotated[str, Field(min_length=1, max_length=256)]
    provider_kind: ModelProviderKind = ModelProviderKind.AZURE_OPENAI
    api_style: ModelApiStyle = ModelApiStyle.OPENAI_V1
    api_version: Annotated[str, Field(min_length=1, max_length=64)] | None = None


class DiscoveryConfig(_ConfigModel):
    schema_version: Literal["fdai.model-endpoint-discovery.v1"] = "fdai.model-endpoint-discovery.v1"
    azure_openai: tuple[AzureAccountConfig, ...] = ()
    apim: tuple[ApimRouteConfig, ...] = ()

    def model_post_init(self, __context: object) -> None:
        if not self.azure_openai and not self.apim:
            raise ValueError("endpoint discovery config MUST declare at least one source")


class EndpointDiscoveryCliError(RuntimeError):
    """Endpoint discovery input or output cannot be handled safely."""


async def _discover(config: DiscoveryConfig) -> tuple[ModelEndpointBinding, ...]:
    sources: list[ModelEndpointObservationSource] = []
    for account in config.azure_openai:
        sources.append(
            AzureCliOpenAIEndpointSource(
                resource_group=account.resource_group,
                account_name=account.account_name,
                specs=tuple(
                    AzureOpenAIDiscoverySpec(
                        capability=item.capability,
                        deployment=item.deployment,
                        api_version=item.api_version,
                        features=item.features.contract(),
                    )
                    for item in account.capabilities
                ),
            )
        )
    for route in config.apim:
        sources.append(
            AzureCliApimEndpointSource(
                spec=ApimEndpointDiscoverySpec(
                    resource_group=route.resource_group,
                    service_name=route.service_name,
                    api_id=route.api_id,
                    capability=route.capability,
                    endpoint_ref=route.endpoint_ref,
                    deployment=route.deployment,
                    auth_audience=route.auth_audience,
                    publisher=route.publisher,
                    family=route.family,
                    version=route.version,
                    capacity=ModelEndpointCapacity(
                        unit=route.capacity.unit,
                        value=route.capacity.value,
                    ),
                    features=route.features.contract(),
                    ptu_backend_id=route.ptu_backend_id,
                    standard_backend_id=route.standard_backend_id,
                    provider_kind=route.provider_kind,
                    api_style=route.api_style,
                    api_version=route.api_version,
                )
            )
        )
    return await discover_model_endpoints(tuple(sources))


def _read_config(path: Path) -> DiscoveryConfig:
    try:
        raw = _read_guarded(path, "endpoint discovery config")
        return DiscoveryConfig.model_validate_json(raw)
    except ValidationError as exc:
        raise EndpointDiscoveryCliError("endpoint discovery config is invalid") from exc


def _read_resolved(path: Path) -> ResolvedModels:
    try:
        return ResolvedModels.from_json(_read_guarded(path, "resolved models").decode())
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
        raise EndpointDiscoveryCliError("resolved models are invalid") from exc


def _read_guarded(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_INPUT_BYTES:
        raise EndpointDiscoveryCliError(f"{label} MUST be a bounded regular file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EndpointDiscoveryCliError(f"{label} is unreadable") from exc


def _write_private(path: Path, payload: bytes, *, force: bool) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".resolved-models-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise EndpointDiscoveryCliError("output already exists; use --force") from exc
            temporary.unlink()
        path.chmod(0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fdai-model-endpoint-discovery")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--resolved-models", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = _read_config(args.config)
        resolved = _read_resolved(args.resolved_models)
        bindings = asyncio.run(_discover(config))
        updated = replace(resolved, endpoint_bindings=bindings)
        _write_private(args.out, updated.to_json().encode(), force=args.force)
    except (EndpointDiscoveryCliError, RuntimeError, ValueError) as exc:
        print(f"endpoint discovery failed: {exc}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DISCOVERY_CONFIG_SCHEMA", "DiscoveryConfig", "EndpointDiscoveryCliError", "main"]
