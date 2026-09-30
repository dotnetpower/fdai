"""Health projection helpers for Var."""

from __future__ import annotations

from typing import Any


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
    pending_final_approvals = sum(
        1 for key in host._final_approvals if key not in host._published_approvals
    )
    approved = int(behavior.get("approved", 0) or 0)
    rejected = int(behavior.get("rejected", 0) or 0)
    final_decisions = approved + rejected
    expired = int(behavior.get("approval:expired", 0) or 0)
    repeated_escalations = len(host._blocked_attempts)
    return {
        "agent": host.spec.name,
        "status": "degraded" if pending_final_approvals else "ok",
        "status_reason": "approval_publication_backlog" if pending_final_approvals else "ready",
        "approval_durability": "durable" if host._state_store is not None else "process_local",
        "pending_tickets": len(pending_tickets),
        "pending_shadow_reviews": len(host._pending_shadow_reviews),
        "pending_final_approvals": pending_final_approvals,
        "oldest_pending_ticket_age_seconds": None,
        "oldest_pending_ticket_age_evidence_state": "not_observed",
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
            "hil_sla_compliance_rate": ratio_kpi(final_decisions - expired, final_decisions),
            "quorum_compliance_rate": ratio_kpi(approved, final_decisions),
            "expiry_rate": ratio_kpi(expired, final_decisions + expired),
            "repeated_escalation_rate": ratio_kpi(
                repeated_escalations,
                len(pending_tickets) + final_decisions,
            ),
        },
        "behavior": behavior,
    }


__all__ = ["health", "ratio_kpi"]
