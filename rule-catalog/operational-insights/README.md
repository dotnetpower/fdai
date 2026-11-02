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

The catalog contains 150 independently executable recipes.

| Domain | Count | Recipe IDs |
|--------|------:|------------|
| Infrastructure, Kubernetes, and telemetry | 41 | `infrastructure.cpu-saturation`, `infrastructure.memory-pressure`, `infrastructure.disk-pressure`, `infrastructure.container-restart-surge`, `infrastructure.process-disappearance`, `infrastructure.peer-hotspot`, `infrastructure.scaling-oscillation`, `infrastructure.inode-pressure`, `infrastructure.oom-kill-surge`, `infrastructure.zombie-process-surge`, `infrastructure.load-average-saturation`, `infrastructure.cross-zone-load-imbalance`, `infrastructure.ephemeral-storage-pressure`, `infrastructure.file-descriptor-saturation`, `infrastructure.clock-skew-drift`, `infrastructure.cpu-cfs-throttling`, `infrastructure.swap-thrashing`, `infrastructure.disk-io-await-spike`, `infrastructure.kubelet-pleg-latency`, `infrastructure.conntrack-table-saturation`, `infrastructure.kernel-io-error-surge`, `infrastructure.systemd-failed-units`, `infrastructure.container-startup-duration`, `infrastructure.disk-burst-credit-low`, `infrastructure.context-switch-surge`, `infrastructure.regional-vcpu-quota-saturation`, `kubernetes.apiserver-request-latency-p99`, `kubernetes.etcd-wal-fsync-latency-p99`, `kubernetes.scheduler-pending-pods`, `kubernetes.node-not-ready-ratio`, `kubernetes.kube-proxy-sync-latency`, `kubernetes.hpa-maxed-out-replicas`, `kubernetes.daemonset-unavailable-pods`, `kubernetes.cronjob-missed-runs`, `kubernetes.pvc-volume-usage-ratio`, `kubernetes.init-container-restart-surge`, `telemetry.freshness-gap`, `telemetry.ingestion-drop`, `telemetry.cardinality-surge`, `telemetry.log-agent-drop-rate`, `telemetry.trace-sampling-drop-surge` |
| Change and application performance | 23 | `change.latency-regression`, `change.error-regression`, `change.throughput-regression`, `change.canary-analysis-failure-rate`, `change.gitops-out-of-sync-duration`, `change.state-lock-wait-duration`, `change.helm-pending-release-stale`, `change.image-pull-failure-surge`, `change.pdb-blocked-evictions`, `change.admission-webhook-rejection-surge`, `change.rollback-frequency-surge`, `change.blue-green-preview-error-rate`, `change.terraform-drift-resource-count`, `change.deployment-duration-regression`, `change.post-deploy-smoke-test-failures`, `apm.request-error-rate`, `apm.request-latency-p99`, `apm.apdex-drop`, `apm.dependency-error-amplification`, `apm.critical-path-dominance`, `apm.span-error-rate`, `apm.upstream-timeout-cascading-rate`, `apm.circuit-breaker-open-transitions` |
| Data, streams, synthetic checks, and logs | 24 | `database.slow-query-rate`, `database.lock-wait-ratio`, `database.replication-lag`, `database.connection-pool-saturation`, `database.deadlock-surge`, `database.autovacuum-dead-tuple-ratio`, `database.temp-files-spill-surge`, `database.cache-hit-ratio-drop`, `database.xid-wraparound-age-ratio`, `database.redis-eviction-surge`, `database.redis-memory-fragmentation`, `database.wal-archiver-failure-surge`, `database.pgbouncer-client-wait-time`, `database.long-running-transaction-age`, `stream.consumer-lag`, `stream.dead-letter-growth`, `stream.partition-skew-ratio`, `stream.poison-message-retry-surge`, `synthetic.availability-drop`, `synthetic.latency-regression`, `synthetic.dns-resolution-latency`, `log.volume-regression`, `log.new-pattern-surge`, `log.rare-error-growth` |
| SLO, alert quality, and ownership | 10 | `slo.fast-burn`, `slo.slow-burn`, `slo.error-budget-low`, `slo.availability-target-breach`, `slo.latency-objective-burn-rate`, `alert.storm`, `alert.flapping`, `alert.evaluation-stale`, `alert.no-data`, `ownership.missing` |
| Cost governance | 17 | `cost.daily-spend-change`, `cost.budget-overrun`, `cost.unallocated-spend`, `cost.idle-resource-share`, `cost.unit-cost-regression`, `cost.container-request-waste`, `cost.spot-eviction-surge`, `cost.unattached-storage-spend-share`, `cost.reservation-utilization-drop`, `cost.nonprod-offhours-active-ratio`, `cost.egress-transfer-spend-surge`, `cost.log-ingestion-cost-surge`, `cost.orphan-public-ip-count`, `cost.stale-snapshot-spend-share`, `cost.nat-gateway-data-processing-surge`, `cost.cold-blob-hot-tier-ratio`, `cost.acr-untagged-manifest-ratio` |
| Security, network, user impact, and recovery hygiene | 35 | `security.misconfiguration`, `security.excess-privilege`, `security.sensitive-data-growth`, `security.runtime-threat-growth`, `security.vulnerability-exposure`, `security.kube-apiserver-anonymous-or-forbidden-surge`, `security.secret-rotation-overdue`, `security.public-storage-blob-exposure`, `security.nsg-open-management-ports`, `security.workload-identity-token-failures`, `security.container-privileged-pod-count`, `security.keyvault-access-denied-surge`, `impact.user-session-error-share`, `certificate.expiry-window`, `backup.freshness-gap`, `backup.restore-drill-stale`, `backup.geo-replication-lag-seconds`, `network.retransmit-rate`, `network.connection-timeout-surge`, `network.connection-refused-surge`, `network.dns-lookup-failure-rate`, `network.lb-unhealthy-host-ratio`, `network.sticky-session-imbalance`, `network.connection-draining-timeout-surge`, `network.snat-port-exhaustion`, `network.subnet-ip-exhaustion`, `network.tls-handshake-failure-rate`, `network.bgp-route-flap-surge`, `network.ephemeral-port-exhaustion`, `network.waf-blocked-request-surge`, `network.tcp-syn-drop-surge`, `network.coredns-servfail-rate`, `network.gateway-5xx-error-ratio`, `network.gateway-backend-connect-latency`, `network.service-mesh-mtls-failure-surge` |

## Testing

Run the focused catalog and engine checks:

```bash
uv run pytest -q services/core-control-plane/tests/core/detection/test_insights.py \
  services/core-control-plane/tests/core/detection/test_insight_source.py \
  services/core-control-plane/tests/core/detection/test_insight_catalog.py
```
