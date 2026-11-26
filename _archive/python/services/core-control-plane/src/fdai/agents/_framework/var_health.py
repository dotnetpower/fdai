"""Health projection helpers for Var."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

_APPROVAL_SLA_SECONDS = 24 * 60 * 60


def ratio_kpi(numerator: int, denominator: int, *, unit: str = "ratio") -> dict[str, object]:
    if denominator <= 0:
        return {
            "value": None,
            "evidence_state": "insufficient_sample",
            "numerator": numerator,
            "denominator": denominator,
            "unit": unit,
        }
    return {
        "value": numerator / denominator,
        "evidence_state": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
    }


def health(host: Any) -> dict[str, Any]:
    behavior = host.behavior_snapshot()
    pending_tickets = tuple(host._pending.values())
    now = host._clock()
    oldest_pending_age = _oldest_pending_ticket_age_seconds(pending_tickets, now=now)
    pending_final_approvals = sum(
        1 for key in host._final_approvals if key not in host._published_approvals
    )
    approved = int(behavior.get("approved", 0) or 0)
    rejected = int(behavior.get("rejected", 0) or 0)
    final_decisions = approved + rejected
    expired = int(behavior.get("approval:expired", 0) or 0)
    repeated_escalations = len(host._blocked_attempts)
    sla_breaches = 0
    if oldest_pending_age is not None:
        for ticket in pending_tickets:
            age_seconds = _ticket_age_seconds(ticket, now=now)
            if age_seconds is not None and age_seconds > _APPROVAL_SLA_SECONDS:
                sla_breaches += 1
    unauthorized = int(behavior.get("approver_unauthorized", 0) or 0)
    blocked_self = int(behavior.get("self_approval_blocked", 0) or 0)
    blocked_double = int(behavior.get("double_approval_blocked", 0) or 0)
    blocked = unauthorized + blocked_self + blocked_double
    available = approved + rejected
    availability_denominator = available + blocked
    pending_compliant = len(pending_tickets) - sla_breaches
    sla_compliant = final_decisions - expired + pending_compliant
    sla_denominator = final_decisions + len(pending_tickets)
    return {
        "agent": host.spec.name,
        "status": "degraded" if pending_final_approvals or sla_breaches else "ok",
        "status_reason": (
            "approval_publication_backlog"
            if pending_final_approvals
            else ("approval_sla_breach" if sla_breaches else "ready")
        ),
        "approval_durability": "durable" if host._state_store is not None else "process_local",
        "pending_tickets": len(pending_tickets),
        "pending_shadow_reviews": len(host._pending_shadow_reviews),
        "pending_final_approvals": pending_final_approvals,
        "approval_sla_seconds": _APPROVAL_SLA_SECONDS,
        "oldest_pending_ticket_age_seconds": oldest_pending_age,
        "oldest_pending_ticket_age_evidence_state": (
            "measured" if oldest_pending_age is not None else "insufficient_sample"
        ),
        "approval_sla_breach_count": sla_breaches,
        "approver_availability": {
            "available_decisions": available,
            "blocked_decisions": blocked,
            "evidence_state": ("measured" if availability_denominator else "insufficient_sample"),
        },
        "admin_alert": {
            "delivered": len(host._last_cards),
            "last_status": "delivered" if host._last_cards else "not_observed",
        },
        "queue_preserved": True,
        "timeouts_extended": bool(pending_tickets),
        "allowed_action_classes": ["A1", "A2"],
        "approval_outcomes": {
            "approved": approved,
            "rejected": rejected,
            "expired": expired,
            "repeated_escalations": repeated_escalations,
        },
        "kpis": {
            "hil_sla_compliance_rate": ratio_kpi(sla_compliant, sla_denominator),
            "quorum_compliance_rate": ratio_kpi(approved, final_decisions),
            "expiry_rate": ratio_kpi(expired, final_decisions + expired),
            "repeated_escalation_rate": ratio_kpi(
                repeated_escalations,
                len(pending_tickets) + final_decisions,
            ),
        },
        "behavior": behavior,
    }


def _oldest_pending_ticket_age_seconds(tickets: tuple[Any, ...], *, now: datetime) -> int | None:
    ages = [_ticket_age_seconds(ticket, now=now) for ticket in tickets]
    measured = [age for age in ages if age is not None]
    return max(measured) if measured else None


def _ticket_age_seconds(ticket: Any, *, now: datetime) -> int | None:
    created_at = getattr(ticket, "created_at", None) or getattr(ticket, "requested_at", None)
    if created_at is None:
        created_at = _created_at_from_decision_case(getattr(ticket, "decision_case", None))
    if not isinstance(created_at, datetime):
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    return max(0, int((now - created_at).total_seconds()))


def _created_at_from_decision_case(raw: Any) -> datetime | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get("created_at") or raw.get("requested_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


__all__ = ["health", "ratio_kpi"]
