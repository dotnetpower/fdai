---
title: ADR-0001 Azure Day-Zero Platform Baseline
translation_of: 0001-azure-day-zero-platform.md
translation_source_sha: daec66d874ad31cd658d3b8b1951ee52ecabcaa3
translation_revised: 2026-08-11
---
# ADR-0001: Azure Day-Zero Platform 기준선

이 기록은 첫 FDAI 배포가 사용하는 coherent Azure 서비스 기준선을 설정합니다.
PostgreSQL, 이벤트 버스, 배포 항목 지점, 런타임, observability를 권고 또는 열림
choice로 설명하던 이전 lightweight 결정을 종료합니다.

## 상태

**Accepted:** 2026-07-13.

> **구현 업데이트 (2026-07-21):** 초기 single-app 기준선은 코어, Operator API,
> 인제스트 게이트웨이를 위한 별도 Container App과 범위가 제한된 Container Apps 작업으로
> 가산하게 확장되었습니다. 아래 wire, 신원, 상태, 시크릿, observability,
> Terraform 결정은 계속 유효합니다. 현재 런타임 토폴로지의 권한은
> [배포](../../deployment/deployment-ko.md)와
> [Deploy and Onboard](../../deployment/deploy-and-onboard-ko.md)입니다.

## 맥락

FDAI에는 코어의 cloud-provider-neutral 계약을 유지하면서 idle 비용이 낮은 Azure
배포가 필요합니다. Ordered replayable 이벤트, transactional 감사/상태, vector reuse,
시크릿 injection, 수명이 짧은 신원, correlated telemetry, scale-to-zero, Terraform 검토를
지원해야 합니다.

## 결정

Azure day-zero 기준선은 다음과 같습니다.

- **런타임:** Subsystem sidecar가 포함된 Azure Container App 하나와 Container Apps 작업.
- **Event 버스:** `:9093` Kafka 엔드포인트로만 소비하는 Event Hubs Standard.
- **상태와 vector:** pgvector를 포함한 PostgreSQL Flexible Server.
- **시크릿:** Container Apps가 주입하는 Key Vault 참조. 애플리케이션 코드는 환경
 값을 읽고 시크릿 SDK를 호출하지 않습니다.
- **신원:** `WorkloadIdentity` 계약 뒤의 user-assigned managed 신원.
- **Observability:** OpenTelemetry를 Log Analytics로 보내고 Application Insights를 workspace에
 연결합니다.
- **배포:** `infra/`의 Terraform. 같은 signed 다이제스트를 환경 간 승격합니다.
- **Console:** 실행기 신원이 없는 읽기 전용 static SPA.

이 선택은 initial Azure 구현을 정의합니다. 프로바이더 계약을 제거하거나
비-Azure 구현을 승인하지 않습니다.

## 검토한 대안

| 관심사 | 대안 | Day zero에서 선택하지 않은 이유 |
|--------|------|-------------------------------|
| 런타임 | AKS | Node-level 컨트롤이 필요하기 전에 standing 비용과 운영 부담이 큽니다. |
| Event 버스 | Service Bus + Event Grid | 정렬/재생 portability를 위해 선택한 단일 Kafka wire 계약을 제공하지 않습니다. |
| 상태 | Cosmos DB | Initial 규모에는 RU와 geo-distribution이 필요하지 않고 pgvector co-location이 단순합니다. |
| Vector 검색 | Dedicated vector 데이터베이스 | 측정된 말뭉치/지연 시간 요구 전에 독립 저장소를 추가합니다. |
| IaC | Bicep 또는 권한로서 `azd up` | Terraform이 검토된 모듈과 프로바이더 중립적인 모듈 경계를 이미 정의합니다. |
| Telemetry | 자체 호스팅 LGTM | 최소 배포에 always-on operations 표면을 추가합니다. |

## Consequence

### 긍정

- Event 프로토콜 하나와 기본 데이터 저장소 하나로 day-zero 운영 복잡도를 낮춥니다.
- Scale-to-zero가 idle compute를 제한하고 프로바이더 경계는 교체 옵션을 유지합니다.
- PostgreSQL 트랜잭션이 상태, 감사 변환 결과, T1 vector를 함께 유지합니다.
- Terraform 계획을 검토 가능한 배포 산출물로 사용합니다.

### 비용과 제약

- Event Hubs Standard와 PostgreSQL에는 fixed idle 하한이 있습니다.
- 측정 프로파일이 분리를 정당화할 때까지 sidecar는 규모/재시작 단위를 공유합니다.
- Initial PostgreSQL 토폴로지는 hyperscale 또는 sovereign 설계가 아닙니다.
- 운영에는 비공개/allow-listed data-flow 검증, 승인 RPO/RTO, signed 산출물,
 소유자 연결, operational 근거가 필요합니다. 이 ADR은 go-live 승인이 아닙니다.

## 이행과 replacement

측정 트리거에 따라 sidecar를 별도 Container App으로 이동하거나 PostgreSQL을 업그레이드하고,
vector를 분리하거나 cell 아키텍처를 채택할 수 있습니다. Replacement는 새 ADR을 기록하고
shared 프로바이더 계약을 유지하며 expand/계약 또는 parallel-run 이행과 롤백
근거를 포함합니다.

## 근거

- [Technology Stack](../tech-stack-ko.md)
- [Deploy and Onboard](../../deployment/deploy-and-onboard-ko.md)
- [배포](../../deployment/deployment-ko.md)
- [`infra/`](../../../../infra/README.md)
- [Hyperscale Cell 아키텍처](../hyperscale-cell-architecture-ko.md)

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| ARB 승인 경계 | [아키텍처 검토 Board 패킷](../architecture-review-board-ko.md) |
| 운영 근거 계약 | [`config/architecture-review.yaml`](../../../../config/architecture-review.yaml) |
| ADR 프로세스 | [아키텍처 결정 기록](README-ko.md) |
