"""Atomic ontology projection for immutable recovery plans."""

from __future__ import annotations

from fdai.core.recovery.models import RecoveryPlanRecord
from fdai.shared.providers.ontology_instance import OntologyInstanceStore, OntologyLinkRecord


class RecoveryPlanProjector:
    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def project(
        self,
        plan: RecoveryPlanRecord,
        *,
        hypothesis_id: str,
        process_id: str,
    ) -> None:
        record = plan.to_ontology_object()
        existing = await self._store.get_object(record.id)
        if existing is not None:
            if (
                existing.object_type != record.object_type
                or existing.properties != record.properties
            ):
                raise RuntimeError("immutable recovery plan content changed")
            return
        links = (
            OntologyLinkRecord("recovery_addresses_hypothesis", record.id, hypothesis_id),
            *(
                OntologyLinkRecord("recovery_targets_resource", record.id, target)
                for target in plan.direct_target_ids
            ),
            OntologyLinkRecord("recovery_realized_as_process", record.id, process_id),
        )
        await self._store.replace_subgraph(objects=(record,), links=links)


__all__ = ["RecoveryPlanProjector"]
