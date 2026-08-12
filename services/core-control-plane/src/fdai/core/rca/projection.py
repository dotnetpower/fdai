"""Atomic ontology projection for immutable causal hypotheses."""

from __future__ import annotations

from fdai.core.rca.hypothesis import CausalHypothesisRecord
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
)


class CausalProjectionConflictError(RuntimeError):
    """A supposedly immutable hypothesis id resolved to different content."""


class CausalHypothesisProjector:
    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def project(
        self,
        hypothesis: CausalHypothesisRecord,
        *,
        finding_id: str,
        change_ids: tuple[str, ...] = (),
        experiment_ids: tuple[str, ...] = (),
        supporting_evidence_ids: tuple[str, ...] = (),
        refuting_evidence_ids: tuple[str, ...] = (),
        outcome_ids: tuple[str, ...] = (),
        previous_hypothesis_id: str | None = None,
        informed_expected_effect_ids: tuple[str, ...] = (),
        endpoint_objects: tuple[OntologyObjectRecord, ...] = (),
    ) -> None:
        record = hypothesis.to_ontology_object()
        existing = await self._store.get_object(record.id)
        if existing is not None:
            if (
                existing.object_type != record.object_type
                or existing.properties != record.properties
            ):
                raise CausalProjectionConflictError("immutable causal hypothesis content changed")
            return
        links = [
            OntologyLinkRecord("hypothesis_explains_finding", record.id, finding_id),
            *(
                OntologyLinkRecord("hypothesis_claims_change", record.id, target)
                for target in change_ids
            ),
            *(
                OntologyLinkRecord("hypothesis_claims_experiment", record.id, target)
                for target in experiment_ids
            ),
            *(
                OntologyLinkRecord("evidence_supports_hypothesis", source, record.id)
                for source in supporting_evidence_ids
            ),
            *(
                OntologyLinkRecord("evidence_refutes_hypothesis", source, record.id)
                for source in refuting_evidence_ids
            ),
            *(
                OntologyLinkRecord("outcome_tests_hypothesis", source, record.id)
                for source in outcome_ids
            ),
            *(
                OntologyLinkRecord(
                    "hypothesis_informs_expected_effect",
                    record.id,
                    target,
                )
                for target in informed_expected_effect_ids
            ),
        ]
        if previous_hypothesis_id is not None:
            links.append(
                OntologyLinkRecord(
                    "hypothesis_precedes_hypothesis",
                    previous_hypothesis_id,
                    record.id,
                )
            )
        await self._store.replace_subgraph(
            objects=(*endpoint_objects, record),
            links=tuple(links),
        )


__all__ = ["CausalHypothesisProjector", "CausalProjectionConflictError"]
