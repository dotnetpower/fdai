"""Parse bounded analyzer-job environment configuration."""

from __future__ import annotations

import json
from collections.abc import Mapping

from fdai.delivery.analyzer_targets import (
    DEFAULT_MAX_DISCOVERED,
    MAX_DISCOVERED_CEILING,
)
from fdai.delivery.analyzer_tick import DEFAULT_WINDOW_SECONDS, AnalyzerTarget
from fdai.delivery.azure.trace_continuity import TraceTopologyTarget
from fdai.delivery.pod_evidence_binding import POD_EVIDENCE_ENV

TARGETS_ENV = "FDAI_ANALYZER_TARGETS"
WINDOW_ENV = "FDAI_ANALYZER_WINDOW_SECONDS"
TRACE_WINDOW_ENV = "FDAI_TRACE_CONTINUITY_WINDOW_SECONDS"
TRACE_LOOKBACK_ENV = "FDAI_TRACE_CONTINUITY_LOOKBACK_SECONDS"
DEFAULT_TRACE_LOOKBACK_SECONDS = 900
TOPIC_ENV = "FDAI_ANALYZER_TOPIC"
INGRESS_TOPIC_ENV = "KAFKA_TOPIC_EVENTS"
MAX_DISCOVERED_ENV = "FDAI_ANALYZER_MAX_DISCOVERED_TARGETS"
INVENTORY_DSN_ENV = "FDAI_INVENTORY_DSN"
STATE_STORE_DSN_ENV = "FDAI_STATE_STORE_DSN"
TRACE_TOPOLOGIES_ENV = "FDAI_TRACE_TOPOLOGIES_JSON"
POD_EVIDENCE_JSON_ENV = POD_EVIDENCE_ENV
LOOP_INTERVAL_ENV = "FDAI_ANALYZER_INTERVAL_SECONDS"
BUDGET_ENV = "FDAI_ANALYZER_BUDGET_SECONDS"
DEFAULT_TICK_BUDGET_SECONDS = 300
SCHEDULING_MODES = frozenset({"one_shot", "local_loop", "container_apps_job"})

_TARGET_KEYS = frozenset({"resource_id", "kind", "provider_resource_id"})
_TRACE_TOPOLOGY_KEYS = frozenset({"topology_ref", "resource_ref", "expected_hops"})
_MAX_TRACE_TOPOLOGIES = 32
_DEFAULT_LOOP_INTERVAL_SECONDS = 60


def resolve_finding_topic(environ: Mapping[str, str]) -> str:
    """Resolve the topic that actually carries findings into the control loop."""

    topic = environ.get(TOPIC_ENV, "").strip() or environ.get(INGRESS_TOPIC_ENV, "").strip()
    if not topic:
        raise RuntimeError(f"{TOPIC_ENV} or {INGRESS_TOPIC_ENV} is required")
    return topic


def parse_targets(raw: str) -> tuple[AnalyzerTarget, ...]:
    """Parse the configured target list and reject malformed identities."""

    text = raw.strip()
    if not text:
        return ()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{TARGETS_ENV} MUST be a JSON array: {exc}") from exc
    if not isinstance(loaded, list):
        raise ValueError(f"{TARGETS_ENV} MUST be a JSON array")
    targets: list[AnalyzerTarget] = []
    targets_by_resource: dict[str, AnalyzerTarget] = {}
    for index, item in enumerate(loaded):
        if not isinstance(item, dict) or not {"resource_id", "kind"}.issubset(item):
            raise ValueError(f"{TARGETS_ENV}[{index}] MUST be an object")
        if not set(item).issubset(_TARGET_KEYS):
            raise ValueError(f"{TARGETS_ENV}[{index}] contains unknown fields")
        resource_ref = item.get("resource_id")
        resource_kind = item.get("kind")
        provider_ref = item.get("provider_resource_id")
        if not isinstance(resource_ref, str) or not isinstance(resource_kind, str):
            raise ValueError(f"{TARGETS_ENV}[{index}] MUST carry string resource_id and kind")
        if provider_ref is not None and not isinstance(provider_ref, str):
            raise ValueError(f"{TARGETS_ENV}[{index}] provider_resource_id MUST be a string")
        target = AnalyzerTarget(
            resource_ref=resource_ref.strip(),
            resource_kind=resource_kind.strip(),
            provider_query_ref=provider_ref.strip() if provider_ref is not None else None,
        )
        previous = targets_by_resource.get(target.resource_ref)
        if previous is not None:
            if (
                previous.resource_kind != target.resource_kind
                or previous.provider_query_ref != target.provider_query_ref
            ):
                raise ValueError(
                    f"{TARGETS_ENV}[{index}] conflicts with an earlier target identity"
                )
            continue
        targets_by_resource[target.resource_ref] = target
        targets.append(target)
    return tuple(targets)


def parse_trace_topologies(raw: str) -> tuple[TraceTopologyTarget, ...]:
    """Parse strict deployment-supplied trace topology declarations."""

    text = raw.strip()
    if not text:
        return ()
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{TRACE_TOPOLOGIES_ENV} MUST be a JSON array: {exc}") from exc
    if not isinstance(loaded, list) or len(loaded) > _MAX_TRACE_TOPOLOGIES:
        raise ValueError(
            f"{TRACE_TOPOLOGIES_ENV} MUST be an array with at most {_MAX_TRACE_TOPOLOGIES} items"
        )
    targets: list[TraceTopologyTarget] = []
    seen: set[str] = set()
    for index, item in enumerate(loaded):
        if not isinstance(item, dict) or set(item) != _TRACE_TOPOLOGY_KEYS:
            raise ValueError(
                f"{TRACE_TOPOLOGIES_ENV}[{index}] MUST contain exactly "
                "topology_ref, resource_ref, and expected_hops"
            )
        topology_ref = item["topology_ref"]
        resource_ref = item["resource_ref"]
        expected_hops = item["expected_hops"]
        if (
            not isinstance(topology_ref, str)
            or not isinstance(resource_ref, str)
            or not isinstance(expected_hops, list)
            or any(not isinstance(hop, str) for hop in expected_hops)
        ):
            raise ValueError(f"{TRACE_TOPOLOGIES_ENV}[{index}] has invalid field types")
        target = TraceTopologyTarget(
            topology_ref=topology_ref,
            resource_ref=resource_ref,
            expected_hops=tuple(expected_hops),
        )
        if target.topology_ref in seen:
            raise ValueError(f"{TRACE_TOPOLOGIES_ENV} topology_ref values MUST be unique")
        seen.add(target.topology_ref)
        targets.append(target)
    return tuple(targets)


def parse_window_seconds(raw: str) -> int:
    """Parse the optional analyzer window; a malformed value fails closed."""

    text = raw.strip()
    if not text:
        return DEFAULT_WINDOW_SECONDS
    try:
        window = int(text)
    except ValueError as exc:
        raise ValueError(f"{WINDOW_ENV} MUST be a positive integer") from exc
    if window <= 0:
        raise ValueError(f"{WINDOW_ENV} MUST be a positive integer")
    return window


def resolve_trace_window_seconds(environ: Mapping[str, str], analyzer_window: int) -> int:
    """Resolve the trace-continuity detection window."""

    text = environ.get(TRACE_WINDOW_ENV, "").strip()
    if not text:
        return analyzer_window
    try:
        window = int(text)
    except ValueError as exc:
        raise ValueError(f"{TRACE_WINDOW_ENV} MUST be a positive integer") from exc
    if window <= 0:
        raise ValueError(f"{TRACE_WINDOW_ENV} MUST be a positive integer")
    return window


def resolve_trace_lookback_seconds(
    environ: Mapping[str, str],
    detection_window: int,
) -> int:
    """Resolve evidence lookback independently from the idempotency bucket."""

    text = environ.get(TRACE_LOOKBACK_ENV, "").strip()
    if not text:
        return max(DEFAULT_TRACE_LOOKBACK_SECONDS, detection_window)
    try:
        lookback = int(text)
    except ValueError as exc:
        raise ValueError(f"{TRACE_LOOKBACK_ENV} MUST be a positive integer") from exc
    if lookback < detection_window:
        raise ValueError(f"{TRACE_LOOKBACK_ENV} MUST be at least {TRACE_WINDOW_ENV}")
    return lookback


def parse_max_discovered(raw: str) -> int:
    """Parse the optional inventory-backed target bound."""

    text = raw.strip()
    if not text:
        return DEFAULT_MAX_DISCOVERED
    try:
        bound = int(text)
    except ValueError as exc:
        raise ValueError(f"{MAX_DISCOVERED_ENV} MUST be a positive integer") from exc
    if not 1 <= bound <= MAX_DISCOVERED_CEILING:
        raise ValueError(
            f"{MAX_DISCOVERED_ENV} MUST be an integer in [1, {MAX_DISCOVERED_CEILING}]"
        )
    return bound


def parse_loop_interval(raw: str) -> int:
    """Parse the local/deployed schedule interval with one shared bound."""

    text = raw.strip()
    if not text:
        return _DEFAULT_LOOP_INTERVAL_SECONDS
    try:
        interval = int(text)
    except ValueError as exc:
        raise ValueError(f"{LOOP_INTERVAL_ENV} MUST be a positive integer") from exc
    if not 1 <= interval <= 86_400:
        raise ValueError(f"{LOOP_INTERVAL_ENV} MUST be in [1, 86400]")
    return interval


def parse_tick_budget(raw: str) -> int:
    """Parse the shared local and deployed wall-clock budget."""

    text = raw.strip()
    if not text:
        return DEFAULT_TICK_BUDGET_SECONDS
    try:
        budget = int(text)
    except ValueError as exc:
        raise ValueError(f"{BUDGET_ENV} MUST be a positive integer") from exc
    if not 1 <= budget <= DEFAULT_TICK_BUDGET_SECONDS:
        raise ValueError(f"{BUDGET_ENV} MUST be in [1, {DEFAULT_TICK_BUDGET_SECONDS}]")
    return budget


def metric_source_delays(environ: Mapping[str, str]) -> dict[str, str]:
    """Report configured source delay floors without claiming a live measurement."""

    return {
        "log_analytics": (
            "120-300_seconds" if environ.get("FDAI_MONITOR_WORKSPACE_ID", "").strip() else "unbound"
        ),
        "prometheus": (
            "unbound_exact_resource_identity"
            if environ.get("FDAI_PROMETHEUS_ENDPOINT", "").strip()
            else "unbound"
        ),
    }


def resolve_scheduling_mode(raw: str) -> str:
    """Resolve one allowlisted scheduling-mode receipt value."""

    mode = raw.strip() or "one_shot"
    if mode not in SCHEDULING_MODES:
        raise ValueError("FDAI_ANALYZER_SCHEDULING_MODE is invalid")
    return mode


__all__ = [
    "BUDGET_ENV",
    "DEFAULT_MAX_DISCOVERED",
    "DEFAULT_TICK_BUDGET_SECONDS",
    "DEFAULT_TRACE_LOOKBACK_SECONDS",
    "INGRESS_TOPIC_ENV",
    "INVENTORY_DSN_ENV",
    "LOOP_INTERVAL_ENV",
    "MAX_DISCOVERED_ENV",
    "POD_EVIDENCE_JSON_ENV",
    "SCHEDULING_MODES",
    "STATE_STORE_DSN_ENV",
    "TARGETS_ENV",
    "TOPIC_ENV",
    "TRACE_LOOKBACK_ENV",
    "TRACE_TOPOLOGIES_ENV",
    "TRACE_WINDOW_ENV",
    "WINDOW_ENV",
    "metric_source_delays",
    "parse_loop_interval",
    "parse_max_discovered",
    "parse_targets",
    "parse_tick_budget",
    "parse_trace_topologies",
    "parse_window_seconds",
    "resolve_finding_topic",
    "resolve_scheduling_mode",
    "resolve_trace_lookback_seconds",
    "resolve_trace_window_seconds",
]
