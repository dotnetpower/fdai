"""Lifecycle-only nginx acceptance metadata, never an FDAI runtime inventory."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
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

NGINX_ACCEPTANCE_SCHEMA = "fdai.nginx-acceptance-release.v1"
NGINX_ACCEPTANCE_ENTITY_KIND = "nginx-acceptance"
LIFECYCLE_RELEASE_SCHEMAS = frozenset({"fdai.runtime-release.v3", NGINX_ACCEPTANCE_SCHEMA})
LIFECYCLE_IMAGE_SECTIONS = ("services", "sidecars", "installation_agents", "workloads")
_FIELDS = frozenset(
    {"schema_version", "release_version", "source_commit", "platform_tag", "workloads"}
)
_MAX_MANIFEST_BYTES = 1024 * 1024


class LifecycleRelease(SchemaMetadata, Protocol):
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
class NginxAcceptanceRelease:
    """Validated development metadata. Zero denotes no database, not an FDAI migration."""

    release_version: str
    source_commit: str
    platform_tag: str
    digest: str
    _catalog: bytes = field(repr=False)
    configuration_schema: ConfigurationSchema | None = None
    schema_version: str = field(default=NGINX_ACCEPTANCE_SCHEMA, init=False)
    schema_target: int = field(default=0, init=False)
    schema_range: SchemaRange = field(default=SchemaRange(0, 0), init=False)
    downtime_entities: tuple[str, ...] = field(default=(), init=False)

    @property
    def capability_maximums(self) -> Mapping[str, str]:
        return {}

    def to_mapping(self) -> dict[str, object]:
        return load_json_object(self._catalog, label="nginx acceptance release")


def parse_lifecycle_release_manifest(raw: bytes) -> LifecycleRelease:
    """Keep full runtime parsing unchanged; validate a separate, single-image development format."""
    try:
        document = load_json_object(raw, label="lifecycle release", max_bytes=_MAX_MANIFEST_BYTES)
        if document.get("schema_version") != NGINX_ACCEPTANCE_SCHEMA:
            return parse_runtime_release_manifest(raw)
        if not _FIELDS <= document.keys() <= _FIELDS | {"configuration_schema"}:
            raise ValueError("acceptance fields are invalid")
        version = document["release_version"]
        commit = document["source_commit"]
        platform = document["platform_tag"]
        if not isinstance(version, str) or not is_release_id(version):
            raise ValueError("acceptance version is invalid")
        if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
            raise ValueError("acceptance source is invalid")
        if not isinstance(platform, str) or platform not in {"linux-x86_64", "linux-aarch64"}:
            raise ValueError("acceptance platform is invalid")
        workloads = document["workloads"]
        if not isinstance(workloads, dict) or set(workloads) != {"nginx"}:
            raise ValueError("acceptance requires only nginx")
        image = workloads["nginx"]
        if not isinstance(image, dict) or set(image) != {"image_digest"}:
            raise ValueError("acceptance image fields are invalid")
        digest = image["image_digest"]
        if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise ValueError("acceptance image must be digest-pinned")
        schema = (
            parse_release_configuration_schema(document["configuration_schema"])
            if "configuration_schema" in document
            else None
        )
        if schema is not None and schema.release_version != version:
            raise ValueError("acceptance configuration version differs")
        return NginxAcceptanceRelease(
            release_version=version,
            source_commit=commit,
            platform_tag=platform,
            digest=canonical_digest(document),
            _catalog=canonical_bytes(document),
            configuration_schema=schema,
        )
    except RuntimeReleaseError:
        raise
    except (ValueError, TypeError, RecursionError) as error:
        raise RuntimeReleaseError("Lifecycle release metadata is invalid.") from error
