---
title: Service Graduation and Data Ownership
---
# Service Graduation and Data Ownership

This document decides when an FDAI package may become an independently deployed service. It also
assigns cross-process contracts, durable data, identities, and migrations so a process split cannot
create hidden authority or a second writer.

> **Decision scope:** A package boundary does not imply a service. Graduation requires one measured
> forcing trigger and every readiness gate below. Missing evidence means defer; an authority,
> ownership, transport, or rollback violation means reject.
>
> **Evidence scope:** Synthetic tests prove mechanics. Production scale increases require current
> staging or live smoke evidence from the exact image, topology, identity, schema, and contract
> versions being promoted.
>
> **Program target:** The active decomposition program ends with five runtime services. The
> Isolated Executor is a required target, but it receives effect authority only after every binary
> gate passes. Missing evidence blocks program completion; it does not authorize an unsafe cutover.

## Design at a glance

A candidate is **approved** only when at least one scaling, privilege-isolation, or failure-isolation
trigger is met and every contract, durability, observability, cost, and rollback gate passes. It is
**deferred** when no trigger is measured or evidence is incomplete. It is **rejected** when the split
would create direct agent calls, shared mutable coordination, multiple writers, executor-identity
spread, an unversioned wire contract, or no tested rollback. The current deployment has five runtime
services with the Isolated Executor in shadow mode. The tracked cutover removes mutation roles from
Core only after the exact live evidence closes.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Five-service graduation decisions and authority cutover | validated | `config/service-decomposition.json`; `config/independent-services.json`; [Service Decomposition evidence log](service-decomposition-execution-plan.md#evidence-log) | The required and approved service candidates completed exact topology, identity, health, rollback, and remote transition evidence. |
| Single-writer data ownership and service migration branches | validated | `service-migrations/branches/`; independent-service adoption and peer-isolation evidence in the execution plan | Five migration branches and service roles retain disjoint writer ownership across the protected N/N-1/N transition. |
| Versioned cross-process contracts and isolated identities | validated | `packages/service-contracts/`; `infra/services/`; IS-03, IS-05, IS-07, and IS-09 evidence | Service distributions consume the shared contract SDK without importing another service implementation, and only the isolated Executor can hold effect authority. |
| Deferred and rejected future candidates | deferred | [Candidate decisions](#candidate-decisions) | Operator application/read/SSE splits and background read tasks remain deferred until their measured forcing triggers and complete gate evidence exist. The A3 channel edge is accepted as a non-distribution adapter workload with separate implementation gates. Ad hoc control-loop service splits remain rejected. |
| Boundary docstring enforcement | implemented | `scripts/quality/architecture/check-boundary-docstrings.py`; SD-09 evidence | All reviewed decomposition scopes enforce the structural docstring contract. Semantic correctness still depends on focused architecture tests. |
| Temporal Incident roster projection | implemented | `core_incident_projection_20260819`; `operator_incident_projection_read_20260819`; focused migration and Operator checks | An Alembic-owned trigger derives temporal versions inside the append-only audit transaction. Core and Executor roles receive no direct projection write grant, while the Operator role receives SELECT only. |
| Read-investigation request transport | implemented | `fdai-service-contracts` `read-investigation-request` `1.0.0`; Operator CAS outbox; Core consumer and optional coordinator; focused cross-process tests | Operator owns durable proposal acceptance and publication. Core owns request consumption and background-task state. The coordinator remains an optional Core runtime component, not a sixth service. |
| Read-investigation completion transport | in-progress | `fdai-service-contracts` `read-investigation-completion` `1.0.0`; Core completion outbox publisher; Operator inbox, Web conversation writer, `operator_read_investigation_completion_20260826`, and `operator_completion_retention_20260829` | The five-service topology is unchanged. Core never writes Operator conversation tables. Operator atomically owns the inbox and idempotent Web assistant turn, then purges only deadline-expired inbox rows in bounded batches. Channel outbound enqueue and governed deployment evidence remain open. |
### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | validated | Adopted the implementation ledger without reconstructing pre-ledger design history and recorded the completed five-service evidence separately from deferred future candidates. | `current change`; machine manifests, service migration branches, shared contracts, and retained transition evidence cited in the scope table. | Re-evaluate only the deferred candidates whose observable forcing triggers and complete scorecard evidence become available. |
| 2026-08-15 | validated | Renamed the object Norns owns from `PatternObservation` to `Pattern`, so the agent spec, the registered topic, the pantheon tables, and the Console agent contract name one record. | `current change`; `PANTHEON_SPECS`, `agents/_framework/topics.py`, `console/src/routes/agents.model.ts`; focused pantheon layout, doc-parity, and catalog suites passed. | Nothing produces the record yet; publication or retirement is tracked in the prediction-learning ledger. |
| 2026-08-19 | implemented | Added a rebuildable temporal Incident roster projection without creating an Operator writer or another service. The database trigger runs in the Saga audit append transaction, closes the prior correlation version, and inserts the next as-of version; the Operator branch only grants read access after the Core schema prerequisite exists. | `current change`; [Issue #169](https://github.com/dotnetpower/fdai/issues/169); local PostgreSQL migration, trigger, temporal-cursor, platform-exclusion, and role-grant checks passed; focused Operator and service-migration suites passed 117 cases. | Retain deployed latency evidence after the protected migration and service rollout. |
| 2026-08-19 | in-progress | Corrected the accepted A3 edge from Core package and migration ownership to a separate workload in the Operator distribution, which already owns the conversation writer and semantic EventBus bridge. | `current change`; `operator_a3_channel_delivery_20260819`; [Production A3 channel runtime](../interfaces/production-a3-channel-runtime.md); service-migration checks passed 47 cases. | Complete the A3 implementation, hardening, and governed runtime evidence without adding a sixth distribution. |
| 2026-08-20 | implemented | Completed the non-distribution A3 edge implementation and ten-round hardening campaign inside the Operator distribution without changing the five-service inventory or executor authority. | `current change`; [Production A3 channel runtime](../interfaces/production-a3-channel-runtime.md); focused edge checks passed 81 cases; Ruff and strict mypy passed. | Retain governed provider and protected deployment evidence before classifying the edge runtime as validated. |
| 2026-08-20 | implemented | Closed distribution and Console catalog parity exposed by the A3 rollout: Operator now declares its direct `azure-core` dependency, visible release headings are allowlisted, and every canonical resource type has an explicit architecture layer, color, and abbreviation. | `current change`; focused service-distribution and Console catalog checks; Console typecheck; frozen lock check. | Protected A3 deployment evidence remains open. |
| 2026-08-20 | implemented | Restored enforced module-size boundaries without changing service ownership: vertical identity configuration moved to the existing bootstrap binding owner, and pure inventory row and graph projection helpers moved beside the PostgreSQL snapshot provider. | `current change`; 54 focused bootstrap tests, 28 loopback inventory tests, strict mypy, Ruff, and the full file-size gate. | No runtime behavior or authority change remains for this refactor. |
| 2026-08-20 | implemented | Corrected the bootstrap size refactor to preserve its tested private vertical-identity seam and moved only the logical topic registry to a focused runtime module. | `current change`; 55 focused bootstrap and identity-seam tests; Ruff and formatting; bootstrap at 792 lines. | No runtime behavior or authority change remains for this correction. |
| 2026-08-20 | implemented | Registered the extracted topic module in the Core wheel contract and gave the reviewed unclassified resource type an explicit abbreviation distinct from the fallback reserved for unknown types. | `current change`; focused Core wheel and Console architecture checks. | No package or Console catalog parity work remains for this correction. |
| 2026-08-23 | in-progress | Defined the versioned, no-authority `read-investigation-request` transport from the Operator-owned durable outbox to the Core-owned background-task coordinator without promoting that coordinator to another service. | `current change`; this owner document and [Azure Read Investigations](../interfaces/azure-read-investigations.md). | Implement N/N-1 codecs, outbox publication, Core consumption, duplicate/restart tests, and production composition before claiming the path executable. |
| 2026-08-23 | implemented | Implemented exact `1.0.0` request and cancellation codecs, Operator CAS publication, Core persistence-before-wake consumption, duplicate and poison handling, optional coordinator composition, and local/deployed logical-topic configuration without changing the five-service topology. | `current change`; the focused cross-process, background-task, PostgreSQL, Operator, topic, and local-environment gate passed 152 cases with no skips or warnings. | Define the versioned terminal completion transport and retain governed restart, deployment, and rollback evidence. |
| 2026-08-23 | implemented | Replaced independent start and cancellation partition keys with the canonical owner-scoped background-task lifecycle identity. Start and cancel records for one task now share one partition, while Core revalidates the same identity before persistence or cancellation. | `current change`; focused contract and transport checks passed 22 cases, including direct start/cancel partition equality; task-scoped Ruff and strict mypy passed. | Define the reverse terminal completion contract without adding an Operator conversation writer to Core. |
| 2026-08-26 | in-progress | Bound the reverse completion contract to the Core outbox and Operator-owned writer. The Operator migration grants conversation writes and inbox sequence use; one transaction deduplicates the proposal, Web assistant turn, and inbox row without changing service topology or Core authority. | `current change`; focused Operator readiness, completion store, and migration privilege checks passed. | Add channel outbound enqueue, retention purge, and governed deployment/rollback evidence. |
| 2026-08-29 | implemented | Added the Operator-owned completion inbox retention worker and a follow-on migration granting delete only on that inbox. Cleanup uses the contract deadline, a bounded batch, deadline ordering, and `SKIP LOCKED`; a failed purge keeps Operator readiness closed without blocking completion ingestion. | `current change`; `postgres_read_investigation_completion.py`; `read_investigation_completion_runtime.py`; `operator_completion_retention_20260829`; focused completion, composition, migration, and service-inventory checks. | Add verified channel outbound enqueue, then retain governed restart, deployment, and rollback evidence. |
### Remaining work

- [x] No work remains for the approved five-service topology; its graduation, writer ownership, identity isolation, rollback, and remote transition evidence is retained in the decomposition program.
- [ ] Re-evaluate Operator application, read-projection, and SSE candidates only after one candidate records a scorecard forcing trigger and all binary gate evidence on one pinned revision.
- [ ] Retain governed provider and protected deployment evidence for the implemented
	non-distribution A3 edge through its owner design. Re-evaluate only the background read-task
	executor as a future service candidate after it has independent transport, identity,
	persistence, cost/failure evidence, deployment smoke, and rollback.
- [x] Add and implement the versioned terminal read-investigation completion row through the Core
	publisher, Operator inbox, and idempotent Web conversation writer.
- [x] Purge only deadline-expired completion inbox rows through the Operator-owned bounded retention
	worker and prove invalid limits, naive clocks, migration ownership, and cleanup failure readiness.
- [ ] Complete the matrix's channel outbound enqueue claim in
	[Durable Conversation Delivery](../interfaces/durable-conversation-delivery.md), then retain
	governed deployment and rollback evidence.

## Graduation scorecard

Use the same observation window and candidate revision for every measured row. The minimum window is
30 consecutive days unless a binary privilege requirement makes waiting unsafe. Record raw evidence
links, query versions, source freshness, window start/end, measurement cutoff, candidate revision,
reviewer, digest, approval time, and expiry in the
[ARB Evidence and Authority](architecture-review/evidence-and-authority.md#evidence-bindings)
binding format.

| Gate | Approval threshold | Evidence source |
|------|--------------------|-----------------|
| Scaling trigger | p95 CPU >= 70% or p95 memory >= 75% in three separate 30-minute windows per week for 2 weeks; or queue-delay p95 exceeds its SLO in 3 windows | Container Apps / OpenTelemetry resource metrics and queue dashboard |
| Privilege trigger | Split removes at least one cloud role assignment, secret, database write grant, or public ingress permission from the parent process | Terraform plan, identity graph, database privilege query |
| Failure trigger | Candidate caused at least 2 independently reviewed incidents or >= 10% of the parent service error-budget burn in 90 days | Incident ledger, SLO burn report, post-incident review |
| Typed transport | Every cross-process message has an owner, versioned schema, producer, consumers, stable partition key, additive compatibility policy, retry/DLQ, idempotency rule, and retention | Contract registry, compatibility tests, event-bus configuration |
| Durability | Process loss, duplicate, reorder, scale-out, and scale-in tests produce zero duplicate terminal effects and no skipped authority gate | Durable store/CAS tests and restart smoke |
| Observability | Independent liveness/readiness plus latency, queue/lag, error, retry, DLQ, and ownership-conflict signals; required alerts route to an accountable owner | Health probes, telemetry catalog, alert rules, runbook |
| Cost | Monthly incremental cost is measured and inside the approved environment budget; a delta > 20% of the parent service cost requires FinOps approval | Terraform cost estimate and measured billing baseline |
| Rollback | Staging rehearsal restores the prior topology within 15 minutes with no offset reset, data loss, duplicate terminal effect, or authority change | Timed rollback receipt and post-rollback smoke |
| Identity ceiling | The new role has a dedicated identity when privileges differ, and no non-executor role can obtain Thor's identity or executor roles | Terraform identity/RBAC assertions and effective-access probe |

Two graduated services may multiplex versioned logical channels over one physical Event Hub when
each keeps its own schema, producer identity, logical topic, hashed consumer group, readiness,
offset ownership, and DLQ routing. Sharing the broker entity never merges service ownership or
health and does not satisfy a graduation gate by itself.

No weighted score compensates for a failed binary gate. An approved split records the exact evidence
cutoff and expires after 90 days if deployment has not started; it must then be re-evaluated.

## Candidate decisions

These decisions apply the scorecard to the current package and process candidates from the Operator
API inventory and deployed application shape.

| Candidate | Current decision | Reason and next evidence |
|-----------|------------------|--------------------------|
| Isolated Executor | Required program target; cutover gated | Privilege isolation is the forcing trigger. Versioned command/receipt transport, durable duplicate/reorder/restart behavior, independent telemetry, cost, effective access, exact-topology smoke, and timed rollback must pass before effect authority moves from Core. |
| Operator API `application` services | Deferred | Typed in-process boundary exists; no independent scale, privilege, or failure trigger is measured. |
| Operator API read projections | Deferred | Read-only package ownership is clear, but no scale trigger or independent store is justified. |
| Operator API SSE streaming | Deferred | Requires a versioned relay/replay contract and measured connection isolation benefit. |
| Document ingestion API | Approved | Privilege and scaling isolation, typed transport, role-scoped database access, probes, and co-host rollback are implemented. |
| Document ingestion worker | Approved | Durable lease/CAS claims, restart/reorder/DLQ tests, internal health, dedicated identity, and scale gate are implemented. |
| Conversation channel runtime | Accepted as an edge adapter workload, not a sixth distribution | Public provider-authenticated ingress and channel-secret isolation are the forcing trigger. It uses the Operator distribution, conversation writer, migration branch, and semantic EventBus bridge; receives a dedicated no-executor identity; and must pass [Production A3 channel runtime](../interfaces/production-a3-channel-runtime.md). |
| Background read-task executor | Deferred as a separate service | Durable attempts exist. The first production binding runs as an optional Core coordinator over versioned transport; independent service graduation still requires measured cost/failure triggers and the complete scorecard. |
| Scheduler, inventory, measurement, and canary jobs | Approved as jobs | Bounded run-to-completion contracts and dedicated identities already justify out-of-band Container Apps Jobs. |
| Authoritative control-loop stages | Rejected as ad hoc services | No stage may split without preserving agent single-writer ownership, hard dependencies, typed pub/sub, and complete execution safeguards. |

The service-owned Operator parity manifest includes the authenticated read-only
`/agents/activity` projection. This ownership does not change the deferred graduation decision or
grant the route decision, approval, or execution authority.

## Data ownership matrix

One logical record or lifecycle transition has one writer. Sharing a physical table is allowed only
when the matrix names disjoint transitions or columns and database grants plus revision/CAS checks
enforce the split. A reader never becomes a writer by deployment proximity.

| Data or table | Single write owner | Permitted projection readers | Migration owner |
|---------------|--------------------|------------------------------|-----------------|
| `audit_log` | Saga through the append-only audit store | Operator API audit projections, Norns reviewed intake, verification jobs | Alembic migration job |
| Operator API read projections | No durable write; pure projection code owns request-local values only | Authenticated routes over each named authoritative store | Not applicable |
| `operator_incident_projection` | Core-owned database trigger as a derived transition of each Saga/Executor audit insert; no runtime role has direct write access | Authenticated Operator Incident roster and attention projections | Core service migration; Operator service read grant |
| Operator API SSE streaming | No durable write; connection-local cursor/backpressure state only | Authorized stage/activity streams and durable replay projections | Not applicable |
| `conversation_record`, `conversation_turn`, `conversation_policy` ([migration 0019](../../../alembic/versions/20260716_0019_user_context_automation.py)) | User-context/conversation application service for the owning principal | Operator API conversation/history projections | Alembic migration job |
| `conversation_image` | Principal-scoped Operator API image repository | Authenticated owning-principal history route | Alembic migration job |
| `conversation_outbound_delivery*`, `conversation_adapter_breaker`, `conversation_channel_message_claim` | Operator durable conversation-delivery coordinator | Operator API delivery status and Operator edge adapters for claimed work | Operator service migration branch |
| `background_task_attempt`, `background_task_progress`, `background_task_completion`, `background_task_projection_outbox` ([migrations 0040/0051/0088](../../../alembic/versions/20260720_0040_background_task.py)) | Background-task coordinator/store | Owner-scoped Operator API projections and completion delivery | Alembic migration job |
| `read_investigation_run`, `read_investigation_run_progress`, `read_investigation_run_completion` | Core interactive read-investigation coordinator/store | Owner-scoped Operator API replay and completion delivery | Core service migration; Operator service read grant |
| `scheduled_task`, `schedule_dispatch_run`, `scheduled_conversation_anchor` | Scheduler service/store for definitions and one CAS-claimed dispatch run | Operator API scheduler/run projections and continuation delivery | Alembic migration job |
| `inventory_snapshot*`, `inventory_active` | Inventory synchronization job for full-snapshot promotion | Core inventory provider and authorized Operator API inventory projections | Alembic migration job |
| `inventory_realtime_resource`, `inventory_realtime_link` | Realtime inventory projector for normalized provider events | Inventory materializer and authorized graph projections | Alembic migration job |
| `measurement.*` append-only audit/state namespaces | Measurement runner through its append-only audit and namespaced StateStore providers | Promotion review, KPI, and Operator API measurement projections | Shared StateStore/Alembic migration owner |
| Canary broker event and resulting terminal audit | Canary job writes the synthetic event; the normal agent pipeline and Saga own resulting state/audit | Startup/deployment verification and health projections | Event schema owner; no canary table |
| `document_upload_session`, `document_version` - create/upload/received/cancel transitions | Document ingestion API service | Ingestion API status/search authorization and worker processing | Alembic migration job |
| `document_upload_session`, `document_version` - quarantined through terminal processing transitions | Document ingestion worker | Ingestion API status/search projections | Alembic migration job |
| `document_worker_claim` | Document metadata claim CAS under the ingestion worker role | Reconciliation and operational diagnostics | Alembic migration job |
| `knowledge_chunk` for governed documents | Document ingestion worker/index adapter | Authorized Operator API search projection | Alembic migration job |
| `document_api_outbox` | Document ingestion API for API-owned lifecycle and deletion-request events | API outbox drainer | Document ingestion API migration branch |
| `document_worker_outbox` | Document processing worker for worker-owned lifecycle events | Worker outbox drainer | Document processing worker migration branch |
| `executor_receipt_outbox` | Isolated Executor for terminal receipt delivery | Executor receipt drainer | Isolated Executor migration branch |
| `state_kv` namespaced records | The subsystem named by each key namespace | Explicit projections named by that subsystem's provider contract | Alembic migration job |
| Agent-owned control-loop objects and topics | The single pantheon agent declared for each object type | Registered typed subscribers and cited read projections | Shared contract/catalog owner; no service-local migration |

A new candidate must add its data rows before implementation. A row with two overlapping writers,
"shared service" as owner, or an unnamed migration path blocks graduation.

Direct and streamed read execution remains inside the existing Core distribution. Core alone
selects the mode before provider I/O and writes run, progress, cancellation, and completion-outbox
transitions. Operator authenticates proposals and cancellation commands, reads those tables with an
owner predicate under SELECT-only grants, and owns conversation or channel materialization after the
versioned completion handoff. Transport disconnect detaches a replay subscriber and grants no state
transition authority.
## Cross-process contract matrix

| Contract | Schema owner | Producer | Consumers | Partition key | Compatibility | Retry, DLQ, idempotency, retention |
|----------|--------------|----------|-----------|---------------|---------------|------------------------------------|
| Document Saga audit event `1.0.0` | [Document audit schema](../../../services/core-control-plane/src/fdai/shared/contracts/document-worker-audit/schema.json) | Saga | Ingestion audit-gated worker | `upload_id` | Additive fields; old/new producer-consumer tests | At-least-once; invalid records to sibling DLQ; [stage claim](../../../alembic/versions/20260806_0075_document_worker_claims.py) is idempotency fence; event 1 day, DLQ 7 days |
| Document Muninn index command `1.0.0` | [Document index schema](../../../services/core-control-plane/src/fdai/shared/contracts/document-worker-index/schema.json) | Muninn | Ingestion index worker | `upload_id` | Additive fields; unsupported versions fail closed | At-least-once; invalid records to sibling DLQ; completed index claim is terminal dedupe; event 1 day, DLQ 7 days |
| Document deletion request `1.0.0` | `fdai-service-contracts` packaged JSON Schema | Document ingestion API | Document processing worker | `document_id` | Additive fields; unsupported versions fail closed | Transactional API outbox; exact upload/version revision fence; worker stage-claim dedupe; invalid records to sibling DLQ |
| Document lifecycle activity | [Document service contract](../../../packages/service-contracts/src/fdai_service_contracts/document.py) | Ingestion API or worker for its owned transition | Audit/progress consumers and Huginn ingress bridge | `document_id` | Content-free additive event envelope | Stable action/version idempotency; reconciliation republishes persisted facts; event 1 day, DLQ 7 days |
| Operator command/proposal event | [Event](../../../services/core-control-plane/src/fdai/shared/contracts/event/schema.json) and [Action](../../../services/core-control-plane/src/fdai/shared/contracts/action/schema.json) contracts | Operator API command identity | Huginn/Forseti typed pipeline | normalized `resource_id` | Registry semver and additive compatibility | At-least-once; catalog idempotency key; normal event/DLQ retention 1/7 days |
| Operator semantic turn `1.2.0` | `fdai-service-contracts` semantic request and projection codecs | Operator API durable outbox / Core semantic runtime | Core semantic consumer / Operator projection consumer | `request_id` | N accepts `1.0.0`, `1.1.0`, and `1.2.0`; no downgrade of a `1.2.0` payload | At-least-once; idempotent producer; manual commit after projection persistence; malformed JSON to sibling DLQ; durable request/projection dedupe |
| Read investigation request `1.0.0` | `fdai-service-contracts` request codec | Operator API durable proposal outbox | Core read-investigation consumer and Core-owned background-task coordinator | canonical `task_id` derived from owner plus creation idempotency key | Exact `1.0.0`; unsupported versions fail closed; additive successors require N/N-1 codec tests | At-least-once; start and cancel for one task share a partition; Operator CAS claim closes only after broker acceptance; malformed records go to a sibling DLQ; Core revalidates the partition identity, deduplicates by owner plus idempotency key, and commits transport only after durable task or terminal run-ledger persistence; normal/DLQ retention 1/7 days |
| Read investigation completion `1.0.0` | `fdai-service-contracts` completion codec | Core-owned background-task completion outbox | Operator completion consumer, inbox, conversation writer, and durable outbound delivery | canonical `task_id` | Exact `1.0.0`; additive successors retain N/N-1 decoders and never downgrade a newer payload | At-least-once; Core closes its completion only after broker acceptance; malformed records go to a sibling DLQ; unmatched records receive bounded retry before quarantine; one Operator transaction deduplicates inbox, turn, and outbound enqueue; normal/DLQ retention 1/7 days and durable purge follows the contract deadline; rollback preserves both outboxes and every accepted Operator record |
| Agent introspection request/reply | [Agent-introspection transport](../../../services/core-control-plane/src/fdai/delivery/agent_introspection_bus.py) | Bragi/Operator API bridge | Addressed agent and bounded reply consumer | correlation id | Versioned request/reply envelope before process split | Bounded timeout/retry, no authority, content-redacted failure, broker retention 1 day |
| Executor command `1.0.0` and receipt `1.0.0` / `1.1.0` | [Executor transport](../../../services/core-control-plane/src/fdai/shared/contracts/models/executor_transport.py) | Core Thor execution port | Isolated Executor and Core receipt client | exact target resource ref | `1.0.0` receipts remain no-effect; additive `1.1.0` reports dispatch but cannot claim independent verification | At-least-once, poison DLQ, stable Core consumer group, provider plus executor idempotency, normal/DLQ retention 1/7 days |

Contract retention is not audit retention. Event Hubs currently retains normal entities for 1 day
and sibling DLQs for 7 days in the [Event Hubs module](../../../infra/modules/event-bus/event-hubs-kafka/main.tf); durable state and audit follow their own governed retention policies.

Service baseline adoption verifies more than the legacy Alembic head. The migration dispatcher
compares a checked-in fingerprint of each service's owned tables, ordered columns, constraints, and
required PostgreSQL extensions with submitted evidence and the live database catalog before it
stamps a service baseline. Rollback starts only from the exact service branch head, targets the
exact baseline, rechecks the resulting schema fingerprint and head, and writes a timestamped JSON
receipt that points to a resolvable persisted rollback artifact.

## Identity and deployment matrix

| Deployment role | Identity and permissions | Executor authority | Ingress / shape |
|-----------------|--------------------------|--------------------|-----------------|
| Core Control Plane | Decision, audit-intent, recovery, and event-transport roles; the current deployment temporarily carries the executor UAMI until cutover | None after cutover | Internal headless Container App |
| Isolated Executor | Executor UAMI plus registered action-specific roles | Sole eligible holder after cutover | Internal event-driven Container App |
| Operator API read role | Read UAMI, projection stores, no command transport | None | Authenticated public API |
| Operator API command role | Event-transport send/receive only for governed requests | None; requests re-enter typed gates | Attached to Operator API composition |
| Ingestion API | Upload/search DB role, ADLS upload/delete, Event Hubs send | None | Public HTTPS Container App |
| Ingestion worker | Worker DB role, ADLS processing, Event Hubs send/receive, embedding/OCR | None | Internal Container App with ClamAV |
| Ingestion migration | Administrator DSN read and ACR pull for `alembic upgrade head`; identity attaches only to the run-to-completion job | None | Manual Container Apps Job |
| Operator channel edge workload | Operator conversation role, channel secrets, and bounded message transport only | None | Separate public ingress process from the Operator distribution |
| Scheduled jobs | Job-specific identity and minimum required data-plane role | None unless a typed action returns to Thor | Run-to-completion Container Apps Jobs |

Runtime, environment, evidence profile, and fork status cannot convert any non-executor identity
into executor authority.

## Boundary docstring contract

The AST checker applies only to exact reviewed architectural modules. It does not infer semantic
truth and does not scan generated code, fixtures, trivial helpers, or package markers without
architectural responsibility. A scoped module docstring uses these non-empty sections:

- **Responsibility:** one reason the boundary exists.
- **Boundary:** inputs/outputs and behavior that must remain outside.
- **Authority and state:** decisions or writes it may perform, authority it cannot hold, and durable state owner.
- **Dependencies:** contracts or composition inputs it may depend on.
- **Deployment:** process or package role and whether it creates a network boundary.

Scope configuration selects `report` or `enforce`. Report findings are visible but non-blocking.
A scope moves to enforce after its accountable owner confirms all five sections against imports,
state writes, identities, and process wiring and no exclusion remains. Exact justified exclusions may suppress an
existing gap; missing files, exclusions outside the scope, and exclusions left after compliance are
stale and fail the checker. Passing the AST checker proves structure and non-empty text only;
architecture review and executable tests remain responsible for semantic accuracy.

## Related documents

| To learn about | Read |
|----------------|------|
| Five-service work packages and progress | [Service Decomposition Execution Plan](service-decomposition-execution-plan.md) |
| Repository packages and dependency boundaries | [Project Structure](project-structure.md) |
| Azure process shape and rollback | [Deploy and Onboard](../deployment/deploy-and-onboard.md) |
| Operator API baseline inventory | [Operator Console Module Map](../interfaces/operator-console-module-map.md) |
| Agent single-writer authority | [Agent Pantheon](../agents/agent-pantheon.md) |
