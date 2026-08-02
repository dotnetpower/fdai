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
dashboard, general-purpose workflow platform outside cloud operations, or unbounded enterprise
decision platform.

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

Every decision-critical evidence receipt names its authority class, authenticated source identity,
scope, purpose, query or detector version, event and recorded time, freshness policy, coverage or
completeness, provenance digest, and synthetic status. Synthetic or fixture evidence may validate
mechanics but never satisfies live readiness, production approval, or promotion evidence. An
absence claim requires positive coverage and completeness proof; missing, censored, inaccessible,
or unobserved data remains unknown rather than healthy.

Effect verification is independent of the executor and its command channel. A broker, provider, or
API receipt proves dispatch only. A distinct observer using an authoritative effect source closes
the expected observation window. Conflicting authoritative sources remain an explicit conflict and
lower autonomy; aggregation never averages the conflict away.

## Article 3: Agent-driven authority

**FDAI-CONST-003 - Independent accountable agents.** Every capability and state transition has one
accountable agent in the fixed 15-agent pantheon. Agents are independently schedulable and
concurrent. Authority-bearing collaboration and every state transition use schema-validated
event-bus publish and subscribe only. Direct agent calls, RPC chains, implementation imports
between agents, and shared mutable workflow state are not supported. Bounded peer deliberation may
read owned immutable projections through a composition-owned registry only for presentation; it
cannot publish state, decide, approve, execute, or grant authority.

Single-writer ownership and separation of duties are absolute:

- Forseti judges, Var carries human approval, Thor alone executes, Saga audits, and Vidar recovers.
- No principal judges and executes, approves and executes, or grants authority to itself.
- Bragi translates between natural language and typed tools; it never judges, approves, or executes.
- Saga and Vidar are hard dependencies for mutation. Their loss lowers capability to shadow or
  no-op and never fails open.

Dependency loss preserves only paths whose complete required contracts remain independently
available. Read, deny, queue, and shadow evaluation may continue. A state change is blocked when
its judge, executor, auditor, recovery path, required observer, context materializer, or applicable
approval lane is unavailable. One component's heartbeat or cached output never substitutes for a
missing authority or fresh evidence receipt.

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

Every active, candidate, or calculated threshold records its semantic type, unit, scope, allowed
range, exact version or digest, effective interval, evidence cutoff, algorithm or model version,
promotion evidence, and rollback target. Replay resolves those exact values at the original
decision cutoff; a latest value never rewrites a historical decision.

Every decision context pins event time, recorded time, each fact's effective interval, the evidence
cutoff, per-source freshness receipts, and the trusted UTC clock source. Late evidence creates a
new revision and never rewrites the original context. Deadlines use trusted UTC for persisted
instants and monotonic elapsed time within a process. Missing time authority, excessive clock skew,
future-effective facts, or expired facts lowers autonomy and remains visible in replay.

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

| Domain detail | Owner documents |
|---------------|-----------------|
| SRE operations | [Observability and Detection](../rules-and-detection/observability-and-detection.md), [Operator-Initiated SRE and ARB](../operations/operator-initiated-sre-and-arb.md) |
| Resilience Engineering | [Recovery and Chaos Enforcement](../decisioning/recovery-and-chaos-enforcement.md) |
| Change and Architecture Governance | [Architecture Review Board Packet](architecture-review-board.md), [Action Ontology](../decisioning/action-ontology.md) |
| FinOps | [Cost Model](../interfaces/cost-model.md), [Agent Workflows](../agents/agent-workflows.md) |

Coverage requires the complete loop for each domain: observe, normalize, gather evidence, decide,
plan, authorize, act, verify, and learn. Target, implemented, and planned status must remain
explicitly separate.

Each domain capability is covered only when its frozen scenario pack includes: a successful
full-loop case, an explicit unknown or deny case, a cross-objective conflict, a partial failure and
recovery case, an A3-E case or documented non-applicability, and deterministic replay with cited
runtime evidence. Minimum domain outcomes are:

| Capability | Required outcome proof |
|------------|------------------------|
| SRE | SLO or incident detection through independently verified recovery and recurrence closure |
| ARB / Change Safety | graph diff and constraints through approval conditions and post-change verification |
| FinOps | forecast or finding through realized savings while protected reliability objectives remain valid |
| DR | failover or restore through data-integrity checks and measured RTO/RPO |
| Chaos Engineering | explicit human-approved injection through continuous stop guards and verified recovery; A3-E injection is not applicable |

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

**FDAI-CONST-007 - Seven safeguards on every autonomous state change.** Any action that changes a
managed resource, external system, durable artifact, approval state, or notification state is
ineligible unless all seven safeguards are declared and its pre-dispatch checks pass:

1. a machine-evaluable stop condition;
2. a tested rollback or bounded recovery path;
3. a computed impact scope and blast-radius limit;
4. a successful what-if or dry-run receipt;
5. a held logical-target lock with causal ordering, using the resource identity for managed-resource changes;
6. a stable idempotency key with duplicate suppression;
7. an append-only audit intent persisted before the side effect and closed with execution and outcome afterward.

The lock remains held through side-effect commit; long observation windows use the pinned target
revision rather than holding a lock indefinitely. Pure A0 reads and explanations do not require
mutation rollback, dry-run, or a mutation lock, but still require authorization, bounded evidence,
redaction, correlation, and audit according to their read contract. Independent effect
verification is required before success can be reported. New capabilities begin
in shadow mode. Promotion is explicit, per capability, evidence-gated, and independent of runtime,
environment, enabled state, and fork status. A regression or unavailable hard dependency lowers
authority automatically.

## Article 8: Autonomy and standing authority

**FDAI-CONST-008 - Risk-bounded autonomy.** FDAI classifies authority by action risk:

The display labels remain A0-A4. Machine records use namespaced values (`autonomy.a0`,
`autonomy.a1`, `autonomy.a2`, `autonomy.a3_h`, `autonomy.a3_e`, `autonomy.a4`). They are unrelated
to the A1-A4 message categories in Channels and Notifications; implementations must never compare,
join, or translate the two enum families by their numeric suffix.

| Display class | Machine value | Authority |
|---------------|---------------|-----------|
| A0 | `autonomy.a0` | observe, explain, and simulate without mutation |
| A1 | `autonomy.a1` | execute a reversible, resource-scoped, low-risk action inside current policy |
| A2 | `autonomy.a2` | execute a promoted workflow inside a measured and pre-approved envelope |
| A3-H | `autonomy.a3_h` | hold a high-impact action for independent per-execution human approval |
| A3-E | `autonomy.a3_e` | execute a non-destructive, reversible emergency mitigation under valid standing human authorization |
| A4 | `autonomy.a4` | deny prohibited, self-approved, unbounded, cross-tenant, or unverifiable action |

A3-E is approval given in advance, not approval inferred from silence. It is valid only when all of
these conditions hold:

- at least two normalized, distinct humans approved it, including the accountable service owner and
  an Owner-level authority; the requester and executor are ineligible approvers;
- the approval names the service, incident class, ActionTypes, scope, trigger, escalation deadline,
  impact envelope, stop conditions, rollback, validity interval, and current primary and backup responders;
- the authorization is resource-group-equivalent or narrower and pins its own revision, policy
  digest, ActionType and workflow versions, target revision, and evidence revisions; any change or
  revocation makes it ineligible until independently approved again;
- applicable service logs, incidents, and audit history were reviewed and the presence or absence
  of a precedent was recorded; when no adequate precedent exists, a current DR drill, bounded Chaos
  experiment, or simulation provides equivalent scenario evidence;
- every ownership handover re-confirms the delegation; missing, stale, or declined confirmation
  suspends it;
- revocation takes effect immediately and renewal creates a new immutable revision with fresh
  quorum, evidence, responder confirmation, and validity rather than extending the old record;
- delivery through the declared channel fallback is confirmed before human silence is measured;
  every contact, delivery, and escalation attempt is audited;
- the action remains reversible and inside the exact envelope when the deadline expires;
- the action's declared maximum duration fits entirely before `valid_until`; otherwise it returns
  to current human approval instead of starting under authority that will expire mid-run;
- the supervisor re-enters the typed risk pipeline and never calls the executor directly;
- immediate notification and time-bounded post-action review follow execution.

Standing authorization never applies to A4. Irreversible or wider-scope recovery requires fresh
human approval with the configured quorum. A3-E never authorizes Chaos fault injection; an already
approved experiment may pre-authorize only its bounded stop and recovery sequence.

## Article 9: Workflow governance

**FDAI-CONST-009 - Flexible composition, strict execution.** Operators and FDAI may design new
workflows, but a workflow composes only registered ActionTypes and typed evidence steps. It cannot
declare an inline mutation, assign an agent a new role, or bypass the event bus, quality gate, risk
gate, approval, executor, recovery, or audit path.

Every workflow declares its goal, trigger, preconditions, protected objectives, bounded steps,
deadlines, stop conditions, expected effects, failure behavior, compensation, completion criteria,
and anti-scope. One accountable owner advances a revisioned durable Process snapshot and
append-only journal. Ontology and console projections are rebuildable read models; agents never
coordinate by sharing mutable Process state.

A new or materially changed workflow begins in shadow mode and passes structural validation,
simulation or dry-run, scenario regression, and explicit promotion. A promoted workflow instance
may vary only declared parameters inside their active bounds. Changing a step, ActionType, guard,
order, failure edge, or compensation creates a new immutable workflow version that returns to
shadow; approved primitives do not make a new composition pre-approved.

After any failure, cancellation, or timeout, the Process stops new forward dispatch, records the
exact partial state, and compensates applied steps in reverse dependency order through the normal
typed pipeline. It cannot report success until compensation and independent recovery verification
finish. Missing, failed, or unscorable compensation closes as an explicit recovery-incomplete
failure and places a durable automation hold on affected targets. The hold permits reads and
separately approved recovery only; human review cannot relabel partial state as recovered.

## Article 10: Evidence, traceability, and amendment

**FDAI-CONST-010 - Proof and constitutional precedence.** Every operational claim and requirement
must be traceable through this chain:

```text
purpose -> constitutional requirement -> ontology or schema -> policy -> agent responsibility
        -> workflow or ActionType -> implementation -> test -> runtime evidence
```

| Article | Detailed owners | Required verification evidence |
|---------|-----------------|--------------------------------|
| 001 | App Shape, Generic Scope | scope gates, provider-boundary tests, deployment status |
| 002 | Goals and Metrics, Outcome Assurance | zero-threshold guards, outcome receipts, replay |
| 003 | Agent Pantheon | role parity, topic ownership, concurrency, hard-dependency tests |
| 004 | Operating Ontology, Rule Governance | schema, provenance, freshness, promotion, replay tests |
| 005 | Domain owner documents in Article 5 | per-domain full-loop scenario and status evidence |
| 006 | Agent Pantheon arbitration, Risk Classification | hard-constraint and arbitration property tests |
| 007 | Security and Identity, Action Ontology | shadow, dry-run, lock, idempotency, rollback, audit tests |
| 008 | Risk Classification, Escalation and Standing Authority | approval, expiry, handover, envelope, denial tests |
| 009 | Process Automation, Workflow Control-Loop Integration | loader, version pinning, guard, compensation, promotion tests |
| 010 | Design Routes, Constitution Checker | bilingual, link, route, traceability, and CI checks |

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
