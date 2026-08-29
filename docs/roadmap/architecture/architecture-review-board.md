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

FDAI is an agent-driven, headless control plane with a non-privileged console and GitOps/ChatOps
delivery. Fifteen fixed agents own sensing, judgment, arbitration, approval, execution, verification,
recovery, audit, and learning through typed pub/sub. The operating ontology is supporting truth and
safety infrastructure; it constrains agent interpretation but never grants authority or acts.

Repeatable events use T0 deterministic rules and T1 verified reuse; only residual ambiguity reaches
T2 grounded reasoning. Every mutation passes the risk gate, carries stop, rollback, impact, audit,
and independent effect-verification contracts, and starts in shadow mode.

FDAI calls this **[Outcome-Driven Token Economics](llm-strategy.md#cost-controls)**:
maximize verified operational value while minimizing model calls, tokens, latency, and cost by using
ontology-grounded T0/T1 paths by default and reserving direct source retrieval, stronger models,
verification, and human approval for residual ambiguity or risk. Accuracy and safety remain hard
constraints.

## Document set

This entry point stays compact while focused owners carry the complete design.

| Document | Owns |
|----------|------|
| [Ontology-Grounded Agent Loop](architecture-review/ontology-agent-loop.md) | Authoritative ontology state, 15-agent responsibilities, evidence fan-out, deterministic join, and autonomous review levels |
| [Evidence and Authority](architecture-review/evidence-and-authority.md) | Evidence lanes, owner bindings, risks, exceptions, approval integrity, decision receipts, and production exit |
| [Delivery Plan](architecture-review/delivery-plan.md) | Five dependency-ordered work packages, first vertical slice, and validation matrix |
| [Implementation ledger](../../roadmap-implementation/architecture/architecture-review-board.md) | Current implementation scope, append-only history, and remaining work for this entry point |

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

## Review and evidence model

The [ontology-agent loop](architecture-review/ontology-agent-loop.md) assigns every transition to
an accountable member of the fixed pantheon and derives review state from `Change`, context,
evidence, `DecisionCase`, approval, and outcome records. The
[evidence and authority contract](architecture-review/evidence-and-authority.md) defines the
production evidence profile, owner slots, risk and exception records, immutable decision receipt,
failure behavior, and production exit procedure.

The current reusable implementation carries exact verified-snapshot planned-change graph evidence,
rejects accepted critical or high blockers without a complete current risk or exception record, and
requires provider-backed body attestation before production readiness. Immutable final decision
receipts now bind exact evidence and independently recorded approvals without execution authority.
Receipt-derived readiness and the complete observation-mode agent loop remain open.

`ReviewCase` and `ReviewCheck` are read models. They summarize authoritative lineage for the
Process and Console, but they do not grant judgment, approval, or execution authority.

## Decisions

The ADR index is [Architecture Decision Records](decisions/README.md). ADR-0001 records the
accepted Azure day-zero platform baseline. Open environment decisions such as numeric RPO/RTO,
retention, cost caps, and production owners are fork bindings, not hidden architecture defaults.

## Runtime status and manual review

The published workflow app is available at `/workflow-apps/architecture-review`. Its selected
Process view renders at `/processes/{process_id}` from the declarative view and report catalogs. A
valid manifest with missing production evidence remains structurally healthy while the production
gate stays blocked. The Process projection keeps workflow state, review checks, owner and evidence
bindings, approvals, and decisions in typed ontology objects.

Contributor can submit a revision-bound observation-mode review through `POST /workflows/run`. The
Operator API currently rejects `mode=enforce`; the authority-bearing workflow path and its
local/deployed operational evidence remain open. ARB stays control-only: a future governed decision
may persist approval and decision transitions, but any resource change still re-enters the normal
ActionType, policy, risk, approval, execution, verification, and recovery path.

## Next steps

| To learn about | Read |
|----------------|------|
| Accepted platform decisions | [Architecture Decision Records](decisions/README.md) |
| Ontology and 15-agent review loop | [Ontology-Grounded Agent Loop](architecture-review/ontology-agent-loop.md) |
| Evidence, ownership, approval, and production exit | [Evidence and Authority](architecture-review/evidence-and-authority.md) |
| Dependency-ordered implementation | [Delivery Plan](architecture-review/delivery-plan.md) |
| Data and privacy evidence | [Data Governance](data-governance.md) |
| Deployment inventory | [Deploy and Onboard](../deployment/deploy-and-onboard.md) |
| Operational handoff | [Operational Readiness](../operations/operational-readiness.md) |
| Machine-readable readiness state | [`config/architecture-review.yaml`](../../../config/architecture-review.yaml) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/architecture/architecture-review-board.md) |
