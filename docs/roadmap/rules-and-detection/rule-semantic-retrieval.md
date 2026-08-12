---
title: Rule Semantic Retrieval
---
# Rule Semantic Retrieval

This document defines how FDAI turns natural-language policy questions into bounded Rule
candidates without making search, generated metadata, or vectors authoritative. It owns the
active and discovery corpora, semantic-surface lifecycle, index generations, retrieval receipts,
evaluation gates, and failed-query feedback loop.

> **Authority boundary:** Git catalog-as-code remains authoritative for active Rules, Policies,
> and promoted semantic surfaces. PostgreSQL search rows and embeddings are rebuildable read
> projections. A retrieval result never grants policy, approval, or execution authority.
>
> **Safety boundary:** Rule discovery and policy evaluation are separate operations. OPA evaluates
> only an exact active Rule against schema-valid, current evidence through the existing T0 path.
>
> **Implementation status (2026-08-13):** FDAI ships deterministic Rego and expression manifests,
> strict promoted-surface loading, held-out cohort evaluation, privacy-safe challenger feedback,
> atomic in-memory generations, the read-only `catalog.search_rules` function,
> concept-first bounded retrieval, lexical degradation, and a durable StateStore challenger store.
> Direct semantic-runtime composition binds the function only when a caller supplies both a
> provider-neutral semantic index and its exact catalog digest. Without that pair, the principal
> manifest records `catalog.search_rules` as `runtime_binding_unavailable` and does not advertise it
> to the planner. The repository does not yet contain a durable production `CatalogSemanticIndex`
> adapter or a production bootstrap binding. Reader-gated `POST /rules/search` reads an Operator
> Service projection; it does not directly invoke the Core function. Retrieval and function
> receipts retain `execution_authority: false` wherever the Core capability is bound.
> Reproduced retrieval-owned failures flow through Huginn ingress, Heimdall validation, Saga audit,
> and Muninn context materialization. Norns then persists an inert challenger with shadow audit
> before ordinary consensus and Mimir intake.
> Rego manifests now carry the exact deny decision path and a normalized location-free OPA AST
> digest in addition to the source digest. The T0 evaluator uses the same identities and emits
> input- and result-bound evaluation receipts for allow and deny outcomes. Retrieval still cannot
> claim a verdict without that evaluation receipt.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Exact-generation Rule query | implemented | `core/ontology_platform/catalog_queries.py`; `tests/core/ontology_platform/test_catalog_queries.py` | Returns candidate-only results and content-addressed retrieval and invocation receipts with no execution authority. |
| Optional semantic-runtime binding | implemented | `composition/wire_semantic_query.py`; `tests/composition/test_wire_semantic_query.py` | Requires the semantic index and exact catalog digest together. |
| Planner availability accounting | implemented | `core/ontology_platform/query_manifest.py`; `tests/core/ontology_platform/test_query_manifest.py`; current change focused checks | A readable but unbound function remains in structural coverage as `runtime_binding_unavailable` and is hidden from planning. |
| In-memory generation and validation | implemented | `delivery/catalog_search/in_memory.py`; `delivery/catalog_search/generation.py`; `tests/delivery/catalog_search/test_ontology_generation.py` | Supports deterministic off-path generation tests, but is not a durable production adapter. |
| Durable production index and bootstrap binding | not-started | `shared/providers/catalog_search.py`; `runtime/bootstrap.py` | The provider contract exists, but no durable `CatalogSemanticIndex` implementation is composed into production. |
| Operator Rule-search projection | implemented | Operator Service workflow manifest, routes, and PostgreSQL workflow adapter | `POST /rules/search` reads a revisioned materialized projection and grants no policy, approval, mutation, or execution authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the implementation ledger and corrected the unsupported production-binding claim. Added optional exact-digest composition and typed planner unavailability for unbound Rule search. Earlier provenance was not reconstructed. | `current change`; `PYTHONPATH="$PWD/services/core-control-plane/src:$PWD/packages/service-contracts/src" .venv/bin/pytest -q services/core-control-plane/tests/composition/test_wire_semantic_query.py services/core-control-plane/tests/core/ontology_platform/test_query_manifest.py` passes 19 focused tests. | Add a durable production index, production bootstrap binding, Core-to-Operator projection publication, and live receipts. |

### Remaining work

- [ ] Implement and compose a durable production `CatalogSemanticIndex`; exit when focused
  live-database generation, activation, rollback, and exact-generation search checks pass as
  specified by [Build and enrichment lifecycle](#build-and-enrichment-lifecycle).
- [ ] Publish Core retrieval and function-invocation receipts into the Operator projection; exit
  when `POST /rules/search` returns the exact receipt-backed projection without direct Core calls,
  preserving the [query lifecycle](#query-lifecycle).
- [ ] Record governed live evidence for the production binding and Reader-scoped projection before
  changing this capability from `implemented` to `validated`; retain the identities defined by
  [CatalogRetrievalReceipt](#catalogretrievalreceipt).

## Design at a glance

FDAI resolves meaning before it ranks Rules. Exact catalog identity and reviewed ontology links
constrain the candidate set, while lexical and vector retrieval absorb natural-language variation.

```mermaid
flowchart LR
    Q[Operator question] --> I[Interpretation candidate]
    I --> C[Ontology concepts]
    C --> G[Bounded graph expansion]
    G --> R[Hybrid Rule retrieval]
    R --> V[Catalog and generation verification]
    V --> D{Operation class}
    D -->|discover or explain| A[Read-only answer]
    D -->|evaluate| T[Existing T0 and OPA path]
    D -->|action draft| P[Governed ActionType proposal]
    V -->|ambiguous| H[Clarification or hold]
```

The flow preserves three distinctions:

- **Meaning vs. ranking:** ontology identities and links define valid concepts; retrieval ranks
  candidates inside that bounded meaning.
- **Search vs. evaluation:** finding a Rule does not evaluate it. Policy evaluation needs exact
  active Rule identity and authoritative resource evidence.
- **Candidate vs. authority:** lexical, embedding, and model outputs remain candidates. Review and
  exact catalog evidence determine whether a semantic surface can become active.

## Corpus boundaries

The index keeps operational Rules separate from collected discovery material.

| Corpus | Contents | Allowed use | Prohibited use |
|--------|----------|-------------|----------------|
| `active` | Reviewed Rules and promoted semantic surfaces from Git | Operator search, explanation, exact T0 evaluation routing | Treating retrieval score as a policy verdict |
| `discovery` | Collected, normalized, or generated candidates not yet promoted | Catalog curation, gap analysis, shadow retrieval evaluation | OPA evaluation, findings, action proposals, or execution |

Queries default to `active`. An operator must explicitly select discovery scope to inspect
candidate material. A result always carries its corpus so presentation cannot hide the boundary.

## Semantic artifacts

Five immutable contracts carry the lifecycle.

### RuleSemanticManifest

The deterministic manifest records what the source artifacts prove:

- exact Rule id and version;
- policy and content digests;
- parser and parser version;
- source kind and redistribution class;
- resource, signal, property, policy, and ActionType references;
- ontology release digest;
- normalized predicates when the source parser can prove them.

Missing semantics remain unknown. A parser never invents a predicate, concept, or relationship.

### RuleSemanticSurface

A semantic surface is a proposal for how operators may express one manifest's meaning. It may
contain reviewed intent ids, ontology concept refs, localized aliases, training paraphrases, and
hard negatives. It cannot set severity, risk, applicability, enforcement, or action authority.

Every surface records its manifest digest, locale, generator and prompt receipts, evidence refs,
state, validation receipt, and content digest. The states are `candidate`, `validated`,
`promoted`, `retired`, and `rejected`. New surfaces start as `candidate`.

### CatalogSearchGeneration

A generation pins one complete searchable corpus:

- corpus and catalog revision;
- semantic schema and ontology release digests;
- embedding space identity, model version, and dimension;
- ordered document digests and row count;
- build and validation receipts;
- lifecycle state and activation time.

Only one generation per corpus is active. A worker builds and validates an inactive generation,
then atomically changes the active pointer. A failed build leaves the prior generation unchanged.
PostgreSQL activation also holds one transaction-scoped lock per corpus, so concurrent publishers
serialize before retiring or activating a pointer.

Rollback reactivates only a retained prior generation. The caller pins the expected active and
target generation revisions and digests plus the target validation receipt. Both generations must
belong to the same corpus. An ontology compatibility receipt binds the target as the previous
release and the current active generation as the candidate release, allowing exact identity or an
additive N/N-1 transition that passed the canonical compatibility gate. The store checks those
values under the same corpus lock, retires the current generation, and reactivates the target in
one atomic transition. An exact retry with the same rollback time returns the same content-addressed
receipt without another state change. A stale revision or compatibility mismatch leaves the active
generation unchanged.

### CatalogRetrievalReceipt

Each search records the query digest, operation class, corpus, catalog and generation digests,
bounded filters, result Rule refs, ranking components, truncation, and degraded state. Ranking
scores are evidence components, not probabilities or confidence values.

### SurfaceValidationReceipt

A validation receipt pins the surface, frozen dataset, evaluator, metric configuration, cohort
results, failures, and decision. Validation can approve a candidate for review or hold it. It
cannot promote the surface by itself.

## Build and enrichment lifecycle

The build pipeline processes each source through its registered parser. Authored Rego uses OPA AST
parsing. Azure Policy, kube-bench, and other collected formats use source-specific parsers before
they enter one common manifest contract.

```text
source revision
  -> verify provenance and redistribution
  -> parse deterministic semantics
  -> build RuleSemanticManifest
  -> propose RuleSemanticSurface
  -> validate held-out retrieval cohorts
  -> reviewed Git promotion
  -> build inactive index generation
  -> independent generation validation
  -> atomic activation
```

Model enrichment runs off the request and API startup paths. Source text is untrusted data and is
never treated as model instructions. Unknown concept ids produce an inert ontology proposal rather
than extending the ontology automatically.

### Licensing boundary

`reference-only` source text, derived excerpts, generated paraphrases, and embeddings are not
eligible for redistribution. Such a source may contribute only independently authored normalized
logic and bounded provenance references. The enrichment gate rejects a surface when its permitted
input lineage cannot be proved.

## Query lifecycle

Rule search has two read surfaces with different contracts.

### Catalog reference search

The `/rules` reference route accepts text and deterministic filters. It can return exact, lexical,
neighbor, and semantic ranking evidence, but every result remains a read-only candidate. When the
semantic generation is missing, stale, or unavailable, the route uses current-catalog lexical
search and reports the degraded semantic state.

### Conversational concept search

Natural-language operation planning targets a read-only ontology function such as
`catalog.search_rules`, not a Rule declaration directly. The function accepts typed intent,
concept, resource, property, category, and corpus filters. A verified semantic plan still carries
`execution_authority: false`.

The query path uses this order:

1. Resolve exact Rule ids and reviewed lexical terms.
2. Propose intent and ontology concept candidates.
3. Expand only allowlisted typed links under a node and depth bound.
4. Run hybrid ranking inside the resulting candidate set.
5. Verify active catalog, generation, and current ontology release identity.
6. Return candidates, ask for clarification, or hold when evidence is insufficient.

An evaluation request re-enters the existing T0 path with an exact active Rule and current
resource evidence. An action request becomes an ActionType-bound proposal and follows the normal
judgment, approval, execution, recovery, and audit pipeline.

## Retrieval evaluation

The evaluation dataset separates material used to build a surface from held-out questions used to
measure it. Copying an indexed training phrase into the evaluation set tests storage, not semantic
generalization.

Required cohorts include:

- exact Rule ids and canonical terms;
- independently authored English and Korean paraphrases;
- nearby sibling Rules and contradictory hard negatives;
- explicit no-match and ambiguous questions;
- stale catalog and stale generation cases;
- prompt-injection, control-character, confusable, and oversized inputs;
- active and discovery corpus isolation.

Metrics include recall at bounded ranks, mean reciprocal rank, normalized discounted cumulative
gain, no-match precision, clarification utility, cohort coverage, and latency. Promotion thresholds
are configuration selected after a measured baseline. Aggregate success cannot hide a failed
resource, language, severity, or source cohort.

Policy behavior uses separate OPA fixtures. A retrieval benchmark never claims that a Rule's
predicate is correct, and an OPA fixture never claims that natural-language retrieval generalizes.

## Failed-query feedback

Operational failures first receive deterministic attribution. Supported layers include stale
generation, missing concept, mapping gap, ranking error, ambiguity, inactive Rule, provider
evidence, and presentation. Only reproduced retrieval-owned failures can create a semantic-surface
candidate.

Feedback obeys these controls:

- raw operator text remains deployment-local, redacted, access-scoped, and retention-bounded;
- generated and user-originated questions retain distinct origin metadata;
- duplicate, rate, principal, and poisoning controls run before candidate creation;
- a user correction is evidence, not an oracle;
- an exact target Rule and independent validation are required before promotion review;
- candidates run as a challenger and cannot change visible ranking;
- regression automatically withdraws the challenger without changing the active generation.

No online request mutates an active surface or vector row.

## Agent ownership

The fixed pantheon owns the capability without adding an indexer agent.

| Stage | Accountable agent | Contract |
|-------|-------------------|----------|
| External catalog-revision ingress | Huginn | Normalize and publish the source event; no catalog write |
| Failed-query candidate discovery | Norns | Produce inert, deduplicated candidates only |
| Rule, Policy, and promoted surface lifecycle | Mimir | Validate catalog identity and publish governed outcomes |
| Retrieval and generation observation | Heimdall | Produce independent evaluation evidence without promotion authority |
| Correlated audit | Saga | Append candidate, validation, activation, degradation, and retirement evidence |
| Natural-language presentation | Bragi | Translate, show candidates, and ask for clarification; never judge or execute |

The build worker is a mechanical Mimir-owned capability. Authority-bearing transitions travel
through typed events. The Operator API reads the active projection and never promotes a surface or
activates a generation.

## Failure and degradation

| Failure | Safe behavior |
|---------|---------------|
| Semantic index or embedder unavailable | Search the current Git-backed catalog lexically and report semantic unavailability |
| Active generation digest differs from the catalog | Exclude semantic results and report a stale generation |
| Inactive generation build or validation fails | Keep the prior active generation and audit the failure |
| No active generation exists | Keep exact and lexical search available |
| Candidate ambiguity remains | Ask for clarification or return a bounded candidate list without evaluation |
| Evaluation evidence is missing or stale | Hold without running OPA or producing a Finding |
| Feedback attribution is unresolved | Retain evidence only; create no semantic candidate |

Operator-facing degradation uses stable machine reasons such as `generation-unavailable`,
`generation-stale`, and `provider-unavailable`. Provider messages and Python exception names never
cross the API boundary. When an active generation was observed before failure, the degraded
response retains its generation, catalog, semantic schema, ontology release, and corpus identity.
Catalog-reference `GET /rules` degrades to lexical results. Typed `POST /rules/search` reads the
revisioned Operator projection and returns an unavailable response when that projection is absent;
the route does not call the Core function registry or semantic provider directly.

## Delivery sequence

| Batch | Deliverable | Exit criteria |
|-------|-------------|---------------|
| S0 | Design and competency questions | Corpus, authority, storage, agent, and failure contracts are reviewable in English and Korean |
| S1 | Immutable contracts and corpus isolation | Invalid refs, digests, states, origins, and cross-corpus operations fail closed |
| S2 | Deterministic manifests and licensing gate | Rego and expression fixtures produce replay-stable manifests; reference-only violations are rejected |
| S3 | Surface candidates and held-out evaluator | Training and evaluation data cannot overlap; all required cohorts produce receipts |
| S4 | Atomic persistent generations | Searches observe either the prior or new complete generation, rollback returns a replay-stable receipt, and no transition exposes a mixed corpus |
| S5 | Concept-first typed query | Exact, lexical, graph, and semantic stages preserve candidate-only authority and clarification |
| S6 | Challenger feedback | Reproduced retrieval failures create only durable inert candidates; no online active-index mutation exists |
| S7 | Production projection and observability | Operator API startup does not build embeddings; health exposes catalog and generation identity |

## Related docs

| To learn about | Read |
|----------------|------|
| Rule sources, parsing, and licensing | [Rule Catalog Collection](rule-catalog-collection.md) |
| Rule lifecycle and human control | [Rule Governance](rule-governance.md) |
| Typed ontology and time-consistent context | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Proof-carrying semantic plans | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Full-ontology operator question coverage | [Hierarchical Conversation Planning](../interfaces/hierarchical-conversation-planning.md) |
| Deterministic and model tiering | [LLM Strategy](../architecture/llm-strategy.md) |
| Console authority boundary | [FDAI Console Conversations](../interfaces/operator-console.md) |
