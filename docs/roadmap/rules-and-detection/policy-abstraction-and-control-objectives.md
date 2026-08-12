---
title: Policy Abstraction and Control Objectives
---
# Policy Abstraction and Control Objectives

This document defines the semantic layer between FDAI's operating ontology and its concrete Rules
and OPA/Rego policies. It introduces provider-neutral `ControlObjective` and
`RuleObjectiveBinding` records so operators can find and explain reusable control intent without
turning ontology, search, or generated groupings into evaluation authority.

> **Authority boundary:** `Rule`, `Assignment`, `PolicyArtifact`, OPA evaluation, `Verdict`, and
> `ActionType` keep their existing responsibilities. A control objective or binding can narrow a
> candidate set, but it cannot evaluate evidence, set effect or enforcement, approve, or execute.
>
> **Scale boundary:** The semantic index may cover the full active and discovery corpora. The
> operating graph remains a bounded read model and does not ingest every collected Rule.

## Design at a glance

The abstraction represents a stable operational invariant, not another executable policy. One
objective can be realized by several version-pinned Rules whose provider, resource shape,
evidence, parameters, or implementation differ.

```mermaid
flowchart LR
    Q[Natural-language request] --> I[Typed operational intent]
    I --> O[Applicable ControlObjectives]
    O --> B[Verified RuleObjectiveBindings]
    B --> R[Active Rules and Assignments]
    R --> P[PolicyArtifact]
    P --> E[OPA or deterministic evaluator]
    E --> V[Verdict]
    V --> A[Governed ActionType path]
```

The flow preserves three boundaries:

- **Meaning:** The ontology and `ControlObjective` describe the invariant and applicable semantic
  context.
- **Governance:** `RuleObjectiveBinding`, `Rule`, and `Assignment` select an exact active control,
  scope, parameters, effect, and enforcement mode.
- **Decision:** The existing deterministic evaluator produces the decision. Search and semantic
  grouping remain candidate-only.

## Repository baseline

A deterministic inventory on 2026-08-13 found 8,549 unique Rule records. The count separates
authored executable policy from collected discovery material. Reproduce it by loading YAML under
`rule-catalog/catalog` and `rule-catalog/collected`, selecting mappings with `id` and
`check_logic`, then grouping `check_logic.kind` and `source`; the implementation history records
the exact result used by this design.

| Corpus fact | Count | Interpretation |
|-------------|------:|----------------|
| Total Rules | 8,549 | Unique records under curated and collected catalog roots |
| Authored Rego Rules | 62 | Rules with a current `.rego` implementation |
| Expression Rules | 8,487 | Collected normalized expressions, not 8,487 Rego modules |
| Azure Policy records | 3,628 | Discovery records from Azure built-ins |
| kube-bench records | 4,859 | Discovery records from benchmark controls |

The existing model already provides important boundaries:

| Existing artifact | Responsibility | Required treatment |
|-------------------|----------------|--------------------|
| `Rule` | One concrete, testable operational control | Preserve as the evaluation and finding identity |
| `PolicyArtifact` | Deterministic implementation metadata | Preserve; don't replace with a semantic concept |
| `implemented_by_policy` | Rule-to-policy implementation relation | Reuse for exact policy resolution |
| `Assignment` and `RuleSet` | Scope, parameters, effect, and enforcement | Keep governance outside the objective |
| Semantic manifests and surfaces | Candidate-only search meaning | Extend with typed objective references after promotion |
| Active and discovery corpora | Operational vs. inert catalog material | Keep isolated through search, projection, and evaluation |

The missing contract is a stable family identity plus a proof-carrying relation from that family to
an exact Rule version. Creating another generic `Policy` object would duplicate the existing Rule,
governance, and implementation artifacts.

## Semantic model

### ControlObjective

`ControlObjective` is a versioned, provider-neutral invariant such as "a node pool remains
available after one zone fails." It should contain:

- a stable id, version, title, and bounded description;
- operating domain and protected outcome references;
- applicable ontology type and property references;
- a normalized predicate family that describes intent without an active threshold;
- provenance, lifecycle state, supersession, and content digest;
- localization and semantic-surface references used for search and explanation.

It does not contain an OPA package, provider field path, assignment scope, active parameter value,
effect, enforcement mode, risk decision, or action authority. Those values change independently
and remain in their existing contracts.

### RuleObjectiveBinding

`RuleObjectiveBinding` is an immutable catalog record connecting one objective version to one
exact Rule version. It should contain:

- objective and Rule version references plus their content digests;
- relationship kind, initially `realizes` or `partially_realizes`;
- applicability delta for provider, resource subtype, evidence shape, and environment constraints;
- declared variant dimensions such as threshold, unit, aggregation window, or exception model;
- normalized implementation and evidence signatures;
- an optional equivalence receipt and explicit non-equivalence reasons;
- provenance, reviewer, lifecycle state, and content digest.

The binding is first-class because the current LinkType shape cannot carry version pins,
applicability deltas, and proof receipts safely. The ontology may project the record and its links
for bounded queries, while Git catalog-as-code remains authoritative.

### Relationship rules

- One objective may have many bindings and many Rules.
- One Rule may realize several objectives only when each binding has independent applicability and
  evidence.
- Sharing an objective does not imply that two Rules are implementation-equivalent.
- A binding to a discovery Rule remains discovery-only and cannot enter OPA evaluation.
- Retirement of a Rule closes its binding for new resolution without deleting historical replay.
- Objective replacement creates a new version and explicit supersession; it never rewrites prior
  decisions.

A binding inherits the corpus of its referenced Rule. A discovery binding is indexed and returned
only when discovery scope was explicitly requested. A binding has no independent corpus-promotion
switch; promoting or retiring the referenced Rule through existing governance changes where the
binding may appear.

## Applicability and resolution

Objective-aware resolution uses existing authorities in this order:

1. Resolve the operator request into typed intent and exact ontology identities.
2. Search the requested corpus for objectives whose reviewed type, property, and outcome
  constraints match, then use digest-valid bindings to produce Rule candidates only.
3. Independently apply existing Rule lifecycle and Assignment governance to determine which exact
  Rules are active and eligible for evaluation at the requested scope.
4. Resolve Assignment parameters, effect, and enforcement without accepting values from the
  objective or binding.
5. Resolve `PolicyArtifact` through `implemented_by_policy` for each governance-eligible Rule.
6. Evaluate current schema-valid evidence through OPA or the registered deterministic evaluator.
7. Return a decision or hold for clarification. Only the normal governed action path may act.

Missing objectives do not block exact Rule-id evaluation. Missing or stale bindings disable the
objective-aware shortcut and fall back to exact or lexical Rule retrieval with explicit degraded
state. A discovery result never falls through into active evaluation.

## Equivalence and refinement

Embeddings and model-generated summaries may propose families, but they do not prove equivalence.
The refinement pipeline is:

```text
deterministic source parsing
  -> normalized candidate signatures
  -> candidate family proposal
  -> applicability and counterexample analysis
  -> independent equivalence validation
  -> reviewed objective and binding promotion
```

An `EquivalenceValidationReceipt` should pin the compared Rule versions, normalized predicate or
OPA AST digests, required evidence, parameter domains, counterexample set, validator version,
result, failures, and reviewer. It distinguishes:

- **same objective:** both Rules protect the same invariant;
- **same applicability:** both accept the same target and evidence domain;
- **same behavior:** both return the same result over the frozen counterexample set;
- **same implementation:** normalized deterministic logic is equivalent.

Only the first relation is required to share a `ControlObjective`. Automated promotion based only
on vector distance, names, categories, imported profile membership, or shared Rego imports is not
supported.

### Promotion gate

Mimir is the single accountable agent for objective and binding lifecycle transitions. Heimdall
produces independent validation receipts, but those receipts cannot promote an artifact. A Mimir
promotion record should require:

- schema, cross-reference, content-digest, provenance, and corpus validation;
- an independent equivalence receipt when equivalence is claimed;
- frozen counterexample and OPA regression results for every affected authored Rule;
- active/discovery isolation and authority-invariant checks;
- a reviewed catalog pull request and a rollback target.

The promotion record pins all evidence and emits a typed transition for Saga audit. Failure keeps
the candidate inert. Promotion changes search and explanation eligibility only; it never changes
Assignment effect, enforcement, risk, approval, or execution authority.

## Storage and scale

The 8,549-record corpus should not become one operating-graph release.

- **Semantic index:** Store all discovery records and all active Rules in separate complete
  generations. Every result retains its corpus and generation identity.
- **Operating graph:** Project reviewed objectives plus active bindings needed by assigned Rules,
  current questions, or declared competency packs. Preserve the existing 1,000-object bound.
- **Generation identity:** Use row count, a canonical digest root, and bounded chunk manifests for
  corpus-scale generations. Keep inline ordered digests only for small compatibility generations;
  the current 256-digest ceiling cannot represent the full corpus.
- **Replay:** Pin objective, binding, Rule, Assignment, policy, ontology release, and generation
  digests on every objective-aware resolution receipt.

Active and discovery generations use independent activation and rollback pointers. Activation of
one corpus never changes the other.

## Example: multi-zone node pools

The existing
[`kubernetes-node-pool.multi-zone` Rule](../../../rule-catalog/catalog/kubernetes-node-pool.multi-zone.yaml)
and its
[`node_pool_multi_zone.rego` policy](../../../policies/kubernetes/node_pool_multi_zone.rego)
provide a concrete migration example.

1. `ControlObjective reliability.node-pool.zone-failure-tolerance@1` states that a node pool
   remains available after one zone fails.
2. A binding pins that objective to the exact Rule version and declares Kubernetes node-pool,
   availability-zone evidence, and minimum-zone-count as variant dimensions.
3. An Assignment supplies the active scope, threshold, effect, and enforcement mode.
4. `implemented_by_policy` resolves the exact Rego artifact.
5. OPA evaluates the current zone list. Fewer than two zones returns the existing
   `single_zone_node_pool` denial.

The objective improves retrieval and explanation, but the Rule, Assignment, and Rego package still
determine the result. The objective and partial binding now ship as inert candidate records. They
grant no search, evaluation, promotion, or execution authority.

## Agent ownership

The fixed 15-agent pantheon is sufficient. No indexer or policy-abstraction agent is added.

| Stage | Accountable agent | Boundary |
|-------|-------------------|----------|
| Objective, binding, Rule, and policy lifecycle | Mimir | Reviews and promotes catalog artifacts; does not evaluate runtime evidence |
| Candidate family discovery | Norns | Produces inert candidates only |
| Equivalence and retrieval validation | Heimdall | Produces independent receipts; cannot promote |
| Bounded semantic context | Muninn | Materializes pinned read projections |
| Transition and resolution audit | Saga | Appends lifecycle and decision evidence |
| Natural-language presentation | Bragi | Translates and explains; never judges |
| Deterministic runtime decision | Forseti | Uses the resolved exact Rule and evidence; never executes |

Authority-bearing transitions remain typed event-bus messages. Mechanical builders and index
publishers run as Mimir-owned capabilities, not hidden decision makers.

## Operational requirements

| Concern | Required behavior |
|---------|-------------------|
| Failure and degradation | Missing, stale, or invalid objectives, bindings, receipts, or semantic generations fall back to exact and lexical Rule retrieval. They never broaden the candidate set or start evaluation. |
| Corpus mismatch | An active query rejects discovery bindings. A discovery query remains read-only and cannot resolve an evaluation target. |
| Build and rollback | A failed full generation leaves the prior pointer active. Rollback accepts only a retained, corpus-compatible, independently validated generation. |
| Graph limits | Projection stops before the configured object ceiling and reports truncation. An incomplete graph cannot prove that no objective or Rule exists. |
| Policy availability | If the exact evaluator or policy digest is unavailable, the request is held without a decision or action proposal. |
| Security | Source text is untrusted data. Parsers, enrichment, and search receive no executor identity; logs and receipts omit raw operator text, secrets, and provider errors. |
| Observability | Metrics report corpus, generation, objective candidates, binding candidates, ambiguity, stale rejection, fallback, validation holds, build latency, query latency, and rollback without recording query content. |
| Performance | Objective expansion, binding fan-out, result count, graph objects, chunks, and request time use configured hard bounds. Baseline and treatment latency, CPU, and storage are measured on the same 8,549-record revision before promotion; this design claims no unmeasured SLA. |

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Rule-to-policy boundary | in-progress | [`PolicyArtifact.yaml`](../../../rule-catalog/vocabulary/object-types/PolicyArtifact.yaml), [`implemented_by_policy.yaml`](../../../rule-catalog/vocabulary/link-types/implemented_by_policy.yaml) | Existing artifacts are reusable; this change did not revalidate their runtime path. |
| Semantic manifests and corpus isolation | in-progress | [`rule_semantic_retrieval.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/rule_semantic_retrieval.py), [Rule Semantic Retrieval](rule-semantic-retrieval.md) | Existing retrieval contracts lack the new typed objective and binding contract. |
| `ControlObjective` contract and catalog | implemented | [`control_objective.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/control_objective.py), [`ControlObjective.yaml`](../../../rule-catalog/vocabulary/object-types/ControlObjective.yaml), [`reliability.node-pool.zone-failure-tolerance.yaml`](../../../rule-catalog/control-objectives/reliability.node-pool.zone-failure-tolerance.yaml), [`test_control_objective.py`](../../../services/core-control-plane/tests/rule_catalog/test_control_objective.py) | Strict model, loader, digest, lifecycle, vocabulary, candidate record, and negative tests exist. The candidate grants no runtime authority. |
| `RuleObjectiveBinding` and equivalence receipts | in-progress | [`rule_objective_binding.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/rule_objective_binding.py), [`equivalence_validation.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/equivalence_validation.py), [`RuleObjectiveBinding.yaml`](../../../rule-catalog/vocabulary/object-types/RuleObjectiveBinding.yaml), [`EquivalenceValidationReceipt.yaml`](../../../rule-catalog/vocabulary/object-types/EquivalenceValidationReceipt.yaml), [`binding.node-pool-zone-resilience.yaml`](../../../rule-catalog/rule-objective-bindings/binding.node-pool-zone-resilience.yaml), [`test_shipped_policy_abstraction_catalog.py`](../../../services/core-control-plane/tests/rule_catalog/test_shipped_policy_abstraction_catalog.py) | Strict contracts and vocabulary exist. The shipped partial binding verifies canonical objective, Rule, normalized Rego, and evidence signatures and carries no equivalence claim; validator execution and reviewed receipts remain open. |
| Objective-aware projection and resolution | not-started | This design | Existing exact Rule and retrieval paths remain unchanged. |
| Full-corpus generation identity | not-started | [`rule_semantic_generation.py`](../../../services/core-control-plane/src/fdai/rule_catalog/schema/rule_semantic_generation.py) | The inline digest contract is bounded to 256 entries. |
| Shadow evaluation and governed rollout | not-started | This design | No objective-resolution benchmark or promotion receipt exists. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-13 | in-progress | Adopted the policy-abstraction design and implementation ledger; earlier foundation provenance was not reconstructed. | `current change`; deterministic catalog inventory reported 8,549 Rules, including 62 Rego and 8,487 expression records. | Deliver and validate P0-P4 below. |
| 2026-08-13 | in-progress | Added the strict, immutable `ControlObjective` contract with catalog cross-reference checks, canonical content digests, lifecycle validation, and authority-field rejection. | `current change`; `PYTHONPATH="$PWD/services/core-control-plane/src:$PWD/packages/service-contracts/src" .venv/bin/pytest -q --no-cov services/core-control-plane/tests/rule_catalog/test_control_objective.py` passed 7 tests; Ruff and diff checks passed. | Add objective vocabulary and shipped records, then complete binding and equivalence-receipt contracts for P0. |
| 2026-08-13 | in-progress | Added strict equivalence receipts that pin exact Rule versions, normalized predicates, evidence, parameter domains, counterexamples, validator identity, independent claims, and review state without adding promotion authority. | `current change`; focused schema tests passed 14 tests, including aggregate Rule and receipt digest drift, authority-field rejection, claim consistency, and the absence of a promoted receipt state. | Add `RuleObjectiveBinding`, validator execution, vocabulary declarations, and shipped records for P0. |
| 2026-08-13 | in-progress | Added strict `RuleObjectiveBinding` records with objective, Rule, evidence, and reviewed-receipt pins; bounded applicability deltas; declared variant dimensions without values; non-equivalence reasons; and review-gated lifecycle transitions. | `current change`; the combined P0 schema suite passed 23 tests and static diagnostics reported no errors. | Add vocabulary declarations and shipped objective, binding, and receipt records, then implement deterministic equivalence validation. |
| 2026-08-13 | implemented | Completed the P0 catalog contract with six ontology vocabulary declarations, canonical Rule and signature digests, and inert node-pool objective and partial-binding records. The binding records why configuration evidence does not yet prove observed zone-loss behavior and makes no equivalence claim. | `current change`; the focused objective, receipt, binding, Rule, vocabulary, and shipped cross-catalog suite passed 78 tests; Ruff passed on all changed Python files. | Implement deterministic equivalence validator execution and review-gated receipts, then backfill the remaining authored Rego Rules in P1. |

### Remaining work

- [x] P0 exited with strict schemas, loaders, canonical content and signature digests, lifecycle
  validation, ontology vocabulary, inert candidate records, and negative tests for
  `ControlObjective`, `RuleObjectiveBinding`, and equivalence receipts. The focused suite passed
  78 tests and Ruff passed on the changed Python files.
- [ ] P1 exits when all 62 authored Rego Rules have reviewed bindings and migration reports account
  for every active Rule without changing Rule ids or verdict behavior.
- [ ] P2 exits when active and discovery generations load all 8,549 current records independently,
  publish count/root/chunk identities, and prove atomic activation and rollback.
- [ ] P3 exits when objective-aware `catalog.search_rules` resolution is composed through the
  existing read-only function path and exact T0 evaluation still requires an active Rule and
  evaluation receipt.
- [ ] P4 exits when held-out English and Korean retrieval cohorts, counterexamples, stale evidence,
  corpus isolation, rollback, and shadow parity meet configured gates with zero authority escapes.

## Delivery plan

| Phase | Implementation scope | Focused exit evidence |
|-------|----------------------|-----------------------|
| P0 - contracts | Add schema models under `fdai/rule_catalog/schema/`, vocabulary declarations, strict loaders, invariants, and fixtures. | Schema and catalog tests reject unknown refs, digest drift, invalid lifecycle, and authority fields. |
| P1 - backfill and proof | Build normalized signatures, equivalence receipts, review workflow, and bindings for authored Rego Rules first. | Migration report is count-balanced; OPA fixtures and Rule identities are unchanged. |
| P2 - scalable generations | Extend generation identity to count/root/chunk manifests and add objective/binding search documents without merging corpora. | Full 8,549-record load, atomic activation, stale rejection, and rollback tests pass. |
| P3 - runtime composition | Extend catalog projection, objective-aware retrieval filters, resolution receipts, function registration, composition, and query planning. | Read-only search degrades explicitly; evaluation cannot start without exact active Rule and current evidence. |
| P4 - rollout | Run held-out retrieval and equivalence suites, shadow comparison, regression gates, governed promotion, and rollback drills. | Configured cohort thresholds pass, authority escapes remain zero, and prior generation rollback is replay-stable. |

P0 and P1 should use existing catalog and ontology contracts rather than creating a parallel store.
P2 and P3 should extend the existing semantic generation and typed function paths rather than add a
second search service. P4 promotes only reviewed artifacts and never promotes from embeddings.
Focused tests should live under the existing Core test ownership: schema and migration tests under
`services/core-control-plane/tests/rule_catalog/`, projection tests under
`services/core-control-plane/tests/core/ontology_platform/`, and generation adapter tests under
`services/core-control-plane/tests/delivery/catalog_search/`. Each phase records its exact focused
command and result in this ledger when it changes state.

## Migration and compatibility

- Existing Rule ids, versions, PolicyArtifact identities, Assignments, and OPA decision paths stay
  unchanged.
- Objective and binding fields are additive. Exact-id and lexical search continue when the new
  artifacts are absent.
- Backfill starts with the 62 authored Rego Rules. Collected expression records remain discovery
  material until provenance, normalized semantics, and review are sufficient.
- A migration report records bound, intentionally unbound, ambiguous, and rejected Rules. Totals
  must equal the input corpus count.
- Historical receipts without objective refs remain valid and explicitly legacy. They are not
  assigned a reconstructed objective after the fact.
- Rollback restores the prior objective, binding, and semantic-index generation pointers without
  changing the active Rule or policy catalog.

## Validation and acceptance

Implementation should include:

- schema, loader, digest, lifecycle, and cross-reference unit tests;
- property tests proving objective context and retrieval scores never raise authority;
- normalized AST and expression counterexample tests for equivalence receipts;
- catalog-projection tests for identity collisions and the 1,000-object ceiling;
- full-corpus tests for 8,549 records, active/discovery isolation, chunk completeness, activation,
  stale generation rejection, and rollback;
- held-out English and Korean retrieval cohorts with no-match and ambiguous questions;
- OPA regression fixtures proving objective resolution does not change allow or deny behavior;
- replay tests that pin every objective, binding, Rule, Assignment, policy, and evidence digest.

The design is accepted for implementation when all open ledger items have reviewable evidence,
the new abstraction introduces no evaluation or execution authority, every active objective path
terminates in an exact existing Rule, and removing the objective layer leaves exact Rule evaluation
behavior unchanged.

## Non-goals

- Replacing `Rule`, `PolicyArtifact`, Assignment, RuleSet, exemption, or promotion contracts.
- Projecting the full discovery corpus into the bounded operating graph.
- Treating ontology, search rank, embeddings, or model output as a policy decision.
- Automatically declaring equivalence or promoting an objective from semantic similarity.
- Adding a sixteenth agent, a second policy engine, or a second semantic-index service.
- Compiling collected expressions into Rego without provenance, review, and regression evidence.

## Related docs

| To learn about | Read |
|----------------|------|
| Rule search, semantic surfaces, and generations | [Rule Semantic Retrieval](rule-semantic-retrieval.md) |
| Assignment, effect, enforcement, and exemptions | [Rule Governance](rule-governance.md) |
| Catalog sources and normalized Rule shapes | [Rule Catalog Collection](rule-catalog-collection.md) |
| Shared operational meaning and objective semantics | [FDAI Operating Ontology](../architecture/operating-ontology.md) |
| Bounded graph and typed function infrastructure | [FDAI Ontology Safety Infrastructure](../architecture/operating-ontology-platform.md) |
| Fixed agent responsibilities | [Agent Pantheon](../agents/agent-pantheon.md) |
