---
title: Assurance Twin (queryable, proactive, verifiable review)
---
# Assurance Twin (queryable, proactive, verifiable review)

FDAI's answer to the "architecture review agent" request is not a chatbot
bolted onto a document index. It is an **Assurance Twin**: a queryable,
ontology-grounded digital twin of the governed subscription that answers
questions deterministically, reviews changes before anyone asks, and proposes
(never executes) remediation. A model compiles natural language into typed graph
queries and explains the results; the answer itself is produced by the
deterministic engine over the twin, so it is grounded and verifiable by
construction, not by a model's say-so.

> **Scope**: customer-agnostic. The twin's schema, rules, and thresholds are
> generic; a fork supplies its own resource population through the `Inventory`
> seam and its own rule set. No customer values, tenant ids, or resource names
> live here
> ([generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md)).

> **Where it sits**: the twin is a **read-only projection** over the ontology
> graph. It never holds a privileged identity. Every mutation still flows
> through `risk-gate -> executor -> delivery`, preserving the read-only surface
> rule in
> [app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md).
> Answering a question is never an action.

## What this doc covers

This document specifies the review/assurance surface that covers the
architecture-review, Q&A, and assessment-report use cases without regressing the
deterministic-first, event-driven, risk-gated design. It reuses the ontology in
[llm-strategy.md](llm-strategy.md#ontology-foundation), the tiered router and
quality gate in
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md),
the detection findings in
[observability-and-detection.md](observability-and-detection.md), and the
deployment analyzer in [deployment-preflight.md](deployment-preflight.md). It
adds one new subsystem, `core/assurance_twin/`, and one delivery intent; the rest
is composition of existing parts.

## Why not a chatbot

A retrieval-augmented chatbot answers the review use cases with five structural
defects. The twin inverts each one.

| Chatbot limitation | Consequence | Assurance Twin shift |
|--------------------|-------------|----------------------|
| **Reactive** - answers only when asked | reproduces the review-queue lead time (wait for a request, then wait for a human) | **Ambient** - reviews changes proactively on the change event, before a request exists |
| **Ungrounded** - vector similarity over prose | hallucinated verdicts reach a deploy | **Ontology-grounded** - answers are deterministic graph queries with a cited rule path |
| **Stateless** - reads documents, not the live estate | no real evidence for "why is this non-compliant" | **Stateful twin** - a live projection of the subscription kept fresh by inventory delta |
| **Inert** - returns information and stops | a human still fixes it by hand | **Action-bridging** - an answer can carry a shadow remediation-PR proposal |
| **Static** - the index goes stale | wrong answers after a policy change | **Self-improving** - unanswered / abstained questions feed the rule discovery loop |

## The five shifts

### 1. Ambient (reactive to proactive)

The twin reviews changes on the event, not on request. When a change signal
arrives (an IaC pull request opened, an Activity Log resource write, a drift
diff), `event-ingest` normalizes it, the twin applies the diff to a scratch
projection, T0 evaluates the affected rules, and the result is posted back as a
review - a Checks API annotation on the PR, or a finding on the incident. The
"assess after deploy on request" case becomes "assessed on change, unprompted".

Example: a developer opens an IaC PR that adds a storage account without a
private endpoint. Before any review is requested, the twin posts a Check:
`blocked - object-storage.private-endpoint.required (rule cited), resolution:
add private endpoint or apply exemption`.

### 2. Ontology-grounded (retrieval to graph query)

The twin is the ontology graph, not a prose index. Every governed resource is a
`Resource` ObjectType; relationships are the existing typed LinkTypes
(`contains`, `attached_to`, `depends_on`), and rule matches are `Finding`s (see
[llm-strategy.md](llm-strategy.md#ontology-foundation)). "Why is this resource
non-compliant" is answered by a graph traversal that returns a concrete evidence
chain, for example:

```text
Resource:storage-x --attached_to--> Resource:subnet-y
subnet-y --contains(-1)--> vnet-z
Finding: storage-x violates rule:object-storage.private-endpoint.required
  evidence: rule path + evaluated property (publicNetworkAccess=Enabled)
```

The chain is deterministic and reproducible: the same twin state yields the same
answer regardless of who asks or how the question is phrased.

### 3. Verifiable (text-to-query, not text-to-answer)

This is the core mechanism. The model is used to **compile a natural-language
question into a typed ontology query** and, at the end, to **render the result
back into prose**. It is never the source of the fact.

```mermaid
flowchart LR
    Q[NL question] --> C["model: compile<br/>NL to typed ontology query"]
    C --> V["verifier: query is<br/>well-typed and read-only"]
    V --> T0Q["T0: execute query<br/>over the twin (deterministic)"]
    TWIN[(Assurance Twin<br/>ontology graph)] --> T0Q
    T0Q --> R[grounded result set]
    R --> EXP["model: explain<br/>result + cite rule path"]
    EXP --> A["answer + provenance<br/>+ confidence + what-if"]
    R -->|empty / low confidence| AB[abstain: 'not known']
```

- **Compilation is verified**: the compiled query MUST be well-typed against the
  ontology schema and MUST be read-only; a query that fails the check is rejected,
  not executed. This is the same fail-closed posture as the T2 verifier.
- **Answers route through the tiers**: an exact rule/graph match resolves at
  **T0**; a fuzzy question near a known pattern uses **T1** similarity; only a
  genuinely novel or ambiguous question reaches **T2**, and T2 output clears the
  [quality gate](../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2)
  (mixed-model cross-check, verifier, grounding) before it is shown.
- **Grounding or abstain**: every answer cites the rules and graph nodes that
  justify it. An answer that cannot be grounded returns "not known", never a
  guess. Hallucination is closed off by construction, not by prompt tuning.

### 4. Action-bridging (inert to proposing)

An answer may carry a proposed fix, but the twin never executes. When a question
resolves to a fixable Finding, the twin can attach a **shadow remediation-PR
proposal** built from the rule's `remediates` ActionType. Acting on it is the
existing gated path: `risk-gate -> executor -> delivery`, with HIL for anything
high risk (see [risk-classification.md](risk-classification.md)). Chat and the
console remain read-only surfaces; a proposal is a link to a PR, never a button
that mutates.

Example: "fix the storage accounts missing a private endpoint" resolves to a set
of Findings; the twin opens one shadow remediation-PR per resource (batched under
the blast-radius cap), each with a rollback contract, and routes to HIL. Nothing
changes until a human approves.

### 5. Self-improving (static to living)

Questions are a discovery signal. A question the twin **abstains** on, or a
recurring question with no covering rule, is emitted as a candidate to the
autonomous rule discovery loop in
[architecture.instructions.md](../../.github/instructions/architecture.instructions.md)
(the same loop that watches HIL patterns and overrides). The candidate carries
provenance and passes the standard quality gate before it can enter the catalog;
the twin never mutates the catalog directly. The knowledge surface therefore
tracks the estate instead of going stale.

## Twin as simulator (what-if over the whole graph)

The per-action what-if verifier
([architecture.instructions.md](../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2))
predicts the effect of a single change. The twin generalizes it to the whole
graph: apply a proposed change to a **scratch projection** and evaluate the
consequences before anything touches the live estate. One simulation surface
serves all three verticals, which is why the twin simplifies rather than
complicates the design.

| Vertical | Simulation question | Answered by |
|----------|---------------------|-------------|
| **Change Safety** | what is the blast radius of this change? what breaks downstream? | traverse `attached_to` / `depends_on` from the changed `Resource`; report affected set + newly-violated rules |
| **Resilience (DR)** | does the estate meet target RPO/RTO? what fails over? | replay a region/zone-loss scenario against the twin; report resources without a recovery path and the projected RPO/RTO gap |
| **Cost Governance** | what is the cost delta of this change / this optimization? | apply the SKU/scale delta on the projection; report the projected unit-cost change |

- **Read-only and deterministic**: a simulation mutates only the scratch
  projection, never the live estate or the audit store. It is a T0-flavored pass:
  static graph evaluation resolves most of it; bounded read-only probes confirm
  the rest, exactly as [deployment-preflight.md](deployment-preflight.md) does.
- **Shadow-first**: each simulation-derived finding ships in shadow mode and is
  promoted per the shadow-to-enforce rule only after its accuracy and
  false-positive rate are measured on the frozen scenario set
  ([goals-and-metrics.md](goals-and-metrics.md)).
- **Fidelity-measured**: `core/assurance_twin/fidelity.py`
  (`SimulationFidelityLedger`) is the mechanism behind that promotion. It joins
  each **predicted** effect (cost delta, blast-radius count, RPO/RTO gap) with
  the **actual** observed outcome by a stable prediction id and accumulates
  per-predictor MAE, MAPE, and a within-tolerance rate. `is_reliable` turns
  those into a fail-closed promotion signal: a predictor below a minimum sample
  count or above a MAPE bar is not reliable, so the caller keeps it in (or demotes
  it back to) shadow. This stops an unmeasured what-if from acting as an oracle -
  a simulation that does not come true loses its enforce eligibility automatically.

## Assessment report (subscription posture, on demand)

The proactive per-change review composes into a full-estate report. Running every
applicable rule against the current twin produces a `PostureAssessmentReport` - a
generalization of the `DeploymentReadinessReport`
([deployment-preflight.md](deployment-preflight.md)) from a single deploy to the
whole subscription. Each entry keeps the same three required parts - grounded
evidence (a cited rule), a severity, and a resolution mapped to a concrete lever -
so the report is actionable, not just a score. The console renders it through a
read-only `ReadPanel` route
([project-structure.md](project-structure.md#injectable-seams)); it issues no
privileged calls.

## Module placement

The subsystem lives in `core/assurance_twin/` and imports only `shared/`
contracts and providers, like every other core subsystem
([project-structure.md](project-structure.md#module-boundaries)). It holds no
cloud SDK and no privileged identity.

| Component | Responsibility |
|-----------|----------------|
| `projection` | build and maintain the read-only twin from `Inventory.full_snapshot()` + `delta()`; keep a scratch projection for simulation |
| `query` | compile a verified, well-typed, read-only ontology query from a request; execute traversals over the twin |
| `review` | on a change signal, apply the diff to a scratch projection, run T0, emit a review finding |
| `report` | assemble the `PostureAssessmentReport` from Findings |
| `explain` | render a grounded result into prose with rule/graph citations (model-assisted, quality-gated) |

Delivery adds one intent to the existing `chatops` adapter (question in, grounded
answer out) and reuses the `gitops-pr` adapter for proposals and Checks API
reviews. No new privileged surface is introduced.

## Safety posture

- **Read-only twin, gated execution**: the twin and every answer are read-only;
  the only path to a mutation is a proposal that enters `risk-gate -> executor`,
  with the four safety invariants (stop-condition, rollback, blast-radius limit,
  audit entry) enforced there, not in the twin.
- **Fail closed**: an ungroundable answer abstains; a mis-typed or non-read-only
  compiled query is rejected; a stale twin (`Inventory` freshness beyond
  `freshness_ttl`) refuses to answer estate-state questions rather than answer
  from ghost data, mirroring `RequiresInventoryFresh`
  ([llm-strategy.md](llm-strategy.md)).
- **Untrusted input**: question text and change payloads are untrusted and may
  carry prompt injection; the verifier and the read-only query contract are the
  authority, never the model's free text (threat model in
  [security-and-identity.md](security-and-identity.md)).
- **Audited**: every proposal, review, and simulation-derived finding writes an
  audit entry with its grounding; a read-only question that produces no proposal
  is logged but is not an action.

## Phasing

The twin lands incrementally on top of the existing phases; it introduces no new
tier and no new autonomy that the risk gate does not already govern.

| Phase | What lands | Gate |
|-------|------------|------|
| **P2** ([phase-2-quality-and-t1.md](phases/phase-2-quality-and-t1.md)) | twin projection from inventory; verified text-to-query; grounded answers via the quality gate; abstain-to-discovery feedback | answers are grounded or abstain; zero ungrounded answers on the scenario set |
| **P3** ([phase-3-integrated-loop.md](phases/phase-3-integrated-loop.md)) | ambient per-change review; whole-graph simulation for Change/DR/FinOps; shadow remediation-PR proposals; `PostureAssessmentReport` panel | each simulation finding measured shadow-first before enforce |

## Next steps

| To learn about | Read |
|----------------|------|
| the ontology the twin queries | [llm-strategy.md](llm-strategy.md#ontology-foundation) |
| the tiers and quality gate answers route through | [architecture.instructions.md](../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2) |
| the deploy analyzer the report generalizes | [deployment-preflight.md](deployment-preflight.md) |
| detection findings the review consumes | [observability-and-detection.md](observability-and-detection.md) |
| where the subsystem sits in the repo | [project-structure.md](project-structure.md#module-boundaries) |
| how proposals are risk-classified | [risk-classification.md](risk-classification.md) |
