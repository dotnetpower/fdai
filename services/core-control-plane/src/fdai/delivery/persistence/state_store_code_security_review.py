"""Durable code-security review summaries over ``StateStore`` for the Operator read view.

One row per ``(repository alias, revision)`` holds the strict review package that Heimdall
publishes: counts, coverage, exposure, and opaque issue ids. It never holds paths, code, symbols,
or scanner text. Rows are immutable: re-recording the same package is a no-op, and a different
package under the same key is refused so a later scan can't silently replace reviewed evidence.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime

from fdai.core.security.code_findings.review_signal import validate_review_package
from fdai.shared.providers.state_store import StateStore

CODE_SECURITY_REVIEW_STATE_PREFIX = "runtime:code-security-review:"


class CodeSecurityReviewConflictError(RuntimeError):
    """A different review package already exists for the same repository revision."""


def code_security_review_state_key(repository_alias: str, revision: str) -> str:
    return f"{CODE_SECURITY_REVIEW_STATE_PREFIX}{repository_alias}:{revision}"


async def record_code_security_review(
    store: StateStore,
    package: Mapping[str, object],
    *,
    recorded_at: datetime | None = None,
) -> bool:
    """Record a validated review package; return ``True`` when a new row was written."""
    validated = validate_review_package(package)
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
    if json.dumps(stored, sort_keys=True) == json.dumps(validated, sort_keys=True):
        return False
    raise CodeSecurityReviewConflictError(
        f"a different review is already recorded for {validated['repository_alias']}"
        f"@{validated['revision']}"
    )


async def record_review_from_environment(package: Mapping[str, object]) -> bool:
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
        return await record_code_security_review(store, package)
    finally:
        await store.aclose()


__all__ = [
    "CODE_SECURITY_REVIEW_STATE_PREFIX",
    "CodeSecurityReviewConflictError",
    "code_security_review_state_key",
    "record_code_security_review",
    "record_review_from_environment",
]
