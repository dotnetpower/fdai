"""Integrity-pinned orchestration for read-only configuration drift checks."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from fdai.core.detection.configuration_drift import (
    ConfigurationDriftPerformance,
    ConfigurationDriftReport,
    ConfigurationObservation,
    FrozenConfigurationBaseline,
    KnowledgeGroundingStatus,
    compare_configuration,
)
from fdai.shared.providers.knowledge import KnowledgeSource


class BaselineIntegrityError(RuntimeError):
    """The loaded baseline does not match the server-owned immutable binding."""


class ConfigurationBaselineSource(Protocol):
    """Load one frozen baseline from a durable source."""

    async def load(self) -> FrozenConfigurationBaseline: ...


class ConfigurationObservationSource(Protocol):
    """Observe current state inside one exact configured scope."""

    async def observe(self, *, scope: str) -> ConfigurationObservation: ...


class ConfigurationDriftService:
    """Compare server-pinned intent with an authoritative scoped observation."""

    def __init__(
        self,
        *,
        baseline_source: ConfigurationBaselineSource,
        observation_source: ConfigurationObservationSource,
        expected_version: str,
        expected_sha256: str,
        expected_scope: str,
        knowledge_source: KnowledgeSource | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        if not expected_version.strip() or not expected_scope.strip():
            raise ValueError("expected baseline version and scope MUST be non-empty")
        if len(expected_sha256) != 64:
            raise ValueError("expected_sha256 MUST be a SHA-256 digest")
        self._baseline_source = baseline_source
        self._observation_source = observation_source
        self._expected_version = expected_version
        self._expected_sha256 = expected_sha256.lower()
        self._expected_scope = expected_scope
        self._knowledge_source = knowledge_source
        self._monotonic = monotonic

    async def run(self) -> ConfigurationDriftReport:
        """Execute one A0 read; never accepts caller-selected scope or baseline."""

        started_at = self._monotonic()
        baseline = await self._baseline_source.load()
        baseline_loaded_at = self._monotonic()
        if baseline.version != self._expected_version:
            raise BaselineIntegrityError("baseline version does not match the configured binding")
        if baseline.sha256 != self._expected_sha256:
            raise BaselineIntegrityError("baseline digest does not match the configured binding")
        if baseline.scope != self._expected_scope:
            raise BaselineIntegrityError("baseline scope does not match the configured binding")

        observation = await self._observation_source.observe(scope=self._expected_scope)
        observed_at = self._monotonic()
        if observation.scope != self._expected_scope:
            raise BaselineIntegrityError("observation escaped the configured scope")
        report = compare_configuration(baseline, observation)
        compared_at = self._monotonic()
        status, citations = await self._knowledge_citations(baseline)
        completed_at = self._monotonic()
        return replace(
            report,
            knowledge_status=status,
            knowledge_citations=citations,
            performance=ConfigurationDriftPerformance(
                baseline_load_ms=(baseline_loaded_at - started_at) * 1000.0,
                observation_ms=(observed_at - baseline_loaded_at) * 1000.0,
                comparison_ms=(compared_at - observed_at) * 1000.0,
                knowledge_ms=(completed_at - compared_at) * 1000.0,
                total_ms=(completed_at - started_at) * 1000.0,
                resource_count=len(observation.resources),
                finding_count=len(report.findings),
            ),
        )

    async def _knowledge_citations(
        self,
        baseline: FrozenConfigurationBaseline,
    ) -> tuple[KnowledgeGroundingStatus, tuple[str, ...]]:
        if self._knowledge_source is None:
            return KnowledgeGroundingStatus.NOT_CONFIGURED, ()
        query = f"configuration baseline {baseline.version} {baseline.document_sha256}"
        try:
            chunks = await self._knowledge_source.search(query, k=5)
        except Exception:  # noqa: BLE001 - grounding failure cannot change drift evidence
            return KnowledgeGroundingStatus.BLOCKED, ()
        matching = tuple(
            chunk
            for chunk in chunks
            if chunk.metadata.get("baseline_version") == baseline.version
            and chunk.metadata.get("document_sha256") == baseline.document_sha256
        )
        if not matching:
            return KnowledgeGroundingStatus.BLOCKED, ()
        citations = tuple(f"knowledge:{chunk.source_ref}#{chunk.chunk_id}" for chunk in matching)
        return KnowledgeGroundingStatus.CITED, citations


__all__ = [
    "BaselineIntegrityError",
    "ConfigurationBaselineSource",
    "ConfigurationDriftService",
    "ConfigurationObservationSource",
]
