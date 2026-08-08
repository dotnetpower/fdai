"""KPI row emitter for :class:`RecognitionRunReport` (Wave 3 step D-2b-ii-gamma-1).

Turns an aggregated recognition report into a target-neutral list of
:class:`KpiRow` values a downstream renderer (Grafana, Log Analytics,
App Insights, Prometheus) consumes. Keeps the shape flat and hashable
so a shipping runner CAN pipe the same rows into more than one
destination without re-serialising.

Wave 3 step D-2b-ii-gamma-2 will add the CLI runner that connects
:func:`emit_kpi_rows` to a real metric sink; this step ships the pure
row shape + emitter so tests and downstream consumers can already
assert against it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from fdai.core.measurement.prompt_probe_runner import RecognitionRunReport


class RowUnit(StrEnum):
    """Unit the numeric ``value`` on a :class:`KpiRow` carries.

    Kept small and typed so a downstream renderer can dispatch on
    the enum instead of grepping free-form strings. ``ratio`` values
    are in ``[0.0, 1.0]``, ``count`` values are non-negative integers.
    """

    RATIO = "ratio"
    COUNT = "count"


@dataclass(frozen=True, slots=True)
class KpiRow:
    """One metric row ready to publish.

    ``metric`` is a dot-separated stable identifier the dashboard
    panels reference. ``dimensions`` is a small mapping of label
    values (capability, layer id, violation code, ...) that carve up
    a metric into per-slice series - kept as a frozen mapping so a
    row can be cached / deduplicated by a downstream aggregator.
    """

    metric: str
    value: float
    unit: RowUnit
    dimensions: Mapping[str, str] = field(default_factory=dict)


# Metric name constants. Public so tests and dashboard panels can
# reference the same strings without duplicating string literals.
METRIC_SAMPLE_COUNT: Final[str] = "prompt.recognition.sample_count"
METRIC_ADHERENCE_PASS_RATE: Final[str] = "prompt.recognition.adherence.pass_rate"  # noqa: S105 - metric name, not a credential
METRIC_ADHERENCE_VIOLATION_COUNT: Final[str] = "prompt.recognition.adherence.violation_count"
METRIC_CANARY_ECHO_RATE: Final[str] = "prompt.recognition.canary_echo_rate"
METRIC_CITATION_F1_MEAN: Final[str] = "prompt.recognition.citation_f1.mean"


def emit_kpi_rows(
    report: RecognitionRunReport,
    *,
    dimensions: Mapping[str, str] | None = None,
) -> tuple[KpiRow, ...]:
    """Convert a :class:`RecognitionRunReport` into KPI rows.

    ``dimensions`` is the base label set applied to every emitted row
    (typical use: ``{"capability": "t2.reasoner.primary"}``).
    Metric-specific labels (violation code, layer id) are merged on
    top so a row's ``dimensions`` mapping is always the full label
    set the renderer needs.

    Emission rules baked in and tested:

    - **Empty batch** returns only :data:`METRIC_SAMPLE_COUNT` with
      value ``0`` so a dashboard series that always publishes at
      least the sample count does not silently disappear.
    - **Adherence pass rate** is emitted only when ``sample_count > 0``
      because dividing zero by zero would be misleading.
    - **Per-violation-code counts** are one row each, dimensioned by
      the structured violation code.
    - **Per-layer echo rates** are one row each, dimensioned by the
      layer id. A layer never measured never appears (mirrors the
      ``summarize_recognition`` semantic).
    - **Citation F1** is emitted only when the aggregate actually
      scored citations (``mean_citation_f1 is not None``) - a
      dashboard row that reports ``0.0`` on a batch that opted out
      of citation scoring would trigger false alerts.
    """

    base_dims = dict(dimensions or {})
    summary = report.summary
    rows: list[KpiRow] = [
        KpiRow(
            metric=METRIC_SAMPLE_COUNT,
            value=float(summary.sample_count),
            unit=RowUnit.COUNT,
            dimensions=dict(base_dims),
        )
    ]

    if summary.sample_count > 0:
        rows.append(
            KpiRow(
                metric=METRIC_ADHERENCE_PASS_RATE,
                value=summary.adherence_pass_rate,
                unit=RowUnit.RATIO,
                dimensions=dict(base_dims),
            )
        )

    for code, count in sorted(summary.adherence_violation_counts.items()):
        rows.append(
            KpiRow(
                metric=METRIC_ADHERENCE_VIOLATION_COUNT,
                value=float(count),
                unit=RowUnit.COUNT,
                dimensions={**base_dims, "code": code},
            )
        )

    for layer_id, rate in sorted(summary.per_layer_canary_echo_rate.items()):
        rows.append(
            KpiRow(
                metric=METRIC_CANARY_ECHO_RATE,
                value=rate,
                unit=RowUnit.RATIO,
                dimensions={**base_dims, "layer_id": layer_id},
            )
        )

    if summary.mean_citation_f1 is not None:
        rows.append(
            KpiRow(
                metric=METRIC_CITATION_F1_MEAN,
                value=summary.mean_citation_f1,
                unit=RowUnit.RATIO,
                dimensions=dict(base_dims),
            )
        )

    return tuple(rows)


__all__ = [
    "KpiRow",
    "METRIC_ADHERENCE_PASS_RATE",
    "METRIC_ADHERENCE_VIOLATION_COUNT",
    "METRIC_CANARY_ECHO_RATE",
    "METRIC_CITATION_F1_MEAN",
    "METRIC_SAMPLE_COUNT",
    "RowUnit",
    "emit_kpi_rows",
]
