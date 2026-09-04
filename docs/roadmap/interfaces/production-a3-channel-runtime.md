---
title: Production A3 Channel Runtime
---
# Production A3 Channel Runtime

This document owns the production Teams and Slack A3 conversation edge: authenticated ingress,
bounded provider publishing, lifecycle composition, durable recovery, deployment isolation, and
rollback. It completes transport around the channel-neutral conversation and presentation
contracts without creating another judgment or execution surface.

> **Scope:** A3 reads and draft-only requests are in scope. Slack A1 approval, A2/A4 notification
> policy, document semantic transport, inline vision, and unrelated channel backlog remain with
> their existing owners.
>
> **Topology:** The runtime is an authority-free edge adapter workload built from the existing
> Operator Service distribution. It is not a sixth independently releasable control-plane
> distribution, uses the Operator migration branch and conversation table writer, and never
> receives Thor's identity.
>
> The shared migration ownership manifest remains table-specific. Core-owned Cost Governance
> activation and analytics tables do not become Operator channel tables and grant no channel-edge
> write authority.
>
> Forward Operator migrations grant projection retention workers `UPDATE` only on immutable lock-key
> columns required by `FOR UPDATE SKIP LOCKED`. Table-wide projection update authority remains denied.

## Design at a glance

The edge accepts only provider-authenticated requests, replaces vendor identity with one configured
FDAI principal, and claims the provider message in the Operator-owned inbound ledger. It submits a
typed semantic request through `SemanticTurnBridge.append()`, waits for the principal-scoped
terminal projection through `SemanticTurnBridge.open()`, and compiles one presentation artifact.
A schema-v3 artifact may carry a server-selected operational brief or Markdown document layout plus
bounded dynamic-assembly metadata. The edge validates the complete SHA-256-bound render surface,
reduces it to the provider's existing channel-neutral sections, and degrades modified or unsupported
artifacts to canonical text. Schema v1 and v2 stack artifacts remain replay-compatible.
A `direct_response` projection compiles validated model-authored text without evidence,
verification, or artifact claims, so Slack and Teams preserve the same authority-free response as
the Console instead of substituting a channel template.
Operator-owned durable delivery persists that artifact before a pure provider publisher sends it.
Startup resolves every required dependency and reconciles uncertain sends before Starlette accepts
traffic.

![Design at a glance. The main stages are Slack signed event, Slack ingress, Teams service token, Teams ingress, Bounded Operator edge queue, SemanticTurnBridge append, Core semantic EventBus runtime, SemanticTurnBridge open, Operator delivery ledger, Pure capability renderer, Slack publisher, Teams publisher.](../../diagrams/generated/fdai-roadmap-interfaces-production-a3-channel-runtime-01.en.svg)

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| A3 edge design and ownership | implemented | [Issue #235](https://github.com/dotnetpower/fdai/issues/235); this document pair; Operator source and deployment roots | The authority-free Operator-distribution design is implemented. Governed provider and deployment evidence remain open. |
| Authenticated ingress and provider publishers | implemented | `fdai_operator_service/families/conversation/channel_edge/`; focused edge checks (`81 passed`) | Operator-local Slack and Teams adapters enforce canonical-principal replacement, bounded admission, URL-free attachment metadata, fixed destinations, strict token audiences, and definitive-versus-ambiguous acknowledgement classification. The standalone runtime binds both route families. |
| Operator migration and persistence | implemented | `operator_a3_channel_delivery_20260819`; `channel_{delivery_models,message_ledger}.py`; `postgres_channel_{binding,delivery}.py`; live PostgreSQL checks (`9 passed`, no skips) | The Operator branch owns the inbound processing lease and grants the Operator role only the six channel tables. Runtime-role tests prove lease reclaim, permanent dedupe, binding uniqueness, idempotent delivery, claim and acknowledgement closure, process-loss ambiguity, breaker CAS, and retention cleanup. The standalone lifespan binds these stores. |
| Semantic request, result, and durable delivery pipeline | implemented | `semantic_turn_runtime.py`; `channel_edge/{pipeline,pipeline_contracts,worker}.py`; focused edge checks; live PostgreSQL join (`1 passed`, no skips) | The Operator edge resolves server-owned scope, persists typed semantic requests, waits for principal-scoped terminal replay, stores the terminal response before provider I/O, completes inbound ownership only after durable delivery, and fences retry and process-loss recovery with persisted breakers. Due sends revalidate the active principal, scope, conversation, and channel binding before provider I/O. |
| Principal-scoped conversation documents | implemented | `document_export.py`; authenticated document routes; semantic outbox source binding; focused Operator checks | A document draft replays only the authenticated principal's preceding verified result. Partial or unsupported content produces no download, while complete bounded tables can be regenerated as Markdown and optional PDF without execution authority. |
| Fail-closed runtime and local/Azure workload | implemented | `channel_edge/{application,composition,entry,environment,runtime}.py`; `.vscode/tasks.json`; platform and service Terraform roots; protected deployment workflows and helpers; focused checks | Platform can prepare the dedicated non-executor identity and Operator DSN access without provider credentials. The independent service root still requires principal scopes and one complete Slack or Teams Key Vault contract before creating the edge workload. |
| Independent hardening | implemented | [Hardening campaign](#hardening-campaign); focused edge checks (`81 passed`); Ruff and strict mypy | Ten independent rounds completed with focused regressions for every accepted finding and no verified Medium-or-higher residual. Protected runtime evidence remains a separate validation gate. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-19 | in-progress | Accepted the authority-free edge-workload design after critique rejected both Operator API co-hosting and a sixth service distribution. | `current change`; [Issue #235](https://github.com/dotnetpower/fdai/issues/235); route, tracking, translation, and link checks. | Implement, harden, validate, and retain governed local and deployed receipts. |
| 2026-08-19 | implemented | Added the Slack A3 exact-body verifier, closed workspace/sender admission, opaque file normalization, bounded queue adapter, fixed Web API publisher, and strict definitive-versus-ambiguous acknowledgement parsing. | `current change`; focused Slack, renderer, and gateway checks passed 76 cases; Ruff, formatting, strict mypy, and editor diagnostics passed. | Implement the Teams transport and production runtime composition before claiming an enabled A3 path. |
| 2026-08-19 | implemented | Added fixed-algorithm Bot Framework token verification over bounded injected JWKS, exact tenant/principal/service-URL admission, URL-free file normalization, an authenticated endpoint registry, bounded queueing, fixed Connector paths and audience, and strict acknowledgement parsing. Queue rejection leaves no endpoint binding. | `current change`; focused channel and gateway checks passed 92 cases; Ruff, formatting, strict mypy, and editor diagnostics passed. | Add durable stores and fail-closed runtime composition before enabling either transport. |
| 2026-08-19 | withdrawn | Withdrew the Core-owned channel persistence slice after service ownership validation showed that conversation delivery tables belong to Operator Service and the frozen root Alembic chain cannot accept revision 0087. | Root migration head restored to `20260819_0086`; legacy inventory restored to 88 revisions and 105 tables; focused Core migration checks passed 200 cases and service-migration checks passed 47 cases. | Rebuild persistence and edge composition in the Operator distribution without a Core table writer. |
| 2026-08-19 | in-progress | Corrected the edge to the Operator distribution, reused the existing semantic-turn EventBus bridge, and added the inbound claim plus exact channel-table grants to the Operator service migration branch. | `current change`; `operator_a3_channel_delivery_20260819`; ownership manifest; service-migration checks passed 47 cases; loopback Operator branch upgraded to the new head. | Implement Operator-local stores, transports, lifecycle, workload, hardening, and governed runtime evidence. |
| 2026-08-19 | implemented | Added Operator-local inbound claim, verified binding, outbound delivery, attempt, acknowledgement, retention, and breaker stores without importing Core implementation or adding another writer. | `current change`; live loopback PostgreSQL checks passed 9 cases with no skips through the Operator runtime role; Ruff, formatting, and strict mypy passed. | Move the provider transports to Operator ownership and compose the semantic bridge plus fail-closed lifespan. |
| 2026-08-19 | implemented | Moved authenticated Slack and Teams transport into the Operator distribution and composed deterministic inbound replay, semantic terminal projection, durable ownership, provider acknowledgement closure, retry work, process-loss reconciliation, and persisted breaker admission. | Commit `3555ecf9c`; `current change`; focused channel checks passed 32 cases, pipeline and worker checks passed 10 cases, the runtime-role PostgreSQL join passed 1 case with no skips, and Ruff plus strict mypy passed. | Bind the dependencies in a fail-closed Starlette lifespan, add local and deployed workloads, remove the superseded Core prototypes, and retain governed evidence. |
| 2026-08-20 | implemented | Added the standalone fail-closed Starlette workload, private local launch, optional Operator-service Container App, dedicated non-executor identity and least-privilege roles, Key Vault references, probes, and rollback metadata. Removed the superseded Core transports and Core PyJWT dependency. | `current change`; edge package checks passed 74 cases; shared plus Operator channel checks passed 110 cases; local launch checks passed 3 cases; Ruff and strict mypy passed; platform and Operator-service Terraform validation passed. | Complete independent hardening, then retain governed local provider and protected plan/apply/rollback evidence. |
| 2026-08-28 | implemented | Split platform identity/DSN preparation from independent Operator principal/provider configuration after staging planning showed the former incorrectly required the latter. The existing DSN role-assignment address is preserved and duplicate explicit input is removed by set union. | Failed plan-only runs `33111410162` and `33112559478`; `current change`; focused platform, service-root, and deployment checks. | Supply protected principal/provider references before enabling and validating the service workload. |
| 2026-08-20 | implemented | Completed ten independent hardening rounds. Accepted fixes reject platform-out-of-range Slack timestamps without a server error, disable inherited shell tracing before local secrets are read, refresh known Teams JWKS keys after a bounded TTL, revalidate active principal/scope/conversation/channel bindings before due sends, and close owned runtime and credential resources exactly once. | `current change`; focused edge checks passed 81 cases; Ruff and strict mypy passed; every accepted finding has a focused regression. | Retain governed local provider and protected plan/apply/rollback receipts before advancing runtime rows to `validated`. |
| 2026-08-20 | implemented | Closed exact-commit structural findings by assigning every A3 test to the Operator service suite, routing venue selection through the shared `ExecutionVenue` contract, and removing retired Core prototype paths from the A3 design route. | `current change`; focused service-suite, venue-contract, design-route, environment, and composition checks. | Retain governed local provider and protected plan/apply/rollback receipts before advancing runtime rows to `validated`. |
| 2026-08-20 | implemented | Closed the protected-delivery gap that rejected the separate edge Container App. Platform plans now bind the dedicated identity and secret scopes, while Operator service plans seal explicit edge enable or disable transitions, exact target identity and image, new-revision health, route removal, and an automatic disabled-state rollback before primary revision recovery. | `current change`; protected service deployment and workflow contract suites passed `126 + 28` cases; workflow YAML and rollback shell syntax passed. | Supply one real Slack or Teams provider credential and principal-mapping profile through the approved credential stores, then retain local provider and protected plan/apply/rollback receipts. |
| 2026-08-20 | implemented | Re-reviewed the protected rollout for implicit actions, plan substitution, public-route survival, secret exposure, identity substitution, and recovery ordering. One accepted finding moved disable route-removal proof before primary health; eight suspected findings were rejected against separate primary/edge resources, exact transition sealing, and terminal rollback checks. No verified Medium-or-higher implementation residual remains. | `current change`; route-closure and automatic rollback checks passed 2 cases after the focused fix; the full protected deployment suites had already passed 154 cases. | Runtime validation still requires real provider material and governed receipts; it is not an implementation residual. |
| 2026-09-01 | implemented | Bound terminal semantic claims and read activities to exact completed Core receipts before the Operator or A3 delivery path can expose them. Query arguments and provider output values no longer enter the terminal execution record; it carries only a bounded capability identity, status, duration, output availability, completeness, and truncation state. | `current change`; focused Core and Operator semantic suites passed 207 cases; Conversation Assurance contract checks passed 78 cases; Ruff and formatting passed. | Retain governed channel-delivery evidence only after the existing provider and deployment prerequisites are available. |

### Remaining work

- [x] Implement every scope row and pass the focused checks in this document; retain exact-diff evidence with the focused commit.
- [x] Complete at least ten critique rounds and retain only Low or rejected residual findings.
- [ ] Configure one real Slack or Teams provider profile and principal mapping through local-only
  inputs, Key Vault, GitHub secret configuration, and versionless secret-id variables without
  exposing a value in repository or workflow output.
- [ ] Retain governed local and protected deployed plan/apply/provider-acknowledgement/rollback
  receipts before changing any row to `validated`.

## Architectural decision

### Why an edge workload

Three placements were evaluated:

| Placement | Decision | Reason |
|-----------|----------|--------|
| Operator API process co-hosting | Rejected | Channel secrets, public webhook ingress, and provider acknowledgement would widen the authenticated read API process blast radius. |
| Sixth independently releasable service distribution | Rejected | It would reopen the completed five-distribution N/N-1, migration, image, and rollback program without a new domain writer or implementation-isolation need. |
| Existing Operator distribution, separate edge Container App | Accepted | It isolates public ingress and channel credentials while reusing the owning conversation writer, service migration branch, and typed semantic EventBus bridge without cross-service implementation imports. |

The edge workload is independently runnable and can scale separately, but package, writer, and
migration ownership remain with Operator Service. Core receives only the versioned semantic request
and returns only the versioned semantic projection through EventBus. This deployment distinction
does not change the fixed five service distributions or the fifteen-agent pantheon.

## Ingress and publishing

### Slack

Slack ingress verifies the exact raw request body with the configured signing secret, provider
timestamp, constant-time comparison, and a five-minute replay window. It accepts only URL
verification and non-bot message events. A bot event, retry duplicate, unsupported subtype,
malformed body, unknown sender, or oversized message never enters the queue.

Normalized files retain only an opaque file id, safe leaf name, positive byte size, and media-type
hint. Payload URLs are discarded. Private download remains behind the existing server-owned
fetcher and protected-ingestion contract.

Slack publishing uses fixed `chat.postMessage` and `chat.update` endpoints, a startup-resolved bot
token, the pure Block Kit renderer, the inbound channel/thread identity, and strict `ok=true` plus
message timestamp acknowledgement. The response cannot supply a URL, token, or API method.

### Teams

Teams ingress validates the Bot Framework bearer token before parsing operator identity. The
authenticator verifies RS256 against bounded cached JWKS, application audience, approved issuer,
`exp` and `nbf`, and the service URL claim. The activity must also match the configured tenant,
`channelId=msteams`, verified service URL, and a configured `aadObjectId` to FDAI principal map.
The cache refreshes after five minutes even for a known key, so a key removed from the current JWKS
cannot remain accepted for the process lifetime.

Teams publishing resolves only the authenticated service URL allowed for the conversation, obtains
a Bot Framework audience token from the injected workload identity, uses the pure Adaptive Card
renderer, and requires a bounded resource id acknowledgement. Activity payloads cannot select a
different host or token audience.

### Queue and bounds

Each adapter owns one bounded queue. Queue saturation returns a provider-appropriate retry response
without accepting the turn. Request bytes, text, files, fields, identities, provider responses,
and serialized card/block payloads have independent limits. Unsupported input fails before queue
admission. No error includes request bodies, sender ids, file names, credentials, or provider text.

## Durable delivery

Legacy migration `20260720_0047` remains unchanged. The Operator branch revision
`operator_a3_channel_delivery_20260819` adds the inbound claim table and exact role grants. The
Operator-local PostgreSQL adapters implement:

- verified principal binding create/read/revoke/list operations;
- immutable response insert with idempotency-content conflict rejection;
- `FOR UPDATE SKIP LOCKED` due claims and lease-fenced finish;
- attempt and acknowledgement persistence in the same transaction as state closure;
- process-loss conversion from expired `sending` to immutable `ambiguous`;
- revisioned adapter breaker compare-and-set;
- processing leases that can be reclaimed after expiry and completed claims that permanently
  suppress provider redelivery.

Database grants keep the edge on those six channel tables only. It receives no audit append, ontology,
policy, Action, executor, or managed-resource grant. Durable response JSON round-trips artifact
version, layout, assembly metadata, facts, limitations, evidence references, activities, progress,
and thread intent exactly.

## Runtime lifecycle

`ChannelEdgeRuntime` is composed in the top-level Starlette lifespan:

1. Validate the closed environment/config schema and enabled channel set.
2. Resolve secret references and identity dependencies without logging values.
3. Open PostgreSQL and the owned HTTP client with redirects disabled and bounded timeouts.
4. Build authenticated adapters, principal resolvers, protected attachment ingestion, semantic
  bridge, presentation compiler, delivery coordinator, and fixed routes.
5. Reconcile expired `sending` rows before marking readiness true or accepting traffic.
6. Start one supervised gateway consumer per enabled adapter.
7. On shutdown, stop route admission, close queues, cancel and await consumers, close providers
  exactly once, and leave no detached read or send task.

Startup fails before traffic when any enabled channel lacks a secret, principal map, identity,
endpoint policy, database, attachment dependency, or durable delivery binding. `/health/live` and
`/health/ready` report only content-free process state. They expose no channel, principal, endpoint,
credential, delivery, or queue identifiers.

## Deployment and rollback

Local launch adds one edge process on a dedicated nonstandard backend port and keeps the standard
Console and Operator ports unchanged. Local and deployed use the same routes, stores, auth checks,
renderers, queue bounds, reconciliation, and health contract. Local secrets remain local-only and
the full-stack launcher fails closed when an enabled channel is not configured.

Azure uses a separate Container App from the existing Operator Service image with:

- dedicated user-assigned managed identity and no executor roles;
- Key Vault references for channel secret values;
- external HTTPS ingress only on the A3 webhook and content-free health surface;
- minimum and maximum replicas, CPU/memory, request-size limits, and startup/readiness/liveness
  probes;
- service-owned PostgreSQL role and no cross-service implementation package;
- structured logs and aggregate delivery metrics without content or identity.

Protected deployment follows the existing VNet runner path. Rollback restores the prior disabled
or prior-image edge revision without changing Core, Operator API, offsets, migration heads, or
channel bindings. The primary Operator and edge workloads accept only a healthy active rollback
baseline and retain one inactive revision so the captured source remains restorable after apply. A
rollback rehearsal proves route closure, no duplicate terminal send, exact identity roles, and five
existing service revisions unchanged.

The protected rollout uses two state owners. The platform plan first creates only the dedicated
edge identity and its ACR, Event Hubs, and versionless Key Vault secret roles. The Operator service
plan then seals one explicit `enable`, standard image update, or `disable` transition for the edge
Container App in the existing Operator backend. Exact apply verifies the edge resource id, one
workload identity, attested image, fresh healthy revision, and HTTPS readiness. A failed first
enable applies a guarded disabled-state plan before restoring the primary Operator revision, so a
partially created public route cannot survive automatic recovery.

## Failure behavior

| Failure | Required behavior |
|---------|-------------------|
| Invalid signature or service token | Return `401`; enqueue nothing. |
| Valid service, unknown tenant or principal | Return `403`; enqueue nothing. |
| Malformed or oversized request | Return `400` or `413`; retain no body. |
| Queue full | Return bounded retry status; do not claim the message. |
| Duplicate provider event | Acknowledge without coordinator, ingestion, or send replay. |
| Provider rejection before acknowledgement | Record definitive failure for bounded retry. |
| Interrupted or malformed acknowledgement | Record immutable ambiguous duplicate risk; never repost automatically. |
| Process loss with `sending` lease | Startup reconciliation closes it as ambiguous before consumers start. |
| Unsupported artifact or provider capability | Send canonical readable text with mandatory limitations, evidence, authority, and unavailable state. |
| Attachment dependency unavailable | Fail startup when attachment support is enabled; otherwise reject that turn without inline processing. |

## Hardening campaign

Run at least these independent rounds after implementation. A round ends only after each finding is
reproduced or rejected against executable evidence. Every accepted Medium-or-higher finding gets a
focused regression and a new round rechecks the corrected boundary.

1. Slack signature, timestamp, replay, challenge, retry, and bot-loop handling.
2. Teams JWT, JWKS cache/refresh, issuer/audience/time, tenant, service URL, and principal binding.
3. Body, queue, attachment, text, field, block, card, response, and aggregate byte bounds.
4. Secret, token, endpoint, identity, payload, log, error, and metric redaction.
5. Principal/scope/thread binding, cross-channel continuity, self-substitution, and confused deputy.
6. PostgreSQL CAS, duplicate, reorder, concurrent claim, lease expiry, process loss, and immutable terminal state.
7. Publisher fixed destinations, acknowledgement parsing, edit/thread fallback, and duplicate risk.
8. Startup all-or-none composition, readiness, shutdown cancellation, task leaks, and dependency failure.
9. Local/deployed parity, identity roles, public ingress, Key Vault references, probes, and rollback.
10. Contract/version replay, v1/v2/v3 artifact degradation, assembly-integrity rejection, canonical
    fact parity, and no execution authority.

Continue beyond round ten while any verified Medium-or-higher finding remains. Final review records
Low tradeoffs separately and never promotes unit or synthetic evidence to deployed validation.

The 2026-08-20 campaign completed all ten rounds. Accepted findings are the bounded Slack timestamp,
local secret tracing, Teams JWKS freshness, due-delivery binding revalidation, and idempotent runtime
and credential shutdown fixes recorded in the implementation history. Rejected findings included a
missing Operator migration, unbounded duplicate processing, payload-selected destinations, a sixth
distribution, executor authority, TCP-only liveness, and v2 artifact incompatibility; the owning
migration, deterministic durable ids, fixed endpoints, Operator-distribution topology, no-authority
contracts, HTTP probes, and version-aware normalization disproved them. No verified Medium-or-higher
residual remains.

## Verification

Focused checks include adapter unit tests, ASGI route tests, PostgreSQL live tests, gateway and
durable-delivery suites, boundary/import checks, Terraform validation, local process smoke, and
protected deployed plan/apply/rollback receipts. Every focused commit runs
`make test-changed DIFF=<commit>^..<commit>` after commit.

## Related docs

| To learn about | Read |
|----------------|------|
| Channel categories, trust, and rich rendering | [Channels and notifications](channels-and-notifications.md) |
| Durable bindings and delivery recovery | [Durable conversation delivery](durable-conversation-delivery.md) |
| Attachment safety and private fetch | [Conversation attachments](conversation-attachments.md) |
| Service graduation and identity ownership | [Service graduation and data ownership](../architecture/service-graduation-and-ownership.md) |
