---
title: 사이트 신뢰성 엔지니어링
description: 신호와 인시던트부터 대응, 복구, 학습까지 이어지는 FDAI의 SRE 운영 모델입니다.
translation_of: README.md
translation_source_sha: 56fbb769b0381195abe4abe5a970574249681d57
translation_revised: 2026-07-22
---

# 사이트 신뢰성 엔지니어링

사이트 신뢰성 엔지니어링(Site Reliability Engineering, SRE)은 FDAI의 세 초기
버티컬을 연결하는 운영 discipline입니다. Change Safety는 변경 리스크를 낮추고, Cost
Governance는 효율성을 관리하며, Resilience는 복구 가능성을 증명합니다. SRE는 이
기능들을 관찰, 대응, 학습, 대비로 이어지는 하나의 증거 기반 라이프사이클로 묶습니다.

이 섹션은 운영자를 위한 지도입니다. FDAI가 구현한 기능, 사람 승인이 필요한 지점,
배포 환경이나 downstream fork가 제공해야 하는 통합을 설명합니다.

## 무엇을 할 수 있나요?

### 신호 폭풍을 하나의 인시던트로 정리

관련 리소스 이벤트, telemetry 발견된 문제, 변경을 안정적인 멤버십과 시간 순서를 가진
하나의 인시던트로 연계합니다.

예시: 다섯 개의 알림이 동일한 배포 및 리소스 키를 공유 -> 이벤트 상관관계가 인시던트
하나를 생성 -> 운영자는 다섯 페이지가 아니라 하나의 타임라인을 분류합니다.

### 변경을 제안하기 전에 조사

범위가 제한된 증거를 수집하고, 근거가 있는 근본 원인 가설을 생성하며, 모든 완화
제안을 trust-router, 안전성 검토, 승인 정책 뒤에 둡니다.

예시: 오류율 알림 -> 조사가 최근 배포를 연계 -> RCA가 변경과 telemetry를 인용 ->
대응 계획이 rollback을 제안 -> 사람 승인이 제안을 액션 파이프라인에 다시 넣을지 결정.

### 실패를 숨기지 않고 학습

추가 전용 감사 이력, 포스트모템 초안, shadow 결과, rollback 증거를 사용해 규칙과
runbook을 개선합니다. 학습 구성 요소가 정책을 직접 변경하도록 허용하지 않습니다.

예시: 해결된 인시던트 -> 포스트모템이 타임라인과 액션 결과를 추출 -> provenance가
있는 카탈로그 후보 제안 -> 일반 검토 및 승격 게이트를 그대로 통과.

## 연동 대상

- **Azure 신호**: Activity Log 이벤트, 리소스 인벤토리, 배포 이력, 서비스 메트릭이
  provider adapter를 통해 들어옵니다.
- **Telemetry 시스템**: metric, log, trace provider는 증거를 공급하지만 두 번째 실행
  경로가 되지 않습니다.
- **Git과 ChatOps**: 수정 pull request가 변경을 전달하고, Teams 또는 Slack이
  승인과 운영 알림을 전달합니다.
- **감사와 리포팅**: 모든 최종 결과는 추가 전용 감사 레코드와 correlation 참조로
  재구성할 수 있습니다.

## 작동 방식

1. **관찰하고 연계합니다.** 이벤트와 발견된 문제를 정규화 및 중복 제거하고, 관련 멤버를
   하나의 인시던트로 묶습니다.
2. **조사하고 대응합니다.** 범위가 제한된 증거 세트를 만들고 grounded RCA를 도출한
   다음, 모든 완화 제안을 governed action pipeline으로 보냅니다.
3. **복구하고 학습합니다.** 복구를 검증하고 최종 감사 레코드를 쓰며 포스트모템을
   작성한 뒤 증거 기반 개선 후보를 제안합니다.

```text
signals -> finding -> incident -> investigation -> RCA
        -> response plan -> risk gate -> action or approval
        -> recovery evidence -> postmortem -> improvement candidate
```

## 모든 대응을 제어하는 두 가지 판단

Trust routing과 execution policy는 서로 다른 질문에 답합니다. Trust-router는 판단 후보를
만들 T0(결정론 규칙), T1(검증된 재사용), T2(근거 기반 추론)를 선택합니다. 안전성 검토는
policy, action type, 영향 범위, environment, evidence freshness, identity, promotion
state에서 가장 엄격한 허용 결과를 계산합니다.

| 판단 | 질문 | 가능한 결과 |
|------|------|-------------|
| Trust routing | 어떤 tier가 설명하거나 제안할 수 있는가? | T0, T1, T2 또는 검토 보류 |
| Risk gating | 이 제안이 지금 무엇을 할 수 있는가? | `auto`, `hil`, `deny` 또는 shadow-only |
| Execution | 모든 runtime 안전 검사가 여전히 유효한가? | 한 번 적용, no-op, 중지 또는 rollback |

T0 match가 변경 권한을 자동으로 부여하지 않으며 T2 proposal이 스스로 권한을 부여할 수도
없습니다. 실행 가능한 모든 action에는 계속 dry run, stop condition, rollback path,
영향 범위 limit, fresh inventory, per-resource lock, idempotency key, authorized identity,
audit record가 필요합니다.

## 명시적 상태인 저하 운영

FDAI는 누락된 증거를 정상 상태로 바꾸지 않습니다. Provider failure는 의존 증거를
unavailable로 표시합니다. Stale inventory, audit write 실패, unavailable lock, 검증되지 않은
rollback path는 영향을 받는 action을 shadow 또는 deny로 낮춥니다. Notification failure는
durable retry 또는 escalation을 따르지만 승인이 되지 않으며, 이미 유효한 incident transition을
되돌리지도 않습니다.

## SRE 기능 지도

| 영역 | 문서 | Upstream 상태 |
|------|------|---------------|
| 관측성, 상관관계, 이상 감지, 예측 | [관측성, 감지, 예측](observability-detection-and-forecasting-ko.md) | Covered. 실제 telemetry adapter는 배포 binding입니다. |
| 워크로드 목표와 burn rate | [SLO와 오류 예산](slos-and-error-budgets-ko.md) | 실제 metric provider와 예약 trigger가 연결될 때까지 Partial입니다. |
| 용량과 성능 | [용량과 성능](capacity-and-performance-ko.md) | Covered. 자율 액션은 계속 승격 게이트를 따릅니다. |
| 인시던트 라이프사이클 | [인시던트 관리](incident-management-ko.md) | Covered |
| 범위가 제한된 증거 수집 | [분류와 조사](triage-and-investigation-ko.md) | Covered. 증거 깊이는 provider에 따라 달라집니다. |
| 근본 원인 가설 | [근본 원인 분석](root-cause-analysis-ko.md) | Covered. T2는 구성된 모델 및 knowledge binding에 의존합니다. |
| 대응 계획과 완화 | [대응 계획과 완화](response-plans-and-mitigation-ko.md) | Covered. 계획은 제안하고 라우팅하며 승인을 우회하지 않습니다. |
| 온콜과 에스컬레이션 | [온콜과 에스컬레이션](on-call-and-escalation-ko.md) | paging adapter와 DM targeting이 연결될 때까지 Partial입니다. |
| 인시던트 이후 학습 | [포스트모템과 학습](postmortems-and-learning-ko.md) | Covered |
| 성과 측정 | [SRE 성과 측정](measuring-sre-outcomes-ko.md) | baseline 및 treatment window가 있을 때 Covered입니다. |
| 시나리오 증거 | [시나리오 검증 인벤토리](scenario-validation-inventory-ko.md) | Demo 18개, live 적용 모드 10개, frozen replay 9개, catalog scenario 132개 |
| 재해 복구 | [재해 복구와 훈련](disaster-recovery-and-drills-ko.md) | 제공되는 drill과 adapter 범위에서 Covered입니다. |
| 카오스 엔지니어링 | [카오스 엔지니어링](chaos-engineering-ko.md) | Covered. 모든 scenario는 shadow에서 시작합니다. |

> 상태 페이지 broadcast와 DORA 배포 메트릭은 Deferred 상태입니다. Provider 및 데이터
> 계약을 구현하기 전에는 사용 가능한 SRE 기능으로 표시하지 않습니다.

## 환경과 함께 확장

- **Day 1**: shadow에서 신호를 수집하고 인시던트 그룹화를 확인하며 변경 없이 증거를
  검토합니다.
- **Week 1**: 워크로드 메트릭을 연결하고 초기 SLO를 정의하며 온콜 라우팅을 연결하고,
  대응 계획을 합성 또는 과거 사례에 대해 사전 테스트합니다.
- **Month 1**: 측정된 저위험 액션을 개별 승격하고 복구 훈련을 예약하며, 포스트모템
  증거를 사용해 규칙과 runbook을 개선합니다.

## 시작하기

- [관측성, 감지, 예측](observability-detection-and-forecasting-ko.md)부터 시작하세요.
- [인시던트 관리](incident-management-ko.md)에서 이벤트의 흐름을 따라가세요.
- [근본 원인 분석](root-cause-analysis-ko.md)이 grounded 상태를 유지하는 방법을 확인하세요.
- 모든 [scenario validation set](scenario-validation-inventory-ko.md)을 검토하세요.
- [SRE runbook 세트](../../runbooks/README-ko.md)로 운영자 절차를 준비하세요.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| FDAI가 T0, T1, T2를 선택하는 방법 | [신뢰 티어](../concepts/risk-tiers-ko.md) |
| 액션이 안전 계약을 상속하는 방법 | [온톨로지 기반 자동화](../concepts/ontology-driven-automation-ko.md) |
| 복구가 제품 기능이 되는 방법 | [회복탄력성](../capabilities/resilience-ko.md) |
| 증거 추적을 검사하는 방법 | [감사 로그 읽기](../guides/read-audit-log-ko.md) |
| 승인 요청에 응답이 없을 때의 동작 | [에스컬레이션과 상시 권한](../../roadmap/decisioning/escalation-and-standing-authority-ko.md) |
