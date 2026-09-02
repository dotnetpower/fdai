"""Append-only bitemporal operational state-transition evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from fdai.core.ontology_platform.functions import (
    ContextualOntologyFunction,
    FunctionInvocationContext,
)
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.core.ontology_platform.query_values import QueryRow, QueryTable
from fdai.shared.contracts.models import (
    CeilingRole,
    LogicExecutionClass,
    OntologyDeclarationKind,
    OntologyFunctionKind,
    OntologyFunctionType,
    OntologyRelease,
)

RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME = "query.resource_state_transitions"
RESOURCE_STATE_TRANSITION_TYPE = "resource.operational_state"
_MAX_TRANSITIONS = 512
_MAX_TEXT = 512


class StateTransitionLane(StrEnum):
    """Authority-separated transition lane."""

    OBSERVED = "observed"
    DERIVED = "derived"


class StateTransitionAuthority(StrEnum):
    """Authority classes allowed to originate transition facts."""

    PROVIDER = "provider"
    TELEMETRY = "telemetry"
    DETERMINISTIC_FUNCTION = "deterministic_function"


_LANE_AUTHORITIES = {
    StateTransitionLane.OBSERVED: frozenset(
        {StateTransitionAuthority.PROVIDER, StateTransitionAuthority.TELEMETRY}
    ),
    StateTransitionLane.DERIVED: frozenset({StateTransitionAuthority.DETERMINISTIC_FUNCTION}),
}


@dataclass(frozen=True, slots=True)
class OperationalStateTransition:
    """One immutable semantic state edge with event and record time."""

    transition_id: str
    idempotency_key: str
    subject_ref: str
    subject_type: str
    state_type: str
    from_state: str
    to_state: str
    lane: StateTransitionLane
    authority: StateTransitionAuthority
    effective_at: datetime
    evidence_cutoff: datetime
    recorded_at: datetime
    source_identity: str
    source_revision: str
    producer_id: str
    producer_version: str
    freshness_ceiling_seconds: int
    completeness_basis_points: int
    evidence_refs: tuple[str, ...]
    conflicts: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()
    synthetic: bool = False
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        for name, value in (
            ("idempotency_key", self.idempotency_key),
            ("subject_ref", self.subject_ref),
            ("subject_type", self.subject_type),
            ("state_type", self.state_type),
            ("from_state", self.from_state),
            ("to_state", self.to_state),
            ("source_identity", self.source_identity),
            ("source_revision", self.source_revision),
            ("producer_id", self.producer_id),
            ("producer_version", self.producer_version),
        ):
            _bounded(name, value)
        if self.from_state == self.to_state:
            raise ValueError("state transition MUST change state")
        if self.authority not in _LANE_AUTHORITIES[self.lane]:
            raise ValueError("state transition authority is invalid for its lane")
        _times(self.effective_at, self.evidence_cutoff, self.recorded_at)
        if not 1 <= self.freshness_ceiling_seconds <= 31_536_000:
            raise ValueError("state transition freshness ceiling is out of bounds")
        if not 0 <= self.completeness_basis_points <= 10_000:
            raise ValueError("state transition completeness is out of bounds")
        _refs("evidence_refs", self.evidence_refs, required=True)
        _refs("conflicts", self.conflicts)
        _refs("correlation_refs", self.correlation_refs)
        if self.execution_authority is not False:
            raise ValueError("state transition MUST NOT grant execution authority")
        if self.transition_id != self.expected_id:
            raise ValueError("state transition id does not match its content")

    @property
    def expected_id(self) -> str:
        return _digest(self._identity_body())

    def _identity_body(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "idempotency_key": self.idempotency_key,
            "subject_ref": self.subject_ref,
            "subject_type": self.subject_type,
            "state_type": self.state_type,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "lane": self.lane.value,
            "authority": self.authority.value,
            "effective_at": _timestamp(self.effective_at),
            "evidence_cutoff": _timestamp(self.evidence_cutoff),
            "recorded_at": _timestamp(self.recorded_at),
            "source_identity": self.source_identity,
            "source_revision": self.source_revision,
            "producer_id": self.producer_id,
            "producer_version": self.producer_version,
            "freshness_ceiling_seconds": self.freshness_ceiling_seconds,
            "completeness_basis_points": self.completeness_basis_points,
            "evidence_refs": list(self.evidence_refs),
            "conflicts": list(self.conflicts),
            "correlation_refs": list(self.correlation_refs),
            "synthetic": self.synthetic,
            "execution_authority": False,
        }

    @classmethod
    def create(cls, **values: Any) -> OperationalStateTransition:
        normalized = {
            "conflicts": (),
            "correlation_refs": (),
            "synthetic": False,
            "execution_authority": False,
            **values,
        }
        body = _transition_identity_body(normalized)
        return cls(transition_id=_digest(body), **normalized)


@dataclass(frozen=True, slots=True)
class StateTransitionCoverage:
    """Positive coverage proof for one subject and state family."""

    coverage_id: str
    subject_ref: str
    state_type: str
    coverage_start_at: datetime
    coverage_end_at: datetime
    recorded_at: datetime
    source_identity: str
    source_revision: str
    watermark: str
    evidence_ref: str
    complete: bool
    limitation: str | None = None
    synthetic: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("subject_ref", self.subject_ref),
            ("state_type", self.state_type),
            ("source_identity", self.source_identity),
            ("source_revision", self.source_revision),
            ("watermark", self.watermark),
            ("evidence_ref", self.evidence_ref),
        ):
            _bounded(name, value)
        _times(self.coverage_start_at, self.coverage_end_at, self.recorded_at)
        if self.coverage_end_at < self.coverage_start_at:
            raise ValueError("state transition coverage cannot move backward")
        if self.complete == (self.limitation is not None):
            raise ValueError("state transition coverage limitation is inconsistent")
        if self.limitation is not None:
            _bounded("limitation", self.limitation, maximum=128)
        if self.coverage_id != self.expected_id:
            raise ValueError("state transition coverage id does not match its content")

    @property
    def expected_id(self) -> str:
        return _digest(
            {
                "subject_ref": self.subject_ref,
                "state_type": self.state_type,
                "coverage_start_at": _timestamp(self.coverage_start_at),
                "coverage_end_at": _timestamp(self.coverage_end_at),
                "recorded_at": _timestamp(self.recorded_at),
                "source_identity": self.source_identity,
                "source_revision": self.source_revision,
                "watermark": self.watermark,
                "evidence_ref": self.evidence_ref,
                "complete": self.complete,
                "limitation": self.limitation,
                "synthetic": self.synthetic,
            }
        )

    @classmethod
    def create(cls, **values: Any) -> StateTransitionCoverage:
        normalized = {"limitation": None, "synthetic": False, **values}
        body = {
            key: (_timestamp(value) if isinstance(value, datetime) else value)
            for key, value in normalized.items()
        }
        return cls(coverage_id=_digest(body), **normalized)


@dataclass(frozen=True, slots=True)
class StateTransitionBatch:
    """One atomic append of transition facts and their positive coverage."""

    batch_id: str
    transitions: tuple[OperationalStateTransition, ...]
    coverage: tuple[StateTransitionCoverage, ...]
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not self.coverage or len(self.transitions) > _MAX_TRANSITIONS:
            raise ValueError(
                "state transition batch requires coverage and a bounded transition set"
            )
        if any(item.recorded_at != self.recorded_at for item in self.transitions):
            raise ValueError("state transition recorded time does not match its batch")
        if any(item.recorded_at != self.recorded_at for item in self.coverage):
            raise ValueError("state transition coverage time does not match its batch")
        if len({item.idempotency_key for item in self.transitions}) != len(self.transitions):
            raise ValueError("state transition batch idempotency keys MUST be unique")
        if self.batch_id != self.expected_id:
            raise ValueError("state transition batch id does not match its content")

    @property
    def expected_id(self) -> str:
        return _digest(
            {
                "recorded_at": _timestamp(self.recorded_at),
                "transitions": [item.transition_id for item in self.transitions],
                "coverage": [item.coverage_id for item in self.coverage],
            }
        )

    @classmethod
    def create(
        cls,
        *,
        transitions: tuple[OperationalStateTransition, ...],
        coverage: tuple[StateTransitionCoverage, ...],
        recorded_at: datetime,
    ) -> StateTransitionBatch:
        batch_id = _digest(
            {
                "recorded_at": _timestamp(recorded_at),
                "transitions": [item.transition_id for item in transitions],
                "coverage": [item.coverage_id for item in coverage],
            }
        )
        return cls(
            batch_id=batch_id,
            transitions=transitions,
            coverage=coverage,
            recorded_at=recorded_at,
        )


@dataclass(frozen=True, slots=True)
class StateTransitionRead:
    transitions: tuple[OperationalStateTransition, ...]
    coverage: tuple[StateTransitionCoverage, ...]
    complete: bool
    limitation: str | None

    def __post_init__(self) -> None:
        if self.complete == (self.limitation is not None):
            raise ValueError("state transition read limitation is inconsistent")


class StateTransitionStore(Protocol):
    async def append(self, batch: StateTransitionBatch) -> bool: ...

    async def read(
        self,
        *,
        subject_refs: tuple[str, ...],
        state_types: tuple[str, ...],
        to_states: tuple[str, ...],
        start_at: datetime,
        end_at: datetime,
        known_at: datetime,
        limit: int,
    ) -> StateTransitionRead: ...


def state_at(
    transitions: Sequence[OperationalStateTransition],
    *,
    subject_ref: str,
    state_type: str,
    effective_at: datetime,
    known_at: datetime,
) -> str | None:
    """Return the latest recorded state at both bitemporal cutoffs."""

    eligible = [
        item
        for item in transitions
        if item.subject_ref == subject_ref
        and item.state_type == state_type
        and item.effective_at <= effective_at
        and item.recorded_at <= known_at
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (item.effective_at, item.recorded_at, item.transition_id),
    ).to_state


def resource_state_transitions_function_type() -> OntologyFunctionType:
    return OntologyFunctionType(
        name=RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
        version="1.0.0",
        kind=OntologyFunctionKind.QUERY,
        artifact_digest=f"sha256:{hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}",
        publisher="fdai",
        input_schema={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "query_result",
                "state_types",
                "to_states",
                "start_at",
                "end_at",
                "known_at",
                "limit",
            ],
            "properties": {
                "query_result": {"type": "object", "x-fdai-dependency-only": True},
                "state_types": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 16,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_.-]{0,127}$"},
                },
                "to_states": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 16,
                    "uniqueItems": True,
                    "items": {"type": "string", "pattern": r"^[a-z][a-z0-9_.-]{0,127}$"},
                },
                "start_at": {"type": "string", "format": "date-time"},
                "end_at": {"type": "string", "format": "date-time"},
                "known_at": {"type": "string", "format": "date-time"},
                "limit": {"type": "integer", "minimum": 1, "maximum": _MAX_TRANSITIONS},
            },
        },
        output_schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["rows", "complete", "truncation_reason"],
            "properties": {
                "rows": {"type": "array", "maxItems": _MAX_TRANSITIONS},
                "complete": {"type": "boolean"},
                "truncation_reason": {"type": ["string", "null"]},
            },
        },
        read_sets=["Resource"],
        execution_class=LogicExecutionClass.DETERMINISTIC,
        required_role=CeilingRole.READER,
        purpose_bindings=["operations-review"],
        timeout_seconds=10,
        cpu_millis=250,
        memory_bytes=67_108_864,
        max_output_bytes=1_048_576,
        network_allowed=False,
        credentials_allowed=False,
    )


def resource_state_transitions_function(
    release: OntologyRelease,
    *,
    reader: StateTransitionStore,
) -> ContextualOntologyFunction:
    release.type_ref(
        OntologyDeclarationKind.FUNCTION,
        RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME,
    )

    async def evaluate(
        arguments: Mapping[str, Any],
        context: FunctionInvocationContext,
    ) -> object:
        if context.purposes != ("operations-review",):
            raise PermissionError("state transition purpose does not match invocation context")
        secured = SecuredObjectSetQueryResult.model_validate(arguments["query_result"])
        if secured.receipt.truncated or not secured.receipt.complete:
            return _table((), complete=False, limitation="resource_scope_incomplete")
        subject_refs = tuple(sorted(item.id for item in secured.materialization.graph.objects))
        if not subject_refs:
            return _table((), complete=True, limitation=None)
        to_states = tuple(sorted(str(item) for item in arguments["to_states"]))
        result = await reader.read(
            subject_refs=subject_refs,
            state_types=tuple(sorted(str(item) for item in arguments["state_types"])),
            to_states=to_states,
            start_at=_parse_time(arguments["start_at"], "start_at"),
            end_at=_parse_time(arguments["end_at"], "end_at"),
            known_at=_parse_time(arguments["known_at"], "known_at"),
            limit=int(arguments["limit"]),
        )
        rows = tuple(
            QueryRow.from_values(
                f"state-transition-{index:04d}",
                {
                    "transition_id": item.transition_id,
                    "subject_ref": item.subject_ref,
                    "subject_type": item.subject_type,
                    "state_type": item.state_type,
                    "from_state": item.from_state,
                    "to_state": item.to_state,
                    "lane": item.lane.value,
                    "authority": item.authority.value,
                    "effective_at": _timestamp(item.effective_at),
                    "recorded_at": _timestamp(item.recorded_at),
                    "source_identity": item.source_identity,
                    "source_revision": item.source_revision,
                    "evidence_refs": list(item.evidence_refs),
                    "complete": item.completeness_basis_points == 10_000,
                    "conflicts": list(item.conflicts),
                    "synthetic": item.synthetic,
                    "execution_authority": False,
                },
            )
            for index, item in enumerate(result.transitions, start=1)
        )
        return _table(rows, complete=result.complete, limitation=result.limitation)

    return evaluate


def _table(
    rows: tuple[QueryRow, ...],
    *,
    complete: bool,
    limitation: str | None,
) -> dict[str, object]:
    table = QueryTable(rows=rows, complete=complete, truncation_reason=limitation)
    return cast(dict[str, object], json.loads(table.canonical_json()))


def _parse_time(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"state transition {name} MUST be RFC 3339")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"state transition {name} MUST be RFC 3339") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"state transition {name} MUST include a timezone")
    return result.astimezone(UTC)


def _times(effective_at: datetime, evidence_cutoff: datetime, recorded_at: datetime) -> None:
    timestamps = (effective_at, evidence_cutoff, recorded_at)
    if any(item.tzinfo is None or item.utcoffset() is None for item in timestamps):
        raise ValueError("state transition timestamps MUST include a timezone")
    if not effective_at <= evidence_cutoff <= recorded_at:
        raise ValueError("state transition timestamps are not causally ordered")


def _bounded(name: str, value: str, *, maximum: int = _MAX_TEXT) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"state transition {name} MUST be bounded non-empty text")


def _refs(name: str, values: tuple[str, ...], *, required: bool = False) -> None:
    if required and not values:
        raise ValueError(f"state transition {name} MUST be non-empty")
    if values != tuple(sorted(set(values))) or len(values) > 64:
        raise ValueError(f"state transition {name} MUST be unique, ordered, and bounded")
    for value in values:
        _bounded(name, value)


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _transition_identity_body(values: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "idempotency_key": values["idempotency_key"],
        "subject_ref": values["subject_ref"],
        "subject_type": values["subject_type"],
        "state_type": values["state_type"],
        "from_state": values["from_state"],
        "to_state": values["to_state"],
        "lane": cast(StateTransitionLane, values["lane"]).value,
        "authority": cast(StateTransitionAuthority, values["authority"]).value,
        "effective_at": _timestamp(cast(datetime, values["effective_at"])),
        "evidence_cutoff": _timestamp(cast(datetime, values["evidence_cutoff"])),
        "recorded_at": _timestamp(cast(datetime, values["recorded_at"])),
        "source_identity": values["source_identity"],
        "source_revision": values["source_revision"],
        "producer_id": values["producer_id"],
        "producer_version": values["producer_version"],
        "freshness_ceiling_seconds": values["freshness_ceiling_seconds"],
        "completeness_basis_points": values["completeness_basis_points"],
        "evidence_refs": list(cast(tuple[str, ...], values["evidence_refs"])),
        "conflicts": list(cast(tuple[str, ...], values["conflicts"])),
        "correlation_refs": list(cast(tuple[str, ...], values["correlation_refs"])),
        "synthetic": values["synthetic"],
        "execution_authority": False,
    }


__all__ = [
    "OperationalStateTransition",
    "RESOURCE_STATE_TRANSITIONS_FUNCTION_NAME",
    "RESOURCE_STATE_TRANSITION_TYPE",
    "StateTransitionAuthority",
    "StateTransitionBatch",
    "StateTransitionCoverage",
    "StateTransitionLane",
    "StateTransitionRead",
    "StateTransitionStore",
    "resource_state_transitions_function",
    "resource_state_transitions_function_type",
    "state_at",
]
