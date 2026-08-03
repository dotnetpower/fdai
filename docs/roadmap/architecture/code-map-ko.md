---
title: 코드 맵
translation_of: code-map.md
translation_source_sha: 8deeb36df280c409213fce6a55b5d1c7000d0b79
translation_revised: 2026-08-03
---
# 코드 맵

FDAI 코드베이스의 원페이지 인덱스. 서브시스템 이름에서 소스, 테스트, 설계
문서로 한 번에 이동할 수 있게 만든 지도. 에이전트와 사람 모두를 위한 지도다.
[project-structure.md](project-structure-ko.md) (모듈 경계와 DI seam 상세)의
**스캔용 파트너**로 쓴다.

"X는 어디 있지?"에 `list_dir`을 다섯 번 열지 않고 답하고 싶을 때 사용한다.
아래 표들은 core 컨트롤 플레인 서브시스템, 15명 판테온 에이전트, delivery /
shared 패키지를 커버한다.

## 한눈에 보기

- **`src/fdai/core/`** = 헤드리스 컨트롤 플레인. UI 없음, 클라우드 SDK
  직접 import 없음. 컨트롤 플레인 서브시스템과 최상위 `ontology_explorer.py`
  모듈을 컨트롤 루프 역할별로 아래에 정리.
- **`src/fdai/agents/`** = 15명 판테온 (평면 배치, 에이전트당 파일 하나) +
  `_framework/` (버스, 런타임, 레지스트리, 판테온 스펙).
- **`src/fdai/delivery/`** = 외부 어댑터 (Azure, chatops, PR 게이트, 알림,
  영속성, Operator API).
- **`src/fdai/shared/`** = CSP-중립 배관: contracts, ontology, provider
  Protocol, streaming, telemetry, resilience.
- **`src/fdai/composition/`** = 컴포지션 루트 (fork DI가 여기 붙는다).
- **`src/fdai/rule_catalog/`** = `rule-catalog/` 로더.

## 컨트롤 루프 서브시스템

이벤트 -> 감사 핫패스의 12개 서브시스템. **>= 90% 커버리지 바닥**을
유지하는 안전-핵심 모듈들이다.

| 서브시스템 | 책임 | 소스 | 테스트 | 설계 문서 |
|-----------|------|------|--------|----------|
| event_ingest | 이벤트 정규화 + 중복제거 + 인시던트로 상관관계 묶기 | [src/fdai/core/event_ingest/](../../../src/fdai/core/event_ingest/) | [tests/core/event_ingest/](../../../tests/core/event_ingest/) | [architecture.instructions.md § Control Loop](../../../.github/instructions/architecture.instructions.md#control-loop) |
| trust_router | 신뢰도 계산, T0/T1/T2 라우팅 | [src/fdai/core/trust_router/](../../../src/fdai/core/trust_router/) | [tests/core/trust_router/](../../../tests/core/trust_router/) | [architecture.instructions.md § Trust Routing](../../../.github/instructions/architecture.instructions.md#trust-routing-3-tier) |
| tiers/t0_deterministic | 정책 + 체크리스트 + what-if + drift. Audit attribution은 evaluator 일부 abstain과 전체 abstain을 구분합니다 | [src/fdai/core/tiers/t0_deterministic/](../../../src/fdai/core/tiers/t0_deterministic/) | [tests/core/tiers/](../../../tests/core/tiers/) | project-structure-ko.md |
| tiers/t1_lightweight | 유사도 재사용, immutable operational-case context 및 current evidence 검증 | [src/fdai/core/tiers/t1_lightweight/](../../../src/fdai/core/tiers/t1_lightweight/) | [tests/core/tiers/](../../../tests/core/tiers/) | project-structure-ko.md |
| tiers/t2_reasoning | 신규 케이스용 프론티어 모델 추론, 후보별 call budgeting, bounded primary-to-secondary proposer failover, durable preferred-route selection, sanitized attempt receipt, fail-closed HIL exhaustion. 금액 한도는 metering 기록에 위치 | [src/fdai/core/tiers/t2_reasoning/](../../../src/fdai/core/tiers/t2_reasoning/) | [tests/core/tiers/](../../../tests/core/tiers/) | [llm-strategy-ko.md](llm-strategy-ko.md) |
| quality_gate | 정규화된 action type과 parameters 전체에 대한 혼합 모델 quorum + verifier + grounding (T2 가드) | [src/fdai/core/quality_gate/](../../../src/fdai/core/quality_gate/) | [tests/core/quality_gate/](../../../tests/core/quality_gate/) | [architecture.instructions.md § LLM Quality Gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2) |
| risk_gate | 통합 auto vs HIL vs deny 권위. 선언된 모든 ActionType precondition에 indexed deterministic evidence를 요구하며, evidence가 없거나 실패하면 사람 승인으로 라우팅합니다. Ceiling override는 Rego를 렌더하므로 삽입되는 모든 field는 pattern으로 제한되고 escape됩니다. 요청이 정책을 쓸 수 있어서는 안 됩니다. | [src/fdai/core/risk_gate/](../../../src/fdai/core/risk_gate/) | [tests/core/risk_gate/](../../../tests/core/risk_gate/) | [decisioning/](../decisioning/) |
| execution_authorization | Risk evaluation 전에 provider-neutral capability requirement를 scoped customer policy 및 effective-access evidence와 비교하고, 별도의 exact-plan access-grant lifecycle을 관리합니다. | [src/fdai/core/execution_authorization/](../../../src/fdai/core/execution_authorization/) | [tests/core/execution_authorization/](../../../tests/core/execution_authorization/) | [execution-authorization-ontology-ko.md](../decisioning/execution-authorization-ontology-ko.md) |
| hil_resume | 사람 결정까지 park/resume합니다. Principal identity는 대소문자를 구분하지 않고 비교하므로, object id의 표기를 바꿔 한 사람을 두 사람처럼 보이게 해서 no-self-approval 바닥을 무너뜨릴 수 없습니다. no-drop load plan, group당 initial dispatch 1개, atomic expiry reaping, bounded reminder, durable decision delivery 및 CAS 소유 shadow non-response ladder를 제공합니다. | [src/fdai/core/hil_resume/](../../../src/fdai/core/hil_resume/), [hil_registry.py](../../../src/fdai/shared/providers/hil_registry.py), [hil_decision.py](../../../src/fdai/delivery/chatops/hil_decision.py) | [tests/core/hil_resume/](../../../tests/core/hil_resume/), [test_hil_callback.py](../../../tests/delivery/operator_api/test_hil_callback.py), [test_hil_decision.py](../../../tests/delivery/test_hil_decision.py) | [channels-and-notifications-ko.md](../interfaces/channels-and-notifications-ko.md) |
| executor | Logical-target lock, 멱등 적용, 공유 blast-radius ceiling, PR-native content-addressed dry-run 및 pre-effect/terminal audit lifecycle. 영향 count 미선언 action은 거부됩니다. | [src/fdai/core/executor/](../../../src/fdai/core/executor/) | [tests/core/executor/](../../../tests/core/executor/) | project-structure-ko.md |
| execution_backend | Profile intersection, 기록된 profile이 사라지면 fail closed하는 exact-version durable reconciliation, shadow health probe를 제공하며 eligibility authority는 없음 ([설계](../interfaces/execution-backends-ko.md)) | [src/fdai/core/execution_backend/](../../../src/fdai/core/execution_backend/) | [tests/core/execution_backend/](../../../tests/core/execution_backend/) | [execution-backends-ko.md](../interfaces/execution-backends-ko.md) |
| audit | append-only 해시체인 로그. 체인 규칙(genesis, canonical 형태, chaining digest)은 `shared/providers/audit_hash.py`에 한 번만 존재하므로 두 StateStore 백엔드가 동일한 digest를 만들고 한쪽이 쓴 체인을 다른 쪽이 검증합니다. Startup readiness는 저장된 체인을 재계산하고 불일치하면 차단합니다. Nullable-stage correlation trace 및 KPI도 방출합니다 | [src/fdai/core/audit/](../../../src/fdai/core/audit/) | [tests/core/audit/](../../../tests/core/audit/) | [security-and-identity-ko.md](security-and-identity-ko.md) |
| control_loop | 파이프라인 오케스트레이터 (Stage 프로토콜) | [src/fdai/core/control_loop/](../../../src/fdai/core/control_loop/) | [tests/core/](../../../tests/core/) | project-structure-ko.md |
| pipeline | 위 서브시스템들의 도메인 그룹 파사드 | [src/fdai/core/pipeline/](../../../src/fdai/core/pipeline/) | (멤버와 동일) | project-structure-ko.md |

## 탐지, RCA, 인시던트 라이프사이클

| 서브시스템 | 책임 | 소스 | 테스트 |
|-----------|------|------|--------|
| detection | Anomaly와 operational-insight producer, 변경 불가능한 positive/negative/abstained forecast episode, event-time closure 및 publication outbox | [src/fdai/core/detection/](../../../src/fdai/core/detection/), [src/fdai/runtime/forecast_learning.py](../../../src/fdai/runtime/forecast_learning.py), [src/fdai/delivery/persistence/postgres_forecast_episode.py](../../../src/fdai/delivery/persistence/postgres_forecast_episode.py) | [tests/core/detection/](../../../tests/core/detection/), [tests/runtime/test_forecast_learning.py](../../../tests/runtime/test_forecast_learning.py), [tests/persistence/test_postgres_forecast_episode.py](../../../tests/persistence/test_postgres_forecast_episode.py) |
| case_history | Canonical case revision, strict operational receipt compilation, action/incident artifact-first intake, StateStore-to-PostgreSQL shadow migration, generic metadata 전체 chain backfill, retention, governed Norns 분석, 환경 독립 failure fingerprint ([case-history 설계](../rules-and-detection/prediction-learning-and-case-history-ko.md), [operational-learning 설계](../rules-and-detection/operational-learning-ontology-ko.md)) | [src/fdai/core/case_history/](../../../src/fdai/core/case_history/), [src/fdai/shared/providers/case_history.py](../../../src/fdai/shared/providers/case_history.py), [src/fdai/delivery/persistence/](../../../src/fdai/delivery/persistence/) | [tests/core/case_history/](../../../tests/core/case_history/), [tests/persistence/test_case_history_backfill.py](../../../tests/persistence/test_case_history_backfill.py), [tests/persistence/test_postgres_case_history.py](../../../tests/persistence/test_postgres_case_history.py), [tests/agents/test_forecast_learning_chain.py](../../../tests/agents/test_forecast_learning_chain.py) |
| rca | Leakage-safe lagged evidence, immutable hypothesis, support/refutation 및 independent closure를 위한 shadow runtime이 포함된 근본원인 분석 | [src/fdai/core/rca/](../../../src/fdai/core/rca/) | [tests/core/rca/](../../../tests/core/rca/) |
| incident | 인시던트 라이프사이클 레지스트리 + 상태 머신 | [src/fdai/core/incident/](../../../src/fdai/core/incident/) | [tests/core/incident/](../../../tests/core/incident/) |
| slo | 워크로드 SLO / burn-rate 평가자 | [src/fdai/core/slo/](../../../src/fdai/core/slo/) | [tests/core/slo/](../../../tests/core/slo/) |
| irp | 인시던트 대응 계획 오케스트레이터 | [src/fdai/core/irp/](../../../src/fdai/core/irp/) | [tests/core/irp/](../../../tests/core/irp/) |
| investigation | 예산 제한 증거 수집 러너 | [src/fdai/core/investigation/](../../../src/fdai/core/investigation/) | [tests/core/investigation/](../../../tests/core/investigation/) |
| runbook | 선형 runbook + 실패 분기 | [src/fdai/core/runbook/](../../../src/fdai/core/runbook/) | [tests/core/](../../../tests/core/) |
| postmortem | LLM-옵션 PIR 초안 | [src/fdai/core/postmortem/](../../../src/fdai/core/postmortem/) | [tests/core/postmortem/](../../../tests/core/postmortem/) |
| chaos | Resilience 및 chaos probe입니다. Impact envelope, continuous guard, pre-authorized recovery의 target contract는 [recovery-and-chaos-enforcement-ko.md](../decisioning/recovery-and-chaos-enforcement-ko.md)에 있습니다. | [src/fdai/core/chaos/](../../../src/fdai/core/chaos/) | [tests/core/chaos/](../../../tests/core/chaos/) |
| capacity | 용량 + 예측 findings | [src/fdai/core/capacity/](../../../src/fdai/core/capacity/) | [tests/core/capacity/](../../../tests/core/capacity/) |
| oncall | 온콜 로테이션 리더 (read-only) | [src/fdai/core/oncall/](../../../src/fdai/core/oncall/) | [tests/core/](../../../tests/core/) |

## 지식, 메모리, 프롬프트

| 서브시스템 | 책임 | 소스 | 테스트 |
|-----------|------|------|--------|
| knowledge | 장기 지식 저장소 seam | [src/fdai/core/knowledge/](../../../src/fdai/core/knowledge/) | [tests/core/knowledge/](../../../tests/core/knowledge/) |
| document_ingestion | 에이전트 gate를 적용한 upload lifecycle: scan/protection inspection, Forseti/Saga decision, Var HIL, Muninn indexing, replay-only gated-state recovery ([설계](../interfaces/document-ingestion-agent-ownership-ko.md)) | [src/fdai/core/document_ingestion/](../../../src/fdai/core/document_ingestion/) 및 [src/fdai/delivery/ingestion_gateway/](../../../src/fdai/delivery/ingestion_gateway/) | [tests/core/document_ingestion/](../../../tests/core/document_ingestion/) 및 [tests/delivery/ingestion_gateway/](../../../tests/delivery/ingestion_gateway/) |
| operator_memory | HIL 승인된 오퍼레이터 노트 저장소 | [src/fdai/core/operator_memory/](../../../src/fdai/core/operator_memory/) | [tests/core/operator_memory/](../../../tests/core/operator_memory/) |
| learning | 동의 기반 off-path post-turn eligibility, mixed-family consensus, 중복 제거, 비활성 proposal routing ([설계](../decisioning/post-turn-improvement-review-ko.md)) | [src/fdai/core/learning/](../../../src/fdai/core/learning/) | [tests/core/learning/](../../../tests/core/learning/) |
| conversation_assurance | 결정론적 terminal 검사, 독립 모델 점수, append-only 평가와 이의 제기, 구독별 사후 분포 학습, chat-policy 승격 및 롤백 ([설계](../decisioning/conversation-assurance-ko.md)) | [src/fdai/core/conversation_assurance/](../../../src/fdai/core/conversation_assurance/), [conversation_assurance.py](../../../src/fdai/delivery/azure/llm/conversation_assurance.py), [postgres_conversation_assurance.py](../../../src/fdai/delivery/persistence/postgres_conversation_assurance.py) | [tests/core/conversation_assurance/](../../../tests/core/conversation_assurance/), [test_conversation_assurance.py](../../../tests/delivery/operator_api/test_conversation_assurance.py), adapter/runtime 집중 테스트 |
| trajectory | Authorization-first immutable source join, versioned observable envelope, deterministic JSONL export, offline validation/replay, retention/legal hold, reviewed-only Norns aggregate intake ([설계](../interfaces/governed-trajectory-datasets-ko.md)) | [src/fdai/core/trajectory/](../../../src/fdai/core/trajectory/) 및 [src/fdai/shared/providers/trajectory.py](../../../src/fdai/shared/providers/trajectory.py) | [tests/core/trajectory/](../../../tests/core/trajectory/), [tests/delivery/trajectory/](../../../tests/delivery/trajectory/), focused API/persistence/agent test |
| task_worker | 축소된 capability, 영구 branch state, 신뢰되지 않은 parent synthesis를 사용하는 격리된 depth-one 읽기 전용 조사 ([설계](../agents/bounded-task-workers-ko.md)) | [src/fdai/core/task_worker/](../../../src/fdai/core/task_worker/) | [tests/core/task_worker/](../../../tests/core/task_worker/) |
| background_task | Lease/CAS ownership, server-clock quota, coalesced progress, atomic completion outbox, bounded handoff retry, process-loss reconciliation, gated retention purge를 사용하는 영구 detached 읽기 전용 session ([설계](../interfaces/background-task-sessions-ko.md)) | [src/fdai/core/background_task/](../../../src/fdai/core/background_task/) | [tests/core/background_task/](../../../tests/core/background_task/) |
| read_investigation | 검증된 typed current/activity resource query, observed-facet deterministic compilation, exact-resource follow-up, 30일 Activity Log history, bounded parallel evidence, RG-scoped subscription health, durable latency profile, owner-scoped direct/stream replay, honest cost usage, SSE heartbeat 및 stream-close cancellation ([설계](../interfaces/azure-read-investigations-ko.md)) | [src/fdai/core/read_investigation/](../../../src/fdai/core/read_investigation/), [chat_inventory_query.py](../../../src/fdai/delivery/operator_api/routes/chat_inventory_query.py), [chat_inventory_compiler.py](../../../src/fdai/delivery/operator_api/routes/chat_inventory_compiler.py), [chat_inventory_activity.py](../../../src/fdai/delivery/operator_api/routes/chat_inventory_activity.py), [chat_resource_context.py](../../../src/fdai/delivery/operator_api/routes/chat_resource_context.py) 및 [src/fdai/delivery/azure/read_investigation/](../../../src/fdai/delivery/azure/read_investigation/) | [tests/core/read_investigation/](../../../tests/core/read_investigation/), [tests/delivery/azure/read_investigation/](../../../tests/delivery/azure/read_investigation/), [test_chat_inventory_query.py](../../../tests/delivery/operator_api/test_chat_inventory_query.py), [test_chat_inventory_compiler.py](../../../tests/delivery/operator_api/test_chat_inventory_compiler.py) 및 focused Operator API/persistence test |
| briefing | Report feed 기반 결정적 opening 및 scheduled briefing | [src/fdai/core/briefing/](../../../src/fdai/core/briefing/) | [tests/core/briefing/](../../../tests/core/briefing/) |
| busy_input | Web, Slack, Teams conversation이 공유하는 영구 queue, interrupt, safe-boundary steer arbitration ([설계](../interfaces/busy-input-modes-ko.md)) | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/conversation/](../../../tests/conversation/) |
| durable_delivery | Verified principal binding, persisted outbound response와 typed cumulative channel update, bounded recovery 및 adapter breaker ([설계](../interfaces/durable-conversation-delivery-ko.md)) | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/conversation/](../../../tests/conversation/) 및 [tests/persistence/](../../../tests/persistence/) |
| conversation_progress | Deterministic `none` / `compact` / `timeline` / `detached` presentation 선택, Web/Slack/Teams용 ordered redacted activity snapshot, request 또는 identity payload를 저장하지 않는 bounded aggregate progress counter 및 latency | [conversation_channel.py](../../../src/fdai/shared/providers/conversation_channel.py), [channel_gateway.py](../../../src/fdai/core/conversation/channel_gateway.py), [publishers.py](../../../src/fdai/delivery/channels/publishers.py), [conversation_progress.py](../../../src/fdai/shared/telemetry/conversation_progress.py) | [test_channel_gateway.py](../../../tests/conversation/test_channel_gateway.py), [test_publishers_and_routes.py](../../../tests/delivery/channels/test_publishers_and_routes.py), [test_rich_contract.py](../../../tests/delivery/channels/test_rich_contract.py), [test_conversation_progress_metrics.py](../../../tests/shared/test_conversation_progress_metrics.py), focused Web recovery test |
| user_context_projection | 사용자 context 및 workflow binding metadata만 runtime ontology에 projection | [src/fdai/core/user_context_projection.py](../../../src/fdai/core/user_context_projection.py) | [tests/core/test_user_context_projection.py](../../../tests/core/test_user_context_projection.py) |
| working_context | 턴당 프롬프트 조립, invariant validation, capability-gated policy lifecycle, bounded shadow 비교 및 approved-fixture replay ([설계](../decisioning/context-selection-policy-ko.md)) | [src/fdai/core/working_context/](../../../src/fdai/core/working_context/) | [tests/core/working_context/](../../../tests/core/working_context/) |
| operational_context | Typed evidence path, effective-time 및 provenance projection, source-freshness receipt, fail-closed truncation, atomic provider-owned subgraph replacement 및 stale deletion을 포함하는 replay-stable snapshot ([설계](operating-ontology-ko.md)) | [src/fdai/core/operational_context/](../../../src/fdai/core/operational_context/), [shared/providers/operating_model.py](../../../src/fdai/shared/providers/operating_model.py), [delivery/operating_model/](../../../src/fdai/delivery/operating_model/), [runtime/operating_model.py](../../../src/fdai/runtime/operating_model.py) | [tests/core/operational_context/](../../../tests/core/operational_context/), [tests/delivery/operating_model/](../../../tests/delivery/operating_model/), [test_operating_model.py](../../../tests/runtime/test_operating_model.py) |
| decision_case | Protected-objective selection, Forseti/Odin/Thor/Var propagation, `ResponseOutcome` closure를 공유하는 reliability, ARB, cost option | [src/fdai/core/decision_case/](../../../src/fdai/core/decision_case/) | [tests/core/decision_case/](../../../tests/core/decision_case/), [test_decision_case_e2e.py](../../../tests/agents/test_decision_case_e2e.py) |
| operational_planning | Immutable specialist contribution, hard-constraint eligibility, bounded Pareto pruning, exact logic/simulation receipt lineage 및 ordered Process child phase입니다. Planning은 A0로 유지되며 execution authority를 부여하지 않습니다 ([설계](../decisioning/operational-planning-ko.md)) | [src/fdai/core/operational_planning/](../../../src/fdai/core/operational_planning/) | [tests/core/operational_planning/](../../../tests/core/operational_planning/) |
| operational_learning | Sealed operational case를 classify하고 하나의 fingerprint 및 ActionType과 balanced verified-success/negative-control evidence를 요구하며 immutable revision을 인용합니다. 기존 consensus 및 rate limit을 거쳐 deduplicate된 inert Norns mapping만 emit하고 raw response outcome은 hold합니다. | [src/fdai/core/operational_learning/](../../../src/fdai/core/operational_learning/) | [tests/core/operational_learning/](../../../tests/core/operational_learning/), [test_norns_operating_pattern.py](../../../tests/agents/test_norns_operating_pattern.py), [test_operating_pattern_learning_e2e.py](../../../tests/agents/test_operating_pattern_learning_e2e.py) |
| prompts | catalog-as-code 프롬프트 컴포저 | [src/fdai/core/prompts/](../../../src/fdai/core/prompts/) | [tests/core/](../../../tests/core/) |
| skills | Progressive disclosure, governed bundle, durable approved-source quarantine ([bundle 설계](../decisioning/governed-skill-bundles-ko.md), [source 설계](../interfaces/skill-source-management-ko.md)) | [src/fdai/core/skills/](../../../src/fdai/core/skills/) 및 [src/fdai/core/supply_chain/](../../../src/fdai/core/supply_chain/) | [tests/core/skills/](../../../tests/core/skills/), [tests/core/supply_chain/](../../../tests/core/supply_chain/), [tests/persistence/](../../../tests/persistence/) |
| programmatic_pipeline | Run capability, durable receipt, isolated runner, compact result를 사용하는 검토된 bounded read-only tool loop ([설계](../interfaces/programmatic-tool-pipelines-ko.md)) | [src/fdai/core/programmatic_pipeline/](../../../src/fdai/core/programmatic_pipeline/) | [tests/core/programmatic_pipeline/](../../../tests/core/programmatic_pipeline/) 및 [tests/delivery/programmatic_pipeline/](../../../tests/delivery/programmatic_pipeline/) |
| browser_evidence | Origin 및 DNS policy, redaction, immutable artifact, evidence-only surface, shadow comparison ([설계](../interfaces/browser-evidence-ko.md)) | [src/fdai/core/browser_evidence/](../../../src/fdai/core/browser_evidence/) | [tests/core/browser_evidence/](../../../tests/core/browser_evidence/) 및 [tests/delivery/browser/](../../../tests/delivery/browser/) |
| tools | T2 file, package, composite tool registry + ToolExecutor + typed command catalog | [src/fdai/core/tools/](../../../src/fdai/core/tools/) | [tests/core/tools/](../../../tests/core/tools/) |
| web_search | 최후 수단 웹 검색 seam | [src/fdai/core/web_search/](../../../src/fdai/core/web_search/) | [tests/core/web_search/](../../../tests/core/web_search/) |
| capability_catalog | Typed binding, optional reasoning-tool metadata, provider, disabled-first extension lifecycle을 갖춘 additive capability package | [src/fdai/core/capability_catalog/](../../../src/fdai/core/capability_catalog/) | [tests/core/capability_catalog/](../../../tests/core/capability_catalog/) |
| licensing | 이미지로 전달되는 distribution을 위한 서명된 capability entitlement: crypto-free token contract, available 축 전용 해석, 안전 저하 ([design](../fork-and-sequencing/capability-licensing-ko.md)) | [src/fdai/core/licensing/](../../../src/fdai/core/licensing/) | [tests/core/licensing/](../../../tests/core/licensing/)와 [tests/scripts/test_issue_license.py](../../../tests/scripts/test_issue_license.py) |
| ontology_explorer | 로드된 ObjectType / LinkType 카탈로그의 결정론적 Mermaid 렌더러 (단일 모듈, 패키지 아님) | [src/fdai/core/ontology_explorer.py](../../../src/fdai/core/ontology_explorer.py) | [tests/core/](../../../tests/core/) |
| ontology_platform | Exact release, semantic interface, bounded ObjectSet, mutation planning, typed function, projection/reconciliation, proposal-only SDK generation | [src/fdai/core/ontology_platform/](../../../src/fdai/core/ontology_platform/) | [tests/core/ontology_platform/](../../../tests/core/ontology_platform/) |

Provider 전체 Azure discovery, 정제된 reproduction command 및 명시적 coverage receipt는
[Azure Resource Discovery Command Coverage](../interfaces/azure-resource-discovery-commands-ko.md)의
목표 설계입니다. 위의 구현된 `read_investigation` 행을 확장하며 아직 제공된 subsystem은 아닙니다.

## 오퍼레이터 서피스와 알림

| 서브시스템 | 책임 | 소스 | 테스트 |
|-----------|------|------|--------|
| conversation | NL turn -> bounded read tool. Channel pairing과 cross-channel identity link는 정규화된 identity로 판정한 distinct approver를 요구하므로, id 표기를 바꿔 자기 자신의 승인자가 될 수 없습니다; model-free Bragi current-screen T0 answer; bounded cross-process agent introspection; principal-timezone server-clock answer; exact-argument contextual follow-up translation; identity-scoped conflict blocking을 포함한 all-before-execution 2-3 step read planning; role-scoped zero-execution clarification; AnswerPlan/tool/evidence/history-composed grounded narration과 exact-ref, canonical-ID, numeric, timestamp, freshness fallback; hybrid T0 + strict semantic public-search intent 및 query normalization; current-screen evidence walkthrough; turn별 agent prompt-layer manifest를 narrator constraint로 전달; 답변 turn 전에 범위 한정 소유 증거를 모으는 결정론적 이중언어 read-tool 계획(개수·깊이 상한과 단일 prefetch 예산과 유계 소유 route로 제한되며 답한 owner에게만 첨부); evidence-preserving 한국어 prose review | [agent_introspection_bus.py](../../../src/fdai/delivery/agent_introspection_bus.py), 순수 argument parsing을 [tool_arguments.py](../../../src/fdai/core/conversation/tool_arguments.py)에 둔 [src/fdai/core/conversation/](../../../src/fdai/core/conversation/), [chat_screen_data.py](../../../src/fdai/delivery/operator_api/routes/chat_screen_data.py), [chat_current_time.py](../../../src/fdai/delivery/operator_api/routes/chat_current_time.py), [chat_web_search_intent.py](../../../src/fdai/delivery/operator_api/routes/chat_web_search_intent.py), [chat_prompt.py](../../../src/fdai/delivery/operator_api/routes/chat_prompt.py), [chat_prompt_ontology.py](../../../src/fdai/delivery/operator_api/routes/chat_prompt_ontology.py) 및 [chat_answer_quality.py](../../../src/fdai/delivery/operator_api/routes/chat_answer_quality.py) | [tests/core/conversation/](../../../tests/core/conversation/), [test_agent_introspection_bus.py](../../../tests/delivery/test_agent_introspection_bus.py), [test_chat_screen_data.py](../../../tests/delivery/operator_api/test_chat_screen_data.py), [test_chat_current_time.py](../../../tests/delivery/operator_api/test_chat_current_time.py), [test_chat_web_search.py](../../../tests/delivery/operator_api/test_chat_web_search.py), [test_chat_prompt.py](../../../tests/delivery/operator_api/test_chat_prompt.py) 및 [test_chat_answer_quality.py](../../../tests/delivery/operator_api/test_chat_answer_quality.py) |
| conversation_attachments | Explicit attachment purpose, protected Slack/Teams fetch, web document ref 및 optional OCR ([설계](../interfaces/conversation-attachments-ko.md)) | [src/fdai/core/conversation/attachment_directive.py](../../../src/fdai/core/conversation/attachment_directive.py), [src/fdai/delivery/channels/](../../../src/fdai/delivery/channels/), [document_ocr.py](../../../src/fdai/delivery/azure/document_ocr.py) | [tests/delivery/channels/](../../../tests/delivery/channels/), [test_document_ocr.py](../../../tests/delivery/azure/test_document_ocr.py), focused chat test |
| operator | 오퍼레이터 콘솔 코디네이터 | [src/fdai/core/operator/](../../../src/fdai/core/operator/) | (delivery/operator_api 통합) |
| runtime_settings | Allowlist된 environment default와 revision 및 audit가 적용된 StateStore override | [src/fdai/delivery/runtime_settings.py](../../../src/fdai/delivery/runtime_settings.py) 및 [runtime_settings.py](../../../src/fdai/delivery/operator_api/routes/runtime_settings.py) | [test_runtime_settings.py](../../../tests/delivery/test_runtime_settings.py) 및 [test_runtime_settings.py](../../../tests/delivery/operator_api/test_runtime_settings.py) |
| console_request | write-direction 콘솔 경로의 오퍼레이터 재요청 정책 (Scenario B deny-override) | [src/fdai/core/console_request/](../../../src/fdai/core/console_request/) | [tests/core/console_request/](../../../tests/core/console_request/) |
| notifications | 매트릭스 기반 채널 라우팅 레이어 | [src/fdai/core/notifications/](../../../src/fdai/core/notifications/) | [tests/notifications/](../../../tests/notifications/) |
| report_feed | 렌더된 리포트 구독 | [src/fdai/core/report_feed/](../../../src/fdai/core/report_feed/) | [tests/core/report_feed/](../../../tests/core/report_feed/) |
| reporting | 리포트 컴포저 + 포매터 | [src/fdai/core/reporting/](../../../src/fdai/core/reporting/) | [tests/core/reporting/](../../../tests/core/reporting/) |
| views | Workflow-matched ViewSpec -> bounded RenderedView 및 deterministic inventory architecture projection | [src/fdai/core/views/](../../../src/fdai/core/views/) | [tests/core/views/](../../../tests/core/views/) 및 Operator API architecture-view test |
| rbac | Operator API 인간 RBAC. Principal identity를 대소문자 구분 없이 비교하므로 요청자가 다른 표기로 자기 요청을 승인할 수 없습니다. | [src/fdai/core/rbac/](../../../src/fdai/core/rbac/) | [tests/core/](../../../tests/core/) |
| human_assignment | 변경 불가능한 role/duty 의도, 독립 검토, 리비전 기반 effect, shadow-first Entra 적용, 재시작 안전 피로도 예산과 evidence-only review를 갖춘 handover goal | [src/fdai/core/human_assignment/](../../../src/fdai/core/human_assignment/), [human_assignments.py](../../../src/fdai/delivery/operator_api/routes/human_assignments.py), [handover_goals.py](../../../src/fdai/delivery/operator_api/routes/handover_goals.py), [identity/](../../../src/fdai/delivery/identity/), [human_access.py](../../../src/fdai/runtime/human_access.py) | [tests/core/human_assignment/](../../../tests/core/human_assignment/), [test_human_assignments.py](../../../tests/delivery/operator_api/test_human_assignments.py), [test_handover_goals.py](../../../tests/delivery/operator_api/test_handover_goals.py), [tests/delivery/identity/](../../../tests/delivery/identity/), [settings-iam-assignments.test.tsx](../../../console/src/routes/settings-iam-assignments.test.tsx) |
| stewardship | 사람 <-> agent handover map, authoritative structured assignment extraction, deterministic diff/notification, scheduled identity health, persisted idempotent draft-PR receipt, signed merge audit | [src/fdai/core/stewardship/](../../../src/fdai/core/stewardship/) 및 [src/fdai/delivery/stewardship/](../../../src/fdai/delivery/stewardship/) | [tests/core/stewardship/](../../../tests/core/stewardship/) 및 [tests/delivery/stewardship/](../../../tests/delivery/stewardship/) |

`conversation` 행의 owner-tool 세부 동작은 후처리 첨부가 아니라 인과적 경로입니다. Bragi가
최종 T0/T1 owner route를 완료하고, 점수가 유일하게 가장 높은 owned read 하나를 실행한 다음,
완료된 결과를 primary answer로 사용합니다. 선택된 read가 실패하면 generic 또는 contributor
fallback 없이 handoff합니다. Delivery adapter는 완료된 답변에 무관한 tool evidence를 추가하지
않습니다.

Inventory scope-only follow-up은
[`chat_inventory_followup.py`](../../../src/fdai/delivery/operator_api/routes/chat_inventory_followup.py)에
분리되어 있습니다. 이 helper는 최신 user inventory intent만 재사용하며 `chat.py`와
`chat_stream.py`는 동일한 deterministic planning bypass와 subscription-root provider scope를
적용합니다.

Presentation intent는
[`answer_plan.py`](../../../src/fdai/core/conversation/answer_plan.py)에서 typed contract로
관리합니다. 명시적인 table 및 chart format과
[`chat_presentation.py`](../../../src/fdai/delivery/operator_api/routes/chat_presentation.py)의
strict shape-only model selection은 `chat_verification.py`를 거쳐 deterministic
inventory rendering에 전달됩니다. `chat_evidence_enrichment.py`는 내부 inventory read를
provider command를 만들지 않고 verifier가 승인한 typed query 및 snapshot provenance를
channel-neutral query activity row로 projection합니다.

## 룰 카탈로그, 배포, 플랫폼

| 서브시스템 | 책임 | 소스 | 테스트 |
|-----------|------|------|--------|
| rule_catalog_profiles | 프로파일 / 팩 레이어 + `extends` 오버라이드 | [src/fdai/core/rule_catalog_profiles/](../../../src/fdai/core/rule_catalog_profiles/) | [tests/core/rule_catalog_profiles/](../../../tests/core/rule_catalog_profiles/) |
| deploy_preflight | 배포 전 실현성 프로브 | [src/fdai/core/deploy_preflight/](../../../src/fdai/core/deploy_preflight/) | [tests/core/deploy_preflight/](../../../tests/core/deploy_preflight/) |
| onboarding | 테넌트 / 환경 온보딩 흐름 | [src/fdai/core/onboarding/](../../../src/fdai/core/onboarding/) | [tests/core/](../../../tests/core/) |
| runtime_bootstrap | durable T2 recovery receipt, legacy backfill, reconciliation, grounded chat visibility, Thor/Vidar가 승인된 mutation과 rollback을 소유하는 StateStore-backed proposer route registry를 포함한 프로세스 composition 및 long-running task orchestration | [src/fdai/runtime/bootstrap.py](../../../src/fdai/runtime/bootstrap.py), [src/fdai/runtime/t2_recovery.py](../../../src/fdai/runtime/t2_recovery.py), [src/fdai/runtime/t2_route_registry.py](../../../src/fdai/runtime/t2_route_registry.py), [src/fdai/runtime/bootstrap_lifecycle.py](../../../src/fdai/runtime/bootstrap_lifecycle.py) | [tests/runtime/test_bootstrap_config.py](../../../tests/runtime/test_bootstrap_config.py), [tests/runtime/test_t2_recovery.py](../../../tests/runtime/test_t2_recovery.py), [tests/runtime/test_t2_route_registry.py](../../../tests/runtime/test_t2_route_registry.py) |
| readiness | 운영 handoff, deterministic Best Practice checklist, attempt별 synthetic correlation을 사용하는 startup probe, agent 소유 monitored-target readiness, due-gated scheduled discovery repair의 fail-closed reduction, evidence expiry, authority ceiling 및 durable transition ([설계](../operations/startup-and-lifecycle-ko.md)) | [src/fdai/core/readiness/](../../../src/fdai/core/readiness/), [src/fdai/runtime/readiness.py](../../../src/fdai/runtime/readiness.py), [src/fdai/delivery/startup_probe.py](../../../src/fdai/delivery/startup_probe.py), [src/fdai/delivery/analyzer_tick_cli.py](../../../src/fdai/delivery/analyzer_tick_cli.py), [src/fdai/delivery/inventory_sync_cli.py](../../../src/fdai/delivery/inventory_sync_cli.py) 및 [src/fdai/delivery/persistence/postgres_inventory_snapshot.py](../../../src/fdai/delivery/persistence/postgres_inventory_snapshot.py) | [tests/core/readiness/](../../../tests/core/readiness/), [tests/agents/test_detection_readiness.py](../../../tests/agents/test_detection_readiness.py), [tests/runtime/test_readiness.py](../../../tests/runtime/test_readiness.py), [tests/delivery/test_inventory_reconciliation_gate.py](../../../tests/delivery/test_inventory_reconciliation_gate.py) 및 [tests/delivery/test_analyzer_tick_cli.py](../../../tests/delivery/test_analyzer_tick_cli.py) |
| assurance_twin | Persisted active/challenger effect model과 bounded runtime no-op/action branch simulation을 포함한 read-only ontology twin (실행 금지) | [src/fdai/core/assurance_twin/](../../../src/fdai/core/assurance_twin/) | [tests/assurance_twin/](../../../tests/assurance_twin/) |
| architecture_review | Architecture-review manifest -> governed ontology projection | [src/fdai/core/architecture_review/](../../../src/fdai/core/architecture_review/) | [tests/core/architecture_review/](../../../tests/core/architecture_review/) |
| workflow | Version-pinned WorkflowDefinition을 컴파일 및 실행합니다. 승인 quorum은 정규화된 principal을 세므로 한 운영자가 두 표기로 quorum을 채우거나 자신이 요청한 step을 승인할 수 없습니다. Principal binding과 Process journal과 projection retry 관리 | [src/fdai/core/workflow/](../../../src/fdai/core/workflow/) | [tests/core/workflow/](../../../tests/core/workflow/) |
| scheduler | Create/pause/resume/edit/run-now/cancel lifecycle, cron dispatch, run history, blueprint, idempotent lifecycle audit 및 CAS winner만 expiry audit을 기록하는 범위 제한 continuation ([설계](../interfaces/scheduled-result-continuations-ko.md)) | [src/fdai/core/scheduler/](../../../src/fdai/core/scheduler/) | [tests/core/scheduler/](../../../tests/core/scheduler/) |
| metering | 사용량 미터링 카운터와 모든 LLM 경로가 측정되는 공유 model budget. 호출이 기록되는 단일 지점에서 차감하며, 총량은 ledger 축출을 견디지만 correlation별 한도는 그렇지 않으며, metering 기록이 실패해도 차감은 수행. 관문은 읽고 쓰기가 아니라 exact prospective call 및 microUSD increment를 검증하는 원자적 예약. Ledger는 microUSD로 계산하며 다른 통화 가격은 차감하지 않음 | [src/fdai/core/metering/](../../../src/fdai/core/metering/) | [tests/core/metering/](../../../tests/core/metering/) |
| measurement | MTTR, DORA, pattern growth, Dynamic challenger learning 및 audited immutable operational-promotion receipt. Live-only observation window와 Wilson confidence가 clock 또는 small-sample promotion을 차단합니다 | [src/fdai/core/measurement/](../../../src/fdai/core/measurement/) | [tests/core/measurement/](../../../tests/core/measurement/) |
| mscp_profile | 레벨 비종속 `mscp-operational-v1` provenance, 순수 effect/cycle/integrity 검사 및 optional ControlLoop shadow observation ([설계](mscp-operational-profile-ko.md)) | [src/fdai/core/mscp_profile/](../../../src/fdai/core/mscp_profile/) | [tests/core/mscp_profile/](../../../tests/core/mscp_profile/) |
| security | 보안 시그널 생산자 | [src/fdai/core/security/](../../../src/fdai/core/security/) | [tests/core/security/](../../../tests/core/security/) |
| platform | 플랫폼 프리미티브 파사드 | [src/fdai/core/platform/](../../../src/fdai/core/platform/) | [tests/core/](../../../tests/core/) |
| verticals | Resilience / Change Safety / Cost | [src/fdai/core/verticals/](../../../src/fdai/core/verticals/) | [tests/core/verticals/](../../../tests/core/verticals/) |

## 에이전트 판테온

15명의 이름있는 에이전트. 모든 파일은 `src/fdai/agents/` 아래 평면 배치;
프레임워크 헬퍼는 `_framework/` 아래. fork-잠금 role 바인딩과 변경 계약은
[.github/instructions/agent-pantheon.instructions.md](../../../.github/instructions/agent-pantheon.instructions.md)
참조.

Conversation charter text는 `_framework/charters.py`에 있고 `_framework/pantheon.py`가 각 agent를
bind하며 `AgentSpec`이 정확한 role 및 budget contract를 삽입합니다. Turn별 상황 조립은
`_framework/conversation_prompt.py`에 있습니다. Bounded T1/T2
discussion contract는 `_framework/deliberation.py`에 있으며 Bragi가 `PantheonRuntime.deliberate`를
통해 orchestrate합니다.
[conversational-deliberation-ko.md](../agents/conversational-deliberation-ko.md)를 참조하세요.
Bounded cost, capacity, chaos trigger parsing은 `_framework/specialist_ingress.py`에 있고 domain
agent는 owned advisory topic을 publish하기 전에 이 canonical Event를 consume합니다.

| 에이전트 | 역할 | 소스 | 설계 문서 |
|---------|------|------|----------|
| Odin | 마스터 플래너 + 타이 브레이커 | [odin.py](../../../src/fdai/agents/odin.py) | [agent-pantheon-ko.md](../agents/agent-pantheon-ko.md) |
| Thor | 유일 특권 실행자 / 디스패처 | [thor.py](../../../src/fdai/agents/thor.py) | agent-pantheon.md |
| Forseti | 판사 (판결 발행자) | [forseti.py](../../../src/fdai/agents/forseti.py) | agent-pantheon.md |
| Huginn | 이벤트 수집자 | [huginn.py](../../../src/fdai/agents/huginn.py) | agent-pantheon.md |
| Heimdall | 관찰자 / 시그널 수집자 | [heimdall.py](../../../src/fdai/agents/heimdall.py) | agent-pantheon.md |
| Var | HIL 승인 주체 | [var.py](../../../src/fdai/agents/var.py) | agent-pantheon.md |
| Vidar | 복구 / 롤백 / DR | [vidar.py](../../../src/fdai/agents/vidar.py) | agent-pantheon.md |
| Bragi | 내레이터 (번역기 전용, 판사 아님) | [bragi.py](../../../src/fdai/agents/bragi.py) | agent-pantheon.md |
| Saga | 감사자 + 이슈 핸드오프 | [saga.py](../../../src/fdai/agents/saga.py) | agent-pantheon.md |
| Mimir | 룰 스튜어드 | [mimir.py](../../../src/fdai/agents/mimir.py) | agent-pantheon.md |
| Norns | 학습자 | [norns.py](../../../src/fdai/agents/norns.py) | agent-pantheon.md |
| Muninn | 메모리 | [muninn.py](../../../src/fdai/agents/muninn.py) | agent-pantheon.md |
| Njord | 비용 전문가 (자문) | [njord.py](../../../src/fdai/agents/njord.py) | agent-pantheon.md |
| Freyr | 용량 전문가 (자문) | [freyr.py](../../../src/fdai/agents/freyr.py) | agent-pantheon.md |
| Loki | 카오스 전문가 (자문) | [loki.py](../../../src/fdai/agents/loki.py) | agent-pantheon.md |

## Delivery 어댑터 (외부)

| 어댑터 | 목적 | 소스 |
|--------|------|------|
| azure | Azure operation, inventory, typed command, metric, bounded KQL, App Insights evidence, development Function gateway `DirectApiExecutor`, pinned-template Container Apps Job backend | [src/fdai/delivery/azure/](../../../src/fdai/delivery/azure/) |
| shell | Bash no-exec 검사, private Git workspace, credential-free bubblewrap command runner | [src/fdai/delivery/shell/](../../../src/fdai/delivery/shell/) |
| execution_backend | Bubblewrap 및 VM-task sandbox authority를 보존하는 lifecycle adapter | [src/fdai/delivery/execution_backend/](../../../src/fdai/delivery/execution_backend/) |
| programmatic_pipeline | Local isolated child runner 및 broker transport | [src/fdai/delivery/programmatic_pipeline/](../../../src/fdai/delivery/programmatic_pipeline/) |
| browser | General browser handle 없이 GET/HEAD를 intercept하는 선택적 isolated async Playwright capture | [src/fdai/delivery/browser/](../../../src/fdai/delivery/browser/) |
| trajectory | Deterministic streaming exporter, PostgreSQL metadata/quarantine store, Owner-only read projection, offline CLI | [src/fdai/delivery/trajectory/](../../../src/fdai/delivery/trajectory/), [postgres_trajectory.py](../../../src/fdai/delivery/persistence/postgres_trajectory.py), [trajectory_datasets.py](../../../src/fdai/delivery/operator_api/routes/trajectory_datasets.py), [deployment_cli/trajectory.py](../../../src/fdai/deployment_cli/trajectory.py) |
| case_history | StateStore CAS metadata 및 managed-identity Azure Blob artifact | [state_store_case_history.py](../../../src/fdai/delivery/persistence/state_store_case_history.py), [case_history_artifacts.py](../../../src/fdai/delivery/azure/case_history_artifacts.py), [runtime/case_history.py](../../../src/fdai/runtime/case_history.py) |
| azure_devops | Azure DevOps PR / 파이프라인 게이트 | [src/fdai/delivery/azure_devops/](../../../src/fdai/delivery/azure_devops/) |
| github | GitHub App / Checks API | [src/fdai/delivery/github/](../../../src/fdai/delivery/github/) |
| gitops_pr | PR-native 리메디에이션 패키저 | [src/fdai/delivery/gitops_pr/](../../../src/fdai/delivery/gitops_pr/) |
| chatops | Teams / Slack Adaptive Cards | [src/fdai/delivery/chatops/](../../../src/fdai/delivery/chatops/) |
| notifications | 채널 dispatch와 PagerDuty/ServiceNow incident lifecycle 및 PagerDuty roster adapter | [notifications/](../../../src/fdai/delivery/notifications/), [incident_platform/](../../../src/fdai/delivery/incident_platform/) |
| operator_api | 콘솔 read-only HTTP 서피스, production optional-service builder, route-owned chat request, principal 범위 complete-history 및 knowledge-context 조립, bounded terminal timing, trajectory-detail replay, verification rendering, background, busy-input, skill, read-investigation helper | [src/fdai/delivery/operator_api/](../../../src/fdai/delivery/operator_api/), [production/knowledge_context.py](../../../src/fdai/delivery/operator_api/production/knowledge_context.py), [production/python_tasks.py](../../../src/fdai/delivery/operator_api/production/python_tasks.py), [chat_history_context.py](../../../src/fdai/delivery/operator_api/routes/chat_history_context.py), [chat_knowledge_context.py](../../../src/fdai/delivery/operator_api/routes/chat_knowledge_context.py), [chat_stream_request.py](../../../src/fdai/delivery/operator_api/routes/chat_stream_request.py), [chat_stream_setup.py](../../../src/fdai/delivery/operator_api/routes/chat_stream_setup.py), [chat_stream_terminal.py](../../../src/fdai/delivery/operator_api/routes/chat_stream_terminal.py), [chat_trajectory_detail.py](../../../src/fdai/delivery/operator_api/routes/chat_trajectory_detail.py), [chat_vision_prompt.py](../../../src/fdai/delivery/operator_api/routes/chat_vision_prompt.py), [chat_verification_rendering.py](../../../src/fdai/delivery/operator_api/routes/chat_verification_rendering.py), [chat_verification_text.py](../../../src/fdai/delivery/operator_api/routes/chat_verification_text.py), [read_investigation_payload.py](../../../src/fdai/delivery/operator_api/routes/read_investigation_payload.py), [read_investigation_execution.py](../../../src/fdai/delivery/operator_api/routes/read_investigation_execution.py) |
| provisioning | Terraform / IaC apply 드라이버 | [src/fdai/delivery/provisioning/](../../../src/fdai/delivery/provisioning/) |
| persistence | Durable delivery, execution, metering, projection, receipt store와 함께 focused background-task completion/serialization 및 read-investigation run serialization 모듈을 포함하는 Postgres + pgvector store | [src/fdai/delivery/persistence/](../../../src/fdai/delivery/persistence/), [postgres_background_task_completion.py](../../../src/fdai/delivery/persistence/postgres_background_task_completion.py), [postgres_background_task_serialization.py](../../../src/fdai/delivery/persistence/postgres_background_task_serialization.py), [postgres_read_investigation_run_serialization.py](../../../src/fdai/delivery/persistence/postgres_read_investigation_run_serialization.py) |
| document_index | Structure-aware document chunking과 로컬 embedding retrieval | [src/fdai/delivery/document_index/](../../../src/fdai/delivery/document_index/) |
| behavior_knowledge | Localized object/architecture behavior seed, hybrid/comparison 검색, tracked-source freshness, 20문항 quality gate ([설계](../interfaces/behavior-knowledge-ko.md)) | [src/fdai/delivery/behavior_knowledge/](../../../src/fdai/delivery/behavior_knowledge/) |
| pgvector | Persistent document 및 behavior vector-index adapter | [src/fdai/delivery/pgvector/](../../../src/fdai/delivery/pgvector/) |
| datadog | Datadog 메트릭 / 이벤트 어댑터 (`metric.py`의 `DatadogMetricProvider`) | [src/fdai/delivery/datadog/](../../../src/fdai/delivery/datadog/) |
| prometheus | Prometheus scrape 어댑터 (`metric.py`의 `PrometheusMetricProvider`) | [src/fdai/delivery/prometheus/](../../../src/fdai/delivery/prometheus/) |
| splunk | Splunk 로그 어댑터 (`metric.py`의 `SplunkMetricProvider`) | [src/fdai/delivery/splunk/](../../../src/fdai/delivery/splunk/) |
| jira | Jira 이슈 어댑터 (`tool.py`의 `JiraToolExecutor`) | [src/fdai/delivery/jira/](../../../src/fdai/delivery/jira/) |
| mcp | Model Context Protocol seam | [src/fdai/delivery/mcp/](../../../src/fdai/delivery/mcp/) |
| webhook | 범용 아웃바운드 webhook + 옵션 `POST /webhook` 라우트를 위한 인바운드 `WebhookIngress` | [src/fdai/delivery/webhook/](../../../src/fdai/delivery/webhook/) |
| working_context | Delivery 측 컨텍스트 조립 | [src/fdai/delivery/working_context/](../../../src/fdai/delivery/working_context/) |
| chaos (delivery) | `Chaos` runbook 단계가 enforce로 갈 때 쓰는 라이브 카오스 주입 어댑터 - CSP-중립 `live_injectors.py` + `chaos_mesh.py` (Chaos Mesh CRD) + `mysql_load.py` (MySQL 벤치마크 부하) | [src/fdai/delivery/chaos/](../../../src/fdai/delivery/chaos/) |
| investigation (delivery) | 공유 MetricProvider를 사용하는 governed on-demand investigation ToolExecutor | [src/fdai/delivery/investigation/](../../../src/fdai/delivery/investigation/) |
| irp (delivery) | 권고를 typed pipeline에 재진입시키는 alert handler + EventBus proposal router | [src/fdai/delivery/irp/](../../../src/fdai/delivery/irp/) |
| remediation (delivery) | 직접 API 리메디에이션용 구체 `DirectApiExecutor` (`live_direct_api.py`); Protocol 정의는 `shared/providers/`에 있음 | [src/fdai/delivery/remediation/](../../../src/fdai/delivery/remediation/) |
| scheduler_tick_cli | cron / Container Apps Job에서 스케줄러 tick을 구동하는 독립 엔트리 포인트 (단일 모듈, 패키지 아님) | [src/fdai/delivery/scheduler_tick_cli.py](../../../src/fdai/delivery/scheduler_tick_cli.py) |
| analyzer_tick_cli | finding을 publish하고 report signal을 저장하는 inventory 기반 metric analyzer 엔트리 포인트 | [src/fdai/delivery/analyzer_tick_cli.py](../../../src/fdai/delivery/analyzer_tick_cli.py) |

## Shared 배관 (`src/fdai/shared/`)

| 패키지 | 목적 | 소스 |
|--------|------|------|
| contracts | ObjectType lifecycle 기준과 ActionType declaration 및 runtime Action이 공유하는 structured stop-condition value object를 포함한 크로스 패키지 Pydantic 계약 | [src/fdai/shared/contracts/](../../../src/fdai/shared/contracts/) |
| ontology | 도메인 온톨로지 (ObjectType / LinkType / ActionType) | [src/fdai/shared/ontology/](../../../src/fdai/shared/ontology/) |
| providers | `ExecutionBackend`, bounded diagnostic receipt와 분리되고 cache되지 않는 ephemeral typed-command output, strict decode와 count/character bound 및 secret scan이 있는 durable channel-neutral handoff/execution activity를 포함한 Provider Protocol, same-group lease를 직렬화하고 독립 group 진행을 보장하는 process-local EventBus, bounded SSE, isolated programmatic pipeline runner, [access-scoped conversation search](../interfaces/conversation-search-ko.md), [structured behavior knowledge](../interfaces/behavior-knowledge-ko.md) | [src/fdai/shared/providers/](../../../src/fdai/shared/providers/) |
| config | 설정 로더, 스키마, shared runtime activation flag | [src/fdai/shared/config/](../../../src/fdai/shared/config/) |
| streaming | Kafka / Event Hub 추상화 | [src/fdai/shared/streaming/](../../../src/fdai/shared/streaming/) |
| resilience | 재시도 / circuit-breaker 헬퍼 | [src/fdai/shared/resilience/](../../../src/fdai/shared/resilience/) |
| telemetry | 구조화 로깅 + 메트릭 헬퍼 | [src/fdai/shared/telemetry/](../../../src/fdai/shared/telemetry/) |

## Benchmark integration

| 경로 | 목적 |
|------|------|
| [evaluation-sdk/](../../../evaluation-sdk/) | 독립적으로 package할 수 있는 neutral contract, public Protocol, workspace value 및 bounded runner입니다. |
| [src/fdai/evaluation/](../../../src/fdai/evaluation/) | Public host 구현, capability attenuation, artifact custody, workspace policy, typed ingress 및 result receipt입니다. |
| [src/fdai/benchmarking/](../../../src/fdai/benchmarking/) | Legacy benchmark caller를 위한 임시 `0.1.x` compatibility facade입니다. |
| [benchmarks/](../../../benchmarks/) | 독립적으로 package된 SREGym 및 CyberGym driver입니다. [benchmark adapter 설계](../interfaces/benchmark-adapters-ko.md)를 참조하세요. |

## Optional extension package

| 경로 | 용도 |
|------|------|
| [extensions/code-assurance/](../../../extensions/code-assurance/) | Bounded read-only GitHub pull-request code/security review, self-contained capability binding, governed skill asset을 제공하는 독립 shadow-first wheel입니다. |

## Composition과 카탈로그

| 경로 | 목적 |
|------|------|
| [src/fdai/composition/\_\_init\_\_.py](../../../src/fdai/composition/__init__.py) | 파사드 + `default_container` + `default_container_from_env`. |
| [src/fdai/composition/_helpers.py](../../../src/fdai/composition/_helpers.py) | `Container`, 지출이 차감되는 metering, pricing, model key와 함께 바인딩되는 optional conversation T2 synthesis를 포함한 `LlmBindings`, `LlmBindingsUnavailableError`. |
| [src/fdai/composition/wire_llm.py](../../../src/fdai/composition/wire_llm.py) | Azure OpenAI LLM 바인더 (컴포지션 타임 모델 해석). |
| [src/fdai/composition/wire_azure.py](../../../src/fdai/composition/wire_azure.py) | Fork-wire 컨테이너 + `AzureWireOverrides`. |
| [src/fdai/composition/wire_change_feed.py](../../../src/fdai/composition/wire_change_feed.py) | change-feed 팩토리 wiring (Azure DevOps / GitHub 변경 생산자). |
| [src/fdai/composition/wire_metric_provider.py](../../../src/fdai/composition/wire_metric_provider.py) | `MetricProvider` 바인더 (`FDAI_MONITOR_WORKSPACE_ID` 세팅 시 Azure Monitor Logs 자동 바인드); LOC 상한 유지를 위해 `wire_azure`에서 분리 (G-4). |
| [src/fdai/composition/wire_trajectory.py](../../../src/fdai/composition/wire_trajectory.py) | 기본 container에서 feature를 활성화하지 않고 authorization-first source join, dataset metadata, quarantine export, read-only administration을 bind. |
| [src/fdai/composition/wire_execution_backends.py](../../../src/fdai/composition/wire_execution_backends.py) | Server-selected profile을 validate하고 required backend 및 durable ledger를 bind하며 profile은 기본적으로 enable하지 않습니다. |
| [src/fdai/rule_catalog/](../../../src/fdai/rule_catalog/) | Rule, Best Practice, governance artifact 및 나머지 `rule-catalog/` YAML 트리의 strict loader. |
| [src/fdai/rule_catalog/pipeline/distill/](../../../src/fdai/rule_catalog/pipeline/distill/) | Build-time manual compilation, `DocumentEnvelope` provenance bridge, normalized cross-format graph 비교, review-only ontology proposal, partition release gate, provider conformance 및 lifecycle/evaluation plan. |
| [rule-catalog/](../../../rule-catalog/) | Rule, Best Practice, policy, rule-set 및 action-type 카탈로그 (데이터). |

## 개발자 엔트리 포인트와 슬래시 커맨드

로컬 개발, 검증, 세션 인수인계를 일관되게 유지하기 위해 리포에서 제공하는
스크립트와 Copilot 슬래시 커맨드 모음.

| 경로 | 목적 |
|------|------|
| [scripts/verify.sh](../../../scripts/verify.sh) | 단일 로컬 게이트: 기본은 fast text/lint와 clean-checkout 계약을 실행합니다. `--full <path>`는 지정한 pytest 대상만 실행하고, 명시적 `--all`은 전체 리포지토리 coverage와 console/CLI 검증을 추가합니다. |
| [check-readable-hangul.py](../../../scripts/quality/localization/check-readable-hangul.py) | Source의 불투명한 Hangul escape를 차단하고 UTF-8 기계적 fixer를 제공하며, 정확한 rationale이 있는 code-point 예외만 허용합니다. |
| [tools/architecture-diagrams/](../../../tools/architecture-diagrams/) | Bilingual YAML을 SVG/PNG architecture diagram으로 컴파일하고 progressive site viewer를 생성합니다. Canonical spec은 [docs/diagrams/](../../diagrams/)에 있습니다. |
| [scripts/lib/design-routes.json](../../../scripts/lib/design-routes.json) | Machine-readable path -> required instruction/design doc -> owning doc -> focused validation route입니다. |
| [scripts/agent/design_context.py](../../../scripts/agent/design_context.py) / [.github/hooks/design-context.json](../../../.github/hooks/design-context.json) | Agent session별 design-document read 성공을 기록하고 required context가 없거나 stale이면 edit를 차단합니다. |
| [check-design-doc-impact.py](../../../scripts/quality/architecture/check-design-doc-impact.py) / [check-document-size.py](../../../scripts/quality/architecture/check-document-size.py) | Docs-after enforcement와 new-doc/legacy-growth size ratchet입니다. |
| [check-fork-runtime-independence.py](../../../scripts/quality/architecture/check-fork-runtime-independence.py) | Fork integrity marker가 runtime/config/infra behavior에 들어오면 차단합니다. |
| [scripts/quality/ci/check-ci-contracts.py](../../../scripts/quality/ci/check-ci-contracts.py) | 로컬 검증과 CI가 공유하는 clean-checkout, Docker build-context, live-DB skip 순서, Python test partition 회귀 검사입니다. |
| [scripts/quality/ci/run-python-tests.sh](../../../scripts/quality/ci/run-python-tests.sh) | Local `all` mode는 coverage와 integration을 유지합니다. CI는 deterministic no-coverage regression shard, core-focused coverage, serial live-DB integration 중 하나를 선택합니다. Change-scope 분류는 docs-only와 console-only 변경에서 비싼 Python job을 생략합니다. |
| [scripts/quality/ci/pytest_shard.py](../../../scripts/quality/ci/pytest_shard.py) / [resolve_test_scope.py](../../../scripts/quality/ci/resolve_test_scope.py) | 비싼 CI test job을 위한 stable file-level shard assignment와 Git diff 분류입니다. |
| [scripts/quality/ci/run-operator-surfaces.sh](../../../scripts/quality/ci/run-operator-surfaces.sh) | Console/CLI 테스트, type check, production build, entry-bundle 예산 검사를 실행합니다. |
| [scripts/deployment/local/dev-up.sh](../../../scripts/deployment/local/dev-up.sh) / [dev-down.sh](../../../scripts/deployment/local/dev-down.sh) / [dev-logs.sh](../../../scripts/deployment/local/dev-logs.sh) / [dev-status.sh](../../../scripts/deployment/local/dev-status.sh) | 로컬 Docker Compose 스택 (pgvector + Redpanda) 라이프사이클. |
| [scripts/automation/tests-for-diff.sh](../../../scripts/automation/tests-for-diff.sh) | 현재 diff에 영향받는 pytest 파일만 실행. |
| [scripts/deployment/azure/genesis-up.sh](../../../scripts/deployment/azure/genesis-up.sh) | `terraform apply`를 `delivery/provisioning`으로 스트리밍해서 Day-1 Genesis 서피스로 전달. |
| [scripts/deployment/azure/azd-up.sh](../../../scripts/deployment/azure/azd-up.sh) | `azd up` 래퍼 (기본 safe-preview). |
| [scripts/automation/resume.sh](../../../scripts/automation/resume.sh) | 세션 간 인수인계용 세션 재개 스냅샷. |
| [.github/prompts/verify.prompt.md](../../../.github/prompts/verify.prompt.md) | `/verify` - `scripts/verify.sh` 실행. |
| [.github/prompts/critique-batch.prompt.md](../../../.github/prompts/critique-batch.prompt.md) | `/critique-batch` - critique-and-harden 루프 (`coding-hardening` 스킬과 세트). |
| [.github/prompts/harden-coverage.prompt.md](../../../.github/prompts/harden-coverage.prompt.md) | `/harden-coverage` - 저커버리지 모듈에 대한 coverage 하드닝. |
| [.github/prompts/pantheon-safe-edit.prompt.md](../../../.github/prompts/pantheon-safe-edit.prompt.md) | `/pantheon-safe-edit` - `src/fdai/agents/**` 아래 보호된 편집. |
| [.github/prompts/resume-session.prompt.md](../../../.github/prompts/resume-session.prompt.md) | `/resume-session` - 이전 세션 컨텍스트 재로드. |

## 관련 문서

| 알아볼 것 | 읽을 문서 |
|----------|----------|
| 모듈 경계와 DI seam | [project-structure-ko.md](project-structure-ko.md) |
| 3-티어 컨트롤 루프 | [../../../.github/instructions/architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) |
| 에이전트 역할과 권한 | [../agents/agent-pantheon-ko.md](../agents/agent-pantheon-ko.md) |
| CSP-중립 계약 seam | [csp-neutrality-ko.md](csp-neutrality-ko.md) |
| LLM 티어링과 grounding | [llm-strategy-ko.md](llm-strategy-ko.md) |
