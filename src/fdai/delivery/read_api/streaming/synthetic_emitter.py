"""Synthetic control-loop stage producer for local read API demos."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fdai.delivery.read_api.streaming.contracts import LiveEmitter
from fdai.shared.providers.sse import SseSink
from fdai.shared.providers.stage_publisher import (
    ObservationSource,
    StageEvent,
    StageName,
    StagePhase,
    StagePublisher,
)
from fdai.shared.streaming.stage_publisher import SseSinkStagePublisher

_LOGGER = logging.getLogger(__name__)


@dataclass
class SyntheticLiveEmitter(LiveEmitter):
    """Publish synthetic control-loop stage transitions at a target rate."""

    sink: SseSink
    channel: str = "aw.pipeline.stages"
    events_per_second: float = 5.0
    tier_weights: Mapping[str, float] = field(
        default_factory=lambda: {"t0": 0.75, "t1": 0.18, "t2": 0.07}
    )
    gate_weights_by_tier: Mapping[str, Mapping[str, float]] = field(
        default_factory=lambda: {
            "t0": {"auto": 0.92, "hil": 0.03, "abstain": 0.01, "deny": 0.04},
            "t1": {"auto": 0.83, "hil": 0.10, "abstain": 0.04, "deny": 0.03},
            "t2": {"auto": 0.35, "hil": 0.42, "abstain": 0.18, "deny": 0.05},
        }
    )
    catalog: tuple[tuple[str, str, str, str], ...] = field(
        default_factory=lambda: (
            ("storage.public-blob.deny", "storage.public-blob.disable", "rg-webapp", "change"),
            ("database.pitr.required", "database.enable-pitr", "rg-billing", "resilience"),
            (
                "compute.autoscale.floor.min-2",
                "compute.autoscale.raise-floor",
                "rg-web-eu",
                "change",
            ),
            ("identity.cert.expiry.30d", "identity.cert.rotate", "rg-core", "change"),
            ("cost.rightsize.candidate", "cost.rightsize.downshift-cpu", "rg-batch", "cost"),
            (
                "network.firewall.orphan-rule",
                "network.firewall.deny-orphan",
                "rg-net",
                "change",
            ),
            (
                "k8s.rbac.cluster-admin.narrow",
                "k8s.rbac.narrow-cluster-admin",
                "aks-prod",
                "change",
            ),
            (
                "network.dns.public-resolver.deny",
                "network.dns.pin-internal",
                "rg-net",
                "change",
            ),
            ("keyvault.access.grant-narrow", "keyvault.grant-narrow", "rg-ident", "change"),
            (
                "observability.log.retention",
                "observability.log.extend-retention",
                "rg-obs",
                "change",
            ),
            ("cost.orphan-disk.cleanup", "cost.disk.delete-orphan", "rg-legacy", "cost"),
            (
                "reliability.replica-lag.alert",
                "reliability.replica.failover",
                "rg-db-eu",
                "resilience",
            ),
            ("storage.tls.min-1_2", "storage.tls.enforce-min-1_2", "rg-media", "change"),
            ("compute.public-ip.deny", "compute.public-ip.remove", "rg-net", "change"),
            (
                "cost.reserved-instance.recommend",
                "cost.ri.propose-purchase",
                "rg-fleet",
                "cost",
            ),
            (
                "reliability.backup.stale",
                "reliability.backup.trigger",
                "rg-billing",
                "resilience",
            ),
        )
    )
    rng_seed: int | None = None
    _task: asyncio.Task[None] | None = field(default=None, init=False, repr=False)
    _running: bool = field(default=False, init=False, repr=False)
    _counter: int = field(default=0, init=False, repr=False)
    _rng: random.Random = field(default_factory=random.Random, init=False, repr=False)
    _publisher: StagePublisher = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.events_per_second <= 0:
            raise ValueError("events_per_second MUST be positive")
        if abs(sum(self.tier_weights.values()) - 1.0) > 0.01:
            raise ValueError("tier_weights MUST sum to ~1.0")
        for tier, mix in self.gate_weights_by_tier.items():
            if abs(sum(mix.values()) - 1.0) > 0.01:
                raise ValueError(f"gate_weights_by_tier[{tier!r}] MUST sum to ~1.0")
        if not self.catalog:
            raise ValueError("catalog MUST NOT be empty")
        if self.rng_seed is not None:
            self._rng = random.Random(self.rng_seed)  # noqa: S311
        self._publisher = SseSinkStagePublisher(self.sink, channel=self.channel)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.get_running_loop().create_task(
            self._run(), name="fdai.live.synthetic-emitter"
        )

    async def stop(self) -> None:
        self._running = False
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                _LOGGER.debug("live_emitter_stop_exception", exc_info=True)

    async def _run(self) -> None:
        interval = 1.0 / self.events_per_second
        try:
            while self._running:
                await self._emit_one_sequence()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def _emit_one_sequence(self) -> None:
        self._counter += 1
        tier = self._pick_tier()
        rule, action_type, scope, vertical = self._rng.choice(self.catalog)
        outcome = self._pick_outcome(tier)
        event_id = f"evt-{self._counter:012d}"
        correlation_id = f"corr-{self._counter:012d}"
        base_detail: dict[str, Any] = {
            "tier": tier,
            "rule": rule,
            "action_type": action_type,
            "scope": scope,
            "vertical": vertical,
            "latency_ms": self._pick_latency_ms(tier),
            "latency_budget_ms": {"t0": 2000, "t1": 5000, "t2": 15000}.get(tier, 5000),
            "mode": "shadow",
        }
        await self._emit(event_id, correlation_id, StageName.INGEST, base_detail, "Huginn")
        await self._emit(
            event_id,
            correlation_id,
            StageName.ROUTE,
            {**base_detail, "routed_to": tier},
            "Heimdall",
        )
        if tier != "t0":
            await self._emit(
                event_id,
                correlation_id,
                StageName.VERIFY,
                {**base_detail, "checks": ["schema", "policy", "what_if"]},
                "Forseti",
            )
        await self._emit(
            event_id,
            correlation_id,
            StageName.GATE,
            {**base_detail, "gate_decision": outcome},
            "Var" if outcome == "hil" else "Forseti",
        )
        if outcome == "auto":
            await self._emit(
                event_id,
                correlation_id,
                StageName.EXECUTE,
                {**base_detail, "mode": "shadow"},
                "Thor",
            )
        await self._emit(
            event_id,
            correlation_id,
            StageName.AUDIT,
            {**base_detail, "gate_decision": outcome},
            "Saga",
        )

    async def _emit(
        self,
        event_id: str,
        correlation_id: str,
        stage: StageName,
        detail: Mapping[str, Any],
        principal: str,
    ) -> None:
        await self._publisher.emit(
            StageEvent(
                event_id=event_id,
                correlation_id=correlation_id,
                stage=stage,
                phase=StagePhase.DONE,
                source=ObservationSource.SYNTHETIC_DEV,
                detail={**detail, "producer_principal": principal},
            )
        )

    def _pick_tier(self) -> str:
        return self._weighted_choice(self.tier_weights)

    def _pick_outcome(self, tier: str) -> str:
        return self._weighted_choice(self.gate_weights_by_tier[tier])

    def _weighted_choice(self, weights: Mapping[str, float]) -> str:
        target = self._rng.random()
        accumulated = 0.0
        for value, weight in weights.items():
            accumulated += weight
            if target < accumulated:
                return value
        return next(iter(weights))

    def _pick_latency_ms(self, tier: str) -> int:
        base = {"t0": 320.0, "t1": 750.0, "t2": 2100.0}.get(tier, 400.0)
        jitter = 0.75 + self._rng.random() * 0.5
        return int(round(base * jitter))


__all__ = ["SyntheticLiveEmitter"]
