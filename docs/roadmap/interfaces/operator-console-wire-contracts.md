---
title: Operator Console - Data and Wire Contracts
---

# Operator Console - Data and Wire Contracts

> Focused owner document extracted from [operator-console.md](operator-console.md) section 13 (13.1-13.3, 13.6-13.9).

## 13. Data + wire contracts

### 13.1 Audit entry - `console.turn` action_kind

```json
{
  "action_kind": "console.turn",
  "session_id": "...",
  "turn_id": "...",
  "principal": {"kind": "user|cli|bot", "id": "...", "role": "Reader|..."},
  "channel": "cli|teams|slack|web",
  "direction": "inbound|outbound|tool_call|tool_result",
  "tier": "T0|T1|T2",
  "escalation_trigger": "...",
  "tool_name": "...",
  "arguments": {...},
  "result_preview": "...",
  "evidence_refs": ["..."],
  "verifier_verdict": "pass|abstain|deny|n/a",
  "model_deployment_id": "...",
  "prompt_tokens": 0,
  "completion_tokens": 0,
  "started_at": "...",
  "finished_at": "..."
}
```

### 13.2 CLI REPL wire contract

- stdin: one operator utterance per line.
- stdout: JSON-Lines when `--json` flag is set; formatted text otherwise.
- stderr: coordinator log lines (structured; separate stream so the
  formatted view stays clean).
- Exit code: `0` on clean session end; `2` on invalid config; `3` on
  unrecoverable channel error.

### 13.3 Read-API approval callback (Week 1)

- `POST /hil/{approval_id}/decision`
- Body: `{"decision": "approve|reject|defer", "justification": "..."}`
- Headers: `X-FDAI-Signature: sha256=<hex>`,
  `X-FDAI-Timestamp: <RFC3339>`.
- Signature material: `HMAC-SHA256(secret, timestamp . approval_id . body)`
  where the three parts are joined by a literal `.` separator. Binding
  the URL path `approval_id` into the digest blocks a captured valid
  message from being replayed against a different pending item (URL
  swap). The bot MUST include the same `approval_id` it puts in the URL.
- Response: `200 {"queued": true, "audit_entry_id": "..."}`.

This is a documented write-route exception to the read API's GET-only
projection surface. The invariant test allow-lists this callback explicitly.
This does **not**
break the "console never executes" rule from
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md):
the endpoint only *records an approval decision* into the existing HIL
queue (a signal), which a separate executor principal later acts on. The
API process never holds the executor Managed Identity and never calls a
mutation surface itself; approval and execution stay distinct principals.
### 13.6 Semantic action draft and typed confirmation

All natural-language turns use `POST /chat` or `POST /chat/stream`. The configured
mini narrator returns a strict JSON-schema `TurnPlan` that selects an answer,
read tool, agent owner, public-web query, clarification, or write draft from the
server-provided capability manifest. The browser does not classify action intent
and does not send natural language directly to a write endpoint.

- **Draft**: An `action_draft` or `incident_draft` returns the allowlisted
  `action_type`, bounded typed arguments, conversation `session_id`, and a
  request-scoped idempotency key. Producing the draft publishes no event and
  creates no Incident. The browser shows Confirm and Cancel controls.
- **Typed confirmation**: `POST /chat/action/confirm` accepts only
  `{"action_type": str, "arguments": object, "session_id": str?,
  "idempotency_key": str}`. The server rechecks the ActionType allowlist,
  argument bounds, authenticated principal, and RBAC before publishing one
  proposal. Unknown fields and unlisted actions are rejected.
- **Compatibility endpoint**: `POST /chat/action`, body
  `{"prompt": str, "session_id": str?,
  "idempotency_key": str?}`. Registered only when `ReadApiConfig.console_action`
  wires a `ConsoleActionSubmitter`
  (`src/fdai/delivery/read_api/routes/console_action.py`). This raw-prompt route
  remains for compatible API clients; the browser Command Deck does not use it.
  Operator-supplied values are bounded (prompt <= 4000,
  question <= 2000, resource id / session id / idempotency key <= 200 chars) so
  one large value cannot bloat the pipeline or audit. The client `idempotency_key`
  becomes the proposal's dedup key (namespaced by the initiator, so one operator
  cannot reuse another's key to suppress their action), so a retried or
  duplicated submit collapses at Huginn instead of enqueuing a second action;
  Thor is additionally idempotent per correlation so an at-least-once
  re-delivery never double-executes.
- **Server-derived RBAC**. The operator's role comes from the validated bearer
  token (`Principal.roles`), never client JSON. Submitting requires the
  `author-draft-pr` capability (Contributor and above); a Reader is refused with
  `403 {"submitted": false, "reason": "rbac_capability"}` before anything
  publishes. Forseti re-checks the initiator principal downstream (deny +
  `SecurityEvent`) - defense in depth.
- **Both entry gates agree on the capability, not a role rank**. The
  conversational entry gate (`Bragi.submit_action_proposal`) maps the session's
  Entra role to the SAME canonical capability matrix (`fdai.core.rbac.roles`)
  and also requires `author-draft-pr`, so the HTTP and conversational surfaces
  never diverge. In particular `BreakGlass` is hard-isolated (not a superset of
  Owner) and does not carry `author-draft-pr`, so it cannot submit a normal
  action from either surface.
- **Refusals are observable**. Every pre-pipeline refusal (`invalid_principal` /
  `rbac_capability` / `deny_override_forbidden`) is logged and offered to an
  optional injected `RefusalObserver` (`ConsoleActionSubmitter.refusal_observer`)
  so repeated refusals for one actor - a privilege-probing signal Forseti never
  sees because the request never enters the pipeline - become detectable (audit
  / metric / security event). Absent the seam, only a structured log line is
  emitted.
- **Legacy translation**. The compatibility endpoint uses
  `fdai.agents.bragi.translate_action_intent`, which first matches an
  exact ActionType id or one unambiguous full suffix from the loaded ActionType
  catalog (for example, `flush cache` -> `ops.flush-cache`), then uses the
  conservative built-in verb fallback. Ambiguous and unmapped commands return
  `200 {"submitted": false, "reason": "unmapped_action_intent"}` instead of
  guessing. The function remains the single source of truth shared with the
  pantheon-internal path.
- **Deny-override block (Scenario B)**. When a `prior_outcome_lookup` seam is
  wired, the submitter checks the pipeline's last terminal conclusion for this
  exact `(initiator, resource, action_type)` before publishing. A prior **deny**
  (judged unsafe) is authoritative: a repeat console ask cannot lift it, so the
  submitter refuses with `403 {"submitted": false,
  "reason": "deny_override_forbidden"}` and publishes nothing - only a governed
  rule / policy / override change can lift a deny, never a repeat request. A
  prior **no-op** (the action was unnecessary because the target was already
  satisfied) does **not** block a re-request: conditions drift, so the request
  re-enters the pipeline and is judged fresh. The rule lives in one pure
  function (`fdai.core.console_request.evaluate_operator_rerequest`). Absent the
  seam, every request is treated as fresh (no deny-override check).
- **Response** (submitted): `200 {"submitted": true, "correlation_id": ...,
  "action_type": ..., "resource_id": ...}`. The operator tracks progress by the
  `correlation_id` (Trace panel / audit); the pipeline result (auto shadow-exec,
  HIL wait, or deny) is asynchronous.
- **Investigation Incident**. An explicit `tool.run-investigation <kind> <resource>` command is
  itself confirmation to open or reuse a deterministic Incident for the session, target, and
  resource kind. The proposal uses the Incident ID as its correlation and carries `incident_id`
  in typed parameters. Ordinary questions and discovery work create no Incident.
- **Live stage turn**. After a successful submit, the web deck opens an authenticated,
  correlation-filtered `/live/stream` reader and updates one transcript turn through Huginn
  ingest, Forseti route/verify/gate, Thor execute, and Saga audit. Audit is terminal; timeout or
  stream failure leaves the durable Trace correlation as the recovery source.
- **This is the second documented write route** alongside the 13.3 approval
  callback; both record a signal and never hold the executor Managed Identity.

### 13.7 Python VM task workbench

The Workflow Builder includes a multi-file Python task workbench backed by the
six mutation routes and the read-only `GET /python-tasks/capabilities` route in
[`python_tasks.py`](../../../src/fdai/delivery/read_api/routes/python_tasks.py).
Operators can edit source files, choose an entrypoint, declare modules and host
capabilities, validate, stage an immutable artifact, and render a shadow plan
for an inventory Resource.

The capability response reports each optional operation separately. The console
doesn't open the workbench when the route is absent and disables any operation
whose adapter, submitter, or schedule store isn't wired, so an unavailable path
never appears as an executable control that fails with a generic `404`.

The workbench preserves the console identity boundary:

- **Validate** is pure AST and manifest validation.
- **Generate editable draft** calls the injected `PythonTaskAuthor` with the
  operator intent, target capabilities, and allowlisted modules. The draft must
  still validate and stage before any request control is enabled.
- **Stage artifact** writes the content-addressed artifact store, not a VM.
- **Test shadow plan** uses `PlanningVmTaskRunner`; the read API has no Managed
  Identity capable of creating a Run Command.
- **Request governed run** publishes a typed `ActionProposal`. It doesn't call
  `VmTaskRunner`, copy a file, or execute Python from the console process.
- **Create schedule** stores a strict cron binding for the selected catalog
  Workflow, artifact, and inventory target. A later scheduler tick publishes
  the typed event.

The read-API keeps background, busy-input, and skill runtime composition helpers under `routes/`; the result panel shows validation issues, artifact reference, planned file and
byte counts, target capabilities, or the submitted correlation id. Runtime
status continues on the Processes and audit surfaces after the control loop
accepts the proposal.

### 13.8 Grounded code in chat replies

When a terminal Command Deck answer contains a fenced code block, the read API
extracts it as a bounded `GroundedCodeArtifact`. The artifact carries the code,
language, SHA-256 reference, and a static validation result. Python blocks are
parsed and compiled without importing or executing them. Other languages are
marked `not_checked` rather than presented as validated.

The console keeps code collapsed under **Code evidence** by default. Expanding
the disclosure shows the exact grounded content, its artifact reference, and
whether syntax validation passed. The terminal artifact is derived from the
final verified answer, not from an incomplete streaming token sequence. A tab
may retain the artifact in `sessionStorage` with the transcript; defensive
parsing drops malformed or oversized persisted entries.

This display contract does not grant execution authority:

- **No runtime writes**: the chat route never writes generated code into the
  FDAI source tree, installed package, container filesystem, or active Git
  checkout.
- **No chat execution**: static parsing is the only operation performed in the
  read API. It does not import the generated module, start a subprocess, create
  a virtual environment, or call `VmTaskRunner`.
- **Governed execution stays separate**: an operator who wants to run code must
  create and stage a `PythonTask`, then publish a typed `ActionProposal` through
  the flow in section 13.7. The risk gate, approval ceiling, executor identity,
  and audit path remain authoritative.
- **Temporary storage is not the sandbox**: a runner may use a per-run directory
  such as `/tmp/fdai-code/<run-id>` for writable files, but isolation comes from
  a separate principal, a read-only runtime filesystem, path and symlink checks,
  resource limits, network policy, and cleanup. A path convention alone is not
  a security boundary.

### 13.9 Ontology registry projection

`GET /ontology/graph` is the read-only registry projection for the web
console's three ontology views:

The Ontology screen also exposes a fourth **Ontology map** view backed independently by
`GET /inventory/graph`. It is a runtime resource projection, not another copy of the declaration
catalog or the generic ontology-instance tables. This separation lets the registry views remain
available when runtime inventory is unavailable.

Storage questions use a deterministic catalog contract rather than treating the requested path as
a missing screen field. Built-in ObjectType and LinkType definitions come from
`rule-catalog/vocabulary/object-types/` and `rule-catalog/vocabulary/link-types/`; ActionType
definitions come from `rule-catalog/action-types/`. A downstream composition can inject additional
validated roots. At startup, the Read API loads the combined definitions into an immutable
in-memory catalog, and `/ontology/graph` provides its read-only projection. Runtime ontology
instances are stored in PostgreSQL `ontology_resource` and `ontology_link`. ObjectType and LinkType
metadata can also be synchronized to PostgreSQL as validated references for foreign-key checks,
but those rows aren't the authoring source or source of truth for the definitions. The SPA stores
no separate copy. JSON and SSE chat return the same contract answer without calling the narrator.

- **Objects**: ObjectTypes and LinkType edges render as one selected,
  deterministic one-hop neighborhood. The inspector shows recorded properties
  plus incoming and outgoing relationships.
- **Links**: selecting a LinkType shows every recorded `from_type -> to_type`
  endpoint pair, cardinality, and the causal, transitive, and temporal flags.
  The console doesn't infer relationship semantics absent from the catalog.
- **Actions**: the response includes the loaded ActionType catalog as complete
  safety-contract records. The catalog view exposes category, trigger,
  execution path, rollback contract, default mode, preconditions, stop
  conditions, blast-radius declaration, tier ceilings, and promotion gate.
- **Ontology map**: the console sends no inventory request until the operator provides a root
  resource id. It then requests only that bounded neighborhood with `depth=2`, `limit=200`, and
  `contains,attached_to,depends_on`. Selecting a neighbor can re-root the query; submitting the
  current root retries in place without adding a duplicate history entry. The view preserves source,
  freshness, snapshot time, and stable truncation reasons from the provider, and handles an unavailable
  inventory route without disabling the three registry views. Before browser serialization, the Read API
  rejects missing or invalid snapshot time, freshness, resource name, and resource status fields. Shared
  canvas, resource-selector, and layer labels follow the operator locale, including accessible names.

The ActionType projection is additive: `action_type_count` and `action_types`
may be zero or absent on an older deployment, while ObjectType and LinkType
exploration continues to work. ActionTypes stay out of the ObjectType graph so
a large action catalog doesn't obscure resource relationships. All four views
are GET-only and issue no action or approval call.
