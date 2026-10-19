---
title: Approved Document Intent Projection
---
# Approved Document Intent Projection

This design owns the bounded approved-document intent namespace for #2256 G02 and child Task
#2268. It connects normalized governed envelopes to independent exact-diff approval, persistent
ontology records, current source-aware queries, and recovery.

> **Implemented boundary:** The Core SDK and typed agent flow support explicit machine-authored
> `BusinessService` intent records. Synthetic provider/directory input is tested with actual
> PostgreSQL and owning agents. This is not raw upload/Console E2E or deployment qualification.
>
> **Authority boundary:** Intent is not provider truth, telemetry, policy, or execution permission.
> No new agent, execution identity, ActionType, authority registry, or provider mutation is added.
> Existing ingestion/indexing approval keeps its original meaning.

## Design at a glance

The private namespace uses the pinned `BusinessService` declaration and existing secured
ObjectSet query contract. Its rows never enter common `ontology_resource` observation storage.
Authority remains the API-owned source and Var's existing durable approval. New SQL tables contain
provenance, an outbox, and a source-owned read model, not an alternative authority registry.

| Stage | Owner | Existing topic |
|-------|-------|----------------|
| Source and readiness | Huginn, then Muninn | `object.event`, `object.context-index` |
| Candidate and independent verification | Norns, then Mimir | `object.rule-candidate`, `object.rule` |
| Admissibility and audit | Forseti, then Saga | `object.verdict`, `object.audit-entry` |
| Exact-diff review and audit | Var, then Saga | `object.approval`, `object.audit-entry` |
| Atomic materialization | Muninn | `object.context-index` |
| Independent readback and audit | Heimdall, then Saga | `object.retrieval-validation`, `object.audit-entry` |
| Source-owned recovery | Vidar | `object.rollback` |
| Held conflict | Forseti, then Odin | `object.arbitration-request`, `object.arbitration-decision` |

Messages use `document_intent_projection` and immutable content-bound identities. General bus and
audit records contain opaque references, not source bodies or proposed properties. Thor ignores
this family. Odin holds for review; it cannot override source ownership, access, or exact approval.

## Admissible source and approval

The first slice accepts one normalized structural unit containing JSON with exactly two keys:
`kind: fdai.declared-intent.business-service.v1` and `properties`. Properties are the declaration's
scalar `id`, `name`, `criticality`, `effective_from`, optional `effective_to`, and immutable
`source_ref`. The id starts with `service:`. This is a typed data contract, not lexical inference
from prose. Arbitrary prose, extra properties, other types, links, observed health, and execution
permissions are not admissible here; their existing review-only distillation path is unchanged.

The source is current, active, available, unprotected governed knowledge with active indexing,
live retention, and `manual_distillation` purpose. The complete normalized-envelope commitment,
source hash, document/version, ACL, scope, and effective interval are checked. Purpose alone grants
no projection authority.

`DocumentIntentRuntime.submit` binds the authenticated requester and exact add/update revision.
`review_diff` gives an independently authorized reviewer the complete immutable diff. The separate
non-action `document.review-intent-diff` Var ticket binds that digest. Current review role and
source access are required; uploader and requester cannot approve. Ingestion approval, a message
claiming approval, or a handover receipt cannot replace Var's durable final record.

## Atomic persistence, replay, and recovery

The Core migration owns `document_intent_projection`, `document_intent_transition`, and
`document_intent_resource`. Core uses a restricted security-definer metadata function over the
API-owned `document_version`, not raw document SELECT. Operator cannot read private tables.
Diff/envelope identity and transition bodies are immutable.

One transaction locks current source metadata, exact durable approval, the private target, and
source-owned provenance. It checks source/ACL revision, release, target revision, independent
reviewer, candidate, decision, and Saga seals. Before-image, new revision, and publication intent
commit with the record. A foreign owner, stale input, missing stage, or altered replay holds without
partial writes. Identical replay does not advance the revision; restart republishes retained
content-bound events rather than reapproving or reapplying.

Heimdall independently opens committed storage and compares the effect with the approved diff.
An audited mismatch reaches Vidar. Recovery restores the exact before-image with a monotonic
revision or removes only the exact newly created row. A changed target holds for Odin; unrelated
writes survive. Restored content never restores revoked source access. A withdrawal notification
can re-observe an applied packet and retire it through the same audited flow.

## Current authorized queries and remaining integration

`document_intent_gateway` binds a server-authenticated principal to actual PostgreSQL source
metadata and the current directory reader. It rechecks every contributing source before and after
execution; Owner cannot bypass source ACL. The first namespace supports at most 64 active records.
Over-bound, incomplete, changed, expired, or inaccessible sets return unavailable or denied, never
a silently partial count. Generation names start with `document-intent:`. The private adapter
rejects writes. A restarted reader reauthorizes instead of trusting a retained approval or result.

The command boundary starts at an already governed `DocumentEnvelope`. Automatic Ingestion
API/worker routing, protected review UI, common graph/query-manifest exposure, and source-aware
cached-result reuse outside this private namespace are not implemented. Do not claim an uploaded
raw file is queryable through ordinary Console or conversation. Deployment, live corpus/model
evidence, elapsed observation, and promotion remain separate gates.

## Related docs

| To learn about | Read |
|----------------|------|
| Broader proposal lifecycle | [Document ontology distillation](document-ontology-distillation.md) |
| Existing source ownership | [Document ingestion agent ownership](../interfaces/document-ingestion-agent-ownership.md) |
| Evidence and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/document-declared-intent-projection.md) |
