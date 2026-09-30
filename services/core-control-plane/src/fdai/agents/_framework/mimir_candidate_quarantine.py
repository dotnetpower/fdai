from __future__ import annotations

from collections import deque
from typing import Any, Protocol

from fdai.agents._framework.mimir_governance_state import (
    MimirCatalogGovernanceStore,
    quarantine_summary,
)


class MimirCandidateQuarantineHost(Protocol):
    _catalog_governance_store: MimirCatalogGovernanceStore
    _quarantined_candidates: deque[dict[str, Any]]

    def record_behavior(self, key: str, count: int = 1) -> None: ...

    async def _audit_outcome(
        self,
        payload: dict[str, Any],
        *,
        outcome: str,
        reason: str,
        candidate_digest: str | None = None,
        package_digest: str | None = None,
        review_ref: str | None = None,
    ) -> None: ...


async def quarantine_candidate(
    host: MimirCandidateQuarantineHost,
    payload: dict[str, Any],
    reason: str,
) -> None:
    prior_quarantine = await host._catalog_governance_store.quarantine(payload)
    if prior_quarantine is not None:
        host._quarantined_candidates.append(prior_quarantine)
        host.record_behavior("catalog_candidate_quarantine_duplicate")
        return
    host._quarantined_candidates.append(
        {**quarantine_summary(payload), "quarantine_reason": reason}
    )
    await host._catalog_governance_store.persist_quarantine(payload, reason)
    await host._audit_outcome(payload, outcome="quarantined", reason=reason)


__all__ = ["quarantine_candidate"]
