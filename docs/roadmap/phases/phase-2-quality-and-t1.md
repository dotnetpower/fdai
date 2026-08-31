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

## Deliverables

- **Continuous rule-update pipeline** (living rules), delivered as catalog-as-code PRs.
  P1 W-3 lands the deterministic in-process stages under
  [`services/core-control-plane/src/fdai/rule_catalog/pipeline/`](../../../services/core-control-plane/src/fdai/rule_catalog/pipeline):
  `ShadowEvaluator` replays a candidate rule set against a scenario set in judge-and-log
  mode; `RegressionGate` enforces zero policy-violation escapes + coverage ratio floor
  + missing-expected-rules cap; `RulePromotionController` records promote/rollback with
  a hash-chained audit entry; the `ContinuousRulePipeline` orchestrator composes all
  three. External wiring (source watcher + GitHub App PR delivery) plugs into these
  stages without editing `core/`.
- **LLM quality gate** guarding T2: mixed-model cross-check, deterministic verifier, and
  grounding. Execution eligibility is granted by the verifier, **never by the model**.
  Implemented in [`services/core-control-plane/src/fdai/core/quality_gate/`](../../../services/core-control-plane/src/fdai/core/quality_gate)
  with three DI Protocols (`CrossCheckModel`, `VerifierPolicy`, `GroundingSource`) and
  the `QualityGate` orchestrator that emits `eligible | abstain | disagree | deny`.
  In-memory fakes for every seam live under
  [`quality_gate/testing.py`](../../../services/core-control-plane/src/fdai/core/quality_gate/testing.py) so
  a fork can smoke the composition root without any live LLM.
- **Rubric hallucination filter** (subtractive): an optional
  [`RubricEvaluator`](../../../services/core-control-plane/src/fdai/core/quality_gate/rubric.py) scores a T2
  candidate's `reasoning_trace` against fixed criteria and the gate folds the minimum
  score into confidence via `min()` (never additive). Shadow-first, fail-closed, judge
  distinct from proposer. A `SelfConsistencySampler` adds an `action_stability` signal.
  Full design in [hallucination-rubric-gate.md](../decisioning/hallucination-rubric-gate.md).
- **T1 lightweight tier**: embedding similarity + safety-re-verified learned-action reuse.
  [`services/core-control-plane/src/fdai/core/tiers/t1_lightweight/`](../../../services/core-control-plane/src/fdai/core/tiers/t1_lightweight)
  ships the `T1Tier` orchestrator plus `EmbeddingModel` / `PatternLibrary` seams; the
  fake `DeterministicEmbeddingModel` + `InMemoryPatternLibrary` under
  [`t1_lightweight/testing.py`](../../../services/core-control-plane/src/fdai/core/tiers/t1_lightweight/testing.py)
  power reproducible unit tests without a real embedding model or pgvector.
- **Shadow → enforce promotion**, per-action, gated on measured metrics with zero policy escapes.
  [`services/core-control-plane/src/fdai/core/risk_gate/`](../../../services/core-control-plane/src/fdai/core/risk_gate) implements
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
- **Collector handoff**: Phase 1 collection-review packages are inert inputs to this phase. Mimir
  owns the reviewed candidate transition; the promotion controller records only shadow promotion
  or rollback evidence, and a separately authorized catalog-as-code merge changes the active
  revision. Snapshot storage, review-package merge, and controller output never activate rules by
  themselves.
- **New resource types**: detect provider schema changes, identify uncovered resource types, and
  generate **rule stubs that ship shadow-only and HIL-reviewed** - a stub is never auto-enforced.

### Global provider schema accounting

Provider schema discovery uses a separate, content-addressed evidence catalog rather than adding
every upstream type to the operational `ResourceType` vocabulary. The global catalog accounts for
every type in one complete immutable source revision, including unused, unobserved, preview-only,
read-only, and unsupported types. Operational vocabulary and relationship mappings remain a
reviewed semantic subset.

The Azure source is the generated `Azure/bicep-types-az` type index pinned to an immutable commit.
An internal mirror or signed offline bundle may supply the same tree and must produce the same
snapshot digest. The watcher never substitutes the current subscription's registered providers for
the global corpus because that would hide types the deployment doesn't use.

Each bounded run ends in one explicit state:

| State | Meaning | Promotion effect |
|-------|---------|------------------|
| `not_due` | The last complete check is within policy cadence. | Keep the previous complete snapshot. |
| `unchanged` | The complete source revision produces the current digest. | Record the check; create no proposal. |
| `compatible` | Types or API versions were added without removing a stable surface. | Append drift evidence; semantic work remains an inert review candidate. |
| `breaking` | A type or stable API version was removed, or incompatible changes coexist with additions. | Hold the pinned semantic surface and require governed review. |
| `policy_blocked` | Network policy permits neither primary nor mirror access. | Make no external call, retain the last complete snapshot, and report stale or unavailable evidence. |
| `unavailable` | Every allowed source failed integrity, completeness, timeout, or I/O checks. | Retain the last complete snapshot and create no semantic proposal. |

Relationship candidate refresh invalidates a changed provider type and only the transitive
relationship-reference component that depends on it. Unrelated provider components stay reusable.
The D4 review ledger preserves immutable prior and aligned contexts, the exact comparison, regression
receipts, and distinct-reviewer outcomes. Approval can create only a catalog pull request proposal;
it cannot activate a mapping or mutate the graph. An active proposal pointer is valid only while its
content-addressed generation artifact still exists. Rollback recomputes that artifact's digest before
moving the pointer.

Deterministic diffing compares normalized type identities and stable/preview API-version sets.
Removal is a tombstone in the evidence ledger, never immediate deletion from ontology or rule
catalogs. Only a material, policy-gated drift package enters the existing agent and architecture
review flow. A mechanical watcher never edits `ResourceType`, `LinkType`, relationship mappings,
rules, or policies, and no provider-schema record grants observation, approval, or execution
authority.

The implemented Azure path pins both evidence planes. `Azure/bicep-types-az` accounts for 3,405
global resource types, while `Azure/azure-rest-api-specs` contributes 6,896 explicit ARM ID
references and 5,382 Azure resource-definition markers. Exact and unresolved targets remain
separate. A content-addressed review classifies the 4,707 exact references into 908 endpoint pairs
without inferring LinkType or orientation. It records eight overlaps with existing reviewed mapping
IDs, keeps semantic review required, and fixes automatic promotion to false. Terraform defines a
daily Container Apps Job, while the runtime paths can restore and persist the append-only ledger
through the private PostgreSQL StateStore. Material drift is validated by Heimdall and published only
on the shadow `object.drift` topic with `event_type: provider.schema_drift`. A protected scheduled-run
receipt remains required before operational validation.

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
- **Mandatory evidence set**: the runtime-composed path requires both `what_if` evidence from the
  `simulation_engine` authority and `security` evidence from the `security_scanner` authority.
  Each versioned record binds the core-owned candidate digest, producer, observation and expiry
  times, evidence references, conflict status, and synthetic status. Missing, stale, conflicting,
  future-dated, candidate-mismatched, or synthetic evidence holds before any model cross-check.
  Explicit failed evidence denies the candidate. A fork must inject both provider-neutral verifiers
  together; partial binding fails at construction.
- **Grounding (RAG)**: force citation of the justifying rules/policies and **validate each cited
  item exists in the rule catalog and actually supports the claim** (guards fabricated citations);
  **abstain to HIL** when ungrounded.
- **Threshold gating**: schema, policy, what-if, and security-scan checks must all pass and a
  **confidence derived from verifier/cross-check signals** (not the model's self-report) must
  clear a configured threshold; below threshold routes to HIL. Outcomes are typed and audited:
  `eligible | abstain | disagree | deny`.

The first design considered extending the rule verifier with optional what-if and security callbacks.
That shape could silently skip an unbound callback and would let a single component self-attest
several evidence families. The revised design keeps rule authorization separate, gives each
deterministic evidence family a fixed authority class, and makes the production runtime bind explicit
unavailable verifiers until both real producers are injected. Direct QualityGate construction remains
available for isolated compatibility tests, but the shipped runtime cannot produce an eligible T2
candidate without both current independent records. Synthetic records can test mechanics only and
never satisfy live promotion.

## T1 Lightweight Tier

- **Similarity match**: embed each normalized event and match against the pattern library; a
  match requires the similarity score to clear a **configured threshold** (thresholds are config,
  not hard-coded), guarding against false matches.
- **Abstain path**: no rule match, similarity below threshold, or no applicable learned action
  → **abstain to T2** (per the T1→T2 boundary in [llm-strategy.md](../architecture/llm-strategy.md)).
- **Learned-action reuse (provenance + safety)**: a reused action carries provenance (source
  incident id, historical success rate) and is **re-validated through the verifier and risk gate
  before it can execute** - reuse is not auto-trust.
- **Evidence bounds**: similarity must be finite and within `[-1, 1]`; success rate must be within
  `[0, 1]`; reuse count and required action provenance must be valid. Malformed pattern-library
  evidence abstains instead of becoming a reuse candidate.
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

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/phases/phase-2-quality-and-t1.md) |
