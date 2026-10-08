"""Hub domain records: one installation aggregate and the outcomes of planning it."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from functools import cmp_to_key
from typing import ClassVar, Self, get_args
from zoneinfo import ZoneInfo

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.lifecycle_plan import (
    ConstraintBlock,
    LifecyclePlan,
    MaintenanceWindow,
    PlanType,
    SuppressionWindow,
)
from fdai_deployment_cli.runtime_release import compare_release_ids, is_release_id

type Clock = Callable[[], datetime]

_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


class StaleStateError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class DailyWindow:
    """A maintenance window that opens every day at a local wall-clock time."""

    start: time
    duration: timedelta
    timezone: str
    allows_downtime: bool = False

    def __post_init__(self) -> None:
        if self.start.tzinfo is not None:
            raise ValueError("window start is a local wall-clock time")
        if not timedelta(minutes=1) <= self.duration <= timedelta(days=1):
            raise ValueError("window duration must be between one minute and one day")
        ZoneInfo(self.timezone)  # Rejects unknown zones at construction.

    def around(self, now: datetime) -> Iterator[MaintenanceWindow]:
        """Yield the occurrences that start on the previous, current, and next local day."""

        zone = ZoneInfo(self.timezone)
        today = now.astimezone(zone).date()
        for day in (today - timedelta(days=1), today, today + timedelta(days=1)):
            starts_at = datetime.combine(day, self.start, zone).astimezone(UTC)
            yield MaintenanceWindow(starts_at, starts_at + self.duration, self.allows_downtime)


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    """The customer-approved subscription and placement of one installation."""

    channel: str
    version_range: str
    region: str
    allowed_regions: frozenset[str]
    windows: tuple[DailyWindow, ...]
    plan_duration: timedelta = timedelta(minutes=30)
    fencing_generation: int = 1

    @property
    def plan_duration_minutes(self) -> int:
        return self.plan_duration // timedelta(minutes=1)


@dataclass(frozen=True, slots=True, kw_only=True)
class Entity:
    """One deployable unit of an installation. Only managed entities receive Plans."""

    entity_id: str
    kind: str
    managed: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class Configuration:
    """One configuration package revision, addressed by the digest of its content."""

    schema: Mapping[str, object]
    environment: Mapping[str, object]
    entity_overrides: tuple[Mapping[str, object], ...]

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "schema": self.schema,
                "environment": self.environment,
                "entity_overrides": self.entity_overrides,
            }
        )


class Health(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityState:
    release_id: str
    artifact_digests: frozenset[str]
    health: Health

    def __post_init__(self) -> None:
        if not is_release_id(self.release_id):
            raise ValueError(f"release id is not canonical SemVer: {self.release_id!r}")
        Health(self.health)  # Rejects an unknown health value.


@dataclass(frozen=True, slots=True, kw_only=True)
class ReportedState:
    """One lifecycle-state snapshot reported by the installation.

    `digest` is the installation's own digest of this snapshot. The Hub echoes it into the
    Plan, and the agent admits the Plan only while its local state still has that digest.
    """

    digest: str
    schema_revision: int
    entities: Mapping[str, EntityState]
    observed_at: datetime

    def __post_init__(self) -> None:
        if not _SHA256_HEX.fullmatch(self.digest):
            raise ValueError("state digest must be 64 lowercase hex characters")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")

    def current_release(self, entity_ids: frozenset[str]) -> str:
        """The oldest Release among `entity_ids`, so a partial upgrade plans from the laggard."""

        releases = (self.entities[entity_id].release_id for entity_id in entity_ids)
        return min(releases, key=cmp_to_key(compare_release_ids))

    def artifact_digests(self) -> frozenset[str]:
        return frozenset().union(*(state.artifact_digests for state in self.entities.values()))


@dataclass(frozen=True, slots=True, kw_only=True)
class IssuedPlan:
    """A signed Plan as the Hub stores and serves it."""

    plan_id: str
    sequence: int
    target_release_id: str
    source_state_digest: str
    configuration_digest: str
    hub_key_id: str
    entity_ids: frozenset[str]
    expires_at: datetime
    signed_payload: bytes
    signature: bytes

    @classmethod
    def from_signed(cls, plan: LifecyclePlan) -> Self:
        return cls(
            plan_id=plan.plan_id,
            sequence=plan.sequence,
            target_release_id=plan.target_release_id,
            source_state_digest=plan.source_state_digest,
            configuration_digest=plan.configuration_revision_digest,
            hub_key_id=plan.hub_key_id,
            entity_ids=plan.entity_ids,
            expires_at=plan.expires_at,
            signed_payload=plan.signed_payload,
            signature=plan.signature,
        )

    @property
    def digest(self) -> str:
        """The digest an agent reports for the exact Plan bytes it checked."""

        return f"sha256:{hashlib.sha256(self.signed_payload).hexdigest()}"

    def still_valid_for(self, plan: LifecyclePlan, now: datetime) -> bool:
        """True when `plan` would change nothing the open Plan doesn't already carry."""

        return now < self.expires_at and (
            self.target_release_id,
            self.source_state_digest,
            self.configuration_digest,
            self.hub_key_id,
            self.entity_ids,
        ) == (
            plan.target_release_id,
            plan.source_state_digest,
            plan.configuration_revision_digest,
            plan.hub_key_id,
            plan.entity_ids,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class Installation:
    """Everything the Hub plans from, loaded and locked as one unit."""

    installation_id: str
    settings: Settings
    entities: frozenset[Entity]
    configuration: Configuration
    reported: ReportedState
    suppressions: tuple[SuppressionWindow, ...] = ()
    last_sequence: int = 0
    open_plan: IssuedPlan | None = None

    def __post_init__(self) -> None:
        if not self.managed_entity_ids:
            raise ValueError("an installation needs at least one managed entity")
        if missing := self.managed_entity_ids - self.reported.entities.keys():
            raise ValueError(f"reported state lacks managed entities: {sorted(missing)}")

    def with_reported(self, state: ReportedState) -> Self:
        """Return this installation with a newer snapshot. Raises on a stale or partial one."""

        if state.observed_at <= self.reported.observed_at:
            raise StaleStateError("reported state is not newer than the current state")
        return replace(self, reported=state)

    def suppressed(self, window: SuppressionWindow, now: datetime) -> Self:
        """Return this installation with `window` added and its expired windows dropped."""

        if window.ends_at <= max(window.starts_at, now):
            raise ValueError("a suppression must end in the future and after it starts")
        if not self._is_scope(window.scope):
            raise ValueError(f"unknown suppression scope: {window.scope!r}")
        return replace(self, suppressions=(*self._unexpired(now), window))

    def lifted(self, scope: str, now: datetime) -> Self:
        """Return this installation without its unexpired suppressions for `scope`."""

        current = self._unexpired(now)
        remaining = tuple(window for window in current if window.scope != scope)
        if remaining == current:
            raise ValueError(f"no active suppression for scope {scope!r}")
        return replace(self, suppressions=remaining)

    def _unexpired(self, now: datetime) -> tuple[SuppressionWindow, ...]:
        return tuple(window for window in self.suppressions if window.ends_at > now)

    def _is_scope(self, scope: str) -> bool:
        kind, _, target = scope.partition(":")
        match kind:
            case "installation":
                return not target
            case "plan":
                return target in get_args(PlanType)
            case "entity":
                return target in {entity.entity_id for entity in self.entities}
            case _:
                return False

    @property
    def managed_entity_ids(self) -> frozenset[str]:
        return frozenset(entity.entity_id for entity in self.entities if entity.managed)

    @property
    def current_release(self) -> str:
        return self.reported.current_release(self.managed_entity_ids)

    def maintenance_windows(self, now: datetime) -> tuple[MaintenanceWindow, ...]:
        return tuple(
            occurrence for window in self.settings.windows for occurrence in window.around(now)
        )


class OutcomeKind(StrEnum):
    ISSUED = "issued"
    UNCHANGED = "unchanged"
    WAITING = "waiting"
    NO_ELIGIBLE_RELEASE = "no-eligible-release"
    UP_TO_DATE = "up-to-date"


@dataclass(frozen=True, slots=True)
class CandidateCheck:
    """The constraint blocks one candidate Release produced. Empty means it passed."""

    release_id: str
    blocks: tuple[ConstraintBlock, ...]


@dataclass(frozen=True, slots=True)
class Issued:
    """A new signed Plan for the newest eligible Release."""

    kind: ClassVar[OutcomeKind] = OutcomeKind.ISSUED
    plan: LifecyclePlan
    checks: tuple[CandidateCheck, ...]


@dataclass(frozen=True, slots=True)
class Unchanged:
    """The open Plan already targets the newest eligible Release from the same state."""

    kind: ClassVar[OutcomeKind] = OutcomeKind.UNCHANGED
    plan: IssuedPlan
    checks: tuple[CandidateCheck, ...]


@dataclass(frozen=True, slots=True)
class Waiting:
    """The newest eligible Release is known, but a window or suppression holds it."""

    kind: ClassVar[OutcomeKind] = OutcomeKind.WAITING
    release_id: str
    checks: tuple[CandidateCheck, ...]


@dataclass(frozen=True, slots=True)
class NoEligibleRelease:
    """Every newer Release on the channel is blocked by a Release-specific constraint."""

    kind: ClassVar[OutcomeKind] = OutcomeKind.NO_ELIGIBLE_RELEASE
    checks: tuple[CandidateCheck, ...]


@dataclass(frozen=True, slots=True)
class UpToDate:
    """No Release on the channel is newer than the current one."""

    kind: ClassVar[OutcomeKind] = OutcomeKind.UP_TO_DATE
    checks: tuple[CandidateCheck, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Evaluation:
    """A recorded recompute: its outcome and every candidate check behind it."""

    outcome: OutcomeKind
    target_release_id: str | None
    plan_id: str | None
    checks: tuple[CandidateCheck, ...]
    evaluated_at: datetime


type PlanOutcome = Issued | Unchanged | Waiting | NoEligibleRelease | UpToDate
type Planner = Callable[[Installation, datetime], PlanOutcome]
