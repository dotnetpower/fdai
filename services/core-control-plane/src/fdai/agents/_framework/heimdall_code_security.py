"""Code-security review behavior for Heimdall.

Heimdall is the accountable observer for source-code security: scan reviews are observations of
a repository revision, so they travel on Heimdall's owned ``object.drift`` topic, where Forseti
judges them and Saga audits the verdict. Heimdall never scans, edits code, or grants authority;
scanners are workers that hand Heimdall a strict, no-authority review package.

For conversation, Heimdall reads the recorded reviews back from the state store, because the scan
worker publishes from its own process. The facts are bounded: the newest review per repository,
with decision, counts, coverage, and source kind, never paths, code, or scanner text.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.bus import PantheonBus
from fdai.core.security.code_findings.review_signal import (
    CodeSecurityReviewError,
    review_decision,
    validate_review_package,
)
from fdai.shared.providers.code_security import CodeSecurityDriftProjector
from fdai.shared.providers.state_store import StateStore

CODE_SECURITY_REVIEW_STATE_PREFIX = "runtime:code-security-review:"
DRIFT_TOOL_ID = "read_drift_status"
"""Code-security reviews are Drift, so Heimdall's drift tool carries their facts."""
_MAX_REVIEW_ROWS = 50
_MAX_REPOSITORIES = 10


class HeimdallCodeSecurityMixin:
    """Publish code-security review drift and answer from recorded reviews."""

    bus: PantheonBus | None
    _code_security_drift_projector: CodeSecurityDriftProjector | None
    _state_store: StateStore | None

    if TYPE_CHECKING:

        def record_behavior(self, key: str, count: int = 1) -> None: ...

    async def publish_code_security_drift(self, package: Mapping[str, object]) -> bool:
        """Publish one strict no-authority code-security review for governed review."""

        if self._code_security_drift_projector is None:
            self.record_behavior("code_security_drift:projector_unavailable")
            return False
        payload = self._code_security_drift_projector(package)
        self.record_behavior(f"code_security_drift:{payload['decision']}")
        if self.bus is None:
            return False
        await self.bus.publish("Heimdall", "object.drift", payload)
        return True

    async def code_security_facts(self) -> dict[str, Any] | None:
        """Return bounded facts about recorded reviews, or ``None`` without a state store.

        Malformed rows are counted as withheld instead of being rendered. ``truncated`` is true
        when the bounded read may have missed older rows.
        """
        if self._state_store is None:
            return None
        rows = await self._state_store.read_states(
            CODE_SECURITY_REVIEW_STATE_PREFIX, limit=_MAX_REVIEW_ROWS
        )
        latest: dict[str, dict[str, Any]] = {}
        withheld = 0
        for row in rows:
            package, recorded_at = row.get("package"), row.get("recorded_at")
            try:
                if not isinstance(package, Mapping) or not isinstance(recorded_at, str):
                    raise CodeSecurityReviewError("review row is malformed")
                review = validate_review_package(package)
            except CodeSecurityReviewError:
                withheld += 1
                continue
            alias = str(review["repository_alias"])
            if alias in latest and latest[alias]["recorded_at"] >= recorded_at:
                continue
            source = review.get("source")
            latest[alias] = {
                "repository_alias": alias,
                "revision": str(review["revision"])[:12],
                "decision": review_decision(review),
                "issue_count": review["issue_count"],
                "coverage_complete": review["coverage_complete"],
                "source_kind": source.get("kind") if isinstance(source, Mapping) else None,
                "recorded_at": recorded_at,
            }
        ordered = sorted(latest.values(), key=lambda item: item["recorded_at"], reverse=True)
        return {
            "code_security_reviews_read": len(rows) - withheld,
            "code_security_latest_decisions": ordered[:_MAX_REPOSITORIES],
            "code_security_reviews_withheld": withheld,
            "code_security_reviews_truncated": len(rows) >= _MAX_REVIEW_ROWS,
        }


def code_security_statement(facts: Mapping[str, Any]) -> str:
    """Summarize recorded reviews deterministically; Bragi localizes the final answer."""
    decisions = facts.get("code_security_latest_decisions") or []
    if not decisions:
        return "No code-security scan review has been recorded"
    urgent = sum(1 for item in decisions if item["decision"] == "urgent")
    incomplete = sum(1 for item in decisions if item["decision"] == "coverage_incomplete")
    return (
        f"Latest code-security reviews cover {len(decisions)} repositories: {urgent} urgent and "
        f"{incomplete} with incomplete coverage"
    )


__all__ = [
    "CODE_SECURITY_REVIEW_STATE_PREFIX",
    "DRIFT_TOOL_ID",
    "HeimdallCodeSecurityMixin",
    "code_security_statement",
]
