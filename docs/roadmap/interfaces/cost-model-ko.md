---
title: 비용 모델 (예시)
translation_of: cost-model.md
translation_source_sha: 074a272486578f11e831c27c4f5fb8ec8c8a9973
translation_revised: 2026-07-21
---

# 비용 모델 (예시)

[deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 에
정의된 최소 Azure 리소스 인벤토리의 월간 예상 비용을, 고정 vs 변동 지출과 트래픽 시나리오로
분해합니다. 비용 효율 원칙은
[deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#cost-efficiency-principles) 에서 옵니다.

> **과거 계획 예시 - 배포 견적 아님.** 아래 가격 band는 초기 최소 세트의 planning snapshot이며
> 현재 Terraform plan의 합계가 아닙니다. Azure 리스트 가격은 리전, 시간, 구독 계약(EA / CSP / MCAPS /
> Reserved Instances / Savings Plans)에 따라 바뀝니다. 이 문서의 모든 숫자는 **근사값**
> 이며 어떤 커밋 전에도
> [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) 에 대해
> 재확인되어야 합니다. 여기의 어느 것도 보장이 아닙니다. 수치는 문서 작성 시점의 리스트
> 가격을 반영합니다; 포크의 비용 대시보드에 `pricing.confirmed_at` 필드가 마지막 검증
> 시점을 기록해야 합니다.

## 가정(Assumptions)

- **리전**: 크기 자릿수 수치는 Korea Central 상당 단일 Azure 리전; 리전 차이 ±20% 는 정상.
- **통화**: USD 리스트 가격, PAYG(Pay-As-You-Go) 티어. 엔터프라이즈 계약은 보통 5-20%
  감소; Reserved Instances / Savings Plans는 1년/3년 약정으로 컴퓨트 + 데이터베이스 지출을
  30-60% 감소시킬 수 있음.
- **트래픽 (베이스라인)**: **낮은 트래픽** - 월 수천에서 수만 이벤트. 현재 core Container App은
  Event Hubs lag scaler가 없으므로 `min_replicas = 1`입니다. Scheduled job만 실행 사이에 0으로
  내려갑니다.
- **보존**: Log Analytics 기본 30일
  ([deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set)).
- **무료 티어**: Container Apps 월간 컴퓨트와 Log Analytics 첫 GB ingestion 무료 부여가 관련
  없는 워크로드에 소비되지 **않는다고** 가정.
- **모델 비용 (T1/T2 추론)**: `enable_llm=true`일 때 Azure OpenAI/Foundry deployment의
  token 또는 provisioned-capacity 비용이 추가되며 [T2 LLM Cost](#t2-llm-cost) 에 별도 보고합니다.
  모델 지출은 [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 의 모델 예산 상한에 의해
  bounded; overflow는 uncapped inference가 아니라 HIL로 강등.
- **비-Azure 대상**: 현재 구현 대상은 Azure이며 다른 CSP 비용은 이 문서에서 모델링하지 않습니다.

이후 모든 수치는 이 가정들의 대상입니다.

## 비용 카테고리

비용은 두 카테고리로 분할됩니다; 절대값이 움직여도 각 리소스의 지출 형상은 안정적:

- **Fixed** - 시스템이 유휴여도 발생(관리 서비스 기본 요금, 상주 저장소).
- **Variable** - 트래픽에 비례(컴퓨트-초, ingestion GB, 딜리버리 작업).

## 리소스별 추정

모든 행은
[deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 의
리소스를 인용합니다. 범위는 베이스라인 트래픽 하에 예상되는 월간 밴드; 상한은 다소 바쁜 달을
반영합니다.

| # | 리소스 | 비용 모델 | 베이스라인 월간 (USD) | 카테고리 | 노트 |
|---|--------|----------|---------------------|----------|------|
| 1 | Container Apps environment | environment fee = $0; vCPU-초 + GB-초 소비 | **현재 plan으로 재산정** | variable | Core replica floor와 opt-in app 수에 따라 달라짐 |
| 2 | Container App (통합 코어, 단일 Python process) | #1에 포함 | #1에 포함 | variable | 기본 `min_replicas = 1`, `max_replicas = 3`; 검증된 lag scaler가 있을 때만 0 허용 |
| 3 | Container Apps Jobs | #1에 포함 | **현재 plan으로 재산정** | variable | Scheduler, out-of-band, inventory, canary 및 활성화된 worker/job이 Consumption 사용량 공유 |
| 4 | Event Hubs **Standard** 네임스페이스 (1 TU, auto-inflate off) | 처리량 단위 시간당 (~$0.03/시 × 730시) + 인그레스 이벤트 (~$0.028/백만) | **≈ $22** | fixed | `:9093` 의 Kafka 와이어 이벤트 버스로 소비; DLQ는 Kafka `<topic>.dlq` 규약, 추가 리소스 없음 |
| 5 | Event Grid inventory subscription + Diagnostic Settings | Event Grid delivery operation + 목적지 서비스 사용량 | **현재 plan으로 재산정** | variable | 별도 custom topic은 없고 inventory event는 Event Hubs로, 진단은 Log Analytics로 전달 |
| 6 | PostgreSQL Flexible **Burstable B1ms** (1 vCore, 2 GB) | 컴퓨트 + 저장소 + 백업 | **≈ $20 - $25** | fixed | 컴퓨트 ≈$15, 32 GB SSD ≈$4, 7일 백업 ≈$3-5 |
| 7 | Key Vault Standard | 10k 작업당 ~$0.03 | **≈ $1** | variable (bounded) | 베이스라인에서 낮음 |
| 8 | User-assigned Managed Identity | 무료 | **$0** | - | |
| 9 | Log Analytics workspace | ingestion ~$2.30/GB (Analytics 로그); 30일 이내 보존 무료 | **$5 - $15** | variable | ingestion 볼륨이 주 드라이버 |
| 10 | Azure Container Registry (Basic) | 고정 일 요금(~$0.167) + 10 GB 저장소 포함 | **≈ $5** | fixed | 후에 geo-replication이나 더 많은 저장소 필요 시 Standard ≈$20 |

배포에 포함된 비-과금 요소
([deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 참조):

- Azure Bot Free tier는 downstream에서 Teams channel을 선택할 때 별도 제공하며 upstream
  Terraform 기본 배포에는 포함되지 않습니다.
- Static Web Apps Free tier (읽기 전용 콘솔 호스팅).
- App registration + workload identity federation.
- Diagnostic Settings 포워더 자체 (비용은 Event Hubs 행에 있음).

## 월간 Envelope (초기 planning snapshot, 모델 비용 제외)

위 카테고리를 베이스라인 가정 하에 결합:

| 버킷 | 내용 | 월간 (USD) |
|------|------|-----------|
| **Fixed** | Event Hubs + PostgreSQL + ACR | **≈ $47 - $52** |
| **Variable** | 초기 scale-to-zero 가정의 Container Apps/Jobs + Key Vault + Log Analytics | **≈ $6 - $28** |
| **Total (초기 최소 세트 예시)** | 현재 Terraform topology의 견적이 아님 | **≈ $53 - $80 / 월 (historical)** |

이 합계는 scale-to-zero를 가정한 초기 snapshot이므로 현재 core `min_replicas = 1` 배포의 예산으로
사용하면 안 됩니다. 배포 전 `terraform plan`에서 활성 resource와 SKU를 추출하고 Azure Pricing
Calculator 또는 Retail Prices API로 다시 합산합니다. Production HA PostgreSQL, private networking,
Azure OpenAI, document ingestion, read API/console, email channel은 각각 별도 line item입니다.

### 현재 Terraform inventory reconciliation

| 범위 | 현재 리소스 | 견적 처리 |
|------|------------|-----------|
| 기본 | Container Apps environment, core replica 1개, scheduled jobs, Event Hubs, Event Grid inventory subscription, PostgreSQL, Key Vault, identities, Log Analytics/Application Insights, ACR, canary | 모든 활성 SKU와 replica/resource usage를 plan에서 다시 계산 |
| Production delta | zone-redundant PostgreSQL HA, 35일 geo backup, private networking/DNS 및 private runner 경로 | dev B1ms band에 포함하지 않고 별도 계산 |
| `enable_llm` | Azure OpenAI/Foundry account와 capability deployment | token/PTU 및 embedding usage를 모델 budget에 합산 |
| `enable_document_ingestion` | ADLS Gen2 ZRS/HNS, blob/dfs private endpoint, ingestion app + ClamAV, migration worker | storage capacity/operations, endpoint, always-on replica를 별도 계산 |
| Channel/console opt-in | read API/channel app, Static Web Apps, ACS Email/SMS 등 활성 adapter | 실제 enablement와 전송량 기준으로 별도 계산 |

## T2 LLM 비용

Reasoning-tier (T2) 추론은 고정 인프라 합계와 분리하는 **usage 또는 provisioned-capacity 비용**입니다.
현재 구현은 opt-in Azure OpenAI/Foundry deployment를 지원하며 [llm-strategy-ko.md](../architecture/llm-strategy-ko.md)가
그 모델 선택과 budget gate를 관장합니다. 별도 보고 이유:

- 모델 패밀리와 mixed-model 교차 검사 요건에 따라 자릿수로 변동
  ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 에
  따라 각 T2 판단은 최소 2개 별개 모델 호출).
- 설정으로 예산 상한 부여; overflow는 **HIL로 강등**, 절대 uncapped inference 아님.

이벤트 볼륨에 키를 맞춘 대략 envelope, 이벤트의 ~10%가 T2에 도달, 각 T2 판단이 2개 별개 모델을
호출, 평균 프롬프트가 ~3 k input + ~500 output 토큰에 맞는다고 가정:

| 월간 이벤트 | T2 판단 (10%) | Small-model 티어 | Mid-model 티어 | Frontier 티어 |
|-------------|--------------|-----------------|----------------|--------------|
| 10 k | ~1 k | **$5 - $15** | **$30 - $100** | **$100 - $500** |
| 100 k | ~10 k | **$50 - $150** | **$300 - $1,000** | **$1,000 - $5,000** |

모델 선택과 무관하게 성립하는 규칙:

- **예산 상한이 천장**; 초과해도 더 지출되지 않고 finding을 HIL 큐로 보냄.
- 모델 선택은 **설정**, 코드가 아님 ([llm-strategy-ko.md](../architecture/llm-strategy-ko.md)); 측정된
  비용/품질로 스왑은 안전.
- Provider-side rate limit과 요청당 timeout이 단일 이벤트가 상한을 격리적으로 폭파하지 않도록
  유지.

**Provider 사용량 측정.** 위 수치는 invoice가 아닌 *envelope*입니다. 각 모델 호출에서
provider가 측정한 `usage`(prompt + completion 토큰)를 `MeteringSink`가 캡처합니다.
`LlmCostPanel`은 호환 경로 `GET /kpi/llm-cost`를 유지하지만 operator projection에는 토큰만
노출합니다. workload scope, model, invocation, conversation, 일, 월별로 확인할 수 있습니다.
설정된 가격은 내부 budget gate에 계속 사용할 수 있지만, 리전 및 협상 요율이 다르므로 콘솔은
이를 실제 지출로 표시하지 않습니다 ([operator-console-ko.md § 4.4](operator-console-ko.md#44-cost와-rate-limit) 참조).

## 트래픽 스케일링

이벤트 볼륨이 커지면서 envelope이 어떻게 움직이는지. 하드 SLA가 아니라 인벤토리 재검토
트리거 세트.

| 시나리오 | 예상 인프라 월간 | 압박 받을 첫 항목 | 권장 액션 |
|----------|-----------------|-------------------|-----------|
| **베이스라인 (≤10 k 이벤트/월)** | 현재 plan + 측정 사용량 | core replica floor, standing service | 활성 최소 세트와 budget 검증 |
| **10 k - 100 k 이벤트/월** | plan + telemetry로 재산정 | Log Analytics ingestion, Container Apps 컴퓨트 | 티어 유지; Log Analytics **daily cap** 설정; ingestion 예산 알림 감시 |
| **100 k - 1 M 이벤트/월** | plan + telemetry로 재산정 | Log Analytics ingestion, Container Apps 컴퓨트, PostgreSQL 저장소 | 감사 스트림에 **Basic Logs** 고려, PostgreSQL 저장소 티어 업, core replica/resource sizing 검토 |
| **≥ 1 M 이벤트/월** | 재모델링 | 대부분 행 | 인벤토리 리뷰 재실행; Event Hubs 추가 TU 또는 Dedicated, PostgreSQL General Purpose, 전용 vector store 평가 |

승격 트리거(core replica/resource sizing, PostgreSQL 티어 업, Log Analytics 분리)는
[Open Decisions](#open-decisions) 에 있습니다.

## 최적화 옵션

지출이 envelope 상한에 접근할 때 기회적으로 적용. 각 옵션은 특정 trade-off가 문서화되어
선택이 눈감고 이루어지지 않도록 합니다.

| 옵션 | 절감 | Trade-off |
|------|------|-----------|
| PostgreSQL **Reserved Instance / Savings Plan** (1년 또는 3년) | 컴퓨트 30-55% 감소 | 티어 약정; 다운그레이드는 조기 해지 필요 |
| **Log Analytics daily cap** | 폭주하는 ingestion 월 방지 | 상한 초과 로그는 워크스페이스 정책에 따라 드롭 또는 스로틀 |
| 감사 스트림에 **Basic Logs 티어** | Analytics-티어 ingestion 대비 ~74% 감소 | Basic Logs에 대한 쿼리가 느림/유료 (아카이브 + 가끔 리플레이용으로 그대로 유지) |
| 태그되지 않은 매니페스트에 **ACR retention 정책** | 작은 저장소 절감 | 오래된 디버그 이미지가 정리됨; 서명된 릴리스 digest는 명시적으로 유지 |
| **Replica floor를 workload별로 설정** | Scheduled job은 실행 사이 0; core는 기본 1 | Core를 0으로 내리려면 Event Hubs lag scaler와 wake-up 검증 필요 |
| **MCAPS / Founder Hub / free trial 크레딧** | 초기 몇 달을 완전히 상쇄 | 자격은 시간 제한; 지속적 레버 아님 |
| 콘솔 이미지를 GHCR로 이동 | ACR Basic (~$5/월) 절감 | 레지스트리 혼합 - 포크가 Azure에 밀접 통합되어 있지 않을 때만 가치 (포크는 ACR 선택 - [deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 참조) |

### Warm-capacity 정책 (cold-start vs MTTR)

Scale-to-zero는 eligible job/lane의 목표이지 현재 core 기본값이 아닙니다. 일괄 min-replicas = 0 은 긴급 recovery 의 MTTR 에
cold-start 지연을 떠넘긴다 - SEV1 failover 는 컨테이너 부팅을 기다릴 수 없다.
`core/capacity/warm_pool.py` (`WarmCapacityPolicy`) 가 그 tension 을 결정론적으로
해소한다: cold start 를 흡수할 수 없는 작업 - 설정된 severity 이상(기본 SEV2)의
incident, active event storm(cold start 로 serialize 될 remediation burst), 그리고
off-hours(콘솔에 이미 warm 한 사람이 없어 autonomous recovery 가 유일한 fast path)
- 에만 **warm** lane (min-replicas > 0)을 권고하고, scaler와 wake-up path가 검증된 나머지 lane은 scale-to-zero 에
남긴다. threshold 는 fork-tunable config 이고, 정책은 순수 권고다: deployment layer
가 plan time 에 `min_replicas` floor 를 읽고 runtime 이 action class 별
`warm_required` 를 읽는다. 이는 idle-cost envelope 을 온전히 유지하면서 중요한
곳의 recovery latency 를 보호한다.

## Envelope이 다루지 않는 것

이 문서 밖의 의도적 비용:

- **T1/T2 model usage 또는 provisioned capacity** - [T2 LLM Cost](#t2-llm-cost) 에 별도 보고.
- **인간 노동** - 운영자 on-call 시간, HIL 승인자 시간.
- **GitHub / Azure DevOps** - GitOps 호스트는 비-Azure 비용
  ([deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#prerequisites) 의 같은 카테고리 노트).
- **DR / secondary-region 리소스** - 현재 최소 inventory 밖이며 별도 deployment topology와
  plan으로 산정합니다.
- **스케일에서의 네트워크 egress** - 베이스라인에서 무시 가능하다고 가정; 트래픽이
  100 k/월 티어에 도달할 때 재검토.

## 관련 문서

- [deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md) - 이 문서가 추정하는 인벤토리.
- [tech-stack-ko.md](../architecture/tech-stack-ko.md) - 서비스 선택 근거.
- [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) - T2 모델 선택, 예산 상한.
- [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) - 모든 cost-per-unit 주장을 관장하는
  measurement-first 규칙.

## Open Decisions

- [ ] 최소 세트 내 구체적인 티어 값(PostgreSQL 저장소, Log Analytics daily cap, ACR retention
      윈도우, Event Hubs 처리량-단위 상한).
- [ ] 승격 트리거: 각 비용 행이 재티어링될 **숫자 임계값** (PostgreSQL step-up을 트리거하는
      이벤트/월 비율, Basic Logs 분리, core replica/resource resizing).
- [ ] T2 모델 티어 선택(small / mid / frontier)과 테넌트당 월간 예산 상한.
- [ ] 포크의 비용 대시보드에 `pricing.confirmed_at` 메커니즘 - 이 문서의 숫자를 Azure Pricing
      Calculator에 대해 어떻게 얼마나 자주 재검증하는가.
- [ ] Reserved Instances / Savings Plans를 첫날에 조달할지 첫 30일 라이브 베이스라인 이후에
      조달할지.
