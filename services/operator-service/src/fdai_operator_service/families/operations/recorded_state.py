"""Allowlisted recorded Resource facts, without health or execution judgments."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypedDict

MAX_STATE_VALUE_CHARS = 256
MAX_STATE_CONFLICTS = 16
DEFAULT_STATE_FRESHNESS_CEILING_SECONDS = 21_600
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})")
_OPERATIONAL_PATHS = (
    "status",
    "state",
    "phase",
    "ready_status",
    "readiness",
    "runningStatus",
    "operationalState",
    "dnsResolverState",
    "diskState",
    "resourceState",
    "snapshotAccessState",
    "userVisibleState",
    "virtualNetworkLinkState",
    "powerState.code",
    "powerState",
    "instanceView.powerState.code",
    "extended.instanceView.powerState.code",
)
OPERATIONAL_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE: Mapping[str, tuple[str, ...]] = {
    "app-service-plan": ("powerState", "status"),
    "compute.container-app": ("runningStatus",),
    "compute.container-app-job": ("runningStatus",),
    "compute.function": ("state",),
    "compute.vm": (
        "powerState",
        "instanceView.powerState.code",
        "extended.instanceView.powerState.code",
    ),
    "compute.vm-shutdown-schedule": ("status",),
    "compute.web-app": ("state",),
    "disk": ("diskState",),
    "disk-snapshot": ("snapshotAccessState", "diskState"),
    "event-hub": ("status",),
    "kubernetes-cluster": ("powerState",),
    "kubernetes.daemon-set": ("ready_status",),
    "kubernetes.deployment": ("ready_status",),
    "kubernetes.job": ("phase",),
    "kubernetes.node": ("ready_status",),
    "kubernetes-node-pool": ("powerState.code",),
    "kubernetes.pod": ("phase",),
    "kubernetes.replica-set": ("ready_status",),
    "kubernetes.stateful-set": ("ready_status",),
    "mysql-server": ("state",),
    "network.application-gateway": ("operationalState",),
    "network.dns-resolver": ("dnsResolverState",),
    "network.private-dns-zone-link": ("virtualNetworkLinkState",),
    "postgresql-server": ("state",),
    "redis-enterprise": ("resourceState",),
    "service-bus-namespace": ("status",),
    "sql-database": ("status",),
    "sql-server": ("state",),
    "subscription": ("state",),
    "workflow.logic-app": ("state",),
}
OPERATIONAL_STATE_NOT_APPLICABLE_RESOURCE_TYPES = frozenset(
    {
        "action-group",
        "alert-rule",
        "authorization.role-assignment",
        "certificate",
        "compute.vm-scale-set",
        "data-collection-rule",
        "diagnostic-settings",
        "email-domain",
        "kubernetes.cron-job",
        "kubernetes.endpoint-slice",
        "kubernetes.endpoints",
        "kubernetes.ingress",
        "kubernetes.ingress-class",
        "kubernetes.namespace",
        "kubernetes.service",
        "managed-identity",
        "network.private-dns-zone-group",
        "resource-group",
    }
)
RESOURCE_HEALTH_OPERATIONAL_STATE_RESOURCE_TYPES = frozenset(
    {
        "application-insights",
        "log-workspace",
    }
)
PROVIDER_OPERATIONAL_STATE_NOT_EXPOSED_RESOURCE_TYPES = frozenset(
    {
        "api-gateway",
        "cache",
        "communication-service",
        "compute.container-app-environment",
        "container-registry",
        "data-collection-endpoint",
        "email-service",
        "event-grid-topic",
        "file-share",
        "llm-endpoint",
        "llm-model-deployment",
        "metrics-workspace",
        "network.dns-resolver-inbound-endpoint",
        "network.dns-zone",
        "network.firewall",
        "network.interface",
        "network.load-balancer",
        "network.nat-gateway",
        "network.nsg",
        "network.private-dns-zone",
        "network.private-endpoint",
        "network.public-ip",
        "network.route-table",
        "network.subnet",
        "network.virtual-network-gateway",
        "network.vnet",
        "nosql-database",
        "object-storage",
        "secret-store",
        "static-web-app",
    }
)


@dataclass(frozen=True, slots=True)
class RecordedStateObservation:
    """Immutable snapshot columns that qualify one retained provider value."""

    generation: str
    observed_at: datetime
    recorded_at: datetime
    freshness_ceiling_seconds: int = DEFAULT_STATE_FRESHNESS_CEILING_SECONDS

    def __post_init__(self) -> None:
        if not self.generation.strip():
            raise ValueError("recorded state generation MUST be non-empty")
        if any(
            value.tzinfo is None or value.utcoffset() is None
            for value in (
                self.observed_at,
                self.recorded_at,
            )
        ):
            raise ValueError("recorded state observation times MUST be timezone-aware")
        if self.freshness_ceiling_seconds < 1:
            raise ValueError("recorded state freshness ceiling MUST be positive")


class RecordedStateFact(TypedDict):
    """One exact supplied state value with nullable, property-scoped metadata."""

    value: str | None
    source_path: str | None
    observed_at: str | None
    recorded_at: str | None
    freshness: Literal["fresh", "stale", "unknown"]
    completeness: float | None
    conflicts: list[str]
    reason: str | None


def recorded_resource_states(
    properties: Mapping[str, object],
    *,
    resource_type: str | None = None,
    observation: RecordedStateObservation | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Project three separate recorded lanes, never substituting inventory observation time.

    Paths cover the inventory property bag and its canonical Resource wrapper.
    Flat canonical metadata applies only to its sibling status/state; keyed metadata
    must name the exact selected property. No provider payload or verifier claim escapes.
    """
    evaluated_at = now if now is not None else datetime.now(UTC)
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("recorded state evaluation time MUST be timezone-aware")
    return {
        "schema_version": "1.0.0",
        "operational": _fact(
            properties,
            _OPERATIONAL_PATHS,
            evaluated_at,
            resource_type=resource_type,
            observation=observation,
        ),
        "provisioning": _fact(
            properties,
            ("provisioningState",),
            evaluated_at,
            resource_type=resource_type,
            observation=observation,
        ),
        "availability": _fact(
            properties,
            ("availabilityState",),
            evaluated_at,
            resource_type=resource_type,
            observation=observation,
        ),
    }


def _fact(
    properties: Mapping[str, object],
    paths: tuple[str, ...],
    now: datetime,
    *,
    resource_type: str | None,
    observation: RecordedStateObservation | None,
) -> RecordedStateFact:
    result: RecordedStateFact = {
        "value": None,
        "source_path": None,
        "observed_at": None,
        "recorded_at": None,
        "freshness": "unknown",
        "completeness": None,
        "conflicts": [],
        "reason": _missing_reason(resource_type, paths),
    }
    for prefix in ("", "properties.", "properties.properties."):
        for path in paths:
            source_path = prefix + path
            value = _at(properties, source_path)
            if (
                not isinstance(value, str)
                or not value.strip()
                or value.strip().casefold() == "unknown"
            ):
                continue
            if len(value) > MAX_STATE_VALUE_CHARS or any(ord(char) < 32 for char in value):
                result["reason"] = "state_value_invalid"
                continue
            result["value"] = value
            result["source_path"] = source_path
            metadata = _metadata(properties, source_path, prefix, path)
            if metadata is None and observation is not None:
                metadata = _snapshot_metadata(observation, source_path)
            if metadata is None:
                result["reason"] = "state_metadata_not_recorded"
                return result
            try:
                _qualify_metadata(result, metadata, now)
            except ValueError:
                result.update(
                    {
                        "observed_at": None,
                        "recorded_at": None,
                        "freshness": "unknown",
                        "completeness": None,
                        "conflicts": [],
                        "reason": "state_metadata_invalid",
                    }
                )
            return result
    return result


def _missing_reason(resource_type: str | None, paths: tuple[str, ...]) -> str:
    if resource_type == "unclassified-resource":
        return "resource_type_unclassified"
    if paths == _OPERATIONAL_PATHS and resource_type is not None:
        if resource_type in OPERATIONAL_STATE_SOURCE_PATHS_BY_RESOURCE_TYPE:
            return "state_source_not_recorded"
        if resource_type in OPERATIONAL_STATE_NOT_APPLICABLE_RESOURCE_TYPES:
            return "state_not_applicable"
        if resource_type in RESOURCE_HEALTH_OPERATIONAL_STATE_RESOURCE_TYPES:
            return "resource_health_projection_not_bound"
        if resource_type in PROVIDER_OPERATIONAL_STATE_NOT_EXPOSED_RESOURCE_TYPES:
            return "provider_operational_state_not_exposed"
        return "state_applicability_unknown"
    return "state_not_recorded"


def _snapshot_metadata(
    observation: RecordedStateObservation,
    source_path: str,
) -> Mapping[str, object]:
    """Qualify legacy snapshot values from their immutable row and snapshot timestamps."""

    return {
        "source_path": source_path,
        "lane": "observed",
        "authority": "provider",
        "source_identity": "inventory-snapshot",
        "source_revision": observation.generation,
        "effective_at": observation.observed_at.isoformat(),
        "recorded_at": observation.recorded_at.isoformat(),
        "evidence_cutoff": observation.recorded_at.isoformat(),
        "freshness_ceiling_seconds": observation.freshness_ceiling_seconds,
        "completeness": 1.0,
        "synthetic": False,
        "conflicts": [],
        "evidence_refs": [f"inventory-generation:{observation.generation}"],
    }


def _at(properties: Mapping[str, object], path: str) -> object:
    current: object = properties
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _metadata(
    properties: Mapping[str, object], source_path: str, prefix: str, path: str
) -> Mapping[str, object] | None:
    for owner_path in dict.fromkeys(("", prefix)):
        raw = _at(properties, owner_path + "state_fact_metadata")
        if not isinstance(raw, Mapping):
            continue
        for key in dict.fromkeys((source_path, path if owner_path == prefix else source_path)):
            selected = raw.get(key)
            if isinstance(selected, Mapping):
                declared_path = selected.get("source_path")
                if declared_path is not None and (
                    not isinstance(declared_path, str)
                    or declared_path
                    not in {source_path, path if owner_path == prefix else source_path}
                ):
                    return None
                return selected
        declared_path = raw.get("source_path")
        if declared_path == source_path:
            return raw
        if (
            declared_path is None
            and owner_path == prefix
            and path in {"status", "state"}
            and "lane" in raw
        ):
            return raw
    return None


def _qualify_metadata(
    result: RecordedStateFact, metadata: Mapping[str, object], now: datetime
) -> None:
    """Qualify recorded time and limits only; this is not evidence admission."""
    if metadata.get("lane", "observed") != "observed":
        raise ValueError("metadata does not describe an observed property")
    if metadata.get("authority", "provider") not in ("provider", "telemetry"):
        raise ValueError("metadata does not describe a provider or telemetry property")
    if "synthetic" in metadata and not isinstance(metadata["synthetic"], bool):
        raise ValueError("invalid recorded synthetic flag")
    observed = _timestamp(metadata.get("effective_at", metadata.get("observed_at")))
    recorded = _timestamp(metadata.get("recorded_at"))
    cutoff = _timestamp(metadata.get("evidence_cutoff"))
    completeness = metadata.get("completeness")
    if completeness is not None and (
        isinstance(completeness, bool)
        or not isinstance(completeness, (int, float))
        or not 0 <= completeness <= 1
    ):
        raise ValueError("invalid recorded completeness")
    conflicts = metadata.get("conflicts", [])
    if (
        not isinstance(conflicts, (tuple, list))
        or len(conflicts) > MAX_STATE_CONFLICTS
        or any(
            not isinstance(item, str)
            or not item.strip()
            or len(item) > MAX_STATE_VALUE_CHARS
            or any(ord(char) < 32 for char in item)
            for item in conflicts
        )
    ):
        raise ValueError("invalid recorded conflicts")
    ceiling = metadata.get("freshness_ceiling_seconds")
    if ceiling is not None and (
        isinstance(ceiling, bool) or not isinstance(ceiling, int) or not 1 <= ceiling <= 31_536_000
    ):
        raise ValueError("invalid recorded freshness ceiling")
    result["observed_at"] = observed.isoformat() if observed is not None else None
    result["recorded_at"] = recorded.isoformat() if recorded is not None else None
    result["completeness"] = float(completeness) if completeness is not None else None
    result["conflicts"] = list(conflicts)
    result["reason"] = None
    if (
        (observed is not None and cutoff is not None and observed > cutoff)
        or (cutoff is not None and recorded is not None and cutoff > recorded)
        or (observed is not None and recorded is not None and observed > recorded)
    ):
        raise ValueError("recorded state timestamps are inconsistent")
    declared_observation = (
        metadata.get("lane") == "observed"
        and metadata.get("authority") in ("provider", "telemetry")
        and metadata.get("synthetic") is False
    )
    if any(stamp is not None and stamp > now for stamp in (observed, cutoff, recorded)):
        result["reason"] = "state_after_cutoff"
    elif (
        declared_observation
        and observed is not None
        and recorded is not None
        and cutoff is not None
        and ceiling is not None
    ):
        age = (now - observed).total_seconds()
        result["freshness"] = "stale" if age > ceiling else "fresh"
    if result["conflicts"]:
        result["reason"] = "state_conflicting"
    elif result["freshness"] == "stale":
        result["reason"] = "state_stale"
    elif metadata.get("synthetic") is True:
        result["reason"] = "state_synthetic"
    elif result["reason"] is None and (
        observed is None
        or recorded is None
        or completeness is None
        or completeness < 1
        or result["freshness"] == "unknown"
    ):
        result["reason"] = "state_metadata_incomplete"


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40 or _TIMESTAMP.fullmatch(value) is None:
        raise ValueError("invalid recorded timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    try:
        parsed.astimezone(UTC)
    except OverflowError as exc:
        raise ValueError("invalid recorded timestamp range") from exc
    return parsed
