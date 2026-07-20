---
title: Preflight Active Plan Reassembly (policy blocker to re-rendered terraform)
---
# Preflight Active Plan Reassembly (policy blocker to re-rendered terraform)

When [deployment-preflight](deployment-preflight.md) reports a `policy_guardrail`
or `supply_chain_egress` blocker that has a registered capability-mode toggle,
the shipped pure loop can calculate and re-verify overrides that **actively re-render the
terraform plan** into a supported alternate shape. That shape never emits the denied operation.
Delivery as a remediation PR through the existing
[executor](../architecture/project-structure.md) begins after live composition wiring lands.

This document is authoritative for **the active-reassembly loop, its
convergence and stop-conditions, the ActionType that carries it, and the honest
limits of what can be reassembled**. The blocker taxonomy, the toggle mapping
table, and the report shape stay in [deployment-preflight.md](deployment-preflight.md);
the toggle modules themselves live in
[infra/modules/preflight-toggles/](../../../infra/modules/preflight-toggles/README.md).

> Customer-agnostic: no denylist value, mirror endpoint, or toggle default is
> baked in upstream. The upstream ships the reassembly machinery and the generic
> toggle catalog; a fork supplies the specific guardrail values and consumer
> wiring ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
>
> **Implementation status.** The bounded convergence loop, toggle proposal builder, ActionType,
> data-only toggle modules, and reference consumer are shipped. The real policy-finding trigger,
> plan renderer, `ProposalSink` -> Huginn binding, PR publisher, and audit write are not wired yet.

## Why This Is Possible (and Not Magic)

The rails already exist; active reassembly connects them end to end:

1. **Detection** - a `FeasibilityProbe` emits a grounded `ProbeFinding`
   ([feasibility_probe.py](../../../src/fdai/shared/providers/feasibility_probe.py)).
2. **Mapping** - the finding carries a `ProbeResolution(kind=TERRAFORM_TOGGLE,
   autofix, module, set_vars)` naming the exact infra sub-module and the variable
   override that makes the deploy comply.
3. **Alternate rendering** - the
   [preflight-toggles](../../../infra/modules/preflight-toggles/README.md) modules
   encode the compliant shape (`disk_provisioning=attach_existing`,
   `registry_source=acr_mirror`, ...) as data-only Terraform.

The two pieces this design added now have these states:

- **Toggle proposal builder (shipped)**: renders every `autofix` toggle in a cleared outcome as
  one typed proposal. The live sink/publisher binding is still absent, so it does not open a PR
  ([check_publish.py](../../../src/fdai/core/deploy_preflight/check_publish.py)).
- **Convergence loop (shipped)**: uses caller-provided plan-render and reanalysis callbacks to
  ensure a fix for one blocker cannot silently introduce another.

## The Reassembly Loop

Reassembly is a bounded, deterministic loop, never a single shot - a re-rendered
plan must be re-checked because a toggle can move a blocker rather than remove
it.

```text
terraform plan (JSON)
  -> preflight.analyze
       -> CLEAR              -> deliver plan / merge
       -> BLOCKED + autofix toggle for every blocking finding
                            -> render tfvars override (reassemble)
                            -> re-plan -> back to preflight.analyze   (bounded)
       -> BLOCKED + a blocking finding has no autofix toggle
                            -> hil (partial autofix is never applied)
```

- **All-or-nothing per pass**: reassembly proceeds only when *every* blocking
  finding has an `autofix` toggle. A single manual-resolution blocker routes the
  whole pass to `hil` - the loop never applies a partial fix that would still
  fail apply.
- **Verifier is authority**: the reassembled plan is re-checked by the same
  deterministic preflight (OPA re-check + what-if), never trusted because a
  toggle was applied. This mirrors the
  [quality-gate rule](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2):
  execution eligibility is granted by verification, not by the fix generator.

### Convergence and Stop-Conditions

The loop MUST terminate. Its stop-conditions are safety invariants, not
optimizations:

| Stop-condition | Effect |
|----------------|--------|
| `max_reassembly_iterations` (default 3) exceeded | route to `hil`, attach the last report |
| same toggle proposed twice for the same finding id | non-convergence -> `hil` (prevents flip-flop / infinite loop) |
| a reassembly pass produces *more* blocking findings than the prior pass | regression -> `hil` |
| any probe raises | fail-closed -> `hil` (never reassemble on a partial pass) |

The iteration counter, the per-finding toggle history, and the caps are
configuration, not hardcoded literals, so a fork can tune them without editing
`core/`.

## ActionType: `remediate.apply-preflight-toggle`

Active reassembly is **not** a new privileged path. It reuses the existing
[executor](../../../src/fdai/core/executor/executor.py) by registering a first-class
ontology `ActionType`, so the four safety invariants, shadow-first gating, and
the append-only audit entry come for free (the same reason the console vocabulary
routes every action through the typed pipeline, see
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#action-ontology-and-console-vocabulary)).

The declaration (authored under `rule-catalog/action-types/`):

- `category: remediation`
- `trigger_kind: both` - the preflight loop initiates it automatically on a
  blocking finding, and an operator MAY request a specific toggle; it is
  parametric (`argument_schema`: `scope`, `finding_id`, `toggle_module`,
  `set_vars`, `reason`), so it is not a static resource-posture rule.
- `execution_path: pr_native` - the change is a tfvars-override PR against the
  infra repo, never a direct substrate mutation.
- `rollback_contract: pr_revert` - reverting the PR restores the prior tfvars;
  the reassembly is fully reversible, so `irreversible: false`.
- `default_mode: shadow` - the first ship judges and renders the PR as a draft
  with the `shadow` label; it never auto-merges.
- `promotion_gate` - measured on the frozen scenario set (false-positive rate of
  the toggle mapping) before any per-category promotion to enforce.
- `preconditions` - `graph_fresh_within_seconds` (the plan and the environment
  profile must be current) and `no_conflicting_open_action_on_resource`.
- `stop_conditions` - the convergence caps above, plus the standard
  `time_box_exceeded_seconds` and `provider_api_error_streak`.
- `blast_radius` - the set of infra variables the override touches; a reassembly
  that would flip more toggles than the cap abstains to `hil`.

### Autofix Eligibility Gate

An `autofix` PR is proposed automatically **only** when all of these hold;
otherwise the finding degrades to guidance + `hil`:

1. the resolution `kind` is `TERRAFORM_TOGGLE` with `autofix: true`;
2. the toggle is a **deterministic** data-only module (no LLM in the path);
3. the reassembled plan re-passes preflight (verifier re-check);
4. the override stays within the declared `blast_radius`.

`autofix: false` toggles submit no proposal or diff. They remain manual guidance in the report,
the whole pass escalates, and the operator reviews the variable change.

### Action Granularity: One Action per Toggle

A reassembly can apply several toggles (across findings and iterations). Each
applied toggle becomes **its own** `remediate.apply-preflight-toggle` Action -
not one bundled Action per pass. This keeps the ActionType's `argument_schema`
single-toggle (`finding_id` + `toggle_module` + `set_vars`), so audit, rollback
(`pr_revert`), and blast-radius stay at toggle granularity and map 1:1 to the
finding each toggle resolves. The loop retains the per-toggle provenance
(`AppliedToggle`: `finding_id`, `module`, `set_vars`, `scope`); the proposal
builder ([reassembly_proposals.py](../../../src/fdai/core/deploy_preflight/reassembly_proposals.py))
renders one proposal per toggle and submits each through the same typed pipeline
seam an operator command re-enters (`ProposalSink` -> Huginn -> Forseti -> Thor),
shadow-first. An escalated outcome yields no proposals - the caller routes it to
`hil`.

## What Can and Cannot Be Reassembled

Honesty about the boundary is a safety property, not a caveat:

- **Reassemblable** - blockers with a registered alternate rendering: inline disk
  deny -> `attach_existing`; blocked `docker.io` egress -> `acr_mirror`; NSG
  create deny -> `byo`; PyPI egress deny -> internal `python_index_url`;
  ordering violation -> `dependency_ordering=strict`.
- **Not reassemblable (routes to `hil`)** - policies with no supported
  alternate: a region banned outright, a mandatory-tag policy, a denied SKU with
  no substitute SKU, or any guardrail whose only resolution is a scoped
  exemption or a governance decision. These emit a `MANUAL` resolution and never
  auto-reassemble.

The discovery loop treats a recurring `MANUAL` blocker across environments as a
signal to propose a **new** toggle (a new default alternate rendering), which
then enters the catalog through the standard quality gate
([architecture.instructions.md § Rule Catalog](../../../.github/instructions/architecture.instructions.md#rule-catalog)).

## Safety Invariants

Every reassembly action satisfies all four invariants, enforced by the executor
it reuses:

- **Stop-condition** - the convergence caps above, declared on the ActionType.
- **Rollback path** - `pr_revert`; the override PR is a single-commit revert away
  from the prior plan, and the rollback reference is embedded in the PR body.
- **Blast-radius limit** - the reassembly touches only the declared infra
  variables; exceeding the cap abstains to `hil`.
- **Audit-log entry** - the pure loop returns an audit-grade terminal reason and toggle
  provenance. Live composition writes the hash-chained audit record when it submits the result;
  the currently unwired core primitive does not call the audit store.

Reassembly ships **shadow-first**: the PR is a draft, judged and rendered but not
merged, until the toggle mapping's false-positive rate is measured and the
category is explicitly promoted to enforce.

## Subsystem Layout

| Piece | Location | Status |
|-------|----------|--------|
| Toggle resolution on a finding | [feasibility_probe.py](../../../src/fdai/shared/providers/feasibility_probe.py) | shipped |
| Capability-mode toggle modules | [infra/modules/preflight-toggles/](../../../infra/modules/preflight-toggles/README.md) | shipped (data-only) |
| Readiness report + verdict | [core/deploy_preflight/report.py](../../../src/fdai/core/deploy_preflight/report.py) | shipped |
| Report -> PR check publish | [core/deploy_preflight/check_publish.py](../../../src/fdai/core/deploy_preflight/check_publish.py) | shipped (report only) |
| Convergence loop + stop-conditions | [core/deploy_preflight/reassemble.py](../../../src/fdai/core/deploy_preflight/reassemble.py) | shipped |
| `remediate.apply-preflight-toggle` ActionType | [rule-catalog/action-types/](../../../rule-catalog/action-types/remediate.apply-preflight-toggle.yaml) | shipped |
| Overrides -> Action proposals (one per toggle) | [core/deploy_preflight/reassembly_proposals.py](../../../src/fdai/core/deploy_preflight/reassembly_proposals.py) | shipped |
| Reference consumer wiring (one toggle) | [infra/modules/preflight-toggles/reference-disk-consumer/](../../../infra/modules/preflight-toggles/reference-disk-consumer/README.md) | shipped (fork copies it) |
| **Composition wiring: `ProposalSink` + live trigger** | composition root + `delivery/azure/preflight/` | **remaining** |

`core/` sees only the `FeasibilityProbe` Protocol and a caller-supplied `ProposalSink` callable;
the reassembly loop constructs no cloud SDK
and opens no PR itself - it decides the overrides and hands them to the executor
(via the ActionType), which owns the publish and the invariants.

## Delivery Increments

Each is separately reviewable:

1. **Docs-first** (this document) - the loop, ActionType, and limits. *(shipped)*
2. The `remediate.apply-preflight-toggle` ActionType YAML + schema validation. *(shipped)*
3. The bounded convergence loop, shadow-mode, with property tests: "same toggle
   never applied twice", "partial blocker -> hil", "reassembled plan is
   re-verified", "regression -> hil", "fail-closed on a raising reanalyze". *(shipped)*
4. One reference consumer wiring (the `disk_provisioning` toggle) under `infra/`
   so a fork has a copy-paste starting point. *(shipped)*
5. The overrides-to-executor step: render each applied toggle into a
   `remediate.apply-preflight-toggle` proposal (one Action per toggle,
   granularity A) and submit through the typed pipeline seam. *(shipped)*
6. Composition wiring (bind the `ProposalSink` to Huginn ingest) plus live
   Azure adapters that feed real policy findings into the loop and open the
   tfvars-override PR (after the preflight live adapters land, shadow-first).
   *(remaining)*

## References

- [deployment-preflight.md](deployment-preflight.md) - probe taxonomy, toggle mapping table, report shape
- [infra/modules/preflight-toggles/README.md](../../../infra/modules/preflight-toggles/README.md) - the capability-mode toggle modules
- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) - control loop, quality gate, safety invariants, action ontology
- [project-structure.md](../architecture/project-structure.md) - executor, module boundaries, infra sub-module pattern
- [risk-classification.md](../decisioning/risk-classification.md) - how a blocking finding routes to `hil`
- [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md) - the four safety invariants, shadow-first, ActionType contract
