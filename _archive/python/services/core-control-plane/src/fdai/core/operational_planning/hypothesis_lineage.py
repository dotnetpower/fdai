"""Immutable ontology lineage from an operational decision to its observed outcome."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from fdai.shared.providers.ontology_instance import (
    OntologyInstanceStore,
    OntologyLinkRecord,
    OntologyObjectRecord,
    normalize_object_record,
)


class OperationalHypothesisLineageConflictError(RuntimeError):
    """A replay attempted to change an immutable lineage object."""


@dataclass(frozen=True, slots=True)
class OperationalProspectiveLineage:
    """Forseti-owned records produced before one selected option executes."""

    decision_case: OntologyObjectRecord
    action_option: OntologyObjectRecord
    expected_effects: tuple[OntologyObjectRecord, ...]

    def __post_init__(self) -> None:
        _require_type(self.decision_case, "DecisionCase")
        _require_type(self.action_option, "ActionOption")
        if not self.expected_effects:
            raise ValueError("prospective lineage requires at least one expected effect")
        for expected_effect in self.expected_effects:
            _require_type(expected_effect, "ExpectedEffect")
        if not self.decision_case.properties.get("no_action_baseline"):
            raise ValueError("prospective lineage requires a no-action baseline")
        if self.action_option.properties.get("decision_case_id") != self.decision_case.id:
            raise ValueError("action option does not belong to the decision case")
        expected_effect_by_id = {item.id: item for item in self.expected_effects}
        if len(expected_effect_by_id) != len(self.expected_effects):
            raise ValueError("prospective lineage expected effects MUST be unique")
        expected_effect_ids = _expected_effect_refs(self.action_option.properties)
        if len(expected_effect_ids) != len(expected_effect_by_id) or set(
            expected_effect_ids
        ) != set(expected_effect_by_id):
            raise ValueError("action option does not cite every expected effect")
        object.__setattr__(
            self,
            "expected_effects",
            tuple(expected_effect_by_id[effect_id] for effect_id in expected_effect_ids),
        )

    @property
    def objects(self) -> tuple[OntologyObjectRecord, ...]:
        return (self.decision_case, self.action_option, *self.expected_effects)

    @property
    def links(self) -> tuple[OntologyLinkRecord, ...]:
        return (
            OntologyLinkRecord("considers", self.decision_case.id, self.action_option.id),
            *(
                OntologyLinkRecord("expects", self.action_option.id, expected_effect.id)
                for expected_effect in self.expected_effects
            ),
        )


class OperationalProspectiveLineageSource(Protocol):
    """Resolve already-produced Forseti records for one execution correlation."""

    async def resolve(self, correlation_id: str) -> OperationalProspectiveLineage | None: ...


class OperationalOutcomeLineageSink(Protocol):
    """Compatibility marker for the retired one-effect outcome writer."""


class OperationalOutcomeLineageProducer:
    """Reject construction of the retired duplicate observed-lineage path."""

    def __init__(self, **_: object) -> None:
        raise RuntimeError(
            "OperationalOutcomeLineageProducer is retired; use reconciliation materialization"
        )


@dataclass(frozen=True, slots=True)
class OperationalHypothesisLineage:
    """Existing ontology records that form one prospective intervention episode."""

    decision_case: OntologyObjectRecord
    action_option: OntologyObjectRecord
    expected_effects: tuple[OntologyObjectRecord, ...]
    action_run: OntologyObjectRecord
    observed_outcomes: tuple[OntologyObjectRecord, ...]

    def __post_init__(self) -> None:
        _require_type(self.decision_case, "DecisionCase")
        _require_type(self.action_option, "ActionOption")
        _require_type(self.action_run, "ActionRun")
        if not self.expected_effects:
            raise ValueError("operational lineage requires at least one expected effect")
        if not self.observed_outcomes:
            raise ValueError("operational lineage requires at least one observed outcome")
        for expected_effect in self.expected_effects:
            _require_type(expected_effect, "ExpectedEffect")
        for observed_outcome in self.observed_outcomes:
            _require_type(observed_outcome, "ObservedOutcome")
        if not self.decision_case.properties.get("no_action_baseline"):
            raise ValueError("operational lineage requires a no-action baseline")
        if self.action_option.properties.get("decision_case_id") != self.decision_case.id:
            raise ValueError("action option does not belong to the decision case")
        expected_effect_by_id = {item.id: item for item in self.expected_effects}
        if len(expected_effect_by_id) != len(self.expected_effects):
            raise ValueError("operational lineage expected effects MUST be unique")
        expected_effect_ids = _expected_effect_refs(self.action_option.properties)
        if len(expected_effect_ids) != len(expected_effect_by_id) or set(
            expected_effect_ids
        ) != set(expected_effect_by_id):
            raise ValueError("action option does not cite every expected effect")
        object.__setattr__(
            self,
            "expected_effects",
            tuple(expected_effect_by_id[effect_id] for effect_id in expected_effect_ids),
        )
        if self.action_option.properties.get("action_type_ref") != self.action_run.properties.get(
            "action_type_ref"
        ):
            raise ValueError("action run does not execute the selected option")
        observed_outcome_by_effect: dict[str, OntologyObjectRecord] = {}
        for observed_outcome in self.observed_outcomes:
            if observed_outcome.properties.get("action_run_id") != self.action_run.id:
                raise ValueError("observed outcome does not cite the action run")
            effect_id = observed_outcome.properties.get("expected_effect_ref")
            if not isinstance(effect_id, str) or not effect_id:
                raise ValueError("observed outcome does not cite an expected effect")
            if effect_id in observed_outcome_by_effect:
                raise ValueError("operational lineage outcomes MUST cite unique expected effects")
            observed_outcome_by_effect[effect_id] = observed_outcome
            if observed_outcome.properties.get("verification") != "independent":
                raise ValueError("operational lineage requires an independent observation")
        if set(observed_outcome_by_effect) != set(expected_effect_ids):
            raise ValueError("operational lineage does not observe every expected effect")
        object.__setattr__(
            self,
            "observed_outcomes",
            tuple(observed_outcome_by_effect[effect_id] for effect_id in expected_effect_ids),
        )
        object_ids = tuple(item.id for item in self.objects)
        if len(object_ids) != len(set(object_ids)):
            raise ValueError("operational lineage object ids MUST be unique")

    @property
    def objects(self) -> tuple[OntologyObjectRecord, ...]:
        """Return the existing episode records in deterministic lineage order."""

        return (
            self.decision_case,
            self.action_option,
            *self.expected_effects,
            self.action_run,
            *self.observed_outcomes,
        )

    @property
    def links(self) -> tuple[OntologyLinkRecord, ...]:
        """Return the authority-free relationships that make the episode replayable."""

        return (
            OntologyLinkRecord("considers", self.decision_case.id, self.action_option.id),
            *(
                OntologyLinkRecord("expects", self.action_option.id, expected_effect.id)
                for expected_effect in self.expected_effects
            ),
            OntologyLinkRecord("executed_as", self.action_option.id, self.action_run.id),
            *(
                OntologyLinkRecord("resulted_in", self.action_run.id, observed_outcome.id)
                for observed_outcome in self.observed_outcomes
            ),
        )


class OperationalHypothesisLineageProjector:
    """Append one validated episode through the store's atomic subgraph contract."""

    def __init__(self, *, store: OntologyInstanceStore) -> None:
        self._store = store

    async def project_prospective(self, lineage: OperationalProspectiveLineage) -> None:
        """Persist the complete pre-execution subgraph idempotently."""

        await self._project_objects(
            objects=lineage.objects,
            links=lineage.links,
            action_option=lineage.action_option,
        )

    async def project(self, lineage: OperationalHypothesisLineage) -> None:
        """Append missing objects and idempotently restore their typed links."""

        await self._project_objects(
            objects=lineage.objects,
            links=lineage.links,
            action_option=lineage.action_option,
        )

    async def _project_objects(
        self,
        *,
        objects: tuple[OntologyObjectRecord, ...],
        links: tuple[OntologyLinkRecord, ...],
        action_option: OntologyObjectRecord,
    ) -> None:
        missing: list[OntologyObjectRecord] = []
        for record in objects:
            existing = await self._store.get_object(record.id)
            if existing is None:
                if record is action_option and not _uses_plural_effect_refs(record):
                    raise ValueError(
                        "new action option lineage requires plural expected-effect references"
                    )
                missing.append(record)
                continue
            if not _same_immutable_object(existing, record):
                raise OperationalHypothesisLineageConflictError(
                    f"immutable operational lineage object changed: {record.id}"
                )
        await self._store.replace_subgraph(
            objects=tuple(missing),
            links=links,
        )


def _require_type(record: OntologyObjectRecord, expected: str) -> None:
    if record.object_type != expected:
        raise ValueError(f"operational lineage requires {expected}, got {record.object_type}")


def _expected_effect_refs(properties: Mapping[str, object]) -> tuple[str, ...]:
    plural = properties.get("expected_effect_refs")
    singular = properties.get("expected_effect_ref")
    if plural is not None and singular is not None:
        raise ValueError("action option expected-effect references are ambiguous")
    if plural is not None:
        return _text_refs(plural)
    if isinstance(singular, str) and singular:
        return (singular,)
    return ()


def _uses_plural_effect_refs(record: OntologyObjectRecord) -> bool:
    return record.properties.get("expected_effect_refs") is not None


def _text_refs(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple) or not value:
        return ()
    if any(not isinstance(item, str) or not item for item in value):
        return ()
    return tuple(value)


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
    "OperationalProspectiveLineage",
    "OperationalProspectiveLineageSource",
]
