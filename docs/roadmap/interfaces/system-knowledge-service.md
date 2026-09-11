---
title: System Knowledge Service
---
# System Knowledge Service

This document defines the independent FDAI microservice that answers bounded questions about
FDAI's own design, implementation, verification status, and known gaps through a dedicated Teams
mention bot. The service is a read-only product-knowledge surface and never becomes an operational
query, approval, or execution path.

> **Scope:** The service answers only from release-bound FDAI repository knowledge. Customer
> documents, live Azure state, incident evidence, user conversation history, and managed-resource
> actions stay outside this service.
>
> **Deployment boundary:** This is an independently packaged sixth-service candidate with its own
> image, health boundary, Teams application identity, and release artifact. It does not run inside
> Core, Operator Service, or the existing A3 channel-edge workload. Protected deployment summary
> and cleanup steps run only after the protected-source verifier succeeds.
>
> **Authority boundary:** Every response carries `execution_authority=false`. A Teams mention,
> retrieved record, implementation status, or cited source can explain FDAI behavior but cannot
> authorize a change.

## Design at a glance

A dedicated Teams bot receives a direct mention, verifies the Bot service token, tenant, team,
channel, recipient, and sender mapping, then removes only the verified bot mention. The service
searches an immutable catalog compiled from tracked design documents and bounded source metadata.
It renders one concise response with design, implementation, limitations, and citations, records a
safe-to-retry message claim, and replies in the same Teams conversation.

```text
Teams @mention
  -> System Knowledge Service
  -> service-token, tenant, team, channel, recipient, and sender verification
  -> release-bound SystemKnowledgeCatalog
  -> deterministic exact and bilingual lexical retrieval
  -> design + implementation + limitations + citations
  -> durable message claim
  -> same-conversation Teams reply
```

Muninn remains accountable for the release context index. Bragi owns the deterministic
conversation presentation profile. The service is mechanical infrastructure for those existing
responsibilities and does not add or rename a Pantheon agent.

## Initial design

The first option extended the existing Operator A3 channel edge and restored
`BehaviorKnowledgeIndex` inside Core. Teams would continue through `SemanticTurnBridge`, Core would
retrieve repository behavior records, and the normal channel renderer would return the result.

This option reused the most code and preserved one Teams ingress.

## Design critique

The initial option mixes two lifecycles that should remain independent:

- **Failure isolation:** Repository catalog loading and self-knowledge search could make the
  operational conversation path unavailable.
- **Release isolation:** Core and Operator images would need a repository-derived artifact that
  changes with documentation and source revisions.
- **Identity scope:** A product-knowledge bot needs no operational principal scope, provider-read
  credential, or action capability.
- **Deployment cadence:** FDAI design and implementation knowledge can refresh without redeploying
  the operational control plane.
- **Channel intent:** A dedicated bot makes every accepted mention a system-knowledge query. It
  avoids keyword routing while the general A3 bot continues to interpret operational requests.
- **Rollback:** Disabling the knowledge bot should not roll back Core, Operator Service, or existing
  channel delivery.

Sharing the existing A3 runtime would therefore reduce process count but increase fault, identity,
and release coupling.

## Revised design

The revised design creates `fdai-system-knowledge-service` as a separate distribution:

- **Separate process:** The service has its own package, entry point, image, health probes, and
  bounded configuration.
- **Separate Teams app:** A deployment supplies a dedicated bot application and installs it only in
  approved standard channels. The initial release does not request resource-specific consent (RSC)
  to read all messages.
- **Mention-only ingress:** Channel messages are accepted only when the authenticated activity
  contains a mention entity for the exact bot recipient.
- **Release-bound catalog:** A build command compiles structured records and source citations from
  tracked files. The runtime image contains the catalog, not repository source or Git credentials.
- **Deterministic retrieval:** Exact aliases rank first. Normalized English tokens and Korean
  two-syllable tokens provide bounded lexical fallback. Low-score searches return an explicit
  unavailable answer.
- **Status separation:** Each record distinguishes `not_started`, `in_progress`, `implemented`,
  `validated`, `deferred`, and `not_applicable`.
- **No operational authority:** The service has no Azure provider reader, Event Hubs producer,
  action catalog, approval callback, or executor identity.

## Knowledge contract

`SystemKnowledgeRecord` is the retrieval unit:

| Field | Purpose |
|-------|---------|
| `knowledge_id`, `subject_id` | Stable identity and comparison grouping |
| `status`, `owner` | Current delivery state and accountable subsystem |
| `question_aliases` | Reviewed English and Korean questions |
| `designed_behavior` | What the authoritative design requires |
| `implemented_behavior` | What current source and focused tests prove |
| `limitations` | Missing, stale, unvalidated, or deliberately excluded behavior |
| `sources` | Repository-relative path, symbol, line, blob SHA, kind, and authority role |
| `generated_at` | UTC build time included in `catalog_digest` so each compiled artifact has an explicit creation boundary |
| `source_revision`, `catalog_digest` | Exact release and complete catalog identity |

`catalog_digest` covers the schema version, source revision, build time, records, and authority
flag. Rebuilding the same records at a different time therefore creates a distinct packaged
artifact. Any change to a cited source, including formatting-only compaction, requires a catalog
rebuild before packaging so its blob pins and digest match the release tree.

The compiled catalog rejects duplicate identifiers, duplicate exact aliases, untracked paths,
invalid source ranges, digest mismatch, and records without sources. Source bodies are not part of
the runtime response. Its `source_revision` is the current checkout's merge-base with protected
`origin/main` and remains a protected-main ancestor after rebase or squash integration. Each
source's `blob_sha` separately pins the current reviewed checkout, so catalog content can advance
without assigning side-branch lineage to the release anchor.

## Teams trust boundary

The service validates these values before search:

1. Bot service JWT signature, fixed algorithm, issuer, audience, time, and `serviceurl`.
2. Activity `channelId=msteams` and exact allowed service URL.
3. Configured tenant, team, and channel.
4. Sender `aadObjectId` mapped to one enabled knowledge principal.
5. Activity recipient equal to the configured bot application.
6. A mention entity whose `mentioned.id` equals that recipient.

The service derives the query by removing the exact mention entity text. It does not infer mention
identity from `<at>` markup alone. Unsupported activities, oversized bodies, and unknown mappings
are rejected before search. Private and shared channels are not supported in the initial release,
so deployments must exclude them from the configured team and channel allowlists.

## Delivery and failure behavior

| Failure | Safe behavior |
|---------|---------------|
| Invalid service token | Return `401`; search and send nothing |
| Unknown tenant, team, channel, sender, or recipient | Return `403`; search and send nothing |
| Missing direct bot mention | Return `202`; record no query and send nothing |
| Empty question after mention removal | Send bounded usage guidance |
| Catalog revision mismatch | Readiness remains unavailable and no answer is sent |
| No relevant record | State that no verified system-knowledge record matched |
| Provider rejection before acknowledgement | Release the retryable claim |
| Interrupted acknowledgement | Preserve an ambiguous terminal claim and do not resend |
| Process restart | Reuse the venue-specific durable claim store before any provider send |

The local implementation uses a service-owned SQLite claim store. The deployed implementation uses
a Managed Identity Blob compare-and-swap (CAS) ledger in a private existing storage account. It
creates no storage key, connection string, or file share. Startup probes the container, removes
interrupted `processing` claims, and converts interrupted `sending` claims to terminal `ambiguous`.
The first deployment retains one replica; higher replica counts remain blocked until concurrency,
cost, and rollback evidence closes the service-graduation scorecard.

The standalone Terraform root owns one dedicated user-assigned managed identity (UAMI), one private
claim container, `AcrPull`, `Storage Blob Data Contributor`, and `Key Vault Secrets User`, one
single-replica Container App, one F0 Azure Bot, and one Teams channel. A protected workflow creates
plan-only output by default and requires exact CI, image attestations, plan and context digests, and
an explicit `enable` or `disable` transition before apply.

## Rollout

1. Build and test the catalog, deterministic search, mention verification, and reply renderer.
2. Package the service and image without repository source.
3. Run a local Activity Protocol canary against synthetic signed activities.
4. Apply the guarded Terraform plan, build the deterministic Teams package, and install it through
   a tenant administrator with the required Microsoft Graph app-catalog permission.
5. Validate mention-only receipt, same-conversation reply, restart deduplication, disable, and
   rollback before declaring the service production-ready.

## Related docs

| To learn about | Read |
|----------------|------|
| Current implementation state | [System Knowledge Service implementation ledger](../../roadmap-implementation/interfaces/system-knowledge-service.md) |
| Deploy and install the dedicated Teams bot | [System Knowledge Teams onboarding](../../runbooks/system-knowledge-teams-onboarding.md) |
| General operational Teams conversations | [Production A3 channel runtime](production-a3-channel-runtime.md) |
| Human identity and role boundaries | [User RBAC and Entra identity](user-rbac-and-identity.md) |
| Service split acceptance gates | [Service graduation and data ownership](../architecture/service-graduation-and-ownership.md) |
| Existing structured behavior design | [Behavior knowledge](behavior-knowledge.md) |
