"""Run every due registered observation source under one bounded read contract."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol

from fdai_service_contracts import (
    AgentOperationalActivity,
    ObservationDomain,
    OperationalActivityKind,
    OperationalActivityStatus,
    OperationalFreshness,
)

from fdai.shared.providers.state_store import StateStore

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9.-]{0,95}$")
_STATE_PREFIX = "observation-campaign:source:"
_CLAIM_GRACE_SECONDS = 30
_MAX_CLAIM_ATTEMPTS = 8

ObservationOwner = Literal["Huginn", "Heimdall", "Njord", "Freyr", "Vidar"]


class ObservationCoverage(StrEnum):
    """Source coverage outcome without provider error detail."""

    READY = "ready"
    PARTIAL = "partial"
    UNAUTHORIZED = "unauthorized"
    UNCONFIGURED = "unconfigured"
    UNREACHABLE = "unreachable"
    RETENTION_GAP = "retention-gap"
    STALE = "stale"


class ObservationThrottledError(RuntimeError):
    """Signal that a provider exhausted its bounded throttling budget."""


class ObservationProbeContractError(RuntimeError):
    """Signal that a probe returned metadata outside its registered limits."""


@dataclass(frozen=True, slots=True)
class ObservationSourceSpec:
    """Declare one reviewed, bounded source in the campaign registry."""

    source_id: str
    domain: ObservationDomain
    owner_agent: ObservationOwner
    interval_seconds: int
    lookback_seconds: int
    timeout_seconds: float
    max_targets: int
    max_results: int
    max_output_bytes: int
    required: bool = True

    def __post_init__(self) -> None:
        if not _IDENTIFIER.fullmatch(self.source_id):
            raise ValueError("observation source_id MUST be a bounded lowercase identifier")
        if not 60 <= self.interval_seconds <= 2_592_000:
            raise ValueError("observation interval_seconds MUST be in [60, 2592000]")
        if not 60 <= self.lookback_seconds <= 7_776_000:
            raise ValueError("observation lookback_seconds MUST be in [60, 7776000]")
        if not 0 < self.timeout_seconds <= 300:
            raise ValueError("observation timeout_seconds MUST be in (0, 300]")
        if not 1 <= self.max_targets <= 100:
            raise ValueError("observation max_targets MUST be in [1, 100]")
        if not 1 <= self.max_results <= 10_000:
            raise ValueError("observation max_results MUST be in [1, 10000]")
        if not 1 <= self.max_output_bytes <= 2_000_000:
            raise ValueError("observation max_output_bytes MUST be in [1, 2000000]")
        _validate_owner(self.domain, self.owner_agent)


@dataclass(frozen=True, slots=True)
class ObservationProbeResult:
    """Return only bounded source metadata; raw evidence stays provider-owned."""

    coverage: ObservationCoverage
    evidence_count: int = 0
    cursor: str | None = None
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.evidence_count <= 1_000_000:
            raise ValueError("observation evidence_count MUST be in [0, 1000000]")
        if self.cursor is not None and not 1 <= len(self.cursor) <= 4096:
            raise ValueError("observation cursor MUST be bounded non-empty text")
        if len(self.reason_codes) > 16 or len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("observation reason_codes MUST contain up to 16 unique values")
        if any(not code or len(code) > 128 for code in self.reason_codes):
            raise ValueError("observation reason codes MUST be bounded non-empty text")
        if self.coverage is not ObservationCoverage.READY and not self.reason_codes:
            raise ValueError("non-ready observation results MUST include a reason code")


class ObservationProbe(Protocol):
    """Collect one source with server-owned limits and an optional durable cursor."""

    async def collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> ObservationProbeResult: ...


class ObservationActivityPublisher(Protocol):
    """Publish a bounded activity tip after its source state transition."""

    async def publish(self, activity: AgentOperationalActivity) -> bool: ...


@dataclass(frozen=True, slots=True)
class ObservationSourceRun:
    """Describe one terminal source run without raw evidence."""

    source_id: str
    domain: ObservationDomain
    owner_agent: ObservationOwner
    status: OperationalActivityStatus
    coverage: ObservationCoverage
    freshness: OperationalFreshness
    evidence_count: int
    duration_ms: int
    reason_codes: tuple[str, ...]
    skipped: bool = False


@dataclass(frozen=True, slots=True)
class ObservationCampaignSummary:
    """Aggregate one campaign without collapsing source-specific outcomes."""

    campaign_id: str
    status: Literal["completed", "partial"]
    sources: tuple[ObservationSourceRun, ...]


class ObservationCampaignRunner:
    """Run due source probes concurrently and persist each transition before publication."""

    def __init__(
        self,
        *,
        sources: Sequence[ObservationSourceSpec],
        probes: Mapping[str, ObservationProbe],
        store: StateStore,
        publisher: ObservationActivityPublisher,
        max_concurrency: int = 4,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        if not sources:
            raise ValueError("observation campaign MUST register at least one source")
        source_ids = [source.source_id for source in sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("observation campaign source ids MUST be unique")
        if not 1 <= max_concurrency <= 4:
            raise ValueError("observation campaign max_concurrency MUST be in [1, 4]")
        self._sources = tuple(sources)
        self._probes = dict(probes)
        self._store = store
        self._publisher = publisher
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._clock = clock or (lambda: datetime.now(tz=UTC))
        self._monotonic = monotonic or time.monotonic

    async def run(self, campaign_id: str) -> ObservationCampaignSummary:
        """Run all due sources and return completed only when required coverage is ready."""
        if not _IDENTIFIER.fullmatch(campaign_id):
            raise ValueError("campaign_id MUST be a bounded lowercase identifier")
        runs = await asyncio.gather(
            *(self._run_source(source, campaign_id) for source in self._sources)
        )
        partial = any(
            source.required and run.coverage is not ObservationCoverage.READY
            for source, run in zip(self._sources, runs, strict=True)
        )
        return ObservationCampaignSummary(
            campaign_id=campaign_id,
            status="partial" if partial else "completed",
            sources=tuple(runs),
        )

    async def _run_source(
        self,
        spec: ObservationSourceSpec,
        campaign_id: str,
    ) -> ObservationSourceRun:
        state_key = f"{_STATE_PREFIX}{spec.source_id}"
        claim = await self._claim_source(state_key, spec=spec, campaign_id=campaign_id)
        if isinstance(claim, ObservationSourceRun):
            return claim
        previous, started_at, claim_revision = claim
        cursor = _optional_text(previous.get("cursor"), maximum=4096)
        await self._publish_activity(
            _activity(
                spec=spec,
                campaign_id=campaign_id,
                status=OperationalActivityStatus.STARTED,
                freshness=OperationalFreshness.UNKNOWN,
                evidence_count=0,
                duration_ms=None,
                reason_codes=(),
                observed_at=started_at,
            )
        )

        started = self._monotonic()
        result, failed = await self._collect(spec, cursor=cursor)
        duration_ms = max(0, round((self._monotonic() - started) * 1000))
        status, freshness = _activity_state(result.coverage, failed=failed)
        completed_at = self._clock()
        terminal: dict[str, object] = {
            "schema_version": "1.0.0",
            "revision": claim_revision + 1,
            "source_id": spec.source_id,
            "domain": spec.domain.value,
            "campaign_id": campaign_id,
            "status": status.value,
            "coverage": result.coverage.value,
            "freshness": freshness.value,
            "evidence_count": result.evidence_count,
            "duration_ms": duration_ms,
            "reason_codes": list(result.reason_codes),
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
        }
        if result.cursor is not None:
            terminal["cursor"] = result.cursor
        elif cursor is not None:
            terminal["cursor"] = cursor
        if result.coverage is ObservationCoverage.READY:
            terminal["last_success_at"] = completed_at.isoformat()
        elif "last_success_at" in previous:
            terminal["last_success_at"] = previous["last_success_at"]
        persisted = await self._store.compare_and_set_state_with_audit(
            state_key,
            terminal,
            expected_revision=claim_revision,
            audit_entry=_audit_transition(
                spec=spec,
                campaign_id=campaign_id,
                status=status.value,
                revision=claim_revision + 1,
                observed_at=completed_at,
            ),
        )
        if not persisted:
            await self._publish_activity(
                _activity(
                    spec=spec,
                    campaign_id=campaign_id,
                    status=OperationalActivityStatus.SUPERSEDED,
                    freshness=OperationalFreshness.UNKNOWN,
                    evidence_count=0,
                    duration_ms=duration_ms,
                    reason_codes=("state_write_conflict",),
                    observed_at=completed_at,
                )
            )
            return _state_conflict(spec)
        await self._publish_activity(
            _activity(
                spec=spec,
                campaign_id=campaign_id,
                status=status,
                freshness=freshness,
                evidence_count=result.evidence_count,
                duration_ms=duration_ms,
                reason_codes=result.reason_codes,
                observed_at=completed_at,
            )
        )
        return ObservationSourceRun(
            source_id=spec.source_id,
            domain=spec.domain,
            owner_agent=spec.owner_agent,
            status=status,
            coverage=result.coverage,
            freshness=freshness,
            evidence_count=result.evidence_count,
            duration_ms=duration_ms,
            reason_codes=result.reason_codes,
        )

    async def _publish_activity(self, activity: AgentOperationalActivity) -> bool:
        try:
            return await self._publisher.publish(activity)
        except Exception:  # noqa: BLE001 - durable state remains the recovery source
            return False

    async def _claim_source(
        self,
        state_key: str,
        *,
        spec: ObservationSourceSpec,
        campaign_id: str,
    ) -> tuple[Mapping[str, object], datetime, int] | ObservationSourceRun:
        for _ in range(_MAX_CLAIM_ATTEMPTS):
            previous = await self._store.read_state(state_key) or {}
            replay = _replay(previous, spec, campaign_id)
            if replay is not None:
                return replay
            now = self._clock()
            if _active_claim(previous, now=now):
                return _in_progress(spec)
            if not _due(previous, now=now, interval_seconds=spec.interval_seconds):
                skipped = _skipped(spec, previous)
                if skipped is not None:
                    return skipped
            prior_revision = _revision(previous)
            claim_revision = prior_revision + 1
            claim = {
                **_retained_state(previous),
                "schema_version": "1.0.0",
                "revision": claim_revision,
                "source_id": spec.source_id,
                "domain": spec.domain.value,
                "campaign_id": campaign_id,
                "status": "started",
                "started_at": now.isoformat(),
                "claim_expires_at": (
                    now + timedelta(seconds=spec.timeout_seconds + _CLAIM_GRACE_SECONDS)
                ).isoformat(),
            }
            audit = _audit_transition(
                spec=spec,
                campaign_id=campaign_id,
                status="started",
                revision=claim_revision,
                observed_at=now,
            )
            if previous:
                claimed = await self._store.compare_and_set_state_with_audit(
                    state_key,
                    claim,
                    expected_revision=prior_revision,
                    audit_entry=audit,
                )
            else:
                claimed = await self._store.write_state_with_audit_if_absent(
                    state_key,
                    claim,
                    audit,
                )
            if claimed:
                return previous, now, claim_revision
        return _state_conflict(spec)

    async def _collect(
        self,
        spec: ObservationSourceSpec,
        *,
        cursor: str | None,
    ) -> tuple[ObservationProbeResult, bool]:
        probe = self._probes.get(spec.source_id)
        if probe is None:
            return (
                ObservationProbeResult(
                    coverage=ObservationCoverage.UNCONFIGURED,
                    reason_codes=("source_unconfigured",),
                ),
                False,
            )
        try:
            async with self._semaphore, asyncio.timeout(spec.timeout_seconds):
                result = await probe.collect(spec, cursor=cursor)
                if result.evidence_count > spec.max_results:
                    raise ObservationProbeContractError(
                        "observation probe exceeded its registered result limit"
                    )
                return result, False
        except TimeoutError:
            return (
                ObservationProbeResult(
                    coverage=ObservationCoverage.UNREACHABLE,
                    reason_codes=("source_timeout",),
                ),
                False,
            )
        except PermissionError:
            return (
                ObservationProbeResult(
                    coverage=ObservationCoverage.UNAUTHORIZED,
                    reason_codes=("source_unauthorized",),
                ),
                False,
            )
        except ObservationThrottledError:
            return (
                ObservationProbeResult(
                    coverage=ObservationCoverage.PARTIAL,
                    reason_codes=("source_throttled",),
                ),
                False,
            )
        except ObservationProbeContractError:
            return (
                ObservationProbeResult(
                    coverage=ObservationCoverage.UNREACHABLE,
                    reason_codes=("provider_contract_violation",),
                ),
                True,
            )
        except Exception:  # noqa: BLE001 - provider details never cross the boundary
            return (
                ObservationProbeResult(
                    coverage=ObservationCoverage.UNREACHABLE,
                    reason_codes=("provider_failure",),
                ),
                True,
            )


def _activity(
    *,
    spec: ObservationSourceSpec,
    campaign_id: str,
    status: OperationalActivityStatus,
    freshness: OperationalFreshness,
    evidence_count: int,
    duration_ms: int | None,
    reason_codes: tuple[str, ...],
    observed_at: datetime,
) -> AgentOperationalActivity:
    return AgentOperationalActivity(
        schema_version="1.1.0",
        activity_id=f"observation:{spec.source_id}:{campaign_id}:{status.value}",
        idempotency_key=f"observation:{spec.source_id}:{campaign_id}:{status.value}",
        kind=OperationalActivityKind.OBSERVATION,
        status=status,
        owner_agent=spec.owner_agent,
        producer="observation-campaign-job",
        observation_domain=spec.domain,
        observed_at=observed_at,
        source=spec.source_id,
        freshness=freshness,
        evidence_count=evidence_count,
        duration_ms=duration_ms,
        correlation_id=campaign_id,
        reason_codes=reason_codes,
    )


def _activity_state(
    coverage: ObservationCoverage,
    *,
    failed: bool,
) -> tuple[OperationalActivityStatus, OperationalFreshness]:
    if failed:
        return OperationalActivityStatus.FAILED, OperationalFreshness.UNAVAILABLE
    if coverage is ObservationCoverage.READY:
        return OperationalActivityStatus.COMPLETED, OperationalFreshness.FRESH
    if coverage is ObservationCoverage.STALE:
        return OperationalActivityStatus.DEGRADED, OperationalFreshness.STALE
    return OperationalActivityStatus.DEGRADED, OperationalFreshness.UNAVAILABLE


def _due(state: Mapping[str, object], *, now: datetime, interval_seconds: int) -> bool:
    completed_at = _timestamp(state.get("completed_at"))
    if completed_at is None:
        return True
    return (now - completed_at).total_seconds() >= interval_seconds


def _active_claim(state: Mapping[str, object], *, now: datetime) -> bool:
    if state.get("status") != "started":
        return False
    claim_expires_at = _timestamp(state.get("claim_expires_at"))
    return claim_expires_at is not None and claim_expires_at > now


def _revision(state: Mapping[str, object]) -> int:
    revision = state.get("revision", 0)
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise ValueError("observation source revision MUST be non-negative")
    return revision


def _replay(
    state: Mapping[str, object],
    spec: ObservationSourceSpec,
    campaign_id: str,
) -> ObservationSourceRun | None:
    if state.get("campaign_id") != campaign_id or state.get("status") == "started":
        return None
    return _terminal_run(spec, state, skipped=False)


def _skipped(
    spec: ObservationSourceSpec,
    state: Mapping[str, object],
) -> ObservationSourceRun | None:
    return _terminal_run(spec, state, skipped=True)


def _terminal_run(
    spec: ObservationSourceSpec,
    state: Mapping[str, object],
    *,
    skipped: bool,
) -> ObservationSourceRun | None:
    try:
        if (
            state.get("source_id", spec.source_id) != spec.source_id
            or state.get("domain", spec.domain.value) != spec.domain.value
            or _timestamp(state.get("completed_at")) is None
        ):
            return None
        status = OperationalActivityStatus(str(state["status"]))
        coverage = ObservationCoverage(str(state["coverage"]))
        freshness = OperationalFreshness(str(state["freshness"]))
        evidence_count = state.get("evidence_count", 0)
        duration_ms = state.get("duration_ms", 0)
        raw_reasons = state.get("reason_codes", ())
        if (
            status is OperationalActivityStatus.STARTED
            or not isinstance(evidence_count, int)
            or isinstance(evidence_count, bool)
            or not 0 <= evidence_count <= min(spec.max_results, 1_000_000)
            or not isinstance(duration_ms, int)
            or isinstance(duration_ms, bool)
            or not 0 <= duration_ms <= 86_400_000
            or not isinstance(raw_reasons, (list, tuple))
        ):
            return None
        reason_codes = tuple(str(item) for item in raw_reasons)
        ObservationProbeResult(
            coverage=coverage,
            evidence_count=evidence_count,
            reason_codes=reason_codes,
        )
    except (KeyError, TypeError, ValueError):
        return None
    return ObservationSourceRun(
        source_id=spec.source_id,
        domain=spec.domain,
        owner_agent=spec.owner_agent,
        status=status,
        coverage=coverage,
        freshness=freshness,
        evidence_count=evidence_count,
        duration_ms=duration_ms,
        reason_codes=reason_codes,
        skipped=skipped,
    )


def _in_progress(spec: ObservationSourceSpec) -> ObservationSourceRun:
    return ObservationSourceRun(
        source_id=spec.source_id,
        domain=spec.domain,
        owner_agent=spec.owner_agent,
        status=OperationalActivityStatus.DEGRADED,
        coverage=ObservationCoverage.STALE,
        freshness=OperationalFreshness.UNKNOWN,
        evidence_count=0,
        duration_ms=0,
        reason_codes=("source_in_progress",),
    )


def _state_conflict(spec: ObservationSourceSpec) -> ObservationSourceRun:
    return ObservationSourceRun(
        source_id=spec.source_id,
        domain=spec.domain,
        owner_agent=spec.owner_agent,
        status=OperationalActivityStatus.FAILED,
        coverage=ObservationCoverage.UNREACHABLE,
        freshness=OperationalFreshness.UNAVAILABLE,
        evidence_count=0,
        duration_ms=0,
        reason_codes=("state_write_conflict",),
    )


def _audit_transition(
    *,
    spec: ObservationSourceSpec,
    campaign_id: str,
    status: str,
    revision: int,
    observed_at: datetime,
) -> dict[str, object]:
    return {
        "action_kind": "observation-campaign.source-transition",
        "source_id": spec.source_id,
        "domain": spec.domain.value,
        "campaign_id": campaign_id,
        "status": status,
        "revision": revision,
        "observed_at": observed_at.isoformat(),
        "execution_authority": False,
    }


def _retained_state(state: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value for key in ("cursor", "last_success_at") if (value := state.get(key)) is not None
    }


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _optional_text(value: object, *, maximum: int) -> str | None:
    return value if isinstance(value, str) and 1 <= len(value) <= maximum else None


def _validate_owner(domain: ObservationDomain, owner: ObservationOwner) -> None:
    expected: Mapping[ObservationDomain, frozenset[str]] = {
        ObservationDomain.INVENTORY: frozenset({"Huginn"}),
        ObservationDomain.ACTIVITY_LOG: frozenset({"Huginn"}),
        ObservationDomain.RESOURCE_HEALTH: frozenset({"Heimdall"}),
        ObservationDomain.SERVICE_HEALTH: frozenset({"Heimdall"}),
        ObservationDomain.METRICS: frozenset({"Heimdall", "Freyr"}),
        ObservationDomain.LOGS: frozenset({"Heimdall"}),
        ObservationDomain.GUEST_LOGS: frozenset({"Heimdall"}),
        ObservationDomain.NETWORK_CONFIG: frozenset({"Heimdall"}),
        ObservationDomain.COST: frozenset({"Njord"}),
        ObservationDomain.RECOVERY: frozenset({"Vidar"}),
    }
    if owner not in expected[domain]:
        raise ValueError("observation source owner MUST match its domain")


__all__ = [
    "ObservationCampaignRunner",
    "ObservationCampaignSummary",
    "ObservationCoverage",
    "ObservationProbe",
    "ObservationProbeContractError",
    "ObservationProbeResult",
    "ObservationSourceRun",
    "ObservationSourceSpec",
    "ObservationThrottledError",
]
