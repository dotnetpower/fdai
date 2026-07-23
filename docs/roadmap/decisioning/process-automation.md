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
twelve cross-agent workflows in prose and sequence diagrams, this one defines
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

The separation matters: a `Workflow` declares *what* runs and *when*; a `Runbook` is the thin
executor a compiled `Workflow` produces; a `Process` is the audited state of one live run. Mutation
steps delegate to an `ActionType` and inherit its safety invariants. The read-only `evidence` step
instead uses `WorkflowEvidenceDispatcher`, has no action authority, and fails closed when browser
evidence is unavailable ([design](../interfaces/browser-evidence.md)).

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

### 2.2 Definitions, ownership, and bindings

The catalog document and the operator's automation settings are separate
records:

- **`WorkflowDefinition`** is an immutable, content-hashed workflow document.
  It records `origin` (`upstream`, `tenant`, or `user`), `visibility`
  (`global`, `team`, or `private`), lifecycle, owner, provenance, the resolved
  ActionType versions, and an ActionType catalog digest.
- **`WorkflowBinding`** belongs to one authenticated principal and binds a
  visible definition to `deck_open`, `schedule`, or `signal`. Schedule bindings
  require a strict cron expression and IANA timezone; signal bindings require a
  signal type. Parameter values stay scalar and cannot define a new action.

The console groups definitions as **Built-in**, **Shared**, and **Mine**.
Built-in definitions originate in the upstream git catalog. Shared definitions
are tenant catalog artifacts that passed review. Mine contains private user
definitions; **My automations** lists the principal's bindings separately so a
new trigger or timezone reuses a definition instead of cloning its step graph.

Every action step still resolves through the ActionType catalog. A binding
cannot raise autonomy or add an unregistered action. Before a Process starts,
the compiler pins the workflow version, definition hash, resolved ActionType
versions, and catalog digest so replay does not depend on the current catalog.
Sharing or promoting a private definition remains a reviewed governance flow,
not an in-place visibility toggle.

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

Moved to a focused owner document: [workflow-control-loop-integration.md](workflow-control-loop-integration.md). It covers the governed shadow and enforce orchestrator, the guard evaluation seam, the runtime journal and ontology projection, the manual shadow or enforce command, governed Python tasks and cron schedules, and governed command and shell artifacts.

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
and uses a bounded authoring contract: it validates, previews, and visualizes;
an explicit save creates only a principal-owned private `draft`. Publishing,
binding, enabling, and execution remain separate reviewed paths.

Step editors and other authoring groups are structural panels, not data cards. They use editor or
section semantics because they have no drill-down destination; data cards remain reserved for
summaries that link to an owned detail or evidence view.

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
(`welcome -> need_action -> need_trigger -> confirm_plan -> offer_extra ->
confirm_safety -> confirm_name -> ready`) and, at each turn, returns one bot
message: a short explanation of what it now understands, the next question,
and clickable **option chips** whose values are echoed back to the engine.
Design properties:

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
- inferred actions and triggers never advance without an explicit
  `confirm_plan` turn. When more than three distinct actions match the bounded
  proposal, the confirmation discloses that additional actions were omitted;
- `confirm_safety` states the fail-closed behavior, shadow posture, and
  promotion thresholds. The operator can record an `anti_scope` boundary
  before naming the workflow;
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
- a **structural validation result** from `POST /workflows/validate` ("structurally
  valid, every step resolves..."), so the operator can test the design before
  taking it anywhere. This check doesn't execute, simulate, or predict the
  workflow;
- an explicit **Save private draft** action that calls
  `POST /workflows/definitions` with confirmation and creates a private
  `draft`. The saved definition isn't runnable and doesn't appear in
  Operations;
- a collapsible **Edit validated draft** surface for action steps. It supports
  ActionType replacement, insertion, removal, ordering, step ids, guard and
  recovery references, primitive parameters, trigger metadata, anti-scope,
  and promotion thresholds. Every edit invalidates the prior save result and
  reruns the same server structural validation after a short debounce;
- tab-scoped draft recovery in bounded `sessionStorage`. Defensive decoding
  drops malformed or oversized records instead of loading an untrusted draft;
- the git-native next step: copy the YAML into
  `rule-catalog/workflows/<name>.yaml` and open a remediation PR.

Additional-step suggestions remain bounded to actions matched from the stated
goal plus communication follow-ups. The builder doesn't fill suggestion rows
with unrelated mutations merely to represent every ActionType category.

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

Three opt-in, Reader-gated read API routes back validation and browsing as pure
projections that write no state (see
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

The console keeps the privileged read-only invariant
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)):
the palette and catalog are GETs through the GET-only `ReadApiClient`, validation
is pure, and saving writes only a principal-owned private authoring record. The
save route never receives the executor identity and cannot publish, bind, enable,
or run the definition. A valid draft also yields YAML the operator can propose at
`rule-catalog/workflows/<name>.yaml` through the git-native path. New catalog
entries remain locked to `shadow`; promotion to enforce stays the separate
governance PR of [section 6](#6-governance).

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
  `GET /views/process/{process_id}` expose the list and workflow-specific detail
  projections. `GET /views/process/{process_id}/events` returns the authoritative
  snapshot and append-only event journal for every Process, including workflows
  that don't register a ViewSpec.
- **Generic console renderer** supports the approved widget vocabulary only. It
  never turns arbitrary ontology properties into executable UI or action buttons.

The **Processes** route lists every run, summarizes active, completed, and failed
counts, and renders the selected Process timeline from oldest event to newest.
Operators can refresh the read projection after a CLI or ChatOps command advances
the Process. A workflow-specific ViewSpec, when available, appears below the
runtime journal. The screen exposes no start, approve, retry, or execute button.

The architecture map remains separate. It visualizes the actual infrastructure
topology returned by the inventory graph. Process views visualize workflow state
and domain projections. Neither surface is the source of truth for the other.

### 8.3 Workflow apps and menu exposure

A workflow that needs a reusable read surface registers a **WorkflowApp**
manifest separately from its Workflow and ViewSpec. The manifest controls
discovery only. It never adds execution logic, an action button, JavaScript, or
an arbitrary backend route.

The console exposes one stable **Workflow apps** entry in the Operations domain.
That hub lists the published manifests visible to the current principal. Each
app uses `/workflow-apps/{app_id}` and reuses the generic Process list, journal,
ViewSpec, ReportSpec, and widget renderer filtered by `workflow_ref`. A generated
workflow never becomes a new compiled `ConsolePanel` by itself, so runtime
catalog growth cannot change the frontend bundle or flood the Activity Bar.

The manifest lifecycle controls exposure:

- `draft` manifests remain visible only in authoring and never enter Operations.
- `shadow` manifests may provide a workflow-specific Process detail ViewSpec,
  but don't appear in the Workflow apps hub.
- `published` manifests appear in the hub after workflow, ViewSpec, and role
  cross-references validate.
- `retired` manifests leave navigation while existing audit and Process deep
  links remain readable.

`WorkflowApp` ids and routes are permanent machine references. The launchpad, catalog, detail,
automation, chat, and Python-task views localize labels through parity-checked route catalogs with
English fallback; workflow ids, serialized values, and validation results remain unchanged. The read
API returns only manifests authorized for the principal; browser hiding is not access control. New
interaction models or executable frontend code use build-time `EXTRA_PANELS`, an injected
`ReadPanel`, and a separate reviewed release, never conversation-generated remote code.

## 9. Relationship to agent-workflows.md

[agent-workflows.md](../agents/agent-workflows.md) is the design reference: the twelve
workflows, their agents, their sequence diagrams, and their exit criteria. This
document is the implementation contract those workflows compile into. The two
stay in sync: a new workflow lands as a doc entry in agent-workflows.md and a
catalog YAML under [`rule-catalog/workflows/`](../../../rule-catalog/workflows),
in the same PR.

## 10. Anti-patterns

- **A workflow that declares a new mutation primitive.** Steps reference the
  existing `ActionType` catalog; a missing capability is an upstream
  `ActionType` PR, not an inline step body.
- **A state-changing step that bypasses the risk-gate.** Every action step re-enters the typed
  pipeline. Evidence and control steps cannot call an executor.
- **An always-on process orchestrator.** Processes are event-driven and
  scale-to-zero; a polling daemon contradicts the app shape
  ([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)).
- **A workflow that ships `enforce`.** Upstream workflows are shadow-first;
  enforce is a separate gated promotion.
- **Partial state on failure with no compensation.** A non-reversible step
  without `compensated_by` MUST route failure to HIL, never leave the target
  half-changed.
