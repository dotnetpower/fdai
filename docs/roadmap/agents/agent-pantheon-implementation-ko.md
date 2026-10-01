---
title: 에이전트 판테온 구현 계획
translation_of: agent-pantheon-implementation.md
translation_source_sha: 985df44eaf5b1dd5383950ff2ef8a6a1fb226158
translation_revised: 2026-10-01
---

# 에이전트 판테온 구현 계획

이 문서는 고정된 15개 에이전트 판테온의 구현을 조정합니다. 추가 전용 전달 원장, W0-W8
의존성 순서, 런타임 조립 계약을 한곳에 유지합니다. 에이전트 역할과 불변식은
[에이전트 판테온](agent-pantheon-ko.md)이 소유하고, 각 에이전트 간 작업 흐름은
[에이전트 작업 흐름 Shadow 롤아웃](agent-workflow-rollout-ko.md)에서 독립적으로 추적합니다.

> **범위:** 이 계획은 고객과 무관하며 Azure를 우선합니다. 포크는 지원되는 의존성 주입
> 경계를 통해 프로바이더와 전달 바인딩을 설정합니다. 에이전트 이름, 역할 바인딩 또는
> shadow 승격 경계를 변경하지 않습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 온톨로지 ContextIndex 소유자 라우팅 | implemented | `agents/_framework/ontology_index.py`; `test_ontology_context_index.py`; 실제 인메모리 EventBus 단계 연결 검사 | Huginn 유입, Muninn 준비 및 전이 게시, Heimdall 검증 게시, Saga 감사 및 봉인 게시는 기존 소유 토픽을 사용합니다. 래퍼는 소유자, 토픽, 내용, 단계 불일치를 거부하고 일반 판단과 학습에서 분리합니다. 이 라우팅 검사의 기계적 처리기는 합성이며 영속 원본 및 수명주기 처리기와 운영 bootstrap 연결은 남아 있습니다. |
| W0-W1 문서, 온톨로지 및 프레임워크 기반 | implemented | [`test_framework_layout.py`](../../../services/core-control-plane/tests/agents/test_framework_layout.py), [`test_pantheon_doc_parity.py`](../../../services/core-control-plane/tests/agents/test_pantheon_doc_parity.py), [`test_topics.py`](../../../services/core-control-plane/tests/agents/test_topics.py) | 고정 레지스트리, 패키지 경계, 문서 일치 및 타입이 지정된 토픽 기반을 실행하고 검사할 수 있습니다. |
| Bus 및 graph ownership 분리 | implemented | `_framework/{pantheon,topics}.py`; ontology alignment, topic, registry, doc parity 및 Console agent contract 검사 | 이제 `AgentSpec.owns`에는 생산 가능한 event-bus 객체만 포함됩니다. `Budget`과 `SizingRecommendation`은 사용되지 않는 topic을 만들지 않고 Njord와 Freyr의 graph lifecycle ownership을 유지합니다. ActionRun에 포함된 attempt 상태와 core RCA projection은 bus registry 밖에 유지됩니다. |
| 소유 topic producer 완전성 | implemented | [`test_registry.py`](../../../services/core-control-plane/tests/agents/test_registry.py) | AST 기반 registry 검증은 모든 `AgentSpec.publishes` topic이 구체적인 publish call에 도달하도록 요구하고, 선언되지 않은 topic의 producer 근거를 거부합니다. 임의의 문자열 언급을 producer로 취급하지 않고 literal call, import된 topic 상수 및 정확한 dynamic-topic 비교를 인식합니다. |
| W2-W6 거버넌스, 파이프라인, 인터페이스, 전문 에이전트, 인계 및 보안 메커니즘 | implemented | [`test_runtime_chain.py`](../../../services/core-control-plane/tests/agents/test_runtime_chain.py), [`test_thor_durable.py`](../../../services/core-control-plane/tests/agents/test_thor_durable.py), [`test_conversational_port.py`](../../../services/core-control-plane/tests/agents/test_conversational_port.py), [`test_prompt_deliberation.py`](../../../services/core-control-plane/tests/agents/test_prompt_deliberation.py) | 선택적 T2 종합 전의 T1 답변 평가를 포함한 범위가 제한된 메커니즘을 집중 합성 검사로 실행하지만 실제 운영 검증을 입증하지는 않습니다. |
| 영속 권한, 복구, 인계 및 학습 재생 | implemented | [`test_runtime.py`](../../../services/core-control-plane/tests/agents/test_runtime.py), [`test_wave2_governance.py`](../../../services/core-control-plane/tests/agents/test_wave2_governance.py), [`test_wave3_pipeline.py`](../../../services/core-control-plane/tests/agents/test_wave3_pipeline.py), [`test_bootstrap_config.py`](../../../services/core-control-plane/tests/runtime/test_bootstrap_config.py) | StateStore 기반 CAS, 점유 유효 기간, 검사 지점, 보낼 편지함 및 시작 복구 경로에는 재시작과 동시성 집중 검사 근거가 있습니다. 범위가 제한된 Low 심각도 복제본 간 및 작업 신원 잔여 문제 두 건은 아래에 열어 둡니다. |
| 전권 개발 승인 및 복구 | in-progress | `agents/{forseti,thor,var,vidar}.py`; `agents/_framework/*development_authority*.py`; [`test_development_authority.py`](../../../services/core-control-plane/tests/agents/test_development_authority.py) | 명시적 조립은 신뢰 원본으로 검증한 확인 한 건을 Forseti에서 Var와 Thor로 전달하고 Vidar 및 재시작 시 다시 검증하며 신원을 만들어 내지 않습니다. 역할, 토픽 및 `PANTHEON_SPECS`는 바뀌지 않습니다. 업스트림 권위 결속 원본은 구현되거나 배포되지 않았습니다. |
| 영속 Huginn 유입 중복 제거 | implemented | `agents/{huginn.py,_framework/huginn_dedup.py}` 및 집중 discovery/runtime 검사 | 프로덕션 조립은 유입 consumer를 시작하기 전에 최대 64개의 정확한 용량 shard에 제한된 key claim, 정확한 정규화 재시도 payload, owner lease 및 게시 checkpoint를 영속화합니다. 일반 claim은 권한 없는 개정 번호 CAS를 사용해 각 이벤트를 감사에 중복 기록하지 않으며, 복구와 이행은 계속 감사합니다. 시작 시 기존 단일 행 원장을 멱등적으로 이행하고 압축합니다. Broker 수락 후 checkpoint 전 crash는 event bus의 at-least-once 계약에 따라 동일한 stable idempotency key를 다시 전달할 수 있습니다. |
| Loki ResilienceScore 생산 | implemented | `agents/{loki.py,_framework/loki_resilience.py}`; 집중 Wave 5 및 cross-vertical 후보 검사 | Loki는 Huginn이 소유하는 정규화 score Event를 consumer의 정확한 후보 계약으로 검증하고 `object.resilience-score`를 게시하며, 범위가 제한된 읽기 전용 score 변환 결과만 유지합니다. 후보는 판단, 승인 또는 실행 권한을 부여하지 않습니다. |
| Bragi 세션 객체 생산 | implemented | `agents/{bragi.py,_framework/bragi_publication.py}`; 집중 Bragi, 대화, Norns, runtime 및 governance 검사 | 첫 in-process 세션은 content-free `Conversation` 하나를 게시합니다. 명시적 메서드는 검증된 `UserPreferenceRecord`와 동의가 확인된 `PostTurnReviewInput` 값만 받아 소유 topic에 게시하며 판단, 승인 또는 실행 경로를 노출하지 않습니다. 배포가 소유하는 store 및 queue binding은 별도입니다. |
| W7 에이전트 간 shadow 작업 흐름 메커니즘 | implemented | [`test_wave7_workflows.py`](../../../services/core-control-plane/tests/agents/test_wave7_workflows.py) | 작업 흐름에 실행 가능한 합성 shadow 추적이 있으며, enforce 작업 흐름을 기본값으로 사용하는 근거는 이 문서에 없습니다. |
| W8 KPI, 승격 및 성능 저하 메커니즘 | implemented | [`test_wave8_kpi_degradation.py`](../../../services/core-control-plane/tests/agents/test_wave8_kpi_degradation.py) | KPI 보고는 측정값과 사용 불가능한 근거를 구분하고, 근거가 없으면 승격을 차단하며, 주입된 성능 저하 훈련이 고정 판테온을 다룹니다. |
| W3 추적 연속성 근거 인계 | implemented | `huginn.py`; `heimdall.py`; `test_trace_continuity_chain.py` | sensing 경로는 허용 목록의 범위가 제한된 연속성 근거만 보존하고 역할, topic, 작업 권한을 바꾸지 않은 채 관측된 사유를 인시던트 후보 하나에 전달합니다. |
| 운영 활동 귀속 | implemented | `control_loop/_measurement.py`; `control_loop/_rca.py`; `agents/_framework/provider_adapters.py`; `delivery/{agent_activity,observation_campaign,startup_probe}.py`; Operator 활동 투영과 집중 테스트 | 기계 행위자와 책임지는 Pantheon 소유자를 구분합니다. 주기적 런타임 스냅샷은 활성 handler 상태를 보존하고 서로 독립적인 에이전트 레코드를 동시에 게시합니다. 인증된 버스 게시자만 `producer_principal`을 채우며, 소유자를 알 수 없는 기존 사용자 정의 source는 감사 근거로 유지하고 임의의 에이전트 활동으로 만들지 않습니다. |
| 최종 ActionRun 효과 관찰 경로 | implemented | [`executed_action_observation.py`](../../../services/core-control-plane/src/fdai/delivery/executed_action_observation.py), [`wire_azure_operational_evidence.py`](../../../services/core-control-plane/src/fdai/composition/wire_azure_operational_evidence.py), [`test_executed_action_observation.py`](../../../services/core-control-plane/tests/delivery/test_executed_action_observation.py) | Heimdall은 Thor의 최종 ActionRun을 소비하고 정확한 실행 전 아티팩트를 복원하며 검증기가 승인한 독립 관찰만 저장합니다. 배포가 소유하는 서명된 컨텍스트와 실제 종료 근거는 아직 필요합니다. |
| O7 운영 승격 근거 측정 | implemented | [`operational_promotion.py`](../../../services/core-control-plane/src/fdai/core/measurement/operational_promotion.py), [`operational_promotion_evidence.py`](../../../services/core-control-plane/src/fdai/delivery/measurement/operational_promotion_evidence.py), [`test_operational_promotion_evidence.py`](../../../services/core-control-plane/tests/delivery/test_operational_promotion_evidence.py) | 실행기는 매니페스트에 결합된 불변 배치를 소비하고 인과관계, 측정 단위, 재발 또는 정책 이탈 근거가 없으면 안전하게 차단합니다. 현재 완전한 실제 배치를 구체화하는 런타임 생산자는 없습니다. |
| 실제 운영 KPI 검증 및 실제 enforce 승격 | in-progress | [운영 학습 온톨로지](../rules-and-detection/operational-learning-ontology-ko.md), [목표와 메트릭](../architecture/goals-and-metrics-ko.md) | 측정 및 관찰 소비자는 있지만 완전하게 보존된 실제 shadow 코호트, 운영 승격 증적, 독립적인 검토 또는 실제 판테온 enforce 승격 근거는 없습니다. |
| 관찰 우선 학습 및 예측 결과 경계 | implemented | `agents/_framework/{advisory_verdicts,forseti_learned_outputs,thor_persistence,action_run_identity}.py`; `StateStoreActionRunStore.reserve_correlation`; `core/control_loop/_learned_reuse.py`; `runtime/{control_loop,bootstrap_pantheon}.py`; `test_learned_output_profile_boundary.py`; `test_learned_output_arbitration_gate.py`; `test_learned_output_durable_gate.py`; `test_learned_reuse_profile_boundary.py`; `test_bootstrap_pantheon_product_selection.py` | `governed-execution` 제품 추가 기능을 선택하지 않으면 예측, Freyr 용량 중재, 학습된 패턴의 T1 재사용은 Thor가 무시하는 ActionType 없는 자문 근거만 만듭니다. 종결된 자문 중재는 Thor의 영속 비작업 상관관계 점유를 통해 Core 재시작이나 관문 축출 뒤에도 해당 상관관계에서 나중에 관찰된 신호를 자동 실행하지 않도록 막습니다. 추가 기능을 선택하면 기존 관문이 다시 열리며, 의도적인 제한은 하나뿐입니다. 정확한 `mode: enforce`가 없는 예측에서 도출한 작업 판정은 `shadow_only`로 제한됩니다. 선택은 제품 프로필에서만 오며, T2 제안은 이 행의 범위가 아닙니다. |
| Phase-2 실행 증적 및 failover 계약 | implemented | `agents/{thor.py,vidar.py}`; `_framework/{thor_preflight,thor_execution,vidar_dr,vidar_rehearsal}.py`; `test_wave7_workflows.py`; `test_thor_durable.py` | Thor는 고위험 및 의무 전용 실행에서 executor I/O 전에 정확한 신원에 묶인 pre-flight simulation 증적을 기록합니다. Vidar는 DR failover 계약을 수락하거나 보류하고 범위가 제한된 rollback rehearsal 증적을 기록합니다. |
| Phase-2 학습 및 거버넌스 루프 | implemented | `agents/{huginn.py,bragi.py,mimir.py,norns.py}`; `_framework/{huginn_schema_learning,bragi_intent_training,norns_issue_close_support}.py`; `test_mimir_issue_close_evidence.py`; `test_wave7_workflows.py`; `test_runtime.py` | 서명된 operator-request 증적, schema-cluster 근거, shadow 전용 Bragi intent-training 근거, Mimir promotion/deprecation 근거, Norns quiet-window 적격성은 검토된 활성화나 Saga 소유 종료 경로가 소비하기 전까지 비활성입니다. |
| Phase-2 전문 에이전트 sampling 및 scenario generation | implemented | `agents/{freyr.py,loki.py}`; `_framework/{capacity_utilization,loki_scheduling,loki_adversarial}.py`; `test_sensing_specialist_contracts.py`; `test_loki_recurring_scheduler.py`; `test_loki_adversarial_generation.py` | Freyr는 주입된 읽기 전용 sampler로 표본을 수집하고 capacity forecast 또는 shadow/HIL scale proposal을 냅니다. Loki는 always-HIL 제안 또는 hold를 예약하고 기본 바인딩이 없는 off-path port로 비활성 adversarial scenario 후보를 생성할 수 있습니다. |
| Phase-2 replay, cost, backlog 제어 | implemented | `agents/{forseti.py,odin.py,muninn.py,thor.py}`; `_framework/{forseti_what_if,thor_persistence}.py`; `test_forseti_retrospective_what_if.py`; `test_wave7_workflows.py`; `muninn.py` compaction regressions | Cost annotation은 Forseti, Odin, Thor를 지나며 명시적으로 유지됩니다. Retrospective what-if replay는 비활성입니다. Muninn publication outbox compaction과 provider replay 근거는 보존 상태를 제한합니다. 영속 poison-halt 저장소는 opt-in으로 남습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-10-01 | implemented | 다섯 번째 비평 라운드를 마무리했습니다. Saga 이슈 자동 종료는 재발 재확인과 취소 감사를 갖춘 checkpoint 기반 2단계 흐름이 되었고, 첫 ActionRun 게시가 실패하면 게시되지 않은 실행과 정확한 리소스 점유를 되돌리며, 적용 모드 시작은 `(ActionType, rollback_contract)` 쌍별 실행기 범위를 검증하고, `object.rollback` 레코드는 schema 검증을 거치며, Vidar rehearsal 주기는 게시를 기다리고, Bragi 보낼 편지함은 점유 토큰으로 보호되며, Heimdall은 큰 재생 payload를 유지하고, Loki, Freyr, Njord는 게시되지 않았거나 오래된 작업을 완료로 보고하지 않습니다. | `current change`; `services/core-control-plane/src/fdai/agents/**`; `test_bragi_outbox_fencing.py`, `test_heimdall_large_publication.py`, `test_stale_sample_fences.py`, `test_mimir_issue_close_evidence.py`, `test_vidar_dr_failover_rehearsal.py`, `test_thor_durable.py`, `test_runtime.py`, `test_governance_authority.py`; `pytest services/core-control-plane/tests/{agents,runtime,scenarios,providers}`: 4463 passed, 1 skipped. | 아래에 나열한 남은 프로덕션 port와 live 또는 배포 근거를 바인딩하고 검증합니다. |
| 2026-10-01 | implemented | 반복 비평 라운드로 Phase-2 Agent Pantheon 기능을 하드닝했습니다. 서명되고 차단 장치 순서를 지키는 ordered-poison-halt clear, 존재 여부를 구분하는 workflow lineage와 pending 후 확정되는 replay 차단 장치를 가진 증적 schema `1.1.0`, 범위가 제한된 게시, 페이지 단위 복구, 행 단위 연기, 유지 관리 재게시를 갖춘 토큰 차단 영속 게시 보낼 편지함, ActionType별 롤백 준비 상태, batch 거부 집계, 범위가 제한된 전문 에이전트 sampling과 복구 가능한 Loki window, 정확한 키 단위 `delete_state` 보존을 포함합니다. 지나치게 커진 멤버는 동작 변경 없이 `_framework` 기능 모듈로 옮겼습니다. | `current change`; `services/core-control-plane/src/fdai/agents/**`; `services/operator-service/src/fdai_operator_service/**`; `services/core-control-plane/tests/agents/test_outbox_publication_hardening.py`; `pytest services/core-control-plane/tests/{agents,runtime,scenarios,providers}`: 4407 passed, 1 skipped; loopback Redpanda와 PostgreSQL의 실제 provider matrix가 두 번 통과했습니다. | 아래에 나열한 남은 프로덕션 port와 live 또는 배포 근거를 바인딩하고 검증합니다. |
| 2026-10-01 | implemented | Phase-2 Agent Pantheon 기능을 문서화했습니다. Pre-flight 증적, DR 계약, 서명된 operator-request 증적, schema learning, intent-training 근거, Mimir 및 Norns issue-close 지원, Freyr/Loki 전문 루프, poison-halt clear 시맨틱, cost annotation, multi-target batch 시맨틱, Muninn compaction을 포함합니다. | `current change`; `docs/roadmap/agents/agent-pantheon*.md`; `docs/roadmap/agents/agent-pantheon-implementation*.md`; `docs/roadmap-implementation/agents/agent-pantheon.md`; 최종 보고서의 집중 검사. | 아래 남은 production port 및 live/deployment 근거를 바인딩하고 검증합니다. |
| 2026-09-29 | implemented | Thor, Heimdall, Mimir, Forseti가 역할, 소유 객체, 토픽을 유지한 채 독립 검증기가 기록한 명시적 거부 유형을 기록하고 해당 거부 기록을 인용합니다. Thor의 테스트 맥락 디스패치 보류는 `object.action-run`에 `ActionRun` 결과와 `evidence_rejection_ref`를 설정하고, Heimdall은 `object.forecast-outcome`의 `ForecastOutcome` `1.2.0`에서 점수 산정을 제외합니다. Mimir는 `test_context.transition_refused` 감사 항목을 추가하고 `object.policy`를 게시하지 않으며, Forseti의 보류 판정은 `evidence_rejection_ref`를 담습니다. `unavailable`만 각 일반 사유를 유지하고, 발급은 제한된 제공자 호출로 남으며, 실행 권한이나 승격 권한은 바뀌지 않습니다. | `current change`; `agents/_framework/{thor_execution,thor_action_run,thor_persistence,forseti_judgment}.py`; `tests/agents/test_operational_evidence_owner_records.py`; [독립 운영 근거 원장](../../roadmap-implementation/rules-and-detection/independent-operational-evidence.md) 참조 | 검증기 재확인이 연결되지 않은 목적은 여전히 `unavailable`로만 이 에이전트에 도달합니다. |
| 2026-09-28 | implemented | 기본 프로필에서 학습된 패턴과 예측이 작업 제안이 되던 남은 경로를 기존 `governed-execution` 제품 추가 기능 기준으로 닫았습니다. 컨트롤 루프 빌더가 `RuntimeProductSelection.governed_execution`을 컨트롤 루프에 전달하고, Pantheon 조립은 컨트롤 루프의 값을 Forseti에 전달하므로 두 번째 선택 입력은 없습니다. 추가 기능이 없으면 Forseti는 예측과 용량 입력이 포함된 중재에 ActionType 없는 판정으로 응답하고 예측에서 결정 선택지나 kinetic 제안을 만들지 않으며, 컨트롤 루프는 학습된 T1 재사용을 Action을 만들기 전에 멈춥니다. 종결된 모든 자문 중재는 통제 경로와 마찬가지로 해당 상관관계를 미해결로 기록하고, 상관관계별 잠금 아래에서 판정 하나만 게시하며, Thor는 ActionRun 저장소에 종결된 비작업 점유를 기록해 상관관계를 영속적으로 유지합니다. 따라서 재시작이나 관문 축출 뒤에 같은 상관관계로 온 판정은 통제 경로가 재사용된 상관관계를 거부하듯 거부되며, ActionRun, 승인 또는 실행기 호출은 생기지 않습니다. 추가 기능을 선택하면 기존 관문이 실행되며, 의도적인 제한은 하나뿐입니다. 정확한 `mode: enforce`가 없는 예측에서 도출한 작업 판정은 `shadow_only`로 제한됩니다. 역할, 토픽 및 `PANTHEON_SPECS`는 바뀌지 않았습니다. | `current change`; `test_learned_output_profile_boundary.py`, `test_learned_output_arbitration_gate.py`, `test_learned_output_durable_gate.py`, `test_learned_reuse_profile_boundary.py`, `test_bootstrap_pantheon_product_selection.py`의 검사 50개, 관문별, 미해결 기록, 게시 재시도와 잠금, 영속 점유 및 두 조립 전달 지점의 변이 검사, 제품 프로필로 추가 기능을 선택하도록 갱신한 통제 경로의 중재, 결정 사례, 전문 에이전트 및 T1 연결 검사; 프레임워크 구조, Ruff 및 엄격한 mypy 통과. | T2, 이상 작업 후보, 경보 소음 학습 및 다른 학습 근거 소비자를 검토해야 합니다. 실제 운영 검증은 수행하지 않았습니다. |
| 2026-09-27 | in-progress | 고정 역할 및 토픽 경계를 유지하면서 신뢰 원본으로 검증한 전권 개발 묶음을 실제 Forseti, Var, Thor 및 Vidar 타입 경로에 통합했습니다. 원래 정족수와 유효 정족수를 구분하고 선택한 프로필에만 정확한 권한 부여를 재생 신원에 포함합니다. | `current change`; 집중 권한, 버스, 재생 및 인접 검사 723개, 구조 검사, Ruff 및 엄격한 타입 검사 통과. | 권위 있는 배포 원본을 구현하고 결속한 뒤 관리되는 런타임 증적을 보존해야 합니다. 실제 운영 검증은 수행하지 않았습니다. |
| 2026-09-22 | validated | 로컬 Core 시작 및 종료의 리소스 소유권을 수정했습니다. 이제 런타임 설정은 런타임이 소유하는 단일 StateStore pool을 재사용하고, Pantheon consumer 종료는 첫 drain 기한 뒤 범위가 제한된 마무리 시간을 부여하며, 로컬 broker를 파괴적으로 초기화할 때 모든 관리형 서비스 lock을 유지하므로 연결이 끊긴 실행 중 consumer를 유휴 상태로 오인할 수 없습니다. 에이전트 역할, topic, 모델 정책, 승격 상태 및 권한은 바뀌지 않았습니다. | `현재 변경`; 공유 store, 순서가 지정된 종료, 지연된 stream 닫기, consumer 재시도, broker reset fence, framework layout, Ruff 및 strict typing 집중 검사. 관리형 재시작은 12/12 준비 상태에 도달했고 각 서비스는 lock이 소유하는 프로세스 쌍 하나만 유지했으며 새 세대 marker 뒤에 수정 대상 오류가 나타나지 않았습니다. | 이 범위가 제한된 수명주기 수정에는 남은 작업이 없습니다. 배포된 런타임 검증과 승격 근거는 별개입니다. |
| 2026-09-21 | implemented | 닫힌 온톨로지 ContextIndex 메시지 묶음과 소유자별 런타임 구독 래퍼를 추가했습니다. Heimdall과 Saga의 ContextIndex 구독 및 타입이 지정된 Huginn 유입을 연결하고 실제 버스 검사에서 드러난 도메인 스키마와 전송 버전 구분을 수정했습니다. | `current change`; 집중 ContextIndex 라우팅, 프레임워크 구조, 인접 Rule 생성 경로, 정확한 감사 후 봉인 검사. | 실제 원본 및 벡터 검증, 감사된 포인터 허용, 최종 결과 재생, 런타임 소비자를 연결합니다. 고정 에이전트 역할, 주요 경로의 모델 정책, 패키지 활성화, 실행 권한은 바뀌지 않았습니다. |
| 2026-09-21 | implemented | Forseti의 소유자 인증 cross-vertical 유입, Odin 중재, 결정 사례 마무리, HIL 대체 경로, kinetic proposal 검증 및 prospective-lineage 게시를 하나의 목적별 비공개 framework mixin으로 분리했습니다. Forseti는 Judge이자 자신이 소유한 네 객체 topic의 유일한 게시자로 유지되며 승인 또는 실행 권한을 얻지 않습니다. | `현재 변경`, `agents/{forseti.py,_framework/forseti_arbitration.py}`, 12개 관점 비평, 역할·중재·정족수 집중 테스트 145개와 layout, 동등성, import, Ruff 및 strict mypy 게이트 통과. | timeout HIL 종결, Odin 사용 불가, 중복 전달 및 prospective-lineage 구체화에 대한 통제된 runtime 근거를 보존합니다. |
| 2026-09-21 | implemented | Thor의 영속 ActionRun codec, verdict 검증, 감사로 통제된 실행 단계, 재생 및 게시 lifecycle, 효과 종결 지원, 읽기 전용 대화 변환을 용도별 비공개 framework 모듈로 분리했습니다. 이제 영속 재생은 짝을 이루는 kinetic proposal이 없는 prospective lineage를 거부합니다. Thor는 유일한 privileged 실행기이자 ActionRun 게시자로 유지됩니다. AgentSpec, topic, 정족수, 승인, 감사, rollback, 효과 검증 및 모델 정책은 바뀌지 않았습니다. | `현재 변경`; `agents/{thor.py,_framework/thor_*.py}`; Thor durability, conversation 및 framework layout 검사 203개 통과, 집중 strict mypy 통과. | 성능 저하 shadow, 실행 전 감사, 재시작 replay, 독립 효과 종결 및 기존 live 승격 전제 조건에 대한 통제된 runtime 근거를 보존합니다. |
| 2026-09-20 | implemented | 기존 pipeline 테스트가 의도한 운영자 RBAC와 ActionType 의미를 명시적으로 주입하도록 했습니다. 알 수 없는 principal 거부와 카탈로그 부재 시 정족수 2를 유지하고, Bragi fixture는 Conversation 이후 Turn을 게시하는 순서에 맞췄습니다. 런타임 코드는 기존 800줄 상한을 위한 주석 축약만 포함합니다. | `현재 변경`; 집중 에이전트 테스트 83개와 고정 replay 테스트 122개 통과, 집중 Ruff 및 strict mypy 통과. | 보호된 CI 근거를 보존합니다. 역할, topic, 승인, 실행 또는 복구 권한은 바뀌지 않았습니다. |
| 2026-09-20 | implemented | Huginn의 범위가 제한된 영속 유입 원장을 최대 64개의 결정론적 shard로 분할하고, 기존 단일 행을 압축하는 개정 번호 CAS 이행을 추가했습니다. 일반 claim 및 게시 갱신은 더 이상 권한 없는 전달 checkpoint를 감사에 중복 기록하지 않으며 복구와 이행은 계속 감사합니다. 정확한 전체 용량, 대기 lease, 정규화된 재시도 payload, 재시작 replay, 충돌 거부 및 broker 수락/checkpoint 경계는 바뀌지 않습니다. | `현재 변경`; 기존 원장 이행, 제거, 재시작, lease, 충돌, checkpoint 감사, discovery, Ruff 및 strict mypy 집중 검사. | 통제된 broker 중단 및 재시작 근거를 보존합니다. Broker 수락/checkpoint crash 구간에서는 at-least-once 재전달 가능성이 남습니다. |
| 2026-09-20 | implemented | Huginn discovery 상태에서 관측 부재를 명시하도록 했습니다. Snapshot은 projection 결속 여부를 보고하고, 전달 소유 cursor, backpressure 및 source-health 신호가 없을 때 정상으로 간주하지 않고 `not_observed`로 표시합니다. | `현재 변경`; 집중 Huginn 상태 계약 및 discovery 검사. | 배포 소유 관측값이 준비되면 결속합니다. Cursor, transport 또는 provider 권한은 Huginn으로 이동하지 않았습니다. |
| 2026-09-20 | implemented | 이전 ownership 교정 및 Loki 행을 조정했습니다. 해당 행의 Bragi 및 ResilienceScore source 잔여는 위에 추가된 후속 producer 완료 행으로 대체됐습니다. | `현재 변경`; append-only 원장 순서 및 집중 producer 근거. | 배포된 Bragi callback 및 통제된 runtime 근거는 남지만 구현되지 않은 source producer는 없습니다. |
| 2026-09-20 | implemented | Loki의 raw `detected_at` 및 attribute timestamp fallback을 제거했습니다. 이제 ResilienceScore 후보 기준 시점은 Huginn이 검증한 `occurred_at` 또는 trusted `ingested_at`만 사용하므로 검증되지 않은 시간 출처를 허용하지 않으면서 실제 정규화 producer 경로가 동작합니다. | `현재 변경`; 집중 source-time, ingestion-time fallback, raw-time 거부 및 Huginn-to-Loki end-to-end 검사. | 통제된 runtime score-refresh 근거를 보존합니다. 범위가 제한된 대화 변환 결과의 durability는 주장하지 않습니다. |
| 2026-09-20 | implemented | 모든 Pantheon 소유 topic에 양방향 producer 완전성 회귀를 추가했습니다. 제거된 dead claim과 구체적인 call 경로가 없는 향후 ownership 선언을 거부합니다. | `현재 변경`; 전체 registry invariant 검사. | 검토된 producer가 새 call shape를 도입할 때만 extractor를 확장하며 dead topic을 allowlist에 추가하지 않습니다. |
| 2026-09-20 | implemented | Bragi의 누락된 `Conversation`, `UserPreference` 및 `PostTurnReview` producer 경계를 추가했습니다. Conversation은 세션마다 한 번, 첫 Turn보다 먼저 게시됩니다. Preference payload는 principal을 hash하고 revision을 별도 content digest에 결속합니다. Post-turn review는 Bragi 소유 topic을 통해서만 Norns에 도달합니다. | `현재 변경`; 집중 producer, privacy, idempotency, no-bus, Norns intake, 대화, runtime, governance, Ruff, mypy, import 및 LOC 검사. | 배포된 Operator preference store와 non-blocking post-turn queue를 typed Bragi 메서드에 결속하고 restart 및 duplicate-delivery 증적을 보존합니다. |
| 2026-09-20 | implemented | 엄격한 Huginn 소유 정규화 Event에서 Loki의 누락된 `object.resilience-score` producer를 추가했습니다. Boolean, 비유한, 범위 밖, 불완전 또는 위조된 입력은 후보를 만들지 않으며, 유효한 후보는 다른 버티컬이 도착할 때까지 Forseti에서 pending 상태로 유지됩니다. Score는 replay 신원에 참여하므로 동일 key의 score 대체는 duplicate로 보이지 않고 HIL로 종결됩니다. | `현재 변경`; 집중 Loki producer, 잘못된 입력, 소유자 인증, score 대체, Forseti pending 상태, Wave 5 및 cross-vertical 검사. | 별도로 선언된 Bragi session event를 구현하고 통제된 runtime score-refresh 근거를 보존합니다. |
| 2026-09-20 | implemented | `AgentSpec.owns`에서 생산되지 않는 event-bus claim 네 개를 제거했습니다. 해당 항목은 ActionRun에 포함된 `ActionAttempt`, core RCA projection, graph-only `Budget` 및 `SizingRecommendation`입니다. 고정 에이전트 15개와 전역 판단자, 승인자, 실행기, 감사자 및 복구 역할은 바뀌지 않았습니다. | `현재 변경`; Pantheon registry, topic, ontology alignment, doc parity, Console agent contract 및 집중 specialist 검사. | 별도로 선언된 Bragi session event와 Loki `ResilienceScore` producer를 구현합니다. Graph materialization 근거는 bus publication과 별도로 보존합니다. |
| 2026-09-20 | implemented | 프로덕션 조립의 프로세스 전용 Huginn 중복 제거를 제한된 StateStore CAS 원장으로 교체했습니다. 게시 대기 상태는 원래 정규화된 Event와 Change를 보존하고, 활성 replica lease는 동시 takeover를 막으며, 시작 시 완료 key를 복원하고 idempotency key payload 대체를 실패 폐쇄합니다. | `현재 변경`; 게시 중단, lease 만료 재시작, 활성 claim 충돌, 완료 key 재수화, payload 충돌, discovery, runtime, Ruff 및 mypy 집중 검사. | 통제된 broker 중단 및 재시작 근거를 보존합니다. Broker 수락/checkpoint crash 구간에서는 at-least-once 재전달 가능성이 남습니다. |
| 2026-09-19 | implemented | Loki의 제안 단계 blast-radius 예약을 개정 번호로 보호된 StateStore 갱신으로 영속화하고 소비자 시작 전에 복원하도록 했습니다. 이제 Loki는 Thor가 소유한 안전한 최종 ActionRun을 읽어 정확한 실험, ActionType 및 대상 예약만 해제합니다. 실패, 알 수 없음, 위조 또는 불일치 종결은 예약을 유지합니다. Loki는 자문 역할을 유지하며 판단, 승인 또는 실행 권한을 얻지 않습니다. | `current change`; `loki_reservations.py`; Loki, 런타임, 구독, 재시작, 재생 및 복제본 간 집중 검사; strict mypy와 Ruff. | 통제된 배포 환경에서 chaos 제안, HIL, 최종 ActionRun 및 예약 해제 추적을 보존합니다. Chaos enforce 승격을 추론하지 않습니다. |
| 2026-09-19 | implemented | 공유 불가역 작업 판단에서 ActionType 이름 휴리스틱을 제거했습니다. 이제 카탈로그의 `irreversible` 필드만 가역성의 긍정 근거가 되며, 카탈로그를 사용할 수 없으면 안전하게 정족수 2를 요구합니다. Forseti는 판단자, Var는 승인자, Thor는 유일한 실행기 역할을 유지합니다. | `current change`; `action_semantics.py`; 집중 정족수 및 카탈로그 회귀 검사; 프레임워크 레이아웃, strict mypy 및 Ruff. | 고정된 ActionType 다이제스트가 포함된 배포 불가역 작업 판단 증적을 보존합니다. 승격 상태는 바뀌지 않습니다. |
| 2026-09-19 | implemented | Forseti의 운영자 RBAC에서 예제 principal 대체 동작을 제거했습니다. 이제 배포 정책이 없으면 운영자 작업 권한을 부여하지 않으며, 명시적으로 주입된 정책은 기존의 거부 및 보안 이벤트 동작을 유지합니다. 에이전트 역할, topic, 모델 정책 및 실행 권한은 바뀌지 않았습니다. | `current change`; `forseti.py`; 집중 RBAC 회귀 검사; Wave 3 및 프레임워크 레이아웃 검사; strict mypy와 Ruff. | 기존 실제 shadow 코호트와 함께 배포된 RBAC 판단 근거를 보존합니다. enforce 승격을 추론하지 않습니다. |
| 2026-09-17 | implemented | 통합 과정에서 strict typing 불일치가 드러난 기존 `ActionObservationHook`을 Heimdall의 명시적 공개 export에 복원했습니다. 역할, 토픽, 관측 동작 및 권한은 바뀌지 않았습니다. | `current change`; `heimdall.py`; 프레임워크 레이아웃 검사; 대상 strict mypy. | 운영 검증을 추론하지 않으며 기존 실제 효과 종료 작업을 유지합니다. |
| 2026-09-16 | implemented | 주기적 런타임 스냅샷이 활성 handler 상태를 보존하고 서로 독립적인 에이전트 레코드 15개를 동시에 게시하도록 했습니다. 느린 Event Hubs 왕복 하나가 모든 새로 고침을 직렬로 지연하지 않습니다. 역할, topic, 판단 및 권한은 바뀌지 않았습니다. | `current change`; `delivery/agent_activity.py`; `runtime/bootstrap_pantheon.py`; 에이전트 활동, 런타임 종료, 인벤토리, 분석기 및 관측 집중 검사 260개 통과, strict mypy와 Ruff 통과. | 배포된 활동 근거를 보존합니다. 초기 전체 인벤토리 Rule 평가와 현재 점검 결과 요약은 [이슈 #1199](https://github.com/dotnetpower/fdai/issues/1199)에서 추적합니다. |
| 2026-09-15 | implemented | 예측 기반 구현의 CI 등록 누락을 보완하고 Mimir 컨텍스트 처리, Muninn Pattern 읽기, Heimdall 이력 수신, Forseti 준비 상태 기록을 전용 framework 보조 모듈로 옮겼습니다. 역할, 소유 토픽, 제한된 대기 시간, 권한은 바뀌지 않았습니다. | `current change`; [PR #1029](https://github.com/dotnetpower/fdai/pull/1029); 분리 경로 집중 검사 234개, 근거 허용 경로 검사 316개, 구조 회귀 검사 55개, 실제 루프백 PostgreSQL 검사 3개, strict mypy와 Ruff 통과. | 보호된 CI와 병합은 대기 중이며 예측 후속 작업은 이슈 #1021부터 #1026에 남아 있습니다. |
| 2026-09-15 | implemented | Rebase 뒤 Var의 공개 대기 티켓 유형을 보호된 main과 일치시키고 기존 배정 검토 바인딩을 집중 배정 작업 흐름 helper로 이동했습니다. | `current change`; 레이아웃, 배정 및 Wave 3 집중 검사 125개 통과, strict mypy, Ruff 및 enforced LOC 통과. | 승인, 배정, 역할 또는 권한 동작은 바뀌지 않았으며 기록된 Low 심각도 잔여 문제를 해결합니다. |
| 2026-09-15 | implemented | 보호된 main으로 rebase한 뒤 Var shadow 검토 레코드, 범위 제한 티켓 제거 및 차단 시도 중복 제거를 집중 티켓 신원 helper로 이동했습니다. | `current change`; Wave 3, 런타임 및 정족수 검사 193개 통과, strict mypy, Ruff, 에이전트 가져오기 및 enforced LOC 통과, Var 800줄. | 승인 동작이나 권한은 바뀌지 않았으며 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | 수명 주기 순위로 오래된 쓰기를 억제하기 전에, 그리고 Thor가 멱등성을 예약하거나 리소스를 점유하기 전에 활성 영속 ActionRun 신원을 검증하도록 했습니다. 상관관계를 공유하는 peer generation은 실행 전에 실패하며 정규 활성 실행을 복구 화면에서 숨길 수 없습니다. | `current change`; 활성 행 및 복제본 간 충돌 회귀 검사, LOC 상한 아래로 provider 점유 시간 helper 추출. | 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | withdrawn | 독립 검토에서 결정, 전달 순서, 삭제 및 리소스 점유 경쟁을 발견해 상관관계 재사용 generation 교체를 철회했습니다. 이제 Thor, Var 및 영속 어댑터는 상관관계마다 변경할 수 없는 ActionRun 신원 하나를 결속하고 서로 다른 모든 generation을 거부합니다. 정확히 같은 generation 재생만 멱등성을 유지합니다. | `current change`; 실제 및 영속 재사용 거부, 기존 tombstone, 해제된 점유, 오래된 권한 및 shadow 일부 정족수 재시작 회귀 검사 300개 통과. | 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | 비활성 Thor tombstone에 이전 액션 멱등성 generation을 보존하고 서로 다른 generation에서만 행을 CAS로 교체하도록 했습니다. 재사용한 상관관계도 완료된 실행을 되살리지 않고 새 shadow HIL 실행을 영속화합니다. | `current change`; 오래된 generation 억제, tombstone 교체 및 상관관계 재사용 일부 정족수 재시작 회귀 검사 통과. | 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | Var가 영속 복구를 사용할 때 프로덕션 shadow 모드에서도 Thor ActionRun을 영속화해 미완료 정족수와 정확히 일치하는 실행이 두 번째 승인 전에 함께 복원되도록 했습니다. | `current change`; 일부 정족수 shadow 재시작, 런타임 및 bootstrap 검사 137개 통과, strict mypy 및 Ruff 통과. | 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | Var 승인과 Vidar 롤백을 수명 주기 동안 안정적인 ActionRun 다이제스트 하나에 결속하고 영속 레코드를 해당 신원으로 범위화했으며, Thor가 실행이나 점유 해제 전에 오래된 권한 메시지를 거부하도록 했습니다. | `current change`; 권한 신원, 상관관계 재사용, 롤백 및 전체 에이전트 검사, strict mypy, Ruff, 에이전트 가져오기 및 LOC 게이트 통과. | Shadow 모드에서 일치하는 Thor ActionRun을 영속화한 뒤 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | Vidar가 성공을 기록하기 전에 범위가 제한되고 공백이 아닌 롤백 증적을 정규화하도록 했습니다. 영속 종결 codec은 비어 있거나 비정규적인 증적을 차단하고 Thor도 공백인 성공 페이로드에서 리소스 점유를 독립적으로 유지합니다. | `current change`; Wave 3, T2 복구 체인 및 Thor 내구성 검사 161개 통과, strict mypy 및 Ruff 통과. | 롤백 증적 완전성의 소스 작업은 남아 있지 않으며 Low 심각도 잔여 문제 세 건은 계속 열려 있습니다. |
| 2026-09-15 | implemented | 비활성 지문 후보를 제안됨으로 표시하기 전에 대기열에 추가해 Norns 포화 복구를 재시도 가능한 상태로 유지했습니다. 용량 실패가 게시하지 않은 후보를 전달 완료로 보이게 할 수 없습니다. | `current change`; 집중 포화 재현과 Norns 내구성, 커버리지 및 런타임 검사 162개 통과, strict mypy 및 Ruff 통과. | 에이전트 역할이나 권한을 넓히지 않고 기록된 Low 심각도 잔여 문제 세 건을 해결합니다. |
| 2026-09-15 | implemented | 기존 판테온 및 프로젝트 구조 문서가 크기 상한에 도달해 구현된 T1/T2, Var, Vidar, Saga, Norns, Bragi 재생 계약을 이 집중 런타임 소유 문서로 통합했습니다. | `current change`; 캠페인 안전 검사 1,372개, 환경 의존 PostgreSQL 건너뜀 1개가 포함된 Cost Governance 격리 검사 170개, strict mypy, Ruff 및 구조/문서 게이트. | 에이전트 역할이나 권한을 넓히지 않고 기록된 Low 심각도 잔여 문제 두 건을 해결합니다. |
| 2026-09-15 | implemented | 런타임 동작을 바꾸지 않고 최종 CI 호환성을 복구했습니다. 검증된 실행 결과 분류를 집중 모듈로 옮기고, 평가 기준 테스트 후보를 신뢰된 대상에 결속하고, Norns를 `object.issue`를 통해 검증하고, 자연어 의미 체계 검출기가 정규 enum 검증을 잘못 분류하지 않도록 Var의 잠금된 비공개 판단 도우미 이름을 바꿨습니다. | `current change`; 집중 ControlLoop 패키지, 평가 기준 및 tier 테스트, Norns, Var, framework layout, semantic routing, Ruff, strict mypy, LOC, 번역 및 설계 검사. | 기록된 Low 심각도 잔여 문제 두 건은 유지됩니다. 역할, topic, 승인, 실행 또는 승격 권한은 바뀌지 않았습니다. |
| 2026-09-14 | implemented | 활동 귀속 변경에서 관련 없는 ActionRun fingerprint 필드를 제거해 영속 및 복구 식별자를 그대로 유지했습니다. | `current change`; 전체 mypy와 집중 Thor 내구성 및 복구 회귀 테스트. | 정확히 병합된 개정 번호의 배포 감사 및 활동 근거를 보존합니다. |
| 2026-09-14 | implemented | 운영 활동 귀속을 기계 행위자, 책임 `owner_agent`, 인증된 `producer_principal`로 분리했습니다. 컨트롤 루프 측정은 Heimdall, RCA는 Forseti, 시작 감사는 Saga, 관측 캠페인은 선언된 소유자에 귀속하며 Saga 감사 미러는 감사 대상 주체를 바꾸지 않고 Saga를 기록합니다. | `current change`; 서비스 계약, 컨트롤 루프, provider adapter, 관측 캠페인, 시작 probe, 파이프라인 및 Operator 투영 테스트. | 정확히 병합된 개정 번호의 배포 감사 및 활동 근거를 보존합니다. 역할, topic 또는 실행 권한은 바뀌지 않았습니다. |
| 2026-08-13 | in-progress | W0-W8 전체 완료 주장을 독립적으로 근거를 확인할 수 있는 구현 영역으로 교체했습니다. | 현재 변경 | 검증 완료 또는 enforce 운영을 주장하기 전에 실제 근거를 수집하고 별도 검토를 거친 승격을 완료합니다. |
| 2026-08-14 | implemented | 선택적 대화 T2 종합을 범위가 제한된 T1 답변 신호의 결정론적 충돌 평가 결과에만 실행하도록 했습니다. | `current change`, 집중 숙의 테스트 36개 및 framework layout 검사 | 에스컬레이션하지 않는 분기와 충돌로 에스컬레이션하는 분기의 통제된 런타임 근거를 보존합니다. |
| 2026-08-17 | implemented | 범위가 제한된 Huginn-Heimdall 연속성 근거 인계를 추가하고 인시던트 후보에 인식된 관측 사유를 보존했습니다. | `current change`; 작업처럼 보이는 위조 입력을 제외한 집중 추적-인시던트 체인 통과. | 이슈 #142에서 추적하는 통제된 실시간 시나리오 근거를 보존합니다. |
| 2026-08-23 | implemented | 정확한 아티팩트 복원과 독립적으로 검증된 Azure 효과 수집을 사용하는 Heimdall의 타입 지정 최종 ActionRun 관찰 경로를 추가했습니다. | `current change`; 실행된 작업 관찰, Azure 수집기, 조립, 런타임 topic 및 판테온 일치 검사. | 배포가 소유하는 서명된 컨텍스트 발급자를 바인딩하고 통제된 실제 종료 증적을 보존합니다. |
| 2026-08-23 | implemented | O7 불변 근거 소비자, 매니페스트 결합 인과관계 및 측정 단위 검증기, 영속 증적 저장소와 선택적 측정 작업을 추가했습니다. | `current change`; 운영 승격 소스, 실행기, 영속성, CLI 및 Terraform 검사. | 통제된 실제 배치 생산자를 구현하고 승격 검토 전에 작업별 근거를 축적합니다. |
| 2026-08-24 | implemented | 에이전트 역할, topic 또는 권한을 바꾸지 않고 운영 가설 계보에 선택된 모든 예상 효과와 독립 결과를 보존했습니다. 단일 속성만 있는 저장 레코드는 하나의 효과로 읽을 수 있고, 모호한 이중 필드 레코드는 안전하게 차단됩니다. | `current change`; `hypothesis_lineage.py`; `ActionOption.yaml`; 집중 계보 및 competency 검사 15개 통과. | 남은 계보 생산자, 서명된 컨텍스트 및 실제 배치 선행조건을 완료합니다. |
| 2026-08-25 | implemented | Thor가 Verdict를 전달할 때와 사람 승인 직후에 실제 시작 준비 상태 권한 상한을 다시 확인하도록 했습니다. 저하되거나 만료되거나 실패한 새로 고침은 AgentSpec, topic, 판단, 승인, 감사 또는 롤백 소유권을 바꾸지 않고 새 실행과 대기 중 실행을 실행기 I/O 전에 shadow로 강제합니다. | `current change`; Thor 내구 auto, 승인 및 권한 프로바이더 실패 회귀 검사, Pantheon 레이아웃 및 import gate. | 배포된 degraded-shadow ActionRun 하나를 보존하고 privileged 실행기가 호출되지 않았음을 증명합니다. |

### 남은 작업

- [x] [운영 학습 온톨로지](../rules-and-detection/operational-learning-ontology-ko.md)에 기록된
  대로 일대다 `expects` 링크와 런타임 예상 효과 계보를 조정하고 선택된 효과마다 하나의 독립
  결과를 보존합니다.
- [ ] Saga 감사 및 `object.issue` 게시 검사 지점을 단조 증가 개정 번호 CAS로 전진시키고,
  복제본 두 개에서도 감사 추가와 게시가 각각 한 번임을 보이는 회귀 검사를 보존합니다.
- [ ] 각 이슈 작업 ID를 전역에서 지문 하나와 요청 다이제스트 하나에 결속하고, 다른 지문에서
  같은 ID를 재사용하면 실패 시 차단됨을 보이는 회귀 검사를 보존합니다.
- [ ] 남은 선행조건을 완료합니다. 배포가 소유하는 서명된 컨텍스트 발급자를 바인딩하고,
  Forseti가 소유하는 남은 인과관계 계보 속성을 보존하며, 실제 런타임 생산자를 구성하고,
  통제된 실제 배치 생산자를 구현합니다.
- [ ] 에이전트 역할, topic 소유권, 모델 정책 또는 작업 권한을 넓히지 않고 운영 의존성을
  대상으로 선언된 성능 저하 동작을 입증합니다.
- [ ] [이슈 #1199](https://github.com/dotnetpower/fdai/issues/1199)를 완료합니다. 전체 인벤토리에서
  내구성 있는 기준 평가 작업을 발행하고 Forseti 판단과 Saga 감사 소유권을 유지하며 근거 공백을
  0으로 추론하지 않는 현재 Rule 점검 결과 요약을 구체화합니다.
- [ ] 하나의 고정된 런타임, 카탈로그, ActionType, 작업 흐름 및 시나리오 집합 리비전에서
  보존된 실제 shadow 코호트를 대상으로 선언된 KPI 수집기를 실행합니다.
- [ ] 승격 후보마다 표본 수와 신뢰 구간을 포함한 권위 있는 결과, 재발, 롤백 및 정책 이탈
  0건 근거를 보존합니다.
- [ ] 판테온 enforce 운영을 사용하거나 보고하기 전에 독립적인 승격 검토를 완료하고 권위 있는
  승격 집합 증적을 기록합니다.
- [ ] 검색한 사례 이력에 근거한 T2 제안, 이상 작업 후보, 경보 소음 학습 및 다른 모든 학습 근거
  소비자를 [학습 및 예측 결과 경계](#학습-및-예측-결과-경계)에 비추어 검토하고, 각 경로를 집중
  검사로 닫거나 기록합니다. 이 항목은 닫힌
  [이슈 #1541](https://github.com/dotnetpower/fdai/issues/1541)의 후속 강화 작업입니다.
- [ ] Mimir promotion 근거, Freyr utilization sampling, Loki recurring schedule 및 adversarial
  generation, Bragi reviewed activation의 production reader와 runner를 바인딩한 뒤 각 port의
  집중 runtime 근거를 기록합니다.
- [ ] Forseti retrospective what-if retained-input replay를 영속 저장소로 이식하고 재시작 후에도
  입력이 안전하게 replay되는 regression을 기록합니다.
- [ ] 영속 ordered-poison-halt 저장소를 production에서 켤지 결정한 뒤, 바인딩된 저장소 근거 또는
  명시적인 opt-in 결정을 기록합니다.

## 설계 개요

웨이브는 별도의 권위 원본이 아니라 의존성 순서를 설명합니다. 완료된 구현 상세는 현재
에이전트, 작업 흐름, 온톨로지 및 런타임 owner가 관리합니다. 이 문서는 조정 요약과 실제
프로세스에서 해당 owner를 연결하는 조립 규칙만 유지합니다.

| Wave | 범위가 제한된 결과 | 현재 owner |
|------|---------------------|------------|
| **W0** | 문서와 온톨로지 기반 | [에이전트 판테온](agent-pantheon-ko.md), [에이전트 작업 흐름](agent-workflows-ko.md) |
| **W1** | 에이전트 프레임워크, 고정 레지스트리, 토픽 및 two-port 골격 | [`agents/_framework/`](../../../services/core-control-plane/src/fdai/agents/_framework/) |
| **W2** | Saga, Mimir, Muninn 및 Norns 거버넌스 메커니즘 | [에이전트 판테온](agent-pantheon-ko.md) |
| **W3** | sensing, 판단, 위험, 롤백 및 shadow 실행 체인 | [에이전트 판테온](agent-pantheon-ko.md) |
| **W4** | 결정론 우선 대화와 중재 | [대화 숙의](conversational-deliberation-ko.md) |
| **W5** | 비용, 용량 및 복원력 전문 에이전트 | [에이전트 판테온](agent-pantheon-ko.md) |
| **W6** | 감사 가능한 인계와 보안 에스컬레이션 | [에이전트 판테온](agent-pantheon-ko.md) |
| **W7** | 독립적으로 승격하는 에이전트 간 작업 흐름 | [에이전트 작업 흐름 Shadow 롤아웃](agent-workflow-rollout-ko.md) |
| **W8** | KPI, 승격 및 성능 저하 근거 | [에이전트 판테온 KPI와 성능 저하 정책](agent-pantheon-ko.md#42-per-agent-kpi-성공과-성능-저하-신호) |

## 11. Wave 7 - Shadow 로 cross-agent workflows

롤아웃 순서, 작업 흐름별 shadow 게이트, 의존성 및 제외 범위는
[에이전트 작업 흐름 Shadow 롤아웃](agent-workflow-rollout-ko.md)이 소유합니다. 각 작업 흐름은
독립적으로 검토하며 이 wave에서는 어떤 작업 흐름도 enforce로 승격하지 않습니다.

## 런타임 조립 계약

`PantheonRuntime`은 고정된 에이전트 집합의 조립 경계입니다. 구현은
`services/core-control-plane/src/fdai/agents/_framework/runtime.py`에 있으며
`services/core-control-plane/src/fdai/runtime/bootstrap_pantheon.py`에서 조립합니다.

### 영속 권한과 재생

이 런타임 계약은 [에이전트 판테온](agent-pantheon-ko.md)의 고정 역할 경계를 보존합니다.
재시작 및 동시성 안전을 제공하지만 다른 에이전트에 판단, 승인, 실행, 감사, 복구 또는 게시
권한을 부여하지 않습니다.

#### 영속 보낼 편지함 규칙

소유자 로컬의 모든 영속 보낼 편지함은 같은 재시도 계약을 따릅니다. 안정적인 멱등성 키로
대기 의도를 쓰고, 소유 이벤트를 게시한 뒤에만 그 의도를 게시 완료로 표시합니다. 시작 복구는
대기 의도를 같은 멱등성 키로 다시 게시하므로 전달은 at-least-once이며, 소비자는 최선 노력
브로커 승인 대신 자체 멱등성 차단 장치에 의존합니다. 게시 후 표시 사이 구간에서 취소되면
완료 근거가 아니라 재생 가능한 상태로 처리합니다.
최종 보낼 편지함 행은 소유 변환 결과의 문서화된 재생 구간 뒤에 다이제스트 전용 tombstone으로
압축됩니다. tombstone은 중복 재전달을 억제하는 데 필요한 멱등성 키, 소유자, 토픽, 다이제스트,
보존 기한만 유지하고 전체 payload 본문과 변경 가능한 전달 metadata는 버립니다.

게시 점유는 차단 장치로 보호됩니다. 소유자는 게시하기 전에 대기 행을 점유마다 고유한 소유자
토큰과 주입된 시계 기준 `claimed_at` 임대로 점유합니다. 브로커 게시는 임대보다 짧은 제한 시간
안에서 실행되고, 제한 시간이 지나거나 호출자가 취소하면 취소된 뒤 종료를 기다립니다. 점유
토큰이 여전히 일치하는 compare-and-swap만 행을 게시 완료로 표시하거나 전송 실패 뒤 점유를
해제하므로, 임대를 회수당한 늦은 게시자가 다른 점유를 완료하거나 다시 열 수 없습니다. 시작
복구는 `pending` 행과 임대가 만료된 `publishing` 행을 명시적 백로그 한도까지 페이지 단위로
읽고 원래 멱등성 키와 payload로 다시 게시합니다. 게시에 실패한 행이나 형식이 잘못된 행은
기록한 뒤 연기하며 시작을 중단하지 않습니다. 범위가 제한된 유지 관리 작업이 연기된 행을 다시
게시합니다. Var 최종 승인, Saga 감사 항목, Muninn 운영 게시, Heimdall 관측 게시, Mimir 규칙 및
정책 게시, Bragi 게시 보낼 편지함이 이 계약을 따릅니다. 게시되지 않은 행은 항상 전체 재생
payload를 유지합니다. Heimdall은 8 KiB를 넘는 본문을 게시 완료 tombstone에서만 버리고, 512 KiB를
넘는 게시는 checkpoint를 쓰기 전에 거부합니다.

#### Tier, 승인 및 명령 신원

- 권한 상한은 액션을 실제 시작 T0, T1 또는 T2 tier로 평가합니다. 대체 경로 액션은 T0
  권한을 물려받을 수 없습니다.
- 라우팅은 중첩된 `resource.type`, 중첩된 `resource.resource_type`, 기존 평면 형태 순서로
  추측 없이 해석합니다. T1은 잘못된 재사용 신원, 횟수, 신뢰도 및 유사도 근거를 차단합니다.
- T2는 대상, 리소스 유형, 인용 및 ActionType을 신뢰된 라우팅 컨텍스트에 결속합니다. 인용된
  라우팅 규칙 중 정확히 하나가 `remediates` 또는 `alternatives`로 ActionType을 허용하며,
  같은 규칙이 위험, 사람 승인 및 실행 렌더링까지 이어집니다. 카탈로그에 선언된
  `alternatives`는 의미 유사도보다 먼저 적용하는 결정론적 근거 확인 자료입니다.
- 혼합 모델 합의에는 서로 다른 범위 제한 정규 모델 신원이 필요합니다. 서로 다른 래퍼로
  감싼 모델 하나가 자체 정족수를 충족할 수 없습니다.
- Var는 원본 ActionRun 멱등성 키를 보존하고 정규화된 각 principal 결정을 감사가 포함된
  StateStore 비교 후 교환(CAS) 집계에 결합합니다. 동시 복제본은 변경할 수 없는 같은 결정
  집합에서 정족수를 계산합니다.
- Var는 티켓을 제거하기 전에 최종 승인 하나와 게시 검사 지점을 저장합니다. 시작 처리는 정확한
  대기 필드를 조회하고 소비자가 시작되기 전에 종결 집계를 완료한 뒤 저장된 최종 페이로드를
  다시 게시하므로 사람에게 같은 결정을 다시 요구하지 않습니다.
- Thor는 상관관계, 액션 ID와 유형, 리소스, 액션 멱등성, 매개변수, 정족수, 시작 주체, 롤백
  계약, 판정 및 작업 흐름 계보에 수명 주기 동안 안정적인 ActionRun 신원 하나를 기록합니다.
  Thor는 멱등성이나 리소스를 점유하기 전에 초기 영속 ActionRun을 대기 중 상관관계 점유로
  원자적으로 생성합니다. 첫 영속 수명 주기 게시는 이를 활성 상태로 승격합니다. 리소스
  경합이 발생하면 재시도할 수 있도록 유지하지만 재시작 복구에서는 제외합니다. 대기
  중에는 정규 신원만 권위가 있으므로 재시도는 승격 전에 shadow 상태 같은 실시간 비신원
  필드를 갱신합니다. 활성 행과 종결 tombstone은 정규 신원 다이제스트를 보존하므로 정확히
  같은 재생만 행을 복구할 수 있습니다. 중복 디스패치는 해당 상관관계만 읽고 복제본 간
  재시작 복구 탐색을 실행하거나 관련 없는 리소스 점유를 변경하지 않습니다. Thor는 동일한
  활성 재생을 반환할 때 다른 복제본의 실행이나 로컬 뮤텍스를 캐시하지 않습니다.
  이전 버전 tombstone은 비어 있지 않은 멱등성 generation이 일치할 때만 완료로
  처리합니다. Var는 결정 및 최종 레코드를 이 신원으로 범위화하고 명시적 액션 필드와 함께
  전달하며, Thor는 오래된 승인을 실행 전에 거부합니다. Thor와 Var는 상관관계도 이 신원에
  결속하므로 다른 멱등성 generation이 같은 상관관계를 재사용할 수 없습니다.
- 재시작은 만료된 승인 구간을 되살리지 않습니다. Thor는 프로세스가 중지된 동안 승인 시간이
  지난 경우 실시간 유지 관리에서 사용하는 것과 같은 가시적인 실패 시 안전한 만료 결과로 닫아,
  오래된 사람 승인 티켓이 리소스를 붙잡지 않게 합니다.

#### 롤백 점유와 종결 재생

- Vidar는 프로바이더 복구 전에 상관관계와 정규 롤백 명령 다이제스트를 소유자 토큰 및 범위가
  제한된 점유 유효 기간과 함께 점유합니다. 하나의 안정적인 효과 필드 허용 목록이 실행기 입력과
  다이제스트를 모두 정의합니다. 매개변수, 액션 신원, 작업 흐름 계보 및 롤백 데이터는 포함하고
  다시 생성되는 `terminal_at` 같은 전달 메타데이터는 제외합니다.
- 경합하는 복제본은 유효한 점유를 변경하지 않고 재시도 가능한 처리기 실패를 발생시킵니다.
  검증된 만료 뒤의 재처리는 모호한 점유를 `execution_unknown`으로 닫고, 개정 번호 CAS는 늦은
  소유자의 완료를 차단합니다.
- 프로세스 내부 및 영속 재생은 전체 명령 다이제스트를 검증합니다. 종결 재생은 schema, 개정
  번호, 소유자 토큰, 점유 유효 기간, 범위 제한 신원, 상태, 메모 및 증적도 검증합니다. 성공한
  롤백은 정규화되고 공백이 아니며 범위가 제한된 `rollback_ref`를 제공해야 합니다. Thor도
  리소스 점유를 해제하기 전에 같은 증적 경계를 독립적으로 검증합니다.
- Vidar는 점유, 종결 및 게시 레코드를 같은 ActionRun 신원으로 범위화하고 액션 유형, 리소스,
  롤백 계약과 함께 전달합니다. Thor는 오래되었거나 일치하지 않는 롤백을 무시하고 현재 실행과
  점유를 그대로 유지합니다.

#### 파라미터 검증, 멱등성 및 보호 장치

상관관계 재사용은 실행 시 검증합니다. 같은 작업 신원의 재시도는 멱등성을 유지하지만, 같은
상관관계 아래 다른 작업은 모호한 전달이 아니라 감사 가능한 최종 차단 결과가 됩니다. Thor는
`ActionRun`을 만들거나 영속화하기 전에 판정 파라미터를 범위 제한합니다. 너무 크거나 깊게
중첩되었거나 스키마에 맞지 않는 필드는 영속 실행기 맥락, 승인 맥락 또는 감사 자료가 되기 전에
차단됩니다.

실행 가능한 non-shadow 판정은 wire에 일곱 가지 보호 장치를 모두 포함합니다. 정지 조건,
검증된 롤백, 영향 범위, 예행 실행, 논리적 대상 잠금, 안정적인 멱등성 키, 2단계 감사입니다.
Thor는 Forseti가 전달한 `auto` 또는 `hil` 판정에 보호 장치가 하나라도 없으면 멱등성 키의
형태나 첨부된 kinetic 제안과 관계없이 실행기 I/O 전에 거부합니다. 직접
`dispatch_verdict()` 호출은 프로세스 내부 테스트 경계이며, 소스 경계 테스트가 Thor의 타입이
지정된 포트를 유일한 운영 호출자로 고정합니다. Forseti는 실행 가능한 rule 및 중재 판정에 이 보호
장치를 담아 내보냅니다. 자문 판정은 타입이 지정된 안정 멱등성 키를 유지하지만 작업 권한은
부여하지 않습니다. Forseti의 rule cache는 Mimir가 인증한 엄격히 더 새로운 rule 개정만
수락합니다.

`dry_run_evidence` 보호 장치 필드는 예행 실행 보호 장치의 출처를 밝힙니다.
`upstream_receipt`는 발생 이벤트가 가져온 what-if 또는 예행 실행 증적을 인용합니다.
`declared_obligation`은 결정적인 의무 식별자일 뿐이며 예행 실행이 실제로 수행되었다는 증거가
아닙니다. Thor는 의무에만 의존하는 non-shadow 전달을 `dispatch:dry_run_obligation_only`로
집계합니다. `evaluate_pre_dispatch`를 호출하는 Core 실행기 경로는 자체 예행 실행 증적을
계산하며, 위험도가 높거나 의무만 있는 디스패치에는 Thor 사전 시뮬레이터가 증적을 제공합니다.
자세한 내용은 [Pre-flight simulation 및 증적](#pre-flight-simulation-및-증적)을 참조하세요.

첫 `object.action-run` 게시가 실패하면 수명 주기 인계로 보지 않습니다. Thor는 게시되지 않은
실행을 제거하고, enforce `auto` 경로에서는 게시되지 않은 정확한 리소스 점유를 포기하며, 리소스
잠금을 해제하므로 다시 전달된 판정은 같은 멱등성 키로 재시도됩니다. 실패한 시도와 더 이상
일치하지 않는 영속 행은 그대로 두고 집계합니다.

#### 영향 범위와 배치 시맨틱

현재 런타임은 `ActionAttempt`, `attempt_id`, 타입이 지정된 시도별 롤업 필드를 노출하지
않습니다. 배치 시맨틱은 계획되어 있습니다. 종료 조건: multi-target ActionType이 독립 attempt
신원, 대상별 rollback 격리, 타입이 지정된 롤업 필드, Saga의 시도별 및 롤업 감사 항목을
생성합니다. 계획된 실패 격리는 실패한 시도를 자기 타깃으로 제한하고, 형제 성공을 보존하며,
혼합 결과를 롤업 `ActionRun`에 기록하고, 시도별 및 롤업 감사 항목을 모두 씁니다.
파티션 키는 리소스별 순서만 보존하며 리소스 간 순서는 보장하지 않습니다.

#### 롤백 정족수와 복구 결정

Thor는 실행 가능한 상태로 `verdicted`를 떠나기 전에 ActionType 의미에서 되돌릴 수 없는 작업의
정족수를 다시 계산합니다. 사람 승인은 정확한 `ActionRun` 신원, Var producer 근거, 승인 멱등성
키, 승인자 집합 및 정족수 근거에 결속됩니다. 영속 Var 재조회가 설정되어 있으면 Thor는 전이
전에 현재 저장된 승인을 요구합니다. Var는 게시를 점유하기 전에 결정을 영속화하고 소비자는 게시
도중에 승인을 받을 수 있으므로, 재조회는 Var 보낼 편지함의 `pending`, `publishing`,
`published` 상태를 모두 받아들입니다. Thor가 캐시한 `ActionRun` 신원은 읽을 때마다 수명 주기
동안 고정되어야 하는 모든 필드를 다시 검증하므로, 승인이나 롤백이 `ActionRun`에 더 이상 없는
파라미터에 결속되지 않습니다. Var도 ActionType 의미에서 정족수를 다시 계산하고, 알 수 없거나
카탈로그가 없는 작업은 되돌릴 수 없는 작업의 최소값이 필요한 것으로 처리합니다. Vidar는 Thor가
소유한 `ActionRun` 메시지 중 신원과 롤백 근거가 일치하는 경우에만 롤백을 받아들입니다.

Forseti는 `auto`를 상한으로만 취급합니다. 거버넌스가 적용된 되돌릴 수 있는 ActionType 의미가
없거나 판정에 정족수 `>= 2`가 필요하면 런타임은 결정을 사람 승인(`hil`)으로 낮춥니다. 판단 표는
주입되며 digest가 찍힙니다. Forseti는 맨 상관관계로 대체하지 않고 이벤트 신원과 작업에서
결정론적 verdict 키를 기록합니다. retired 또는 revoked 규칙도 `auto`를 `hil`로 낮춥니다.
중재 결정은 Odin이 보낸 경우에만 수락하며, 해결된 중재 verdict를 내보내기 전에 영역별 처리
결과를 반영합니다. 해결된 중재 verdict에는 결과 자율성 상한과 Thor가 강제할 작업 멱등성 키가
포함됩니다.

`execution_unknown`은 성공이나 실패한 작업이 아니라 복구 결정입니다. Vidar는 롤백 계약을
통해서만 이를 닫거나, 필요한 영속 롤백 전제 조건이 없으면 가시적인 `rollback_refused` 상태로
닫습니다. Thor는 rollback 실패나 거절 뒤에 리소스 잠금을 해제하거나 차단해 멈춘 실행이
가시적으로 남되 리소스를 무기한 점유하지 않게 합니다.

롤백 준비 상태는 `(ActionType, rollback_contract)` 쌍 단위로 검증합니다. 적용 모드 조립은 시작
전에 바인딩된 ActionType 시맨틱 카탈로그에서 실행 가능한 모든 쌍을 도출하고, 해당 계약용 일반
실행기나 정확한 액션별 실행기를 요구합니다. 되돌릴 수 없는 계약과 실행기가 필요 없는 계약은
제외합니다. 계약 이름만으로는 바인딩된 실행기가 다른 ActionType을 복구할 수 있다는 근거가
되지 않습니다. 예를 들어 AKS acceptance `ops.scale-out` 실행기는 일치하는 `state_forward_only`
롤백 어댑터가 함께 제공될 때만 비 shadow 실행에 바인딩됩니다.

#### 중재, 서술, 감사 및 전문 에이전트 재생

- Forseti는 대기 중인 중재 맥락, 영역 간 후보 기한, 완료된 후보 차단 장치, 중재 완료
  표시를 영속화합니다. 재시작 뒤에도 저장된 Odin 결정을 소비하고 해결되지 않은 사례를
  가시적으로 닫으며 같은 중재에 대해 두 번째 완료를 내보내지 않습니다. 대기 중인 영역 간
  기한은 상관관계마다 sleep task를 만들지 않고 정렬된 기한 위의 범위가 제한된 timer 하나로
  예약합니다.
- Bragi는 도착 순서대로 턴 번호를 예약하면서 대화, 인계, 턴 보낼 편지함을 영속화하므로 느린
  응답기나 브로커 게시가 복구 뒤 세션 대화 기록 순서를 바꾸지 않습니다.
- Bragi가 소유한 인계 에스컬레이션과 턴 이후 검토 게시는 다른 소유자 로컬 게시와 같은
  영속 보낼 편지함 규칙을 사용합니다. 복구는 같은 멱등성 키로 다시 게시하고 broker publish가
  반환된 뒤에만 행을 게시 완료로 표시합니다.
- Saga의 감사 체인은 영속 head에서 계속됩니다. 소비자가 시작되기 전에 변경, 게시, 완료를
  검사 지점으로 기록하므로 로컬 감사 복사본이 재시작 뒤 새 체인을 만들지 않습니다.
- 메모리 내부 및 공급자 기반 감사 체인은 entry hash를 다시 계산해 필드 변조를 감지하고, 봉인된
  head 또는 예상 길이와 비교해 잘림을 감지합니다. Saga는 anchored checkpoint에서 증분 검증하고
  전체 체인을 스캔하지 않고 상관관계 인덱스로 재생을 제공합니다.
- Odin은 상관관계별 중재 결정 차단 장치를 저장합니다. 다시 전달된 중재 요청은 Odin이 같은
  사례의 순위를 다시 매기지 않고 원래 결정을 재생합니다.
- Forseti는 각 요청에 영역별 중재 계보와 최신성을 보존합니다. 오래된 영역 신호는 집계하되
  결합에서 제외하며 합성 최신 중재 입력으로 바꾸지 않습니다.
- Heimdall, Njord, Freyr는 재생된 원본 이벤트를 받기 전에 주입된 저장소에서 관측, 자문, 예측
  차단 장치를 복구하므로, 재전달은 중복 구간이나 오래된 기준선을 전진시키지 않고 완료되지
  않은 게시를 끝낼 수 있습니다.

#### 영속 인계와 학습

- Saga는 외부 변경 전에 각 에스컬레이션을 런타임 StateStore에서 점유합니다. 타입 지정 인계는
  안정적인 작업 ID 하나를 정확한 이슈 내용에 결속하는 추가형
  `IdempotentIssueTrackerAdapter`를 사용합니다. 기존 `IssueTrackerAdapter` 구현은 직접
  에스컬레이션에 계속 사용할 수 있습니다.
- 배포되는 `StateStoreIssueTrackerAdapter`는 이슈 상태와 정확한 작업 결과를 CAS로 영속화하고
  소비자가 시작되기 전에 범위 제한 실제 변환 결과를 복원합니다. 실제 프로바이더 재정의는
  프로바이더 측에서 같은 영속성을 제공하며 `InMemoryGithubIssueAdapter`는 타입 지정 런타임
  인계의 테스트에만 사용합니다.
- Saga는 변경, 감사, 게시 및 완료 검사 지점을 기록합니다. `object.issue`를 게시한 뒤에만
  완료를 기록합니다. 버스가 없으면 이전 검사 지점을 대기 상태로 유지하고 재시도 가능한 실패를
  발생시킵니다. 종료 정보는 범위가 제한된 발생 댓글 목록 밖에 두고 CAS 전에 검증합니다.
- Saga 인계 이슈 구체화는 재시작 시 게시되지 않은 `object.issue` 레코드를 복구합니다. 이전
  방식 인계 fallback은 이슈를 만들거나 댓글을 남기기 전에 문제 지문으로 중복 제거합니다.
- Norns는 인계 멱등성 키를 점유하고 대기 작업을 영속 지문 횟수에 CAS로 적용하며, 게시 또는
  결정론적 보류가 전달 완료를 표시할 때까지 각 후보를 유지합니다. 시작 처리는 정확한 대기 필드를
  범위가 제한된 항목 하나씩 조회합니다. 차단된 선두 항목은 복구를 멈추지만 다음으로 성공한
  flush는 그 뒤의 영속 후보를 계속 처리합니다. 용량을 검증하고 후보를 추가한 뒤에만 지문을
  제안됨 집합에 넣으므로 포화 복구도 다시 시도할 수 있습니다.

> **현재 제한 사항:** 동시 Saga 복제본은 작업에 결속된 외부 변경 한 번 뒤에도 감사 및 이슈
> 게시 이벤트를 중복 추가할 수 있습니다. 하류 게시 멱등성과 Norns 중복 제거가 영향을
> 제한합니다. 배포되는 이슈 어댑터도 작업 ID 결속을 지문 하나의 범위에서만 확인합니다. Saga의
> 별도 영속 인계 점유가 배포되는 타입 지정 호출자의 위험을 완화합니다.

#### 범위가 제한된 공유 상태

`StateStore`는 제거 연산 두 개를 노출합니다. `delete_states_beyond(prefix, retain_newest)`는
`read_states`와 같은 순서로 변환 결과 한도를 넘는 가장 오래된 행을 제거합니다.
`delete_state(key)`는 만료된 재생 차단 장치처럼 권한이 없는 정확한 행 하나를, 소유자가 범위가
제한된 보존 요약을 기록한 뒤 제거합니다. 두 연산 모두 감사 항목이나 권한 기록에는 사용하지
않습니다. 적용 모드 조립은
명시적인 `thor_state_store`, `vidar_state_store`, `var_state_store`, `forseti_state_store`
바인딩을 요구합니다. Var 복구가 영속이면 프로덕션은 shadow 및 enforce 모드 모두에서 Thor
저장소도 제공하므로 미완료 정족수와 해당 ActionRun이 함께 재개됩니다. 또한 프로덕션은 선택적
거버넌스 및 전문 에이전트 저장소인 `forseti_state_store`, `bragi_state_store`,
`odin_state_store`, `proposal_rate_limit_state_store`, `heimdall_state_store`,
`njord_state_store`, `freyr_state_store`를 인시던트 감사 저장소에 연결합니다.
`ordered_poison_halt_state_store`는 명시적 선택으로 유지합니다. Owner 전용 Operator clear 표면은
있으며, 영속 halt 저장소를 프로덕션에서 켤지는 기록된 남은 결정입니다. 적용 모드 조립은 모든 정확한 에이전트 소유 바인딩을 요구하며, 하나라도 없으면
프로세스 로컬 승인 또는 롤백 상태를 사용하기 전에 시작을 차단합니다. 비활성 Thor 행은 안정적인
멱등성 generation을 유지합니다. 같은 generation은 계속 억제하고 다른 generation은 실패 시
차단합니다. Generation을 알 수 없는 기존 tombstone도 재사용 권한을 부여하지 않습니다. 활성
행은 리소스 점유, 수명 주기 순위 억제 또는 실행 전에 검증합니다. 해제된 리소스 점유는
상관관계, 멱등성 키 및 액션 지문이 모두 같아야 완료된 같은 실행으로 인정합니다.
장기간 실행되는 에이전트는 재생된 작업을 받기 전에 영속 복구 상태를 범위가 제한된 페이지로
읽습니다. 키별 잠금은 참조 수를 추적하거나 최종 완료 뒤 회수하므로, 축출되었거나 완료된 키가
범위 없이 프로세스 로컬 잠금을 남기지 않습니다.
In-process bus, testing bus, local bus는 보존된 묶음과 dead letter를 범위 안에 둡니다.
버려진 consumer group 상태는 제한 없이 쌓이지 않고 만료됩니다. 이전 tick이 아직 실행 중이면
maintenance tick은 합쳐지므로 느린 상태 작업이 무제한 backlog를 만들지 않습니다. Redrive는
명시적 cap을 적용한 dead-letter batch를 읽고 남은 backlog를 다음 운영자 작업의 근거로
기록합니다.

### 대화형 액션 재진입

Bragi는 `object.event`의 단독 쓰기 담당인 `Huginn.ingest`에 연결된 `proposal_sink`를 사용하며
변경 토픽을 게시하지 않습니다. 제안은 운영자를 `initiator_principal`로 포함하고 추적 가능한
상관관계 ID를 반환하며 실행하지 않고 타입 지정 파이프라인 진행만 렌더링합니다. Forseti와 Thor는
시작 주체를 보존하고 Var는 자기 승인을 차단합니다. 진입 RBAC는 `Contributor` 미만의 액션
요청을 차단합니다. Huginn은 `event_type == "operator_request"`일 때만 운영자 제안 필드를
수락하고 `operator_initiated`를 엄격한 Boolean으로 처리하므로 외부 신호가 운영자 액션을
위조할 수 없습니다.
시작 주체 principal은 멱등성 재료에 포함되며, 타입 지정 파라미터는 대화 계보에 대한
다이제스트 또는 참조와 액션 인자만 담고 원시 질문 텍스트나 원시 세션 식별자를 담지 않습니다.
Huginn은 원시 요청의 형태와 깊이를 제한하고, 안전하지 않은 신원 문자를 거부하며, 수락한 원본
시간을 범위가 제한된 오차 안에서 UTC로 정규화하고, 신뢰할 수 없는 입력에는 내용 없는 거부
횟수를 기록합니다. 원시 운영자 요청은 엄격하게 제한된 필드와 서버가 소유한 채널만 유지합니다.
인증된 서비스 producer에는 `ingress`, Bragi의 프로세스 내부 제안 진입점에는 `conversation`을
사용합니다. Huginn은 호출자가 제공한 시작 주체, ActionType, params 같은 소유되지 않은 권한
필드를 원시 유입에서 복사하지 않으며, Forseti의 RBAC는 알 수 없는 시작 주체를 verdict 형성
전에 차단합니다.

### Phase-2 기능 메커니즘

이 메커니즘은 고정 역할을 확장하지 않으며 새 역할 바인딩이나 기본 실행 권한을 추가하지
않습니다.

#### Pre-flight simulation 및 증적

`ThorPreflightSimulator`는 고위험 또는 의무 전용 executor I/O 전에 범위가 제한된 읽기 전용
시뮬레이션을 제공합니다. 통과 증적은 schema version, ActionRun 신원, ActionType, target,
parameter digest, simulator 신원과 version, outcome, timestamp, reason, receipt digest를
기록합니다. Thor는 receipt digest를 `dry_run_receipt`로 사용합니다. 바인딩 없음, 실패,
timeout, 오류 또는 변경을 수행하는 시뮬레이션은 executor I/O 전에 안전하게 차단됩니다.

#### DR failover 계약 및 rollback rehearsal

Vidar는 Thor가 `ops.failover-primary`를 계속하기 전에 정확한 ActionRun 신원에 대한
`dr_failover_contract` 결정을 수락하거나 보류합니다. 보류된 결정과 주입된 clock timeout은
실행을 거부합니다. Rollback rehearsal port는 dry-run-only입니다. 바인딩되지 않은 port는 보이는
no-op 근거를 기록하고, 바인딩된 port는 digest-bound rehearsal 증적과 DR readiness fact를 만듭니다.
Rehearsal은 증적이 `object.rollback`에 게시된 뒤에만 주기를 완료하며, 복구는 저장되었지만 게시되지
않은 증적을 원래 신원으로 다시 게시합니다.

#### Issue-close promotion 근거 및 Mimir 유지 관리

Mimir는 주입된 읽기 전용 port를 통해 rule source를 polling하고 regression 근거를 실행하며
deprecation 후보를 기록합니다. 검토된 promotion 하나는 fingerprint, promotion PR, correlation에
대해 Saga issue-close promotion 근거를 최대 한 번 방출할 수 있습니다. 대기 중인 게시는 같은
key로 재생되며, clean start 뒤 재발하려면 새 검토 promotion이 필요합니다.

#### Norns quiet-window 적격성

Norns는 `object.rule-candidate`에 비활성 quiet-window close 적격성을 게시합니다. 이슈를 직접
변경하지 않습니다. Saga는 계속 이슈 종료 담당자이며, 종료 전에 Mimir promotion 근거와 깨끗한
재발 없음 구간을 기다립니다. Saga는 issue-close 적격성을 범위가 제한된 영속 상태에 보관하고
종료 검사 전에 다시 불러옵니다. 각 자동 종료는 revision compare-and-swap으로 진행하는 영속
checkpoint입니다. `issue_auto_close_intent` 감사, 멱등적인 외부 종료 직전의 재발 재확인, 최종
`issue_auto_close` 감사, `object.issue` 게시, 완료 순서로 진행합니다. 재발이 확인되면 최종
`issue_auto_close_cancelled` 감사와 함께 종료를 취소합니다. 복구는 이슈가 이미 닫힌 경우를
포함해 대기 중인 checkpoint를 페이지 단위로 처리합니다.

#### Operator-request 증적 및 schema learning

Raw-ingress `operator_request` 이벤트는 idempotency key, correlation id, initiator, ActionType,
canonical params digest, resource id, producer identity, validity window를 결속하는 서명된 증적을
가집니다. Huginn은 누락, 만료, replay, 불일치, 검증 불가, 알 수 없는 producer 증적을 거부합니다.
Schema learning은 hot path에서 범위가 제한된 content-free fingerprint를 기록하고 maintenance 중
비활성 `schema_cluster.evidence`를 게시합니다.

증적 schema `1.1.0`이 기본값이며 `canonical_workflow_action_digest`도 결속합니다. Workflow
lineage digest는 존재 여부를 구분하므로 lineage가 없을 때와 비어 있을 때 서로 다른 digest가
나옵니다. Schema `1.0.0`은 workflow lineage가 없는 요청에만 허용합니다. Huginn은 게시 전에
증적 replay 차단 장치를 pending으로 예약하고, 게시와 deduplication checkpoint가 성공한 뒤
확정하며, 게시가 실패하면 자신이 예약한 pending 항목만 해제합니다. 차단 장치는 주입된 시계
기준으로 `expires_at`에 허용 clock skew를 더한 시점 뒤에 만료되며, 범위가 제한된 집계 요약과
함께 제거됩니다. Core는 시작 시 Core 및 Operator signing seed에서 신뢰하는 producer 공개 키를
도출하고 `core-control-plane`으로만 서명합니다. Schema-cluster 근거는 이벤트 유형 인가
검사를 통과한 뒤에만 기록합니다.

#### Freyr sampling 및 Loki scheduling/adversarial generation

Freyr는 주입된 읽기 전용 sampler로 utilization을 표본 추출합니다. 바인딩되지 않았으면 sampler는
runtime degraded가 아니라 보이는 no-op을 보고합니다. Sampler 호출은 제한 시간으로 묶이며 초과하면
`capacity_sampling:timeout`을 기록합니다. Freyr와 Njord는 오래된 표본의 중복 차단 장치를
완료하므로, 다시 전달된 오래된 표본은 재처리되지 않고 중복으로 처리됩니다. Forecast는 governed advisory-to-verdict
경로가 Forseti를 통해 shadow/HIL proposal을 낼 때까지 자문 근거로 유지됩니다.

Loki의 결정론적 recurring scheduler는 due window마다 완전한 always-HIL chaos proposal 하나를
내거나 보이는 hold를 기록합니다. 점유된 window는 재시작 뒤 복구되거나 범위가 제한된 사유와 함께
hold되며, 조용히 건너뛰지 않습니다. 영속 보낼 편지함과 bus가 모두 없으면 proposal은
`publication_unavailable`이 되고 예약을 해제합니다. Adversarial scenario generator는 기본 바인딩이 없는 주입형
off-path port입니다. 수락된 candidate는 비활성이며 frozen corpus에 대해 regression-gated됩니다.
Heimdall의 recovery-effect 관측 키에는 게시된 resource id가 포함되므로, 한 correlation 안의 서로
다른 리소스 관측이 하나의 키로 합쳐지지 않습니다.

#### Poison-halt clear surface 및 publication replay 근거

Ordered poison halt는 Owner-only Operator route가 shared pantheon-object transport로
multiplex되는 logical `fdai.operator.ordered-poison-halt.clear.v1` topic의 요청을 영속 수락할
때만 해제됩니다. Core는 consumer를 재개하기 전에 topic, group, agent, halt revision/digest,
retained DLQ parked-record key, offset, digest를 검증하고 감사된 compare-and-swap clear를
수행합니다. 영속 halt 저장소는 opt-in으로 남습니다.

Operator는 principal, halt, parked-record 근거 digest를 포함한 정확한 canonical clear 요청에
operator-request 증적으로 서명합니다. 증적 발급기가 구성되지 않으면 route는 `503`을 반환합니다.
수락 단계는 게시 전에 저장된 proposal을 임대와 소유자 토큰으로 점유하고, 그 점유에 대한
compare-and-swap으로 게시 완료를 표시하며, 전송 실패 뒤에만 점유를 해제합니다. 다른 활성 점유가
있으면 요청은 수락되어 대기 중인 것으로 보고됩니다. Core는 신뢰하는 `operator-service`
producer, 만료, replay 차단 장치, Owner 역할, halt marker의 key, offset, group, topic 결속,
multi-handler group 문법, 요청 TTL을 검증합니다. 영속 halt compare-and-swap 전에 증적 replay
차단 장치를 확정하고, DLQ 근거 검색을 제한 시간과 레코드 수로 제한하며, 해제된 ordinal
consumer group만 재개합니다. 거부된 clear는 감사되고 조회할 수 있으며 집계됩니다.

Provider-harness restart replay 검사는 Bragi, Var final approval, Saga audit outbox, Muninn,
Mimir, Heimdall, Odin publication replay를 다룹니다. 영속 publication replay와 Odin 재전달에 대한
실제 provider matrix는 loopback Redpanda v26.2.2와 PostgreSQL에서 두 번 통과했습니다(각 실행
30개 테스트). 배포 환경의 실제 broker 근거는 deployment-owned 검증 단계로 남습니다.

#### Forseti what-if 및 cost annotation

Forseti retrospective what-if replay는 judge-only이고 비활성입니다. 보존된 judgment input을
versioned contract로 비교하고 권한을 바꾸지 않는 disagreement 근거를 게시합니다. What-if 키에는
correlation이 포함되므로 같은 규칙을 다른 이벤트에 재생한 결과가 구분됩니다. 실행 가능 및
자문 Verdict와 ArbitrationRequest는 범위가 제한된 `cost_annotation` 근거나 명시적 unavailable
상태를 담습니다. Odin은 이를 보존하고 Thor는 non-identity metadata로 저장합니다.

#### Bragi intent-training loop

Bragi는 범위가 제한되고 consent-filtered이며 digest-only인 검증된 routing outcome에서 shadow 전용
intent-training 근거를 기록합니다. Candidate 평가는 off-path, 결정론적, regression-gated, audited
입니다. Routing 권한은 바뀌지 않으며 reviewed activation은 별도 binding으로 남습니다. Norns는
이 근거와 `object.post-turn-review`의 다른 비 review 종류를 관측 가능한 비학습 결과로 기록하며,
`kind: post_turn_review`만 학습기 검토에 들어갑니다.

#### Multi-target batch

명시적이고 범위가 제한된 target list가 있는 multi-target Verdict는 rollup `ActionRun` 하나와
대상별 독립 `ActionRun` 하나씩을 만듭니다. 각 시도는 안정적인 신원, resource lock,
idempotency key, 보호 장치, pre-flight/audit/executor/effect 경로, target-scoped Vidar rollback을
가집니다. Rollup은 count, 실패 및 rollback target digest, 종료 규칙, 영속된 범위 제한 target
list를 기록하므로 재시작 후 승인도 같은 set에 결속됩니다. Rollup은 rejected와 `deny_dropped`
대상을 따로 집계하며, rejected 또는 deny-dropped 시도가 하나라도 있는 종료 batch는
`batch_refused_attempt` outcome과 함께 `rollback_failed`가 됩니다. Single-target run은 기존
신원과 payload를 유지합니다.

#### Muninn compaction

Muninn은 게시된 행 64개마다 그리고 maintenance 시 publication outbox를 compact하며, 5,000행
retention window에서 최대 64행 범위 안으로 제한됩니다. In-memory StateStore test double은 감사
write rollback을 위해 touched row만 snapshot합니다.

### 조립과 수명 주기

- `PantheonRuntime.build(provider, raw_event_topic)`는 활성 에이전트를 인스턴스화하고 하나의
  `EventBusBridge`를 바인딩하며, 에이전트별 소비자 그룹에서 선언된 각 구독을 등록합니다.
- 원시 유입은 별도의 판테온 소비자 그룹을 사용하며 Huginn을 통해 진입합니다. 기본 컨트롤
  루프의 레코드를 가로채거나 해당 루프의 의존성이 되지 않은 채 나란히 실행합니다.
- `run()`은 소비자 실패를 격리하고 범위가 제한된 일시적 실패를 재시작하며 정상 형제 소비자를
  계속 실행합니다. 종료 시간도 제한됩니다.
- 시작은 recovery-effect observer intake를 연결하고 재생 전에 ContextIndex 복구를 되살리며,
  ContextIndex 봉인에 영속 Saga 감사를 사용할 수 없으면 실패 시 안전하게 닫습니다.
- 런타임은 기본적으로 활성화된 shadow입니다. `FDAI_START_PANTHEON=0`으로 비활성화하며,
  소비자 조립이 없으면 in-memory 대체품을 만들지 않고 명시적으로 건너뜁니다.
- 별도 검토된 승격이 enforce를 활성화하기 전까지 Thor는 `enforce=False`를 유지합니다. Enforce
  조립에는 영속 Saga 감사 바인딩과 진행 중 ActionRun의 영속 저장소가 필요합니다.
- Vertical 간 중재에서는 헌법의 hard constraint가 부적격 선택지를 먼저 제거한 다음 Odin이
  남은 soft objective의 순위를 결정합니다.

### 학습 및 예측 결과 경계

관찰 우선 기본 프로필에서 학습된 패턴과 예측은 자문 근거로만 남습니다.
[런타임 배포 프로필](../deployment/runtime-deployment-profiles-ko.md#설계-개요)의
`governed-execution` 추가 기능만 이를 선택합니다. Core 조립은
`RuntimeProductSelection.governed_execution`으로 이 값을 한 번 읽습니다. 컨트롤 루프 빌더가 값을
컨트롤 루프에 전달하고, Pantheon 조립은 컨트롤 루프의 값을 Forseti에 전달합니다. 환경 이름,
포크 표시, 패키지 존재 여부, `FDAI_PANTHEON_ENFORCE`, 실행기 바인딩은 이 추가 기능을 선택하지
않습니다. 선택 자체는 권한을 부여하지 않습니다. 변경되지 않은 risk gate, Var 승인, Thor 수명
주기, 안전장치 및 승격 상태가 여전히 모든 결과를 결정합니다.

| 입력 | 기본 프로필 | `governed-execution` 추가 기능 선택 |
|------|-------------|----------------------------|
| Heimdall `object.forecast` | Forseti는 사유 `governed_execution_unselected`, `advisory_source: forecast`, `shadow_only` 상한을 가진 ActionType 없는 판정을 게시합니다. 예측 필드에서 규칙 일치, 중재 또는 ActionType을 도출하지 않습니다. | 기존 규칙 일치, 중재, 위험 및 승인 관문이 실행되며, 의도적인 제한은 하나뿐입니다. 정확히 `mode: enforce`를 선언하지 않은 예측에서 Forseti가 작업 판정을 도출하면 다른 모든 상한을 적용한 뒤 그 판정을 `shadow_only`로 제한하고 `source_mode`를 기록합니다. 예측에 대한 ActionType 없는 판정과 중재 판정에는 `source_mode`가 없습니다. |
| 중재에 포함된 Freyr `object.capacity-forecast` | Odin은 여전히 목표를 비교하지만 Forseti는 DecisionCase 선택지, 계획 기록 또는 kinetic 제안을 만들지 않습니다. 종결된 판정은 ActionType을 지정하지 않고 중재 결과를 근거로 기록합니다. 모든 결과는 DecisionCase가 없을 때의 통제 경로와 마찬가지로 해당 상관관계를 미해결로 기록하므로, 같은 상관관계에서 나중에 관찰된 신호는 자동 실행되지 않습니다. 같은 프로세스에서든 재시작이나 관문 축출 뒤에든 Thor의 영속 상관관계 점유가 제한된 판정을 거부하며, Thor는 영속 저장소 없이 실행될 때만 이를 폐기합니다. | 기존 DecisionCase, 중재, kinetic 제안 및 사람 검토 경로가 실행됩니다. |
| 학습된 패턴의 T1 재사용 | 컨트롤 루프는 `control_loop.t1_reuse_advisory`를 기록하고 Action을 만들기 전에 멈추므로 실행 승인 평가, risk gate, 승인 요청, 시뮬레이션 또는 전달이 실행되지 않습니다. | 기존 검증, risk gate, 승인 및 전달 경로가 실행됩니다. |

Thor는 모든 프로필에서 이 사유를 가진 ActionType 없는 판정을 무시하므로 ActionRun, 승인, 롤백
또는 실행기 호출이 이어지지 않습니다. 자문 중재 판정에 대해서는 Thor가 ActionRun 저장소에
종결된 비작업 상관관계 점유도 기록합니다. 복구는 이 점유를 불러오지 않지만, 기존 상관관계
검사는 통제 경로가 기록하는 ActionRun의 재사용을 거부하듯 이후 같은 상관관계의 모든 판정을
거부합니다. 이 판정 조건은 선택 값을 읽지 않으며, Forseti는 추가
기능이 없을 때만 이 사유를 기록합니다. 관찰된 신호에 대한 결정론적 판단은 두 프로필에서 모두
바뀌지 않습니다. 예측 `mode` 상한은 이 경계가 선택된 프로필에 추가하는 유일한 제한이며,
선언되지 않았거나 shadow인 예측을 누락된 모드를 믿지 않고 shadow 우선으로 유지합니다.

### 구성 및 관측 경계

| 경계 | 계약 |
|------|------|
| `consumer_group_prefix` | 환경별로 소비자 그룹을 격리합니다. |
| `disabled_agents` | 선택적 에이전트를 바인딩과 구독에서 제거하며 Saga와 Vidar는 비활성화할 수 없습니다. |
| `governed_execution_selected` | `RuntimeProductSelection.governed_execution`을 조립된 컨트롤 루프에서 Forseti로 전달합니다. 기본값은 학습 및 예측 입력을 자문 상태로 유지합니다. |
| `saga` | enforce 운영에 필요한 추가 전용 영속 감사를 제공합니다. |
| `thor_state_store` | 최종 상태가 아닌 ActionRun을 재구성하고 재시작 후 리소스 잠금을 보존하며, 종결된 비작업 점유로 자문 중재 상관관계를 유지합니다. |
| `vidar_state_store` | 롤백 점유, 소유자 점유 유효 기간, 차단 개정 번호 및 종결 증적을 영속화합니다. |
| `var_state_store` | 승인 결정, 최종 페이로드 및 게시 검사 지점을 영속화합니다. |
| `forseti_state_store` | 판단 상한, 중재 맥락, 영역 간 후보 기한 및 완료 표시를 영속화합니다. 적용 모드 조립에 필요합니다. |
| `bragi_state_store` | 대화, 인계, 턴 보낼 편지함을 영속화해 세션 복구가 도착 순서를 보존하고 대기 중인 대화 레코드를 다시 게시하게 합니다. |
| `odin_state_store` | 중재 결정 차단 장치를 영속화하고 다시 전달된 요청에는 원래 결정을 재생합니다. |
| `proposal_rate_limit_state_store` | 제안 예산 구간과 복제본 간 원자적 예약을 영속화합니다. |
| `ordered_poison_halt_state_store` | 순서가 있는 소비자의 poison 중단을 선택적으로 영속화합니다. 프로덕션은 운영자 해제 표면이 생길 때까지 연결하지 않습니다. |
| `heimdall_state_store` | 관측 구간, 알림 예산, 중계 보낼 편지함, 효과 관측 재생 차단 장치를 영속화합니다. |
| `njord_state_store` | 비용 샘플 차단 장치, 오래된 샘플 방지 장치 및 자문 기준선을 영속화합니다. |
| `freyr_state_store` | 용량 샘플 차단 장치, smoothing 상태, 예측 보낼 편지함 및 용량 graduation에 쓰는 비용 근거를 영속화합니다. |
| `muninn_state_store` | Muninn 변환 결과, Saga 이슈 상태 및 Norns 인계 학습 복구를 지원합니다. |
| `payload_validator` | 프로바이더 경계에서 잘못된 게시를 거부합니다. |
| 소비자 재시작 제한 | 형제 소비자를 취소하지 않고 지수 백오프와 유한한 재시작 상한을 적용합니다. |
| `health()` | 브리지 메트릭, 에이전트와 소비자 상태, 사용할 수 없는 에이전트, 연속성 및 유효 enforce 상태를 보고합니다. |
| Shadow 관찰기 | 권위 있는 구독자의 레코드를 소비하지 않고 실행 예정 결정을 측정합니다. |
| `ShadowDivergenceLedger` | 승격 근거를 위해 상관관계 ID로 shadow 결정과 권위 있는 결정을 결합합니다. |
| `heimdall_action_observation_hook` | 정확한 최종 ActionRun 아티팩트를 복원하고 독립적으로 검증된 효과 관찰만 기록합니다. |
| 하트비트 | 설정된 주기로 범위가 제한된 상태 스냅샷을 발행합니다. |

### 이벤트 버스 불변식

- 토픽 소유권과 파티션 키는 공유 토픽 레지스트리를 사용합니다. 변경 토픽에는 비어 있지 않은
  리소스 키가 필요하며 잘못된 키는 게시 전에 차단됩니다.
- 모든 소유 토픽 게시는 게시 경계에서 비어 있지 않은 `correlation_id`와
  `idempotency_key`를 포함해야 합니다. 변경 토픽에는 `resource_id`도 필요합니다.
  인메모리 버스와 프로덕션 브리지는 안전하지 않은 변경 묶음 누락을 fail closed로 처리하고,
  다른 소유 토픽의 공유 묶음 누락은 기록합니다.
- 게시 묶음은 생산자, 스키마, 상관관계 및 멱등성 메타데이터를 포함합니다. 소비자 측 소유권
  검사는 사칭 게시자를 핸들러에 전달하기 전에 dead-letter 처리합니다.
- 한 에이전트의 서로 다른 핸들러가 같은 토픽을 소비하면 각각 결정론적 소비자 그룹으로
  fan-out합니다. 핸들러가 하나뿐이면 기존 group id를 유지합니다. 순서가 있는 poison은 해당
  토픽의 모든 형제 소비자를 중단합니다. 잘못된 소유 레코드는 broker 레코드마다 한 번만
  dead-letter 처리하고 실패한 소비자 신원을 남깁니다.
- 핸들러 재시도와 토픽별 시간 제한은 범위가 제한됩니다. 핸들러는 짧은 협력적 취소 안전
  임계 구간을 표시할 수 있으므로 멈춘 핸들러는 여전히 시간 초과되지만 영속 확정
  구간은 끝낼 수 있습니다.
- 관찰자 콜백과 dead-letter 쓰기는 범위가 제한됩니다. 순서가 있는 변경 스트림은
  dead-letter를 쓸 수 없으면 중단하므로 나중 효과가 실패한 이전 효과를 앞지를 수 없습니다.
- DLQ redrive는 명시적 운영자 작업입니다. DLQ 쓰기 실패는 집계하며 정상 소비자와 격리합니다.
  단, 순서가 있는 소비자는 스트림 순서를 보존하기 위해 중단합니다.
- DLQ redrive는 batch 범위가 제한되며 모든 레코드에서 소유자, 스키마, 묶음, 파티션 검증을
  보존합니다. Redrive batch가 cap에 도달하면 나머지는 빈 상태가 될 때까지 loop하지 않고
  관측 가능한 backlog 근거와 함께 보관합니다.
- 제안 예산은 용량을 예약하고 제안을 게시한 뒤 예약을 확정합니다. 영속 제한기는 복제본
  전체에서 원자적 CAS 예약을 사용하고 실패나 취소 시 예약을 해제합니다.
- `InMemoryBus`는 로컬 검사에 parity가 필요한 범위에서 프로덕션 브리지와 동일한 묶음,
  파티션, 시간 제한 및 실패 격리 계약을 따릅니다. 선택 항목은 payload 검증, 범위가 제한된
  handler retry, duplicate-delivery simulation, 변경 토픽의 ordered poison halt를 포함합니다.
- 남은 로컬 버스 차이는 의도적입니다. 전달은 순차적이고 in-process이며, 토픽 간 동시성이나
  broker 수준 partition rebalancing은 없습니다.
- 로컬 및 테스트 bus retention은 범위가 제한됩니다. 오래된 accepted envelope, dead letter, abandoned
  consumer-group 상태는 명시적 한도 아래에서 만료됩니다. 이렇게 해서 로컬 bus를 프로덕션
  broker로 가장하지 않으면서 parity 검사를 결정론적으로 유지합니다.
- `LocalEventBus`는 구독 재시작 후에도 확정된 offset을 유지합니다. 명시적 `reset_offsets()`만
  확정된 레코드를 재생하므로 재시작 복구와 재생 검사를 구분할 수 있습니다.
- 에이전트 게시는 `PantheonBus` 프로토콜을 사용하므로 런타임 조립에서 역할이나 권한 계약을
  바꾸지 않고 전달 어댑터를 교체할 수 있습니다.

### 비율 한도, 상태 및 범위가 제한된 백로그

런타임 비율 한도 적용은 고정 버킷이 아니라 슬라이딩 윈도를 사용하므로 경계 시점 버스트가
유효 비율을 두 배로 만들지 않습니다. 초과 제안은 범위가 제한된 큐에 넣고 큐가 넘치면
`rate_limit_exceeded` 감사 항목과 함께 폐기하여 Saga와 Norns가 에이전트 버스트의 원인을 학습하도록
합니다.

상태와 KPI 스냅샷은 측정된 값과 사용할 수 없는 근거를 구분합니다. 누락, stale, incomplete,
degraded sample은 `value: null`과 근거 상태 및 성능 저하 사실을 함께 렌더링합니다. 승격 gate는
이를 0이나 성공이 아니라 실패로 처리합니다. Coverage claim은 측정된 값만 사용합니다. Workflow
7은 synthetic trace에서 추정하지 않고 사용할 수 없거나 stale한 measurement에 대해 성능 저하
사실을 보고합니다. Freyr capacity freshness도 같은 규칙을 따릅니다. 새로운 utilization 근거의
gap은 자동 graduation을 차단하고 오래된 sample을 재사용하는 대신 freshness gap을 기록합니다.
Saga audit digest는 유한한 JSON-native 값의 엄격한 canonical JSON을 사용합니다. JSON이 아닌 값,
NaN, Infinity, 프로세스별 rendering은 hash하거나 표시하지 않고 보류합니다.

## 거버넌스와 롤백

권위 있는 웨이브 간 규칙은 저장소 지침에서 관리합니다:

- 문서와 이중 언어 업데이트: [코딩 규칙](../../../.github/instructions/coding-conventions.instructions.md)과 [언어 정책](../../../.github/instructions/language.instructions.md)
- 고정 에이전트 역할과 권한: [에이전트 판테온 지침](../../../.github/instructions/agent-pantheon.instructions.md)
- 포크 커스터마이제이션: [고객 무관 범위](../../../.github/instructions/generic-scope.instructions.md)

범위가 제한된 각 웨이브는 독립적으로 되돌릴 수 있습니다. 새로 조립한 단계는 shadow에서
시작하며, 롤백은 권한을 부여하거나 과거 근거를 다시 쓰지 않은 채 이전 바인딩을 복원합니다.

## 관련 문서

| 학습 주제 | 읽기 |
|-----------|------|
| 고정 역할, 토픽, 작업 및 성능 저하 | [에이전트 판테온](agent-pantheon-ko.md) |
| 에이전트 간 작업 흐름 정의 | [에이전트 작업 흐름](agent-workflows-ko.md) |
| 작업 흐름별 롤아웃 순서와 근거 | [에이전트 작업 흐름 Shadow 롤아웃](agent-workflow-rollout-ko.md) |
| 런타임 소스 소유권 | [프로젝트 구조](../architecture/project-structure-ko.md) |
| KPI 측정과 승격 근거 | [목표와 메트릭](../architecture/goals-and-metrics-ko.md) |
| 지원되는 다운스트림 바인딩 | [다운스트림 포크 가이드](../fork-and-sequencing/downstream-fork-guide-ko.md) |
