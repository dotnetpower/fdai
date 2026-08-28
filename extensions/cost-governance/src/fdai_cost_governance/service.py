"""Activation-gated deterministic Cost Governance collection and analysis."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fdai.shared.providers.cost_governance import (
    CostAnalysisSample,
    CostCollectionRequest,
    CostObservation,
    CostObservationProvider,
    CostObservationStore,
    CostPackageActivation,
    CostPackageActivationReader,
    CostSamplePublisher,
)


@dataclass(frozen=True, slots=True)
class CostJobConfig:
    package_id: str
    ontology_release_id: str
    ontology_release_digest: str
    known_service_ids: frozenset[str]
    max_pages: int = 10
    max_bytes: int = 10_000_000
    page_size: int = 500
    attempt_timeout: timedelta = timedelta(minutes=2)
    max_observation_age: timedelta = timedelta(days=2)

    def __post_init__(self) -> None:
        if not self.package_id or not self.ontology_release_digest:
            raise ValueError("cost job identity MUST be non-empty")
        if not self.known_service_ids:
            raise ValueError("cost job known services MUST be non-empty")
        if self.max_pages < 1 or self.max_bytes < 1 or not 1 <= self.page_size <= 1000:
            raise ValueError("cost job budgets MUST be positive and bounded")


@dataclass(frozen=True, slots=True)
class CostJobResult:
    status: str
    provider_calls: int = 0
    stored: int = 0
    published: int = 0
    pages: int = 0


class CostCollectorService:
    """Collect provider pages only while an exact package revision is enabled."""

    def __init__(
        self,
        *,
        config: CostJobConfig,
        activation: CostPackageActivationReader,
        provider: CostObservationProvider,
        store: CostObservationStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._activation = activation
        self._provider = provider
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))
        self.diagnostics: dict[str, int] = {}

    async def collect(
        self,
        *,
        scope_id: str,
        start_at: datetime,
        end_at: datetime,
    ) -> CostJobResult:
        active = await self._enabled()
        if active is None:
            return self._result("disabled")
        cursor = await self._store.read_cost_cursor(self._config.package_id, scope_id)
        expected_revision = cursor.revision if cursor else 0
        resume_token = cursor.resume_token if cursor else None
        deadline = self._clock() + self._config.attempt_timeout
        provider_calls = stored = pages = total_bytes = 0
        while pages < self._config.max_pages:
            if self._clock() >= deadline:
                return self._result(
                    "deadline",
                    provider_calls=provider_calls,
                    stored=stored,
                    pages=pages,
                )
            active = await self._enabled()
            if active is None:
                return self._result(
                    "disabled",
                    provider_calls=provider_calls,
                    stored=stored,
                    pages=pages,
                )
            request = CostCollectionRequest(
                package_id=self._config.package_id,
                scope_id=scope_id,
                start_at=start_at,
                end_at=end_at,
                page_size=self._config.page_size,
                deadline_at=deadline,
            )
            page = await self._provider.collect_cost_page(
                request,
                resume_token=resume_token,
            )
            provider_calls += 1
            pages += 1
            total_bytes += page.bytes_read
            invalid = self._invalid_page(page.observations, scope_id, total_bytes)
            if invalid is not None:
                return self._result(
                    invalid,
                    provider_calls=provider_calls,
                    stored=stored,
                    pages=pages,
                )
            if await self._enabled() is None:
                return self._result(
                    "disabled",
                    provider_calls=provider_calls,
                    stored=stored,
                    pages=pages,
                )
            appended = await self._store.append_cost_page(
                page,
                package_id=self._config.package_id,
                scope_id=scope_id,
                expected_revision=expected_revision,
                coverage_through_at=end_at,
                retention_floor_at=start_at,
            )
            if not appended:
                return self._result(
                    "cursor_conflict",
                    provider_calls=provider_calls,
                    stored=stored,
                    pages=pages,
                )
            expected_revision += 1
            stored += len(page.observations)
            resume_token = page.next_resume_token
            if page.complete:
                return CostJobResult(
                    "complete",
                    provider_calls=provider_calls,
                    stored=stored,
                    pages=pages,
                )
        return self._result(
            "page_limit",
            provider_calls=provider_calls,
            stored=stored,
            pages=pages,
        )

    async def _enabled(self) -> CostPackageActivation | None:
        snapshot = await self._activation.read_cost_activation(self._config.package_id)
        if (
            snapshot is None
            or not snapshot.available
            or not snapshot.enabled
            or snapshot.package_id != self._config.package_id
            or snapshot.ontology_release_id != self._config.ontology_release_id
            or snapshot.ontology_release_digest != self._config.ontology_release_digest
        ):
            self._record("activation_unavailable")
            return None
        return snapshot

    def _invalid_page(
        self,
        observations: tuple[CostObservation, ...],
        scope_id: str,
        total_bytes: int,
    ) -> str | None:
        if total_bytes > self._config.max_bytes:
            return "byte_limit"
        now = self._clock()
        seen: set[str] = set()
        for item in observations:
            if item.observation_id in seen:
                return "duplicate_page_fact"
            seen.add(item.observation_id)
            if item.package_id != self._config.package_id or item.scope_id != scope_id:
                return "scope_mismatch"
            if item.service_id not in self._config.known_service_ids:
                return "unknown_service"
            if (
                item.ontology_release_id != self._config.ontology_release_id
                or item.ontology_release_digest != self._config.ontology_release_digest
            ):
                return "ontology_mismatch"
            if item.completeness != Decimal("1"):
                return "incomplete"
            if now - item.observed_at > self._config.max_observation_age:
                return "stale"
            if not item.source_authority.strip():
                return "missing_source_authority"
        return None

    def _record(self, reason: str) -> None:
        self.diagnostics[reason] = self.diagnostics.get(reason, 0) + 1

    def _result(self, status: str, **counts: int) -> CostJobResult:
        self._record(status)
        return CostJobResult(status=status, **counts)


class CostAnalyzerService:
    """Single-publish bridge from retained facts to Njord's typed ingress."""

    def __init__(
        self,
        *,
        config: CostJobConfig,
        activation: CostPackageActivationReader,
        store: CostObservationStore,
        publisher: CostSamplePublisher,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._config = config
        self._activation = activation
        self._store = store
        self._publisher = publisher
        self._clock = clock or (lambda: datetime.now(UTC))
        self.diagnostics: dict[str, int] = {}

    async def analyze(
        self,
        *,
        scope_id: str,
        since: datetime,
        limit: int = 500,
    ) -> CostJobResult:
        snapshot = await self._enabled()
        if snapshot is None:
            return self._result("disabled")
        observations = await self._store.read_cost_observations(
            package_id=self._config.package_id,
            scope_id=scope_id,
            since=since,
            limit=limit,
        )
        cursor = await self._store.read_cost_cursor(self._config.package_id, scope_id)
        if cursor is None:
            return self._result("cursor_missing")
        analysis_revision = cursor.analysis_revision
        last_published = (
            (cursor.last_published_at, cursor.last_published_observation_id)
            if cursor.last_published_at is not None
            and cursor.last_published_observation_id is not None
            else None
        )
        published = 0
        seen: set[str] = set()
        for item in sorted(observations, key=lambda fact: (fact.observed_at, fact.observation_id)):
            if (
                last_published is not None
                and (
                    item.observed_at,
                    item.observation_id,
                )
                <= last_published
            ):
                continue
            reason = self._invalid(item, seen)
            if reason is not None:
                self._record(reason)
                continue
            snapshot = await self._enabled()
            if snapshot is None:
                return self._result("disabled", published=published)
            await self._publisher.publish_cost_sample(
                item,
                activation_revision=snapshot.revision,
            )
            advanced = await self._store.advance_cost_analysis_cursor(
                package_id=self._config.package_id,
                scope_id=scope_id,
                observation_id=item.observation_id,
                observed_at=item.observed_at,
                expected_analysis_revision=analysis_revision,
            )
            if not advanced:
                return self._result("analysis_cursor_conflict", published=published + 1)
            analysis_revision += 1
            last_published = (item.observed_at, item.observation_id)
            seen.add(item.observation_id)
            published += 1
        return CostJobResult("complete", published=published)

    async def _enabled(self) -> CostPackageActivation | None:
        snapshot = await self._activation.read_cost_activation(self._config.package_id)
        if (
            snapshot is None
            or not snapshot.available
            or not snapshot.enabled
            or snapshot.ontology_release_id != self._config.ontology_release_id
            or snapshot.ontology_release_digest != self._config.ontology_release_digest
        ):
            self._record("activation_unavailable")
            return None
        return snapshot

    def _invalid(self, item: CostObservation, seen: set[str]) -> str | None:
        if item.observation_id in seen:
            return "duplicate"
        if item.service_id not in self._config.known_service_ids:
            return "unknown_service"
        if (
            item.ontology_release_id != self._config.ontology_release_id
            or item.ontology_release_digest != self._config.ontology_release_digest
        ):
            return "ontology_mismatch"
        if item.completeness != Decimal("1"):
            return "incomplete"
        if self._clock() - item.observed_at > self._config.max_observation_age:
            return "stale"
        if not item.source_authority.strip():
            return "missing_source_authority"
        return None

    def _record(self, reason: str) -> None:
        self.diagnostics[reason] = self.diagnostics.get(reason, 0) + 1

    def _result(self, status: str, **counts: int) -> CostJobResult:
        self._record(status)
        return CostJobResult(status=status, **counts)


def observation_to_sample(item: CostObservation) -> CostAnalysisSample:
    """Convert a retained fact to Njord's package-neutral analysis input."""

    return CostAnalysisSample(
        scope_id=item.scope_id,
        resource_id=item.source_uri,
        amount_usd=item.amount,
        correlation_id=item.observation_id,
        observed_at=item.observed_at,
        source_authority=item.source_authority,
        completeness=item.completeness,
        ontology_release_digest=item.ontology_release_digest,
    )


__all__ = [
    "CostAnalyzerService",
    "CostCollectorService",
    "CostJobConfig",
    "CostJobResult",
    "observation_to_sample",
]
