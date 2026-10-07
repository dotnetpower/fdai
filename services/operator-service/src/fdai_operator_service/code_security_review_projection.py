"""Code-security review projection - state_kv rows to a Console envelope.

Core records one immutable review summary per repository revision
(``fdai.delivery.persistence.state_store_code_security_review``). This module renders those
summaries as-is: counts by priority, severity, and confidence, exposure, coverage completeness,
and opaque issue ids. It never re-derives severity or priority and never carries paths, code,
symbols, or scanner text.

Fail-closed contract: a row is rendered only when its key matches its identity and every field
is present, typed, and bounded. Any other row becomes an explicit gap, so an empty ``reviews``
list never reads as a clean estate. ``available`` states whether any usable review exists and
``complete`` states whether anything was withheld.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

CODE_SECURITY_REVIEW_STATE_PREFIX = "runtime:code-security-review:"
"""Mirrors the Core writer; the services stay independently packaged."""

GAP_MALFORMED = "code_security_review_malformed"
GAP_TRUNCATED = "code_security_review_truncated"

_MAX_ITEMS = 200
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ISSUE = re.compile(r"^FDAI-SEC-[0-9a-f]{12}$")
_PRIORITIES = ("P0", "P1", "P2", "P3", "P4")
_SEVERITIES = ("critical", "high", "medium", "low", "undetermined")
_CONFIDENCES = ("hypothesis", "reported", "corroborated", "verified", "proven")
_EXPOSURES = ("exposed", "internal", "not_deployed", "unknown")


class _MalformedError(ValueError):
    pass


def _match(value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise _MalformedError
    return value


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 1_000_000:
        raise _MalformedError
    return value


def _counts(value: object, keys: Sequence[str]) -> dict[str, int]:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise _MalformedError
    return {key: _count(value[key]) for key in keys}


def _decision(review: Mapping[str, Any]) -> str:
    """Mirror Core ``review_decision`` for display; it is never an authority."""
    if not review["coverage_complete"]:
        return "coverage_incomplete"
    if review["by_priority"]["P0"]:
        return "urgent"
    return "open" if review["issue_count"] else "clear"


def _review(key: object, value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _MalformedError
    package = value.get("package")
    if not isinstance(package, Mapping):
        raise _MalformedError
    if (
        package.get("kind") != "code-security-review"
        or package.get("grants_authority") is not False
    ):
        raise _MalformedError
    alias = _match(package.get("repository_alias"), _ALIAS)
    revision = _match(package.get("revision"), _REVISION)
    if key != f"{CODE_SECURITY_REVIEW_STATE_PREFIX}{alias}:{revision}":
        raise _MalformedError
    recorded_at = value.get("recorded_at")
    if not isinstance(recorded_at, str):
        raise _MalformedError
    try:
        datetime.fromisoformat(recorded_at)
    except ValueError as exc:
        raise _MalformedError from exc
    exposure = package.get("exposure")
    coverage = package.get("coverage_complete")
    top = package.get("top_issue_ids")
    if exposure not in _EXPOSURES or not isinstance(coverage, bool):
        raise _MalformedError
    if not isinstance(top, list) or len(top) > 20:
        raise _MalformedError
    review: dict[str, object] = {
        "repository_alias": alias,
        "revision": revision,
        "review_digest": _match(package.get("review_digest"), _DIGEST),
        "recorded_at": recorded_at,
        "issue_count": _count(package.get("issue_count")),
        "by_priority": _counts(package.get("by_priority"), _PRIORITIES),
        "by_severity": _counts(package.get("by_severity"), _SEVERITIES),
        "by_confidence": _counts(package.get("by_confidence"), _CONFIDENCES),
        "known_exploited_count": _count(package.get("known_exploited_count")),
        "exposure": exposure,
        "coverage_complete": coverage,
        "top_issue_ids": [_match(item, _ISSUE) for item in top],
    }
    review["decision"] = _decision(review)
    return review


def code_security_reviews_projection(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Render bounded review rows, newest first, with explicit gaps for withheld rows."""
    reviews: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    if len(rows) > _MAX_ITEMS:
        gaps.append({"reason_code": GAP_TRUNCATED})
    for row in rows[:_MAX_ITEMS]:
        try:
            reviews.append(_review(row.get("key"), row.get("value")))
        except _MalformedError:
            gaps.append({"reason_code": GAP_MALFORMED})
    reviews.sort(key=lambda item: (str(item["recorded_at"]), str(item["revision"])), reverse=True)
    return {
        "surface": "code-security-reviews",
        "available": bool(reviews),
        "complete": not gaps,
        "source": "postgresql:state_kv:code-security-review",
        "reviews": reviews,
        "gaps": gaps,
    }


__all__ = [
    "CODE_SECURITY_REVIEW_STATE_PREFIX",
    "GAP_MALFORMED",
    "GAP_TRUNCATED",
    "code_security_reviews_projection",
]
