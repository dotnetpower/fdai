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
`src/fdai/core/mscp_profile/`. Callers provide already collected observations, limits, and
component digests. The profile returns typed verification or hold decisions and never calls a
provider, changes a resource, writes an audit entry, promotes a capability, or edits a rule.

The runtime identifier deliberately omits an MSCP level. FDAI combines selected concepts from more
than one level, while each module docstring and the mapping below retain the level-specific design
provenance.

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
consumed by the scheduled Dynamic challenger-learning pass. This additional record remains shadow
evidence. It cannot promote an effect model or change execution authority.

After both durable audit records are written, an optional composition-owned sink republishes the
strict contract through raw ingress. Audit failure suppresses the relay, so unaudited outcomes
cannot enter learning. Huginn and Muninn then feed the governed operating-pattern cohort path. Sink
failure is logged and cannot alter the executor result. The relay does not make a shadow outcome
reusable: the cohort projector accepts only verified enforce outcomes as positive evidence.

Moving from shadow observation to gating is a separate, future governed change. It requires a
measured evidence window, a rollback target, and a proof that the profile can only preserve or lower
the existing authority decision.

The pure `combine_mscp_authority` function supplies that never-raising proof surface. It maps
`preserve`, `human_approval`, `hold`, and `deny` ceilings onto the canonical FDAI authority ladder
and takes `min(existing FDAI authority, MSCP ceiling)`. Its immutable result preserves the complete
unified risk decision and adds an audit projection with the profile, existing decision, ceiling,
reason, final decision, and whether authority was lowered. The function performs no I/O and cannot
bypass the risk gate, human approval, executor, rollback, or audit owners. It is not connected to
the ControlLoop while the measured readiness window and governed profile lifecycle remain absent.

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

Focused tests under `tests/core/mscp_profile/` cover:

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
