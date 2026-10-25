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
APPLICATION_COMPONENT_RELEASE_SCHEMA = "fdai.application-release.v2"
SCHEMA_EXPAND_JOB_SCHEMA = "fdai.schema-expand-job.v1"
MIGRATION_CLASSIFICATION_SCHEMA = "fdai.migration-classification.v1"
APPLICATION_RELEASE_SCHEMAS = frozenset(
    {APPLICATION_RELEASE_SCHEMA, APPLICATION_COMPONENT_RELEASE_SCHEMA}
)
LIFECYCLE_RELEASE_SCHEMAS = frozenset({"fdai.runtime-release.v3", *APPLICATION_RELEASE_SCHEMAS})
LIFECYCLE_IMAGE_SECTIONS = (
    "services",
    "sidecars",
    "installation_agents",
    "workloads",
    "components",
)
_IDENTIFIER = re.compile(r"[a-z][a-z0-9-]{0,62}\Z", re.ASCII)
_COMPONENT = re.compile(r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z", re.ASCII)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_REVISION_ID = re.compile(r"[A-Za-z0-9_]{1,128}\Z", re.ASCII)
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
class SchemaExpandMigration:
    classification: Mapping[str, str]
    active_deadline_seconds: int


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
    schema_expand: SchemaExpandMigration | None = None
    schema_version: str = APPLICATION_RELEASE_SCHEMA
    components: Mapping[str, str] = field(default_factory=dict)
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
        schema_version = document.get("schema_version")
        if schema_version not in APPLICATION_RELEASE_SCHEMAS:
            return parse_runtime_release_manifest(raw)
        section = (
            "components" if schema_version == APPLICATION_COMPONENT_RELEASE_SCHEMA else "workloads"
        )
        required = (_FIELDS - {"workloads"}) | {section}
        if (
            not required
            <= document.keys()
            <= required
            | {
                "configuration_schema",
                "schema",
                "schema_expand",
            }
        ):
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
        workloads = document[section]
        if not isinstance(workloads, dict) or not 1 <= len(workloads) <= 64:
            raise ValueError("application requires bounded workloads")
        component_only = schema_version == APPLICATION_COMPONENT_RELEASE_SCHEMA
        parsed_workloads = (
            {}
            if component_only
            else {name: _workload(name, value) for name, value in workloads.items()}
        )
        parsed_components = (
            {
                name: _image_record(name, value, allowed={"image_digest"})
                for name, value in workloads.items()
            }
            if component_only
            else {}
        )
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
        schema_expand = (
            _schema_expand(document["schema_expand"]) if "schema_expand" in document else None
        )
        if schema_expand is not None and (
            not component_only or target == 0 or not schema_expand.classification
        ):
            raise ValueError("schema expand Job requires a component Release schema transition")
        catalog = canonical_bytes(document)
        load_json_object(catalog, label="canonical application release", strict=True)
        return ApplicationRelease(
            product=product,
            release_version=version,
            source_commit=commit,
            platform_tag=platform,
            digest=canonical_digest(document),
            workloads=MappingProxyType(parsed_workloads),
            _catalog=catalog,
            schema_target=target,
            schema_range=schema_range,
            configuration_schema=configuration,
            schema_expand=schema_expand,
            schema_version=str(schema_version),
            components=MappingProxyType(parsed_components),
        )
    except RuntimeReleaseError:
        raise
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        raise RuntimeReleaseError("Lifecycle release metadata is invalid.") from error


def _image_record(name: object, value: object, *, allowed: set[str]) -> str:
    if not isinstance(name, str) or _COMPONENT.fullmatch(name) is None:
        raise ValueError("application component is invalid")
    if not isinstance(value, dict) or not {"image_digest"} <= value.keys() <= allowed:
        raise ValueError("application workload fields are invalid")
    digest = value["image_digest"]
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise ValueError("application image must be digest-pinned")
    return digest


def _workload(name: object, value: object) -> HttpWorkload:
    digest = _image_record(name, value, allowed={"image_digest", "port", "health_path", "replicas"})
    if not isinstance(value, dict):
        raise ValueError("application workload fields are invalid")
    port = value.get("port", 8080)
    path = value.get("health_path", "/")
    replicas = value.get("replicas", 1)
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


def _schema_expand(value: object) -> SchemaExpandMigration:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"schema_version", "classification", "active_deadline_seconds"}
        or value["schema_version"] != SCHEMA_EXPAND_JOB_SCHEMA
        or not isinstance(value["classification"], Mapping)
    ):
        raise ValueError("schema expand Job is invalid")
    classification = value["classification"]
    if (
        set(classification) != {"schema", "revisions"}
        or classification["schema"] != MIGRATION_CLASSIFICATION_SCHEMA
        or not isinstance(classification["revisions"], Mapping)
        or not classification["revisions"]
        or not all(
            isinstance(revision, str)
            and _REVISION_ID.fullmatch(revision)
            and migration_class in {"expand", "contract"}
            for revision, migration_class in classification["revisions"].items()
        )
    ):
        raise ValueError("migration classification is invalid")
    if any(
        migration_class == "contract" for migration_class in classification["revisions"].values()
    ):
        raise ValueError("schema expand Job cannot contain contract revisions")
    deadline = value["active_deadline_seconds"]
    if type(deadline) is not int or not 60 <= deadline <= 3600:
        raise ValueError("schema expand Job deadline is invalid")
    return SchemaExpandMigration(
        MappingProxyType(
            {
                str(revision): str(migration_class)
                for revision, migration_class in classification["revisions"].items()
            }
        ),
        deadline,
    )


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
