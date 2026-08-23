"""Validate provider-neutral collection policy declarations."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import Any

_SOURCE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_MAX_POLICY_BYTES = 1_048_576


class CollectionSourceKind(StrEnum):
    """Identify how one authenticated provider source supplies observations."""

    EVENT = "event"
    DELTA = "delta"
    SNAPSHOT = "snapshot"
    LIVE_READ = "live_read"


@dataclass(frozen=True, slots=True)
class CollectionPriorityPolicy:
    """Rank due work without granting observation or execution authority."""

    base: int
    changed_boost: int
    stale_boost: int
    critical_boost: int
    operator_requested_boost: int

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"collection priority {field.name} MUST be a non-negative integer")
        if self.base < 1:
            raise ValueError("collection priority base MUST be >= 1")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> CollectionPriorityPolicy:
        """Decode one strict priority declaration."""

        expected = {field.name for field in fields(cls)}
        _require_exact_keys(value, expected, "collection priority")
        return cls(**{key: value[key] for key in expected})  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class SourceCollectionPolicy:
    """Bound freshness, load, progress, and throttling for one source."""

    source_id: str
    source_kind: CollectionSourceKind
    target_freshness_seconds: int
    max_staleness_seconds: int
    min_poll_interval_seconds: int
    max_poll_interval_seconds: int
    budget_window_seconds: int
    max_requests_per_window: int
    max_bytes_per_window: int
    global_concurrency_limit: int
    scope_concurrency_limit: int
    resource_type_concurrency_limit: int
    endpoint_concurrency_limit: int
    max_cursor_pages: int
    max_objects: int
    max_relationships: int
    max_run_seconds: int
    no_progress_timeout_seconds: int
    jitter_ratio: float
    backoff_base_seconds: int
    backoff_max_seconds: int
    circuit_failure_threshold: int
    circuit_probe_interval_seconds: int
    priority: CollectionPriorityPolicy

    def __post_init__(self) -> None:
        if _SOURCE_ID_PATTERN.fullmatch(self.source_id) is None:
            raise ValueError("collection source_id MUST be a lowercase stable identifier")
        if not isinstance(self.source_kind, CollectionSourceKind):
            raise ValueError("collection source_kind MUST be a CollectionSourceKind")
        integer_fields = (
            "target_freshness_seconds",
            "max_staleness_seconds",
            "min_poll_interval_seconds",
            "max_poll_interval_seconds",
            "budget_window_seconds",
            "max_requests_per_window",
            "max_bytes_per_window",
            "global_concurrency_limit",
            "scope_concurrency_limit",
            "resource_type_concurrency_limit",
            "endpoint_concurrency_limit",
            "max_cursor_pages",
            "max_objects",
            "max_relationships",
            "max_run_seconds",
            "no_progress_timeout_seconds",
            "backoff_base_seconds",
            "backoff_max_seconds",
            "circuit_failure_threshold",
            "circuit_probe_interval_seconds",
        )
        for field_name in integer_fields:
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"collection policy {field_name} MUST be a positive integer")
        if self.target_freshness_seconds > self.max_staleness_seconds:
            raise ValueError("target freshness MUST NOT exceed maximum staleness")
        if self.min_poll_interval_seconds > self.max_poll_interval_seconds:
            raise ValueError("minimum poll interval MUST NOT exceed maximum poll interval")
        if self.max_poll_interval_seconds > self.max_staleness_seconds:
            raise ValueError("maximum poll interval MUST NOT exceed maximum staleness")
        concurrency_limits = (
            self.scope_concurrency_limit,
            self.resource_type_concurrency_limit,
            self.endpoint_concurrency_limit,
        )
        if any(limit > self.global_concurrency_limit for limit in concurrency_limits):
            raise ValueError("nested concurrency limits MUST NOT exceed the global limit")
        if self.no_progress_timeout_seconds > self.max_run_seconds:
            raise ValueError("no-progress timeout MUST NOT exceed maximum run time")
        if self.backoff_base_seconds > self.backoff_max_seconds:
            raise ValueError("backoff base MUST NOT exceed backoff maximum")
        if isinstance(self.jitter_ratio, bool) or not isinstance(self.jitter_ratio, (int, float)):
            raise ValueError("collection policy jitter_ratio MUST be numeric")
        if not 0.0 <= float(self.jitter_ratio) <= 0.5:
            raise ValueError("collection policy jitter_ratio MUST be in [0, 0.5]")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SourceCollectionPolicy:
        """Decode a strict machine declaration and reject unknown fields."""

        expected = {field.name for field in fields(cls)}
        _require_exact_keys(value, expected, "collection source policy")
        priority_value = value["priority"]
        if not isinstance(priority_value, Mapping):
            raise ValueError("collection source policy priority MUST be an object")
        source_kind_value = value["source_kind"]
        if not isinstance(source_kind_value, str):
            raise ValueError("collection source_kind MUST be a string")
        try:
            source_kind = CollectionSourceKind(source_kind_value)
        except ValueError as exc:
            raise ValueError("collection source_kind is unsupported") from exc
        kwargs: dict[str, Any] = {key: value[key] for key in expected}
        kwargs["source_kind"] = source_kind
        kwargs["priority"] = CollectionPriorityPolicy.from_mapping(priority_value)
        return cls(**kwargs)


@dataclass(frozen=True, slots=True)
class InventoryCollectionPolicy:
    """Hold uniquely identified source policies for one collection deployment."""

    sources: tuple[SourceCollectionPolicy, ...]

    def __post_init__(self) -> None:
        if not self.sources:
            raise ValueError("inventory collection policy MUST declare at least one source")
        source_ids = tuple(source.source_id for source in self.sources)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("inventory collection policy source ids MUST be unique")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> InventoryCollectionPolicy:
        """Decode a versioned collection policy document."""

        _require_exact_keys(value, {"schema_version", "sources"}, "inventory collection policy")
        if value["schema_version"] != "1.0.0":
            raise ValueError("inventory collection policy schema_version MUST be 1.0.0")
        source_values = value["sources"]
        if not isinstance(source_values, list):
            raise ValueError("inventory collection policy sources MUST be an array")
        policies: list[SourceCollectionPolicy] = []
        for source_value in source_values:
            if not isinstance(source_value, Mapping):
                raise ValueError("inventory collection policy source entries MUST be objects")
            policies.append(SourceCollectionPolicy.from_mapping(source_value))
        return cls(sources=tuple(policies))

    def source(self, source_id: str) -> SourceCollectionPolicy:
        """Return one declared source or fail closed for an unknown identifier."""

        for policy in self.sources:
            if policy.source_id == source_id:
                return policy
        raise KeyError(source_id)


def _require_exact_keys(
    value: Mapping[str, object],
    expected: set[str],
    subject: str,
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise ValueError(f"{subject} fields are invalid: missing={missing}, unknown={unknown}")


def load_inventory_collection_policy(path: Path) -> InventoryCollectionPolicy:
    """Load one bounded strict JSON policy document from deployment configuration."""

    payload = path.read_bytes()
    if len(payload) > _MAX_POLICY_BYTES:
        raise ValueError("inventory collection policy exceeds the 1 MiB limit")
    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("inventory collection policy MUST be valid UTF-8 JSON") from exc
    if not isinstance(decoded, Mapping):
        raise ValueError("inventory collection policy root MUST be an object")
    return InventoryCollectionPolicy.from_mapping(decoded)


__all__ = [
    "CollectionPriorityPolicy",
    "CollectionSourceKind",
    "InventoryCollectionPolicy",
    "SourceCollectionPolicy",
    "load_inventory_collection_policy",
]
