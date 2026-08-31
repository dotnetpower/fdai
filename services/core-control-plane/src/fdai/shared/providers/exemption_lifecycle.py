"""ExemptionLifecycleNotifier - ahead-of-expiry digest delivery contract.

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
    from fdai.rule_catalog.schema.exemption_lifecycle import ExemptionExpiryDigest

_LOGGER = logging.getLogger("fdai.governance.exemption_lifecycle")


@runtime_checkable
class ExemptionLifecycleNotifier(Protocol):
    """Deliver one bounded ahead-of-expiry digest without granting authority."""

    async def notify_expiry_digest(
        self,
        *,
        digest: ExemptionExpiryDigest,
    ) -> None: ...


class LoggingExemptionLifecycleNotifier:
    """Upstream default: structured log line, no network.

    Ships in shadow-safe form (architecture.instructions.md "New capabilities
    ship in shadow mode"): it never calls out to ChatOps/email. A deployment
    that wants live delivery injects its own :class:`ExemptionLifecycleNotifier`
    (e.g. a ChatOps adapter) at the composition root.
    """

    async def notify_expiry_digest(
        self,
        *,
        digest: ExemptionExpiryDigest,
    ) -> None:
        _LOGGER.warning(
            "exemption_expiry_lookahead_digest",
            extra={
                "generated_at": digest.generated_at.isoformat(),
                "item_count": len(digest.items),
                "items": [
                    {
                        "exemption_id": item.exemption_id,
                        "exemption_revision": item.exemption_revision,
                        "rule_id": item.rule_id,
                        "requested_by": item.requested_by,
                        "expires_at": item.expires_at.isoformat(),
                    }
                    for item in digest.items
                ],
            },
        )


__all__ = ["ExemptionLifecycleNotifier", "LoggingExemptionLifecycleNotifier"]
