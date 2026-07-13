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
[agent-workflows.md](../agents/agent-workflows.md). Where that document describes the
eleven cross-agent workflows in prose and sequence diagrams, this one defines
the catalog schema, the ontology additions, and the runtime wiring that let a
workflow ship as catalog-as-code and run in shadow mode.

> **Scope.** Everything here is customer-agnostic
> ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
> A workflow references only the upstream `ActionType` catalog under
> [`rule-catalog/action-types/`](../../../rule-catalog/action-types); it never
> declares a new mutation primitive. A process that needs a new capability is
> a signal to open an upstream `ActionType` doc PR first.

## 1. Four distinct concepts

Process automation composes four concepts that MUST NOT be conflated. Each has
a single responsibility.

| Concept | Responsibility | Backing |
|---------|----------------|---------|
| **ActionType** | one CSP-neutral mutation category with its safety invariants (stop-condition, rollback contract, blast-radius cap, audit) | [`rule-catalog/action-types/`](../../../rule-catalog/action-types), [action-ontology.md](action-ontology.md) |
| **Workflow** | the *declaration* of a business process: an ordered list of steps, each referencing one `ActionType`, plus a trigger, a promotion gate, and a default mode | [`rule-catalog/workflows/`](../../../rule-catalog/workflows), schema below |
| **Process** | the *runtime instance and state* of a running workflow: which step is current, which resource it targets, which findings it advanced through | `Process` ObjectType (ontology) |
| **Runbook** | the *execution mechanism*: walk the step list, honor `on_failure`, write the aggregate audit row | [`src/fdai/core/runbook/`](../../../src/fdai/core/runbook) |

The separation matters: a `Workflow` declares *what* runs and *when*; a
`Runbook` is the thin executor a compiled `Workflow` produces; a `Process` is
the audited state of one live run. A step never carries its own mutation logic
- it delegates to an `ActionType`, so every step inherits the four safety
invariants for free.

## 2. Workflow catalog schema

A workflow is catalog-as-code under
[`rule-catalog/workflows/`](../../../rule-catalog/workflows), validated at load
against [`shared/contracts/workflow/schema.json`](../../../src/fdai/shared/contracts/workflow/schema.json)
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
    params:                                  # optional scalar args; strings may template
      reason: "drift on ${event.resource_ref}"
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
  [`load_action_type_catalog`](../../../src/fdai/rule_catalog/schema/action_type.py).
  A typo fails at load, not at first dispatch - the same cross-reference
  discipline the `remediates` link uses in
  [`rule.py`](../../../src/fdai/rule_catalog/schema/rule.py).
- `compensated_by`, when set, MUST also resolve to an `ActionType` name. It is
  the saga rollback action for that step (see [section 5](#5-saga-compensation)).
- `on_failure`, when set, MUST reference an existing step `id` in the same
  workflow that appears **later** in the step list (never itself or an earlier
  step), exactly like a [`Runbook`](../../../src/fdai/core/runbook/models.py)
  step. A backward fallback would make the runner re-run an already-applied
  step, so it is rejected at load.
- `guard_rule_ref`, when set, MUST resolve to a Rule id from the loaded rule
  catalog. The guard is the deterministic "when" for the step - a
  policy-as-code predicate, never model text.
- Upstream workflows MUST set `default_mode: shadow`. A workflow that ships
  `enforce` is a schema violation upstream; promotion to enforce is a separate,
  gated governance PR.
- `params`, when set, is a map of scalar (string / number / boolean) arguments
  for the step. A string value MAY carry `${event.resource_ref}` /
  `${event.trigger_ts}` / `${event.event_type}` tokens the orchestrator
  substitutes from the triggering event at run time; an unknown token is left
  verbatim so the unresolved reference is visible in the audit. The resolved
  params are recorded on the `workflow.step` audit row.

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

[`rule-catalog/vocabulary/object-types/Process.yaml`](../../../rule-catalog/vocabulary/object-types/Process.yaml)
declares the runtime state of one workflow run. It keys on `id` like every
shipped built-in.

| Property | Type | Meaning |
|----------|------|---------|
| `id` | string | Idempotent process id derived from `(workflow_ref, target_resource_id, trigger_ts)`; retries reuse it. Uses 1-200 URL-safe letters, digits, `_`, `.`, `:`, or `-` so every stored Process is addressable through the read API. |
| `workflow_ref` | string | The `Workflow` name this process instantiates. |
| `workflow_version` | string | The immutable Workflow version selected for this run. |
| `status` | string | `pending`, `running`, `waiting`, `compensating`, `compensated`, `succeeded`, `failed`, `cancelled`, or `timed_out`. |
| `current_step` | string | Step id currently in flight (empty when terminal). |
| `target_resource_id` | string | Primary Resource the process operates on. |
| `started_at` | datetime | RFC 3339 UTC start timestamp. |
| `updated_at` | datetime | RFC 3339 UTC timestamp of the latest committed transition. |
| `correlation_id` | string | Correlation id shared by the Process journal, audit rows, and projections. |
| `revision` | integer | Optimistic concurrency revision of the authoritative snapshot. |

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
[`WorkflowCompiler`](../../../src/fdai/core/workflow/compiler.py) turns a
`Workflow` into a [`Runbook`](../../../src/fdai/core/runbook/models.py), and the
existing [`RunbookRunner`](../../../src/fdai/core/runbook/runner.py) walks the
steps. Each step is dispatched through the injected `StepExecutor`, which
re-enters the typed pipeline: `ActionType` -> risk-gate -> executor -> audit.
There is no direct RPC between steps and no bypass of the risk-gate. This
matches the pantheon rule that any request to act re-enters the typed pipeline
([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).

Because every step is an `ActionType` invocation, the four safety invariants
hold per step: a stop-condition, a rollback contract, a blast-radius cap, and
an audit-log entry. The runner adds one aggregate `runbook.terminal` audit row
so a reviewer can reconstruct the whole run by id.

### 4.1 Shadow orchestrator (P1)

The [`WorkflowOrchestrator`](../../../src/fdai/core/workflow/orchestrator.py) is the
first live consumer. It plans approvals ([section 6.1](#61-approver-assignment)),
derives an idempotent `Process` id from `(workflow, target_resource_id,
trigger_ts)`, compiles the workflow, and walks it with the
[`ShadowWorkflowStepExecutor`](../../../src/fdai/core/workflow/orchestrator.py) - a
`StepExecutor` that has no publisher, no direct-API executor, and no resource
lock, so it **structurally cannot mutate**. Each step is judged and logged (with
its resolved approver assignment) and reported `SUCCESS`; the run emits a
`workflow.process-plan` audit row, one `workflow.step` row per step, and the
runner's `runbook.terminal`. The run also writes the dedicated
`ProcessRuntimeStore`: one current snapshot plus an append-only transition journal.
The PostgreSQL adapter updates the snapshot and appends its typed `ProcessEvent`
in one transaction with optimistic revision checking. In-memory storage implements
the same contract for tests and local development. Promotion to a live executor
that re-enters the risk-gate -> executor -> delivery path is a separate, gated
change; until then a workflow run cannot change cloud state, matching the
shadow-before-enforce invariant.

The event entry is the
[`WorkflowTriggerCoordinator`](../../../src/fdai/core/workflow/coordinator.py): an
Event that clears `event-ingest` is matched against the
[`WorkflowTriggerIndex`](../../../src/fdai/core/workflow/trigger_index.py) on its
`event_type`, and every matched Workflow is run in shadow (name-ordered,
resource + timestamp taken from the Event). An event matching no Workflow starts
nothing.

The coordinator is wired into the [`ControlLoop`](../../../src/fdai/core/control_loop/orchestrator.py)
as an **opt-in, fail-safe side-consumer**: when `FDAI_WORKFLOW_SHADOW` is truthy
and the catalog ships a Workflow, the entry point assembles it (from the loaded
Workflow catalog, the RBAC group mapping, and the notification matrix) and every
ingested event also fires its matched Workflows. It adds audit rows only - it
never changes routing, the risk decision, or the return path, and a coordinator
failure is logged and swallowed. Upstream default is off, so the control loop
behaves exactly as before unless a deployment opts in.

### 4.2 Guard evaluation (seam)

A step's `guard_rule_ref` is the deterministic "when" for the step - a
policy-as-code predicate, never model text. The orchestrator exposes a
[`WorkflowGuardEvaluator`](../../../src/fdai/core/workflow/orchestrator.py) seam
(async, deterministic, side-effect free). The upstream default injects **no**
evaluator: a guard is load-validated against the rule catalog but recorded as
`guard_evaluated: false` at run time, so upstream stays behaviourally neutral. A
fork (or the future enforce path) binds a concrete OPA-backed evaluator through
this seam. When an evaluator is bound and a step's guard returns false, the
shadow run records `guard_passed: false` and treats the step as a judged no-op
(reason `guard_blocked_shadow_noop`) - the run continues, nothing mutates. Every
`workflow.step` audit row carries `guard_rule_ref` / `guard_evaluated` /
`guard_passed` so a reviewer sees exactly which guard gated which step.

### 4.3 Runtime journal and ontology projection

The runtime snapshot answers "where is this Process now?" The append-only journal
answers "how did it get here?" Typed events cover creation, step lifecycle,
wait/approval/decision state, parallel branch outcomes, compensation, timeout, and
terminal outcomes. Approval steps count distinct approving principals, exclude the
requester when `no_self_approval` is enabled, and remain waiting until their quorum
is met. Wait and approval timeouts end the Process as `timed_out`. Parallel branches
run concurrently and write child events without competing for the parent snapshot
revision.

The ontology graph is a read model, not the source of truth. After each committed
event, `ProcessOntologyProjector` materializes the current `Process` object and its
`targets` link. A workflow-specific projector can add domain objects and links. The
architecture-review projector, for example, materializes its review case, checks,
evidence, principals, approvals, and decisions from the same snapshot and event.

Projection delivery uses a durable retry outbox:

- The PostgreSQL runtime adapter inserts the `process_event` and its
  `process_projection_outbox` job in the same transaction.
- The immediate projector is best effort. A projection failure is logged with the
  Process correlation id but never changes or hides the committed runtime result.
- `ProcessProjectionWorker.run_once()` leases a bounded batch with
  `FOR UPDATE SKIP LOCKED`, retries idempotent projections, and releases failures
  after a configured delay. A successful new projection also drains one due batch.
- The worker is a one-shot event/job primitive, not an always-on polling daemon. A
  Container Apps Job or startup hook can call `retry_pending()` to recover backlog.

This separation lets runtime processing continue if the ontology store is briefly
unavailable while preserving every projection intent for recovery.


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
[`WorkflowApprovalPlanner`](../../../src/fdai/core/workflow/approval.py).

Given a `Workflow`, the planner produces a deterministic, read-only
`ApprovalPlan` - one `StepApproval` per step:

- **Is it a gate?** A step is an approval gate when its `ActionType`
  `ceiling_by_tier` has any `enforce_hil` tier, or its `prod_downgrade`
  collapses to `enforce_hil`. This is the same source of truth the risk-gate
  uses; the planner never invents a second rule.
- **Who approves?** The required human role is the highest `min_role` across the
  HIL tiers, resolved to its Entra security-group objectId via the RBAC
  [`GroupMapping`](../../../src/fdai/core/rbac/resolver.py) (the `aw-approvers` or
  `aw-owners` group). No-self-approval is carried forward on every gated step.
- **How are they reached?** The A1 `hil_approval` route from the
  [notifications matrix](../../../config/notifications-matrix.yaml) - Teams primary,
  Slack / email fallback. The concrete adapters implement the
  [`HilChannel`](../../../src/fdai/shared/providers/hil_channel.py) seam:
  [`TeamsHilAdapter`](../../../src/fdai/delivery/chatops/teams_adapter.py) and
  [`SlackHilAdapter`](../../../src/fdai/delivery/chatops/slack_adapter.py) (Adaptive
  Card / Block Kit, HMAC-signed, fail-closed). Email is a send-only alert lane,
  not an A1 approval back-channel.

The plan supplies the role and channel assignment. At runtime, an approval step
parks the Process, records `approval.requested`, validates distinct principals and
no-self-approval, and resumes only after its declared quorum. A decision step accepts
only one of its catalog-declared outcomes and records `decision.recorded`. The
specific on-call OID and pushed channel card remain integrations of
[`HilResumeCoordinator`](../../../src/fdai/core/hil_resume/coordinator.py) and
[`OnCallResolver`](../../../src/fdai/core/oncall/resolver.py); the workflow runtime
does not create a second approval authority.

## 7. Loader and CI validation

[`load_workflow_catalog`](../../../src/fdai/rule_catalog/schema/workflow.py) is
pure I/O plus validation, mirroring the `ActionType` and ObjectType loaders. It
fails closed: any issue in any file raises a single aggregated error carrying
every issue across every file. It cross-references each `action_type_ref` and
`compensated_by` against the `ActionType` catalog and each `guard_rule_ref`
against the rule catalog, and it enforces the upstream shadow-default policy.
The entry point loads the catalog at startup so a malformed workflow blocks
boot rather than surfacing at first dispatch.

## 8. Authoring surface (console workflow-builder)

An operator authors a custom business process through the console's
**workflow-builder** view, not by hand-writing YAML from memory and not by
filling a multi-section form. The surface maps the process onto the ontology
and is **read-only by construction**: it validates, previews, and visualizes,
but it never commits.

The view has two modes. The default is a **launchpad plus a read-only list of
the built-in workflows**: a `read-only browse table` lists every shipped
process with its trigger, step count, and mode, and a per-row detail panel
(property table, steps table, anti-scope, and the raw catalog YAML) lets an
operator study a working example first. A single **"Design a new workflow"**
entry opens the conversational designer.

### 8.1 Conversational designer

The designer is a **chat that co-designs the workflow with the operator**, not
a form. It asks deep, plain-language questions, restates what it understood,
and offers option chips the way an assistant proposes next actions - so a
non-expert reaches a valid workflow by answering questions, never by learning
the schema. It is backed by a **deterministic, LLM-free interview engine**
([`workflow-builder.chat.ts`](../../../console/src/routes/workflow-builder.chat.ts)),
a slot-filling state machine that stays true to the deterministic-first
contract: it works with the narrator absent and never invents a mutation the
`ActionType` palette does not already carry.

The engine walks a fixed set of stages
(`welcome -> need_action -> need_trigger -> offer_extra -> confirm_name ->
ready`) and, at each turn, returns one bot message: a short explanation of what
it now understands, the next question, and clickable **option chips** whose
values are echoed back to the engine. Design properties:

- the welcome turn shows **worked examples** (e.g. "when a pod on
  `aks-cluster-01` runs hot, notify me"), so the operator sees what kinds of
  processes are expressible before typing;
- a single free-text goal is pre-parsed by the same deterministic matcher the
  legacy composer used
  ([`suggestDraftFromText`](../../../console/src/routes/workflow-builder.intent.ts)):
  when the sentence already names a trigger and an action, the interview skips
  straight to confirming the rest, only asking for what is still missing;
- after each answer the engine **restates its understanding** as one plain
  "when -> do" sentence, and at `offer_extra` it proposes further steps
  (another action, a guard, a notification) as chips the operator accepts or
  declines;
- the workflow name is **auto-suggested** from the goal (a snake_case id) and
  confirmed in one turn, so the operator never has to invent an identifier.

At the `ready` stage the UI
([`workflow-builder.chatpanel.tsx`](../../../console/src/routes/workflow-builder.chatpanel.tsx))
runs the existing validate + preview path on the accumulated draft and renders,
inline in the chat:

- an **inline flow-map visualization** (`when -> do -> ... -> done`) that draws
  the workflow as the node chain the operator will recognize from
  [`mocks/ui/workflow-builder.html`](../../../mocks/ui/workflow-builder.html),
  so the chat shows how the process will actually run;
- the **canonical YAML** as a copyable code block, presented as "here is the
  workflow I generated";
- a **dry-run test result** from `POST /workflows/validate` ("structurally
  valid, every step resolves..."), so the operator can test the design before
  taking it anywhere;
- the git-native next step: copy the YAML into
  `rule-catalog/workflows/<name>.yaml` and open a remediation PR.

The engine's pure, stateless pieces are split into sibling modules so each has
one axis of change and is unit-testable without a DOM: the chip / form-slot
builders and the option-token grammar
([`workflow-builder.chat.builders.ts`](../../../console/src/routes/workflow-builder.chat.builders.ts)),
the inline-markdown tokenizer
([`workflow-builder.richtext.ts`](../../../console/src/routes/workflow-builder.richtext.ts)),
and the flow-map derivation
([`workflow-builder.viz.ts`](../../../console/src/routes/workflow-builder.viz.ts)).
The operator's own typed text is echoed as plain text (never through the
markdown parser), and only the newest turn's chips stay interactive so a stale
suggestion cannot corrupt a later stage.

The same three opt-in, Reader-gated read API routes back it, all pure
projections that
write no state (see
[`workflow_authoring.py`](../../../src/fdai/delivery/read_api/routes/workflow_authoring.py)):

- **`GET /workflows/catalog`** - the built-in Workflow catalog. A read-only
  projection of the loaded `Workflow` catalog carrying each workflow's full
  content (trigger, steps, promotion gate, `step_count`, and the canonical
  YAML) so the console can list and inspect shipped processes before an
  operator drafts a new one.
- **`GET /workflows/action-types`** - the `ActionType` palette. A projection of
  the loaded `ActionType` catalog (name, category, `rollback_contract`,
  `irreversible`, `default_mode`, and the tiers whose ceiling escalates to HIL)
  so the builder offers a typed dropdown per step. Picking from the palette is
  what makes a step's `action_type_ref` resolvable at load time - the builder
  cannot invent an unknown reference.
- **`POST /workflows/validate`** - a pure function that runs the same
  [`load_workflow_from_mapping`](../../../src/fdai/rule_catalog/schema/workflow.py)
  the catalog loader uses (JSON Schema + the `Workflow` pydantic structural
  invariants + `ActionType` / rule cross-reference), and returns the aggregated
  issues plus a canonical YAML preview. It mutates nothing and creates no PR.

These routes are opt-in through
[`ReadApiConfig.workflow_authoring`](../../../src/fdai/delivery/read_api/main.py)
(a `WorkflowAuthoringConfig` carrying the loaded palette, built-in workflows,
rule ids, and schema registry); unset upstream so the console stays minimal,
wired in the local dev harness so the view renders out of the box.

The console keeps the read-only invariant
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)):
the palette and catalog are GETs through the GET-only `ReadApiClient`, and the
validate call is the single non-GET the console makes - a read-only validator
that lives outside `ReadApiClient` (mirroring the chat backend) and changes no
state. There
is no console button that commits. A valid draft yields YAML the operator copies
into `rule-catalog/workflows/<name>.yaml` and lands as a remediation PR through
the git-native path, so audit, review, and rollback come for free. New drafts
are locked to `shadow`; promotion to enforce stays the separate governance PR of
[section 6](#6-governance).

### 8.2 Dynamic runtime view

The **Processes** console route renders running and completed workflow instances
without embedding architecture-review logic in the frontend. The projection path is:

```text
Workflow -> Process snapshot + journal -> ontology projection
         -> ontology datasource -> ReportSpec -> ViewSpec
         -> RenderedView API -> generic console widgets
```

Each artifact has one responsibility:

- **Workflow** declares execution and control flow. It does not contain UI layout.
- **Process snapshot and journal** are the authoritative mutable state and history.
- **Ontology projection** gives the runtime state typed domain meaning and links.
- **ReportSpec** selects bounded datasets and widget data from the projection.
- **ViewSpec** maps a workflow reference to report regions and column spans. It is
  catalog-as-code under [`rule-catalog/views/`](../../../rule-catalog/views/).
- **ViewEngine** resolves the Process, matching ViewSpec, and reports into a bounded
  `RenderedView`. Reader-gated `GET /views/process` and
  `GET /views/process/{process_id}` expose the list and detail projections.
- **Generic console renderer** supports the approved widget vocabulary only. It
  never turns arbitrary ontology properties into executable UI or action buttons.

The architecture map remains separate. It visualizes the actual infrastructure
topology returned by the inventory graph. Process views visualize workflow state
and domain projections. Neither surface is the source of truth for the other.

## 9. Relationship to agent-workflows.md

[agent-workflows.md](../agents/agent-workflows.md) is the design reference: the eleven
workflows, their agents, their sequence diagrams, and their exit criteria. This
document is the implementation contract those workflows compile into. The two
stay in sync: a new workflow lands as a doc entry in agent-workflows.md and a
catalog YAML under [`rule-catalog/workflows/`](../../../rule-catalog/workflows),
in the same PR.

## 10. Anti-patterns

- **A workflow that declares a new mutation primitive.** Steps reference the
  existing `ActionType` catalog; a missing capability is an upstream
  `ActionType` PR, not an inline step body.
- **A step that bypasses the risk-gate.** Every step re-enters the typed
  pipeline. A step that calls an executor directly is a defect.
- **An always-on process orchestrator.** Processes are event-driven and
  scale-to-zero; a polling daemon contradicts the app shape
  ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
- **A workflow that ships `enforce`.** Upstream workflows are shadow-first;
  enforce is a separate gated promotion.
- **Partial state on failure with no compensation.** A non-reversible step
  without `compensated_by` MUST route failure to HIL, never leave the target
  half-changed.
