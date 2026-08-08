---
title: 회복탄력성
description: FDAI가 필요해지기 전에 복구를 증명하는 방법입니다. 예약된 DR 훈련, 범위가 제한된 카오스 실험, 알려진 실패 패턴에 대한 자가 치유를 다룹니다.
translation_of: resilience.md
translation_source_sha: 93b09b5000c991d81fca299829a7de4d03bef3b6
translation_revised: 2026-08-09
---

# 회복탄력성

FDAI는 워크로드를 복구 가능한 상태로 유지하고, 실제 장애가 발생하기 전에 정기적으로
복구 가능성을 검증합니다. 재해 복구를 예행 연습하고, 데이터베이스 복원을 복구 목표에
맞춰 훈련하며, 영향 범위가 제한된 카오스 실험을 실행하고, 이전에 확인한 실패 패턴을
자가 치유합니다. 따라서 복구 경로를 처음 실행하는 순간이 실제 장애 상황이 되지 않도록
합니다.

## 무엇을 얻나요

- **예약된 DR 훈련.** 재해 복구 예행 연습은 비정기적으로 수행하지 않고 지정된 훈련
  시간대(exercise window)에 실행하며 결과를 기록합니다.
- **복구 목표 검증.** 데이터베이스 복원 훈련은 목표 RPO와 RTO를 기준으로 복원을
  수행하고, 문제가 되기 전에 `point-in-time-restore` 미지원 구간 같은 차이를 식별합니다.
- **범위가 제한된 카오스 실험.** 실패는 엄격한 영향 범위 한도 안에서 주입되므로,
  실험이 선언된 범위를 결코 초과할 수 없습니다.
- **알려진 패턴에 대한 자가 치유.** 해결된 인시던트 패턴과 일치하는 실패는 자동으로
  고쳐지고, 새로운 소수의 실패는 사람에게 올라옵니다.

## 에이전트가 회복탄력성을 제공하는 방법

Huginn은 signal을 normalize하고 Heimdall은 gap을 감지하고 outcome을 독립 검증합니다. Loki는
bounded experiment를 제안하고 Forseti는 판단하며 Odin은 objective conflict를 중재합니다. Var는
필수 사람 승인을 소유하고 Thor는 실행하며 Vidar는 rollback과 recovery를 통제하고 Saga는 immutable
trace를 기록합니다. Norns는 closure 뒤 inert learning candidate만 제안하며 policy를 변경하지 못합니다.

## FDAI가 복구를 증명하는 방법

<!-- fdai:steps -->

1. **차이 찾기.** 예약된 작업이 중요 데이터베이스의 `point-in-time-restore` 미지원 구간
  같은 회복탄력성 문제를 감지하고 발견된 문제를 생성합니다.
2. **훈련 예약.** 에이전트가 지정된 훈련 시간대 안에 연계 복원 훈련을 예약하며,
  라이브 트래픽을 대상으로 범위 제한 없이 실행하지 않습니다.
3. **영향 범위 안에서 실행.** 훈련은 범위, 배치, 속도 한도 안에서 실행됩니다. 모든
   자율 작업에 적용되는 것과 같은 안전 장치를 따릅니다.
4. **목표 대비 검증.** 복원 결과를 목표 RPO와 RTO에 따라 확인하고, 성공과 실패를 모두
  기록합니다.
5. **증거 감사.** 결과는 복구 경로가 작동한다는 증거로 추가 전용(append-only) 감사
  로그에 기록됩니다.

## 약속이 아니라 증거

회복탄력성은 단언하지 않고 베이스라인을 기준으로 측정합니다. 자세한 내용은
[목표와 메트릭](../../roadmap/architecture/goals-and-metrics-ko.md)을 참조하세요.

- **MTTR**은 해결까지 걸리는 평균 시간입니다. 단축을 목표로 삼되 평균과 함께 중앙값,
  p90도 보고합니다.
- **자동 해결률**은 사람 접점 없이, 사후 롤백 없이 해결된 이벤트의 비율입니다. 높이는
  것이 목표입니다.
- **롤백률**과 **위음성률**은 보호 지표이며, 둘 다 기준선 임계값보다 나빠지면 안 됩니다.

모든 훈련과 자가 치유 기능은 먼저 [관찰 모드](../concepts/shadow-then-enforce-ko.md)로
출시되고, 측정한 정확도가 기준을 충족한 뒤에만 적용 모드로 올라갑니다.

## 관련 문서

<!-- fdai:cards -->

- [사이트 신뢰성 엔지니어링](../sre/README-ko.md) - 관찰, 대응, 복구, 학습의 전체 라이프사이클.
- [재해 복구와 훈련](../sre/disaster-recovery-and-drills-ko.md) - 복구 경로를 격리, 측정, 감사하는 방법.
- [카오스 엔지니어링](../sre/chaos-engineering-ko.md) - 범위가 제한된 장애 시나리오로 복구 동작을 증명하는 방법.
- [에이전트와 자가 치유](../concepts/agents-and-self-healing-ko.md) - 에이전트 조직이 실패를 해소하는 방식.
- [리스크 티어](../concepts/risk-tiers-ko.md) - 복구 작업이 자동 실행, 사람 승인, 거부로 갈리는 방식.
- [운영 준비성 검토](../../roadmap/operations/operational-readiness-ko.md) - 개발에서 운영으로 넘어가기 위한 준비 기준.
- [배포와 온보딩](../../roadmap/deployment/deploy-and-onboard-ko.md) - FDAI를 환경에 도입하는 방법.
