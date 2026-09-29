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
> **Implementation evidence:** The [ledger below](#implementation-status) records shipped
> manifests, held-out evaluation, strict promoted-surface loading, corpus-isolated indexes,
> receipt-backed Operator projections, and the accountable build, validation, and activation pipeline.
> Core registers `catalog.search_rules` only with a supplied semantic index and matching catalog,
> schema, ontology, and embedding identities. Missing, stale, or inaccessible state leaves the
> function unregistered as an optional readiness degradation, never a policy or execution grant.
> Governed live binding and Reader-scoped projection evidence remain open.
>
> Rego manifests now carry the exact deny decision path and a normalized location-free OPA AST
> digest in addition to the source digest. The T0 evaluator uses the same identities and emits
> input- and result-bound evaluation receipts for allow and deny outcomes. Retrieval still cannot
> claim a verdict without that evaluation receipt.

## Search execution boundaries

Both adapters use the same bilingual lexical scorer, configurable finite ranking weights,
minimum score, and stable identifier tie order. Exact authorized identifier lookup does not require
an embedding call. PostgreSQL still verifies active generation identity before returning candidates.
Its bounded document cache checks ordered MVCC row versions and transaction epoch on every read;
changed rows invalidate cached validation, and rows modified in the current transaction are never
cached. The 36-case local adapter cohort covers 24 English/Korean positive queries, eight no-match
queries, and four exact identifiers with an unavailable embedder. This tests retrieval mechanics,
not live embedding relevance, language-model accuracy, or promotion eligibility. The historical
seven-case promotion fixture remains a separate, small evidence set.

The evaluator itself emits `HOLD` with a named failure for every missing required cohort. A passing English-only subset cannot stand in for required Korean evidence. Existing policy and receipt identities are unchanged; this guard does not establish sufficient sample sizes or live embedding quality.

Evaluation policy `1.1.0` requires an explicit `min_samples_per_metric` from 2 to 10,000. Each measured recall, reciprocal-rank, and no-match metric must satisfy that floor in both evaluation and independent review; a large positive cohort cannot compensate for one negative sample. Legacy `1.0.0` retains its exact digest and existing receipts, but cannot carry the new field or qualify under a new policy digest. The production policy is not silently upgraded, historical promoted artifacts are not rewritten, and the configured floor still requires an independently reviewed held-out dataset and real-embedder evidence.
## Design at a glance

FDAI resolves meaning before it ranks Rules. Exact catalog identity and reviewed ontology links
constrain the candidate set, while lexical and vector retrieval absorb natural-language variation.

![Design at a glance. The main stages are Operator question, Interpretation candidate, Ontology concepts, Bounded graph expansion, Hybrid Rule retrieval, Catalog and generation verification, Operation class, Read-only answer, Existing T0 and OPA path, Governed ActionType proposal, Clarification or hold.](../../diagrams/generated/fdai-roadmap-rules-and-detection-rule-semantic-retrieval-01.en.svg)

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

The ontology release digest is the governed catalog release, which the release-derived pin
generator also measures. The runtime's operational release adds source-derived competency
FunctionTypes to that catalog and identifies runtime plans, never a Rule semantic manifest, a
promoted surface, a validation receipt, or their search generation. Startup loads the governed
release from the same catalog root and accepts it only when the operational release equals it
plus function declarations; otherwise Rule generation stays unbound.

### RuleSemanticSurface

A semantic surface is a proposal for how operators may express one manifest's meaning. It may
contain reviewed intent ids, ontology concept refs, localized aliases, training paraphrases, and
hard negatives. It cannot set severity, risk, applicability, enforcement, or action authority.

Every surface records its manifest digest, locale, generator and prompt receipts, evidence refs,
state, validation receipt, and content digest. The states are `candidate`, `validated`,
`promoted`, `retired`, and `rejected`. New surfaces start as `candidate`.

A validation receipt binds the surface's candidate-form semantic subject: lifecycle state and the
receipt reference are normalized to `candidate` and absent. Promotion therefore cannot change the
content that was evaluated or create a digest cycle. The promoted Git artifact has its own digest,
including `state: promoted` and the exact validation receipt reference.

The Git catalog stores the full validation receipt at a path derived from its content digest. The
strict loader recomputes that digest, resolves every promoted surface reference, and verifies a
passing validation-only decision for the same candidate-form subject and current evaluation
policy. Missing, malformed, tampered, held, authority-bearing, subject-mismatched, or stale-policy
receipts block the surface from loading. Current generation and catalog identity remain an exact
promotion-review and generation-publication check so loading historical evidence does not create a
surface-to-generation cycle.

Search document identity uses the ordered set of candidate-form semantic subject digests, not the
surface lifecycle artifact digests. A candidate and its receipt-linked promoted form therefore
produce the same exact search documents and generation. Promotion changes review metadata without
invalidating the generation that the receipt evaluated.

### CatalogSearchGeneration

A generation pins one complete searchable corpus:

- corpus and catalog revision;
- semantic schema and governed catalog ontology release digests;
- embedding space identity, model version, and dimension;
- exact row count, a hierarchical canonical digest root, and ordered chunks of at most 256 rows;
- inline ordered document digests only for compatibility generations of at most 256 rows;
- build and validation receipts;
- lifecycle state and activation time.

Only one generation per corpus is active. A worker builds and validates an inactive generation,
then atomically changes the active pointer. A failed build leaves the prior generation unchanged.
PostgreSQL activation also holds one transaction-scoped lock per corpus. Each publisher captures
the expected prior active generation id and digest before staging. Activation checks that identity,
the target digest and lifecycle state, replay identity, and timestamp chronology under the same
transaction before retiring or activating a pointer. A stale or partial expected identity leaves
the active generation unchanged.

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

A validation receipt pins the candidate-form surface subject, exact search generation and catalog,
frozen dataset, evaluator, metric configuration, cohort results, failures, and decision. Review
replay holds when either evaluated search identity differs from the expected generation. Validation
can approve a candidate for review or hold it. It cannot promote the surface by itself.

Passing receipts are persisted as content-addressed JSON artifacts. Their filenames, schema-valid
bodies, canonical content digests, subject identities, policy identities, decisions, failures, and
validation-only authority are independently replayed before a promoted surface enters a search
projection.

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

### Source-only release refresh

Use the [release-derived pin generator](../../../scripts/catalog/refresh-release-derived-pins.py)
when a reviewed ontology change invalidates source pins. It checks by default; `--write` requires
real in-memory lexical retrieval of the seven existing held-out cases through the canonical
`evaluate_semantic_surface`, followed by current-policy `ELIGIBLE_FOR_REVIEW`. Recompute metrics
rather than copying them. Rebind the existing profile declaration set to the exact active release refs while retaining the frozen dataset, training queries, configured thresholds, authored `promoted` state, and prior content-addressed receipts. Before any write, source/policy
fingerprints and original destination bytes must still match; symlink destinations, including
dangling links, and immutable receipt replacement are rejected. Activation is confined to the
temporary evaluation index; neither the deployed index nor a promotion registry is changed. Alert ActionType additions use this same measured source-refresh boundary.

### Independent generation validation

The builder and validator do not share an in-memory `SemanticGenerationBuild`. After the
Mimir-owned mechanical builder stages an inactive generation, it publishes only the bounded
`RuleGenerationBuildResultEvent`. Heimdall loads that exact generation through a read-only
`CatalogGenerationValidationSnapshot` containing metadata and canonical ordered rows. Both the
in-memory and PostgreSQL adapters revalidate row count, content hashes, order, and the hierarchical
manifest before returning the snapshot.

Heimdall recomputes the generation identity from the snapshot and publishes validation-only
evidence. It cannot attach the receipt, activate a pointer, promote a surface, or grant execution
authority. Mimir may bind the exact receipt and issue an activation command only after receiving
that independently produced evidence through the event bus.

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
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/rules-and-detection/rule-semantic-retrieval.md) |
| Rule sources, parsing, and licensing | [Rule Catalog Collection](rule-catalog-collection.md) |
| Rule lifecycle and human control | [Rule Governance](rule-governance.md) |
| Typed ontology and time-consistent context | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Proof-carrying semantic plans | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Full-ontology operator question coverage | [Hierarchical Conversation Planning](../interfaces/hierarchical-conversation-planning.md) |
| Deterministic and model tiering | [LLM Strategy](../architecture/llm-strategy.md) |
| Console authority boundary | [FDAI Console Conversations](../interfaces/operator-console.md) |
