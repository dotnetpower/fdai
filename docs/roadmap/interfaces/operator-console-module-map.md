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
[`test_operator_api_layout.py`](../../../tests/delivery/operator_api/test_operator_api_layout.py)
also pins the exact default method, path, and route-name set plus representative HTTP envelopes.
An intentional default route addition updates this reviewed baseline in the same change.

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

Internal route and test consumers import the explicit package facade. The only retained
`routes.chat_verification` module is a compatibility facade because the capability catalog still
names that source path; it contains no verification implementation. Rollback restores the moved
modules under `routes/` and redirects the package facade without changing JSON, SSE, authentication,
or conversation-history behavior.

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
| `adapters/` | Concrete Operator API provider implementations outside HTTP routes | Keep provider I/O behind application contracts. |
| `adapters/conversation/` | Azure and OpenAI-compatible narrator transports and startup construction | Import through its explicit facade; keep credentials and transport outside routes. |
| `app/` | Shared ASGI assembly, middleware, registration, and lifespan | Retain as the HTTP composition boundary. |
| `application/` | Typed process-local, non-authoritative application coordination | Retain until service-graduation evidence justifies a process boundary. |
| `application/conversation/` | Process-local conversation capabilities outside HTTP transport | Retain in-process until service-graduation evidence exists. |
| `application/conversation/capabilities/` | Typed process-local conversation capabilities grouped by domain | Retain as the non-authoritative capability owner. |
| `application/conversation/capabilities/inventory/` | Typed inventory queries, deterministic compilation, semantic grounding, and provider-read coordination | Import through its explicit package facade; keep JSON, SSE, authentication, and history in routes. |
| `application/conversation/backend/` | Provider-neutral backend contracts and request-local latency routing | Import through its explicit facade; keep provider implementations in adapters. |
| `application/conversation/claims/` | Deterministic answer-claim extraction and bounded evidence verification | Import through its explicit package facade; keep JSON, SSE, and authentication in routes. |
| `application/conversation/verification/` | Deterministic terminal answer verification and bounded evidence rendering | Import through its explicit package facade; keep wire behavior and authentication in routes. |
| `dev/` | Interactive local and test-only provider composition | Keep unavailable to production imports. |
| `dev/fixtures/` | Synthetic pytest-only fixtures | Keep outside production composition. |
| `persistence/` | Operator API read-model implementations and projections | Retain behind owned read contracts. |
| `projections/` | Read-only projection ownership outside HTTP routes | Retain as the owner of migrated families. |
| `projections/audit/` | Audit query and autonomy/FinOps measurement projections | Import through its explicit facade; keep old route modules as shims. |
| `projections/conversation/` | Request-local conversation read projections outside HTTP transport | Retain in-process until service-graduation evidence exists. |
| `projections/conversation/presentation/` | Value-free layout selection and verified evidence artifact compilation | Import through its explicit facade; keep JSON and SSE behavior in routes. |
| `projections/conversation/inventory/` | Inventory evidence sanitization, result projection, and deterministic rendering | Import through its explicit facade; keep query compilation and provider coordination in the application package. |
| `production/` | Production provider construction and bindings | Reduce fanout incrementally without changing wire behavior. |
| `routes/` | Mixed HTTP adapters, coordination, projections, and policy helpers | Move one measured family at a time; don't bulk-move chat before its typed service boundary. |
| `streaming/` | Read-only SSE transport, redaction, fanout, and runtime projection | Retain until versioned relay and replay contracts exist. |

`fdai.delivery.operator_api.main` is the public app facade. `read_model` remains a public delivery
contract until a reviewed replacement exists. `fdai.delivery.auth` owns framework-neutral bearer
and Entra verification; `operator_api.auth` and `operator_api.entra_verifier` are compatibility
facades only.
The `main` facade's `busy_input_runtime` re-export is a transitional public seam rather than a new
runtime ownership claim.
`routes.panels` and `routes.reporting` remain transitional public extension seams because current
fork and reporting guidance imports them directly. Other individual `routes.*` modules are
internal implementation paths; `routes.chat_verification` is the classified source-path facade for
the capability catalog. A migration uses a per-module forwarding shim only when a classified
compatibility need exists. Runtime-owned agent-state records and event-bus publication
live in `fdai.delivery.agent_activity`, so the headless runtime imports no Operator API streaming
implementation. Provisioning's `streaming.provision_stream` compatibility remains classified
separately. Issue 71 closes the chat wire debts recorded by the baseline. Version 1 semantic frames
require the server-owned request id and integer sequence, known HTTP failures retain a bounded
status and reason, and the producer rejects frames above the browser's 256 KiB limit.

PostgreSQL and Alembic remain the shared migration authority during these moves. A module or route
migration does not create a second schema owner; service-owned schemas and migration lanes require
a separately reviewed boundary.

## Core and delivery map

- [`src/fdai/core/conversation/`](../../../src/fdai/core/conversation)
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
- [`src/fdai/core/conversation/channel_gateway.py`](../../../src/fdai/core/conversation/channel_gateway.py)
  authenticates senders, claims message idempotency keys, calls the coordinator, and persists the
  complete response before provider send when durable delivery is configured.
- [`src/fdai/delivery/channels/`](../../../src/fdai/delivery/channels)
  - `teams.py` normalizes Bot Framework activities after bearer-token verification and uses an
    injected reply publisher. It never trusts a payload-supplied reply URL.
  - `slack.py` verifies timestamped signatures, rejects replayed or bot-authored events, normalizes
    messages, and uses an injected reply publisher.
  - Slack, Teams, and web attachment contracts converge through
    [conversation attachments](conversation-attachments.md). A dedicated WebSocket adapter remains
    optional.
- [`chat_current_time.py`](../../../src/fdai/delivery/operator_api/routes/chat_current_time.py)
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
- `projections/conversation/presentation/` owns value-free presentation plans, verified evidence
  artifact compilation, bounds, and localized labels. It does not own HTTP, SSE, authentication,
  cancellation, terminal delivery, or durable state.
- `projections/conversation/inventory/` owns inventory evidence sanitization, result projection,
  and deterministic rendering. It does not own provider selection, query compilation, HTTP, SSE,
  authentication, history, or durable state.
- `chat_stream_setup.py` owns authenticated request, evidence, history, and answer-plan validation.
- `chat_stream_terminal.py` owns pure terminal verification-frame and replay-payload assembly.
- `chat_trajectory_detail.py` owns bounded final progress projection for durable trajectory replay.
- `chat_knowledge_context.py` reads exact prior-turn runbooks, source freshness, consented memory,
  and materialized learning without writing state.
- `chat_vision_prompt.py` projects validated images.
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
