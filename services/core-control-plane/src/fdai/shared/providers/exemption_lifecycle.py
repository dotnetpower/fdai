"""ExemptionLifecycleNotifier - ahead-of-expiry notification contract.

Realizes the "ahead-of-expiry" notification half of
``rule-governance.md § Exemptions``: once
:func:`fdai.rule_catalog.schema.exemption_lifecycle.plan_exemption_lifecycle`
decides an active exemption needs an
:class:`~fdai.rule_catalog.schema.exemption_lifecycle.ExemptionLifecycleAction.ALERT_AHEAD_OF_EXPIRY`
notice, :class:`fdai.delivery.exemption_lifecycle.ExemptionLifecycleCoordinator`
calls this Protocol exactly once per exemption (idempotency lives in the
coordinator, not here).

This is a delivery seam, not a decision: the notifier MUST NOT judge whether to
notify - it only delivers a notice the pure planner already decided is due.
Real delivery (ChatOps / email) is deployment-configured
(``FDAI_CHATOPS_WEBHOOK_URL`` et al. - see ``delivery/runtime_settings.py``);
this module ships only the Protocol and a safe, network-free default so the
control plane can be exercised end to end without live delivery.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.rule_catalog.schema.exemption import Exemption
    from fdai.rule_catalog.schema.exemption_lifecycle import ExemptionLifecycleDecision

_LOGGER = logging.getLogger("fdai.governance.exemption_lifecycle")


@runtime_checkable
class ExemptionLifecycleNotifier(Protocol):
    """Deliver one ahead-of-expiry notice for an active exemption."""

    async def notify_ahead_of_expiry(
        self,
        *,
        exemption: Exemption,
        decision: ExemptionLifecycleDecision,
    ) -> None: ...


class LoggingExemptionLifecycleNotifier:
    """Upstream default: structured log line, no network.

    Ships in shadow-safe form (architecture.instructions.md "New capabilities
    ship in shadow mode"): it never calls out to ChatOps/email. A deployment
    that wants live delivery injects its own :class:`ExemptionLifecycleNotifier`
    (e.g. a ChatOps adapter) at the composition root.
    """

    async def notify_ahead_of_expiry(
        self,
        *,
        exemption: Exemption,
        decision: ExemptionLifecycleDecision,
    ) -> None:
        _LOGGER.warning(
            "exemption_ahead_of_expiry",
            extra={
                "exemption_id": exemption.id,
                "rule_id": exemption.rule_id,
                "expires_at": decision.expires_at.isoformat(),
                "at": decision.at.isoformat(),
            },
        )


__all__ = ["ExemptionLifecycleNotifier", "LoggingExemptionLifecycleNotifier"]
