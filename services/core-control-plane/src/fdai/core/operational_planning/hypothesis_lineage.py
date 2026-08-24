"""Immutable ontology lineage from an operational decision to its observed outcome."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from fdai.shared.contracts.models import Action, ResponseOutcome, ResponseOutcomeLabel
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


class OperationalProspectiveLineageSource(Protocol):
    """Resolve already-produced Forseti records for one execution correlation."""

    async def resolve(self, correlation_id: str) -> OperationalProspectiveLineage | None: ...


class OperationalOutcomeLineageSink(Protocol):
    """Receive one actual execution and its independently observed outcome."""

    async def __call__(
        self,
        *,
        correlation_id: str,
        action: Action,
        execution_status: str,
        execution_started_at: datetime,
        execution_ended_at: datetime,
        response_outcome: ResponseOutcome,
        execution_receipt_ref: str | None = None,
    ) -> bool: ...


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

    async def project(self, lineage: OperationalHypothesisLineage) -> None:
        """Append missing objects and idempotently restore their typed links."""

        missing: list[OntologyObjectRecord] = []
        for record in lineage.objects:
            existing = await self._store.get_object(record.id)
            if existing is None:
                if record is lineage.action_option and not _uses_plural_effect_refs(record):
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
            links=lineage.links,
        )


class OperationalOutcomeLineageProducer:
    """Append a complete episode only when its prospective records already exist."""

    def __init__(
        self,
        *,
        prospective_source: OperationalProspectiveLineageSource,
        projector: OperationalHypothesisLineageProjector,
    ) -> None:
        self._prospective_source = prospective_source
        self._projector = projector

    async def __call__(
        self,
        *,
        correlation_id: str,
        action: Action,
        execution_status: str,
        execution_started_at: datetime,
        execution_ended_at: datetime,
        response_outcome: ResponseOutcome,
        execution_receipt_ref: str | None = None,
    ) -> bool:
        """Project one exact closure, or return false when no prospective episode exists."""

        if not correlation_id:
            raise ValueError("operational lineage correlation id MUST be non-empty")
        prospective = await self._prospective_source.resolve(correlation_id)
        if prospective is None:
            return False
        lineage = build_executed_operational_lineage(
            prospective=prospective,
            action=action,
            execution_status=execution_status,
            execution_started_at=execution_started_at,
            execution_ended_at=execution_ended_at,
            response_outcome=response_outcome,
            execution_receipt_ref=execution_receipt_ref,
        )
        await self._projector.project(lineage)
        return True


def build_executed_operational_lineage(
    *,
    prospective: OperationalProspectiveLineage,
    action: Action,
    execution_status: str,
    execution_started_at: datetime,
    execution_ended_at: datetime,
    response_outcome: ResponseOutcome,
    execution_receipt_ref: str | None = None,
) -> OperationalHypothesisLineage:
    """Close one single-effect episode from owned execution and observation values.

    The producer refuses ambiguous or incomplete joins. In particular, it does
    not infer a missing effect, ActionType version, execution timestamp, or
    independent observation from the prospective records.
    """

    if action.action_type_ref is None:
        raise ValueError("executed lineage requires an exact ActionType reference")
    if not execution_status:
        raise ValueError("executed lineage requires an execution status")
    if (
        execution_started_at.tzinfo is None
        or execution_ended_at.tzinfo is None
        or execution_ended_at < execution_started_at
        or execution_started_at < action.created_at
    ):
        raise ValueError("executed lineage requires ordered timezone-aware execution timestamps")
    if prospective.decision_case.properties.get("target_ref") != action.target_resource_ref:
        raise ValueError("executed lineage target does not match the decision case")
    if prospective.action_option.properties.get("action_type_ref") != action.action_type:
        raise ValueError("executed lineage action does not match the selected option")
    if prospective.action_option.properties.get("arguments") != action.params:
        raise ValueError("executed lineage arguments do not match the selected option")
    if (
        response_outcome.action_id != action.action_id
        or response_outcome.action_type_id != action.action_type
        or response_outcome.execution_mode is not action.mode
        or response_outcome.target_digest
        != hashlib.sha256(action.target_resource_ref.encode()).hexdigest()
    ):
        raise ValueError("response outcome does not match the executed Action")
    if (
        response_outcome.label is ResponseOutcomeLabel.UNSCORABLE
        or response_outcome.metric is None
        or response_outcome.expected_min is None
        or response_outcome.expected_max is None
        or response_outcome.predicted_at is None
        or response_outcome.observation_deadline is None
        or response_outcome.observed_value is None
        or response_outcome.observed_at is None
    ):
        raise ValueError("executed lineage requires one scorable independent outcome")
    if len(prospective.expected_effects) != 1:
        raise ValueError("executed lineage currently requires exactly one expected effect")

    expected_effect = prospective.expected_effects[0]
    expected_window = response_outcome.observation_deadline - response_outcome.predicted_at
    if expected_window.total_seconds() != int(expected_window.total_seconds()) or (
        expected_effect.properties.get("metric") != response_outcome.metric
        or expected_effect.properties.get("lower_bound") != response_outcome.expected_min
        or expected_effect.properties.get("upper_bound") != response_outcome.expected_max
        or expected_effect.properties.get("window_seconds") != int(expected_window.total_seconds())
        or expected_effect.properties.get("created_at") != response_outcome.predicted_at
    ):
        raise ValueError("response outcome does not match the expected effect")

    action_run_properties: dict[str, object] = {
        "id": str(action.action_id),
        "action_type_ref": action.action_type,
        "action_type_version": action.action_type_ref.version,
        "target_ref": action.target_resource_ref,
        "status": execution_status,
        "mode": action.mode.value,
        "idempotency_key": action.idempotency_key,
        "started_at": execution_started_at,
        "ended_at": execution_ended_at,
    }
    if execution_receipt_ref is not None:
        action_run_properties["receipt_ref"] = execution_receipt_ref
    action_run = OntologyObjectRecord(
        str(action.action_id),
        "ActionRun",
        action_run_properties,
    )
    recovery_status = (
        "succeeded"
        if response_outcome.rollback_succeeded is True
        else "failed"
        if response_outcome.rollback_succeeded is False
        else "not_observed"
    )
    observed_outcome = OntologyObjectRecord(
        str(response_outcome.outcome_id),
        "ObservedOutcome",
        {
            "id": str(response_outcome.outcome_id),
            "action_run_id": action_run.id,
            "expected_effect_ref": expected_effect.id,
            "verification": "independent",
            "recovery_status": recovery_status,
            "observed_values": {response_outcome.metric: response_outcome.observed_value},
            "telemetry_complete": False,
            "scorable": response_outcome.scorable,
            "observed_at": response_outcome.observed_at,
        },
    )
    return OperationalHypothesisLineage(
        decision_case=prospective.decision_case,
        action_option=prospective.action_option,
        expected_effects=prospective.expected_effects,
        action_run=action_run,
        observed_outcomes=(observed_outcome,),
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
    "OperationalOutcomeLineageSink",
    "OperationalOutcomeLineageProducer",
    "OperationalProspectiveLineage",
    "OperationalProspectiveLineageSource",
    "build_executed_operational_lineage",
]
