# Near-real-time detection paths implementation ledger

This delivery ledger preserves reviewable implementation scope, append-only transitions,
and resumable work while the roadmap owner remains focused on normative design.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Routed pull providers | implemented | `services/core-control-plane/src/fdai/composition/wire_metric_provider.py`; `services/core-control-plane/tests/providers/test_routed_metric.py` | Prometheus, Metrics API, and Logs providers resolve through a deterministic route order. |
| Scheduled analyzer job | implemented | `infra/modules/compute/container-apps/analyzer_tick_job.tf`; `services/core-control-plane/src/fdai/delivery/analyzer_tick_cli.py`; `services/core-control-plane/tests/delivery/test_analyzer_tick_routed.py` | Terraform declares the one-minute job and its `fdai.delivery.analyzer_tick_cli` entry point ships. One focused tick reaches each routed backend and publishes its breach as a shadow-mode Event; governed live latency evidence remains open. |
| AKS detection-readiness reduction | implemented | `services/core-control-plane/tests/agents/test_huginn_detection_readiness.py`; `tests/integration/infra/test_detection_readiness.py` | Focused tests cover the agent-owned readiness observations and the infrastructure contract. This is implementation evidence, not live latency evidence. |
| Metric Alert webhook path | in-progress | `infra/modules/observability/metric-alert-rules/main.tf`; `services/operator-service/src/fdai_operator_service/families/operations/manifest.py`; `services/operator-service/tests/test_operator_operations_family.py` | The Terraform primitive and compatibility route declaration exist. A handler, normalizer, and authenticated Action Group bridge don't. |
| Diagnostic Event Hub path | in-progress | `infra/modules/observability/diagnostic-eventhub-route/main.tf`; `services/core-control-plane/src/fdai/delivery/azure/event_bus.py` | The routing module and Kafka adapter exist. Diagnostic-record normalization and composition wiring don't. |
| Managed alert-rule authoring | not-started | [What is NOT yet shipped](../../roadmap/rules-and-detection/near-real-time-detection-paths.md#what-is-not-yet-shipped) | No catalog-driven generator materializes alert rules from governed Rule entries. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected end-to-end delivery claims to match the current source tree. | `current change`; paths and focused checks listed in the scope table. | Restore a runnable pull entry point and complete both authenticated push paths. |
| 2026-08-16 | implemented | Corrected the stale claim that `fdai.delivery.analyzer_tick_cli` is absent; the module ships. Added a focused integration test that drives one tick through a `RoutedMetricProvider`, proving each metric reaches the backend its routing table selects, that a breach publishes one shadow-mode Event, that a healthy pass publishes nothing, and that an unrouted metric marks the pass partial instead of healthy. | `current change`; `services/core-control-plane/tests/delivery/test_analyzer_tick_routed.py`; `pytest services/core-control-plane/tests/delivery/test_analyzer_tick_routed.py` (4 passed). | Complete both authenticated push paths and record governed live latency evidence per path. |

### Remaining work

- [x] `fdai.delivery.analyzer_tick_cli` ships as the entry point the scheduled job invokes, and one focused integration test drives a tick through the `RoutedMetricProvider` to a published shadow-mode Event, proven by `services/core-control-plane/tests/delivery/test_analyzer_tick_routed.py`.
- [ ] Add a tested Azure Monitor request handler, payload normalizer, and authenticated Action Group bridge for path #1.
- [ ] Add a tested diagnostic-record normalizer and composition binding that feeds path #2 records into the ingest topic.
- [ ] Record governed latency evidence for each path before changing any path from `implemented` to `validated`.
