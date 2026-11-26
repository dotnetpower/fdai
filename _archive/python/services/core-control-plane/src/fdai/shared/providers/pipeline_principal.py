"""PipelinePrincipalRegistry - actor-identity lookup for Change Safety attribution.

Realizes the out-of-band attribution rule from
``docs/roadmap/phases/phase-1-rule-catalog-t0.md § Out-of-Band Detection``:
a change signal is *authorized* when its actor identity matches a known
pipeline principal (CI service principal, deployment stack MSI, GitOps
runner, etc.); anything else is a candidate for the *out_of_band* branch.

Design boundaries
-----------------

- ``core/`` MAY reference this Protocol (it lives under
  ``fdai.shared.providers``) but MUST NOT construct a concrete
  registry. Bindings happen at the composition root; a fork registers
  the identities of its own pipelines via configuration.
- The Protocol is intentionally minimal: one membership check on an
  opaque ``principal_id`` string (typically an object-id / service-
  principal-id / MSI-id - never a UPN, per
  ``docs/roadmap/architecture/security-and-identity.md § no-self-approval``).
- Lookups are cheap and idempotent; implementations MAY cache but MUST
  NOT block on network calls at ``contains()`` call time - the caller
  is on the event-loop.

The in-memory :class:`InMemoryPipelinePrincipalRegistry` fake is shipped
alongside the Protocol (mirrors :mod:`~fdai.shared.providers.exemption`)
so unit tests import both from the same module.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable


@runtime_checkable
class PipelinePrincipalRegistry(Protocol):
    """Membership check for known pipeline actor identities.

    A truthy result promises that the caller (the change-safety
    detector) MAY treat the associated change as *authorized*. A false
    result never confirms out-of-band by itself - the detector still
    consults the remediation-PR ledger for a correlation link before
    concluding attribution.
    """

    def contains(self, principal_id: str) -> bool:
        """Return ``True`` iff ``principal_id`` is a registered pipeline actor.

        ``principal_id`` MUST be an opaque identity token (object-id,
        service-principal-id, MSI-id). Implementations MUST NOT
        transform / normalize case-sensitively; ``contains`` is a raw
        membership check on an already-canonical identifier chosen by
        the composition root.
        """
        ...


class InMemoryPipelinePrincipalRegistry(PipelinePrincipalRegistry):
    """Frozen-set backed registry - the upstream default + a test fake.

    A fork replaces this with a config-driven or state-store adapter
    that hydrates from ``config/pipeline-principals.yaml`` (or the
    equivalent secret store). Kept in ``shared/providers/`` (not
    ``testing/``) because ``core/`` needs a working default so the
    control loop can be exercised end-to-end in dev without a fork.
    """

    __slots__ = ("_principals",)

    def __init__(self, principals: Iterable[str] = ()) -> None:
        # frozenset gives an O(1) contains + immutability so a caller
        # cannot mutate the registry through a returned view.
        self._principals: frozenset[str] = frozenset(principals)

    def contains(self, principal_id: str) -> bool:
        return principal_id in self._principals


__all__ = [
    "InMemoryPipelinePrincipalRegistry",
    "PipelinePrincipalRegistry",
]
