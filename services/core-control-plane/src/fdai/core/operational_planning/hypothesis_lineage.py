"""Immutable ontology lineage from an operational decision to its observed outcome."""

from __future__ import annotations

from dataclasses import dataclass

from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_object_record,
)


class OperationalHypothesisLineageConflictError(RuntimeError):
    """A replay attempted to change an immutable lineage object."""


@dataclass(frozen=True, slots=True)
class OperationalHypothesisLineage:
    """Existing ontology records that form one prospective intervention episode."""

    decision_case: OntologyObjectRecord
    action_option: OntologyObjectRecord
    expected_effect: OntologyObjectRecord
    action_run: OntologyObjectRecord
    observed_outcome: OntologyObjectRecord

    def __post_init__(self) -> None:
        _require_type(self.decision_case, "DecisionCase")
        _require_type(self.action_option, "ActionOption")
        _require_type(self.expected_effect, "ExpectedEffect")
        _require_type(self.action_run, "ActionRun")
        _require_type(self.observed_outcome, "ObservedOutcome")
        if not self.decision_case.properties.get("no_action_baseline"):
            raise ValueError("operational lineage requires a no-action baseline")
        if self.action_option.properties.get("decision_case_id") != self.decision_case.id:
            raise ValueError("action option does not belong to the decision case")
        if self.action_option.properties.get("expected_effect_ref") != self.expected_effect.id:
            raise ValueError("action option does not cite the expected effect")
        if self.action_option.properties.get("action_type_ref") != self.action_run.properties.get(
            "action_type_ref"
        ):
            raise ValueError("action run does not execute the selected option")
        if self.observed_outcome.properties.get("action_run_id") != self.action_run.id:
            raise ValueError("observed outcome does not cite the action run")
        if self.observed_outcome.properties.get("expected_effect_ref") != self.expected_effect.id:
            raise ValueError("observed outcome does not cite the expected effect")
        if self.observed_outcome.properties.get("verification") != "independent":
            raise ValueError("operational lineage requires an independent observation")

    @property
    def objects(self) -> tuple[OntologyObjectRecord, ...]:
        """Return the existing episode records in deterministic lineage order."""

        return (
            self.decision_case,
            self.action_option,
            self.expected_effect,
            self.action_run,
            self.observed_outcome,
        )

    @property
    def links(self) -> tuple[OntologyLinkRecord, ...]:
        """Return the authority-free relationships that make the episode replayable."""

        return (
            OntologyLinkRecord("considers", self.decision_case.id, self.action_option.id),
            OntologyLinkRecord("expects", self.action_option.id, self.expected_effect.id),
            OntologyLinkRecord("executed_as", self.action_option.id, self.action_run.id),
            OntologyLinkRecord("resulted_in", self.action_run.id, self.observed_outcome.id),
        )


class OperationalHypothesisLineageProjector:
    """Atomically append one validated episode without rewriting existing objects."""

    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def project(self, lineage: OperationalHypothesisLineage) -> None:
        """Append missing objects and idempotently restore their typed links."""

        missing: list[OntologyObjectRecord] = []
        for record in lineage.objects:
            existing = await self._store.get_object(record.id)
            if existing is None:
                missing.append(record)
                continue
            if not _same_immutable_object(existing, record):
                raise OperationalHypothesisLineageConflictError(
                    f"immutable operational lineage object changed: {record.id}"
                )
        await self._store.replace_subgraph(
            objects=tuple(missing),
            links=lineage.links,
        )


def _require_type(record: OntologyObjectRecord, expected: str) -> None:
    if record.object_type != expected:
        raise ValueError(f"operational lineage requires {expected}, got {record.object_type}")


def _same_immutable_object(
    existing: OntologyObjectRecord,
    candidate: OntologyObjectRecord,
) -> bool:
    return (
        existing.object_type == candidate.object_type
        and normalize_object_record(existing).properties
        == normalize_object_record(candidate).properties
    )


__all__ = [
    "OperationalHypothesisLineage",
    "OperationalHypothesisLineageConflictError",
    "OperationalHypothesisLineageProjector",
]
