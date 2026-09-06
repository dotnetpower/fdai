"""Fresh, bounded routing evidence for presentation-only mini narrators."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from statistics import median

import httpx

from fdai.delivery.azure.llm.adaptive_answer import (
    AdaptiveModelTarget,
    AzureOpenAIAdaptiveModel,
    AzureOpenAIAdaptiveModelConfig,
)
from fdai.shared.providers.workload_identity import WorkloadIdentity

T1_ROUTING_STATE_KEY = "conversation:t1-mini-routing:v1"


class T1MiniRouting:
    """Rank verified mini candidates without changing judge or T2 bindings.

    A model factory returns an immutable author/reviewer pair for a whole turn.
    Failed candidates are ineligible until a successful probe; missing or stale
    measurements preserve configured order without claiming measured speed.
    """

    def __init__(
        self,
        *,
        candidates: tuple[AdaptiveModelTarget, ...],
        config: AzureOpenAIAdaptiveModelConfig,
        identity: WorkloadIdentity,
        http_client: httpx.AsyncClient,
        enabled: bool = False,
        interval_seconds: int = 300,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if type(interval_seconds) is not int or not 30 <= interval_seconds <= 3600:
            raise ValueError("narrator probe interval MUST be in [30, 3600]")
        if type(enabled) is not bool:
            raise ValueError("narrator probe enabled MUST be boolean")
        minis = tuple(item for item in candidates if item.family.casefold().endswith("-mini"))
        self.candidates = minis[:4]
        if not self.candidates or len({c.target.deployment for c in self.candidates}) != len(
            self.candidates
        ):
            raise ValueError("mini routing requires distinct verified narrator deployments")
        self.enabled = enabled
        self.interval_seconds = interval_seconds
        self._config = config
        self._identity = identity
        self._http = http_client
        self._now = now
        self._samples: dict[str, deque[tuple[datetime, float]]] = {
            c.target.deployment: deque(maxlen=8) for c in self.candidates
        }
        self._failures: set[str] = set()

    def record(self, deployment: str, duration_ms: float | None) -> None:
        """Record one verified probe, or explicitly exclude its failed deployment."""
        if deployment not in self._samples:
            raise ValueError("probe deployment MUST belong to the configured mini pool")
        if duration_ms is None:
            self._failures.add(deployment)
            return
        if not math.isfinite(duration_ms) or duration_ms < 0:
            raise ValueError("probe duration MUST be finite and nonnegative")
        self._failures.discard(deployment)
        self._samples[deployment].append((self._now(), duration_ms))

    def _fresh(self, deployment: str) -> list[float]:
        cutoff = self._now() - timedelta(seconds=2 * self.interval_seconds)
        return [value for at, value in self._samples[deployment] if at > cutoff]

    def selected_config(self) -> AzureOpenAIAdaptiveModelConfig | None:
        """Select only a valid independent pair; never probe or mutate another turn."""
        if not self.enabled:
            return self._config
        available = [
            item for item in self.candidates if item.target.deployment not in self._failures
        ]

        def rank(item: AdaptiveModelTarget) -> tuple[bool, float]:
            values = self._fresh(item.target.deployment)
            return (not bool(values), median(values) if values else 0)

        ranked = sorted(available, key=rank)
        for primary in ranked:
            reviewer = next(
                (
                    item
                    for item in ranked
                    if item.independent_of(primary)
                    and (
                        self._config.escalation is None
                        or item.independent_of(self._config.escalation)
                    )
                ),
                None,
            )
            if reviewer is not None:
                return replace(self._config, primary=primary, reviewer=reviewer)
        return None

    def model_for_turn(self) -> AzureOpenAIAdaptiveModel | None:
        """Freeze this turn's pair before any child provider task is created."""
        selected = self.selected_config()
        return (
            AzureOpenAIAdaptiveModel(
                identity=self._identity, http_client=self._http, config=selected
            )
            if selected is not None
            else None
        )

    def snapshot(self) -> dict[str, object]:
        """Project bounded endpoint-free timing evidence, not operational authority."""
        now = self._now()
        selected = self.selected_config()
        model = selected.primary.target.deployment if selected is not None else None
        candidates: list[dict[str, object]] = []
        for item in self.candidates:
            name = item.target.deployment
            values = self._fresh(name)
            history = self._samples[name]
            status = (
                "failed"
                if name in self._failures
                else "measured"
                if values
                else "stale"
                if history
                else "unmeasured"
            )
            measured = status == "measured"
            candidates.append(
                {
                    "deployment": name,
                    "status": status,
                    "measured_at": history[-1][0].isoformat() if history else None,
                    "p50_ms": median(values) if measured else None,
                    "p95_ms": sorted(values)[math.ceil(len(values) * 0.95) - 1]
                    if measured
                    else None,
                    "samples": len(values) if measured else 0,
                    "history_ms": values if measured else [],
                }
            )
        chosen = next((item for item in candidates if item["deployment"] == model), None)
        reason = (
            "disabled"
            if not self.enabled
            else "unavailable"
            if model is None
            else "latency"
            if chosen is not None and chosen["status"] == "measured"
            else "stale"
            if chosen is not None and chosen["status"] == "stale"
            else "unmeasured"
        )
        return {
            "schema_version": 1,
            "source": "core-t1-mini-routing",
            "execution_authority": False,
            "model": model,
            "router": {
                "chose": model or "",
                "reason": reason,
                "updated_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=2 * self.interval_seconds)).isoformat(),
                "interval_seconds": self.interval_seconds,
                "candidates": candidates,
            },
        }
