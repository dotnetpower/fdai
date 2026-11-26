"""Integrity-pinned orchestration for read-only configuration drift checks."""

from __future__ import annotations

import logging
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

_LOGGER = logging.getLogger(__name__)


class BaselineIntegrityError(RuntimeError):
    """The loaded baseline does not match the server-owned immutable binding."""


class ConfigurationBaselineSource(Protocol):
    """Load one frozen baseline from a durable source."""

    async def load(self) -> FrozenConfigurationBaseline: ...


class ConfigurationObservationSource(Protocol):
    """Observe current state inside one exact configured scope."""

    async def observe(self, *, scope: str) -> ConfigurationObservation: ...


class ConfigurationDriftReportSink(Protocol):
    """Record completed, integrity-checked evidence without granting authority."""

    async def record(
        self,
        baseline: FrozenConfigurationBaseline,
        report: ConfigurationDriftReport,
    ) -> None: ...


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
        report_sink: ConfigurationDriftReportSink | None = None,
        monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        if (
            not isinstance(expected_version, str)
            or not expected_version.strip()
            or not isinstance(expected_scope, str)
            or not expected_scope.strip()
        ):
            raise ValueError("expected baseline version and scope MUST be non-empty")
        normalized_sha = expected_sha256.strip().lower() if isinstance(expected_sha256, str) else ""
        if len(normalized_sha) != 64 or any(c not in "0123456789abcdef" for c in normalized_sha):
            raise ValueError("expected_sha256 MUST be a SHA-256 digest")
        self._baseline_source = baseline_source
        self._observation_source = observation_source
        self._expected_version = expected_version.strip()
        self._expected_sha256 = normalized_sha
        self._expected_scope = expected_scope.strip()
        self._knowledge_source = knowledge_source
        self._report_sink = report_sink
        self._monotonic = monotonic

    async def run(self) -> ConfigurationDriftReport:
        """Read the pinned scope and record the result before returning it.

        A configured sink failure propagates instead of claiming a durably
        recorded result. Measured latency covers evidence acquisition and
        comparison, not persistence.
        """

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
        baseline_load_ms = max(0.0, (baseline_loaded_at - started_at) * 1000.0)
        observation_ms = max(0.0, (observed_at - baseline_loaded_at) * 1000.0)
        comparison_ms = max(0.0, (compared_at - observed_at) * 1000.0)
        knowledge_ms = max(0.0, (completed_at - compared_at) * 1000.0)
        total_ms = max(
            baseline_load_ms + observation_ms + comparison_ms + knowledge_ms,
            (completed_at - started_at) * 1000.0,
        )
        completed_report = replace(
            report,
            knowledge_status=status,
            knowledge_citations=citations,
            performance=ConfigurationDriftPerformance(
                baseline_load_ms=baseline_load_ms,
                observation_ms=observation_ms,
                comparison_ms=comparison_ms,
                knowledge_ms=knowledge_ms,
                total_ms=total_ms,
                resource_count=len(observation.resources),
                finding_count=len(report.findings),
            ),
        )
        if self._report_sink is not None:
            await self._report_sink.record(baseline, completed_report)
        return completed_report

    async def _knowledge_citations(
        self,
        baseline: FrozenConfigurationBaseline,
    ) -> tuple[KnowledgeGroundingStatus, tuple[str, ...]]:
        if self._knowledge_source is None:
            return KnowledgeGroundingStatus.NOT_CONFIGURED, ()
        query = f"configuration baseline {baseline.version} {baseline.document_sha256}"
        try:
            chunks = await self._knowledge_source.search(query, k=5)
        except Exception as exc:  # noqa: BLE001 - grounding failure cannot change drift evidence
            _LOGGER.warning(
                "configuration_drift_knowledge_failed",
                extra={
                    "baseline_version": baseline.version,
                    "baseline_sha256": baseline.sha256,
                    "error_type": type(exc).__name__,
                },
            )
            return KnowledgeGroundingStatus.BLOCKED, ()
        matching = tuple(
            chunk
            for chunk in chunks
            if chunk.metadata.get("baseline_version") == baseline.version
            and chunk.metadata.get("document_sha256") == baseline.document_sha256
        )
        if not matching:
            return KnowledgeGroundingStatus.BLOCKED, ()
        citations = tuple(
            dict.fromkeys(
                f"knowledge:{chunk.source_ref.strip()}#{chunk.chunk_id.strip()}"
                for chunk in matching
                if isinstance(chunk.source_ref, str)
                and chunk.source_ref.strip()
                and isinstance(chunk.chunk_id, str)
                and chunk.chunk_id.strip()
            )
        )
        if not citations:
            return KnowledgeGroundingStatus.BLOCKED, ()
        return KnowledgeGroundingStatus.CITED, citations


__all__ = [
    "BaselineIntegrityError",
    "ConfigurationBaselineSource",
    "ConfigurationDriftService",
    "ConfigurationDriftReportSink",
    "ConfigurationObservationSource",
]
