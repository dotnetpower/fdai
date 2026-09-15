"""Project one complete analyzer tick into bounded aggregate coverage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime

from fdai_operator_service.analyzer_coverage_projection import (
    project_analyzer_coverage,
    unavailable_analyzer_coverage,
)
from fdai_operator_service.families.operations import ProjectionUnavailableError

_SCHEDULING = frozenset({"one_shot", "local_loop", "container_apps_job"})
_METRIC_ACCESS = frozenset({"available", "unavailable", "unverified"})
_EVENT_PUBLICATION = frozenset({"verified", "unavailable", "unverified"})


def project_analyzer_run(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    """Return the newest successful no-authority tick aggregate, or no aggregate."""

    for row in rows:
        try:
            projection = _project_analyzer_run(row, include_coverage=False)
        except ProjectionUnavailableError:
            return None
        if _is_successful(projection):
            return projection
    return None


def project_latest_analyzer_coverage(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Return coverage from the newest receipt without hiding failed evaluations."""

    if not rows:
        return {
            "source": "postgresql:state_kv:analyzer-tick-receipt",
            "recorded_at": None,
            **unavailable_analyzer_coverage(
                "receipt_absent",
                run_attempt_id=None,
            ),
        }
    try:
        projection = _project_analyzer_run(rows[0])
    except ProjectionUnavailableError:
        return {
            "source": "postgresql:state_kv:analyzer-tick-receipt",
            "recorded_at": None,
            **unavailable_analyzer_coverage(
                "invalid_receipt",
                run_attempt_id=None,
            ),
        }
    coverage = projection["coverage"]
    if not isinstance(coverage, Mapping):
        raise ProjectionUnavailableError("analyzer coverage projection is malformed")
    return {
        "source": projection["source"],
        "recorded_at": projection["recorded_at"],
        **coverage,
    }


def _project_analyzer_run(
    row: Mapping[str, object],
    *,
    include_coverage: bool = True,
) -> dict[str, object]:
    raw = row.get("value")
    if not isinstance(raw, Mapping) or raw.get("schema_version") not in {
        "1.2.0",
        "1.3.0",
    }:
        raise ProjectionUnavailableError("analyzer run receipt is malformed")
    schema_version = str(raw["schema_version"])
    report = _mapping(raw.get("report"), "analyzer run report")
    digest = _text(raw.get("report_digest"), "analyzer run report digest", maximum=64)
    canonical = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    if hashlib.sha256(canonical.encode()).hexdigest() != digest:
        raise ProjectionUnavailableError("analyzer run report digest mismatched")
    if raw.get("execution_authority") is not False:
        raise ProjectionUnavailableError("analyzer run receipt widened its authority")
    attempt_id = _text(raw.get("attempt_id"), "analyzer run attempt", maximum=64)
    coverage: dict[str, object] | None = None
    if include_coverage:
        if schema_version == "1.2.0":
            coverage = unavailable_analyzer_coverage(
                "legacy_receipt",
                run_attempt_id=attempt_id,
            )
        else:
            try:
                coverage = project_analyzer_coverage(
                    report.get("coverage"),
                    run_attempt_id=attempt_id,
                )
            except ProjectionUnavailableError:
                coverage = unavailable_analyzer_coverage(
                    "invalid_coverage",
                    run_attempt_id=attempt_id,
                )

    target_resolution = _mapping(
        report.get("target_resolution"),
        "analyzer target resolution",
    )
    readiness = _mapping(report.get("readiness"), "analyzer readiness")
    inventory_consulted = _boolean(
        target_resolution.get("inventory_consulted"),
        "inventory consulted",
    )
    source_complete = _boolean(
        target_resolution.get("source_complete"),
        "source completeness",
    )
    truncated = _boolean(target_resolution.get("truncated"), "target truncation")
    candidate_count = _optional_count(target_resolution, "candidate_count")
    skipped_reason_counts = _optional_count_mapping(
        target_resolution.get("skipped_reason_counts"),
        "analyzer skipped reason counts",
    )
    targets = _count(report, "targets")
    configured_targets = _count(target_resolution, "configured")
    discovered_targets = _count(target_resolution, "discovered")
    skipped_reasons = _string_list(
        target_resolution.get("skipped_reasons"),
        "analyzer skipped reasons",
        maximum=16,
    )
    trace_continuity = _mapping(
        report.get("trace_continuity"),
        "analyzer trace continuity",
    )
    if targets != configured_targets + discovered_targets:
        raise ProjectionUnavailableError("analyzer target totals do not reconcile")
    if candidate_count is not None and candidate_count < discovered_targets:
        raise ProjectionUnavailableError("analyzer candidate total does not reconcile")
    if skipped_reason_counts is not None and set(skipped_reason_counts) != set(skipped_reasons):
        raise ProjectionUnavailableError("analyzer skipped reasons do not reconcile")
    projection: dict[str, object] = {
        "source": "postgresql:state_kv:analyzer-tick-receipt",
        "recorded_at": _timestamp(raw.get("recorded_at")),
        "targets": targets,
        "findings": _count(report, "findings"),
        "published": _count(report, "published"),
        "duplicates_suppressed": _count(report, "duplicates_suppressed"),
        "uncertain": _count(report, "uncertain"),
        "configured_targets": configured_targets,
        "discovered_targets": discovered_targets,
        "candidate_count": candidate_count,
        "inventory_consulted": inventory_consulted,
        "source_complete": source_complete,
        "truncated": truncated,
        "skipped_reasons": skipped_reasons,
        "skipped_reason_counts": skipped_reason_counts,
        "unsupported_target_count": len(
            _string_list(
                report.get("unsupported_targets"),
                "unsupported analyzer targets",
                maximum=500,
            )
        ),
        "analyzer_error_count": _error_count(
            report.get("analyzer_errors"),
            "analyzer errors",
        ),
        "publish_error_count": _error_count(
            report.get("publish_errors"),
            "analyzer publish errors",
        ),
        "receipt_error_count": _error_count(
            report.get("receipt_errors"),
            "analyzer receipt errors",
        ),
        "trace_publish_error_count": _error_count(
            trace_continuity.get("publish_errors"),
            "trace continuity publish errors",
        ),
        "scheduling": _member(readiness, "scheduling", _SCHEDULING),
        "metric_access": _member(readiness, "metric_access", _METRIC_ACCESS),
        "event_publication": _member(
            readiness,
            "event_publication",
            _EVENT_PUBLICATION,
        ),
        "execution_authority": False,
    }
    if coverage is not None:
        projection["coverage"] = coverage
    return projection


def _is_successful(projection: Mapping[str, object]) -> bool:
    """Return whether a projected receipt represents a successful analyzer tick."""

    return (
        projection["source_complete"] is True
        and projection["truncated"] is False
        and projection["unsupported_target_count"] == 0
        and projection["analyzer_error_count"] == 0
        and projection["publish_error_count"] == 0
        and projection["receipt_error_count"] == 0
        and projection["trace_publish_error_count"] == 0
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


def _count(value: Mapping[str, object], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or isinstance(item, bool) or item < 0:
        raise ProjectionUnavailableError(f"analyzer run {key} is malformed")
    return item


def _optional_count(value: Mapping[str, object], key: str) -> int | None:
    return None if key not in value else _count(value, key)


def _optional_count_mapping(value: object, label: str) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or len(value) > 16:
        raise ProjectionUnavailableError(f"{label} is malformed")
    result: dict[str, int] = {}
    for key, item in value.items():
        if (
            not isinstance(key, str)
            or not key
            or len(key) > 128
            or not isinstance(item, int)
            or isinstance(item, bool)
            or item < 0
        ):
            raise ProjectionUnavailableError(f"{label} is malformed")
        result[key] = item
    return dict(sorted(result.items()))


def _boolean(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ProjectionUnavailableError(f"analyzer run {label} is malformed")
    return value


def _text(value: object, label: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ProjectionUnavailableError(f"{label} is malformed")
    return value


def _timestamp(value: object) -> str:
    text = _text(value, "analyzer run recorded_at", maximum=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProjectionUnavailableError("analyzer run recorded_at is malformed") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProjectionUnavailableError("analyzer run recorded_at is malformed")
    return parsed.isoformat()


def _string_list(value: object, label: str, *, maximum: int) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > maximum
        or any(not isinstance(item, str) or not item or len(item) > 128 for item in value)
        or len(value) != len(set(value))
    ):
        raise ProjectionUnavailableError(f"{label} is malformed")
    return sorted(value)


def _error_count(value: object, label: str) -> int:
    if not isinstance(value, list) or len(value) > 500:
        raise ProjectionUnavailableError(f"{label} is malformed")
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or any(not isinstance(part, str) or not part or len(part) > 512 for part in item)
        ):
            raise ProjectionUnavailableError(f"{label} is malformed")
    return len(value)


def _member(
    value: Mapping[str, object],
    key: str,
    allowed: frozenset[str],
) -> str:
    item = _text(value.get(key), f"analyzer readiness {key}")
    if item not in allowed:
        raise ProjectionUnavailableError(f"analyzer readiness {key} is unsupported")
    return item


__all__ = ["project_analyzer_run", "project_latest_analyzer_coverage"]
