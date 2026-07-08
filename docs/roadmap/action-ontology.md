---
title: Action Ontology
---

# Action Ontology

Every FDAI action - whether a rule-fired remediation or an operator-
requested ops task - is one instance of an **`ActionType`** entry in the
shipped ontology. This document is authoritative for the schema, the
trigger axis (`rule_violation` vs `operator_request`), the tier and role
ceilings, the live-probe reference, and the **fork-override seams** that
let a customer redefine any of these without editing `core/`.

Consumers of this ontology:

- The T0Engine + ActionBuilder ([phase-1](phases/phase-1-rule-catalog-t0.md))
  reads `rollback_contract`, `preconditions`, `stop_conditions`, and
  `blast_radius` when building a rule-fired action.
- The unified RiskGate + Executor ([execution-model.md](execution-model.md))
  reads the tier ceiling, min-role, live-probe reference, and execution
  path to decide **whether** and **how** to run.
- The operator-console narrator ([operator-console.md](operator-console.md))
  reads `trigger_kind`, `description`, and `argument_schema` when
  suggesting or executing an ops-flavoured tool call.

Because a single ontology feeds all three, adding a new remediation or a
new ops verb is one YAML file - no branching in the engine, no new
executor.

> Customer-agnostic: every ActionType name, parameter, and blast-radius
> value below is a placeholder or example. A fork adds / overrides
> entries via config
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

## 1. One ontology, two triggers

The pre-existing 16 shipped ActionTypes were all rule-fired remediation
(`remediate.tag-add`, `remediate.disable-public-access`, ...). Operator
console pull-direction (§4 of
[operator-console.md](operator-console.md)) needs actions that are
triggered by an **operator's chat request** rather than a rule fire:
"restart this pod", "scale out", "flush the cache". These share the same
safety envelope but a different trigger surface.

The ontology handles both with **one schema plus one axis**. `trigger_kind`
is an object whose `kind` field takes one of three allowed values:

```yaml
trigger_kind:
  kind: rule_violation | operator_request | both
  # rule_violation   - T0/T1/T2 engine matched a rule -> auto proposal
  # operator_request - human via console -> explicit ops
  # both             - same ActionType usable by either path
```

- **`rule_violation`** - the ControlLoop constructs the action from a
  matched rule + finding. The trigger is the T0/T1/T2 verdict.
- **`operator_request`** - the operator-console narrator emits a
  tool_call whose target is this ActionType. The trigger is the
  console session + principal + arguments.
- **`both`** - some actions belong to either surface. For example,
  `ops.restart-service` may be triggered by an operator ("restart this")
  or by a rule (a health-probe fail rule). The ontology entry declares
  the union; runtime picks the path.

Nothing in the schema is trigger-specific except this axis; the
executor, the RiskGate, and the audit contract are the same for both.

## 2. Schema

```yaml
schema_version: "1.0.0"
name: string                            # STABLE UNIQUE IDENTIFIER, snake+dot: "ops.restart-service"
                                        # This is the ontology id. Audit refers to it as
                                        # action_type_id; the loader dedupes on it; the
                                        # override overlay file is <name>.yaml (see 7.1).
                                        # (No separate `id` field - `name` already exists on
                                        # every shipped YAML and is the migration-safe key.)
version: semver
category:                               # top-level bucket
  - remediation                         # rule-fired, config-drift-style
  - ops                                 # operator-requested runtime action
  - governance                          # policy / exemption / promotion changes
description: string                     # <= 200 chars, English, no marketing

# --- Operation + interfaces (EXISTING, kept - risk-classification reads these) ---
operation: enum                         # tag | delete | drop | purge | detach | rotate | ...
                                        # risk-classification `destructive` = operation in
                                        # {delete, drop, purge, detach}
interfaces:                             # capability flags on the ActionType
  - ControlPlane | DataPlaneMutating    # risk-classification `data_plane_touched`
  - RequiresInventoryFresh              # risk-classification `graph_stale` input
  - IdempotentByKey | GraphTraversalRequired

# --- Trigger axis (§1) --------------------------------------------------
trigger_kind:                           # one of rule_violation | operator_request | both
  kind: enum
  restrict_to_scenarios: [string, ...]  # optional; narrow which scenarios may fire this

# --- Autonomy + safety (existing, kept exactly as phase-1) --------------
default_mode: shadow                    # NEW ActionType MUST default to shadow
promotion_gate:
  min_shadow_days: int
  min_samples: int
  min_accuracy: float
  max_policy_escapes: int

# --- Execution path (execution-model.md details) ------------------------
execution_path: pr_native | direct_api | pr_manual
                                        # pr_native → shipped GitOpsPrAdapter (default)
                                        # direct_api → ops-fast-path (Azure ARM call)
                                        # pr_manual → PR with hil label, no auto-merge

# --- Rollback contract (existing) ---------------------------------------
rollback_contract: pr_revert | scripted | pitr | snapshot_restore | state_forward_only
irreversible: bool                       # if true, HIL required regardless of tier

# --- Preconditions + stop conditions (existing) -------------------------
preconditions:
  - kind: graph_fresh_within_seconds
    value: int
  - kind: resource_tag_present
    tag: string
  - ...                                  # existing catalog reused

stop_conditions:
  - kind: provider_api_error_streak
    count: int
  - kind: time_box_exceeded_seconds
    seconds: int
  - ...

# --- Blast radius (existing static) -------------------------------------
blast_radius:
  computation: static_enum | graph_derived
  static_bucket: resource | resource_group | subscription
                                        # CSP-neutral bucket, shared with risk-classification.md
  max_affected_resources: int            # graph_derived only

# --- NEW: live-blast probe pointer (TOP-LEVEL; Month 1+; see §6) ---------
live_probe_ref: string                   # optional; e.g. "probes/vm_traffic_last_5m"
                                         # read as ActionType.live_probe_ref by the RiskGate

# --- NEW: tier × role ceilings (execution-model.md §3) ------------------
ceiling_by_tier:
  t0:
    max_autonomy: enforce_auto | enforce_hil | shadow_only
    min_role: reader | contributor | approver | owner
  t1:
    max_autonomy: enforce_auto | enforce_hil | shadow_only
                                         # upstream ships enforce_hil|shadow_only; a fork MAY
                                         # set enforce_auto (schema permits; still gated by
                                         # the Rego requirement in execution-model 2.1)
    min_role: contributor | approver | owner
  t2:
    max_autonomy: shadow_only            # T2 defaults to shadow-only; explicit fork override to raise
    min_role: approver | owner
# NOTE: min_role uses the ordinary ladder reader<contributor<approver<owner only.
# BreakGlass is OFF-LADDER (a separate Entra group, not nested in Owner) and is never a
# min_role value; it only affects approval eligibility at dispatch (execution-model 2.5).

# --- NEW: prod-vs-non-prod downgrade ------------------------------------
env_scope: prod | non_prod | any        # default: any. `non_prod` = dev-only ActionType
                                        # (prod_downgrade MAY be omitted). `any`/`prod` MUST
                                        # carry a prod_downgrade or inherit the risk-table env
                                        # signal - a missing block never fails open into prod auto.
prod_downgrade:
  mode: enforce_hil | shadow_only        # what "prod" collapses to
  detection_ref: string                  # resolves to the SAME env classifier defined in
                                         # risk-classification.md (Environment Detection); do not
                                         # define a second prod-detection rule here

# --- Arguments (only for operator_request or both) ----------------------
argument_schema:                         # JSON Schema; console renders + validates
  type: object
  properties: {...}
  required: [...]

# --- Provenance (existing) ---------------------------------------------
provenance:
  source_url: string
  resolved_ref: string                   # git sha / registry version
  content_hash: string                   # sha256
  license: string
  retrieved_at: RFC3339
```

Existing shipped ActionTypes get **auto-migrated** with:

- `trigger_kind.kind = rule_violation`
- `category = remediation`
- `ceiling_by_tier` filled from the current implicit defaults (T0 →
  `enforce_hil` for medium/high severity, `enforce_auto` for low; T1/T2
  → `shadow_only`)
- No schema-breaking rename; the loader treats missing new fields as
  the safest value.

## 3. Category catalog

Three top-level categories. New categories require a doc PR + a
short-form entry in
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)
so the domain vocabulary stays flat.

### 3.1 `remediation.*`

Rule-fired, config-drift-style. Currently shipped:

- `remediate.tag-add`
- `remediate.disable-public-access`
- `remediate.right-size`
- `remediate.rotate-secret`
- `remediate.enable-tde`
- `remediate.enable-encryption`
- `remediate.enable-diagnostic-settings`
- `remediate.enable-backup-protection`
- `remediate.enable-zone-redundancy`
- `remediate.enable-rbac`
- `remediate.restrict-network-access`
- `remediate.remove-orphan-resource`
- `remediate.set-tls-policy`
- `remediate.enable-purge-protection`
- `remediate.set-retention-policy`
- `remediate.assign-identity`

Default `execution_path: pr_native` (GitOps). A fork MAY override to
`direct_api` per action where the API mutation is a single idempotent
call.

### 3.2 `ops.*`

Operator-requested runtime actions. Shipped Day 1:

- `ops.restart-service` - AKS pod restart, App Service restart, Container App revision restart.
- `ops.scale-out` - increase replica count / instance count. MUST declare
  `cost_impact_monthly` (spend-increasing) so the risk-classification cost
  gate applies ([execution-model.md § 2.8](execution-model.md#28-cost-increasing-ops-actions)).
- `ops.scale-in` - decrease replica count (Approver + live probe).
- `ops.flush-cache` - Redis / CDN cache flush.
- `ops.drain-connection` - drain connections on a load balancer backend.
- `ops.rotate-cert` - rotate a TLS cert (App Gateway / Front Door).
- `ops.failover-primary` - trigger a failover on a replicated resource.
  MUST declare `cost_impact_monthly` when failover targets a larger tier.
- `ops.publish-change-summary` - render a rendered Markdown change
  summary for a resource-group over a bounded time window and hand it
  to the delivery adapter. Reference example of a non-Resource
  business-object flow; the paired ObjectType `ChangeSummary` and
  LinkType `summarizes` are the copy-ready scaffold in
  [downstream-fork-example-vertical.md](downstream-fork-example-vertical.md).

**Vertical mapping.** Each ops ActionType is tagged with the owning
vertical so the [verticals](../../src/fdai/core/verticals) can claim
it and a vertical rule can `remediates:` it: `ops.failover-primary` and
`ops.restart-service` -> Resilience; `ops.scale-in` / `ops.scale-out` ->
Cost Governance; `ops.drain-connection` / `ops.rotate-cert` -> Change
Safety. `ops.flush-cache` and `ops.publish-change-summary` are
cross-vertical (operator-triggered).

Default `execution_path: direct_api` (ops are latency-sensitive; PR
overhead defeats the purpose). A fork MAY force `pr_manual` for a
compliance-heavy environment where every runtime change must land as a
reviewable diff.

### 3.3 `governance.*`

Ontology / catalog / exemption / promotion changes. Four entries are
authored in the ontology today; **only one currently has a live
dispatcher** (the other three are catalog-as-code artifacts waiting on
a PR-native writer to land in P2):

- `governance.promote-action-type` - flip `default_mode` from shadow →
  enforce for one ActionType (bounded by that ActionType's
  `promotion_gate`).
  **Dispatcher: not yet implemented (P2 backlog).**
- `governance.retire-rule` - remove a rule from the enforce set
  (shadow-only or full retire).
  **Dispatcher: not yet implemented (P2 backlog).**
- `governance.grant-exemption` - create a time-boxed exemption
  ([rule-governance.md](rule-governance.md)). Existing exemptions are
  authored as JSON under `rule-catalog/exemptions/` and consumed by
  the risk gate via `ExemptionRegistry`; the runtime **create-a-new-
  exemption** operator flow lands with the same P2 PR-native writer.
- `governance.override-ceiling` - operator-side override on the tier
  ceiling for a specific resource / tag scope (fork extension).
  **Dispatcher shipped** in
  [`src/fdai/core/risk_gate/override_writer.py`](../../src/fdai/core/risk_gate/override_writer.py).

Governance actions always use `execution_path: pr_native` - they are
catalog-as-code changes and MUST land as a reviewed diff.

## 4. Trigger surfaces

### 4.1 `rule_violation` (unchanged behaviour)

```
Event → EventIngest → TrustRouter → T0/T1/T2 → Finding →
  ActionBuilder(finding, rule, action_type) → Action → RiskGate → Executor
```

- The rule declares the ActionType via `remediates: <action_type_id>`
  (existing field).
- `ActionBuilder` populates the Action's `params` from the rule's
  `parameters` block.
- The trigger surface is the event bus.

### 4.2 `operator_request` (new)

```
Chat turn → Narrator → tool_call(action_type_id, args) →
  Coordinator validate args against argument_schema →
  RiskGate → Executor
```

- The operator picks the ActionType through a natural-language turn
  translated to a tool_call by the narrator.
- `argument_schema` (JSON Schema on the ActionType) validates the args
  at the coordinator boundary - the console never dispatches an
  ill-formed action to the executor.
- The trigger surface is the operator-console session.

Note: both surfaces meet at the RiskGate (execution-model.md §3). The
ActionType does not know which trigger produced its invocation - only
`trigger_kind` scoping (§1) constrains it.

### 4.3 Three classification axes (how they relate)

Three orthogonal labels describe an action; they are not synonyms:

| Axis | Owner doc | Values | Answers |
|------|-----------|--------|---------|
| `category` | this doc (§3) | remediation / ops / governance | *what kind of change* |
| `trigger_kind` | this doc (§1) | rule_violation / operator_request / both | *who initiates* |
| `side_effect_class` | [operator-console.md § 3.4](operator-console.md#34-tool-discovery-contract) | read / simulate / approve / execute / breakglass | *what the console tool does* |

Typical combinations: a `remediation` ActionType is
`trigger_kind=rule_violation` and, when surfaced as a console tool, its
tool is `side_effect_class=execute`; an `ops` ActionType is usually
`trigger_kind=both` with an `execute` tool; a `governance` ActionType is
`trigger_kind=operator_request` and its tool is `approve` or `execute`.
The audit entry (§9) carries all three so analytics can slice on any axis.

## 5. Argument schema (operator_request only)

Rule-fired ActionTypes receive their params from the rule's
`parameters` block; operator-requested ActionTypes receive theirs from
the operator's tool_call arguments and MUST declare an
`argument_schema` JSON Schema so the console can:

1. Render the tool in `list_tools()` with a machine-readable shape.
2. Validate arguments at the coordinator boundary
   ([operator-console.md § 5.2](operator-console.md#52-consoletool)) before
   calling the action.
3. Redact sensitive fields (mark with `x-fdai-redact: true`) at
   the audit-write boundary.

### 5.1 Example - `ops.restart-service`

```yaml
argument_schema:
  type: object
  additionalProperties: false
  required: [target_resource_ref, restart_reason]
  properties:
    target_resource_ref:
      type: string
      description: >-
        CSP-neutral resource id, e.g. "example-rg/aks/cluster/pod-name".
        Grammar is the CSP-neutral inventory resource id defined in
        csp-neutrality.md (Inventory contract); the coordinator validates
        the ref against that grammar before dispatch.
    restart_reason:
      type: string
      minLength: 10
      maxLength: 200
      description: Human-readable justification; recorded in the audit trail.
    grace_period_seconds:
      type: integer
      default: 30
      minimum: 0
      maximum: 300
```

### 5.2 Redaction hints

Fields the operator may type that could carry secrets or PII (e.g. a
password mid-tool-call, an email inside a `restart_reason`) SHOULD carry
`x-fdai-redact` so the redactor strips them before the audit
write:

```yaml
properties:
  temp_admin_password:
    type: string
    x-fdai-redact: true    # never persisted verbatim
```

## 6. Live blast probe (§6 of execution-model.md, Month 1+)

Static `blast_radius` alone is coarse - the same "delete storage
account" mutation can be trivial on a dead resource and catastrophic on
a live one. Month 1 adds a **live_probe_ref** field on ActionType so
the RiskGate can consult a probe before deciding.

```yaml
live_probe_ref: probes/vm_traffic_last_5m
```

- Probes are declared as YAML under
  [`rule-catalog/probes/`](../../rule-catalog/probes/) - one file per
  probe id.
- Each probe declares the input (target resource ref), the query
  (Azure Monitor KQL / Metric API / ARG), and the interpretation
  function (`quiet | active | overloaded`).
- `RiskGate` calls the probe and combines the answer with the static
  ceiling (see [execution-model.md § 4](execution-model.md#4-live-blast-probe)).

Probes are opt-in per ActionType and per environment. A fork ships
its own probes; the upstream catalog ships a small starter set (VM
traffic, storage access log, load-balancer backend health).

## 7. Fork override seams

Everything above is data. A fork MUST be able to redefine any axis
without editing `core/` or the upstream YAMLs. The ontology exposes
four override channels:

### 7.1 File-based overlay

- Upstream ships `rule-catalog/action-types/<name>.yaml`.
- A fork places `rule-catalog/action-types-overrides/<name>.yaml` with a
  strict subset of fields to override.
- The loader merges upstream + overrides at startup with **key-by-key
  precedence** (overrides win); a missing overrides field falls back to
  upstream. An overlay whose `name` has no matching upstream ActionType
  is a fatal load error - the overlay layer only *tightens* an existing
  ActionType, it can never introduce one. A fork that adds a **new**
  ActionType ships it under `rule-catalog/action-types-custom/` and
  concatenates that root instead (see 7.6).
- Every merge writes an audit entry
  (`action_kind=catalog.load.action_type_overlay`) so a promoted
  override is traceable.

```yaml
# example: fork tightens tag-add on prod
# path: rule-catalog/action-types-overrides/remediate.tag-add.yaml
name: remediate.tag-add
ceiling_by_tier:
  t0:
    max_autonomy: enforce_hil      # upstream had enforce_auto; fork downgrades
prod_downgrade:
  mode: shadow_only
```

### 7.2 Policy-as-code overlay

- Rego policies under `policies/action_types/` can compute a per-invocation
  override, e.g. "on Friday afternoon downgrade every enforce_auto to
  enforce_hil" (change freeze).
- The RiskGate evaluates the policy after the file overlay - Rego wins
  when both express something for the same axis.

### 7.3 Config-driven overlay

- Env-var toggles for coarse switches (feature-flag style):
  `FDAI_OVERRIDE_ACTION_TYPE_<id>_MAX_AUTONOMY=shadow_only`.
- Rare; documented for emergency downgrades where a Rego re-deploy is
  too slow.

### 7.4 Runtime override (chat)

- An Approver / Owner in the operator console can call
  `governance.override-ceiling` with a bounded scope
  (`resource_group=X, until=YYYY-MM-DDT..Z`). This writes a
  Rego policy fragment under `policies/action_types/` via `pr_native`
  (audited).
- Time-boxed; auto-expiry ships with the existing exemption workflow
  ([rule-governance.md](rule-governance.md)).

### 7.5 Precedence

When multiple overlays speak to the same axis, precedence is:

1. Runtime override (Rego fragment, chat-authored, time-boxed) - most
   specific, most recent.
2. Rego policy (`policies/action_types/`) - operator-authored steady
   state.
3. File overlay (`rule-catalog/action-types-overrides/`) - fork
   compile-time.
4. Upstream YAML (`rule-catalog/action-types/`) - repository default.

The RiskGate always resolves in that order and records the winning
overlay layer on the audit entry.

### 7.6 New ActionType additions (separate root)

The four channels above only *modify* a shipped ActionType. Adding a
**brand-new** ActionType is not an override and does not participate in
the 7.5 precedence chain. A fork ships the new ActionType under
`rule-catalog/action-types-custom/` (upstream keeps that directory empty
apart from a `.yaml.example` template) and loads it as a second catalog
root concatenated with the upstream catalog:

```python
action_types = (
    load_action_type_catalog(Path("rule-catalog/action-types"), ...)
    + load_action_type_catalog(Path("fork/action-types-custom"), ...)
)
```

A duplicate `name` across the two roots is a fatal load error, so an
addition can never silently shadow an upstream ActionType (shadowing is
what the 7.1 overlay layer is for). See
[../../rule-catalog/action-types-custom/README.md](../../rule-catalog/action-types-custom/README.md).

## 8. Loader + validation

- The loader ([`rule_catalog/schema/action_type.py`](../../src/fdai/rule_catalog/schema/action_type.py))
  loads upstream + overrides + Rego references at startup.
- Cross-checks (already shipped):
  - Every `remediates:` on a rule points to a loaded ActionType.
  - Every `check_logic.reference` under `policies/` resolves to a real
    file.
- New Day-1 cross-checks:
  - `trigger_kind = rule_violation | both` → at least one shipped rule
    references it, otherwise the loader logs a "dangling
    remediation-only ActionType" warning (not fatal - fork may enable
    later).
  - `trigger_kind = operator_request | both` → `argument_schema` MUST
    be non-empty. Missing schema is a fatal load error.
  - `ceiling_by_tier.t2.max_autonomy != shadow_only` → fatal unless a
    Rego policy in `policies/action_types/` explicitly names the
    ActionType (T2 raise MUST be defended by an operator-authored
    policy).
  - `live_probe_ref` -> the referenced probe MUST exist under
    `rule-catalog/probes/` (or under a fork-only path). Missing probe
    is fatal. On Day 1 no shipped ActionType sets `live_probe_ref` and
    `rule-catalog/probes/` ships with only a `README.md` placeholder, so
    this cross-check is a no-op until Month 1 binds the first probe.
  - Every `argument_schema` property flagged `x-fdai-redact: true`
    MUST be a leaf `string`/`number`; the loader collects the redaction
    path set and hands it to the audit redactor so the value never lands
    verbatim (§5.2). Any unknown `x-fdai-*` extension key is a fatal
    load error (typo guard, so a misspelled redact hint cannot silently
    leak a secret).
- Catalog-entry policy (fatal, `load_action_type_catalog` only):
  safety-critical fields that the JSON Schema leaves optional for the
  Day-1 backfill (§10) MUST be present on a real catalog entry. A
  missing field is a fatal load error, not a silent inheritance of a
  permissive default:
  - `category`, `trigger_kind`, `execution_path`, and `blast_radius`
    MUST be declared.
  - `ceiling_by_tier` MUST declare all three tiers (`t0`, `t1`, `t2`).
  - `argument_schema`, when present, MUST set `type: object` and
    `additionalProperties: false` so the console can never pass an
    unspecified argument.
  - `operation: drop` or `operation: purge` (both destroy data or
    schema) MUST declare the `DataPlaneMutating` interface, so the risk
    gate applies the data-plane HIL gate. Omitting it would silently
    downgrade the risk classification.
  This gate runs only on the real catalog roots (upstream +
  `action-types-custom/`); `load_action_type_from_mapping` stays
  permissive so a unit-test model fixture needs only the pydantic-
  required fields. An ActionType that reaches the RiskGate with no
  `blast_radius` (only possible for a hand-built model in a test or fork
  adapter) caps the static-blast axis at `enforce_hil`, never
  `enforce_auto` - an unknown impact surface fails closed.

## 9. Audit contract

Every action dispatch (rule-fired or operator-fired) writes an audit
entry with the ActionType metadata attached:

```json
{
  "action_kind": "action.dispatch",
  "action_type_id": "ops.restart-service",
  "category": "ops",
  "trigger_kind": "operator_request",
  "side_effect_class": "execute",
  "principal": {...},
  "arguments": {...},
  "arguments_redacted": [...],
  "resolved_ceiling": { "...": "full 6-axis + risk_table block per execution-model.md 8" },
  "risk_decision": "hil",
  "quorum": 1,
  "mode": "enforce",
  "execution_path": "direct_api",
  "started_at": "...",
  ...
}
```

The `resolved_ceiling` block is the readable proof of how the
risk-classification table + 6 axes combined to reach the decision; its
exact shape (including the `risk_table` axis and `quorum`) is authoritative
in [execution-model.md § 8](execution-model.md#8-resolved_ceiling-audit-block).
A future overlay change never breaks past audit entries because the
ceiling that was in effect at dispatch time is recorded verbatim.

## 10. Migration plan

The ontology change lands in three steps; each step is a reviewed
catalog-as-code PR (see [rule-governance.md](rule-governance.md)):

1. **Schema extension** - the loader learns the new fields with
   safe defaults. All 16 shipped ActionTypes still validate.
2. **Backfill** - `trigger_kind = rule_violation` is set on every
   existing entry; `ceiling_by_tier` is populated from the pre-existing
   implicit ceilings (`default_mode`, `promotion_gate.max_policy_escapes`).
3. **Ops catalog** - the shipped ops.* set (§3.2) lands with
   `argument_schema`, `direct_api` path, and the appropriate ceilings.

The operator console does not consume `trigger_kind = operator_request`
ActionTypes until step 3 completes; earlier steps are strictly
non-breaking for the ControlLoop.

## 11. Testability

- **Schema** - JSON Schema validation on every YAML load (existing).
- **Overlay precedence** - table-driven test over every axis + layer
  combination (§7.5).
- **Argument schema** - property tests: any input outside the schema is
  rejected before dispatch; redacted fields never appear in audit
  payload.
- **Live-probe hook** - fake `LiveBlastProbe` returns each of `quiet /
  active / overloaded`; ceiling adjustment table-driven.
- **Rego overlay** - integration tests exercising a policy that
  downgrades on Fridays; time frozen; assert the audit entry names the
  overlay layer.
- **Cross-check load errors** - fixture ActionType with a missing
  `argument_schema` for `operator_request` fails load with a specific
  error.

## 12. Related docs

- [execution-model.md](execution-model.md) - consumes this ontology; the
  RiskGate + Executor + live-probe combinator.
- [operator-console.md](operator-console.md) - operator-request
  trigger surface; tool schema is `argument_schema`.
- [rule-governance.md](rule-governance.md) - how ActionType promotions,
  retirements, and overrides flow through the catalog PR pipeline.
- [phase-1-rule-catalog-t0.md](phases/phase-1-rule-catalog-t0.md) -
  original ActionType introduction and rule → ActionType dispatch.
- [security-and-identity.md](security-and-identity.md) - safety
  invariants and identity contract every action inherits.
