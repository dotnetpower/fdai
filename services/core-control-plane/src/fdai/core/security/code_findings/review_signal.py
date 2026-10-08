"""Code-security review signals for Heimdall's existing Drift ownership.

A scan produces a strict, no-authority review package: counts by priority, severity, and
confidence, known exploitation, exposure, coverage completeness, and up to twenty opaque issue
ids. It carries no paths, code, symbols, or scanner text, because bus messages reach the Console,
Bragi, and audit. Heimdall projects the package into ``object.drift`` with a shadow ceiling;
Forseti judges it and Saga audits the verdict. Nothing in the package can grant execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

from fdai.core.security.code_findings.models import UNDETERMINED, CodeSecurityIssue
from fdai.rule_catalog.code_security import Confidence, Exposure, Priority, SeverityBand

PACKAGE_KIND = "code-security-review"
EVENT_TYPE = "code_security.findings_drift"
_ALIAS = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REVISION = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_ISSUE = re.compile(r"^FDAI-SEC-[0-9a-f]{12}$")
_SEVERITIES = (*(band.value for band in SeverityBand), UNDETERMINED)
_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "repository_alias",
        "revision",
        "review_digest",
        "issue_count",
        "by_priority",
        "by_severity",
        "by_confidence",
        "known_exploited_count",
        "exposure",
        "coverage_complete",
        "top_issue_ids",
        "review_required",
        "grants_authority",
    }
)


class CodeSecurityReviewError(ValueError):
    """Raised when a review package is malformed or claims authority."""


def _counts(values: Sequence[str], keys: Sequence[str]) -> dict[str, int]:
    return {key: sum(1 for value in values if value == key) for key in keys}


def build_review_package(
    issues: Sequence[CodeSecurityIssue],
    *,
    repository_alias: str,
    revision: str,
    exposure: Exposure,
    coverage_complete: bool,
) -> dict[str, object]:
    """Return a strict review package for ``issues`` (ordered by priority)."""
    priorities = [issue.priority.priority.value for issue in issues]
    severities = [issue.severity.label for issue in issues]
    confidences = [issue.confidence.value for issue in issues]
    issue_ids = sorted(issue.issue_id for issue in issues)
    digest = hashlib.sha256(
        json.dumps([repository_alias, revision, issue_ids, priorities]).encode()
    ).hexdigest()
    package: dict[str, object] = {
        "schema_version": "1.0.0",
        "kind": PACKAGE_KIND,
        "repository_alias": repository_alias,
        "revision": revision,
        "review_digest": digest,
        "issue_count": len(issues),
        "by_priority": _counts(priorities, [p.value for p in Priority]),
        "by_severity": _counts(severities, _SEVERITIES),
        "by_confidence": _counts(confidences, [c.value for c in Confidence]),
        "known_exploited_count": sum(1 for issue in issues if issue.known_exploited),
        "exposure": exposure.value,
        "coverage_complete": coverage_complete,
        "top_issue_ids": [issue.issue_id for issue in issues[:20]],
        "review_required": True,
        "grants_authority": False,
    }
    return validate_review_package(package)


def _count_map(raw: object, keys: Sequence[str], name: str) -> dict[str, int]:
    if not isinstance(raw, Mapping) or set(raw) != set(keys):
        raise CodeSecurityReviewError(f"{name} must count exactly {', '.join(keys)}")
    result = {}
    for key in keys:
        value = raw[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise CodeSecurityReviewError(f"{name}.{key} must be a non-negative integer")
        result[key] = value
    return result


def validate_review_package(raw: Mapping[str, object]) -> dict[str, object]:
    """Return a normalized copy of an untrusted package or raise."""
    if set(raw) != _KEYS:
        raise CodeSecurityReviewError("code-security review package fields are invalid")
    if raw["schema_version"] != "1.0.0" or raw["kind"] != PACKAGE_KIND:
        raise CodeSecurityReviewError("code-security review package identity is invalid")
    if raw["review_required"] is not True or raw["grants_authority"] is not False:
        raise CodeSecurityReviewError("code-security review authority boundary is invalid")
    alias, revision = raw["repository_alias"], raw["revision"]
    if not isinstance(alias, str) or _ALIAS.fullmatch(alias) is None:
        raise CodeSecurityReviewError("repository_alias is invalid")
    if not isinstance(revision, str) or _REVISION.fullmatch(revision) is None:
        raise CodeSecurityReviewError("revision must be a full commit id")
    digest = raw["review_digest"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise CodeSecurityReviewError("review_digest is invalid")
    count = raw["issue_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise CodeSecurityReviewError("issue_count must be a non-negative integer")
    by_priority = _count_map(raw["by_priority"], [p.value for p in Priority], "by_priority")
    by_severity = _count_map(raw["by_severity"], _SEVERITIES, "by_severity")
    by_confidence = _count_map(raw["by_confidence"], [c.value for c in Confidence], "by_confidence")
    for name, counts in (
        ("by_priority", by_priority),
        ("by_severity", by_severity),
        ("by_confidence", by_confidence),
    ):
        if sum(counts.values()) != count:
            raise CodeSecurityReviewError(f"{name} does not add up to issue_count")
    kev = raw["known_exploited_count"]
    if not isinstance(kev, int) or isinstance(kev, bool) or not 0 <= kev <= count:
        raise CodeSecurityReviewError("known_exploited_count is invalid")
    try:
        exposure = Exposure(str(raw["exposure"]))
    except ValueError as exc:
        raise CodeSecurityReviewError("exposure is invalid") from exc
    if not isinstance(raw["coverage_complete"], bool):
        raise CodeSecurityReviewError("coverage_complete must be a boolean")
    top = raw["top_issue_ids"]
    if (
        not isinstance(top, list)
        or len(top) > min(20, count)
        or not all(isinstance(i, str) and _ISSUE.fullmatch(i) for i in top)
    ):
        raise CodeSecurityReviewError("top_issue_ids must hold at most 20 issue ids")
    return {
        "schema_version": "1.0.0",
        "kind": PACKAGE_KIND,
        "repository_alias": alias,
        "revision": revision,
        "review_digest": digest,
        "issue_count": count,
        "by_priority": by_priority,
        "by_severity": by_severity,
        "by_confidence": by_confidence,
        "known_exploited_count": kev,
        "exposure": exposure.value,
        "coverage_complete": raw["coverage_complete"],
        "top_issue_ids": list(top),
        "review_required": True,
        "grants_authority": False,
    }


def review_decision(package: Mapping[str, object]) -> str:
    """Return ``coverage_incomplete``, ``urgent``, ``open``, or ``clear`` deterministically."""
    by_priority = package["by_priority"]
    if package["coverage_complete"] is not True:
        return "coverage_incomplete"
    if isinstance(by_priority, Mapping) and by_priority.get("P0", 0):
        return "urgent"
    return "open" if package["issue_count"] else "clear"


def code_security_drift_payload(raw: Mapping[str, object]) -> dict[str, object]:
    """Project one strict package into Heimdall's Drift ownership with a shadow ceiling."""
    package = validate_review_package(raw)
    alias = str(package["repository_alias"])
    digest = str(package["review_digest"])
    return {
        "producer_principal": "Heimdall",
        "kind": "code_security",
        "event_type": EVENT_TYPE,
        "correlation_id": f"code-security:{alias}:{digest}",
        "idempotency_key": f"code-security-drift:{digest}",
        "resource_id": f"code-repository://{alias}",
        "target_type": "code-repository",
        "decision": review_decision(package),
        "authority_ceiling": "shadow",
        **{key: package[key] for key in sorted(package) if key not in ("schema_version", "kind")},
    }


__all__ = [
    "EVENT_TYPE",
    "PACKAGE_KIND",
    "CodeSecurityReviewError",
    "build_review_package",
    "code_security_drift_payload",
    "review_decision",
    "validate_review_package",
]
