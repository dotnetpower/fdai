---
title: 비용 모델 (예시)
translation_of: cost-model.md
translation_source_sha: ebf4facef88e325ed0e6c9f8ae0b1e8f5ef1cabf
translation_revised: 2026-08-14
---

# 비용 모델 (예시)

[deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 에
정의된 최소 Azure 리소스 인벤토리의 월간 예상 비용을, 고정 vs 변동 지출과 트래픽 시나리오로
분해합니다. 비용 효율 원칙은
[deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#cost-efficiency-principles) 에서 옵니다.

> **과거 계획 예시 - 배포 견적 아님.** 아래 가격 band는 초기 최소 세트의 계획 수립 스냅샷이며
> 현재 Terraform 계획의 합계가 아닙니다. Azure 리스트 가격은 리전, 시간, 구독 계약(EA / CSP / MCAPS /
> Reserved Instances / 절감 계획)에 따라 바뀝니다. 이 문서의 모든 숫자는 **근사값**
> 이며 어떤 커밋 전에도
> [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) 에 대해
> 재확인되어야 합니다. 여기의 어느 것도 보장이 아닙니다. 수치는 문서 작성 시점의 리스트
> 가격을 반영합니다; 포크의 비용 대시보드에 `pricing.confirmed_at` 필드가 마지막 검증
> 시점을 기록해야 합니다.

## 가정(Assumptions)

- **리전**: 크기 자릿수 수치는 Korea Central 상당 단일 Azure 리전; 리전 차이 ±20% 는 정상.
- **통화**: USD 리스트 가격, PAYG(Pay-As-You-Go) 티어. 엔터프라이즈 계약은 보통 5-20%
  감소; Reserved Instances / 절감 계획은 1년/3년 약정으로 컴퓨트 + 데이터베이스 지출을
  30-60% 감소시킬 수 있음.
- **트래픽 (베이스라인)**: **낮은 트래픽** - 월 수천에서 수만 이벤트. 현재 코어 Container App은
  Event Hubs lag scaler가 없으므로 `min_replicas = 1`입니다. Scheduled 작업만 실행 사이에 0으로
  내려갑니다.
- **보존**: Log Analytics 기본 30일
  ([deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set)).
- **무료 티어**: Container Apps 월간 컴퓨트와 Log Analytics 첫 GB 인제스트 무료 부여가 관련
  없는 워크로드에 소비되지 **않는다고** 가정.
- **모델 비용 (T1/T2 추론)**: `enable_llm=true`일 때 Azure OpenAI/Foundry 배포의
  토큰 또는 provisioned-capacity 비용이 추가되며 [T2 LLM 비용](#t2-llm-cost) 에 별도 보고합니다.
  모델 지출은 [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 의 모델 예산 상한에 의해
  범위가 제한된; 초과분은 uncapped inference가 아니라 HIL로 강등.
- **비-Azure 대상**: 현재 구현 대상은 Azure이며 다른 CSP 비용은 이 문서에서 모델링하지 않습니다.

이후 모든 수치는 이 가정들의 대상입니다.

## 비용 카테고리

비용은 두 카테고리로 분할됩니다; 절대값이 움직여도 각 리소스의 지출 형상은 안정적:

- **Fixed** - 시스템이 유휴여도 발생(관리 서비스 기본 요금, 상주 저장소).
- **Variable** - 트래픽에 비례(컴퓨트-초, 인제스트 GB, 딜리버리 작업).

## 리소스별 추정

모든 행은
[deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 의
리소스를 인용합니다. 범위는 베이스라인 트래픽 하에 예상되는 월간 밴드; 상한은 다소 바쁜 달을
반영합니다.

| # | 리소스 | 비용 모델 | 베이스라인 월간 (USD) | 카테고리 | 노트 |
|---|--------|----------|---------------------|----------|------|
| 1 | Container Apps 환경 | 환경 fee = $0; vCPU-초 + GB-초 소비 | **현재 계획으로 재산정** | variable | Core 복제본 하한과 명시적 선택 앱 수에 따라 달라짐 |
| 2 | Container App (통합 코어, 단일 Python 프로세스) | #1에 포함 | #1에 포함 | variable | 기본 `min_replicas = 1`, `max_replicas = 3`; 검증된 lag scaler가 있을 때만 0 허용 |
| 3 | Container Apps Jobs | #1에 포함 | **현재 계획으로 재산정** | variable | 스케줄러, out-of-band, 인벤토리, canary 및 활성화된 워커/작업이 Consumption 사용량 공유 |
| 4 | Event Hubs **Standard** 네임스페이스 (1 TU, auto-inflate off) | 처리량 단위 시간당 (~$0.03/시 × 730시) + 인그레스 이벤트 (~$0.028/백만) | **≈ $22** | fixed | `:9093` 의 Kafka 와이어 이벤트 버스로 소비; DLQ는 Kafka `<topic>.dlq` 규약, 추가 리소스 없음 |
| 5 | Event Grid 인벤토리 구독 + Diagnostic Settings | Event Grid 전달 연산 + 목적지 서비스 사용량 | **현재 계획으로 재산정** | variable | 별도 custom 토픽은 없고 인벤토리 이벤트는 Event Hubs로, 진단은 Log Analytics로 전달 |
| 6 | PostgreSQL Flexible **Burstable B1ms** (1 vCore, 2 GB) | 컴퓨트 + 저장소 + 백업 | **≈ $20 - $25** | fixed | 컴퓨트 ≈$15, 32 GB SSD ≈$4, 7일 백업 ≈$3-5 |
| 7 | Key Vault Standard | 10k 작업당 ~$0.03 | **≈ $1** | variable (범위가 제한된) | 베이스라인에서 낮음 |
| 8 | User-assigned Managed Identity | 무료 | **$0** | - | |
| 9 | Log Analytics workspace | 인제스트 ~$2.30/GB (Analytics 로그); 30일 이내 보존 무료 | **$5 - $15** | variable | 인제스트 볼륨이 주 드라이버 |
| 10 | Azure Container Registry (Basic) | 고정 일 요금(~$0.167) + 10 GB 저장소 포함 | **≈ $5** | fixed | 후에 geo-replication이나 더 많은 저장소 필요 시 Standard ≈$20 |

배포에 포함된 비-과금 요소
([deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 참조):

- Azure Bot Free 계층은 다운스트림에서 Teams 채널을 선택할 때 별도 제공하며 업스트림
  Terraform 기본 배포에는 포함되지 않습니다.
- Static Web Apps Free 계층 (읽기 전용 콘솔 호스팅).
- App 등록 + 워크로드 신원 federation.
- Diagnostic Settings 포워더 자체 (비용은 Event Hubs 행에 있음).

## 월간 묶음 (초기 계획 수립 스냅샷, 모델 비용 제외)

위 카테고리를 베이스라인 가정 하에 결합:

| 버킷 | 내용 | 월간 (USD) |
|------|------|-----------|
| **Fixed** | Event Hubs + PostgreSQL + ACR | **≈ $47 - $52** |
| **Variable** | 초기 scale-to-zero 가정의 Container Apps/Jobs + Key Vault + Log Analytics | **≈ $6 - $28** |
| **합계 (초기 최소 세트 예시)** | 현재 Terraform 토폴로지의 견적이 아님 | **≈ $53 - $80 / 월 (historical)** |

이 합계는 scale-to-zero를 가정한 초기 스냅샷이므로 현재 코어 `min_replicas = 1` 배포의 예산으로
사용하면 안 됩니다. 배포 전 `terraform plan`에서 활성 리소스와 SKU를 추출하고 Azure Pricing
Calculator 또는 Retail Prices API로 다시 합산합니다. 운영 HA PostgreSQL, 비공개 networking,
Azure OpenAI, 문서 인제스트, Operator API/콘솔, 이메일 채널은 각각 별도 줄 항목입니다.

### 현재 Terraform 인벤토리 조정

| 범위 | 현재 리소스 | 견적 처리 |
|------|------------|-----------|
| 기본 | Container Apps 환경, 코어 복제본 1개, scheduled jobs, Event Hubs, Event Grid 인벤토리 구독, PostgreSQL, Key Vault, identities, Log Analytics/Application Insights, ACR, canary | 모든 활성 SKU와 복제본/리소스 사용량을 계획에서 다시 계산 |
| 운영 delta | zone-redundant PostgreSQL HA, 35일 geo 백업, 비공개 networking/DNS 및 비공개 실행기 경로 | dev B1ms band에 포함하지 않고 별도 계산 |
| `enable_llm` | Azure OpenAI/Foundry 계정과 기능 배포 | 토큰/PTU 및 임베딩 사용량을 모델 예산에 합산 |
| `enable_document_ingestion` | ADLS Gen2 ZRS/HNS, 블롭/dfs 비공개 엔드포인트, 인제스트 앱 + ClamAV, 이행 워커 | 저장소 용량/operations, 엔드포인트, always-on 복제본을 별도 계산 |
| 채널/콘솔 명시적 선택 | Operator API/채널 앱, Static Web Apps, ACS 이메일/SMS 등 활성 어댑터 | 실제 활성화와 전송량 기준으로 별도 계산 |

## T2 LLM 비용

Reasoning-tier (T2) 추론은 고정 인프라 합계와 분리하는 **사용량 또는 provisioned-capacity 비용**입니다.
현재 구현은 명시적 선택 Azure OpenAI/Foundry 배포를 지원하며 [llm-strategy-ko.md](../architecture/llm-strategy-ko.md)가
그 모델 선택과 예산 게이트를 관장합니다. 별도 보고 이유:

- 모델 패밀리와 mixed-model 교차 검사 요건에 따라 자릿수로 변동
  ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 에
  따라 각 T2 판단은 최소 2개 별개 모델 호출).
- 설정으로 예산 상한 부여; 초과분은 **HIL로 강등**, 절대 uncapped inference 아님.

이벤트 볼륨에 키를 맞춘 대략 묶음, 이벤트의 ~10%가 T2에 도달, 각 T2 판단이 2개 별개 모델을
호출, 평균 프롬프트가 ~3 k 입력 + ~500 출력 토큰에 맞는다고 가정:

| 월간 이벤트 | T2 판단 (10%) | Small-model 티어 | Mid-model 티어 | Frontier 티어 |
|-------------|--------------|-----------------|----------------|--------------|
| 10 k | ~1 k | **$5 - $15** | **$30 - $100** | **$100 - $500** |
| 100 k | ~10 k | **$50 - $150** | **$300 - $1,000** | **$1,000 - $5,000** |

모델 선택과 무관하게 성립하는 규칙:

- **예산 상한이 천장**; 초과해도 더 지출되지 않고 발견 사항을 HIL 큐로 보냄. `core/metering/budget.py`의 `ModelBudget`이 모든 LLM 경로에 대해 그 천장을 microUSD로 선언하고 `BudgetLedger`가 호출 전에 집행합니다. T2 계층은 `t2_budget_exhausted`로 HIL에 escalate하고 대화 포트는 `budget_denied`로 T1에 머뭅니다. 단위별 한도는 항상 적용되며, fleet 전체 총량은 배포가 선언했을 때만 존재합니다. 리셋되지 않는 총량은 예산이 아니라 kill 전환이기 때문입니다. Atomic reservation은 spend를 변경하기 전에 요청된 호출 및 microUSD increment를 포함한 prospective 합계를 평가합니다. 단독으로 남은 예산보다 큰 reservation은 allowance를 소비하지 않고 거부됩니다.
- 모델 선택은 **설정**, 코드가 아님 ([llm-strategy-ko.md](../architecture/llm-strategy-ko.md)); 측정된
  비용/품질로 스왑은 안전.
- Provider-side 비율 한도와 요청당 시간 초과가 단일 이벤트가 상한을 격리적으로 폭파하지 않도록
  유지.

**프로바이더 사용량 측정.** 위 수치는 청구서가 아닌 *묶음*입니다. 각 모델 호출에서
프로바이더가 측정한 `usage`(프롬프트 + 완료 토큰)를 `MeteringSink`가 캡처합니다.
`LlmCostPanel`은 호환 경로 `GET /kpi/llm-cost`를 유지하지만 운영자 변환 결과에는 토큰만
노출합니다. 워크로드 범위, 모델, 호출, 대화, 일, 월별로 확인할 수 있습니다.
설정된 가격은 내부 예산 게이트에 계속 사용할 수 있지만, 리전 및 협상 요율이 다르므로 콘솔은
이를 실제 지출로 표시하지 않습니다 ([operator-console-ko.md § 4.4](operator-console-runtime-model-ko.md#44-cost와-rate-limit) 참조).

## 트래픽 스케일링

이벤트 볼륨이 커지면서 묶음이 어떻게 움직이는지. 하드 SLA가 아니라 인벤토리 재검토
트리거 세트.

| 시나리오 | 예상 인프라 월간 | 압박 받을 첫 항목 | 권장 액션 |
|----------|-----------------|-------------------|-----------|
| **베이스라인 (≤10 k 이벤트/월)** | 현재 계획 + 측정 사용량 | 코어 복제본 하한, standing 서비스 | 활성 최소 세트와 예산 검증 |
| **10 k - 100 k 이벤트/월** | 계획 + 텔레메트리로 재산정 | Log Analytics 인제스트, Container Apps 컴퓨트 | 티어 유지; Log Analytics **daily 상한** 설정; 인제스트 예산 알림 감시 |
| **100 k - 1 M 이벤트/월** | 계획 + 텔레메트리로 재산정 | Log Analytics 인제스트, Container Apps 컴퓨트, PostgreSQL 저장소 | 감사 스트림에 **Basic Logs** 고려, PostgreSQL 저장소 티어 업, 코어 복제본/리소스 sizing 검토 |
| **≥ 1 M 이벤트/월** | 재모델링 | 대부분 행 | 인벤토리 리뷰 재실행; Event Hubs 추가 TU 또는 Dedicated, PostgreSQL General 용도, 전용 vector 저장소 평가 |

승격 트리거(코어 복제본/리소스 sizing, PostgreSQL 티어 업, Log Analytics 분리)는
[열림 Decisions](#open-decisions) 에 있습니다.

## 최적화 옵션

지출이 묶음 상한에 접근할 때 기회적으로 적용. 각 옵션은 특정 trade-off가 문서화되어
선택이 눈감고 이루어지지 않도록 합니다.

| 옵션 | 절감 | Trade-off |
|------|------|-----------|
| PostgreSQL **Reserved 인스턴스 / 절감 계획** (1년 또는 3년) | 컴퓨트 30-55% 감소 | 티어 약정; 다운그레이드는 조기 해지 필요 |
| **Log Analytics daily 상한** | 폭주하는 인제스트 월 방지 | 상한 초과 로그는 워크스페이스 정책에 따라 드롭 또는 스로틀 |
| 감사 스트림에 **Basic Logs 티어** | Analytics-티어 인제스트 대비 ~74% 감소 | Basic Logs에 대한 쿼리가 느림/유료 (아카이브 + 가끔 리플레이용으로 그대로 유지) |
| 태그되지 않은 매니페스트에 **ACR 보존 정책** | 작은 저장소 절감 | 오래된 디버그 이미지가 정리됨; 서명된 릴리스 다이제스트는 명시적으로 유지 |
| **복제본 하한을 워크로드별로 설정** | Scheduled 작업은 실행 사이 0; 코어는 기본 1 | Core를 0으로 내리려면 Event Hubs lag scaler와 wake-up 검증 필요 |
| **MCAPS / Founder 허브 / free trial 크레딧** | 초기 몇 달을 완전히 상쇄 | 자격은 시간 제한; 지속적 레버 아님 |
| 콘솔 이미지를 GHCR로 이동 | ACR Basic (~$5/월) 절감 | 레지스트리 혼합 - 포크가 Azure에 밀접 통합되어 있지 않을 때만 가치 (포크는 ACR 선택 - [deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) 참조) |

### Warm-capacity 정책 (cold-start vs MTTR)

Scale-to-zero는 조건을 충족한 작업/레인의 목표이지 현재 코어 기본값이 아닙니다. 일괄 min-replicas = 0 은 긴급 복구 의 MTTR 에
cold-start 지연을 떠넘긴다 - SEV1 장애 조치 는 컨테이너 부팅을 기다릴 수 없다.
`core/capacity/warm_pool.py` (`WarmCapacityPolicy`) 가 그 tension 을 결정론적으로
해소한다: cold 시작 를 흡수할 수 없는 작업 - 설정된 심각도 이상(기본 SEV2)의
인시던트, 활성 이벤트 storm(cold 시작 로 serialize 될 교정 burst), 그리고
off-hours(콘솔에 이미 warm 한 사람이 없어 자율 복구 가 유일한 fast 경로)
- 에만 **warm** 레인 (min-replicas > 0)을 권고하고, scaler와 wake-up 경로가 검증된 나머지 레인은 scale-to-zero 에
남긴다. 임계값 는 fork-tunable 구성 이고, 정책은 순수 권고다: 배포 계층
가 계획 시간 에 `min_replicas` 하한 를 읽고 런타임 이 액션 등급 별
`warm_required` 를 읽는다. 이는 idle-cost 묶음 을 온전히 유지하면서 중요한
곳의 복구 지연 시간 를 보호한다.

## 묶음이 다루지 않는 것

이 문서 밖의 의도적 비용:

- **T1/T2 모델 사용량 또는 프로비저닝된 용량** - [T2 LLM 비용](#t2-llm-cost) 에 별도 보고.
- **인간 노동** - 운영자 on-call 시간, HIL 승인자 시간.
- **GitHub / Azure DevOps** - GitOps 호스트는 비-Azure 비용
  ([deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#prerequisites) 의 같은 카테고리 노트).
- **DR / secondary-region 리소스** - 현재 최소 인벤토리 밖이며 별도 배포 토폴로지와
  계획으로 산정합니다.
- **스케일에서의 네트워크 egress** - 베이스라인에서 무시 가능하다고 가정; 트래픽이
  100 k/월 티어에 도달할 때 재검토.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 최소 Azure 인벤토리 모델 | in-progress | `infra/`; [현재 Terraform 인벤토리 조정](#현재-terraform-인벤토리-조정) | Terraform은 배포 가능한 인벤토리를 선언하지만 과거 가격 행은 현재 계획에서 생성되지 않습니다. |
| LLM 사용량 측정 및 예산 적용 | implemented | `services/core-control-plane/src/fdai/core/metering/`; `services/core-control-plane/tests/core/metering/` | Focused 테스트는 레코드, 사용량, 가격 입력, 집계, 싱크 동작 및 예상 예산 차단을 다룹니다. 이는 예산 동작을 입증하지만 Azure 청구서를 입증하지는 않습니다. |
| 현재 SKU 및 수량 조정 | not-started | [리소스별 추정](#리소스별-추정) | 행에 여전히 `recalculate from current plan`이 있으며 체크인된 계획-비용 조정 산출물이 없습니다. |
| 가격 확인 및 배포 기준선 | not-started | [열림 Decisions](#열림-decisions) | 관리되는 `pricing.confirmed_at`, Retail Prices 또는 Calculator 증적, 측정된 청구 기준선이나 차이 알림 근거가 보존되지 않았습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 구현 ledger를 도입했으며 이전 출처 이력은 재구성하지 않았습니다. | `current change`; 구현 범위 표에 나열된 현재 인프라 및 측정 근거입니다. | 현재 계획을 조정하고 가격을 확인하며 측정된 배포 기준선을 보존해야 합니다. |

### 남은 작업

- [ ] 검토된 Terraform 계획에서 활성화된 리소스, SKU, 복제본 하한, 저장소, 보존 및 선택적 기능을 내보내고 모든 비용 행을 정확한 계획 다이제스트와 조정합니다.
- [ ] 선택한 지역과 통화에 대해 Azure Pricing Calculator 또는 Retail Prices API에서 날짜가 있는 `pricing.confirmed_at` 증적을 기록하고 가정 및 제외된 할인을 포함합니다.
- [ ] 과거 묶음을 현재 추정으로 바꾸기 전에 조정된 추정을 측정된 청구 구간 하나와 비교하고 관찰 가능한 차이 알림을 정의합니다.
- [ ] 검토된 배포 근거를 사용해 아래 tier, 승격 트리거, 모델 예산, 약정 및 확인 주기 결정을 해결합니다.

## 관련 문서

- [deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md) - 이 문서가 추정하는 인벤토리.
- [tech-stack-ko.md](../architecture/tech-stack-ko.md) - 서비스 선택 근거.
- [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) - T2 모델 선택, 예산 상한.
- [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) - 모든 cost-per-unit 주장을 관장하는
  measurement-first 규칙.

## 열림 Decisions

- [ ] 최소 세트 내 구체적인 티어 값(PostgreSQL 저장소, Log Analytics daily 상한, ACR 보존
      윈도우, Event Hubs 처리량-단위 상한).
- [ ] 승격 트리거: 각 비용 행이 재티어링될 **숫자 임계값** (PostgreSQL step-up을 트리거하는
      이벤트/월 비율, Basic Logs 분리, 코어 복제본/리소스 resizing).
- [ ] T2 모델 티어 선택(small / mid / frontier)과 테넌트당 월간 예산 상한.
- [ ] 포크의 비용 대시보드에 `pricing.confirmed_at` 메커니즘 - 이 문서의 숫자를 Azure Pricing
      Calculator에 대해 어떻게 얼마나 자주 재검증하는가.
- [ ] Reserved Instances / 절감 계획을 첫날에 조달할지 첫 30일 라이브 베이스라인 이후에
      조달할지.
