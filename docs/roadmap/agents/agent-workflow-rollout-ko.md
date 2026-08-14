---
title: Agent Workflow Shadow Rollout
translation_of: agent-workflow-rollout.md
translation_source_sha: 4d17413106348693d475f7c342cfe0b7225bc543
translation_revised: 2026-08-14
---
# 에이전트 작업 흐름 shadow 롤아웃

이 문서는 cross-agent 작업 흐름의 롤아웃 순서와 공통 exit 게이트를 소유합니다. 각 작업 흐름은
독립적으로 검토할 수 있으며 적용 모드로 승격하기 전에 shadow 모드에서 시작합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 13개 작업 흐름 롤아웃 인벤토리 | implemented | `docs/roadmap/agents/agent-workflows.md`; `services/core-control-plane/src/fdai/agents/_framework/workflows.py`; `services/core-control-plane/tests/agents/test_wave7_workflows.py` | 레지스트리와 테스트가 문서화된 작업 흐름 수와 shadow 기본값을 유지합니다. |
| 집중 shadow 경로 근거 | implemented | `services/core-control-plane/tests/agents/test_wave7_workflows.py`; 등록된 `trace_ref` 대상 | 집중 테스트는 구현 동작을 증명할 뿐이며, 보존된 런타임 롤아웃 추적은 아닙니다. |
| 공통 운영 종료 게이트 | not-started | 이 문서의 종료 조건 | 모든 작업 흐름에 대해 KPI 기준선, 필요한 shadow 기간, 정책 위반 탈출 0건을 입증하는 보존 근거가 없습니다. |
| 독립 적용 모드 승격 | not-started | `docs/roadmap/agents/agent-workflows.md`의 승격 게이트 | 모든 레지스트리 항목은 `shadow`에 머물며, 회고적 가정 분석은 계속 shadow로 유지됩니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-13 | implemented | 구현 원장을 도입하고 집중 shadow 경로 구현과 운영 롤아웃 검증을 분리했습니다. 이전 구현 이력은 재구성하지 않았습니다. | 현재 변경; 집중 작업 흐름 테스트 | 런타임 종료 게이트 근거를 수집하고 독립 승격 결과를 기록합니다. |
| 2026-08-14 | implemented | Forseti의 순수 결정 mapping, conflict, impact 및 freshness helper를 private framework로 추출하고 판단 역할, topic, workflow mode 및 승격 상태는 변경하지 않았습니다. | `current change`, 집중 layout 및 Forseti 판단 검사 104개 통과, strict mypy 및 agent import gate 통과 | 런타임 종료 게이트 근거와 독립 승격 결과는 변경 없이 남아 있습니다. |

### 남은 작업

- [ ] 운영 환경에서 작업 흐름별 영구 shadow 추적, KPI 기준선, 정책 위반 탈출 관찰을 수집합니다.
- [ ] 적용 기간과 임계값 근거가 존재한 뒤에만 승격을 평가합니다.
- [ ] 승격 대상 작업 흐름마다 승격 또는 shadow 유지 결과를 별도로 기록합니다.

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
