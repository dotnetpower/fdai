# Live Blast Probes

Live-blast probes let the RiskGate consult a real-time signal (traffic,
access-log volume, backend health) before deciding autonomy for an action,
so a static blast radius can be narrowed when the target resource is
actually quiet. See
[docs/roadmap/execution-model.md § 4](../../docs/roadmap/execution-model.md#4-live-blast-probe)
and
[docs/roadmap/action-ontology.md § 6](../../docs/roadmap/action-ontology.md#6-live-blast-probe-6-of-execution-modelmd-month-1).

## Status: placeholder (Day 1)

This directory intentionally ships **only this README** on Day 1. No shipped
ActionType sets `live_probe_ref` yet, so there is nothing to load. The
loader cross-check that "`live_probe_ref` must resolve to a probe under
`rule-catalog/probes/`" is therefore a no-op until Month 1 binds the first
probe (`AzureMonitorBlastProbe`). Keeping the empty directory under version
control documents the contract and prevents a "missing directory" load
error on forks that add probes early.

## Contract (Month 1)

Each probe is one YAML file `<probe_id>.yaml` with:

- `id`, `description`, `adapter_ref` (DI seam id).
- an adapter-specific query payload (kept **out** of the core schema so the
  probe stays CSP-neutral - an Azure Monitor probe wraps its KQL under the
  adapter payload, a future non-Azure probe wraps its own query language).
- `interpretation` mapping the raw result to `quiet | active | overloaded`.
- `timeout_seconds`, `cache_ttl_seconds`.

Probe failure fails toward safety: a single failure yields `active` (forces
HIL), repeated failure yields `shadow_only` (defer). Replay reads the
recorded probe result, never a fresh query.
