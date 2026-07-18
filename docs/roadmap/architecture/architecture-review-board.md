---
title: Architecture Review Board Packet
---
# Architecture Review Board Packet

This packet is the canonical entry point for reviewing FDAI's target architecture. It separates
approval of the design baseline from approval to deploy or enable production enforcement, and it
links every claim to a repository artifact or a fork-supplied evidence binding.

> **Decision requested:** conditionally approve the Azure target-architecture baseline. Production
> deployment and enforce-mode approval are explicitly out of scope while
> `config/architecture-review.yaml` reports `production_approval_status: blocked`.
>
> **Customer boundary:** upstream defines the reusable architecture and evidence contract. A fork
> supplies environment values, accountable people, privacy decisions, service objectives, and
> production evidence.

## Design at a glance

FDAI is a headless, event-driven control plane with a read-only console and GitOps/ChatOps delivery.
It resolves repeatable events with T0 deterministic rules and T1 similarity reuse, and sends only
ambiguous cases to T2 grounded reasoning. Every proposed mutation passes the risk gate, carries a
stop condition, rollback contract, blast-radius limit, and audit record, and starts in shadow mode.

## Decision boundary

| Decision | Current request | Approval effect |
|----------|-----------------|-----------------|
| Target architecture | Conditional approval | Accepts the system boundaries, Azure day-zero choices, control loop, and safety model |
| Production deployment | Not requested | Requires the production evidence gate to pass |
| Enforce-mode capability | Not requested | Requires per-action shadow evidence and separate approval |
| Hyperscale Plan B | Reference only | Becomes applicable only after a measured trigger in the hyperscale design |
| Sovereign profile | Reference only | Requires a separate regulatory and residency review |

The machine-readable decision state lives in
[`config/architecture-review.yaml`](../../../config/architecture-review.yaml). Run the structural
check on every change:

```bash
python3 scripts/governance/check-arb-readiness.py
```

A production promotion pipeline uses the fail-closed form:

```bash
python3 scripts/governance/check-arb-readiness.py --require-production-ready
```

## Scope and context

### In scope

- Azure implementation of the headless control plane and its provider boundaries.
- Event Hubs through the Kafka endpoint, Container Apps, PostgreSQL Flexible Server with pgvector,
  Key Vault references, managed identities, Log Analytics, and Application Insights.
- The T0/T1/T2 control loop, quality gate, unified risk gate, executor, audit, GitOps, and HIL.
- Development, staging, and production artifact promotion with shadow-before-enforce controls.
- Day-zero operations, rollback, observability, cost, and the measured path to cell-based scale.

### Out of scope for this decision

- Non-Azure provider implementations.
- Customer-specific rules, thresholds, identities, endpoints, and organization policy.
- Production approval, because owner and evidence bindings remain intentionally empty upstream.
- Plan B deployment, sovereign-profile certification, and secondary-region resources.

## Architecture views

| View | Design authority | Review focus |
|------|------------------|--------------|
| System context and layer boundaries | [App Shape](../../../.github/instructions/app-shape.instructions.md) | humans, Git, ChatOps, console, core, and privileged executor boundaries |
| Control flow | [Architecture](../../../.github/instructions/architecture.instructions.md) | event ingestion, tiering, verification, risk decision, execution, and audit |
| Module and deployment mapping | [Project Structure](project-structure.md) | ownership boundaries and provider adapters |
| Azure day-zero deployment | [Deploy and Onboard](../deployment/deploy-and-onboard.md) | concrete resource inventory and bootstrap order |
| Identity and data flows | [Security and Identity](security-and-identity.md) | trust boundaries, authorization, secrets, and STRIDE threats |
| Scale transition | [Hyperscale Cell Architecture](hyperscale-cell-architecture.md) | trigger-based move from one cell to sharded cells |

### Current, target, and transition states

| State | Description | Evidence status |
|-------|-------------|-----------------|
| Current upstream | Reusable code, Terraform modules, tests, generic configuration, and design docs; no customer production values | Verifiable in this repository |
| Day-zero target | One Azure region, one Container Apps cell, Event Hubs Kafka, PostgreSQL + pgvector, Key Vault, scoped managed identity, Log Analytics | Design accepted by ADR-0001; production evidence still required |
| Production target | Signed image, private or explicitly allow-listed data flows, bound owners, approved objectives, blocking release controls, operational-readiness report | Blocked until the manifest production gate passes |
| Scale target | Multiple cells, policy-driven fan-in, CQRS audit indexing, and deployment profiles | Deferred until a measured trigger is crossed |

## Requirements traceability

| Requirement | Design response | Verification source |
|-------------|-----------------|---------------------|
| Deterministic-first decisions | T0 exact rules, then T1 reuse, then quality-gated T2 | tier tests and frozen scenario set |
| No ungated autonomous mutation | unified risk gate and role-bound executor | risk-gate property tests and audit evidence |
| Separation of duties | requester, approver, judge, and executor are distinct principals | RBAC configuration and HIL tests |
| Retry safety | stable idempotency key and per-resource serialization | idempotency and replay tests |
| Reversibility | rollback contract plus stop condition on each ActionType | rollback rehearsal evidence |
| Customer isolation | fork-supplied values and dependency injection | generic-scope gates and config validation |
| Operability | health signals, canary, smoke, alert routing, and runbooks | operational-readiness report |
| Cost control | scale-to-zero, token budgets, resource budgets, and measured graduation triggers | cost confirmation and capacity evidence |

## Nonfunctional evidence contract

Targets that depend on a deployment are not universal upstream constants. A production fork records
the approved value, measurement method, result, timestamp, and approver in its evidence binding.

| Area | Required production evidence | Pass condition |
|------|------------------------------|----------------|
| Availability | control-plane SLO and error budget | approved objective plus measured staging result |
| Latency | p50/p95/p99 by tier and end-to-end canary | within the fork-approved budget |
| Capacity | sustained and burst event rate, partition lag, DB saturation, quota headroom | no loss; bounded lag; documented saturation point |
| Reliability | service-specific RPO/RTO and business-impact analysis | approved numeric objectives |
| Recovery | isolated restore and failover drill | objectives met with integrity and smoke checks passing |
| Security | threat review, private/allow-listed data-flow validation, least-privilege probe | no unresolved critical/high finding |
| Privacy | privacy impact assessment and data inventory | approved by the privacy owner |
| Operations | signed operational-readiness report, canary, smoke, alert, and runbook evidence | all production checks pass |
| Supply chain | SBOM, signature, provenance, vulnerability and IaC scans | release artifact verified; blocking scans clean |
| Cost | current calculator export, monthly cap, quota, and 12/36-month assumptions | cost owner approval |

## Data, privacy, and compliance

[Data Governance](data-governance.md) defines the classification, minimization, residency,
retention, legal-hold, deletion, model-provider, and privacy-assessment contract. The upstream
design does not claim a customer compliance certification. A production fork selects its control
profile, maps controls to evidence, records exceptions, and binds a privacy and data owner.

## Ownership and support

The production gate requires these accountable slots. A group may fill a slot, but every binding
must identify an escalation route and a distinct approval authority where separation of duties
applies.

| Owner slot | Accountable for |
|------------|-----------------|
| `architecture-owner` | architecture baseline, ADRs, and accepted technical debt |
| `security-owner` | threat model, identity, network posture, and security exceptions |
| `privacy-owner` | privacy impact assessment and data-processing decisions |
| `data-owner` | classification, retention, legal hold, deletion, and data quality |
| `operations-owner` | on-call, alerts, runbooks, and operational-readiness acceptance |
| `reliability-owner` | SLO, RPO/RTO, recovery design, and drill acceptance |
| `release-owner` | artifact provenance, deployment, rollback, and promotion gates |
| `cost-owner` | budget, quota, price confirmation, and capacity graduation |

Agent stewardship remains a separate accountability overlay. It does not grant authorization or
replace these production owner slots.

Each `owner_bindings` entry uses this shape:

```yaml
architecture-owner:
   subject: group:<fork-owned-subject>
   escalation: <fork-owned-escalation-route>
```

Each `evidence_bindings` entry is immutable evidence metadata, not the evidence body:

```yaml
production-terraform-plan:
   uri: evidence://<governed-store-reference>
   sha256: <64-lowercase-hex-digest>
   approved_by: group:<fork-owned-approver>
   approved_at: 2026-07-13T00:00:00Z
```

The checker rejects unknown binding keys, missing fields, malformed digests, and invalid timestamps.
Customer names, resource ids, and evidence bodies remain in the fork's governed store.

## Dependencies and failure behavior

| Dependency | Contract | Failure behavior | Production evidence |
|------------|----------|------------------|---------------------|
| Event Hubs Kafka | ordered, at-least-once event log with DLQ topics | backpressure or hold for review; never drop silently | round-trip, lag, replay, and DLQ test |
| PostgreSQL + pgvector | transactional state, audit projection, and T1 vectors | fail closed; no in-memory fallback in production | connection, backup, restore, and saturation test |
| Key Vault reference | environment-secret injection | startup fails if a required secret cannot resolve | rotation and unavailable-vault test |
| Entra and managed identity | short-lived, audience-scoped identity | deny access; no credential fallback | least-privilege and recertification evidence |
| Git host | reviewed remediation and governance changes | queue proposal; do not execute out of band | protected-branch and rollback test |
| HIL channel | authenticated, action-bound approval | queue and use configured fallback; timeout is no-op | primary/fallback and replay-resistance test |
| Model providers | budgeted, grounded T2 and narrator access | hold for review when unavailable or unverified | provider, residency, retention, and budget evidence |
| Observability backend | correlated logs, metrics, traces, and alerts | raise monitor-of-monitor signal | canary and alert delivery result |

## Decisions

The ADR index is [Architecture Decision Records](decisions/README.md). ADR-0001 records the
accepted Azure day-zero platform baseline. Open environment decisions such as numeric RPO/RTO,
retention, cost caps, and production owners are fork bindings, not hidden architecture defaults.

## Risk, assumptions, issues, and exceptions

The active critical and high risks are machine-readable under `blockers` in
`config/architecture-review.yaml`.

| Type | Rule |
|------|------|
| Risk | carries severity, accountable owner slot, mitigation, residual risk, and review date |
| Assumption | identifies the validating evidence and expires when contradicted or measured |
| Issue | links to the artifact or implementation that closes it |
| Exception | is scoped, time-bound where required, independently approved, and audited |

An accepted risk is not a resolved blocker. The production gate accepts a critical or high item
only after its status and evidence are updated through review.

## Production exit procedure

1. Bind every required owner slot in the customer fork.
2. Attach each required evidence artifact and verify that it contains no secret or customer data
   in the upstream repository.
3. Resolve or formally accept each blocker through the appropriate governance path.
4. Mark production artifacts `ready`, approve the design review, and set production approval to
   `ready`.
5. Run `python3 scripts/governance/check-arb-readiness.py --require-production-ready` in the promotion job.
6. Record the ARB decision, approvers, conditions, and expiry of any exception in the audit store.

Passing this gate permits a production deployment review. It does not enable any ActionType; each
capability still follows its own shadow-to-enforce promotion gate.

## Next steps

| To learn about | Read |
|----------------|------|
| Accepted platform decisions | [Architecture Decision Records](decisions/README.md) |
| Data and privacy evidence | [Data Governance](data-governance.md) |
| Deployment inventory | [Deploy and Onboard](../deployment/deploy-and-onboard.md) |
| Operational handoff | [Operational Readiness](../operations/operational-readiness.md) |
| Machine-readable readiness state | [`config/architecture-review.yaml`](../../../config/architecture-review.yaml) |
