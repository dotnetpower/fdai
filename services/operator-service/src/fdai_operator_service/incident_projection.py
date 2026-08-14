"""Audit-backed Incident summary and outcome projections for Operator reads."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Final, cast

from fdai_service_contracts import JsonObject, JsonValue

from fdai_operator_service.projection_logic import audit_item

INCIDENT_TITLE_LIMIT: Final = 160
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
    incident_id = _first_entry_string(newest, "incident_id")
    ticket_id = _first_entry_string(newest, "ticket_id")
    lifecycle = _incident_status(newest)
    vertical = _vertical(_first_entry_string(newest, "vertical", "category"))
    title, title_source = _incident_title(newest, items, incident_id or correlation_id)
    return cast(
        JsonObject,
        {
            "correlation_id": correlation_id,
            "incident_id": incident_id,
            "ticket_id": ticket_id,
            "title": title,
            "title_source": title_source,
            "source": _incident_source_context(newest),
            "response_plan": _incident_response_plan(newest),
            "independent_outcome_verified": bool(
                _first_entry_typed_value(newest, "independent_outcome_verified", bool)
            ),
            "mitigated_by": _mitigated_by(newest),
            "agent_assisted": bool(_first_entry_typed_value(newest, "agent_assisted", bool)),
            "severity": _first_entry_string(newest, "severity") or "unknown",
            "status": lifecycle[0],
            "status_source": lifecycle[1],
            "disposition": _first_entry_string(newest, "outcome") or "unknown",
            "verdict": _verdict(newest),
            "vertical": vertical,
            "opened_at": _first_entry_string(items, "opened_at") or str(items[0]["recorded_at"]),
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
) -> JsonObject:
    """Aggregate bounded incident outcomes without inferring success from lifecycle state."""
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


def _incident_status(items: Sequence[JsonObject]) -> tuple[str, str]:
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
            return ("resolved" if state in {"resolved", "closed"} else state, kind or "audit")
    if _first_entry_string(items, "outcome") in {
        "resolved",
        "remediated",
        "mitigated",
        "rollback_succeeded",
        "rollback_completed",
    }:
        return ("resolved", "audit_projection")
    if len(items) > 1 or _verdict(items) == "hil":
        return ("in_progress", "audit_projection")
    return ("open", "audit_projection")


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
) -> tuple[str, str]:
    for key, source in (("title", "recorded_title"), ("summary", "recorded_summary")):
        if value := _first_entry_string(newest, key):
            return (_bounded_title(value), source)
    if rule_id := _first_entry_string(newest, "rule_id") or _first_entry_list_value(
        newest, "citing_rules"
    ):
        return (_bounded_title(f"Rule {_humanize_subject(rule_id)}"), "rule_id")

    signal, resource = _correlation_subjects(oldest)
    if signal and resource:
        return (
            _bounded_title(f"{_humanize_subject(signal)} - {_resource_subject(resource)}"),
            "correlation_subject",
        )
    if signal:
        return (_bounded_title(_humanize_subject(signal)), "correlation_subject")
    if resource:
        return (_bounded_title(f"Resource {_resource_subject(resource)}"), "correlation_subject")
    return (_bounded_title(f"Incident {fallback_id}"), "identifier_fallback")


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


def _resource_subject(value: str) -> str:
    parts = [part for part in value.strip().split("/") if part]
    if "providers" in parts:
        provider_index = parts.index("providers")
        provider_parts = parts[provider_index + 1 :]
        if len(provider_parts) >= 3:
            return f"{_humanize_subject(provider_parts[-2])} {provider_parts[-1]}"
    return value


def _humanize_subject(value: str) -> str:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    words = separated.replace("_", " ").replace("-", " ").replace(".", " ").split()
    return " ".join(words).capitalize() or value


def _bounded_title(value: str) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= INCIDENT_TITLE_LIMIT:
        return normalized
    return normalized[: INCIDENT_TITLE_LIMIT - 3].rstrip() + "..."


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
