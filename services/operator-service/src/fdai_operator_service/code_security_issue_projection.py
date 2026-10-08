"""Code-security issue summaries - one review's bounded issue rows for the Console.

Core records the summaries next to each review (``runtime:code-security-issues:<alias>:<rev>``)
bound by the review digest. This projection returns them only when the stored digest matches the
recorded review, so a summary row can never describe a different review. Each row carries triage
fields only; paths, lines, symbols, scanner messages, and code never leave developer machines.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

CODE_SECURITY_ISSUES_STATE_PREFIX = "runtime:code-security-issues:"
"""Mirrors the Core writer; the services stay independently packaged."""

GAP_ISSUES_MALFORMED = "code_security_issue_malformed"
GAP_ISSUES_UNAVAILABLE = "code_security_issues_unavailable"
GAP_ISSUES_TRUNCATED = "code_security_issues_truncated"

_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ISSUE = re.compile(r"^FDAI-SEC-[0-9a-f]{12}$")
_CLASS = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_ADVISORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_PACKAGE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9@._/+-]{0,127}$")
_PRODUCER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,63}$")
_PRIORITIES = ("P0", "P1", "P2", "P3", "P4")
_SEVERITIES = ("critical", "high", "medium", "low", "undetermined")
_CONFIDENCES = ("hypothesis", "reported", "corroborated", "verified", "proven")
_KEYS = frozenset(
    {
        "issue_id",
        "priority",
        "due_days",
        "severity",
        "confidence",
        "weakness_class",
        "cwe_ids",
        "advisory_ids",
        "package",
        "producers",
        "known_exploited",
    }
)
_MAX_ISSUES = 200
_FetchAll = Callable[[str, tuple[object, ...]], Awaitable[list[dict[str, Any]]]]
_ROW_SQL = "SELECT key, value FROM state_kv WHERE key = %s LIMIT 1"


class _MalformedError(ValueError):
    pass


def _tokens(raw: object, pattern: re.Pattern[str], limit: int) -> list[str]:
    if not isinstance(raw, list) or len(raw) > limit:
        raise _MalformedError
    if not all(isinstance(item, str) and pattern.fullmatch(item) for item in raw):
        raise _MalformedError
    return list(raw)


def _issue(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != _KEYS:
        raise _MalformedError
    issue_id, weakness, package = raw["issue_id"], raw["weakness_class"], raw["package"]
    due, cwe = raw["due_days"], raw["cwe_ids"]
    if not isinstance(issue_id, str) or not _ISSUE.fullmatch(issue_id):
        raise _MalformedError
    if raw["priority"] not in _PRIORITIES or raw["severity"] not in _SEVERITIES:
        raise _MalformedError
    if raw["confidence"] not in _CONFIDENCES:
        raise _MalformedError
    if not isinstance(weakness, str) or not _CLASS.fullmatch(weakness):
        raise _MalformedError
    if package is not None and (not isinstance(package, str) or not _PACKAGE.fullmatch(package)):
        raise _MalformedError
    if not isinstance(due, int) or isinstance(due, bool) or not 0 <= due <= 3650:
        raise _MalformedError
    if (
        not isinstance(cwe, list)
        or len(cwe) > 8
        or not all(isinstance(i, int) and not isinstance(i, bool) and 0 < i < 100_000 for i in cwe)
    ):
        raise _MalformedError
    if not isinstance(raw["known_exploited"], bool):
        raise _MalformedError
    return {
        "issue_id": issue_id,
        "priority": raw["priority"],
        "due_days": due,
        "severity": raw["severity"],
        "confidence": raw["confidence"],
        "weakness_class": weakness,
        "cwe_ids": list(cwe),
        "advisory_ids": _tokens(raw["advisory_ids"], _ADVISORY, 3),
        "package": package,
        "producers": _tokens(raw["producers"], _PRODUCER, 8),
        "known_exploited": raw["known_exploited"],
    }


def code_security_issues_projection(
    *,
    repository_alias: str,
    revision: str,
    review: Mapping[str, Any] | None,
    issues_row: Mapping[str, Any] | None,
) -> dict[str, object]:
    """Render one review's issue summaries, withholding rows that don't match its digest."""
    base: dict[str, object] = {
        "surface": "code-security-issues",
        "repository_alias": repository_alias,
        "revision": revision,
        "source": "postgresql:state_kv:code-security-issues",
        "issues": [],
        "truncated": False,
    }
    package = review.get("package") if isinstance(review, Mapping) else None
    digest = package.get("review_digest") if isinstance(package, Mapping) else None
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest) or issues_row is None:
        return {
            **base,
            "available": False,
            "complete": False,
            "gaps": [{"reason_code": GAP_ISSUES_UNAVAILABLE}],
        }
    stored, raw_issues = issues_row.get("review_digest"), issues_row.get("issues")
    truncated = issues_row.get("truncated")
    if stored != digest or not isinstance(raw_issues, list) or not isinstance(truncated, bool):
        return {
            **base,
            "available": False,
            "complete": False,
            "gaps": [{"reason_code": GAP_ISSUES_MALFORMED}],
        }
    issues: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    for raw in raw_issues[:_MAX_ISSUES]:
        try:
            issues.append(_issue(raw))
        except _MalformedError:
            gaps.append({"reason_code": GAP_ISSUES_MALFORMED})
    if truncated or len(raw_issues) > _MAX_ISSUES:
        gaps.append({"reason_code": GAP_ISSUES_TRUNCATED})
    return {
        **base,
        "available": True,
        "complete": not gaps,
        "issues": issues,
        "truncated": truncated,
        "gaps": gaps,
    }


def _single(params: Mapping[str, Sequence[str]], name: str, pattern: re.Pattern[str]) -> str:
    values = params.get(name, ())
    if len(values) != 1 or not pattern.fullmatch(values[0]):
        raise ValueError(f"{name} is required and must be valid")
    return values[0]


async def read_code_security_issues(
    params: Mapping[str, Sequence[str]],
    fetch_all: _FetchAll,
    review_prefix: str,
) -> Mapping[str, object]:
    """Read the review and its issue row for exactly one ``repository_alias`` and ``revision``."""
    alias = _single(params, "repository_alias", _ALIAS)
    revision = _single(params, "revision", _REVISION)
    review_rows = await fetch_all(_ROW_SQL, (f"{review_prefix}{alias}:{revision}",))
    issue_rows = await fetch_all(
        _ROW_SQL, (f"{CODE_SECURITY_ISSUES_STATE_PREFIX}{alias}:{revision}",)
    )
    review = review_rows[0].get("value") if review_rows else None
    issues_row = issue_rows[0].get("value") if issue_rows else None
    return code_security_issues_projection(
        repository_alias=alias,
        revision=revision,
        review=review if isinstance(review, Mapping) else None,
        issues_row=issues_row if isinstance(issues_row, Mapping) else None,
    )


__all__ = [
    "CODE_SECURITY_ISSUES_STATE_PREFIX",
    "GAP_ISSUES_MALFORMED",
    "GAP_ISSUES_TRUNCATED",
    "GAP_ISSUES_UNAVAILABLE",
    "code_security_issues_projection",
    "read_code_security_issues",
]
