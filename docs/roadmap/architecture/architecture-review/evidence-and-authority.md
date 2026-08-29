---
title: ARB Evidence and Authority
---
# ARB Evidence and Authority

This design defines the evidence, ownership, risk, approval, and decision-receipt contract for an
architecture review. It separates machine readiness from authority to promote or execute a change.

> **Scope:** This document owns evidence and authority. The
> [ontology-agent loop](ontology-agent-loop.md) owns evaluation behavior, and the
> [delivery plan](delivery-plan.md) owns implementation sequence.
>
> **Customer boundary:** Upstream defines generic evidence keys and validation contracts. A fork
> supplies environment values, accountable identities, objectives, and governed evidence.

## Design at a glance

An evidence reference is accepted only when an authoritative provider binds its exact body,
revision, scope, time, and digest. A complete evidence set can establish machine readiness, but it
cannot grant approval or execution authority. A final decision separately binds the evaluated case,
conditions, authority basis, and approval receipts.

## Evidence lanes

`OperationalEvidenceBundle` keeps four evidence lanes separate so one source cannot silently
substitute for another.

| Lane | Contents | Required verification |
|------|----------|-----------------------|
| Ontology | Secured objects, typed paths, graph revision, topology completeness | Purpose, release, cutoff, membership, link verification, freshness |
| State | Observed, derived, desired, and execution state facts | Source identity, effective time, completeness, conflicts, synthetic status |
| Catalog | Exact Rules, Policies, constraints, ActionTypes, and workflow versions | Catalog release, version, content digest, promotion state |
| Document | Governed excerpts and external reports | Source revision, excerpt digest, classification, retention, no instruction authority |

Missing, stale, conflicting, synthetic, after-cutoff, target-mismatched, or truncated evidence
cannot preserve automatic authority. Healthy evidence may satisfy a check, but it never raises the
authority ceiling above the caller's policy and approval limits.

## Production evidence contract

Deployment-dependent targets are not universal upstream constants. A deployment records the
approved value, measurement method, result, timestamp, approver, and immutable evidence digest.

| Area | Required production evidence | Pass condition |
|------|------------------------------|----------------|
| Availability | Control-plane SLO and error budget | Approved objective plus measured staging result |
| Latency | p50/p95/p99 by tier and end-to-end canary | Within the fork-approved budget |
| Capacity and performance | Sustained and burst rate, lag, saturation, quota headroom | No loss, bounded lag, documented saturation point |
| Reliability | Service-specific RPO/RTO and business-impact analysis | Approved numeric objectives |
| Recovery | Isolated restore, fencing, event recovery, failover, and failback drill | Integrity and smoke pass; objectives met |
| Security | Threat review, network data flow, identity, and minimum-permission probes | No unresolved critical or high finding |
| Privacy and data | Privacy impact assessment, inventory, classification, retention, deletion | Privacy and data owners approve the exact scope |
| Operations | Signed readiness report, canary, smoke, alerts, runbooks | All required operational checks pass |
| Supply chain | SBOM, image signature, provenance, vulnerability and IaC scans | Exact release artifact verified; blocking scans clean |
| Cost | Current estimate, monthly cap, quota, and 12/36-month assumptions | Cost owner approves the measured envelope |

The required-evidence profile should cover all five Azure Well-Architected pillars. Reliability and
Operational Excellence controls are already cataloged; Security, Cost Optimization, and
Performance Efficiency need the same machine-checkable depth.

## Ownership bindings

The production gate uses accountable owner slots. A group may fill a slot, but the binding names an
escalation route and a distinct approval authority when separation of duties applies.

| Owner slot | Accountable for |
|------------|-----------------|
| `architecture-owner` | Architecture baseline, ADRs, constraints, and accepted technical debt |
| `security-owner` | Threat model, identity, network posture, security exceptions |
| `privacy-owner` | Privacy impact assessment and data-processing decisions |
| `data-owner` | Classification, retention, legal hold, deletion, data quality |
| `operations-owner` | On-call, alerts, runbooks, operational-readiness acceptance |
| `reliability-owner` | SLO, RPO/RTO, recovery design, drills |
| `release-owner` | Artifact provenance, deployment, rollback, promotion gates |
| `cost-owner` | Budget, quota, price confirmation, capacity graduation |

Blocker ownership must resolve to one of the registered slots. Agent stewardship is a separate
human accountability overlay and does not replace production owners or approval authority.

```yaml
owner_bindings:
  architecture-owner:
    subject: group:<fork-owned-subject>
    escalation: <fork-owned-escalation-route>
```

## Evidence bindings

The manifest carries metadata, not the evidence body. Runtime verification retrieves the governed
body through an injected provider, recomputes its digest, confirms scope and revision, validates the
approver, and applies the shorter of binding expiry and control freshness.

The injected provider returns a bounded body, observation time, authenticated approver set, and
authentication reference. Runtime readiness rejects a missing provider, body or URI mismatch,
scope or revision mismatch, unauthorized approver, stale or future observation, post-observation
approval mismatch, synthetic evidence, and bodies outside the fixed byte ceiling. Structural CLI
validation cannot turn metadata alone into production readiness.

```yaml
evidence_bindings:
  production-terraform-plan:
    uri: evidence://<governed-store-reference>
    sha256: <64-lowercase-hex-digest>
    scope_ref: <fork-owned-scope-reference>
    revision: <immutable-source-revision>
    approved_by: group:<fork-owned-approver>
    approved_at: 2026-07-13T00:00:00Z
    expires_at: 2027-01-13T00:00:00Z
    freshness_seconds: 86400
```

Structural validation rejects unknown keys, missing fields, malformed digests, and invalid time
ranges. Production validation also verifies the external evidence body and authority binding. A
syntactically valid URI or digest alone is not production proof.

## Risk, assumptions, issues, and exceptions

| Type | Required contract |
|------|-------------------|
| Risk | Severity, owner slot, mitigation, residual risk, review date, evidence refs |
| Assumption | Validation method, evidence ref, owner, expiry or falsification condition |
| Issue | Artifact or implementation that closes the gap, owner, observable exit condition |
| Exception | Exact scope, reason, compensating controls, independent approval, effective interval, audit ref |

An accepted risk is not resolved. A critical or high item can leave `open` only when its complete
risk or exception record is independently reviewed and remains current. Expiry, evidence removal,
scope drift, or a violated compensating control reopens the review automatically.

The manifest checker enforces the accepted-risk and accepted-exception record shape plus the review
or effective-time window. Runtime production readiness also requires provider-backed evidence-body
attestation. Live compensating-control validation remains separate production-gate work.

## Decision receipt

A final `Decision` is immutable and contains or links to:

- the exact `ReviewCase`, `Change`, `DecisionCase`, and `ImpactEnvelope` identities;
- context, evidence bundle, graph revision, catalog release, and decision digests;
- outcome, rationale, conditions, authority basis, effective interval, and reevaluation trigger;
- requester, judge, arbitrator when used, approvers, quorum, and approval receipt refs;
- audit intent, terminal audit ref, and any resulting governance ActionType proposal.

Changing an evidence item, condition, approval set, target revision, or graph revision produces a
new decision identity. A workflow context value or mutable manifest field cannot amend an existing
receipt.

## Failure behavior

| Dependency | Failure behavior |
|------------|------------------|
| Event bus | Backpressure, retry, dead-letter, and replay; never interpret loss as approval |
| Ontology store | Hold when the exact release, target, graph coverage, or freshness cannot be proven |
| Evidence provider | Record unavailable or failed verification; retain no authority from prior unbound data |
| PostgreSQL state and audit | Fail closed; production does not fall back to process memory |
| Git host | Queue a governance proposal; do not apply an out-of-band catalog change |
| Approval channel | Preserve the queue, use configured fallback, and end timeout as no-op |
| Model provider | Use deterministic paths or hold; model output never supplies authority |
| Observability backend | Hold effect-dependent success and raise a monitor-of-monitor signal |

## Production exit procedure

1. Bind every required owner slot in the customer fork.
2. Attach each required evidence artifact through a verifier-backed provider.
3. Resolve or formally accept every blocker with the complete risk or exception contract.
4. Produce a fresh ontology-grounded `DecisionCase` and impact envelope for the exact release.
5. Record required independent approvals and create the immutable decision receipt.
6. Run `python3 scripts/governance/check-arb-readiness.py --require-production-ready` against that
   receipt-bound state in the promotion job.
7. Verify that the deployment or ActionType promotion remains a separate governed decision.

Passing ARB permits the next production review. It does not deploy resources or enable an
ActionType.

## Related docs

| To learn about | Read |
|----------------|------|
| ARB entry point and decision boundary | [Architecture Review Board Packet](../architecture-review-board.md) |
| Ontology and agent evaluation | [Ontology-Grounded Agent Loop](ontology-agent-loop.md) |
| Dependency-ordered implementation | [Delivery Plan](delivery-plan.md) |
| Data and privacy requirements | [Data Governance](../data-governance.md) |
| Human roles and approval integrity | [User RBAC and Identity](../../interfaces/user-rbac-and-identity.md) |
| Delivery status and remaining work | [Implementation ledger](../../../roadmap-implementation/architecture/architecture-review/evidence-and-authority.md) |
