"""Bounded read-only projection of context-selection shadow comparisons.

Responsibility: Reduce durable comparison records to the exact Reader panel payload.
Boundary: No storage, transport, or governance transition lives here.
Authority and state: The projection is read-only and owns no state.
Dependencies: Python typing primitives and Starlette's HTTP error type only.
Deployment: Process-local helper inside the independently deployable Operator Service.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final, cast

from fdai_service_contracts import JsonObject, JsonValue
from starlette.exceptions import HTTPException

_ROW_FIELDS: Final = (
    "evaluation_id",
    "baseline_policy_ref",
    "candidate_policy_ref",
    "baseline_tokens",
    "candidate_tokens",
    "evidence_overlap",
    "omissions",
    "pinned_preserved",
    "latency_ms",
    "failure_reason",
    "created_at",
)


def project_context_selection_comparisons(
    records: Sequence[Mapping[str, object]],
) -> JsonObject:
    """Return the read-only comparison panel payload for durable records.

    The payload always declares `read_only` and `mutation_controls` so the browser can
    reject any response that would imply a governance control. A malformed durable
    record fails closed with HTTP 503 instead of degrading into a partial panel.
    """

    comparisons = [_row(record) for record in records]
    return {
        "read_only": True,
        "mutation_controls": False,
        "count": len(comparisons),
        "invariant_failures": sum(1 for row in comparisons if row["failure_reason"] is not None),
        "comparisons": cast(list[JsonValue], comparisons),
    }


def _row(record: Mapping[str, object]) -> dict[str, JsonValue]:
    if any(field not in record for field in _ROW_FIELDS):
        raise _malformed()
    failure_reason = record["failure_reason"]
    return {
        "evaluation_id": _text(record["evaluation_id"]),
        "baseline_policy_ref": _text(record["baseline_policy_ref"]),
        "candidate_policy_ref": _text(record["candidate_policy_ref"]),
        "baseline_tokens": _count(record["baseline_tokens"]),
        "candidate_tokens": _optional_count(record["candidate_tokens"]),
        "evidence_overlap": _optional_ratio(record["evidence_overlap"]),
        "omissions": [_text(item) for item in _sequence(record["omissions"])],
        "pinned_preserved": _flag(record["pinned_preserved"]),
        "latency_ms": _duration(record["latency_ms"]),
        "failure_reason": None if failure_reason is None else _text(failure_reason),
        "created_at": _text(record["created_at"]),
    }


def _malformed() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="authoritative context-selection comparison is malformed",
    )


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _malformed()
    return value


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _malformed()
    return value


def _optional_count(value: object) -> int | None:
    return None if value is None else _count(value)


def _optional_ratio(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _malformed()
    if not 0.0 <= float(value) <= 1.0:
        raise _malformed()
    return float(value)


def _flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise _malformed()
    return value


def _duration(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0.0:
        raise _malformed()
    return float(value)


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, list):
        raise _malformed()
    return value


__all__ = ["project_context_selection_comparisons"]
