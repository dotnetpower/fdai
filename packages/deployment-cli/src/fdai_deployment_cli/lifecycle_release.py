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
    stencil: Mapping[str, object] | None = None
    downtime_entities: tuple[str, ...] = field(default=(), init=False)

    @property
    def capability_maximums(self) -> Mapping[str, str]:
        if self.stencil is None:
            return {}
        caps: dict[str, str] = {}
        stencil_id = self.stencil.get("stencil_id")
        if isinstance(stencil_id, str):
            caps[f"stencil:{stencil_id}"] = "enabled"
        for key in ("enabled_workloads", "enabled_loops"):
            items = self.stencil.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str):
                        caps[item] = "enabled"
        raw_panels = self.stencil.get("enabled_panel_ids")
        if isinstance(raw_panels, list):
            for panel in raw_panels:
                if isinstance(panel, str):
                    caps[f"panel:{panel}"] = "enabled"
        raw_jobs = self.stencil.get("enabled_scheduled_jobs")
        if isinstance(raw_jobs, list):
            for job in raw_jobs:
                if isinstance(job, str):
                    caps[f"job:{job}"] = "enabled"
        feature_flags = self.stencil.get("feature_flags")
        if isinstance(feature_flags, dict) and isinstance(
            feature_flags.get("enabled_addons"), list
        ):
            for addon in feature_flags["enabled_addons"]:
                if isinstance(addon, str):
                    caps[f"addon:{addon}"] = "enabled"
        return caps

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
                "stencil",
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
                name: _image_record(name, value, allowed={"image_digest", "image_ref"})
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
        stencil_meta = (
            _validate_release_stencil(
                document["stencil"],
                parsed_components=parsed_components,
                component_only=component_only,
            )
            if "stencil" in document
            else None
        )
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
            stencil=stencil_meta,
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
    if "image_ref" in value:
        reference = value["image_ref"]
        if (
            not isinstance(reference, str)
            or len(reference) > 512
            or re.fullmatch(
                r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?"
                r"(?::[1-9][0-9]{0,4})?/"
                r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
                r"@sha256:[0-9a-f]{64}",
                reference,
                re.ASCII,
            )
            is None
            or reference.rsplit("@", 1)[1] != digest
        ):
            raise ValueError("application image source must match its signed digest")
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


def _validate_release_stencil(
    value: object,
    *,
    parsed_components: Mapping[str, str],
    component_only: bool,
) -> Mapping[str, object]:
    if not component_only or not isinstance(value, dict):
        raise ValueError("stencil metadata requires an application-release.v2 object")
    required_keys = {
        "stencil_id",
        "stencil_digest",
        "topology_profile",
        "azure_rbac_posture",
        "enabled_workloads",
        "enabled_panel_ids",
    }
    optional_keys = {
        "title",
        "title_ko",
        "omitted_workloads",
        "enabled_loops",
        "disabled_loops",
        "enabled_scheduled_jobs",
        "disabled_panel_ids",
        "required_azure_roles",
        "release_labels",
        "feature_flags",
    }
    if not required_keys <= value.keys() <= (required_keys | optional_keys):
        raise ValueError("stencil metadata fields are invalid")
    stencil_id = value["stencil_id"]
    stencil_digest = value["stencil_digest"]
    profile = value["topology_profile"]
    rbac_posture = value["azure_rbac_posture"]
    workloads = value["enabled_workloads"]
    panels = value["enabled_panel_ids"]
    if not isinstance(stencil_id, str) or _IDENTIFIER.fullmatch(stencil_id) is None:
        raise ValueError("stencil_id is invalid")
    if not isinstance(stencil_digest, str) or _DIGEST.fullmatch(stencil_digest) is None:
        raise ValueError("stencil_digest is invalid")
    if profile not in {"lite-observe-alert", "standard-sre", "full-enterprise"}:
        raise ValueError("stencil topology_profile is invalid")
    if rbac_posture not in {"read-only-observation", "governed-execution"}:
        raise ValueError("stencil azure_rbac_posture is invalid")
    if (
        not isinstance(workloads, list)
        or not all(isinstance(w, str) and _COMPONENT.fullmatch(w) for w in workloads)
        or not {"core-control-plane", "operator-service"}.issubset(workloads)
    ):
        raise ValueError("stencil enabled_workloads must include locked safety-core workloads")
    if (
        not isinstance(panels, list)
        or not all(isinstance(p, str) and _IDENTIFIER.fullmatch(p) for p in panels)
        or not {"audit", "dashboard", "settings-general"}.issubset(panels)
    ):
        raise ValueError("stencil enabled_panel_ids must include locked safety-core panels")
    disabled_panels = value.get("disabled_panel_ids")
    if disabled_panels is not None:
        if (
            not isinstance(disabled_panels, list)
            or not all(isinstance(p, str) and _IDENTIFIER.fullmatch(p) for p in disabled_panels)
            or bool({"audit", "dashboard", "settings-general"} & set(disabled_panels))
            or bool(set(panels) & set(disabled_panels))
        ):
            raise ValueError("stencil disabled_panel_ids is invalid or overlaps enabled_panel_ids")
    enabled_loops = value.get("enabled_loops")
    disabled_loops = value.get("disabled_loops")
    if disabled_loops is not None:
        if (
            not isinstance(disabled_loops, list)
            or not all(isinstance(lp, str) and _IDENTIFIER.fullmatch(lp) for lp in disabled_loops)
            or bool(
                {
                    "anomaly-analyzer",
                    "inventory-reconciliation",
                    "notification-dispatch",
                    "saga-audit",
                }
                & set(disabled_loops)
            )
            or (isinstance(enabled_loops, list) and bool(set(enabled_loops) & set(disabled_loops)))
        ):
            raise ValueError("stencil disabled_loops is invalid or overlaps enabled_loops")
    expected_components = set(workloads) | {"pgvector"}
    if "document-ingestion-api" in workloads:
        expected_components.add("clamav")
    if set(parsed_components) != expected_components:
        raise ValueError("stencil enabled_workloads do not match manifest components")
    feature_flags = value.get("feature_flags")
    if feature_flags is not None:
        _validate_stencil_feature_flags(
            feature_flags,
            stencil_id=stencil_id,
            stencil_digest=stencil_digest,
            enabled_panels=set(panels),
        )
    return MappingProxyType(dict(value))


def _validate_stencil_feature_flags(
    value: object,
    *,
    stencil_id: str,
    stencil_digest: str,
    enabled_panels: set[str],
) -> None:
    if not isinstance(value, dict):
        raise ValueError("stencil feature_flags must be an object")
    if value.get("schema_version") != "fdai.stencil-feature-flags.v1":
        raise ValueError("stencil feature_flags schema_version is invalid")
    if value.get("enforcement_mode") != "fail-closed":
        raise ValueError("stencil feature_flags enforcement_mode must be fail-closed")
    if "stencil_id" in value and value["stencil_id"] != stencil_id:
        raise ValueError("stencil feature_flags.stencil_id does not match parent stencil_id")
    if "stencil_digest" in value and value["stencil_digest"] != stencil_digest:
        raise ValueError(
            "stencil feature_flags.stencil_digest does not match parent stencil_digest"
        )
    ff_digest = value.get("feature_flags_digest")
    if ff_digest is not None and (
        not isinstance(ff_digest, str) or _DIGEST.fullmatch(ff_digest) is None
    ):
        raise ValueError("stencil feature_flags.feature_flags_digest is invalid")
    panel_flags = value.get("panel_flags")
    if not isinstance(panel_flags, dict) or not all(
        isinstance(k, str) and _IDENTIFIER.fullmatch(k) and type(v) is bool
        for k, v in panel_flags.items()
    ):
        raise ValueError("stencil feature_flags.panel_flags is invalid")
    for locked_panel in ("audit", "dashboard", "settings-general"):
        if panel_flags.get(locked_panel) is not True:
            raise ValueError(
                "stencil feature_flags.panel_flags must keep locked safety-core panels enabled"
            )
    for enabled_panel in enabled_panels:
        if panel_flags.get(enabled_panel) is not True:
            raise ValueError("stencil feature_flags.panel_flags must match enabled_panel_ids")
    ff_disabled_panels = value.get("disabled_panel_ids")
    if isinstance(ff_disabled_panels, list):
        if bool(enabled_panels & set(ff_disabled_panels)) or any(
            panel_flags.get(dp) is not False for dp in ff_disabled_panels if isinstance(dp, str)
        ):
            raise ValueError("stencil feature_flags.disabled_panel_ids contradicts panel_flags")
    loop_flags = value.get("loop_flags")
    if not isinstance(loop_flags, dict) or not all(
        isinstance(k, str) and _IDENTIFIER.fullmatch(k) and type(v) is bool
        for k, v in loop_flags.items()
    ):
        raise ValueError("stencil feature_flags.loop_flags is invalid")
    for locked_loop in (
        "anomaly-analyzer",
        "inventory-reconciliation",
        "notification-dispatch",
        "saga-audit",
    ):
        if loop_flags.get(locked_loop) is not True:
            raise ValueError(
                "stencil feature_flags.loop_flags must keep locked safety-core loops enabled"
            )
    for map_key, locked_keys in (
        ("workload_flags", ("core-control-plane", "operator-service")),
        ("scheduled_job_flags", ("analyzer", "inventory")),
        ("addon_flags", ("notifications", "read-only-console")),
    ):
        axis_map = value.get(map_key)
        if axis_map is not None:
            if not isinstance(axis_map, dict) or not all(
                isinstance(k, str) and _IDENTIFIER.fullmatch(k) and type(v) is bool
                for k, v in axis_map.items()
            ):
                raise ValueError(f"stencil feature_flags.{map_key} is invalid")
            if any(axis_map.get(lk) is not True for lk in locked_keys):
                raise ValueError(
                    f"stencil feature_flags.{map_key} must keep locked core items enabled"
                )
    runtime_env = value.get("runtime_env")
    if (
        not isinstance(runtime_env, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in runtime_env.items())
        or runtime_env.get("FDAI_STENCIL_ENFORCE_INACTIVE_MENUS") != "1"
    ):
        raise ValueError("stencil feature_flags.runtime_env is invalid")


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
