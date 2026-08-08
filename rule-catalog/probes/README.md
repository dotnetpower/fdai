# Live Blast Probes

Live-blast probes let the RiskGate consult a real-time signal (traffic,
access-log volume, backend health) before deciding autonomy for an action,
so a static blast radius can be narrowed when the target resource is
actually quiet. See
[docs/roadmap/decisioning/execution-model.md § 4](../../docs/roadmap/decisioning/execution-model.md#4-live-blast-probe)
and
[docs/roadmap/decisioning/action-ontology.md § 6](../../docs/roadmap/decisioning/action-ontology.md#6-live-blast-probe-6-of-execution-modelmd-month-1).

## Shipped Probes

| Probe id | Signal | Current catalog use |
|----------|--------|---------------------|
| `vm_traffic_last_5m` | VM network throughput over five minutes | Referenced by `ops.restart-service` and `ops.scale-in`. |
| `lb_backend_health` | Load-balancer backend health ratio | Available to ActionTypes that explicitly reference it. |
| `storage_access_log` | Storage transaction volume | Available to stateful storage actions that explicitly reference it. |
| `blast_radius_classifier` | External-path versus internal-path health | Requires a fork-supplied `probe-adapters/blast-radius-http` binding. |

[`probe.schema.json`](probe.schema.json) defines the authored shape. The loader in
[`probe.py`](../../services/core-control-plane/src/fdai/rule_catalog/schema/probe.py) validates
every manifest and the ActionType loader rejects an unresolved `live_probe_ref`.

## Contract

Each probe is one YAML file `<probe_id>.yaml` with:

- `id`, `description`, `adapter_ref` (DI seam id).
- an adapter-specific query payload (kept **out** of the core schema so the
  probe stays CSP-neutral - an Azure Monitor probe wraps its KQL under the
  adapter payload, a future non-Azure probe wraps its own query language).
- `interpretation` mapping the raw result to `quiet | active | overloaded`.
- `timeout_seconds`, `cache_ttl_seconds`.

Probe failure fails toward safety: a single failure yields `active` and forces human approval;
repeated failure yields `shadow_only` and defers execution. Replay reads the recorded probe result,
never a fresh query. A manifest declares an adapter reference but does not create the adapter or
grant provider credentials; composition owns that binding.
