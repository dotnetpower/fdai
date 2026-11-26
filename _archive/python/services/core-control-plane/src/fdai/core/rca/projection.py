"""Atomic ontology projection for immutable causal hypotheses."""

from __future__ import annotations

from fdai.core.rca.hypothesis import CausalHypothesisRecord
from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
    canonical_json_mapping,
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
        if not isinstance(finding_id, str) or not finding_id.strip():
            raise ValueError("finding_id MUST be non-empty")
        record = hypothesis.to_ontology_object()
        if previous_hypothesis_id is not None:
            if not isinstance(previous_hypothesis_id, str) or not previous_hypothesis_id.strip():
                raise ValueError("previous_hypothesis_id MUST be non-empty when provided")
            if previous_hypothesis_id.strip() == record.id:
                raise ValueError("previous_hypothesis_id MUST NOT reference the same hypothesis")
        for group_name, group_values in (
            ("change_ids", change_ids),
            ("experiment_ids", experiment_ids),
            ("supporting_evidence_ids", supporting_evidence_ids),
            ("refuting_evidence_ids", refuting_evidence_ids),
            ("outcome_ids", outcome_ids),
            ("informed_expected_effect_ids", informed_expected_effect_ids),
        ):
            if any(not isinstance(item, str) or not item.strip() for item in group_values):
                raise ValueError(f"{group_name} MUST contain non-empty strings")
        existing = await self._store.get_object(record.id)
        if existing is not None:
            if (
                existing.object_type != record.object_type
                or canonical_json_mapping(existing.properties, path="causal_hypothesis")[1]
                != canonical_json_mapping(record.properties, path="causal_hypothesis")[1]
            ):
                raise CausalProjectionConflictError("immutable causal hypothesis content changed")
            return
        links = [
            OntologyLinkRecord("hypothesis_explains_finding", record.id, finding_id.strip()),
            *(
                OntologyLinkRecord("hypothesis_claims_change", record.id, target.strip())
                for target in dict.fromkeys(change_ids)
            ),
            *(
                OntologyLinkRecord("hypothesis_claims_experiment", record.id, target.strip())
                for target in dict.fromkeys(experiment_ids)
            ),
            *(
                OntologyLinkRecord("evidence_supports_hypothesis", source.strip(), record.id)
                for source in dict.fromkeys(supporting_evidence_ids)
            ),
            *(
                OntologyLinkRecord("evidence_refutes_hypothesis", source.strip(), record.id)
                for source in dict.fromkeys(refuting_evidence_ids)
            ),
            *(
                OntologyLinkRecord("outcome_tests_hypothesis", source.strip(), record.id)
                for source in dict.fromkeys(outcome_ids)
            ),
            *(
                OntologyLinkRecord(
                    "hypothesis_informs_expected_effect",
                    record.id,
                    target.strip(),
                )
                for target in dict.fromkeys(informed_expected_effect_ids)
            ),
        ]
        if previous_hypothesis_id is not None:
            links.append(
                OntologyLinkRecord(
                    "hypothesis_precedes_hypothesis",
                    previous_hypothesis_id.strip(),
                    record.id,
                )
            )
        await self._store.replace_subgraph(
            objects=(*endpoint_objects, record),
            links=tuple(links),
        )


__all__ = ["CausalHypothesisProjector", "CausalProjectionConflictError"]
