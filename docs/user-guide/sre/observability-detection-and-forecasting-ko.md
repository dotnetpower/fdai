---
title: 관측성, 감지, 예측
description: FDAI가 두 번째 실행 경로를 만들지 않고 이벤트와 telemetry를 연계된 설명 가능한 발견된 문제로 바꾸는 방법입니다.
translation_of: observability-detection-and-forecasting.md
translation_source_sha: f8d6229ddd6f0e4ac5023a03dc7eea95d85df7da
translation_revised: 2026-07-22
---

# 관측성, 감지, 예측

FDAI는 관측성을 실행 surface가 아니라 증거 생성으로 다룹니다. 이벤트, 메트릭, 로그,
트레이스, 이상, 예측은 정규화된 발견된 문제가 되어 다른 모든 이벤트와 동일한 trust 및
risk pipeline에 다시 들어갑니다.

> 이벤트 상관관계, 결정론적 이상 감지, 예측은 upstream에 구현되어 있습니다. 실제
> 워크로드를 관찰하려면 배포 환경에서 metric, log, trace provider를 연결해야 합니다.

## 이 가이드에서 다루는 내용

- 원시 신호, 발견된 문제, incident, action의 차이.
- 결정론적 상관관계가 데이터를 버리지 않고 알림 노이즈를 줄이는 방법.
- 이상 및 예측 detector가 설명 가능성과 shadow-first를 유지하는 방법.
- 감지 결과를 신뢰하기 전에 운영자가 확인할 증거.

## 신호 모델

| 레코드 | 의미 | 실행 가능 여부 |
|--------|------|----------------|
| 원시 신호 | provider 이벤트, metric sample, log, trace 하나 | 불가 |
| 발견된 문제 | 정규화된 anomaly, forecast, policy observation | 불가 |
| Incident | 관련 event와 발견된 문제의 안정적인 그룹 | 불가 |
| RCA hypothesis | 인용이 있는 incident 설명 | 불가 |
| Action proposal | 안전 계약을 가진 typed change | 일반 gate 통과 후에만 가능 |

발견된 문제 자체는 변경 권한을 부여하지 않습니다. `ActionType`에 매핑되고, 검증 및 scope
검사를 통과하고, resource lock을 획득하며, policy가 요구하는 risk 결정을 받아야
합니다.

## 판단 전에 연계

상관관계는 정규화 및 중복 제거 이후에 실행됩니다. Resource, deployment, trace,
causal parent, 제한된 time window 같은 안정적인 key로 신호를 그룹화합니다. 늦게 도착한
member는 열린 incident에 합류할 수 있으며, 설정된 window를 지난 event는 연결된 후속
incident를 생성합니다.

상관관계는 레코드가 서로 관련됐음을 나타낼 뿐, 하나가 다른 하나의 원인이라고 주장하지
않습니다. 인과관계 판단은 근본 원인 분석이 담당합니다.

예시: deployment가 변경 event 하나를 생성하고 네 service에서 error 발생 -> 공유된
deployment 및 resource graph가 incident 하나를 생성 -> 원시 레코드 다섯 개는 member로
모두 유지 -> RCA가 원인을 별도로 평가.

## 설명 가능한 이상 감지

결정론적 detector는 metric을 설정된 rolling 또는 seasonal baseline과 비교합니다.
발견된 문제는 baseline, observed value, deviation, direction, window, severity를 기록하므로
운영자가 발생 이유를 재현할 수 있습니다.

- **Cold start**: 이력이 부족하면 추측하지 않고 판단 보류합니다.
- **Flat baseline**: 분산이 0인 경우를 명시적으로 처리해 0 나눗셈이나 무한 severity를
  만들지 않습니다.
- **Seasonality**: pooled 24x7 평균이 아니라 같은 시간대 또는 주간 phase와 비교합니다.
- **Composite degradation**: 여러 metric 발견된 문제가 quorum을 충족해야 compound anomaly를
  생성할 수 있습니다.
- **Change awareness**: maintenance 및 진행 중인 change는 예상된 deviation을 주석 처리하거나
  억제합니다.

Composite 감지는 또 다른 baseline이 아니라 fuser입니다. 중복 metric은 가장 강한
occurrence 하나로 축약하고, 동일한 resource와 window에서 서로 다른 member가 설정된
quorum만큼 발생할 때만 발견된 문제를 생성합니다. Quorum 미만에서는 판단 보류합니다. Quorum
이상이면 member의 범위와 결합 magnitude에 따라 severity를 높일 수 있지만, 결과는 계속
관찰 모드 발견된 문제로 유지됩니다.

## 결정론적 운영 조건 평가

유용한 조건마다 통계 baseline이 필요한 것은 아닙니다. 버전이 관리되는 operational-insight
catalog는 infrastructure, application performance, data system, SLO burn, alert quality,
cost, security, recovery hygiene를 위한 결정론적 recipe를 제공합니다. 각 recipe는
정규화된 sample에 `above`, `below`, delta, ratio, `absent`, `stale` 같은 명시적
operator를 적용합니다.

Recipe는 observed value, reference, threshold, score, explanation을 기록합니다. 불완전하거나
유한하지 않은 입력, sample 부족, 잘못된 ratio 입력은 발견된 문제를 만들지 않고 보류합니다.
Threshold와 metric binding은 catalog data에 남으므로 배포 환경에서 evaluator를 변경하지
않고 조정할 수 있습니다. 모든 recipe는 관찰 모드에서 시작하고 trust routing 전에 안정적인
중복 제거를 거치도록 event ingest에 다시 들어갑니다.

## 부재와 provider 실패 구분

Sample이 없는 성공한 query는 `absent` recipe의 증거가 될 수 있습니다. Provider error는
다릅니다. FDAI는 해당 metric을 unavailable로 표시하고 의존하는 모든 recipe를 억제하여
telemetry 장애가 workload 장애로 보고되지 않게 합니다. Stale recipe는 제한된 확장 lookback을
사용합니다. 그 범위에도 last-seen sample이 없으면 timestamp나 값을 만들어 내지 않고
보류합니다.

| 입력 상태 | Detector 동작 | 운영 의미 |
|-----------|---------------|-----------|
| 유효한 sample을 반환한 성공한 query | Recipe 또는 baseline 평가 | 증거를 사용할 수 있음 |
| 비어 있는 성공한 query | 부재를 허용하는 의미만 평가 | 부재가 증거일 수 있음 |
| Provider error | 의존 평가 억제 | 증거를 사용할 수 없음 |
| Cold 또는 stale history | 판단 보류 또는 보류 | 증거가 불충분함 |

## 임계값 위반 예측

Forecast detector는 측정된 추세가 제한된 horizon 안에서 설정된 threshold를 넘을지
추정합니다. 각 결과는 예상 위반 시각, fit quality, uncertainty band를 포함합니다. Fit이
약하거나 crossing이 불확실하면 판단 보류합니다.

일반적인 대상은 capacity exhaustion, RPO limit에 가까워지는 replication lag,
certificate expiry, budget run rate, backup-retention drift입니다.

Forecast는 결정론적 사실이 아닙니다. 발견된 문제를 생성하고 예방적 수정 pull request를
제안할 수 있지만, 제안은 계속 trust-router, verifier, 안전성 검토, 일반 승인 정책을
통과해야 합니다.

승격 전에 forecaster는 알려진 과거 위반을 backtest하고 관찰 모드에서 설정된 정확도
기준을 통과합니다. FDAI는 승격 후에도 forecast error를 추적합니다. 측정된 drift가 발생하면
forecaster를 shadow로 되돌립니다. Prediction interval은 불확실한 point-estimate breach를
억제할 수 있지만 point forecast가 예측하지 않은 breach를 만들 수는 없습니다.

## 운영자 워크플로

1. Provider, resource, time window, data freshness를 확인합니다.
2. Baseline, threshold, deviation, cold-start 상태를 검사합니다.
3. 비어 있는 성공한 query와 unavailable provider 결과를 구분합니다.
4. Incident membership과 deployment 또는 maintenance window가 신호를 설명하는지 확인합니다.
5. Correlation ID를 따라 RCA, 결정, action proposal, audit row를 확인합니다.
6. 누락된 증거는 unavailable로 처리합니다. 0이나 정상 상태로 추론하지 마세요.

## 증거와 보호 지표

Detector fire rate, cold-start abstention, false-positive rate, false-negative rate,
forecast precision 및 recall, forecast lead time, incident-to-raw-signal ratio를
추적합니다. 승격에는 고정된 scenario set에서 측정한 증거가 필요하며, 회귀가 발생하면
detector를 shadow로 되돌립니다.

## 상세 레퍼런스

구현 계약, detector 알고리즘, control-loop wiring은
[관측성과 감지](../../roadmap/rules-and-detection/observability-and-detection-ko.md)에
정의되어 있습니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 발견된 문제가 incident가 되는 방법 | [인시던트 관리](incident-management-ko.md) |
| 워크로드 영향이 우선순위를 바꾸는 방법 | [SLO와 오류 예산](slos-and-error-budgets-ko.md) |
| 원인이 상관관계와 다른 이유 | [근본 원인 분석](root-cause-analysis-ko.md) |
| 최종 증거를 검사하는 방법 | [감사 로그 읽기](../guides/read-audit-log-ko.md) |
