---
title: Operator Console Module Map and Boundaries
---
# Operator Console Module Map and Boundaries

This document maps the Operator Console conversation modules, routes, channels, and provider
boundaries. It keeps source ownership discoverable without expanding the main console contract.

## Executable baseline

[`operator-console-module-inventory.json`](operator-console-module-inventory.json) records the
current Operator API package responsibilities, route-family classifications, candidate
destinations, and import-surface status. It is descriptive rather than a file-count target, but an
executable completeness gate requires every current module directory and route module to remain
classified.
Candidate destinations remain package hints. [Service Graduation and Data Ownership](../architecture/service-graduation-and-ownership.md) is the gate for a new process, identity, transport, or data owner.
[`test_operator_api_layout.py`](../../../services/operator-service/tests/)
also pins the exact default method, path, and route-name set plus representative HTTP envelopes.
An intentional default route addition updates this reviewed baseline in the same change.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Current-state activity projection boundary | implemented | `fdai_operator_service/activity_projection.py`; `test_activity_projection.py`; focused persistence and projection tests (`6 passed`) | Durable rows require the hashed correlation reference, use the same activity id as live frames, retain only the newest duplicate, and keep `execution_authority=false`. |
| Governed semantic receipt presentation | implemented | `console/src/deck/backend-normalizers.ts`; `backend-stream.ts`; `transcript-store.ts`; `conversation-trajectory-view.tsx`; `console-routes.spec.ts`; focused Console tests | The Console parses terminal semantic receipts fail closed, persists and replays the exact typed fields, and renders route, unavailable reason, assurance digests, evidence references, and no-execution-authority state. The authenticated runner binds the terminal receipt to the caller request UUID and reads a cloned response stream so application consumption remains unchanged. Authenticated browser evidence remains pending. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | implemented | Adopted the implementation ledger without reconstructing earlier provenance and recorded the durable/live current-state projection identity. | Current source plus `test_activity_projection.py`; the focused projection and persistence suites passed. | Reduce the report-only dependency debt through the reviewed migration families below. |
| 2026-08-13 | in-progress | Added exact typed semantic receipt parsing, stream capture, durable replay, presentation, and authenticated evidence runners. | `current change`; focused Console tests and typecheck pass. | Run the governed request-to-Console and bilingual randomized assurance browser paths and retain both passing records. |
| 2026-08-13 | implemented | Bound authenticated terminal-receipt capture to the caller request UUID and captured the SSE body from `Response.clone()` without consuming the application's original stream. | `current change`; `console-routes.spec.ts`; Console typecheck and Playwright discovery pass. | Execute the authenticated governed runner and retain its passing record before randomized assurance. |

### Remaining work

- [ ] Move each report-only reverse dependency behind its reviewed neutral contract or provider boundary, then reduce the matching `.check-operator-api-boundaries.debt` budget before making that direction enforceable.
- [ ] Retain passing authenticated request-to-Console and bilingual randomized assurance evidence before declaring semantic receipt presentation ready.

### Dependency-direction gate

`check-operator-api-boundaries.py` parses imports without loading application code. It enforces
the cleaned core-to-delivery, runtime-to-Operator API, ingestion-to-Operator API, shared
delivery-to-application, application-to-provider-adapter, and route-to-provider-adapter
directions. Existing route-to-core policy imports and opposite-direction
Operator API service imports remain report-only debt, so unrelated work isn't blocked while the
later migration issues reduce them.

The gate also measures unique internal imports for the production factory, development factory,
and runtime bootstrap. A composition root at or above the reviewed limit needs an exact path,
maximum import count, and preceding justification comment in
`.check-operator-api-boundaries.allowlist`. Exceeding that reviewed maximum requires a new review.
Missing justification, an unreviewed high-fanout root, or a stale exception fails the check.
Report-only rules use `.check-operator-api-boundaries.debt` as aggregate non-growth budgets: debt
may shrink without updating the file, but an increase fails CI. Use one or more
`--path <repository-relative-path>` arguments for a narrow package or touched-file check; stale
detection is limited to the same selected scope, while CI and pre-push always run the full scan.

Fix an enforced finding by moving the dependency to a neutral contract or provider seam and
binding its implementation at a reviewed composition root. Don't add an allowlist entry for a
reverse service import. Report-only findings are migration inventory and become enforceable only
after their owning package is cleaned.

`check-boundary-docstrings.py` checks exact reviewed package modules for non-empty Responsibility,
Boundary, Authority and state, Dependencies, and Deployment sections. Scopes start in report mode
and move to enforcement only after review. Justified exclusions fail when missing, out of scope,
or no longer needed. This structural AST check does not prove semantic truth.

### First reversible family migration

Issue 70 selects the five `routes/audit*.py` modules as the first migration family. The executable
inventory already classifies them as one read-projection family. Each module has one or two direct
Python consumers outside the family, one to three internal FDAI imports, and one or two changes in
the measured 90-day window. The family is read-only and owns no approval, execution, CORS, or
lifespan behavior, so it has a smaller behavioral surface than chat, workflow, or investigation.

The implementation owner moves to `fdai.delivery.operator_api.projections.audit`, with filenames
and public symbols unchanged. App-side audit query use and production panel composition import the
new package facade; development composition reaches the same facade through the shared production
panel builder. Every former `routes.audit_*` module remains an explicit per-module compatibility
shim. Method, path, route name, authorization, response payload, provenance, and database ownership
stay unchanged.

Rollback keeps both import surfaces stable. Restore the implementation files under `routes/`,
change each new `projections.audit` module into a forwarding shim to its restored route module,
and leave composition imports on the package facade. This reverses physical ownership without an
API or wire rollback and avoids a broad wildcard facade.

### Conversation turn application boundary

Issue 71 introduces `fdai.delivery.operator_api.application.conversation_turn` as the process-local
application-service boundary shared by JSON and SSE chat routes. After authentication and bounded
transport parsing, each route creates an immutable `ConversationTurnInput` and starts one typed
lifecycle. Existing evidence, planning, narration, verification, history, busy-input, progress,
and cancellation implementations remain in-process and finish through that lifecycle. No network
hop or separately deployed service is introduced.

The input contains only server-derived principal, conversation, request, correlation, prompt,
locale, target-agent, evidence-reference, history-count, and transport-mode values. It has no
provider scope, credential, approval, role, executor identity, or mutable context field. The
immutable result records terminal status, verified answer, verification summary, evidence refs,
presentation artifact, delegation metadata, and explicit failure detail. Its frozen wire snapshot
round-trips to the existing JSON payload or SSE terminal frame without adding fields.

The service is non-authoritative and stateless between calls. It cannot approve, execute, promote,
select provider scope, or receive Thor's identity. HTTP status mapping, SSE sequence/revision,
headers, route names, authorization, and cancellation transport remain route-owned. Bragi remains
the presentation translator, and authority-bearing agent work continues through typed pub/sub.

### Conversation intent graph projection boundary

The shared ontology-query SDK owns exact-plan `IntentGraph` and `IntentGraphEvidence` records.
Explicit projection functions remove internal frame and plan digests, parse canonical goal
arguments, and emit only the bounded Console v2 graph and v1 evidence shapes. The Console parser
accepts terminal cancellation at both graph and goal-receipt levels, preserving
`request_cancelled` instead of dropping a valid terminal update. Projection rejects more than
eight goals, invalid display goal ids, deep or oversized arguments, excess dependencies, and more
than twelve evidence references. It copies no provider body and grants no execution authority.

Core produces these records from a principal-manifest-verified query plan. Operator adapts the
durable semantic projection to the existing `done` frame, and production SSE carries the graph,
evidence, verification counters, and deterministic answer without changing the Console parser.

The independent Operator/Core bridge now has additive version 1.2 wire shapes for a semantic turn
and its terminal projection. The Operator remains responsible for authentication, durable outbox
acceptance, principal-scoped replay, and SSE sequencing. Core remains responsible for selecting the
exact release and principal manifest, executing the verified plan, and producing evidence receipts.
The contract does not permit direct service imports or semantic downgrade to an older peer.

The Core semantic runtime now composes planning, dependency-wave execution, and these projections
as one async server result. Every accepted turn terminates as answer, clarification, hold,
unsupported, action draft, or cancellation. The synchronous compatibility coordinator defaults to
exact canonical commands and does not apply natural-language regex, keyword narration, or
canonical-string read planning unless an explicit temporary caller selects `legacy` mode.

The independent Operator package owns its concrete Event Hubs Kafka adapter under `adapters/`.
Production composition builds one adapter for both ports only after the bootstrap, request topic,
and projection topic pass all-or-none validation. The producer is idempotent and the consumer uses
manual commit: a valid mapping is committed only after the semantic bridge processes it, while
malformed or oversized JSON is written to the sibling DLQ and then committed. The adapter owns its
managed-identity credential and closes it with the application lifecycle. Explicit injected
publisher/source pairs remain the test and downstream override seam. Semantic Kafka and the
dev-only local narrator are mutually exclusive. The same process boundary owns `GET /chat/health`:
it projects bridge worker readiness directly and never requires a durable conversation projection.

### Conversation claims application boundary

The SD-01 claims slice owns deterministic answer-claim verification under
`fdai.delivery.operator_api.application.conversation.claims`. Extraction, evidence collection,
matching, manifest construction, and frozen-corpus evaluation run in-process and keep request-local
state only. Route adapters continue to own authentication, HTTP status mapping, JSON envelopes,
SSE sequencing, cancellation, and terminal rendering.

The owned terminal verifier imports the explicit claims package facade. Repository-wide consumers
of the former `routes.chat_claim*` modules were internal implementation or test imports and moved
in the same slice, so no claim compatibility shim remains. Rollback restores the implementation
modules and facade under `routes/`, then redirects the claims package facade to that restored
owner without changing the JSON or SSE wire contracts.

### Conversation verification application boundary

The SD-01 verification slice owns terminal answer verification under
`fdai.delivery.operator_api.application.conversation.verification`. The package contains the
canonical result, text-integrity checks, deterministic claim and evidence coordination, bounded
incident and agent-activity rendering, and tool/operational verification handlers. It is
request-local and keeps HTTP status mapping, JSON envelopes, SSE sequencing, authentication,
cancellation, and terminal frame assembly in routes.

Internal route and test consumers import the explicit package facade. The capability catalog names
that owned package directly, so no verification compatibility module remains under `routes/`.
Rollback restores the moved modules under `routes/` and redirects the package facade without
changing JSON, SSE, authentication, or conversation-history behavior.

### Conversation presentation projection boundary

The SD-01 presentation slice owns value-free layout selection and verified evidence artifact
compilation under `fdai.delivery.operator_api.projections.conversation.presentation`. The package
contains the presentation contract, shape profiles, bounded planner, and deterministic inventory
and subscription-health artifact compilers. It is read-only and request-local.

JSON and SSE routes import the explicit presentation facade and continue to own authentication,
HTTP status mapping, JSON envelopes, SSE sequence and revision, cancellation, terminal assembly,
and conversation history. The former `routes.chat_presentation*` modules were internal import
paths, so no compatibility shim remains. The move preserves the exact canonical text fallback,
artifact schema, localized labels, evidence references, byte bounds, and planner degradation.
Rollback restores the route implementation modules and redirects the presentation facade without
changing either wire contract.

### Conversation inventory application and projection boundaries

The SD-01 inventory slice owns typed queries, deterministic compilation, follow-up scope,
catalog-backed language and resource semantics, ontology functions, semantic retrieval, and
provider-read coordination under
`fdai.delivery.operator_api.application.conversation.capabilities.inventory`. The capability is
read-only and request-local. It does not own HTTP, SSE, authentication, cancellation, history, or
inventory writes.

Sanitization, current and activity result projection, scheduled-shutdown projection, and
deterministic answer rendering live under
`fdai.delivery.operator_api.projections.conversation.inventory`. Routes and terminal verification
import the explicit application or projection facade according to responsibility. Every former
`routes.chat_inventory*` consumer was internal implementation or test code, so no compatibility
shim remains. JSON, SSE sequence and revision, authorization, provider scope, and conversation
history behavior stay unchanged.

Rollback restores the inventory implementation modules under `routes/` and redirects the two
inventory package facades to those restored owners. It does not change either wire contract or the
authoritative inventory providers.

### Conversation backend application and adapter boundaries

The SD-01 backend slice owns provider-neutral contracts and request-local latency routing under
`fdai.delivery.operator_api.application.conversation.backend`. The application package selects
among injected backends, preserves bounded failover and multimodal dispatch, and exposes only
credential-free endpoint metadata. It does not import Azure or OpenAI implementations.

Concrete Azure workload-identity and OpenAI-compatible HTTP implementations, shared response
validation, metering transport, resolved-model loading, and startup construction live under
`fdai.delivery.operator_api.adapters.conversation`. JSON and SSE routes continue to own
authentication, HTTP status mapping, sequence and revision, cancellation, terminal delivery, and
conversation history. All repository consumers of the former `routes.chat_backend_*` modules were
internal implementation or test imports, so no compatibility shim remains.

Rollback restores the five backend modules under `routes/`, then redirects the application and
adapter facades to those restored owners without changing auth, provider scope, JSON, or SSE.

### Conversation evidence application boundary

The SD-01 evidence slice owns read-only operational evidence resolution, provenance projection,
bounded branch lifecycle, and authority-preserving result merge under
`fdai.delivery.operator_api.application.conversation.evidence`. Operational lookup continues to
read the authorized server read model and retains the exact `matched`, `summary`, `ambiguous`,
`none`, and `unavailable` outcomes. Missing, conflicting, or unselected evidence remains explicit
instead of falling through to an unsupported answer.

Independent branches still complete concurrently and return in canonical specification order. The
merge keeps the established tool, operational, agent, and public-web authority precedence, while
JSON and SSE routes continue to own authentication, request parsing, HTTP status mapping, frame
sequence and revision, cancellation, terminal assembly, and conversation history. All old
`routes.chat_evidence*` consumers were internal source or test imports and moved in this slice, so
no compatibility shim remains. Rollback restores the five route implementations and redirects the
evidence facade without changing JSON, SSE, authentication, evidence authority, or history.

### Conversation progress metric projection boundary

The SD-01 streaming metric slice owns pure queue-accepted progress reduction under
`fdai.delivery.operator_api.projections.conversation.stream_metrics`. It records only aggregate
first-progress latency, terminal branch outcome and duration, and output truncation. It retains no
prompt, answer, branch id, channel id, principal id, or resource identifier.

The SSE route continues to own frame sequencing, queue admission, cancellation, and transport
delivery. The former `routes.chat_stream_metrics` module had no external compatibility consumer, so
no shim remains. Rollback restores the reducer under `routes/` and changes the stream route import
without changing metric names, SSE frames, or cancellation behavior.

### Conversation terminal projection boundary

The SD-01 terminal slice owns pure verification-frame assembly, terminal payload compilation,
measured LLM usage rendering, durable inventory result context, and source-failure replay context
under `fdai.delivery.operator_api.projections.conversation.terminal`. The package also owns the
bounded public intent-graph and conversation-policy summaries used in terminal responses. It is
read-only and request-local.

JSON and SSE routes continue to own authentication, request parsing, HTTP status mapping, frame
sequence and revision, cancellation, terminal delivery, and conversation history. All repository
consumers of the four former route modules moved to the explicit terminal facade, and the package
imports no `fdai.delivery.operator_api.routes` module, so no compatibility shim remains. Rollback
restores the four route implementations and redirects the terminal facade without changing either
wire contract.

### Conversation post-generation application boundary

The SD-01 post-generation slice owns streamed turn completion under
`fdai.delivery.operator_api.application.conversation.post_generation`. After answer generation,
the package coordinates bounded quality review, deterministic verification, terminal payload
validation, principal-scoped assistant-turn persistence, and off-path post-turn review in the
established order. It delegates pure payload compilation to `projections.conversation.terminal`
and writes durable history only through an injected persister.

The SSE route retains authorization, request parsing, heartbeat framing, connection and busy-input
cancellation, request sequence and revision, trajectory projection, and final transport delivery.
The package imports no `fdai.delivery.operator_api.routes` module. The former
`routes.chat_stream_post_generation` path was internal, so no compatibility shim remains. Rollback
restores that route module and changes the stream-route import without changing frame order, JSON
or SSE terminal payloads, verification, history, or post-turn review behavior.

### Conversation request preparation application boundary

The SD-01 request-preparation slice owns content-policy validation and replay, user preferences,
document-reference resolution, complete-history assembly, verified prior context, resource and
freshness context, follow-up scope, answer planning, and target-agent derivation under
`fdai.delivery.operator_api.application.conversation.request_preparation`. The package accepts one
server-authenticated, byte-bounded JSON object and returns a typed prepared request or replay
outcome. It is process-local, non-authoritative, and imports no `operator_api.routes` module.

`routes/chat_stream_request.py` retains `authorize(request)`, Content-Length preflight, raw body
reading, byte limits, JSON-object parsing, Starlette `HTTPException` mapping, and the SSE adapter
call. JSON chat retains its established transport sequence while importing the same preparation
contracts and helpers. The former route-owned history module moved in full; document, replay,
resource-context, and identity helpers split from their mixed route modules. Every consumer was an
internal source or test import, so no compatibility shim remains.

Document resolver failures become one fixed unavailable detail at the application boundary for
both JSON and SSE. Exception chaining preserves internal diagnostics, but provider URLs, tokens,
and error text never cross the HTTP boundary.

Rollback restores the history and preparation helpers under `routes/`, restores
`chat_stream_setup.py`, and redirects JSON and SSE imports without changing authentication, status
codes, body bounds, content-policy replay, history, document access, answer plans, or either wire
contract.

### Conversation lifecycle application boundary

The SD-01 lifecycle slice moves shadow answer-planning task coordination to
`application.conversation.planning`, Korean narrator review to
`application.conversation.post_generation.quality`, input content-policy recovery to
`application.conversation.request_preparation.content_policy`, and request-local steer and active
narrator interruption coordination to `application.conversation.busy_input`. These modules keep
only bounded process-local state and import no `operator_api.routes` module.

`BusyInputCoordinator` remains the core authority for active-turn registration and arbitration.
The application helper only consumes its safe-boundary and cancel-event contracts; it does not
connect conversation cancellation to Thor, an ActionType, or managed-resource state. JSON and SSE
routes retain authentication, HTTP and SSE status mapping, frame sequence and revision, connection
cancellation, history transport, and final delivery.

Every former route-module consumer was internal source or test code, so no compatibility shim
remains. Rollback restores the four route implementations and redirects those internal imports
without changing planning bounds, quality verification, policy recovery, steering, interruption,
JSON, or SSE behavior.

### Conversation terminal support projection boundary

The SD-01 terminal support slice owns bounded trajectory-detail replay, deterministic current-screen
T0 answers, opt-in redacted model-call traces, and verified resource-follow-up response context under
`fdai.delivery.operator_api.projections.conversation`. These projections are read-only and
request-local. They import no `operator_api.routes` module and perform no durable write or model or
provider call.

Request resource parsing and follow-up contextualization remain in
`application.conversation.request_preparation.resource_context`. Azure and OpenAI-compatible
adapters record already-issued model requests and responses through the tracing projection, while
the provider calls remain adapter-owned. JSON and SSE routes retain authentication, body parsing,
status mapping, frame sequence and revision, cancellation, terminal delivery, and conversation
history. Every former route consumer was internal, so no compatibility shim remains. Rollback
restores the four route implementations and redirects internal consumers without changing either
wire contract.

### Conversation persistence and document evidence boundaries

The SD-01 persistence slice owns principal-scoped transcript writes, content-free policy receipts,
replay metadata, and the conversation-image lifecycle under
`fdai.delivery.operator_api.persistence.conversation`. Its explicit facade preserves stable
operator and assistant idempotency keys, ordered turn allocation, and bounded ontology projection.
An assistant projection timeout or failure remains a logged degradation after the durable answer
write. It does not change the stored answer or terminal response.

Validated images keep the established pending create, exact-attempt compensation, and durable
finalization sequence. Turn metadata contains only image id, display name, and validated media
type. Image bytes remain in the principal and conversation-scoped image repository. Pure governed
document context and verification merging live in
`projections.conversation.document_evidence`, which preserves exact citation values and stable
first-occurrence order when duplicate refs are removed.

JSON and SSE routes retain authentication, request parsing, HTTP status mapping, frame sequence and
revision, cancellation, and transport delivery. Every former route-module consumer was internal
source or test code, so no compatibility shim remains. Rollback restores the three implementations
under `routes/` and redirects internal imports without changing transcript identity, image expiry,
document refs, JSON, or SSE behavior.

### Conversation capability application boundary

The SD-01 capability slice owns bounded Pantheon delegation, runtime-skill disclosure,
configuration-baseline reads, public-web evidence resolution, request-time capability visibility,
and strict topology intent under `fdai.delivery.operator_api.application.conversation`. Agent
delegation remains a read-only adapter over the existing runtime and bridge contract. It disables
action proposals and handoff materialization and does not move Pantheon judgment, approval,
execution, recovery, or audit authority into the Operator API.

The provider-neutral web-search resolver owns deterministic and semantic intent precedence,
sanitization, bounded timeouts, availability, progress, and fail-closed provider errors under
`application.conversation.capabilities.web_search`. Azure candidate construction and environment
loading live in `adapters.conversation.web_search`; caller text never supplies provider scope,
allowed domains, endpoint, deployment, or credentials. Configuration drift keeps the exact
server-pinned document route ahead of action-context phrases, and topology intent continues to
require exact server-owned selectors.

JSON and SSE routes retain authentication, request parsing, HTTP status mapping, frame sequence and
revision, cancellation, terminal delivery, and conversation history. All consumers of the six
former route modules were internal source or test imports, so no compatibility shim remains.
Rollback restores those implementations under `routes/` and redirects internal imports without
changing authority classification, provider scope, intent precedence, or either wire contract.

### Final conversation route closure

Commit `e141ab07e` established a six-file structural inventory and moved compiled user-policy,
assurance-policy, and one-shot response completion behind explicit application owners. Pure
terminal summaries and payload values remain under `projections.conversation.terminal`, and
conversation application, projection, and persistence packages import no route module.

JSON and streamed turn lifecycles now live under
`application/conversation/turn_execution`. Its typed services coordinate request preparation,
planning, evidence, generation and stream collection, busy input, verification, response
completion, persistence, metering, and user-context projection without importing Starlette,
provider adapters, or route modules. `chat.py` retains authentication, bounded JSON parsing,
application error-to-status mapping, `JSONResponse` delivery, route binding, and reviewed
compatibility imports.

`chat_stream.py` now retains only authentication and bounded request transport delegation,
pre-stream application error-to-status mapping, `StreamingResponse` construction, SSE encoding,
heartbeat bytes, sequence and revision fields, and connection-close cancellation through async
iterator teardown. The application event owns the canonical answer `revision`; the route adds a
separate monotonic `seq` for wire-frame order and preserves the revision unchanged.
`chat_registration.py` owns registration, `chat_stream_protocol.py` owns the
SSE protocol, and `chat_stream_request.py` owns request transport. The chat family is structurally
transport-only while preserving SSE frame order, replay, interruption, cancellation, history, and
terminal payloads.

### Change lineage projection boundary

The SD-06 Operator projection owns bounded summary and detail views over canonical immutable
Change lineage under `fdai.delivery.operator_api.projections.change_lineage`. It is read-only and
request-local, preserves candidate-only learning and zero execution or promotion authority, and
performs no provider I/O or persistence.

### Immutable app composition

Issue 72 keeps `OperatorApiConfig(**kwargs)` as the bounded compatibility constructor and projects
it through `split()` before any route registration. `OperatorApiValues` contains only inert,
environment-derived values. `OperatorApiRuntimeBindings` groups process-local dependencies into
stream, projection, lifecycle, read-view, conversation, governed-route, and fixed-HTTP records.
Each registration function receives only its capability record rather than the legacy aggregate.

All records are frozen. Mapping inputs are copied into read-only views, and intentionally shared
providers must reference the same object across their consumers. `OperatorApiComposition.validate()`
checks those shared references and required cross-group pairs before a route is appended or a
lifecycle callback starts. The records contain neither raw provider credentials nor Thor's
executor identity. Production and interactive local composition continue to build the same legacy
constructor and enter the same split and validation boundary, so no synthetic production fallback
or venue-specific route model is introduced.

Route methods, paths, names, registration order, authorization, CORS, response payloads, and
availability defaults remain unchanged. Rollback moves the immutable record definitions and
validation back into `app/config.py`, removes `app/composition.py`, and leaves the legacy
constructor, `split()` mapping, public `main` facade, and registration signatures intact. This
reverses physical ownership without a wire or caller migration.

| Package | Current responsibility | Migration rule |
|---------|------------------------|----------------|
| Root | Public facades and foundational contracts | Preserve until a classified replacement exists. |
| `adapters/` | Concrete Operator API provider implementations outside HTTP routes, including the independently owned shared Kafka observation consumer | Keep provider I/O behind application contracts and commit stage/runtime records only after validation and Live/Agent fan-out. |
| `adapters/conversation/` | Azure and OpenAI-compatible narrator transports plus web-search startup construction | Import through explicit modules; keep credentials, endpoints, deployment selection, and transport outside application and routes. |
| `app/` | Shared ASGI assembly, middleware, registration, and lifespan | Retain as the HTTP composition boundary. |
| `application/` | Typed process-local, non-authoritative application coordination | Retain until service-graduation evidence justifies a process boundary. |
| `application/conversation/` | Process-local conversation planning, server policy resolution, one-shot JSON execution, response completion, capability visibility, strict intent classification, busy-input steering and interruption, and capabilities outside HTTP transport | Retain in-process until service-graduation evidence exists; keep HTTP and SSE transport responsibilities in routes. |
| `application/conversation/turn_execution/` | Typed, Starlette-free JSON and streamed turn request preparation, planning, evidence, generation, verification, persistence, metering, and completion coordination | Import through its explicit facade; keep authentication, body parsing, status mapping, JSON/SSE encoding, heartbeat, sequence, revision, and response delivery in routes. |
| `application/conversation/capabilities/` | Typed process-local agent delegation, runtime-skill, configuration-drift, web-search, and read-model capabilities grouped by domain | Retain as the non-authoritative capability owner; use injected read-only runtime and provider contracts. |
| `application/conversation/capabilities/inventory/` | Typed inventory queries, deterministic compilation, semantic grounding, and provider-read coordination | Import through its explicit package facade; keep JSON, SSE, authentication, and history in routes. |
| `application/conversation/backend/` | Provider-neutral backend contracts and request-local latency routing | Import through its explicit facade; keep provider implementations in adapters. |
| `application/conversation/claims/` | Deterministic answer-claim extraction and bounded evidence verification | Import through its explicit package facade; keep JSON, SSE, and authentication in routes. |
| `application/conversation/verification/` | Deterministic terminal answer verification and bounded evidence rendering | Import through its explicit package facade; keep wire behavior and authentication in routes. |
| `application/conversation/evidence/` | Operational evidence resolution, provenance, branch lifecycle, and authority-preserving merge | Import through its explicit package facade; keep JSON, SSE, authentication, cancellation, and history in routes. |
| `application/conversation/post_generation/` | Quality review, verification, history persistence coordination, terminal payload validation, and post-turn review | Import through its explicit package facade; keep authorization, request parsing, heartbeat framing, sequencing, cancellation, and SSE delivery in routes. |
| `application/conversation/request_preparation/` | Content policy and replay, preferences, document refs, history, prior context, resource and freshness context, follow-up scope, answer plans, and target-agent derivation | Import through its explicit package facade; keep authorization, bounded body parsing, HTTP mapping, SSE sequencing, and transport delivery in routes. |
| `dev/` | Interactive local and test-only provider composition | Keep unavailable to production imports. |
| `dev/fixtures/` | Synthetic pytest-only fixtures | Keep outside production composition. |
| `persistence/` | Operator API read-model and conversation-state persistence implementations | Retain behind owned store contracts. |
| `persistence/conversation/` | Principal-scoped transcript, policy-receipt, replay-metadata, and conversation-image lifecycle persistence | Import through the explicit facade and keep HTTP, SSE, authentication, status mapping, and transport in routes. |
| `projections/` | Read-only projection ownership outside HTTP routes | Retain as the owner of migrated families. |
| `projections/audit/` | Audit query and autonomy/FinOps measurement projections | The independent Operator Service owns its equivalent PostgreSQL read model, including bounded `GET /kpi/llm-cost`; keep pricing, executor authority, and Core implementation imports outside that service. |
| `projections/change_lineage/` | Bounded canonical Change-lineage summary and detail views | Import through its explicit facade; keep HTTP, provider I/O, persistence, execution, and promotion outside the package. |
| `projections/conversation/` | Request-local conversation read projections, including screen data, exact document evidence, model traces, trajectory detail, resource response context, and queue-accepted progress metric reduction | Retain in-process until service-graduation evidence exists. |
| `projections/conversation/presentation/` | Value-free layout selection and verified evidence artifact compilation | Import through its explicit facade; keep JSON and SSE behavior in routes. |
| `projections/conversation/inventory/` | Inventory evidence sanitization, result projection, and deterministic rendering | Import through its explicit facade; keep query compilation and provider coordination in the application package. |
| `projections/conversation/terminal/` | Terminal payload, LLM usage, resource-result, and source-failure projections | Import through its explicit facade; keep JSON, SSE, authentication, cancellation, and history in routes. |
| `production/` | Production provider construction and bindings | Reduce fanout incrementally without changing wire behavior. |
| `routes/` | HTTP and SSE transport, route registration, domain request adapters, and classified compatibility facades | Retain as the transport and reviewed facade boundary; conversation lifecycle orchestration stays behind the typed application facade. |
| `streaming/` | Read-only bounded SSE fan-out and fail-closed stage/runtime projection for `/live/stream` and `/agents/stream` | Keep authentication and HTTP response ownership in routes; never infer runtime readiness from keepalives. |

The independent Operator Service exposes authenticated `GET /agents/activity` as the durable, bounded replay source for inventory scans, ontology projection, and current-state reads.
A bounded latency profile preserves only the hashed `read-correlation:<digest>` for a current-state read and stores neither the raw operator question nor resource identity; its latency audit entry remains correlation-free.
The Console loads this projection before applying newer `/agents/stream` frames. Durable and live current-state activity use the same activity id, while durable projection ignores legacy samples without `correlation_ref`.
Both paths validate the same no-authority contract, reject malformed rows or authority-bearing frames, and keep `execution_authority=false`.

`fdai.delivery.operator_api.main` is the public app facade. `read_model` remains a public delivery
contract until a reviewed replacement exists. `fdai.delivery.auth` owns framework-neutral bearer
and Entra verification; `operator_api.auth` and `operator_api.entra_verifier` are compatibility
facades only.
The `main` facade's `busy_input_runtime` re-export is a transitional public seam rather than a new
runtime ownership claim.
`routes.panels` and `routes.reporting` remain transitional public extension seams because current
fork and reporting guidance imports them directly. Other individual `routes.*` modules are
internal implementation paths. A migration uses a per-module forwarding shim only when a
classified compatibility need exists. Runtime-owned agent-state records and event-bus publication
live in `fdai.delivery.agent_activity`, so the headless runtime imports no Operator API streaming
implementation. Provisioning's `streaming.provision_stream` compatibility remains classified
separately. Issue 71 closes the chat wire debts recorded by the baseline. Version 1 semantic frames
require the server-owned request id and integer sequence, known HTTP failures retain a bounded
status and reason, and the producer rejects frames above the browser's 256 KiB limit.

PostgreSQL and Alembic remain the shared migration authority during these moves. A module or route
migration does not create a second schema owner; service-owned schemas and migration lanes require
a separately reviewed boundary.

## Core and delivery map

- [`services/core-control-plane/src/fdai/core/conversation/`](../../../services/core-control-plane/src/fdai/core/conversation)
  - `coordinator.py` owns the Layer 2 `ConversationCoordinator` orchestration.
  - `tool_arguments.py` owns pure canonical-verb argument parsing and grants no tool authority.
  - `read_plan.py` owns bounded-plan validation, serial read execution, result aggregation, and
    identity-scoped high-signal conflict detection.
  - `contextual_translation.py` owns scalar argument provenance over current and prior turn text.
  - `grounded_answer_validation.py` owns conservative canonical-ID, numeric, timestamp, freshness,
    and exact-reference checks over narration and immutable tool authority.
  - `tools.py` defines `SystemConsoleTool` and implementations that delegate to Layer 1 modules.
  - `narrator.py` defines synchronous intent, contextual, proposal-only read-plan,
    zero-execution clarification, and presentation-only grounded-answer protocols.
  - `session.py` provides the disposable core/CLI `ConversationSession` projection. The
    principal-scoped `ConversationHistoryStore` owns production transcripts.
- [`cli/`](../../../cli)
  - `src/repl.ts` is the IME-safe stdin/stdout channel for the shared `POST /chat` coordinator.
  - `src/cockpit.ts` is the live SSE presentation that publishes a self-describing screen snapshot
    to the same coordinator.
- [`services/core-control-plane/src/fdai/core/conversation/channel_gateway.py`](../../../services/core-control-plane/src/fdai/core/conversation/channel_gateway.py)
  authenticates senders, claims message idempotency keys, calls the coordinator, and persists the
  complete response before provider send when durable delivery is configured.
- [`services/operator-service/src/fdai_operator_service//`](../../../services/operator-service/src/fdai_operator_service/)
  - `teams.py` normalizes Bot Framework activities after bearer-token verification and uses an
    injected reply publisher. It never trusts a payload-supplied reply URL.
  - `slack.py` verifies timestamped signatures, rejects replayed or bot-authored events, normalizes
    messages, and uses an injected reply publisher.
  - Slack, Teams, and web attachment contracts converge through
    [conversation attachments](conversation-attachments.md). A dedicated WebSocket adapter remains
    optional.
- [`current_time.py`](../../../services/operator-service/src/fdai_operator_service/)
  resolves current-time questions from an injected aware clock and principal IANA timezone.

## Operator API route ownership

- `application/conversation/backend/` owns the provider-neutral backend contract, prompt-policy
  error, bounded latency routing, failover, and multimodal dispatch. It does not own provider I/O,
  HTTP, SSE, authentication, or durable state.
- `adapters/conversation/` owns Azure workload-identity and OpenAI-compatible provider calls,
  response validation, metering transport, resolved-model loading, and backend construction. It
  does not own route authorization, JSON or SSE delivery, or conversation history.
- `application/conversation/claims/` owns deterministic claim extraction, evidence matching, and
  evidence manifests. It does not own HTTP, SSE, authentication, or durable state.
- `application/conversation/verification/` owns terminal answer integrity, deterministic evidence
  verification, and bounded verification prose. It does not own HTTP, SSE, authentication,
  cancellation, or durable state.
- `application/conversation/capabilities/inventory/` owns typed inventory queries, compilation,
  semantic grounding, and provider-read coordination. It does not own HTTP, SSE, authentication,
  history, rendering, or inventory writes.
- `application/conversation/evidence/` owns read-only operational evidence resolution, provenance,
  canonical branch ordering, and authority-preserving merge. It does not own HTTP, SSE,
  authentication, cancellation, history, or durable state.
- `application/conversation/post_generation/` owns ordered quality review, verification, terminal
  validation, history persistence coordination, and post-turn review. It does not own HTTP,
  authentication, request parsing, heartbeat framing, SSE sequencing, connection cancellation, or
  transport delivery.
- `application/conversation/request_preparation/` owns content-policy validation and replay,
  preferences, document refs, history assembly, verified prior context, resource and freshness
  context, follow-up scope, answer planning, and target-agent derivation. It does not own Request,
  HTTP status mapping, authorization, SSE sequencing, cancellation, or transport delivery.
- `application/conversation/planning.py` owns bounded shadow planning task start, metadata, and
  drain. `application/conversation/busy_input.py` owns safe-boundary steering and active narrator
  interruption only. Neither owns connection cancellation, core busy-input authority, action
  state, or durable state.
- `application/conversation/capabilities/` owns action, prior-context, current-time, source,
  readiness, knowledge, metering, log, network, subscription-health, T2 recovery, behavior, and
  read-model helpers. `application/conversation/` owns turn and intent-graph planning, prompt
  assembly, public-web intent, and vision validation. Neither package imports `routes`.
- `projections/conversation/presentation/` owns value-free presentation plans, verified evidence
  artifact compilation, bounds, and localized labels. It does not own HTTP, SSE, authentication,
  cancellation, terminal delivery, or durable state.
- `projections/conversation/inventory/` owns inventory evidence sanitization, result projection,
  and deterministic rendering. It does not own provider selection, query compilation, HTTP, SSE,
  authentication, history, or durable state.
- `projections/conversation/terminal/` owns terminal verification-frame and payload assembly,
  measured LLM usage rendering, durable result context, and bounded public terminal summaries. It
  does not own HTTP, SSE sequencing, authentication, cancellation, history, or durable state.
- `projections/conversation/stream_metrics.py` owns queue-accepted aggregate progress reduction.
  It does not own frame sequencing, queue admission, cancellation, transport, or durable state.
- `projections/conversation/` owns incident-dossier and RCA rendering, bounded execution-output
  projection, provider-receipt projection, tool-progress reduction, current-screen T0 rendering,
  redacted model traces, trajectory-detail replay, and resource-follow-up response projection.
  These moved internal helpers have no compatibility shims.
- `routes/chat_stream_request.py` owns authorization, Content-Length and raw-body bounds, JSON-object
  parsing, application-error to HTTP mapping, and the SSE preparation adapter.
- `application/conversation/turn_execution/` owns one-shot JSON request preparation, planning,
  evidence, generation, verification, persistence, metering, and terminal completion through typed
  dependencies and results. It imports no Starlette, route, or provider-adapter module.
- The five-file `chat*.py` structural inventory contains `chat.py`, `chat_registration.py`,
  `chat_stream.py`, `chat_stream_protocol.py`, and `chat_stream_request.py`. `chat.py` owns only
  JSON HTTP transport and compatibility binding. `chat_stream.py` owns only SSE transport and maps
  application revisions into transport-sequenced frames. The other three files remain
  registration, SSE protocol, and request-transport owners respectively.
- `application/conversation/capabilities/knowledge_context.py` reads exact prior-turn runbooks,
  source freshness, consented memory,
  and materialized learning without writing state.
- `application/conversation/vision_prompt.py` projects validated images.
- `routes/` retains JSON and SSE envelopes, authentication, HTTP and SSE status mapping, frame
  sequencing, connection cancellation, route registration, and HTTP handlers for graph,
  data-source, and readiness projections.
- `read_investigation_responder.py` renders registered Heimdall read intents from typed evidence.
  Missing evidence produces an explicit unavailable answer. `read_investigation_catalog.py` blocks
  startup when catalog IDs, ownership, or plan bindings drift.
- `routes/rule_catalog.py` exposes a read-only active/discovery Rule reference projection. It uses
  semantic ranking only from a catalog-matched active generation and otherwise returns lexical
  results with an explicit degraded state. Reader-gated `POST /rules/search` invokes the exact
  `catalog.search_rules` ontology function and returns retrieval plus function receipts without
  evaluation or execution authority. Generation publishing remains outside API startup.

English and Korean presentation literals use NFC UTF-8. Escaped Hangul is accepted only for exact,
rationale-bearing code-point behavior. This representation does not change machine values,
evidence authority, locale selection, or typed-pipeline decisions.

Scheduler Runs, Automation Blueprints, Scheduled Continuations,
[governed trajectory datasets](governed-trajectory-datasets.md), and
[execution backend status](execution-backends.md) expose read-only metadata. These views contain no
enable, submit, retry, cancel, cleanup, execute, or approval controls. They omit credentials and
Thor's identity and keep commands outside the SPA.

[`tools/chat.py`](../../../tools/chat.py) is the headless JSONL development harness for the core
coordinator, not a second policy implementation.

## Boundary invariant

`core/conversation/` imports protocols only. Azure SDK, HTTP, Bot Framework, and provider calls live
under `delivery/`. Conversation presentation never becomes execution authority.

## Related docs

| To learn about | Read |
|----------------|------|
| Console framing, tools, RBAC, and safety | [Operator Console](operator-console.md) |
| Runtime model and DI seams | [Operator Console runtime model](operator-console-runtime-model.md) |
| Durable channel delivery | [Durable conversation delivery](durable-conversation-delivery.md) |
