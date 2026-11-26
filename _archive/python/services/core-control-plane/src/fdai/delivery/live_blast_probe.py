"""Production-capable Axis-E adapter over deployment-supplied neutral sources."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from math import isfinite

from fdai.shared.providers.blast_probe import (
    BlastSignalSource,
    LiveBlastProbe,
    ProbeFailureStreakSource,
    ProbeQuery,
    ProbeResult,
    ProbeVerdict,
)

_FAILURE_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class LiveBlastProbeAdapter(LiveBlastProbe):
    """Read a bounded live signal and fail toward a lower autonomy posture.

    The adapter performs no provider discovery and has no substrate mutation
    capability. Both sources are deployment-owned dependency-injection seams.
    A source failure returns ``active`` until the durable streak reaches the
    threshold, then returns ``overloaded``. A missing or malformed source
    response is never treated as ``quiet``.
    """

    signal_source: BlastSignalSource
    failure_streak_source: ProbeFailureStreakSource
    failure_threshold: int = _FAILURE_THRESHOLD

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold MUST be positive")

    async def measure(self, query: ProbeQuery) -> ProbeResult:
        """Return one bounded result, with timeout and streak handling."""

        deadline = asyncio.get_running_loop().time() + query.deadline_seconds
        try:
            remaining = _remaining(deadline)
            streak = await asyncio.wait_for(
                self.failure_streak_source.get(query),
                timeout=remaining,
            )
            if isinstance(streak, bool) or not isinstance(streak, int) or streak < 0:
                raise ValueError("probe failure streak MUST be a non-negative integer")
        except Exception:
            return ProbeResult(
                verdict=ProbeVerdict.OVERLOADED,
                reason="probe failure streak unavailable",
                degraded=True,
            )
        try:
            remaining = _remaining(deadline)
            result = await asyncio.wait_for(
                self.signal_source.read(query),
                timeout=remaining,
            )
            _validate_result(result)
            if result.degraded:
                failure_result = await self._failure(
                    query,
                    "probe measurement degraded",
                    timeout=False,
                    cause=RuntimeError(result.reason),
                    deadline=deadline,
                )
                return result if result.verdict is ProbeVerdict.OVERLOADED else failure_result
        except TimeoutError as exc:
            return await self._failure(
                query,
                "probe measurement timed out",
                timeout=True,
                cause=exc,
                deadline=deadline,
            )
        except Exception as exc:
            return await self._failure(
                query,
                "probe measurement unavailable",
                timeout=False,
                cause=exc,
                deadline=deadline,
            )

        try:
            remaining = _remaining(deadline)
            await asyncio.wait_for(
                self.failure_streak_source.record_success(query),
                timeout=remaining,
            )
        except Exception as exc:
            # A successful reading without a durable streak update is not
            # trustworthy for a future dispatch.
            failure_result = await self._failure(
                query,
                "probe failure streak source unavailable",
                timeout=False,
                cause=exc,
                deadline=deadline,
            )
            return (
                ProbeResult(
                    verdict=ProbeVerdict.OVERLOADED,
                    reason=(f"{result.reason}; probe failure streak source unavailable"),
                    degraded=True,
                    metrics=result.metrics,
                )
                if result.verdict is ProbeVerdict.OVERLOADED
                else failure_result
            )
        return result

    async def _failure(
        self,
        query: ProbeQuery,
        reason: str,
        *,
        timeout: bool,
        cause: BaseException,
        deadline: float,
    ) -> ProbeResult:
        try:
            remaining = _remaining(deadline)
            streak = await asyncio.wait_for(
                self.failure_streak_source.record_failure(query),
                timeout=remaining,
            )
        except Exception:
            # The streak source is part of the safety decision. If it cannot
            # be read, use the most restrictive result rather than guessing.
            return ProbeResult(
                verdict=ProbeVerdict.OVERLOADED,
                reason=f"{reason}; failure streak unavailable",
                degraded=True,
            )
        if isinstance(streak, bool) or not isinstance(streak, int) or streak < 1:
            return ProbeResult(
                verdict=ProbeVerdict.OVERLOADED,
                reason=f"{reason}; failure streak malformed",
                degraded=True,
            )
        verdict = (
            ProbeVerdict.OVERLOADED if streak >= self.failure_threshold else ProbeVerdict.ACTIVE
        )
        detail = f"{reason}; consecutive failures={streak}"
        if timeout:
            detail = f"{detail}; timeout"
        del cause
        return ProbeResult(verdict=verdict, reason=detail, degraded=True)


def _validate_result(result: object) -> None:
    if not isinstance(result, ProbeResult):
        raise TypeError("probe source MUST return ProbeResult")
    if not isinstance(result.verdict, ProbeVerdict):
        raise TypeError("probe source returned an invalid verdict")
    if type(result.degraded) is not bool:
        raise TypeError("probe source degraded flag MUST be boolean")
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value)
        for value in result.metrics.values()
    ):
        raise ValueError("probe source metrics MUST be finite numeric values")


def _remaining(deadline: float) -> float:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError("live blast probe deadline exhausted")
    return remaining


__all__ = ["LiveBlastProbeAdapter"]
