---
title: Agent Workflow Shadow Rollout
translation_of: agent-workflow-rollout.md
translation_source_sha: 1cfcee5397c8e80406509d6cee568fe06c214037
translation_revised: 2026-08-11
---
# 에이전트 작업 흐름 shadow 롤아웃

이 문서는 cross-agent 작업 흐름의 롤아웃 순서와 공통 exit 게이트를 소유합니다. 각 작업 흐름은
독립적으로 검토할 수 있으며 적용 모드로 승격하기 전에 shadow 모드에서 시작합니다.

## 작업 흐름 순서

[agent-workflows-ko.md](agent-workflows-ko.md)의 13개 작업 흐름은 각각 자체 shadow-mode 게이트가
있는 별도 PR로 도입합니다. 대략적인 순서는 다음과 같습니다.

1. Cost-aware 교정 (Njord + Forseti + Thor)
2. Predictive 규모 (Freyr + Heimdall + Njord)
3. DR 훈련 orchestration (Loki + Vidar + Heimdall + Norns)
4. 재정의 -> 발견 (Var + Saga + Norns + Mimir)
5. Security 에스컬레이션 (Wave 6 이후 작업 흐름 객체로 formalize)
6. 인계 -> 기능 (Saga + Norns + Mimir)
7. 에이전트 상태 성능 저하 (Heimdall + Odin + Bragi)
8. Judgment coherence 감사 (Forseti + Norns + Mimir)
9. Rollback 예행 연습 (Loki + Vidar + Heimdall + Saga)
10. Retrospective what-if (Saga + Forseti + Norns + Mimir)
11. Operational 준비 상태 인계 (Forseti)
12. Scheduled 통제된 Python 작업 (Forseti + Thor)
13. Detection 준비 상태 assurance (Huginn + Heimdall + Muninn + Forseti + Saga + Bragi)

## 작업 흐름별 exit 게이트

- 모든 참여 에이전트를 포함한 shadow 종단 간 추적을 확보합니다.
- 승격 게이트를 평가하기 전에 KPI 기준선을 수집합니다.
- shadow에서 policy-violation escape가 없어야 합니다.

## 의존성 및 anti-scope

Wave 6가 완료되어야 합니다. 이 롤아웃 wave에서는 작업 흐름을 강제 적용으로 승격하지 않습니다.
승격은 Wave 8 이후 각 작업 흐름별로 측정된 KPI 임계값을 통과한 경우에만 진행합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 작업 흐름 정의와 에이전트 참여 | [에이전트 workflows](agent-workflows-ko.md) |
| 구현 wave와 공통 불변식 | [에이전트 Pantheon 구현](agent-pantheon-implementation-ko.md) |
| 승격 메트릭과 가드 임계값 | [목표 및 메트릭](../architecture/goals-and-metrics-ko.md) |
