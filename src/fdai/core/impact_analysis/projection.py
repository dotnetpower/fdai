"""Atomic ontology projection for immutable impact envelopes."""

from __future__ import annotations

from fdai.core.impact_analysis.models import ImpactEnvelopeRecord
from fdai.shared.providers.ontology_instance import OntologyInstanceStore, OntologyLinkRecord


class ImpactEnvelopeProjector:
    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def project(
        self,
        envelope: ImpactEnvelopeRecord,
        *,
        experiment_ids: tuple[str, ...] = (),
        action_option_ids: tuple[str, ...] = (),
    ) -> None:
        record = envelope.to_ontology_object()
        existing = await self._store.get_object(record.id)
        if existing is not None:
            if (
                existing.object_type != record.object_type
                or existing.properties != record.properties
            ):
                raise RuntimeError("immutable impact envelope content changed")
            return
        links = (
            *(
                OntologyLinkRecord("envelope_bounds_experiment", record.id, target)
                for target in experiment_ids
            ),
            *(
                OntologyLinkRecord("envelope_bounds_action_option", record.id, target)
                for target in action_option_ids
            ),
            *(
                OntologyLinkRecord("envelope_protects_objective", record.id, target)
                for target in envelope.protected_objective_ids
            ),
        )
        await self._store.replace_subgraph(objects=(record,), links=links)


__all__ = ["ImpactEnvelopeProjector"]
