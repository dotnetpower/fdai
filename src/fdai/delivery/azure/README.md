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
  [design](../../../../docs/roadmap/csp-neutrality.md#5-inventory-contract--resource-graph)).
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
  **Link extraction (`contains` / `attached_to` / `depends_on`) is
  reserved for P2** - this file returns `()` for links today.
