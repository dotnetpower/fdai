---
title: Ontology-Grounded ARB Agent Loop
---
# Ontology-Grounded ARB Agent Loop

This design defines how FDAI's operating ontology and fixed 15-agent pantheon review a planned
change. It keeps meaning, authority, execution, observation, and learning in separate accountable
boundaries.

> **Scope:** This document owns the ARB decision loop. The
> [evidence and authority contract](evidence-and-authority.md) owns evidence bindings, approval,
> risks, and production exit. The [delivery plan](delivery-plan.md) sequences implementation.
>
> **Authority boundary:** The ontology validates identity, relationships, time, evidence, and
> constraints. It never judges, approves, executes, or raises autonomy.

## Design at a glance

A normalized `Change` starts one bounded review. Muninn freezes the current operating context,
relevant specialists publish their owned evidence, and Forseti joins the required inputs into an
immutable `DecisionCase` and `ImpactEnvelope`. Odin resolves only eligible cross-objective
conflicts. Var requests human approval only when policy or residual risk requires it.

![Design at a glance. The main stages are Huginn: Change, Muninn: context snapshot, Relevant specialists, OperationalEvidenceBundle, Ontology scenario branch, Forseti: DecisionCase, Mimir: constraints and policies, Odin: arbitration, Var: approval, Decision receipt, Saga: audit and Process projection, Thor: execution.](../../../diagrams/generated/fdai-roadmap-architecture-architecture-review-ontology-agent-loop-01.en.svg)

## Authoritative state model

The ARB read model derives from agent-owned records. It does not use mutable checklist status as a
second source of truth.

| Record | Authority | ARB use |
|--------|-----------|---------|
| `Change` | Huginn | Exact proposed revision, target, actor, desired-state digest, and correlation |
| `OperationalContextSnapshot` | Muninn-supported projection | Time-consistent topology, objectives, ownership, freshness, and conflicts |
| `OperationalEvidenceBundle` | Verified provider receipts | Immutable ontology, state, catalog, and document evidence lanes |
| `ArchitectureConstraint` and `Policy` | Mimir | Effective constraints and deterministic evaluation rules |
| Domain observations | Heimdall, Njord, Freyr, Loki | Reliability, security, cost, capacity, performance, and recovery evidence |
| `DecisionCase` and `ImpactEnvelope` | Forseti | Bounded options, no-action baseline, protected objectives, uncertainty, and impact limits |
| `ArbitrationDecision` | Odin | Selection among constitutionally eligible soft-objective tradeoffs |
| `Approval` | Var | Current, scoped approval when policy requires a person |
| `Decision` and audit chain | Saga projection over owned events | Replayable decision, conditions, authority basis, and terminal status |
| `ActionRun` | Thor | Separate execution after the ARB decision and normal action gates |
| `ObservedOutcome` | Heimdall | Independent effect closure against expected effects |

`ReviewCase` and `ReviewCheck` remain read models. They summarize these records for the Process and
Console, but they cannot create a decision or mark evidence ready by themselves.

## The 15-agent responsibility model

Every agent has a possible ARB responsibility, but a review activates only the agents relevant to
the target's ontology relationships and active objectives.

| Agent | ARB responsibility | Activation condition |
|-------|--------------------|----------------------|
| Odin | Arbitrate eligible cross-objective conflicts | Two or more eligible options conflict after hard constraints |
| Thor | Execute a separately promoted action | A final action verdict passes all action gates |
| Forseti | Join evidence, evaluate constraints, create the case and decision recommendation | Every planned change review |
| Huginn | Normalize, deduplicate, correlate, and publish the exact `Change` revision | Planned-change ingress |
| Heimdall | Validate graph and telemetry health, then independently close effects | Reliability, security, drift, forecast, or terminal outcome evidence is required |
| Vidar | Validate recovery readiness and own recovery after failure | The proposed change needs rollback or recovery evidence |
| Var | Enforce role, quorum, timeout, and no-self-approval | Policy-mandated or residual human approval |
| Bragi | Translate an operator request and explain grounded results | Conversational start or explanation |
| Saga | Persist audit intent, decision lineage, conditions, and terminal closure | Every review transition |
| Mimir | Supply active constraints and policies; steward approved catalog changes | Constraint evaluation or accepted constraint change |
| Muninn | Retain change revisions and materialize bounded context | Every planned change review |
| Norns | Propose inert rules from repeated reviewed outcomes | A bounded outcome cohort shows a reusable pattern |
| Njord | Evaluate cost objectives and budget effects | Cost-sensitive services or resources are in scope |
| Freyr | Evaluate capacity and performance effects | Capacity or performance objectives are in scope |
| Loki | Propose resilience experiments without self-authorizing them | Existing evidence cannot establish recovery behavior safely |

## Evidence fan-out and join

Agents collaborate through typed publish and subscribe only. The review coordinator is mechanical:
it records deadlines and required evidence keys, but Forseti owns the decision to continue, hold,
or escalate.

1. Huginn publishes one immutable `Change` and preserves one correlation ID plus the requested
   ontology release digest.
2. Muninn materializes a secured snapshot for the exact graph release and evidence cutoff. The
   snapshot requires verified links before it can produce authenticated graph evidence.
3. Relevant specialists publish only their owned object topics with the same case reference.
4. Forseti converts that exact snapshot into the planned-change graph receipt, compares its ontology
   release with the requested digest, and joins the policy-required evidence set under a deadline.
   Missing, stale, unauthenticated, conflicting, synthetic, or truncated evidence lowers the
   authority ceiling.
5. Before asking a person, FDAI attempts bounded reacquisition, an alternate authoritative source,
   deterministic reevaluation, or a smaller safe option.

Slow or failed subscribers do not block unrelated work. The owner of the join records an explicit
missing or late branch instead of interpreting silence as success.

The current runtime binding keeps this boundary observation-only. A dedicated non-agent consumer
group reads owned `object.change`, `object.state-snapshot`, specialist, `object.verdict`, and
`object.audit-entry` topics, replays the immutable `ArchitectureReviewObservationTrace`, and
retains terminal observer `gave_up`/`halted` states as degradation evidence. It does not call
agents directly, mutate runtime state, or grant execution authority. When an ARB stage has no
distinct owned record yet, the trace stays on hold instead of synthesizing success.

The review accepts only `planned` intent. It hashes the complete Change identity, uses one absolute
deadline, and serializes only identical idempotency keys, so unrelated reviews can continue in
parallel. Context and evidence must name the same ontology and catalog releases. An unavailable
re-read preserves existing checks instead of removing them, and evidence artifact identities bind
the bundle and item content. The resulting `Change`, `DecisionCase`, `ImpactEnvelope`, and
`ReviewCase` records retain typed lineage links and remain explicitly observation-only.
The base graph must be complete and its source generation must match the authenticated context
before an envelope can be conformant. Projection status is recorded with the observation, so a
stored result retries a failed or unavailable production projection without re-running evidence
collection. Existing Huginn `Change` records are preserved; a new Change is projected only when
the exact normalized fields are present.
Scenario branch identifiers use an ASCII-safe bounded prefix plus a content digest, including for
UUID-shaped or otherwise long Change identifiers.

## Autonomous review levels

Autonomy applies to review work before it applies to changes. A machine-ready result is not the
same as production authorization.

| Level | Conditions | Result |
|-------|------------|--------|
| Automatic conformance | Exact change, fresh complete graph, active objectives and constraints, verified evidence, bounded impact, no conflict | Record a conformant recommendation under bounded standing authority |
| Automatic conditional review | Deterministic conditions can close all known gaps | Record conditions and reevaluate automatically when evidence changes |
| Human approval | Policy requires a person, an exception is requested, impact is high, or residual ambiguity remains | Var opens a scoped approval with quorum and expiry |
| Hold or reject | Evidence is incomplete, stale, conflicting, target-mismatched, or a hard constraint is violated | Apply no change; record the reason and next evidence action |

Architecture baseline changes, production promotion, irreversible changes, and exceptions do not
gain automatic authority from a green graph result.

## Review projection

The Console should present separate axes instead of one green or red status:

- **Evidence state:** complete, incomplete, stale, conflicting, or unavailable.
- **Evaluation state:** conformant, conditional, violated, or held.
- **Authority state:** observation only, standing authorization, approval required, or approved.
- **Execution state:** not requested, pending, running, verified, failed, or recovered.
- **Learning state:** ineligible, cohort collecting, candidate proposed, or catalog reviewed.

Every displayed state links to the exact `Change`, context digest, evidence bundle digest,
`DecisionCase`, conditions, approvals, and audit records that produced it.

## Current gaps

| Gap | Required correction |
|-----|---------------------|
| Planned-change assessment now falls back to `ChangeGraphEvidenceReceipt.unavailable()` | Wire the receipt from the exact `OperationalContextSnapshot` so planned-change review carries an authenticated graph revision, release match, freshness, and truncation state |
| Workflow parallel branches journal caller-supplied outcomes | Drive branches from agent-owned typed evidence and record explicit deadlines |
| ARB projection reads manifest status directly | Derive `ReviewCase` and `ReviewCheck` from decision lineage and verified evidence |
| `OperationalEvidenceBundle` and scenario branches are not composed into ARB | Bind them before Forseti creates the review `DecisionCase` |
| Operating intent instances are not proven end to end | Project service, recovery, cost, ownership, constraint, and change-window instances with freshness |
| The ARB trace runtime binding currently covers only the emitted owned topics | Extend owned records for context, evidence bundle, impact envelope, recommendation, and the derived `ReviewCase` projection so the observation-only runtime trace can close the full first vertical slice without synthesizing missing stages |

## Related docs

| To learn about | Read |
|----------------|------|
| ARB entry point and decision boundary | [Architecture Review Board Packet](../architecture-review-board.md) |
| Evidence, approvals, and production exit | [Evidence and Authority](evidence-and-authority.md) |
| Dependency-ordered implementation | [Delivery Plan](delivery-plan.md) |
| Operating ontology ownership | [Operating Ontology](../operating-ontology.md) |
| Fixed agent roles | [Agent Pantheon](../../agents/agent-pantheon.md) |
| Delivery status and remaining work | [Implementation ledger](../../../roadmap-implementation/architecture/architecture-review/ontology-agent-loop.md) |
