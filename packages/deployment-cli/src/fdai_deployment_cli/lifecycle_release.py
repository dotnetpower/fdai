"""Application-neutral lifecycle packages and the legacy runtime compatibility adapter."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol

from fdai_deployment_cli.contracts import canonical_bytes, canonical_digest, load_json_object
from fdai_deployment_cli.runtime_release import (
    ConfigurationSchema,
    RuntimeReleaseError,
    SchemaMetadata,
    SchemaRange,
    is_release_id,
    parse_release_configuration_schema,
    parse_runtime_release_manifest,
)

APPLICATION_RELEASE_SCHEMA = "fdai.application-release.v1"
LIFECYCLE_RELEASE_SCHEMAS = frozenset({"fdai.runtime-release.v3", APPLICATION_RELEASE_SCHEMA})
LIFECYCLE_IMAGE_SECTIONS = ("services", "sidecars", "installation_agents", "workloads")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,62}\Z", re.ASCII)
_COMPONENT = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z", re.ASCII)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_FIELDS = frozenset(
    {"schema_version", "product", "release_version", "source_commit", "platform_tag", "workloads"}
)


def is_product_id(value: object) -> bool:
    return isinstance(value, str) and _IDENTIFIER.fullmatch(value) is not None


class LifecycleRelease(SchemaMetadata, Protocol):
    @property
    def product(self) -> str | None: ...

    @property
    def schema_version(self) -> str: ...

    @property
    def source_commit(self) -> str: ...

    @property
    def platform_tag(self) -> str: ...

    @property
    def digest(self) -> str: ...

    @property
    def capability_maximums(self) -> Mapping[str, str]: ...

    @property
    def downtime_entities(self) -> tuple[str, ...]: ...

    @property
    def configuration_schema(self) -> ConfigurationSchema | None: ...

    def to_mapping(self) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class HttpWorkload:
    image_digest: str
    port: int = 8080
    health_path: str = "/"
    replicas: int = 1


@dataclass(frozen=True, slots=True)
class ApplicationRelease:
    product: str
    release_version: str
    source_commit: str
    platform_tag: str
    digest: str
    workloads: Mapping[str, HttpWorkload]
    _catalog: bytes = field(repr=False)
    schema_target: int = 0
    schema_range: SchemaRange = SchemaRange(0, 0)
    configuration_schema: ConfigurationSchema | None = None
    schema_version: str = field(default=APPLICATION_RELEASE_SCHEMA, init=False)
    downtime_entities: tuple[str, ...] = field(default=(), init=False)

    @property
    def capability_maximums(self) -> Mapping[str, str]:
        return {}

    def to_mapping(self) -> dict[str, object]:
        return load_json_object(self._catalog, label="application release", strict=True)


def parse_lifecycle_release_manifest(raw: bytes) -> LifecycleRelease:
    """Validate bounded strict JSON before either format reaches publication or execution."""
    try:
        document = load_json_object(raw, label="lifecycle release", strict=True)
        if document.get("schema_version") != APPLICATION_RELEASE_SCHEMA:
            return parse_runtime_release_manifest(raw)
        if not _FIELDS <= document.keys() <= _FIELDS | {"configuration_schema", "schema"}:
            raise ValueError("application fields are invalid")
        product = document["product"]
        version = document["release_version"]
        commit = document["source_commit"]
        platform = document["platform_tag"]
        if not isinstance(product, str) or not is_product_id(product):
            raise ValueError("application product is invalid")
        if not isinstance(version, str) or not is_release_id(version) or len(version) > 64:
            raise ValueError("application version is invalid")
        if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise ValueError("application source is invalid")
        if not isinstance(platform, str) or platform not in {"linux-x86_64", "linux-aarch64"}:
            raise ValueError("application platform is invalid")
        workloads = document["workloads"]
        if not isinstance(workloads, dict) or not 1 <= len(workloads) <= 64:
            raise ValueError("application requires bounded workloads")
        parsed_workloads = {name: _workload(name, value) for name, value in workloads.items()}
        configuration = (
            parse_release_configuration_schema(document["configuration_schema"])
            if "configuration_schema" in document
            else None
        )
        if configuration is not None and configuration.release_version != version:
            raise ValueError("application configuration version differs")
        target, schema_range = (
            _schema(document["schema"]) if "schema" in document else (0, SchemaRange(0, 0))
        )
        return ApplicationRelease(
            product=product,
            release_version=version,
            source_commit=commit,
            platform_tag=platform,
            digest=canonical_digest(document),
            workloads=MappingProxyType(parsed_workloads),
            _catalog=canonical_bytes(document),
            schema_target=target,
            schema_range=schema_range,
            configuration_schema=configuration,
        )
    except RuntimeReleaseError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise RuntimeReleaseError("Lifecycle release metadata is invalid.") from error


def _workload(name: object, value: object) -> HttpWorkload:
    if not isinstance(name, str) or _COMPONENT.fullmatch(name) is None:
        raise ValueError("application component is invalid")
    if not isinstance(value, dict) or not (
        {"image_digest"} <= value.keys() <= {"image_digest", "port", "health_path", "replicas"}
    ):
        raise ValueError("application workload fields are invalid")
    digest = value["image_digest"]
    port = value.get("port", 8080)
    path = value.get("health_path", "/")
    replicas = value.get("replicas", 1)
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError("application image must be digest-pinned")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("application port is invalid")
    if (
        not isinstance(path, str)
        or path.startswith("//")
        or not re.fullmatch(r"/[A-Za-z0-9/._~-]{0,255}", path, re.ASCII)
    ):
        raise ValueError("application health path is invalid")
    if type(replicas) is not int or not 1 <= replicas <= 3:
        raise ValueError("application replicas are invalid")
    return HttpWorkload(digest, port, path, replicas)


def _schema(value: object) -> tuple[int, SchemaRange]:
    if not isinstance(value, dict) or set(value) != {"target", "tolerates"}:
        raise ValueError("application schema is invalid")
    target = value["target"]
    limits = value["tolerates"]
    if not isinstance(limits, dict) or set(limits) != {"minimum", "maximum"}:
        raise ValueError("application schema range is invalid")
    minimum, maximum = limits["minimum"], limits["maximum"]
    if any(type(item) is not int for item in (target, minimum, maximum)) or not (
        0 <= minimum <= target <= maximum <= 2**31 - 1
    ):
        raise ValueError("application schema revisions are invalid")
    return target, SchemaRange(minimum, maximum)
