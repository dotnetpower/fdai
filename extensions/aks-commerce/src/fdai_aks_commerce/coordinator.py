"""Bounded observation-to-projection coordinator for the commerce scenario."""

from __future__ import annotations

from typing import Protocol

from fdai.shared.providers.state_store import StateStore
from fdai_service_contracts import AksCommerceProjection

from fdai_aks_commerce.assessment import assess_aks_commerce
from fdai_aks_commerce.models import (
    AksCommerceAssessmentPolicy,
    AksCommerceEvidenceFrame,
)

PROJECTION_KEY_PREFIX = "aks-commerce:projection:v1:"


class AksCommerceObservationSource(Protocol):
    """Collect one exact, bounded evidence frame."""

    async def collect(self, service_id: str) -> AksCommerceEvidenceFrame: ...


class AksCommerceCoordinator:
    """Collect, assess, and persist one content-addressed projection."""

    def __init__(
        self,
        *,
        source: AksCommerceObservationSource,
        store: StateStore,
        policy: AksCommerceAssessmentPolicy | None = None,
        retain_newest: int = 96,
    ) -> None:
        if not 1 <= retain_newest <= 10_000:
            raise ValueError("AKS commerce retention must be in [1, 10000]")
        self._source = source
        self._store = store
        self._policy = policy
        self._retain_newest = retain_newest

    async def run_once(self, service_id: str) -> AksCommerceProjection:
        """Persist one immutable assessment and update the latest pointer."""

        frame = await self._source.collect(service_id)
        projection = assess_aks_commerce(frame, policy=self._policy)
        payload = projection.model_dump(mode="json")
        prefix = f"{PROJECTION_KEY_PREFIX}{service_id}:"
        await self._store.write_state(f"{prefix}{projection.assessment_id}", payload)
        await self._store.write_state(f"{prefix}latest", payload)
        await self._store.delete_states_beyond(prefix, retain_newest=self._retain_newest)
        return projection
