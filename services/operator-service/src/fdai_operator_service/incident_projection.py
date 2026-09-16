"""Audit-backed Incident summary and outcome projections for Operator reads."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final, cast

from fdai_service_contracts import JsonObject, JsonValue
from fdai_service_contracts.incident_intervention import incident_target_ref

from fdai_operator_service.projection_logic import audit_item

INCIDENT_TITLE_LIMIT: Final = 160
_INCIDENT_TITLE_COMPONENT_LIMIT: Final = 72
_MAX_INCIDENT_RESOURCE_ID_CHARS: Final = 2_048
_OPAQUE_INTEGRATION_RESOURCE = re.compile(
    r"^integration-[0-9a-f]{32}(?:-second)?$",
    re.IGNORECASE,
)
_TITLE_ACRONYMS: Final = {
    "api": "API",
    "cpu": "CPU",
    "gpu": "GPU",
    "http": "HTTP",
    "id": "ID",
    "rca": "RCA",
    "slo": "SLO",
    "tls": "TLS",
    "vm": "VM",
}
_SIGNAL_LABELS: Final = {
    "kubernetes_pod_restart_detected": "Kubernetes pod restart detected",
    "resource_inventory_change": "Resource inventory changed",
    "trace_continuity_discontinuity": "Trace continuity interrupted",
    "trace_propagation_gap": "Trace propagation gap",
}
_REASON_LABELS: Final = {
    "control_loop_unhandled_error": "Control loop error",
    "no_rule_match": "No response rule matches",
    "no_rule_matches_resource_and_signal_type": (
        "No response rule matches this resource and signal"
    ),
}
_CANONICAL_INCIDENT_STATES: Final = frozenset(
    {"open", "triaging", "mitigated", "resolved", "closed"}
)
_TERMINAL_INCIDENT_STATES: Final = frozenset({"resolved", "closed"})
PANTHEON_AGENTS: Final = frozenset(
    {
        "Odin",
        "Thor",
        "Forseti",
        "Huginn",
        "Heimdall",
        "Var",
        "Vidar",
        "Bragi",
        "Saga",
        "Mimir",
        "Norns",
        "Muninn",
        "Njord",
        "Freyr",
        "Loki",
    }
)


def incident_summary(rows: Sequence[Mapping[str, Any]]) -> JsonObject:
    """Project one oldest-first correlated audit history into an incident summary."""
    items = [audit_item(row) for row in rows]
    newest = list(reversed(items))
    correlation_id = str(rows[-1]["normalized_correlation_id"])
    incident_id = _first_row_string(rows, "canonical_incident_id") or _first_entry_string(
        newest, "incident_id"
    )
    incident_number = _first_row_string(rows, "canonical_incident_number") or _first_entry_string(
        newest, "incident_number"
    )
    ticket_id = _first_row_string(rows, "canonical_ticket_id") or _first_entry_string(
        newest, "ticket_id"
    )
    lifecycle = _incident_status(newest, _first_row_string(rows, "canonical_lifecycle_state"))
    vertical = _vertical(_first_entry_string(newest, "vertical", "category"))
    title, title_source, title_presentation = _incident_title(
        newest,
        items,
        incident_id or correlation_id,
    )
    return cast(
        JsonObject,
        {
            "correlation_id": correlation_id,
            "incident_id": incident_id,
            "incident_number": incident_number,
            "ticket_id": ticket_id,
            "title": title,
            "title_source": title_source,
            "title_presentation": title_presentation,
            "source": _incident_source_context(newest),
            "response_plan": _incident_response_plan(newest),
            "target_ref": _incident_target_ref(rows, items),
            "independent_outcome_verified": bool(
                _first_entry_typed_value(newest, "independent_outcome_verified", bool)
            ),
            "mitigated_by": _mitigated_by(newest),
            "agent_assisted": bool(_first_entry_typed_value(newest, "agent_assisted", bool)),
            "severity": _first_entry_string(newest, "severity") or "unknown",
            "status": lifecycle[0],
            "status_source": lifecycle[1],
            "lifecycle_state": lifecycle[2],
            "disposition": _first_entry_string(newest, "outcome") or "unknown",
            "verdict": _verdict(newest),
            "vertical": vertical,
            "opened_at": _first_row_string(rows, "canonical_opened_at")
            or _first_entry_string(items, "opened_at")
            or str(items[0]["recorded_at"]),
            "last_updated_at": str(newest[0]["recorded_at"]),
            "latest_mode": str(newest[0]["mode"]),
            "history_count": int(rows[-1].get("group_history_count", len(rows))),
            "involved_agents": sorted(
                {str(item["actor"]) for item in items if str(item["actor"]) in PANTHEON_AGENTS}
            ),
            "last_seq": int(rows[-1]["group_last_seq"]),
        },
    )


def incident_outcome_metrics(
    incidents: Sequence[Mapping[str, Any]],
    *,
    snapshot_seq: int,
    truncated: bool,
    matched_total: int | None = None,
) -> JsonObject:
    """Aggregate bounded incident outcomes without inferring success from lifecycle state.

    `matched_total` is the number of incidents the snapshot matched before the measurement
    bound. It is `None` when the caller could not observe it, and it is never inferred from
    the measured sample size.
    """
    cohort_names = (
        "agent_mitigated",
        "agent_assisted",
        "human_mitigated",
        "pending",
        "integrity_excluded",
    )
    counts = {name: 0 for name in cohort_names}
    drilldown: dict[str, list[JsonValue]] = {name: [] for name in cohort_names}
    drilldown_truncated = {name: False for name in cohort_names}
    observed_times: list[datetime] = []
    verified_durations: list[int] = []
    for incident in incidents:
        status = str(incident.get("status") or "")
        verified = incident.get("independent_outcome_verified") is True
        mitigated_by = incident.get("mitigated_by")
        assisted = incident.get("agent_assisted") is True
        if status != "resolved":
            cohort = "pending"
        elif not verified:
            cohort = "integrity_excluded"
        elif mitigated_by == "agent":
            cohort = "agent_mitigated"
        elif mitigated_by == "human" and assisted:
            cohort = "agent_assisted"
        elif mitigated_by == "human":
            cohort = "human_mitigated"
        else:
            cohort = "integrity_excluded"
        counts[cohort] += 1
        correlation_id = incident.get("correlation_id")
        if isinstance(correlation_id, str) and len(drilldown[cohort]) < 200:
            drilldown[cohort].append(correlation_id)
        elif isinstance(correlation_id, str):
            drilldown_truncated[cohort] = True

        opened_at = _parse_projection_time(incident.get("opened_at"))
        updated_at = _parse_projection_time(incident.get("last_updated_at"))
        if opened_at is not None:
            observed_times.append(opened_at)
        if updated_at is not None:
            observed_times.append(updated_at)
        if status == "resolved" and verified and opened_at is not None and updated_at is not None:
            duration = int((updated_at - opened_at).total_seconds())
            if duration >= 0:
                verified_durations.append(duration)

    ordered_durations = sorted(verified_durations)
    median_ttm = None
    if ordered_durations:
        middle = len(ordered_durations) // 2
        median_ttm = (
            float(ordered_durations[middle])
            if len(ordered_durations) % 2 == 1
            else (ordered_durations[middle - 1] + ordered_durations[middle]) / 2
        )
    return cast(
        JsonObject,
        {
            "source": "operator-postgres-incident-projection",
            "snapshot_seq": snapshot_seq,
            "denominator": len(incidents),
            "matched_total": matched_total,
            "truncated": truncated,
            "window_from": min(observed_times).isoformat() if observed_times else None,
            "window_to": max(observed_times).isoformat() if observed_times else None,
            "cohorts": cast(JsonObject, counts),
            "drilldown": cast(JsonObject, drilldown),
            "drilldown_truncated": cast(JsonObject, drilldown_truncated),
            "median_time_to_mitigate_seconds": median_ttm,
            "time_to_mitigate_sample_size": len(verified_durations),
            "terminal_rule": "resolved_and_independently_verified",
        },
    )


def _roster_status(state: str) -> str:
    # The canonical machine is open -> triaging -> mitigated -> resolved -> closed,
    # but the roster reads only three states. Anything still in flight stays
    # in_progress so an unrecognized state never claims the incident is over.
    normalized = state.casefold()
    if normalized in _TERMINAL_INCIDENT_STATES:
        return "resolved"
    return "open" if normalized == "open" else "in_progress"


def _incident_status(
    items: Sequence[JsonObject], canonical_state: str | None = None
) -> tuple[str, str, str | None]:
    normalized_canonical = (canonical_state or "").casefold()
    if normalized_canonical in _CANONICAL_INCIDENT_STATES:
        return (
            _roster_status(normalized_canonical),
            "incident_lifecycle",
            normalized_canonical,
        )
    for item in items:
        entry = _mapping(item.get("entry"))
        kind = _nonempty(entry.get("kind"))
        state = (
            _nonempty(entry.get("to_state"))
            if kind == "incident.transition"
            else _nonempty(entry.get("state"))
            if kind == "incident.open"
            else None
        )
        if state:
            normalized = state.casefold()
            lifecycle_state = normalized if normalized in _CANONICAL_INCIDENT_STATES else None
            return (_roster_status(state), "incident_lifecycle", lifecycle_state)
    if _first_entry_string(items, "outcome") in {
        "resolved",
        "remediated",
        "mitigated",
        "rollback_succeeded",
        "rollback_completed",
    }:
        return ("resolved", "audit_projection", None)
    if len(items) > 1 or _verdict(items) == "hil":
        return ("in_progress", "audit_projection", None)
    return ("open", "audit_projection", None)


def _verdict(items: Sequence[JsonObject]) -> str:
    for item in items:
        entry = _mapping(item.get("entry"))
        tokens = {
            str(item.get("action_kind") or "").lower(),
            str(entry.get("decision") or "").lower(),
            str(entry.get("gate_decision") or "").lower(),
            str(entry.get("outcome") or "").lower(),
            str(entry.get("status") or "").lower(),
        }
        for verdict in ("auto", "hil", "deny", "abstain"):
            if verdict in tokens or (verdict == "abstain" and "abstained" in tokens):
                return verdict
    return "unknown"


def _incident_title(
    newest: Sequence[JsonObject],
    oldest: Sequence[JsonObject],
    fallback_id: str,
) -> tuple[str, str, JsonObject | None]:
    for key, source in (("title", "recorded_title"), ("summary", "recorded_summary")):
        if value := _first_entry_string(newest, key):
            return (_bounded_title(value), source, None)
    if rule_id := _first_entry_string(newest, "rule_id") or _first_entry_list_value(
        newest, "citing_rules"
    ):
        rule_label = _humanize_subject(rule_id)
        return (
            _bounded_title(f"Rule requires attention: {rule_label}"),
            "rule_id",
            _title_presentation(
                kind="rule_attention",
                subject=rule_label,
                technical_ref=rule_id,
            ),
        )

    signal, resource = _correlation_subjects(oldest)
    if signal and resource:
        subject, subject_kind, technical_ref = _resource_presentation(resource, signal=signal)
        signal_label = _signal_label(signal)
        resource_label = subject or _resource_kind_label(subject_kind)
        return (
            _bounded_title(f"{resource_label}: {signal_label}"),
            "correlation_subject",
            _title_presentation(
                kind="signal_on_subject",
                subject=subject,
                subject_kind=subject_kind,
                signal=signal,
                signal_label=signal_label,
                technical_ref=technical_ref,
            ),
        )
    if signal:
        signal_label = _signal_label(signal)
        return (
            _bounded_title(signal_label),
            "correlation_subject",
            _title_presentation(
                kind="signal",
                signal=signal,
                signal_label=signal_label,
            ),
        )
    if resource:
        subject, subject_kind, technical_ref = _resource_presentation(resource)
        resource_label = subject or _resource_kind_label(subject_kind)
        return (
            _bounded_title(f"{resource_label} requires attention"),
            "correlation_subject",
            _title_presentation(
                kind="resource_attention",
                subject=subject,
                subject_kind=subject_kind,
                technical_ref=technical_ref,
            ),
        )
    if subject_parts := _recorded_subject_parts(newest):
        (
            recorded_subject,
            recorded_subject_kind,
            recorded_technical_ref,
            recorded_reason,
            recorded_reason_label,
        ) = subject_parts
        if recorded_subject and recorded_reason_label:
            title = f"{recorded_subject}: {recorded_reason_label}"
            kind = "subject_reason"
        elif recorded_subject:
            title = f"{recorded_subject} requires attention"
            kind = "resource_attention"
        else:
            title = recorded_reason_label or ""
            kind = "reason"
        return (
            _bounded_title(title),
            "recorded_subject",
            _title_presentation(
                kind=kind,
                subject=recorded_subject,
                subject_kind=recorded_subject_kind,
                reason=recorded_reason,
                reason_label=recorded_reason_label,
                technical_ref=recorded_technical_ref,
            ),
        )
    return (_bounded_title(f"Incident {fallback_id}"), "identifier_fallback", None)


def _recorded_subject_parts(
    items: Sequence[JsonObject],
) -> tuple[str | None, str | None, str | None, str | None, str | None] | None:
    """Return recorded subject parts without inventing an unrecorded incident cause.

    Used only after an explicit title, summary, rule, and correlation key are all absent. It
    reports what the control loop recorded about the incident rather than presenting an
    identifier as the subject; it never infers a target that no entry recorded.
    """
    target = _first_recorded_string(items, "resource_id")
    subject: str | None
    subject_kind: str | None
    technical_ref: str | None
    if target:
        subject, subject_kind, technical_ref = _resource_presentation(target)
    else:
        subject = subject_kind = technical_ref = None
    if subject is None and (resource_type := _first_recorded_string(items, "resource_type")):
        subject = _humanize_subject(resource_type)
        subject_kind = "resource"
    reason = _first_recorded_string(items, "reason")
    if subject is None and reason is None:
        return None
    return subject, subject_kind, technical_ref, reason, _reason_label(reason) if reason else None


def _first_recorded_string(items: Sequence[JsonObject], key: str) -> str | None:
    """Read `key` from an entry, then from its audit-envelope `payload` before the next entry."""
    for item in items:
        entry = _mapping(item.get("entry"))
        if value := _nonempty(entry.get(key)):
            return value
        if value := _nonempty(_mapping(entry.get("payload")).get(key)):
            return value
    return None


def _incident_source_context(items: Sequence[JsonObject]) -> JsonObject | None:
    source_url = _first_entry_string(items, "source_url")
    source_url_trusted = _first_entry_typed_value(items, "source_url_trusted", bool) is True
    if source_url is not None and (
        not source_url_trusted or not source_url.startswith("https://") or len(source_url) > 1024
    ):
        source_url = None
    context = cast(
        JsonObject,
        {
            "platform": _first_entry_string(items, "source_platform", "incident_platform"),
            "incident_id": _first_entry_string(items, "source_incident_id", "external_incident_id"),
            "status": _first_entry_string(items, "source_status", "external_status"),
            "fired_at": _first_entry_string(items, "source_fired_at", "fired_at"),
            "description": _first_entry_string(items, "description"),
            "url": source_url,
        },
    )
    return context if any(value is not None for value in context.values()) else None


def _incident_response_plan(items: Sequence[JsonObject]) -> JsonObject | None:
    plan = cast(
        JsonObject,
        {
            "id": _first_entry_string(items, "response_plan_id"),
            "revision": _first_entry_string(items, "response_plan_revision"),
            "enabled": _first_entry_typed_value(items, "response_plan_enabled", bool),
            "historical_match_count": _first_entry_nonnegative_int(
                items, "response_plan_match_count"
            ),
            "reinvestigation_cooldown_seconds": _first_entry_nonnegative_int(
                items, "reinvestigation_cooldown_seconds"
            ),
            "deduplication_key": _first_entry_string(items, "deduplication_key"),
        },
    )
    return plan if any(value is not None for value in plan.values()) else None


def _correlation_subjects(items: Sequence[JsonObject]) -> tuple[str | None, str | None]:
    signal: str | None = None
    resource: str | None = None
    for item in items:
        keys = _mapping(item.get("entry")).get("correlation_keys")
        for value in _strings(keys):
            if signal is None and value.startswith("signal:") and value[7:]:
                signal = value[7:]
            elif resource is None and value.startswith("resource:") and value[9:]:
                resource = value[9:]
    return signal, resource


def _incident_target_ref(
    rows: Sequence[Mapping[str, Any]],
    items: Sequence[JsonObject],
) -> str | None:
    """Digest one exact recorded resource target without exposing its identifier."""
    if "canonical_correlation_keys" in rows[-1]:
        return _target_ref_from_correlation_keys(rows[-1].get("canonical_correlation_keys"))
    resources: set[str] = set()
    for item in items:
        keys = _mapping(item.get("entry")).get("correlation_keys")
        resource = _resource_from_correlation_keys(keys)
        if resource is None and any(value.startswith("resource:") for value in _strings(keys)):
            return None
        if resource is not None:
            resources.add(resource)
    if len(resources) != 1:
        return None
    return incident_target_ref(resources.pop())


def _target_ref_from_correlation_keys(keys: object) -> str | None:
    resource = _resource_from_correlation_keys(keys)
    if resource is None:
        return None
    return incident_target_ref(resource)


def _resource_from_correlation_keys(keys: object) -> str | None:
    resources = tuple(
        value[9:].strip()
        for value in _strings(keys)
        if value.startswith("resource:") and value[9:].strip()
    )
    if len(resources) != 1 or len(resources[0]) > _MAX_INCIDENT_RESOURCE_ID_CHARS:
        return None
    return resources[0]


def _resource_subject(value: str) -> str:
    parts = [part for part in value.strip().split("/") if part]
    if "providers" in parts:
        provider_index = parts.index("providers")
        provider_parts = parts[provider_index + 1 :]
        if len(provider_parts) >= 3:
            return f"{_humanize_subject(provider_parts[-2])} {provider_parts[-1]}"
    return value


def _resource_presentation(
    value: str,
    *,
    signal: str | None = None,
) -> tuple[str | None, str, str]:
    """Reduce one recorded resource reference to a safe operator-facing subject."""
    normalized = value.strip()
    if _OPAQUE_INTEGRATION_RESOURCE.fullmatch(normalized):
        return None, "integration_resource", normalized
    parts = [part for part in normalized.split("/") if part]
    if normalized.startswith("kubernetes://"):
        kind = (
            "kubernetes_workload"
            if "/workload/" in normalized
            else "kubernetes_pod"
            if signal == "kubernetes_pod_restart_detected"
            else "kubernetes_resource"
        )
        return (parts[-1] if parts else None), kind, normalized
    if normalized.startswith("trace-topology/"):
        return (parts[-1] if parts else None), "trace_target", normalized
    if "providers" in parts:
        provider_index = parts.index("providers")
        provider_parts = parts[provider_index + 1 :]
        if len(provider_parts) >= 3:
            return provider_parts[-1], "cloud_resource", _resource_subject(normalized)
    if len(parts) > 1:
        return parts[-1], "resource", normalized
    return normalized or None, "resource", normalized


def _title_presentation(
    *,
    kind: str,
    subject: str | None = None,
    subject_kind: str | None = None,
    signal: str | None = None,
    signal_label: str | None = None,
    reason: str | None = None,
    reason_label: str | None = None,
    technical_ref: str | None = None,
) -> JsonObject:
    """Build deterministic display metadata from the same recorded title evidence."""
    return cast(
        JsonObject,
        {
            "kind": kind,
            "subject": _bounded_title_component(subject),
            "subject_kind": subject_kind,
            "signal": _bounded_title_component(signal),
            "signal_label": _bounded_title_component(signal_label),
            "reason": _bounded_title_component(reason),
            "reason_label": _bounded_title_component(reason_label),
            "technical_ref": _bounded_title(technical_ref) if technical_ref else None,
        },
    )


def _resource_kind_label(kind: str) -> str:
    return {
        "cloud_resource": "Cloud resource",
        "integration_resource": "Integration resource",
        "kubernetes_pod": "Kubernetes pod",
        "kubernetes_resource": "Kubernetes resource",
        "kubernetes_workload": "Kubernetes workload",
        "trace_target": "Trace target",
    }.get(kind, "Resource")


def _signal_label(value: str) -> str:
    return _SIGNAL_LABELS.get(value.casefold(), _humanize_subject(value))


def _reason_label(value: str) -> str:
    return _REASON_LABELS.get(value.casefold(), _humanize_subject(value))


def _humanize_subject(value: str) -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    words = separated.replace("_", " ").replace("-", " ").replace(".", " ").split()
    if not words:
        return value
    humanized = [_TITLE_ACRONYMS.get(word.casefold(), word) for word in words]
    if humanized[0].casefold() not in _TITLE_ACRONYMS:
        humanized[0] = humanized[0][:1].upper() + humanized[0][1:]
    return " ".join(humanized)


def _bounded_title(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= INCIDENT_TITLE_LIMIT:
        return normalized
    return normalized[: INCIDENT_TITLE_LIMIT - 3].rstrip() + "..."


def _bounded_title_component(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if len(normalized) <= _INCIDENT_TITLE_COMPONENT_LIMIT:
        return normalized
    return normalized[: _INCIDENT_TITLE_COMPONENT_LIMIT - 3].rstrip() + "..."


def _vertical(value: str | None) -> str:
    normalized = (value or "").lower().replace("-", "_")
    if normalized in {"resilience", "dr", "reliability", "chaos"}:
        return "resilience"
    if normalized in {"change", "change_safety", "config_drift", "security"}:
        return "change_safety"
    if normalized in {"cost", "cost_governance", "finops"}:
        return "cost_governance"
    return "unknown"


def _first_entry_string(items: Sequence[JsonObject], *keys: str) -> str | None:
    for item in items:
        entry = _mapping(item.get("entry"))
        for key in keys:
            if value := _nonempty(entry.get(key)):
                return value
    return None


def _first_row_string(rows: Sequence[Mapping[str, Any]], key: str) -> str | None:
    for row in reversed(rows):
        if value := _nonempty(row.get(key)):
            return value
    return None


def _first_entry_list_value(items: Sequence[JsonObject], key: str) -> str | None:
    for item in items:
        values = _strings(_mapping(item.get("entry")).get(key))
        if values:
            return values[0]
    return None


def _first_entry_typed_value[T](
    items: Sequence[JsonObject], key: str, expected_type: type[T]
) -> T | None:
    for item in items:
        value = _mapping(item.get("entry")).get(key)
        if type(value) is expected_type:
            return value
    return None


def _first_entry_nonnegative_int(items: Sequence[JsonObject], key: str) -> int | None:
    value = _first_entry_typed_value(items, key, int)
    return value if value is not None and value >= 0 else None


def _mitigated_by(items: Sequence[JsonObject]) -> str | None:
    value = _first_entry_string(items, "mitigated_by")
    return value if value in {"agent", "human"} else None


def _parse_projection_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _nonempty(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


__all__ = ["incident_outcome_metrics", "incident_summary"]
