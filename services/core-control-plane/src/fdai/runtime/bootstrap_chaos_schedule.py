"""Bind an explicit bounded Loki schedule without granting Chaos execution authority."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

from fdai.agents import ChaosScheduleConfig, validate_chaos_schedule
from fdai.core.operational_evidence.registry_json import load_strict_json_text

_REQUIRED_FIELDS = frozenset(
    {
        "schedule_id",
        "cadence_seconds",
        "targets",
        "action_type",
        "start_at",
        "causal_hypothesis_ref",
        "refutation_query_ref",
        "impact_envelope_id",
        "recovery_plan_id",
        "dry_run_receipt",
    }
)


def build_chaos_schedule(
    *,
    environment: Mapping[str, str],
    action_type_names: frozenset[str],
) -> ChaosScheduleConfig | None:
    """An absent declaration stays unbound; malformed or incomplete schedules fail startup."""
    raw = environment.get("FDAI_LOKI_SCHEDULE_JSON", "").strip()
    if not raw:
        return None
    if len(raw.encode()) > 16_384:
        raise ValueError("Loki schedule declaration MUST be at most 16 KiB")
    parsed = load_strict_json_text(raw, label="Loki recurring schedule")
    if (
        not isinstance(parsed, Mapping)
        or not _REQUIRED_FIELDS <= parsed.keys()
        or parsed.keys() - _REQUIRED_FIELDS - {"correlation_id"}
    ):
        raise ValueError("Loki schedule declaration fields are incomplete or unknown")
    cadence = parsed["cadence_seconds"]
    if type(cadence) is not int or not 1 <= cadence <= 31_536_000:
        raise ValueError("Loki schedule cadence MUST be an integer from 1 through 31536000 seconds")
    targets = parsed["targets"]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 32:
        raise ValueError("Loki schedule targets MUST contain between 1 and 32 identities")
    values: dict[str, str] = {}
    for name in _REQUIRED_FIELDS - {"cadence_seconds", "targets"}:
        value = parsed[name]
        if not _canonical_string(value):
            raise ValueError("Loki schedule identities and evidence references MUST be canonical")
        values[name] = value
    if any(not _canonical_string(target) for target in targets) or len(set(targets)) != len(
        targets
    ):
        raise ValueError("Loki schedule target identities MUST be canonical and unique")
    if values["action_type"] not in action_type_names:
        raise ValueError("Loki schedule ActionType MUST be present in the active catalog")
    correlation = parsed.get("correlation_id", "")
    if "correlation_id" in parsed and (
        not _canonical_string(correlation) or len(correlation) > 256
    ):
        raise ValueError("Loki schedule correlation MUST be a canonical identifier")
    try:
        start_at = datetime.fromisoformat(values["start_at"])
    except ValueError:
        raise ValueError("Loki schedule start_at MUST be an ISO 8601 timestamp") from None
    schedule = ChaosScheduleConfig(
        schedule_id=values["schedule_id"],
        cadence=timedelta(seconds=cadence),
        targets=tuple(targets),
        action_type=values["action_type"],
        start_at=start_at,
        causal_hypothesis_ref=values["causal_hypothesis_ref"],
        refutation_query_ref=values["refutation_query_ref"],
        impact_envelope_id=values["impact_envelope_id"],
        recovery_plan_id=values["recovery_plan_id"],
        dry_run_receipt=values["dry_run_receipt"],
        correlation_id=correlation,
    )
    reason = validate_chaos_schedule(schedule)
    if reason:
        raise ValueError(f"Loki schedule declaration is invalid: {reason}")
    return schedule


def _canonical_string(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 512
        and value == value.strip()
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


__all__ = ["build_chaos_schedule"]
