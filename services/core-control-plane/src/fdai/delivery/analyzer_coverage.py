"""Reconcile per-resource analyzer coverage into the versioned per-type run receipt."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from fdai.delivery.analyzer_targets import AnalyzerResourceTypeResolution
from fdai.delivery.analyzer_tick import AnalyzerPublicationStatus

PUBLICATION_STATES = tuple(item.value for item in AnalyzerPublicationStatus)


def normalize_publication_counts(counts: Mapping[str, int]) -> dict[str, int]:
    return {state: counts.get(state, 0) for state in PUBLICATION_STATES}


def coverage_by_resource_type(
    resolutions: tuple[AnalyzerResourceTypeResolution, ...],
    resources: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows: dict[str, dict[str, object]] = {
        resolution.resource_type: {
            "resource_type": resolution.resource_type,
            "candidate_count": resolution.candidate_count,
            "selected_count": resolution.selected_count,
            "evaluated_count": 0,
            "held_count": resolution.held_count,
            "held_reason_counts": dict(resolution.held_reason_counts),
            "finding_count": 0,
            "unsupported_count": 0,
            "error_count": 0,
            "error_codes": [],
            "publication_counts": normalize_publication_counts({}),
        }
        for resolution in resolutions
    }
    observed_selected: Counter[str] = Counter()
    for resource in resources:
        resource_type = resource.get("resource_type")
        evaluation_state = resource.get("evaluation_state")
        finding_count = resource.get("finding_count")
        unsupported_count = resource.get("unsupported_count")
        error_count = resource.get("error_count")
        error_codes = resource.get("error_codes")
        publication_counts = resource.get("publication_counts")
        if (
            not isinstance(resource_type, str)
            or resource_type not in rows
            or not isinstance(evaluation_state, str)
            or not isinstance(finding_count, int)
            or not isinstance(unsupported_count, int)
            or not isinstance(error_count, int)
            or not isinstance(error_codes, list)
            or any(not isinstance(code, str) for code in error_codes)
            or not isinstance(publication_counts, Mapping)
        ):
            raise ValueError("analyzer coverage resource row is malformed")
        row = rows[resource_type]
        observed_selected[resource_type] += 1
        if evaluation_state in {"evaluated_no_finding", "finding"}:
            _increment_coverage_count(row, "evaluated_count", 1)
        _increment_coverage_count(row, "finding_count", finding_count)
        _increment_coverage_count(row, "unsupported_count", unsupported_count)
        _increment_coverage_count(row, "error_count", error_count)
        row_error_codes = row["error_codes"]
        if not isinstance(row_error_codes, list):
            raise ValueError("analyzer coverage error codes are malformed")
        row["error_codes"] = sorted(set(row_error_codes) | set(error_codes))
        row_publications = row["publication_counts"]
        if not isinstance(row_publications, dict):
            raise ValueError("analyzer coverage publication counts are malformed")
        for state in PUBLICATION_STATES:
            value = publication_counts.get(state)
            current = row_publications.get(state)
            if not isinstance(value, int) or not isinstance(current, int):
                raise ValueError("analyzer coverage publication count is malformed")
            row_publications[state] = current + value
    for resolution in resolutions:
        if observed_selected[resolution.resource_type] != resolution.selected_count:
            raise ValueError("analyzer coverage selected totals MUST reconcile")
    return [rows[resource_type] for resource_type in sorted(rows)]


def _increment_coverage_count(
    row: dict[str, object],
    key: str,
    increment: int,
) -> None:
    current = row.get(key)
    if not isinstance(current, int):
        raise ValueError("analyzer coverage count is malformed")
    row[key] = current + increment
