---
title: FinOps 자율 운영
translation_of: finops-autonomous-operations.md
translation_source_sha: 7b93a7b31933d5e5b66de36922440947189eaf03
translation_revised: 2026-08-28
---

# FinOps 자율 운영

이 문서는 FDAI의 운영 온톨로지와 고정된 15개 에이전트 조직이 사람의 개입을 최소화하면서 비용
거버넌스 에피소드를 종료하는 방법을 정의합니다. 온톨로지는 exact 의미와 범위가 제한된 근거를
제공합니다. 에이전트는 계속 활성 컨트롤 플레인 역할을 하며 모든 상태 전이를 소유합니다.

> **범위:** 이 설계는 FinOps 결정 프레임, 에이전트 choreography, 자율 복구, 효과 정산 및 학습
> 루프를 소유합니다. 배포판과 활성화 계약은 [온톨로지 기반 FinOps 패키지
> 아키텍처](finops-package-architecture-ko.md)에 있습니다. 전달 wave는 [FinOps 패키지 전달
> 계획](../fork-and-sequencing/finops-package-delivery-plan-ko.md)에 있습니다.
> 구독 전체 분석, 리소스 수준 SKU 결정, 절감액 귀속 및 Console 작업 영역은
> [FinOps 리소스 효율 및 SKU 결정](finops-resource-efficiency-ko.md)에서 다룹니다.
>
> **권한 경계:** 온톨로지 근거는 자율성을 유지하거나 낮출 수 있습니다. 판단, 승인, 실행,
> promotion을 수행하거나 의도한 효과가 발생했다고 단정할 수 없습니다.
>
> **현재 상태:** 정확한 FinOps 의미 프로파일, 고정된 15개 책임 trace, 범위가 제한된 복구
> 조정기, 독립 다중 효과 정산, replay, 보존 및 통제된 학습 입력은 로컬 근거와 함께 구현되어
> 있습니다. Live-authoritative 정산 cohort와 독립 패키지 및 액션별 승격 검토는 아직 없습니다.
> 하드닝 라운드 1-6은 campaign 혼합과 option 대체를 차단하고 Azure 인증, 메모리 상한, 공개, cursor 없는 비용 읽기 방지를 보존합니다. 런타임 권한은 바뀌지 않습니다.

## 설계 개요

적격 FinOps 에피소드는 범위가 제한된 비용 또는 리소스 근거로 시작하고 에이전트가 소유한 최종
결과가 있어야 종료됩니다. 에이전트는 활성 온톨로지 release를 통해 대상을 확인하고, 결정
컨텍스트를 구체화하고, 안전한 대안을 비교하고, 결정론적 정책을 적용하고, Thor를 통해서만
실행하고, 효과를 독립적으로 관측한 뒤, 통제된 학습에 결과를 제공합니다.

![설계 개요. 주요 단계는 Observed cost and resource evidence, Release-bound ontology context, Domain advice and safe options, Forseti judgment, Odin arbitration when objectives conflict, Thor execution or typed no-op, Var approval only when required, Heimdall independent observation, Vidar recovery when needed, Saga terminal audit, Muninn, Norns, and Mimir learning loop입니다.](../../diagrams/generated/fdai-roadmap-architecture-finops-autonomous-operations-01.ko.svg)

## 운영 원칙

- **에이전트 소유 전이:** 게시된 모든 객체에는 기존 pantheon 소유자가 있습니다. 패키지,
  projector, 프로바이더 또는 온톨로지 함수가 숨겨진 에이전트가 되지 않습니다.
- **온톨로지가 필수인 결정:** 후보가 작업 적격 상태가 되려면 exact 대상, 적용되는 목표, 관계
  범위, 근거 기준 시점 및 활성 온톨로지 release가 있어야 합니다. 프로바이더 payload와 자유
  형식 텍스트는 정규화될 때까지 후보 근거로 남습니다.
- **결정론 우선 처리:** 반복 가능한 탐지, 대안 필터링, 정책, 가드레일 및 정산은 T0 규칙과
  타입이 지정된 함수를 사용합니다. T1은 검증된 이전 사례를 재사용합니다. T2는 남은 모호성에만
  사용하며 기존 품질 게이트를 계속 통과해야 합니다.
- **에스컬레이션 전 자율 처리:** 에이전트는 Var가 사람 승인을 요청하기 전에 범위가 제한된 근거
  복구, 더 안전한 대안 선택, 더 작은 영향 범위, 타입이 지정된 no-op 또는 롤백을 시도합니다.
  정책상 필요한 승인, 되돌릴 수 없는 작업 및 해결되지 않은 높은 위험은 사람 결정으로 남습니다.
- **독립 종료:** 발송이나 API 성공은 FinOps 결과가 아닙니다. 절감액, 단위 비용, 용량, 신뢰성
  및 복구 효과는 권위 있는 관측이 정산 구간을 종료할 때까지 예측으로 남습니다.
- **침묵 없는 완료:** 알 수 없음, 보류, 차단, no-op, 롤백 및 검증되지 않은 결과는 Saga 감사
  근거가 있는 명시적 최종 또는 대기 기록입니다.

## 온톨로지 기반 결정 프레임

각 에피소드는 exact 온톨로지 release와 의미 프로필에서 하나의 변경할 수 없는 결정 프레임을
구체화합니다. 이 프레임은 별도 FinOps 그래프를 만들지 않고 다섯 개의 운영 관점을 사용합니다.

| 관점 | 필요한 FinOps 내용 |
|------|--------------------|
| 객체 | `BusinessService`, `Workload`, `Resource`, `Environment`, 적용 목표, 신호, 대안, 효과, 실행 및 결과입니다. |
| 관계 | 서비스에서 워크로드와 리소스로 이어지는 영향 경로, `depends_on`, 목표 연결, 소유권, 검토한 대안, 예상 효과, 실행 및 관측 결과입니다. |
| 상태 | 출처 권한이 있는 관측 비용과 사용률, 파생된 이상 또는 예측, 희망 목표 및 실행 상태를 분리합니다. |
| 컨텍스트 | exact 개정, 근거 경로, 기준 시점, 최신성, 완전성, 충돌, 제외 사항 및 자율성 상한입니다. |
| 작업 | exact `ActionType`, 대상 개정, 사전 조건, 중단 조건, 영향 제한, dry-run, 잠금, 멱등성, 롤백 및 사후 조건입니다. |

최소 결정 프레임에는 다음 내용이 포함됩니다.

1. **식별자:** 활성 온톨로지 release를 통해 확인된 하나의 exact 대상 또는 범위가 제한된 대상 집합입니다.
2. **운영 범위:** 도달 가능한 서비스, 워크로드, 의존성, 환경, 소유권 및 명시적인
   `unknown_service` 또는 잘림 표시입니다.
3. **의도:** 같은 기준 시점에 유효한 `CostObjective`, `ServiceObjective`,
   `RecoveryObjective`, `ArchitectureConstraint` 및 `ChangeWindow` 기록입니다.
4. **근거:** 이벤트, 유효, 기록 및 기준 시점이 있는 인증된 비용, 사용률, 토폴로지, 정책, 예측
   및 이전 결과 참조입니다.
5. **대안:** no-action 기준선과 예상 비용, 신뢰성, 용량, 복구 및 가역성 효과가 있는 범위가
   제한된 `ActionOption` 집합입니다.
6. **안전성:** exact ActionType 계약, 정책 결과, dry-run 증적, 대상 잠금, 영향 범위, 중단 조건,
   롤백 준비 상태 및 안정적인 멱등성 키입니다.

누락되거나 모순되는 내용이 있다고 자동으로 사람 검토를 요구하지는 않습니다. 먼저 아래의 범위가
제한된 복구 단계를 실행합니다. 추측한 서비스 매핑, 합성 목표, 검증되지 않은 관계, 오래된 비용
값 또는 모델이 작성한 권한으로 내용을 대체할 수 없습니다.

## 온톨로지 역량 게이트

결정론적 fixture가 다음 질문에 답하기 전에는 vertical을 활성화할 준비가 되지 않은 상태입니다.

| 게이트 | 질문과 필요한 결과 |
|--------|--------------------|
| F1 - 대상 | 후보가 어떤 exact 리소스, 워크로드 및 서비스에 영향을 줍니까? 알 수 없거나 잘린 범위를 명시적으로 유지합니다. |
| F2 - 의도 | 기준 시점에 어떤 비용, 서비스, 복구, 아키텍처 및 시간 구간 제약이 적용됩니까? |
| F3 - 근거 | 어떤 사실이 최신이고 완전하며 독립적으로 검증되었거나, 충돌하거나, 합성이거나, 사용할 수 없습니까? |
| F4 - 대안 | 어떤 no-action 대안과 변경 대안을 비교했으며 어떤 강한 제약이 대안을 제거했습니까? |
| F5 - 효과 | 각 대안에 어떤 비용 및 비비용 효과가 예측되며 불확실성과 반증 조건은 무엇입니까? |
| F6 - 권한 | 선택된 경로를 어떤 Rule, ActionType, risk 결과, 상시 권한 또는 사람 승인이 허용합니까? |
| F7 - 정산 | 실행 출력을 관측으로 취급하지 않고 독립 관측으로 각 예상 효과를 확인했습니까? |
| F8 - 학습 | Rule 후보를 제안하기 전에 exact 컨텍스트, 결정, 실행 및 결과를 replay할 수 있습니까? |

## 15개 에이전트 책임 모델

15개 에이전트는 모두 기존 이름, 소유 ObjectType, 토픽 및 권한을 유지합니다. 모든 에피소드가 모든
에이전트를 호출할 필요는 없지만 vertical은 각 책임에 유효한 경로를 제공해야 합니다.

| 에이전트 | FinOps 책임 | 참여 방식 |
|----------|-------------|-----------|
| Huginn | 범위가 제한된 프로바이더, 청구, inventory, 변경 및 일정 ingress를 소유한 `Event` 또는 `Change` 기록으로 정규화합니다. | 필수 ingress |
| Heimdall | 이상, drift, forecast 및 근거 상태 기록을 생성한 뒤 최종 관측을 모든 예상 효과와 독립적으로 비교합니다. | 필수 감지 및 변경 상태 종료 |
| Njord | `CostAnomaly`와 `Budget` advisory object 및 비용 목표 해석을 소유합니다. 주입된 `CostEstimator`는 에이전트나 publisher가 되지 않고 프로바이더에 연결된 추정값을 제공합니다. | 비용 판단에 필수 |
| Freyr | 절감이 포화나 여유 용량 손실을 숨기지 않도록 용량 예측과 크기 조정 조언을 제공합니다. | 용량에 영향을 주는 대안에 필수 |
| Loki | 불확실성 때문에 운영 환경 추측 대신 실험이 필요할 때 범위가 제한되고 항상 검토되는 복원력 실험을 제안합니다. | 조건부 검증 |
| Muninn | replay와 T1 재사용을 위해 변경할 수 없는 컨텍스트 색인, 상태 스냅샷, 이전 사례 및 exact 변경 개정을 보존합니다. | 재사용과 학습에 필수 |
| Forseti | 결정 컨텍스트를 구체화하고 헌법상 부적격한 대안을 제거하고 T0/T1/T2로 판단한 뒤 `Verdict`를 게시합니다. | 필수 판단 |
| Odin | 비용이 신뢰성, 용량, 복구 또는 포트폴리오 목표와 충돌할 때 적격 대안만 순위를 정합니다. | 조건부 중재 |
| Var | 정책이나 남은 위험이 요구할 때 분리된 사람 승인과 quorum을 기록합니다. | 남은 사례만 처리 |
| Thor | 적격 ActionType을 단독으로 발송하고 `ActionRun`과 `ActionAttempt`를 소유합니다. | 변경에 필수 |
| Vidar | 중단 조건, 효과 실패 또는 회귀에 복구가 필요할 때 복구 준비 상태를 검증하고 롤백을 소유합니다. | 필수 복구 의존성 |
| Saga | 의도와 최종 감사를 추가하고 correlation을 보존하며 에피소드를 안전하게 종료할 수 없을 때 통제된 Issue를 엽니다. | 필수 hard dependency |
| Norns | 활성 카탈로그를 바꾸지 않고 감사된 cohort를 분석해 비활성 `RuleCandidate` 또는 `Pattern` 기록을 제안합니다. | off-path 학습 |
| Mimir | 카탈로그 거버넌스를 통해 FinOps Rule과 Policy를 검증하고 회귀 검사하고 shadow 처리하고 promotion, revoke 및 versioning을 수행합니다. | 통제된 개선 |
| Bragi | 운영자 locale로 컨텍스트, 대안, 근거 미비점, 결정, 승인 및 결과를 설명합니다. 작업 요청은 타입이 지정된 ingress로 다시 들어갑니다. | 읽기 전용 상호 작용 |

## 타입이 지정된 이벤트 choreography

패키지는 handler와 프로필을 기존 소유 토픽에 연결합니다. 직접 에이전트 호출이나 비공개 Workflow
버스를 만들지 않습니다.

| 단계 | 소유 메시지 경로 |
|------|------------------|
| ingress와 감지 | Huginn `object.event` 또는 `object.change` -> Heimdall 관측과 Njord 비용 조언 |
| 교차 도메인 근거 | Heimdall `object.anomaly`, `object.drift` 또는 `object.forecast`, Njord `object.cost-anomaly`, Freyr `object.capacity-forecast`, Loki `object.chaos-experiment` |
| 판단과 충돌 | Forseti `object.verdict`, 필요하면 `object.arbitration-request` -> Odin `object.arbitration-decision` |
| 승인과 작업 | Thor가 Verdict를 소비하고 Var가 `object.approval`을 소유하며 Thor만 `object.action-run`을 소유합니다. |
| 복구와 종료 | Vidar가 `object.rollback`을 소유하고 Heimdall이 최종 작업 효과를 관측하며 Saga가 `object.audit-entry`를 추가합니다. |
| 학습 | Muninn이 범위가 제한된 `object.context-index`를 게시하고 Norns가 비활성 `object.rule-candidate`를 게시하며 Mimir가 검토된 `object.rule` 또는 `object.policy`를 게시합니다. |

at-least-once 전달은 안정적인 correlation과 멱등성 식별자를 사용합니다. 리소스별 순서 지정,
중복 억제, deadline, backpressure, dead-letter 처리, 재시작 replay 및 최종 감사는 다른 vertical과
동일하게 적용됩니다.

## 범위가 제한된 자율 복구

정책이 허용하는 경우 선택적 에피소드가 사람 승인에 도달하기 전에 책임 에이전트가 다음 단계를
순서대로 시도합니다.

1. 새로운 기준 시점에서 컨텍스트를 다시 구체화하고 여러 release가 섞인 근거를 차단합니다.
2. 누락된 비용, 토폴로지, 목표 또는 효과 사실을 독립 출처에 질의합니다.
3. 해결되지 않은 사실에 의존하거나 강한 목표를 위반하는 대안을 제거합니다.
4. 의도를 보존하면서 대상 집합, 기간, 용량 변화 또는 영향 범위를 줄입니다.
5. 전체 안전장치가 있는 되돌릴 수 있는 대안이나 타입이 지정된 no-action 기준선을 선택합니다.
6. 근거가 나중에 도착할 수 있으면 범위가 제한된 재시도 또는 정산 deadline과 함께 에피소드를 보류합니다.
7. 남은 모호성, 정책상 필수 승인, 되돌릴 수 없는 효과 또는 상시 권한 밖의 위험에만 Var로 보냅니다.

no-op은 이유, 결정 프레임 및 최종 감사를 기록할 때만 자율 처리로 계산합니다. 구현이 아무 작업도
하지 않아 자율성 수치를 부풀리지 않도록 no-op, 유익한 작업, 차단, 롤백 및 승인 결과를 분리해
보고합니다.

## 효과 정산과 학습

선택된 모든 대안은 실행 전에 하나 이상의 예상 효과를 선언합니다. Heimdall은 설정된 horizon과
telemetry grace 뒤에 독립적인 authoritative 관측으로 각 효과를 종료합니다. 관측이 누락되면
평가할 수 없는 상태로 남습니다. 개입 작업이나 불완전한 telemetry가 있으면 성공이 아니라 censored
에피소드로 표시합니다.

Saga는 완전한 계보를 봉인하고 Muninn은 replay 가능한 사례를 색인합니다. Norns는 성공과 함께
실패, 거절, no-op, 롤백 또는 재발이 포함된 검증된 cohort에서만 학습합니다. Mimir는 생성된 Rule
후보를 독립적으로 검증하고 회귀 및 shadow 게이트를 실행하며 authoritative promotion 레지스트리를
사용합니다. 학습은 패키지, 온톨로지 커널, `AgentSpec` 또는 활성 카탈로그를 직접 편집하지 않습니다.

## 자율성 측정

수락한 모든 FinOps 에피소드를 대상으로 자율 처리를 측정하고 정책으로 제외된 에피소드를 별도로
보고합니다. 기본 비율은 사람 승인 없이 종료된 에피소드를 적격 에피소드로 나눈 값입니다. 보조
지표에는 유익한 작업, no-op, 차단, 롤백, 미해결, 근거 복구, 정산 완전성, 정책 이탈 및 목표 회귀
비율이 포함됩니다.

promotion에는 고정된 시나리오 집합에 대해 설정된 최소 cohort와 임곗값이 필요합니다. 높은 자율성
비율로 정책 이탈, 감사 누락, 롤백 실패, 오래된 온톨로지 컨텍스트 또는 검증되지 않은 효과를 상쇄할
수 없습니다. 운영 주장은 보존된 exact-revision 증적이 필요합니다. 단위 테스트는 동작을 입증하지만
운영 자율성을 입증하지는 않습니다.

## 성능 저하 동작

- Saga 또는 Vidar가 없으면 새 변경을 관찰 모드로 강제합니다.
- Forseti가 없으면 대체 판단을 만들지 않습니다. 근거는 계속 대기열에 보존합니다.
- Heimdall이 없으면 효과를 독립적으로 종료할 수 없으므로 변경 상태 성공을 차단합니다.
- Njord, Freyr 또는 필수 온톨로지 컨텍스트가 없으면 영향을 받는 대안을 보류 또는 승인으로 낮춥니다.
- Odin이 없으면 해결되지 않은 교차 목표 충돌을 로컬 tie-breaking 없이 승인으로 보냅니다.
- Var가 없으면 승인 대기열을 보존합니다. 침묵은 권한을 부여하지 않습니다.
- Norns, Mimir, Muninn 학습 입력 또는 Bragi가 없으면 학습이나 설명 기능이 줄어들지만 활성 결정 및
  안전 경로를 우회하지 않습니다.

## 비목표

- pantheon 에이전트 추가, 제거, 이름 변경 또는 역할 변경
- 온톨로지, 모델 또는 패키지를 행위자나 권한 출처로 취급
- 선언된 책임이 관련되지 않은 에피소드에도 모든 에이전트 실행 요구
- 서비스, 복구, 보안, 신원 또는 데이터 무결성 목표를 위반하는 비용 최적화
- 발송, 프로바이더 수락 또는 예상 절감액을 검증된 결과로 계산

## 관련 문서

| 자세히 알아볼 내용 | 문서 |
|--------------------|------|
| 구독 분석, SKU 결정 및 Console 작업 영역 | [FinOps 리소스 효율 및 SKU 결정](finops-resource-efficiency-ko.md) |
| 패키지와 활성화 경계 | [온톨로지 기반 FinOps 패키지 아키텍처](finops-package-architecture-ko.md) |
| 전달 wave와 종료 게이트 | [FinOps 패키지 전달 계획](../fork-and-sequencing/finops-package-delivery-plan-ko.md) |
| 구현 상태 | [FinOps Autonomous Operations implementation ledger](../../roadmap-implementation/architecture/finops-autonomous-operations.md) |
| 공유 운영 의미 | [FDAI 운영 온톨로지](operating-ontology-ko.md) |
| 고정 에이전트 소유권 | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
| 기존 비용 인식 에이전트 흐름 | [에이전트 Workflow](../agents/agent-workflows-ko.md#1-cost-aware-fix) |
