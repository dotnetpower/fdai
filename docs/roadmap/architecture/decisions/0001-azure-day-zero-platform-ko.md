---
title: ADR-0001 Azure Day-Zero Platform Baseline
translation_of: 0001-azure-day-zero-platform.md
translation_source_sha: ca2fd67e2a4b52b96b3a027c4cbe1bfd8f92cfc4
translation_revised: 2026-07-13
---
# ADR-0001: Azure Day-Zero Platform Baseline

이 record는 첫 FDAI deployment가 사용하는 coherent Azure service baseline을 설정합니다.
PostgreSQL, event bus, deployment entry point, runtime, observability를 recommendation 또는 open
choice로 설명하던 이전 lightweight decision을 종료합니다.

## 상태

**Accepted:** 2026-07-13.

## Context

FDAI에는 core의 cloud-provider-neutral contract를 유지하면서 idle cost가 낮은 Azure
deployment가 필요합니다. Ordered replayable event, transactional audit/state, vector reuse,
secret injection, short-lived identity, correlated telemetry, scale-to-zero, Terraform review를
지원해야 합니다.

## Decision

Azure day-zero baseline은 다음과 같습니다.

- **Runtime:** Subsystem sidecar가 포함된 Azure Container App 하나와 Container Apps Job.
- **Event bus:** `:9093` Kafka endpoint로만 소비하는 Event Hubs Standard.
- **State와 vector:** pgvector를 포함한 PostgreSQL Flexible Server.
- **Secret:** Container Apps가 주입하는 Key Vault reference. Application code는 environment
  value를 읽고 secret SDK를 호출하지 않습니다.
- **Identity:** `WorkloadIdentity` contract 뒤의 user-assigned managed identity.
- **Observability:** OpenTelemetry를 Log Analytics로 보내고 Application Insights를 workspace에
  binding합니다.
- **Deployment:** `infra/`의 Terraform. 같은 signed digest를 환경 간 promotion합니다.
- **Console:** Executor identity가 없는 read-only static SPA.

이 선택은 initial Azure implementation을 정의합니다. Provider contract를 제거하거나
비-Azure implementation을 승인하지 않습니다.

## 검토한 대안

| 관심사 | 대안 | Day zero에서 선택하지 않은 이유 |
|--------|------|-------------------------------|
| Runtime | AKS | Node-level control이 필요하기 전에 standing cost와 운영 부담이 큽니다. |
| Event bus | Service Bus + Event Grid | Ordering/replay portability를 위해 선택한 단일 Kafka wire contract를 제공하지 않습니다. |
| State | Cosmos DB | Initial scale에는 RU와 geo-distribution이 필요하지 않고 pgvector co-location이 단순합니다. |
| Vector search | Dedicated vector database | 측정된 corpus/latency 요구 전에 독립 store를 추가합니다. |
| IaC | Bicep 또는 authority로서 `azd up` | Terraform이 reviewed module과 provider-neutral module boundary를 이미 정의합니다. |
| Telemetry | Self-hosted LGTM | Minimum deployment에 always-on operations surface를 추가합니다. |

## Consequence

### Positive

- Event protocol 하나와 primary data store 하나로 day-zero 운영 복잡도를 낮춥니다.
- Scale-to-zero가 idle compute를 제한하고 provider seam은 교체 option을 유지합니다.
- PostgreSQL transaction이 state, audit projection, T1 vector를 함께 유지합니다.
- Terraform plan을 review 가능한 deployment artifact로 사용합니다.

### 비용과 constraint

- Event Hubs Standard와 PostgreSQL에는 fixed idle floor가 있습니다.
- 측정 profile이 분리를 정당화할 때까지 sidecar는 scale/restart unit을 공유합니다.
- Initial PostgreSQL topology는 hyperscale 또는 sovereign 설계가 아닙니다.
- Production에는 private/allow-listed data-flow validation, 승인 RPO/RTO, signed artifact,
  owner binding, operational evidence가 필요합니다. 이 ADR은 go-live 승인이 아닙니다.

## Migration과 replacement

측정 trigger에 따라 sidecar를 별도 Container App으로 이동하거나 PostgreSQL을 upgrade하고,
vector를 분리하거나 cell architecture를 채택할 수 있습니다. Replacement는 새 ADR을 기록하고
shared provider contract를 유지하며 expand/contract 또는 parallel-run migration과 rollback
evidence를 포함합니다.

## Evidence

- [Technology Stack](../tech-stack-ko.md)
- [Deploy and Onboard](../../deployment/deploy-and-onboard-ko.md)
- [Deployment](../../deployment/deployment-ko.md)
- [`infra/`](../../../../infra/README.md)
- [Hyperscale Cell Architecture](../hyperscale-cell-architecture-ko.md)

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| ARB 승인 경계 | [Architecture Review Board 패킷](../architecture-review-board-ko.md) |
| Production evidence contract | [`config/architecture-review.yaml`](../../../../config/architecture-review.yaml) |
| ADR process | [Architecture Decision Record](README-ko.md) |
