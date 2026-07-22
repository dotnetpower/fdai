---
title: 코드 맵
translation_of: code-map.md
translation_source_sha: d9afbd6ab32f74611151a60e910830892d7ae2e3
translation_revised: 2026-07-22
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
  영속성, read API).
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
| tiers/t0_deterministic | 정책 + 체크리스트 + what-if + drift | [src/fdai/core/tiers/t0_deterministic/](../../../src/fdai/core/tiers/t0_deterministic/) | [tests/core/tiers/](../../../tests/core/tiers/) | project-structure-ko.md |
| tiers/t1_lightweight | 유사도 재사용 + 소형 모델 분류 | [src/fdai/core/tiers/t1_lightweight/](../../../src/fdai/core/tiers/t1_lightweight/) | [tests/core/tiers/](../../../tests/core/tiers/) | project-structure-ko.md |
| tiers/t2_reasoning | 프론티어 모델 추론 (신규 케이스만) | [src/fdai/core/tiers/t2_reasoning/](../../../src/fdai/core/tiers/t2_reasoning/) | [tests/core/tiers/](../../../tests/core/tiers/) | [llm-strategy-ko.md](llm-strategy-ko.md) |
| quality_gate | 혼합 모델 + verifier + grounding (T2 가드) | [src/fdai/core/quality_gate/](../../../src/fdai/core/quality_gate/) | [tests/core/quality_gate/](../../../tests/core/quality_gate/) | [architecture.instructions.md § LLM Quality Gate](../../../.github/instructions/architecture.instructions.md#llm-quality-gate-required-for-t2) |
| risk_gate | 통합 auto vs HIL vs deny 권위 | [src/fdai/core/risk_gate/](../../../src/fdai/core/risk_gate/) | [tests/core/risk_gate/](../../../tests/core/risk_gate/) | [decisioning/](../decisioning/) |
| hil_resume | 파킹 + 채널 푸시 + 결정시 재개 | [src/fdai/core/hil_resume/](../../../src/fdai/core/hil_resume/) | [tests/core/hil_resume/](../../../tests/core/hil_resume/) | project-structure-ko.md |
| executor | 리소스별 lock, 멱등 적용 | [src/fdai/core/executor/](../../../src/fdai/core/executor/) | [tests/core/](../../../tests/core/) (executor 관련) | project-structure-ko.md |
| execution_backend | Profile intersection, durable reconciliation, shadow health probe를 제공하며 eligibility authority는 없음 ([설계](../interfaces/execution-backends-ko.md)) | [src/fdai/core/execution_backend/](../../../src/fdai/core/execution_backend/) | [tests/core/execution_backend/](../../../tests/core/execution_backend/) | [execution-backends-ko.md](../interfaces/execution-backends-ko.md) |
| audit | append-only 해시체인 로그, nullable-stage correlation trace 및 KPI 방출 | [src/fdai/core/audit/](../../../src/fdai/core/audit/) | [tests/core/audit/](../../../tests/core/audit/) | [security-and-identity-ko.md](security-and-identity-ko.md) |
| control_loop | 파이프라인 오케스트레이터 (Stage 프로토콜) | [src/fdai/core/control_loop/](../../../src/fdai/core/control_loop/) | [tests/core/](../../../tests/core/) | project-structure-ko.md |
| pipeline | 위 서브시스템들의 도메인 그룹 파사드 | [src/fdai/core/pipeline/](../../../src/fdai/core/pipeline/) | (멤버와 동일) | project-structure-ko.md |

## 탐지, RCA, 인시던트 라이프사이클

| 서브시스템 | 책임 | 소스 | 테스트 |
|-----------|------|------|--------|
| detection | 이상치, 예측, 50개 카탈로그 기반 운영 insight 발견자 (event-ingest 재진입) | [src/fdai/core/detection/](../../../src/fdai/core/detection/) | [tests/core/detection/](../../../tests/core/detection/) |
| rca | 근본원인 분석 (T0 + T2 seam 뒤) | [src/fdai/core/rca/](../../../src/fdai/core/rca/) | [tests/core/rca/](../../../tests/core/rca/) |
| incident | 인시던트 라이프사이클 레지스트리 + 상태 머신 | [src/fdai/core/incident/](../../../src/fdai/core/incident/) | [tests/core/incident/](../../../tests/core/incident/) |
| slo | 워크로드 SLO / burn-rate 평가자 | [src/fdai/core/slo/](../../../src/fdai/core/slo/) | [tests/core/slo/](../../../tests/core/slo/) |
| irp | 인시던트 대응 계획 오케스트레이터 | [src/fdai/core/irp/](../../../src/fdai/core/irp/) | [tests/core/irp/](../../../tests/core/irp/) |
| investigation | 예산 제한 증거 수집 러너 | [src/fdai/core/investigation/](../../../src/fdai/core/investigation/) | [tests/core/investigation/](../../../tests/core/investigation/) |
| runbook | 선형 runbook + 실패 분기 | [src/fdai/core/runbook/](../../../src/fdai/core/runbook/) | [tests/core/](../../../tests/core/) |
| postmortem | LLM-옵션 PIR 초안 | [src/fdai/core/postmortem/](../../../src/fdai/core/postmortem/) | [tests/core/postmortem/](../../../tests/core/postmortem/) |
| chaos | 회복성 / 카오스 프로브 | [src/fdai/core/chaos/](../../../src/fdai/core/chaos/) | [tests/core/chaos/](../../../tests/core/chaos/) |
| capacity | 용량 + 예측 findings | [src/fdai/core/capacity/](../../../src/fdai/core/capacity/) | [tests/core/capacity/](../../../tests/core/capacity/) |
| oncall | 온콜 로테이션 리더 (read-only) | [src/fdai/core/oncall/](../../../src/fdai/core/oncall/) | [tests/core/](../../../tests/core/) |

## 지식, 메모리, 프롬프트

| 서브시스템 | 책임 | 소스 | 테스트 |
|-----------|------|------|--------|
| knowledge | 장기 지식 저장소 seam | [src/fdai/core/knowledge/](../../../src/fdai/core/knowledge/) | [tests/core/knowledge/](../../../tests/core/knowledge/) |
| operator_memory | HIL 승인된 오퍼레이터 노트 저장소 | [src/fdai/core/operator_memory/](../../../src/fdai/core/operator_memory/) | [tests/core/operator_memory/](../../../tests/core/operator_memory/) |
| learning | 동의 기반 off-path post-turn eligibility, mixed-family consensus, 중복 제거, 비활성 proposal routing ([설계](../decisioning/post-turn-improvement-review-ko.md)) | [src/fdai/core/learning/](../../../src/fdai/core/learning/) | [tests/core/learning/](../../../tests/core/learning/) |
| trajectory | Authorization-first immutable source join, versioned observable envelope, deterministic JSONL export, offline validation/replay, retention/legal hold, reviewed-only Norns aggregate intake ([설계](../interfaces/governed-trajectory-datasets-ko.md)) | [src/fdai/core/trajectory/](../../../src/fdai/core/trajectory/) 및 [src/fdai/shared/providers/trajectory.py](../../../src/fdai/shared/providers/trajectory.py) | [tests/core/trajectory/](../../../tests/core/trajectory/), [tests/delivery/trajectory/](../../../tests/delivery/trajectory/), focused API/persistence/agent test |
| task_worker | 축소된 capability, 영구 branch state, 신뢰되지 않은 parent synthesis를 사용하는 격리된 depth-one 읽기 전용 조사 ([설계](../agents/bounded-task-workers-ko.md)) | [src/fdai/core/task_worker/](../../../src/fdai/core/task_worker/) | [tests/core/task_worker/](../../../tests/core/task_worker/) |
| background_task | Lease/CAS ownership, server-clock quota, coalesced progress, 정직한 process-loss state, completion handoff를 사용하는 영구 detached 읽기 전용 session ([설계](../interfaces/background-task-sessions-ko.md)) | [src/fdai/core/background_task/](../../../src/fdai/core/background_task/) | [tests/core/background_task/](../../../tests/core/background_task/) |
| read_investigation | Exact-resource-first Azure VM 및 network read, bounded parallel evidence, RG-scoped subscription health와 대표 metric sweep, durable latency profile 및 direct/streamed/detached policy ([설계](../interfaces/azure-read-investigations-ko.md)) | [src/fdai/core/read_investigation/](../../../src/fdai/core/read_investigation/), [src/fdai/shared/providers/read_investigation.py](../../../src/fdai/shared/providers/read_investigation.py) 및 [src/fdai/delivery/azure/subscription_health.py](../../../src/fdai/delivery/azure/subscription_health.py) | [tests/core/read_investigation/](../../../tests/core/read_investigation/), [tests/delivery/azure/read_investigation/](../../../tests/delivery/azure/read_investigation/) 및 focused Azure/read API test |
| briefing | Report feed 기반 결정적 opening 및 scheduled briefing | [src/fdai/core/briefing/](../../../src/fdai/core/briefing/) | [tests/core/briefing/](../../../tests/core/briefing/) |
| busy_input | Web, Slack, Teams conversation이 공유하는 영구 queue, interrupt, safe-boundary steer arbitration ([설계](../interfaces/busy-input-modes-ko.md)) | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/conversation/](../../../tests/conversation/) |
| durable_delivery | Verified principal binding, persisted outbound response, bounded recovery 및 adapter breaker ([설계](../interfaces/durable-conversation-delivery-ko.md)) | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/conversation/](../../../tests/conversation/) 및 [tests/persistence/](../../../tests/persistence/) |
| user_context_projection | 사용자 context 및 workflow binding metadata만 runtime ontology에 projection | [src/fdai/core/user_context_projection.py](../../../src/fdai/core/user_context_projection.py) | [tests/core/test_user_context_projection.py](../../../tests/core/test_user_context_projection.py) |
| working_context | 턴당 프롬프트 조립, invariant validation, capability-gated policy lifecycle, bounded shadow 비교 및 approved-fixture replay ([설계](../decisioning/context-selection-policy-ko.md)) | [src/fdai/core/working_context/](../../../src/fdai/core/working_context/) | [tests/core/working_context/](../../../tests/core/working_context/) |
| prompts | catalog-as-code 프롬프트 컴포저 | [src/fdai/core/prompts/](../../../src/fdai/core/prompts/) | [tests/core/](../../../tests/core/) |
| skills | Progressive disclosure, governed bundle, durable approved-source quarantine ([bundle 설계](../decisioning/governed-skill-bundles-ko.md), [source 설계](../interfaces/skill-source-management-ko.md)) | [src/fdai/core/skills/](../../../src/fdai/core/skills/) 및 [src/fdai/core/supply_chain/](../../../src/fdai/core/supply_chain/) | [tests/core/skills/](../../../tests/core/skills/), [tests/core/supply_chain/](../../../tests/core/supply_chain/), [tests/persistence/](../../../tests/persistence/) |
| programmatic_pipeline | Run capability, durable receipt, isolated runner, compact result를 사용하는 검토된 bounded read-only tool loop ([설계](../interfaces/programmatic-tool-pipelines-ko.md)) | [src/fdai/core/programmatic_pipeline/](../../../src/fdai/core/programmatic_pipeline/) | [tests/core/programmatic_pipeline/](../../../tests/core/programmatic_pipeline/) 및 [tests/delivery/programmatic_pipeline/](../../../tests/delivery/programmatic_pipeline/) |
| browser_evidence | Origin 및 DNS policy, redaction, immutable artifact, evidence-only surface, shadow comparison ([설계](../interfaces/browser-evidence-ko.md)) | [src/fdai/core/browser_evidence/](../../../src/fdai/core/browser_evidence/) | [tests/core/browser_evidence/](../../../tests/core/browser_evidence/) 및 [tests/delivery/browser/](../../../tests/delivery/browser/) |
| tools | T2 툴 레지스트리 + ToolExecutor + typed command catalog | [src/fdai/core/tools/](../../../src/fdai/core/tools/) | [tests/core/tools/](../../../tests/core/tools/) |
| web_search | 최후 수단 웹 검색 seam | [src/fdai/core/web_search/](../../../src/fdai/core/web_search/) | [tests/core/web_search/](../../../tests/core/web_search/) |
| capability_catalog | 각 에이전트가 아는 것 | [src/fdai/core/capability_catalog/](../../../src/fdai/core/capability_catalog/) | [tests/core/capability_catalog/](../../../tests/core/capability_catalog/) |
| ontology_explorer | 로드된 ObjectType / LinkType 카탈로그의 결정론적 Mermaid 렌더러 (단일 모듈, 패키지 아님) | [src/fdai/core/ontology_explorer.py](../../../src/fdai/core/ontology_explorer.py) | [tests/core/](../../../tests/core/) |

## 오퍼레이터 서피스와 알림

| 서브시스템 | 책임 | 소스 | 테스트 |
|-----------|------|------|--------|
| conversation | NL 턴 -> read-only 툴 호출 하나 | [src/fdai/core/conversation/](../../../src/fdai/core/conversation/) | [tests/core/conversation/](../../../tests/core/conversation/) |
| operator | 오퍼레이터 콘솔 코디네이터 | [src/fdai/core/operator/](../../../src/fdai/core/operator/) | (delivery/read_api 통합) |
| console_request | write-direction 콘솔 경로의 오퍼레이터 재요청 정책 (Scenario B deny-override) | [src/fdai/core/console_request/](../../../src/fdai/core/console_request/) | [tests/core/console_request/](../../../tests/core/console_request/) |
| notifications | 매트릭스 기반 채널 라우팅 레이어 | [src/fdai/core/notifications/](../../../src/fdai/core/notifications/) | [tests/notifications/](../../../tests/notifications/) |
| report_feed | 렌더된 리포트 구독 | [src/fdai/core/report_feed/](../../../src/fdai/core/report_feed/) | [tests/core/report_feed/](../../../tests/core/report_feed/) |
| reporting | 리포트 컴포저 + 포매터 | [src/fdai/core/reporting/](../../../src/fdai/core/reporting/) | [tests/core/reporting/](../../../tests/core/reporting/) |
| views | Workflow-matched ViewSpec -> bounded RenderedView 및 deterministic inventory architecture projection | [src/fdai/core/views/](../../../src/fdai/core/views/) | [tests/core/views/](../../../tests/core/views/) 및 read-API architecture-view test |
| rbac | Read API 인간 RBAC | [src/fdai/core/rbac/](../../../src/fdai/core/rbac/) | [tests/core/](../../../tests/core/) |
| stewardship | 인간 <-> 에이전트 인수인계 맵 (책임 + 에스컬레이션 오버레이) | [src/fdai/core/stewardship/](../../../src/fdai/core/stewardship/) | [tests/core/stewardship/](../../../tests/core/stewardship/) |

## 룰 카탈로그, 배포, 플랫폼

| 서브시스템 | 책임 | 소스 | 테스트 |
|-----------|------|------|--------|
| rule_catalog_profiles | 프로파일 / 팩 레이어 + `extends` 오버라이드 | [src/fdai/core/rule_catalog_profiles/](../../../src/fdai/core/rule_catalog_profiles/) | [tests/core/rule_catalog_profiles/](../../../tests/core/rule_catalog_profiles/) |
| deploy_preflight | 배포 전 실현성 프로브 | [src/fdai/core/deploy_preflight/](../../../src/fdai/core/deploy_preflight/) | [tests/core/deploy_preflight/](../../../tests/core/deploy_preflight/) |
| onboarding | 테넌트 / 환경 온보딩 흐름 | [src/fdai/core/onboarding/](../../../src/fdai/core/onboarding/) | [tests/core/](../../../tests/core/) |
| readiness | grounding된 준비도 리포트 | [src/fdai/core/readiness/](../../../src/fdai/core/readiness/) | [tests/core/](../../../tests/core/) |
| assurance_twin | Read-only 온톨로지 트윈 (실행 금지) | [src/fdai/core/assurance_twin/](../../../src/fdai/core/assurance_twin/) | [tests/core/assurance_twin/](../../../tests/core/assurance_twin/) |
| architecture_review | Architecture-review manifest -> governed ontology projection | [src/fdai/core/architecture_review/](../../../src/fdai/core/architecture_review/) | [tests/core/architecture_review/](../../../tests/core/architecture_review/) |
| workflow | Version-pinned WorkflowDefinition과 principal binding을 컴파일 및 실행하고 Process journal과 projection retry 관리 | [src/fdai/core/workflow/](../../../src/fdai/core/workflow/) | [tests/core/workflow/](../../../tests/core/workflow/) |
| scheduler | Create/pause/resume/edit/run-now/cancel lifecycle, cron dispatch, run history, blueprint, 범위 제한 continuation ([설계](../interfaces/scheduled-result-continuations-ko.md)) | [src/fdai/core/scheduler/](../../../src/fdai/core/scheduler/) | [tests/core/scheduler/](../../../tests/core/scheduler/) |
| metering | 사용량 미터링 카운터 | [src/fdai/core/metering/](../../../src/fdai/core/metering/) | [tests/core/metering/](../../../tests/core/metering/) |
| measurement | MTTR 및 네 가지 DORA measure를 포함한 Phase-4 연속 측정 | [src/fdai/core/measurement/](../../../src/fdai/core/measurement/) | [tests/core/measurement/](../../../tests/core/measurement/) |
| mscp_profile | 레벨 비종속 `mscp-operational-v1` provenance, 순수 effect/cycle/integrity 검사 및 optional ControlLoop shadow observation ([설계](mscp-operational-profile-ko.md)) | [src/fdai/core/mscp_profile/](../../../src/fdai/core/mscp_profile/) | [tests/core/mscp_profile/](../../../tests/core/mscp_profile/) |
| security | 보안 시그널 생산자 | [src/fdai/core/security/](../../../src/fdai/core/security/) | [tests/core/security/](../../../tests/core/security/) |
| platform | 플랫폼 프리미티브 파사드 | [src/fdai/core/platform/](../../../src/fdai/core/platform/) | [tests/core/](../../../tests/core/) |
| verticals | Resilience / Change Safety / Cost | [src/fdai/core/verticals/](../../../src/fdai/core/verticals/) | [tests/core/verticals/](../../../tests/core/verticals/) |

## 에이전트 판테온

15명의 이름있는 에이전트. 모든 파일은 `src/fdai/agents/` 아래 평면 배치;
프레임워크 헬퍼는 `_framework/` 아래. fork-잠금 role 바인딩과 변경 계약은
[.github/instructions/agent-pantheon.instructions.md](../../../.github/instructions/agent-pantheon.instructions.md)
참조.

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
| azure | Azure operation, inventory, typed command, metric, bounded KQL, App Insights evidence, pinned-template Container Apps Job backend | [src/fdai/delivery/azure/](../../../src/fdai/delivery/azure/) |
| shell | Bash no-exec 검사, private Git workspace, credential-free bubblewrap command runner | [src/fdai/delivery/shell/](../../../src/fdai/delivery/shell/) |
| execution_backend | Bubblewrap 및 VM-task sandbox authority를 보존하는 lifecycle adapter | [src/fdai/delivery/execution_backend/](../../../src/fdai/delivery/execution_backend/) |
| programmatic_pipeline | Local isolated child runner 및 broker transport | [src/fdai/delivery/programmatic_pipeline/](../../../src/fdai/delivery/programmatic_pipeline/) |
| browser | General browser handle 없이 GET/HEAD를 intercept하는 선택적 isolated async Playwright capture | [src/fdai/delivery/browser/](../../../src/fdai/delivery/browser/) |
| trajectory | Deterministic streaming exporter, PostgreSQL metadata/quarantine store, Owner-only read projection, offline CLI | [src/fdai/delivery/trajectory/](../../../src/fdai/delivery/trajectory/), [postgres_trajectory.py](../../../src/fdai/delivery/persistence/postgres_trajectory.py), [trajectory_datasets.py](../../../src/fdai/delivery/read_api/routes/trajectory_datasets.py), [deployment_cli/trajectory.py](../../../src/fdai/deployment_cli/trajectory.py) |
| azure_devops | Azure DevOps PR / 파이프라인 게이트 | [src/fdai/delivery/azure_devops/](../../../src/fdai/delivery/azure_devops/) |
| github | GitHub App / Checks API | [src/fdai/delivery/github/](../../../src/fdai/delivery/github/) |
| gitops_pr | PR-native 리메디에이션 패키저 | [src/fdai/delivery/gitops_pr/](../../../src/fdai/delivery/gitops_pr/) |
| chatops | Teams / Slack Adaptive Cards | [src/fdai/delivery/chatops/](../../../src/fdai/delivery/chatops/) |
| notifications | 채널 dispatch와 PagerDuty/ServiceNow incident lifecycle 및 PagerDuty roster adapter | [notifications/](../../../src/fdai/delivery/notifications/), [incident_platform/](../../../src/fdai/delivery/incident_platform/) |
| read_api | 콘솔 read-only HTTP 서피스와 route-owned background, busy-input, skill runtime helper | [src/fdai/delivery/read_api/](../../../src/fdai/delivery/read_api/) |
| provisioning | Terraform / IaC apply 드라이버 | [src/fdai/delivery/provisioning/](../../../src/fdai/delivery/provisioning/) |
| persistence | Durable conversation delivery, execution submission/attempt, LLM metering, report-signal projection, skill-source state, programmatic pipeline receipt/aggregate를 포함한 Postgres + pgvector store | [src/fdai/delivery/persistence/](../../../src/fdai/delivery/persistence/) |
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
| contracts | optional ObjectType lifecycle 기준을 포함한 크로스 패키지 Pydantic 계약 | [src/fdai/shared/contracts/](../../../src/fdai/shared/contracts/) |
| ontology | 도메인 온톨로지 (ObjectType / LinkType / ActionType) | [src/fdai/shared/ontology/](../../../src/fdai/shared/ontology/) |
| providers | `ExecutionBackend`, bounded diagnostic receipt와 분리되고 cache되지 않는 ephemeral typed-command output을 포함한 Provider Protocol, process-local EventBus, bounded SSE, isolated programmatic pipeline runner, [access-scoped conversation search](../interfaces/conversation-search-ko.md), [structured behavior knowledge](../interfaces/behavior-knowledge-ko.md) | [src/fdai/shared/providers/](../../../src/fdai/shared/providers/) |
| config | 설정 로더, 스키마, shared runtime activation flag | [src/fdai/shared/config/](../../../src/fdai/shared/config/) |
| streaming | Kafka / Event Hub 추상화 | [src/fdai/shared/streaming/](../../../src/fdai/shared/streaming/) |
| resilience | 재시도 / circuit-breaker 헬퍼 | [src/fdai/shared/resilience/](../../../src/fdai/shared/resilience/) |
| telemetry | 구조화 로깅 + 메트릭 헬퍼 | [src/fdai/shared/telemetry/](../../../src/fdai/shared/telemetry/) |

## Composition과 카탈로그

| 경로 | 목적 |
|------|------|
| [src/fdai/composition/\_\_init\_\_.py](../../../src/fdai/composition/__init__.py) | 파사드 + `default_container` + `default_container_from_env`. |
| [src/fdai/composition/_helpers.py](../../../src/fdai/composition/_helpers.py) | `Container`, `LlmBindings`, `LlmBindingsUnavailableError`. |
| [src/fdai/composition/wire_llm.py](../../../src/fdai/composition/wire_llm.py) | Azure OpenAI LLM 바인더 (컴포지션 타임 모델 해석). |
| [src/fdai/composition/wire_azure.py](../../../src/fdai/composition/wire_azure.py) | Fork-wire 컨테이너 + `AzureWireOverrides`. |
| [src/fdai/composition/wire_change_feed.py](../../../src/fdai/composition/wire_change_feed.py) | change-feed 팩토리 wiring (Azure DevOps / GitHub 변경 생산자). |
| [src/fdai/composition/wire_metric_provider.py](../../../src/fdai/composition/wire_metric_provider.py) | `MetricProvider` 바인더 (`FDAI_MONITOR_WORKSPACE_ID` 세팅 시 Azure Monitor Logs 자동 바인드); LOC 상한 유지를 위해 `wire_azure`에서 분리 (G-4). |
| [src/fdai/composition/wire_trajectory.py](../../../src/fdai/composition/wire_trajectory.py) | 기본 container에서 feature를 활성화하지 않고 authorization-first source join, dataset metadata, quarantine export, read-only administration을 bind. |
| [src/fdai/composition/wire_execution_backends.py](../../../src/fdai/composition/wire_execution_backends.py) | Server-selected profile을 validate하고 required backend 및 durable ledger를 bind하며 profile은 기본적으로 enable하지 않습니다. |
| [src/fdai/rule_catalog/](../../../src/fdai/rule_catalog/) | `rule-catalog/` 트리 (YAML) 로더. |
| [rule-catalog/](../../../rule-catalog/) | 룰 / 정책 / action-type 카탈로그 (데이터). |

## 개발자 엔트리 포인트와 슬래시 커맨드

로컬 개발, 검증, 세션 인수인계를 일관되게 유지하기 위해 리포에서 제공하는
스크립트와 Copilot 슬래시 커맨드 모음.

| 경로 | 목적 |
|------|------|
| [scripts/verify.sh](../../../scripts/verify.sh) | 단일 로컬 게이트: 기본은 fast text/lint와 clean-checkout 계약을 실행합니다. `--full`은 safety-core coverage와 console/CLI 검증을 추가하고, `--full <path>`는 지정한 pytest 대상만 실행합니다. |
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
