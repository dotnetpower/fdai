"""Bridge the ``MetricProvider`` seam to the deterministic burn-rate evaluator.

Design contract: ``docs/roadmap/fork-and-sequencing/scope-expansion.md`` sections 3.2 (telemetry
ingestion seam) and 3.3 (workload SLO / error budget).

The pieces on either side already exist: :class:`BurnRateEvaluator` is a pure,
I/O-free function of per-window ``(good, total)`` pairs, and
:class:`~fdai.shared.providers.metric.MetricProvider` is the CSP-neutral seam
that streams external metric samples. Nothing connected them - the evaluator's
docstring said "callers fetch metric samples ... and hand the pairs here", but
no caller existed. :class:`MetricBurnRateSource` is that caller: it fetches the
SLI good/total counts per alert window from the metric seam, compresses each
window to a ``(good, total)`` pair, and runs the evaluator.

Fail-closed: a window with zero total events, or an inconsistent series where
``good > total``, yields ``insufficient_data=True`` so the caller abstains
rather than emit a false all-clear. This matches the safety-invariant rule in
``architecture.instructions.md`` - the control plane never auto-acts on a
partial or missing observation; it routes to HIL.

The upstream default metric binding is
:class:`~fdai.shared.providers.metric.NoopMetricProvider` (empty result), so
this source reports ``insufficient_data`` until a real adapter (Prometheus
PromQL, Azure Monitor Logs KQL, CloudWatch) is wired at the composition root.
``core/`` never imports a concrete backend.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from fdai.shared.contracts.models import Event, Mode
from fdai.shared.providers.metric import MetricProvider, MetricQuery

from .burn_rate import BurnRateBreach, BurnRateEvaluator, build_alerts
from .models import SLO

_DEFAULT_SOURCE = "fdai.core.slo.burn_rate"
_EVENT_TYPE = "slo.error_budget_burn"


@dataclass(frozen=True, slots=True)
class BurnRateEvaluation:
    """Outcome of evaluating one SLO's burn-rate alerts from live metrics."""

    slo_id: str
    breaches: tuple[BurnRateBreach, ...]
    insufficient_data: bool
    evaluated_at: datetime

    @property
    def breached(self) -> bool:
        """True when at least one multi-window burn-rate alert fired."""
        return bool(self.breaches)


class MetricBurnRateSource:
    """Fetch SLI counts from the metric seam and run the burn-rate evaluator.

    Stateless apart from its injected collaborators; safe to reuse across
    SLOs. Every call is a fresh read - no caching, so a stale evaluation is
    impossible.
    """

    def __init__(
        self,
        metric_provider: MetricProvider,
        *,
        evaluator: BurnRateEvaluator | None = None,
        source: str = _DEFAULT_SOURCE,
    ) -> None:
        self._metrics = metric_provider
        self._evaluator = evaluator if evaluator is not None else BurnRateEvaluator()
        self._source = source

    async def evaluate(self, slo: SLO, *, now: datetime) -> BurnRateEvaluation:
        """Evaluate ``slo``'s burn-rate alerts against metrics up to ``now``.

        Returns an empty, non-insufficient result when the SLO declares no
        burn-rate alerts (nothing to evaluate). Otherwise fetches the good and
        total counts for every referenced window and runs the evaluator,
        abstaining (``insufficient_data=True``) on any window with no data or
        an inconsistent series.
        """
        windows = _required_windows(slo)
        if not windows:
            return BurnRateEvaluation(
                slo_id=slo.id, breaches=(), insufficient_data=False, evaluated_at=now
            )

        samples: dict[int, tuple[int, int]] = {}
        insufficient = False
        for window_minutes in sorted(windows):
            since = now - timedelta(minutes=window_minutes)
            good = await self._count(slo.sli.good_query, slo, since, now)
            total = await self._count(slo.sli.total_query, slo, since, now)
            if total <= 0 or good > total:
                insufficient = True
            samples[window_minutes] = (good, total)

        if insufficient:
            return BurnRateEvaluation(
                slo_id=slo.id, breaches=(), insufficient_data=True, evaluated_at=now
            )

        alerts = build_alerts(slo=slo, samples=samples)
        return BurnRateEvaluation(
            slo_id=slo.id,
            breaches=self._evaluator.evaluate(alerts),
            insufficient_data=False,
            evaluated_at=now,
        )

    def to_events(
        self,
        evaluation: BurnRateEvaluation,
        *,
        slo: SLO,
        mode: Mode = Mode.SHADOW,
    ) -> tuple[Event, ...]:
        """Normalize each burn-rate breach into an ``slo.error_budget_burn`` Event.

        One Event per fired alert, re-entering ``event-ingest`` like any other
        finding (never a side channel; it never auto-remediates on its own) so
        the trust-router / risk-gate / executor path governs the response. The
        idempotency key is derived from ``slo + alert + minute-bucket`` so
        repeated evaluation ticks inside the same minute deduplicate while a
        later re-breach still fires. Returns an empty tuple when the evaluation
        did not breach (an abstained / insufficient-data evaluation emits
        nothing - fail-closed).
        """
        if not evaluation.breaches:
            return ()
        at = evaluation.evaluated_at
        bucket = at.replace(second=0, microsecond=0).isoformat()
        resource_ref = slo.sli.labels.get("resource_id") or slo.id
        events: list[Event] = []
        for breach in evaluation.breaches:
            alert_def = breach.alert.alert
            idempotency_key = str(
                uuid5(NAMESPACE_URL, f"fdai-slo-burn:{slo.id}:{alert_def.name}:{bucket}")
            )
            payload: dict[str, object] = {
                "kind": "slo_burn",
                "slo_id": slo.id,
                "alert": alert_def.name,
                "severity": alert_def.severity,
                "burn_rate_threshold": alert_def.burn_rate_threshold,
                "short_window_minutes": alert_def.short_window_minutes,
                "long_window_minutes": alert_def.long_window_minutes,
                "short_rate": breach.short_rate,
                "long_rate": breach.long_rate,
                "objective_ratio": slo.objective_ratio,
                "resource": {"resource_ref": resource_ref},
            }
            events.append(
                Event(
                    schema_version="1.0.0",
                    event_id=uuid4(),
                    idempotency_key=idempotency_key,
                    source=self._source,
                    event_type=_EVENT_TYPE,
                    resource_ref=resource_ref,
                    payload=payload,
                    detected_at=at,
                    ingested_at=at,
                    mode=mode,
                )
            )
        return tuple(events)

    async def _count(
        self,
        metric_name: str,
        slo: SLO,
        since: datetime,
        until: datetime,
    ) -> int:
        """Sum the metric samples for one SLI query over ``[since, until]``.

        The SLI's ``good_query`` / ``total_query`` are passed as the
        CSP-neutral ``metric_name``; a real adapter maps them to its vendor
        query language. Sample values are summed into an event count.
        """
        query = MetricQuery(
            metric_name=metric_name,
            labels=slo.sli.labels,
            since=since,
            until=until,
            aggregation="sum",
        )
        total = 0.0
        async for point in self._metrics.query(query):
            # An untrusted provider (a fork adapter need not sanitize) can emit
            # a non-finite value. Summed in, it makes ``round(total)`` raise
            # (``round(nan)`` -> ValueError, ``round(inf)`` -> OverflowError),
            # crashing the whole SLO pass. Skip non-finite samples so the count
            # stays finite; a window left with no usable samples reads as zero
            # and the caller's ``total <= 0`` guard abstains (fail-closed).
            if not math.isfinite(point.value):
                continue
            total += point.value
        return round(total)


def _required_windows(slo: SLO) -> set[int]:
    """Every distinct window (minutes) referenced by the SLO's alerts."""
    windows: set[int] = set()
    for alert in slo.burn_rate_alerts:
        windows.add(alert.short_window_minutes)
        windows.add(alert.long_window_minutes)
    return windows


__all__ = ["BurnRateEvaluation", "MetricBurnRateSource"]
