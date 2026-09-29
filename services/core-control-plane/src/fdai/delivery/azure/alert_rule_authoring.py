"""Materialize reviewed metric alert entries as Azure Monitor metric alert inputs.

The output feeds ``infra/modules/observability/metric-alert-rules`` one instance per alert.
Only a CSP-neutral metric that maps directly onto one reviewed Azure platform metric in
``azure_metrics_api_queries`` is materialized; dimension-filtered or deployment-scoped
templates, unknown metrics, and namespace conflicts are refused with a stable reason, never
approximated. The document digest covers every alert and refusal, so the same catalog always
yields byte-identical output. Materialized alerts only feed the shadow-mode push path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from fdai.delivery.azure.metrics_api import MetricsApiTemplate
from fdai.delivery.azure.metrics_api_queries import azure_metrics_api_queries
from fdai.rule_catalog.metric_alerts import MetricAlertComparison, MetricAlertEntry

METRIC_ALERT_DOCUMENT_SCHEMA = "1.0.0"
_MODULE_AGGREGATIONS = frozenset({"Average", "Maximum", "Minimum", "Total", "Count"})
_OPERATORS = {
    MetricAlertComparison.ABOVE: "GreaterThan",
    MetricAlertComparison.AT_OR_ABOVE: "GreaterThanOrEqual",
    MetricAlertComparison.BELOW: "LessThan",
    MetricAlertComparison.AT_OR_BELOW: "LessThanOrEqual",
}


@dataclass(frozen=True, slots=True)
class MaterializedMetricAlert:
    """Inputs for one ``metric-alert-rules`` module instance."""

    alert_id: str
    name: str
    description: str
    severity: int
    metric_namespace: str
    metric_name: str
    aggregation: str
    operator: str
    threshold: float
    window_size: str
    evaluation_frequency: str


@dataclass(frozen=True, slots=True)
class MetricAlertRefusal:
    """A catalog entry that cannot become a native static-threshold alert."""

    alert_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class MetricAlertMaterialization:
    alerts: tuple[MaterializedMetricAlert, ...]
    refusals: tuple[MetricAlertRefusal, ...]

    def document(self) -> dict[str, object]:
        """Return the canonical JSON document, including its content digest."""

        body: dict[str, object] = {
            "schema_version": METRIC_ALERT_DOCUMENT_SCHEMA,
            "mode": "shadow",
            "alerts": [asdict(alert) for alert in self.alerts],
            "refusals": [asdict(refusal) for refusal in self.refusals],
        }
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        return {**body, "digest": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()}


def materialize_metric_alerts(
    entries: Sequence[MetricAlertEntry],
    *,
    templates: Mapping[str, MetricsApiTemplate] | None = None,
) -> MetricAlertMaterialization:
    """Map each entry to exactly one alert or one refusal, in stable ``alert_id`` order."""

    reviewed = azure_metrics_api_queries() if templates is None else templates
    alerts: list[MaterializedMetricAlert] = []
    refusals: list[MetricAlertRefusal] = []
    for entry in sorted(entries, key=lambda item: item.alert_id):
        reason = _refusal(entry, reviewed.get(entry.metric))
        if reason is not None:
            refusals.append(MetricAlertRefusal(entry.alert_id, reason))
            continue
        template = reviewed[entry.metric]
        alerts.append(
            MaterializedMetricAlert(
                alert_id=entry.alert_id,
                name="alert-fdai-" + entry.alert_id.replace(".", "-"),
                description=entry.description,
                severity=entry.severity,
                metric_namespace=template.resource_type or entry.resource_type or "",
                metric_name=template.azure_metric_name,
                aggregation=template.aggregation,
                operator=_OPERATORS[entry.comparison],
                threshold=entry.threshold,
                window_size=entry.window,
                evaluation_frequency=entry.frequency,
            )
        )
    return MetricAlertMaterialization(tuple(alerts), tuple(refusals))


def _refusal(entry: MetricAlertEntry, template: MetricsApiTemplate | None) -> str | None:
    if template is None:
        return "unknown_metric"
    if template.dimension_filters:
        return "dimension_filtered_metric"
    if template.deployment_scope:
        return "deployment_scoped_metric"
    if template.aggregation not in _MODULE_AGGREGATIONS:
        return "unsupported_aggregation"
    if template.resource_type is None:
        return None if entry.resource_type is not None else "resource_type_missing"
    if entry.resource_type is not None and (
        entry.resource_type.casefold() != template.resource_type.casefold()
    ):
        return "resource_type_mismatch"
    return None


__all__ = [
    "METRIC_ALERT_DOCUMENT_SCHEMA",
    "MaterializedMetricAlert",
    "MetricAlertMaterialization",
    "MetricAlertRefusal",
    "materialize_metric_alerts",
]
