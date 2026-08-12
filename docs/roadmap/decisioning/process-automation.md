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
| **ActionType** | one CSP-neutral mutation category with seven safeguards (stop, rollback, impact cap, dry-run, lock, idempotency, audit) | [`rule-catalog/action-types/`](../../../rule-catalog/action-types), [action-ontology.md](action-ontology.md) |
| **Workflow** | the *declaration* of a business process: an ordered list of steps, each referencing one `ActionType`, plus a trigger, a promotion gate, and a default mode | [`rule-catalog/workflows/`](../../../rule-catalog/workflows), schema below |
| **Process** | the *runtime instance and state* of a running workflow: which step is current, which resource it targets, which findings it advanced through | `Process` ObjectType (ontology) |
| **Runbook** | the *execution mechanism*: walk the step list, honor `on_failure`, write the aggregate audit row | [`services/core-control-plane/src/fdai/core/runbook/`](../../../services/core-control-plane/src/fdai/core/runbook) |

The separation matters: a `Workflow` declares *what* runs and *when*; a `Runbook` is the thin
executor a compiled `Workflow` produces; a `Process` is the audited state of one live run. Mutation
steps delegate to an `ActionType` and inherit its safety invariants. The read-only `evidence` step
instead uses `WorkflowEvidenceDispatcher`, has no action authority, and fails closed when browser
evidence is unavailable ([design](../interfaces/browser-evidence.md)).

## 2. Workflow catalog schema

A workflow is catalog-as-code under
[`rule-catalog/workflows/`](../../../rule-catalog/workflows), validated at load
against [`shared/contracts/workflow/schema.json`](../../../services/core-control-plane/src/fdai/shared/contracts/workflow/schema.json)
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
  [`load_action_type_catalog`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/action_type.py).
  A typo fails at load, not at first dispatch - the same cross-reference
  discipline the `remediates` link uses in
  [`rule.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/rule.py).
- `compensated_by`, when set, MUST also resolve to an `ActionType` name. It is
  the saga rollback action for that step (see [section 5](#5-saga-compensation)).
- `on_failure`, when set, MUST reference an existing step `id` in the same
  workflow that appears **later** in the step list (never itself or an earlier
  step), exactly like a [`Runbook`](../../../services/core-control-plane/src/fdai/core/runbook/models.py)
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
  Until conditional branching is implemented and tested, any workflow with non-null `on_failure`
  is ineligible for enforce promotion and must remain shadow. Shipped workflows leave it null and
  use `compensated_by`; authoring an idempotent fallback does not waive the promotion block.

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
| `id` | string | Idempotent process id derived from `(workflow_ref, target_resource_id, trigger_ts)`; retries reuse it. Uses 1-200 URL-safe letters, digits, `_`, `.`, `:`, or `-` so every stored Process is addressable through the Operator API. |
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

Runtime delivery has one catalog-root invariant across catalog-backed tools. When
the control loop is composed with an explicit `catalog_root`, it must pass
`catalog_root / "chaos-scenarios"` to both the chaos executor (all and promoted
entries) and the RCA symptom index. Execution eligibility, promotion state, and
diagnostic evidence therefore use the same deployed or test catalog instead of
silently falling back to the repository default. Composition without an
explicit override retains the default catalog.

Direct API delivery routes registered ActionTypes to dedicated adapters before using the
operations gateway fallback. Human-access actions bind their allowlisted Entra adapter only when
the workload identity, HTTP client, state store, and complete role-group mapping are configured;
they remain in observation mode until separately promoted. All other supported operations keep
the existing gateway path. A recording fake can't be combined with either live binding, and a
partial gateway or human-access configuration stops startup instead of selecting a weaker path.
`governance.promote-effect-model` uses this same router only when its durable evidence registry is
available; it still passes through the ordinary risk, Owner approval, Thor, rollback, and audit path.

## 5. Saga compensation

A multi-step process that fails partway MUST be able to undo the steps that
already applied. Each step MAY declare `compensated_by`, the `ActionType` that
reverses it. The compensation contract is:

- On a step failure, prior applied steps are compensated in reverse order by
  dispatching their `compensated_by` action through the same pipeline.
- Compensation actions are themselves `ActionType` invocations, so they carry
  their own rollback contract and audit entry - there is no unaudited undo.
- A step with no `compensated_by` and a non-reversible `ActionType` forces the
  workflow to stop forward dispatch, record the exact partial state, and route recovery to HIL.
  HIL does not make the partial state disappear.
- Failure, cancellation, or timeout after any applied step triggers reverse-dependency compensation
  before a normal terminal status. Parallel branches stop accepting new work and join their applied
  receipts before compensation order is computed.
- Missing, failed, or unscorable compensation ends with `status=failed` plus
  `recovery_incomplete=true`, cited applied/compensation receipts, and a durable automation hold on
  affected targets. Only reads and separately approved Vidar recovery may cross that hold. A
  verified full compensation may use `status=compensated`; no partial outcome becomes `succeeded`.

The process orchestrator now dispatches declared compensation through typed ingress. It writes a
compensation intent before dispatch, records the proposal reference separately, and resumes the
same Process after a crash. A proposal reference proves dispatch only. `WorkflowOutcomeVerifier`
must independently validate each action and compensation receipt before a forward step completes or
the Process becomes `compensated`. Missing, rejected, or malformed evidence remains waiting or
closes as `recovery_incomplete`; it never becomes success.

The upstream headless runtime and production Operator API bind
`StateStoreWorkflowOutcomeLedger` to the shared durable state store. The control loop records an
immutable receipt only for an enforce Action whose execution identity matches its
`ResponseOutcome`; a successful receipt additionally requires independently verified effect
evidence. The resolver reads that receipt by proposal reference, Process, and step, so resume does
not trust caller-supplied status or receipt context. Shadow, unknown, missing, mismatched, or
unscorable outcomes cannot advance the Process.

`StateStoreAutomationHoldLedger` now writes a target-digested hold before a
recovery-incomplete Process closes. The headless control loop reads that hold before every ordinary
Action and the RiskGate returns `deny`; a failed or malformed hold read also denies. Read paths do
not use this mutation gate. Only a `compensate_*` Action whose workflow lineage matches the Process
that owns the active hold may re-enter the ordinary safety and authorization pipeline, and the
RiskGate caps that recovery at human approval. Every compensation outcome still requires independent
effect evidence. After all receipts verify, the coordinator releases the matching hold with a
revision compare-and-set before it records `status=compensated`; a release conflict or persistence
failure closes as `recovery_incomplete`. Released holds can be reissued for a later Process, and an
older Process cannot release the newer hold.

`ChangeWindowWorkflowGuardEvaluator` resolves `gate_ref: change-window.active` with the exact
Process target and evaluation time. It delegates other refs to the existing guard evaluator, so
the architecture-review production gate remains unchanged. The shipped
`planned-vm-start-change` workflow demonstrates the complete reusable pattern: active window,
Owner quorum, `ops.start-vm`, independent outcome verification, change summary, and
`ops.deallocate-vm` compensation. It pins those ActionTypes by versioned workflow design; runtime
selection of an arbitrary mutation is intentionally unsupported.

The public workflow run route accepts context only for declared parameter substitution. It always
replaces `requester.principal` with the authenticated operator and rejects caller-supplied
`approval.*`, `action.*`, `compensation.*`, `decision.*`, `parallel.*`, `requester.*`, and
`wait.*` keys. Those namespaces are server-owned Process evidence. A public request cannot create
approval quorum, action success, recovery, or control-step progress.

Every new `process.created` event carries the minimal server-owned envelope needed to resume that
exact Process. It records the original trigger time and mode, `requester.principal`, and only the
context keys referenced by workflow parameter templates. Values used by an `x-fdai-redact`
argument are omitted and mark the envelope incomplete, which blocks resume rather than persisting a
secret. `POST /workflows/{process_id}/resume` accepts no request body. The route reloads the Process
snapshot and creation event, verifies the workflow name and version plus the derived Process id,
and then reuses the original target, correlation, trigger, mode, and safe context. A Contributor can
resume a shadow Process. An enforce Process still requires Owner and the current workflow enforce
allowlist. Missing, legacy, malformed, redacted, version-mismatched, or identity-mismatched evidence
returns a typed conflict and dispatches no step.

`POST /workflows/{process_id}/cancel` also accepts no request body and resolves the same durable
envelope. A Contributor can cancel a shadow Process; an enforce Process requires Owner. The
command records `process.cancellation-requested` only when the Process is `pending` or `waiting`.
A `running` Process returns `process_not_at_safe_boundary` because an in-flight dispatcher cannot
be assumed idle. A waiting action first reconciles its authoritative outcome. The executor blocks
every new step, and any verified applied steps enter the existing reverse compensation path. A
waiting approval closes its durable Var state and every HIL slot, so a late approval cannot revive
the cancelled Process. Cancellation with no applied step closes as `cancelled`; verified recovery
after an applied step closes as `compensated`.

Action dispatch and step journal identity include an explicit positive `attempt`, with `1` as the
compatibility default. `STEP_STARTED`, `ACTION_DISPATCHED`, branch, waiting, completion, failure,
terminal, and audit ids include that attempt, and `WorkflowActionDispatcher` uses it in the typed
proposal idempotency key. Two attempts therefore cannot collapse into one event or proposal.

`POST /workflows/{process_id}/retry` starts a new attempt from `failed`, or from `timed_out` only
when the terminal reason is `approval_timed_out`, and accepts no body. The terminal attempt must
have an allowlisted effect-free reason and no action dispatch, cancellation, or compensation
evidence. Approval evidence is admitted only for terminal `approval_rejected` or
`approval_timed_out`. A dispatcher exception is ambiguous even without a local dispatch event and
returns `retry_requires_recovery`. Shadow retry requires Contributor; enforce retry requires Owner
and the current enforce allowlist. The server-owned attempt limit defaults to 3 and cannot be
raised by the caller.

Workflow approval state and HIL slot identity bind Process, step, and attempt. Attempt 1 retains
the legacy key for existing durable records; later attempts use distinct keys. One rejection makes
the complete quorum attempt terminal and closes every sibling slot, so a late approval cannot race
the rejection. A bounded retry after `approval_rejected` or `approval_timed_out` creates only fresh
slots for the new attempt. The terminal workflow CAS remains authoritative if sibling park closure
is interrupted, so the queue hides stale or expired slots and the next provider read heals their
physical park state. Cancellation and timeout close the exact attempt, and rejection, cancellation,
and timeout cannot overwrite one another. The workflow provider owns timeout terminalization; the
generic HIL expiry worker skips workflow slots. Approval decisions are accepted only before the
durable deadline. If a late decision changes the revision first, the executor rereads that attempt
and retries timeout CAS, so quorum completed after the deadline never advances the Process. Quorum
completed before the deadline remains valid when Process reconciliation resumes later. Callback
and conversation approval surfaces compare normalized principals for no-self-approval. Approval
claim CAS retries scale with the immutable slot quorum rather than a fixed contention bound.

Workflow audit uses each ActionType's `x-fdai-redact` paths. Redacted fields render as
`[REDACTED]` and never enter the Process journal. Because the workflow runtime has no secret
custody provider, an enforce action whose resolved params include a redacted field fails before
typed dispatch. Secret-bearing workflow steps remain unavailable until a dedicated custody seam
can supply the value without persisting it in audit or replay state.

ChangeWindow evaluation follows the ontology vocabulary: `reviewed` and `active` are effective
statuses; `allow`, `maintenance`, and `emergency` permit the gate; `freeze` and `quiet` block it.
Malformed, out-of-range, or truncated evidence remains blocked.

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
[`WorkflowApprovalPlanner`](../../../services/core-control-plane/src/fdai/core/workflow/approval.py).

Given a `Workflow`, the planner produces a deterministic, read-only
`ApprovalPlan` - one `StepApproval` per step:

- **Is it a gate?** A step is an approval gate when its `ActionType`
  `ceiling_by_tier` has any `enforce_hil` tier, or its `prod_downgrade`
  collapses to `enforce_hil`. This is the same source of truth the risk-gate
  uses; the planner never invents a second rule.
- **Who approves?** The required human role is the highest `min_role` across the
  HIL tiers, resolved to its Entra security-group objectId via the RBAC
  [`GroupMapping`](../../../services/core-control-plane/src/fdai/core/rbac/resolver.py) (the `aw-approvers` or
  `aw-owners` group). No-self-approval is carried forward on every gated step.
- **How are they reached?** The A1 `hil_approval` route from the
  [notifications matrix](../../../config/notifications-matrix.yaml) - Teams primary,
  Slack / email fallback. The concrete adapters implement the
  [`HilChannel`](../../../services/core-control-plane/src/fdai/shared/providers/hil_channel.py) seam:
  [`TeamsHilAdapter`](../../../services/core-control-plane/src/fdai/delivery/chatops/teams_adapter.py) and
  [`SlackHilAdapter`](../../../services/core-control-plane/src/fdai/delivery/chatops/) (Adaptive
  Card / Block Kit, HMAC-signed, fail-closed). Email is a send-only alert lane,
  not an A1 approval back-channel.

An unavailable notification route lowers only workflows and incident paths that require that
route. The runtime reports the gap and keeps unrelated read, deny, queue, and shadow paths
available; it never treats a missing channel as delivered approval or a successful notification.

The plan supplies the role and channel assignment. In enforcement mode, the approval provider
parks one HIL slot per quorum member in the shared durable StateStore. A revision compare-and-set
records the exact Process, step, required role, normalized principal, decision, receipt, and time
with a Var audit entry before the receipt projection. Both the signed callback and `approve_hil`
recheck the required role and no-self-approval. One case-insensitive principal cannot claim two
slots. The Process can resume from the authoritative decision even when receipt projection is
interrupted. The headless runtime and production Operator API bind this provider; interactive local
enforcement also requires its durable database and Azure event transport. The specific on-call OID
and channel card remain integrations of
[`HilResumeCoordinator`](../../../services/core-control-plane/src/fdai/core/hil_resume/coordinator.py) and
[`OnCallResolver`](../../../services/core-control-plane/src/fdai/core/oncall/resolver.py); no second approval authority is added.

## 7. Loader and CI validation

[`load_workflow_catalog`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py) is
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

Three opt-in, Reader-gated Operator API routes back validation and browsing as pure
projections that write no state (see
[`workflow_authoring.py`](../../../services/operator-service/src/fdai_operator_service/)):

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
  [`load_workflow_from_mapping`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/workflow.py)
  the catalog loader uses (JSON Schema + the `Workflow` pydantic structural
  invariants + `ActionType` / rule cross-reference), and returns the aggregated
  issues plus a canonical YAML preview. It mutates nothing and creates no PR.

These routes are opt-in through
[`OperatorApiConfig.workflow_authoring`](../../../services/operator-service/src/fdai_operator_service/)
(a `WorkflowAuthoringConfig` carrying the loaded palette, built-in workflows,
rule ids, and schema registry); unset upstream so the console stays minimal,
wired in the local dev harness so the view renders out of the box.

The console keeps the privileged read-only invariant
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md)):
the palette and catalog are GETs through the GET-only `OperatorApiClient`, validation
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

An operational-planning Process also folds its append-only `planning.phase.recorded` child events
into a Planning Room inside the same detail route. The projection shows accountable agents,
candidate ActionTypes, expected ranges, constraint and simulation receipts, rejected reasons,
selection margin, and human-review status. It is rebuildable from the journal, adds no route, and
contains no approval or execution control.

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
