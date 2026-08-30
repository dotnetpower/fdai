---
title: 다중 서비스 저장소 레이아웃
translation_of: multi-service-repository-layout.md
translation_source_sha: 98140983309da9cd2190a962c501a14a06194c9b
translation_revised: 2026-08-31
---
# 다중 서비스 저장소 레이아웃

FDAI는 하나의 개발 저장소에 독립적으로 패키징하고 배포하는 5개 백엔드 서비스와 공유 서비스
계약 SDK를 둡니다. 루트는 도구와 통합 테스트를 조정하지만 모놀리식 런타임 배포판이 아니며,
어떤 서비스도 다른 서비스의 구현을 가져오지 않습니다.

## 패키징 계약

| 표면 | 소유권 계약 |
|------|-------------|
| 백엔드 서비스 5개 | 각 `services/*` 루트가 자체 `pyproject.toml`, 소스 패키지, 테스트, 이미지, 프로세스 신원 및 서비스 migration branch를 소유합니다. |
| Core 암호화 검증 | Core manifest가 배포 소유 Ed25519 관측 증적을 검증하는 `cryptography` 의존성을 소유합니다. 다른 서비스는 Core 구현을 가져오지 않으며 signing seed를 받지 않습니다. |
| 공유 서비스 계약 | `packages/service-contracts/`가 서비스 구현을 가져오지 않는 버전된 wire 형식과 스키마를 소유합니다. |
| 저장소 루트 | 루트 `pyproject.toml`과 `uv.lock`은 개발 도구와 서비스 간 통합을 조정합니다. 루트 pytest 경로는 배포 CLI를 uv workspace에 추가하지 않고도 테스트에서 독립 설치형 CLI를 가져올 수 있으며, 루트는 FDAI 런타임 배포판을 발행하지 않습니다. |
| 서비스 통신 | 서비스는 버전된 계약을 PostgreSQL 소유 변환 결과와 이벤트 버스로 교환합니다. 한 서비스는 다른 서비스의 구현 패키지를 가져오지 않습니다. |

## 다중 서비스 저장소 레이아웃

```text
fdai/
├── services/core-control-plane/src/fdai/ # 독립적으로 패키징된 headless Core 서비스
│   ├── core/                  # headless 컨트롤 플레인 (UI 없음, 클라우드 SDK 직접 import 없음). Domain-group facade는 `pipeline/`, `incident/`, `operator/`, `knowledge/`, `platform/`, `verticals/`를 다루며 direct subsystem import와 grouped import를 모두 호환합니다.
│   │   ├── event_ingest/       # 버스 컨슈머; 이벤트 스키마로 정규화; idempotency key로 dedup; 관련 이벤트를 인시던트로 상관 연결
│   │   ├── trust_router/       # 계산된 신뢰도로 각 이벤트를 T0 | T1 | T2 로 라우팅
│   │   ├── tiers/
│   │   │   ├── t0_deterministic/    # deterministic-engine: policy, checklist, what-if, drift eval
│   │   │   ├── t1_lightweight/      # 임베딩 유사도 및 learned-action 재사용; operational case는 persisted immutable context와 fresh graph, owner, policy, dry-run, safety evidence를 요구
│   │   │   └── t2_reasoning/        # 프론티어 모델 추론과 budgeted proposer failover, durable route selection, sanitized attempt receipt 및 측정된 안정성이 티어 결과를 유지하거나 낮추기만 하는 선택적 self-consistency cascade
│   │   ├── prompts/            # catalog-as-code 프롬프트 컴포저 (`rule-catalog/prompts/` 로드, T2에 공급)
│   │   ├── tools/              # T2 툴 카탈로그 레지스트리 + `ToolExecutor` (shadow-mode 게이팅)
│   │   ├── web_search/         # 최후 수단 웹 검색 seam (`NoOpWebSearchProvider` 기본; 도메인 allowlist + sanitizer)
│   │   ├── browser_evidence/   # 읽기 전용 origin/DNS policy, redaction, immutable artifact, custody, shadow comparison
│   │   ├── operator_memory/    # HIL 승인된 오퍼레이터 메모리를 untrusted `<operator_note>` 데이터로 주입. 두 번째 승인 단계는 시간 범위가 제한되고 재실행에 안전 (항목 id와 기록된 승인자가 같은 정규 형태를 쓰므로 재전달은 중복 대신 거부되고 만료는 종결적)
│   │   ├── learning/           # 동의 기반 off-path turn eligibility, consensus, dedup ledger, 비활성 proposal routing
│   │   ├── conversation_assurance/ # deterministic-first 완료 turn 점수, exact failure attribution, hold-first ontology adequacy review, mixed-family 평가, 범위 제한 이의 제기, 구독별 학습, chat-policy 승격 및 롤백, versioned 50-item hard-cap quality scorecard
│   │   ├── trajectory/         # authorization-first observable trajectory projection, version policy, reviewed aggregate, offline validation, provider-neutral 보존 claim 조정
│   │   ├── case_history/       # canonical revision, strict operational receipt, artifact-first intake, scoped retrieval, backfill 및 retention
│   │   ├── task_worker/        # 격리된 depth-one 읽기 전용 worker: capability 축소, lifecycle, 영구 state, parent synthesis
│   │   ├── background_task/    # 영구 detached read: lease/CAS, atomic completion outbox, replay-idempotent 인계, bounded retry, process-loss, retention purge
│   │   ├── read_investigation/ # Exact-resource VM/network planning, evidence, immutable provider-vs-graph shadow comparison과 그 결정적 교차 출처 충돌 판정, latency policy, owner-scoped direct/stream replay, honest cost usage, SSE heartbeat, stream-close cancellation. Cloud SDK와 execution authority 없음
│   │   ├── briefing/           # report-feed evidence 기반 결정적 opening/scheduled briefing
│   │   ├── scheduler/          # create/pause/resume/edit/run-now/cancel lifecycle, cron dispatch, run history, blueprint, 범위 제한 continuation
│   │   ├── document_ingestion/ # upload lifecycle + split inspect/index worker; Forseti/Saga/Var/Muninn gate, durable stage lease/CAS claim, replay-only gated-state recovery
│   │   ├── working_context/    # 턴당 경계 프롬프트 조립: 불변 selection policy + 필수 validator + shadow evidence/replay + planner/orchestrator fold + summarizer/retriever seam
│   │   ├── operational_context/ # atomic owned-subgraph replacement, time-consistent snapshot, cutoff-bound graph+document evidence bundle과 typed path, provenance, source-freshness receipt, fail-closed truncation
│   │   ├── decision_case/      # protected-objective option, deterministic selection, response closure
│   │   ├── change_lineage/     # 변경 불가능하고 replay-stable한 Change -> assessment -> decision -> action -> outcome join. Execution 또는 promotion authority 없음
│   │   ├── operational_planning/ # hard-constraint eligibility, Pareto pruning, Process planning phase, replay-stable plan identity 및 exact kinetic proposal contract. Execution authority 없음
│   │   ├── operational_learning/ # sealed-case classification, fingerprint/action cohort gate, immutable citation, inert candidate mapping
│   │   ├── rule_semantic_generation/ # agent-facing 빌드/검증 handler Protocol, exact 활성화, 영속 종결 및 발행. 실행 권한 없음
│   │   ├── quality_gate/       # mixed-model 교차 검사, verifier, grounding, 증적 게이트 기반 루브릭 모드; 실패한 fan-out은 sibling을 cancel+drain (T2 방어)
│   │   ├── rca/                # 루트 원인 분석 (T0 deterministic + seam 뒤의 T2 reasoner; grounding-gated)
│   │   ├── risk_gate/          # 통합 authority: 리스크 스코어 + auto vs HIL vs deny; malformed promotion metric 거부 + 7개 안전조건 강제 + 카탈로그 probe id 기반 기록 관측값으로 Axis-E live probe 해석 + 자기완결적 재현을 위한 feature vector, catalog version, 나머지 상한 입력 감사
│   │   ├── execution_authorization/ # 온톨로지 기반 pre-dispatch capability policy, grant lifecycle, replay-stable decision
│   │   ├── rbac/               # Operator API 를 위한 사람 RBAC (5개 롤 매트릭스, resolver, enforcer)
│   │   ├── human_assignment/   # 변경 불가능한 역할/임무 의도, 정규화된 검토 정족수, 리비전 기반 StateStore lifecycle, 결과 영수증
│   │   ├── hil_resume/         # HIL park/resume, no-drop grouping, bounded reminder, CAS 소유 shadow non-response supervision
│   │   ├── executor/           # logical-target lock, 멱등성, dry-run receipt, pre-effect/terminal audit, delivery adapter
│   │   ├── execution_backend/  # profile intersection, durable lifecycle coordination, shadow probe; 판단 authority 없음
│   │   ├── audit/              # append-only 해시 체인 감사 로그 + KPI/메트릭 발행
│   │   ├── notifications/      # notifications matrix 위에 얹은 채널 라우팅 레이어
│   │   ├── detection/          # anomaly/forecast 평가, 변경 불가능한 episode, event-time closure 및 outbox contract
│   │   ├── incident/           # lifecycle + 32-key/1024-char identity, 감사 기반 ontology projection, evidence, severity 및 notice
│   │   ├── slo/                # 워크로드 SLO / burn-rate 평가기 (컨트롤 플레인 SLO 와는 구분)
│   │   ├── runbook/            # 런북 오케스트레이터 (선형 시퀀스 + 실패 시에만 실행되는 순방향 전용 on-failure 브랜치)
│   │   ├── workflow/           # version-pinned WorkflowDefinition + principal WorkflowBinding 컴파일; 승인 플래너 + shadow 오케스트레이터 + 트리거 인덱스 + 이벤트 코디네이터
│   │   ├── python_task/         # generated multi-file PythonTask artifact 및 reviewed programmatic pipeline static validation; task code 를 import 또는 실행하지 않음
│   │   ├── programmatic_pipeline/ # capability-scoped read-only tool loop: immutable contract, broker, receipt, compact result, deterministic benchmark
│   │   ├── postmortem/         # LLM 옵션 postmortem / PIR 드래프트 생성기
│   │   ├── rule_catalog_profiles/  # 프로파일 / 팩 레이어 - 이름 붙은 룰 번들 (`extends` 체인 + overrides)
│   │   ├── measurement/        # 지속 측정 및 confidence/guard gate를 포함한 immutable revision/scenario operational-promotion receipt
│   │   ├── mscp_profile/       # 실행 authority 없는 순수 mscp-operational-v1 provenance, effect verification, cycle guard, runtime-integrity policy 및 never-raising authority ceiling
│   │   ├── deploy_preflight/   # 배포 전 feasibility 프로브 → grounded readiness 리포트
│   │   ├── readiness/          # 운영 handoff + startup, monitored-target 및 rule-discovery activation 계약, fail-closed reducer, evidence expiry 및 authority ceiling
│   │   ├── assurance_twin/     # 읽기 전용 온톨로지 트윈: text-to-query, scalar/graph active-challenger model, 필수 invariant, durable trajectory episode, 결정론적 simulation, off-path outcome closure (실행 또는 promotion 안 함)
│   │   ├── ontology_platform/   # exact release, release-aware direction-shadow 비교, semantic interface, bounded object set, secured purpose/ACL query receipt, 인시던트 감사 근거, shared exact-number property semantics, cluster-scoped network/Pod telemetry verification, immutable diagnostic ledger/result projection, mutation plan, typed function, authenticated reconciliation과 proposal-only terminal outbox, proposal-only SDK generation
│   │   ├── conversation/       # Bragi-owned model-free screen T0, schema-constrained whole-turn semantic frame/query-plan shadowing, principal-manifest verification, intent-graph evidence projection, compatibility intent/tool 조정, grounded narration, per-turn isolation, durable delivery 및 busy-input arbitration
│   │   ├── user_context_projection.py  # principal context / workflow binding metadata만 runtime ontology에 projection
│   │   ├── console_request/    # 오퍼레이터 콘솔 write-direction 재요청 정책 (Scenario B deny-override), 순수 함수 `evaluate_operator_rerequest` 하나
│   │   ├── verticals/          # Resilience / Change Safety / Cost Governance (P3 통합 지점); Resilience는 control-plane recovery plan, record codec, epoch-fenced reducer 및 durable CAS coordinator를 포함하고, 각 vertical 은 sub-package (G-6) 로 자체 orchestrator + 서브모듈 을 가지며 공유 `Vertical` Protocol 은 `base.py`, `VerticalRegistry` seam 도 함께 제공
│   │   ├── control_loop/       # P1 파이프라인: `orchestrator.py` (ControlLoop 조립과 exact property-semantics injection), `_process.py` (순서가 보존된 이벤트 단계), `_fallback.py` (T1/T2), `_execution.py` (거버넌스/리스크/디스패치), `_rca.py` (shadow RCA), `_boundary.py` (감사/알림/stage 어댑터), `models.py` (typed result), `operator_request.py` (authoritative proposal lifecycle), `_helpers.py` (순수 유틸), `stages/` (Stage Protocol 스캐폴드). Semantic metadata는 authority를 높이지 않음
│   │   └── ontology_explorer.py    # 로드된 ObjectType / LinkType 카탈로그를 결정론적 Mermaid 로 렌더
│   ├── shared/                # 크로스컷팅; core/ 로부터 import 금지
│   │   ├── contracts/          # domain별 model + 공유 safety value + versioned isolated-Executor command/receipt schema + registry.py + validation.py
│   │   │   ├── event/          # event/schema.json
│   │   │   ├── action/         # action/schema.json
│   │   │   ├── response-outcome/ # expected-versus-observed action effect outcome
│   │   │   ├── rule/           # rule/schema.json
│   │   │   ├── ontology/       # object/link/action 스키마; ObjectType은 lifecycle 기준 + provenance 선언 가능
│   │   │   └── workflow/       # workflow/schema.json (프로세스 자동화 카탈로그)
│   │   ├── ontology/           # 런타임 온톨로지 헬퍼 (ACL, 감사 purposes, purpose taxonomy)
│   │   ├── providers/          # OperatingModelProvider, 하위 호환 Distiller conformance 및 action-bound control-plane recovery approval verification을 포함한 CSP-중립 클라우드 provider interface (adapter가 구현)
│   │   │                       #   event_bus.py, secret_provider.py, state_store.py, execution_backend.py,
│   │   │                       #   workload_identity.py, inventory.py, log_query.py, trace_query.py, incident_platform.py, behavior_knowledge.py, programmatic_pipeline.py + LLM / 채널 / RBAC seam
│   │   │                       # `providers/local/` = process-local transport adapter, bounded document format adapter(immutable ceiling `document_limits.py`, Markdown/SGML `document_text.py`, OOXML `document_structure.py`, pypdf/OCR `document_pdf.py`) 및 명시적 offline helper;
│   │   │                       # `providers/testing/` = 테스트 스위트 전반에서 쓰이는 인-메모리 페이크 (prod 에서는 바인딩 안 됨)
│   │   ├── streaming/          # `SseBroadcaster` + `StagePublisher`: EventBus 토픽을 SSE 채널로 릴레이
│   │   ├── telemetry/          # 구조화 로깅, 트레이싱, 메트릭 헬퍼
│   │   └── config/             # config 스키마 + 시작 시 검증 (fail-fast)
│   ├── delivery/              # 액션 딜리버리 어댑터 (공유 인터페이스 뒤)
│   │   ├── agent_introspection_bus.py # shared EventBus를 사용하는 bounded cross-process Bragi request/reply; executor identity 없음
│   │   ├── gitops_pr/          # remediation-pr 어댑터: GitHub App / Azure DevOps, Checks API
│   │   ├── channels/           # 순수 Teams/Slack 표현과 인증된 범위 제한 A3 전송; executor identity 없음
│   │   ├── chatops/            # 채널 어댑터 (Teams / Slack / email / webhook / pager / SMS)
│   │   ├── notifications/      # 채널별 sender; sibling `incident_platform/`은 PagerDuty/ServiceNow lifecycle 및 PagerDuty roster adapter 제공
│   │   ├── persistence/        # Forecast episode/outbox, relational case-history backfill 및 원자적 background-task 완료 감사 표시를 포함한 Postgres / pgvector store
│   │   ├── operating_model/    # bounded JSON deployment operating-model adapter; startup-only, all-before-write
│   │   ├── runtime_settings.py  # allowlist된 env default + revisioned StateStore override; executor identity 또는 promotion authority 없음
│   │   ├── behavior_knowledge/ # in-memory hybrid behavior index, tracked-source freshness, built-in behavior seed
│   │   ├── catalog_search/     # candidate-only concrete semantic index, full/incremental Rule/ontology declaration/eligible deployment-object generation, immutable staged-generation validation snapshot, independent validation, atomic activation, stale detection 및 rollback. Durable pgvector binding은 delivery work로 남습니다.
│   │   ├── pgvector/           # persistent document 및 behavior vector index
│   │   ├── azure/              # bounded log/metric/App Insights trace와 promoted inventory 기반 strict operational-learning evidence를 포함한 Azure 전용 adapter
│   │   │                       #   `case_history_artifacts.py`는 workload identity로 private Blob에 content-addressed case revision 저장
│   │   │                       #   `vm_task.py` 는 Managed Run Command 사용; `container_apps_job_backend.py` 는 pinned Job template만 시작; `llm/python_task_author.py` 는 inert draft 생성
│   │   ├── vm_task/            # planning-only read adapter + ontology ToolExecutor bridge; cloud SDK import 없음
│   │   ├── execution_backend/  # 기존 sandbox authority 위의 bubblewrap 및 VM-task lifecycle adapter
│   │   ├── programmatic_pipeline/ # local isolated child runner; Azure strict submission adapter는 delivery/azure 아래 유지
│   │   ├── browser/             # 선택적 isolated async Playwright evidence capture; GET/HEAD 전용, page handle 없음
│   │   ├── trajectory/         # deterministic JSONL streaming export, quarantine, atomic partial-file cleanup
│   │   ├── kubernetes/         # evaluation/runtime evidence가 공유하는 exact quantity, cluster-scoped topology, UID-grounded owner, exact-release diagnostic function 및 hold-only finding
│   │   ├── chaos/              # `Chaos` runbook 단계가 enforce로 갈 때 쓰는 라이브 카오스 주입 어댑터: `live_injectors.py` (CSP-중립 프리미티브 fan-out) + `chaos_mesh.py` (Chaos Mesh CRD) + `mysql_load.py` (MySQL 벤치마크 부하)
│   │   ├── remediation/        # 직접 API 리메디에이션용 구체 `DirectApiExecutor` (`live_direct_api.py`); Protocol 은 `shared/providers/`에 있음
│   │   ├── operator_api/           # 얇은 ASGI - `main.py`가 principal 범위 complete-history 및 read-only knowledge-context 조립과 IAM 옆의 Owner 전용 관찰 assignment case를 포함한 route module을 조립. GET route는 bounded state를 projection하고 POST command route는 governed record 또는 typed proposal을 제출하며 privileged executor 또는 human-access provisioner를 직접 호출하지 않음
│   │   ├── ingestion_gateway/  # 독립 public upload API + internal durable worker process; scoped ref, deletion, optional handover governance
│   │   ├── provisioning/       # surface-A Genesis 부트스트랩: 순수 `terraform_bridge.py` (terraform `-json` → `provision.*`) + `serve.py` harness (`aiter_json_lines` + `pump_provision_events`, I/O 주입, subprocess 없음)
│   │   └── scheduler_tick_cli.py  # cron / Container Apps Job에서 스케줄러 tick을 구동하는 독립 엔트리 포인트
│   ├── rule_catalog/          # rule-catalog 파이프라인 코드
│   │   ├── schema/             # Rule, Best Practice, governance, ontology 및 semantic retrieval schema + validation
│   │   ├── sources/            # 소스별 컬렉터 (WAF, CIS, OPA, IaC scanners, ...)
│   │   ├── pipeline/           # watch -> collect -> shadow/regression; distill은 DocumentEnvelope provenance bridge, cross-format equivalence 및 review-only ontology gate 추가
│   │   └── codegen/            # 저작 헬퍼 (`new_action_type`, `new_object_type`) - 스캐폴드 생성만, 라이브 카탈로그 변경 안 함
│   ├── agents/                # 판테온 런타임 - 15개 agent, typed topic, 선택적 exact-proposal Verdict binding, v2 conversation charter 및 bounded T1/T2 deliberation; [agent-pantheon-ko.md](../agents/agent-pantheon-ko.md) 참조
│   ├── composition/           # composition root 패키지 (G-3, 트래커 #14): `__init__.py` facade + `_helpers.py` Container/LlmBindings + `resolved_models.py` artifact loading/capability helper + request-role executor를 사용하는 exact-release semantic query assembly와 영속 비교 저장소를 직접 소유하는 context-selection shadow 실행기를 연결하는 `wire_context_selection.py`를 포함한 focused `wire_*` binder
│   ├── runtime/               # reviewed alias-free metric-semantic catalog loading, exact Rule 세대 문서 스냅샷과 replay가 동일한 reconciliation, versioned isolated Executor shadow/effect handling, stable-offset remote client, EventBus/DLQ/health supervision, production entry point, reversible authority probe, operating-model 및 diagnostic-catalog startup projection/status, durable T2 recovery observation/backfill, Thor/Vidar 실행과 rollback을 사용하는 StateStore-backed proposer route selection, deadline-bound 영속 변환 결과 재생을 포함한 semantic runtime availability/readiness binding, transport/identity binding, startup readiness, worker gating 및 Norns post-turn review를 포함한 headless lifecycle/composition
│   └── __main__.py            # 진입점 (P1 컨트롤 루프 기동)
├── services/core-control-plane/{src/fdai_core_service,tests}/ # Core entry point와 test
├── services/{operator-service,document-ingestion-api,document-processing-worker,isolated-executor}/와 packages/service-contracts/ # 독립 package, shared SDK, test, 타입이 고정된 semantic JSONB 영속성 및 projection row에 의존하지 않는 process-owned semantic bridge 상태
├── evaluation-sdk/            # 휴면 상태의 독립 패키지 evaluation 계약과 실행기; FDAI 런타임 의존성 밖에서 보존
├── benchmarks/                # 휴면 외부 실행 장치 driver 패키지와 별도의 명시적 CyberGym shadow 실행기
├── eval/golden-dataset/       # 활성 이중 언어 의미 회귀 corpus와 온톨로지 탐색 oracle; 캠페인 연결은 남아 있음
├── extensions/                # 독립적으로 package된 optional capability; FDAI wheel에 포함되지 않음
│   └── code-assurance/         # read-only bounded GitHub PR code/security review + governed skill asset
├── rule-catalog/              # catalog-as-code 데이터 (YAML) - Python 아님; 파이프라인은 services/core-control-plane/src/fdai/rule_catalog/ 에
│   ├── schema/                 # JSON Schema 정의 (데이터)
│   ├── vocabulary/             # canonical CSP-중립 어휘: resource-types.yaml, object-types/, link-types/, interface-types/, interface-implementations/
│   ├── action-types/           # 업스트림 온톨로지 ActionType 인스턴스 (shadow-default, promotion_gate 필수)
│   ├── action-types-custom/    # 포크 전용 ActionType 추가 (업스트림 CI 에서 deny-list)
│   ├── action-types-overrides/ # 업스트림 ActionType 의 스코프 오버라이드 (≤ resource-group 스코프)
│   ├── profiles/               # 이름 붙은 룰 팩 (업스트림)
│   ├── profiles-overrides/     # profiles 의 포크 오버레이
│   ├── best-practices/         # typed evidence requirement가 있는 framework checklist control
│   ├── rule-sets/              # atomic rule을 버전 고정한 governance initiative
│   ├── prompts/                # catalog-as-code 프롬프트 조각 (태스크 팩, 툴, 페르소나)
│   ├── remediation/            # remediation-plan 아티팩트
│   ├── operator-console/       # `SystemConsoleTool` descriptor 번들
│   ├── probes/                 # deploy-preflight feasibility 프로브 descriptor
│   ├── catalog/                # 정규화된 룰 (promotion 후, catalog-of-record)
│   ├── collected/              # 정규화 전 원본 업스트림 소스 스냅샷
│   ├── exemptions/             # 시간-바운드 감사된 예외 아티팩트
│   ├── sources/                # 소스별 룰 스냅샷 + provenance
│   ├── llm-registry.yaml       # capability 별 LLM 바인딩 레지스트리 (데이터, composition 시점에 해석)
│   └── risk-classification.yaml # authoritative first-match 리스크 분류 테이블 (risk-classification-ko.md 참조)
├── policies/                  # T0와 verifier가 소비하는 OPA/Rego policy-as-code
├── infra/                     # IaC: Terraform (HCL); 엔트리 커맨드 `terraform apply`
│   ├── modules/
│   │   ├── resource-group/          # rg-fdai; deploy-and-onboard-ko.md 에 따라 CAF 명명
│   │   ├── identity/                # executor 를 위한 user-assigned Managed Identity
│   │   ├── compute/                 # runtime seam - 대안은 형제 폴더에
│   │   │   └── container-apps/      # 기본 (Consumption + KEDA)
│   │   ├── isolated-executor/       # opt-in internal shadow Container App; 전용 transport identity, effect role 없음
│   │   ├── container-registry/      # compute 이미지용 ACR
│   │   ├── state-store/             # audit + KPI + pgvector
│   │   │   └── postgres-flex/       # 기본
│   │   ├── event-bus/               # Kafka 와이어
│   │   │   └── event-hubs-kafka/    # 기본 (Event Hubs, :9093)
│   │   ├── secret-store/            # env + Key Vault reference 브릿지
│   │   │   └── key-vault/           # 기본
│   │   ├── observability/           # Log Analytics + 여기 바인딩된 App Insights
│   │   │   └── log-analytics/       # 기본
│   │   ├── llm/                     # 배포자 스코프 LLM 프로비저닝 (dev-and-deploy parity 계약)
│   │   │   └── azure-openai/        # 기본 Azure OpenAI 디플로이먼트 세트
│   │   ├── measurement-runners/     # 자동 regression + pattern-growth 러너용 Container Apps Jobs
│   │   ├── vm-task-host/             # custom Linux/GPU VM용 cloud-init profile
│   │   ├── vm-task-rbac/             # target-VM-scoped Managed Run Command RBAC
│   │   ├── preflight-toggles/       # preflight blocker 를 Terraform 토글로 매핑하는 피처 플래그 표면
│   │   └── console/                 # 읽기 전용 SPA 를 호스팅하는 Static Web App
│   │       └── static-web-app/      # 기본
│   ├── local/                       # 로컬 개발용 IaC (docker-compose, testcontainers 배선; Azure 에 apply 안 함)
│   └── envs/                        # 환경별 tfvars (git-ignored; 커밋 금지)
│       ├── dev/
│       ├── staging/
│       └── prod/
├── console/                   # 얇은 SPA (Vite + Preact) - 운영자 보기, 소유자 범위 background-task 점검, 제한된 governed command, 로컬 표시 설정, 관찰 전용 IAM Assignments
│   ├── src/                    # 셸, 패널 레지스트리, GET 전용 클라이언트, 라우트, 브라우저 로컬 환경 설정
│   ├── index.html              # Vite 진입점
│   ├── package.json            # 의존: preact, @azure/msal-browser
│   └── vite.config.ts          # 빌드 → console/dist/ (git-ignored)
├── cli/                       # operator-console CLI (Ink) - 뷰모델 하나, 렌더러 여럿
│   ├── src/view-model/         # 표현 중립 브리핑 계약 + 블록 IR + 빌더
│   ├── src/renderers/          # ink (터미널) / text / slack (Block Kit) / teams (Adaptive Card)
│   ├── src/cli.tsx             # 진입점: 브리핑을 한 번 빌드하고 --surface 별로 렌더
│   └── package.json            # 의존: ink, react (tsx로 실행, 빌드 단계 없음)
├── site/                      # Astro / Starlight 문서 사이트 (docs/**/*.md 를 i18n + 검색으로 렌더)
├── ui/                        # (미래) 정적 UI 킷 (Calm Slate 테마) - placeholder
├── tests/integration/         # cross-service compatibility와 repository check만 유지
├── docs/roadmap/              # 이 로드맵과 설계 문서
├── pyproject.toml             # virtual uv workspace root (`package = false`)
└── .github/                   # instructions/ 와 workflows/ (CI: lint, secret-scan, coverage)
```

런타임 초기화는 semantic-turn 준비 상태를 `bootstrap_lifecycle.py`에, exact Rule 세대 스냅샷과 영속 요청을 `rule_generation_documents.py`에, 버티컬 워크로드 신원을 `bootstrap_bindings.py`에 위임합니다. 이렇게 해서 범위가 제한된 프로바이더 구성과,
테스트와 포크가 사용하는 주입 가능한 identity-builder 경계를 함께 보존합니다. 리소스 상태 조립은 권위 있는 Heimdall 읽기 뒤에 shared 단계 topic의 no-authority 게시자도 연결합니다.
범위가 제한된 latency 프로파일은 hash된 correlation만 유지해 영속 활동과 실제 운영 활동이 같은 identity를 사용하게 합니다. 질문 텍스트, 리소스 식별자, 실행기 기능 또는 추가 latency-audit 필드는 내보내지 않으며 broker 실패가 답을 다시 쓰지 않습니다.

> 디렉터리 이름은 [language.instructions.md](../../../.github/instructions/language.instructions.md)의
> 정본 어휘를 따릅니다: `trust-router`, `deterministic-engine`, `rule-catalog`, `risk-gate`,
> `remediation-pr`, `shadow-mode`, `HIL`.
> 디스크상의 식별자는 `snake_case`를 쓰며, 각 패키지가 자신의 테스트를 소유하고 서비스 간 및
> 저장소 전역 검사만 `tests/integration/`에 남습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 모듈 경계, 확장 seam 및 조립 | [프로젝트 구조](project-structure-ko.md) |
| 서비스 추출 근거 및 폐기된 호환 경로 | [서비스 분해 실행 계획](service-decomposition-execution-plan-ko.md) |
| 서비스 승격 및 데이터 소유권 | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/architecture/multi-service-repository-layout.md) |
