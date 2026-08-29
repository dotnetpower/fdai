---
title: Autonomous Rule Discovery
---
# Autonomous Rule Discovery

This document owns the catalog discovery loop that proposes, verifies, and integrates rule
candidates from upstream and operational signals. Collection sources and normalization remain in
[Rule Catalog Collection](rule-catalog-collection.md).

## Design at a glance

Collection is not only "read upstream sources". The catalog also grows and self-corrects from
**operational signals**, so the deterministic layer keeps pace with the environment without a
human hand-crafting every rule. This is the "Living rules" principle in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).

## Loop

A long-horizon loop repeats indefinitely; every cycle keeps the same shared world model - the
normalized catalog, audit log, incident library, and provenance store - so cycles build on
each other rather than restart from scratch:

```text
sources + operational signals ─► observe ─► hypothesize ─► verify ─► integrate
                                                            (quality gate)
```

- **observe** - the loop reads three feeds side by side, not one at a time:
  1. **Upstream sources** via the collector pipeline above (new/changed controls).
  2. **Operational signals** - recent audit-log entries, HIL approval patterns, shadow-mode
     outcomes, rollbacks, and **override events** ([rule-governance.md](rule-governance.md)).
  3. **The current catalog** - existing rules, their provenance, their measured accuracy.
- **hypothesize** - an inference stage (an LLM stage, treated like any T2 output) proposes
  **candidate** entries in three shapes:
  - **new-rule**: a control not yet covered, motivated by a recurring incident/HIL pattern or a
    newly published upstream control.
  - **revision**: an existing rule whose upstream source changed (its `content_hash` moved)
    or whose shadow accuracy drifted below threshold.
  - **retirement**: an existing rule that is repeatedly overridden or whose shadow outcomes
    show it is a poor fit for real environments.
- **verify** - every candidate is inert data until it passes the standard **quality gate**:
  1. strict JSON Schema (`additionalProperties: false`);
  2. provenance check - `source_url`, `resolved_ref`, `content_hash`, `license`,
     `redistribution` all present and verifiable (a candidate with no grounded provenance is
     rejected outright);
  3. **mixed-model cross-check** - a second model (different family/vendor) re-derives or
     re-approves the same candidate; disagreement escalates to HIL, never auto-resolves
     ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md));
  4. deterministic verifier - Rego parses, no duplicate `id`, no conflict with existing rules
     that would silently weaken a stricter control;
  5. regression suite - existing fixtures still pass;
  6. shadow-mode dwell - the candidate runs judge-and-log-only on real traffic for a
     configured minimum period and sample size, with accuracy above threshold and zero
     policy-violation escapes.
- **integrate** - a candidate that clears the gate is promoted per the assignment/effect
  lifecycle in [rule-governance.md](rule-governance.md) (new-rule/revision lands as an audit
  effect first; a retirement lands as a tombstone). The catalog is only ever mutated by a
  merged catalog-as-code PR, never by the loop directly.

## Candidate Requirements (MUST)

- Every candidate MUST cite **grounded provenance** - an upstream document URL + resolved
  revision/hash, or a specific incident/HIL/override event id, or a specific
  vulnerability/advisory id. "The model thought of it" is not provenance.
- Every candidate MUST target the CSP-neutral `resource_type` vocabulary, never a vendor path.
- Reference-only source text MUST NOT be pasted into the candidate; only authored `check_logic`
  plus a citation, per the
  [Licensing](rule-catalog-collection.md#licensing-read-before-adding-a-source) rules.
- A candidate that fails any gate step becomes an **abstain** - logged with the reason so the
  next cycle can revisit it, but never partially applied.

## Override Feedback

Overrides are a first-class input to the loop, not a dead-end. When a rule accumulates
long-lived or recurring overrides across scopes, the observe stage flags it and the
hypothesize stage proposes a **revision** (narrow the rule so the override becomes unnecessary)
or a **retirement** (the rule is systematically a poor fit). Either way the proposal still
passes the full quality gate. Overrides never mutate the catalog directly - they only supply
signal.

## Safety and Trust

- The loop is a **candidate generator**, not an executor. It cannot mutate the live catalog,
  cannot flip an assignment to enforce, and cannot bypass the promotion approvals in
  [rule-governance.md](rule-governance.md).
- Any LLM stage in this loop is a T2 call and obeys the T2 quality gate (mixed-model,
  verifier, grounding, abstain-when-unsupported) in
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md).
- The loop's own throughput (candidates/cycle, gate pass rate, override-triggered proposal
  rate, retirement rate) is instrumented and reported in
  [goals-and-metrics.md](../architecture/goals-and-metrics.md) so it can be measured, not asserted.

## Candidate Guard (upstream implementation)

`fdai.agents._framework.candidate_guard.CandidateGuard` is the deterministic gate Mimir runs on every
`RuleCandidate` before it enters the pending list - the enforcement point for the Candidate
Requirements above and the discovery loop's poisoning defense. It never promotes anything (the
quality gate owns that); it decides **accept** vs **quarantine** and records a reason, so a
rejected candidate is preserved for audit rather than silently dropped. Checks are pure (no I/O,
no model call):

- **Provenance** - `proposed_by` and a known `proposal_kind`
  (`new` / `new-scenario` / `revision` / `retirement` / `threshold_adjustment`) are required.
- **Grounding** - a non-empty `evidence` mapping is required; an ungrounded candidate is
  quarantined ("the model thought of it" is not evidence).
- **Range sanity** - numeric evidence must be in range (a `rollback_rate` outside `[0, 1]` or a
  non-positive count is a corrupt or forged signal).
- **Flood detection** - identical candidate fingerprints beyond a repeat cap are quarantined as
  a suspected poisoning flood (Norns already dedups legitimate proposals, so a repeat burst is
  anomalous).

## Shadow Dwell Evidence (upstream implementation)

`fdai.core.operational_learning.shadow_dwell` is the deterministic half of quality-gate
step 6. It retains judge-and-log-only observations per candidate target, turns them into
a self-verifying `ShadowDwellEvidence` record (window, sample size, reviewed and agreed
counts, policy-violation escapes), and answers whether that record clears the configured
`ShadowDwellThresholds`. It promotes nothing and touches no catalog.

Three properties make it a gate rather than a formality:

- **Absent evidence is not consent.** A candidate with no dwell record is ineligible; it
  cannot pass by omission.
- **Evidence verifies itself.** The record travels on the wire from Norns to Mimir, so
  contradictory counts, an inverted window, or a naive timestamp are rejected outright
  instead of trusted. A record naming a different target cannot vouch for this candidate.
- **The escape allowance is not configurable.** The design says zero escapes, and a
  tunable escape budget is exactly the knob that gets turned under delivery pressure.

Norns retains a shadow audit outcome as a dwell observation instead of discarding it,
while still keeping shadow results out of the real rollback-rate learner, and attaches
the resulting evidence to the candidate it publishes. Mimir re-derives the verdict from
that wire evidence: `Mimir.promotion_ready_candidates()` omits any candidate that has not
proven its dwell, and `Mimir.promote()` refuses a rule whose pending discovery-loop
candidate is under threshold. Eligibility is still not promotion - the catalog changes
only through a merged catalog-as-code pull request.

## Bounded Cycle Runtime (upstream implementation)

`fdai.core.operational_learning.discovery_cycle` runs one interval-bucket cycle at a time. The
mechanical scheduler claims a stable cycle identity in `StateStore`, persists each stage with
revision compare-and-set, and replays an existing terminal record without calling a model or
publisher again.

The cycle keeps the discovery boundary explicit:

- **Observe:** An injected source returns one complete, bounded window containing upstream,
  operational, override, and catalog signals.
- **Hypothesize:** One configured off-path T2 model proposes inert candidates.
- **Verify:** At least one model from a different identity and family re-approves each canonical
  candidate. A digest mismatch, disagreement, incomplete source window, timeout, or deterministic
  verifier failure produces a retained hold or rejection.
- **Integrate:** An injected integrator can publish only an inert, review-required artifact. The
  cycle record and every metric state `grants_authority: false`; catalog mutation still requires the
  ordinary merged catalog-as-code pull request.

The scheduler bounds signal count, candidate count, elapsed time, and retained cycle history. It
publishes an audited state projection for candidates per cycle, gate pass rate, override-trigger
rate, and retirement rate. The `override` signal kind is the non-bus binding for the existing
override feedback path; `object.override` remains unsupported.

## Human Shadow Review Closure (upstream implementation)

Shadow outcomes now close their review gap through the existing agent owners. Saga publishes the
initial `object.audit-entry` with one stable shadow observation id and the policy-escape flag. Var
queues that exact record for a distinct human reviewer and publishes the resulting
`object.approval`. Saga then republishes the reviewed audit entry, and Norns upgrades the retained
observation by id instead of counting a second sample.

The reviewer cannot be the action initiator. Replayed or already reviewed observations do not
increase sample or reviewed counts, and the review cannot change the policy-escape fact recorded on
the original shadow outcome.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Candidate grounding and poisoning guard | implemented | `services/core-control-plane/src/fdai/agents/_framework/candidate_guard.py`; `services/core-control-plane/tests/agents/test_candidate_guard.py` | Mimir quarantines ungrounded, malformed, or flooding candidates without granting promotion authority. |
| Norns consensus | implemented | `services/core-control-plane/src/fdai/agents/_framework/norns_consensus.py`; `services/core-control-plane/tests/agents/test_norns_consensus.py` | All three deterministic perspectives must agree before Norns publishes an inert candidate. |
| Candidate review and catalog compilation | implemented | `services/core-control-plane/src/fdai/core/operational_learning/catalog.py`; `review.py`; `services/core-control-plane/tests/agents/test_mimir_catalog_review.py` | Review packages and bounded publication state are implemented; activation still requires the ordinary catalog-as-code path. |
| Override and operational-signal intake | implemented | `services/core-control-plane/src/fdai/core/operational_learning/discovery_contracts.py`; `services/core-control-plane/tests/core/operational_learning/test_discovery_cycle.py`; existing Norns override learner tests | A normalized override signal enters the bounded observe window without creating an unsupported `object.override` topic, and candidate metrics retain its exact signal identity. |
| Per-candidate shadow-dwell evidence and threshold gate | implemented | `services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py`; `services/core-control-plane/tests/core/operational_learning/test_shadow_dwell.py`; `services/core-control-plane/tests/agents/test_discovery_shadow_{dwell,review}.py` | Norns retains each shadow observation once, Var records a distinct human review, Saga stamps the reviewed audit entry, and Mimir still refuses insufficient, inconsistent, target-mismatched, or escaped evidence. |
| Long-horizon discovery cycle | implemented | `services/core-control-plane/src/fdai/core/operational_learning/discovery_cycle.py`; `services/core-control-plane/tests/core/operational_learning/test_discovery_cycle.py` | The interval-bucket scheduler persists observe, hypothesize, verify, and integrate stages with stable identities, timeout and volume bounds, revision fencing, terminal replay, and bounded retention. Deployment-supplied sources and models remain configuration, not embedded provider values. |
| Mixed-model cross-check | implemented | `services/core-control-plane/src/fdai/core/operational_learning/discovery_contracts.py`; `discovery_cycle.py`; focused cycle tests | Construction requires distinct model identities and families. Every candidate is digest-bound to independent re-approval, and disagreement or digest substitution stays held for human review. |
| Loop throughput metrics | implemented | `DiscoveryCycleMetrics`; focused cycle persistence tests | Each completed cycle stores an audited no-authority projection for candidates per cycle, gate pass rate, override-trigger rate, and retirement rate. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance. | `current change`; current source and focused tests listed in the scope table. | Complete the scheduled loop, shadow evidence, override intake, and mixed-model gate. |
| 2026-08-15 | in-progress | Implemented per-candidate shadow-dwell retention and the fail-closed threshold gate, and split the former combined scheduler/dwell row. | `current change`; `services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py`; `uv run pytest -q --no-cov services/core-control-plane/tests/core/operational_learning services/core-control-plane/tests/agents` passed (1214 tests). | Scheduler, mixed-model cross-check, loop metrics, and an audit-entry producer for operator review outcomes. |
| 2026-08-29 | implemented | Added the replayable bounded discovery cycle, independent-family candidate re-approval, override-aware audited throughput metrics, and the Var-Saga-Norns human shadow-review closure without adding catalog or execution authority. | `current change`; discovery cycle, persistence, shadow dwell, Var, and Saga paths; `uv run pytest -q --no-cov services/core-control-plane/tests/core/operational_learning services/core-control-plane/tests/agents/test_discovery_shadow_dwell.py services/core-control-plane/tests/agents/test_discovery_shadow_review.py services/core-control-plane/tests/agents/test_wave2_governance.py services/core-control-plane/tests/agents/test_wave3_pipeline.py services/core-control-plane/tests/agents/test_quorum.py services/core-control-plane/tests/agents/test_framework_layout.py services/core-control-plane/tests/agents/test_pantheon_doc_parity.py` passed 309 tests. | Retain a governed deployed cycle and live review cohort before raising any area to `validated`. |
| 2026-08-29 | implemented | Hardening round 1 closed a nested authority-field injection path in model-produced candidate payloads. The inert-candidate contract now searches every nested mapping and sequence before integration. | `current change`; `discovery_contracts.py`; `test_discovery_cycle.py`; focused tests passed 8 cases with Ruff and strict mypy. | Continue the bounded hardening campaign; governed deployment evidence remains separate. |

### Remaining work

- [x] Complete the bounded implementation scope: persist the four-stage cycle with replayable
  identities, retain one human-reviewed shadow sample without duplication, bind override signals and
  independent-family disagreement to review, and publish audited throughput metrics. Focused
  evidence is in `services/core-control-plane/tests/core/operational_learning/test_discovery_cycle.py`
  and `services/core-control-plane/tests/agents/test_discovery_shadow_review.py`.
