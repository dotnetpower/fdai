# `src/fdai/delivery/azure`

Azure-specific delivery adapters. Modules here MAY import `azure-*` SDKs;
`core/` never does. Every adapter registered here MUST implement one of the
CSP-neutral Protocols in
[`shared/providers/`](../../shared/providers/) so that a fork can swap it
out at the composition root without editing core.

Current adapters
----------------

- [`inventory.py`](inventory.py) - Azure Resource Graph (ARG) implementation
  of the `Inventory` Protocol
  ([contract](../../shared/providers/inventory.py),
  [design](../../../../docs/roadmap/architecture/csp-neutrality.md#5-inventory-contract--resource-graph)).
  Provides bounded-concurrency parallel-shard fan-out, the `final=True`
  atomic-promote fence, and the idempotent-upsert dedup precondition; the
  per-shard fetch behind it is a `ResourceQueryFn` bound at the composition
  root.
- [`arg_query.py`](arg_query.py) - `AzureArgQueryFactory`, the real
  Kusto-over-ARG REST implementation of `ResourceQueryFn`. Takes a
  `WorkloadIdentity` (OIDC token issuer) + a shared `httpx.AsyncClient` +
  the CSP-neutral resource-type vocabulary and returns an async callable
  the `Inventory` adapter fans out over. Handles `$skipToken` pagination
  under a bounded page cap, truncates untrusted vendor properties, and
  fail-closes on any HTTP / JSON / body-shape error via `ArgQueryError`.
  Extracts bounded `contains`, `attached_to`, and `depends_on` links from
  trusted ARM-id and property paths.
- [`resource_change.py`](resource_change.py) - strict Event Grid
  write/delete normalizer for Huginn's real-time resource discovery ingress.
  It reuses the ARG neutral-id and relationship projection rules, emits
  bounded `inventory_change` Events, and rejects malformed or unknown resource
  types so the raw consumer can dead-letter them.
- [`activity_log.py`](activity_log.py) - bounded direct Activity Log recovery
  reader. It is opt-in through `FDAI_INVENTORY_RECOVERY_DELTA`; production uses
  the managed-identity push path by default. Pagination cursors must remain on
  the configured HTTPS management host before a bearer token is attached.
- [`metric_logs.py`](metric_logs.py) - `AzureMonitorLogsMetricProvider`,
  the Azure Monitor Logs (Log Analytics KQL) implementation of the
  `MetricProvider` seam ([contract](../../shared/providers/metric.py)).
  A CSP-neutral `metric_name` maps to a trusted config-supplied KQL
  template; untrusted labels are filtered in memory (no KQL injection),
  the query is bounded server-side by `timespan` + `max_rows`, and any
  partial / malformed result fail-closes via `MetricProviderError`.
- [`deployment_history.py`](deployment_history.py) -
  `AzureResourceGraphDeploymentHistory`, the Azure Resource Graph
  (`resourcechanges`-shaped) implementation of the
  `DeploymentHistoryProvider` seam
  ([contract](../../shared/providers/observation.py)). Answers "what
  changed in the estate over the window" - the change/deployment signal
  T1 causal-chain RCA reasons over and the console `query_deployments`
  tool surfaces. A trusted config-supplied Kusto template carries a
  `{window_seconds}` token (the untrusted `window` is validated to a
  positive integer second-count from an ISO-8601 duration; the untrusted
  `resource_ref` is filtered in memory - no Kusto injection). Bounded by
  `$skipToken` page cap + `max_records`; any HTTP / JSON / shape error or
  missing column fail-closes via `DeploymentHistoryError`.
- [`log_query.py`](log_query.py) - `AzureLogAnalyticsQueryProvider`, the
  Azure Monitor Logs (Log Analytics KQL) implementation of the
  `LogQueryProvider` seam
  ([contract](../../shared/providers/observation.py)) behind the console
  `query_log` tool. Runs an opaque, caller-supplied KQL query against a
  single workspace. The adapter validates one tabular expression, blocks
  cross-workspace functions, limits the ISO 8601 `window` to 31 days,
  sends it as the server-side `timespan`, and appends `take max_rows + 1`.
  The result is clipped to `max_rows` (`truncated=True` when exceeded)
  under hard row, query-character, response-byte, and request-timeout caps.
  Identity, HTTP, partial-response, JSON, and table-shape errors fail closed
  through `LogQueryError`.
