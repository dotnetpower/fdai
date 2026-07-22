---
title: 재해 복구와 훈련
description: FDAI가 예약되고 격리되며 증거를 남기는 restore 및 failover exercise로 복구 경로를 증명하는 방법입니다.
translation_of: disaster-recovery-and-drills.md
translation_source_sha: 0c211aa9fa5cc3648a95f0a018f7d3ba57db3495
translation_revised: 2026-07-22
---

# 재해 복구와 훈련

재해 복구(Disaster Recovery, DR)는 outage 전에 recovery path를 훈련하고 측정해야 신뢰할
수 있습니다. FDAI는 범위가 제한된 drill을 예약하고 격리된 target에 복원하며 recovery
objective를 검증하고 cleanup 및 audit evidence를 기록합니다.

## 훈련 계획

Drill은 protected workload, target RPO 및 RTO, exercise window, isolated destination,
owner, stop condition, 영향 범위, cleanup plan, evidence requirement를 선언합니다.
Verification restore는 production data를 덮어쓰지 않습니다.

## 훈련 라이프사이클

1. Backup readiness, restore window, identity, quota, destination isolation을 확인합니다.
2. Restore point를 선택하고 expected RPO를 기록합니다.
3. 새로 격리한 resource group 또는 동등 scope에 복원합니다.
4. Connectivity, schema, integrity, application-level verification을 실행합니다.
5. 달성한 RPO와 RTO를 objective와 비교해 측정합니다.
6. Evidence를 기록하고 temporary resource를 제거한 뒤 cleanup을 검증합니다.

## Fail closed

Source identity가 모호하거나 destination이 production에 영향을 줄 수 있거나 backup metadata가
없거나 verification이 불완전하거나 cleanup을 보장할 수 없으면 drill을 중지합니다. 실패한
drill은 recovery gap의 증거이며 workload를 healthy로 표시할 이유가 아닙니다.

## 승격과 주기

새 drill automation은 shadow에서 시작합니다. Scheduler가 cadence를, 안전성 검토가 scope와
execution eligibility를, audit log가 proof를 담당합니다. 승격에는 반복 가능한 성공과 정책
위반 escape 0건이 필요합니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 상세 database 절차 | [Deep DB-DR 복원 훈련](../../runbooks/db-dr-drill-ko.md) |
| Failure injection이 DR을 보완하는 방법 | [카오스 엔지니어링](chaos-engineering-ko.md) |
| 복구를 측정하는 방법 | [SRE 성과 측정](measuring-sre-outcomes-ko.md) |
| Resilience capability | [회복탄력성](../capabilities/resilience-ko.md) |
