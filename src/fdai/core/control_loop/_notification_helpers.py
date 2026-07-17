"""Best-effort notification and HIL delivery for the control loop."""

from __future__ import annotations

import logging

from fdai.core.control_loop.models import ControlLoopOutcome
from fdai.core.hil_resume import HilResumeCoordinator
from fdai.core.notifications.renderer import default_catalog
from fdai.core.notifications.router import NotificationRouter
from fdai.shared.contracts.models import Action, Event, Mode, Rule
from fdai.shared.providers.notifications.base import (
    NotificationMessage,
    Severity,
    TrustTier,
)


async def notify_decision(
    router: NotificationRouter | None,
    logger: logging.Logger,
    *,
    event: Event,
    correlation_id: str,
    overall: ControlLoopOutcome,
    decision_word: str,
    resource_type: str | None,
    citing_rule_ids: tuple[str, ...],
) -> None:
    if router is None:
        return
    severity = {
        ControlLoopOutcome.EXECUTED: Severity.INFO,
        ControlLoopOutcome.HIL: Severity.WARN,
        ControlLoopOutcome.DENIED: Severity.ERROR,
    }.get(overall)
    if severity is None:
        return
    notify_params = {
        "decision": decision_word,
        "resource_title": resource_type or "unknown",
        "resource_body": resource_type or "n/a",
        "rules": ", ".join(citing_rule_ids) if citing_rule_ids else "n/a",
        "mode": Mode.SHADOW.value,
    }
    title, body_markdown = default_catalog().render("decision", notify_params, "en")
    message = NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id=correlation_id,
        title=title,
        body_markdown=body_markdown,
        template_key="decision",
        params=notify_params,
        severity=severity,
        metadata={
            "outcome": overall.value,
            "decision": decision_word,
            "event_id": str(event.event_id),
        },
    )
    try:
        await router.dispatch(message)
    except Exception:  # noqa: BLE001 - notification never changes an audited decision
        logger.warning(
            "notify_decision_dispatch_failed",
            extra={"correlation_id": correlation_id, "outcome": overall.value},
            exc_info=True,
        )


async def request_hil_approval(
    coordinator: HilResumeCoordinator | None,
    logger: logging.Logger,
    *,
    action: Action,
    rule: Rule,
    correlation_id: str,
    submitter_oid: str,
) -> None:
    if coordinator is None:
        return
    try:
        await coordinator.request_approval(
            action=action,
            rule=rule,
            submitter_oid=submitter_oid,
            correlation_id=correlation_id,
        )
    except Exception:  # noqa: BLE001 - a failed park remains fail-closed
        logger.warning(
            "hil_request_approval_failed",
            extra={"correlation_id": correlation_id, "action_type": action.action_type},
            exc_info=True,
        )
