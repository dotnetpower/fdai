# `rule-catalog/chaos-scenarios/`

Catalog-as-code for FDAI fault-injection scenarios.

Data-only YAML tree. Loader + validator live in
[`src/fdai/core/chaos/scenario_catalog.py`](../../src/fdai/core/chaos/scenario_catalog.py).
Design memo:
[`docs/internals/sre-scenario-library-scaling.md`](../../docs/internals/sre-scenario-library-scaling.md).

## Layout

```
rule-catalog/
├── chaos-scenarios/
│   ├── schema/                       # JSON Schema for one scenario YAML
│   │   └── chaos-scenario.schema.json
│   ├── collected/                    # inbound; NOT loaded by default
│   │   ├── azure-chaos-studio/
│   │   ├── aws-fis/
│   │   ├── chaos-mesh/
│   │   ├── kubernetes-docs/
│   │   ├── litmus/
│   │   ├── postmortems/
│   │   ├── synthesized/              # deterministic combinator output
│   │   └── gpu/                      # GPU-domain scenarios (usually shadow-only)
│   ├── evidence/                     # sanitized tracked summary, never raw live data
│   └── promoted/                     # gate passed; loaded at startup
├── chaos-scenarios-custom/           # fork-only additions
└── chaos-scenarios-overrides/        # fork-only parameter overrides
```

## Scenario shape

Every YAML file MUST validate against
[`schema/chaos-scenario.schema.json`](schema/chaos-scenario.schema.json).

Minimum example:

```yaml
id: chaos.aks.pod-kill-mild
version: 1
provenance:
  source: chaos-mesh
  synthesis_method: collected
category: compute
target_type: pod
fault_family: stop
intensity: mild
duration_seconds: 360
expected_signal: pod_restart      # must be in core/detection/signals.py
injector: chaos-mesh:PodChaos
blast_radius_cap: 1
rollback_note: "ReplicaSet reschedules the killed pod."
gates:
  shadow_status: pending
  enforce_status: null
requires_hardware: false
```

## Rules

- **Signals**: `expected_signal` MUST match a registered `SIGNAL_*` in
  [`src/fdai/core/detection/signals.py`](../../src/fdai/core/detection/signals.py).
  The loader rejects unknown signals.
- **Injectors**: `injector: needs-injector` is allowed only in `collected/`;
  scenarios with that value cannot land in `promoted/`.
- **Runtime gate**: a scenario under `promoted/` or the fork-owned
  `chaos-scenarios-custom/` MUST use an executable injector and carry
  `gates.shadow_status: passed`; the loader rejects pending or failed entries.
- **Promotion evidence**: enforce eligibility is projected from append-only
  `ScenarioPromotionEvidence` records bound to scenario ID, scenario version,
  runner version, and the complete catalog fingerprint. Saga records validated
  shadow evidence, Mimir requests approval and changes promotion state, and a
  Var approval reference is required before `enforce_eligible`.
- **Detection-only scenarios**: `probe-only:*` entries read an injected provider
  seam without perturbing or holding a target. They still require promotion
  evidence before an enforce-mode validation and never imply a substrate change.
- **Hardware gate**: `requires_hardware: true` scenarios MAY sit indefinitely
  with `enforce_status: pending`; they are still loadable and shadow-testable.
- **Fork boundary**: upstream ships `collected/` + `promoted/` only. Forks
  add or override in `chaos-scenarios-custom/` and `chaos-scenarios-overrides/`
  (fork-only paths). Upstream MUST NOT touch either.
- **Override validation**: the loader revalidates the complete merged scenario
  after applying an override. An override cannot introduce an unknown signal,
  invalid schema value, non-executable marker, or unpassed runtime shadow gate.
- **No customer values**: scenarios stay CSP-neutral and customer-agnostic.
  `target_selector` is an opaque `<type>:<name>` handle, never a real
  resource name.

## Compiled artifact

[`scripts/build-symptom-index.py`](../../scripts/build-symptom-index.py) builds
the committed `chaos-scenarios.index.json` snapshot from `load_all()` by
default. Pass `--promoted-only` for a runtime-only snapshot. Runtime callers
can also rebuild the index in memory from `load_promoted()` or load a snapshot.
The catalog CI gate rejects a stale committed snapshot.

## Validation evidence

The retention model uses both a tracked summary and an external full bundle.
`evidence/catalog-validation-summary.json` contains only scenario IDs, versions,
bounded outcomes, safe measurements, and the catalog fingerprint. Full live-run
bundles belong in CI or release artifacts with a 90-day retention period; the
tracked summary records their SHA-256 digest when one exists. The catalog gate
rejects a summary after any scenario body or version changes.

Generate the current dispatchability summary without a substrate:

```bash
python scripts/run-catalog-scenario.py --dry-run \
  --evidence-summary rule-catalog/chaos-scenarios/evidence/catalog-validation-summary.json
```
