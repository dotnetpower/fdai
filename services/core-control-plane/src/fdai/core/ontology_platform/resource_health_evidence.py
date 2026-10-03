"""Exact-denominator Resource Health evidence contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Protocol

_MAX_RESOURCES = 1000
_MAX_NARRATION_CHARS = 8000
_DEFAULT_RESOURCE_HEALTH_QUERY_REVISION = "azure-resource-health-arg-v1"
_DEFAULT_RESOURCE_HEALTH_COVERAGE_CONTRACT = "resource-health-exact-denominator-v1"
_UNSAFE_FENCE_STATUSES: frozenset[ResourceHealthCoverageStatus]


class ResourceHealthAvailabilityState(StrEnum):
    """Canonical Azure Resource Health availability states."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"
    STATE_ABSENT = "state_absent"


class ResourceHealthCoverageStatus(StrEnum):
    """Per-target collection disposition within the exact authorized denominator."""

    OBSERVED = "observed"
    STATE_ABSENT = "state_absent"
    NO_RECORD = "no_record"
    NOT_MODELED = "not_modeled"
    MODELING_UNKNOWN = "modeling_unknown"
    SCOPE_UNREADABLE = "scope_unreadable"
    TARGET_UNRESOLVED = "target_unresolved"
    DUPLICATE_RECORD = "duplicate_record"
    RESPONSE_INVALID = "response_invalid"
    RESPONSE_TRUNCATED = "response_truncated"
    STATE_CHANGED = "state_changed"


class ResourceHealthTerminalDisposition(StrEnum):
    """Deterministic terminal disposition for an answer over a typed receipt."""

    ALL_CLEAR = "all_clear"
    NON_HEALTHY = "non_healthy"
    INCOMPLETE_DENOMINATOR = "incomplete_denominator"
    STATE_CHANGED = "state_changed"


@dataclass(frozen=True, slots=True)
class ResourceHealthObservation:
    """One normalized Resource Health status bound to a requested logical resource."""

    resource_id: str
    availability_state: ResourceHealthAvailabilityState
    reason_kind: str
    provider_observed_at: datetime | None
    evidence_ref: str

    def __post_init__(self) -> None:
        for name, value, maximum in (
            ("resource_id", self.resource_id, 1024),
            ("availability_state", self.availability_state, 64),
            ("reason_kind", self.reason_kind, 64),
            ("evidence_ref", self.evidence_ref, 256),
        ):
            if not value.strip() or len(value) > maximum:
                raise ValueError(f"Resource Health {name} MUST be bounded and non-empty")
        if not isinstance(self.availability_state, ResourceHealthAvailabilityState):
            raise ValueError("Resource Health availability_state MUST be canonical")
        if self.provider_observed_at is not None and self.provider_observed_at.tzinfo is None:
            raise ValueError("Resource Health provider_observed_at MUST be timezone-aware")


@dataclass(frozen=True, slots=True)
class ResourceHealthCoverage:
    """One exact target's collection disposition without inferring provider support."""

    resource_id: str
    status: ResourceHealthCoverageStatus

    def __post_init__(self) -> None:
        if not self.resource_id.strip() or len(self.resource_id) > 1024:
            raise ValueError("Resource Health coverage resource_id MUST be bounded and non-empty")
        if not isinstance(self.status, ResourceHealthCoverageStatus):
            raise ValueError("Resource Health coverage status MUST be canonical")


@dataclass(frozen=True, slots=True)
class ResourceHealthCollection:
    """Bounded provider result over the exact requested denominator and observation window."""

    resource_ids: tuple[str, ...]
    observations: tuple[ResourceHealthObservation, ...]
    coverage: tuple[ResourceHealthCoverage, ...]
    started_at: datetime
    completed_at: datetime
    attempt_ref: str
    query_revision: str = _DEFAULT_RESOURCE_HEALTH_QUERY_REVISION
    coverage_contract: str = _DEFAULT_RESOURCE_HEALTH_COVERAGE_CONTRACT
    deadline_at: datetime | None = None
    issues: tuple[str, ...] = ()
    execution_authority: Literal[False] = False
    target_set_digest: str = field(init=False)
    complete: bool = field(init=False)
    limitation: str | None = field(init=False)

    def __post_init__(self) -> None:
        if not self.resource_ids or len(self.resource_ids) > _MAX_RESOURCES:
            raise ValueError("Resource Health scope MUST contain between 1 and 1000 resources")
        if self.resource_ids != tuple(sorted(set(self.resource_ids))):
            raise ValueError("Resource Health scope MUST be unique and ordered")
        object.__setattr__(self, "target_set_digest", _target_set_digest(self.resource_ids))
        observed_ids = tuple(item.resource_id for item in self.observations)
        if len(observed_ids) != len(set(observed_ids)):
            raise ValueError("Resource Health observations MUST be unique by resource")
        if not set(observed_ids) <= set(self.resource_ids):
            raise ValueError("Resource Health observations widened the requested scope")
        coverage_ids = tuple(item.resource_id for item in self.coverage)
        if coverage_ids != self.resource_ids:
            raise ValueError("Resource Health coverage MUST equal the exact requested scope")
        coverage_by_id = {item.resource_id: item.status for item in self.coverage}
        for observation in self.observations:
            status = coverage_by_id[observation.resource_id]
            if observation.availability_state is ResourceHealthAvailabilityState.STATE_ABSENT:
                if status is not ResourceHealthCoverageStatus.STATE_ABSENT:
                    raise ValueError(
                        "Resource Health blank state MUST retain state_absent coverage"
                    )
            elif observation.provider_observed_at is None:
                if status is not ResourceHealthCoverageStatus.RESPONSE_INVALID:
                    raise ValueError(
                        "Resource Health missing provider time MUST retain "
                        "response_invalid coverage"
                    )
            elif status is not ResourceHealthCoverageStatus.OBSERVED:
                raise ValueError("Resource Health observation coverage MUST be observed")
        observation_ids = set(observed_ids)
        if any(
            item.resource_id not in observation_ids
            for item in self.coverage
            if item.status
            in {
                ResourceHealthCoverageStatus.OBSERVED,
                ResourceHealthCoverageStatus.STATE_ABSENT,
            }
        ):
            raise ValueError("Resource Health observed coverage MUST carry an observation")
        if any(
            item.resource_id in observation_ids
            for item in self.coverage
            if item.status
            not in {
                ResourceHealthCoverageStatus.OBSERVED,
                ResourceHealthCoverageStatus.STATE_ABSENT,
                ResourceHealthCoverageStatus.RESPONSE_INVALID,
            }
        ):
            raise ValueError("Resource Health non-observed coverage MUST NOT carry an observation")
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("Resource Health collection window MUST be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("Resource Health collection window MUST NOT move backward")
        if self.deadline_at is not None and self.deadline_at.tzinfo is None:
            raise ValueError("Resource Health deadline MUST be timezone-aware")
        if self.issues != tuple(sorted(set(self.issues))):
            raise ValueError("Resource Health issues MUST be unique and ordered")
        if any(
            item not in {"provider_scope_mismatch", "response_invalid", "state_changed"}
            for item in self.issues
        ):
            raise ValueError("Resource Health issue is unsupported")
        if not self.attempt_ref.strip() or len(self.attempt_ref) > 256:
            raise ValueError("Resource Health attempt_ref MUST be bounded and non-empty")
        for name, value in (
            ("query_revision", self.query_revision),
            ("coverage_contract", self.coverage_contract),
        ):
            if not value.strip() or len(value) > 128:
                raise ValueError(f"Resource Health {name} MUST be bounded and non-empty")
        if self.execution_authority is not False:
            raise ValueError("Resource Health collection MUST NOT grant execution authority")
        limitations = tuple(
            dict.fromkeys(
                (
                    *self.issues,
                    *(
                        item.status.value
                        for item in self.coverage
                        if item.status is not ResourceHealthCoverageStatus.OBSERVED
                    ),
                )
            )
        )
        object.__setattr__(self, "complete", not limitations)
        object.__setattr__(self, "limitation", "+".join(limitations) if limitations else None)


class ResourceHealthCollectionReader(Protocol):
    """Read current provider health for an exact server-selected resource set."""

    async def read_current(
        self,
        *,
        resource_ids: tuple[str, ...],
    ) -> ResourceHealthCollection: ...


@dataclass(frozen=True, slots=True)
class ResourceHealthNarrationClaims:
    """Structured model-authored claims that accompany Resource Health narration text."""

    terminal_disposition: ResourceHealthTerminalDisposition
    all_clear: bool
    denominator_count: int
    observed_count: int
    reason_codes: tuple[str, ...]
    window_started_at: datetime
    window_completed_at: datetime
    execution_authority: bool

    def __post_init__(self) -> None:
        if not isinstance(self.terminal_disposition, ResourceHealthTerminalDisposition):
            raise ValueError("Resource Health terminal disposition MUST be canonical")
        if self.denominator_count < 0 or self.observed_count < 0:
            raise ValueError("Resource Health narration counts MUST be non-negative")
        if self.reason_codes != tuple(sorted(set(self.reason_codes))):
            raise ValueError("Resource Health narration reason codes MUST be unique and ordered")
        if any(not item.strip() or len(item) > 256 for item in self.reason_codes):
            raise ValueError("Resource Health narration reason codes MUST be bounded")
        for name, value in (
            ("window_started_at", self.window_started_at),
            ("window_completed_at", self.window_completed_at),
        ):
            if value.tzinfo is None:
                raise ValueError(f"Resource Health narration {name} MUST be timezone-aware")
        if self.window_completed_at < self.window_started_at:
            raise ValueError("Resource Health narration window MUST NOT move backward")


@dataclass(frozen=True, slots=True)
class ResourceHealthAnswerValidation:
    """Fail-closed Resource Health answer validation outcome."""

    accepted: bool
    terminal_disposition: ResourceHealthTerminalDisposition
    replacement_claim: str
    preserved_reasons: tuple[str, ...]
    violations: tuple[str, ...]
    execution_authority: Literal[False] = False


async def read_current_with_reread_fence(
    reader: ResourceHealthCollectionReader,
    *,
    resource_ids: tuple[str, ...],
    deadline_at: datetime,
    query_revision: str = _DEFAULT_RESOURCE_HEALTH_QUERY_REVISION,
    coverage_contract: str = _DEFAULT_RESOURCE_HEALTH_COVERAGE_CONTRACT,
    clock: Callable[[], datetime] | None = None,
) -> ResourceHealthCollection:
    """Read an exact Resource Health tuple set twice and fail closed on drift."""

    if resource_ids != tuple(sorted(set(resource_ids))):
        raise ValueError("Resource Health reread fence scope MUST be unique and ordered")
    if deadline_at.tzinfo is None:
        raise ValueError("Resource Health reread fence deadline MUST be timezone-aware")
    now = clock or (lambda: datetime.now(UTC))
    attempts: list[ResourceHealthCollection] = []

    async def read_once() -> ResourceHealthCollection:
        if _aware_utc(now()) > deadline_at:
            return _state_changed_collection(
                resource_ids,
                attempts=tuple(attempts),
                deadline_at=deadline_at,
                query_revision=query_revision,
                coverage_contract=coverage_contract,
                clock=now,
            )
        collection = await reader.read_current(resource_ids=resource_ids)
        bound = _bind_fence_contract(
            collection,
            deadline_at=deadline_at,
            query_revision=query_revision,
            coverage_contract=coverage_contract,
        )
        if bound.resource_ids != resource_ids:
            raise ValueError("Resource Health reader changed the secured resource scope")
        attempts.append(bound)
        return bound

    first = await read_once()
    second = await read_once()
    if first.issues == ("state_changed",) or second.issues == ("state_changed",):
        return second
    if _fence_digest(first) == _fence_digest(second):
        return second
    if _has_unsafe_fence_evidence((first, second)):
        return _state_changed_collection(
            resource_ids,
            attempts=(first, second),
            deadline_at=deadline_at,
            query_revision=query_revision,
            coverage_contract=coverage_contract,
            clock=now,
        )
    third = await read_once()
    if third.issues == ("state_changed",):
        return third
    if _fence_digest(second) == _fence_digest(third):
        return third
    return _state_changed_collection(
        resource_ids,
        attempts=(first, second, third),
        deadline_at=deadline_at,
        query_revision=query_revision,
        coverage_contract=coverage_contract,
        clock=now,
    )


def validate_resource_health_answer(
    collection: ResourceHealthCollection,
    *,
    narration: str,
    claims: ResourceHealthNarrationClaims | None,
) -> ResourceHealthAnswerValidation:
    """Validate Resource Health narration using only typed receipt fields and claims."""

    terminal = _terminal_disposition(collection)
    reasons = _preserved_reason_codes(collection)
    violations: list[str] = []
    if not narration.strip() or len(narration) > _MAX_NARRATION_CHARS:
        violations.append("narration_unbounded")
    if claims is None:
        violations.append("structured_claims_absent")
    else:
        observed_count = sum(
            1
            for item in collection.coverage
            if item.status is ResourceHealthCoverageStatus.OBSERVED
        )
        if claims.terminal_disposition is not terminal:
            violations.append("terminal_disposition_contradiction")
        if claims.all_clear and terminal is not ResourceHealthTerminalDisposition.ALL_CLEAR:
            violations.append("all_clear_claim_replaced")
        if claims.denominator_count != len(collection.resource_ids):
            violations.append("denominator_contradiction")
        if claims.observed_count != observed_count:
            violations.append("count_contradiction")
        if (
            claims.window_started_at != collection.started_at
            or claims.window_completed_at != collection.completed_at
        ):
            violations.append("time_window_contradiction")
        if claims.execution_authority is not False:
            violations.append("authority_contradiction")
        if claims.reason_codes != reasons:
            violations.append("reason_preservation_contradiction")
    unique = tuple(dict.fromkeys(violations))
    return ResourceHealthAnswerValidation(
        accepted=not unique,
        terminal_disposition=terminal,
        replacement_claim=_replacement_claim(terminal),
        preserved_reasons=reasons,
        violations=unique,
    )


def _target_set_digest(resource_ids: tuple[str, ...]) -> str:
    encoded = json.dumps(resource_ids, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Resource Health reread fence clock MUST be timezone-aware")
    return value.astimezone(UTC)


def _bind_fence_contract(
    collection: ResourceHealthCollection,
    *,
    deadline_at: datetime,
    query_revision: str,
    coverage_contract: str,
) -> ResourceHealthCollection:
    return ResourceHealthCollection(
        resource_ids=collection.resource_ids,
        observations=collection.observations,
        coverage=collection.coverage,
        started_at=collection.started_at,
        completed_at=collection.completed_at,
        attempt_ref=collection.attempt_ref,
        query_revision=query_revision,
        coverage_contract=coverage_contract,
        deadline_at=deadline_at,
        issues=collection.issues,
    )


def _fence_digest(collection: ResourceHealthCollection) -> str:
    tuples = tuple(
        sorted(
            (
                item.resource_id,
                item.availability_state.value,
                item.provider_observed_at.isoformat() if item.provider_observed_at else "",
            )
            for item in collection.observations
            if item.availability_state is not ResourceHealthAvailabilityState.STATE_ABSENT
        )
    )
    coverage = tuple(
        (item.resource_id, item.status.value)
        for item in collection.coverage
        if item.status is not ResourceHealthCoverageStatus.OBSERVED
    )
    payload = {
        "coverage": coverage,
        "coverage_contract": collection.coverage_contract,
        "deadline_at": collection.deadline_at.isoformat() if collection.deadline_at else None,
        "query_revision": collection.query_revision,
        "target_set_digest": collection.target_set_digest,
        "tuples": tuples,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(encoded.encode()).hexdigest()}"


def _has_unsafe_fence_evidence(collections: tuple[ResourceHealthCollection, ...]) -> bool:
    return any(item.status in _UNSAFE_FENCE_STATUSES for c in collections for item in c.coverage)


def _state_changed_collection(
    resource_ids: tuple[str, ...],
    *,
    attempts: tuple[ResourceHealthCollection, ...],
    deadline_at: datetime,
    query_revision: str,
    coverage_contract: str,
    clock: Callable[[], datetime],
) -> ResourceHealthCollection:
    started_at = attempts[0].started_at if attempts else _aware_utc(clock())
    completed_at = max(_aware_utc(clock()), started_at)
    material = "|".join(
        (
            "state_changed",
            _target_set_digest(resource_ids),
            query_revision,
            coverage_contract,
            deadline_at.isoformat(),
            *(_fence_digest(item) for item in attempts),
        )
    )
    return ResourceHealthCollection(
        resource_ids=resource_ids,
        observations=(),
        coverage=tuple(
            ResourceHealthCoverage(
                resource_id=resource_id,
                status=ResourceHealthCoverageStatus.STATE_CHANGED,
            )
            for resource_id in resource_ids
        ),
        started_at=started_at,
        completed_at=completed_at,
        attempt_ref=f"resource-health-reread-fence:{hashlib.sha256(material.encode()).hexdigest()}",
        query_revision=query_revision,
        coverage_contract=coverage_contract,
        deadline_at=deadline_at,
        issues=("state_changed",),
    )


def _terminal_disposition(
    collection: ResourceHealthCollection,
) -> ResourceHealthTerminalDisposition:
    if any(
        item.status is ResourceHealthCoverageStatus.STATE_CHANGED for item in collection.coverage
    ):
        return ResourceHealthTerminalDisposition.STATE_CHANGED
    if not collection.complete:
        return ResourceHealthTerminalDisposition.INCOMPLETE_DENOMINATOR
    if any(
        item.availability_state is not ResourceHealthAvailabilityState.AVAILABLE
        for item in collection.observations
    ):
        return ResourceHealthTerminalDisposition.NON_HEALTHY
    return ResourceHealthTerminalDisposition.ALL_CLEAR


def _preserved_reason_codes(collection: ResourceHealthCollection) -> tuple[str, ...]:
    reasons = [
        f"{item.resource_id}:coverage:{item.status.value}"
        for item in collection.coverage
        if item.status is not ResourceHealthCoverageStatus.OBSERVED
    ]
    reasons.extend(
        f"{item.resource_id}:availability:{item.availability_state.value}:{item.reason_kind}"
        for item in collection.observations
        if item.availability_state is not ResourceHealthAvailabilityState.AVAILABLE
    )
    return tuple(sorted(dict.fromkeys(reasons)))


def _replacement_claim(terminal: ResourceHealthTerminalDisposition) -> str:
    if terminal is ResourceHealthTerminalDisposition.ALL_CLEAR:
        return "resource_health_all_clear"
    if terminal is ResourceHealthTerminalDisposition.NON_HEALTHY:
        return "resource_health_non_healthy_targets"
    if terminal is ResourceHealthTerminalDisposition.STATE_CHANGED:
        return "resource_health_state_changed"
    return "resource_health_incomplete_denominator"


_UNSAFE_FENCE_STATUSES = frozenset(
    {
        ResourceHealthCoverageStatus.STATE_ABSENT,
        ResourceHealthCoverageStatus.NO_RECORD,
        ResourceHealthCoverageStatus.NOT_MODELED,
        ResourceHealthCoverageStatus.MODELING_UNKNOWN,
        ResourceHealthCoverageStatus.SCOPE_UNREADABLE,
        ResourceHealthCoverageStatus.TARGET_UNRESOLVED,
        ResourceHealthCoverageStatus.DUPLICATE_RECORD,
        ResourceHealthCoverageStatus.RESPONSE_INVALID,
        ResourceHealthCoverageStatus.RESPONSE_TRUNCATED,
        ResourceHealthCoverageStatus.STATE_CHANGED,
    }
)


__all__ = [
    "ResourceHealthAvailabilityState",
    "ResourceHealthCollection",
    "ResourceHealthCollectionReader",
    "ResourceHealthCoverage",
    "ResourceHealthCoverageStatus",
    "ResourceHealthAnswerValidation",
    "ResourceHealthNarrationClaims",
    "ResourceHealthObservation",
    "ResourceHealthTerminalDisposition",
    "read_current_with_reread_fence",
    "validate_resource_health_answer",
]
