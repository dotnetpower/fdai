"""Admin-card delivery helper for Var."""

from __future__ import annotations

import inspect
from typing import Any

from fdai.agents._framework.adapters import AdminCard
from fdai.agents._framework.var_ticket_identity import evict_oldest_ticket


async def deliver_admin_card(host: Any, payload: dict[str, Any]) -> AdminCard:
    initiator = str(payload.get("initiator_principal", ""))
    action = str(payload.get("attempted_action", ""))
    severity = str(payload.get("severity", "high"))
    counter = int(payload.get("counter", 1))
    key = (initiator, action)
    card = AdminCard(
        severity=severity,
        initiator_principal=initiator,
        attempted_action=action,
        counter=counter,
    )
    try:
        delivery = host.admin_channel.upsert(key, card)
        delivered = await delivery if inspect.isawaitable(delivery) else delivery
    except Exception:
        host.record_behavior("admin_alert:failed")
        raise
    if not isinstance(delivered, AdminCard):
        host.record_behavior("admin_alert:failed")
        raise TypeError("admin channel returned a malformed card")
    host._last_cards[key] = delivered
    host.record_behavior("admin_alert:delivered")
    evict_oldest_ticket(host._last_cards, host._MAX_CARDS, keep=key)
    return delivered


__all__ = ["deliver_admin_card"]
