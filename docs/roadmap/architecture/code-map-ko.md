---
title: 코드 맵
translation_of: code-map.md
translation_source_sha: e73b835bbd1e4765c23c74e3e28188cc7cf2e334
translation_revised: 2026-09-12
---
# 코드 맵

이 페이지는 FDAI 런타임 배포 단위와 저장소 영역을 소스, 테스트, 소유 설계 문서에 연결합니다. 기능 상태나 구현 이력을 기록하는 대신 구현 경계를 찾을 때 사용합니다.

> **범위:** 이 인덱스는 안정적인 저장소 소유권을 기록합니다. 동작과 현재 구현 원장은 연결된 각 설계 문서가 소유합니다.
>
> **과거 기록:** 폐기된 혼합 목적 상태 원장은 [보관된 코드 맵 구현 원장](../../roadmap-implementation/architecture/code-map.md)에 남아 있습니다.

## 설계 개요

- **서비스 소유권:** 배포 가능한 각 서비스는 패키지, 테스트, 마이그레이션, 런타임 조립을 소유합니다.
- **Core 소유권:** Core 컨트롤 플레인은 결정론적 판단, 온톨로지 처리, 에이전트, 권한 게이트를 `fdai` 네임스페이스 안에 유지합니다.
- **공유 계약:** 프로세스 간 wire 형식은 구현을 포함하지 않는 패키지에 둡니다. 검증과 비즈니스 판단은 각 서비스가 유지합니다.
- **통합 소유권:** 루트 통합 테스트는 서비스 간 호환성, 저장소 구조, 배포 토폴로지, 롤백 경계를 검증합니다.

## 물리 서비스 소유권

| 소유자 | 소스 | 테스트 | 배포 단위 |
|--------|------|--------|-----------|
| Core 컨트롤 플레인 | [fdai](../../../services/core-control-plane/src/fdai/) 및 [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core 테스트](../../../services/core-control-plane/tests/) | `fdai-core-control-plane` |
| Operator Service | [fdai_operator_service](../../../services/operator-service/src/fdai_operator_service/) | [Operator 테스트](../../../services/operator-service/tests/) | `fdai-operator-service` |
| Document Ingestion API | [fdai_ingestion_api_service](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) | [Ingestion API 테스트](../../../services/document-ingestion-api/tests/) | `fdai-document-ingestion-api` |
| Document Processing Worker | [fdai_document_worker_service](../../../services/document-processing-worker/src/fdai_document_worker_service/) | [Worker 테스트](../../../services/document-processing-worker/tests/) | `fdai-document-processing-worker` |
| Isolated Executor | [fdai_executor_service](../../../services/isolated-executor/src/fdai_executor_service/) | [Executor 테스트](../../../services/isolated-executor/tests/) | `fdai-isolated-executor-service` |
| System Knowledge Service | [fdai_system_knowledge_service](../../../services/system-knowledge-service/src/fdai_system_knowledge_service/) | [System Knowledge 테스트](../../../services/system-knowledge-service/tests/) | `fdai-system-knowledge-service` |
| 서비스 계약 | [fdai_service_contracts](../../../packages/service-contracts/src/fdai_service_contracts/) | [계약 테스트](../../../packages/service-contracts/tests/) | `fdai-service-contracts` |
| 선택적 Cost Governance 패키지 | [fdai_cost_governance](../../../extensions/cost-governance/src/fdai_cost_governance/) | [패키지 테스트](../../../extensions/cost-governance/tests/) | `fdai-cost-governance` |
| 서비스 간 통합 | 해당 없음 | [루트 통합 테스트](../../../tests/integration/) | 가상 루트 전용 |

## Core 컨트롤 플레인 지도

Core 배포 단위는 전체 `fdai` 네임스페이스를 유지합니다. 다음 표는 안정적인 하위 시스템 경계를 안내합니다. 동작 세부 정보와 제공 근거는 연결된 설계 문서와 구현 원장에서 확인합니다.

| 영역 | 소스 | 테스트 | 소유 설계 |
|------|------|--------|-----------|
| 컨트롤 루프와 판단 사례 | [control_loop](../../../services/core-control-plane/src/fdai/core/control_loop/) 및 [decision_case](../../../services/core-control-plane/src/fdai/core/decision_case/) | [Core 테스트](../../../services/core-control-plane/tests/core/) | [실행 모델](../decisioning/execution-model-ko.md) |
| 에이전트 런타임 | [agents](../../../services/core-control-plane/src/fdai/agents/) | [에이전트 테스트](../../../services/core-control-plane/tests/agents/) | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
| 대화, typed 판단 정규화 및 의미 조회 | [conversation](../../../services/core-control-plane/src/fdai/core/conversation/) 및 [knowledge](../../../services/core-control-plane/src/fdai/core/knowledge/) | [대화 테스트](../../../services/core-control-plane/tests/conversation/) | [계층형 대화 계획](../interfaces/hierarchical-conversation-planning-ko.md) |
| 운영 온톨로지와 인스턴스 그래프 | [ontology_platform](../../../services/core-control-plane/src/fdai/core/ontology_platform/) | [온톨로지 테스트](../../../services/core-control-plane/tests/core/ontology_platform/) | [운영 온톨로지 플랫폼](operating-ontology-platform-ko.md) |
| 운영 맥락 | [operational_context](../../../services/core-control-plane/src/fdai/core/operational_context/) | [운영 맥락 테스트](../../../services/core-control-plane/tests/core/operational_context/) | [운영 의도 원본](operating-intent-source-ko.md) |
| 감지와 조사 | [detection](../../../services/core-control-plane/src/fdai/core/detection/) 및 [investigation](../../../services/core-control-plane/src/fdai/core/investigation/) | [감지 테스트](../../../services/core-control-plane/tests/core/detection/) 및 [조사 테스트](../../../services/core-control-plane/tests/core/investigation/) | [관측성과 감지](../rules-and-detection/observability-and-detection-ko.md) |
| 근본 원인 분석과 평가 | [RCA](../../../services/core-control-plane/src/fdai/core/rca/) 및 [framework_assessment](../../../services/core-control-plane/src/fdai/core/framework_assessment/) | [RCA 테스트](../../../services/core-control-plane/tests/core/rca/) 및 [평가 테스트](../../../services/core-control-plane/tests/core/framework_assessment/) | [근본 원인 분석](../rules-and-detection/root-cause-analysis-ko.md) |
| Workflow와 실행 조정 | [workflow](../../../services/core-control-plane/src/fdai/core/workflow/) 및 [executor](../../../services/core-control-plane/src/fdai/core/executor/) | [Workflow 테스트](../../../services/core-control-plane/tests/core/workflow/) 및 [실행기 테스트](../../../services/core-control-plane/tests/core/executor/) | [실행 권한 온톨로지](../decisioning/execution-authorization-ontology-ko.md) |
| Rule Catalog 런타임 | [rule_catalog](../../../services/core-control-plane/src/fdai/rule_catalog/) | [Rule Catalog 테스트](../../../services/core-control-plane/tests/rule_catalog/) | [Rule Catalog 수집](../rules-and-detection/rule-catalog-collection-ko.md) |
| 측정 및 통제된 코호트 근거 | [측정 코어](../../../services/core-control-plane/src/fdai/core/measurement/) 및 [측정 전달](../../../services/core-control-plane/src/fdai/delivery/measurement/) | [측정 테스트](../../../services/core-control-plane/tests/core/measurement/) 및 [전달 측정 테스트](../../../services/core-control-plane/tests/delivery/measurement/) | [목표와 메트릭](goals-and-metrics-ko.md) |
| Prompt와 모델 바인딩 | [prompts](../../../services/core-control-plane/src/fdai/core/prompts/) 및 [LLM 조립](../../../services/core-control-plane/src/fdai/composition/wire_llm.py) | [Prompt 테스트](../../../services/core-control-plane/tests/core/prompts/) | [Prompt 조립](../decisioning/prompt-composition-ko.md) |
| 전달과 영속성 어댑터 | [delivery](../../../services/core-control-plane/src/fdai/delivery/) | [전달 테스트](../../../services/core-control-plane/tests/delivery/) 및 [영속성 테스트](../../../services/core-control-plane/tests/persistence/) | [프로젝트 구조](project-structure-ko.md) |
| 조립과 런타임 | [composition](../../../services/core-control-plane/src/fdai/composition/) 및 [runtime](../../../services/core-control-plane/src/fdai/runtime/) | [조립 테스트](../../../services/core-control-plane/tests/composition/) 및 [런타임 테스트](../../../services/core-control-plane/tests/runtime/) | [프로젝트 구조](project-structure-ko.md) |
| Core 서비스 진입점 | [fdai_core_service](../../../services/core-control-plane/src/fdai_core_service/) | [Core 서비스 테스트](../../../services/core-control-plane/tests/) | [다중 서비스 저장소 레이아웃](multi-service-repository-layout-ko.md) |

## 독립 서비스 지도

| 서비스 | 책임 | 패키지 지도 |
|--------|------|-------------|
| Operator Service | 인증된 운영자 API, 조회 모델, 승인 채널, 영속 대화 변환 | [패키지](../../../services/operator-service/src/fdai_operator_service/) 및 [설계](../interfaces/operator-console-ko.md) |
| Document Ingestion API | 업로드 접수, 커넥터 상태, 문서 정책, 수집 게시 | [패키지](../../../services/document-ingestion-api/src/fdai_ingestion_api_service/) 및 [설계](../interfaces/document-ingestion-ko.md) |
| Document Processing Worker | 영속 추출, 광학 문자 인식, 인덱싱, 게시 | [패키지](../../../services/document-processing-worker/src/fdai_document_worker_service/) 및 [설계](../interfaces/document-lifecycle-governance-ko.md) |
| Isolated Executor | Thor 소유 명령 처리, 공급자 효과, 실행 증적 | [패키지](../../../services/isolated-executor/src/fdai_executor_service/) 및 [설계](../decisioning/execution-model-ko.md) |
| System Knowledge Service | 상호 배타적인 Bot Framework 또는 HMAC 인증 Outgoing Webhook 멘션 유입을 통한 release 연결 저장소 지식 검색, 운영 권한 없음 | [패키지](../../../services/system-knowledge-service/src/fdai_system_knowledge_service/) 및 [설계](../interfaces/system-knowledge-service-ko.md) |
| Cost Governance 확장 | 선택적으로 독립 패키지화한 비용 분석과 정책 통합 | [패키지](../../../extensions/cost-governance/src/fdai_cost_governance/) 및 [설계](finops-package-architecture-ko.md) |
| Console | Operator Service 계약을 사용하는 간결한 운영자 단일 페이지 애플리케이션 | [패키지](../../../console/) 및 [설계](../interfaces/operator-console-ko.md) |

서비스는 다른 서비스 구현이 아니라 [fdai-service-contracts](../../../packages/service-contracts/)에 의존합니다. 로컬 및 배포 조립은 같은 논리 topic, 멱등성, 준비 상태, 증적 경계를 유지합니다.

## Shared 계약 SDK

| 패키지 | 책임 | 테스트 |
|--------|------|--------|
| [fdai-service-contracts](../../../packages/service-contracts/) | 서비스 조립이나 공급자 I/O가 없는 버전별 프로세스 간 wire 서술자, codec, 준비 상태 레코드, 호환성 검사 | [계약 테스트](../../../packages/service-contracts/tests/) |
| [github-app-auth](../../../packages/github-app-auth/) | 승인된 서비스 이미지가 공유하는 갱신 가능한 GitHub App 자격 증명 | [패키지 테스트](../../../packages/github-app-auth/tests/) |

[공유 계약 런타임 참조](../../reference/shared-contract-runtime-ko.md)에서 버전 협상, 논리 topic, 실행 장소, 호환성 규칙을 설명합니다.

## 기타 저장소 소유자

| 경로 | 책임 |
|------|------|
| [evaluation-sdk](../../../evaluation-sdk/) 및 [benchmarks](../../../benchmarks/) | 독립 패키지형 평가 계약과 외부 harness driver |
| [eval/golden-dataset](../../../eval/golden-dataset/) | 이중 언어 의미 질문, 형식화된 관측, 답변 기준 |
| [extensions](../../../extensions/) | 선택적 독립 패키지 기능 |
| [rule-catalog](../../../rule-catalog/) | Catalog-as-code 스키마, 어휘, 규칙, 수집 원본 |
| [policies](../../../policies/) | OPA/Rego policy-as-code |
| [console](../../../console/) | 운영자 웹 애플리케이션 |
| [infra](../../../infra/) | Terraform 모듈과 배포 루트 |
| [cli](../../../cli/) 및 [deployment-cli](../../../packages/deployment-cli/) | 운영자 및 배포 명령줄 도구 |
| [scripts](../../../scripts/) | 저장소 품질, 개발, 배포, 에이전트 workflow 자동화 |

## 이 지도 유지 관리

- 안정적인 소유자, 소스 루트, 테스트 루트, 배포 단위, 소유 설계가 바뀔 때만 이 페이지를 업데이트합니다.
- 동작, 구현 상태, 검증 근거, 제공 이력은 소유 설계 문서와 해당 구현 원장에 기록합니다.
- 항목은 하위 시스템 또는 패키지 수준으로 유지합니다. 기능 설명을 추가하는 대신 집중 문서에 연결합니다.
- 영문과 한국어 페이지를 함께 업데이트합니다. 문서 크기 게이트는 이 인덱스가 다시 상태 원장이 되지 않도록 제한합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 물리 서비스와 패키지 소유권 | [다중 서비스 저장소 레이아웃](multi-service-repository-layout-ko.md) |
| 모듈 경계와 의존성 주입 | [프로젝트 구조](project-structure-ko.md) |
| 서비스 작업 패키지와 로컬 우선 순서 | [서비스 분해 실행 계획](service-decomposition-execution-plan-ko.md) |
| 서비스 승격, 데이터 소유권, 롤백 | [서비스 승격과 데이터 소유권](service-graduation-and-ownership-ko.md) |
| 컨트롤 루프 권한 | [아키텍처 instructions](../../../.github/instructions/architecture.instructions.md) |
| 에이전트 역할과 권한 | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
