---
title: Risk Classification (automatic execution vs human approval vs denial)
---
# Risk Classification (automatic execution vs human approval vs denial)

The risk-classification table ([architecture.instructions.md § Control Loop](../../../.github/instructions/architecture.instructions.md#control-loop))
classifies every candidate action's baseline as `auto`, `hil`, or `deny`. The unified RiskGate
can lower the final outcome through its six-axis ceiling, including to `shadow`. This file is
authoritative for **the baseline classification rules**: their shape, initial rule table,
ownership, and update process. It resolves P0 Open Decision *"Risk-classification
policy (auto vs HIL) and initial policy approver"* from
[security-and-identity.md](../architecture/security-and-identity.md#open-decisions).

> Customer-agnostic: every value below (cost threshold, tag key, resource-group name) is a
> **default** in the upstream; a fork tunes them via config
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
## Where the Table Lives

- **Runtime path**: `rule-catalog/risk-classification.yaml` - catalog-as-code, reviewed via
  PR like rules/assignments/exemptions/overrides. Repository CODEOWNERS names the GitHub
  `fdai-owners` team. The deployment's branch protection/CI applies the two-person
  `aw-approvers` governance contract ([user-rbac-and-identity.md § 5.1](../interfaces/user-rbac-and-identity.md#51-codeowners-single-approver-group-path-based-reviewer-count)).
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

Standing authorization does not raise an `hil` baseline to `auto` or alter the matched rule.
Instead, it supplies a pre-existing, human-authored Approval after the escalation deadline when
the exact A3-E envelope remains valid. Thor may execute the approved HIL action while the audit
retains the original risk rule, approval identity, standing-authorization id, and authority class.
Silence without that Approval remains a no-op. See
[Escalation and Standing Authority](escalation-and-standing-authority.md).

### Full-authority development profile

The planned single-operator production profile is a different, narrower exception. It lets one
named operator satisfy approval and quorum in one production installation, but it keeps this
table's risk classes and denials. See
[Operator Governance Profiles](operator-governance-profiles.md).

The profile is a separate development authority axis, not another risk-table rule. The table still
computes and records the baseline decision, but an exact, unexpired profile binding plus the sole
Owner's current approval may admit any registered action category inside its dedicated test scope.
This includes subscription-wide Azure mutation inside the bound test subscription, destructive or
irreversible actions, Chaos, and ActionType or Workflow promotion, demotion, and rollback. Unknown
actions, scope escape, identity mismatch, or missing audit, lock, and idempotency evidence remain
ineligible. The shared contract is immutable and digest-only for tenant, subscription, and optional
resource-group identity. Deployment composition must inject the profile, current Owner check, and
distinct executor identity explicitly. Var and Thor retain the original risk and quorum while
recording the effective development quorum of one. Development promotion writes only to the exact
profile namespace and records `production_ready: false`. Core provides the authoritative source: it
prepares each binding from its own built Action, deterministic dry-run receipt, and the selected
profile, records it once with an audit entry, and verifies only a current recorded binding.
Deployment selects the profile through `FDAI_FULL_AUTHORITY_DEVELOPMENT_PROFILE_JSON` and a distinct
executor principal, and the ControlLoop and the Pantheon share one source. The ControlLoop never
accepts an event-carried confirmation. When the Owner's own operator request routes to human
approval, Core reads the exact target revision, records the binding of the exact action it parks,
and writes a digest-bound development block into the park. The block retains the original level
and quorum, the effective quorum of one, the target revision, the dry-run and scope digests, and the
authorized executor identity, and the approval card shows those exact facts to the Owner.
The Owner approves from the FDAI Console approval queue after a fresh Entra sign-in. The Operator
requires a signed `auth_time` later than the park and at most 10 minutes old, and the decision
transaction revalidates the exception against the locked park row. Core admits it only after it
rereads the durable Operator receipt and binding, confirms that the target revision is unchanged,
and the shared evaluator accepts the reconstructed confirmation, including the current ActionType.
Because the Owner's decision is the approval's only receipt, a refused self-approval closes the park
with its reason so the Owner can submit the request again.
A category-only denial of the Owner's own request parks instead of denying. It is category-only when
every matching deny rule conditions only ActionType category dimensions (blast radius,
destructiveness, reversibility, rollback path, or data-plane touch), the table without those rules
would not deny, `risk_table` and `static_blast` are the only denying ceiling axes, every other axis
already admits human approval, the runtime gate itself does not deny, current evidence has no
conflict, and every development safety and evidence prerequisite holds. The upstream table's
`deny-subscription-blast` is the only such rule. Core parks it only for a registered direct-API
ActionType, because the binding records the deterministic direct-API dry-run receipt, only while the
profile is valid, and never for a workflow step; the shipped subscription-bucket ActionType
`governance.retire-rule` is `pr_native` and keeps its denial. The binding scope is the target
location widened to the declared blast radius; a subscription-wide, undeclared, or graph-derived
blast radius needs the whole dedicated subscription, which a profile that binds only resource groups
never covers, and admission refuses a narrower binding. The block records the original `deny`, the
category facts, the evaluated event, and, as the original quorum, the quorum the table requires once
the category rule is lifted, and it marks the park Owner-only. Operator, the decision transaction,
and Core each refuse every approval except the Owner's attested self-approval. Any authorized
approver, including the requesting Owner, may reject it, because a rejection grants nothing; an
unanswered park expires. Before the ordinary resume claim dispatches an admitted self-approval, the
ControlLoop reruns the full current evaluation: current inventory, execution authorization, kill
switch, degradation, promotion state, evidence conflicts, preconditions, live probe, and the risk
table must still yield the same category-only denial and residual quorum in the same mode, and the
target revision must be unchanged. Every other denial, and any denial outside the profile or its
scope, still denies. Inside the profile, disposable-resource recreation is the bounded recovery
path. Any missing evidence parks the action for ordinary multi-operator approval. The runtime Owner
check accepts only the profile's owner principal while the profile is current. Audit preserves the
original role, quorum, and no-self-approval rule and records the effective development quorum of one
without inventing identities; typed authority records use the public contract-model facade, and
digest helpers add no authority. A missing profile, binding source, current Owner check, or distinct
executor keeps the ordinary no-self-approval rule, Slack and Teams never carry the Owner's
self-approval, and self-rejection of any other development park keeps the ordinary refusal. The
capability stays `in-progress` until a live Owner run is retained. Focused tests don't establish a
live deployment or production readiness.

## Classification Dimensions

The risk gate composes a **feature vector** for every candidate action from the ontology
signals it already has ([llm-strategy.md § Rule-to-Decision Lookup Pipeline](../architecture/llm-strategy.md#rule-to-decision-lookup-pipeline)).
No new data collection is introduced.

| Dimension | Type | Source |
|-----------|------|--------|
| `policy_violation` | bool | OPA/Rego verifier verdict |
| `destructive` | bool | ontology `ActionType.operation ∈ {delete, drop, purge, detach}` |
| `irreversible` | bool | ontology `ActionType.irreversible == true` (a rolled-back state cannot fully restore the pre-action state) |
| `blast_radius` | enum `resource` \| `resource_group` \| `subscription` | `applies_to` × scope of the affected resource(s); when `ActionType.blast_radius.computation == graph_derived`, the risk-gate walks Resource→Resource links (default `contains` + reverse `depends_on`, depth 2) and maps the affected-resource count to a bucket |
| `rollback_path` | enum `pr_revert` \| `scripted` \| `pitr` \| `snapshot_restore` \| `state_forward_only` | `remediates` action's rollback contract (no `none` value - every ActionType MUST declare an undo path) |
| `reversible` | bool | shortcut for `irreversible == false` |
| `environment` | enum `prod` \| `non-prod` | see the [environment detection method](#environment-detection) |
| `data_plane_touched` | bool | ontology `ActionType.interfaces` include `DataPlaneMutating` |
| `graph_stale` | bool | ontology `ActionType.interfaces` include `RequiresInventoryFresh` AND the target Resource's inventory record exceeds `freshness_ttl` |
| `cross_resource_impact` | int | `ActionType.blast_radius.computation == graph_derived` ⇒ count of affected Resources returned by the traversal; `unknown` when the graph is unavailable and the ActionType lacks `GraphTraversalRequired` |
| `cost_impact_monthly` | number (USD/month) | rule's `remediation.cost_impact_monthly_usd` estimate, or observed post-hoc reconciliation |
| `verifier_confidence` | number [0..1] | LLM quality-gate signal (only set for T2-produced actions) |

Dimensions are strictly typed; a rule that references an unknown key fails at CI load.

## Initial Rule Table (upstream default)

```yaml
# rule-catalog/risk-classification.yaml (upstream default; fork MAY tune thresholds)
version: 1.0.0
owner_group: aw-owners
rules:
  # ── DENY (never execute) ──
  - id: deny-policy-violation
    if: { policy_violation: true }
    decision: deny
    reason: "policy-as-code verifier rejected the action"
  - id: deny-subscription-blast
    if: { blast_radius: subscription }
    decision: deny
    reason: "no autonomous change spans a full subscription"
  - id: deny-graph-stale
    if: { graph_stale: true }
    decision: deny
    reason: "inventory graph is stale; refuse to act on a possibly-ghost resource"

  # ── HIL (human approval required) ──
  - id: hil-irreversible
    if: { irreversible: true }
    decision: hil
    reason: "irreversible mutation always requires an approver quorum >= 2"
    quorum: 2
  - id: hil-destructive
    if: { destructive: true }
    decision: hil
    reason: "delete/drop/purge/detach always requires an approver"
  - id: hil-prod
    if: { environment: prod, allowlist_prod_auto: false }
    decision: hil
    reason: "prod defaults to HIL unless the rule is on the prod-auto allowlist"
  - id: hil-data-plane
    if: { data_plane_touched: true }
    decision: hil
    reason: "data-plane mutations always require an approver"
  - id: hil-cost
    if: { cost_impact_monthly: '>= 100' }
    decision: hil
    reason: "cost impact above the auto threshold"
  - id: hil-resource-group-blast
    if: { blast_radius: resource_group }
    decision: hil
    reason: "RG-wide changes require an approver"
  - id: hil-low-confidence
    if: { verifier_confidence: '< 0.85' }
    decision: hil
    reason: "T2 quality-gate confidence below auto threshold"

  # ── AUTO (execute without approval) ──
  - id: auto-low-risk
    if:
      all:
        - reversible: true
        - blast_radius: resource
        - cost_impact_monthly: '< 100'
        - data_plane_touched: false
    decision: auto
    reason: "reversible, resource-scoped, low cost, control-plane only"

  # ── FAIL-CLOSE ──
  - id: default-hil
    default: hil
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

- Canonical tag key: `fdai:env` (written by the Terraform base tag set).
- Compatibility keys: `environment` and `Environment` are accepted for resources that predate
  the namespaced tag. When both exist, `fdai:env` wins.
- Values: `prod` / `production` → `prod`; `non-prod` / `dev` / `test` / `staging` /
  `qa` → `non-prod`
- **Missing or unrecognized tag → `prod`** (fail-safe: unknown environment is treated as
  the highest-risk category)

Enforcement: an Azure Policy assignment SHOULD deny resource-group creation without the
`fdai:env` tag, so the fail-safe path never applies in a governed environment. The
policy assignment is a Phase 1 deliverable in
[phase-1-rule-catalog-t0.md](../phases/phase-1-rule-catalog-t0.md).

## Environment Promotion (handoff target)

The binary `prod` / `non-prod` axis above is the authoritative runtime classifier. The
dev-to-ops handoff gate ([operational-readiness.md](../operations/operational-readiness.md)) needs one
thing the runtime axis does not carry: a direction. It reads the **target** environment on
the `ownership_transfer` signal and gates on whether the transfer is a promotion *toward
prod*.

To keep a single definition, the lifecycle stages are an ordering over the exact tag
values the classifier already recognizes - no new tag, no second classifier:

`dev < test < staging < qa < prod`

- The stages `dev`, `test`, `staging`, `qa` all resolve to `non-prod` on the runtime
  axis; the ordering is used only to answer "is the target stage `prod`" at handoff time.
- A transfer whose **target stage is `prod`** is a promotion into production: the ORR
  treats any `critical` finding as `blocking` regardless of the active profile default,
  reusing the same fail-safe posture as `prod_downgrade` (a downgrade never raises
  autonomy).
- A missing or unrecognized target stage resolves to `prod`, the same fail-safe as
  Environment Detection, so an un-tagged handoff is gated at the strictest level.
- The ordering never widens autonomy: a lower target stage never unlocks an auto path the
  runtime axis would have gated.

The ordering is a doc-level contract consumed only by the ORR gate; it adds no runtime axis
to `risk-classification.yaml`. The runtime risk table still sees only
`environment: prod | non-prod`.

## Cost Impact Threshold

- **Auto ceiling**: **$100 / month** per action.
- Rationale: covers small right-sizing / stop-idle / tier-adjust remediations without
  approving large disposals. Chosen conservatively for Phase 1 shadow measurement; the
  threshold is a config value, adjustable via a governance PR after measurement.
- The estimate comes from the rule's `remediation.cost_impact_monthly_usd` field; if the rule cannot
  estimate, the value is `unknown` → treated as `>= 100` → HIL.

## Allowlist for Prod-Auto

A tiny set of very-low-risk rules MAY be marked as auto-eligible in prod
(`allowlist_prod_auto: true`). Candidates for the initial allowlist (evaluated in shadow
before promotion):

- Tag remediation (add missing owner / cost-center / environment tags).
- Release of unattached public IP addresses.
- NSG allow-any-source rule removal on resources with no data-plane exposure.

**Every allowlist entry is a separately promoted assignment** and passes the standard
shadow → enforce gate ([architecture.instructions.md § Shadow → Enforce Promotion](../../../.github/instructions/architecture.instructions.md#safety-invariants)).
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
  ([llm-strategy.md § Signature Composition](../architecture/llm-strategy.md#signature-composition)).

### What the commit gate proves

The approval quorum lives in branch protection and cannot be read from a local checkout, so
[`check-risk-table-change.py`](../../../scripts/quality/architecture/check-risk-table-change.py)
enforces only the half that the diff decides. On every commit that touches the table it requires:

- A strictly increasing `MAJOR.MINOR.PATCH` version, so no change reaches the audit payload
  wearing the version of the revision it replaced.
- An unchanged `owner_group`, so a table edit cannot quietly re-home ownership away from the
  Owner tier that the table's blast radius demands.
- A non-empty `reason` on every rule, which is the in-file half of the PR `Justification:` block.
- Unique rule ids, exactly one fail-close `default`, and that default last - a default that
  drifts upward would stop catching the cases no rule matched.
- At least a **minor** version bump for a loosening change. The catalog version is all a replayed
  audit record shows, so a loosening that hid behind a patch bump would be indistinguishable from
  a typo fix months later.

Direction classification is fail-closed. Widening a decision, dropping a guardrail rule, lowering
a quorum, editing a match condition, or reordering rules all count as loosening, because first-match
evaluation means the gate cannot prove any of those narrows the table on its own. Only a provably
safety-side edit is reported as tightening, so an unrecognized edit shape raises the review bar
rather than lowering it. The gate never claims to have checked the reviewer quorum or the
Owner-tier reviewer; it prints which one the change needs.

## Audit

The current control-loop audit entry records:

- The matched rule id (`default-hil` on fail-through).
- The final decision (`auto` / `hil` / `shadow` / `deny`) and quorum.
- The `resolved_ceiling` with every axis that contributed to the final decision.
- The `catalog_version` of the `risk-classification.yaml` revision that classified the action.
- The `feature_vector` snapshot, including the dimensions that were unset, so an absent
  signal is distinguishable from a dropped one.
- The `ceiling_inputs` block: resolved role, graph-derived affected count, the recorded
  live-probe reading, its consecutive-failure streak, and the `system_degraded` and
  `kill_switch_engaged` fail-safe flags.

The last three make replay self-contained: a recorded payload is re-evaluated against the table
version it names and the inputs it carries, so a later catalog change cannot silently rewrite a
historical decision and a replay never re-queries a live probe.

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

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/decisioning/risk-classification.md) |
