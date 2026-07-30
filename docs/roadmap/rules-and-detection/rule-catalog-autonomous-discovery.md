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
