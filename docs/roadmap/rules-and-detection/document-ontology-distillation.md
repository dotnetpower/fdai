---
title: Document Ontology Distillation
---
# Document Ontology Distillation

This document defines how FDAI turns governed operational documents into evidence-backed ontology
change proposals. Model output remains inert: it can identify claims and propose typed graph
changes, but deterministic verification and accountable review decide what can enter an ontology
revision.

> **Authority boundary:** A document can declare intent, ownership, procedures, and historical
> evidence only within its approved source authority. It cannot prove current provider state,
> telemetry, execution permission, or a successful external effect.
>
> **Safety boundary:** Distillation never writes the graph, catalog, policy, or provider directly.
> It produces an `OntologyChangeProposal`; an ambiguous, unsupported, stale, conflicting, or
> incomplete proposal is held for review.
>
> **Customer boundary:** Uploaded documents, extracted text, deployment identities, and proposed
> instances remain in governed deployment storage. Upstream ships only generic contracts,
> deterministic gates, and provider seams.
>
> **Implementation status (2026-08-03):** D0-D4 contracts, claim inventory, strict proposal
> compilation, deterministic gates, review packages, lifecycle plans, and frozen-corpus scoring are
> implemented. D5 promotion assessment is implemented as evidence-only evaluation; no live-shadow
> evidence or automatic promotion is claimed.

## Design at a glance

The pipeline inventories claims before extraction so omitted statements remain measurable. It then
maps each claim to existing ontology declarations, verifies exact source support and authoritative
external evidence, and stages a reviewable graph diff. Approved proposals create a new immutable
revision; reconciliation keeps accepted intent separate from observed external truth.

```mermaid
flowchart LR
    D[Governed document] --> I[Claim inventory]
    I --> E[Typed extraction]
    E --> V[Deterministic verification]
    V --> P[Ontology change proposal]
    P --> H[Accountable review]
    H --> R[Immutable ontology revision]
    R --> C[Authority reconciliation]
    C --> S[Shadow measurement]
```

## Proposal contract

An `OntologyChangeProposal` is content-addressed and proposal-only. It includes:

- proposal id, source document id, immutable document revision, content hash, and extraction run;
- target ontology release and expected graph revision;
- one add, update, remove, or supersede operation over an object or link;
- exact source evidence with section and 1-based inclusive line range;
- claim authority class, effective interval, and freshness policy;
- bounded entity-resolution candidates and the selected canonical identity, when resolved;
- normalized votes from independent extractors or reviewers;
- deterministic gate receipts, conflict references, and a proposal digest;
- review, projection, reconciliation, supersession, rejection, and rollback lineage.

The lifecycle is monotonic:

```text
candidate -> validated -> review_required -> approved -> projected -> reconciled
                  |              |
                  +-> denied     +-> rejected
projected -> superseded | rolled_back
```

A retry with the same source revision, claim, operation, and target release produces the same
proposal identity. A changed source or target revision creates a new proposal rather than mutating
the prior record.

## Claim inventory

Coverage starts before ontology extraction. A claim inventory records every statement that may
carry operational meaning, including:

- normative terms, thresholds, units, prohibitions, and conditional branches;
- service, workload, resource, environment, and owner references;
- dependency, containment, implementation, and escalation relationships;
- procedures, actions, rollback steps, stop conditions, and expected effects;
- event-time observations, historical incidents, and declared effective intervals.

Each claim ends in exactly one disposition: `mapped`, `ignored_with_reason`, or `needs_review`.
Duplicate claim ids, missing dispositions, overlapping contradictory dispositions, and candidate
references to unknown claims fail validation. Structural heuristics and a model-backed detector may
both propose claims, but the deterministic ledger performs the completeness accounting.

## Authority classes

The source authority controls which proposal operations are eligible.

| Authority class | Document use | Required reconciliation |
|-----------------|--------------|-------------------------|
| `declared_intent` | objectives, ownership, constraints, service maps | approved intent source and effective interval |
| `procedure` | rules, workflows, ActionType candidates | catalog schema, safety invariants, shadow replay, review |
| `historical_evidence` | incidents, outcomes, lessons | immutable case or audit evidence |
| `provider_observation` | resource and topology statements | fresh Inventory or provider observation |
| `telemetry_observation` | metric and health statements | fresh telemetry evidence with event time |
| `execution_authority` | permission or autonomy statements | never granted by a document; approved policy remains authoritative |

Source precedence is configured by authority class and scope, never by model confidence. A lower
authority source cannot overwrite a higher authority source. Equal-authority disagreement remains
an explicit conflict and routes to review.

## Extraction and identity resolution

The extractor receives bounded structural units rather than unrestricted document bytes. It must
return schema-constrained data and treat source text as untrusted data, not instructions.

1. Preserve heading, table, page, slide, cell, and line provenance during extraction.
2. Match only an exact existing ObjectType or LinkType from the pinned ontology release.
3. Normalize identifiers, values, units, polarity, comparisons, and effective time.
4. Resolve entities against stable ids and configured aliases before using fuzzy candidates.
5. Return a bounded ambiguous set when no unique identity exists; never invent an instance id.
6. Propose an inert schema change when no existing type can represent a supported claim.

Exact stable-id matches may resolve automatically. Alias and fuzzy matches require deterministic
scoring evidence, one unique winner above configured thresholds, and no conflicting exact match.
Ambiguity always produces `review_required`.

## Verification gates

The verifier evaluates one proposal without calling an executor or mutating a source.

| Gate | Required proof | Failure outcome |
|------|----------------|-----------------|
| Shape | schema, enum, line range, digest, and target release are valid | `denied` |
| Grounding | cited text exists and supports the normalized claim | `denied` |
| Claim accounting | claim exists and has exactly one disposition | `denied` |
| Semantic fidelity | polarity, comparison, number, unit, scope, and time are preserved | `review_required` |
| Identity | one canonical target is proven | `review_required` |
| Authority | source may assert this fact class for this scope | `denied` or `review_required` |
| Conflict | precedence is deterministic and unresolved ties remain visible | `review_required` |
| External truth | provider or telemetry statements have fresh authoritative evidence | `review_required` |
| Safety | rules, workflows, and actions satisfy their complete safety contracts | `denied` |
| Coverage | every claim has a disposition and critical recall meets the release gate | `review_required` |

Model self-reported confidence is never an authority signal. A computed confidence may summarize
grounding, independent agreement, identity resolution, freshness, and historical performance, but
it can only lower eligibility. Independent model disagreement on normalized critical fields routes
to review.

## Lifecycle and rollback

Document and graph lifecycles stay linked by immutable digests:

- **Revision:** A content or curation change reprocesses only affected claims and proposals.
- **Deletion:** A confirmed source deletion creates bounded tombstone proposals. An empty listing
  over a non-empty snapshot is a suspected source outage and cannot mass-delete graph state.
- **Access change:** A narrower source ACL blocks derived reads immediately and schedules removal
  or re-protection of affected artifacts.
- **Conflict:** A later conflicting source does not rewrite accepted history. It creates a new
  proposal linked to the prior revision and conflict receipt.
- **Supersession:** Approved intent replaces a prior effective interval without changing historical
  decision context.
- **Rollback:** Projection failure or later rejection restores the exact prior graph revision and
  records the failed proposal digest.

Projection and reconciliation are separate. Accepting declared intent can update the governed
intent projection. A provider-observed statement becomes current truth only after fresh external
observation matches it.

## Agent ownership

The existing pantheon owns the pipeline without a new coordinator:

| Stage | Accountable agent | Output |
|-------|-------------------|--------|
| Ingress | Huginn | document event |
| Safety and source observations | Heimdall | bounded findings |
| Admissibility | Forseti | admit, hold, or deny decision |
| Structural index and claim ledger | Muninn | immutable context index |
| Inert proposal creation | Norns | proposal candidate |
| Catalog and ontology lifecycle | Mimir | reviewed change package |
| Human approval | Var | independent approval |
| Conflict arbitration | Odin | arbitration decision |
| Audit | Saga | append-only lifecycle evidence |
| Rollback | Vidar | rollback outcome |

No stage calls another agent directly. Authority-bearing transitions use typed events, and no
document path reaches Thor because graph and catalog changes remain reviewed governance proposals.

## Evaluation and promotion

Evaluation uses a frozen, versioned corpus with licensed or synthetic documents, annotated claims,
expected graph diffs, adversarial instructions, scans, tables, conflicting revisions, deletions,
and source outages. Human annotations record reviewer identity and disagreement resolution.

Release gates are:

- zero unsupported critical claims;
- zero number, unit, polarity, or comparison changes on critical claims;
- 100% critical claim disposition accounting;
- at least 0.98 critical-claim recall and 0.98 entity/link precision on the frozen corpus;
- 100% competency-query, replay, rollback, deletion, and ACL regression pass rate;
- zero authority violations, policy escapes, wrong-target projections, and unverified truth claims.

The initial capability is review-only. A later promotion may consider only low-risk mappings after
at least 30 distinct live-shadow days and 500 eligible reviewed proposals, zero guard violations,
and a Wilson 95% precision lower bound of at least 0.99. Ownership, objectives, constraints, rules,
policies, workflows, ActionTypes, permissions, autonomy, schema changes, conflicts, and ambiguous
identities always require accountable review.

## Delivery sequence

| Wave | Deliverable | Exit criteria |
|------|-------------|---------------|
| D0 | Proposal, claim, evidence, authority, receipt, and lifecycle contracts | invalid identity, range, digest, state, and authority fixtures fail closed |
| D1 | Claim inventory and typed extraction adapter | every detected claim receives exactly one disposition |
| D2 | Grounding, semantic, identity, authority, conflict, and coverage gates | adversarial and ambiguity fixtures reach only deny or review |
| D3 | Incremental revision, deletion, ACL, supersession, and rollback planning | outage cannot create mass deletion; replay restores exact revisions |
| D4 | Review package and evaluation report | reviewers see graph diff, source evidence, gate receipts, and unresolved claims |
| D5 | Shadow measurement and limited promotion evidence | statistical and zero-violation gates pass without widening authority |

## Hardening record

Thirteen adversarial rounds covered the complete proposal-only path:

| Round | Focus | Result |
|-------|-------|--------|
| 1 | immutable contracts and replay digests | bounded identifiers, scalar values, and candidate lineage |
| 2 | claim completeness | provider and Korean claims, percent thresholds, fences, exact claim accounting |
| 3 | untrusted model output | source-revision pinning, strict keys, authority-bound identity, size limits |
| 4 | verifier behavior | unknown-link crash, stale revision, comparator normalization, safety denial |
| 5 | entity and link integrity | declared endpoint types, target-resolution binding, operation semantics |
| 6 | conflict and external truth | source revision, UTC time, freshness policy, evidence and conflict provenance |
| 7 | review privacy | source access-policy lineage, exact content digest, package bounds |
| 8 | lifecycle and rollback | projection-only revision changes, exact rollback, duplicate retirement rejection |
| 9 | promotion statistics | typed risk class, as-of cutoff, unique evidence, future-observation rejection |
| 10 | integration boundaries | package invariants, context bounds, correct mixed fence handling |
| 11 | reconciliation isolation | proposal-bound receipts and restored current graph revision |
| 12 | boundary formats | ontology release digest, RFC 3339 UTC evidence, bounded references |
| 13 | executable closure | 156 focused tests, 90.62% branch coverage, Ruff and strict mypy pass |

No verified Medium, High, or Critical finding remains. Residual Low risk is limited to conservative
heuristic coverage for complex layout or language forms, downstream enforcement of the carried
access-policy reference, and missing live-shadow promotion evidence. These conditions keep the
capability in review-only mode and cannot raise authority.

## Verification matrix

| Concern | Required proof |
|---------|----------------|
| Grounding | Every accepted change resolves to immutable source text and document revision. |
| Completeness | Every critical claim has one disposition and omissions remain visible. |
| Identity | Ambiguous or stale targets never project automatically. |
| Authority | Documents cannot assert current external state or grant execution permission. |
| Security | Untrusted text cannot change prompts, tools, policy, or execution identity. |
| Replay | The same inputs and release produce the same proposal and gate digests. |
| Lifecycle | Revision, deletion, outage, ACL, supersession, and rollback are bounded and audited. |
| Customer isolation | Upstream code, fixtures, and docs contain no deployment document content. |

## Related docs

| To learn about | Read |
|----------------|------|
| Upload protection and governed storage | [Document ingestion](../interfaces/document-ingestion.md) |
| Existing manual compilation pipeline | [Manual distillation](manual-distillation.md) |
| Shared semantic and authority model | [FDAI operating ontology](../architecture/operating-ontology.md) |
| Proposal-only ontology primitives | [FDAI ontology safety infrastructure](../architecture/operating-ontology-platform.md) |
