---
title: Data Governance and Privacy Evidence
---
# Data Governance and Privacy Evidence

This document defines the data classification, minimization, lifecycle, residency, and privacy
evidence contract for FDAI. It supplies the reusable control model; each production fork records
its approved values and evidence without committing customer data upstream.

> **Scope:** this is not a certification or a completed privacy impact assessment. Production
> approval remains blocked until a fork binds a privacy owner, a data owner, its retention values,
> its model-provider terms, and an approved assessment in `config/architecture-review.yaml`.

## Design at a glance

FDAI stores identifiers and derived operational facts instead of raw customer payloads whenever
possible. Machine and audit records remain English, access is role-scoped, encryption is required
in transit and at rest, and model-bound content is redacted before it leaves the trust boundary.

## Data inventory

| Data class | Examples | Default handling | System of record |
|------------|----------|------------------|------------------|
| Event metadata | event id, resource type, correlation id, normalized properties | minimize; reject secrets at ingress | event bus, then audit/state store |
| Tool and inventory output | resource graph facts, policy results, deployment-plan facts | retain only fields needed for a decision and evidence | state store or short-lived processing buffer |
| Audit records | decision, actor id, tier, rule citations, idempotency and rollback references | append-only, tamper-evident, legal-hold capable | audit ledger |
| Telemetry | logs, metrics, traces, health and performance measurements | sample or aggregate telemetry; never sample required audit entries | Log Analytics or configured telemetry backend |
| Embeddings and patterns | vectors derived from resolved incidents and approved knowledge | version model and source; avoid embedding secrets or raw personal data | PostgreSQL + pgvector |
| Operator conversation | question, verified tool calls, grounded answer, proposal references | separate presentation text from machine decisions; apply approved session retention | operator-memory store |
| Governance artifacts | rules, assignments, exemptions, overrides, ADRs | versioned and reviewed as code | Git |

## Classification and access

A fork maps each class to its organization taxonomy, such as public, internal, confidential, or
restricted. It records the data owner, allowed principals, approved regions, encryption profile,
and downstream processors. Missing classification is treated as the most restrictive configured
class and blocks export to a model provider.

Access follows these rules:

- **Minimum permissions:** the console reads projections and never holds the executor identity.
- **Purpose limitation:** a provider receives only fields required for its declared operation.
- **No secret propagation:** secrets are not written to events, logs, audit, prompts, fixtures, or
  evidence attachments.
- **Actor traceability:** human and workload identities use stable object identifiers in audit.
- **Break-glass visibility:** emergency access is time-bounded, alerted, and reviewed.

## Lifecycle and retention

The fork maintains a retention schedule with these fields for every data class:

| Field | Requirement |
|-------|-------------|
| Purpose | operational, security, legal, training, or another approved purpose |
| Active retention | queryable duration in the primary store |
| Archive retention | duration, archive tier, and restore expectation |
| Legal hold | authority, hold marker, release process, and immutable evidence |
| Deletion | trigger, method, verification, and downstream propagation |
| Backup inheritance | whether deletion waits for backup expiry or uses approved key destruction |
| Review cadence | owner and next review date |

The Azure day-zero telemetry default is 30 days. Audit, conversation, embedding, and customer
record retention do not inherit that value automatically. Their values must be approved in the
fork and attached to the production evidence binding.

## Privacy assessment

The privacy impact assessment records:

1. data subjects and personal or customer-identifying fields that may enter the system;
2. purpose, lawful basis, necessity, proportionality, and minimization controls;
3. data flow across event, state, telemetry, Git, ChatOps, and model-provider boundaries;
4. region and cross-border transfer constraints;
5. processor terms, retention, training-use restrictions, and incident-notification terms;
6. access, correction, export, deletion, and legal-hold handling where applicable;
7. residual privacy risks, mitigating controls, approver, and review date.

If a payload cannot be redacted enough for the selected model-provider terms, FDAI holds the case
for human review and does not transmit it.

## Model and embedding controls

- Record provider, publisher, model family/version, deployment region, retention terms, and whether
  provider training on submitted data is disabled.
- Apply secret and personal-data redaction before model or embedding calls.
- Keep prompt/tool input separate from the deterministic verdict and audit authority.
- Version embeddings with source provenance, classification, model, and deletion lineage.
- Rebuild or delete derived vectors when the approved source is removed and no legal hold applies.

## Compliance evidence

The upstream catalog may cite controls from MCSB, CIS, or other standards, but those citations do
not establish certification. A production fork creates a crosswalk with control id, implementation,
automated evidence, manual evidence, owner, frequency, exceptions, and residual risk. Unsupported
or not-applicable controls remain explicit; they are not silently omitted.

## Production gate

Production data/privacy readiness requires:

- approved data inventory and classification mapping;
- privacy and data owner bindings;
- approved retention, legal-hold, deletion, and backup behavior;
- data-flow and residency validation;
- model-provider and subprocessors review;
- completed privacy impact assessment;
- compliance crosswalk for the selected customer profile;
- tested access review, deletion, and incident-response evidence.

These artifacts are customer records and stay in the fork or its governed evidence store. The
upstream manifest records only the required evidence keys and generic blocker state.

## Next steps

| To learn about | Read |
|----------------|------|
| ARB decision and evidence binding | [Architecture Review Board Packet](architecture-review-board.md) |
| Security and threat model | [Security and Identity](security-and-identity.md) |
| Human authorization | [User RBAC and Entra Identity](../interfaces/user-rbac-and-identity.md) |
| Audit and telemetry scale | [Hyperscale Cell Architecture](hyperscale-cell-architecture.md) |
