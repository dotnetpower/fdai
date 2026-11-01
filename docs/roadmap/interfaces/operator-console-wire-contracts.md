---
title: Operator Console - Data and Wire Contracts
---

# Operator Console - Data and Wire Contracts

> Focused owner document extracted from [operator-console.md](operator-console.md) section 13 (13.1-13.3, 13.6-13.9).

Console-governed ownership candidates add no Operator wire contract yet. An Owner-only typed activation request remains open under #458. Until it lands, candidates stay inert and grant no ownership, RBAC, approval, or execution authority.

## 13. Data + wire contracts
The existing runtime-state projection can include process-owned first-tier-decision lag with its
source and unavailable state; this adds no Incident command, approval or execution authority.

Semantic request 1.11.0 adds the explicit no-authority `presentation_mode=agent_discussion`.
Semantic request 1.12.0 adds the optional no-authority `dialogue_state`: exact accounting of the prior turns beyond the verbatim window (turn ids and a range digest, no turn text). The Operator emits it only when `FDAI_SEMANTIC_DIALOGUE_STATE_ENABLED` is on, after every Core consumer accepts 1.12.0; a 1.11.0 consumer rejects it by schema. Core only compares it with its own accounting in a log-only observation.
The ordinary default stays absent from serialized requests. Operator requires Owner and retained
authentication receipts; Core independently admits the exact current installation read grant.
Discussion uses existing stream, cancellation, deadline and durable terminal projection fields,
never Incident creation or action drafts. Console renders the returned position, critique,
participant outcomes and held/verified conclusion without inferring operational truth from them.

`GET /operations/runtime-state` is an authenticated Reader-role projection over one durable Core
snapshot. It contains the exact 15 self-health signals and the version, configuration, rule-effect,
override, discovery, canary, kill-switch, and break-glass fields as source-qualified digests,
freshness, or explicit unavailable states. Operator validates and redacts the shared contract. It
does not query providers, infer healthy defaults, approve a change, or gain execution authority.
Core supplies actual listener liveness, guarded readiness, persisted kill switch, process startup
duration, consumed-canary age, deterministic-verifier and native comparison-round rates, plus installed-version,
consumed-policy and kill-switch digests. Exact coverage stays with the
[source owner](../operations/operating-and-verification.md#remaining-source-boundaries);
the aggregate adapter signal and missing sources remain unavailable. Verifier/comparison warmup, pending and unknown
results are data states in the unchanged contract, not approval decisions. Source failures retain bounded missing, malformed, or unreachable
reasons; the wire shape and Reader authorization are unchanged. Sharing `bootstrap_core.py`
with Incident composition does not create or confirm an Incident, publish an Incident request,
or change its lifecycle. A kill-switch digest does not expose its state revision or verify a
requested transition; the independent drill evidence below remains required. See the
[source contract](../operations/operating-and-verification.md#local-source-bindings).

Optional `model_provider_scope` and `model_provider_registration` response siblings expose typed
model sub-observations without changing the existing `snapshot` or its digest. Core writes them
atomically with the parent snapshot. The complete startup role set is independently pinned from
observations; missing roles, stale/replaced bindings, missing registration, or unfinished calls
cannot yield complete coverage or aggregate Healthy. Operator checks both typed contracts,
their exact configured-role/binding equality, parent digest/time, and catalog freshness. It
rejects a model sub-scope presented as proof of global adapter Healthy. Reader access is unchanged.
`runtime_model_scope_projection.py` owns this validation and the runtime-record decoding; the
reader facade retains its SQL, dispatch, and existing read-clock hook. Core's
`bootstrap_readiness.build_runtime_self_health_bindings` owns the coupled catalog/scope binding.
This module split changes no full-role obligation, response field, digest, aggregate, or time rule.

`GET /knowledge/github/sources` returns typed repository provenance and separate knowledge-read
and scan-permission state. Owner-only `POST` on the same path accepts `connect` or `disconnect`,
an alias and expected revision; `connect` also requires location and a credential reference.
It rejects credential bytes and scan-permission fields, requires `Idempotency-Key`, and reuses
`code_security.repository_change` without a new topic. HTTP `202` is durable intent, not source
verification. This [connection contract](../../runbooks/knowledge-github-sources.md) changes no
Incident creation, approval callback, semantic confirmation, or managed-resource write authority.

`GET /stewardship/candidates` returns the newest Console ownership revision candidates (id, digest,
title, body, YAML, state) from an Owner-only projection that Core writes. Core writes it when the enterprise-identity add-on is selected, even without governed execution; until the first write the route answers `503`. Owner-only
`POST /stewardship/candidates/activate` accepts exactly `candidate_id` and `candidate_digest`,
requires `Idempotency-Key`, and stores one inert `stewardship.candidate_activation` proposal without
a new topic. HTTP `202` is durable intent: Core rechecks the stored Owner role, reads the candidate
again, rejects a digest mismatch, and writes one `stewardship_activation:*` receipt, so redelivery
changes nothing. The request carries no YAML, role, or approval claim and grants no IAM,
deployment, or Azure authority.

The existing numeric `usage` map may include `model_calls` and a provider-reported `cached_tokens` beside token totals; `cached_tokens` appears only when a call measured it. This is
recorded conversation-call telemetry, not detailed prompt capture, action authority, or
independent operational evidence. Missing values remain unavailable; older consumers may
ignore the additive numeric key without changing answer verification or Incident handling.

Optional `technical_details.post_turn_procedure` contains a versioned, content-free completed-query
receipt. Operator binds it to the exact principal, turn, release, plan and execution result before
forwarding it through the existing consent-gated post-turn request. The optional receipt survives
Bragi's raw-text filtering; it grants no body-sharing, Incident, approval, execution or promotion
authority. Older consumers can ignore it. [Post-Turn Improvement Review](../decisioning/post-turn-improvement-review.md#recurrent-query-observations)
owns the recurrence and unavailable rules; answer fields and request versions are unchanged.

The [common answer presentation](operator-console.md#common-answer-presentation) reuses existing
answer text, verification, citation, and presentation-artifact fields. Source disclosure, the
verification posture line, and original Markdown inspection do not add wire fields, requests,
Incident confirmation, or execution authority; rejected content remains outside the
display-authorized answer.

Test-context choices are a dedicated authenticated read contract. They return reviewed scope and policy choices plus a source revision, and lifecycle writes still use the existing proposal, review, and revocation routes with `execution_authority=false`.

Core's supervised instance-index reconciliation is separate from Incident creation and transport. Enrollment comes only from authenticated Function invocation context, not model arguments or index records. Candidate preparation and exact-ID reads cannot create an Incident, approve a change, or alter the semantic wire's no-execution-authority contract. The dedicated terminal projection verifies principal, release, query, result digest, invocation evidence, and candidate accounting. It displays only identity/type/revision rows with bilingual non-exhaustive and no-authority notices; zero candidates never establish absence and raw properties stay excluded.
Recent Resource change continuations add only an Operator read route that forwards an opaque continuation reference; Operator does not decode the reference or read the continuation body, and Core remains responsible for reauthorization and typed `continuation_invalid` outcomes.
Core bootstrap keeps the assembled runtime data model and human-approval registry binding in focused modules. Incident consumers, supervised tasks, logical topics, durable acceptance, and the Operator/Core authority split remain unchanged.
Semantic result-handle references are additive no-authority fields on the semantic request and
projection contracts. Operator stores and replays only the opaque reference; Core remains the only
reader of encrypted handle bodies. Ordinal follow-ups over those references reauthorize rows in
Core before anchoring a read and do not change the Operator/Core authority split.

Observer setup uses a separate `observer-proposal-projection` schema and
`core.observer-deployment.projections` logical topic on the existing transport. Operator owns the
ordered local projection and authenticated GET route; its one-minute lease grants no approval or
Incident creation authority. The shared Kafka allowlist adds only this subscription and its
sanitized DLQ, never a proposal, approval or mutation publisher. See the
[observer delivery contract](../architecture/aks-outbound-connector.md#operator-delivery-contract).

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

#### Pantheon assurance attribution extension

A Pantheon assurance terminal adds `answer_generation` and
`pantheon_evaluator_models`. Answer generation records `agent_projection` with no model identity,
or `t2_model` with one nonempty model identity and family. The evaluator list contains at most
three distinct configured reviewer identities and families plus whether each produced a validated
output for that turn. Operator validates these fields before forwarding the terminal. Historical
records without attribution remain readable as `legacy_unattributed`; Operator never guesses a
model from a digest, deployment default, or current configuration.

The same terminal requires `pantheon_prompt_profiles`. `answer_participants` carries at most three
agent names, prompt versions, situation keys, and SYSTEM SHA-256 values. `evaluator_profiles`
carries at most three profile identities, versions, digests, SYSTEM SHA-256 values, and bounded
token budgets. Core and Operator reject malformed shapes; Console displays only these content-free
fields inside the expanded Run Record and never receives raw SYSTEM text through this extension.

A captured model call's `prompt_manifest` may also carry `assembly` when its profile is dynamic:
`mode` (`selected` or `complete`), sorted assembly `keys`, the ids of `unselected_layers`, and the
assembly `digest`. The object is content-free, parsers that do not display it ignore it, and it
never carries prompt text or authority. A selected-mode frame attempt discarded for a guidance
coverage gap remains in the trace before its complete-prompt retry.

The local campaign CLI may place this attribution with bounded question and answer content in an
owner-only transcript. That transcript is diagnostic data, not a cross-service contract,
qualification record, audit entry, or authority source.

### 13.3 Operator API approval callback (Week 1)

Operator-owned receivers resolve in one decision service. None trusts message identity or
authority:

Approval callbacks that resolve a single-operator production park read the pinned approval-profile
metadata from the stored approval context, not from a current environment value or a Core
implementation import. The shared approval-profile contract validates the revision shape and
digest, while Core remains responsible for choosing the active Mimir approval policy pointer and
for honoring the pinned revision during resume.

| Transport | Route | Authentication and actor |
|-----------|-------|--------------------------|
| Teams Bot activity | `POST /hil/teams-activity` | Verify the Bot Framework RS256 service token, issuer, audience, `serviceurl`, tenant, configured group-connected team/channel, and `invoke` plus `adaptiveCard/action`. Derive `approval_id` from the exact card contract and the actor from `from.aadObjectId`, then verify the delegated OBO token for the Operator API audience and authorized bot client. |
| Internal Slack relay | `POST /hil/{approval_id}/decision` | Verify HMAC over timestamp, URL approval id, and exact bytes inside the replay window. Resolve the mapped Slack user through a delegated Operator bearer. This route refuses `channel=teams`. |
| Slack browser handoff | `POST /hil/slack/interaction`; `GET/POST /hil/slack/handoff/{nonce}` | The outbound `fdai_hil_approve` and `fdai_hil_reject` buttons carry only the original approval id; dispatch identity is separate and digest-bound. Verify Slack v0 over exact form bytes and a five-minute timestamp window before extracting `team.id` and `user.id`. One click gets one nonce digest bound to original approval, action, workspace, user map revision, and expiry. The signed receiver returns a server-origin Console URL. The browser preview supplies no authority; POST accepts only an optional justification, requires a verified API access token with `auth_time` after the click and a current exact mapping, atomically consumes the nonce, and calls the same decision service. Missing claim, authority, context, or mapping holds the decision. Live Slack delivery and Entra optional-claim configuration remain external. |
| Console development self-approval | `POST /hil/{approval_id}/operator-decision` | The body is `decision` plus an optional `justification` of at most 2000 characters; an absent or blank reason is recorded as an empty string and never blocks an approve or reject. When the approver is the submitter of a park that Core marked with a development block, the route reads the verified API token claims and admits only the named Owner's approve decision with a signed `auth_time` later than the park and at most 10 minutes old. It records a token-free attestation in the durable receipt and the outbox payload; each HIL queue item tells the caller only `development_self_approval_available`, never the Owner identity. Only that Owner also receives `development_binding` (binding, target revision, dry-run, and scope digests), which the approval card shows before the decision. Every caller also receives `development_owner_only`; when it is true, the park is a category-only denial that this route, every Slack or Teams callback, and the decision transaction refuse to approve for anyone but that attested Owner, while any authorized approver, including that Owner, may still reject it. |

The Teams card carries only `approval_id`, `correlation_id`, `idempotency_key`, `action_hash`,
channel audience, decision, and justification, which may be empty. The receiver rejects any extra card key,
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
and does not send natural language directly to a write endpoint. A sole `resource_identity`
unresolved term with a typed subject or resource-identity requirement is rendered as a locale-specific request for the exact resource
name or ID; the internal token remains on the machine contract and is not shown as interface copy.
No clarification is fixed to one product or resource kind: a stated constraint the typed judgment
omits, including the operand of a stated relation that a frame drops, is repaired or held as
`semantic_constraint_uncovered`, never replaced by preset question text.
A read held on its reading keeps its typed `reason_code`, such as `semantic_constraint_uncovered`,
`semantic_plan_constraint_uncovered`, `semantic_reading_ambiguous`, `semantic_reading_unverified`, or
`semantic_stated_constraint_unsupported`, instead of `semantic_evidence_held` or
`semantic_request_unsupported`; a held one carries `unavailable_reason` `semantic_planner_unavailable`.
Its `answer` is a reviewed bilingual notice that names the closed constraint roles or atom categories
the planner recorded, never operator words, and the Console maps each code to a restate or unsupported
prompt. The `reason_code` stays a bounded lowercase code, so the wire schema is unchanged.
A compiled single-target health answer uses the same reviewed assessment rendering as the current
path, and its `answer` restates the assessment's fixed window through a reviewed bilingual notice;
the wire schema is unchanged. A compiled property lookup renders the one reviewed value of its bound
Resource, states a missing value as unknown, and its `answer` states the value's inventory source and
reviewed freshness bound through a reviewed bilingual notice; the wire schema is unchanged.
Concurrent semantic requests share one durable processing claim. A waiter retries the claim after
its lease expires, so a failed owner cannot strand the request until its outer deadline. A result
store failure while waiting returns an explicit held projection.
Schema-valid requests that policy rejects return an immediate no-authority held terminal. Optional
observation failure cannot block delivery, and outbox closure failure remains retryable. Only malformed
envelopes dead-letter; no held or retry state can create an Incident or confirm an action draft.
Core never truncates a terminal evidence manifest. When the deduplicated receipt references of an
answered or execution-held turn exceed 12, or one reference exceeds the 256-character manifest
bound, the turn holds as `semantic_evidence_incomplete` without retained goal receipts. The terminal
event therefore cites no evidence reference outside its manifest. The 256-character bound comes
from the Core `SemanticTurnResult` contract. It is stricter than the 512-character item bound for
`semantic_result.evidence_refs` in the published `core-operator-projection` JSON schemas 1.2.0
through 1.7.0, so Core holds a 257- to 512-character reference as `semantic_evidence_incomplete`
even though those schemas accept it. The Operator validates every received result with the same
shared `SemanticTurnResult` model, so it also refuses a 257-character reference. The published
schema bound tightens with the next `core-operator-projection` version.
The Operator verifies Core's commitments before durable projection. With the shared
`fdai_service_contracts.semantic_projection` functions, it recomputes `evidence_digest` over the
semantic result, or over the assessment, trace receipt, and Pantheon diagnostic of a Pantheon
assurance turn, and recomputes the content-bound `projection_id`. A projection whose result,
manifest, receipts, or payload no longer matches is quarantined and never rendered. A held
projection that the Operator builds itself carries no Core commitment and uses a separate local
path that accepts only a held status.
Core keeps semantic request binding, Incident evidence projection, and localized Incident answer
rendering in dedicated modules while the semantic turn processor retains orchestration.
The split preserves every wire field, row limit, locale, evidence reference, and no-authority value.
When the local development diagnostic channel is enabled, the processor also records a
content-free [semantic decision trace](../deployment/developer-workflow-assurance.md#semantic-decision-traces)
after it builds each projection. The trace stays in the Core process, and the projection, its
schema version, and every wire field remain unchanged.
Ontology manifest declaration lists and counts also render from a dedicated module. A declaration
list names each readable declaration with its version and states display and source-completeness
limits. A row that is not an available, no-authority declaration of the requested kind renders a
bounded unavailable answer instead of a generic row count.
When a Resource list or declaration list is incomplete, its limitation line explains each known
typed source-limitation code in the answer locale and keeps the exact code in inline code. An
unknown code is shown only as its code. The `source_truncation_reason` wire field carries only the
machine code; localized text never replaces it.
Answer text names provider lifecycle states, timezone-aware instants in UTC, and source
completeness in the answer language, and pairs the `execution_authority=false` marker with a
sentence that states the read-only boundary. A recent-change row without a Resource name shows the
last segment of its reference. Wire rows and technical details keep the exact provider values; an aggregate row leads with its group's scalar fields. `GET /me/conversations` pages legacy conversation rows together with journaled semantic-turn sessions, newest first.
Operator's PostgreSQL family facade similarly delegates immutable records, row projection, and
evidence decoding without changing query parameters, proposal claims, replay order, or wire fields.
Operator terminal presentation delegates Pantheon assurance, localized Incident blocks, and
content-redacted read trajectories to focused renderers and attaches grounded `code_artifacts`
(`grounded_behavior_code_artifacts`) when a prompt matches `DEFAULT_SECURITY_BEHAVIOR_SPECS` without
changing fields, bounds, locale, evidence authority, or the fixed no-execution contract.

- **Incident draft**: A verified `incident_create` judgment returns an
  authority-free `incident.create` draft with bounded severity and target,
  conversation `session_id`, and a request-scoped idempotency key. The server
  retains its source digest and 10-minute expiry. Producing the draft publishes
  no event and creates no Incident. The browser shows Confirm and Cancel controls.
- **Typed Incident confirmation**: `POST /chat/action/confirm` accepts only
  `{"action_type": str, "arguments": object, "session_id": str,
  "idempotency_key": str}`. The server reloads the exact principal-owned
  semantic projection, compares every public field, checks expiry and current
  RBAC, then durably queues one versioned request. Unknown fields, stale drafts,
  modified arguments, and unsupported action types are blocked.
- **Dedicated Incident transport**: the outbox publishes
  `IncidentCreationRequest` on `operator.incident-creation.requests`. Core
  validates its digest, role floor, source identities, partition key, and
  no-authority fields before `IncidentLifecycleWorkflow` opens or reuses the
  Incident. This record operation does not use Thor and does not depend on an
  ActionType's shadow or enforcement mode.
- **Compatibility endpoint**: the independent Operator Service does not
  register the former raw-prompt `POST /chat/action` path. Browser and API
  clients use the semantic draft plus typed confirmation path so natural
  language never enters a write endpoint.
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
- **Response** (accepted): `202 {"submitted": true, "created": false,
  "action_type": "incident.create", "request_id": ..., "dispatch_status":
  "pending", ...}`. This response proves durable acceptance, not Incident
  creation. The authoritative `/incidents` projection proves completion after
  Core records `incident.open`.
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
the Operator [workflow route family](../../../services/operator-service/src/fdai_operator_service/families/workflow/manifest.py).
Operators can edit source files, choose an entrypoint, declare modules and host
capabilities, validate, stage an immutable artifact, and render a shadow plan
for an inventory Resource.

The capability response reports each optional operation separately. The console
doesn't open the workbench when the route is absent and disables any operation
whose adapter, submitter, or schedule store isn't wired, so an unavailable path
never appears as an executable control that fails with a generic `404`.

The Operator composition owns this response in
[`python_task_capability.py`](../../../services/operator-service/src/fdai_operator_service/python_task_capability.py).
The workbench is available only when a static validator and a VM task runner are
bound. Otherwise the route returns HTTP `200` with `available: false`, every
operation disabled, and `unavailable_reasons` naming each missing owner
(`python_task_validator_not_bound` or `python_task_vm_runner_not_bound`). The
independent Operator binds neither today, so it reports unavailable in every
venue, and `execution_authority` is always `false`. The console treats that report
like an absent route and announces the reasons. The
[Console Read Boundary](../deployment/console-read-boundary.md#workflow-definitions-and-python-task-capability)
records why the Operator owns this report.

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
the disclosure shows each artifact's static check, which always states that the
code was not executed, the exact grounded content on the shared code surface with
Copy, and its artifact reference. The terminal artifact is derived from the
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

The `logical_service_current_state` answer shape presents the exact BusinessService, Workload, and
runtime Resource mapping plus fresh verified component states. Empty or incomplete mappings remain
explicit. The answer never derives aggregate service health or cause and always keeps
`execution_authority=false`.

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
`mutation_authority: false`. Inventory SSE negotiates `cursor_version=2` for repaired `epoch:sequence` cursors and emits an identifier-free reset requirement when epochs differ. Clients reread their authenticated snapshot before reconnecting; numeric-only clients receive unavailable for repaired streams. Other principal-scoped stream cursors, including incident replay, remain unchanged.

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
| Runtime impact | Schema `1.1.0` adds `relationship_evidence_complete`, `relationship_source_coverage`, and each edge's bounded `evidence` object to the `1.0.0` envelope. Both versions retain `schema_version`, exact ontology release, `source_generation`, `source_cutoff`, exact target, traversal depth and ordered LinkTypes, reached nodes, traversed edges, affected count, query completeness, depth/edge truncation reasons, and both authority flags fixed to `false`. Every edge carries visible `verification_status`; an optional map must match the same snapshot generation or cutoff and contain every Resource and edge in the exact simulation result. Missing or incomplete relationship-source coverage keeps configuration evidence unavailable for verification while preserving its bounded provenance fields and an exact recovery reason. |

The common detail `_revision` and dependent `_revision` are SHA-256 digests over canonical
projection bytes. Release diff uses `diff_digest` for the compared pair. Runtime impact pins the
active inventory generation instead of using a catalog revision as runtime evidence. Context
snapshots remain separate, purpose-scoped, receipt-bound projections and are never reconstructed
from the current screen.

The Console exposes these reads at `/ontology/object-types/:name` and
`/ontology/releases/:digest`. LinkType and ActionType clean paths reuse their existing contract
inspectors. Related actions appear only when an ActionType carries an exact semantic ObjectType or
InterfaceType target. Legacy actions without that evidence lower completeness and are not inferred.
An ObjectType that declares no lifecycle carries `lifecycle_classification` (`category`,
`rationale`, `source_refs`) copied from the reviewed classification registry, so the Console explains
who owns the lifecycle instead of showing an empty state. It grants no lifecycle owner or authority.
Known evidence-unavailable reason codes render as plain language with the raw code kept visible.
InterfaceType and FunctionType keep their registry identity and topology nodes until more than one
meaningful active declaration and an authoritative usage source justify dedicated P2 views.

### 13.11 Semantic work progress frame

The semantic `POST /chat/stream` path adds one optional `work_progress` event. Its data is
`{seq, revision: 0, work_progress_shape}`, and the shape follows the
[work progress contract](operator-console-progressive-conversations.md#work-progress-contract).
Operator sends the event at most once per stream and before the first query `activity`. A live
frame uses event id `0:planning`, and a replayed frame uses `<projection sequence>:planning`.
Clients that don't recognize the event ignore it. It carries no evidence or execution authority.

Operator reports the semantic turn's own lifecycle, such as evidence executed, evidence verified,
and answer prepared, as `activity` events with `kind` `semantic_turn`, an `activity_id` of
`semantic:<phase>`, and no `execution` record. They state workflow facts, not reads, so clients
don't count them as observed reads when they choose the presentation density.

A live model-call `activity` also carries a closed `model_call` object with `stage`, and `model` and
`duration_ms` when known. Clients render the row label and detail from their own catalog in the
console language and fall back to the server `label` and `detail` for an unknown stage.

The terminal `done` event's `trajectory_detail` may carry `work_progress_shape`, `turn_budget`, and
`context_receipts`. Operator validates each field separately and drops a malformed field alone. It
keeps at most eight activities within 60 KiB and counts the rest in `omitted.activities`.

A compiled answer states each reviewed limitation of its frame right after its heading, such as the
read window, a cause that is not established, a possible impact, or an anchor whose name uniqueness is
unproven under incomplete inventory coverage. An answer read from such an anchor keeps the
`semantic_answer_partial` reason code, and a verified table leads with the reader's declared measure
fields before its receipt fields.
For multi-output collection answers, Core bounds each verified table while reserving space for
later outputs. Operator receives the resulting answer and typed limitations unchanged; the
reservation changes neither Incident creation, evidence authority, nor execution authority.

A stopped collection metric read may name an opaque continuation reference, and a recipe threshold
or window is stated in the answer text. Operator relays both unchanged; neither changes Incident
creation, evidence authority, or execution authority.

### 13.12 Semantic turn authentication receipt reference

The Operator emits the optional content-free `authentication_receipt_ref` in `operator-core-request` 1.9.0 only when `FDAI_SEMANTIC_AUTHENTICATION_RECEIPT_REF_ENABLED` is on. The setting defaults off, and with it off every envelope keeps its earlier version and bytes. Enable it only after a Core that accepts 1.9.0 is deployed. The reference grants no authority by itself. With the setting on, the Operator API and the channel edge retain the content-free receipt for each semantic request before they send the reference, and the verifier checks `case-history-read` against the receipt retained for that exact request. With it off, Pattern reads still fail closed.

### 13.13 Entitlement stamp response header

Every Operator response to a request whose bearer credential verified carries
`X-FDAI-Entitlement` with one of `none`, `evaluation-ended`, or `not-activated`, and CORS exposes it
to the Console. The value is Core's [Trial expiry watermark](../fork-and-sequencing/capability-licensing.md#entitlement-state-transport)
notice. A missing, malformed, unreadable, or stale notice is stamped `not-activated`, an
unauthenticated response carries no stamp, and a route cannot replace it. The header is an
availability notice and grants no authority.

### 13.14 Rule detected issue summary

`GET /rules/findings-summary` returns schema version `2.0.0` when Forseti's latest version 2
baseline coverage exists. Core binds the bounded Forseti baseline worker at startup when the state
store and an inventory database are configured. `FDAI_BASELINE_EVALUATION_ENABLED=false` disables
it, and `FDAI_BASELINE_EVALUATION_INTERVAL_SECONDS` and `FDAI_BASELINE_EVALUATION_MAX_RESOURCES`
bound it.

| Field | Meaning |
|-------|---------|
| `evaluated` | `true` only when coverage is complete and the outcomes match its outcome-set digest |
| `complete` | Whether the T0 dispatch pair set is fully covered |
| `counts` | Violated Resource count per bounded Rule reference; empty when not evaluated |
| `expected_pair_count`, `covered_pair_count` | Dispatch-derived denominator and terminal outcomes in it |
| `limitations` | Coverage limitation codes, such as `pair_missing`, when not complete |
| `coverage_digest`, `rule_activation_generation_id` | The coverage record and activation generation it binds |

Without version 2 coverage the response is `{"evaluated": false, "counts": {}}`. A malformed or
ambiguous record returns `503` instead of an inferred zero. The summary grants no authority.

`GET /code-security/reviews` and `GET /code-security/packs` return `surface`, `available`,
`complete`, `source`, the `reviews` or `packs` list, and `gaps`. Rows carry only counts, revisions,
opaque issue ids, decisions, verdict counts, and adjudication decisions, never paths, code,
rationale, or approval references. Malformed rows become `gaps` entries, so an empty list never
reads as a clean estate. Schema `1.1.0` review rows also carry `source` (kind, provider, revision
kind, trigger, and request id) and `producers`; older rows return `source: null`.

`GET /code-security/repositories` returns registered repositories (alias, provider, location,
default ref, exposure, enabled, and registration time) without the registrant.
`GET /code-security/scan-requests` returns Console scan requests with `status` (`queued`,
`running`, `completed`, or `rejected`), timestamps, a rejection reason code, or a bounded result
(revision, digest, decision, issue count, coverage, and publication), never the requester.
`POST /code-security/scan-requests` accepts only `repository_alias` and an optional `ref`, requires
an `Idempotency-Key`, and returns the `202` proposal receipt. Request rows also carry `kind`
(`scan` or `repository_change`), `action`, and `location`; a completed registration change returns
`result: {"enabled": ...}`.

`POST /code-security/repositories` (Owner only) accepts `action` (`register`, `enable`, or
`disable`) and `repository_alias`; `register` also requires `location` (`owner/repository`) and
accepts `default_ref` (default `HEAD`, the repository's default branch) and `exposure`. Any other field returns `400`.
`GET /code-security/issues?repository_alias=...&revision=...` returns `available`, `complete`,
`truncated`, `issues`, and `gaps` for one review. Each issue carries id, priority, due days,
severity, confidence, weakness class, CWE ids, advisory ids, package, producers, and known
exploitation. A summary row whose digest doesn't match the recorded review is withheld.

### 13.15 MCSB control assessment fields

`GET /mcsb-controls` and `GET /mcsb-controls/{benchmark_version}/{control_id}` add server-owned
shadow assessment fields to the catalog read. Only `v1` is assessed.

| Field | Meaning |
|-------|---------|
| `assessment_summary.status` | `evaluated`, `not_evaluated`, `unavailable` (no assessment projection), or `not_assessed` (another benchmark version) |
| `assessment_summary.satisfaction_counts` | Control count per satisfaction value when a projection exists |
| `assessment_summary.execution_authority` | Always `false` |
| `controls[].assessment` | The control's applicability, evaluation, satisfaction, evaluation time, completeness, and limitations, or `null` |
| `assessment.requirements` | Detail only: each requirement's kind, reference, `decisive` or `supporting_only` evidence role, status, and limitations |

A malformed or authority-bearing assessment projection returns `503` instead of an unknown state.
The Console renders these values and never derives satisfaction.

### 13.16 Global kill-switch request

`POST /system/kill-switch` requires a fresh human Owner or BreakGlass principal, an
`Idempotency-Key` header, and a JSON body containing only `engaged` and `reason`. The Operator API
signs the exact actor, roles, authentication time, request time, state, reason, correlation, and
idempotency key, then publishes `operator.kill-switch.requests`. HTTP `202` returns the request id
and digest after publication; it grants no executor authority and does not prove a state change.

Var is the accountable consumer. It revalidates the signed Operator receipt, producer, human
identity, Owner or BreakGlass role, authentication lifetime, correlation, and replay fence before
the Core command service compare-and-set writes `system:kill-switch` with its audit entry. An
authorized readback surface for the resulting state revision is not implemented yet, so a live
engage or disengage drill remains incomplete until an independent store observation is retained.


## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/operator-console-wire-contracts.md) |
