# Operational Insight Catalog

This catalog defines deterministic operational conditions that FDAI can
evaluate over normalized telemetry. The evaluator emits shadow-first findings
that re-enter `event-ingest`; recipes never execute actions directly.

## Contract

[`catalog.yaml`](catalog.yaml) is the versioned source of truth. Each recipe
declares an ID, category, severity, operator, input metric, threshold, minimum
sample count, and optional comparison metric. The strict loader lives in
`fdai.rule_catalog.schema.operational_insight`.

Supported operators cover direct bounds, change from the previous window,
percentage change from a baseline, ratios between two metrics, missing input,
and stale input. Invalid, non-finite, incomplete, or undersampled telemetry
holds without emitting a finding.

`OperationalInsightSource` bridges the catalog to the shared `MetricProvider`.
It queries each distinct metric once per resource and window, derives current,
previous, and historical baseline values, and passes one normalized observation
to the engine. A successful empty query can satisfy `absent`; a provider error
marks the metric unavailable and always holds. Stale recipes use a bounded
lookback of twice their threshold so an old last-seen sample remains observable
without scanning unbounded telemetry history.

## Capability Inventory

The initial catalog contains 50 independently executable recipes.

| Domain | Count | Recipe IDs |
|--------|------:|------------|
| Infrastructure and telemetry | 9 | `infrastructure.cpu-saturation`, `infrastructure.memory-pressure`, `infrastructure.disk-pressure`, `infrastructure.container-restart-surge`, `infrastructure.process-disappearance`, `infrastructure.peer-hotspot`, `telemetry.freshness-gap`, `telemetry.ingestion-drop`, `telemetry.cardinality-surge` |
| Change and application performance | 9 | `change.latency-regression`, `change.error-regression`, `change.throughput-regression`, `apm.request-error-rate`, `apm.request-latency-p99`, `apm.apdex-drop`, `apm.dependency-error-amplification`, `apm.critical-path-dominance`, `apm.span-error-rate` |
| Data, streams, synthetic checks, and logs | 9 | `database.slow-query-rate`, `database.lock-wait-ratio`, `stream.consumer-lag`, `stream.dead-letter-growth`, `synthetic.availability-drop`, `synthetic.latency-regression`, `log.volume-regression`, `log.new-pattern-surge`, `log.rare-error-growth` |
| SLO, alert quality, and ownership | 8 | `slo.fast-burn`, `slo.slow-burn`, `slo.error-budget-low`, `alert.storm`, `alert.flapping`, `alert.evaluation-stale`, `alert.no-data`, `ownership.missing` |
| Cost governance | 6 | `cost.daily-spend-change`, `cost.budget-overrun`, `cost.unallocated-spend`, `cost.idle-resource-share`, `cost.unit-cost-regression`, `cost.container-request-waste` |
| Security, user impact, and recovery hygiene | 9 | `security.misconfiguration`, `security.excess-privilege`, `security.sensitive-data-growth`, `security.runtime-threat-growth`, `security.vulnerability-exposure`, `impact.user-session-error-share`, `certificate.expiry-window`, `backup.freshness-gap`, `network.retransmit-rate` |

## Testing

Run the focused catalog and engine checks:

```bash
uv run pytest -q services/core-control-plane/tests/core/detection/test_insights.py \
  services/core-control-plane/tests/core/detection/test_insight_source.py \
  services/core-control-plane/tests/core/detection/test_insight_catalog.py
```
