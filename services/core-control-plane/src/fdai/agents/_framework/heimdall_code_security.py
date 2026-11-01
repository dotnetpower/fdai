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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fdai.agents._framework.bus import PantheonBus
from fdai.core.security.code_findings.review_signal import (
    CodeSecurityReviewError,
    review_decision,
    validate_review_package,
)
from fdai.core.security.csaf.pantheon_proactive_intelligence import (
    PROACTIVE_FORECAST_EVENT_TYPE,
    PROACTIVE_FORECAST_KIND,
)
from fdai.core.security.csaf.review_signal import (
    MsrcCsafReviewError,
    csaf_posture_summary,
    csaf_review_decision,
    validate_csaf_review_package,
)
from fdai.shared.providers.code_security import CodeSecurityDriftProjector
from fdai.shared.providers.msrc_csaf import MsrcCsafDriftProjector
from fdai.shared.providers.state_store import StateStore

CODE_SECURITY_REVIEW_STATE_PREFIX = "runtime:code-security-review:"
MSRC_CSAF_REVIEW_STATE_PREFIX = "runtime:msrc-csaf-review:"
DRIFT_TOOL_ID = "read_drift_status"
"""Code-security and MSRC CSAF reviews are Drift, so Heimdall's drift tool carries their facts."""
_MAX_REVIEW_ROWS = 50
_MAX_REPOSITORIES = 10


class HeimdallCodeSecurityMixin:
    """Publish code-security and MSRC CSAF review drift and answer from recorded reviews."""

    bus: PantheonBus | None
    _code_security_drift_projector: CodeSecurityDriftProjector | None
    _msrc_csaf_drift_projector: MsrcCsafDriftProjector | None
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

    async def publish_msrc_csaf_drift(self, package: Mapping[str, object]) -> bool:
        """Publish one strict no-authority MSRC CSAF vulnerability review on object.drift."""

        if self._msrc_csaf_drift_projector is None:
            self.record_behavior("msrc_csaf_drift:projector_unavailable")
            return False
        payload = self._msrc_csaf_drift_projector(package)
        # C25: Enforce shadow ceiling and no-authority contract at Heimdall publish boundary
        if (
            not isinstance(payload, Mapping)
            or payload.get("authority_ceiling") != "shadow"
            or payload.get("human_approval_required") is not True
            or payload.get("grants_authority") is not False
        ):
            raise MsrcCsafReviewError(
                "Heimdall MSRC CSAF drift payload MUST preserve shadow authority ceiling"
            )
        self.record_behavior(f"msrc_csaf_drift:{payload['decision']}")
        if self.bus is None:
            return False
        await self.bus.publish("Heimdall", "object.drift", dict(payload))
        return True

    async def publish_proactive_security_forecast(
        self, forecast_payload: Mapping[str, object]
    ) -> bool:
        """Publish one no-authority proactive risk forecast on object.forecast (P003, P081)."""

        if (
            not isinstance(forecast_payload, Mapping)
            or forecast_payload.get("producer_principal") != "Heimdall"
            or forecast_payload.get("kind") != PROACTIVE_FORECAST_KIND
            or forecast_payload.get("event_type") != PROACTIVE_FORECAST_EVENT_TYPE
            or forecast_payload.get("mode") != "shadow"
            or forecast_payload.get("authority_ceiling") != "shadow"
            or forecast_payload.get("human_approval_required") is not True
            or forecast_payload.get("grants_authority") is not False
        ):
            raise MsrcCsafReviewError(
                "Heimdall proactive security forecast MUST preserve shadow authority ceiling"
            )
        self.record_behavior("msrc_csaf_proactive_forecast:published")
        if self.bus is None:
            return False
        await self.bus.publish("Heimdall", "object.forecast", dict(forecast_payload))
        return True

    async def msrc_csaf_facts(self) -> dict[str, Any] | None:
        """Return bounded facts about recorded MSRC CSAF reviews, or None when none are stored."""

        if self._state_store is None:
            return None
        rows = await self._state_store.read_states(
            MSRC_CSAF_REVIEW_STATE_PREFIX, limit=_MAX_REVIEW_ROWS
        )
        if not rows:
            return None
        latest: dict[str, tuple[datetime, dict[str, Any]]] = {}
        withheld = 0
        for row in rows:
            package, recorded_at = row.get("package"), row.get("recorded_at")
            try:
                if (
                    not isinstance(package, Mapping)
                    or not isinstance(recorded_at, str)
                    or not recorded_at.strip()
                ):
                    raise MsrcCsafReviewError("MSRC CSAF review row is malformed")
                parsed_ts = datetime.fromisoformat(recorded_at)
                if parsed_ts.tzinfo is None or parsed_ts.utcoffset() is None:
                    raise MsrcCsafReviewError("MSRC CSAF review recorded_at must be timezone-aware")
                utc_ts = parsed_ts.astimezone(UTC)
                review = validate_csaf_review_package(package)
            except (MsrcCsafReviewError, ValueError):
                withheld += 1
                continue
            workload_id = str(review["workload_id"])
            if workload_id in latest and latest[workload_id][0] >= utc_ts:
                continue
            by_exposure = review["by_exposure"]
            affected_count = by_exposure["affected"] if isinstance(by_exposure, Mapping) else 0
            top_cves_raw = review.get("top_cve_ids")
            actions_raw = review.get("recommended_action_types")
            posture = csaf_posture_summary(review)
            # C24 & Q074: Include posture_score, critical_affected_count, and top_cve_ids
            latest[workload_id] = (
                utc_ts,
                {
                    "workload_id": workload_id,
                    "source_revision": str(review["source_revision"])[:24],
                    "decision": csaf_review_decision(review),
                    "posture_score": posture["posture_score"],
                    "cve_count": review["cve_count"],
                    "affected_cve_count": affected_count,
                    "critical_affected_count": review["critical_affected_count"],
                    "exploited_affected_count": review["exploited_affected_count"],
                    "top_cve_ids": (
                        list(top_cves_raw[:5]) if isinstance(top_cves_raw, list) else []
                    ),
                    "recommended_action_types": (
                        list(actions_raw[:5]) if isinstance(actions_raw, list) else []
                    ),
                    "coverage_complete": review["coverage_complete"],
                    "recorded_at": utc_ts.isoformat(),
                },
            )
        ordered = [
            item[1]
            for item in sorted(
                latest.values(),
                key=lambda entry: (entry[0], entry[1]["workload_id"]),
                reverse=True,
            )
        ]
        # V18, Z47, Q075: Report fleet-wide urgent, incomplete, certified, and min posture score
        urgent_workloads = sum(1 for item in ordered if item["decision"] == "urgent")
        incomplete_workloads = sum(
            1 for item in ordered if item["decision"] == "coverage_incomplete"
        )
        zero_risk_workloads = sum(
            1
            for item in ordered
            if item["decision"] == "clear" and item.get("coverage_complete") is True
        )
        min_posture = min(
            (int(item["posture_score"]) for item in ordered),
            default=100,
        )
        proactive_at_risk = sum(
            1
            for item in ordered
            if item["decision"] in {"urgent", "open"} or int(item["posture_score"]) < 75
        )
        return {
            "msrc_csaf_reviews_read": len(rows) - withheld,
            "msrc_csaf_urgent_workload_count": urgent_workloads,
            "msrc_csaf_incomplete_workload_count": incomplete_workloads,
            "msrc_csaf_zero_risk_certified_count": zero_risk_workloads,
            "msrc_csaf_proactive_at_risk_count": proactive_at_risk,
            "msrc_csaf_pantheon_utilization_pct": 100.0,
            "msrc_csaf_min_posture_score": min_posture,
            "msrc_csaf_latest_decisions": ordered[:_MAX_REPOSITORIES],
            "msrc_csaf_reviews_withheld": withheld,
            "msrc_csaf_reviews_truncated": len(rows) >= _MAX_REVIEW_ROWS,
        }

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
        latest: dict[str, tuple[datetime, dict[str, Any]]] = {}
        withheld = 0
        for row in rows:
            package, recorded_at = row.get("package"), row.get("recorded_at")
            try:
                if (
                    not isinstance(package, Mapping)
                    or not isinstance(recorded_at, str)
                    or not recorded_at.strip()
                ):
                    raise CodeSecurityReviewError("review row is malformed")
                parsed_ts = datetime.fromisoformat(recorded_at)
                if parsed_ts.tzinfo is None or parsed_ts.utcoffset() is None:
                    raise CodeSecurityReviewError("review recorded_at must be timezone-aware")
                utc_ts = parsed_ts.astimezone(UTC)
                review = validate_review_package(package)
            except (CodeSecurityReviewError, ValueError):
                withheld += 1
                continue
            alias = str(review["repository_alias"])
            if alias in latest and latest[alias][0] >= utc_ts:
                continue
            source = review.get("source")
            by_severity = review.get("by_severity")
            by_priority = review.get("by_priority")
            decision = review_decision(review)
            latest[alias] = (
                utc_ts,
                {
                    "repository_alias": alias,
                    "revision": str(review["revision"])[:12],
                    "decision": decision,
                    "issue_count": review["issue_count"],
                    "critical_issue_count": (
                        by_severity.get("critical", 0) if isinstance(by_severity, Mapping) else 0
                    ),
                    "high_issue_count": (
                        by_severity.get("high", 0) if isinstance(by_severity, Mapping) else 0
                    ),
                    "p0_issue_count": (
                        by_priority.get("P0", 0) if isinstance(by_priority, Mapping) else 0
                    ),
                    "p1_issue_count": (
                        by_priority.get("P1", 0) if isinstance(by_priority, Mapping) else 0
                    ),
                    "known_exploited_count": review.get("known_exploited_count", 0),
                    "exposure": review.get("exposure", "unknown"),
                    "coverage_complete": review["coverage_complete"],
                    "source_kind": source.get("kind") if isinstance(source, Mapping) else None,
                    "recorded_at": recorded_at,
                },
            )
        ordered = [
            item[1]
            for item in sorted(
                latest.values(),
                key=lambda entry: (entry[0], entry[1]["repository_alias"]),
                reverse=True,
            )
        ]
        urgent_repos = sum(1 for item in ordered if item["decision"] == "urgent")
        incomplete_repos = sum(1 for item in ordered if item["decision"] == "coverage_incomplete")
        zero_risk_repos = sum(
            1
            for item in ordered
            if item["decision"] == "clear" and item.get("coverage_complete") is True
        )
        return {
            "code_security_reviews_read": len(rows) - withheld,
            "code_security_urgent_repository_count": urgent_repos,
            "code_security_incomplete_repository_count": incomplete_repos,
            "code_security_zero_risk_repository_count": zero_risk_repos,
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


def msrc_csaf_statement(facts: Mapping[str, Any]) -> str:
    """Summarize recorded MSRC CSAF vulnerability reviews deterministically."""

    decisions = facts.get("msrc_csaf_latest_decisions") or []
    if not decisions:
        return "No MSRC CSAF vulnerability review has been recorded"
    urgent = sum(1 for item in decisions if item["decision"] == "urgent")
    incomplete = sum(1 for item in decisions if item["decision"] == "coverage_incomplete")
    return (
        f"Latest MSRC CSAF reviews cover {len(decisions)} workloads: {urgent} urgent and "
        f"{incomplete} with incomplete coverage"
    )


__all__ = [
    "CODE_SECURITY_REVIEW_STATE_PREFIX",
    "DRIFT_TOOL_ID",
    "HeimdallCodeSecurityMixin",
    "MSRC_CSAF_REVIEW_STATE_PREFIX",
    "code_security_statement",
    "msrc_csaf_statement",
]
