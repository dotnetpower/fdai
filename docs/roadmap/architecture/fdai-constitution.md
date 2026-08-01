---
title: FDAI Constitution
---
# FDAI Constitution

This document is the highest design authority for FDAI. It defines the purpose, guarantees,
authority boundaries, and amendment rules that every detailed design, machine contract,
implementation, workflow, and deployment must preserve.

> **Normative scope:** This constitution defines target behavior. Implementation status belongs in
> capability and delivery documents and must never weaken a constitutional requirement.
>
> **Accuracy scope:** FDAI guarantees contract-conformant behavior, not a correct diagnosis or a
> successful external outcome in every novel situation. Uncertainty results in recovery, a smaller
> safe plan, no-op, denial, rollback, or human review instead of an unsupported action.

## Design at a glance

FDAI is an evidence-governed autonomous cloud-operations control plane. Fifteen independently
runnable agents use typed events, a shared operating ontology, deterministic rules, bounded
reasoning, and separated authority to observe, decide, plan, authorize, execute, verify, recover,
audit, and learn. Humans define policy, risk, and delegated authority; FDAI minimizes human
touchpoints without weakening those boundaries.

## Article 1: Purpose and scope

**FDAI-CONST-001 - Autonomous cloud operations.** FDAI exists to minimize human intervention in
cloud operations while preserving safety, accountability, and measured operational objectives.
It is a headless control plane with a thin FDAI Console and ChatOps surfaces, not a chatbot,
dashboard, general workflow engine, or unbounded enterprise decision platform.

Azure is the implemented provider. Provider contracts remain cloud-provider-neutral so another
provider can be added without changing constitutional behavior. Upstream artifacts remain
customer-agnostic; deployment identities, values, objectives, evidence, and accountable people
stay in governed deployment configuration or a supported downstream distribution.

## Article 2: Contract-conformant accuracy

**FDAI-CONST-002 - Zero unsafe guesses.** FDAI targets 100% contract-conformant terminal behavior.
Every accepted input must reach a schema-valid, evidence-supported, authorized, attributable, and
replayable result, or an explicit unknown, no-op, denial, rollback, or human-review state.

The following outcomes are constitutional violations with a threshold of zero:

- action against the wrong object identity or stale target revision;
- execution outside a registered ActionType, authority, identity, or impact scope;
- policy-violation escape into enforcement;
- success claimed without independent expected-effect verification;
- external truth inferred from an ontology or catalog write instead of authoritative observation;
- learned output that raises authority without review and promotion evidence.

## Article 3: Agent-driven authority

**FDAI-CONST-003 - Independent accountable agents.** Every capability and state transition has one
accountable agent in the fixed 15-agent pantheon. Agents are independently schedulable and
concurrent. Machine collaboration uses schema-validated event-bus publish and subscribe only.
Direct agent calls, RPC chains, implementation imports between agents, and shared mutable workflow
state are not supported.

Single-writer ownership and separation of duties are absolute:

- Forseti judges, Var carries human approval, Thor alone executes, Saga audits, and Vidar recovers.
- No principal judges and executes, approves and executes, or grants authority to itself.
- Bragi translates between natural language and typed tools; it never judges, approves, or executes.
- Saga and Vidar are hard dependencies for mutation. Their loss lowers capability to shadow or
  no-op and never fails open.

## Article 4: Semantic, policy, and learning boundaries

**FDAI-CONST-004 - Meaning does not grant authority.** The operating ontology defines object,
relationship, state, objective, action, and evidence semantics. It validates identity, units,
ranges, cardinality, freshness, and allowed combinations, but it does not sense, judge, approve,
execute, or grant permission.

Control values are separated by responsibility:

| Concern | Authority |
|---------|-----------|
| Meaning, type, unit, range, and hard semantic bounds | versioned ontology and schemas |
| Active thresholds, objectives, scope, and risk rules | versioned policy and configuration |
| Candidate thresholds and learned patterns | inert learning records with provenance and confidence |
| Promotion into active use | independently reviewed promotion registry |
| Current external state | authoritative inventory, telemetry, provider, and audit observations |

Hard safety bounds are not adaptive. Governed policy thresholds may change inside declared bounds
after evidence, validation, shadow evaluation, and promotion. Situation-specific values may be
calculated at decision time only by an approved, versioned algorithm. Missing, stale, conflicting,
or unproven context can only preserve or lower autonomy.

## Article 5: Operating domains

**FDAI-CONST-005 - One control plane, multiple operating domains.** Domain capability does not
create a domain-specific super-agent. Stable responsibility agents apply the same control loop and
ontology across these operating domains:

| Domain | Constitutional scope |
|--------|----------------------|
| SRE operations | SLOs, error budgets, observability, incidents, capacity, performance, and operational automation |
| Resilience Engineering | disaster recovery, backup, restore, failover, continuity, and Chaos Engineering |
| Change and Architecture Governance | Architecture Review Board evidence, architecture constraints, drift, deployment, and change safety |
| FinOps | cost visibility, allocation, forecasting, efficiency, and verified optimization |

SRE is the overall operating model. Resilience, Change Safety, and Cost Governance remain the
initial product verticals. Disaster recovery and Chaos Engineering are distinct Resilience
capabilities; Architecture Review Board governance applies across all domains.

Coverage requires the complete loop for each domain: observe, normalize, gather evidence, decide,
plan, authorize, act, verify, and learn. Target, implemented, and planned status must remain
explicitly separate.

## Article 6: Objective precedence

**FDAI-CONST-006 - Constraints before optimization.** FDAI first removes every option that violates
a higher-order constraint. Weighted scoring or learned optimization may rank only the remaining
eligible options and can never compensate for a failed hard constraint.

The default precedence is:

1. safety, security, compliance, tenant, and identity boundaries;
2. data integrity and recoverability;
3. approved SLO, RTO, RPO, and error-budget objectives;
4. change safety and impact containment;
5. performance and operational efficiency;
6. cost optimization.

A deployment may refine objectives inside this order. Lowering a higher-order objective for a
business tradeoff requires an explicit policy amendment and human authority; it is not an
automatic arbitration result.

## Article 7: Autonomous-action safeguards

**FDAI-CONST-007 - Seven safeguards on every autonomous mutation.** An autonomous mutation is
ineligible unless all seven safeguards are present and verified:

1. a machine-evaluable stop condition;
2. a tested rollback or bounded recovery path;
3. a computed impact scope and blast-radius limit;
4. a successful what-if or dry-run receipt;
5. a held per-resource lock with causal ordering;
6. a stable idempotency key with duplicate suppression;
7. an append-only audit record covering decision, authority, execution, and outcome.

Independent effect verification is required before success can be reported. New capabilities begin
in shadow mode. Promotion is explicit, per capability, evidence-gated, and independent of runtime,
environment, enabled state, and fork status. A regression or unavailable hard dependency lowers
authority automatically.

## Article 8: Autonomy and standing authority

**FDAI-CONST-008 - Risk-bounded autonomy.** FDAI classifies authority by action risk:

| Class | Authority |
|-------|-----------|
| A0 | observe, explain, and simulate without mutation |
| A1 | execute a reversible, resource-scoped, low-risk action inside current policy |
| A2 | execute a promoted workflow inside a measured and pre-approved envelope |
| A3-H | hold a high-impact action for independent per-execution human approval |
| A3-E | execute a reversible emergency mitigation under valid standing human authorization |
| A4 | deny prohibited, self-approved, unbounded, cross-tenant, or unverifiable action |

A3-E is approval given in advance, not approval inferred from silence. It is valid only when all of
these conditions hold:

- a named accountable human approved the service, incident class, ActionTypes, scope, trigger,
  escalation deadline, impact envelope, stop conditions, rollback, validity period, and primary
  and backup responders;
- applicable service logs, incidents, and audit history were reviewed and the presence or absence
  of a precedent was recorded; when no adequate precedent exists, a current DR drill, bounded Chaos
  experiment, or simulation provides equivalent scenario evidence;
- every ownership handover re-confirms the delegation; missing, stale, or declined confirmation
  suspends it;
- real humans are contacted through the declared escalation ladder and every attempt is audited;
- the action remains reversible and inside the exact envelope when the deadline expires;
- the supervisor re-enters the typed risk pipeline and never calls the executor directly;
- immediate notification and time-bounded post-action review follow execution.

Standing authorization never applies to A4. Irreversible or wider-scope recovery requires fresh
human approval with the configured quorum.

## Article 9: Workflow governance

**FDAI-CONST-009 - Flexible composition, strict execution.** Operators and FDAI may design new
workflows, but a workflow composes only registered ActionTypes and typed evidence steps. It cannot
declare an inline mutation, assign an agent a new role, or bypass the event bus, quality gate, risk
gate, approval, executor, recovery, or audit path.

Every workflow declares its goal, trigger, preconditions, protected objectives, bounded steps,
deadlines, stop conditions, expected effects, failure behavior, compensation, completion criteria,
and anti-scope. Its runtime Process is reconstructed from an append-only journal and immutable
projections rather than shared mutable coordination state.

A new or materially changed workflow begins in shadow mode and passes structural validation,
simulation or dry-run, scenario regression, and explicit promotion. Previously promoted templates
may adapt policy parameters or compose approved primitives only inside their active authority.

## Article 10: Evidence, traceability, and amendment

**FDAI-CONST-010 - Proof and constitutional precedence.** Every operational claim and requirement
must be traceable through this chain:

```text
purpose -> constitutional requirement -> ontology or schema -> policy -> agent responsibility
        -> workflow or ActionType -> implementation -> test -> runtime evidence
```

Authority descends in this order:

1. this constitution defines purpose and non-negotiable design constraints;
2. `.github/copilot-instructions.md` carries its short always-on execution summary;
3. scoped instruction and roadmap documents refine one responsibility without overriding it;
4. versioned schemas, ontologies, and catalogs encode exact machine contracts;
5. code, tests, and runtime evidence demonstrate implementation and compliance.

A lower layer that disagrees with a higher layer is defective; deployed behavior does not become
correct merely because code currently implements it. Machine-readable sources of truth own exact
names, versions, and observed values only inside their declared constitutional boundary.

An amendment updates the English source and Korean translation together, identifies affected
requirement ids, updates every impacted instruction and contract in the same change, and supplies
focused validation evidence. A change that widens autonomy requires independent owner-level review
under the governance policy. Implementation status and target metrics never amend the constitution.

## Related documents

| To learn about | Read |
|----------------|------|
| Always-on engineering rules | [Copilot instructions](../../../.github/copilot-instructions.md) |
| Control loop and agent runtime | [Architecture instructions](../../../.github/instructions/architecture.instructions.md) |
| Accuracy metrics and zero thresholds | [Goals and Metrics](goals-and-metrics.md) |
| Shared operational meaning | [Operating Ontology](operating-ontology.md) |
| Fixed agent responsibilities | [Agent Pantheon](../agents/agent-pantheon.md) |
| Baseline risk decisions | [Risk Classification](../decisioning/risk-classification.md) |
| Emergency delegated authority | [Escalation and Standing Authority](../decisioning/escalation-and-standing-authority.md) |
| Governed workflow composition | [Process Automation](../decisioning/process-automation.md) |
