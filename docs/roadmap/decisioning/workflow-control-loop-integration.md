---
title: Workflow Control-Loop Integration
---

# Workflow Control-Loop Integration

> Focused owner document extracted from [process-automation.md](process-automation.md) section 4.

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

Every state-changing action step is an `ActionType` invocation, so its seven safeguards hold.
Evidence and control steps have no mutation authority and use their dedicated typed contracts. The
runner adds one aggregate `runbook.terminal` audit row for reconstruction.

### 4.1 Governed shadow and enforce orchestrator

The [`WorkflowOrchestrator`](../../../src/fdai/core/workflow/orchestrator.py) plans
approvals ([section 6.1](#61-approver-assignment)),
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
the same contract for tests and local development. An explicit enforce run uses
`WorkflowActionDispatcher`: each action step republishes an idempotent
`operator_request` to typed ingress and still passes ActionType promotion, risk,
HIL, and Thor execution. The Process records `action.dispatched`, then waits until an injected
`WorkflowOutcomeVerifier` validates an authoritative effect receipt. Command context alone cannot
claim success. A failed later step starts reverse compensation for journaled, independently
verified applied steps. Compensation intent is committed before typed dispatch, and only verified
compensation receipts close the Process as `compensated`. A missing dispatcher, verifier, receipt,
or failed guard holds or fails the Process closed. Control-only workflows such as ARB persist real approval and decision
transitions without gaining resource mutation authority.

The event entry is the
[`WorkflowTriggerCoordinator`](../../../src/fdai/core/workflow/coordinator.py): an
Event that clears `event-ingest` is matched against the
[`WorkflowTriggerIndex`](../../../src/fdai/core/workflow/trigger_index.py) on its
`event_type`, and every matched Workflow is run in shadow (name-ordered,
resource + timestamp taken from the Event). An event matching no Workflow starts
nothing.

The coordinator is wired into the [`ControlLoop`](../../../src/fdai/core/control_loop/orchestrator.py)
as an **enabled-by-default, fail-safe side-consumer**: when the catalog ships a Workflow,
the entry point assembles it (from the loaded
Workflow catalog, the RBAC group mapping, and the notification matrix) and every
ingested event also fires its matched Workflows. It adds audit rows only - it
never changes routing, the risk decision, or the return path, and a coordinator
failure is logged and swallowed. `FDAI_WORKFLOW_SHADOW=0|false|no|off` is the explicit
maintenance disable; unset keeps non-mutating observation active.

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
is met. Wait and approval timeouts with no applied step end as `timed_out`; after any applied step
they stop forward dispatch and enter compensation. Parallel branches run concurrently and write
child events without competing for the parent snapshot revision, but a failure freezes new branch
dispatch and joins applied receipts before reverse-dependency compensation.

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

### 4.4 Manual shadow or enforce command

You can start a catalog Workflow without waiting for its production signal by
calling the optional Contributor-gated `POST /workflows/run` command. The route
accepts a catalog workflow name, target resource id, RFC 3339 trigger timestamp,
bounded parameter-substitution context, and `mode`. Contributor can run shadow.
Enforce requires Owner and a deployment `FDAI_WORKFLOW_ENFORCE_ALLOWLIST` entry.
Action steps republish to the normal typed pipeline; the workflow never calls an
executor directly.

The local dev composition wires the command and the Processes read routes to
the same `ProcessRuntimeStore`. Use the CLI wrapper to exercise it:

```bash
FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1 uv run uvicorn \
  'fdai.delivery.operator_api.dev.local:app' --factory --port 8000

uv run python scripts/automation/run-workflow.py architecture-review \
  --target fdai-control-plane

uv run python scripts/automation/run-workflow.py \
  --resume-process-id <process-id-from-start-response>
```

The response includes the Process id and links to its snapshot, journal, and
console route. `POST /workflows/{process_id}/resume` and the CLI
`--resume-process-id` mode send no body. The server reloads the original target,
trigger, mode, correlation, and audit-safe parameter context from the Process
journal, then repeats current role and enforce-allowlist checks. Production
compositions opt in by injecting `WorkflowExecutionConfig`; leaving it unset
registers neither command route. The SPA does not call these endpoints. CLI and
ChatOps are the command channels, and the console remains a read-only status
surface.

### 4.5 Governed Python tasks and cron schedules

A Workflow can reference `tool.run-python-on-vm` to run a generated Python
artifact on an ontology-selected compute Resource. `PythonTask` stores the
immutable manifest and content hash. `VmTaskRun` stores one plan or execution
receipt. The `executes_task` and `runs_on` links make the artifact and target
traversable without placing source code in the Process journal or event bus.

The authoring path separates six operations:

1. `POST /python-tasks/generate` asks the injected `PythonTaskAuthor` for an
  editable JSON source bundle grounded in the selected target capabilities and
  allowlisted modules. The returned draft is statically validated and never
  auto-staged.
2. `POST /python-tasks/validate` parses and compiles the AST without executing
  it. It rejects traversal, embedded secret markers, dynamic `eval` / `exec`,
  undeclared external modules, undeclared host capabilities, and an inline
  artifact larger than 64 KiB. Larger bundles require a future
  managed-identity object-storage staging adapter rather than a larger Run
  Command body.
3. `POST /python-tasks/stage` immutably stores a valid content-addressed
  artifact. Rewriting the same `task_id@version` with different content is
  blocked.
4. `POST /python-tasks/test` resolves the target from active inventory and
  returns a shadow plan. The Operator API binds `PlanningVmTaskRunner`, which has
  no executor identity and cannot copy files or run code.
5. `POST /python-tasks/request-run` publishes only the artifact reference,
  target Resource reference, and reason as an `ActionProposal`. The ordinary
  control loop normalizes the proposal into a canonical Event, validates its
  trigger and arguments against the referenced ActionType, loads trusted
  target properties from active inventory, and applies the unified risk gate.
  The Owner HIL ceiling and `ToolCallShadowExecutor` govern live work.
6. `POST /python-tasks/schedule` binds a staged artifact, inventory target,
   catalog Workflow, and strict cron expression into the persistent scheduler.
   It records a future typed event; it does not contact the VM.

The headless core binds `VmPythonToolExecutor` when
`FDAI_VM_TASK_ENABLED=1`. Shadow dispatch calls the runner with `dry_run=true`.
Enforce dispatch additionally requires `FDAI_VM_TASK_ENFORCE=1`; the Azure
adapter resolves the provider ARM reference from active inventory, creates a
Managed Run Command resource through the executor Managed Identity, stages
base64-encoded files, and rechecks every SHA-256 digest on every invocation,
including a cached artifact. It then verifies GPU and required modules and runs
the entrypoint as the pre-created `fdai-task` user.
The Run Command invokes a root-owned launcher that creates a transient systemd
unit: source is read-only, output is confined to the per-run directory,
network/process/device access follows declared capabilities, privilege
escalation is disabled, and host credential paths are inaccessible. It never
installs packages. Deleting the Run Command resource cancels an in-flight run;
the content-addressed artifact remains an immutable cache. A status polling
failure or local coroutine cancellation also attempts to delete the remote Run
Command before reporting the terminal result.
The reusable [`vm-task-host`](../../../infra/modules/vm-task-host) Terraform
module produces the VM cloud-init profile. The separate
[`vm-task-rbac`](../../../infra/modules/vm-task-rbac) module grants only VM read
plus Managed Run Command read/write/delete at the target VM scope. Neither
creates or starts a VM; a downstream composition passes the host profile into
an approved GPU VM image that already contains Python, drivers, CUDA, and
approved modules, then binds RBAC after the VM exists.
The host module's `inventory_tags` output sets `fdai:vm-task-ready=true` and
the declared `fdai:capabilities` list. The target resolver refuses an active
inventory VM without that explicit opt-in and cross-checks GPU capability from
the VM SKU (`NC`, `ND`, or `NV` family).

Schedule-triggered Workflows use strict five-field cron expressions. The
scheduler stores the cron alongside interval tasks, emits at most once per
matching minute, and stores the catalog Workflow reference alongside the task.
For a single-action scheduled Workflow, `scheduled_task_from_workflow()` also
materializes a typed `action_proposal`. At due time the scheduler publishes it
as the same raw `operator_request` used by an immediate request. `EventIngest`
normalizes both forms, and `ActionBuilder` preserves only arguments allowed by
the ActionType schema. The control loop loads the target environment from
active inventory rather than trusting the proposal, parks the complete Action
and policy context for Owner approval, and dispatches an approved request
through the declared tool executor. The optional Pantheon runtime observes the
same topic in shadow; it is not a second execution authority. The binding
supplies one target and artifact without embedding either environment value in
the upstream YAML.

Scheduled tasks declare one of four kinds: `interval`, `one-shot`, `cron`, or `event-exit`.
One-shot tasks fire once at or after `start_at`. Cron tasks evaluate a strict five-field expression
in a validated IANA timezone while retaining a UTC occurrence id. Event-exit tasks repeat on their
interval until `SchedulerService.observe_event()` receives the configured normalized event type,
then the durable store records the exit time and disables the task. Kind-qualified deterministic
occurrence ids prevent retry, restart, and cross-kind duplicate publication.

Every task also carries a durable `ScheduledRunIsolationProfile`. The default profile denies all
ambient tools and bounds session duration and context size. An opt-in profile must name every
allowed tool, cap total tool calls, and may reference a server-owned command sandbox profile.
`ScheduledRunIsolationGuard` rechecks context, elapsed time, tool id, and prior call count at the
downstream execution boundary. Every synthetic event and action proposal carries this immutable
profile; a scheduled run never inherits the creating operator's broader session, credentials,
workspace, or tool authority.

Every due publication is recorded in the durable `schedule_dispatch_run` ledger before the
event bus call. An atomic claim keyed by the schedule idempotency key moves through
`claimed -> published|failed`. A `published` row is written before `scheduled_task.last_run` is
advanced, so a process failure between broker publication and task-state update does not publish
the same event again. `failed` rows can be reclaimed for retry. The scheduler job reconciles a
`claimed` row older than its configured lease to `lost`, and `lost` rows can also be reclaimed.
The attempt counter and task-scoped history survive process restarts in PostgreSQL.

`published` means only that the synthetic event reached the event bus. It does not claim that the
downstream control loop or requested action succeeded. Those later outcomes remain in the normal
event, process, action, and audit records.

`ScheduleRunHistoryService` projects the ledger as a read-only task-scoped history. It orders
attempts newest first, supports status filtering and bounded limits, and uses an opaque cursor
derived from `(scheduled_for, run_id)` so page boundaries remain stable as newer runs arrive. The
projection exposes status, attempt, timestamps, and error kind only. It has no retry, cancel, or
execute method. The reader-role `GET /scheduler-runs` panel accepts `task_id`, optional status,
bounded limit, and opaque cursor parameters. Production composes it with the PostgreSQL ledger;
the console's `/processes/scheduler-runs` nested view preserves task and status filters in the URL
and renders cursor-paginated evidence without action buttons or executor identity. The response
also carries `source` and `durable`: production reports `postgres` and `true`, while the local
in-memory harness reports `synthetic-dev` and `false`. The console renders these fields instead of
inferring durability from the route name or static copy; [Reviewable Automation Blueprints](automation-blueprints.md) owns repeated-work suggestions.

The local Operator API uses the same authoritative ControlLoop with in-memory task,
inventory, audit, and HIL adapters. A Workflow Builder run request therefore
reaches the Owner approval gate and emits route, gate, and terminal audit frames
to `/live/stream`; the dev harness never auto-approves the parked action.

### 4.6 Governed command and shell artifacts

Generated Python tasks no longer receive the `process` capability. Static
validation rejects it even when the source does not appear to spawn a child.
This fail-closed default prevents generated Python from invoking an arbitrary
binary from the task host `PATH` before a typed command broker is available.

The command foundation separates intent, resolution, and execution:

- **Typed catalog**: `CommandCatalog` accepts a registered `command_id`, typed
  request arguments, and server-owned trusted values. It produces a frozen
  `CommandPlan`; the request cannot select an executable, raw argv, environment,
  credential profile, network profile, working directory, subscription, or
  project.
- **Runner seam**: `CommandRunner` receives only a resolved plan. The upstream
  default remains `RecordingCommandRunner`, which keeps dry-run as a real no-op.
  The opt-in `BubblewrapCommandRunner` executes `local_read` plans only: it
  resolves an opaque ref beneath a private workspace root, mounts that workspace
  and configured runtimes read-only, unshares the network, drops capabilities,
  exposes only a private tmpfs, starts a new process group, and enforces timeout
  and stdout/stderr byte caps. It rejects workspace-write, cloud, and credentialed
  plans before process creation.
- **Sandbox profile gate**: `SandboxProfileCatalog` gives each command id exactly one server-owned
  isolation profile. Unprofiled commands are denied. A profile fixes its backend, allowed
  execution classes and network profiles, workspace access, credential policy, timeout, and
  output ceiling. `ProfiledCommandRunner` validates the final `CommandPlan` immediately before the
  concrete runner and lowers requested limits to the profile ceilings. Bubblewrap profiles are
  structurally read-only, offline, and credential-free; a profile that attempts to widen those
  properties is rejected at registration.
- **Cross-adapter sandbox adoption**: VM tasks, external tools, and binary document converters use
  the same default-deny pattern at their concrete adapter boundaries. `ProfiledVmTaskRunner`
  limits task capabilities, input count and bytes, and timeout; profiles never allow the `process`
  capability. `McpServerCatalog.build_routes(...)` requires a `ToolSandboxCatalog` for every
  enabled ActionType, and `ProfiledToolExecutor` rechecks mode, argument count and bytes, and tool
  reference size before invocation. Binary knowledge ingestion accepts only an injected
  `DocumentConverter` paired with a `DocumentConverterSandboxCatalog`; the profile owns converter
  ids, suffixes, and input/output byte ceilings, while the request exposes relative provenance and
  content bytes rather than a host path or executable. Missing or violated profiles fail closed.
- **Shell artifact**: `ShellTaskSpec` stores a content-addressed, credential-free
  Bash bundle. Structural validation permits local constructs such as loops,
  pipes, and heredocs, while refusing cloud CLIs, privilege-escalation tools,
  protected host paths, metadata endpoints, embedded secret markers, `eval`,
  `exec`, `source`, xtrace, and any non-offline network profile.
- **No-exec syntax check**: `BashSyntaxChecker` invokes a pinned absolute Bash
  path with `--noprofile --norc -n` and source on stdin. Its minimal environment,
  timeout, and stderr cap make syntax checking bounded; `-n` parses commands but
  does not execute them. ShellCheck remains required before a future live runner.
- **Private workspace patch**: `CodePatchSet` targets only a content-addressed
  `workspace_ref` and carries the base revision, one operation per repository-
  relative path, the expected before hash, and the after-content hash. Validation
  blocks traversal, duplicate operations, runtime/generated files, binary text,
  and oversized changes. No upstream provider applies a patch to the active
  runtime checkout. `GitCodeWorkspaceProvider` clones a committed revision with
  no hardlinks, removes its origin, preserves source-checkout WIP, and materializes
  each validated patch as a new copy-on-write workspace. Stale hashes, symlink
  traversal, and protected paths are rechecked at the apply boundary.

The upstream command catalog initially exposes only `local.git.status`, scoped
`local.git.diff`, targeted `local.python.pytest`, targeted `local.python.ruff`,
and the Azure read operation `azure.resource.list`. Local commands require a
private workspace reference. The Azure command gets its subscription and
credential profile from trusted composition values, not from model arguments.
No cloud mutation, raw REST, recursive object-store operation, or arbitrary
command entry exists in this catalog. The opt-in `AzureCliCommandRunner` supports
that one read command. It creates a private `AZURE_CONFIG_DIR` per invocation,
logs in with a configured user-assigned Managed Identity, disables dynamic
extension installation, rechecks the active subscription, and validates the
exact argv shape before invoking Azure CLI. Dry-run performs no login. The
adapter is available for composition but is not bound by the upstream app.

These contracts reuse the existing execution paths. Local checks and read-only
result artifacts attach through `tool_call`; cloud substrate mutations remain
`direct_api`; fixed operating procedures remain `run_runbook`. A generic
`shell_exec` path and model-authored privileged `bash -c` command are not
supported. Shell artifacts themselves still do not execute: `BashSyntaxChecker`
only parses, while `BubblewrapCommandRunner` runs catalog-resolved argv. A future
shell-artifact compiler must add ShellCheck, convert every external operation to
a command id, and produce audit receipts before a complete script can run.
