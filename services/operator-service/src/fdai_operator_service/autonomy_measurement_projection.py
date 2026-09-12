"""Validate the stored autonomy measurement projection at the Operator read boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from fdai_operator_service.families.operations import ProjectionUnavailableError

_ERROR = "authoritative autonomy measurement projection is malformed"
_SUCCESS_METRICS = frozenset(
    {
        "auto_resolution_rate",
        "human_touchpoints_per_100",
        "mttr_seconds",
        "change_lead_time_seconds",
        "cost_per_resolved_event_usd",
    }
)
_LEADING_METRICS = frozenset(
    {
        "mixed_model_disagreement_rate",
        "verifier_failure_rate",
        "shadow_divergence_rate",
    }
)
_VERTICALS = frozenset({"resilience", "change_safety", "cost", "unattributed"})


def validate_autonomy_measurement(value: object) -> dict[str, object]:
    """Return one complete non-synthetic measurement envelope or fail closed."""

    try:
        projection = _mapping(value)
        _validate_identity(projection)
        sample_size = _integer(projection.get("sample_size"), positive=False)
        _integer(projection.get("window_days"), positive=True)
        _optional_ratio(projection.get("confidence"))
        _validate_counts(
            _mapping(projection.get("rules")),
            ("active", "candidates_30d", "promoted_30d"),
        )
        _validate_metrics(_mapping(projection.get("success")), _SUCCESS_METRICS)
        _validate_metrics(_mapping(projection.get("leading")), _LEADING_METRICS)
        _validate_guards(projection.get("guards"))
        finalization = _mapping(projection.get("finalization"))
        _validate_counts(
            finalization,
            ("finalized_events", "pending_events", "adverse_events"),
        )
        attribution = _mapping(projection.get("attribution"))
        _validate_counts(attribution, ("attributed_events", "unattributed_events"))
        verticals = _validate_verticals(projection.get("verticals"))
        _validate_totals(
            sample_size=sample_size,
            attribution=attribution,
            finalization=finalization,
            verticals=verticals,
        )
        _validate_tier(_mapping(projection.get("tier")))
        _number_series(_mapping(projection.get("trend")))
    except (KeyError, TypeError, ValueError):
        raise ProjectionUnavailableError(_ERROR) from None
    return cast(dict[str, object], dict(projection))


def _validate_identity(projection: Mapping[str, object]) -> None:
    source = _mapping(projection.get("source"))
    if (
        projection.get("schema_version") != "1.0.0"
        or projection.get("synthetic") is not False
        or source.get("kind") != "measurement"
        or not _text(source.get("name"))
    ):
        raise ValueError
    as_of = _text(source.get("as_of"))
    parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError


def _validate_metrics(values: Mapping[str, object], required: frozenset[str]) -> None:
    if not required.issubset(values):
        raise ValueError
    for name in required:
        metric = _mapping(values[name])
        _optional_number(metric.get("value"))
        _optional_number(metric.get("baseline"))
        if metric.get("direction") not in {"higher", "lower"}:
            raise ValueError


def _validate_guards(value: object) -> None:
    rows = _sequence(value)
    keys: set[str] = set()
    for raw in rows:
        guard = _mapping(raw)
        key = _text(guard.get("key"))
        if key in keys or type(guard.get("ok")) is not bool:
            raise ValueError
        keys.add(key)
        for field in ("value", "baseline", "threshold"):
            _number(guard.get(field))


def _validate_verticals(value: object) -> tuple[Mapping[str, object], ...]:
    rows = tuple(_mapping(raw) for raw in _sequence(value))
    keys: set[str] = set()
    for row in rows:
        key = _text(row.get("key"))
        if key not in _VERTICALS or key in keys:
            raise ValueError
        keys.add(key)
        events = _integer(row.get("events"), positive=False)
        auto_resolved = _integer(row.get("auto_resolved"), positive=False)
        _integer(row.get("open_risks"), positive=False)
        _number(row.get("monthly_savings"))
        if auto_resolved > events:
            raise ValueError
    return rows


def _validate_totals(
    *,
    sample_size: int,
    attribution: Mapping[str, object],
    finalization: Mapping[str, object],
    verticals: tuple[Mapping[str, object], ...],
) -> None:
    attributed = cast(int, attribution["attributed_events"])
    unattributed = cast(int, attribution["unattributed_events"])
    total = attributed + unattributed
    coverage = _optional_ratio(attribution.get("coverage"))
    expected_coverage = None if total == 0 else attributed / total
    vertical_total = sum(cast(int, row["events"]) for row in verticals)
    unattributed_vertical = sum(
        cast(int, row["events"]) for row in verticals if row["key"] == "unattributed"
    )
    if (
        sample_size != total
        or vertical_total != total
        or vertical_total - unattributed_vertical != attributed
        or unattributed_vertical != unattributed
        or (coverage is None) != (expected_coverage is None)
        or (
            coverage is not None
            and expected_coverage is not None
            and not math.isclose(coverage, expected_coverage, abs_tol=1e-12)
        )
    ):
        raise ValueError
    finalized = cast(int, finalization["finalized_events"])
    pending = cast(int, finalization["pending_events"])
    adverse = cast(int, finalization["adverse_events"])
    auto_resolved = sum(cast(int, row["auto_resolved"]) for row in verticals)
    if adverse > finalized or finalized + pending > total or auto_resolved != finalized - adverse:
        raise ValueError


def _validate_tier(tier: Mapping[str, object]) -> None:
    _number_record(_mapping(tier.get("mix")))
    bands = _mapping(tier.get("bands"))
    for value in bands.values():
        bounds = _sequence(value)
        if len(bounds) != 2:
            raise ValueError
        _number(bounds[0])
        _number(bounds[1])


def _validate_counts(values: Mapping[str, object], fields: tuple[str, ...]) -> None:
    for field in fields:
        _integer(values.get(field), positive=False)


def _number_series(values: Mapping[str, object]) -> None:
    for value in values.values():
        for item in _sequence(value):
            _number(item)


def _number_record(values: Mapping[str, object]) -> None:
    for value in values.values():
        _number(value)


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError
    return cast(Mapping[str, object], value)


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError
    return cast(Sequence[object], value)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError
    return value


def _integer(value: object, *, positive: bool) -> int:
    if type(value) is not int or value < (1 if positive else 0):
        raise TypeError
    return value


def _number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise TypeError
    return float(value)


def _optional_number(value: object) -> float | None:
    return None if value is None else _number(value)


def _optional_ratio(value: object) -> float | None:
    number = _optional_number(value)
    if number is not None and not 0 <= number <= 1:
        raise ValueError
    return number
