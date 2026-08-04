"""Immutable models for deterministic configuration drift evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceCompleteness(StrEnum):
    """Coverage status for one current-state snapshot."""

    COMPLETE = "complete"
    PARTIAL = "partial"


class DriftType(StrEnum):
    """Relationship between frozen intent and current evidence."""

    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    UNKNOWN = "unknown"
    UNAUTHORIZED = "unauthorized"


class DriftVerdict(StrEnum):
    """Evidence-aware result for a finding or report."""

    PASSED = "passed"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    FAILED = "failed"
    NOT_APPLICABLE = "not-applicable"


class KnowledgeGroundingStatus(StrEnum):
    """Whether the exact frozen baseline received a knowledge citation."""

    CITED = "cited"
    BLOCKED = "blocked"
    NOT_CONFIGURED = "not-configured"


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _freeze(value: object, *, path: str) -> JsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} MUST contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{path} keys MUST be non-empty strings")
            frozen[key] = _freeze(item, path=f"{path}.{key}")
        return MappingProxyType(dict(sorted(frozen.items())))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze(item, path=f"{path}[]") for item in value)
    raise ValueError(f"{path} contains unsupported value type {type(value).__name__}")


def plain_json_value(value: object) -> object:
    """Convert validated immutable JSON values into serializable containers."""

    if isinstance(value, Mapping):
        return {key: plain_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain_json_value(item) for item in value]
    return value


def _required_text(name: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} MUST be non-empty")
    return normalized


@dataclass(frozen=True, slots=True)
class ConfigurationResource:
    """One expected or observed resource with normalized comparable attributes."""

    local_name: str
    resource_type: str
    region: str
    attributes: Mapping[str, object] = field(default_factory=dict)
    unknown_attributes: frozenset[str] = field(default_factory=frozenset)
    unauthorized_attributes: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        object.__setattr__(self, "local_name", _required_text("local_name", self.local_name))
        object.__setattr__(
            self,
            "resource_type",
            _required_text("resource_type", self.resource_type).lower(),
        )
        object.__setattr__(self, "region", _required_text("region", self.region).lower())
        frozen = _freeze(self.attributes, path=f"resource[{self.local_name}].attributes")
        if not isinstance(frozen, Mapping):
            raise ValueError("attributes MUST be a mapping")
        object.__setattr__(self, "attributes", frozen)
        unknown = frozenset(
            _required_text("unknown attribute", item) for item in self.unknown_attributes
        )
        unauthorized = frozenset(
            _required_text("unauthorized attribute", item) for item in self.unauthorized_attributes
        )
        overlap = unknown & unauthorized
        if overlap:
            raise ValueError(
                f"attributes cannot be both unknown and unauthorized: {sorted(overlap)}"
            )
        supplied = set(frozen)
        if supplied & (unknown | unauthorized):
            raise ValueError("observed attributes cannot also be unknown or unauthorized")
        object.__setattr__(self, "unknown_attributes", unknown)
        object.__setattr__(self, "unauthorized_attributes", unauthorized)

    @property
    def key(self) -> tuple[str, str]:
        return (self.resource_type, self.local_name)

    def to_dict(self) -> dict[str, object]:
        return {
            "local_name": self.local_name,
            "resource_type": self.resource_type,
            "region": self.region,
            "attributes": plain_json_value(self.attributes),
            "unknown_attributes": sorted(self.unknown_attributes),
            "unauthorized_attributes": sorted(self.unauthorized_attributes),
        }


@dataclass(frozen=True, slots=True)
class ConfigurationLink:
    """One expected or observed topology relationship."""

    source: str
    relation: str
    target: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _required_text("link source", self.source))
        object.__setattr__(self, "relation", _required_text("link relation", self.relation))
        object.__setattr__(self, "target", _required_text("link target", self.target))

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.relation, self.target)

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "relation": self.relation, "target": self.target}


@dataclass(frozen=True, slots=True)
class FrozenConfigurationBaseline:
    """Reviewed intended state pinned to one version and document digest."""

    version: str
    created_at: datetime
    scope: str
    source: str
    document_sha256: str
    resources: tuple[ConfigurationResource, ...]
    links: tuple[ConfigurationLink, ...] = ()
    allowed_exceptions: tuple[str, ...] = ()
    unknown_items: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _aware("created_at", self.created_at)
        object.__setattr__(self, "version", _required_text("version", self.version))
        object.__setattr__(self, "scope", _required_text("scope", self.scope))
        object.__setattr__(self, "source", _required_text("source", self.source))
        digest = self.document_sha256.strip().lower()
        if not _SHA256.fullmatch(digest):
            raise ValueError("document_sha256 MUST be a lowercase SHA-256 digest")
        object.__setattr__(self, "document_sha256", digest)
        _reject_duplicate_resources(self.resources)
        _reject_duplicate_links(self.links)
        object.__setattr__(
            self, "resources", tuple(sorted(self.resources, key=lambda item: item.key))
        )
        object.__setattr__(self, "links", tuple(sorted(self.links, key=lambda item: item.key)))
        object.__setattr__(
            self,
            "allowed_exceptions",
            tuple(
                sorted(
                    _required_text("allowed exception", item) for item in self.allowed_exceptions
                )
            ),
        )
        object.__setattr__(
            self,
            "unknown_items",
            tuple(sorted(_required_text("unknown item", item) for item in self.unknown_items)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "scope": self.scope,
            "source": self.source,
            "document_sha256": self.document_sha256,
            "resources": [resource.to_dict() for resource in self.resources],
            "links": [link.to_dict() for link in self.links],
            "allowed_exceptions": list(self.allowed_exceptions),
            "unknown_items": list(self.unknown_items),
        }

    @property
    def sha256(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfigurationObservation:
    """One bounded current-state observation from authoritative read sources."""

    scope: str
    observed_at: datetime
    source: str
    completeness: EvidenceCompleteness
    resources: tuple[ConfigurationResource, ...]
    links: tuple[ConfigurationLink, ...] = ()

    def __post_init__(self) -> None:
        _aware("observed_at", self.observed_at)
        object.__setattr__(self, "scope", _required_text("scope", self.scope))
        object.__setattr__(self, "source", _required_text("source", self.source))
        _reject_duplicate_resources(self.resources)
        _reject_duplicate_links(self.links)
        object.__setattr__(
            self, "resources", tuple(sorted(self.resources, key=lambda item: item.key))
        )
        object.__setattr__(self, "links", tuple(sorted(self.links, key=lambda item: item.key)))


def _reject_duplicate_resources(resources: Sequence[ConfigurationResource]) -> None:
    keys = [resource.key for resource in resources]
    if len(keys) != len(set(keys)):
        raise ValueError("resource keys MUST be unique")


def _reject_duplicate_links(links: Sequence[ConfigurationLink]) -> None:
    keys = [link.key for link in links]
    if len(keys) != len(set(keys)):
        raise ValueError("topology links MUST be unique")


@dataclass(frozen=True, slots=True)
class DriftFinding:
    """One evidence-backed difference between intent and observation."""

    target: str
    field: str
    baseline_value: object
    actual_value: object
    verdict: DriftVerdict
    drift_type: DriftType
    source: str


@dataclass(frozen=True, slots=True)
class ConfigurationDriftReport:
    """Deterministic comparison result with safety counters."""

    baseline_version: str
    baseline_sha256: str
    scope: str
    observed_at: datetime
    verdict: DriftVerdict
    findings: tuple[DriftFinding, ...]
    knowledge_status: KnowledgeGroundingStatus = KnowledgeGroundingStatus.NOT_CONFIGURED
    knowledge_citations: tuple[str, ...] = ()
    mutation_count: int = 0
    approval_request_count: int = 0
    mitigation_execution_count: int = 0
    unsupported_claim_count: int = 0
    performance: ConfigurationDriftPerformance | None = None


@dataclass(frozen=True, slots=True)
class ConfigurationDriftPerformance:
    """Measured stage latency and cardinality for one fresh drift run."""

    baseline_load_ms: float
    observation_ms: float
    comparison_ms: float
    knowledge_ms: float
    total_ms: float
    resource_count: int
    finding_count: int

    def __post_init__(self) -> None:
        latencies = (
            self.baseline_load_ms,
            self.observation_ms,
            self.comparison_ms,
            self.knowledge_ms,
            self.total_ms,
        )
        if any(not math.isfinite(value) or value < 0 for value in latencies):
            raise ValueError("configuration drift latencies MUST be finite and non-negative")
        stage_total = sum(latencies[:4])
        tolerance = max(1e-6, self.total_ms * 1e-9)
        if stage_total > self.total_ms + tolerance:
            raise ValueError("configuration drift stage latencies MUST NOT exceed total latency")
        if self.resource_count < 0 or self.finding_count < 0:
            raise ValueError("configuration drift counts MUST be non-negative")

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_load_ms": self.baseline_load_ms,
            "observation_ms": self.observation_ms,
            "comparison_ms": self.comparison_ms,
            "knowledge_ms": self.knowledge_ms,
            "total_ms": self.total_ms,
            "resource_count": self.resource_count,
            "finding_count": self.finding_count,
        }


__all__ = [
    "ConfigurationDriftPerformance",
    "ConfigurationDriftReport",
    "ConfigurationLink",
    "ConfigurationObservation",
    "ConfigurationResource",
    "DriftFinding",
    "DriftType",
    "DriftVerdict",
    "EvidenceCompleteness",
    "FrozenConfigurationBaseline",
    "KnowledgeGroundingStatus",
    "plain_json_value",
]
