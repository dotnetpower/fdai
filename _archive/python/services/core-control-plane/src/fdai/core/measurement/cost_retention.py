"""Bounded Cost Governance retention and legal-hold coordination."""

from __future__ import annotations

from datetime import datetime

from fdai.shared.providers.cost_governance_decision import CostGovernanceEpisodeStore


class CostGovernanceRetentionService:
    """Apply explicit legal holds and bounded purge without activation coupling."""

    def __init__(self, *, store: CostGovernanceEpisodeStore) -> None:
        self._store = store

    async def set_legal_hold(
        self,
        episode_id: str,
        *,
        expected_revision: int,
        legal_hold_ref: str,
        recorded_at: datetime,
    ) -> bool:
        """Apply a referenced hold with compare-and-set semantics."""

        if not legal_hold_ref.strip():
            raise ValueError("legal hold reference MUST be non-empty")
        return await self._store.compare_and_set_cost_retention(
            episode_id,
            expected_revision=expected_revision,
            legal_hold=True,
            legal_hold_ref=legal_hold_ref,
            recorded_at=recorded_at,
        )

    async def release_legal_hold(
        self,
        episode_id: str,
        *,
        expected_revision: int,
        recorded_at: datetime,
    ) -> bool:
        """Release a hold explicitly; package enablement is not consulted."""

        return await self._store.compare_and_set_cost_retention(
            episode_id,
            expected_revision=expected_revision,
            legal_hold=False,
            legal_hold_ref=None,
            recorded_at=recorded_at,
        )

    async def purge_due(
        self,
        *,
        now: datetime,
        limit: int = 100,
    ) -> tuple[str, ...]:
        """Append at most ``limit`` purge tombstones for due non-held episodes."""

        if not 1 <= limit <= 500:
            raise ValueError("cost purge limit MUST be in [1, 500]")
        return await self._store.purge_due_cost_episodes(now=now, limit=limit)


__all__ = ["CostGovernanceRetentionService"]
