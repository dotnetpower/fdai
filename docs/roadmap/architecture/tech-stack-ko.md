---
title: 기술 스택
translation_of: tech-stack.md
translation_source_sha: 1aaeacb20844f6b58160eb71e4576a2c09b5a146
translation_revised: 2026-08-14
---

# 기술 스택

선택은 **CSP-중립, OSS-우선** 컴포넌트를 선호하여 컨트롤 플레인을 이식 가능하고 벤더 락인
없이 유지합니다. 이 스택에서 **Azure만이 구현 대상** 입니다. 대안 컬럼에 나열된 비-Azure
관리 서비스는 **TBD** 입니다
([구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must)
참조). 특정 관리 서비스가 지명된 경우 그것은 **채택 시점에 재확인할 권장사항**(관리형 오퍼링과
프리뷰 기능은 변경됨)이지 하드 의존이 아닙니다. 이 스택은
[app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 의 토폴로지를
실현하며
[coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
의 안전·코드 규칙과 [security-and-identity-ko.md](security-and-identity-ko.md) 의 위협 모델을
만족해야 합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| Python 서비스 분포와 5개 서비스 런타임 | validated | `services/`; `packages/service-contracts/`; `config/independent-service-live-evidence-manifest.json`; `config/independent-service-remote-evidence.attestation.jsonl` | 5개 서비스 분포, 이미지, 상태 경계 및 보호된 N/N-1/N 전이에 원격 근거가 보존돼 있습니다. |
| Terraform Azure 플랫폼, Event Hubs Kafka, PostgreSQL 및 pgvector | implemented | `infra/`; `alembic/`; `service-migrations/branches/`; 집중 인프라 및 migration 테스트 | 스택과 보호된 배포 mechanics가 있습니다. 일반 플랫폼 소유자는 검증을 주장하기 전에 통제된 적용 증적을 보존해야 합니다. |
| OPA/Rego 정책과 카탈로그 실행 | implemented | `policies/`; `rule-catalog/`; `scripts/catalog/sync-rule-semantics.py`; 집중 정책 및 카탈로그 테스트 | 출하된 Rego, 정규화된 카탈로그 메타데이터, OPA 컴파일, 의미 표류 검사 및 결정론적 평가를 실행할 수 있습니다. |
| OpenTelemetry와 Azure 관측 어댑터 | in-progress | `shared/telemetry/`; `delivery/azure/metric_logs.py`; `delivery/azure/log_query.py`; `delivery/azure/telemetry_query.py`; 관측 캠페인 테스트 | 계측과 범위가 제한된 Azure 어댑터를 구현했습니다. 5개 서비스 전체의 보존된 종단 운영 텔레메트리 캠페인은 아직 필요합니다. |
| 비-Azure 관리형 대안 | deferred | [OD-3](#od-3-멀티클라우드-이벤트-버스-phase-4---tbd); [구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must) | 대안은 설계 선택지이며 구현되거나 동등성을 검증한 대상이 아닙니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 이전 이력을 재구성하지 않고 구현 원장을 도입했으며 스택을 현재의 5개 서비스, Rego, 텔레메트리 및 Azure 전용 구현에 맞췄습니다. | `current change`; 위에 인용한 서비스 근거, 인프라, 정책, 텔레메트리 및 집중 테스트 경로입니다. | 플랫폼 적용 및 텔레메트리 캠페인 근거를 보존하고 비-Azure 대상을 보류합니다. |

### 남은 작업

- [ ] 정확한 Terraform 계획, 소스 개정 번호, 서비스 이미지, migration, 신원 및 적용 후 상태를 연결하는 통제된 플랫폼 적용 증적을 보존합니다.
- [ ] 상관관계, 보존, 실패 및 사용 불가 상태 근거를 포함해 5개 서비스 전체에서 하나의 종단 OpenTelemetry 및 Azure 조회 캠페인을 보존합니다.
- [ ] 모델 교체를 운영 상태로 설명하기 전에 검토된 주간 모델 조정기를 구현하고 모든 교체를 초안 PR 및 shadow 재현으로 게이트합니다.
- [ ] 동등성과 롤백 근거를 갖춘 대상 하나가 명시적으로 승인될 때까지 비-Azure 대안을 구현하지 않습니다.

## 이 문서 읽는 법

- **굵은 글씨** 항목은 권장으로 제시된 지명 관리 서비스이며, 각각 Alternatives 컬럼에서 CSP-중립
  또는 OSS 대체와 짝지어집니다. 모두 위의 채택 시점 재확인 주의사항의 대상입니다.
- 굵지 않은 항목은 그대로 이식 가능한 OSS 또는 언어 수준 선택입니다.
- Azure 특이 요소는 모두 **프로바이더 어댑터 뒤에** 있으므로 코어 엔진이 벤더 SDK를 직접
  가져오기 하지 않습니다 (모듈 경계는 [project-structure-ko.md](project-structure-ko.md) 참조).

## 선택 원칙

- **CSP-중립 코어**: 정책은 OPA/Rego, IaC는 Terraform/OpenTofu, 프로바이더 접근은 어댑터 뒤에.
  벤더 SDK 호출은 코어 엔진에 등장하지 않습니다.
- **OSS-우선**: 벤더 락 등가물보다 오픈·permissive 라이선스 컴포넌트(OPA, Checkov/tfsec/KICS/Trivy,
  kube-bench, OpenCost, Chaos Mesh)를 선호.
- **이벤트-기반, scale-to-zero**: 항시 폴링 데몬 없음.
- **참신성보다 정합성**: 결정론적 엔진과 감사 저장소는 새 기술 채택보다 예측 가능한
  동작, 테스트 가능성, 관측성을 최적화합니다.
- **하나의 인터페이스 뒤에 두 구현**: 모든 독점적 선택마다 향후 비-Azure 어댑터가 추가적일 수
  있도록 문서화된 중립 대체를 유지합니다. 오늘 Azure만이 구현 대상이며 다른 CSP는 TBD입니다
  ([구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).

## 권장 스택

| 관심사 | 권장 | 근거 | Alternatives (중립 / OSS) |
|--------|------|------|--------------------------|
| Core 엔진 런타임 | **Python (3.12+)** - `services/core-control-plane/src/fdai/` 아래 src-layout | LLM / OPA / IaC-스캐너 SDK가 가장 성숙, mypy로 타이핑 강제 가능, 모든 서브시스템이 한 언어 ([OD-1](#od-1-core-런타임-언어) 참조) | TypeScript (노드), Go, .NET - 동일 인터페이스 뒤에서 향후 성능 기반 분리 시 예비 |
| Policy 엔진 | **OPA / Rego** | CSP-중립 policy-as-code; T0와 T2 검증기가 재사용 | Gatekeeper (K8s), Cloud 관리인 |
| IaC | **Terraform** (Azure 대상, HCL) | OD 해결; Terraform이 엔트리 커맨드 대상 (`terraform apply`)이며 [csp-neutrality-ko.md](csp-neutrality-ko.md)의 8개 CSP-중립 계약을 렌더링; Bicep과 OpenTofu는 호환 대안 | 엄격한 OSS 툴체인이 필요하면 **OpenTofu** (MPL-2.0 포크); Azure-only 편의는 Bicep; 범용 언어 선호 시 Pulumi |
| Event 버스 | **Event Hubs** 를 **`:9093` 의 Kafka 엔드포인트 로만** 소비 (Kafka 와이어 프로토콜이 CSP-중립 계약 - [csp-neutrality-ko.md](csp-neutrality-ko.md#1-이벤트버스-계약--kafka-와이어-프로토콜) 참조) | 하나의 와이어 프로토콜이 모든 관리형 대상 (MSK, GCP Managed Kafka, Confluent, Redpanda) 을 커버 → 비-Azure 어댑터는 구성 스왑 | MSK Serverless / GCP Managed Kafka / Confluent / Redpanda / 자체 호스팅 Strimzi - 비-Azure 옵션은 TBD |
| Event/메시지 스키마 | 버전된 레지스트리에 JSON 스키마 (또는 CloudEvents 묶음) | 타입 있는 버전된 이벤트 계약; 안전한 진화와 인그레스 검증 가능 | Avro/Protobuf + Confluent-호환 레지스트리 |
| Dead-letter 처리 | Kafka **dead-letter 토픽** 규약 (예: `<topic>.dlq`) + 재생/redrive 워커 | 어떤 이벤트도 조용히 드롭되지 않음; poison 메시지는 격리·재처리 가능; 모든 프로바이더에서 동일 | 벤더 native DLQ 는 **미사용** (프로바이더별 동작 상이) |
| Compute | **Azure Container Apps** (Consumption) - 독립적으로 패키지된 5개 런타임 서비스와 범위가 제한된 작업을 **OCI 이미지 + Knative 호환 매니페스트 subset**에서 렌더링 ([csp-neutrality-ko.md](csp-neutrality-ko.md#2-런타임-계약--oci-이미지--knative-호환-매니페스트) 참조) | Headless 코어 계약을 바꾸지 않고 서비스와 범위가 제한된 작업을 독립적으로 확장하며 매니페스트는 Cloud Run, App Runner 또는 K8s 위 Knative로도 렌더링 | Cloud Run(native Knative), App Runner, AKS/EKS/GKE 위의 Knative; 커스텀 네트워킹, DaemonSet 또는 GPU가 필요할 때 AKS |
| 경량 트리거 | **Container Apps Jobs** (Compute와 동일 환경); 다른 대상에서는 K8s `CronJob` / Cloud 실행 작업 / EventBridge 로 렌더링 | out-of-band 변경 감지, 비용 이상 훅, 스케줄 프로브 - 별도 Functions 계획 프로비저닝을 회피 | 네이티브 바인딩이 필요하면 Azure Functions; Knative eventing |
| 상태 / 감사 / KPI | **PostgreSQL** (기본) 또는 **Cosmos DB** | 추가 전용 감사 로그, 패턴 라이브러리, KPI 저장; 런타임 온톨로지 인스턴스 상태도 호스팅 ([llm-strategy-ko.md § 온톨로지 Storage 배치](llm-strategy-ko.md#ontology-storage-layout)) | [데이터 저장소 선택](#data-store-selection-criteria) 참조 |
| Vector 검색 (T1) | pgvector (PostgreSQL과 co-located) | 임베딩을 감사/상태 옆에 유지; 하나의 datastore로 운영 | 큰 스케일에서는 전용 vector DB (Qdrant/Milvus) - [Vector Search 근거 설명](#vector-search-rationale) 참조 |
| 시크릿 저장소 | Azure 에서는 **Container Apps native 시크릿 + Key Vault 참조**; 앱은 주입된 `SecretProvider` 를 통해 env 변수만 읽음 - [csp-neutrality-ko.md](csp-neutrality-ko.md#3-시크릿-계약--환경변수--k8s-secret) 참조 | 앱이 시크릿 SDK 를 가져오기 하지 않음; 비-Azure 대상에서는 **외부 Secrets Operator (ESO)** 가 AWS Secrets Manager / GCP 시크릿 Manager / HashiCorp Vault 를 동일 env 계약으로 이어줌 | ESO + Secrets Manager / GCP 시크릿 Manager / Vault; dev/로컬 에서만 SOPS + age |
| Feature flags / shadow 토글 | OSS 플래그 서비스 (OpenFeature + flagd) | 재배포 없이 액션별 shadow-vs-enforce 승격 게이팅 | 상태 저장소의 config-driven 플래그 |
| DB migrations | 버전된 마이그레이션 (Flyway / Alembic / Prisma Migrate) | 스키마 변경이 리뷰·순서·역방향 가능 | - |
| CI/CD | GitHub Actions 또는 Azure Pipelines | lint, tests, 커버리지 게이트, 시크릿 검사 (gitleaks), 의존성/SBOM 감사 실행 | GitLab CI |
| PR 게이트 | **GitHub App** (Checks API) 또는 Azure DevOps 서비스 hooks | 감사/롤백/승인이 이미 git에 존재 | 호스트에 관계없이 교정은 PR로 전달 |
| HIL 채널 | **Bot Framework / Teams** Adaptive Cards | 운영자가 있는 곳에서 도달 | Slack 어댑터; notifier 인터페이스 뒤의 이메일/웹훅 대체 경로 - [channels-and-notifications-ko.md](../interfaces/channels-and-notifications-ko.md) 참조 |
| LLM 접근 (T2) | 2개 이상 별개 모델을 감싸는 provider-agnostic 게이트웨이/라우터 | [llm-strategy-ko.md](llm-strategy-ko.md)의 mixed-model 교차 검사; 모델은 capability-preferences 레지스트리에서 해석되며 주간 검토 조정기는 아직 계획 상태 - [llm-strategy-ko.md](llm-strategy-ko.md#model-provisioning-and-lifecycle) | LiteLLM/OpenRouter 스타일 라우터 |
| Observability | OpenTelemetry (traces/metrics/logs) → 수집기 → 백엔드 (**Log Analytics** + 여기에 바인딩된 App Insights - 별도 APM 리소스 없음) | measurement-first는 일급 원격측정 필요; 보존은 기본 30일, UI에서 설정 가능 ([deploy-and-onboard-ko.md](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set)) | Prometheus + Grafana + Tempo/Loki (OSS); 벤더 APM |

## 데이터 저장소 선택 기준

기본은 **PostgreSQL** 입니다. 선호가 아니라 아래 기준에 따라 선택합니다:

- **관계형 + 감사 무결성**: 추가 전용 감사 로그, foreign 키, 트랜잭션 쓰기는 PostgreSQL을
  선호.
- **Co-located 벡터**: pgvector가 T1 임베딩을 같은 저장소에 유지 - 운영 단순, 하나의 백업/복원
  경로.
- **글로벌 분산 / 멀티 리전 쓰기 / 탄력적 파티션 스케일**: 쓰기 볼륨이나 지리적 분산이 단일
  기본을 초과할 때 Cosmos DB.
- **이식성**: PostgreSQL은 클라우드 간·로컬에서 동일 동작; Cosmos DB는 Azure 특이라 상태-저장
  어댑터 뒤에 있어야 함.
- **비용 모델**: PostgreSQL은 프로비저닝된/예측 가능; Cosmos DB는 RU 미터링 - 커밋 전에 예상
  감사 쓰기 처리량에 대해 검증할 것.

## Vector 검색 근거

- **pgvector로 시작**: 하나의 datastore, 감사/상태와 트랜잭션 일관성, 낮은-중간 코퍼스 크기에서
  T1 유사도 재사용에 충분.
- **전용 vector DB로 졸업**: 코퍼스가 대략 10^6-10^7 벡터를 초과하거나, p95 재현율/지연 시간 목표가
  HNSW/IVFFlat 튜닝으로 실패하거나, 임베딩 갱신이 트랜잭션 로드와 경합할 때.
- **임베딩 모델** 은 별도 결정(로컬/자체 호스팅 vs hosted API)이며 비용·프라이버시가 주도합니다.
  같은 LLM-게이트웨이 인터페이스 뒤에 두고 구성으로 버전 관리합니다.
- 인덱스 유형, 차원 수, 거리 메트릭은 하드코딩이 아니라 설정입니다.

## OSS 라이선스 자세

- 코어에 컴파일·링크되는 모든 것은 permissive/weak-copyleft 라이선스(Apache-2.0, MIT, MPL-2.0)
  를 선호합니다;
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
  에 따라 신규 의존성의 라이선스를 PR에 기록.
- **Terraform 참고**: Terraform은 BUSL-1.1 라이선스로 이동; 엄격한 OSS IaC 툴체인이 필요하면
  **OpenTofu** (MPL-2.0) 사용. `.tf` 모듈 에코시스템은 호환 유지.
- 재배포되는 컴포넌트에 대해서는 컴플라이언스 영향이 리뷰·수용되지 않는 한 AGPL을 회피.

## IaC 스캐너와 규칙 소스 (OSS)

- **Checkov, tfsec, KICS, Trivy** - IaC/misconfig 스캔.
- **kube-bench** - CIS Kubernetes 벤치마크 검사.
- **OPA/Gatekeeper** 라이브러리 - 재사용 가능한 정책 번들.
- **OpenCost** - FinOps를 위한 비용/단위 경제 신호.
- **Chaos Mesh** (또는 Azure Chaos Studio) - DR/Chaos 실험.

이들은 규칙 카탈로그에 공급됩니다
([phase-1-rule-catalog-t0-ko.md](../phases/phase-1-rule-catalog-t0-ko.md)).

## 공급망 및 품질 도구

- **Lockfile** 이 모든 의존성을 고정; CI는 lockfile에서만 설치.
- **시크릿 검사** (gitleaks) 과 **의존성/vulnerability 감사** 이 CI에서 실행되고
  high-severity 발견 시 블록.
- **Linter/formatter** (예: ESLint/Prettier 또는 Ruff/Black) 와 테스트 프레임워크가 필수 CI
  게이트의 일부이며,
  [coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)
  의 테스트 규칙과 정합.
- 릴리스 아티팩트에 대해 **SBOM** 생성 - 하류 포크 감사 지원.

## 로컬 개발

- Docker Compose가 **pgvector 있는 PostgreSQL** 을 띄워 로컬 스키마와 벡터 동작이 프로덕션과
  일치하도록 함(SQLite는 pgvector가 없어 통합 경로에서 회피).
- **이벤트 버스 충실도**: 로컬 실행은 **Docker 에서 Kafka 호환 브로커** (`redpanda` 단일
  노드 또는 `apache/kafka` 컨테이너) 를 사용하여 순서, 컨슈머 그룹, DLQ 시맨틱이 프로덕션과
  동일한 이벤트 인터페이스 뒤에서 일치. 클라우드 통합 테스트가 승격 전에 Event Hubs Kafka
  엔드포인트 에 대해 재검증.
- 결정론적 엔진과 risk 게이트는 완전 오프라인(클라우드 호출 없음)으로 실행되어 빠른 단위
  테스트.
- **LLM 모드는 환경과 독립**: `llm.mode` 기본값 `local-fake`가 결정론적 in-memory
  가짜(`DeterministicEmbeddingModel`, `MatchTypeCrossCheckModel`, `StaticVerifier`,
  `InMemoryGroundingSource`)를 Azure 자격 증명이나 토큰 비용 없이 연결합니다. 로컬 또는
  deployed 런타임은 `llm.mode == "azure"`를 명시적으로 선택할 수 있으며 `runtime.env`는
  근거/모델 프로파일을 선택하지 않습니다. Azure 어댑터는 `delivery/azure/llm/` 아래에
  있고 조립 루트만 가져옵니다. 전체 동등성 계약 + 작업 계획:
  [dev-and-deploy-parity-ko.md](../deployment/dev-and-deploy-parity-ko.md).
- rule-catalog 엔트리와 이벤트 페이로드 픽스처는 영문·시크릿 없음.

## 미결 결정(열림 Decisions)

가벼운 결정 기록으로 추적; 상태가 Decided 될 때까지 각 항목은 열려 있습니다. 전체 ADR은
[project-structure-ko.md](project-structure-ko.md) 에 정의된 프로젝트 구조 하에 등록됩니다.

### OD-1: Core 런타임 언어

- **컨텍스트**: 어댑터, LLM SDK, 규칙 도구가 선택을 주도.
- **옵션**: TypeScript (노드) · Python · Go.
- **기준**: 어댑터/SDK 성숙도, 팀 친숙도, 타이핑/성능 헤드룸.
- **상태**: **결정됨 - Python (3.12+), `services/core-control-plane/src/fdai/` 아래 단일 언어 monorepo.**
  근거: (i) OPA 바인딩, LLM 프로바이더, IaC 스캐너 툴체인 (Checkov / tfsec / KICS / Trivy) 이
  가장 풍부한 언어가 Python; (ii) mypy로 safety-core 에 필요한 타이핑 강도 확보; (iii) 모든
  서브시스템이 한 언어라 `core/tiers/t0_deterministic` 과 `core/risk_gate` 의 ≥ 90% 커버리지
  게이트가 단순해짐. 향후 성능 기반 분리 (예: `event_ingest` 를 Go 로) 는 서브시스템이 이미
  `shared/` 의 인터페이스 뒤에 있어 추가적으로 가능.
- **패키지 레이아웃**: Python "src 배치" - 모든 런타임 모듈은 `services/core-control-plane/src/fdai/<subsystem>/`
  아래. [project-structure-ko.md](project-structure-ko.md) 의 `core/`, `shared/`, `delivery/`,
  `rule_catalog/` 서브시스템 폴더는 각각 `services/core-control-plane/src/fdai/core/`, `services/core-control-plane/src/fdai/shared/`,
  `services/core-control-plane/src/fdai/delivery/`, `services/core-control-plane/src/fdai/rule_catalog/` 로 매핑됩니다. 디렉토리 이름은
  `snake_case` (Python 식별자 규칙); 논리적 `kebab-case` 이름은
  [language.instructions.md](../../../.github/instructions/language.instructions.md) 에 따라
  문서와 룰 id 에서 어휘로 유지됩니다.
- **Lockfile**: 리포 루트에 하나의 `uv.lock` (또는 동등물); 서브시스템별 lockfile 지침은
  다언어 레이아웃 초안에 해당했던 것으로 Python monorepo 에서는 폐지. 서브시스템 경계 강제는
  별도 패키지 경계가 아니라 CI 의 import-lint (W1.7) 로 수행됩니다.

### OD-2: 주 상태 저장소

- **컨텍스트**: 감사 로그, 패턴 라이브러리, T1 임베딩.
- **옵션**: PostgreSQL + pgvector · Cosmos DB.
- **기준**: [데이터 저장소 선택](#data-store-selection-criteria) 참조 (이식성, 스케일, 비용
  모델).
- **상태**: **결정됨 - PostgreSQL Flexible Server + pgvector.**
  `infra/modules/state-store/postgres-flex/`에 구현되어 있으며 루트 Terraform 모듈이
  선택합니다. Cosmos DB는 측정된 확장 요구가 생길 때 `StateStore` 프로바이더 뒤에서
  검토하는 대안이며 day-zero 인벤토리에는 포함되지 않습니다.

### OD-3: 멀티 클라우드 이벤트 버스 (단계 4 - TBD)

- **컨텍스트**: Azure 이벤트 서비스를 넘는 이식성. 비-Azure 대상은 TBD
  ([구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must));
  비-Azure 어댑터가 스코프에 들어올 때만 재검토.
- **옵션**: 현재 Kafka wire 계약을 다른 managed Kafka 대상으로 확장 · NATS JetStream ·
  순서, 재생, DLQ 의미를 보존하는 다른 로그 구현.
- **기준**: 순서 + DLQ 보장, 리플레이 필요, 운영 비용, CSP 중립성.
- **상태**: Deferred (TBD) - Azure만이 유일한 구현 대상이며 Event Hubs의 Kafka 엔드포인트를
  사용합니다. Azure 버스 결정은 완료되었고 이 항목은 향후 비-Azure 구현만 다룹니다.
