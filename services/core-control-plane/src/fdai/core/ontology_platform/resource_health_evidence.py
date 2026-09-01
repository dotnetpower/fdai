"""Exact-denominator Resource Health evidence contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal, Protocol

_MAX_RESOURCES = 1000


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
    issues: tuple[str, ...] = ()
    execution_authority: Literal[False] = False
    complete: bool = field(init=False)
    limitation: str | None = field(init=False)

    def __post_init__(self) -> None:
        if not self.resource_ids or len(self.resource_ids) > _MAX_RESOURCES:
            raise ValueError("Resource Health scope MUST contain between 1 and 1000 resources")
        if self.resource_ids != tuple(sorted(set(self.resource_ids))):
            raise ValueError("Resource Health scope MUST be unique and ordered")
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
        if self.issues != tuple(sorted(set(self.issues))):
            raise ValueError("Resource Health issues MUST be unique and ordered")
        if any(item not in {"provider_scope_mismatch", "response_invalid"} for item in self.issues):
            raise ValueError("Resource Health issue is unsupported")
        if not self.attempt_ref.strip() or len(self.attempt_ref) > 256:
            raise ValueError("Resource Health attempt_ref MUST be bounded and non-empty")
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


__all__ = [
    "ResourceHealthAvailabilityState",
    "ResourceHealthCollection",
    "ResourceHealthCollectionReader",
    "ResourceHealthCoverage",
    "ResourceHealthCoverageStatus",
    "ResourceHealthObservation",
]
