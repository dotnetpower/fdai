# Document ingestion agent ownership

This document assigns every document-ingestion transition to an FDAI pantheon agent. It keeps the
gateway mechanical and makes admission, indexing, audit, and catalog growth part of the same
agent-driven control loop used for every other event.

> **Scope:** The upload gateway authenticates, streams to quarantine, and seals size and hash. It
> has no judgment authority and its dedicated identity never receives Thor executor permissions.

## Design at a glance

The [declared-intent projection](../rules-and-detection/document-declared-intent-projection.md)
adds an exact-diff approval lane to normal worker and Core bootstrap. Indexing approval still grants
no graph-write authority.
Prior-policy author, requester, and reviewer equality uses canonical principal identity before
approval. Case or surrounding-space variants never create an independent reviewer.

An upload is an `Event`. Authority-bearing stages emit or consume typed logical objects multiplexed
over `fdai.pantheon.objects`; `fdai.pipeline.stages` carries operational activity only. No worker or
gateway side effect can substitute for an owning agent decision.

For the explicit declared-intent kind, the worker stores normalized bytes in its own table and the
existing content-free ready/deleted events drive Core proposal or source-owned rollback. The worker
does not approve or write the private graph; Core cannot bulk-read worker document content.

![Design at a glance. The main stages are Upload event, Huginn - ingress, Heimdall - safety signals, Forseti - admissibility, abandon or deny, Var - human approval, Muninn - retrieval index, Saga - audit seal, Mimir / Norns - catalog growth, Bragi - progress + citation.](../../diagrams/generated/fdai-roadmap-interfaces-document-ingestion-agent-ownership-01.en.svg)

## Ownership map

| Stage | Owning agent | Owned object or basis |
|-------|--------------|-----------------------|
| Ingress - accept the upload as an event | **Huginn** (Event Collector) | `Event`; the upload arrives through an external adapter, not the bus |
| Safety observation - malware, secret, protection, RMS signals | **Heimdall** (Observer) | `Anomaly` or `SecurityEvent` for a malicious, protected, or suspicious upload |
| Admissibility - admit, hold, or abandon | **Forseti** (Judge) | `Verdict`; RMS denial or malware becomes abandon or deny, not a silent gateway drop |
| Human approval - sensitive or authoritative documents | **Var** (Approver) | `Approval`; approval precedes promotion to authoritative knowledge, with no self-approval |
| Retrieval indexing - chunk and embed | **Muninn** (Memory) | `ContextIndex`; the accepted governed version becomes retrievable |
| Audit seal - lifecycle and access decisions | **Saga** (Auditor, hard dependency) | `AuditEntry`; nothing progresses unaudited and the record contains no document text |
| Catalog growth - authoritative documents and recurring patterns | **Mimir** and **Norns** | `Rule`, `Policy`, or `RuleCandidate`; manuals and runbooks can seed reviewed candidates |
| Narration - progress and grounded citation | **Bragi** (Narrator) | `Turn`; renders progress and cites `doc:` sources without making decisions |
| Conflict or rollback - contradicting or bad versions | **Odin** and **Vidar** | `ArbitrationDecision` or `Rollback`; retract or supersede a version |

## Promotion and audit invariants

A newly ingested document is advisory first. Bragi may cite it, but it does not drive a T2 decision
until Forseti admits it, Var approves any sensitive promotion, and Saga seals the audit. This is the
same observation-to-enforcement discipline used by every capability.

The gateway and worker always express a stage transition as the owning agent's typed object. A
transition without an owning agent and Saga audit entry is a defect. A conflict routes to Odin, and
a bad or superseded version retains a Vidar rollback path.

## Ingress implementation

Forseti's auxiliary v1 comparison-input retention uses bounded asynchronous storage without
retaining document bodies. Storage failure preserves the original document-admission verdict and
holds retrospective comparison. It does not alter ingestion purpose, independent approval, Saga
audit, Muninn indexing or Thor's no-action boundary.

The ingress step is wired first. The gateway composition wraps the durable activity sink with a
`PantheonDocumentActivitySink` that promotes the `document.received` transition onto the pantheon
bus as Huginn's owned `object.event`. The `EventBusDocumentIngestionIntake` claims the Huginn
`producer_principal`, partitions by `document_id`, and supplies canonical `event_type`,
`correlation_id`, `idempotency_key`, and `resource_id` fields so Forseti and Heimdall (already
`object.event` subscribers) receive an actionable first-class event. Forseti emits a
`kind = document_ingestion` admissibility verdict with no action type; malformed ingress is held.
Thor explicitly ignores this non-action verdict, so an upload can never create an `ActionRun`.
The delivery layer never holds Thor's executor identity. Saga consumes the document verdict,
appends it to the audit chain, and republishes a content-free `object.audit-entry`. The ingestion
worker consumes only Saga's audited `stage = received`, `decision = admit` record. A plain
`RECEIVED` document is excluded from reconciliation and remains fail-closed until both Forseti and
the Saga hard dependency complete. The worker then stops at `PROTECTION_CHECK` after scan and
protection inspection. Huginn republishes the content-free inspection facts, Heimdall normalizes
them as an `object.anomaly`, Forseti emits the protection verdict, and Saga seals it. A clear,
audited decision reaches Muninn, which alone publishes the `object.context-index` command that
unlocks extraction and indexing; a blocked decision moves the version to `HELD`. In the current
implementation, a clear document with a sensitivity label, `handover_bootstrap`,
`report_line_bootstrap`, `manual_distillation`, or `cloud_reference` purpose
receives a human-approval (`hil`) verdict instead. For `cloud_reference`, a valid package signature
does not replace Var's independent human review and approval. Saga seals that verdict, Var creates
a document approval ticket, and the uploader cannot approve their own document. The independent
reviewer's approval is sealed again by Saga before Muninn can unlock indexing; rejection moves the
version to `HELD`. Thor ignores both document verdicts and approvals. Reconciliation
replays `RECEIVED` and `PROTECTION_CHECK` events with stable idempotency keys but never advances
those gated states. It resumes only post-decision work in `QUARANTINED`, `SCANNING`, `EXTRACTING`,
or `INDEXING`.

### Backpressure and gated-state recovery

Saga separates bounded local queue admission from the audit append's conflict budget. An
authenticated message that exhausts that budget is retained in a durable recovery inbox before
its broker delivery completes. Maintenance retries a bounded page under revision-fenced leases;
no downstream audit seal is published before the append succeeds. Integrity failures still block
the chain. This recovery adds no agent, approval, or execution authority.

Gated-state reconciliation is repeatable, not a completed effect. It releases its replay claim,
rearms an already-published worker outbox fact, and preserves the original payload and idempotency
key. Saga can redeliver the exact already-sealed document decision when its original source fact
is replayed. The worker's multiplexed Kafka consumer batches offset commits across skipped
non-document records on `fdai.pantheon.objects` and flushes on idle poll timeout or decode
dead-letter, so high-volume runtime traffic does not starve `object.audit-entry` or
`object.context-index` delivery. When worker-local stewardship environment variables are absent,
`HandoverBootstrapConsumer` reads the Core-materialized stewardship coverage projection as its
review-only baseline without granting map-write authority. Inspection and indexing effects retain
terminal claim deduplication. Logs identify audit receipt, stage, claim outcome, completion, and
retry using upload UUIDs and exception types, without source names, document text, identities,
broker keys, or exception messages.

Example: a `RECEIVED` upload whose first recovery attempt met audit backpressure remains gated,
then republishes the same ingress fact on a later reconciliation cycle. Only Saga's audited
admission unlocks inspection; handover-purpose indexing still requires Var's independent approval.

Cloud-reference rollback currently provides a manual review request. An `Owner` can submit an
eligible retained version with a higher sequence, preserving source dates and the same independent
approval and indexing gates. Withdrawn or revoked content is not an eligible target. This request
does not establish automatic Vidar recovery after failed activation or failed readback. Automatic
recovery and independent effect verification remain open in the
[cloud lifecycle ledger](../../roadmap-implementation/interfaces/cloud-resource-knowledge-lifecycle.md).

The [structured retrieval extension](cloud-resource-knowledge-structured-rag.md) keeps these owners.
A block, excerpt, format selection, or signature cannot replace Forseti admission, the applicable
Saga-audited Var authorization, or Muninn's index command.

The [requester-initiated application target](cloud-resource-knowledge-lifecycle.md#requester-initiated-application-target)
removes a new per-document human decision only for eligible reference content covered by previously
and independently approved policy. Var would verify that existing human authorization for the exact
request; it would not generate a human review or grant authority to the requester. The intake API
records the actual requester when the request exists, not a person selected during preparation.
The explicit authenticated API lane now binds API-owned administrative policy input through Var's
independent read of persisted authority; Saga audits the distinct prior-policy basis before Muninn
indexes. API/worker direct writes cannot replace that owned choreography. Current per-document
approval remains the default, and no-self-approval stays enforced. Sensitive content and promotion
into decision-authoritative rules or policies keep their own approval requirements. Local source
tests are not production promotion evidence.

The `report_line_bootstrap` purpose produces only grounded, review-only person-to-manager
candidates. One relationship endpoint and an independent Owner must confirm each edge before it
can enter the current reporting graph. See
[Human report lines and approval routing](human-report-lines-and-approval-routing.md).

Protected original-byte downloads remain principal-scoped reads. Their
[purpose-specific provider receipt](document-ingestion.md#purpose-bound-source-download)
authorizes only the exact bounded export, not document admission, index activation, rule
promotion, or an operational action. The gateway uses the existing content-free durable audit
outbox and rechecks current collection and source policy; it never borrows Var or Thor authority.

## Durable worker ownership

Each mechanical worker operation acquires a separate PostgreSQL claim for `(upload_id, stage)`
before it reads or changes lifecycle state. The claim records the worker owner, attempt id,
revision, server-clock claim time, bounded lease expiry, and active, completed, or released status.
It does not add worker authority to `UploadSession` and does not replace the Saga or Muninn gate.

- **Single owner:** Concurrent replicas contend on one row, so only one active unexpired claim can
  run a stage.
- **Fenced completion:** Renew, complete, and release compare the owner, attempt id, and expected
  revision. A stale or crashed worker cannot close a newer attempt.
- **Bounded recovery:** A new attempt can recover an active claim only after its server-time lease
  expires. An explicitly released claim can be retried immediately with a new attempt and revision.
- **Terminal deduplication:** A completed claim cannot be reacquired. Duplicate broker deliveries
  and reconciliation therefore reuse the durable terminal result instead of repeating the stage.
- **Recovery convergence:** Broker redelivery and state reconciliation may race after restart or
  scale-in, but both must acquire the same stage claim before any lifecycle effect.
- **Gate preservation:** Received and protection reconciliation only republishes persisted facts.
  Inspection still requires a Saga-audited admission, and indexing still requires a Muninn-owned
  command or recovery from an already started post-decision state.

Production schedules the upload API and worker as separate Container Apps. This split changes
process lifetime, scaling, managed identity, and database grants only. The API never subscribes to
worker consumer groups, the worker exposes no upload ingress, and neither process gains judgment,
approval, audit, memory, or executor authority from its deployment role. Topic-scoped RBAC lets the worker receive Saga and Muninn objects and send mechanical lifecycle
facts through logical channels on `fdai.pantheon.objects`; the API identity has no worker receive
grant in split mode. Operational progress remains separate on `fdai.pipeline.stages`.
Each process also receives its attached user-assigned identity client id through
`FDAI_MI_CLIENT_ID`. Storage, Event Hubs, model, optional OCR, and stewardship adapters select that
exact identity and do not fall back to an ambient or system-assigned principal.
## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/document-ingestion-agent-ownership.md) |
| Drop-zone, storage, lifecycle, and event contracts | [Document ingestion](document-ingestion.md) |
| Slack, Teams, web chat, protected fetch, and image OCR | [Conversation attachments](conversation-attachments.md) |
| Pantheon role boundaries | [Agent pantheon](../agents/agent-pantheon.md) |
