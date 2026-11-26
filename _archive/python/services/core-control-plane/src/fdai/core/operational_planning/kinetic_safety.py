"""Provider-neutral pre-dispatch persistence for exact kinetic artifacts."""

from __future__ import annotations

from typing import Protocol

from fdai.shared.contracts.models import Action


class PreDispatchKineticSafetyWriter(Protocol):
    """Persist exact existing kinetic artifacts before provider dispatch.

    Returning ``None`` preserves the legacy path when no proposal exists.
    Invalid, ambiguous, unavailable, or conflicting artifacts raise and block
    dispatch; implementations never reconstruct an Action or MutationPlan.
    """

    async def persist(
        self,
        *,
        action: Action,
        correlation_id: str,
    ) -> str | None: ...


__all__ = ["PreDispatchKineticSafetyWriter"]
