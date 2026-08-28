---
title: FinOps Autonomous Operations
---

# FinOps Autonomous Operations

This document defines how FDAI's operating ontology and fixed 15-agent organization close Cost
Governance episodes with minimal human intervention. The ontology supplies exact meaning and
bounded evidence. Agents remain the active control plane and own every state transition.

> **Scope:** This design owns the FinOps decision frame, agent choreography, autonomous recovery,
> effect settlement, and learning loop. Distribution and activation contracts belong to
> [Ontology-Grounded FinOps Package Architecture](finops-package-architecture.md). Delivery waves
> belong to the [FinOps Package Delivery Plan](../fork-and-sequencing/finops-package-delivery-plan.md).
> Subscription-wide analysis, resource-level SKU decisions, savings attribution, and the Console
> workspace belong to
> [FinOps Resource Efficiency and SKU Decisions](finops-resource-efficiency.md).
>
> **Authority boundary:** Ontology evidence can preserve or lower autonomy. It cannot judge,
> approve, execute, promote, or assert that an intended effect occurred.
>
> **Current status:** The exact FinOps semantic profile, fixed-15 responsibility trace, bounded
> recovery coordinator, independent multi-effect settlement, replay, retention, and governed
> learning inputs are implemented with local evidence. A live-authoritative settled cohort and
> independent package and per-action promotion reviews do not yet exist.

## Design at a glance

An eligible FinOps episode begins with bounded cost or resource evidence and ends only after an
agent-owned terminal outcome. Agents resolve the target through the active ontology release,
materialize a decision context, compare safe options, apply deterministic policy, execute only
through Thor, independently observe the effect, and feed the result into governed learning.

![Design at a glance. The main stages are Observed cost and resource evidence, Release-bound ontology context, Domain advice and safe options, Forseti judgment, Odin arbitration when objectives conflict, Thor execution or typed no-op, Var approval only when required, Heimdall independent observation, Vidar recovery when needed, Saga terminal audit, Muninn, Norns, and Mimir learning loop.](../../diagrams/generated/fdai-roadmap-architecture-finops-autonomous-operations-01.en.svg)

## Operating principles

- **Agent-owned transitions:** Every published object has its existing pantheon owner. A package,
  projector, provider, or ontology function does not become a hidden agent.
- **Ontology-required decisions:** A candidate cannot become action-eligible without an exact
  target, applicable objectives, relationship coverage, evidence cutoff, and active ontology
  release. Provider payloads and free text remain candidate evidence until normalized.
- **Deterministic-first handling:** Repeatable detection, option filtering, policy, guardrails, and
  settlement use T0 rules and typed functions. T1 reuses verified prior cases. T2 is reserved for
  residual ambiguity and still passes the existing quality gate.
- **Autonomy before escalation:** Agents try bounded evidence recovery, safer option selection,
  smaller impact scope, typed no-op, or rollback before Var requests human approval. Policy-required
  approval, irreversible action, and unresolved high risk remain human decisions.
- **Independent closure:** Dispatch or API success is not a FinOps result. Savings, unit-cost,
  capacity, reliability, and recovery effects remain predicted until authoritative observation
  closes the settlement window.
- **No silent completion:** Unknown, held, denied, no-op, rollback, and unverified outcomes are
  explicit terminal or pending records with Saga audit evidence.

## Ontology-grounded decision frame

Each episode materializes one immutable decision frame from an exact ontology release and semantic
profile. The frame uses the five operational lenses without creating a parallel FinOps graph.

| Lens | Required FinOps content |
|------|-------------------------|
| Object | `BusinessService`, `Workload`, `Resource`, `Environment`, applicable objectives, signals, options, effects, runs, and outcomes. |
| Relationship | Service-to-workload-to-resource impact paths, `depends_on`, objective bindings, ownership, considered options, expected effects, execution, and observed results. |
| State | Separate observed cost and utilization, derived anomaly or forecast, desired objectives, and execution state with source authority. |
| Context | Exact revisions, evidence paths, cutoff, freshness, completeness, conflicts, exclusions, and autonomy ceiling. |
| Action | Exact `ActionType`, target revision, preconditions, stop conditions, impact limit, dry-run, lock, idempotency, rollback, and postconditions. |

The minimum decision frame contains:

1. **Identity:** One exact target or bounded target set resolved through the active ontology release.
2. **Operating scope:** Reachable service, workload, dependencies, environment, ownership, and
   explicit `unknown_service` or truncation markers.
3. **Intent:** Effective `CostObjective`, `ServiceObjective`, `RecoveryObjective`,
   `ArchitectureConstraint`, and `ChangeWindow` records for the same cutoff.
4. **Evidence:** Authenticated cost, utilization, topology, policy, forecast, and prior-outcome
   references with event, effective, recorded, and cutoff time.
5. **Alternatives:** A no-action baseline and bounded `ActionOption` set with expected cost,
   reliability, capacity, recovery, and reversibility effects.
6. **Safety:** Exact ActionType contract, policy result, dry-run receipt, target lock, impact scope,
   stop conditions, rollback readiness, and stable idempotency key.

Missing or contradictory content does not automatically require a person. It first invokes the
bounded recovery ladder below. It can never be replaced by a guessed service mapping, synthetic
objective, unverified relationship, stale cost value, or model-written permission.

## Ontology competency gates

The vertical is not ready for activation until deterministic fixtures answer these questions:

| Gate | Question and required result |
|------|------------------------------|
| F1 - Target | Which exact resources, workloads, and services does the candidate affect? Unknown and truncated scope stays explicit. |
| F2 - Intent | Which cost, service, recovery, architecture, and time-window constraints apply at the cutoff? |
| F3 - Evidence | Which facts are current, complete, independently verified, conflicting, synthetic, or unavailable? |
| F4 - Options | What no-action and change options were compared, and which hard constraints removed an option? |
| F5 - Effect | What cost and non-cost effects are predicted for each option, with uncertainty and falsifiers? |
| F6 - Authority | Which rule, ActionType, risk result, standing authorization, or human approval permits the selected path? |
| F7 - Settlement | Did independent observations confirm each expected effect without treating execution output as observation? |
| F8 - Learning | Can the exact context, decision, execution, and outcome be replayed before a rule candidate is proposed? |

## The 15-agent responsibility model

All 15 agents retain their existing names, owned object types, topics, and authority. Not every
episode invokes every agent, but the vertical must provide a valid path for each responsibility.

| Agent | FinOps responsibility | Participation |
|-------|-----------------------|---------------|
| Huginn | Normalize bounded provider, billing, inventory, change, and schedule ingress into owned `Event` or `Change` records. | Required ingress. |
| Heimdall | Produce anomaly, drift, forecast, and evidence-health records, then independently compare terminal observations with every expected effect. | Required sensing and changed-state closure. |
| Njord | Own `CostAnomaly` and `Budget` advisory objects and cost-objective interpretation. An injected `CostEstimator` supplies provider-bound estimates without becoming an agent or publisher. | Required for cost judgment. |
| Freyr | Supply capacity forecasts and sizing advice so savings cannot hide saturation or headroom loss. | Required for capacity-affecting options. |
| Loki | Propose bounded, always-reviewed resilience experiments when uncertainty requires an experiment rather than a production guess. | Conditional validation. |
| Muninn | Retain immutable context indexes, state snapshots, prior cases, and exact change revisions for replay and T1 reuse. | Required for reuse and learning. |
| Forseti | Materialize the decision context, remove constitutionally ineligible options, judge through T0/T1/T2, and publish `Verdict`. | Required judgment. |
| Odin | Rank only eligible options when cost conflicts with reliability, capacity, recovery, or portfolio objectives. | Conditional arbitration. |
| Var | Record distinct human approval and quorum when policy or residual risk requires it. | Residual path only. |
| Thor | Solely dispatch an eligible ActionType and own `ActionRun` and `ActionAttempt`. | Required for mutation. |
| Vidar | Validate recovery readiness and own rollback when stop conditions, failed effects, or regressions require recovery. | Required recovery dependency. |
| Saga | Append intent and terminal audit, preserve correlation, and open a governed issue when the episode cannot close safely. | Required hard dependency. |
| Norns | Analyze audited cohorts and propose inert `RuleCandidate` or `Pattern` records without changing the catalog. | Off-path learning. |
| Mimir | Validate, regress, shadow, promote, revoke, and version FinOps rules and policies through catalog governance. | Governed improvement. |
| Bragi | Explain context, options, evidence gaps, decisions, approvals, and outcomes in the operator's locale; action requests re-enter typed ingress. | Read-only interaction. |

## Typed event choreography

The package binds handlers and profiles to existing owned topics. It does not create direct agent
calls or a private workflow bus.

| Stage | Owned message path |
|-------|--------------------|
| Ingress and sensing | Huginn `object.event` or `object.change` -> Heimdall observations and Njord cost advice. |
| Cross-domain evidence | Heimdall `object.anomaly`, `object.drift`, or `object.forecast`; Njord `object.cost-anomaly`; Freyr `object.capacity-forecast`; Loki `object.chaos-experiment`. |
| Judgment and conflict | Forseti `object.verdict` and, when needed, `object.arbitration-request` -> Odin `object.arbitration-decision`. |
| Approval and action | Thor consumes verdicts; Var owns `object.approval`; Thor alone owns `object.action-run`. |
| Recovery and closure | Vidar owns `object.rollback`; Heimdall observes terminal action effects; Saga appends `object.audit-entry`. |
| Learning | Muninn publishes bounded `object.context-index`; Norns publishes inert `object.rule-candidate`; Mimir publishes reviewed `object.rule` or `object.policy`. |

At-least-once delivery uses stable correlation and idempotency identities. Per-resource ordering,
duplicate suppression, deadlines, backpressure, dead-letter handling, restart replay, and terminal
audit apply exactly as they do for other verticals.

## Bounded autonomous recovery

Before an optional episode reaches human approval, the accountable agents attempt these steps in
order when policy permits:

1. Re-materialize the context at a fresh cutoff and reject mixed-release evidence.
2. Query an independent source for the missing cost, topology, objective, or effect fact.
3. Remove options that depend on unresolved facts or violate hard objectives.
4. Reduce the target set, duration, capacity delta, or impact scope while preserving intent.
5. Select a reversible option with complete safeguards, or select the typed no-action baseline.
6. Hold the episode with a bounded retry or settlement deadline when evidence may arrive later.
7. Route to Var only for remaining ambiguity, policy-required approval, irreversible effect, or
   risk outside standing authorization.

A no-op counts as autonomous handling only when it records the reason, decision frame, and terminal
audit. Reports separate no-op, beneficial action, denial, rollback, and approval outcomes so an
implementation cannot inflate autonomy by doing nothing.

## Effect settlement and learning

Every selected option declares one or more expected effects before execution. Heimdall closes each
effect against an independent authoritative observation after the configured horizon and telemetry
grace. Missing observations remain unscorable; an intervening action or incomplete telemetry marks
the episode censored rather than successful.

Saga seals the complete lineage and Muninn indexes the replayable case. Norns learns only from
verified cohorts that include successes plus failures, refusals, no-ops, rollbacks, or recurrences.
Mimir independently validates any resulting rule candidate, runs regression and shadow gates, and
uses the authoritative promotion registry. Learning never edits the package, ontology kernel,
AgentSpec, or active catalog directly.

## Autonomy measurement

Measure autonomous handling over all admitted FinOps episodes and report policy-excluded episodes
separately. The primary ratio is terminal episodes closed without Var approval divided by eligible
episodes. Supporting measures include beneficial-action, no-op, denial, rollback, unresolved,
evidence-recovery, settlement-completeness, policy-escape, and objective-regression rates.

Promotion requires a configured minimum cohort and threshold on a frozen scenario set. A higher
autonomy ratio cannot compensate for a policy escape, missing audit, failed rollback, stale
ontology context, or unverified effect. Operational claims require retained exact-revision
receipts; unit tests prove behavior but not production autonomy.

## Degradation behavior

- Missing Saga or Vidar forces new mutations to observation mode.
- Missing Forseti produces no fallback judgment. Evidence continues to queue.
- Missing Heimdall blocks changed-state success because effects cannot close independently.
- Missing Njord, Freyr, or required ontology context lowers affected options to hold or approval.
- Missing Odin sends unresolved cross-objective conflict to approval without local tie-breaking.
- Missing Var preserves the approval queue; silence does not grant authority.
- Missing Norns, Mimir, Muninn learning intake, or Bragi reduces learning or explanation but does
  not bypass the active decision and safety path.

## Non-goals

- Adding, removing, renaming, or repointing any pantheon agent.
- Treating the ontology, a model, or a package as an actor or permission source.
- Requiring every agent to run in every episode when its declared responsibility is not relevant.
- Optimizing cost by violating service, recovery, security, identity, or data-integrity objectives.
- Counting dispatch, provider acceptance, or estimated savings as a verified outcome.

## Related docs

| To learn about | Read |
|----------------|------|
| Subscription analysis, SKU decisions, and Console workspace | [FinOps Resource Efficiency and SKU Decisions](finops-resource-efficiency.md) |
| Package and activation boundary | [Ontology-Grounded FinOps Package Architecture](finops-package-architecture.md) |
| Delivery waves and exit gates | [FinOps Package Delivery Plan](../fork-and-sequencing/finops-package-delivery-plan.md) |
| Implementation state | [FinOps Autonomous Operations implementation ledger](../../roadmap-implementation/architecture/finops-autonomous-operations.md) |
| Shared operational meaning | [FDAI Operating Ontology](operating-ontology.md) |
| Fixed agent ownership | [Agent Pantheon](../agents/agent-pantheon.md) |
| Existing cost-aware agent flow | [Agent Workflows](../agents/agent-workflows.md#1-cost-aware-fix) |
