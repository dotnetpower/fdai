"""Bounded per-issue summaries recorded next to a code-security review for the Console.

The review package that travels on Heimdall's bus carries counts and opaque ids only. Operators
also need to see which issues a review found, so the scan records a separate state row with one
summary per canonical issue: id, priority, severity, confidence, weakness class, CWE ids, up to
three advisory ids, the dependency package name, producers, and known exploitation.

A summary never carries a path, line, symbol, scanner message, code flow, or secret value; those
stay in the SARIF, reports, and remediation packs on developer machines. Summaries are bounded,
validated on write and on read, and bound to the review by its digest.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from fdai.core.security.code_findings.models import UNDETERMINED, CodeSecurityIssue
from fdai.rule_catalog.code_security import Confidence, Priority, SeverityBand

MAX_ISSUE_SUMMARIES = 200
_ISSUE = re.compile(r"^FDAI-SEC-[0-9a-f]{12}$")
_CLASS = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
_ADVISORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_PACKAGE = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9@._/+-]{0,127}$")
_PRODUCER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,63}$")
_SEVERITIES = (*(band.value for band in SeverityBand), UNDETERMINED)
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


class IssueSummaryError(ValueError):
    """An issue summary is malformed or carries a field outside the bounded contract."""


def _token(value: object, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def summarize_issue(issue: CodeSecurityIssue) -> dict[str, object]:
    """Return the bounded summary of one issue; unsafe optional tokens are dropped."""
    return {
        "issue_id": issue.issue_id,
        "priority": issue.priority.priority.value,
        "due_days": issue.priority.due_days,
        "severity": issue.severity.label if issue.severity.label in _SEVERITIES else UNDETERMINED,
        "confidence": issue.confidence.value,
        "weakness_class": issue.weakness_class
        if _CLASS.fullmatch(issue.weakness_class)
        else "unclassified",
        "cwe_ids": sorted({cwe for cwe in issue.cwe_ids if 0 < cwe < 100_000})[:8],
        "advisory_ids": sorted({item for item in issue.advisory_ids if _token(item, _ADVISORY)})[
            :3
        ],
        "package": _token(issue.package, _PACKAGE),
        "producers": sorted({item for item in issue.producers if _token(item, _PRODUCER)})[:8],
        "known_exploited": issue.known_exploited,
    }


def summarize_issues(issues: Sequence[CodeSecurityIssue]) -> tuple[list[dict[str, object]], bool]:
    """Return summaries for the most urgent issues first and whether any were left out."""
    ordered = list(issues)[:MAX_ISSUE_SUMMARIES]
    return [summarize_issue(issue) for issue in ordered], len(issues) > MAX_ISSUE_SUMMARIES


def _int_list(raw: object, *, limit: int) -> list[int]:
    if (
        not isinstance(raw, list)
        or len(raw) > limit
        or not all(isinstance(i, int) and not isinstance(i, bool) and 0 < i < 100_000 for i in raw)
    ):
        raise IssueSummaryError("cwe_ids must be a short list of CWE numbers")
    return list(raw)


def _token_list(raw: object, pattern: re.Pattern[str], *, limit: int, name: str) -> list[str]:
    if not isinstance(raw, list) or len(raw) > limit:
        raise IssueSummaryError(f"{name} must be a short list")
    if not all(isinstance(item, str) and pattern.fullmatch(item) for item in raw):
        raise IssueSummaryError(f"{name} holds an invalid token")
    return list(raw)


def validate_issue_summary(raw: Mapping[str, object]) -> dict[str, object]:
    """Return a normalized copy of an untrusted summary or raise ``IssueSummaryError``."""
    if set(raw) != _KEYS:
        raise IssueSummaryError("issue summary fields are invalid")
    issue_id = _token(raw["issue_id"], _ISSUE)
    if issue_id is None:
        raise IssueSummaryError("issue_id is invalid")
    if raw["priority"] not in {item.value for item in Priority}:
        raise IssueSummaryError("priority is invalid")
    due = raw["due_days"]
    if not isinstance(due, int) or isinstance(due, bool) or not 0 <= due <= 3650:
        raise IssueSummaryError("due_days is invalid")
    if raw["severity"] not in _SEVERITIES:
        raise IssueSummaryError("severity is invalid")
    if raw["confidence"] not in {item.value for item in Confidence}:
        raise IssueSummaryError("confidence is invalid")
    weakness = _token(raw["weakness_class"], _CLASS)
    if weakness is None:
        raise IssueSummaryError("weakness_class is invalid")
    package = raw["package"]
    if package is not None and _token(package, _PACKAGE) is None:
        raise IssueSummaryError("package is invalid")
    if not isinstance(raw["known_exploited"], bool):
        raise IssueSummaryError("known_exploited must be a boolean")
    return {
        "issue_id": issue_id,
        "priority": raw["priority"],
        "due_days": due,
        "severity": raw["severity"],
        "confidence": raw["confidence"],
        "weakness_class": weakness,
        "cwe_ids": _int_list(raw["cwe_ids"], limit=8),
        "advisory_ids": _token_list(raw["advisory_ids"], _ADVISORY, limit=3, name="advisory_ids"),
        "package": package,
        "producers": _token_list(raw["producers"], _PRODUCER, limit=8, name="producers"),
        "known_exploited": raw["known_exploited"],
    }


__all__ = [
    "MAX_ISSUE_SUMMARIES",
    "IssueSummaryError",
    "summarize_issue",
    "summarize_issues",
    "validate_issue_summary",
]
