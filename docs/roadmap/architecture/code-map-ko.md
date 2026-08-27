---
title: 코드 맵
translation_of: code-map.md
translation_source_sha: 45db6008691945f6f88f14d466510b452831c271
translation_revised: 2026-08-27
---
# 코드 맵

이 페이지는 각 FDAI 런타임 서비스와 shared 패키지를 물리 출처, 테스트 및 소유 design에
연결합니다. 폐기된 최상위 애플리케이션 트리에 의존하지 않고 현재 service-owned 구현을
찾을 때 사용합니다.

> **범위:** 이 지도는 검증된 로컬 IS-08 저장소 소유권과 IS-07 로컬 업그레이드 및 롤백
> 증명을 설명합니다. 지연된 원격 검증은 IS-09가 소유합니다.

## 설계 개요

- **서비스 분포 5개:** 각 런타임 프로세스는 `services/` 아래 패키지 하나를 소유합니다.
- **Shared SDK 1개:** `packages/service-contracts/`는 서비스 구현 없이 서비스 간
  계약을 포함합니다.
- **Service-owned 테스트:** 단위 및 컴포넌트 테스트는 소유 서비스 또는 패키지 옆에 있습니다.
- **가상 루트:** 루트 `pyproject.toml`은 `package = false`이며 uv workspace를 조정합니다.
- **Integration-only 루트 테스트:** `tests/integration/`은 서비스 간 호환성, 토폴로지 및
  저장소 검사를 소유합니다.

> **인덱스 계약:** 이 페이지는 탐색 전용입니다. 현재 구현 상태와 이력은 연결된 소유
> 문서에서 관리합니다. 기존 혼합 목적 원장은
> [보관된 코드 맵 구현 원장](../../roadmap-implementation/architecture/code-map.md)에 보존합니다.

> **Kubernetes 복구 계약:** durable lifecycle 조회에는 fresh cursor, exact UID scope 및
> sentinel 행을 사용하는 truncation 검사가 필요합니다. lifecycle로 분류된 종료 행만
> exact-target 교체 축약기에 전달되며 incomplete lifecycle 근거는 recovered 상태를 유지할 수
> 없습니다.

## 물리 서비스 소유권

| 소유자 | 출처 | 테스트 | 분포 |
|--------|--------|------|--------------|
| Core 컨트롤 플레인 | [fdai](../../../services/core-control-plane/src/fdai/)와 [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core 테스트](../../../services/core-control-plane/tests/) | `fdai-core-control-plane` |
| Operator 서비스 | [fdai_operator_service](../../../services/operator-service/src/fdai_operator_service/) | [Operator 테스트](../../../services/operator-service/tests/) | `fdai-operator-service` |
| 문서 인제스트 API | [fdai_ingestion_api_service](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) | [인제스트 API 테스트](../../../services/document-ingestion-api/tests/) | `fdai-document-ingestion-api` |
| 문서 처리 워커 | [fdai_document_worker_service](../../../services/document-processing-worker/src/fdai_document_worker_service/) | [워커 테스트](../../../services/document-processing-worker/tests/) | `fdai-document-processing-worker` |
| Isolated 실행기 | [fdai_executor_service](../../../services/isolated-executor/src/fdai_executor_service/) | [실행기 테스트](../../../services/isolated-executor/tests/) | `fdai-isolated-executor-service` |
| 서비스 계약 | [fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) | [계약 테스트](../../../packages/service-contracts/tests/) | `fdai-service-contracts` |
| 서비스 간 통합 | 해당 없음 | [루트 통합 테스트](../../../tests/integration/) | 가상 루트 only |

## Core 컨트롤 플레인 지도

Core 분포는 전체 `fdai` 이름 공간을 유지합니다. 내부 모듈 경계는 물리 이동으로
변경되지 않습니다.

의미 대화 계획은 `semantic_planning.py`, `semantic_planning_cascade.py`,
`semantic_planning_frame.py`를 호환성 facade로 유지합니다. 집중 sibling 모듈은 공개 import,
결정론적 gate 순서 및 읽기 전용 권한을 보존하면서 frame 검사, plan dispatch, 판단, 검증, frame
생성, facet, 근거별 조사 정규화 및 조회를 소유합니다.
semantic-routing 기준선은 각 어휘 판단 소유자를 기록하고 competency fixture는 운영 준비 완료를
주장하지 않으면서 현재 구조 release와 Reader 매니페스트를 고정합니다.

| 영역 | Responsibility | 출처 | 테스트 |
|------|----------------|--------|------|
| Kubernetes Resource 이벤트 이력 | 출처에 근거한 정확한 대상 계획, 실패 시 차단하는 정확한 identity 개수 검사, 증적에 결속된 정확한 child UID 필터 또는 명시적인 정확한 클러스터 범위의 제한된 Kubernetes Event 읽기, 정규화한 이벤트 시각, 내용 기반 근거, 제한 사항을 보여주는 이중 언어 답변, 독립적인 Azure/Kubernetes 기능군 라우팅, 명시적인 불완전 결과, 원시 메시지와 원인, 변경 또는 실행 권한 없음 | [의미 플래너](../../../services/core-control-plane/src/fdai/core/conversation/semantic_resource_event_planning.py), [FunctionType](../../../services/core-control-plane/src/fdai/core/ontology_platform/resource_event_queries.py), [Kubernetes 읽기 경로](../../../services/core-control-plane/src/fdai/delivery/kubernetes_resource_event_history.py), [기능군 라우터](../../../services/core-control-plane/src/fdai/delivery/resource_event_history.py), [런타임 연결](../../../services/core-control-plane/src/fdai/runtime/resource_event_providers.py), [답변 변환 결과](../../../services/core-control-plane/src/fdai_core_service/semantic_turn_processor.py) | [의미 계획 테스트](../../../services/core-control-plane/tests/conversation/test_semantic_planning.py), [Kubernetes 어댑터 테스트](../../../services/core-control-plane/tests/delivery/test_kubernetes_resource_event_history.py), [라우터 테스트](../../../services/core-control-plane/tests/delivery/test_resource_event_history.py), [FunctionType 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_resource_event_queries.py), [답변 테스트](../../../services/core-control-plane/tests/test_semantic_turn_processor.py), [런타임 테스트](../../../services/core-control-plane/tests/runtime/test_resource_health_provider.py) |
| 컨트롤 루프와 decisioning | Event 정규화, 계층 라우팅, 정확한 Rego allow/deny 평가 증적, quality, risk, 승인, 실행 coordination, 복구 및 감사 | [코어](../../../services/core-control-plane/src/fdai/core/) | [코어 테스트](../../../services/core-control-plane/tests/core/) |
| 컨트롤 플레인 지역 복구 shadow 경로 | 실제 공급자를 변경하지 않고 예상 epoch 차단, 검증된 단일 writer 상태, 범위가 제한된 근거 증적, 다음 작업 전 중단 동작을 적용하는 공급자 중립적인 순서 기반 failover 및 failback 예행 연습 | [shadow 복구](../../../services/core-control-plane/src/fdai/core/verticals/resilience/shadow_recovery.py), [복구 공급자 계약](../../../services/core-control-plane/src/fdai/shared/providers/control_plane_recovery.py) | [shadow 복구 테스트](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan_shadow.py), [복구 계획 테스트](../../../services/core-control-plane/tests/core/verticals/test_recovery_plan.py), [복구 조정기 테스트](../../../services/core-control-plane/tests/core/verticals/test_recovery_coordinator.py) |
| 환각 루브릭 승격 | 짝지은 불변 기준선/처리군 근거, 신뢰도를 고려한 준비 판정, 독립 검토 결속, 엄격한 매니페스트 검증 및 승격 권한이 없는 ActionType별 실패 시 차단 루브릭 모드 해석 | [루브릭 승격 core](../../../services/core-control-plane/src/fdai/core/quality_gate/promotion.py) 및 [매니페스트 어댑터](../../../services/core-control-plane/src/fdai/delivery/measurement/rubric_promotion_evidence.py) | [루브릭 승격 테스트](../../../services/core-control-plane/tests/core/quality_gate/test_rubric_promotion.py), [어댑터 테스트](../../../services/core-control-plane/tests/delivery/test_rubric_promotion_evidence.py) 및 [조립 테스트](../../../services/core-control-plane/tests/composition/test_rubric_promotion_binding.py) |
| 실행 권한 부여 | 프로바이더 중립적인 요구 사항 결과, 비어 있지 않은 결정 집합의 최소 권한 축소, 정규 요청 및 인벤토리 연결, 모호한 ID 또는 연결되지 않은 권한 부여 제안 거부 | [execution_authorization](../../../services/core-control-plane/src/fdai/core/execution_authorization/) | [실행 권한 부여 테스트](../../../services/core-control-plane/tests/core/execution_authorization/) |
| 온톨로지 안전성 platform | 카탈로그에서 로드한 Interface 및 FunctionType 선언을 포함하는 exact 의미 release, release-aware 조회 profile 및 함수 등록, principal 범위로 한정된 매니페스트, 검증된 Resource와 ResourceType 분류, 범용/temporal 조회 algebra, bitemporal 토폴로지/차이, 범위가 제한된 blast-radius 차이, authoritative inventory rebuild pointer 및 서로 다른 검토자와 회귀 증적에 결속된 catalog PR 제안을 포함하는 immutable direction-generation shadow comparison, 검토된 메트릭 개념, topology-aware causal 결합, Resource별 최신성 메타데이터가 완전한 그래프 읽기, 다이제스트로 차단된 지속형 운영 모델 replay 복구, 프로덕션 쓰기 권한이 없는 근거 기반 읽기 및 copy-on-write scenario branch, 별도의 planner-function 및 operational-plan lineage와 안전하게 닫히도록 문서화된 인자, 근거, 대상 및 효과 검증 계약이 있는 변경 계획, compact typed effect-reconciliation event, 인증된 독립 observer binding 및 lease-fenced 영속 terminal outbox 전달 | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [온톨로지 platform 테스트](../../../services/core-control-plane/tests/core/ontology_platform/) |
| 온톨로지 구조 모델 | 정확한 ResourceType 아이덴티티, 검토된 ResourceClass 집계, 검토된 Property 의미 및 capability Interface, 직접 링크 역할과 의미 특성, 탐색형 관계 탐색, 순서가 있는 형식화된 경로, 제한을 보존하는 그래프 표현 | [소유 설계](ontology-structural-model-ko.md), [온톨로지 계약](../../../services/core-control-plane/src/fdai/shared/contracts/models/ontology.py), [카탈로그 변환 결과](../../../services/core-control-plane/src/fdai/core/ontology_platform/catalog_projection.py), [쿼리 platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [온톨로지 platform 테스트](../../../services/core-control-plane/tests/core/ontology_platform/), [카탈로그 테스트](../../../services/core-control-plane/tests/rule_catalog/), [Console 그래프 테스트](../../../console/src/components/ontology-graph.model.test.ts) |
| 운영 인스턴스 근거 adapter | 인증된 exact-endpoint runtime-call observation, principal-safe PostgreSQL role 근거, 명시적 unavailable source 상태, action authority 없이 inventory single writer를 통과하는 검증된 pre-promotion 보강 | [runtime-call telemetry](../../../services/core-control-plane/src/fdai/core/ontology_platform/runtime_call_telemetry.py), [PostgreSQL role 근거](../../../services/core-control-plane/src/fdai/core/ontology_platform/postgres_role_evidence.py), [inventory binding](../../../services/core-control-plane/src/fdai/delivery/runtime_call_inventory.py) | [runtime-call telemetry 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_runtime_call_telemetry.py), [PostgreSQL role 근거 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_postgres_role_evidence.py), [inventory binding 테스트](../../../services/core-control-plane/tests/delivery/test_runtime_call_inventory.py) |
| 지속형 운영 인스턴스 그래프 | 검증된 source policy, adaptive collection, event/delta/snapshot convergence, 로컬/배포 analyzer 일정 관리 동등성, principal-safe health, typed semantic rollup, content-addressed archive lifecycle, 5개 결과를 갖는 graph refresh 결정, 관계를 진술할 수 있는 스냅샷만 게이팅하는 관계 커버리지, 안전한 부분 live-evidence write-through, action authority가 없는 typed 대표 competency | [소유 설계](continuous-operational-instance-graph-ko.md), [감사 계약](../../../config/continuous-operational-instance-graph-audit.json), [analyzer CLI](../../../services/core-control-plane/src/fdai/delivery/analyzer_tick_cli.py), [로컬 analyzer 작업](../../../scripts/deployment/local/run-analyzer-loop.sh), [rollup core](../../../services/core-control-plane/src/fdai/core/ontology_platform/semantic_rollup.py), [archive core](../../../services/core-control-plane/src/fdai/core/ontology_platform/archive_manifest.py), [graph refresh](../../../services/core-control-plane/src/fdai/core/ontology_platform/graph_evidence_refresh.py), [투영 커버리지](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_ontology.py), [competency](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_instance_competency.py), [inventory adapter](../../../services/core-control-plane/src/fdai/delivery/inventory_rollup.py), [live evidence](../../../services/core-control-plane/src/fdai/delivery/inventory_live_evidence.py), [archive persistence](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_operational_archive.py), [Core migration](../../../service-migrations/branches/core-control-plane/versions/20260822_core_operational_archive.py) | [analyzer 테스트](../../../services/core-control-plane/tests/delivery/test_analyzer_tick_cli_topic.py), [감사 테스트](../../../tests/integration/scripts/test_continuous_operational_instance_graph_audit.py), [refresh 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_graph_evidence_refresh.py), [competency 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_operational_instance_competency.py), [live-evidence 테스트](../../../services/core-control-plane/tests/delivery/test_inventory_live_evidence.py), [rollup 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_semantic_rollup.py), [archive 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_archive_manifest.py), [purge 테스트](../../../services/core-control-plane/tests/delivery/test_operational_archive_purge.py), [cross-lane 테스트](../../../tests/integration/test_operational_instance_retention.py) |
| 정확한 Pod 진단 근거 | 하나의 정확한 Pod UID를 변환된 종료 상태, 수명 주기 이벤트, 범위가 제한되고 로그 본문을 보존하지 않는 AppTraces, AppExceptions 및 ContainerLogV2 근거와 결합하며 원인 또는 실행 권한을 부여하지 않습니다. | [진단 조회](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_diagnosis_queries.py)와 [로그 어댑터](../../../services/core-control-plane/src/fdai/delivery/kubernetes_pod_log_evidence.py) | [진단 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_kubernetes_pod_diagnosis_queries.py)와 [로그 어댑터 테스트](../../../services/core-control-plane/tests/delivery/test_kubernetes_pod_log_evidence.py) |
| Kubernetes 워크로드 근거 | 허용 목록에 있는 Deployment 및 Pod 관측, 정확한 대상 선택, rollout 및 Pod 소유자 방향에서 모두 발급된 2단계 소유권 근거, 검토된 불변 Pod 재시작 이력 메트릭, 근본 원인 또는 실행 권한을 주장하지 않는 최신성 및 충돌 인식 rollout, 같은 UID 복구 및 서로 다른 UID 교체 순수 축약기. 이제 영속 재개 가능 수명 주기 collector가 cluster/namespace/UID/reason 타입 근거를 atomic cursor-plus-append-only store 뒤에서 보존하고, retained 행을 기존 Resource-event query dependency와 공통 local/deployed analyzer schedule로 전달하며 정확한 old UID에 해당하는 종료 행만 lifecycle 기반 교체 축약기가 선택합니다. 누락된 과거 관측은 추론하지 않습니다. | [Kubernetes 인벤토리 source](../../../services/core-control-plane/src/fdai/delivery/kubernetes_api_inventory.py), [rollout 조회](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_rollout_queries.py), [Pod 복구 조회](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_recovery_queries.py), [Pod 교체 축약기](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_pod_replacement_evidence.py), [의미 플래너](../../../services/core-control-plane/src/fdai/core/conversation/), [durable Resource-event adapter](../../../services/core-control-plane/src/fdai/delivery/durable_kubernetes_resource_event_history.py), [수명 주기 observation 모델](../../../services/core-control-plane/src/fdai/core/ontology_platform/kubernetes_lifecycle_observation.py), [수명 주기 source](../../../services/core-control-plane/src/fdai/delivery/kubernetes_lifecycle_source.py), [수명 주기 collector](../../../services/core-control-plane/src/fdai/delivery/kubernetes_lifecycle_collector.py), [수명 주기 Postgres store](../../../services/core-control-plane/src/fdai/delivery/persistence/postgres_kubernetes_lifecycle.py), [수명 주기 Core migration](../../../service-migrations/branches/core-control-plane/versions/20260828_core_kubernetes_lifecycle.py), [수명 주기 collector CLI](../../../services/core-control-plane/src/fdai/delivery/kubernetes_lifecycle_collector_cli.py) | [인벤토리 source 테스트](../../../services/core-control-plane/tests/delivery/test_kubernetes_api_inventory.py), [워크로드 축약기 테스트](../../../services/core-control-plane/tests/core/ontology_platform/), [플래너 테스트](../../../services/core-control-plane/tests/conversation/), [조립 테스트](../../../services/core-control-plane/tests/composition/), [durable adapter 테스트](../../../services/core-control-plane/tests/delivery/test_durable_kubernetes_resource_event_history.py), [수명 주기 observation 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_kubernetes_lifecycle_observation.py), [수명 주기 source 테스트](../../../services/core-control-plane/tests/delivery/test_kubernetes_lifecycle_source.py), [수명 주기 collector 테스트](../../../services/core-control-plane/tests/delivery/test_kubernetes_lifecycle_collector.py), [수명 주기 Postgres store 테스트](../../../services/core-control-plane/tests/persistence/test_postgres_kubernetes_lifecycle.py), [수명 주기 CLI 테스트](../../../services/core-control-plane/tests/delivery/test_kubernetes_lifecycle_collector_cli.py) |
| 온톨로지 선언 워크벤치 변환 결과 | Exact-release 선언 상세, 토폴로지 기반 종속 항목, 정제된 ObjectType 근거 상태, 보존 release 호환성, 역할/용도 redaction 및 변경 권한이 없는 결정론적 개정 번호 | [ontology_declaration_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_declaration_projection.py), [ontology_dependents_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_dependents_projection.py), [ontology_evidence_health_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_evidence_health_projection.py), [ontology_release_diff_projection.py](../../../services/core-control-plane/src/fdai/delivery/ontology_release_diff_projection.py) | [delivery 변환 결과 테스트](../../../services/core-control-plane/tests/delivery/), [catalog materializer 테스트](../../../tests/integration/scripts/test_materialize_authoritative_catalogs.py) |
| OI-12 운영 인증 | Exact-release 7축 집계 snapshot, 읽기 전용 PostgreSQL 수집, signed storage growth, 명시적인 unavailable 근거, 범위가 제한된 로컬 rollup/archive/restore exercise 및 권한이 없는 증적 발행 | [인증 계약](../../../services/core-control-plane/src/fdai/core/ontology_platform/operational_instance_certification.py), [인증 reducer](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification.py), [PostgreSQL source](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_postgres.py), [archive exercise](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_archive.py), [인증 CLI](../../../services/core-control-plane/src/fdai/delivery/operational_instance_certification_cli.py) | [계약 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_operational_instance_certification.py), [delivery 테스트](../../../services/core-control-plane/tests/delivery/test_operational_instance_certification.py), [archive exercise 테스트](../../../services/core-control-plane/tests/delivery/test_operational_instance_certification_archive.py) |
| 의미 대화 계획 수립 | Whole-turn 스키마 제안, 후속 프레임 제안보다 먼저 적용하는 canonical typed judgment, 서버가 소유한 프레임/계획 신원, principal-manifest 검증, 비동기 검증된 실행, 근거가 필요 없는 타입 지정 직접 응답, 전체 최종 처리 결과, 결정론적 의도 그래프, exact-command 호환성 전환, 선언 기반의 범위가 제한된 질문 집합 생성, 인식 상태 완결성 release 증적, 정확한 서비스-Resource 범위와 실패 시 차단되는 Resource 상태 근거를 사용하는 타입 기반 네트워크 대 애플리케이션 지연 조사, 발화가 이미 지목한 대상을 되묻지 않도록 출력 계열과 무관하게 동작하는 정확한 Resource 신원 해소 및 실행 권한이 없는 연속 커버리지 게이트 | [대화](../../../services/core-control-plane/src/fdai/core/conversation/), [S3 프레임 정규화](../../../services/core-control-plane/src/fdai/core/conversation/semantic_planning_frame_normalization.py), [대상 후보 계획](../../../services/core-control-plane/src/fdai/core/conversation/semantic_target_candidate_planning.py), [조사 플래너](../../../services/core-control-plane/src/fdai/core/conversation/semantic_investigation_planning.py) | [대화 테스트](../../../services/core-control-plane/tests/conversation/) |
| 영속 백그라운드 작업 인계 | 프로덕션 실행기 연결 없이 임차 기간으로 보호되는 분리 읽기 레코드, 원자적 최종 발신함, 재생 멱등 대화 완료 및 단일 기록 완료 감사 표시 | [background_task](../../../services/core-control-plane/src/fdai/core/background_task/) 및 [완료 감사 어댑터](../../../services/core-control-plane/src/fdai/delivery/persistence/background_task_completion_audit.py) | [백그라운드 작업 테스트](../../../services/core-control-plane/tests/core/background_task/) 및 [완료 감사 테스트](../../../services/core-control-plane/tests/persistence/test_background_task_completion_audit.py) |
| Rule 의미 세대 종결 | 타입 기반 활성화 명령 및 최종 결과, 정확한 대상 증적과 예상 이전 세대 compare-and-swap, 프로바이더 접근 전 replay 차단, 원자적 StateStore 결과/outbox 영속성, lease 차단, 재시도 예약, 손상 거부 및 정책 또는 실행 권한이 없는 broker 확인 기반 발행 상태 | [rule_semantic_generation](../../../services/core-control-plane/src/fdai/core/rule_semantic_generation/) | [Rule 의미 세대 테스트](../../../services/core-control-plane/tests/core/rule_semantic_generation/) |
| 온톨로지 의미 세대 | 프로바이더 중립적이고 범위가 제한된 순서 보장 문서 매니페스트, 자체 검증 가능한 세대 ID, 후보 전용 구체적인 인덱스, 영속 PostgreSQL 저장, 예상 이전 세대 활성화 compare-and-swap, full/incremental 선언 및 deployment-object 문서, 독립적인 검증 증적, stale detection 및 롤백 | [catalog_search 프로바이더](../../../services/core-control-plane/src/fdai/shared/providers/catalog_search.py) 및 [catalog_search 전달](../../../services/core-control-plane/src/fdai/delivery/catalog_search/) | [카탈로그 검색 테스트](../../../services/core-control-plane/tests/delivery/catalog_search/) |
| 메트릭, VM 프로세스 및 MySQL 압력 근거 연결 | 별칭 없는 검토된 메트릭 개념, 정확한 ObjectSet에서 파생한 label 선택기, 어떤 계획도 보호된 근거를 모델이 작성한 리터럴로 대체하지 못하도록 객체 값을 받는 모든 FunctionType 입력에 적용한 dependency-only 근거 연결, 관측된 0을 프로바이더 공백과 구분하는 정확한 `MetricProvider` 구간, 범위가 제한된 VM 프로세스별 CPU 레코드, 원인 또는 실행 권한이 없는 staged MySQL 포화 대 수요 근거 | [metric_window.py](../../../services/core-control-plane/src/fdai/delivery/metric_window.py), [metric_semantic_catalog.py](../../../services/core-control-plane/src/fdai/runtime/metric_semantic_catalog.py), [VM 프로세스 계약](../../../services/core-control-plane/src/fdai/core/ontology_platform/vm_process_evidence.py), [Azure Monitor Perf 어댑터](../../../services/core-control-plane/src/fdai/delivery/azure/vm_process_evidence.py), [MySQL 압력 근거](../../../services/core-control-plane/src/fdai/core/ontology_platform/mysql_pressure_evidence.py) | [메트릭 의미 카탈로그 테스트](../../../services/core-control-plane/tests/runtime/test_metric_semantic_catalog.py), [VM 프로세스 계약 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_vm_process_evidence.py), [Azure 어댑터 테스트](../../../services/core-control-plane/tests/delivery/azure/test_vm_process_evidence.py), [MySQL 압력 테스트](../../../services/core-control-plane/tests/core/ontology_platform/test_mysql_pressure_evidence.py) |
| 운영 가설 루프 | 완전한 graph Dynamic 근거 연결, 근거 하한을 고려한 계획 선택, 기한이 제한된 독립 궤적 종결, 일반 exact-plan 실행에서 시작하는 감독되는 타입 기반 효과 조정, 권한이 없는 exact kinetic proposal handoff, 과거 단일 참조 읽기와 새로운 복수 참조 전용 쓰기를 지원하는 변경 불가능한 다중 효과 운영 계보 및 Owner 사람 승인을 거치는 graph-model pointer 승격 | [graph 근거](../../../services/core-control-plane/src/fdai/delivery/azure/graph_dynamic_evidence.py), [종결](../../../services/core-control-plane/src/fdai/core/assurance_twin/graph_closure.py), [조정](../../../services/core-control-plane/src/fdai/delivery/reconciliation_runtime.py), [일반 요청 producer](../../../services/core-control-plane/src/fdai/delivery/reconciliation_request.py), [kinetic proposal producer](../../../services/core-control-plane/src/fdai/delivery/kinetic_proposal.py), [Forseti binding](../../../services/core-control-plane/src/fdai/agents/forseti.py), [계보](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py) 및 [승격](../../../services/core-control-plane/src/fdai/delivery/graph_model_promotion.py) | [graph 근거 테스트](../../../services/core-control-plane/tests/delivery/azure/test_graph_dynamic_evidence.py), [종결 테스트](../../../services/core-control-plane/tests/assurance_twin/test_graph_closure.py), [조정 테스트](../../../services/core-control-plane/tests/delivery/test_reconciliation_runtime.py), [kinetic proposal 테스트](../../../services/core-control-plane/tests/delivery/test_kinetic_proposal.py), [Forseti 테스트](../../../services/core-control-plane/tests/agents/test_decision_case_e2e.py), [계보 테스트](../../../services/core-control-plane/tests/core/operational_planning/test_hypothesis_lineage.py) 및 [승격 테스트](../../../services/core-control-plane/tests/delivery/test_graph_model_promotion.py) |
| 운영 학습 전달 | 결정론적 O3 후보 검증, 내용 기반 주소가 지정된 비활성 초안 PR 게시, 검증기 바인딩 Heimdall 관측 replay, 승격 권한이 없는 exact-digest O7 측정 | [O3 검증기 및 게시자](../../../services/core-control-plane/src/fdai/delivery/gitops_pr/), [O3 runtime 연결](../../../services/core-control-plane/src/fdai/runtime/operational_catalog_review.py), [관측 mailbox](../../../services/core-control-plane/src/fdai/delivery/reconciliation_observations.py), [O7 근거](../../../services/core-control-plane/src/fdai/delivery/measurement/operational_promotion_evidence.py) | [O3 전달 테스트](../../../services/core-control-plane/tests/delivery/test_gitops_catalog_validator.py), [O3 runtime 테스트](../../../services/core-control-plane/tests/runtime/test_operational_catalog_review.py), [관측 테스트](../../../services/core-control-plane/tests/delivery/test_reconciliation_observations.py), [O7 근거 테스트](../../../services/core-control-plane/tests/delivery/test_operational_promotion_evidence.py) |
| 발견 루프 shadow dwell | judge-and-log-only 관측의 후보별 보존, 자기 검증 되는 dwell 근거, 그리고 후보가 승격 대상이 되기 전에 Mimir가 다시 유도하는 실패 시 차단 임계 게이트 | [shadow_dwell.py](../../../services/core-control-plane/src/fdai/core/operational_learning/shadow_dwell.py) | [shadow dwell 테스트](../../../services/core-control-plane/tests/core/operational_learning/test_shadow_dwell.py)와 [발견 dwell 테스트](../../../services/core-control-plane/tests/agents/test_discovery_shadow_dwell.py) |
| 운영 준비 인계 | 타입이 지정된 소유권 이전 수집, Forseti가 책임지는 읽기 전용 검토, 재생 시 중복을 막는 보고서 전달, 승인 권한과 실행 권한이 없는 근거 기반 shadow 조치 | [준비성 조립](../../../services/core-control-plane/src/fdai/composition/readiness.py), [런타임 소비자](../../../services/core-control-plane/src/fdai/runtime/consumers.py), [작업 연결](../../../services/core-control-plane/src/fdai/runtime/bootstrap_tasks.py) | [런타임 수집 테스트](../../../services/core-control-plane/tests/runtime/test_operational_readiness_ingest.py), [준비성 서비스 테스트](../../../services/core-control-plane/tests/composition/test_readiness_service.py), [조치 테스트](../../../services/core-control-plane/tests/core/readiness/test_remediation.py) |
| 아키텍처 검토 | 매니페스트 준비 상태, 제어 전용 Process 변환 결과, 역할이 분명한 문서로 나눈 목표 온톨로지 기반 15개 에이전트 검토 루프 | [아키텍처 검토 코어](../../../services/core-control-plane/src/fdai/core/architecture_review/), [소유자 색인](architecture-review-board-ko.md), [온톨로지 에이전트 루프](architecture-review/ontology-agent-loop-ko.md), [근거 권한 계약](architecture-review/evidence-and-authority-ko.md), [전달 계획](architecture-review/delivery-plan-ko.md) | [아키텍처 검토 테스트](../../../services/core-control-plane/tests/core/architecture_review/), [준비 상태 검사기 테스트](../../../tests/integration/scripts/test_check_arb_readiness.py) |
| 운영자 SRE 명령 경로 | 운영자 문제 대응 요청 하나를 단일 correlation 아래에서 Incident 하나와 멱등 타입 ActionProposal 하나에 연결하고 권위 있는 Incident, Trace, Process, Approval 링크를 반환합니다 | [sre_request.py](../../../services/core-control-plane/src/fdai/core/incident/sre_request.py), [operator_request.py](../../../services/core-control-plane/src/fdai/shared/providers/operator_request.py) | [SRE 요청 테스트](../../../services/core-control-plane/tests/core/incident/test_sre_request.py) |
| 에이전트 pantheon | 고정 에이전트 15개와 타입이 지정된 이벤트 런타임 | [에이전트](../../../services/core-control-plane/src/fdai/agents/) | [에이전트 테스트](../../../services/core-control-plane/tests/agents/) |
| 조립 | Exact-release 의미 조회 assembly, request-role 실행기 factory, 짝지은 rubric receipt source/verifier binding 및 호출 범위의 불투명 상관관계를 사용하는 리소스 상태 활동 게시를 포함한 프로바이더/런타임 의존성 주입 | [조립](../../../services/core-control-plane/src/fdai/composition/) | [조립 테스트](../../../services/core-control-plane/tests/composition/) |
| Core 어댑터 | Core에 남은 프로바이더, 영속성, 알림 및 platform 어댑터입니다. 공개 웹 결과는 Azure 어댑터가 반환하기 전에 답변 구간을 exact source digest 및 권한 없는 실행 증적에 연결합니다. | [전달](../../../services/core-control-plane/src/fdai/delivery/) | [전달 테스트](../../../services/core-control-plane/tests/delivery/) |
| Rule 카탈로그 프로파일 바인딩 | 관리되는 `FDAI_PROFILE_ID`를 시작 시 한 번 해석해 T0 색인과 워크플로 guard 검증이 함께 읽는 불변 Rule 튜플로 만들고, 선택과 등급 조정을 차단 기본으로 처리하며, 테넌트 값이 없는 시작 진단을 남깁니다 | [rule_profile.py](../../../services/core-control-plane/src/fdai/runtime/rule_profile.py) | [Rule 프로파일 테스트](../../../services/core-control-plane/tests/runtime/test_rule_profile.py) |
| 런타임 | 불변 시작 계획, 타입이 지정된 active-runtime 조립, 지속형 operating-model 구독, ControlLoop가 ontology store를 노출한 뒤 연결되는 effect reconciliation, 집중된 메시징, Incident, 의미, 리소스 소유권 및 작업 hook 경계, 명시적 종료 순서, process-critical 상태 및 감사 쓰기와 authority-critical 전체 체인 증명을 분리하는 준비 상태, 작업 감독을 포함하는 Core 프로세스 수명 주기 | [런타임](../../../services/core-control-plane/src/fdai/runtime/), [bootstrap_plan.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_plan.py), [bootstrap_core.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_core.py), [bootstrap_resources.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_resources.py), [bootstrap_messaging.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_messaging.py), [bootstrap_incidents.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_incidents.py), [bootstrap_semantics.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_semantics.py) 및 [bootstrap_task_hooks.py](../../../services/core-control-plane/src/fdai/runtime/bootstrap_task_hooks.py) | [런타임 테스트](../../../services/core-control-plane/tests/runtime/), [부팅 계획 테스트](../../../services/core-control-plane/tests/runtime/test_bootstrap_plan.py), [메시징 테스트](../../../services/core-control-plane/tests/runtime/test_bootstrap_messaging.py), [Incident 테스트](../../../services/core-control-plane/tests/runtime/test_bootstrap_incidents.py) 및 [종료 테스트](../../../services/core-control-plane/tests/runtime/test_bootstrap_shutdown.py) |
| Core 계약과 프로바이더 경계 | Core 전용 타입, 프로바이더 프로토콜, 구성, 스트리밍 및 텔레메트리 | [shared](../../../services/core-control-plane/src/fdai/shared/) | [shared 테스트](../../../services/core-control-plane/tests/shared/) |
| Rule 카탈로그 파이프라인 | 카탈로그 스키마 로딩, 수집, 검증, 정제 및 승격 support | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) | [Rule 카탈로그 테스트](../../../services/core-control-plane/tests/rule_catalog/) |
| 검토된 Property 의미 커버리지 | 룰이 평가하는 참조 대비 검토된 Property 의미의 측정 커버리지, 선언된 프로바이더 경로의 근거 규칙, 회귀 방지 하한, 결정론적 우선순위 백로그 | [check-property-semantic-coverage.py](../../../scripts/quality/architecture/check-property-semantic-coverage.py) 및 [property-semantics.yaml](../../../rule-catalog/vocabulary/property-semantics.yaml) | [커버리지 게이트 테스트](../../../tests/integration/scripts/test_property_semantic_coverage.py) |
| Core 서비스 항목 지점 | Core 분포 시작과 서비스 조립 | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core 패키지 테스트](../../../services/core-control-plane/tests/) |

Inventory 관계 수렴은 지속형 운영 인스턴스 그래프가 소유합니다. 검토된 provider parent가 일반
containment를 shadow하고 snapshot 및 ontology store가 cardinality를 강제하며 inventory
ontology projector는 graph 교체와 generation commit marker를 직렬화합니다. Resource
ObjectSet receipt는 결과가 0개인 read를 포함해 source generation 및 completeness를 query
truncation과 독립적으로 보존합니다.

Bounded ARM compute overlay는 검토된 parent 및 attachment mapping을 통해 VMSS VM과 NIC child
collection을 소유합니다. Console instance presentation은 role assignment를 생략하고 선택한
non-scope root의 immediate Resource Group 하나만 유지하며 provider relationship을 추가하지 않고
evidence-backed AKS managed group, VMSS, VM, NIC hierarchy를 렌더링합니다.

Safety-core 커버리지 하한은 Core 패키지 안의 결정론적 계층과 risk 게이트에 적용됩니다. 해당
테스트는 Core 소유 테스트 트리에 유지합니다.

온톨로지 조회 실행은 런타임에서 exact release, 매니페스트, 역할 및 용도를 다시 검사합니다.
범위가 제한된 의존성 wave는 노드 기한에 큐 wait를 포함하고 in-flight 취소를 전파하며
차단된 descendant를 건너뜁니다. 안정적인 핸들러 타입, 값 및 런타임 실패는
`capability_failed`로 유지됩니다. 구조화된 진단에는 `node_kind`와 `failure_type`만 허용하며,
예외 본문, 인자, 노드 식별자, 프로바이더 페이로드 또는 운영자 데이터는 포함하지 않습니다.
조립은 범위가 제한된 secured ObjectSet 증적을 발급하고 source-derived 네트워크 및 Pod
텔레메트리 함수를 exact release에 등록합니다. 함수 dependency는 발급된 content 다이제스트만
해석합니다. `catalog.search_rules` 함수는 해당 exact release와 프로바이더 중립적이고 범위가
제한된 순서 보장 문서 매니페스트에 연결된 활성 Rule 세대만 허용합니다. 세대 다이제스트는 exact
순서 보장 문서 집합에서 독립적으로 재현할 수 있으므로 개수, 청크, 루트 또는 행 드리프트가 있으면
검증에 실패합니다. PostgreSQL 어댑터는 각 코퍼스 수명 주기를 직렬화하고 활성 포인터를 교체하기
전에 활성화 트랜잭션에서 예상 이전 세대를 정확히 확인합니다. 검색은 `CatalogRetrievalReceipt`와
함께 후보 전용 Rule을 반환하며 판단, 승인
또는 실행 권한을 부여하지 않습니다. Resource-state 조사 경로는 promoted 인벤토리를 답변 권한으로
유지하고 온톨로지 조회를 shadow로 실행하며 principal-scoped 동등성 증적을 StateStore에
저장합니다. 실제 호출마다 실시간 및 영속 활동 수명 주기에서 공유하는 불투명한
`correlation_ref` 하나를 받고, 불투명한 요청자 및 대화 참조는 재시도 간 논리적 질문
`idempotency_key`를 안정적으로 유지합니다. 별도 호출은 상관관계 값을 재사용하지 않습니다.
공개 조립 파사드는 선택적 resource-state composer만 내보냅니다. 구현 타입은 focused binder에
유지해 파사드가 structural 상한 아래에 머물도록 합니다.
플래너 매니페스트는 ObjectType 및 Interface 속성에 동일한 역할/용도 filtering을 적용합니다.
함수 서술자는 조립된 런타임에 handler가 등록된 선언에만 발행됩니다. 읽을 수 있지만 바인딩되지
않은 함수 선언은 `runtime_binding_unavailable`로 구조 coverage에 남으며, 이 accounting은 판단,
승인, 변경, 승격 또는 실행 권한을 부여하지 않습니다. 의도 근거는 최종 사유를 보존하면서 범위가
제한된 evidence-reference 잘림도 공개합니다.
검증기는 I/O 전에 declared DAG 노드를 가리키지 않는 출력을 거부합니다. Answered 턴은 범위가 제한된
검증된 조회 표만 렌더링하며 transient 변환 결과 게시는 dead-letter 전에 같은 영속
멱등적 결과를 재시도합니다.
Azure 의미 계획 수립은 기존 `httpx` 및 `WorkloadIdentity` 어댑터를 사용하여 검증된 JSON-object
제안 두 개를 만듭니다. 조립은 해석된 narrator 또는 `t1.judge` 후보를 T1 플래너로 연결하고
`t2.reasoner.primary` 후보는 별도의 선택적 escalation 어댑터에 유지합니다. Core는 T1 제안을
사용할 수 없거나 결정론적 스키마, 매니페스트, 구성 또는 계획 검증을 통과하지 못한 경우에만 T2를
호출합니다. 각 제안은 기본 90초 예산을 가지며, 범위가 제한된 `Retry-After` 지연이 이 예산 안에
들어올 때 제한된 후보 하나를 최대 한 번 재시도합니다. 조립은 권위 있는 프로바이더가 연결된
핸들러만 노출합니다. 공개
프레임 제안은 Core가 서버 소유 다이제스트를 다시 만들기 전에 shared wire 식별자 제약을
적용합니다. 구조화된 진단은 계획 단계, 후보 인덱스, 실패 클래스 및 입력을 포함하지 않는
검증 위치만 기록하며 운영자 텍스트와 프로바이더 상세는 제외합니다. 공개
조립 파사드는 Azure 전용 모델 및 카탈로그 연결을 `semantic_query_azure_composition.py`에 위임하면서
강제 적용되는 800줄 한도 아래를 유지합니다. 모듈 계약은 패키지 배치 게이트가 강제하는
`composition`, `seam` 및 `container` 기준점을 보존합니다. 검증된 `llm.mode` 문자열은 다른 LLM
연결기와 동일하게 값 비교로 Azure 의미 조립을 선택합니다.
ObjectSet 핸들러는 각 요청 역할에 맞게 다시 만들어지므로 읽기 담당이 Owner 가시성을 상속하지 않고
Owner도 읽기 담당으로 조용히 축소되지 않습니다. 모델, release, 저장소 또는 전송 계층 선행 조건이 없으면
암시적 `runtime=None` 대신 명시적 startup-readiness 실패로 유지됩니다.
Continuous 커버리지 증적은 결정론적 고정본 structural 검증과 운영 준비 상태를
분리합니다. 외부에서 생성된 `cross_service_e2e` 또는 `live_assurance` 질문 증적만
`production_ready`를 설정할 수 있으며 committed `deterministic_fixture`는 false로 유지합니다.
런타임 초기화는 의미 준비 상태와 버티컬 workload-identity construction을 기존 수명 주기 및
연결 보조 로직에 위임하여 기본 조립 루트를 검토된 fanout 상한 아래로 유지합니다. Thin
초기화 래퍼는 injected identity-builder 테스트 및 포크 경계를 보존합니다.
운영 가설 루프는 service 또는 agent를 추가하지 않습니다. 완전한 graph prerequisite는
composition에서 연결됩니다. 일반 실행은 일치하는 기존 exact V2 plan에서만 effect-reconciliation
request를 생성하고 broker 발행 전에 영속 outbox에 commit합니다. 누락된 observation 또는 발행
failure는 held 또는 pending evidence로 남으며 executor outcome을 다시 쓰지 않습니다. Model pointer
변경은 기존 governance ActionType, risk, Owner 승인, Thor execution, rollback 및 Saga audit 경로
안에 유지됩니다.
[계보 producer](../../../services/core-control-plane/src/fdai/core/operational_planning/hypothesis_lineage.py)와
[컨트롤 루프 sink](../../../services/core-control-plane/src/fdai/core/control_loop/_execution.py)는
권위 있는 계획 기록, 완료된 실행기 결과, 일치하는 독립적이고 채점 가능한 관측이 모두 있을
때만 단일 효과 episode 하나를 제출합니다. 변환 결과 기록 실패는 실행기 결과를 변경하지 않으며,
이 producer는 누락된 결과를 날조하는 대신 복수 효과를 거부합니다. focused 계보 및 컨트롤 루프
shadow 테스트가 두 경계를 고정합니다.

## 독립 서비스 지도

| 서비스 | 패키지 responsibility | 패키지 지도 |
|---------|------------------------|-------------|
| 환경 모델 바인딩 | 권한이 없는 공유 정책 계약, 정확한 제안-정책 결합, 3-way-CAS Settings projection, 고유한 기능 신원, 정확한 GA 및 TPM/PTU 해석, 범위가 제한된 공급자 읽기, Core 전용 attested runtime binding, healthy active-revision CAS, 정책 결속 exact 적용 및 독립 공급자 readback | [공유 계약](../../../packages/service-contracts/src/fdai_service_contracts/model_binding.py), [해석기 스키마](../../../services/core-control-plane/src/fdai/rule_catalog/schema/model_binding_policy.py), [제안 검증기](../../../scripts/deployment/azure/model_binding_proposal.py), [projection workflow](../../../.github/workflows/model-settings-projection.yml), [projection materializer](../../../scripts/deployment/local/materialize-authoritative-settings.py), [service guard](../../../scripts/deployment/service/guard_plan.py), [계획 검증기](../../../scripts/deployment/azure/verify-deployment-plan.py), [active revision 검증기](../../../scripts/deployment/azure/verify_active_core_revision.py), [공급자 readback](../../../scripts/deployment/azure/verify_model_deployments.py), [Operator IAM 어댑터](../../../services/operator-service/src/fdai_operator_service/postgres_iam.py), [Console 편집기](../../../console/src/routes/settings-model-binding-policy.tsx) |
| Operator 서비스 | 인증된 경로 계열, 영속 의미 브리지, 프로세스 소유 브리지 상태, 순서가 정해진 Managed Identity Kafka 수명 주기, exact-release 온톨로지 읽기, 범위가 제한된 활성 인벤토리 영향 탐색, 소유자 범위 백그라운드 작업 목록, 상세, 진행 상황 및 유한 SSE 재생 | [operations family](../../../services/operator-service/src/fdai_operator_service/families/operations/), [백그라운드 작업 변환 결과](../../../services/operator-service/src/fdai_operator_service/families/conversation/background_tasks.py), [PostgreSQL family store](../../../services/operator-service/src/fdai_operator_service/postgres_family_store.py), [읽기 migration](../../../service-migrations/branches/operator-service/versions/20260823_operator_background_task_read.py), [어댑터](../../../services/operator-service/src/fdai_operator_service/adapters/), [streaming](../../../services/operator-service/src/fdai_operator_service/streaming/) 및 [composition.py](../../../services/operator-service/src/fdai_operator_service/composition.py) |
| FDAI Console 백그라운드 작업 점검 | 엄격한 소유자 범위 작업/진행 상황 decoder, 이중 언어 목록 및 선택 상세 표현, 생성, 취소, 재시도 또는 실행 컨트롤이 없는 명시적 새로 고침 | [경로](../../../console/src/routes/background-tasks.tsx), [decoder](../../../console/src/routes/background-tasks.model.ts), [decoder 테스트](../../../console/src/routes/background-tasks.model.test.ts) |
| FDAI Console 온톨로지 워크벤치 | Exact 선언 경로, 엄격한 변환 결과 decoder, 근거/종속 항목/release 구역, localized 검증 상태 및 실행 control이 없는 스냅샷 결속 영향/map 표현 | [ObjectType 워크벤치](../../../console/src/routes/ontology-object-type-detail.tsx), [영향 경로](../../../console/src/routes/blast-radius.tsx), [영향 decoder](../../../console/src/routes/blast-radius.model.ts), [온톨로지 계약](../../../console/src/routes/ontology.types.ts) |
| 네트워크 토폴로지 시각화 | 공유 네트워크 어휘, 작성된 정적 다이어그램 계약, 관측 전용 Console 포커스 및 경로 표현, 실행 권한이 없는 정제된 내보내기 | [공유 어휘](../../../packages/network-topology-contracts/), [다이어그램 컴파일러](../../../tools/architecture-diagrams/), [Console 아키텍처 컴포넌트](../../../console/src/components/), [소유 설계](../interfaces/network-topology-visualization-ko.md) |
| 문서 인제스트 API | 업로드 intake, API 소유 전이 및 서비스 어댑터 | [패키지](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) |
| 문서 처리 워커 | 영속 문서 처리와 워커 소유 어댑터 | [패키지](../../../services/document-processing-worker/src/fdai_document_worker_service/) |
| Isolated 실행기 | Thor 소유 명령 처리, 프로바이더 효과, 증적 및 실행기 어댑터 | [패키지](../../../services/isolated-executor/src/fdai_executor_service/) |

이 패키지는 `fdai-service-contracts`에 의존할 수 있습니다. 다른 서비스의 구현
패키지는 가져오기하지 않습니다.
로컬 조립은 각 패키지 안에서 service-owned client lifecycle과 loopback adapter를 연결합니다.
따라서 Operator semantic bridge, ingestion publisher, 문서 worker consumer 및 isolated Executor는
배포된 managed-identity adapter와 동일한 logical topic, 멱등성, 준비 상태 및 증적 경계를
보존합니다. 문서 worker는 신뢰할 수 없는 압축 해제가 장기 실행 서비스를 종료하지 못하도록
native PDF를 리소스 상한이 있는 별도 프로세스에서 구문 분석합니다.

## Shared 계약 SDK

[fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/)는 프로세스가
공유하는 versioned wire 서술자, codec, 호환성 검사, 준비 상태 기록, 문서 계약,
운영자 계약 및 실행기 계약을 소유합니다. 서비스 조립, 프로바이더 구현,
데이터베이스 접근 또는 business 작업 흐름은 포함하지 않습니다.
`IncidentPageProjection`은 일반 `PageProjection` wire 형태를 안정적으로 유지하면서 Incident
roster page와 같은 스냅샷의 결과 metric을 하나의 읽기 전용 Operator 계약으로 연결합니다.
선택적 `incident_number`는 현재 UTC 월을 기준으로 할당되는 표시 전용 참조이며, 정규 Incident와
correlation 신원은 변경되지 않습니다.

Shared SDK는 Core/Operator 경계에서 사용하는 no-authority ontology-query 기록도 소유합니다.
의미 problem 프레임, 범위가 제한된 조회 DAG, 의도 그래프, 작업 증적 및 structural 커버리지 증적입니다.
프로바이더 클라이언트, 온톨로지 저장소, 플래너 모델 또는 실행 핸들러는 포함하지 않습니다.
또한 Core에서 Operator 화면으로 범위가 제한된 인벤토리 검사, 온톨로지 변환 및 현재 상태 읽기 근거를
전달하는 버전이 지정된 no-authority 운영 활동 기록을 소유합니다. 이 기록은 논리적 에이전트 소유권과
생산 프로세스를 분리하고 `execution_authority=false`를 고정합니다.

기존 Operator/Core 묶음의 버전 1.2는 범위가 제한된 semantic-turn 요청 하나와 근거에 묶인 최종
결과 하나를 추가합니다. 요청은 인증된 역할, 세션 정렬, 용도, 기한 및 멱등성을
pin합니다. Answered 결과에는 exact release, 매니페스트, 계획, 실행 증적 및 근거 참조가
필요합니다. SDK는 해당 필드를 폐기하는 대신 의미 downgrade to N-1을 거부합니다. 런타임
게시와 consumption은 service-owned 구현으로 유지됩니다.

SDK는 두 semantic channel이 하나의 physical Event Hub를 공유할 때 사용하는 logical-topic marker와
결정론적 consumer-group 파생 규칙도 소유합니다. Core와 Operator는 서로 다른 adapter, codec,
identity, logical topic 및 offset group을 유지하며 상대 서비스 구현을 가져오지 않습니다. 같은 계약은
targeted Terraform 상태가 새 output을 아직 materialize하지 않았을 때 사용하는 canonical physical-topic
기본값도 제공합니다.

또한 SDK는 실행 장소 계약을 소유합니다. `FDAI_EXECUTION_VENUE`를 해석하는 유일한 resolver와
장소가 선택하는 기능 플래그 표 하나입니다. 모든 프로세스가 같은 변수를 해석하고 독립 서비스는
core 컨트롤 플레인을 import할 수 없으므로 특정 서비스가 아니라 여기에 둡니다.
`fdai/runtime/venue.py`는 이를 다시 내보내기만 하고 자체 바인딩을 선언하지 않습니다.

서비스 분포 5개는 deployable `0.1.2` 이미지를 N-1, `0.1.3`을 N으로 사용합니다. 기존 contract-set
`1.0.0`/`1.1.0` 매트릭스는 프로세스 간 호환성 경계로 유지합니다.
내용 기반 주소를 가진 실제 운영 근거는 exact 서비스와 관측 종류도 연결하고 `observed=true`를
요구합니다. 다이제스트를 다시 계산해도 관측하지 않은 점유는 실제 운영 증적이 될 수 없습니다.

패키지 테스트 트리는 SDK 행동을 검증합니다. 서비스 간 N/N-1 및 토폴로지 검사는
[루트 통합 테스트](../../../tests/integration/)에 유지합니다.

## 기타 저장소 소유자

| 경로 | Responsibility |
|------|----------------|
| [evaluation-sdk/](../../../evaluation-sdk/) | 패키지 범위 CI로 보존하는 휴면 독립 evaluation 계약과 실행기입니다. |
| [benchmarks/](../../../benchmarks/) | 휴면 외부 실행 장치 driver 패키지와 명시적 독립 CyberGym shadow 실행기입니다. |
| [eval/golden-dataset/](../../../eval/golden-dataset/) | 로캘 중립 온톨로지 탐색 및 답변 oracle을 갖춘 이중 언어 cloud-operations 의미 질문입니다. |
| [services/core-control-plane/src/fdai/delivery/golden_question_dataset.py](../../../services/core-control-plane/src/fdai/delivery/golden_question_dataset.py) | 저장소 golden dataset의 범위가 제한된 loader와 결정론적 typed-observation adapter입니다. Semantic 축이 누락되면 release evidence 전에 인증에 실패합니다. |
| [extensions/](../../../extensions/) | 선택적 독립 패키지 기능입니다. |
| [rule-catalog/](../../../rule-catalog/) | Catalog-as-code 데이터입니다. |
| [policies/](../../../policies/) | OPA/Rego policy-as-code입니다. |
| [콘솔/](../../../console/) | 얇은 운영자 SPA입니다. |
| [cli/](../../../cli/) | Operator command-line 클라이언트입니다. |
| [scripts/agent/design_context.py](../../../scripts/agent/design_context.py) | Design 맥락 읽기를 기록하고 dirty 편집 경로를 예약하며, framework 및 constitution 편집의 stale 맥락을 hard-block하고, commit 범위와 파괴적 Git을 보호하며, repository-wide 검증을 명시적인 integration 또는 release 경계로 라우팅합니다. |

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 물리 서비스 및 패키지 소유권 | [다중 서비스 저장소 레이아웃](multi-service-repository-layout-ko.md) |
| 모듈 경계와 의존성 주입 | [프로젝트 구조](project-structure-ko.md) |
| 대화 및 온톨로지 조회 구현 순서 | [온톨로지 조회 커버리지 구현 계획](../interfaces/ontology-query-coverage-implementation-plan-ko.md) |
| IS 작업 패키지와 local-first 순서 | [서비스 분해 실행 계획](service-decomposition-execution-plan-ko.md) |
| 서비스 승격, 데이터 소유권 및 롤백 게이트 | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| Control-loop 권한 | [아키텍처 instructions](../../../.github/instructions/architecture.instructions.md) |
| 에이전트 역할과 권한 | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
