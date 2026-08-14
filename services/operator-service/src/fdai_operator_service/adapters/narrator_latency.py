"""Bounded latency and TTFT windows for service-local narrator routing."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median

_MAX_LATENCY_SAMPLES = 8


@dataclass(frozen=True, slots=True)
class NarratorTarget:
    """One validated Azure OpenAI narrator deployment from the resolved artifact."""

    endpoint: str
    deployment: str
    api_version: str


@dataclass(frozen=True, slots=True)
class NarratorLatencyStats:
    """Sanitized rolling timing evidence for one narrator deployment."""

    deployment: str
    sample_count: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    ttft_p50_ms: float | None
    ttft_p95_ms: float | None


@dataclass(slots=True)
class _TimingWindow:
    latency_ms: list[float] = field(default_factory=list)
    ttft_ms: list[float] = field(default_factory=list)

    def add(self, *, latency_ms: float, ttft_ms: float) -> None:
        if (
            not math.isfinite(latency_ms)
            or not math.isfinite(ttft_ms)
            or latency_ms < 0
            or ttft_ms < 0
            or ttft_ms > latency_ms
        ):
            raise ValueError("narrator timing sample is invalid")
        self.latency_ms.append(latency_ms)
        self.ttft_ms.append(ttft_ms)
        del self.latency_ms[:-_MAX_LATENCY_SAMPLES]
        del self.ttft_ms[:-_MAX_LATENCY_SAMPLES]

    def stats(self, deployment: str) -> NarratorLatencyStats:
        return NarratorLatencyStats(
            deployment=deployment,
            sample_count=len(self.latency_ms),
            latency_p50_ms=_percentile(self.latency_ms, 0.50),
            latency_p95_ms=_percentile(self.latency_ms, 0.95),
            ttft_p50_ms=_percentile(self.ttft_ms, 0.50),
            ttft_p95_ms=_percentile(self.ttft_ms, 0.95),
        )


@dataclass(slots=True)
class NarratorLatencyPool:
    """Rank text and vision candidates from bounded independent timing windows."""

    text_targets: tuple[NarratorTarget, ...]
    vision_targets: tuple[NarratorTarget, ...]
    _text_windows: dict[str, _TimingWindow] = field(init=False, repr=False)
    _vision_windows: dict[str, _TimingWindow] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.text_targets:
            raise ValueError("narrator text candidate pool MUST be non-empty")
        _require_unique_deployments(self.text_targets, "text")
        _require_unique_deployments(self.vision_targets, "vision")
        self._text_windows = {target.deployment: _TimingWindow() for target in self.text_targets}
        self._vision_windows = {
            target.deployment: _TimingWindow() for target in self.vision_targets
        }

    def ranked(self, *, vision: bool) -> tuple[NarratorTarget, ...]:
        targets = self.vision_targets if vision else self.text_targets
        windows = self._vision_windows if vision else self._text_windows
        return tuple(
            sorted(
                targets,
                key=lambda target: _rank_key(windows[target.deployment]),
            )
        )

    def record(
        self,
        *,
        deployment: str,
        vision: bool,
        latency_ms: float,
        ttft_ms: float,
    ) -> None:
        windows = self._vision_windows if vision else self._text_windows
        window = windows.get(deployment)
        if window is None:
            raise ValueError("narrator timing target is not registered in the selected pool")
        window.add(latency_ms=latency_ms, ttft_ms=ttft_ms)

    def snapshot(self, *, vision: bool = False) -> tuple[NarratorLatencyStats, ...]:
        targets = self.vision_targets if vision else self.text_targets
        windows = self._vision_windows if vision else self._text_windows
        return tuple(windows[target.deployment].stats(target.deployment) for target in targets)


def _rank_key(window: _TimingWindow) -> tuple[float, ...]:
    if not window.latency_ms:
        return (0.0, 0.0, 0.0)
    return (1.0, median(window.latency_ms), median(window.ttft_ms))


def _percentile(samples: list[float], quantile: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + ((ordered[upper] - ordered[lower]) * fraction)


def _require_unique_deployments(
    targets: tuple[NarratorTarget, ...],
    pool: str,
) -> None:
    deployments = tuple(target.deployment for target in targets)
    if len(deployments) != len(set(deployments)):
        raise ValueError(f"narrator {pool} candidate deployments MUST be unique")


__all__ = ["NarratorLatencyPool", "NarratorLatencyStats", "NarratorTarget"]
