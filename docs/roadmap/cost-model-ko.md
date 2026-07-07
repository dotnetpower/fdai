---
title: 비용 모델 (예시)
translation_of: cost-model.md
translation_source_sha: 00b4b4d940f3d18bcaebccd4b6933b6f143ed5cf
translation_revised: 2026-07-07
---

# 비용 모델 (예시)

[deploy-and-onboard-ko.md](deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 에
정의된 최소 Azure 리소스 인벤토리의 월간 예상 비용을, 고정 vs 변동 지출과 트래픽 시나리오로
분해합니다. 비용 효율 원칙은
[deploy-and-onboard-ko.md](deploy-and-onboard-ko.md#cost-efficiency-principles) 에서 옵니다.

> **예시 - 견적 아님.** Azure 리스트 가격은 리전, 시간, 구독 계약(EA / CSP / MCAPS /
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
- **트래픽 (베이스라인)**: **낮은 트래픽** - 월 수천에서 수만 이벤트, KEDA가 코어 Container App을
  대부분 시간 0 replica로 유지.
- **보존**: Log Analytics 기본 30일
  ([deploy-and-onboard-ko.md](deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set)).
- **무료 티어**: Container Apps 월간 컴퓨트와 Log Analytics 첫 GB ingestion 무료 부여가 관련
  없는 워크로드에 소비되지 **않는다고** 가정.
- **LLM 비용 (T2 추론)**: **인프라 envelope에서 제외** 되며 [T2 LLM Cost](#t2-llm-cost) 에
  별도 보고. LLM 지출은 [llm-strategy-ko.md](llm-strategy-ko.md) 의 모델 예산 상한에 의해
  bounded; overflow는 uncapped inference가 아니라 HIL로 강등.
- **비-Azure 대상**:
  [Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must) 에
  따라 TBD; 다른 CSP에 대한 비용 추정은 여기에 모델링되어 있지 않음.

이후 모든 수치는 이 가정들의 대상입니다.

## 비용 카테고리

비용은 두 카테고리로 분할됩니다; 절대값이 움직여도 각 리소스의 지출 형상은 안정적:

- **Fixed** - 시스템이 유휴여도 발생(관리 서비스 기본 요금, 상주 저장소).
- **Variable** - 트래픽에 비례(컴퓨트-초, ingestion GB, 딜리버리 작업).

## 리소스별 추정

모든 행은
[deploy-and-onboard-ko.md](deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 의
리소스를 인용합니다. 범위는 베이스라인 트래픽 하에 예상되는 월간 밴드; 상한은 다소 바쁜 달을
반영합니다.

| # | 리소스 | 비용 모델 | 베이스라인 월간 (USD) | 카테고리 | 노트 |
|---|--------|----------|---------------------|----------|------|
| 1 | Container Apps environment | environment fee = $0; vCPU-초 + GB-초 소비 | **$0 - $10** | variable | 무료 월간 부여(≈180k vCPU-s + 360k GB-s)가 종종 낮은 트래픽을 흡수 |
| 2 | Container App (통합 코어, 4 사이드카) | #1에 포함 | #1에 포함 | variable | KEDA scale-to-zero |
| 3 | Container Apps Job (프로브) | #1에 포함 | **$0 - $2** | variable | 짧은 스케줄 실행이 무료 부여 공유 |
| 4 | Event Hubs **Standard** 네임스페이스 (1 TU, auto-inflate off) | 처리량 단위 시간당 (~$0.03/시 × 730시) + 인그레스 이벤트 (~$0.028/백만) | **≈ $22** | fixed | `:9093` 의 Kafka 와이어 이벤트 버스로 소비; DLQ는 Kafka `<topic>.dlq` 규약, 추가 리소스 없음 |
| 5 | Diagnostic Settings 포워더 (Activity Log / 리소스 이벤트) | 무료 배관; 목적지 Event Hubs TU 비용은 4번 행에 있음 | **$0** | - | 이전 인벤토리의 독립 Service Bus + Event Grid 커스텀 토픽 대체 |
| 6 | PostgreSQL Flexible **Burstable B1ms** (1 vCore, 2 GB) | 컴퓨트 + 저장소 + 백업 | **≈ $20 - $25** | fixed | 컴퓨트 ≈$15, 32 GB SSD ≈$4, 7일 백업 ≈$3-5 |
| 7 | Key Vault Standard | 10k 작업당 ~$0.03 | **≈ $1** | variable (bounded) | 베이스라인에서 낮음 |
| 8 | User-assigned Managed Identity | 무료 | **$0** | - | |
| 9 | Log Analytics workspace | ingestion ~$2.30/GB (Analytics 로그); 30일 이내 보존 무료 | **$5 - $15** | variable | ingestion 볼륨이 주 드라이버 |
| 10 | Azure Container Registry (Basic) | 고정 일 요금(~$0.167) + 10 GB 저장소 포함 | **≈ $5** | fixed | 후에 geo-replication이나 더 많은 저장소 필요 시 Standard ≈$20 |

배포에 포함된 비-과금 요소
([deploy-and-onboard-ko.md](deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 참조):

- Azure Bot Free tier (HIL용 Teams Adaptive Cards).
- Static Web Apps Free tier (읽기 전용 콘솔 호스팅).
- App registration + workload identity federation.
- Diagnostic Settings 포워더 자체 (비용은 Event Hubs 행에 있음).

## 월간 Envelope (베이스라인, T2 LLM 제외)

위 카테고리를 베이스라인 가정 하에 결합:

| 버킷 | 내용 | 월간 (USD) |
|------|------|-----------|
| **Fixed** | Event Hubs + PostgreSQL + Key Vault + ACR + Log Analytics 베이스라인 | **≈ $53** |
| **Variable** | Container Apps 컴퓨트 + Log Analytics ingestion 베이스라인 초과 | **$5 - $20** |
| **Total (인프라만)** | | **≈ $45 - $70 / 월** |

대부분 시간 유휴로 유지되는 배포(KEDA 0 replica, ingest 버스트 없음)는 하한에 근접; 꾸준한
이벤트 트래픽과 원격측정을 흡수하는 배포는 중간 정도.

## T2 LLM 비용

Reasoning-tier (T2) 추론은 **Azure 리소스 라인이 아님** - [llm-strategy-ko.md](llm-strategy-ko.md)
가 관장하는 외부 모델 API 지출. 별도 보고 이유:

- 모델 패밀리와 mixed-model 교차 검사 요건에 따라 자릿수로 변동
  ([architecture.instructions.md](../../.github/instructions/architecture.instructions.md) 에
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
- 모델 선택은 **설정**, 코드가 아님 ([llm-strategy-ko.md](llm-strategy-ko.md)); 측정된
  비용/품질로 스왑은 안전.
- Provider-side rate limit과 요청당 timeout이 단일 이벤트가 상한을 격리적으로 폭파하지 않도록
  유지.

## 트래픽 스케일링

이벤트 볼륨이 커지면서 envelope이 어떻게 움직이는지. 하드 SLA가 아니라 인벤토리 재검토
트리거 세트.

| 시나리오 | 예상 인프라 월간 | 압박 받을 첫 항목 | 권장 액션 |
|----------|-----------------|-------------------|-----------|
| **베이스라인 (≤10 k 이벤트/월)** | $45 - $70 | (없음) | 최소 세트 유지 |
| **10 k - 100 k 이벤트/월** | $70 - $150 | Log Analytics ingestion, Container Apps 컴퓨트 | 티어 유지; Log Analytics **daily cap** 설정; ingestion 예산 알림 감시 |
| **100 k - 1 M 이벤트/월** | $200 - $500 | Log Analytics ingestion (지배적), Container Apps 컴퓨트, PostgreSQL 저장소 | 감사 스트림에 **Basic Logs** 고려 (~74% ingestion 절감 vs Analytics), PostgreSQL 저장소 티어 업, 사이드카 → 별도 Container App 승격 검토 |
| **≥ 1 M 이벤트/월** | 재모델링 | 대부분 행 | 인벤토리 리뷰 재실행; Event Hubs 추가 TU 또는 Dedicated, PostgreSQL General Purpose, 전용 vector store 평가 |

승격 트리거(사이드카 → 별도 Container App, PostgreSQL 티어 업, Log Analytics 분리)는
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
| **Container Apps min-replicas = 0 도처에** | 이미 기본값; 유지 | 콜드스타트 지연은 [operating-and-verification-ko.md](operating-and-verification-ko.md#self-health-signals) 로 계산 |
| **MCAPS / Founder Hub / free trial 크레딧** | 초기 몇 달을 완전히 상쇄 | 자격은 시간 제한; 지속적 레버 아님 |
| 콘솔 이미지를 GHCR로 이동 | ACR Basic (~$5/월) 절감 | 레지스트리 혼합 - 포크가 Azure에 밀접 통합되어 있지 않을 때만 가치 (포크는 ACR 선택 - [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 참조) |

## Envelope이 다루지 않는 것

이 문서 밖의 의도적 비용:

- **T2 LLM API 지출** - [T2 LLM Cost](#t2-llm-cost) 에 별도 보고.
- **인간 노동** - 운영자 on-call 시간, HIL 승인자 시간.
- **GitHub / Azure DevOps** - GitOps 호스트는 비-Azure 비용
  ([deploy-and-onboard-ko.md](deploy-and-onboard-ko.md#prerequisites) 의 같은 카테고리 노트).
- **DR / secondary-region 리소스** -
  [Implementation Focus](../../.github/copilot-instructions.md#implementation-focus-must) 에
  따라 Phase 4 (TBD)로 연기.
- **스케일에서의 네트워크 egress** - 베이스라인에서 무시 가능하다고 가정; 트래픽이
  100 k/월 티어에 도달할 때 재검토.

## 관련 문서

- [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md) - 이 문서가 추정하는 인벤토리.
- [tech-stack-ko.md](tech-stack-ko.md) - 서비스 선택 근거.
- [llm-strategy-ko.md](llm-strategy-ko.md) - T2 모델 선택, 예산 상한.
- [goals-and-metrics-ko.md](goals-and-metrics-ko.md) - 모든 cost-per-unit 주장을 관장하는
  measurement-first 규칙.

## Open Decisions

- [ ] 최소 세트 내 구체적인 티어 값(PostgreSQL 저장소, Log Analytics daily cap, ACR retention
      윈도우, Event Hubs 처리량-단위 상한).
- [ ] 승격 트리거: 각 비용 행이 재티어링될 **숫자 임계값** (PostgreSQL step-up을 트리거하는
      이벤트/월 비율, Basic Logs 분리, 사이드카 → 자체 Container App).
- [ ] T2 모델 티어 선택(small / mid / frontier)과 테넌트당 월간 예산 상한.
- [ ] 포크의 비용 대시보드에 `pricing.confirmed_at` 메커니즘 - 이 문서의 숫자를 Azure Pricing
      Calculator에 대해 어떻게 얼마나 자주 재검증하는가.
- [ ] Reserved Instances / Savings Plans를 첫날에 조달할지 첫 30일 라이브 베이스라인 이후에
      조달할지.
