"""Best-effort notification and HIL delivery for the control loop."""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from fdai.core.control_loop.models import ControlLoopOutcome
from fdai.core.hil_resume import HilResumeCoordinator, RequestApprovalResult, RequestOutcome
from fdai.core.hil_resume.subject_index import subject_key
from fdai.core.notifications.renderer import default_catalog
from fdai.core.notifications.router import NotificationRouter
from fdai.shared.contracts.models import Action, Event, Mode, Rule
from fdai.shared.providers.notifications.base import (
    NotificationMessage,
    Severity,
    TrustTier,
)

_ACTIVE_GATE_SUBJECT_CAP = 4096
_SUPPRESSED_HIL_OUTCOMES = frozenset(
    {
        RequestOutcome.ALREADY_OPEN,
        RequestOutcome.ALREADY_PARKED,
        RequestOutcome.REJECTED_SUBJECT,
        RequestOutcome.PARKED_DEFERRED,
    }
)


def active_gate_subjects(
    host: Any,
) -> OrderedDict[tuple[str, str], tuple[str, str]]:
    """Return the bounded per-host map of active (resource_id, rule_id) gate subjects."""
    subjects = getattr(host, "_active_gate_subjects_map", None)
    if not isinstance(subjects, OrderedDict):
        subjects = OrderedDict()
        host._active_gate_subjects_map = subjects
    return subjects


def remember_gate_subject(
    subjects: OrderedDict[tuple[str, str], tuple[str, str]],
    key: tuple[str, str],
    value: tuple[str, str],
) -> bool:
    """Record the latest (subject_key, gate_decision) and return True if unchanged."""
    repeated = subjects.get(key) == value
    subjects[key] = value
    subjects.move_to_end(key)
    while len(subjects) > _ACTIVE_GATE_SUBJECT_CAP:
        subjects.popitem(last=False)
    return repeated


def clear_resource_gate_subjects(
    subjects: OrderedDict[tuple[str, str], tuple[str, str]],
    resource_id: str,
) -> None:
    """Clear remembered gate subjects for a resource that became compliant."""
    for key in [item for item in subjects if item[0] == resource_id]:
        subjects.pop(key, None)


def build_gate_stage_detail(
    *,
    rule_id: str,
    action_type: str,
    gate_decision: str,
    mode: str,
    subject: str | None = None,
    repeated_observation: bool = False,
    hil_result: object = None,
    authorization_status: str | None = None,
    tier: str | None = None,
) -> dict[str, Any]:
    """Build StageName.GATE detail with deduplication metadata."""
    detail: dict[str, Any] = {
        "action_type": action_type,
        "gate_decision": gate_decision,
        "mode": mode,
    }
    if tier is not None:
        detail["tier"] = tier
    if rule_id:
        detail["rule_id"] = rule_id
    if authorization_status is not None:
        detail["authorization_status"] = authorization_status
    if subject is not None:
        detail["subject_key"] = subject
    if repeated_observation:
        detail["repeated_observation"] = True
    if hasattr(hil_result, "outcome") and hasattr(hil_result, "approval_id"):
        detail["hil_request_outcome"] = str(hil_result.outcome.value)
        detail["approval_id"] = str(hil_result.approval_id)
    return detail


async def request_unified_hil_approval(
    host: Any,
    *,
    action: Action,
    rule: Rule,
    unified: Any,
    correlation_id: str,
    event: Event | None = None,
    reopen_on_expiry: bool = True,
) -> Any:
    """Park a unified-risk-gated HIL action when the coordinator is configured."""
    if not unified.requires_hil or unified.is_denied or host._hil_resume_coordinator is None:
        return None
    approval_profile = (
        unified.authority.approval_profile.as_audit_dict()
        if unified.authority is not None and unified.authority.approval_profile is not None
        else None
    )
    operator_policy = (
        unified.authority.operator_policy.as_audit_dict()
        if unified.authority is not None and unified.authority.operator_policy is not None
        else None
    )
    original_quorum = (
        unified.authority.original_quorum if unified.authority is not None else unified.quorum
    )
    extra_kwargs: dict[str, Any] = {}
    if event is not None:
        extra_kwargs["event"] = event
    if not reopen_on_expiry:
        extra_kwargs["reopen_on_expiry"] = False
    return await host._request_hil_approval(
        action=action,
        rule=rule,
        correlation_id=correlation_id,
        approval_profile=approval_profile,
        operator_policy=operator_policy,
        original_quorum_required=original_quorum,
        effective_quorum_required=unified.quorum,
        **extra_kwargs,
    )


def gate_subject_key(
    *,
    action: Action,
    rule: Rule,
    submitter_oid: str = "system:control-loop",
    development_authority: Mapping[str, Any] | None = None,
    operator_policy: Mapping[str, Any] | None = None,
) -> str:
    """Return the stable subject identity for one gated action/rule proposal."""
    return subject_key(
        action=action,
        rule=rule,
        submitter_oid=submitter_oid,
        development_digest=(
            str(development_authority["block_digest"])
            if development_authority is not None and "block_digest" in development_authority
            else None
        ),
        operator_policy_digest=(
            str(operator_policy["policy_digest"])
            if operator_policy is not None and "policy_digest" in operator_policy
            else None
        ),
    )


def is_hil_request_suppressed(result: object) -> bool:
    """Return True when a HIL request was deduplicated, deferred, or kept closed."""
    return isinstance(result, RequestApprovalResult) and result.outcome in _SUPPRESSED_HIL_OUTCOMES


def _event_resource_ref(event: Event) -> str | None:
    if event.resource_ref:
        return event.resource_ref
    resource = event.payload.get("resource")
    if isinstance(resource, Mapping):
        for key in ("resource_id", "id"):
            val = resource.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    val = event.payload.get("resource_id")
    return val.strip() if isinstance(val, str) and val.strip() else None


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
    audit_id: str | None = None
    target_resource = _event_resource_ref(event)
    if event.correlation_id is None and target_resource and correlation_id == str(event.event_id):
        material = (
            f"{event.event_type}\0{target_resource}\0{overall.value}\0"
            f"{decision_word}\0{','.join(sorted(citing_rule_ids))}"
        ).encode()
        audit_id = f"control-loop-decision:{hashlib.sha256(material).hexdigest()}"
    message = NotificationMessage(
        category="operational_alert",
        trust_tier=TrustTier.A2_OPERATIONAL_ALERT,
        correlation_id=correlation_id,
        audit_id=audit_id,
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
    event: Event | None = None,
    development_authority: Mapping[str, Any] | None = None,
    approval_profile: Mapping[str, Any] | None = None,
    operator_policy: Mapping[str, Any] | None = None,
    original_quorum_required: int | None = None,
    effective_quorum_required: int | None = None,
    reopen_on_expiry: bool = True,
) -> RequestApprovalResult | None:
    if coordinator is None:
        return None
    try:
        extra_kwargs: dict[str, Any] = {}
        if not reopen_on_expiry and isinstance(coordinator, HilResumeCoordinator):
            extra_kwargs["reopen_on_expiry"] = False
        return await coordinator.request_approval(
            action=action,
            rule=rule,
            submitter_oid=submitter_oid,
            correlation_id=correlation_id,
            development_authority=development_authority,
            approval_profile=approval_profile,
            operator_policy=operator_policy,
            original_quorum_required=original_quorum_required,
            effective_quorum_required=effective_quorum_required,
            escalation_context=(
                {"finding_class": event.event_type, "impact": action.blast_radius.scope.value}
                if event is not None
                else None
            ),
            **extra_kwargs,
        )
    except Exception:  # noqa: BLE001 - a failed park remains fail-closed
        logger.warning(
            "hil_request_approval_failed",
            extra={"correlation_id": correlation_id, "action_type": action.action_type},
            exc_info=True,
        )
        return None
