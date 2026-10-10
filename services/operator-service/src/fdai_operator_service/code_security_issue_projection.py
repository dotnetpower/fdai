"""Code-security issue summaries - one review's bounded issue rows for the Console.

Core records the summaries next to each review (``runtime:code-security-issues:<alias>:<rev>``)
bound by the review digest. This projection returns them only when the stored digest matches the
recorded review, so a summary row can never describe a different review. Each row carries triage
fields only; paths, lines, symbols, scanner messages, and code never leave developer machines.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from html import escape
from typing import Any

CODE_SECURITY_ISSUES_STATE_PREFIX = "runtime:code-security-issues:"
"""Mirrors the Core writer; the services stay independently packaged."""

GAP_ISSUES_MALFORMED = "code_security_issue_malformed"
GAP_ISSUES_UNAVAILABLE = "code_security_issues_unavailable"
GAP_ISSUES_TRUNCATED = "code_security_issues_truncated"
GAP_ARTIFACTS_UNAVAILABLE = "code_security_artifacts_unavailable"
GAP_ARTIFACTS_MALFORMED = "code_security_artifacts_malformed"

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
_MAX_ARTIFACT_BYTES = 900_000
_FetchAll = Callable[[str, tuple[object, ...]], Awaitable[list[dict[str, Any]]]]
_ROW_SQL = "SELECT key, value FROM state_kv WHERE key = %s LIMIT 1"
_SCORECARD_KEYS = (
    "critical",
    "high",
    "medium",
    "low",
    "informational",
    "needs_review",
    "potential_critical",
    "potential_high",
    "potential_medium",
    "potential_low",
)


class _MalformedError(ValueError):
    pass


def _summary_artifacts(
    repository_alias: str,
    revision: str,
    issues: Sequence[Mapping[str, object]],
) -> dict[str, str]:
    rows = "".join(
        "<tr>"
        f"<td>{escape(str(issue['issue_id']))}</td>"
        f"<td>{escape(str(issue['priority']))}</td>"
        f"<td>{escape(str(issue['severity']))}</td>"
        f"<td>{escape(str(issue['confidence']))}</td>"
        f"<td>{escape(str(issue['weakness_class']))}</td>"
        "</tr>"
        for issue in issues
    )
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'\"><title>FDAI code-security summary report</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem}table{border-collapse:collapse}"
        "th,td{border:1px solid #ccc;padding:.35rem .6rem;text-align:left}</style></head><body>"
        "<h1>FDAI code-security summary report</h1>"
        "<p>Full review artifacts are unavailable. This report contains bounded issue metadata "
        "only, with no source code, scanner messages, paths, or code flows.</p>"
        f"<p><strong>Repository:</strong> {escape(repository_alias)}<br>"
        f"<strong>Revision:</strong> {escape(revision)}</p>"
        "<table><thead><tr><th>Issue</th><th>Priority</th><th>Severity</th>"
        "<th>Confidence</th><th>Weakness class</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></body></html>\n"
    )
    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "FDAI summary projection", "rules": []}},
                "automationDetails": {"id": f"{repository_alias}/{revision}"},
                "results": [
                    {
                        "ruleId": str(issue["weakness_class"]),
                        "message": {"text": f"{issue['issue_id']}: FDAI issue summary"},
                        "properties": dict(issue),
                    }
                    for issue in issues
                ],
            }
        ],
    }
    return {
        "mode": "summary",
        "html": html,
        "sarif": json.dumps(sarif, indent=2, ensure_ascii=False) + "\n",
    }


def _relative_path(value: object) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 512:
        return None
    if value.startswith("/") or "\\" in value or "\x00" in value or ".." in value.split("/"):
        return None
    return value


def _sarif_issue_details(document: Mapping[str, object]) -> dict[str, dict[str, object]]:
    runs = document.get("runs")
    if not isinstance(runs, list) or len(runs) != 1 or not isinstance(runs[0], Mapping):
        return {}
    raw_results = runs[0].get("results")
    if not isinstance(raw_results, list) or len(raw_results) > _MAX_ISSUES:
        return {}
    details: dict[str, dict[str, object]] = {}
    for result in raw_results:
        if not isinstance(result, Mapping):
            continue
        properties = result.get("properties")
        if not isinstance(properties, Mapping):
            continue
        issue_id = properties.get("issue_id")
        if not isinstance(issue_id, str) or _ISSUE.fullmatch(issue_id) is None:
            continue
        title = properties.get("title")
        floor, ceiling = properties.get("severity_floor"), properties.get("severity_ceiling")
        rationale = properties.get("severity_rationale")
        deciding = properties.get("deciding_facts")
        locations = result.get("locations")
        location: dict[str, object] | None = None
        if isinstance(locations, list) and locations and isinstance(locations[0], Mapping):
            physical = locations[0].get("physicalLocation")
            if isinstance(physical, Mapping):
                artifact = physical.get("artifactLocation")
                path = (
                    _relative_path(artifact.get("uri")) if isinstance(artifact, Mapping) else None
                )
                region = physical.get("region")
                line = region.get("startLine") if isinstance(region, Mapping) else None
                if path is not None and (
                    line is None
                    or isinstance(line, int)
                    and not isinstance(line, bool)
                    and 0 < line <= 10_000_000
                ):
                    location = {"path": path, "start_line": line}
        code_context = _code_context(properties.get("code_context"))
        flow_steps = _flow_steps(properties.get("flow_steps"))
        details[issue_id] = {
            "title": title if isinstance(title, str) and 1 <= len(title) <= 256 else None,
            "severity_floor": floor if floor in _SEVERITIES[:-1] else None,
            "severity_ceiling": ceiling if ceiling in _SEVERITIES[:-1] else None,
            "severity_rationale": (
                rationale if isinstance(rationale, str) and len(rationale) <= 1024 else None
            ),
            "deciding_facts": (
                [item for item in deciding if isinstance(item, str) and len(item) <= 64][:8]
                if isinstance(deciding, list)
                else []
            ),
            "location": location,
            "code_context": code_context,
            "flow_steps": flow_steps,
        }
    return details


def _code_context(raw: object) -> dict[str, object] | None:
    if not isinstance(raw, Mapping):
        return None
    lines = raw.get("lines")
    start, highlight_start, highlight_end = (
        raw.get("start_line"),
        raw.get("highlight_start"),
        raw.get("highlight_end"),
    )
    if (
        not isinstance(lines, list)
        or not 1 <= len(lines) <= 7
        or not all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for value in (start, highlight_start, highlight_end)
        )
        or not isinstance(raw.get("redacted"), bool)
    ):
        return None
    normalized = []
    for line in lines:
        if not isinstance(line, Mapping):
            return None
        number, text = line.get("number"), line.get("text")
        if (
            not isinstance(number, int)
            or isinstance(number, bool)
            or number <= 0
            or not isinstance(text, str)
            or len(text) > 240
        ):
            return None
        normalized.append({"number": number, "text": text})
    return {
        "start_line": start,
        "highlight_start": highlight_start,
        "highlight_end": highlight_end,
        "redacted": raw["redacted"],
        "lines": normalized,
    }


def _flow_steps(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list) or len(raw) > 12:
        return []
    result = []
    for step in raw:
        if not isinstance(step, Mapping) or step.get("kind") not in {"source", "sink"}:
            return []
        path = _relative_path(step.get("path"))
        line = step.get("line")
        if path is None or (
            line is not None
            and (
                not isinstance(line, int)
                or isinstance(line, bool)
                or line <= 0
                or line > 10_000_000
            )
        ):
            return []
        result.append({"kind": step["kind"], "path": path, "line": line})
    return result


def _scorecard(issues: Sequence[Mapping[str, object]]) -> dict[str, int]:
    counts = {key: 0 for key in _SCORECARD_KEYS}
    for issue in issues:
        severity, priority = issue.get("severity"), issue.get("priority")
        if severity == "undetermined":
            counts["needs_review"] += 1
            ceiling = issue.get("severity_ceiling")
            if ceiling in {"critical", "high", "medium", "low"}:
                counts[f"potential_{ceiling}"] += 1
        elif severity == "low" and priority == "P4":
            counts["informational"] += 1
        elif severity in {"critical", "high", "medium", "low"}:
            counts[str(severity)] += 1
    return counts


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
        "title": None,
        "severity_floor": None,
        "severity_ceiling": None,
        "severity_rationale": None,
        "deciding_facts": [],
        "location": None,
        "code_context": None,
        "flow_steps": [],
    }


def code_security_issues_projection(
    *,
    repository_alias: str,
    revision: str,
    review: Mapping[str, Any] | None,
    issues_row: Mapping[str, Any] | None,
    artifacts_row: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    """Render one review's issue summaries, withholding rows that don't match its digest."""
    base: dict[str, object] = {
        "surface": "code-security-issues",
        "repository_alias": repository_alias,
        "revision": revision,
        "source": "postgresql:state_kv:code-security-issues",
        "issues": [],
        "truncated": False,
        "artifacts": None,
        "scorecard": {key: 0 for key in _SCORECARD_KEYS},
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
    artifacts: dict[str, str] | None = None
    artifact_details: dict[str, dict[str, object]] = {}
    if artifacts_row is None:
        gaps.append({"reason_code": GAP_ARTIFACTS_UNAVAILABLE})
    elif artifacts_row.get("kind") == "code-security-review-artifacts-unavailable":
        expected_gap = {
            "kind",
            "schema_version",
            "repository_alias",
            "revision",
            "review_digest",
            "recorded_at",
            "reason_code",
        }
        if (
            set(artifacts_row) == expected_gap
            and artifacts_row.get("schema_version") == "1.3.0"
            and artifacts_row.get("repository_alias") == repository_alias
            and artifacts_row.get("revision") == revision
            and artifacts_row.get("review_digest") == digest
            and isinstance(artifacts_row.get("recorded_at"), str)
            and artifacts_row.get("reason_code") == "artifact_size_exceeded"
        ):
            gaps.append({"reason_code": GAP_ARTIFACTS_UNAVAILABLE})
        else:
            gaps.append({"reason_code": GAP_ARTIFACTS_MALFORMED})
    else:
        expected = {
            "kind",
            "schema_version",
            "repository_alias",
            "revision",
            "review_digest",
            "recorded_at",
            "html",
            "sarif",
        }
        html, sarif = artifacts_row.get("html"), artifacts_row.get("sarif")
        try:
            sarif_document = json.loads(sarif) if isinstance(sarif, str) else None
        except json.JSONDecodeError:
            sarif_document = None
        if (
            set(artifacts_row) != expected
            or artifacts_row.get("kind") != "code-security-review-artifacts"
            or artifacts_row.get("schema_version") != "1.3.0"
            or artifacts_row.get("repository_alias") != repository_alias
            or artifacts_row.get("revision") != revision
            or artifacts_row.get("review_digest") != digest
            or not isinstance(artifacts_row.get("recorded_at"), str)
            or not isinstance(html, str)
            or not html.startswith("<!doctype html>")
            or not isinstance(sarif, str)
            or not isinstance(sarif_document, Mapping)
            or sarif_document.get("version") != "2.1.0"
            or len(str(artifacts_row).encode()) > _MAX_ARTIFACT_BYTES
        ):
            gaps.append({"reason_code": GAP_ARTIFACTS_MALFORMED})
        else:
            artifact_details = _sarif_issue_details(sarif_document)
            artifacts = {"mode": "full", "html": html, "sarif": sarif}
    if artifact_details:
        issues = [{**issue, **artifact_details.get(str(issue["issue_id"]), {})} for issue in issues]
    if artifacts is None:
        artifacts = _summary_artifacts(repository_alias, revision, issues)
    return {
        **base,
        "available": True,
        "complete": not gaps,
        "issues": issues,
        "truncated": truncated,
        "artifacts": artifacts,
        "scorecard": _scorecard(issues),
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
    artifact_rows = await fetch_all(
        _ROW_SQL,
        (f"{CODE_SECURITY_ISSUES_STATE_PREFIX}{alias}:{revision}:artifacts-1.3",),
    )
    review = review_rows[0].get("value") if review_rows else None
    issues_row = issue_rows[0].get("value") if issue_rows else None
    artifacts_row = artifact_rows[0].get("value") if artifact_rows else None
    return code_security_issues_projection(
        repository_alias=alias,
        revision=revision,
        review=review if isinstance(review, Mapping) else None,
        issues_row=issues_row if isinstance(issues_row, Mapping) else None,
        artifacts_row=artifacts_row if isinstance(artifacts_row, Mapping) else None,
    )


__all__ = [
    "CODE_SECURITY_ISSUES_STATE_PREFIX",
    "GAP_ARTIFACTS_MALFORMED",
    "GAP_ARTIFACTS_UNAVAILABLE",
    "GAP_ISSUES_MALFORMED",
    "GAP_ISSUES_TRUNCATED",
    "GAP_ISSUES_UNAVAILABLE",
    "code_security_issues_projection",
    "read_code_security_issues",
]
