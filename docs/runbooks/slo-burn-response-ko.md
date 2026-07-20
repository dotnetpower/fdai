---
title: SLO Burn 대응 Runbook
description: 발견된 오류 예산 소진 문제를 검증하고 통제된 대응으로 라우팅하는 템플릿입니다.
translation_of: slo-burn-response.md
translation_source_sha: b6165b4f1b729facd55ac723442c592711b6cf97
translation_revised: 2026-07-20
---

# SLO Burn 대응 Runbook

Workload service-level objective (SLO)가 `slo.error_budget_burn`을 생성할 때 이 runbook을
사용합니다. Objective와 source data를 검증하고 short 및 long-window burn을 확인하며 관련
context를 correlation하고 missing data를 healthy로 처리하지 않으면서 governed incident
response로 라우팅합니다.

> Threshold, objective value, metric query, notification route는 downstream fork가 제공하는
> configuration입니다. 이 템플릿은 하나의 universal burn policy를 정의하지 않습니다.

## 진입 기준과 ownership

Finding ID, SLO 및 service ID, evaluated window, source timestamp, configured route를 가지고
시작합니다. Verification owner를 지정하고 더 깊은 investigation을 시작하기 전에 next
decision deadline을 기록합니다.

| 필수 입력 | 검증할 내용 |
|-----------|-------------|
| SLO version | Objective, indicator, target, evaluation period, owner |
| Metric source | Query 또는 projection, aggregation, dimension, freshness |
| Burn window | Short 및 long window boundary, threshold, sample count |
| Error budget | Active period의 consumed 및 remaining budget |
| Scope | Service, region, operation, dependency, explicit exclusion |
| Context | Deployment, maintenance, capacity event, open incident |

## Finding 검증

1. Finding이 현재 active SLO version을 참조하는지 확인합니다.
2. Objective의 measured signal인 service-level indicator (SLI)가 intended scope와 dimension을
	사용하는지 확인합니다.
3. Source health, ingestion delay, sampling, missing-data behavior를 검사합니다.
4. 동일 source에서 configured window 두 개를 recompute하거나 독립적으로 검사합니다.
5. Breach를 rounding으로 없애지 말고 threshold comparison과 remaining error budget을 확인합니다.
6. Finding timestamp를 deployment, maintenance, capacity, incident와 비교합니다.

Finding이 invalid이면 이유를 기록하고 labeled case를 [alert tuning](alert-tuning-ko.md)으로
라우팅합니다. 단순히 noise로 종료하지 않습니다.

## 대응 절차

1. **Baseline을 기록합니다.** Window value, error budget, source freshness, affected
	dimension, current user impact를 수집합니다.
2. **Incident를 확인합니다.** Stable correlation key를 사용해 기존 correlated incident를
	갱신하거나 새 incident를 생성합니다.
3. **Severity를 설정합니다.** Configured severity policy를 measured user impact, burn,
	duration, scope에 적용합니다. Burn alert만으로 policy를 우회하지 않습니다.
4. **지정하고 알립니다.** Configured owner를 선택하고 durable notification을 보내며
	delivery 또는 fallback outcome을 확인합니다.
5. **Context를 조사합니다.** Recent change, capacity, dependency, related finding에 대해
	bounded investigation을 시작합니다.
6. **Mitigation을 준비합니다.** Proposed change마다 evidence, intended effect, scope,
	what-if result, stop condition, rollback을 기록합니다.
7. **Proposal을 라우팅합니다.** Typed action을 risk 및 approval policy로 보냅니다.
8. **Recovery를 관찰합니다.** SLO를 stable로 선언하기 전에 configured recovery period
	동안 두 burn window를 계속 관찰합니다.

## 결정 분기

| Finding state | 대응 |
|---------------|------|
| 두 window가 breach되고 impact가 확인됨 | 즉시 incident를 triage하거나 갱신합니다. |
| Short window만 breach됨 | Next deadline까지 모니터링하고 acute context를 검사합니다. |
| Short-window spike 없이 long window가 breach됨 | Sustained degradation과 budget trend를 조사합니다. |
| Burn은 valid지만 visible user impact가 없음 | Finding을 active로 유지하고 budget exhaustion 전에 조사합니다. |
| Source 또는 SLI scope가 invalid임 | Invalid finding을 기록하고 measured alert tuning을 시작합니다. |
| 기존 incident가 이미 scope를 포함함 | Duplicate를 생성하지 말고 해당 incident에 evidence를 추가합니다. |

## 중지 조건

Sample이 오래됐거나 SLI scope가 잘못됐거나 missing data를 0으로 취급했거나 rollback 및
window boundary가 configuration과 다르거나 impact bound가 없으면 중지합니다. Incident가
concurrent하게 변경되면 state transition을 중지하고 refresh한 뒤 decision을 반복합니다.

## 검증과 recovery

Recovery에는 healthy sample 하나보다 많은 evidence가 필요합니다. 다음 항목을 검증합니다.

- **Window**: Short 및 long burn value가 configured recovery condition보다 낮게 유지됩니다.
- **Budget**: Mitigation 후 remaining error budget과 projection이 기록됩니다.
- **Impact**: Affected operation과 dependency가 health check를 통과합니다.
- **Change**: 모든 mitigation에 known active version과 rollback reference가 있습니다.
- **Incident**: State가 defined review deadline이 있는 monitoring으로 이동합니다.

Mitigation이 burn 또는 다른 guard condition을 악화시키면 [incident mitigation과
rollback](incident-mitigation-and-rollback-ko.md)을 따릅니다.

## Evidence와 audit

SLO version, window value, source timestamp, incident ID, proposal ID, verdict,
terminal outcome을 기록합니다. SLI dimension, source-health check, error-budget value,
correlation context, notification outcome, recovery window도 기록합니다.

## 완료 기준

Finding이 valid 또는 invalid로 분류되고 incident와 owner가 알려져 있으며 모든 proposal에
terminal verdict가 있고 SLO가 recovery window를 통과했거나 next decision deadline과 함께
open 상태로 유지되면 response를 완료합니다. Invalid finding은 labeled tuning scenario로
보존합니다.

## 관련 runbook

| 다음 작업 | 문서 |
|-----------|------|
| Incident scope와 ownership 설정 | [Incident triage](incident-triage-ko.md) |
| Invalid 또는 noisy detector 개선 | [Alert tuning](alert-tuning-ko.md) |
| Verified response 안전하게 실행 | [Incident mitigation과 rollback](incident-mitigation-and-rollback-ko.md) |
