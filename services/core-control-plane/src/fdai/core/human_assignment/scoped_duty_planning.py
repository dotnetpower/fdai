"""Current-only H10 coverage planning and inert versioned review rendering.

Only the injected read-only ports perform I/O. No global map, assignment case,
role, approval, agent, or production binding is changed by this module.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Literal

from fdai.core.human_assignment.scoped_duties import (
    DutyResolution,
    DutySubject,
    DutySubjectKind,
    DutySubjectResolver,
    ExactScopeCatalogReader,
    ScopeCatalogEntry,
    ScopedDutyBinding,
    ScopedDutyInput,
    ScopedDutyPolicy,
    ScopedDutyValidationError,
    canonical_digest,
    canonical_json,
    utc_instant,
)
from fdai.core.stewardship.model import Duty


class HeldReason(StrEnum):
    """Bounded, content-free reasons why current coverage cannot be established."""

    NOT_YET_EFFECTIVE = "not_yet_effective"
    EXPIRED = "expired"
    NOT_OBSERVED = "not_observed_at_query_time"
    CLOCK_ROLLBACK = "clock_rollback"
    UNKNOWN_SCOPE = "unknown_scope"
    SCOPE_UNAVAILABLE = "scope_unavailable"
    SCOPE_MISMATCH = "scope_revision_or_identity_mismatch"
    RESOLUTION_UNAVAILABLE = "resolution_unavailable"
    INVALID_RESOLUTION = "invalid_resolution"
    SUBJECT_MISMATCH = "resolution_subject_mismatch"
    QUERY_TIME_MISMATCH = "resolution_query_time_mismatch"
    INCOMPLETE_RESOLUTION = "incomplete_resolution"
    EMPTY_RESOLUTION = "empty_resolution"
    STALE_RESOLUTION = "stale_resolution"
    PRIMARY_MISSING = "current_primary_missing"
    DISTINCT_BACKUP_MISSING = "current_distinct_backup_or_escalation_missing"
    SELF_CONFLICT = "primary_and_fallback_resolve_to_same_person"


@dataclass(frozen=True, slots=True)
class ResolvedScopedDuty:
    """Planner-owned evidence for one declaration, retaining holds and fallback provenance."""

    binding: ScopedDutyBinding
    scope: ScopeCatalogEntry | None
    resolution: DutyResolution | None
    held_reason: HeldReason | None
    schedule_failure: HeldReason | None

    @property
    def used_fallback(self) -> bool:
        """Distinguish a resolved static fallback from merely attempting that fallback."""
        return self.schedule_failure is not None and self.resolution is not None

    def to_dict(self) -> dict[str, object]:
        """Return a fresh review record whose digest binds the declared and resolved subjects."""
        return {
            "binding": self.binding,
            "scope": self.scope,
            "resolution": self.resolution,
            "held_reason": self.held_reason,
            "schedule_failure": self.schedule_failure,
            "used_fallback": self.used_fallback,
            "digest": canonical_digest(self),
        }


@dataclass(frozen=True, slots=True)
class CurrentScopeCoverage:
    """Observed people for one exact agent/scope; backup outputs exclude every primary."""

    agent_name: str
    scope_ref: str
    primary_refs: tuple[str, ...]
    backup_refs: tuple[str, ...]
    escalation_refs: tuple[str, ...]
    held_reasons: tuple[HeldReason, ...]

    @property
    def has_current_coverage(self) -> bool:
        """Require a current primary, distinct backup/escalation, and no unresolved defects."""
        return bool(
            self.primary_refs
            and (self.backup_refs or self.escalation_refs)
            and not self.held_reasons
        )


@dataclass(frozen=True, slots=True)
class ScopedDutyPlan:
    """Planner-produced review snapshot, not a decoder, activation, or authorization receipt.

    Coverage concerns only the listed agent/scopes at checked_at. Evidence is queried
    at resolution_at and rechecked after all reads. Neither timestamp nor validity
    metadata establishes continuous or future coverage, approval eligibility, or IAM.
    """

    source_revision: str
    input_digest: str
    resolution_at: datetime
    checked_at: datetime
    bindings: tuple[ResolvedScopedDuty, ...]
    coverage: tuple[CurrentScopeCoverage, ...]
    policy: ScopedDutyPolicy
    supersedes_case_id: str | None = None

    @property
    def review_required(self) -> Literal[True]:
        """Every plan requires independent review, including plans with observed coverage."""
        return True

    @property
    def execution_authority(self) -> Literal[False]:
        """Planning cannot grant execution authority and has no configurable override."""
        return False

    @property
    def has_current_coverage(self) -> bool:
        """Report coverage only when every represented exact scope has current evidence."""
        return bool(self.coverage) and all(row.has_current_coverage for row in self.coverage)

    @property
    def digest(self) -> str:
        """Bind the complete versioned review payload for deterministic replay."""
        return canonical_digest(self._payload())

    def _payload(self) -> dict[str, object]:
        return {
            "kind": "scoped_duty_review",
            "schema_version": "1.0.0",
            "source_revision": self.source_revision,
            "input_digest": self.input_digest,
            "policy": self.policy.to_dict(),
            "resolution_at": self.resolution_at,
            "checked_at": self.checked_at,
            "coverage_basis": "current_observation_only",
            "current_coverage": self.has_current_coverage,
            "review_required": self.review_required,
            "execution_authority": self.execution_authority,
            "bindings": tuple(row.to_dict() for row in self.bindings),
            "coverage": self.coverage,
            **({"supersedes_case_id": self.supersedes_case_id} if self.supersedes_case_id else {}),
        }


@dataclass(frozen=True, slots=True)
class ScopedDutyPlanner:
    """Perform serial, bounded exact reads; construction performs no I/O.

    Clock and policy are mandatory. Provider errors become explicit holds, schedules
    may use only their declared fresh PERSON fallback, and cancellation propagates.
    """

    subjects: DutySubjectResolver
    scopes: ExactScopeCatalogReader
    clock: Callable[[], datetime]
    policy: ScopedDutyPolicy

    def __post_init__(self) -> None:
        if not callable(self.clock) or not isinstance(self.policy, ScopedDutyPolicy):
            raise ScopedDutyValidationError("planner requires an explicit clock and typed policy")

    async def plan(self, request: ScopedDutyInput) -> ScopedDutyPlan:
        """Check current coverage only, retaining every declaration and rechecking time after I/O.

        Invalid inputs/clocks raise ScopedDutyValidationError before they can prove
        coverage. Failed scope reads prevent identity reads for the affected scope.
        No future or expired declaration triggers schedule or person resolution.
        """
        if not isinstance(request, ScopedDutyInput):
            raise ScopedDutyValidationError("planner requires a validated ScopedDutyInput")
        try:
            async with asyncio.timeout(self.policy.total_timeout_seconds):
                return await self._plan(request)
        except TimeoutError as exc:
            raise ScopedDutyValidationError("scoped duty plan total deadline exceeded") from exc

    async def _plan(self, request: ScopedDutyInput) -> ScopedDutyPlan:
        at = utc_instant(self.clock())
        scope_results = {
            scope: await self._scope(scope, request.source_revision)
            for scope in sorted({binding.scope_ref for binding in request.bindings})
        }
        rows: list[ResolvedScopedDuty] = []
        for binding in request.ordered_bindings:
            scope, reason = scope_results[binding.scope_ref]
            reason = reason or _window_reason(binding, at)
            receipt = None
            schedule_failure = None
            if reason is None:
                receipt, reason = await self._resolve(binding.subject, at)
                if (
                    reason is not None
                    and binding.subject.kind is DutySubjectKind.SCHEDULE
                    and binding.fallback is not None
                ):
                    schedule_failure = reason
                    receipt, reason = await self._resolve(binding.fallback, at)
            rows.append(ResolvedScopedDuty(binding, scope, receipt, reason, schedule_failure))
        current_scopes = {
            scope: await self._scope(scope, request.source_revision)
            for scope, (_, reason) in scope_results.items()
            if reason is None
        }
        for index, row in enumerate(rows):
            entry, reason = current_scopes.get(row.binding.scope_ref, (row.scope, None))
            if reason is not None:
                rows[index] = replace(row, scope=entry, held_reason=reason)
        checked_at = utc_instant(self.clock())
        resolved = tuple(self._recheck(row, at, checked_at) for row in rows)
        return ScopedDutyPlan(
            request.source_revision,
            request.digest,
            at,
            checked_at,
            resolved,
            _coverage(resolved, checked_at),
            self.policy,
            request.supersedes_case_id,
        )

    async def _scope(
        self, scope_ref: str, revision: str
    ) -> tuple[ScopeCatalogEntry | None, HeldReason | None]:
        try:
            async with asyncio.timeout(self.policy.read_timeout_seconds):
                entry = await self.scopes.read_scope(scope_ref, source_revision=revision)
        except Exception:
            return None, HeldReason.SCOPE_UNAVAILABLE
        if entry is None:
            return None, HeldReason.UNKNOWN_SCOPE
        if (
            not isinstance(entry, ScopeCatalogEntry)
            or entry.scope_ref != scope_ref
            or entry.source_revision != revision
        ):
            return None, HeldReason.SCOPE_MISMATCH
        return entry, None

    async def _resolve(
        self, subject: DutySubject, at: datetime
    ) -> tuple[DutyResolution | None, HeldReason | None]:
        try:
            async with asyncio.timeout(self.policy.read_timeout_seconds):
                receipt = await self.subjects.resolve(subject, at=at)
        except ScopedDutyValidationError:
            return None, HeldReason.INVALID_RESOLUTION
        except Exception:
            return None, HeldReason.RESOLUTION_UNAVAILABLE
        if receipt is None:
            return None, HeldReason.RESOLUTION_UNAVAILABLE
        if not isinstance(receipt, DutyResolution):
            return None, HeldReason.INVALID_RESOLUTION
        if receipt.subject != subject:
            return None, HeldReason.SUBJECT_MISMATCH
        if receipt.at != at:
            return None, HeldReason.QUERY_TIME_MISMATCH
        if not receipt.complete:
            return None, HeldReason.INCOMPLETE_RESOLUTION
        if not receipt.people:
            return None, HeldReason.EMPTY_RESOLUTION
        if not receipt.is_current(at=at, max_age=self.policy.max_resolution_age):
            return None, HeldReason.STALE_RESOLUTION
        return receipt, None

    def _recheck(
        self, row: ResolvedScopedDuty, at: datetime, checked_at: datetime
    ) -> ResolvedScopedDuty:
        """Do not reuse an observation after expiry or manufacture a newly started window."""
        if checked_at < at:
            return replace(row, held_reason=HeldReason.CLOCK_ROLLBACK)
        temporal = _window_reason(row.binding, checked_at)
        if temporal is not None:
            return replace(row, held_reason=temporal)
        if row.held_reason in {HeldReason.NOT_YET_EFFECTIVE, HeldReason.EXPIRED}:
            return replace(row, held_reason=HeldReason.NOT_OBSERVED)
        if row.held_reason is not None:
            return row
        if row.resolution is None:
            return replace(row, held_reason=HeldReason.RESOLUTION_UNAVAILABLE)
        if not row.resolution.is_current(at=checked_at, max_age=self.policy.max_resolution_age):
            return replace(row, held_reason=HeldReason.STALE_RESOLUTION)
        return row


def _window_reason(binding: ScopedDutyBinding, at: datetime) -> HeldReason | None:
    if at < binding.effective_from:
        return HeldReason.NOT_YET_EFFECTIVE
    if at >= binding.effective_until:
        return HeldReason.EXPIRED
    return None


def _coverage(
    rows: tuple[ResolvedScopedDuty, ...], at: datetime
) -> tuple[CurrentScopeCoverage, ...]:
    """Count people, never declaration ids; unresolved current duties keep their scope held."""
    results: list[CurrentScopeCoverage] = []
    for agent, scope in sorted({(row.binding.agent_name, row.binding.scope_ref) for row in rows}):
        matching = tuple(
            row for row in rows if (row.binding.agent_name, row.binding.scope_ref) == (agent, scope)
        )
        current = tuple(row for row in matching if _window_reason(row.binding, at) is None)
        reasons = {row.held_reason for row in (current or matching) if row.held_reason is not None}
        people: dict[Duty, set[str]] = {duty: set() for duty in Duty}
        for row in current:
            if row.held_reason is None and row.resolution is not None:
                people[row.binding.duty].update(person.ref for person in row.resolution.people)
        primary = people[Duty.PRIMARY]
        backup = people[Duty.BACKUP]
        escalation = people[Duty.ESCALATION]
        if not primary:
            reasons.add(HeldReason.PRIMARY_MISSING)
        if primary & (backup | escalation):
            reasons.add(HeldReason.SELF_CONFLICT)
        if not (backup | escalation) - primary:
            reasons.add(HeldReason.DISTINCT_BACKUP_MISSING)
        results.append(
            CurrentScopeCoverage(
                agent,
                scope,
                tuple(sorted(primary)),
                tuple(sorted(backup - primary)),
                tuple(sorted(escalation - primary)),
                tuple(sorted(reasons)),
            )
        )
    return tuple(results)


def render_scoped_duty_review(plan: ScopedDutyPlan) -> str:
    """Return versioned JSON plus LF, retaining exact scope/time/evidence and no authority.

    This is not v2 global stewardship YAML, a persistence operation, or an applied
    assignment. A later consumer must revalidate current sources and obtain review.
    """
    return canonical_json({**plan._payload(), "digest": plan.digest}) + "\n"


__all__ = [
    "CurrentScopeCoverage",
    "HeldReason",
    "ResolvedScopedDuty",
    "ScopedDutyPlan",
    "ScopedDutyPlanner",
    "render_scoped_duty_review",
]
