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
| Metric Alert webhook path | implemented | `fdai_service_contracts/azure_monitor.py`; Operator operations route, durable webhook outbox bridge, semantic Kafka event route; focused contract, route, bridge, and Kafka tests | Verified Common Alert payloads become sanitized shadow Events and publish from a lease-fenced durable proposal. Governed live Action Group delivery and latency evidence remain open. |
| Diagnostic Event Hub path | implemented | `delivery/azure/monitor_events.py`; `diagnostic_event_ingest.py`; runtime bootstrap and Core service Terraform binding; focused normalizer, bridge, bootstrap, shutdown, and infrastructure tests | A dedicated Kafka consumer normalizes only configured metrics, dead-letters malformed matching records, and feeds the ordinary ingest topic. Governed live delivery and latency evidence remain open. |
| Managed alert-rule authoring | not-started | [What is NOT yet shipped](../../roadmap/rules-and-detection/near-real-time-detection-paths.md#what-is-not-yet-shipped) | No catalog-driven generator materializes alert rules from governed Rule entries. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-29 | implemented | Hardening round 4 reviewed 26 diagnostic-ingest lenses and normalized diagnostic record time to UTC before Event identity derivation. Offset-only replays now retain one idempotency key. | `current change`; focused Azure diagnostic normalizer tests. | Retain governed live delivery and latency evidence. |
| 2026-08-29 | implemented | Hardening round 2 reviewed 25 alert-contract lenses and normalized provider timestamps to UTC before deriving Event and idempotency identity. Equivalent offset representations of one alert can no longer create duplicate incident signals. | `current change`; focused Azure Monitor contract tests. | Retain governed live delivery and latency evidence. |
| 2026-08-28 | implemented | Completed both push-path implementations. The HMAC-verified Operator webhook now converts Common Alert Schema bodies into shared sanitized Events before durable acceptance, and a lease-fenced outbox publishes them directly to the Core event topic. Core now owns a separately configured diagnostic Kafka transport, normalizes bounded whitelisted `AllMetrics` records, dead-letters malformed matching input, and supervises the bridge with startup readiness and ordered shutdown. Both capabilities remain shadow and grant no action authority. | `current change`; shared alert contract; Operator route, outbox, Kafka, composition, and focused tests; Core normalizer, bridge, bootstrap, shutdown, Terraform contract, and focused tests. | Retain governed live Action Group and diagnostic Event Hub delivery and latency evidence. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and corrected end-to-end delivery claims to match the current source tree. | `current change`; paths and focused checks listed in the scope table. | Restore a runnable pull entry point and complete both authenticated push paths. |
| 2026-08-16 | implemented | Corrected the stale claim that `fdai.delivery.analyzer_tick_cli` is absent; the module ships. Added a focused integration test that drives one tick through a `RoutedMetricProvider`, proving each metric reaches the backend its routing table selects, that a breach publishes one shadow-mode Event, that a healthy pass publishes nothing, and that an unrouted metric marks the pass partial instead of healthy. | `current change`; `services/core-control-plane/tests/delivery/test_analyzer_tick_routed.py`; `pytest services/core-control-plane/tests/delivery/test_analyzer_tick_routed.py` (4 passed). | Complete both authenticated push paths and record governed live latency evidence per path. |

### Remaining work

- [x] `fdai.delivery.analyzer_tick_cli` ships as the entry point the scheduled job invokes, and one focused integration test drives a tick through the `RoutedMetricProvider` to a published shadow-mode Event, proven by `services/core-control-plane/tests/delivery/test_analyzer_tick_routed.py`.
- [x] Add a tested Azure Monitor request handler, shared payload normalizer, HMAC verifier, durable
  outbox, and event-topic publisher for path #1.
- [x] Add a tested diagnostic-record normalizer and runtime binding that feeds path #2 records into
  the ingest topic and dead-letters malformed matching records.
- [ ] Record governed latency evidence for each path before changing any path from `implemented` to `validated`.
