"""PatternLibraryWriter Protocol - write seam for the T1 pattern library.

Companion to
:class:`~fdai.core.tiers.t1_lightweight.tier.PatternLibrary`, which
is the READ-only search Protocol used at T1 inference time. This module
defines the WRITE seam that the Phase-4 pattern-growth intake runner
uses to add new, shadow-mode patterns to the library.

Design boundaries
-----------------

- ``core/`` MAY import this Protocol (it lives under
  ``fdai.shared.providers``) but MUST NOT import a concrete
  implementation. Concrete writers live under
  ``fdai.delivery.persistence.*`` (production) and
  ``fdai.shared.providers.testing.*`` (unit tests + local dev).
- Every operation is ``async`` because the real backend runs against
  Postgres+pgvector under a bearer token issued via
  :class:`~fdai.shared.providers.workload_identity.WorkloadIdentity`.
- ``LearnedAction`` is imported under ``TYPE_CHECKING`` so this shared
  module has no runtime dependency on ``core/`` - the shape is stable
  and the Protocol stays honest at type-check time.

Safety invariants (owned by the caller)
---------------------------------------

- The Phase-4 intake filter (``evaluate_intake``) MUST pass BEFORE this
  seam is called. The writer carries no policy - it is a delivery seam.
- Growth NEVER auto-promotes. New patterns enter with
  ``historical_success_rate == 0.0`` so the T1 tier's ``min_success_rate``
  floor filters them out of execution until a subsequent, measured
  promotion step lifts them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from fdai.core.tiers.t1_lightweight.tier import LearnedAction


@runtime_checkable
class PatternLibraryWriter(Protocol):
    """Write seam for shadow-first pattern ingestion.

    The Protocol is intentionally minimal - a single upsert operation
    keyed by :attr:`LearnedAction.signature`. Retirement / rebalancing
    are governed by the reviewed catalog pipeline, not this seam.
    """

    async def upsert_pattern(
        self,
        *,
        vector: Sequence[float],
        action: LearnedAction,
    ) -> None:
        """Insert or update one pattern by its natural key ``action.signature``.

        Implementations MUST be idempotent on ``signature``: re-upserting
        the same pattern MUST NOT create a duplicate row. Callers rely
        on this to make the growth intake runner replay-safe.

        Raises :class:`ValueError` when ``vector`` violates the adapter's
        embedding-dimension contract; any other error is an unrecoverable
        substrate failure the caller MUST audit as an intake abort.
        """
        ...


__all__ = ["PatternLibraryWriter"]
