# `policies/`

OPA / Rego policy-as-code.

Consumed by T0 (`src/fdai/core/tiers/t0_deterministic/`) and by the T2 verifier
(`src/fdai/core/quality_gate/`). Policies are data, not code paths - adding a
policy MUST NOT require an engine change.

## Layout

One folder per CSP-neutral `resource_type` family. Each `.rego` file implements a
single deterministic `check_logic.reference` cited from a rule under
[`rule-catalog/catalog/`](../rule-catalog/catalog/); the rule loader
([`src/fdai/rule_catalog/schema/rule.py`](../src/fdai/rule_catalog/schema/rule.py))
cross-checks that every `check_logic.reference` under `policies/` actually exists on
disk at load time.

```text
policies/
├── object_storage/
│   ├── public_access.rego         # object-storage.public-access.deny
│   └── owner_tag_required.rego    # object-storage.owner-tag.required
├── compute/
│   └── vmss_over_provisioned.rego # compute.vm-scale-set.over-provisioned
├── secret_store/
│   └── rotation_overdue.rego      # secret-store.rotation-overdue
└── sql_database/
    └── tde_required.rego          # sql-database.tde-required
```

## Authoring rules

- **Package** name mirrors the file path: `fdai.<folder>.<file>`.
- Every module exports a `default deny := false` and a `deny if { ... }` rule so
  the T0 evaluator can query a single deterministic entrypoint.
- `input.resource.type` MUST equal the CSP-neutral `resource_type` the rule targets
  (defense-in-depth against a runtime dispatch mistake).
- `input.parameters` carries per-assignment overrides
  ([rule-governance.md](../docs/roadmap/rules-and-detection/rule-governance.md)); use the
  `x := input.parameters.foo else := <default>` idiom so a missing parameter
  falls back to the rule's authored default.
- Emit a `deny_reason` string on every deny so the audit-log entry carries a
  human-readable citation without extra plumbing.
- **No I/O, no `http.send`, no `time.now_ns`** - a rule MUST be a pure function of
  its input; time / http-dependent checks belong in an authored evaluator, not in
  Rego.

## Runner

The OPA/Rego runner
[`OpaRegoEvaluator`](../src/fdai/core/tiers/t0_deterministic/opa_evaluator.py)
shells out to `opa eval --stdin-input --format json` under a bounded subprocess
timeout (default 5 s). It is bound at the composition root through the existing
`PolicyEvaluator` DI seam - the T0 engine itself never imports it.

- **Fail-fast at construction**: `MissingOpaBinaryError` is raised when `opa`
  is not on `PATH`. A composition root running in a degraded environment
  (local dev without OPA installed) MUST catch that and bind
  [`AbstainEvaluator`](../src/fdai/core/tiers/t0_deterministic/engine.py)
  explicitly - auditable degradation, no silent no-op.
- **Fail-close per rule**: subprocess timeout, non-zero exit, non-JSON stdout,
  or a missing / traversal-shaped policy reference raises `OpaEvaluatorError`.
  The T0 engine converts that into an hold for review **for that rule only**, so a
  single broken policy cannot silence the rest of the catalog.
- **Package query**: given `rule.check_logic.reference == "policies/foo/bar.rego"`,
  the evaluator queries `data.fdai.foo.bar` and inspects `deny` /
  `deny_reason`. An undefined query result is an hold for review.
- **CI installs OPA** ([.github/workflows/ci.yml](../.github/workflows/ci.yml))
  pinned to a checksummed version so the merge gate exercises the real
  subprocess path; local dev tests skip gracefully when `opa` is absent.
