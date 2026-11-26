"""Opt-in temporal sufficient statistics; never infer unobserved continuity."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict, cast

if TYPE_CHECKING:
    from fdai.core.ontology_platform.semantic_rollup import (
        RollupObservation,
        SemanticRollup,
        SemanticRollupPolicy,
    )

TEMPORAL_STATISTICS = frozenset(
    {"counter_delta", "state_timeline", "change_timeline", "extrema_timestamps", "time_coverage"}
)


@dataclass(frozen=True)
class Sample:
    """Keep exact boundary identity and both source times, not delivery order."""

    observation_id: str
    value: str
    interval_start: str
    interval_end: str
    effective_at: str
    event_at: str | None
    generation_ref: str
    source_revision: str
    recorded_at: str
    complete: bool
    conflict_count: int


class SampleData(TypedDict):
    observation_id: str
    value: str
    interval_start: str
    interval_end: str
    effective_at: str
    event_at: str | None
    generation_ref: str
    source_revision: str
    recorded_at: str
    complete: bool
    conflict_count: int


class PolicyBinding(TypedDict):
    version: int
    statistics: list[str]
    expected_interval_seconds: int


class CounterEdge(TypedDict):
    before: SampleData
    after: SampleData
    reason: NotRequired[str]


class CounterSummary(TypedDict):
    known_delta: str
    resets: list[CounterEdge]
    unresolved: list[CounterEdge]
    reset_count: NotRequired[int]
    unresolved_step_count: NotRequired[int]
    delta_semantics: NotRequired[str]


class StateRun(TypedDict):
    value: str
    first: SampleData
    last: SampleData
    count: int
    observed_interval_seconds: str
    source_revision_order: list[str]


class Transition(TypedDict):
    """Observed bounds are not an exact provider transition timestamp."""

    from_state: str
    to_state: str
    after_observed_at: str
    by_observed_at: str
    exact_transition_time_available: bool
    evidence_status: str


class TemporalSummary(TypedDict):
    policy: PolicyBinding
    source: list[str] | None
    time_basis: str | None
    first: SampleData | None
    last: SampleData | None
    coverage: list[list[str]]
    gaps: NotRequired[list[list[str]]]
    observed_interval_seconds: NotRequired[str]
    counter_delta: NotRequired[CounterSummary]
    timeline: NotRequired[list[StateRun]]
    continuity: NotRequired[str]
    extrema: NotRequired[dict[str, SampleData]]
    transitions: NotRequired[list[Transition]]
    known_at_reconstruction: NotRequired[str]


def enabled(policy: SemanticRollupPolicy) -> bool:
    return bool(TEMPORAL_STATISTICS.intersection(policy.statistics))


def binding(policy: SemanticRollupPolicy) -> PolicyBinding:
    return {
        "version": 1,
        "statistics": sorted(policy.statistics),
        "expected_interval_seconds": policy.expected_interval_seconds,
    }


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _decimal(value: Decimal) -> str:
    if not value:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _add(*values: Decimal) -> Decimal:
    """Keep counter differences exact even beyond the ambient Decimal precision."""
    if not values:
        return Decimal(0)
    with localcontext() as context:
        context.prec = max(
            1,
            max(value.adjusted() for value in values)
            - min(int(value.as_tuple().exponent) for value in values)
            + len(str(len(values)))
            + 2,
        )
        return sum(values, Decimal(0))


def _seconds(start: str, end: str) -> Decimal:
    delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    return _add(Decimal(delta.days * 86400 + delta.seconds), Decimal(f"0.{delta.microseconds:06d}"))


def build_temporal(
    policy: SemanticRollupPolicy,
    observations: tuple[RollupObservation, ...],
    window_start: datetime,
    window_end: datetime,
) -> TemporalSummary:
    sources = {(item.source_id, item.source_partition_digest) for item in observations}
    if len(sources) > 1:
        raise ValueError("temporal rollup requires one source and source partition")
    bases = {item.event_at is not None for item in observations}
    if len(bases) > 1:
        raise ValueError("temporal rollup MUST NOT mix missing and present event times")
    if any(isinstance(item.value, Decimal) and not item.value.is_finite() for item in observations):
        raise ValueError("temporal numeric samples MUST be finite")
    samples = [
        cast(
            SampleData,
            asdict(
                Sample(
                    item.observation_id,
                    _decimal(item.value) if isinstance(item.value, Decimal) else str(item.value),
                    _iso(item.interval_start),
                    _iso(item.interval_end),
                    _iso(item.effective_at),
                    _iso(item.event_at) if item.event_at is not None else None,
                    item.generation_ref,
                    item.source_revision,
                    _iso(item.recorded_at),
                    item.complete,
                    item.conflict_count,
                )
            ),
        )
        for item in sorted(observations, key=lambda item: item.interval_start)
    ]
    for sample in samples:
        if not sample["interval_start"] <= _time(sample) <= sample["interval_end"]:
            raise ValueError("temporal sample time MUST be within its observation interval")
    summary: TemporalSummary = {
        "policy": binding(policy),
        "source": list(next(iter(sources))) if sources else None,
        "time_basis": "event_at" if bases == {True} else "effective_at" if bases else None,
        "first": samples[0] if samples else None,
        "last": samples[-1] if samples else None,
        "coverage": [],
    }
    if "counter_delta" in policy.statistics:
        if any(Decimal(sample["value"]) < 0 for sample in samples):
            raise ValueError("counter delta requires non-negative cumulative samples")
        summary["counter_delta"] = {"known_delta": "0", "resets": [], "unresolved": []}
    if "state_timeline" in policy.statistics or "change_timeline" in policy.statistics:
        summary["timeline"] = []
        summary["continuity"] = "not_asserted"
    if "extrema_timestamps" in policy.statistics:
        summary["extrema"] = {}
    for index, sample in enumerate(samples):
        if index:
            _validate_pair(samples[index - 1], sample)
            _counter_pair(policy, summary, samples[index - 1], sample)
        _cover(summary["coverage"], sample["interval_start"], sample["interval_end"])
        if "timeline" in summary:
            _append_run(
                policy,
                summary["timeline"],
                {
                    "value": sample["value"],
                    "first": sample,
                    "last": sample,
                    "count": 1,
                    "source_revision_order": [sample["source_revision"]],
                    "observed_interval_seconds": _decimal(
                        _seconds(sample["interval_start"], sample["interval_end"])
                    ),
                },
            )
        if "extrema" in summary:
            for name in ("minimum", "maximum"):
                old = summary["extrema"].get(name)
                if old is None or (
                    Decimal(sample["value"]) < Decimal(old["value"])
                    if name == "minimum"
                    else Decimal(sample["value"]) > Decimal(old["value"])
                ):
                    summary["extrema"][name] = sample
    _finish(summary, window_start, window_end)
    return summary


def _time(sample: SampleData) -> str:
    return str(sample["event_at"] or sample["effective_at"])


def _validate_pair(prior: SampleData, current: SampleData) -> None:
    if current["interval_start"] < prior["interval_end"]:
        raise ValueError("temporal observation intervals MUST NOT overlap")
    if _time(current) <= _time(prior) or current["effective_at"] <= prior["effective_at"]:
        raise ValueError("temporal observation order is ambiguous or contradictory")


def _counter_pair(
    policy: SemanticRollupPolicy,
    summary: TemporalSummary,
    prior: SampleData,
    current: SampleData,
) -> None:
    if "counter_delta" not in summary:
        return
    counter = summary["counter_delta"]
    reason = (
        "missing_interval"
        if current["interval_start"] != prior["interval_end"]
        or _seconds(_time(prior), _time(current)) > policy.expected_interval_seconds
        else "generation_boundary"
        if current["generation_ref"] != prior["generation_ref"]
        else "incomplete_or_conflicting"
        if not prior["complete"]
        or not current["complete"]
        or prior["conflict_count"]
        or current["conflict_count"]
        else None
    )
    edge: CounterEdge = {"before": prior, "after": current}
    if reason:
        counter["unresolved"].append({**edge, "reason": reason})
    elif Decimal(current["value"]) < Decimal(prior["value"]):
        counter["resets"].append(edge)
    else:
        counter["known_delta"] = _decimal(
            _add(
                Decimal(counter["known_delta"]),
                Decimal(current["value"]),
                Decimal(prior["value"]).copy_negate(),
            )
        )


def _append_run(policy: SemanticRollupPolicy, runs: list[StateRun], run: StateRun) -> None:
    if runs and "state_timeline" in policy.statistics:
        last = runs[-1]
        before, after = last["last"], run["first"]
        if (
            last["value"] == run["value"]
            and before["interval_end"] == after["interval_start"]
            and before["generation_ref"] == after["generation_ref"]
            and _seconds(_time(before), _time(after)) <= policy.expected_interval_seconds
            and before["complete"]
            and after["complete"]
            and not before["conflict_count"]
            and not after["conflict_count"]
        ):
            runs[-1] = {
                **last,
                "last": run["last"],
                "count": last["count"] + run["count"],
                "source_revision_order": last["source_revision_order"]
                + run["source_revision_order"][
                    int(last["source_revision_order"][-1] == run["source_revision_order"][0]) :
                ],
                "observed_interval_seconds": _decimal(
                    _add(
                        Decimal(last["observed_interval_seconds"]),
                        Decimal(run["observed_interval_seconds"]),
                    )
                ),
            }
            return
    runs.append(run)


def _cover(coverage: list[list[str]], start: str, end: str) -> None:
    if coverage and start == coverage[-1][1]:
        coverage[-1] = [coverage[-1][0], end]
    else:
        coverage.append([start, end])


def _finish(summary: TemporalSummary, start: datetime, end: datetime) -> None:
    cursor = _iso(start)
    gaps = []
    for left, right in summary["coverage"]:
        if cursor < left:
            gaps.append([cursor, left])
        cursor = right
    if cursor < _iso(end):
        gaps.append([cursor, _iso(end)])
    summary["gaps"] = gaps
    summary["observed_interval_seconds"] = _decimal(
        _add(*(_seconds(left, right) for left, right in summary["coverage"]))
    )
    if "counter_delta" in summary:
        counter = summary["counter_delta"]
        counter["reset_count"] = len(counter["resets"])
        counter["unresolved_step_count"] = len(counter["unresolved"])
        counter["delta_semantics"] = "sum_of_observed_non_decreasing_steps"
    if "timeline" in summary:
        summary["known_at_reconstruction"] = (
            "cannot_reconstruct_intermediate_known_at"
            if any(run["count"] > 2 for run in summary["timeline"])
            else "retained_boundary_recorded_times_only"
        )
        summary["transitions"] = [
            {
                "from_state": prior["value"],
                "to_state": current["value"],
                "after_observed_at": _time(prior["last"]),
                "by_observed_at": _time(current["first"]),
                "exact_transition_time_available": False,
                "evidence_status": (
                    "unresolved"
                    if prior["last"]["conflict_count"]
                    or current["first"]["conflict_count"]
                    or not prior["last"]["complete"]
                    or not current["first"]["complete"]
                    else "observed_bounds_only"
                ),
            }
            for prior, current in zip(summary["timeline"], summary["timeline"][1:], strict=False)
            if prior["value"] != current["value"]
        ]


def merge_temporal(
    policy: SemanticRollupPolicy,
    rollups: tuple[SemanticRollup, ...],
    rows: tuple[dict[str, Any], ...],
) -> TemporalSummary:
    """Combine sufficient statistics without replaying or inventing samples."""
    raw_summaries = [row.get("temporal") for row in rows]
    if any(
        not isinstance(item, dict) or item.get("policy") != binding(policy)
        for item in raw_summaries
    ):
        raise ValueError("temporal rollup merge requires the exact statistics policy")
    summaries = cast(list[TemporalSummary], raw_summaries)
    present = [item for item in summaries if item["first"] is not None]
    if len({tuple(item["source"] or ()) for item in present}) > 1:
        raise ValueError("temporal rollup merge requires one source and source partition")
    if len({item["time_basis"] for item in present}) > 1:
        raise ValueError("temporal rollup merge MUST NOT mix missing and present event times")
    # JSON decoding already makes these task-local copies, never shared input state.
    result = summaries[0]
    for current in summaries[1:]:
        prior_last = result["last"]
        if prior_last is not None and current["first"] is not None:
            _validate_pair(prior_last, current["first"])
            _counter_pair(policy, result, prior_last, current["first"])
        for start, end in current["coverage"]:
            _cover(result["coverage"], start, end)
        if "counter_delta" in result:
            left, right = result["counter_delta"], current["counter_delta"]
            left["known_delta"] = _decimal(
                _add(Decimal(left["known_delta"]), Decimal(right["known_delta"]))
            )
            left["resets"].extend(right["resets"])
            left["unresolved"].extend(right["unresolved"])
        if "timeline" in result:
            for run in current["timeline"]:
                _append_run(policy, result["timeline"], run)
        if "extrema" in result:
            for name, point in current["extrema"].items():
                old = result["extrema"].get(name)
                if old is None or (
                    Decimal(point["value"]) < Decimal(old["value"])
                    if name == "minimum"
                    else Decimal(point["value"]) > Decimal(old["value"])
                ):
                    result["extrema"][name] = point
        if result["first"] is None and current["first"] is not None:
            result["first"] = current["first"]
            result["source"] = current["source"]
            result["time_basis"] = current["time_basis"]
        if current["last"] is not None:
            result["last"] = current["last"]
    _finish(result, rollups[0].window_start, rollups[-1].window_end)
    return result
