"""Derive the Console watermark notice from one resolved entitlement.

The notice is an availability statement for people, not a decision. It never
grants or removes a capability: the shared execution ceiling still checks every
acting request. Core derives it once, so the Operator and the Console only carry
the value and never re-resolve licensing on their own.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from fdai.core.licensing.entitlement import Entitlement, LicenseStatus

ACTING_CAPABILITY_ID: Final = "operations.typed-mutation"
"""The catalog capability that every acting execution path requires."""


class EntitlementNotice(StrEnum):
    """What the watermark tells an operator about acting availability."""

    NONE = "none"
    EVALUATION_ENDED = "evaluation-ended"
    NOT_ACTIVATED = "not-activated"


def entitlement_notice(entitlement: Entitlement) -> EntitlementNotice:
    """Return ``none`` only when the entitlement includes the acting capability.

    An expired token or an ended Trial reads as an ended evaluation. Every other
    state that withholds acting work, including an absent, untrusted, misbound,
    not-yet-valid, clock-blocked, or unreachable one, reads as not activated.
    """

    if ACTING_CAPABILITY_ID in entitlement.available_capability_ids:
        return EntitlementNotice.NONE
    if entitlement.status is LicenseStatus.EXPIRED:
        return EntitlementNotice.EVALUATION_ENDED
    return EntitlementNotice.NOT_ACTIVATED


__all__ = ["ACTING_CAPABILITY_ID", "EntitlementNotice", "entitlement_notice"]
