---
title: ADR-0001 Azure Day-Zero Platform Baseline
---
# ADR-0001: Azure Day-Zero Platform Baseline

This record establishes the coherent Azure service baseline used by the first FDAI deployment. It
closes the older lightweight decisions that described PostgreSQL, the event bus, deployment entry
point, runtime, and observability as recommendations or open choices.

## Status

**Accepted:** 2026-07-13.

## Context

FDAI needs a low-idle-cost Azure deployment that preserves cloud-provider-neutral contracts in the
core. It must support ordered replayable events, transactional audit/state, vector reuse, secret
injection, short-lived identity, correlated telemetry, scale-to-zero, and Terraform-based review.

## Decision

The Azure day-zero baseline is:

- **Runtime:** one Azure Container App with subsystem sidecars plus Container Apps Jobs.
- **Event bus:** Event Hubs Standard consumed only through the Kafka endpoint on `:9093`.
- **State and vectors:** PostgreSQL Flexible Server with pgvector.
- **Secrets:** Key Vault references injected by Container Apps; application code reads environment
  values and does not call a secret SDK.
- **Identity:** user-assigned managed identity behind the `WorkloadIdentity` contract.
- **Observability:** OpenTelemetry to Log Analytics with Application Insights bound to the workspace.
- **Deployment:** Terraform under `infra/`; the same signed digest is promoted across environments.
- **Console:** read-only static SPA with no executor identity.

These choices define the initial Azure implementation. They do not remove the provider contracts or
authorize a non-Azure implementation.

## Alternatives considered

| Concern | Alternative | Reason not selected for day zero |
|---------|-------------|----------------------------------|
| Runtime | AKS | higher standing cost and operational burden before node-level control is required |
| Event bus | Service Bus + Event Grid | does not provide the single Kafka wire contract selected for ordering and replay portability |
| State | Cosmos DB | RU and geo-distribution benefits are not required at initial scale; pgvector co-location is simpler |
| Vector search | dedicated vector database | adds an independent store before measured corpus or latency requires it |
| IaC | Bicep or `azd up` as authority | Terraform already defines the reviewed modules and provider-neutral module boundary |
| Telemetry | self-hosted LGTM | adds an always-on operations surface to the minimum deployment |

## Consequences

### Positive

- One event protocol and one primary data store reduce day-zero operational complexity.
- Scale-to-zero limits idle compute while the provider seams preserve later replacement options.
- PostgreSQL transactions keep state, audit projection, and T1 vectors close together.
- Terraform plans provide a reviewable deployment artifact.

### Costs and constraints

- Event Hubs Standard and PostgreSQL have a fixed idle floor.
- Sidecars share a scale and restart unit until measured profiles justify separation.
- The initial PostgreSQL topology is not a hyperscale or sovereign design.
- Production still requires private/allow-listed data-flow validation, approved RPO/RTO, signed
  artifacts, owner bindings, and operational evidence. This ADR is not a go-live approval.

## Migration and replacement

Measured triggers may move a sidecar to its own Container App, upgrade PostgreSQL, split vectors,
or adopt the cell architecture. A replacement records a new ADR, preserves the shared provider
contract, uses an expand/contract or parallel-run migration, and includes rollback evidence.

## Evidence

- [Technology Stack](../tech-stack.md)
- [Deploy and Onboard](../../deployment/deploy-and-onboard.md)
- [Deployment](../../deployment/deployment.md)
- [`infra/`](../../../../infra/README.md)
- [Hyperscale Cell Architecture](../hyperscale-cell-architecture.md)

## Next steps

| To learn about | Read |
|----------------|------|
| ARB approval boundary | [Architecture Review Board Packet](../architecture-review-board.md) |
| Production evidence contract | [`config/architecture-review.yaml`](../../../../config/architecture-review.yaml) |
| ADR process | [Architecture Decision Records](README.md) |
