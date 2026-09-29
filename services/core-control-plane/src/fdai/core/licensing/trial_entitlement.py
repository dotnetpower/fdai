"""Resolve durable Trial state into an entitlement decision at an exact time.

The Trial record in `trial.py` is an inert transition model: it says what a stored
window means, never what a caller may do. This module is the single place that turns
one durably stored, compare-and-set observed record into a capability decision, so
every execution path inherits the same answer through `LicenseEntitlementAuthority`.

A Trial never widens authority. It can only supply the same capability set a valid
signed token would, and only while its own window is open. A missing record, a record
bound to another installation, an expired window, or a detected clock regression each
resolve to no capability rather than to a default grant.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.core.capability_catalog.catalog import CapabilityCatalog
from fdai.core.licensing.entitlement import Entitlement, LicenseStatus
from fdai.core.licensing.trial import TrialRecord, TrialStatus


class TrialStore(Protocol):
    """Durable, authenticated Trial storage owned by the deployment.

    `observe` must read the current record, apply `TrialRecord.observe`, and commit it
    with a compare-and-set on the complete previous revision. A losing writer must
    return the winning record rather than retrying blindly, so concurrent replicas
    converge on one monotonic observation instead of restarting the window.
    """

    def observe(self, *, now: datetime) -> TrialRecord | None:
        """Return the committed record for this installation, or None when absent."""


@dataclass(frozen=True, slots=True)
class TrialEntitlementResolver:
    """Decide capability availability from durable Trial state alone.

    This resolver is consulted only when no signed token grants access, so an active
    token always wins and a Trial can never downgrade it. Storage failure is treated
    as absence: the deployment keeps observing and stops acting, which is the same
    outcome as an unactivated installation.
    """

    catalog: CapabilityCatalog
    store: TrialStore
    installation_binding: str
    deployment_binding: str
    on_storage_error: Callable[[Exception], None] | None = None

    def resolve(self, *, now: datetime) -> Entitlement:
        """Return the availability decision that applies at ``now``."""

        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Trial resolution requires a timezone-aware UTC clock")
        try:
            record = self.store.observe(now=now)
        except Exception as error:  # noqa: BLE001 - storage failure must not grant access
            if self.on_storage_error is not None:
                self.on_storage_error(error)
            return _denied("trial state is unavailable")
        if record is None:
            return _denied("no Trial has been activated for this installation")
        if (
            record.installation_binding != self.installation_binding
            or record.deployment_binding != self.deployment_binding
        ):
            return _denied("Trial record belongs to another installation")
        status = record.status
        if status is TrialStatus.CLOCK_BLOCKED:
            return _denied("Trial observed a clock regression and stays denied")
        if status is TrialStatus.EXPIRED:
            return _denied("Trial window has ended")
        if record.last_observed_at < now:
            # The store must commit an observation at or after `now` before acting, so a
            # replica cannot act on a stale read that predates an expiry another wrote.
            return _denied("Trial observation is stale for this decision")
        return Entitlement(
            status=LicenseStatus.ACTIVE,
            available_capability_ids=frozenset(
                capability.capability_id for capability in self.catalog.list()
            ),
            reason="active Trial window",
        )


def _denied(reason: str) -> Entitlement:
    """Deny every capability while preserving observation-only operation."""

    return Entitlement(
        status=LicenseStatus.ABSENT,
        available_capability_ids=frozenset(),
        reason=reason,
    )
