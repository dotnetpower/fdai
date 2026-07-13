---
title: Architecture Decision Records
---
# Architecture Decision Records

Architecture decision records (ADRs) capture choices that change FDAI's system boundaries,
contracts, deployment topology, or long-lived operational obligations. The register makes the
decision, alternatives, consequences, status, and replacement history reviewable in one place.

> **Scope:** environment values such as a customer's RPO/RTO, retention period, region, budget,
> or named owner are production evidence bindings, not upstream ADRs. A fork may add its own ADRs
> without rewriting the upstream records.

## Register

| ADR | Status | Decision | Supersedes |
|-----|--------|----------|------------|
| [ADR-0001](0001-azure-day-zero-platform.md) | Accepted | Azure day-zero platform baseline | lightweight OD entries in `tech-stack.md` and deployment drafts |

## Status vocabulary

| Status | Meaning |
|--------|---------|
| Proposed | under review; not an implementation authority |
| Accepted | current design authority |
| Deprecated | retained for history but not used for new work |
| Superseded | replaced by the named ADR |
| Rejected | considered and not selected |

## Record contract

Every ADR contains:

1. **Context:** the forces and constraints that require a decision.
2. **Decision:** the selected behavior and its boundary.
3. **Alternatives:** serious options considered and why they were not selected.
4. **Consequences:** positive, negative, operational, security, and migration effects.
5. **Status and date:** lifecycle state, decision date, and replacement relationship.
6. **Evidence:** implementation and validation links when the decision has landed.

One ADR should answer one coherent decision. A platform-baseline ADR may bind several inseparable
service choices when they form one deployment contract; later replacement of one choice receives a
new ADR that explicitly supersedes the affected section.

## Change process

1. Add a proposed ADR and its Korean translation in the same pull request.
2. Link affected design docs and implementation paths.
3. Record security, reliability, cost, and migration consequences.
4. Obtain the architecture-owner approval and any specialist approval required by the change.
5. Mark the ADR accepted only when the implementation plan and rollback path are reviewable.
6. Update this register and the machine-readable ARB manifest when readiness changes.

## Next steps

| To learn about | Read |
|----------------|------|
| Current ARB decision | [Architecture Review Board Packet](../architecture-review-board.md) |
| Azure day-zero baseline | [ADR-0001](0001-azure-day-zero-platform.md) |
| Technology selection detail | [Technology Stack](../tech-stack.md) |
