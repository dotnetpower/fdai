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

## Graduation scorecard

Use the same observation window and candidate revision for every measured row. The minimum window is
30 consecutive days unless a binary privilege requirement makes waiting unsafe. Record raw evidence
links, query versions, source freshness, window start/end, measurement cutoff, candidate revision,
reviewer, digest, approval time, and expiry in the [Architecture Review Board Packet](architecture-review-board.md#ownership-and-support) evidence-binding format.

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
| Conversation channel runtime | Deferred | Durable delivery coordination remains in-process; standalone adapter ingress, identity, persistence binding, and deployment smoke remain unbound. |
| Background read-task executor | Deferred | Durable attempts exist; independent cost/failure trigger and deployed transport evidence are not yet measured. |
| Scheduler, inventory, measurement, and canary jobs | Approved as jobs | Bounded run-to-completion contracts and dedicated identities already justify out-of-band Container Apps Jobs. |
| Authoritative control-loop stages | Rejected as ad hoc services | No stage may split without preserving agent single-writer ownership, hard dependencies, typed pub/sub, and complete execution safeguards. |

## Data ownership matrix

One logical record or lifecycle transition has one writer. Sharing a physical table is allowed only
when the matrix names disjoint transitions or columns and database grants plus revision/CAS checks
enforce the split. A reader never becomes a writer by deployment proximity.

| Data or table | Single write owner | Permitted projection readers | Migration owner |
|---------------|--------------------|------------------------------|-----------------|
| `audit_log` | Saga through the append-only audit store | Operator API audit projections, Norns reviewed intake, verification jobs | Alembic migration job |
| Operator API read projections | No durable write; pure projection code owns request-local values only | Authenticated routes over each named authoritative store | Not applicable |
| Operator API SSE streaming | No durable write; connection-local cursor/backpressure state only | Authorized stage/activity streams and durable replay projections | Not applicable |
| `conversation_record`, `conversation_turn`, `conversation_policy` ([migration 0019](../../../alembic/versions/20260716_0019_user_context_automation.py)) | User-context/conversation application service for the owning principal | Operator API conversation/history projections | Alembic migration job |
| `conversation_image` | Principal-scoped Operator API image repository | Authenticated owning-principal history route | Alembic migration job |
| `conversation_outbound_delivery*`, `conversation_adapter_breaker` | Durable conversation-delivery coordinator | Operator API delivery status and channel adapters for claimed work | Alembic migration job |
| `background_task_attempt`, `background_task_progress`, `background_task_completion` ([migrations 0040/0051](../../../alembic/versions/20260720_0040_background_task.py)) | Background-task coordinator/store | Owner-scoped Operator API projections and completion delivery | Alembic migration job |
| `scheduled_task`, `schedule_dispatch_run`, `scheduled_conversation_anchor` | Scheduler service/store for definitions and one CAS-claimed dispatch run | Operator API scheduler/run projections and continuation delivery | Alembic migration job |
| `inventory_snapshot*`, `inventory_active` | Inventory synchronization job for full-snapshot promotion | Core inventory provider and authorized Operator API inventory projections | Alembic migration job |
| `inventory_realtime_resource`, `inventory_realtime_link` | Realtime inventory projector for normalized provider events | Inventory materializer and authorized graph projections | Alembic migration job |
| `measurement.*` append-only audit/state namespaces | Measurement runner through its append-only audit and namespaced StateStore providers | Promotion review, KPI, and Operator API measurement projections | Shared StateStore/Alembic migration owner |
| Canary broker event and resulting terminal audit | Canary job writes the synthetic event; the normal agent pipeline and Saga own resulting state/audit | Startup/deployment verification and health projections | Event schema owner; no canary table |
| `document_upload_session`, `document_version` - create/upload/received/cancel transitions | Document ingestion API service | Ingestion API status/search authorization and worker processing | Alembic migration job |
| `document_upload_session`, `document_version` - quarantined through terminal processing transitions | Document ingestion worker | Ingestion API status/search projections | Alembic migration job |
| `document_worker_claim` | Document metadata claim CAS under the ingestion worker role | Reconciliation and operational diagnostics | Alembic migration job |
| `knowledge_chunk` for governed documents | Document ingestion worker/index adapter | Authorized Operator API search projection | Alembic migration job |
| `state_kv` namespaced records | The subsystem named by each key namespace | Explicit projections named by that subsystem's provider contract | Alembic migration job |
| Agent-owned control-loop objects and topics | The single pantheon agent declared for each object type | Registered typed subscribers and cited read projections | Shared contract/catalog owner; no service-local migration |

A new candidate must add its data rows before implementation. A row with two overlapping writers,
"shared service" as owner, or an unnamed migration path blocks graduation.

## Cross-process contract matrix

| Contract | Schema owner | Producer | Consumers | Partition key | Compatibility | Retry, DLQ, idempotency, retention |
|----------|--------------|----------|-----------|---------------|---------------|------------------------------------|
| Document Saga audit event `1.0.0` | [Document audit schema](../../../src/fdai/shared/contracts/document-worker-audit/schema.json) | Saga | Ingestion audit-gated worker | `upload_id` | Additive fields; old/new producer-consumer tests | At-least-once; invalid records to sibling DLQ; [stage claim](../../../alembic/versions/20260806_0075_document_worker_claims.py) is idempotency fence; event 1 day, DLQ 7 days |
| Document Muninn index command `1.0.0` | [Document index schema](../../../src/fdai/shared/contracts/document-worker-index/schema.json) | Muninn | Ingestion index worker | `upload_id` | Additive fields; unsupported versions fail closed | At-least-once; invalid records to sibling DLQ; completed index claim is terminal dedupe; event 1 day, DLQ 7 days |
| Document lifecycle activity | [Document activity contract](../../../src/fdai/delivery/ingestion_gateway/activity.py) | Ingestion API or worker for its owned transition | Audit/progress consumers and Huginn ingress bridge | `document_id` | Content-free additive event envelope | Stable action/version idempotency; reconciliation republishes persisted facts; event 1 day, DLQ 7 days |
| Operator command/proposal event | [Event](../../../src/fdai/shared/contracts/event/schema.json) and [Action](../../../src/fdai/shared/contracts/action/schema.json) contracts | Operator API command identity | Huginn/Forseti typed pipeline | normalized `resource_id` | Registry semver and additive compatibility | At-least-once; catalog idempotency key; normal event/DLQ retention 1/7 days |
| Agent introspection request/reply | [Agent-introspection transport](../../../src/fdai/delivery/agent_introspection_bus.py) | Bragi/Operator API bridge | Addressed agent and bounded reply consumer | correlation id | Versioned request/reply envelope before process split | Bounded timeout/retry, no authority, content-redacted failure, broker retention 1 day |
| Executor command `1.0.0` and receipt `1.0.0` / `1.1.0` | [Executor transport](../../../src/fdai/shared/contracts/models/executor_transport.py) | Core Thor execution port | Isolated Executor and Core receipt client | exact target resource ref | `1.0.0` receipts remain no-effect; additive `1.1.0` reports dispatch but cannot claim independent verification | At-least-once, poison DLQ, stable Core consumer group, provider plus executor idempotency, normal/DLQ retention 1/7 days |

Contract retention is not audit retention. Event Hubs currently retains normal entities for 1 day
and sibling DLQs for 7 days in the [Event Hubs module](../../../infra/modules/event-bus/event-hubs-kafka/main.tf); durable state and audit follow their own governed retention policies.

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
| Channel adapter/runtime | Channel secret and bounded message transport only | None | Deployment-specific ingress process when complete |
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
