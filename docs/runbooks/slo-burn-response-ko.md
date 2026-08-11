---
title: SLO Burn 대응 Runbook
description: 발견된 오류 예산 소진 문제를 검증하고 통제된 대응으로 라우팅하는 템플릿입니다.
translation_of: slo-burn-response.md
translation_source_sha: 2fc1abd5d40cb69d776c4e31eb9a547754d0fba6
translation_revised: 2026-08-11
---

# SLO Burn 대응 런북

워크로드 service-level 목표 (SLO)가 `slo.error_budget_burn`을 생성할 때 이 런북을
사용합니다. 목표와 출처 데이터를 검증하고 short 및 long-window burn을 확인하며 관련
맥락을 상관관계하고 누락된 데이터를 healthy로 처리하지 않으면서 통제된 인시던트
응답으로 라우팅합니다.

> 임계값, 목표 값, 메트릭 조회, 알림 경로는 다운스트림 포크가 제공하는
> 구성입니다. 이 템플릿은 하나의 universal burn 정책을 정의하지 않습니다.

## 진입 기준과 소유권

발견된 문제 ID, SLO 및 서비스 ID, evaluated 구간, 출처 시각, 구성된 경로를 가지고
시작합니다. 검증 소유자를 지정하고 더 깊은 조사를 시작하기 전에 next
결정 기한을 기록합니다.

| 필수 입력 | 검증할 내용 |
|-----------|-------------|
| SLO 버전 | 목표, indicator, 대상, evaluation 기간, 소유자 |
| 메트릭 출처 | 조회 또는 변환 결과, 집계, dimension, 최신성 |
| Burn 구간 | Short 및 long 구간 경계, 임계값, 샘플 개수 |
| 오류 예산 | 활성 기간의 consumed 및 remaining 예산 |
| 범위 | 서비스, 지역, 연산, 의존성, 명시적 exclusion |
| 맥락 | 배포, maintenance, 용량 이벤트, 열림 인시던트 |

## 발견된 문제 검증

1. 발견된 문제가 현재 활성 SLO 버전을 참조하는지 확인합니다.
2. 목표의 measured 신호인 service-level indicator (SLI)가 intended 범위와 dimension을
	사용하는지 확인합니다.
3. 출처 상태, 인제스트 delay, sampling, missing-data 행동을 검사합니다.
4. 동일 출처에서 구성된 구간 두 개를 recompute하거나 독립적으로 검사합니다.
5. Breach를 rounding으로 없애지 말고 임계값 비교와 remaining 오류 예산을 확인합니다.
6. 발견된 문제 시각을 배포, maintenance, 용량, 인시던트와 비교합니다.

발견된 문제가 잘못된이면 이유를 기록하고 labeled 사례를 [경보 튜닝](alert-tuning-ko.md)으로
라우팅합니다. 단순히 noise로 종료하지 않습니다.

## 대응 절차

1. **기준선을 기록합니다.** 구간 값, 오류 예산, 출처 최신성, affected
	dimension, 현재 user 영향을 수집합니다.
2. **인시던트를 확인합니다.** 고정된 상관관계 키를 사용해 기존 correlated 인시던트를
	갱신하거나 새 인시던트를 생성합니다.
3. **심각도를 설정합니다.** 구성된 심각도 정책을 measured user 영향, burn,
	소요 시간, 범위에 적용합니다. Burn 경보만으로 정책을 우회하지 않습니다.
4. **지정하고 알립니다.** 구성된 소유자를 선택하고 영속 알림을 보내며
	전달 또는 대체 경로 결과를 확인합니다.
5. **맥락을 조사합니다.** Recent 변경, 용량, 의존성, related 발견된 문제에 대해
	범위가 제한된 조사를 시작합니다.
6. **완화를 준비합니다.** Proposed 변경마다 근거, intended 효과, 범위,
	what-if 결과, stop 조건, 롤백을 기록합니다.
7. **제안을 라우팅합니다.** 타입이 지정된 액션을 risk 및 승인 정책으로 보냅니다.
8. **복구를 관찰합니다.** SLO를 고정된으로 선언하기 전에 구성된 복구 기간
	동안 두 burn 구간을 계속 관찰합니다.

## 결정 분기

| 발견된 문제 상태 | 대응 |
|---------------|------|
| 두 구간이 breach되고 영향이 확인됨 | 즉시 인시던트를 분류하거나 갱신합니다. |
| Short 구간만 breach됨 | Next 기한까지 모니터링하고 acute 맥락을 검사합니다. |
| Short-window spike 없이 long 구간이 breach됨 | Sustained 성능 저하와 예산 trend를 조사합니다. |
| Burn은 valid지만 visible user 영향이 없음 | 발견된 문제를 활성으로 유지하고 예산 exhaustion 전에 조사합니다. |
| 출처 또는 SLI 범위가 잘못된임 | 잘못된 발견된 문제를 기록하고 measured 경보 튜닝을 시작합니다. |
| 기존 인시던트가 이미 범위를 포함함 | 중복을 생성하지 말고 해당 인시던트에 근거를 추가합니다. |

## 중지 조건

샘플이 오래됐거나 SLI 범위가 잘못됐거나 누락된 데이터를 0으로 취급했거나 롤백 및
구간 경계가 구성과 다르거나 영향 한계가 없으면 중지합니다. 인시던트가
동시하게 변경되면 상태 전이를 중지하고 새로 고침한 뒤 결정을 반복합니다.

## 검증과 복구

복구에는 healthy 샘플 하나보다 많은 근거가 필요합니다. 다음 항목을 검증합니다.

- **구간**: Short 및 long burn 값이 구성된 복구 조건보다 낮게 유지됩니다.
- **예산**: 완화 후 remaining 오류 예산과 변환 결과가 기록됩니다.
- **영향**: Affected 연산과 의존성이 상태 검사를 통과합니다.
- **변경**: 모든 완화에 known 활성 버전과 롤백 참조가 있습니다.
- **인시던트**: 상태가 defined 검토 기한이 있는 모니터링으로 이동합니다.

완화가 burn 또는 다른 가드 조건을 악화시키면 [인시던트 완화와
롤백](incident-mitigation-and-rollback-ko.md)을 따릅니다.

## 근거와 감사

SLO 버전, 구간 값, 출처 시각, 인시던트 ID, 제안 ID, 결정,
최종 결과를 기록합니다. SLI dimension, source-health 검사, error-budget 값,
상관관계 맥락, 알림 결과, 복구 구간도 기록합니다.

## 완료 기준

발견된 문제가 valid 또는 잘못된으로 분류되고 인시던트와 소유자가 알려져 있으며 모든 제안에
최종 판정이 있고 SLO가 복구 구간을 통과했거나 next 결정 기한과 함께
열림 상태로 유지되면 응답을 완료합니다. 잘못된 발견된 문제는 labeled 튜닝 시나리오로
보존합니다.

## 관련 런북

| 다음 작업 | 문서 |
|-----------|------|
| 인시던트 범위와 소유권 설정 | [인시던트 분류](incident-triage-ko.md) |
| 잘못된 또는 noisy detector 개선 | [경보 튜닝](alert-tuning-ko.md) |
| 검증된 응답 안전하게 실행 | [인시던트 완화와 롤백](incident-mitigation-and-rollback-ko.md) |
