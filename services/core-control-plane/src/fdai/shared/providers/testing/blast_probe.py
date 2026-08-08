"""In-memory :class:`LiveBlastProbe` for tests + upstream Day-1 wiring.

Upstream ships this "no-opinion" probe so an ActionType with an
unbound ``live_probe_ref`` never lowers autonomy on its own; a fork
replaces it with a live adapter (Azure Monitor, Prometheus, ...) once
it is ready to enforce.

Test hooks:

- ``force_verdict(verdict, *, reason='', metrics=None, degraded=False)`` -
  next :meth:`measure` returns exactly ``verdict``.
- ``next_timeout()`` - raises :class:`BlastProbeTimeoutError` on the next call.
- ``next_error(exc)`` - raises ``exc`` on the next call.
- ``record`` / ``queries`` - assertion helpers listing every query the
  RiskGate made in order.
"""

from __future__ import annotations

from collections.abc import Mapping

from fdai.shared.providers.blast_probe import (
    BlastProbeTimeoutError,
    LiveBlastProbe,
    ProbeQuery,
    ProbeResult,
    ProbeVerdict,
)


class NoOpBlastProbe(LiveBlastProbe):
    """Default upstream probe: always ``no_opinion`` unless overridden.

    The RiskGate treats :attr:`ProbeVerdict.NO_OPINION` as
    ceiling-neutral, so binding this fake at composition time keeps
    the static ceiling in charge until a live adapter lands.
    """

    def __init__(self) -> None:
        self._queries: list[ProbeQuery] = []
        self._next_result: ProbeResult | None = None
        self._next_timeout: bool = False
        self._next_error: Exception | None = None

    async def measure(self, query: ProbeQuery) -> ProbeResult:
        self._queries.append(query)

        if self._next_timeout:
            self._next_timeout = False
            raise BlastProbeTimeoutError(
                f"probe {query.probe_id!r} exceeded deadline {query.deadline_seconds}s (fake)"
            )

        if self._next_error is not None:
            err, self._next_error = self._next_error, None
            raise err

        if self._next_result is not None:
            result, self._next_result = self._next_result, None
            return result

        return ProbeResult(
            verdict=ProbeVerdict.NO_OPINION,
            reason="NoOpBlastProbe: no live adapter bound",
        )

    # ------------------------------------------------------------------
    # Test-only hooks
    # ------------------------------------------------------------------

    def force_verdict(
        self,
        verdict: ProbeVerdict,
        *,
        reason: str = "",
        metrics: Mapping[str, float] | None = None,
        degraded: bool = False,
    ) -> None:
        """Force the very next :meth:`measure` call to return ``verdict``."""
        self._next_result = ProbeResult(
            verdict=verdict,
            reason=reason or f"forced verdict {verdict.value}",
            metrics=dict(metrics or {}),
            degraded=degraded,
        )

    def next_timeout(self) -> None:
        """Raise :class:`BlastProbeTimeoutError` on the very next call."""
        self._next_timeout = True

    def next_error(self, exc: Exception) -> None:
        """Raise ``exc`` on the very next call."""
        self._next_error = exc

    @property
    def queries(self) -> tuple[ProbeQuery, ...]:
        """Every query the RiskGate has made, in order."""
        return tuple(self._queries)


__all__ = ["NoOpBlastProbe"]
