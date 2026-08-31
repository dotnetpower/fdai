---
title: MSCP Operational Profile
---
# MSCP Operational Profile

The `mscp-operational-v1` profile adapts selected ideas from the
[Minimal Self-Consciousness Protocol (MSCP)](https://github.com/dotnetpower/mscp)
to FDAI's operational safety model. It preserves source provenance without claiming that FDAI
implements every MSCP level or satisfies full MSCP conformance.

> The MSCP source repository remains independent and unchanged by this implementation. FDAI pins
> the reviewed source revision `b66401cb4d3b43ee8d66e6ce106c51defd4c6d3a` in code.

> The profile is not an execution authority. The trust router, quality gate, risk gate, human
> approval, executor, rollback principal, promotion registry, and audit store retain their existing
> ownership.

## Design at a glance

The profile supplies deterministic, I/O-free policy primitives under
`services/core-control-plane/src/fdai/core/mscp_profile/`. Callers provide already collected observations, limits, and
component digests. The profile returns typed verification or hold decisions and never calls a
provider, changes a resource, writes an audit entry, promotes a capability, or edits a rule.

The runtime identifier deliberately omits an MSCP level. FDAI combines selected concepts from more
than one level, while each module docstring and the mapping below retain the level-specific design
provenance.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Profile identity and deterministic policy primitives | implemented | `core/mscp_profile/profile.py`; `cycle_guard.py`; `runtime_integrity.py`; focused tests under `tests/core/mscp_profile/` | Source provenance, non-conformance, bounded cycle checks, and runtime-manifest comparison are implemented as pure policy. |
| Optional effect observation and `ResponseOutcome` projection | implemented | `core/mscp_profile/effect_verification.py`; `response_outcome.py`; `test_control_loop_shadow.py`; `test_response_outcome.py` | Pair-only composition preserves executor outcomes and writes shadow evidence without adding authority. |
| Never-raising authority ceiling | implemented | `core/mscp_profile/authority_ceiling.py`; `test_authority_ceiling.py` | Exhaustive finite-domain tests prove that the profile can only preserve or lower the existing FDAI decision. The ceiling is not connected to the enforce path. |
| Conflict-aware authority lowering | implemented | `core/ontology_platform/evidence_conflict.py`; control-loop and HIL resume checks | Canonical Property semantic intersections reuse the never-raising ceiling to hold only related ActionTypes. Missing conflict state fails closed before executor I/O. |
| Rule-governance coexistence | implemented | `runtime/control_loop.py`; `core/control_loop/_process.py`; focused governance safety-path tests | Assignment observation and exemption holds occur before dispatch. They do not activate MSCP effect observation, synthesize a `ResponseOutcome`, or alter the profile lifecycle. |
| Decision-context projection and governed gating | not-started | [Adopted mechanisms](#adopted-mechanisms); [Activation and runtime behavior](#activation-and-runtime-behavior) | The current runtime has no profile lifecycle, measured readiness window, or authority-gating integration. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-31 | implemented | Held a not-yet-recorded observation instead of only dropping it, and put the action lifecycle on an injectable clock. The earlier projection dropped an observation the contract cannot represent but left the verdict `verified`, so a real `verify_effect` result whose observation followed `recorded_at` still raised a contract validation error inside dispatch. Admissibility now runs before the decision, the shadow audit entry, and the projection, downgrading such evidence to `hold` with `observation_not_yet_recorded` while an already-held verdict keeps its reason. The shadow effect entry additionally records action creation and the dispatch window, and `ControlLoop` and `ActionBuilder` accept one shared clock so a frozen replay orders creation, prediction, dispatch, observation, and recording on the scenario timeline instead of wall clock. | `current change`; `core/mscp_profile/effect_verification.py`; `core/mscp_profile/response_outcome.py`; `core/mscp_profile/shadow_effect.py`; `core/control_loop/_execution.py`; `core/executor/action_builder.py`; the `not_yet_recorded` case of `tests/scenarios/test_v2026_07_replay.py::test_sre_full_loop_fails_closed_on_deficient_effect_evidence`, which fails with the contract validation error when the hold is reverted; `uv run pytest -q --no-cov services/core-control-plane/tests/scenarios services/core-control-plane/tests/core/mscp_profile services/core-control-plane/tests/core/executor services/core-control-plane/tests/pipeline` passed. | Evidence remains frozen in-process replay in shadow; a pinned deployed shadow evidence window stays open. |
| 2026-08-31 | implemented | Made the `ResponseOutcome` projection fail closed on an observation the contract cannot represent. An observation outside the effect window, or one not yet recorded, previously raised a contract validation error inside dispatch, so deficient effect evidence became a dispatch-time error instead of shadow `hold` evidence. The projection now drops such an observation and records `unscorable`, while the shadow effect audit entry keeps the raw value and the contract invariant itself is unchanged. | `current change`; `core/mscp_profile/response_outcome.py`; `tests/core/mscp_profile/test_response_outcome.py`; the stale case of `tests/scenarios/test_v2026_07_replay.py::test_sre_full_loop_fails_closed_on_deficient_effect_evidence`, which fails with the contract validation error when the projection fix is reverted; `uv run pytest -q --no-cov services/core-control-plane/tests/scenarios services/core-control-plane/tests/core/mscp_profile services/core-control-plane/tests/contracts/test_response_outcome.py` passed. | Evidence comes from frozen in-process replays in shadow, so a pinned deployed shadow evidence window is still open. |
| 2026-08-14 | in-progress | Adopted the implementation ledger without reconstructing earlier provenance and separated implemented shadow observation from unimplemented gating. | `current change`; profile source and focused tests listed in the scope table. | Retain a measured readiness window and implement the bounded decision-context and gating work below. |
| 2026-08-23 | implemented | Recorded the ordering boundary between immutable rule governance and optional post-dispatch MSCP effect observation. | `current change`; focused governance and MSCP composition checks. | The existing measured-readiness and governed-gating work remains unchanged. |

### Remaining work

- [ ] Project authoritative ontology, incident, workflow, and audit state into one immutable decision context, then prove missing or conflicting inputs produce a hold.
- [ ] Retain a pinned shadow evidence window that measures profile matches, mismatches, holds, audit failures, and unchanged executor outcomes.
- [ ] Add a governed profile lifecycle and connect the never-raising ceiling only after focused tests prove rollback, replay, and unchanged risk, approval, execution, and audit ownership.

## Profile contract

| Field | Value | Meaning |
|-------|-------|---------|
| Profile id | `mscp-operational-v1` | Versioned FDAI adaptation, independent of MSCP level labels |
| Source repository | `https://github.com/dotnetpower/mscp` | Public origin of the adopted concepts |
| Source revision | `b66401cb4d3b43ee8d66e6ce106c51defd4c6d3a` | Reviewed source snapshot |
| Full conformance | `false` | FDAI does not claim complete MSCP implementation or certification |

The profile id may appear in structured evidence as `safety_profile`. FDAI action kinds, event
topics, ontology types, API routes, database tables, and product labels continue to use operational
domain vocabulary rather than MSCP terminology.

## Adopted mechanisms

| FDAI mechanism | MSCP provenance | FDAI adaptation | v1 status |
|----------------|-----------------|-----------------|-----------|
| Profile provenance | Cross-level protocol versioning | Immutable profile id, source revision, and non-conformance declaration | Implemented |
| Effect verification | Level 3 prediction gating | Compare one expected metric range with an independently observed, correlated, time-bounded value | Optional shadow runtime wiring and `ResponseOutcome` projection implemented |
| Cycle guard | Level 3 meta-escalation, oscillation, and cognitive budget | Hold when caller-owned cycle, elapsed-time, cost, rollback, or sign-change limits are reached | Pure policy implemented; runtime wiring deferred |
| Runtime integrity | Level 3 identity continuity | Compare canonical manifests of pre-hashed runtime components; no persona or mutable identity model | Pure policy implemented; runtime wiring deferred |
| Decision context | Level 2 persistent world model | Project authoritative ontology, incident, workflow, and audit state without creating a new system of record | Planned |

MSCP's published numerical thresholds are not copied into the profile. FDAI callers supply limits
through their governed configuration or ActionType contract and validate them on the same frozen
scenario set used for promotion evidence.

## Authority boundaries

| Decision or side effect | Authoritative FDAI owner | Profile role |
|-------------------------|--------------------------|--------------|
| Context and state acquisition | Ontology, incident, workflow, audit, and provider owners | Consume an immutable projection only |
| Prediction quality history | Assurance Twin and measurement | Produce one typed comparison result |
| Auto, human approval, hold, or deny | Risk gate | No authority to raise autonomy |
| Resource mutation | Executor and Thor | Never executes |
| Human approval | Human approval path and Var | Never approves |
| Recovery | Vidar and rollback adapters | Reports mismatch or hold; never rolls back directly |
| Promotion and demotion | Promotion registry and measurement runners | Profile presence never promotes a capability |
| Audit durability | Audit store and Saga | Supplies optional provenance fields only |
| Rule or policy changes | Norns-to-Mimir governed candidate path | Never updates accepted policy directly |

Unexpected input, stale observations, mismatched correlation, exhausted budgets, oscillation, and
runtime drift all return a hold-style result. Callers may lower autonomy to shadow mode or route to
human approval. They cannot interpret a profile result as permission to bypass the risk gate.

## Activation and runtime behavior

MSCP effect observation is disabled by default. `Container.mscp_expected_effect_provider` and
`Container.mscp_effect_observer` both default to `None`, and an unbound ControlLoop performs no
extra calls or audit writes. A composition root activates shadow observation by creating a new
immutable container with both collaborators:

```python
container = dataclasses.replace(
	container,
	mscp_expected_effect_provider=expected_effect_provider,
	mscp_effect_observer=independent_effect_observer,
)
```

Partial binding fails at container construction and again at direct ControlLoop construction. The
headless runtime builder passes a complete pair into the ControlLoop. The loop then preserves this
order for every PR-native, direct-API, and tool-call dispatch:

```text
expected-effect provider -> existing executor -> independent observer -> shadow audit
```

The observer receives the Action and ExpectedEffect, not the executor receipt. This prevents the
observer from treating the component's own success claim as independent evidence. Each deployment
chooses an effect appropriate to the delivery path, such as a PR receipt projection, a tool-side
post-condition, or an authoritative substrate metric.

Provider failures, missing predictions or observations, target mismatch, stale observations, and
value mismatch produce `hold` or `mismatch` shadow evidence. They do not alter the executor result,
the risk decision, or the terminal ControlLoop outcome. A shadow-audit write failure is logged and
also leaves the primary result unchanged.

The same observation now writes a strict `ResponseOutcome` as
`measurement.action_outcome.v1`. The contract stores a target digest rather than the resource
reference, marks missing or stale evidence `unscorable`, and supplies the independent watermark
consumed by the scheduled Dynamic challenger-learning pass. Evidence the contract cannot
represent - an observation outside the effect window, or one timestamped after the moment the
comparison is recorded - is inadmissible: the verdict fails closed to `hold` before the decision,
the shadow audit entry, and the projection read it, so the record is `unscorable` and dispatch
never raises a contract error. A value that matches its prediction is held the same way when it
has not been recorded yet, because a recorder cannot attest an observation it has not seen, and a
verdict already held keeps its original reason. The shadow effect audit entry keeps the raw
observed value together with the action lifecycle timeline - creation, dispatch start and
completion, prediction, observation, and recording - so no evidence is lost and the ordering stays
reviewable. Those lifecycle timestamps come from the control-loop clock seam, which a frozen
replay binds so that an observation is ordered against the dispatch it describes instead of
against wall clock. This additional record remains shadow evidence. It cannot promote an effect
model or change execution authority.

After both durable audit records are written, an optional composition-owned sink republishes the
strict contract through raw ingress. Audit failure suppresses the relay, so unaudited outcomes
cannot enter learning. Huginn and Muninn then feed the governed operating-pattern cohort path. Sink
failure is logged and cannot alter the executor result. The relay does not make a shadow outcome
reusable: the cohort projector accepts only verified enforce outcomes as positive evidence.

Expected effects can now enter a durable StateStore-backed pending-effect ledger before observation.
The ledger preserves the candidate ActionType, environment, observer version, exact deadline, and
immutable effect digest across process restart. Compare-and-set claims carry a revision and owner
generation. An active duplicate owner, stale revision, expired owner completion, or conflicting
prediction identity fails closed. A separate bounded worker claims deadline-ordered records and
writes `verified`, `mismatch`, or `hold` plus the deterministic reason. Missing observations and
provider failures become explicit holds. Completed effects do not run again, and the worker remains
outside the synchronous executor path with no execution authority.

Moving from shadow observation to gating is a separate, future governed change. It requires a
measured evidence window, a rollback target, and a proof that the profile can only preserve or lower
the existing authority decision.

A pure readiness evaluator now keeps each `(ActionType, effect metric, environment, observer
version)` candidate separate. It reports reviewed sample count, point accuracy, the 95% Wilson lower
bound, false-positive and false-negative outcomes, policy escapes, correlation errors, observer
coverage and p95 latency, stale and provider-failure rates, rollback rate, and human touchpoints. The
14-day and 100-sample floors cannot be weakened. Missing statistical or drill evidence remains an
explicit gap, and the report carries no promotion authority.

The pure `combine_mscp_authority` function supplies that never-raising proof surface. It maps
`preserve`, `human_approval`, `hold`, and `deny` ceilings onto the canonical FDAI authority ladder
and takes `min(existing FDAI authority, MSCP ceiling)`. Its immutable result preserves the complete
unified risk decision and adds an audit projection with the profile, existing decision, ceiling,
reason, final decision, and whether authority was lowered. The function performs no I/O and cannot
bypass the risk gate, human approval, executor, rollback, or audit owners. It is not connected to
the ControlLoop while the measured readiness window and governed profile lifecycle remain absent.

The profile lifecycle now persists a default `shadow` record per exact candidate tuple. A `gating`
transition requires both a ready report and an independent review bound to the report digest.
Compare-and-set revision fencing permits only one concurrent winner. Demotion returns immediately to
`shadow` with an audited reason and no review prerequisite. Lifecycle state remains unwired from the
ControlLoop and fixes `activation_authority=false`, so recording `gating` cannot activate an
ActionType or Workflow.

Every non-success prediction or observation reason now has one explicit bounded failure decision.
Prediction failure holds before dispatch and permits at most one caller-owned retry and one approval
request. Observation, correlation, and deadline failure holds after dispatch with no retry or
approval fan-out. A measured mismatch requests recovery after dispatch. Every failure in `gating`
requires demotion to `shadow`, and no failure decision carries execution authority.

## Independent axes

The profile is independent from the runtime axes in
[ADR-0002](decisions/0002-independent-runtime-axes.md). Execution venue, deployment environment,
evidence profile, action lifecycle, identity, and distribution do not select or modify the safety
profile. In particular:

- Local execution does not disable profile checks.
- Production does not imply that a profile result may execute.
- A fork cannot use the profile id to raise autonomy or bypass framework integrity.
- Shadow and enforce remain ActionType and Workflow lifecycle states, not MSCP states.

## Verification

Focused tests under `services/core-control-plane/tests/core/mscp_profile/` cover:

- level-neutral profile identity and the mandatory non-conformance declaration;
- stable, source-pinned audit provenance;
- time, target, metric, and correlation checks for expected and observed effects;
- strict `ResponseOutcome` schema parity and privacy-minimized audit projection;
- default-off composition, pair-only activation, and predict-execute-observe ordering;
- unchanged executor results across mismatch and provider or shadow-audit failure;
- exhaustive finite-domain combinations proving the MSCP ceiling never raises unified authority;
- caller-owned cycle budgets and bounded sign-change detection;
- order-independent runtime manifest hashing and component drift reporting; and
- fail-closed validation of non-finite values, malformed digests, and invalid limits.
- restart-safe pending-effect ownership and deadline-worker verified, mismatch, missing, provider
  failure, and replay behavior.
- candidate-separated reviewed readiness metrics, confidence lower bounds, zero-tolerance guards,
  SLO gaps, and non-authoritative review eligibility.
- restart-safe default-shadow lifecycle, exact readiness/review binding, single-winner compare-and-set
  transitions, hash-chain audit verification, and immediate demotion without runtime activation.
- exhaustive failure-reason routing with one-request ceilings, post-dispatch hold or recovery, and
  mandatory gating demotion.

The v1 profile is connected only as optional shadow observation. It is not connected to the enforce
decision path. A future gating change should demonstrate that no profile outcome raises the existing
risk decision.

## Related docs

| To learn about | Read |
|----------------|------|
| Control-loop and module boundaries | [Project Structure](project-structure.md) |
| Safety and identity invariants | [Security and Identity](security-and-identity.md) |
| Promotion evidence and guard metrics | [Goals and Metrics](goals-and-metrics.md) |
| Independent runtime axes | [ADR-0002](decisions/0002-independent-runtime-axes.md) |
