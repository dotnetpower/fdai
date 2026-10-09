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

Schema ``1.1.0`` reviews also carry their ``source`` (local path, git repository, or external
SARIF, with provider and trigger) and producer names, so the Console can separate results; older
rows render with ``source: null``. Registered repositories and Console scan requests are rendered
from their own state rows without credentials, requester identities, or code.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CODE_SECURITY_REVIEW_STATE_PREFIX = "runtime:code-security-review:"
"""Mirrors the Core writer; the services stay independently packaged."""

CODE_SECURITY_PACK_STATE_PREFIX = "runtime:code-security-pack:"
"""Mirrors the Core state-store pack registry."""

CODE_SECURITY_REPOSITORY_STATE_PREFIX = "runtime:code-security-repository:"
"""Mirrors the Core repository registration store."""

SCAN_REQUEST_OPERATION = "code_security.scan_request"
GAP_REPOSITORY_MALFORMED = "code_security_repository_malformed"
GAP_REQUEST_MALFORMED = "code_security_scan_request_malformed"

GAP_MALFORMED = "code_security_review_malformed"
GAP_PACK_MALFORMED = "code_security_pack_malformed"
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
_PACK_ID = re.compile(r"^[0-9a-f]{12}$")
_PRINCIPAL = re.compile(r"^[A-Za-z0-9@._:/+-]{1,128}$")
_VERDICTS = ("fixed_verified", "still_present", "inconclusive", "not_applicable")
_DECISIONS = ("accepted", "rejected")
_DISPOSITIONS = ("false_positive", "open")
_MAX_REVIEWS = 500
_SOURCE_KINDS = ("local_path", "git_repository", "external_sarif")
_REVISION_KINDS = ("commit", "snapshot")
_TRIGGERS = ("cli", "console", "schedule")
_PROVIDER = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_PRODUCER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,63}$")
_REQUEST_ID = re.compile(r"^operator-[0-9a-f]{32}$")
_LOCATION = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_REF_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$"
_REF = re.compile(_REF_PATTERN)
_ALIAS_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
_REQUEST_STATUSES = {
    "pending": "queued",
    "claimed": "running",
    "published": "completed",
    "rejected": "rejected",
}
_REJECTIONS = (
    "request_malformed",
    "requester_role_insufficient",
    "repository_not_registered",
    "repository_disabled",
    "repository_conflict",
    "source_unavailable",
    "scan_failed",
    "review_conflict",
    "attempts_exhausted",
)
REPOSITORY_CHANGE_OPERATION = "code_security.repository_change"
_CHANGE_ACTIONS = ("register", "enable", "disable", "connect", "disconnect")
_LOCATION_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"


class CodeSecurityScanRequestBody(BaseModel):
    """The only fields a Console scan request may carry; the worker re-validates them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    repository_alias: str = Field(pattern=_ALIAS_PATTERN)
    ref: str | None = Field(default=None, pattern=_REF_PATTERN)


class CodeSecurityRepositoryChangeBody(BaseModel):
    """An Owner's registration change; ``register`` needs a GitHub ``owner/repository``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["register", "enable", "disable"]
    repository_alias: str = Field(pattern=_ALIAS_PATTERN)
    location: str | None = Field(default=None, pattern=_LOCATION_PATTERN)
    default_ref: str | None = Field(default=None, pattern=_REF_PATTERN)
    exposure: Literal["exposed", "internal", "not_deployed", "unknown"] | None = None

    @model_validator(mode="after")
    def _fields_match_action(self) -> CodeSecurityRepositoryChangeBody:
        if self.action == "register" and self.location is None:
            raise ValueError("register needs a location")
        if self.action != "register" and (
            self.location is not None or self.default_ref is not None or self.exposure is not None
        ):
            raise ValueError("enable and disable take only the alias")
        if self.default_ref is not None and ".." in self.default_ref:
            raise ValueError("default_ref is invalid")
        return self


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
        "source": None,
        "producers": [],
    }
    if package.get("schema_version") == "1.1.0":
        review["source"] = _source(package.get("source"))
        producers = package.get("producers")
        if not isinstance(producers, list) or len(producers) > 16:
            raise _MalformedError
        review["producers"] = [_match(item, _PRODUCER) for item in producers]
    review["decision"] = _decision(review)
    return review


def _source(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _MalformedError
    kind, revision_kind, trigger = (
        value.get("kind"),
        value.get("revision_kind"),
        value.get("trigger"),
    )
    if (
        kind not in _SOURCE_KINDS
        or revision_kind not in _REVISION_KINDS
        or trigger not in _TRIGGERS
    ):
        raise _MalformedError
    request_id = value.get("request_id")
    return {
        "kind": kind,
        "provider": _match(value.get("provider"), _PROVIDER),
        "revision_kind": revision_kind,
        "trigger": trigger,
        "request_id": None if request_id is None else _match(request_id, _REQUEST_ID),
    }


def _timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise _MalformedError
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise _MalformedError from exc
    return value


def _pack_reviews(raw: object) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Return the latest fix-verification summary and every adjudication, without free text."""
    if not isinstance(raw, list) or len(raw) > _MAX_REVIEWS:
        raise _MalformedError
    latest: dict[str, object] | None = None
    adjudications: list[dict[str, object]] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            raise _MalformedError
        kind = entry.get("kind")
        if kind == "fix_verification":
            verdicts = entry.get("verdicts")
            if not isinstance(verdicts, list):
                raise _MalformedError
            counts = dict.fromkeys(_VERDICTS, 0)
            for row in verdicts:
                if not isinstance(row, Mapping) or row.get("verdict") not in _VERDICTS:
                    raise _MalformedError
                _match(row.get("issue_id"), _ISSUE)
                counts[str(row["verdict"])] += 1
            latest = {
                "rescan_revision": _match(entry.get("rescan_revision"), _REVISION),
                "recorded_at": _timestamp(entry.get("recorded_at")),
                "verdicts": counts,
            }
        elif kind == "false_positive_adjudication":
            decision = entry.get("decision")
            disposition = entry.get("issue_disposition")
            if decision not in _DECISIONS or disposition not in _DISPOSITIONS:
                raise _MalformedError
            adjudications.append(
                {
                    "issue_id": _match(entry.get("issue_id"), _ISSUE),
                    "decision": decision,
                    "issue_disposition": disposition,
                    "adjudicator": _match(entry.get("adjudicator"), _PRINCIPAL),
                    "decided_at": _timestamp(entry.get("decided_at")),
                }
            )
        else:
            raise _MalformedError
    return latest, adjudications


def _pack(key: object, value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _MalformedError
    pack_id = _match(value.get("pack_id"), _PACK_ID)
    if key != f"{CODE_SECURITY_PACK_STATE_PREFIX}{pack_id}":
        raise _MalformedError
    issues = value.get("issue_ids")
    revoked = value.get("revoked")
    if not isinstance(issues, list) or not isinstance(revoked, bool):
        raise _MalformedError
    for issue in issues:
        _match(issue, _ISSUE)
    verification, adjudications = _pack_reviews(value.get("reviews", []))
    return {
        "pack_id": pack_id,
        "base_commit": _match(value.get("base_commit"), _REVISION),
        "issue_count": len(issues),
        "recorded_at": _timestamp(value.get("recorded_at")),
        "expires_at": _timestamp(value.get("expires_at")),
        "revoked": revoked,
        "latest_verification": verification,
        "adjudications": adjudications,
    }


def code_security_packs_projection(rows: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    """Render remediation-pack records with verdict and adjudication summaries, newest first."""
    packs: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    if len(rows) > _MAX_ITEMS:
        gaps.append({"reason_code": GAP_TRUNCATED})
    for row in rows[:_MAX_ITEMS]:
        try:
            packs.append(_pack(row.get("key"), row.get("value")))
        except _MalformedError:
            gaps.append({"reason_code": GAP_PACK_MALFORMED})
    packs.sort(key=lambda item: (str(item["recorded_at"]), str(item["pack_id"])), reverse=True)
    return {
        "surface": "code-security-packs",
        "available": bool(packs),
        "complete": not gaps,
        "source": "postgresql:state_kv:code-security-pack",
        "packs": packs,
        "gaps": gaps,
    }


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


def _repository(key: object, value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or value.get("kind") != "code-security-repository":
        raise _MalformedError
    alias = _match(value.get("repository_alias"), re.compile(_ALIAS_PATTERN))
    if key != f"{CODE_SECURITY_REPOSITORY_STATE_PREFIX}{alias}":
        raise _MalformedError
    enabled, exposure = value.get("enabled"), value.get("exposure")
    if value.get("provider") != "github" or not isinstance(enabled, bool):
        raise _MalformedError
    if exposure not in _EXPOSURES:
        raise _MalformedError
    return {
        "repository_alias": alias,
        "provider": "github",
        "location": _match(value.get("location"), _LOCATION),
        "default_ref": _match(value.get("default_ref"), _REF),
        "exposure": exposure,
        "enabled": enabled,
        "registered_at": _timestamp(value.get("registered_at")),
    }


def code_security_repositories_projection(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    """Render repositories registered for Console scans, sorted by alias."""
    repositories: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    if len(rows) > _MAX_ITEMS:
        gaps.append({"reason_code": GAP_TRUNCATED})
    for row in rows[:_MAX_ITEMS]:
        try:
            repositories.append(_repository(row.get("key"), row.get("value")))
        except _MalformedError:
            gaps.append({"reason_code": GAP_REPOSITORY_MALFORMED})
    repositories.sort(key=lambda item: str(item["repository_alias"]))
    return {
        "surface": "code-security-repositories",
        "available": True,
        "complete": not gaps,
        "source": "postgresql:state_kv:code-security-repository",
        "repositories": repositories,
        "gaps": gaps,
    }


def _scan_request(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping) or value.get("operation") not in (
        SCAN_REQUEST_OPERATION,
        REPOSITORY_CHANGE_OPERATION,
    ):
        raise _MalformedError
    envelope = value.get("payload")
    body = envelope.get("payload") if isinstance(envelope, Mapping) else None
    if not isinstance(body, Mapping):
        raise _MalformedError
    status = _REQUEST_STATUSES.get(str(value.get("dispatch_status")))
    if status is None:
        raise _MalformedError
    is_change = value.get("operation") == REPOSITORY_CHANGE_OPERATION
    ref = None if is_change else body.get("ref")
    action = body.get("action") if is_change else None
    if is_change and action not in _CHANGE_ACTIONS:
        raise _MalformedError
    location = body.get("location") if action == "register" else None
    request: dict[str, object] = {
        "request_id": _match(value.get("proposal_id"), _REQUEST_ID),
        "kind": "repository_change" if is_change else "scan",
        "action": action,
        "location": None if location is None else _match(location, re.compile(_LOCATION_PATTERN)),
        "repository_alias": _match(body.get("repository_alias"), re.compile(_ALIAS_PATTERN)),
        "ref": None if ref is None else _match(ref, _REF),
        "status": status,
        "accepted_at": _timestamp(value.get("accepted_at")),
        "closed_at": None,
        "rejection_reason": None,
        "result": None,
    }
    if status in ("completed", "rejected"):
        request["closed_at"] = _timestamp(value.get("closed_at"))
    if status == "rejected":
        reason = value.get("rejection_reason")
        if reason not in _REJECTIONS:
            raise _MalformedError
        request["rejection_reason"] = reason
    if status == "completed" and is_change:
        result = value.get("request_result")
        if not isinstance(result, Mapping) or not isinstance(result.get("enabled"), bool):
            raise _MalformedError
        request["result"] = {"enabled": result["enabled"]}
    elif status == "completed":
        result = value.get("request_result")
        if not isinstance(result, Mapping):
            raise _MalformedError
        decision = result.get("decision")
        coverage, published = result.get("coverage_complete"), result.get("published")
        if decision not in ("urgent", "open", "clear", "coverage_incomplete"):
            raise _MalformedError
        if not isinstance(coverage, bool) or not isinstance(published, bool):
            raise _MalformedError
        request["result"] = {
            "revision": _match(result.get("revision"), _REVISION),
            "review_digest": _match(result.get("review_digest"), _DIGEST),
            "decision": decision,
            "issue_count": _count(result.get("issue_count")),
            "coverage_complete": coverage,
            "published": published,
        }
    return request


def code_security_scan_requests_projection(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    """Render Console scan requests and registration changes, newest first, without requesters."""
    requests: list[dict[str, object]] = []
    gaps: list[dict[str, object]] = []
    if len(rows) > _MAX_ITEMS:
        gaps.append({"reason_code": GAP_TRUNCATED})
    for row in rows[:_MAX_ITEMS]:
        try:
            requests.append(_scan_request(row.get("value")))
        except _MalformedError:
            gaps.append({"reason_code": GAP_REQUEST_MALFORMED})
    requests.sort(
        key=lambda item: (str(item["accepted_at"]), str(item["request_id"])), reverse=True
    )
    return {
        "surface": "code-security-scan-requests",
        "available": True,
        "complete": not gaps,
        "source": "postgresql:state_kv:operator-proposal",
        "requests": requests,
        "gaps": gaps,
    }


CODE_SECURITY_OPERATIONS = frozenset(
    {
        "code_security.reviews",
        "code_security.packs",
        "code_security.repositories",
        "code_security.scan_requests",
        "code_security.issues",
        "knowledge.github.sources",
    }
)
_STATE_ROWS_SQL = (
    "SELECT key, value FROM state_kv WHERE key LIKE %s ORDER BY updated_at DESC LIMIT 201"
)
_SCAN_REQUEST_ROWS_SQL = (
    "SELECT key, value FROM state_kv WHERE key LIKE 'operator-proposal:operations:%%' "
    "AND value ->> 'operation' IN (%s, %s) ORDER BY updated_at DESC LIMIT 201"
)
_FetchAll = Callable[[str, tuple[object, ...]], Awaitable[list[dict[str, Any]]]]


async def read_code_security_projection(
    operation: str,
    fetch_all: _FetchAll,
    params: Mapping[str, Sequence[str]] | None = None,
) -> Mapping[str, object]:
    """Read one code-security operation through the runtime reader's bounded ``fetch_all``."""
    if operation == "code_security.issues":
        from fdai_operator_service.code_security_issue_projection import (
            read_code_security_issues,
        )

        return await read_code_security_issues(
            params or {}, fetch_all, CODE_SECURITY_REVIEW_STATE_PREFIX
        )
    if operation == "code_security.packs":
        rows = await fetch_all(_STATE_ROWS_SQL, (f"{CODE_SECURITY_PACK_STATE_PREFIX}%",))
        return code_security_packs_projection(rows)
    if operation in {"code_security.repositories", "knowledge.github.sources"}:
        rows = await fetch_all(_STATE_ROWS_SQL, (f"{CODE_SECURITY_REPOSITORY_STATE_PREFIX}%",))
        if operation == "knowledge.github.sources":
            from fdai_operator_service.knowledge_github_projection import (
                knowledge_github_projection,
            )

            return knowledge_github_projection(rows)
        return code_security_repositories_projection(rows)
    if operation == "code_security.scan_requests":
        rows = await fetch_all(
            _SCAN_REQUEST_ROWS_SQL, (SCAN_REQUEST_OPERATION, REPOSITORY_CHANGE_OPERATION)
        )
        return code_security_scan_requests_projection(rows)
    rows = await fetch_all(_STATE_ROWS_SQL, (f"{CODE_SECURITY_REVIEW_STATE_PREFIX}%",))
    return code_security_reviews_projection(rows)


__all__ = [
    "CODE_SECURITY_OPERATIONS",
    "CODE_SECURITY_REPOSITORY_STATE_PREFIX",
    "REPOSITORY_CHANGE_OPERATION",
    "CodeSecurityRepositoryChangeBody",
    "GAP_REPOSITORY_MALFORMED",
    "GAP_REQUEST_MALFORMED",
    "SCAN_REQUEST_OPERATION",
    "CodeSecurityScanRequestBody",
    "code_security_repositories_projection",
    "code_security_scan_requests_projection",
    "CODE_SECURITY_PACK_STATE_PREFIX",
    "CODE_SECURITY_REVIEW_STATE_PREFIX",
    "GAP_PACK_MALFORMED",
    "code_security_packs_projection",
    "GAP_MALFORMED",
    "GAP_TRUNCATED",
    "code_security_reviews_projection",
    "read_code_security_projection",
]
