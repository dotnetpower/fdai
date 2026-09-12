"""Deterministic A3-E provider-commit-fence capability for shipped ActionTypes.

This module is **inert** and pure. It answers exactly one question: does the provider
adapter for an ActionType atomically validate the current standing-authorization lease
and lifecycle fencing generation inside the same transaction that commits the provider
effect (``StandingAuthorizationLeaseStore.check_commit_fence``)?

Today the answer is ``INELIGIBLE_CAPABILITY`` for every ActionType, because
:data:`A3E_COMMIT_FENCE_ADAPTERS` is empty. No shipped adapter implements that
boundary: Azure Resource Manager cannot join its VM start acceptance to the
PostgreSQL lease transaction, and the only shipped provider-boundary artifact
(``delivery/azure/vm_start_shadow_fence.py``) records ``INELIGIBLE_CAPABILITY`` and
never calls the provider.

The capability is **derived here, never declared by a caller**. Before this module
existed, a promotion-candidate author supplied the ineligible ActionType set by hand,
so an author who supplied an empty set obtained an approvable candidate for an
ActionType whose provider cannot close the revoke-during-effect race. Derivation
removes that claim surface.

Registering an ActionType in :data:`A3E_COMMIT_FENCE_ADAPTERS` is an authority-bearing
change. It requires the reviewed durable provider boundary tracked by issue #621, and
it still grants no execution or promotion authority on its own: governed runtime
evidence, independent review, and explicit current human approval (issue #632) remain
separate and unsatisfied.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from fdai.core.standing_authority.lifecycle_codec import AuthorizationLifecycleError


class ProviderFenceCapability(StrEnum):
    """Provider-commit-fence capability of one ActionType's adapter."""

    #: The adapter validates the current lease and fencing generation atomically at
    #: its effect-commit boundary.
    COMMIT_FENCE_ENFORCED = "commit_fence_enforced"

    #: The adapter cannot enforce that boundary, so the ActionType is not A3-E
    #: eligible. The value matches ``LeaseOutcome.INELIGIBLE_CAPABILITY`` so machine
    #: records stay comparable across the lease and eligibility contracts.
    INELIGIBLE_CAPABILITY = "ineligible_capability"


#: ActionType identifiers whose provider adapter enforces the A3-E commit fence.
#:
#: Empty on purpose: zero adapters implement atomic lease and fencing-generation
#: validation at provider commit. Nothing in the shipped runtime adds to this set,
#: and ``test_provider_eligibility.py`` fails if any shipped module assigns to it.
A3E_COMMIT_FENCE_ADAPTERS: Final[frozenset[str]] = frozenset()


@dataclass(frozen=True, slots=True)
class ProviderEligibilityPartition:
    """Canonical split of requested ActionTypes by provider-commit-fence capability."""

    fence_capable: tuple[str, ...]
    ineligible: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, values in (
            ("fence_capable", self.fence_capable),
            ("ineligible", self.ineligible),
        ):
            if len(values) != len(set(values)):
                raise AuthorizationLifecycleError(f"{name} MUST contain distinct values")
            if values != tuple(sorted(values)):
                raise AuthorizationLifecycleError(f"{name} MUST use canonical sorted order")
        if set(self.fence_capable) & set(self.ineligible):
            raise AuthorizationLifecycleError("partition halves MUST be disjoint")


def a3e_fence_capability(action_type_id: str) -> ProviderFenceCapability:
    """Classify one ActionType. Anything not explicitly registered is ineligible."""

    if not isinstance(action_type_id, str) or not action_type_id.strip():
        raise AuthorizationLifecycleError("action_type_id MUST be non-empty text")
    if action_type_id in A3E_COMMIT_FENCE_ADAPTERS:
        return ProviderFenceCapability.COMMIT_FENCE_ENFORCED
    return ProviderFenceCapability.INELIGIBLE_CAPABILITY


def partition_provider_eligibility(
    action_type_ids: Iterable[str],
) -> ProviderEligibilityPartition:
    """Split requested ActionTypes into fence-capable and ineligible halves."""

    capable: set[str] = set()
    ineligible: set[str] = set()
    for action_type_id in action_type_ids:
        if a3e_fence_capability(action_type_id) is ProviderFenceCapability.COMMIT_FENCE_ENFORCED:
            capable.add(action_type_id)
        else:
            ineligible.add(action_type_id)
    return ProviderEligibilityPartition(
        fence_capable=tuple(sorted(capable)),
        ineligible=tuple(sorted(ineligible)),
    )


def derive_ineligible_provider_action_types(
    action_type_ids: Iterable[str],
) -> tuple[str, ...]:
    """Return the canonical ineligible subset of the requested ActionTypes."""

    return partition_provider_eligibility(action_type_ids).ineligible


__all__ = [
    "A3E_COMMIT_FENCE_ADAPTERS",
    "ProviderEligibilityPartition",
    "ProviderFenceCapability",
    "a3e_fence_capability",
    "derive_ineligible_provider_action_types",
    "partition_provider_eligibility",
]
