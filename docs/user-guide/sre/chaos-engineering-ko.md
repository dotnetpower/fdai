---
title: 카오스 엔지니어링
description: FDAI가 제한된 target, stop condition, recovery evidence를 사용해 catalog-driven fault experiment를 실행하는 방법입니다.
translation_of: chaos-engineering.md
translation_source_sha: 3308e4fdc9c58ff63cf85ab53f4e673263a1dd61
translation_revised: 2026-07-22
---

# 카오스 엔지니어링

카오스 엔지니어링은 알려진 fault에서 workload와 recovery control이 예상대로 작동하는지
검증합니다. FDAI는 experiment를 명시적인 target, probe, 영향 범위, stop condition,
rollback, audit evidence가 있는 catalog entry로 표현합니다.

## 시나리오 계약

Fault scenario는 hypothesis, supported resource type, injector, steady-state probe, approved
target, maximum duration, stop condition, rollback, promotion gate를 선언합니다. Catalog schema
validation은 불완전한 scenario가 실행되기 전에 거부합니다.

## 안전한 실험 흐름

1. 승격된 scenario를 선택하고 target eligibility를 검증합니다.
2. Fault를 주입하지 않고 preflight 및 steady-state probe를 실행합니다.
3. 범위가 제한된 target set과 필요한 approval을 확인합니다.
4. Console identity가 아니라 설정된 provider를 통해 주입합니다.
5. Stop condition과 health probe를 계속 평가합니다.
6. Rollback하고 recovery를 검증하며 outcome을 기록합니다.

## Fault injection 전 shadow

Shadow에서 FDAI는 fault를 주입하지 않고 target selection, policy, expected probe, 실행됐을
action을 평가합니다. 승격은 scenario 및 scope별로 수행합니다. 새 scenario는 다른 scenario의
evidence를 상속하지 않습니다.

## 중지와 복구 규칙

Target set이 확대되거나 protected dependency가 저하되거나 probe freshness를 잃거나
experiment가 duration을 초과하거나 rollback을 사용할 수 없거나 audit write가 실패하면 즉시
중지합니다. Recovery verification은 optional cleanup이 아니라 experiment outcome의 일부입니다.

## 커버리지와 증거

Failure mode 및 resource type별 scenario coverage, probe reliability, abort rate, rollback
success, recovery time, unexpected impact를 추적합니다. Recovery가 검증되지 않은 successful
injection은 성공한 experiment가 아닙니다.

[시나리오 검증 인벤토리](scenario-validation-inventory-ko.md)는 catalog entry 132개,
shadow-coverage pack 18개, live 적용 모드 validation 10개, 별도 frozen control-loop scenario를
서로 구분합니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 복구를 훈련하는 방법 | [재해 복구와 훈련](disaster-recovery-and-drills-ko.md) |
| 모든 scenario와 evidence level | [시나리오 검증 인벤토리](scenario-validation-inventory-ko.md) |
| 영향 범위를 관리하는 방법 | [리스크 티어](../concepts/risk-tiers-ko.md) |
| 운영자 절차 | [Chaos game day runbook](../../runbooks/chaos-game-day-ko.md) |
| Resilience capability | [회복탄력성](../capabilities/resilience-ko.md) |
