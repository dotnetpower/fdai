"""Production skill-source persistence, administration, and refresh wiring."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from fdai.core.skills.source_registry import SkillSource
from fdai.core.supply_chain import TrustedArtifactInstaller
from fdai.core.supply_chain.skill_quarantine import DeterministicSkillScanner
from fdai.core.supply_chain.skill_source_admin import SkillSourceAdministrationService
from fdai.core.supply_chain.skill_source_pipeline import SkillSourceRefreshService
from fdai.core.supply_chain.skill_source_refresh import SkillSourceRefreshOrchestrator
from fdai.delivery.github.skill_source import (
    GitHubSkillSourceAdapter,
    GitHubSkillSourceConfig,
)
from fdai.delivery.persistence.postgres_skill_quarantine import (
    PostgresSkillQuarantineStore,
    PostgresSkillRevocationStore,
    PostgresSkillSourceRevoker,
    PostgresSkillUpdateCandidateStore,
)
from fdai.delivery.persistence.postgres_skill_source import (
    PostgresSkillSourceRefreshStateStore,
    PostgresSkillSourceStore,
    PostgresSkillSourceStoreConfig,
)
from fdai.delivery.persistence.postgres_trusted_artifact import (
    PostgresTrustedArtifactStore,
    PostgresTrustedArtifactStoreConfig,
)
from fdai.delivery.read_api.production.skills import _load_trusted_publishers
from fdai.delivery.read_api.routes.skill_sources import SkillSourceRoutesConfig
from fdai.delivery.trust import Ed25519SkillTrustVerifier
from fdai.shared.providers.secret_provider import SecretProvider

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProductionSkillSources:
    routes: SkillSourceRoutesConfig
    startup: Callable[[], Awaitable[None]]
    shutdown: Callable[[], Awaitable[None]]


class ScheduledSkillSourceRefreshRunner:
    def __init__(
        self,
        *,
        orchestrator: SkillSourceRefreshOrchestrator,
        interval_seconds: int,
    ) -> None:
        if interval_seconds < 30:
            raise ValueError("skill source refresh runner interval MUST be at least 30 seconds")
        self._orchestrator = orchestrator
        self._interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        await self._run_once()
        self._task = asyncio.create_task(self._run(), name="skill-source-refresh")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                await self._run_once()

    async def _run_once(self) -> None:
        attempts = await self._orchestrator.run_due(now=datetime.now(tz=UTC))
        for attempt in attempts:
            _LOGGER.info(
                "skill_source_refresh_completed",
                extra={"source_id": attempt.source_id, "status": attempt.status},
            )


def build_production_skill_sources(
    *,
    env: Mapping[str, str],
    dsn: str,
    statement_timeout_ms: int,
    connect_timeout_s: int,
    secrets: SecretProvider,
    refresh_runtime: Callable[[], Awaitable[None]],
) -> ProductionSkillSources:
    config = PostgresSkillSourceStoreConfig(
        dsn=dsn,
        statement_timeout_ms=statement_timeout_ms,
        connect_timeout_s=connect_timeout_s,
    )
    source_store = PostgresSkillSourceStore(config=config)
    quarantine_store = PostgresSkillQuarantineStore(config=config)
    candidate_store = PostgresSkillUpdateCandidateStore(config=config)
    revocation_store = PostgresSkillRevocationStore(config=config)
    refresh_state_store = PostgresSkillSourceRefreshStateStore(config=config)
    trusted_store = PostgresTrustedArtifactStore(
        config=PostgresTrustedArtifactStoreConfig(
            dsn=dsn,
            statement_timeout_ms=statement_timeout_ms,
            connect_timeout_s=connect_timeout_s,
        )
    )
    trusted_publishers = _load_trusted_publishers(env)
    refresh_service = SkillSourceRefreshService(
        quarantine=quarantine_store,
        candidates=candidate_store,
        scanner=DeterministicSkillScanner(),
        verifier_factory=lambda _source, signature: Ed25519SkillTrustVerifier(
            trusted_publishers=trusted_publishers,
            signature=signature,
        ),
        scanner_version="deterministic-skill-scanner-v1",
    )
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=30.0, write=15.0, pool=5.0)
    )

    def adapter_factory(source: SkillSource) -> GitHubSkillSourceAdapter:
        async def token_provider() -> str:
            return await secrets.get(source.authentication_audience_ref)

        return GitHubSkillSourceAdapter(
            config=GitHubSkillSourceConfig(
                api_base=env.get("FDAI_GITHUB_API_BASE", "https://api.github.com").strip()
            ),
            http_client=http_client,
            token_provider=token_provider,
        )

    administration = SkillSourceAdministrationService(
        sources=source_store,
        quarantine=quarantine_store,
        candidates=candidate_store,
        revocations=revocation_store,
        refresher=refresh_service,
        installer=TrustedArtifactInstaller(store=trusted_store),
        verifier_factory=lambda _source, signature: Ed25519SkillTrustVerifier(
            trusted_publishers=trusted_publishers,
            signature=signature,
        ),
        revoker=PostgresSkillSourceRevoker(config=config),
        refresh_runtime=refresh_runtime,
    )
    runner = ScheduledSkillSourceRefreshRunner(
        orchestrator=SkillSourceRefreshOrchestrator(
            sources=source_store,
            states=refresh_state_store,
            refresher=refresh_service,
            adapter_factory=adapter_factory,
        ),
        interval_seconds=int(env.get("FDAI_SKILL_SOURCE_TICK_SECONDS", "60")),
    )

    async def shutdown() -> None:
        await runner.stop()
        await http_client.aclose()

    return ProductionSkillSources(
        routes=SkillSourceRoutesConfig(
            sources=source_store,
            quarantine=quarantine_store,
            candidates=candidate_store,
            revocations=revocation_store,
            refresh_states=refresh_state_store,
            administration=administration,
        ),
        startup=runner.start,
        shutdown=shutdown,
    )


__all__ = [
    "ProductionSkillSources",
    "ScheduledSkillSourceRefreshRunner",
    "build_production_skill_sources",
]
