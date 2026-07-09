---
title: Process Automation
---

# Process Automation

Process automation turns a multi-step business process into a first-class,
ontology-linked, governed artifact. A process is not a script that reaches
around the control plane; it is a declarative sequence of ontology
`ActionType` invocations that the same trust-routing control loop dispatches,
one step at a time, under the same safety invariants as a single remediation.

This document is the machine-readable counterpart to
[agent-workflows.md](agent-workflows.md). Where that document describes the
eleven cross-agent workflows in prose and sequence diagrams, this one defines
the catalog schema, the ontology additions, and the runtime wiring that let a
workflow ship as catalog-as-code and run in shadow mode.

> **Scope.** Everything here is customer-agnostic
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).
> A workflow references only the upstream `ActionType` catalog under
> [`rule-catalog/action-types/`](../../rule-catalog/action-types/); it never
> declares a new mutation primitive. A process that needs a new capability is
> a signal to open an upstream `ActionType` doc PR first.

## 1. Four distinct concepts

Process automation composes four concepts that MUST NOT be conflated. Each has
a single responsibility.

| Concept | Responsibility | Backing |
|---------|----------------|---------|
| **ActionType** | one CSP-neutral mutation category with its safety invariants (stop-condition, rollback contract, blast-radius cap, audit) | [`rule-catalog/action-types/`](../../rule-catalog/action-types/), [action-ontology.md](action-ontology.md) |
| **Workflow** | the *declaration* of a business process: an ordered list of steps, each referencing one `ActionType`, plus a trigger, a promotion gate, and a default mode | [`rule-catalog/workflows/`](../../rule-catalog/workflows/), schema below |
| **Process** | the *runtime instance and state* of a running workflow: which step is current, which resource it targets, which findings it advanced through | `Process` ObjectType (ontology) |
| **Runbook** | the *execution mechanism*: walk the step list, honor `on_failure`, write the aggregate audit row | [`src/fdai/core/runbook/`](../../src/fdai/core/runbook/) |

The separation matters: a `Workflow` declares *what* runs and *when*; a
`Runbook` is the thin executor a compiled `Workflow` produces; a `Process` is
the audited state of one live run. A step never carries its own mutation logic
- it delegates to an `ActionType`, so every step inherits the four safety
invariants for free.

## 2. Workflow catalog schema

A workflow is catalog-as-code under
[`rule-catalog/workflows/`](../../rule-catalog/workflows/), validated at load
against [`shared/contracts/workflow/schema.json`](../../src/fdai/shared/contracts/workflow/schema.json)
and the `Workflow` pydantic model. All fields except `description` and
`anti_scope` are required.

```yaml
schema_version: "1.0.0"
name: cost-aware-remediation          # stable dotted id; the audit key
version: "1.0.0"
description: >-                        # <= 200 chars, English, no marketing
  Attach a cost impact to every SRE remediation so the verdict reflects
  reliability and finance together.
trigger:
  kind: signal                         # signal | schedule
  signal_type: object.drift            # required when kind == signal
  schedule: null                       # RFC-5545-style cron when kind == schedule
default_mode: shadow                   # NEW workflows MUST default to shadow
promotion_gate:
  min_shadow_days: 14
  min_samples: 100
  min_accuracy: 0.95
  max_policy_escapes: 0
steps:
  - id: estimate_cost
    action_type_ref: remediate.right-size   # MUST resolve to an ActionType name
    guard_rule_ref: null                     # optional Rule id that gates the step
    compensated_by: null                     # optional ActionType to undo this step
    on_failure: null                         # optional step id to run on failure
  - id: apply_rightsize
    action_type_ref: remediate.right-size
    on_failure: null
anti_scope: >-                          # optional; what the workflow deliberately omits
  Not a budget enforcement path; it only annotates SRE actions with cost.
```

Field rules the loader enforces:

- `name` is a stable dotted id (`^[a-z][a-z0-9_.-]{0,79}$`); the loader dedupes
  on it across upstream and every fork addition.
- `steps` has at least one entry; step `id` is unique within the workflow.
- Every `action_type_ref` MUST resolve to a registered `ActionType` name from
  [`load_action_type_catalog`](../../src/fdai/rule_catalog/schema/action_type.py).
  A typo fails at load, not at first dispatch - the same cross-reference
  discipline the `remediates` link uses in
  [`rule.py`](../../src/fdai/rule_catalog/schema/rule.py).
- `compensated_by`, when set, MUST also resolve to an `ActionType` name. It is
  the saga rollback action for that step (see [section 5](#5-saga-compensation)).
- `on_failure`, when set, MUST reference an existing step `id` in the same
  workflow, exactly like a [`Runbook`](../../src/fdai/core/runbook/models.py)
  step.
- `guard_rule_ref`, when set, MUST resolve to a Rule id from the loaded rule
  catalog. The guard is the deterministic "when" for the step - a
  policy-as-code predicate, never model text.
- Upstream workflows MUST set `default_mode: shadow`. A workflow that ships
  `enforce` is a schema violation upstream; promotion to enforce is a separate,
  gated governance PR.

### 2.1 Known limitations (P1)

- **`signal_type` is a free string.** The trigger `signal_type` is not
  cross-referenced against a signal-type registry (none exists upstream yet),
  so a typo is not caught at load. Treat it as documentation until the
  `SignalType` ontology promotion lands.
- **`on_failure` also runs on the success path.** The compiled Runbook runner
  walks every declared step in order; an `on_failure` target is a normal step
  that runs on success too, and additionally runs as the fallback on failure.
  Author an `on_failure` target as a step that is safe to run in both paths
  (idempotent), or leave it null and rely on `compensated_by`. The shipped
  workflows leave `on_failure` null for this reason.

## 3. Ontology additions

Process automation adds exactly one ObjectType and two LinkTypes. This is the
minimal, justified extension that makes a running process traversable in the
graph without duplicating the audit log.

### 3.1 `Process` ObjectType

[`rule-catalog/vocabulary/object-types/Process.yaml`](../../rule-catalog/vocabulary/object-types/Process.yaml)
declares the runtime state of one workflow run. It keys on `id` like every
shipped built-in.

| Property | Type | Meaning |
|----------|------|---------|
| `id` | string | Idempotent process id derived from `(workflow_ref, target_resource_id, trigger_ts)`; retries reuse it. |
| `workflow_ref` | string | The `Workflow` name this process instantiates. |
| `status` | string | `pending`, `running`, `succeeded`, `failed`, `compensating`, or `compensated`. |
| `current_step` | string | Step id currently in flight (empty when terminal). |
| `target_resource_id` | string | Primary Resource the process operates on. |
| `started_at` | datetime | RFC 3339 UTC start timestamp. |
| `context` | object | Open-shape context bag captured by the trigger. |

### 3.2 LinkTypes

| LinkType | Endpoints | Cardinality | Flags | Meaning |
|----------|-----------|-------------|-------|---------|
| `targets` | Process -> Resource | many_to_one | - | which resource the process operates on; lets the risk-gate compute blast radius over the process target. |
| `advances` | Process -> Finding | many_to_many | `temporal_order` | the ordered findings a process advanced through; a time-respecting chain for replay. |

The business-critical link - process step to `ActionType` - is not an ontology
LinkType, because `ActionType` instances live in the catalog and are
cross-referenced by name, exactly as `remediates` resolves a Rule to an
`ActionType`. The workflow loader enforces that linkage at load; the ontology
LinkTypes cover only the runtime graph edges between first-class object types.

## 4. Control-loop integration

A compiled workflow does not run in a side channel. The
[`WorkflowCompiler`](../../src/fdai/core/workflow/compiler.py) turns a
`Workflow` into a [`Runbook`](../../src/fdai/core/runbook/models.py), and the
existing [`RunbookRunner`](../../src/fdai/core/runbook/runner.py) walks the
steps. Each step is dispatched through the injected `StepExecutor`, which
re-enters the typed pipeline: `ActionType` -> risk-gate -> executor -> audit.
There is no direct RPC between steps and no bypass of the risk-gate. This
matches the pantheon rule that any request to act re-enters the typed pipeline
([architecture.instructions.md](../../.github/instructions/architecture.instructions.md)).

Because every step is an `ActionType` invocation, the four safety invariants
hold per step: a stop-condition, a rollback contract, a blast-radius cap, and
an audit-log entry. The runner adds one aggregate `runbook.terminal` audit row
so a reviewer can reconstruct the whole run by id.

### 4.1 Shadow orchestrator (P1)

The [`WorkflowOrchestrator`](../../src/fdai/core/workflow/orchestrator.py) is the
first live consumer. It plans approvals ([section 6.1](#61-approver-assignment)),
derives an idempotent `Process` id from `(workflow, target_resource_id,
trigger_ts)`, compiles the workflow, and walks it with the
[`ShadowWorkflowStepExecutor`](../../src/fdai/core/workflow/orchestrator.py) - a
`StepExecutor` that has no publisher, no direct-API executor, and no resource
lock, so it **structurally cannot mutate**. Each step is judged and logged (with
its resolved approver assignment) and reported `SUCCESS`; the run emits a
`workflow.process-plan` audit row, one `workflow.step` row per step, and the
runner's `runbook.terminal`. Promotion to a live executor that re-enters the
risk-gate -> executor -> delivery path is a separate, gated change; until then a
workflow run cannot change cloud state, matching the shadow-before-enforce
invariant.

The event entry is the
[`WorkflowTriggerCoordinator`](../../src/fdai/core/workflow/coordinator.py): an
Event that clears `event-ingest` is matched against the
[`WorkflowTriggerIndex`](../../src/fdai/core/workflow/trigger_index.py) on its
`event_type`, and every matched Workflow is run in shadow (name-ordered,
resource + timestamp taken from the Event). An event matching no Workflow starts
nothing.


## 5. Saga compensation

A multi-step process that fails partway MUST be able to undo the steps that
already applied. Each step MAY declare `compensated_by`, the `ActionType` that
reverses it. The compensation contract is:

- On a step failure, prior applied steps are compensated in reverse order by
  dispatching their `compensated_by` action through the same pipeline.
- Compensation actions are themselves `ActionType` invocations, so they carry
  their own rollback contract and audit entry - there is no unaudited undo.
- A step with no `compensated_by` and a non-reversible `ActionType` forces the
  workflow to route the failure to HIL rather than leaving partial state.

In P1 the runner executes the linear sequence plus the single `on_failure`
branch; the declared `compensated_by` mapping is validated at load and exposed
by the compiler but is dispatched by the process orchestrator that lands with
the risk-gate integration. This is the same declared-versus-live boundary the
action ontology uses ([action-ontology.md § 12.1](action-ontology.md)): a
declared-but-not-yet-dispatched field is inert by construction and cannot act.

## 6. Governance

- **Shadow-first.** Every workflow ships `default_mode: shadow`: it judges and
  logs each step without mutating. Promotion to enforce is an explicit,
  separately reviewed governance PR that measures the workflow's
  `promotion_gate` on the frozen scenario set.
- **HIL through Var, audit through Saga.** A step whose `ActionType` routes to
  HIL goes through the approver principal (Var); every terminal outcome is
  audited by Saga. Process automation adds no new approval or audit surface.
- **Human override applies.** An operator override on a rule that gates a step
  suppresses that step's execution on the override scope while the evaluator
  keeps recording what it would have done, feeding the discovery loop.
- **Fork customization by injection.** A fork adds its own workflows under its
  catalog root and registers them through the same loader seam; it never edits
  `core/`.

### 6.1 Approver assignment

A workflow step that routes to HIL needs a concrete answer to "who approves,
and how are they reached". Process automation does not add a new approval
surface; it bridges a workflow to the existing HIL machinery through the
[`WorkflowApprovalPlanner`](../../src/fdai/core/workflow/approval.py).

Given a `Workflow`, the planner produces a deterministic, read-only
`ApprovalPlan` - one `StepApproval` per step:

- **Is it a gate?** A step is an approval gate when its `ActionType`
  `ceiling_by_tier` has any `enforce_hil` tier, or its `prod_downgrade`
  collapses to `enforce_hil`. This is the same source of truth the risk-gate
  uses; the planner never invents a second rule.
- **Who approves?** The required human role is the highest `min_role` across the
  HIL tiers, resolved to its Entra security-group objectId via the RBAC
  [`GroupMapping`](../../src/fdai/core/rbac/resolver.py) (the `aw-approvers` or
  `aw-owners` group). No-self-approval is carried forward on every gated step.
- **How are they reached?** The A1 `hil_approval` route from the
  [notifications matrix](../../config/notifications-matrix.yaml) - Teams primary,
  Slack / email fallback. The concrete adapters implement the
  [`HilChannel`](../../src/fdai/shared/providers/hil_channel.py) seam:
  [`TeamsHilAdapter`](../../src/fdai/delivery/chatops/teams_adapter.py) and
  [`SlackHilAdapter`](../../src/fdai/delivery/chatops/slack_adapter.py) (Adaptive
  Card / Block Kit, HMAC-signed, fail-closed). Email is a send-only alert lane,
  not an A1 approval back-channel.

The plan is a design-time / shadow-time projection: it says who *would* approve
each step. Runtime assignment (the specific on-call OID, the parked action, the
pushed card, the resume on decision) stays with the existing
[`HilResumeCoordinator`](../../src/fdai/core/hil_resume/coordinator.py) and
[`OnCallResolver`](../../src/fdai/core/oncall/resolver.py); wiring the plan into
a live run is the process-orchestrator work still ahead (see [section 5](#5-saga-compensation)).

## 7. Loader and CI validation

[`load_workflow_catalog`](../../src/fdai/rule_catalog/schema/workflow.py) is
pure I/O plus validation, mirroring the `ActionType` and ObjectType loaders. It
fails closed: any issue in any file raises a single aggregated error carrying
every issue across every file. It cross-references each `action_type_ref` and
`compensated_by` against the `ActionType` catalog and each `guard_rule_ref`
against the rule catalog, and it enforces the upstream shadow-default policy.
The entry point loads the catalog at startup so a malformed workflow blocks
boot rather than surfacing at first dispatch.

## 8. Relationship to agent-workflows.md

[agent-workflows.md](agent-workflows.md) is the design reference: the eleven
workflows, their agents, their sequence diagrams, and their exit criteria. This
document is the implementation contract those workflows compile into. The two
stay in sync: a new workflow lands as a doc entry in agent-workflows.md and a
catalog YAML under [`rule-catalog/workflows/`](../../rule-catalog/workflows/),
in the same PR.

## 9. Anti-patterns

- **A workflow that declares a new mutation primitive.** Steps reference the
  existing `ActionType` catalog; a missing capability is an upstream
  `ActionType` PR, not an inline step body.
- **A step that bypasses the risk-gate.** Every step re-enters the typed
  pipeline. A step that calls an executor directly is a defect.
- **An always-on process orchestrator.** Processes are event-driven and
  scale-to-zero; a polling daemon contradicts the app shape
  ([app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md)).
- **A workflow that ships `enforce`.** Upstream workflows are shadow-first;
  enforce is a separate gated promotion.
- **Partial state on failure with no compensation.** A non-reversible step
  without `compensated_by` MUST route failure to HIL, never leave the target
  half-changed.
