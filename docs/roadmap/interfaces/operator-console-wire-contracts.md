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

### 13.3 Operator API approval callback (Week 1)

Two Operator-owned receivers resolve in one decision service. Neither trusts message identity or
authority:

| Transport | Route | Authentication and actor |
|-----------|-------|--------------------------|
| Teams Bot activity | `POST /hil/teams-activity` | Verify the Bot Framework RS256 service token, issuer, audience, `serviceurl`, tenant, configured group-connected team/channel, and `invoke` plus `adaptiveCard/action`. Derive `approval_id` from the exact card contract and the actor from `from.aadObjectId`, then verify the delegated OBO token for the Operator API audience and authorized bot client. |
| Internal Slack relay | `POST /hil/{approval_id}/decision` | Verify HMAC over timestamp, URL approval id, and exact bytes inside the replay window. Resolve the mapped Slack user through a delegated Operator bearer. This route refuses `channel=teams`. |

The Teams card carries only `approval_id`, `correlation_id`, `idempotency_key`, `action_hash`,
channel audience, decision, and required justification. The receiver rejects any extra card key,
so card data cannot provide `provider_actor_id`, roles, or an approver id. Both receivers revalidate
those bindings against the durable park, current approval capability, expiry, workflow role floor,
and no-self-approval rule. BreakGlass grants no HIL approval capability.

Each transport-authenticated attempt writes sanitized `prepared` and `completed` audit phases.
Unauthenticated traffic is rejected before durable storage. Exact retries preserve the first phase
timestamps. Accepted and rejected decisions are durable before broker publication,
marked delivered only after broker acceptance, and redriven by a lease-fenced outbox worker after
failure or restart.

Core routes `fdai.hil.decisions` by the parked `decision_route`. A `workflow` record occupies one
workflow-registry quorum slot, which enforces distinct approvers and requester separation. Only an
`action` record enters `HilResumeCoordinator`, so workflow approval cannot reach an executor.

This is a documented write-route exception to the Operator API's GET-only
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
  "idempotency_key": str?}`. Registered only when `OperatorApiConfig.console_action`
  wires a `ConsoleActionSubmitter`
  (`services/operator-service/src/fdai_operator_service/`). This raw-prompt route
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
[`python_tasks.py`](../../../services/operator-service/src/fdai_operator_service/).
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
- **Test shadow plan** uses `PlanningVmTaskRunner`; the Operator API has no Managed
  Identity capable of creating a Run Command.
- **Request governed run** publishes a typed `ActionProposal`. It doesn't call
  `VmTaskRunner`, copy a file, or execute Python from the console process.
- **Create schedule** stores a strict cron binding for the selected catalog
  Workflow, artifact, and inventory target. A later scheduler tick publishes
  the typed event.

The Operator API keeps background, busy-input, and skill runtime composition helpers under `routes/`; the result panel shows validation issues, artifact reference, planned file and
byte counts, target capabilities, or the submitted correlation id. Runtime
status continues on the Processes and audit surfaces after the control loop
accepts the proposal.

### 13.8 Grounded code in chat replies

When a terminal Command Deck answer contains a fenced code block, the Operator API
extracts it as a bounded `GroundedCodeArtifact`. The artifact carries the code,
language, SHA-256 reference, and a static validation result. Python blocks are
parsed and compiled without importing or executing them. Other languages are
marked `not_checked` rather than presented as validated. A fenced `chart` block is presentation
data rendered by the rich-answer chart component, so it is excluded from `GroundedCodeArtifact`
extraction and doesn't appear a second time under **Code evidence**.

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
  Operator API. It does not import the generated module, start a subprocess, create
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

`GET /ontology/graph` is the read-only, exact-release registry projection for the web console's
Semantic model, Objects, Relationships, Actions, and Catalog topology views. The response carries
one schema version, projection revision, and ontology release digest. It never includes runtime
instances, grants mutation authority, or substitutes catalog declarations for observed evidence.

Storage questions use a deterministic catalog contract rather than treating the requested path as
a missing screen field. Built-in ObjectType and LinkType definitions come from
`rule-catalog/vocabulary/object-types/` and `rule-catalog/vocabulary/link-types/`; ActionType
definitions come from `rule-catalog/action-types/`. A downstream composition can inject additional
validated roots. A deterministic producer loads the combined definitions, builds the exact
ontology release, and materializes one immutable Operator projection. Runtime ontology instances
are stored separately in PostgreSQL `ontology_resource` and `ontology_link`. ObjectType and
LinkType metadata can also be synchronized to PostgreSQL as validated references for foreign-key
checks, but those rows aren't the authoring source or source of truth for the definitions. The SPA
stores no separate catalog copy. JSON and SSE chat return the same contract answer without calling
the narrator.

- **Semantic model**: the default map places ObjectTypes in the reviewed Operating scope,
  Operating intent, Operating reality, and Decision and learning bands. Object, Relationship,
  State, Context, and Action are orthogonal lenses, not graph communities or additional
  declaration kinds. The layout is deterministic and relationship direction is always visible.
- **Objects**: ObjectTypes and LinkType edges render as one selected,
  deterministic one-hop neighborhood. The inspector shows recorded properties
  plus incoming and outgoing relationships.
- **Relationships**: selecting a LinkType shows every recorded `from_type -> to_type`
  endpoint pair, cardinality, and the causal, transitive, and temporal flags.
  The console doesn't infer relationship semantics absent from the catalog.
- **Actions**: the response includes the loaded ActionType catalog as complete
  safety-contract records. The catalog view exposes category, trigger,
  execution path, rollback contract, default mode, preconditions, stop
  conditions, impact-scope declaration, tier ceilings, and promotion gate.
- **Catalog topology**: the full reference topology combines ObjectTypes, InterfaceTypes,
  FunctionTypes, ResourceTypes, active Rules, ActionTypes, Workflows, Pantheon Agents,
  SignalTypes, and Properties. Weighted communities support dependency exploration only; they
  never represent the semantic bands, evidence completeness, or authority. The topology and the
  declaration views come from the same materialized projection. On initial entry, nodes use one
  deterministic 900 ms spring-settle toward their stored coordinates. Pointer or keyboard input
  ends the effect immediately, reduced-motion preference skips it, and no simulation remains active
  after settling.

A **Context snapshot** is a separate, purpose-scoped runtime projection reached from an evidence,
incident, or query receipt. It pins the ontology release, query profile, cutoff, object and link
revisions, state lanes, source watermarks, completeness, conflicts, truncation, and evidence
references. The browser never merges a catalog topology with runtime inventory and never treats a
missing or incomplete relationship as false. A context snapshot remains read-only and carries
`mutation_authority: false`.

The ActionType projection is additive: `action_type_count` and `action_types`
may be zero or absent on an older deployment, while ObjectType and LinkType
exploration continues to work. ActionTypes stay out of the selected ObjectType one-hop graph, but
the Catalog topology includes them as catalog nodes with Rule, Workflow, and Agent links. All
registry and context views are read-only and issue no action or approval call.

The declaration workbench adds bounded reads without expanding the summary payload:

- `GET /ontology/declarations/{kind}/{name}` returns one role- and purpose-filtered
  ObjectType, LinkType, or ActionType detail on the active release.
- `GET /ontology/declarations/{kind}/{name}/dependents` returns only deterministic
  catalog-topology references, with an explicit result bound and truncation state.
- `GET /ontology/object-types/{name}/evidence-health` returns sanitized source,
  generation, cutoff, freshness, completeness, conflict, synthetic, and aggregate count state.
  A type with no bound runtime source returns unavailable and does not fabricate a zero count.
- `GET /ontology/releases/{candidate_digest}/diff` compares retained declaration references.
  Added declarations are compatible, removals are incompatible, and a changed declaration needs
  migration review because retained release manifests do not reconstruct historical field schemas.
- `GET /simulate/blast-radius` traverses only stored-direction links in the active inventory
  snapshot. The caller supplies one exact Resource id, a depth from 1 through 5, and declared
  LinkTypes. The response binds the ontology release, snapshot generation, cutoff, completeness,
  truncation reasons, and unverified edge status; it returns no provider properties and fixes both
  `execution_authority` and `mutation_authority` to `false`. The Operator database role receives
  SELECT-only access to the active snapshot pointer and snapshot tables.

### 13.10 Ontology workbench projection envelopes

All workbench reads are authenticated, deterministic, and release-bound. A release mismatch fails
closed before projection. The server applies role and purpose filtering before returning a detail;
the browser receives redaction counts and reasons, never hidden fields. These routes expose no raw
SQL, Cypher, model execution, catalog upload, approval, restore, migration, or managed-resource
execution operation.

| Projection | Required envelope and bounded payload |
|------------|---------------------------------------|
| Declaration detail | `schema_version`, `_revision`, `ontology_release_digest`, `declaration_kind`, `declaration_name`, `complete`, `incomplete_reasons`, `redaction`, `declaration`, `relationships`, `related_actions`, and `mutation_authority=false`. ObjectType properties retain `type`, `required`, `description`, `access_scope`, and `purpose_binding`. Relationship rows retain selected direction, cardinality, causal/temporal flags, description, and provenance. |
| Dependents | `schema_version`, `_revision`, exact release and declaration identity, `complete`, `truncated`, nullable `truncation_reason`, deterministic `dependents`, and `mutation_authority=false`. Each dependent carries `kind`, `name`, `relationship`, and `evidence_ref`; only Catalog topology edges may produce a row. |
| Evidence health | `schema_version`, `_revision`, `ontology_release_digest`, `object_type`, `availability`, nullable `unavailable_reason`, sanitized `source`, `freshness_state`, `complete`, `truncated`, nullable `synthetic`, conflicts, drop reasons, nullable visible counts, evidence refs, and both authority flags fixed to `false`. An unavailable source returns null counts, not zero. |
| Release diff | `schema_version`, exact base and candidate release digests, `added`, `changed`, `removed`, `compatibility_verdict`, `migration_required`, nullable `breaking_change`, `historical_schema_detail`, `unbound_historical_evidence`, deterministic `diff_digest`, and `mutation_authority=false`. Retained declaration refs support compatibility review, not field-level historical reconstruction. |
| Runtime impact | `schema_version`, exact ontology release, `source_generation`, `source_cutoff`, exact target, traversal depth and LinkTypes, reached nodes, traversed edges, affected count, completeness, depth/edge truncation reasons, and both authority flags fixed to `false`. Every edge carries visible `verification_status`; an optional map must match the same snapshot generation or cutoff. |

The common detail `_revision` and dependent `_revision` are SHA-256 digests over canonical
projection bytes. Release diff uses `diff_digest` for the compared pair. Runtime impact pins the
active inventory generation instead of using a catalog revision as runtime evidence. Context
snapshots remain separate, purpose-scoped, receipt-bound projections and are never reconstructed
from the current screen.

The Console exposes these reads at `/ontology/object-types/:name` and
`/ontology/releases/:digest`. LinkType and ActionType clean paths reuse their existing contract
inspectors. Related actions appear only when an ActionType carries an exact semantic ObjectType or
InterfaceType target. Legacy actions without that evidence lower completeness and are not inferred.
InterfaceType and FunctionType keep their registry identity and topology nodes until more than one
meaningful active declaration and an authoritative usage source justify dedicated P2 views.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Audit and read-only wire projections | implemented | Operator family manifests and projections; `services/operator-service/tests/test_operator_service_composition.py`; Console trace tests | Default GET/HEAD routes, bounded envelopes, and unavailable behavior have focused coverage. |
| Exact-release ontology registry and workbench | implemented | `ontology_declaration_projection.py`; `ontology_dependents_projection.py`; `ontology_evidence_health_projection.py`; `ontology_release_diff_projection.py`; Operator operations routes; `console/src/routes/ontology-object-type-detail.tsx`; focused Python and Console checks | Exact declaration detail, server-side redaction, bounded dependents, honest evidence health, retained-release comparison, clean routes, and no-authority rendering are implemented. The authenticated local Browser showed the `Decision` and `Resource` paths without overflow, raw resource ids, or execute controls, but no governed Browser artifact was retained. |
| Active-inventory runtime impact | implemented | `inventory_impact.py`; `PostgresFamilyStore` impact reads; `operator_inventory_active_read_20260819`; strict Console decoder and route tests | The read-only route traverses bounded stored-direction links from one exact Resource against the active snapshot and reports exact release, source cutoff, completeness, and truncation without provider properties or execution authority. |
| Receipt-bound runtime Context snapshot | in-progress | Secured ObjectSet and Context contracts in the ontology platform; existing Console unavailable state | The workbench does not merge catalog declarations with runtime instances. A principal-scoped Context receipt remains separate delivery work. |
| HIL callback contract | implemented | Operator IAM family routes; `services/operator-service/tests/test_operator_iam_family.py`; full-composition tests | Signature, replay window, role, no-self-approval, exact pending id, and idempotent decision behavior are implemented. |
| Python task workbench and grounded code | implemented | `services/core-control-plane/src/fdai/core/python_task/`; `services/core-control-plane/tests/core/python_task/`; Operator workflow family; Console Python task tests | Static validation, inert artifacts, capabilities, and no-chat-execution boundaries have focused coverage. |
| Semantic action draft and typed confirmation | in-progress | Operator conversation and workflow application paths | Bounded draft and proposal paths exist, but this owner document retains no governed request-to-audit confirmation receipt across every conflict and denial case. |
| CLI, Teams, and Slack wire parity | in-progress | `cli/`; channel adapters and tests | Shared presentation contracts exist. No current governed multi-channel parity receipt is retained here. |
| Governed cross-contract runtime evidence | in-progress | Operator and Console focused tests | Unit and integration checks prove mechanics, not one authenticated receipt spanning callback, proposal, code artifact, ontology, and durable audit surfaces. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. | `current change`; current Operator, Core Python task, CLI, channel, Console, and focused test evidence listed in the scope table. | Close semantic confirmation, channel parity, and governed cross-contract evidence. |
| 2026-08-14 | in-progress | Defined separate Semantic model, Catalog topology, and receipt-bound Context snapshot contracts instead of presenting one generated force graph as the operating ontology. | `current change`; paired Console contract documents and focused documentation gates. | Implement one exact-release producer and retain focused and authenticated Console evidence. |
| 2026-08-14 | in-progress | Added a bounded deterministic spring-settle when Catalog topology first appears without changing its stored layout. Interaction and reduced-motion requests end or skip the effect, and no persistent simulation runs. | `current change`; `ontology-knowledge-graph.geometry.ts`, `ontology-knowledge-graph.renderer.ts`, `use-ontology-knowledge-graph-controller.ts`; focused Console topology tests report 12 passed and Console typecheck passed. | Retain the separately governed authenticated Context snapshot evidence described below. |
| 2026-08-19 | implemented | Added the exact-release declaration workbench and kept declaration, runtime evidence, dependency, and release-history authority in separate bounded projections. Role and purpose filtering happens before the Operator response, unavailable evidence carries no zero count, and release comparison uses retained declaration refs without restore or migration authority. | [Issue #223](https://github.com/dotnetpower/fdai/issues/223); `current change`; focused Core delivery, materializer, Operator family, Console decoder/router/localization tests, Console typecheck and production build; authenticated local Browser checks at 1440 x 900, 993 x 641, and 390 x 844 found no document overflow or execute control. | Retain a governed Browser artifact and bind a principal-scoped Context snapshot. Dedicated InterfaceType and FunctionType views remain deferred until their P2 entry conditions are measured. |
| 2026-08-19 | implemented | Connected the impact-scope route to a bounded traversal over the active inventory snapshot and added the missing SELECT-only Operator grant for its singleton pointer. | [Issue #223](https://github.com/dotnetpower/fdai/issues/223); `current change`; focused Operator, migration, Console, type, and build checks; authenticated local Browser returned a complete depth-one result with exact release and cutoff, no authority, and no document overflow at 390 px. | Retain the result as a governed exact-source artifact with a secured principal-scoped Context receipt before treating the local observation as durable evidence. |
| 2026-08-19 | implemented | Made the bounded depth probe fail closed when its one-edge result is truncated. A leading cycle can no longer hide a later unreached Resource and incorrectly report the impact projection as complete. | [Issue #223](https://github.com/dotnetpower/fdai/issues/223); `current change`; the focused impact projection suite passed 7 cases, and Ruff, format, and mypy passed. | Continue the independent hardening rounds; an ambiguous depth probe remains explicitly incomplete rather than inferring absence. |
| 2026-08-19 | implemented | Hardened Operator database readiness to reject each individual mutation, truncate, reference, or trigger privilege on read-only inventory and conversation tables. A single accidentally granted write privilege can no longer satisfy the service readiness boundary. | [Issue #223](https://github.com/dotnetpower/fdai/issues/223); `current change`; focused readiness tests passed 2 cases, Ruff, format, and mypy passed, and the actual local `fdai_operator` role remained ready. | Continue the independent hardening rounds; deployed role changes remain migration-controlled. |
| 2026-08-19 | implemented | Separated missing active-inventory targets from missing ontology declarations at the HTTP boundary. Impact scope now returns a resource-appropriate, identifier-free `404` while declaration routes preserve their existing public message. | [Issue #223](https://github.com/dotnetpower/fdai/issues/223); `current change`; the focused operations route regression passed, and Ruff, format, and mypy passed. | Continue the independent hardening rounds; unavailable authoritative sources remain `503` and malformed requests remain `400`. |
| 2026-08-19 | implemented | Integrated the enhancement plan's exact declaration, dependent, evidence-health, release-diff, and active-inventory impact envelopes into this owner contract using the shipped field names. | [Issue #223](https://github.com/dotnetpower/fdai/issues/223); `current change`; paired documentation and route-contract gates. | Preserve these envelopes when adding retained evidence; don't widen the routes into authoring or execution surfaces. |

### Remaining work

- [ ] Retain an authenticated semantic action-draft receipt that proves schema bounds, exact source revision, no-self-approval, stale and idempotency conflicts, typed confirmation, audit correlation, and no direct execution.
- [x] Materialize one exact-release ontology registry and declaration workbench, prove declaration and topology parity from the same producer, and render the four semantic bands with five orthogonal lenses. Focused checks and the authenticated local Browser observation for [Issue #223](https://github.com/dotnetpower/fdai/issues/223) passed without mutation authority.
- [x] Connect Impact scope to one bounded active-inventory traversal with exact release and cutoff, explicit truncation, no provider properties, and no execution or mutation authority.
- [ ] Retain a governed Browser artifact for the ObjectType workbench and bind an authenticated, principal-scoped Context snapshot that exposes completeness without mutation authority.
- [ ] Retain Python task capability, static validation, grounded-code rendering, malformed artifact, and no-execution receipts across Operator API and Console.
- [ ] Run and retain CLI, Teams, Slack, and Web parity cases for terminal status, evidence references, truncation, cancellation, replay, and unavailable behavior.
- [ ] Retain one governed read-only ontology receipt that binds catalog digest, ObjectType, LinkType, ActionType, workbench detail, and generated map without presenting catalog data as runtime evidence.
