"""Notification planning for code-security review packages.

The planner turns one validated review package into notification messages:

- an A2 operational alert when urgent (P0) or known-exploited issues exist;
- an A2 coverage alert when the scan did not report complete coverage;
- an A4 daily digest whenever issues are open or coverage is incomplete.

Messages carry repository aliases, revisions, and counts only. They never include code, file
paths, symbols, or scanner text, because notification channels leave the trust boundary. When
the routing matrix lacks a code-security category the planner refuses instead of letting the
router fall back to the A1 approval route.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from fdai.core.notifications.renderer import NotificationCatalog
from fdai.core.security.code_findings.review_signal import (
    review_decision,
    validate_review_package,
)
from fdai.shared.providers.notifications.base import NotificationMessage, Severity, TrustTier

ALERT_CATEGORY = "code_security_operational_alert"
DIGEST_CATEGORY = "digest_code_security_findings_daily"


class NotificationPlanError(ValueError):
    """Raised when the routing matrix cannot carry code-security notifications."""


def _params(package: Mapping[str, object]) -> dict[str, str]:
    priority = package["by_priority"]
    severity = package["by_severity"]
    confidence = package["by_confidence"]
    if not (
        isinstance(priority, Mapping)
        and isinstance(severity, Mapping)
        and isinstance(confidence, Mapping)
    ):
        raise NotificationPlanError("review package counts are malformed")
    return {
        "repository": str(package["repository_alias"]),
        "revision": str(package["revision"])[:12],
        "total": str(package["issue_count"]),
        "urgent": str(priority["P0"]),
        "p0": str(priority["P0"]),
        "p1": str(priority["P1"]),
        "p2": str(priority["P2"]),
        "p3": str(priority["P3"]),
        "p4": str(priority["P4"]),
        "critical": str(severity["critical"]),
        "high": str(severity["high"]),
        "medium": str(severity["medium"]),
        "low": str(severity["low"]),
        "undetermined": str(severity["undetermined"]),
        "hypothesis": str(confidence["hypothesis"]),
        "kev": str(package["known_exploited_count"]),
        "exposure": str(package["exposure"]),
        "coverage": "yes" if package["coverage_complete"] else "no",
    }


def _message(
    category: str,
    tier: TrustTier,
    template_key: str,
    params: dict[str, str],
    severity: Severity,
    correlation_id: str,
    catalog: NotificationCatalog,
) -> NotificationMessage:
    title, body = catalog.render(template_key, params, "en")
    return NotificationMessage(
        category=category,
        trust_tier=tier,
        correlation_id=correlation_id,
        title=title,
        body_markdown=body,
        severity=severity,
        metadata={"source": "code_security", "repository": params["repository"]},
        template_key=template_key,
        params=params,
    )


def plan_code_security_notifications(
    raw_package: Mapping[str, object],
    *,
    routes: Collection[str],
    catalog: NotificationCatalog | None = None,
) -> tuple[NotificationMessage, ...]:
    """Return the messages to dispatch for one review package.

    ``routes`` are the category names the deployment's notification matrix defines.
    """
    missing = [c for c in (ALERT_CATEGORY, DIGEST_CATEGORY) if c not in routes]
    if missing:
        raise NotificationPlanError(f"notification matrix lacks {', '.join(missing)}")
    package = validate_review_package(raw_package)
    catalog = catalog or NotificationCatalog.load_default()
    params = _params(package)
    correlation = f"code-security:{params['repository']}:{package['review_digest']}"
    decision = review_decision(package)
    messages: list[NotificationMessage] = []
    if decision == "coverage_incomplete":
        messages.append(
            _message(
                ALERT_CATEGORY,
                TrustTier.A2_OPERATIONAL_ALERT,
                "code_security_coverage_alert",
                params,
                Severity.WARN,
                correlation + ":coverage",
                catalog,
            )
        )
    if params["urgent"] != "0" or params["kev"] != "0":
        messages.append(
            _message(
                ALERT_CATEGORY,
                TrustTier.A2_OPERATIONAL_ALERT,
                "code_security_alert",
                params,
                Severity.ERROR,
                correlation + ":urgent",
                catalog,
            )
        )
    if package["issue_count"] or decision == "coverage_incomplete":
        messages.append(
            _message(
                DIGEST_CATEGORY,
                TrustTier.A4_DIGEST,
                "code_security_digest",
                params,
                Severity.INFO,
                correlation + ":digest",
                catalog,
            )
        )
    return tuple(messages)


__all__ = [
    "ALERT_CATEGORY",
    "DIGEST_CATEGORY",
    "NotificationPlanError",
    "plan_code_security_notifications",
]
