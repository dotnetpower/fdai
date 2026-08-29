---
title: Ontology-Grounded ARB Delivery Plan
---
# Ontology-Grounded ARB Delivery Plan

This plan sequences the smallest changes that turn the current manifest-driven review into an
ontology-grounded, agent-owned closed loop. Each work package has an executable exit condition and
keeps authority-bearing changes behind existing FDAI gates.

> **Starting boundary:** The structural checker, generic workflow, Process projection, read-only
> Console view, exact snapshot graph receipt, and injected production evidence attestation exist.
> They do not yet prove an autonomous 15-agent ARB path or an immutable decision authority chain.
>
> **Rollout boundary:** Complete the observation-mode vertical slice before adding an
> authority-bearing decision or execution path.

## Design at a glance

| Work package | Outcome | Depends on |
|--------------|---------|------------|
| ARB-1 Ontology truth | Fresh operating intent, topology, and exact change revision are queryable | Existing ontology platform |
| ARB-2 Agent evidence loop | Relevant agents publish and Forseti joins verified evidence | ARB-1 |
| ARB-3 Decision authority | Immutable decision receipt binds case, evidence, conditions, approvals | ARB-2 |
| ARB-4 Effect closure | Resulting actions close through independent observation and recovery | ARB-3 |
| ARB-5 Learning and rollout | Repeated outcomes produce governed candidates and measured promotion evidence | ARB-4 |

## ARB-1: Make ontology state authoritative

Deliver the operating facts that every later decision consumes:

- project deployment-supplied `ServiceObjective`, `RecoveryObjective`, `CostObjective`,
  `ArchitectureConstraint`, `Ownership`, and `ChangeWindow` instances;
- issue authenticated graph revision, completeness, freshness, purpose, and cutoff receipts;
- bind one normalized planned `Change` to its exact desired-state digest and plan receipt;
- keep `config/architecture-review.yaml` as a review profile, not mutable runtime decision state;
- model review status as evidence, evaluation, authority, execution, and learning axes.

**Exit:** One exact planned change produces a time-consistent context snapshot on a pinned ontology
release. The assessment carries a typed graph evidence receipt, and any accepted critical or high
blocker keeps a current risk or exception record. Missing, stale, mixed-release, unverified, or
truncated context still lowers authority and has a typed reason.

## ARB-2: Compose the 15-agent evidence loop

Wire the existing ownership boundaries rather than adding an ARB agent:

- Huginn publishes the immutable `Change`; Muninn retains the revision and context;
- select Njord, Freyr, Loki, and Heimdall from active objectives and dependency relationships;
- compose `OperationalEvidenceBundle` and `OntologyScenarioBranch` before judgment;
- replace caller-supplied workflow branch outcomes with agent-owned topic evidence;
- let Forseti own the deadline-bound join and produce `DecisionCase` plus `ImpactEnvelope`;
- send only eligible objective conflicts to Odin;
- attempt bounded evidence reacquisition and deterministic reevaluation before Var escalation.

**Exit:** A complete low-risk fixture reaches an automatic conformant recommendation in
observation mode. Stale, conflicting, missing, duplicate, reordered, or late evidence reaches an
explicit hold without mutation or silent loss.

## ARB-3: Bind decision and authority

Replace mutable status assertions with a replayable authority chain:

- version the `Decision` contract with case, context, evidence, graph, catalog, and condition
  digests. The reusable content-addressed receipt and additive Decision `1.1.0` shape are implemented;
- bind approval receipt identities, approver roles, quorum, no-self-approval, and expiry;
- require a complete risk or exception contract for every accepted critical or high blocker;
- reuse the injected provider verification of evidence bodies, digests, scope, revisions, freshness,
  and approver authorization;
- derive production readiness and `ReviewCase` projection from the final receipt;
- represent an accepted constraint or production transition as a separate governance ActionType.

**Exit:** Changing one evidence item, approval, condition, target revision, or graph revision
invalidates the prior decision identity. No manifest edit or workflow context value can create
production authority.

## ARB-4: Close effects independently

Keep ARB control-only while connecting approved work to the ordinary action pipeline:

- route any resource change back through ActionType promotion, policy, risk, Var, Thor, and Saga;
- carry the selected option, impact envelope, stop condition, rollback, lock, idempotency, and
  expected effects unchanged;
- let Heimdall close each expected effect from an authoritative observation;
- leave missing or incomplete observation pending rather than reporting success;
- let Vidar recover within the approved envelope when a failure or stop condition occurs;
- reopen or expire the review when a condition or protected objective is violated.

**Exit:** One accepted shadow case links `Change -> DecisionCase -> ImpactEnvelope -> ActionRun ->
ObservedOutcome`, and a failure fixture reaches recovery without letting the actor score its own
effect.

## ARB-5: Learn and promote safely

Use reviewed outcomes to reduce future human touchpoints without relaxing authority:

- let Muninn retain exact case history and outcome cohorts;
- let Norns propose inert `RuleCandidate` records only from bounded, consent-eligible evidence;
- let Mimir revalidate and promote through reviewed catalog-as-code;
- measure automatic conformance, conditional closure, evidence reacquisition, human approvals,
  holds, policy escapes, rollbacks, and settlement completeness;
- promote only the bounded review capability whose observation cohort meets its gate;
- demote on regression without changing the underlying ActionType authority.

**Exit:** A pinned observation cohort supports an independently reviewed promotion decision with
zero policy escapes and complete decision/effect lineage.

## First vertical slice

Implement this path before extending the Console or production gate:

```text
Huginn Change
-> Muninn context snapshot
-> OperationalEvidenceBundle
-> ontology scenario branch and diff
-> Forseti DecisionCase and ImpactEnvelope
-> observation-mode recommendation
-> Saga audit
-> derived ReviewCase projection
```

The slice is complete when:

- the same change revision creates one immutable case;
- a fresh, complete graph can produce an automatic conformance recommendation;
- stale, truncated, conflicting, or target-mismatched evidence produces a hold;
- protected-objective violations are removed before Odin arbitration;
- evidence updates resume the same Process and reevaluate the same logical case;
- no step can approve, mutate, promote, or execute outside its owner boundary.

## Validation matrix

| Boundary | Focused proof |
|----------|---------------|
| Ontology | Exact release, path direction, temporal cutoff, freshness, completeness, conflict, truncation |
| Topics | Single writer, duplicate, reorder, retry, backpressure, dead-letter, restart, replay |
| Judgment | Hard constraints before arbitration, no-action baseline, bounded options, deterministic identity |
| Approval | Role, quorum, no-self-approval, timeout, receipt replay resistance |
| Execution | ARB control-only; separate promoted ActionType; seven safeguards |
| Outcome | Independent target observation, every expected effect closed or explicitly unscorable |
| Projection | Read model derived from authoritative lineage; expired or removed evidence reconciled |
| Localization | English/Korean structure, links, translation SHA, terminology, punctuation |

## Non-goals

- Do not add a sixteenth ARB agent.
- Do not let the workflow call agents directly or own judgment.
- Do not let the ontology graph approve or execute.
- Do not make Bragi or Odin a universal controller.
- Do not grant automatic authority to architecture baselines, exceptions, irreversible changes, or
  production promotion.
- Do not start with UI polish or enforce routing before the observation-mode vertical slice passes.

## Related docs

| To learn about | Read |
|----------------|------|
| ARB entry point and decision boundary | [Architecture Review Board Packet](../architecture-review-board.md) |
| Target ontology and agent flow | [Ontology-Grounded Agent Loop](ontology-agent-loop.md) |
| Evidence and authority contract | [Evidence and Authority](evidence-and-authority.md) |
| Operational planning foundations | [Operational Planning](../../decisioning/operational-planning.md) |
| Delivery status and remaining work | [Implementation ledger](../../../roadmap-implementation/architecture/architecture-review/delivery-plan.md) |
