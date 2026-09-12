"""Test-only hypothetical A3-E provider-commit-fence capability.

Production registers zero fence-capable adapters, so no real ActionType can produce a
``PENDING`` or ``APPROVED`` promotion candidate. The candidate lifecycle state machine
still needs coverage of review quorum, self-review, duplicate and conflicting review,
evidence gaps, revocation, and replay.

This helper temporarily substitutes a hypothetical adapter registry for the duration of
one record construction. It is deliberately confined to ``tests/``:

- it exposes no production parameter, so no shipped caller can declare eligibility;
- ``test_provider_eligibility.py`` proves that no module under ``src/fdai`` assigns to
  the adapter registry or imports this helper.

Records built inside :func:`hypothetical_fence_capable` describe a hypothetical world.
They are never evidence that any shipped ActionType is A3-E eligible.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from unittest.mock import patch

from fdai.core.standing_authority import provider_eligibility

HELPER_MODULE_NAME = "hypothetical_provider_eligibility"


@contextmanager
def hypothetical_fence_capable(action_type_ids: Iterable[str]) -> Iterator[None]:
    """Treat exactly ``action_type_ids`` as fence-capable inside this block."""

    with patch.object(
        provider_eligibility,
        "A3E_COMMIT_FENCE_ADAPTERS",
        frozenset(action_type_ids),
    ):
        yield


__all__ = ["HELPER_MODULE_NAME", "hypothetical_fence_capable"]
