---
title: "Phase 2 - Continuous Rule Update, Quality Gate, and T1"
---
# Phase 2 - Continuous Rule Update, Quality Gate, and T1

**Goal**: keep the deterministic layer fresh, make LLM (T2) output safe to trust, add the T1
lightweight tier, and validate the auto-resolution rate against the P0 baseline - then promote
specific actions from shadow to enforce. This phase expands the tier/gate rules in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) and
the model-tier design in [llm-strategy.md](../architecture/llm-strategy.md). Coverage figures (T1 ~15-20%)
are **targets to validate**, not guarantees ([goals-and-metrics.md](../architecture/goals-and-metrics.md)).

> **Implementation status**: The continuous-rule-pipeline core, T2 quality gate, T1 tier,
> promotion registry, risk gate, and their deterministic tests are implemented. Composition from
> a production source watcher through GitHub PR delivery, measured T1 and auto-resolution exit
> evidence against the P0 baseline, the Assurance Twin model-backed natural-language compiler,
> and discovery-loop binding are incomplete. The percentages and Exit Criteria below are targets,
> not claims of current attainment.

## Deliverables

- **Continuous rule-update pipeline** (living rules), delivered as catalog-as-code PRs.
  P1 W-3 lands the deterministic in-process stages under
  [`src/fdai/rule_catalog/pipeline/`](../../../src/fdai/rule_catalog/pipeline):
  `ShadowEvaluator` replays a candidate rule set against a scenario set in judge-and-log
  mode; `RegressionGate` enforces zero policy-violation escapes + coverage ratio floor
  + missing-expected-rules cap; `RulePromotionController` records promote/rollback with
  a hash-chained audit entry; the `ContinuousRulePipeline` orchestrator composes all
  three. External wiring (source watcher + GitHub App PR delivery) plugs into these
  stages without editing `core/`.
- **LLM quality gate** guarding T2: mixed-model cross-check, deterministic verifier, and
  grounding. Execution eligibility is granted by the verifier, **never by the model**.
  Implemented in [`src/fdai/core/quality_gate/`](../../../src/fdai/core/quality_gate)
  with three DI Protocols (`CrossCheckModel`, `VerifierPolicy`, `GroundingSource`) and
  the `QualityGate` orchestrator that emits `eligible | abstain | disagree | deny`.
  In-memory fakes for every seam live under
  [`quality_gate/testing.py`](../../../src/fdai/core/quality_gate/testing.py) so
  a fork can smoke the composition root without any live LLM.
- **Rubric hallucination filter** (subtractive): an optional
  [`RubricEvaluator`](../../../src/fdai/core/quality_gate/rubric.py) scores a T2
  candidate's `reasoning_trace` against fixed criteria and the gate folds the minimum
  score into confidence via `min()` (never additive). Shadow-first, fail-closed, judge
  distinct from proposer. A `SelfConsistencySampler` adds an `action_stability` signal.
  Full design in [hallucination-rubric-gate.md](../decisioning/hallucination-rubric-gate.md).
- **T1 lightweight tier**: embedding similarity + safety-re-verified learned-action reuse.
  [`src/fdai/core/tiers/t1_lightweight/`](../../../src/fdai/core/tiers/t1_lightweight)
  ships the `T1Tier` orchestrator plus `EmbeddingModel` / `PatternLibrary` seams; the
  fake `DeterministicEmbeddingModel` + `InMemoryPatternLibrary` under
  [`t1_lightweight/testing.py`](../../../src/fdai/core/tiers/t1_lightweight/testing.py)
  power reproducible unit tests without a real embedding model or pgvector.
- **Shadow → enforce promotion**, per-action, gated on measured metrics with zero policy escapes.
  [`src/fdai/core/risk_gate/`](../../../src/fdai/core/risk_gate) implements
  `ActionPromotionRegistry.consider_promotion(metrics)` which evaluates the ActionType's
  `promotion_gate` (min_shadow_days / min_samples / min_accuracy / max_policy_escapes)
  against measured `PromotionMetrics` and records the resulting mode. `RiskGate.evaluate`
  reads that registry - a shadow-mode ActionType returns `hil`, an enforce-mode
  ActionType with clean invariants returns `auto`, and any invariant miss (blast-radius
  over cap, stale precondition, irreversible ActionType) forces `hil` regardless of mode.
- **Assurance Twin (query slice)**: a read-only ontology twin projected from inventory,
  with verified text-to-query answering that routes through the tiers and this phase's
  quality gate; ungroundable questions abstain and feed the rule discovery loop. Full
  design in [assurance-twin.md](../operations/assurance-twin.md); ambient review and whole-graph
  simulation land in P3.

## Continuous Rule Update Pipeline

```text
source watcher → collect/normalize → shadow eval → regression gate → promote | rollback
```

Every stage writes an audit entry; a rule change is itself a change and ships as a
**catalog-as-code PR** (never an out-of-band auto-edit), defaulting to shadow.

- **Source watcher**: subscribe where a feed exists, else poll on a configured cadence (per
  source); watch upstream rule/policy sources, resource-provider schema versions, and security
  advisories. Deduplicate by rule `id`, capture `source`/`version` provenance, and hold the
  per-source cadence and endpoints in configuration.
- **Collect/normalize**: map each candidate to the P1 normalized schema
  (`id, version, source, severity, category, resource-type, check-logic, remediation`); resolve
  conflicts by severity then source priority, ties → HIL (per
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)).
- **Shadow eval**: replay the candidate rule set against the frozen scenario set and recent real
  events in **judge-and-log** mode (no execution); measure coverage delta, false-positive and
  false-negative rates, and any policy-violation escapes.
- **Regression gate**: the P1 regression suite must pass with **zero policy-violation escapes**
  and no guard-metric regression ([goals-and-metrics.md](../architecture/goals-and-metrics.md)) before a
  set can be promoted; a failing regression blocks promotion.
- **Promote | rollback**: promotion is an explicit, reviewed catalog-as-code merge; **rollback
  triggers** are a failed regression, a shadow-eval escape, or a post-promote guard breach, and
  revert to the last-good versioned set.
- **New resource types**: detect provider schema changes, identify uncovered resource types, and
  generate **rule stubs that ship shadow-only and HIL-reviewed** - a stub is never auto-enforced.

## LLM Quality Gate (T2 - see [llm-strategy.md](../architecture/llm-strategy.md))

T2 inputs are **untrusted** ([security-and-identity.md](../architecture/security-and-identity.md)); the
verifier and policy re-check are the authority, not model text.

- **Mixed-model cross-check**: run **two or more independent models** (distinct providers/weights,
  not two endpoints of one base model - correlated errors defeat the check). Agreement is on the
  normalized structured action; with N ≥ 3 require a configured quorum. Any disagreement
  **escalates to HIL**, never auto-resolves.
- **Verifier**: a deterministic check, independent of any model, re-validates the candidate
  action against policy-as-code and what-if/dry-run. Only a verifier pass makes an action
  execution-eligible.
- **Grounding (RAG)**: force citation of the justifying rules/policies and **validate each cited
  item exists in the rule catalog and actually supports the claim** (guards fabricated citations);
  **abstain to HIL** when ungrounded.
- **Threshold gating**: schema, policy, what-if, and security-scan checks must all pass and a
  **confidence derived from verifier/cross-check signals** (not the model's self-report) must
  clear a configured threshold; below threshold routes to HIL. Outcomes are typed and audited:
  `eligible | abstain | disagree | deny`.

## T1 Lightweight Tier

- **Similarity match**: embed each normalized event and match against the pattern library; a
  match requires the similarity score to clear a **configured threshold** (thresholds are config,
  not hard-coded), guarding against false matches.
- **Abstain path**: no rule match, similarity below threshold, or no applicable learned action
  → **abstain to T2** (per the T1→T2 boundary in [llm-strategy.md](../architecture/llm-strategy.md)).
- **Learned-action reuse (provenance + safety)**: a reused action carries provenance (source
  incident id, historical success rate) and is **re-validated through the verifier and risk gate
  before it can execute** - reuse is not auto-trust.
- Target: absorb ~15-20% of events without a frontier round-trip, **validated by measurement**.

## Promotion (shadow → enforce)

- Promote **per-action**, explicitly and separately reviewed - never bundle enforce with a
  capability's first PR.
- Gate on the auto-resolution rate (metric 2) and **no guard-metric regression**, measured on the
  same frozen scenario-set version and reported with a **sample size and confidence interval**
  ([goals-and-metrics.md](../architecture/goals-and-metrics.md)); require **zero policy-violation escapes**
  in shadow.
- **Demotion**: any guard-metric breach or policy-violation escape demotes the action from enforce
  back to shadow automatically; leading indicators (disagreement rate, verifier abstain/fail rate)
  trigger investigation before a lagging guard regresses.

## Testability

- Property tests for the risk gate and quality gate: "high-risk never auto-executes",
  "shadow mode never mutates", "abstain/disagree/deny never execute".
- A shadow-mode test per action proving it judges and logs without mutating; a regression test
  per rule change ([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).
- A quality-gate regression proving ungrounded, fabricated-citation, and disagreeing output are
  blocked before execution. Tests are deterministic (seeded, no live network).

## Exit Criteria

- Auto-resolution-rate improvement is measured against the P0 baseline on the same scenario-set
  version, with sample size and confidence interval.
- The quality gate demonstrably blocks ungrounded, fabricated-citation, and disagreeing T2 output
  before execution (proven by regression tests).
- Rule updates flow through watcher → shadow eval → regression with audited, versioned rollback.
- T1 absorbs a measured share of events and abstains cleanly to T2 below threshold.

## Dependencies

- P0 baseline, telemetry, and guard-metric dashboard
  ([phase-0-instrumentation.md](phase-0-instrumentation.md)).
- P1 rule catalog and T0 engine running in shadow
  ([phase-1-rule-catalog-t0.md](phase-1-rule-catalog-t0.md)).
- Feeds forward into the integrated control loop
  ([phase-3-integrated-loop.md](phase-3-integrated-loop.md)).
