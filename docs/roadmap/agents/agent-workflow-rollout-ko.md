---
title: Agent Workflow Shadow Rollout
translation_of: agent-workflow-rollout.md
translation_source_sha: 1cfcee5397c8e80406509d6cee568fe06c214037
translation_revised: 2026-08-05
---
# Agent Workflow Shadow Rollout

이 문서는 cross-agent workflow의 rollout 순서와 공통 exit gate를 소유합니다. 각 workflow는
독립적으로 검토할 수 있으며 적용 모드로 승격하기 전에 shadow mode에서 시작합니다.

## Workflow 순서

[agent-workflows-ko.md](agent-workflows-ko.md)의 13개 workflow는 각각 자체 shadow-mode gate가
있는 별도 PR로 도입합니다. 대략적인 순서는 다음과 같습니다.

1. Cost-aware remediation (Njord + Forseti + Thor)
2. Predictive scale (Freyr + Heimdall + Njord)
3. DR drill orchestration (Loki + Vidar + Heimdall + Norns)
4. Override -> Discovery (Var + Saga + Norns + Mimir)
5. Security escalation (Wave 6 이후 workflow object로 formalize)
6. Handoff -> Capability (Saga + Norns + Mimir)
7. Agent health degradation (Heimdall + Odin + Bragi)
8. Judgment coherence audit (Forseti + Norns + Mimir)
9. Rollback rehearsal (Loki + Vidar + Heimdall + Saga)
10. Retrospective what-if (Saga + Forseti + Norns + Mimir)
11. Operational readiness handoff (Forseti)
12. Scheduled governed Python task (Forseti + Thor)
13. Detection readiness assurance (Huginn + Heimdall + Muninn + Forseti + Saga + Bragi)

## Workflow별 exit gate

- 모든 참여 agent를 포함한 shadow end-to-end trace를 확보합니다.
- Promotion gate를 평가하기 전에 KPI baseline을 수집합니다.
- Shadow에서 policy-violation escape가 없어야 합니다.

## Dependency 및 anti-scope

Wave 6가 완료되어야 합니다. 이 rollout wave에서는 workflow를 enforce로 승격하지 않습니다.
승격은 Wave 8 이후 각 workflow별로 측정된 KPI threshold를 통과한 경우에만 진행합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Workflow 정의와 agent 참여 | [Agent workflows](agent-workflows-ko.md) |
| 구현 wave와 공통 invariant | [Agent Pantheon 구현](agent-pantheon-implementation-ko.md) |
| Promotion metric과 guard threshold | [목표 및 메트릭](../architecture/goals-and-metrics-ko.md) |
