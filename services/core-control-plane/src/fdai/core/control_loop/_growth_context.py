"""Record the growth context that lets verified enforce outcomes feed the T1 pattern library.

The verified-outcome record carries only the measured effect. Pattern growth also needs the
event text that T1 will later query with, the rule, the action parameters, and the incident. They
are recorded once per enforce-mode action, before dispatch or approval parking, so a resumed
approval keeps them. The record grants no authority and never affects dispatch.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from fdai.core.tiers.t1_lightweight.tier import event_embedding_projection
from fdai.shared.contracts.models import Action, Event, Mode, Rule
from fdai.shared.providers.state_store import StateStore

GROWTH_CONTEXT_ACTION_KIND: Final = "measurement.growth_context.v1"
_LOGGER = logging.getLogger(__name__)


def growth_context_entry(
    *, event: Event, action: Action, rule: Rule, incident_id: str | None
) -> dict[str, Any]:
    """Return the canonical audit entry for one enforce-mode action."""
    return {
        "actor": "fdai.measurement",
        "action_kind": GROWTH_CONTEXT_ACTION_KIND,
        "mode": Mode.SHADOW.value,
        "event_id": str(event.event_id),
        "action_id": str(action.action_id),
        "action_type_id": action.action_type,
        "rule_id": rule.id,
        "params": dict(action.params),
        "incident_id": incident_id,
        "embedding_projection": event_embedding_projection(event),
        "execution_authority": False,
    }


async def record_growth_context(
    audit_store: StateStore,
    *,
    event: Event,
    action: Action,
    rule: Rule,
    incident_id: str | None,
) -> None:
    """Persist the context for an enforce-mode action; shadow actions never become patterns."""
    if action.mode is not Mode.ENFORCE or not incident_id:
        return
    try:
        await audit_store.append_audit_entry(
            growth_context_entry(event=event, action=action, rule=rule, incident_id=incident_id)
        )
    except Exception:  # noqa: BLE001 - a learning-side audit failure must not stop the loop
        _LOGGER.warning(
            "growth_context_record_failed",
            extra={"action_id": str(action.action_id)},
            exc_info=True,
        )
