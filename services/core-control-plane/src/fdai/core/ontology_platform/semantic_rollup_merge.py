"""Merge adjacent semantic rollups without losing source coverage."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal

from fdai.core.ontology_platform.semantic_rollup import (
    RollupFactKind,
    SemanticRollup,
    SemanticRollupPolicy,
)


def merge_semantic_rollups(
    policy: SemanticRollupPolicy,
    rollups: tuple[SemanticRollup, ...],
) -> SemanticRollup:
    """Merge ordered rollups and make uncovered gaps explicit."""

    if not rollups:
        raise ValueError("semantic rollup merge requires at least one rollup")
    unique = {item.digest: item for item in rollups}
    ordered = tuple(sorted(unique.values(), key=lambda item: item.window_start))
    for item in ordered:
        if (
            item.semantic_id != policy.semantic_id
            or item.fact_kind is not policy.fact_kind
            or item.policy_revision != policy.revision
            or item.ontology_release_digest != policy.ontology_release_digest
        ):
            raise ValueError("semantic rollup merge input does not match its policy")
    for prior, current in zip(ordered, ordered[1:], strict=False):
        if current.window_start < prior.window_end:
            raise ValueError("semantic rollup merge windows MUST NOT overlap")
    missing = [interval for item in ordered for interval in item.missing_intervals]
    for prior, current in zip(ordered, ordered[1:], strict=False):
        if current.window_start > prior.window_end:
            missing.append((prior.window_end, current.window_start))
    statistics = _merge_statistics(policy, ordered)
    source_ids = _strings(ordered, "source_ids")
    source_revisions = _strings(ordered, "source_revisions")
    source_partition_digests = _strings(ordered, "source_partition_digests")
    generation_refs = _strings(ordered, "generation_refs")
    effective_time_range = _merge_ranges(tuple(item.effective_time_range for item in ordered))
    event_time_range = _merge_ranges(tuple(item.event_time_range for item in ordered))
    recorded_time_range = _merge_ranges(tuple(item.recorded_time_range for item in ordered))
    conflict_count = sum(item.conflict_count for item in ordered)
    missing_intervals = tuple(sorted(set(missing)))
    complete = (
        all(item.complete for item in ordered) and not missing_intervals and conflict_count == 0
    )
    body = {
        "semantic_id": policy.semantic_id,
        "fact_kind": policy.fact_kind.value,
        "policy_revision": policy.revision,
        "ontology_release_digest": policy.ontology_release_digest,
        "window_start": ordered[0].window_start.astimezone(UTC).isoformat(),
        "window_end": ordered[-1].window_end.astimezone(UTC).isoformat(),
        "observation_count": sum(item.observation_count for item in ordered),
        "source_ids": source_ids,
        "source_revisions": source_revisions,
        "source_partition_digests": source_partition_digests,
        "generation_refs": generation_refs,
        "effective_time_range": _serialized_range(effective_time_range),
        "event_time_range": _serialized_range(event_time_range),
        "event_time_missing": any(item.event_time_missing for item in ordered),
        "recorded_time_range": _serialized_range(recorded_time_range),
        "missing_intervals": [
            [start.astimezone(UTC).isoformat(), end.astimezone(UTC).isoformat()]
            for start, end in missing_intervals
        ],
        "observed_zero": any(item.observed_zero for item in ordered),
        "conflict_count": conflict_count,
        "complete": complete,
        "statistics": statistics,
        "percentiles_available": False,
    }
    return SemanticRollup(
        semantic_id=policy.semantic_id,
        fact_kind=policy.fact_kind,
        policy_revision=policy.revision,
        ontology_release_digest=policy.ontology_release_digest,
        window_start=ordered[0].window_start,
        window_end=ordered[-1].window_end,
        observation_count=sum(item.observation_count for item in ordered),
        source_ids=source_ids,
        source_revisions=source_revisions,
        source_partition_digests=source_partition_digests,
        generation_refs=generation_refs,
        effective_time_range=effective_time_range,
        event_time_range=event_time_range,
        event_time_missing=any(item.event_time_missing for item in ordered),
        recorded_time_range=recorded_time_range,
        missing_intervals=missing_intervals,
        observed_zero=any(item.observed_zero for item in ordered),
        conflict_count=conflict_count,
        complete=complete,
        statistics_json=_canonical_json(statistics),
        percentiles_available=False,
        digest=_sha256(body),
    )


def _merge_statistics(
    policy: SemanticRollupPolicy,
    rollups: tuple[SemanticRollup, ...],
) -> dict[str, object]:
    rows = tuple(json.loads(item.statistics_json) for item in rollups)
    if policy.fact_kind in {RollupFactKind.GAUGE, RollupFactKind.COUNTER}:
        count = sum(int(row.get("count", 0)) for row in rows)
        total = sum((Decimal(str(row.get("sum", "0"))) for row in rows), Decimal(0))
        result: dict[str, object] = {}
        if "count" in policy.statistics:
            result["count"] = count
        if "sum" in policy.statistics:
            result["sum"] = _decimal(total)
        minimums = [Decimal(str(row["minimum"])) for row in rows if "minimum" in row]
        maximums = [Decimal(str(row["maximum"])) for row in rows if "maximum" in row]
        if minimums and "minimum" in policy.statistics:
            result["minimum"] = _decimal(min(minimums))
        if maximums and "maximum" in policy.statistics:
            result["maximum"] = _decimal(max(maximums))
        if count and "average" in policy.statistics:
            result["average"] = _decimal(total / count)
        return result
    if policy.fact_kind is RollupFactKind.CATEGORICAL_STATE:
        counts: dict[str, int] = {}
        for row in rows:
            for state, count in row.get("state_counts", {}).items():
                counts[str(state)] = counts.get(str(state), 0) + int(count)
        return {"state_counts": counts, "latest": rows[-1].get("latest")}
    keys = (
        ("added", "removed")
        if policy.fact_kind is RollupFactKind.RELATIONSHIP_CHANGE
        else (
            "healthy",
            "incomplete",
            "conflicting",
        )
    )
    return {key: sum(int(row.get(key, 0)) for row in rows) for key in keys}


def _strings(rollups: tuple[SemanticRollup, ...], name: str) -> tuple[str, ...]:
    return tuple(sorted({value for item in rollups for value in getattr(item, name)}))


def _merge_ranges(
    ranges: tuple[tuple[datetime, datetime] | None, ...],
) -> tuple[datetime, datetime] | None:
    present = tuple(item for item in ranges if item is not None)
    if not present:
        return None
    return min(item[0] for item in present), max(item[1] for item in present)


def _serialized_range(
    value: tuple[datetime, datetime] | None,
) -> tuple[str, str] | None:
    if value is None:
        return None
    return (
        value[0].astimezone(UTC).isoformat(),
        value[1].astimezone(UTC).isoformat(),
    )


def _decimal(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f") if normalized else "0"


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


__all__ = ["merge_semantic_rollups"]
