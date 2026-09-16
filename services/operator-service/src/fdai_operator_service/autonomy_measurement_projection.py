"""Validate the autonomy measurement projection at the Operator read boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast

from fdai_operator_service.families.operations import ProjectionUnavailableError

_ERROR = "authoritative autonomy measurement projection is malformed"
_SUCCESS_METRICS = {
    "auto_resolution_rate": "higher",
    "human_touchpoints_per_100": "lower",
    "mttr_seconds": "lower",
    "change_lead_time_seconds": "lower",
    "cost_per_resolved_event_usd": "lower",
}
_LEADING_METRICS = {
    "mixed_model_disagreement_rate": "lower",
    "verifier_failure_rate": "lower",
    "shadow_divergence_rate": "lower",
}
_RATE_METRICS = frozenset({"auto_resolution_rate", *_LEADING_METRICS})
_SOURCE_METRICS = frozenset({"mttr_seconds", "change_lead_time_seconds", "attributed_cost_usd"})
_MEASUREMENT_GAP_PREFIXES = frozenset({"incomplete", "mixed_context", "missing_source"})
_TIER_KEYS = frozenset({"t0", "t1", "t2"})
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
        success = _mapping(projection.get("success"))
        _validate_metrics(success, _SUCCESS_METRICS)
        _validate_metric_evidence(projection, success)
        auto_resolution_rate = _mapping(success["auto_resolution_rate"])
        auto_resolution_value = _optional_ratio(auto_resolution_rate.get("value"))
        _optional_ratio(auto_resolution_rate.get("baseline"))
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
            auto_resolution_value=auto_resolution_value,
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


def _validate_metrics(
    values: Mapping[str, object],
    expected_directions: Mapping[str, str],
) -> None:
    if not expected_directions.keys() <= values.keys():
        raise ValueError
    for name, expected_direction in expected_directions.items():
        metric = _mapping(values[name])
        validator = _optional_ratio if name in _RATE_METRICS else _optional_nonnegative_number
        validator(metric.get("value"))
        validator(metric.get("baseline"))
        if metric.get("direction") != expected_direction:
            raise ValueError


def _validate_metric_evidence(
    projection: Mapping[str, object],
    success: Mapping[str, object],
) -> None:
    samples = _mapping(projection.get("metric_samples"))
    if samples.keys() != _SUCCESS_METRICS.keys():
        raise ValueError
    for metric_id in _SUCCESS_METRICS:
        sample_count = _integer(samples.get(metric_id), positive=False)
        metric = _mapping(success[metric_id])
        if metric.get("value") is not None and sample_count == 0:
            raise ValueError

    gaps = _sequence(projection.get("measurement_gaps"))
    seen: set[str] = set()
    for value in gaps:
        if not isinstance(value, str) or not value or value in seen:
            raise ValueError
        seen.add(value)
        if value == "unattributed_human_input":
            continue
        prefix, separator, metric_id = value.partition(":")
        if (
            separator != ":"
            or prefix not in _MEASUREMENT_GAP_PREFIXES
            or metric_id not in _SOURCE_METRICS
        ):
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
    auto_resolution_value: float | None,
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
    expected_auto_resolution = None if total == 0 else auto_resolved / total
    if (
        adverse > finalized
        or finalized + pending > total
        or auto_resolved != finalized - adverse
        or (
            auto_resolution_value is not None
            and (
                expected_auto_resolution is None
                or not math.isclose(
                    auto_resolution_value,
                    expected_auto_resolution,
                    abs_tol=1e-12,
                )
            )
        )
    ):
        raise ValueError


def _validate_tier(tier: Mapping[str, object]) -> None:
    mix = _mapping(tier.get("mix"))
    if not mix.keys() <= _TIER_KEYS:
        raise ValueError
    shares = tuple(_ratio(value) for value in mix.values())
    if sum(shares) > 1 + 1e-12:
        raise ValueError
    bands = _mapping(tier.get("bands"))
    if not bands.keys() <= _TIER_KEYS:
        raise ValueError
    for value in bands.values():
        bounds = _sequence(value)
        if len(bounds) != 2:
            raise ValueError
        lower = _ratio(bounds[0])
        upper = _ratio(bounds[1])
        if lower > upper:
            raise ValueError


def _validate_counts(values: Mapping[str, object], fields: tuple[str, ...]) -> None:
    for field in fields:
        _integer(values.get(field), positive=False)


def _number_series(values: Mapping[str, object]) -> None:
    for value in values.values():
        for item in _sequence(value):
            _number(item)


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
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError from exc
    if not math.isfinite(number):
        raise ValueError
    return number


def _optional_number(value: object) -> float | None:
    return None if value is None else _number(value)


def _optional_nonnegative_number(value: object) -> float | None:
    number = _optional_number(value)
    if number is not None and number < 0:
        raise ValueError
    return number


def _ratio(value: object) -> float:
    number = _number(value)
    if not 0 <= number <= 1:
        raise ValueError
    return number


def _optional_ratio(value: object) -> float | None:
    return None if value is None else _ratio(value)
