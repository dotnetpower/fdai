---
title: Phase 4 - 스케일 (Azure); 멀티 클라우드 (TBD)
translation_of: phase-4-scale.md
translation_source_sha: 7f3a9b5359f1503dc899a04e407b3f3abb8e8a6a
translation_revised: 2026-08-11
---

# 단계 4 - 스케일 (Azure); 멀티 클라우드 (TBD)

**목표**: 시스템이 스케일할 때 Azure 베이스라인을 정직하게 유지 - 지속 측정, 패턴-라이브러리
성장, 모델 비용/quality 추적, 성능/확장성 - 그래서 목표 배수가 assert되지 않고 **측정된 베이스라인
대비 검증** 유지. 여기서 어떤 배수도 주장되지 않음; 단계 4는 시스템이 스케일할 때 단계 0 증거를
현재하게 유지. **멀티 클라우드 확장은 연기(TBD)** ; 아래 *TBD (deferred)* 표시된 섹션은
전방-지향 설계로 보존되며 비-Azure 대상이 명시적으로 스코프될 때까지 이 로드맵에서 구축되지 않음
([Always-On 룰](../../../.github/copilot-instructions.md#always-on-rules-must)
참조).

> **구현 상태**: 회귀, pattern-growth, model-tracking, latency-budget library와 두
> 측정 실행기, 실행기 CLI 및 Terraform 작업 모듈은 구현되어 있습니다. 운영
> 예약의 지속 실행 결과, statistical 단계 4 exit 근거 및 dedicated vector-store/AKS
> 런타임은 완료되지 않았습니다. 참조 Container Apps는 현재 `min_replicas = 1`이고 KEDA
> 규모 룰이 없습니다. Scale-to-zero는 포크가 lag-based 룰을 추가한 뒤에만 사용할 수 있는
> 목표 토폴로지입니다.

이 단계는 단계 0-3 코어 위에 구축되고 변경하지 않음.
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 와
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 의
CSP-중립 원칙을 **설계 불변식**(어댑터 표면, 정규화 스키마) 로 실현하여 향후 비-Azure 어댑터가
추가적이도록; [tech-stack-ko.md](../architecture/tech-stack-ko.md) 의 스택과 어댑터 경계 재사용, 엄격히
[goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) 로 측정, [security-and-identity-ko.md](../architecture/security-and-identity-ko.md)
의 아이덴티티와 shadow-mode 규칙 상속.

## 산출물

모듈 참조는 [`services/core-control-plane/src/fdai/`](../architecture/project-structure-ko.md)에서 해당 산출물을 담고 있는
주요 Python 패키지를 가리킴; 여기 나열된 모든 모듈은 고객-agnostic이고 Azure 전용
(아래 멀티 클라우드 산출물은 TBD로 남음).

- 자동 회귀 강등 있는 Azure 베이스라인의 지속 측정/개선 루프.
  모듈:
  [core/measurement/regression.py](../../../services/core-control-plane/src/fdai/core/measurement/regression.py).
- 오버피팅 방지 가드 있는 패턴-라이브러리(T1) 성장.
  모듈:
  [core/measurement/pattern_growth.py](../../../services/core-control-plane/src/fdai/core/measurement/pattern_growth.py).
- 측정-주도 스왑 있는 모델 비용/quality 추적.
  모듈:
  [core/measurement/model_tracking.py](../../../services/core-control-plane/src/fdai/core/measurement/model_tracking.py).
- Azure에서 확장성/성능 검증(티어별 지연 예산, 이벤트-기반 scale-to-zero 보존).
  모듈:
  [core/measurement/latency_budget.py](../../../services/core-control-plane/src/fdai/core/measurement/latency_budget.py).
- 두 라이브러리-전용 측정 컴포넌트를 Container Apps Jobs로 배선하는 스케줄 러너 -
  automated-baseline 회귀 러너(P0 시나리오 세트를 매일 리플레이, 회귀 시 자동 강등)와
  pattern-growth 인테이크 러너(감사 스트림 드레인, 허용된 패턴을 shadow 로만 인제스트,
  자동 승격 금지).
  모듈:
  [core/measurement/runners.py](../../../services/core-control-plane/src/fdai/core/measurement/runners.py).
  Infra:
  [infra/modules/measurement-runners/](../../../infra/modules/measurement-runners).
  작업 은 library-only 코어 모듈 이 아니라 `fdai.delivery.measurement_runner_cli`을
  호출합니다. 기준선 모드 는 배포된 enriched 고정된 시나리오 를 재생 하고 회귀
  demotion 을 shared `StateStore`에 저장 하며 모든 실행 을 감사 합니다. Growth 모드 는
  강제 적용 실행, 결정론적 검증, 롤백 상태, 임베딩 변환 결과, exact
  매개변수, 인시던트 출처 이력 를 증명하는 명시적 `measurement.action_outcome.v1` 감사
  기록 만 읽습니다. 결과 및 영속 감사 시각은 timezone-aware여야 합니다. 감사
  시각보다 5분 넘게 미래인 결과는 intake 전에 거부됩니다. 각 범위가 제한된 intake 배치에서는
  액션별 가장 높은 순서의 finalization만 평가합니다. 대체된 행도 영속 watermark를
  전진시키며 명시적 검증 실패는 rejected로 감사됩니다. 출처 이력 가 없으면 training
  데이터 를 추론하지 않고 zero intake 로 처리합니다. Azure text-embedding-3 요청 는 fixed
  384-dimension pgvector 계약 를
  사용하며 다른 계열 또는 dimension 은 시작 에서 실패합니다.
- **TBD (deferred)**: **프로바이더 어댑터** 를 통한 정책과 실행의 멀티 클라우드 확장(새 코어 없음),
  크로스-CSP rule-catalog 정규화, per-CSP 실행 아이덴티티, 멀티 클라우드 이벤트 버스 결정
  ([tech-stack-ko.md](../architecture/tech-stack-ko.md) 의 OD-3). 이 항목들은 비-Azure 작업이 스코프될
  때까지 설계 형상으로만 남음.

## 프로바이더 어댑터 경계 (TBD - deferred)

> 이 섹션은 향후 비-Azure 대상을 위한 **설계 불변식** 으로 보존. 이 단계에서 **구축되지 않음** ;
> [Always-On 룰](../../../.github/copilot-instructions.md#always-on-rules-must)
> 참조.

코어 엔진은 CSP-중립 유지; 새 클라우드는 어댑터 구현으로 추가되지 절대 코어 포크로 추가되지
않음. 어댑터 표면은 고정되고 각 어댑터는 기존 인터페이스 뒤에 추가됨
([project-structure-ko.md](../architecture/project-structure-ko.md) 참조):

- **Policy 어댑터** - 프로바이더-파라미터화된 입력으로 같은 OPA/Rego 정책 평가; per-cloud 정책
  포크 없음.
- **IaC / 실행기 어댑터** - Terraform/OpenTofu 프로바이더로 교정 적용; 교정 PR
  발행, CSP당 7개 안전조건(stop-condition, 롤백, blast-radius, 예행 실행, 리소스 잠금,
  멱등성, 감사) 준수.
- **신원 어댑터** - 범위된 실행 principal 공급(아래 참조).
- **Event-source / 버스 어댑터** - 프로바이더 이벤트를 인그레스에서 버전된 내부 스키마로 정규화.
- **State-store 어댑터** - 감사/pattern-library/KPI 저장을 이식 가능하게 유지.

엄격도 요건(비-Azure 어댑터가 결국 스코프될 때 적용):

- 코어 엔진은 벤더 SDK를 가져오기 하지 않음; SDK 호출은
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
  에 따라 어댑터 안에만 존재.
- 모든 어댑터는 CSP 간 동일한 외부 관측 동작(같은 정규화 이벤트 → 같은 티어 결정 → 같은 액션
  형상) 을 증명하는 **계약/동등성 테스트** 와 함께 나감.
- 프로바이더 선택은 코어의 코드 브랜치가 아니라 설정.

## 멀티 클라우드 규칙 카탈로그 (TBD - deferred)

> 비-Azure 대상이 스코프될 때까지 연기. Azure만 유일한 구현 카탈로그 대상;
> [rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md) 참조.

- 소스 추가: **AWS** (Well-Architected, 구성 managed 룰, CIS AWS) 와 **GCP** (Recommender,
  Policy Controller / Gatekeeper constraints, CIS GCP), [phase-1-rule-catalog-t0-ko.md](phase-1-rule-catalog-t0-ko.md)
  의 기존 Azure와 OSS 소스와 함께.
- 모든 규칙을 공통 CSP-중립 스키마(`id, 버전, 출처, 심각도, category, resource-type,
  check-logic, 교정, 출처 이력`) 로 **정규화** 하여 규칙이 원본 클라우드와 무관하게
  같게 읽힘.
- **크로스-CSP 충돌 처리**: 다른 클라우드나 소스의 규칙이 하나의 이벤트에 매칭될 때, `id` 로
  중복제거, 심각도 다음 출처 priority로 우선순위 해결, 동점은 auto-pick 대신 **HIL로
  escalate**. 출처 이력은 출처 소스와 버전을 기록하여 규칙 변경이 추적·역방향 가능.
- 새 소스는 기존 업데이트 파이프라인(`출처 watcher → collect → shadow eval → 회귀 →
  promote / 롤백`, [phase-2-quality-and-t1-ko.md](phase-2-quality-and-t1-ko.md)) 을 통해
  흐름; 승격은 정책 위반 escape 0으로 회귀 스위트 통과 필요.

## Per-CSP 아이덴티티와 최소권한 (TBD - deferred)

> 연기; Azure 아이덴티티 모델이 오늘 적용(user-assigned Managed Identity, 액션 화이트리스트,
> 별개 승인/실행 principal - [security-and-identity-ko.md](../architecture/security-and-identity-ko.md)
> 참조).

- 각 클라우드는 자체 **범위된 실행 아이덴티티** (예: Azure user-assigned Managed Identity, AWS
  IAM 롤, GCP 서비스 계정), 각각 액션 화이트리스트로 제한. 어떤 아이덴티티도 클라우드 간이나
  레이어 간 공유되지 않음.
- 모든 클라우드에서 **승인과 실행은 별개 principal** - no 자기 승인,
  [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 에 따라.
- Blast-radius 한도(스코프/배치/속도 상한) 은 CSP별로 강제; 잘못 설정된 어댑터는 화이트리스트를
  초과할 수 없음.

## 이벤트 버스 이식성 (TBD - deferred)

> 연기; Azure에서 버스는 Event Hubs의 Kafka 엔드포인트
> ([tech-stack-ko.md](../architecture/tech-stack-ko.md#od-3-멀티-클라우드-이벤트-버스-phase-4--tbd) 참조).

- 비-Azure 대상을 범위에 포함할 때만 OD-3을 결정합니다. 어떤 managed Kafka 또는 다른 로그
  구현이 기존 Kafka wire 순서, 재생, DLQ 계약을 보존하는지 검증합니다.
- 결정 기준: 클라우드 간 **순서, dead-letter, 리플레이, 멱등성 패리티**, 운영 비용, CSP
  중립성 - 버스 어댑터는 백엔드와 무관하게 리소스별 순서와 at-least-once + 멱등 처리 보존해야
  함.
- 비-Azure 결과를 결정 기록으로 남기고
  [tech-stack-ko.md](../architecture/tech-stack-ko.md) OD-3을 업데이트합니다.

## 안전과 Shadow-First 롤아웃

- 새로 추가된 어떤 능력도 shadow 정확도가 정책 위반 escape 0으로 측정될 때까지 **shadow 모드**
  (judge-and-log, 실행 없음) 로 출시; 강제 적용로의 승격은 명시적·액션별,
  [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md)
  와 매칭. 비-Azure 어댑터가 결국 스코프될 때(TBD), 같은 shadow-first 규칙이 어댑터의 첫
  액션에 적용.
- 어떤 회귀는 영향받은 액션을 자동으로 shadow로 강등.

## 지속 측정과 개선

- 고정 버전 시나리오 세트에서 주기적으로 **베이스라인 vs 트리트먼트** 재실행; **회귀** 는
  가드-메트릭 위반 또는 보고된 신뢰구간 넘는 성공-메트릭 하락, 그리고 자동 shadow 강등 트리거
  ([goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md)).
- 가드 메트릭(CFR, false-positive/부정, 롤백 비율, **정확히 0** 정책 위반 escape) 는
  성공 메트릭과 같은 측정 윈도우와 시나리오 세트 버전에서 평가, 그래서 이득과 위반이 다른
  데이터에서 비교되지 않음.
- 후행 가드 메트릭이 이동하기 전 회귀가 잡히도록 **환경별** 선행 지표(티어별 커버리지 표류,
  mixed-model 불일치, 검증기 abstain/fail) 감시. Per-cloud 분해는 **TBD** 설계 불변식,
  비-Azure 어댑터가 스코프될 때만 활성화.
- 목표가 현재, fair 참조를 추적하도록 모든 시나리오 세트 버전 bump에 re-baseline.

## 패턴 라이브러리 성장 (T1)

- 패턴 라이브러리는 **auto-resolved, non-rolled-back, 검증된** 프로덕션 결과에서만 공급;
  실패, revert, HIL-override된 액션은 재사용 가능한 패턴이 되어선 안 됨.
- 새 패턴은 **shadow** 에서 진입하고 T1 액션을 주도할 수 있기 전 shadow-평가됨 - 라이브러리는
  self-promote 할 수 없음.
- 피드백-루프 오버피팅 방어: 시간적 holdout(기준 시점 전에 학습된 패턴, 이후 테스트) 에서 후보
  패턴 검증, T1 false-positive 비율을 가드로 모니터; 상승하는 비율은 offending 패턴 강등. 성장은
  가드 메트릭을 회귀시키지 **않고** auto-resolution을 올려야 함.

## 모델 비용/Quality 추적

- [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) 의 비용/사용량과 원격측정 소스에서
  모델별 비용과 품질을 시간에 걸쳐 추적; T2 reasoner 모델을 **측정된 결과로 스왑, 가정 아님**,
  모델 ID와 임계값을 [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 에 따라 구성으로 유지.
- 모델 폐기/가격 변경 플래그, 강제 적용에 도달하는 어떤 스왑 전에 시나리오 세트에서 mixed-model
  교차 검사 재검증.

## 확장성과 성능

- 이벤트 볼륨이 커질 때 Azure에서 티어별 지연 예산을 보존합니다. 현재 참조는 최소 한
  복제본을 유지하며, event-driven scale-to-zero는 KEDA lag 룰을 추가한 배포에서만 검증합니다.
  멀티 클라우드 성능 패리티는 TBD(연기).
- 코퍼스나 재현율/지연 시간 목표가 요구할 때 T1 벡터 검색을 pgvector에서 전용 vector 저장소로
  졸업([tech-stack-ko.md](../architecture/tech-stack-ko.md) 의 기준); 상태 어댑터가 이를 코어에 투명하게
  유지.
- **초대규모 테넌트(구독 300개, 랜딩존 수십개)** 의 경우, 확장 토폴로지(셀 기반
  스트리밍, 정책-기반 fan-in, 2-평면 로깅, CQRS 감사 인덱싱, 선택적
  **standard / sovereign** 배포 프로파일)는
  [hyperscale-cell-architecture-ko.md](../architecture/hyperscale-cell-architecture-ko.md) 에 명세됨.
  테넌트가 초대규모 트리거를 넘을 때만 진입하며, 모든 안전 불변식과 8개 CSP-중립 계약을 보존.

## 런타임 확장 (AKS) - 연기

> **Container Apps 가 기본 런타임이다**(최소비용 day-zero 와 `standard` 초대규모
> 프로파일). AKS 는 **연기**된다 - `sovereign` 프로파일(self-host 관측 + 리전 내 LLM +
> confidential 노드)이나 Container Apps 한계를 압박하는 heavy 셀에서만 채택. 이식성은
> 런타임 계약(OCI 이미지 + Knative-호환 매니페스트 subset, Dapr 없음 / Envoy-specific
> 유입 없음,
> [csp-neutrality-ko.md](../architecture/csp-neutrality-ko.md#2-런타임-계약--oci-이미지--knative-호환-매니페스트))
> 으로 보장되므로, AKS 이동은 `infra/modules/runtime/aks/` 렌더이지 `core/` 리라이트가 아니다.

- **언제 AKS:** `sovereign` 프로파일이 요구하거나(LGTM / ClickHouse / 리전 내 LLM 이 AKS
  워크로드로; confidential SEV-SNP 노드; 프라이빗 클러스터), heavy 셀이 노드-레벨
  제어(spot / GPU / large-memory SKU), DaemonSet 수집, 파티션-스티키 StatefulSet 컨슈머를
  필요로 하는 경우. 전체 근거와 프로파일 매트릭스는
  [hyperscale-cell-architecture-ko.md § 런타임](../architecture/hyperscale-cell-architecture-ko.md#런타임) 에 있다.
- **범위:** 새 `infra/modules/runtime/aks/` 서브모듈이 동일한 OCI 이미지와 Knative-호환
  매니페스트 subset 을 AKS 에 렌더(KEDA 스케일러 보존)하고, Container Apps Jobs 는 K8s
  CronJob 으로, 네이티브 시크릿 은 외부 Secrets Operator 로 렌더 -
  [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 와 정합.
- **비목표:** AKS 는 제어 루프, 안전 불변식, 어떤 wire 계약도 바꾸지 않는다. 배포 타깃일 뿐
  새 자율 표면이 아니다. Dapr 와 Envoy-specific 유입 는 런타임 계약 이식성을 위해 계속
  금지된다.

## Exit 기준

- 지속 측정이 명시된 Azure 측정 윈도우에서 어떤 가드 메트릭에도 **회귀 없음** 표시, 정책 위반
  escape가 정확히 0으로 유지.
- 배수 목표(메트릭 1-4) 가 Azure 베이스라인 대비 **통계적 증거로 시연** (표본 크기, 신뢰구간,
  시나리오 세트 버전) - 배수와 절대값으로 보고, 절대 assert 아님.
- 패턴-라이브러리 성장이 시간적 holdout에서 가드 메트릭을 회귀시키지 **않고** auto-resolution
  을 올림.
- **멀티 클라우드 이식성은 이 단계의 exit 기준이 아님** - 연기(TBD) 되며 향후 단계에서
  스코프될 예정
  ([Always-On 룰](../../../.github/copilot-instructions.md#always-on-rules-must)
  참조).

## 열림 Questions

- Vector-store 졸업 기준과 마이그레이션 경로(pgvector → 전용 저장소).
- Azure 지속 측정 루프의 회귀-윈도우와 신뢰-구간 설정.
- **TBD (deferred)**: 어떤 두 번째 클라우드를 먼저 온보딩할지와 그 shadow-to-enforce 시퀀싱;
  OD-3이 나중에 새 백엔드 선택할 시 이벤트-버스 마이그레이션 경로; 메트릭 1의 크로스-CSP 비용
  귀속과 통화 정규화.

## 의존성

- 세 버티컬 모두에 걸쳐 안전 불변식이 강제되는 P3 통합 자율 MVP
  ([phase-3-integrated-loop-ko.md](phase-3-integrated-loop-ko.md)).
