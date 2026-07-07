---
title: Risk Classification (auto vs HIL vs deny)
---
# Risk Classification (auto vs HIL vs deny)

The risk gate ([architecture.instructions.md § Control Loop](../../.github/instructions/architecture.instructions.md#control-loop))
routes every candidate action to one of `auto`, `hil`, or `deny`. This file is authoritative
for **the classification rules that produce that routing**: their shape, the initial rule
table, ownership, and update process. It resolves P0 Open Decision *"Risk-classification
policy (auto vs HIL) and initial policy approver"* from
[security-and-identity.md](security-and-identity.md#open-decisions).

> Customer-agnostic: every value below (cost threshold, tag key, resource-group name) is a
> **default** in the upstream; a fork tunes them via config
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## Where the Table Lives

- **Runtime path**: `rule-catalog/risk-classification.yaml` - catalog-as-code, reviewed via
  PR like rules/assignments/exemptions/overrides. `aw-approvers` reviewers with an
  **elevated quorum of 2** for any change ([user-rbac-and-identity.md § 5.1](user-rbac-and-identity.md#51-codeowners-single-approver-group-path-based-reviewer-count)).
- **Policy owner**: the `aw-owners` Entra security group. Ownership sits with Owner-tier
  because the table gates the entire autonomy surface.
- **Evaluation**: first-match wins. Rules are ordered from strictest (`deny`) to most
  permissive (`auto`); a case that matches no rule falls through to the **`default: hil`**
  fail-close entry.

## Relationship to the Execution-Model Six-Axis Ceiling

This table is the **authoritative baseline** decision. The unified RiskGate
([execution-model.md](execution-model.md)) evaluates this table as its
`risk_table` axis (Axis A) and then takes the `min()` of that result and
six ActionType-context ceiling axes (tier, ActionType ceiling, static
blast, live blast, role, env). The six-axis ceiling can only ever **lower**
autonomy further; it never overrides or raises a decision this table made.
Signals that need finding-level data - `cost_impact_monthly`,
`destructive`, `irreversible` (with its `quorum: 2`), `data_plane_touched`,
`verifier_confidence` - are evaluated **here and only here**; the ceiling
axes deliberately do not re-derive them. There are not two decision
engines: there is this table, plus a never-raising ceiling layered on top.

## Classification Dimensions

The risk gate composes a **feature vector** for every candidate action from the ontology
signals it already has ([llm-strategy.md § Rule-to-Decision Lookup Pipeline](llm-strategy.md#rule-to-decision-lookup-pipeline)).
No new data collection is introduced.

| Dimension | Type | Source |
|-----------|------|--------|
| `policy_violation` | bool | OPA/Rego verifier verdict |
| `destructive` | bool | ontology `ActionType.operation ∈ {delete, drop, purge, detach}` |
| `irreversible` | bool | ontology `ActionType.irreversible == true` (a rolled-back state cannot fully restore the pre-action state) |
| `blast_radius` | enum `resource` \| `resource_group` \| `subscription` | `applies_to` × scope of the affected resource(s); when `ActionType.blast_radius.computation == graph_derived`, the risk-gate walks Resource→Resource links (default `contains` + reverse `depends_on`, depth 2) and maps the affected-resource count to a bucket |
| `rollback_path` | enum `pr_revert` \| `scripted` \| `pitr` \| `snapshot_restore` \| `state_forward_only` | `remediates` action's rollback contract (no `none` value - every ActionType MUST declare an undo path) |
| `reversible` | bool | shortcut for `irreversible == false` |
| `environment` | enum `prod` \| `non-prod` | see [Environment Detection](#environment-detection) |
| `data_plane_touched` | bool | ontology `ActionType.interfaces` include `DataPlaneMutating` |
| `graph_stale` | bool | ontology `ActionType.interfaces` include `RequiresInventoryFresh` AND the target Resource's inventory record exceeds `freshness_ttl` |
| `cross_resource_impact` | int | `ActionType.blast_radius.computation == graph_derived` ⇒ count of affected Resources returned by the traversal; `unknown` when the graph is unavailable and the ActionType lacks `GraphTraversalRequired` |
| `cost_impact_monthly` | number (USD/month) | rule's `remediation.cost_impact` estimate, or observed post-hoc reconciliation |
| `verifier_confidence` | number [0..1] | LLM quality-gate signal (only set for T2-produced actions) |

Dimensions are strictly typed; a rule that references an unknown key fails at CI load.

## Initial Rule Table (upstream default)

```yaml
# rule-catalog/risk-classification.yaml (upstream default; fork MAY tune thresholds)
version: 1.0.0
owner_group: aw-owners
rules:
  # ── DENY (never execute) ──
  - if: { policy_violation: true }
    decision: deny
    reason: "policy-as-code verifier rejected the action"
  - if: { blast_radius: subscription }
    decision: deny
    reason: "no autonomous change spans a full subscription"
  - if: { graph_stale: true }
    decision: deny
    reason: "inventory graph is stale; refuse to act on a possibly-ghost resource"

  # ── HIL (human approval required) ──
  - if: { irreversible: true }
    decision: hil
    reason: "irreversible mutation always requires an approver quorum >= 2"
    quorum: 2
  - if: { destructive: true }
    decision: hil
    reason: "delete/drop/purge/detach always requires an approver"
  - if: { environment: prod, allowlist_prod_auto: false }
    decision: hil
    reason: "prod defaults to HIL unless the rule is on the prod-auto allowlist"
  - if: { data_plane_touched: true }
    decision: hil
    reason: "data-plane mutations always require an approver"
  - if: { cost_impact_monthly: '>= 100' }
    decision: hil
    reason: "cost impact above the auto threshold"
  - if: { blast_radius: resource_group }
    decision: hil
    reason: "RG-wide changes require an approver"
  - if: { verifier_confidence: '< 0.85' }
    decision: hil
    reason: "T2 quality-gate confidence below auto threshold"

  # ── AUTO (execute without approval) ──
  - if:
      all:
        - reversible: true
        - blast_radius: resource
        - cost_impact_monthly: '< 100'
        - data_plane_touched: false
    decision: auto
    reason: "reversible, resource-scoped, low cost, control-plane only"

  # ── FAIL-CLOSE ──
  - default: hil
    reason: "no matching rule - fail toward safety"
```

**Rule ordering (MUST)**: `deny` rules come first, then `hil`, then `auto`, then the
`default: hil` catch-all. First-match wins so the strictest applicable rule dominates.
CI validates the order (denies before hils before autos) and rejects any rule that could
be dead-code by a preceding broader rule.

## Environment Detection

This section is the **single authoritative environment classifier** for
the whole control plane. Both [execution-model.md](execution-model.md)
(the env axis, via `ActionType.prod_downgrade.detection_ref`) and
[action-ontology.md](action-ontology.md) (`env_scope`) resolve "prod" vs
"non-prod" through this rule, never through a second definition.

`environment: prod` vs `non-prod` is derived from the target **resource-group tag**:

- Tag key: `environment` (case-insensitive)
- Values: `prod` / `production` → `prod`; `non-prod` / `dev` / `test` / `staging` /
  `qa` → `non-prod`
- **Missing or unrecognized tag → `prod`** (fail-safe: unknown environment is treated as
  the highest-risk category)

Enforcement: an Azure Policy assignment SHOULD deny resource-group creation without the
`environment` tag, so the fail-safe path never applies in a governed environment. The
policy assignment is a Phase 1 deliverable in
[phase-1-rule-catalog-t0.md](phases/phase-1-rule-catalog-t0.md).

## Cost Impact Threshold

- **Auto ceiling**: **$100 / month** per action.
- Rationale: covers small right-sizing / stop-idle / tier-adjust remediations without
  approving large disposals. Chosen conservatively for Phase 1 shadow measurement; the
  threshold is a config value, adjustable via a governance PR after measurement.
- The estimate comes from the rule's `remediation.cost_impact` field; if the rule cannot
  estimate, the value is `unknown` → treated as `>= 100` → HIL.

## Allowlist for Prod-Auto

A tiny set of very-low-risk rules MAY be marked as auto-eligible in prod
(`allowlist_prod_auto: true`). Candidates for the initial allowlist (evaluated in shadow
before promotion):

- Tag remediation (add missing owner / cost-center / environment tags).
- Release of unattached public IP addresses.
- NSG allow-any-source rule removal on resources with no data-plane exposure.

**Every allowlist entry is a separately promoted assignment** and passes the standard
shadow → enforce gate ([architecture.instructions.md § Shadow → Enforce Promotion](../../.github/instructions/architecture.instructions.md#safety-invariants)).
The allowlist is not a bypass; it is an opt-in reduction of the prod default.

## Change Process

Updating the risk table follows the standard governance PR flow:

- **Any change** to `risk-classification.yaml` requires a **quorum of 2** `aw-approvers`
  and a `Justification:` block in the PR body.
- **Loosening changes** (widening auto, raising cost threshold, removing a deny) require
  an Owner-tier reviewer (member of `aw-owners`) in the quorum.
- **Tightening changes** (adding a deny, lowering cost threshold, moving auto→HIL) MAY
  merge with regular quorum - safety-side changes never need Owner approval.
- The table version is bumped on every change and captured in the catalog version, so the
  risk decision that classified any historical action is reconstructable
  ([llm-strategy.md § Signature Composition](llm-strategy.md#signature-composition)).

## Audit

Every risk-gate outcome writes an audit entry recording:

- The matched rule id (or `default` if fail-through).
- The feature vector snapshot at decision time.
- The `catalog_version` of `risk-classification.yaml`.
- The routing outcome (`auto` / `hil` / `deny`) and any downstream approval ids.

A future retrospective can filter the audit log by matched rule id to identify
over-triggered rules (e.g. "every prod change is HIL because everything hits Rule 5") and
propose refinements via the same governance PR flow.

## Open Decisions

- [ ] Whether to add a `time_of_day` gate (business hours vs off-hours) as a future
      dimension - deferred until shadow measurement shows a real need.
- [ ] Whether to compute a numeric `risk_score` in addition to the deterministic rule
      table (would only kick in on ties or as a tie-breaker - the deterministic table
      remains authoritative).
- [ ] Fork override policy: can a fork *loosen* the upstream defaults (e.g. raise the
      cost threshold), or only tighten? Recommended default: tightening is free,
      loosening requires an audited Owner override.
