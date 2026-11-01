"""Production composition, duplicate-runner exclusion, and restart recovery for skill sources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from fdai.core.skills.catalog import SkillCatalog
from fdai.core.skills.source_registry import SkillSource, SkillSourceRefreshPolicy, SkillSourceStore
from fdai.core.supply_chain.artifacts import (
    TrustedArtifactKind,
    TrustedArtifactRecord,
    TrustedArtifactState,
)
from fdai.core.supply_chain.installer import TrustedArtifactInstaller
from fdai.core.supply_chain.skill_quarantine import (
    DeterministicSkillScanner,
    InMemorySkillQuarantineStore,
    InMemorySkillUpdateCandidateStore,
    SkillQuarantineStore,
    SkillRevocation,
    SkillRevocationStore,
    SkillSourceRefreshState,
    SkillSourceRefreshStateStore,
    SkillUpdateCandidateStore,
)
from fdai.core.supply_chain.skill_source_admin import (
    SkillSourceAdministrationService,
    SkillSourceRevocationResult,
    SkillSourceRevoker,
)
from fdai.core.supply_chain.skill_source_pipeline import (
    SkillSourceRefreshService,
    SkillSourceVerifierFactory,
)
from fdai.core.supply_chain.skill_source_refresh import (
    SkillSourceAdapterFactory,
    SkillSourceRefreshAttempt,
    SkillSourceRefreshOrchestrator,
)

DEFAULT_SCANNER_VERSION = "deterministic-skill-scanner-v1"
DEFAULT_RUNNER_LEASE_SECONDS = 300


class DuplicateSkillSourceRunnerError(RuntimeError):
    """Raised when a second scheduled skill-source runner attempts to acquire an active lease."""


@dataclass(frozen=True, slots=True)
class SkillSourceRunnerLease:
    runner_id: str
    acquired_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.runner_id.strip() or len(self.runner_id) > 128:
            raise ValueError("runner_id MUST be a bounded non-empty string")
        if self.acquired_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("runner lease timestamps MUST include timezone")
        if self.expires_at <= self.acquired_at:
            raise ValueError("runner lease expires_at MUST be after acquired_at")


@dataclass(frozen=True, slots=True)
class SkillSourceRestartRecoveryReceipt:
    runner_id: str
    recovered_at: datetime
    reclaimed_due_source_ids: tuple[str, ...]
    preserved_etags: dict[str, str]
    disabled_source_ids: tuple[str, ...]
    disabled_candidate_ids: tuple[str, ...]
    revoked_source_ids: tuple[str, ...]


class SkillSourceRunnerGuard(Protocol):
    def acquire(
        self, runner_id: str, *, now: datetime, lease_seconds: int = DEFAULT_RUNNER_LEASE_SECONDS
    ) -> SkillSourceRunnerLease: ...
    def release(self, runner_id: str) -> None: ...
    def force_recover(
        self, runner_id: str, *, now: datetime, lease_seconds: int = DEFAULT_RUNNER_LEASE_SECONDS
    ) -> SkillSourceRunnerLease: ...


class InMemorySkillSourceRunnerGuard:
    def __init__(self) -> None:
        self._active: SkillSourceRunnerLease | None = None

    def acquire(
        self, runner_id: str, *, now: datetime, lease_seconds: int = DEFAULT_RUNNER_LEASE_SECONDS
    ) -> SkillSourceRunnerLease:
        if now.tzinfo is None or isinstance(lease_seconds, bool) or lease_seconds < 1:
            raise ValueError("runner lease requires timezone-aware now and positive lease_seconds")
        cur = self._active
        if cur is not None and cur.expires_at > now and cur.runner_id != runner_id:
            raise DuplicateSkillSourceRunnerError(
                f"skill-source runner lease is already held by {cur.runner_id!r}"
            )
        self._active = SkillSourceRunnerLease(
            runner_id, now, now + timedelta(seconds=lease_seconds)
        )
        return self._active

    def release(self, runner_id: str) -> None:
        if self._active is not None and self._active.runner_id == runner_id:
            self._active = None

    force_recover = acquire


class InMemorySkillSourceStore:
    def __init__(self) -> None:
        self._sources: dict[str, SkillSource] = {}

    async def put(self, source: SkillSource, *, now: datetime) -> SkillSource:
        if now.tzinfo is None:
            raise ValueError("skill source timestamp MUST include timezone")
        existing = self._sources.get(source.source_id)
        if existing is not None and existing != source:
            raise ValueError("skill source id conflicts with different registration")
        self._sources[source.source_id] = source
        return source

    async def get(self, source_id: str) -> SkillSource | None:
        return self._sources.get(source_id)

    async def list(self, *, enabled_only: bool = False) -> tuple[SkillSource, ...]:
        items = [s for s in self._sources.values() if not enabled_only or s.enabled]
        return tuple(sorted(items, key=lambda item: item.source_id))

    async def set_enabled(
        self, source_id: str, *, enabled: bool, now: datetime
    ) -> SkillSource | None:
        if now.tzinfo is None:
            raise ValueError("skill source timestamp MUST include timezone")
        cur = self._sources.get(source_id)
        if cur is None:
            return None
        self._sources[source_id] = replace(cur, enabled=enabled)
        return self._sources[source_id]


class InMemorySkillSourceRefreshStateStore:
    def __init__(self) -> None:
        self._states: dict[str, SkillSourceRefreshState] = {}

    async def put(self, state: SkillSourceRefreshState) -> SkillSourceRefreshState:
        self._states[state.source_id] = state
        return state

    async def get(self, source_id: str) -> SkillSourceRefreshState | None:
        return self._states.get(source_id)

    async def claim(
        self, *, source_id: str, now: datetime, hold_until: datetime
    ) -> SkillSourceRefreshState | None:
        cur = self._states.get(source_id)
        if cur is not None:
            due = (
                cur.retry_at <= now
                if cur.retry_at is not None
                else cur.next_refresh_at is None or cur.next_refresh_at <= now
            )
            if not due:
                return None
            claimed = replace(cur, next_refresh_at=hold_until, retry_at=None)
        else:
            claimed = SkillSourceRefreshState(source_id=source_id, next_refresh_at=hold_until)
        self._states[source_id] = claimed
        return claimed


class InMemorySkillRevocationStore:
    def __init__(self) -> None:
        self._revocations: dict[str, SkillRevocation] = {}

    async def put(self, revocation: SkillRevocation) -> SkillRevocation:
        existing = self._revocations.get(revocation.revocation_id)
        if existing is not None and existing != revocation:
            raise ValueError("revocation id conflicts with different content")
        self._revocations[revocation.revocation_id] = revocation
        return revocation

    async def list(self, *, source_id: str | None = None) -> tuple[SkillRevocation, ...]:
        items = [
            r for r in self._revocations.values() if source_id is None or r.source_id == source_id
        ]
        return tuple(sorted(items, key=lambda item: (item.revoked_at, item.revocation_id)))

    async def is_revoked(self, *, source_id: str, artifact_digest: str) -> bool:
        return any(
            r.source_id == source_id and r.artifact_digest == artifact_digest
            for r in self._revocations.values()
        )


class InMemoryTrustedSkillArtifactStore:
    def __init__(self) -> None:
        self._records: dict[tuple[TrustedArtifactKind, str], TrustedArtifactRecord] = {}

    async def put(
        self, record: TrustedArtifactRecord, *, expected_revision: int
    ) -> TrustedArtifactRecord:
        key = (record.kind, record.artifact_id)
        current = self._records.get(key)
        if (0 if current is None else current.revision) != expected_revision:
            raise ValueError("trusted artifact revision conflict")
        self._records[key] = record
        return record

    async def get(
        self, kind: TrustedArtifactKind, artifact_id: str
    ) -> TrustedArtifactRecord | None:
        return self._records.get((kind, artifact_id))

    async def disable_by_source(
        self, *, source_id: str, now: datetime
    ) -> tuple[TrustedArtifactRecord, ...]:
        disabled: list[TrustedArtifactRecord] = []
        for key, rec in list(self._records.items()):
            if rec.kind is TrustedArtifactKind.SKILL and rec.source == source_id:
                updated = replace(
                    rec,
                    state=TrustedArtifactState.DISABLED,
                    revision=rec.revision + 1,
                    updated_at=now,
                )
                self._records[key] = updated
                disabled.append(updated)
        return tuple(sorted(disabled, key=lambda item: item.artifact_id))


class CoordinatedSkillSourceRevoker:
    def __init__(
        self,
        *,
        sources: SkillSourceStore,
        quarantine: SkillQuarantineStore,
        revocations: SkillRevocationStore,
        artifacts: InMemoryTrustedSkillArtifactStore,
    ) -> None:
        self._sources, self._quarantine = sources, quarantine
        self._revocations, self._artifacts = revocations, artifacts

    async def revoke_source(
        self, *, source_id: str, reason: str, revoked_at: datetime
    ) -> SkillSourceRevocationResult:
        if await self._sources.get(source_id) is None:
            raise LookupError("skill source not found")
        await self._sources.set_enabled(source_id, enabled=False, now=revoked_at)
        quarantined = await self._quarantine.mark_revoked(source_id=source_id)
        disabled_records = await self._artifacts.disable_by_source(
            source_id=source_id, now=revoked_at
        )
        digests = tuple(
            sorted(
                {i.artifact_digest for i in quarantined}
                | {i.content_sha256 for i in disabled_records}
            )
        )
        for digest in digests:
            await self._revocations.put(
                SkillRevocation(
                    f"skill-revocation-{source_id}-{digest[:16]}",
                    source_id,
                    digest,
                    reason,
                    revoked_at,
                )
            )
        return SkillSourceRevocationResult(
            source_id, digests, tuple(item.artifact_id for item in disabled_records)
        )


@dataclass(frozen=True, slots=True)
class SkillSourceRuntimeBundle:
    sources: SkillSourceStore
    quarantine: SkillQuarantineStore
    candidates: SkillUpdateCandidateStore
    revocations: SkillRevocationStore
    refresh_states: SkillSourceRefreshStateStore
    artifact_store: InMemoryTrustedSkillArtifactStore
    refresh_service: SkillSourceRefreshService
    admin_service: SkillSourceAdministrationService
    orchestrator: SkillSourceRefreshOrchestrator
    runner_guard: SkillSourceRunnerGuard

    async def run_scheduled_tick(
        self, runner_id: str, *, now: datetime, lease_seconds: int = DEFAULT_RUNNER_LEASE_SECONDS
    ) -> tuple[SkillSourceRefreshAttempt, ...]:
        self.runner_guard.acquire(runner_id, now=now, lease_seconds=lease_seconds)
        try:
            return await self.orchestrator.run_due(now=now)
        finally:
            self.runner_guard.release(runner_id)

    async def recover_after_restart(
        self, runner_id: str, *, now: datetime, lease_seconds: int = DEFAULT_RUNNER_LEASE_SECONDS
    ) -> SkillSourceRestartRecoveryReceipt:
        self.runner_guard.force_recover(runner_id, now=now, lease_seconds=lease_seconds)
        try:
            all_sources = await self.sources.list(enabled_only=False)
            reclaimed_due: list[str] = []
            preserved_etags: dict[str, str] = {}
            for source in all_sources:
                state = await self.refresh_states.get(source.source_id)
                if state is not None and state.last_etag is not None:
                    preserved_etags[source.source_id] = state.last_etag
                if (
                    source.enabled
                    and source.refresh_policy is SkillSourceRefreshPolicy.SCHEDULED
                    and state is not None
                    and state.last_refresh_at is None
                    and state.next_refresh_at is not None
                    and state.next_refresh_at <= now
                ):
                    await self.refresh_states.put(replace(state, next_refresh_at=now))
                    reclaimed_due.append(source.source_id)
            candidates = await self.candidates.list()
            revocations = await self.revocations.list()
            return SkillSourceRestartRecoveryReceipt(
                runner_id,
                now,
                tuple(reclaimed_due),
                preserved_etags,
                tuple(s.source_id for s in all_sources if not s.enabled),
                tuple(c.candidate_id for c in candidates if c.disabled),
                tuple(sorted({item.source_id for item in revocations})),
            )
        finally:
            self.runner_guard.release(runner_id)


def build_skill_source_runtime_bundle(
    *,
    adapter_factory: SkillSourceAdapterFactory,
    verifier_factory: SkillSourceVerifierFactory,
    sources: SkillSourceStore | None = None,
    quarantine: SkillQuarantineStore | None = None,
    candidates: SkillUpdateCandidateStore | None = None,
    revocations: SkillRevocationStore | None = None,
    refresh_states: SkillSourceRefreshStateStore | None = None,
    artifact_store: InMemoryTrustedSkillArtifactStore | None = None,
    revoker: SkillSourceRevoker | None = None,
    scanner: DeterministicSkillScanner | None = None,
    scanner_version: str = DEFAULT_SCANNER_VERSION,
    catalog: SkillCatalog | None = None,
    refresh_runtime: Callable[[], Awaitable[None]] | None = None,
    runner_guard: SkillSourceRunnerGuard | None = None,
) -> SkillSourceRuntimeBundle:
    src_store = sources or InMemorySkillSourceStore()
    quar_store = quarantine or InMemorySkillQuarantineStore()
    cand_store = candidates or InMemorySkillUpdateCandidateStore(quar_store)
    rev_store = revocations or InMemorySkillRevocationStore()
    state_store = refresh_states or InMemorySkillSourceRefreshStateStore()
    art_store = artifact_store or InMemoryTrustedSkillArtifactStore()
    revoker_impl = revoker or CoordinatedSkillSourceRevoker(
        sources=src_store, quarantine=quar_store, revocations=rev_store, artifacts=art_store
    )
    refresher = SkillSourceRefreshService(
        quarantine=quar_store,
        candidates=cand_store,
        scanner=scanner or DeterministicSkillScanner(),
        verifier_factory=verifier_factory,
        scanner_version=scanner_version,
    )
    admin = SkillSourceAdministrationService(
        sources=src_store,
        quarantine=quar_store,
        candidates=cand_store,
        revocations=rev_store,
        refresher=refresher,
        installer=TrustedArtifactInstaller(store=art_store),
        verifier_factory=verifier_factory,
        revoker=revoker_impl,
        catalog=catalog or SkillCatalog(),
        refresh_runtime=refresh_runtime,
    )
    orchestrator = SkillSourceRefreshOrchestrator(
        sources=src_store, states=state_store, refresher=refresher, adapter_factory=adapter_factory
    )
    return SkillSourceRuntimeBundle(
        src_store,
        quar_store,
        cand_store,
        rev_store,
        state_store,
        art_store,
        refresher,
        admin,
        orchestrator,
        runner_guard or InMemorySkillSourceRunnerGuard(),
    )
