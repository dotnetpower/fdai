"""Runtime evidence composition for governed discovery activation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fdai.core.readiness import (
    CollectorRunEvidence,
    DiscoveryActivationCoordinator,
    DiscoveryActivationDecision,
    DiscoveryActivationInputs,
    DiscoveryActivationReport,
    DiscoveryEvidenceStatus,
    ProbeStatus,
    ShadowDecisionEvidence,
    StartupProbeResult,
    TimedDiscoveryEvidence,
)
from fdai.delivery.runtime_settings import RuntimeSettingsService
from fdai.rule_catalog.pipeline.collect import CollectorSuccessReceipt
from fdai.runtime.readiness import RuntimeReadinessState
from fdai.shared.providers.state_store import StateStore

_COLLECTOR_SUCCESS_PREFIX = "runtime:collector-success:"
_CROSS_CHECK_PREFIX = "model.cross-check."
_VERIFIER_PROBE_IDS = ("policy.compile",)
_POST_DEPLOY_SMOKE_PROBE_IDS = ("audit.append", "kafka.round-trip")


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class DiscoveryActivationState:
    """Process-local publication gate, disabled until a current report enables it."""

    report: DiscoveryActivationReport | None = None

    def is_enabled(self) -> bool:
        return bool(
            self.report is not None and self.report.decision is DiscoveryActivationDecision.ENABLED
        )


@dataclass(slots=True)
class DiscoveryActivationRuntime:
    """Refresh governed activation evidence without mutating the rule catalog."""

    coordinator: DiscoveryActivationCoordinator
    state_store: StateStore
    runtime_settings: RuntimeSettingsService
    startup_readiness: RuntimeReadinessState
    state: DiscoveryActivationState
    refresh_interval_seconds: float = 60.0
    clock: Callable[[], datetime] = _utc_now
    _shadow_decision_count: Callable[[], int] | None = None

    def __post_init__(self) -> None:
        if self.refresh_interval_seconds <= 0:
            raise ValueError("discovery activation refresh interval MUST be > 0")

    def bind_shadow_decision_count(self, source: Callable[[], int]) -> None:
        """Bind the running Pantheon's current shadow decision counter."""
        self._shadow_decision_count = source

    def is_enabled(self) -> bool:
        """Return the current process-local candidate publication decision."""
        return self.state.is_enabled()

    async def evaluate(self) -> DiscoveryActivationReport:
        """Build typed evidence, reduce it, persist it, and update the local gate."""
        self.state.report = None
        now = self.clock()
        values = await self.runtime_settings.effective_values()
        threshold = _positive_integer(values, "discovery.shadow_decision_threshold")
        freshness_seconds = _positive_integer(
            values,
            "discovery.collector_freshness_seconds",
        )
        report = self.startup_readiness.report
        activation = await self.coordinator.evaluate(
            DiscoveryActivationInputs(
                policy_enabled=values.get("discovery.enabled") is True,
                shadow=self._shadow_evidence(now),
                shadow_decision_threshold=threshold,
                collector=await self._collector_evidence(
                    freshness_seconds=freshness_seconds,
                ),
                cross_check=_startup_group_evidence(
                    report.results if report is not None else (),
                    prefix=_CROSS_CHECK_PREFIX,
                    minimum_count=2,
                ),
                verifier=_startup_group_evidence(
                    report.results if report is not None else (),
                    probe_ids=_VERIFIER_PROBE_IDS,
                    minimum_count=1,
                ),
                post_deploy_smoke=_startup_group_evidence(
                    report.results if report is not None else (),
                    probe_ids=_POST_DEPLOY_SMOKE_PROBE_IDS,
                    minimum_count=len(_POST_DEPLOY_SMOKE_PROBE_IDS),
                ),
            ),
            generated_at=now,
        )
        self.state.report = activation
        return activation

    async def refresh_until_stopped(self, stop: asyncio.Event) -> None:
        """Re-evaluate policy and evidence until process shutdown."""
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.refresh_interval_seconds)
            except TimeoutError:
                await self.evaluate()

    def _shadow_evidence(self, now: datetime) -> ShadowDecisionEvidence | None:
        if self._shadow_decision_count is None:
            return None
        count = self._shadow_decision_count()
        if count < 0:
            raise ValueError("shadow decision count MUST be >= 0")
        return ShadowDecisionEvidence(
            status=DiscoveryEvidenceStatus.PASSED,
            observed_at=now,
            expires_at=now + timedelta(seconds=self.refresh_interval_seconds * 2),
            decision_count=count,
        )

    async def _collector_evidence(
        self,
        *,
        freshness_seconds: int,
    ) -> CollectorRunEvidence | None:
        rows = await self.state_store.read_states(_COLLECTOR_SUCCESS_PREFIX, limit=1)
        if not rows:
            return None
        try:
            receipt = CollectorSuccessReceipt.from_mapping(dict(rows[0]))
        except ValueError:
            return None
        return CollectorRunEvidence(
            status=DiscoveryEvidenceStatus.PASSED,
            observed_at=receipt.verified_at,
            expires_at=receipt.verified_at + timedelta(seconds=freshness_seconds),
            source_id=receipt.source_id,
            resolved_revision=receipt.resolved_revision,
            content_sha256=receipt.content_sha256,
            license=receipt.license,
            redistribution=receipt.redistribution,
            verified_rules=receipt.verified_rules,
            schema_validated=True,
            provenance_validated=True,
        )


def build_discovery_activation_runtime(
    *,
    state_store: StateStore,
    runtime_settings: RuntimeSettingsService,
    startup_readiness: RuntimeReadinessState,
) -> DiscoveryActivationRuntime:
    """Build the default-off runtime around the shared StateStore seam."""
    return DiscoveryActivationRuntime(
        coordinator=DiscoveryActivationCoordinator(state_store=state_store),
        state_store=state_store,
        runtime_settings=runtime_settings,
        startup_readiness=startup_readiness,
        state=DiscoveryActivationState(),
    )


def _startup_group_evidence(
    results: tuple[StartupProbeResult, ...],
    *,
    minimum_count: int,
    prefix: str | None = None,
    probe_ids: tuple[str, ...] = (),
) -> TimedDiscoveryEvidence | None:
    selected = tuple(
        result
        for result in results
        if (prefix is not None and result.probe_id.startswith(prefix))
        or result.probe_id in probe_ids
    )
    selected_ids = {result.probe_id for result in selected}
    if len(selected_ids) < minimum_count or (
        probe_ids and not set(probe_ids).issubset(selected_ids)
    ):
        return None
    return TimedDiscoveryEvidence(
        status=(
            DiscoveryEvidenceStatus.PASSED
            if all(result.status is ProbeStatus.PASSED for result in selected)
            else DiscoveryEvidenceStatus.FAILED
        ),
        observed_at=max(result.observed_at for result in selected),
        expires_at=min(result.expires_at for result in selected),
    )


def _positive_integer(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RuntimeError(f"{key} MUST be a positive integer")
    return value


__all__ = [
    "DiscoveryActivationRuntime",
    "DiscoveryActivationState",
    "build_discovery_activation_runtime",
]
