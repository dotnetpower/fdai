"""Durable code-security review summaries over ``StateStore`` for the Operator read view.

One row per ``(repository alias, revision)`` holds the strict review package that Heimdall
publishes: counts, coverage, exposure, and opaque issue ids. It never holds paths, code, symbols,
or scanner text. Rows are immutable: re-recording the same findings is a no-op even when the
source or trigger differs, and different findings under the same key are refused so a later scan
can't silently replace reviewed evidence.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from fdai.core.security.code_findings.issue_summary import (
    MAX_ISSUE_SUMMARIES,
    validate_issue_summary,
)
from fdai.core.security.code_findings.review_signal import validate_review_package
from fdai.shared.providers.state_store import StateStore

CODE_SECURITY_REVIEW_STATE_PREFIX = "runtime:code-security-review:"
CODE_SECURITY_ISSUES_STATE_PREFIX = "runtime:code-security-issues:"


class CodeSecurityReviewConflictError(RuntimeError):
    """A different review package already exists for the same repository revision."""


def code_security_review_state_key(repository_alias: str, revision: str) -> str:
    return f"{CODE_SECURITY_REVIEW_STATE_PREFIX}{repository_alias}:{revision}"


def code_security_issues_state_key(repository_alias: str, revision: str) -> str:
    return f"{CODE_SECURITY_ISSUES_STATE_PREFIX}{repository_alias}:{revision}"


async def record_code_security_review(
    store: StateStore,
    package: Mapping[str, object],
    *,
    recorded_at: datetime | None = None,
    issues: Sequence[Mapping[str, object]] | None = None,
    issues_truncated: bool = False,
) -> bool:
    """Record a validated review package; return ``True`` when a new row was written.

    ``issues`` are bounded issue summaries for the Console. They are validated and written once
    per revision next to the review, bound by its digest; existing summaries are never replaced.
    """
    validated = validate_review_package(package)
    if issues is not None:
        if len(issues) > MAX_ISSUE_SUMMARIES:
            raise ValueError("too many issue summaries for one review")
        summaries = [validate_issue_summary(item) for item in issues]
        await store.write_state_if_absent(
            code_security_issues_state_key(
                str(validated["repository_alias"]), str(validated["revision"])
            ),
            {
                "review_digest": validated["review_digest"],
                "issues": summaries,
                "truncated": issues_truncated,
            },
        )
    key = code_security_review_state_key(
        str(validated["repository_alias"]), str(validated["revision"])
    )
    row = {
        "package": validated,
        "recorded_at": (recorded_at or datetime.now(UTC)).isoformat(),
    }
    if await store.write_state_if_absent(key, row):
        return True
    existing = await store.read_state(key)
    stored = existing.get("package") if existing else None
    if isinstance(stored, Mapping) and _findings(stored) == _findings(validated):
        return False
    raise CodeSecurityReviewConflictError(
        f"a different review is already recorded for {validated['repository_alias']}"
        f"@{validated['revision']}"
    )


_PROVENANCE_KEYS = frozenset({"schema_version", "source", "producers"})


def _findings(package: Mapping[str, object]) -> str:
    """Compare findings only, so the same revision scanned by CLI and Console is a duplicate."""
    return json.dumps(
        {key: value for key, value in package.items() if key not in _PROVENANCE_KEYS},
        sort_keys=True,
    )


async def record_review_from_environment(
    package: Mapping[str, object],
    *,
    issues: Sequence[Mapping[str, object]] | None = None,
    issues_truncated: bool = False,
) -> bool:
    """Record a review in the PostgreSQL state store named by ``FDAI_STATE_STORE_DSN``.

    The DSN is read from the environment only, never from arguments, so it can't leak through
    command lines or task output.
    """
    from fdai.delivery.persistence.postgres import PostgresStateStore, PostgresStateStoreConfig

    dsn = (
        os.environ.get("FDAI_STATE_STORE_DSN", "").strip()
        or os.environ.get("FDAI_DATABASE_URL", "").strip()
    )
    if not dsn:
        raise ValueError("--record-state requires FDAI_STATE_STORE_DSN in the environment")
    store = PostgresStateStore(config=PostgresStateStoreConfig(dsn=dsn))
    try:
        return await record_code_security_review(
            store, package, issues=issues, issues_truncated=issues_truncated
        )
    finally:
        await store.aclose()


__all__ = [
    "CODE_SECURITY_ISSUES_STATE_PREFIX",
    "CODE_SECURITY_REVIEW_STATE_PREFIX",
    "CodeSecurityReviewConflictError",
    "code_security_issues_state_key",
    "code_security_review_state_key",
    "record_code_security_review",
    "record_review_from_environment",
]
