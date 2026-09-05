---
title: Document Lifecycle Governance
---
# Document Lifecycle Governance

This document defines how FDAI keeps temporary uploads disposable, promotes reviewed content into
governed knowledge, tracks every derived artifact, and verifies deletion across storage and indexes.

> **Scope:** retention durations, quotas, audiences, and legal-hold policy are deployment-owned
> values. The upstream repository defines typed states, safety invariants, and provider seams only.

## Design at a glance

Every source starts with an explicit disposition. Temporary content stays scope-bound and expires
unless a human promotes it through a new immutable governed version. Deletion removes visibility
first, then converges every lineage-bound artifact, and reports completion only after independent
zero-residue verification.

## Design revision

**Initial design.** Give chat attachments a TTL, retain knowledge documents, and cascade physical
deletion to vectors and OCR output.

**Critique.** A TTL alone ignores active conversations, citations, legal holds, and process loss.
Two retention classes cannot represent drafts or regulated evidence. Physical deletion before a
tombstone creates a retrieval race. Reference counting alone misses crash-created orphans, while
unconditional PDF image retention expands cost and privacy exposure.

**Revised design.** Use independent disposition, content, index, retention, and availability axes.
Apply a bounded lease to temporary content, create a new immutable version on promotion, represent
derivatives as a content-addressed artifact graph, tombstone before cleanup, and combine durable
cleanup effects with a bounded mark-and-sweep reconciler and independent purge receipt.

## Independent lifecycle axes

| Axis | Values |
|------|--------|
| Disposition | `session_ephemeral`, `workspace_draft`, `governed_knowledge`, `regulated_record` |
| Content | existing `DocumentState` upload, inspection, extraction, ready, failure, and deletion states |
| Index | `not_requested`, `queued`, `building`, `active`, `tombstoned`, `purged`, `failed` |
| Retention | `live`, `expiring`, `held`, `tombstoned`, `purge_pending`, `purged` |
| Availability | existing `active` and `available` flags, closed before cleanup begins |

Retrieval requires an active, available version with `index_state = active`,
`retention_state = live`, a matching scope, and current access authorization. No other combination
can enter ranking or model context.

## Disposition and retention

| Disposition | Intended use | Default scope | Promotion |
|-------------|--------------|---------------|-----------|
| `session_ephemeral` | chat attachment or test upload | principal plus conversation | explicit human request |
| `workspace_draft` | team draft awaiting review | workspace collection | reviewed collection request |
| `governed_knowledge` | reusable knowledge source | collection policy | already governed |
| `regulated_record` | audit, legal, or approval evidence | dedicated restricted collection | separate regulated workflow |

A deployment calculates temporary expiry from an idle lease and a hard maximum lifetime. Reads do
not extend the hard maximum. Legal hold changes retention to `held` and blocks source, derivative,
index, cache, and backup deletion. Quotas are enforced by principal, conversation, collection,
stored bytes, OCR pages, and embedding count.

## Promotion

Promotion never mutates a temporary record into permanent knowledge:

1. Recheck current actor, target collection, audience, purpose, classification, and retention.
2. Revalidate source digest, malware, protection, and extraction evidence.
3. Create a new immutable governed document version with explicit lineage to the temporary source.
4. Reuse bytes only inside the same tenant, collection, access descriptor, and retention boundary.
5. Activate the governed index only after policy and required human review receipts are durable.
6. Preserve the temporary citation until its conversation expires; never silently rewrite evidence.

## Artifact graph

`DocumentArtifactManifest` binds each derived object to one document version and source digest.
Entries can represent source, native text, page raster, embedded image, OCR text, thumbnail,
normalized envelope, chunk, and embedding. Each retained entry carries its parent, digest, locator,
media type, size, retention deadline, and storage state.

PDF and Office extraction follows these rules:

- Extract native text first and classify each page as text, image, or mixed.
- Rasterize and OCR only pages that need it.
- Keep page rasters and embedded images only when an approved multimodal purpose requires them.
- Prefer on-demand thumbnails with a short cache lease.
- Persist lineage and extractor version even when an intermediate image is discarded.
- Apply page, pixel, byte, unit, character, CPU, memory, and elapsed-time bounds.

## Tombstone, cleanup, and verification

Deletion and expiry use three phases:

1. **Tombstone:** atomically set availability false and index/retention state to tombstoned.
2. **Converge:** delete chunks, embeddings, OCR text, envelopes, rasters, images, thumbnails,
   caches, grants, and policy-permitted source bytes through durable idempotent effects.
3. **Verify:** independently query every owned store and emit a purge receipt. `purged` requires zero
   live index rows, derivatives, source objects, and caches, with no legal or backup blocker.

The reconciler marks active roots from current versions, conversations, citations, connector
pointers, pending work, and holds. It quarantines unreferenced artifacts for a recovery grace period
before sweeping leaves first. Reference counts optimize this process but never replace mark-and-sweep
repair.

## Console contract

Chat defaults to **Use in this conversation only**. Operators can choose **Keep as workspace draft**
or **Add to governed knowledge**, but the latter requires collection and audience confirmation.
Document views expose disposition, expiry, index receipt, derivative storage, promotion, tombstone,
cleanup progress, and any hold that delays physical purge.

## Release gates

- Expired or tombstoned content never enters retrieval.
- Every retained derivative has complete parent lineage and inherited access/retention.
- Process termination between any cleanup steps converges after restart.
- Legal hold prevents every physical deletion.
- A purge receipt cannot pass while any live residue or blocker remains.
- Cross-collection deduplication and existence disclosure remain impossible.
- Metrics expose temporary-byte growth, promotion rate, orphan rate, purge latency, and residue.

## Related docs

| To learn about | Read |
|----------------|------|
| Upload, storage, and API flow | [Document ingestion](document-ingestion.md) |
| Chat and channel attachment boundaries | [Conversation attachments](conversation-attachments.md) |
| Agent ownership | [Document ingestion agent ownership](document-ingestion-agent-ownership.md) |
| Delivery progress | [Implementation ledger](../../roadmap-implementation/interfaces/document-lifecycle-governance.md) |
