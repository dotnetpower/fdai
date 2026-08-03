"""StateStore-backed evidence for stateful ActionType preconditions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from fdai.shared.providers.state_store import StateStore


@dataclass(frozen=True, slots=True)
class StateStoreOpenActionEvidenceProvider:
    """Read Thor's durable active-run index without granting action authority."""

    store: StateStore
    index_key: str = "thor:active-index"
    run_prefix: str = "thor:run|"
    max_active_runs: int = 10_000

    def __post_init__(self) -> None:
        if self.max_active_runs < 1:
            raise ValueError("max_active_runs MUST be positive")

    async def has_conflict(
        self,
        *,
        target_ref: str,
        excluding_idempotency_key: str,
    ) -> bool:
        raw_index = await self.store.read_state(self.index_key)
        if raw_index is None:
            return False
        ids = raw_index.get("ids")
        if not isinstance(ids, list) or len(ids) > self.max_active_runs:
            return True
        for correlation_id in ids:
            if not isinstance(correlation_id, str) or not correlation_id:
                return True
            raw_run = await self.store.read_state(f"{self.run_prefix}{correlation_id}")
            if not isinstance(raw_run, Mapping):
                return True
            if str(raw_run.get("resource_id") or "") != target_ref:
                continue
            stored_key = str(raw_run.get("idempotency_key") or "")
            if not stored_key or stored_key != excluding_idempotency_key:
                return True
        return False


__all__ = ["StateStoreOpenActionEvidenceProvider"]
