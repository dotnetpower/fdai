---
title: Ontology Reasoning Result Handles and Continuations
---
# Ontology Reasoning Result Handles and Continuations

This document designs how the rows an answer showed stay addressable after the turn ends. It
covers the versioned handle, evidence, pushdown, and continuation contracts, where handles are
stored, follow-ups that name a row or one of its properties, and continuations that finish a read
that one answer couldn't hold. It extends the
[Ontology Reasoning Compiler](ontology-reasoning-compiler.md) and its
[follow-up references](ontology-reasoning-compiler.md#follow-up-references).

> **Status:** Proposed design, 2026-10-01. Delivery state and remaining work live in the
> [implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-result-handles.md).
> The shadow binding core that exists today is described in the owner design.

## Design at a glance

A result handle is a server-side record of the exact rows an answer showed, in the order shown. It
lets a follow-up such as "the second one" or "its SKU" bind to a real row instead of a guess from
words. A continuation is server-side state for the rest of a read that one answer cut, so FDAI can
list every row across answers with exact accounting. Both stay read-only and bind the deployment,
principal, conversation, purpose, and manifest. Every row is read again through the secured gateway,
and a reference that can't bind returns one typed clarification.
The H2 local implementation keeps handle bodies encrypted in Core storage and lets Operator persist
only opaque references on durable semantic turns. The semantic request and projection schemas carry
those references additively and grant no read, approval, or execution authority.

| Package | Delivers | Depends on |
|---------|----------|------------|
| H1 Contracts | Versioned handle, evidence manifest, pushdown, and continuation records with rollout-safe version rules (R1) | None |
| H2 Handle store | Core-owned handle bodies, opaque references stored with the durable Operator turn, and up to four references per request (R8) | H1 and the threat review |
| H3 Property follow-ups | A property mention domain and a property lookup on one named resource | H1 |
| H4 Ordinal follow-ups | Ordinals and anaphors over stored handles, including a property of the named row | H2 and H3 |
| H5 Change continuation | Every change in a cut `query.recent_resource_changes` window, across pages | H1 |
| H6 Successive relation plans | An all-kinds neighbourhood larger than one intent graph, read as bounded successive plans | H1 and the H5 continuation rules |

## What exists today

- The shadow runner binds an ordinal or anaphor only to the most recent handle of its own
  conversation. Each mismatch returns a typed `prior_result_*` clarification.
- A cut change read states the exact number of changed Resources it didn't list. The count runs in
  the same repeatable-read snapshot as the page.
- A relation whose sides exceed one intent graph answers only when one union of the reached
  endpoints fits a plan. Otherwise the goal is declined.
- No handle leaves the Core process, so a follow-up in the next turn can't use one yet.

## H1 Contracts

Each record is a versioned model in `packages/service-contracts`, shared by Core and Operator.

| Record | Content | Visibility |
|--------|---------|------------|
| `ResultHandleRef` | A random opaque `handle_ref`, the key version, `issued_at`, and `expires_at` | Stored by Operator with the turn and sent back in requests |
| `ResultHandle` | Deployment scope, principal digest, conversation, purpose, manifest digest, rendered-order digest, ordered typed row keys, sort, page, truncation, and allowlisted snapshot cells | Core only; never sent to a model or to Operator |
| `EvidenceManifest` | The evidence references an answer cited, their receipts, completeness, and a rows digest | Core only |
| `PushdownRequest` | A count with an optional grouping and lineage root, or a typed path with LinkTypes, direction, and a depth bound | Core to the store; returns an exact receipt, never free query text |
| `QueryContinuation` | The fields in [H5](#h5-change-continuation) and [H6](#h6-successive-relation-plans) | Core only; the client holds an opaque reference |

Persisted records outlive one release, so version rules cover the stored life of a record:

- A writer uses the highest version that every running reader supports during a rolling
  deployment, and each reader accepts its own and the previous minor version (N/N-1).
- A record older than N-1, a newer minor or major version, or an unknown key version fails closed
  with a typed error and never a partial read.
- Handle and continuation lifetimes stay shorter than the compatibility window. A record that
  outlives it is migrated or expires.
- Tests cover codec round trips, rolling upgrade and rollback in both directions, and rejection of
  every unsupported version.

**Exit:** codec, N/N-1, rolling-upgrade, and rollback tests pass, and no runtime behavior changes.

## H2 Handle store

1. After deterministic rendering, Core writes the `ResultHandle` to its own store, partitioned by
   deployment scope and encrypted at rest under a versioned key. Core returns a `ResultHandleRef`.
2. Operator stores the reference with the durable turn and sends up to four recent references in
   the next semantic request, newest first. The reference carries no scope or row data, so
   Operator can't read or change what it points to.
3. Core loads a handle only when the deployment scope, principal digest, conversation, purpose,
   and manifest digest all match the request. It rereads the row keys through the secured gateway
   at the current cutoff (`current_rehydrate`, the default). A question about what was shown
   answers only from allowlisted snapshot cells (`snapshot_reference`).
4. Only the most recent handle binds, unless the typed judgment cites an older answer explicitly,
   such as "the list before that".

The threat review must pass before H2 ships:

| Threat | Control |
|--------|---------|
| Cross-conversation, cross-principal, or cross-deployment binding | Core checks every binding field on load; a mismatch returns `prior_result_foreign` |
| Authorization changed since the answer | Every reread goes through the gateway, so an unreadable row never reaches an answer |
| Guessed, tampered, or replayed reference | A random reference with no embedded meaning; an unknown one returns `prior_result_unavailable` |
| Expired handle or deleted conversation | Conversation deletion deletes its handles; expiry returns `prior_result_expired` |
| Retained snapshot values | Only cells already shown, of allowlisted fields, under the conversation's retention and deletion |
| Key compromise or rotation | Versioned keys; rotation keeps the previous key only for decryption until its handles expire |

**Exit:** the follow-up holdout passes at 85% or more in shadow, the threat-review tests record zero
cross-conversation bindings, and the rendered-order digest equals the Console's order on the fixture
graph.

## H3 Property follow-ups

A question such as "what is the SKU of storage account X" asks for a property that the form can't
carry today.

- **Form:** Add the closed mention domain `property` and the measure kind `property`. A property
  mention grounds by closed choice over the readable properties of the subject's ObjectType that
  have a reviewed Property semantic in `rule-catalog/vocabulary/property-semantics.yaml` or a
  declared value domain. The semantic id and provider path are labels, not lookup keys.
- **Compile:** A `lookup` with a `property` measure reads its anchor and projects that property. A
  property that the principal can't read, or that has no reviewed semantic, returns a typed
  unsupported reason and never a raw provider field.
- **Verify:** V-PROV accepts the property only from the measure's binding, and V-SEM requires the
  projection on the anchor read.
- **Answer:** The value states its source, observation time, and freshness. A stale or missing
  value is `UNKNOWN_INCOMPLETE`.

**Exit:** a property lookup on one named resource answers with the exact value, and a property
without a reviewed semantic holds with its typed reason.

## H4 Ordinal follow-ups

An ordinal or anaphor binds to a row of a stored handle (H2), and a property measure (H3) can then
read that row. "What is the SKU of the second one" becomes a property lookup anchored on the handle's
second row after reauthorization.

**Exit:** the traced ordinal SKU follow-up answers with the exact property value.

## H5 Change continuation

The PostgreSQL reader selects the newest change of each Resource inside a derived relation (`DISTINCT
ON (subject_ref)`), pinned to one ingestion cutoff (`recorded_at <= known_at`), and then orders that
relation by `effective_at` descending and `subject_ref` ascending. A continuation seeks only in the
outer query, after the newest change per Resource is chosen, so an older observation of a Resource
can't reappear:

```text
WHERE effective_at < :last_effective_at
   OR (effective_at = :last_effective_at AND subject_ref > :last_subject_ref)
```

- The remaining count comes from the same derived relation under the same cutoff, and the answer
  claims completeness only on the last page.
- The implementation stores the raw seek key only in Core-owned continuation state; decision events
  and Operator traffic carry only the opaque reference and digests.
- Core stores the continuation state: deployment scope, principal digest, conversation, purpose,
  the admitted goal and plan digests, the manifest digest, the query-version digest, the window,
  the cutoff, the ordering, the cursor, the page size, and `expires_at`. The client holds only an
  opaque reference.
- Every page is reauthorized. A mismatch in any bound field, or expiry, returns a typed
  `continuation_invalid`, never a silently different population.
- Tests on a real loopback PostgreSQL cover several observations per Resource, timestamp ties,
  rows recorded after the cutoff, and a changed page size.

**Exit:** a 24-hour window with more than 20 changes lists every change across the continuation
with exact accounting.

## H6 Successive relation plans

When an `all_kinds` relation needs more sides than one intent graph holds, 32 nodes and 8 outputs,
the compiler splits the reviewed sides into ordered batches. The first batch pins the anchor
identity and the source generation. Each later batch is its own verified plan. Its continuation
records `remaining_batches`, the next batch descriptor, and a digest of the endpoints already
listed, not a row count, because later batches haven't run. The answer lists each reached endpoint
with its LinkType and states how many batches remain. A generation change ends the continuation as
incomplete, as the shadow runner does today.
The local implementation keeps this default-off in the shadow path until promotion wires the live
answer behavior.

**Exit:** the traced connected-resources question lists every reached endpoint with its LinkType
across the successive plans.

## Safety and authority

- Every package reads only. A handle or continuation grants no execution, approval, or wider read
  authority, and every row is reauthorized when it is read again.
- Decision events carry digests and counts, never row identifiers, names, or snapshot values.
- A reference that can't bind returns one typed clarification after every check that a new handle
  couldn't change, as the owner design requires.

## Decisions requiring approval

1. Core stores handle bodies and Operator stores only opaque references with the durable turn
   (proposed). This revises the owner design's wording that Operator persists handles. The
   alternative is a Core-sealed envelope that Operator stores and returns intact.
2. Handle and snapshot retention follow the conversation's retention and deletion, capped by the
   compatibility window (proposed).
3. A continuation expires after 15 minutes (proposed).
4. Property follow-ups read only properties with a reviewed Property semantic or a declared value
   domain (proposed), not every readable property.

## Critique and revisions

An independent critique of the first draft found the following issues. This design includes each
revision.

| Finding | Revision |
|---------|----------|
| Handle ownership was contradictory: Operator stored bodies that Core couldn't read back, and deployment scope wasn't bound | Core owns encrypted, scope-partitioned bodies; Operator stores opaque references; decision 1 asks for approval |
| Continuations weren't bound to conversation, purpose, query semantics, or version, and a batch continuation reused a row count | Core-stored state binds every field and reauthorizes each page; batches use `remaining_batches` and a listed-endpoint digest |
| The keyset seek was underspecified and could resurrect an older observation | The seek runs only after the newest change per Resource is chosen, with the mixed-direction predicate and PostgreSQL tests |
| N/N-1 codecs didn't make stored records rollout-safe | Writer version negotiation, typed rejection, lifetimes within the compatibility window, and rollback tests |
| The linked ledger didn't exist | The ledger exists and owns this document's remaining work |

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/interfaces/ontology-reasoning-result-handles.md) |
| The binding core and the delivery rounds | [Ontology Reasoning Compiler](ontology-reasoning-compiler.md) |
| Compiler coverage and current-path work | [Coverage Expansion](ontology-reasoning-coverage-expansion.md) |
| Production shadow, verified answers, and promotion | [Promotion Program](ontology-reasoning-promotion-program.md) |
| Coverage lanes and the parity bar | [Ontology Reasoning Coverage](ontology-reasoning-coverage.md) |
