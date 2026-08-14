---
title: Operational Planning Hardening Evidence
---
# Operational Planning Hardening Evidence

This document records the implementation and adversarial review evidence for operational planning.
It separates implemented shadow behavior from the release evidence required before enforcement
promotion.

> **Scope:** The review covers typed logic assets, deterministic selection, specialist evidence,
> sandbox and twin simulation, durable Process recording, execution handoff, the Planning Room,
> runtime availability, and bounded inputs.
>
> **Result:** Twelve independent review rounds left no known Medium, High, or Critical defect.
> Remaining items are Low release-readiness gaps and cannot raise authority because planning stays
> in shadow mode.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Planning, simulation, durability, and handoff mechanics | implemented | [Implementation evidence](#implementation-evidence), [Review rounds](#review-rounds) | Twelve adversarial rounds retain focused implementation and regression evidence without granting execution authority. |
| Frozen scenario coverage | in-progress | [Residual risk](#residual-risk) | The manifest remains `partial` because partial-execution recovery still uses an explicit release-evidence proxy. |
| Fail-closed live shadow observation | validated | [Live shadow proof](#live-shadow-proof) | The retained 2026-08-03 observation reproduced an ineligible result with zero mutation; it does not validate enforcement. |
| Enforcement readiness | not-started | [Residual risk](#residual-risk) | The pre-dispatch kinetic writer, verified independent observer, protected-runner recovery, production graph Dynamic evidence, and production executor binding remain open. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated validated shadow evidence from enforcement readiness. | `current change`; review rounds, live shadow proof, and residual-risk evidence in this document. | Complete the three release-evidence exits below. |
| 2026-08-14 | in-progress | Corrected the Lane F contract to expose the missing pre-dispatch exact-plan writer and verified independent effect-observation adapter instead of treating them as implied by the executor and graph bindings. | `current change`; `config/ohl-scale-out-evidence.json`, the runbook gate, and focused manifest checks. | Bind both exact sources before starting the protected live mutation phase. |

### Remaining work

- [ ] Bind the kinetic receipt writer before provider dispatch and a Heimdall-owned verified
    independent effect-observation adapter; prove neither source is reconstructed or substituted.
- [ ] Complete the protected-runner partial-execution recovery drill and retain authenticated
    compensation, independent closure, rollback, and cleanup receipts.
- [ ] Bind production graph Dynamic evidence to one exact ontology release and retain a complete,
    non-synthetic planning receipt.
- [ ] Bind the production `ops.scale-out` executor and retain 100 live-shadow samples across 14
    days with zero policy escapes and a verified rollback sequence before promotion review.

## Design at a glance

The campaign used one rule throughout: a finding counted only when it was reproducible against the
implemented contract. Confirmed Medium-or-higher findings received a focused regression test and a
separate hardening commit. Findings that confused proposal evidence with execution authority were
rejected instead of producing unnecessary code.

## Implementation evidence

| Capability | Evidence |
|------------|----------|
| Logic identity and authorization | Canonical releases pin typed functions; invocation checks agent, role, purpose, input schema, artifact digest, and deterministic seed. |
| Decision planning | Hard constraints precede Pareto pruning and existing weighted arbitration. No-action baselines and rejected reasons remain immutable. |
| Agent collaboration | Existing specialist topics feed an optional Forseti coordinator. No direct agent calls, new agent, or shared mutable workflow state were added. |
| Simulation | Reviewed programmatic pipelines and active/challenger twin models produce typed receipts. Missing, malformed, stale, or divergent evidence holds the plan. |
| Durability | Existing Workflow and Process snapshots plus append-only child events record planning phases with idempotent replay. |
| Execution handoff | A selected option compiles to a proposal-only MutationPlan with exact target and release identity. Risk, approval, execution, recovery, and audit remain separate. |
| Effect closure | The selected option, MutationPlan, and ResponseOutcome prediction id form one exact chain before success can close. |
| Product surface | The existing Process route exposes a strict read-only Planning Room projection. It adds no mutation route or executor identity. |
| Runtime operation | Startup logs availability, enablement, shadow mode, reason, and missing prerequisites from one immutable capability status. |

## Review rounds

| Round | Focus | Outcome |
|------:|-------|---------|
| 1 | Agent authority and separation of duties | No authority bypass. A claim that MutationPlan compilation executed an action was rejected because the artifact is proposal-only. |
| 2 | Deterministic replay | Fixed candidate, effect, and receipt ordering so equivalent input produces byte-identical cases and plans. |
| 3 | Constitutional constraints | Confirmed missing, stale, conflicting, or review-required context becomes ineligible and cannot reach arbitration. |
| 4 | Fan-out and candidate enumeration | Confirmed the specialist domain set is bounded and candidates above the hard cap fail instead of truncating. |
| 5 | Compute sandbox isolation | Confirmed reviewed source digest, generated client, capability token, tool allowlist, timeout, byte ceilings, no credentials, and no general network. |
| 6 | Twin evidence and model replay | Fixed effect ordering so equivalent active/challenger inputs produce one stable simulation receipt. |
| 7 | Process durability and concurrency | Fixed PostgreSQL child-event replay with atomic idempotency conflict handling and one outbox winner. |
| 8 | Execution and outcome lineage | Bound closure to the exact selected plan, ActionType, MutationPlan, and prediction id. |
| 9 | Planning Room security and responsive layout | Confirmed strict decoding, correlation checks, read-only routing, and no action controls. Added narrow-screen cell wrapping. |
| 10 | Frozen scenario truthfulness | Downgraded the manifest to partial and marked two release-evidence proxies explicitly. |
| 11 | Runtime observability and degradation | Added structured capability status. Missing optional evidence bindings remain visible and do not block unrelated agent work. |
| 12 | Target binding and adversarial bounds | Bound plans to the frozen target and added pre-artifact limits for objectives, effects, constraints, simulations, text, and the complete nested evidence manifest. |

## Live shadow proof

On 2026-08-03, a read-only observation used a generic non-production Azure Container App as the
target. Only allowlisted state fields were canonicalized; no resource name, account identifier,
endpoint, identity, secret reference, or raw deployment payload entered the repository.

The observed target had conflicting current and ready revision evidence. Operational planning
therefore produced an `ineligible` assessment with `held_no_eligible_option`, no selected option,
and no execution attempt. A second read produced the same allowlisted state digest. The proof
demonstrates fail-closed live evidence handling and zero Azure mutation; it does not claim a
successful enforcement drill.

## Residual risk

The frozen scenario manifest remains `partial` for one explicit proxy:

- **Partial execution recovery:** Contract tests close a mismatched outcome with verified rollback,
  but a dedicated non-production partial-execution drill remains release evidence. The bounded
  contract and protected-runner commands are prepared in
  [OHL Scale-Out Evidence Runbook](../../runbooks/ohl-scale-out-evidence.md).

A0 planning and the shipped irreversible `ops.scale-out` ActionType now provide explicit A3-E
non-applicability evidence. The remaining completion gates require the protected-runner live drill,
the pre-dispatch kinetic writer, a verified independent effect observer, production graph Dynamic
evidence binding, and production `ops.scale-out` executor binding. The provider-side Azure CLI
drill is not FDAI end-to-end execution evidence by itself.

These gaps are Low for the shipped shadow capability because none can enable execution. They block
a future enforcement promotion until replaced by verified scenario evidence. The capability
status, shadow mode, ordinary risk path, fixed observation and recurrence windows, and zero
policy-escape requirement remain authoritative.

## Verification

Focused validation covers the operational-planning subsystem, frozen manifest and Lane F config
schemas, scale-out planning, twin and outcome contracts, protected-runner command contract,
translation freshness, punctuation, and diff hygiene. Central integration validation remains the
merge-boundary authority.

## Related docs

| To learn about | Read |
|----------------|------|
| Operational planning design | [Operational Planning](operational-planning.md) |
| Agent ownership and arbitration | [Agent Pantheon](../agents/agent-pantheon.md) |
| Read-only graph simulation | [Assurance Twin](../operations/assurance-twin.md) |
