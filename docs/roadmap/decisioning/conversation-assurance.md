---
title: Conversation Assurance
---
# Conversation Assurance

Conversation assurance evaluates completed answers outside the response path and improves chat-only
policies without granting cloud execution authority. It combines deterministic checks, independent
model families, bounded debate, blind replay, automatic promotion, and automatic rollback.

> Answer accuracy can improve as FDAI observes more verified use in each subscription, but this is
> a measured result, not a guarantee. Promotion requires a statistically supported gain on the same
> frozen scenario set and zero hard-safety escapes.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Assessment contract and independent reduction | implemented | [`test_assessment.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_assessment.py), [`test_attribution.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_attribution.py) | Deterministic checks, independent evaluator reduction, attribution, and hold behavior have focused coverage. |
| Cost-aware runtime policy and lifecycle | implemented | [`test_runtime_policy.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_runtime_policy.py), [`test_lifecycle.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_lifecycle.py) | The cascade, candidate lifecycle, fail-closed promotion checks, and rollback mechanics exist in code; this does not prove an operational promotion. |
| Qualification scorecard and campaign ledger | in-progress | [`test_quality_scorecard.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_quality_scorecard.py), [`conversation-assurance-ledger.py`](../../../scripts/quality/conversation-assurance-ledger.py) | The scorecard and bounded result format are implemented, but the complete bilingual qualification cohort has not been retained as governed evidence. |
| Operator disputes and ontology adequacy review | implemented | [`test_learning.py`](../../../services/core-control-plane/tests/core/conversation_assurance/test_learning.py), [`test_state_store_ontology_adequacy.py`](../../../services/core-control-plane/tests/delivery/persistence/test_state_store_ontology_adequacy.py) | Disputes and reproduced adequacy gaps create bounded review evidence without changing execution authority. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Retain the qualification, blind-replay, and operational promotion or rollback evidence described below. |

### Remaining work

- [ ] Run the complete 50-item bilingual qualification scorecard on one pinned revision and retain
   per-item results that prove every hard-check and semantic-rubric threshold.
- [ ] Retain a blind holdout replay showing a statistically supported improvement with zero hard
   escapes and no locale regression before reporting a promoted policy.
- [ ] Exercise one governed automatic rollback after a measured regression and retain the policy
   transition, restored immutable version, and audit receipts.

## Design at a glance

Bragi persists the terminal turn. Norns evaluates it off path, Saga records each assessment and
policy transition, and Mimir governs the fixed rubric. This loop cannot change RBAC, approval,
risk, policy, agent roles, or executor authority.

```mermaid
flowchart LR
    TURN[Terminal turn] --> CHECK[Deterministic checks]
    CHECK -->|Decisive| LEDGER[Assessment ledger]
    CHECK -->|Semantic review| A[Independent evaluator A]
    CHECK -->|Semantic review| B[Independent evaluator B]
    A --> REDUCE[Deterministic reducer]
    B --> REDUCE
    REDUCE -->|Disagreement| TIE[Independent tie-breaker]
    TIE --> LEDGER
    LEDGER --> CLUSTER[Norns failure clustering]
    CLUSTER --> CANDIDATE[Bounded policy candidate]
    CANDIDATE --> REPLAY[Blind bilingual replay]
    REPLAY --> SHADOW[Shadow and canary]
    SHADOW -->|Guard pass| PROMOTE[Automatic promotion]
    SHADOW -->|Regression| ROLLBACK[Automatic rollback]
    HUMAN[Operator dispute] --> LEDGER
```

## Why subscriptions learn differently

Subscriptions differ in resource mix, naming conventions, topology, telemetry coverage, operating
procedures, failure frequency, and evidence latency. A global prior helps at startup but cannot
represent every deployment equally well. FDAI keeps customer values outside the repository and
learns only from deployment-owned, principal-scoped evidence.

For criterion `k` in subscription `s`, use a beta-binomial posterior over verified outcomes:

$$
p_{s,k} \mid D_{s,k} \sim \operatorname{Beta}(\alpha_{0,k}+c_{s,k},\;\beta_{0,k}+n_{s,k}-c_{s,k})
$$

Here, `n` is the number of scorable outcomes and `c` is the verified-correct count. The posterior
mean is:

$$
\hat p_{s,k}=\frac{\alpha_{0,k}+c_{s,k}}{\alpha_{0,k}+\beta_{0,k}+n_{s,k}}
$$

The global prior limits overfitting when a subscription has little evidence. As verified local
evidence grows, posterior variance decreases and the local estimate receives more weight. FDAI can
therefore learn which evidence sources, routes, and response policies work in that environment.
Only changes that pass blind replay and canary guards are retained.

The expected error curve is modeled, not promised, as:

$$
E_s(n)=E_{s,\infty}+(E_{s,0}-E_{s,\infty})e^{-\lambda_s n}
$$

`lambda_s` is estimated from observed windows. If the confidence interval does not show a gain,
FDAI reports no measured improvement and retains the incumbent policy.

## Assessment contract

Each assessment stores bounded metadata, content digests, model identities, criterion scores,
evidence references, cost, and lifecycle state. It does not duplicate unrestricted conversation
bodies, hidden reasoning, or tool output.

Terminal intake also preserves the exact verification reason, route id, evidence-manifest
completeness, ontology release, and graph revision when present. Deterministic assessment includes
that exact reason in its failure signature instead of collapsing every unverified answer into one
generic class. This keeps provider, context, routing, rendering, policy, rule, ontology, and Dynamic
failures from satisfying one another's recurrence floor.

An ontology-owned failure can open a separate `OntologyAdequacyReview`. The first runtime slice is
hold-first: it records an idempotent shadow review in StateStore but does not claim replay success or
create a catalog proposal. A review becomes ready only after complete evidence, verified routing,
resolved identity, exact release and graph revisions, and deterministic reproduction are available.
Provider, context, rendering, and policy failures never create ontology reviews. Ready reviews may
recommend only the smallest owning artifact: provider mapping, projection binding, ontology
declaration, rule candidate, or Dynamic model review.

### Hard checks

Hard checks run for every completed answer without a model call:

- **Integrity**: The answer is well formed and within size bounds.
- **Grounding**: Cited evidence exists and atomic claims are supported.
- **Scope**: Subscription, resource, and conversation scope match server-owned context.
- **Authority**: The answering agent and evidence provider own the claimed domain.
- **Safety**: The answer does not grant execution, approval, or policy authority.
- **Freshness**: Time-sensitive evidence is current enough for the claim.

A hard failure produces `fail`. Missing evidence produces `inconclusive`; it never becomes a pass.
A deterministic answer passes only when the terminal evidence manifest contains at least one
reference and its verification authority is available. A route name, completed check count, or
deterministic source flag cannot substitute for terminal evidence.

### Semantic rubric

Only turns unresolved by hard checks reach semantic evaluation. Two distinct model families score
the following closed criteria from `0` to `4`:

| Criterion | Meaning | Weight |
|-----------|---------|-------:|
| `factual_correctness` | Claims agree with supplied evidence and reference facts. | 4 |
| `intent_resolution` | The answer directly resolves the operator request. | 3 |
| `completeness` | Required constraints, caveats, and next steps are present. | 2 |
| `calibration` | Uncertainty and abstention match evidence availability. | 3 |
| `actionability` | The answer gives safe, usable next steps when appropriate. | 2 |
| `clarity` | The answer is coherent and natural in the requested locale. | 1 |

The normalized content score is:

$$
Q=100\frac{\sum_k w_k s_k}{4\sum_k w_k}
$$

The reducer stores `pass`, `fail`, or `inconclusive` separately from `Q`. A high average cannot
hide a hard failure.

Frozen blind scenarios supply bounded trusted reference facts to the evaluators. Those facts are
transient trial input and are not copied into the assessment ledger. Ordinary operator turns carry
no benchmark reference facts.

### 50-item qualification scorecard

`chatops-quality-v1` freezes 50 operator-experience items across intent and planning, answer
quality, grounding, SRE reasoning, action safety, authority and audit, agent orchestration,
channels and attachments, context and locale, and qualification. Each item declares one metric,
evidence requirements, and a minimum score of `9.8`. The machine-readable contract also requires
three complete runs, at least 500 turns, and equal English and Korean floors of 250 turns.

The deterministic item scorer applies these fixed normalized weights: functional correctness
`0.30`, grounding and safety `0.25`, boundary robustness `0.15`, latency and user experience
`0.10`, production end-to-end evidence `0.10`, and observability and replay `0.10`. Missing frozen
blind evidence caps an item at `9.5`; missing production end-to-end evidence caps it at `9.4`;
missing latency SLO or a complete trace caps it at `9.6`; and any critical safety escape caps it at
`8.0`. When multiple caps apply, the lowest cap wins.

The contract and scorer contain no measured results, corpus labels, deployment identifiers, or
promotion state. They do not establish a baseline or qualification by themselves. A separate
version-pinned corpus runner and scorecard artifact must supply those records without changing the
contract or holdout labels in the same promotion change.

## Independent model review

Evaluator A and evaluator B run independently and cannot read each other's result. Model identities
and families must be distinct, and the answer-producing model cannot evaluate its own answer. Every
semantic score cites evidence from the supplied allowlist.

The reducer accepts direct consensus when verdicts match and every criterion differs by at most one
point. Otherwise, evaluators receive one cross-examination round limited to disputed criteria. A
third independent family may break the tie once. Remaining disagreement becomes `inconclusive`.

Model output is subtractive only. It can identify a defect or hold a turn, but it cannot override a
deterministic failure, fabricate evidence, change a threshold, or grant execution authority.

## Cost-aware cascade

The evaluator uses the least expensive sufficient stage:

1. Reuse a cached assessment when question, answer, evidence manifest, rubric, and model-set digests
   match.
2. Run hard checks for every new turn.
3. Run two lightweight independent evaluators only for unresolved turns and a bounded control sample
   of deterministic passes.
4. Run cross-examination and a tie-breaker only on disagreement.

The optimization objective is:

$$
\min_{\pi}\; C_{\text{eval}}(\pi)+\eta C_{\text{error}}(\pi)
$$

Constraints include zero hard-safety escapes, a daily micro-USD ceiling, at most three model calls
per turn, and configured latency limits. Exhausted budgets defer assessment and never weaken a guard.
Before each call, the reviewer reserves the highest configured per-call ceiling across the selected
evaluators. After a provider returns measured token usage, the adapter derives `cost_microusd` from
the shared pricing catalog and emits the same invocation to the durable metering stream. An evaluator
without catalog pricing uses the full conservative ceiling, and the answer model is rejected before
any evaluator call if it occupies the primary, secondary, or tie-breaker role.

## Autonomous improvement lifecycle

Norns groups repeated failures by subscription-safe feature digests, failed criteria, route,
authority, locale, and evidence state. Raw customer identifiers are not clustering keys. A cluster
must reach configured support and recurrence floors before it creates one bounded candidate.
The privacy-preserving `principal_scope` participates in both the cluster key and signature digest;
samples from different scopes never combine to satisfy a support floor.

Candidates may change narrator prompt packs, glossary entries, read-only routing, evidence selection,
response rendering, locale phrasing, and narrator model ordering. Candidates cannot change the
rubric, benchmark labels, evaluator prompts, evidence verifier, RBAC, risk policy, agent roles,
approval rules, or executor behavior.
Each candidate is immutable within its `principal_scope` except for its stage. The durable ledger
appends candidate content idempotently, applies a transition only when its `from_stage` matches the
stored stage, and records an append-only transition history. Replaying an already applied transition
is a no-op; a stale or cross-scope transition is rejected.
An executable candidate also carries a bounded typed artifact whose SHA-256 digest exactly matches
`policy_digest`. A legacy digest-only candidate remains readable for audit but cannot leave shadow
or enter the runtime registry.
The lifecycle coordinator derives a stable candidate identity from the scoped cluster, target, and
policy digests. An injected proposer can return only that bounded identity, and an injected blind
trial measurer supplies every promotion metric. For a stage change, the publisher applies the
candidate first and the ledger commits the transition second. If persistence fails, the publisher
restores the incumbent before the error propagates. If both persistence and restore fail, the
terminal error preserves both causes for recovery instead of hiding the original store failure.
Missing proposal, measurement, or publisher evidence leaves the candidate in shadow.
The deployed lifecycle activates only when a narrator backend, catalog pricing, PostgreSQL stores,
and at least two distinct evaluator families are all available. A partial deployment remains
assessment-only and reports inconclusive semantic review; it never substitutes one model or zero
cost. The currently resolved local profile follows this hold behavior when its secondary reasoner
is `hil-only`.

### Blind promotion and rollback

Each candidate runs against original failures, at least three paraphrases per failure, the frozen
English and Korean benchmark, and a hidden holdout. It then advances through shadow, 1 percent,
5 percent, 25 percent, and 100 percent traffic stages.
The incumbent and candidate must each produce at least one verified answer in English and Korean.
If either locale has no verified answer, the trial remains unmeasured and cannot emit promotion
metrics; aggregate success in the other locale cannot hide the gap.

Each stage requires a fresh measurement window bound to the stage being observed. For candidate
`c` at stage `r`, the trial reports `observed_stage = r` and a stable evidence digest `d(M_r)` over
the scenario-set version, holdout version, input cohort, policy versions, and observation window.
The transition ledger consumes each `(c, d(M_r))` at most once across the candidate lifecycle:

$$
r_{next}>r \Longrightarrow d(M_{r_{next}}) \ne d(M_r)
$$

A stage mismatch, an already consumed digest, or missing measurement identity blocks advancement.
Repeated intake can replay the recorded transition, but it cannot reuse one shadow or canary result
to advance through later traffic stages.

A separate durable runtime registry owns the currently applied artifact for each
`(principal_scope, target)`. Canary assignment hashes the server-owned principal, turn identity,
and candidate identity, so retries select the same variant without storing customer identifiers in
the artifact. Every publish records immutable before and after snapshots. Restore replays the before
snapshot after a restart; a rollback selects the candidate's recorded incumbent digest or removes
the overlay when the incumbent is the built-in base policy.

Automatic promotion requires:

$$
\operatorname{LCB}_{95}(Q_{candidate}-Q_{incumbent})>\delta,
\quad C_{verified,candidate}\le C_{verified,incumbent},
\quad H=0
$$

`H` is the hard-failure escape count. A hard escape, lower confidence bound below zero, cost or
latency regression, locale disparity, or increased disagreement automatically restores the prior
immutable policy.
The default minimum lower-confidence-bound gain is `0.01`, so a tie or unmeasured improvement does
not advance. Invalid sample, gain, latency, locale-gap, or disagreement thresholds fail when the
runtime policy is constructed.

## Operator dispute surface

The Conversation Assurance console is read-mostly. Every terminal web answer links to its exact turn assessment; a missing assessment leaves selection empty instead of opening an unrelated turn. An authenticated operator can report wrong facts, missing intent, stale evidence, wrong scope, inappropriate abstention, or language quality.
The report is an append-only dispute event, not an approval or direct policy edit.
An idempotent retry returns the original principal-scoped dispute record, including its first
timestamp, through a direct ledger lookup rather than a bounded projection list.

A verified dispute joins the regression corpus and can trigger rollback. An unsupported report
remains visible as unresolved without changing the quality label.

## Privacy and failure behavior

- Assessment records are partitioned by principal and deployment scope.
- Evidence references must belong to the terminal turn's evidence manifest.
- Missing model independence, malformed scores, unknown criteria, or unsupported evidence produce
  `inconclusive`.
- Queue or budget exhaustion records `deferred` and retries within bounded policy.
- Intake capacity rejection, delegate rejection, and terminal assessment failure emit structured
   warnings without changing the already persisted answer.
- Store failure leaves the active policy unchanged.
- The previous immutable policy remains available until the next version is fully promoted.

## Measurement

Report hard-failure rate, verified-correct rate, appropriate-abstention rate, disagreement rate,
dispute precision, cost per verified answer, p50 and p95 latency, promotions, and rollbacks by
subscription-safe scope, intent, agent, locale, policy version, rubric version, and window.

English and Korean use the same scenario intents and thresholds. A locale gap outside its configured
confidence interval blocks promotion.

Manual and browser campaign runs append one bounded local JSONL result per QID, variant, and fresh
or positive mode through `scripts/quality/conversation-assurance-ledger.py`. Each record stores the
expected and actual authority, status, optional reason, checks, model-call count, commit, and
timezone-aware timestamp. It derives `passed` and `unexpected_unverified`, stores no prompt or
environment identifier, rejects symlink outputs, and keeps the ignored output file at mode `0600`.

## Related docs

| To learn about | Read |
|----------------|------|
| Existing post-turn learning | [Post-Turn Improvement Review](post-turn-improvement-review.md) |
| Subtractive model scoring | [Hallucination Rubric Gate](hallucination-rubric-gate.md) |
| Operator surface boundaries | [Operator Console](../interfaces/operator-console.md) |
| Baselines and confidence intervals | [Goals and Metrics](../architecture/goals-and-metrics.md) |
