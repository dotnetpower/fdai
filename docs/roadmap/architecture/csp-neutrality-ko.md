---
title: CSP-중립성 계약
translation_of: csp-neutrality.md
translation_source_sha: 034f07233b77ac83575312d782ddae9cb3f59a43
translation_revised: 2026-07-13
---

# CSP-중립성 계약

[Azure 가 유일한 구현 대상](../../../.github/copilot-instructions.md#implementation-focus-must)
임에도 코어를 CSP-중립으로 유지하는 구체적인 **계약(contracts)** 을 명명합니다. 계약은
와이어 수준(프로토콜, 아티팩트, 토큰 포맷)이므로 미래의 비-Azure 어댑터는 코어 재작성이 아니라
**추가 구성** 으로 붙습니다.

토폴로지는 [app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md),
모듈 경계는 [project-structure-ko.md](project-structure-ko.md), 기술 선택은
[tech-stack-ko.md](tech-stack-ko.md), 신원 모델은 [security-and-identity-ko.md](security-and-identity-ko.md)
를 보완합니다.

## 원칙

코어가 클라우드 프로바이더에서 접근하는 모든 것은 벤더 SDK 가 아니라 **관심사당 하나의
와이어 수준 계약** 을 통해야 합니다. 각 계약의 Azure 구현이 오늘 우리가 만드는 것이며,
fork 나 미래 phase 는 `core/` 를 편집하지 않고 **같은 계약** 의 새 구현을 등록해서 다른 CSP 를 추가합니다.

**동시성(Concurrency)**: 여덟 개의 provider Protocol 은 **기본 async** 입니다 (Kafka poll
loop, Postgres asyncpg, Key Vault HTTP, OIDC 토큰 교환, inventory-graph 쿼리, 그리고
§ 6-8 의 세 telemetry-ingestion 쿼리는 모두 I/O bound). Sync 는 event loop 를 블록하지
않도록 CPU / startup 전용 seam - `SchemaRegistry`, `ContractValidator`, `ConfigProvider` -
에만 남겨둡니다. 정본 seam 리스트는
[project-structure-ko.md § 주입 가능한 Seams](project-structure-ko.md#주입-가능한-seams)
참조.

CSP 접촉면을 지배하는 여덟 개의 계약 (다섯 wire-level foundation +
[scope-expansion-ko.md § 3.2](../fork-and-sequencing/scope-expansion-ko.md) 로 추가된 세 telemetry-ingestion
seam):

| # | 계약 | 와이어 / 아티팩트 | Azure 구현 |
|---|------|---------------------|-------------|
| 1 | **이벤트 버스** | Apache Kafka 와이어 프로토콜 | Event Hubs (Kafka endpoint on port `9093`) |
| 2 | **런타임** | OCI 컨테이너 이미지 + Knative 호환 매니페스트 서브셋 | Container Apps (Consumption, KEDA) |
| 3 | **시크릿** | 환경변수 (또는 K8s Secret 마운트) - 앱에서 CSP secret SDK 호출 안 함 | Container Apps native secret + Key Vault reference |
| 4 | **워크로드 아이덴티티** | OIDC 토큰 (federated) | User-assigned Managed Identity + workload identity federation |
| 5 | **인벤토리** | HTTP + OIDC-bearer 와이어로 `(Resource, Link[])` 배치를 반환하는 리소스-그래프 쿼리 표면 | Azure Resource Graph (ARG) + Activity Log delta |
| 6 | **Metric ingestion** | `MetricProvider.query(MetricQuery) -> AsyncIterator[MetricPoint]` (CSP-neutral name + label) | Azure Monitor Logs (KQL) - upstream 은 `FDAI_MONITOR_WORKSPACE_ID` 가 세팅되면 `AzureMonitorLogsMetricProvider` 를 자동 바인딩, 아니면 `NoopMetricProvider` 유지 |
| 7 | **Log ingestion** | `LogQueryProvider.query(LogQuery) -> AsyncIterator[LogRecord]` (vendor `expression` + CSP-neutral label filter) | Log Analytics (KQL) - upstream 은 `NoopLogQueryProvider` ship |
| 8 | **Trace ingestion** | `TraceQueryProvider.query(TraceQuery) -> AsyncIterator[Span]` (`trace_id`, `service`, `operation`, `min_duration`) | Application Insights - upstream 은 `NoopTraceQueryProvider` ship |

여덟 개 모두 `core/` 에 provider 특이를 누출하지 MUST NOT.
거부해야 하는 구체적 위반은 [Anti-Patterns](#anti-patterns) 참조.

## 1. 이벤트버스 계약 - Kafka 와이어 프로토콜

이벤트버스는 작고 프로바이더 독립적인 표면 (`bootstrap.servers`, `sasl.mechanism`,
`security.protocol`, 프로바이더별 토큰/자격증명 소스) 을 가진 **Kafka 프로듀서/컨슈머** 로
표현됩니다. 3대 CSP 모두와 여러 멀티클라우드 벤더가 Kafka 호환 endpoint 를 노출하므로, 같은
클라이언트 라이브러리와 같은 코드 경로가 모든 대상을 커버합니다.

| CSP / 벤더 | 관리형 Kafka endpoint | 인증 방식 | 비고 |
|---|---|---|---|
| Azure | **Event Hubs** (Kafka 1.0+ endpoint, `<ns>.servicebus.windows.net:9093`) | SASL/OAUTHBEARER + Entra 토큰 | 하나의 네임스페이스가 토픽 호스팅; Standard 1 TU 로 idle 비용 낮음 |
| AWS | **MSK Serverless** | SASL/OAUTHBEARER + AWS IAM SigV4 | 실제 serverless (partition-hour 과금) |
| GCP | **Managed Service for Apache Kafka** (GA) | SASL/OAUTHBEARER + Google IAM 토큰 | broker fleet 는 항상 켜져있음; 최소 클러스터 사용 |
| Multi-cloud | **Confluent Cloud** / **Redpanda Cloud** / **Aiven Kafka** | SASL/PLAIN 또는 SASL/OAUTHBEARER | 하이퍼스케일러에 대한 벤더 락인도 받아들일 수 없을 때의 escape hatch |
| Self-hosted | AKS/EKS/GKE 위의 **Strimzi Kafka**, 또는 **Redpanda** | SASL 또는 mTLS | 최후 수단; 운영 부담 큼 |

**규칙 (MUST):**

- 코어는 **Kafka 클라이언트로만** 프로듀스/컨슘 (예: `librdkafka`, `kafka-python`,
  `KafkaJS`, `Sarama`); `ServiceBusClient`, `SqsClient`, `PubSubClient`, 기타 어떤
  벤더 SDK 도 import 하지 않음.
- 이벤트 스키마는 JSON Schema 위에 **CloudEvents envelope** 사용
  ([tech-stack-ko.md](tech-stack-ko.md)); 모든 프로바이더에서 동일 유지.
- **스키마 진화** 는 `check_schema_compatibility`
  (`shared/contracts/compatibility.py`)로 가드된다: 버전별 스키마
  (`event/1.0.0` -> `event/1.1.0`)는 불변이며, catalog-validation 게이트가
  additive-only 가 아닌 bump(필드 제거, 타입/`enum` 제약의 변경 또는 신규
  추가, 신규 required, enum 축소는 `BREAKING`이며 object 속성이나 array
  `items` 내부 중첩 변경도 포함)를 거부한다. 이로써 rolling deploy 나 혼합 버전 replica 가 조용히
  디코딩 실패하는 것을 막아 - 구/신 producer/consumer 가 상호운용을 유지한다.
- **DLQ** = 명명 규약을 따르는 Kafka **dead-letter topic** (예: `<topic>.dlq`) + redrive
  워커; native DLQ 를 제공하는 프로바이더 (Event Hubs 는 제공 안함) 도 동작을 균일하게
  유지하기 위해 **무시** 하고 topic 규약 사용.
- **순서** 는 partition key 로 보장 (per-resource key ⇒ per-resource ordering).
  프로바이더 특이 순서 프리미티브 (Service Bus sessions, FIFO groups) 는 코어로 흘러선 안됨.
- **멱등성** 은 이벤트의 앱 수준 idempotency key 로 강제하지 프로바이더의 "exactly-once"
  플래그로 하지 않음. executor 는 인-프로세스 L1 캐시를 유지하고,
  `IdempotencyStore` seam(`shared/providers/idempotency.py`)이 배선되면 durable
  L2 가드(`PostgresIdempotencyStore`, `INSERT ... ON CONFLICT DO NOTHING`)를
  둔다: 재시작 후 또는 replica 간에서 *mutating* action 이 재전달되면
  재실행 대신 store 에서 반환된다. mutating outcome 만 기록된다 - abstain 은
  mutate 하지 않으므로 재평가해도 무해. "mutation 적용"과 "결과 기록" 사이의
  좁은 창은 `OutboxStore` seam(`shared/providers/outbox.py`;
  `PostgresOutboxStore` 백업)이 닫는다: mutation *전* 에 쓴 claim 이 있으므로
  crash-suspect 재시도는 `IN_PROGRESS` 마커를 발견해 idempotent mutation 을
  완료까지 재실행하며 잃거나 이중 적용하지 않는다. outbox 는 action 이
  mutate 할 때(enforce / P2) 의미가 있다; P1 은 shadow 전용이라 거기서는
  아무것도 이중 적용되지 않는다.
- **replica 간 per-resource 상호배제** 는 `ResourceLock` seam
  (`shared/providers/resource_lock.py`)으로 강제한다: 인-프로세스 `asyncio.Lock`
  (`ResourceLockManager`)이 단일 replica 기본값이고,
  `PostgresAdvisoryResourceLock`(`hashtextextended(resource_id)` 로 키잉된 Postgres
  세션 advisory lock)이 executor 가 replica 하나를 넘어 스케일아웃하면 replica 간
  상호배제를 준다. partition-key 순서는 *stream* 을 직렬화하고, 락은 같은 리소스의
  동시 *action* 을 직렬화한다 - 스케일아웃에선 둘 다 필요하다. 락은 crash-safe
  (연결이 끊기면 세션 락 해제)이며 `lock_timeout` 으로 bound 되어 stuck holder 가
  replica 를 wedge 하지 않고 fail closed 한다.
- **다운스트림 장애 격리** 는 `CircuitBreaker` primitive
  (`shared/resilience/circuit_breaker.py`)를 쓴다: composition root 가 provider
  어댑터의 아웃바운드 호출(Azure ARM, GitHub, Postgres, Kafka)을 감싸, 실패가
  이어지면 회로를 OPEN 으로 트립해 죽은 의존성을 두드리는(재시도 폭풍) 대신 즉시
  실패하고, HALF_OPEN 단일 probe 로 탐침 후 닫는다. clock 주입 가능한 순수 I/O-free
  상태머신이며 composition root 에서 배선(`core` 에선 안 함)되어 CSP-neutral 을
  유지하고 판테온 브리지의 자가치유 재시작을 보완한다.
- **시스템 레벨 fail-toward-safety** 는 `DegradationController`
  (`shared/resilience/degradation.py`)다: circuit breaker 들을 종합해
  `NORMAL` / `DEGRADED` 모드로 판정하고, 중요 의존성이 OPEN 이면 autonomy 를
  shadow 로 캡한다 - 망가진 audit store 나 도달 불가 substrate 가 enforce mutation
  을 몰아선 안 된다. control loop 이 `autonomy_permitted()` 를 참조해 그 결과를
  risk-gate authority 에 `system_degraded` 로 전달하고, 이는 shadow 로 캡된
  `system_health` ceiling axis 를 추가한다 (execution-model.md 2.6a) - action
  승격 전에 적용된다.
- **backpressure** (`shared/resilience/backpressure.py`)는 세마포어로 동시성을
  bound 하고, in-flight 슬롯과 bounded 대기 큐가 모두 차면 *shed*(즉시 거부,
  broker / DLQ 로 재큐잉)해서 이벤트 폭주가 프로세스를 고갈시키는 대신 예측
  가능하게 저하되게 한다.

**Anti-patterns (MUST NOT):**

- Event Hubs 를 native AMQP SDK (또는 Service Bus SDK) 로 사용. Event Hubs 를 쓸 거면
  **`:9093` 의 Kafka endpoint 만** 허용.
- Dapr 의 pub/sub building block 사용 - 사이드카 의존성이 추가되고 런타임 레이어를
  다시 락인.

## 2. 런타임 계약 - OCI 이미지 + Knative 호환 매니페스트

코어는 하나 이상의 **OCI 컨테이너 이미지** 와 traffic / revisions / autoscaling
트리거 / health probe / env·secret 바인딩을 기술하는 작은 **Knative 호환 매니페스트 서브셋**
으로 배포됩니다. 프로바이더 어댑터가 이를 CSP 특이 리소스 모양으로 렌더링합니다.

| CSP / 서브스트레이트 | 런타임 | scale-to-zero | 계약에서 렌더링되는 배포 모양 |
|---|---|---|---|
| Azure | **Container Apps** (Consumption + KEDA) | ✓ | Bicep/Terraform 이 매니페스트에서 `containerapp` 리소스 생성 |
| AWS | **App Runner** (요청 기반) 또는 **ECS Fargate** + KEDA | App Runner ✓ / Fargate - | 같은 매니페스트에서 렌더링 |
| GCP | **Cloud Run** (services & jobs) | ✓ | Cloud Run 은 native Knative; 매니페스트 직접 적용 |
| Any K8s (AKS/EKS/GKE) | **Knative Serving** + KEDA | ✓ | 매니페스트 직접 적용 |
| Fallback | bare `Deployment` + HPA + KEDA | - (idle ≥ 1 replica) | scale-to-zero 불가시 렌더링 |

**규칙 (MUST):**

- 이미지는 표준 **`/healthz` 및 `/readyz`** endpoint 노출. Container Apps probe, K8s
  probe, App Runner probe, Cloud Run probe 모두 이 둘을 가리킴.
- **스케일 트리거는 계약 수준 시그널** (예: `scale-on: kafka-lag`, 또는 CPU target).
  프로바이더 어댑터가 KEDA CRD, App Runner concurrency, Cloud Run CPU utilization 등으로 번역.
- 코어는 Dapr 사이드카, Envoy-특이 ingress annotation, Container Apps 전용 기능 (예:
  Container Apps YAML 에만 존재하는 native KEDA scaler reference) 에 의존하지 **않음**.
- Azure 에서 스케줄 워커를 Container Apps Job 으로 배송하는 곳에서, 다른 프로바이더는 같은
  계약을 K8s `CronJob`, AWS EventBridge 트리거 태스크, 또는 Cloud Run Job 으로 렌더링 -
  모두 상호교환 가능.

**Anti-patterns (MUST NOT):**

- 애플리케이션의 자체 레포에 Container Apps 전용 YAML (Dapr components, native KEDA scaler
  refs) 을 굽는 것.
- Envoy 스타일 ingress 규칙 요구; 이식 가능한 ingress 추상화를 쓰거나 앱 안에서 라우팅 처리.

## 3. 시크릿 계약 - 환경변수 / K8s Secret

애플리케이션은 **환경변수만** 읽거나, Kubernetes 위에서는 `Secret` 에서 마운트된 파일만
읽습니다. CSP secret SDK 를 **직접 호출하지 않습니다**. 주입 레이어가 CSP secret backend 를
컨테이너의 환경으로 이어줍니다.

| CSP / 서브스트레이트 | 주입 레이어 | Backend | 인증 |
|---|---|---|---|
| Azure Container Apps | **Key Vault reference** 를 사용하는 native `secret` 필드 | Key Vault | user-assigned MI |
| Any K8s | `SecretStore` CRD 를 가진 **External Secrets Operator (ESO)** | Key Vault / AWS Secrets Manager / GCP Secret Manager / Vault | CSP 별 Workload Identity |
| AWS (ECS/App Runner) | native task-def secret reference | Secrets Manager / Parameter Store | IRSA |
| GCP (Cloud Run) | native environment-from-secret reference | Secret Manager | Workload Identity |
| Multi-cloud OSS | **ESO + HashiCorp Vault** | Vault | JWT/OIDC |
| Dev/local | 파일 / `sops`-encrypted git | files | GPG/age |

**규칙 (MUST):**

- 코어는 `shared/providers/` 의 주입된 `SecretProvider` 인터페이스 **를 통해서만** secret
  을 읽음 ([project-structure-ko.md](project-structure-ko.md#injectable-seams));
  어떤 벤더 SDK 의 `SecretClient` 도 `core/` 에 나타나지 않음.
- **Secret 이름은 프로바이더 전체에서 안정적 스키마** 를 따름 (upper-snake env var 이름) -
  앱이 프로바이더를 모르게.
- **Fail-closed**: 주입 레이어가 부팅 시 필수 secret 을 해결하지 못하면 프로세스가 fail
  fast - 캐시된 값이나 임베디드 값으로 fallback 하지 않음
  ([security-and-identity-ko.md](security-and-identity-ko.md#secrets-and-config)).
- **로테이션** 은 주입 레이어의 일; 앱은 프로세스 재시작 시 env 를 다시 읽어서 롤된 secret 을
  수용. 복호화된 secret 자재의 장기 캐시는 금지.

**Anti-patterns (MUST NOT):**

- 애플리케이션 코드에서 `SecretClient.GetSecret()` (또는 동등물) 호출.
- 평문 또는 암호화된 secret 을 source 에 커밋 (git 내 SOPS 는 dev/local 에서만 허용;
  staging/prod 에서는 절대 안됨).

## 4. 워크로드 아이덴티티 계약 - OIDC 토큰

executor 는 런타임 서브스트레이트에서 얻은 **짧은 수명의 OIDC 토큰** 으로 CSP 에 인증합니다.
어댑터 경계에서 이 토큰이 CSP 자격증명으로 교환됩니다. executor 는 장기 키나 공유 시크릿을
보유하지 않습니다.

| CSP / 서브스트레이트 | 워크로드 아이덴티티 프리미티브 | 토큰 교환 |
|---|---|---|
| Azure | User-assigned Managed Identity | IMDS → Entra 토큰 (SASL/OAUTHBEARER, ARM, KV) |
| AWS | IAM Roles for Service Accounts (IRSA) | pod 토큰 → `AssumeRoleWithWebIdentity` |
| GCP | Workload Identity Federation | K8s SA 토큰 → GCP STS |
| Any K8s | **SPIFFE/SPIRE** | SVID (JWT/X.509) 를 어댑터별 교환 |
| CI/CD | GitHub Actions OIDC / Azure DevOps federated credential | issuer → CSP-side federation trust |

**규칙 (MUST):**

- 코어는 "X 로 audience-scoped 된 토큰을 가져와"를 노출하는 `WorkloadIdentity` 인터페이스만
  봄; 구체적 토큰 issuer 는 프로바이더 어댑터의 관심사.
- **승인 신원 ≠ 실행 신원** ([security-and-identity-ko.md](security-and-identity-ko.md#execution-identity)).
  위 모든 CSP 매핑에서 유지.
- executor 프로세스, config, secret store 어디에도 **장기 키 없음**. CSP-side 자격증명이
  불가피한 경우 (예: legacy 서비스) 짧은 수명과 자동 로테이션 필수이며 사용은 audit log 에 기록.

**Anti-patterns (MUST NOT):**

- `core/` 안의 `DefaultAzureCredential()` 또는 유사한 이름의 SDK 진입점 - 그건 벤더 SDK
  호출이지 계약이 아님. 인터페이스 뒤의 Azure 프로바이더 어댑터에서 **만** 허용.
- executor 의 신원을 콘솔, ChatOps, 또는 다른 읽기 전용 표면과 공유.

## 5. 인벤토리 계약 - 리소스 그래프

코어는 리소스와 타입된 엣지의 온톨로지 그래프를 가지고 추론함
([llm-strategy-ko.md § 온톨로지 기반](llm-strategy-ko.md#온톨로지-기반)); **인벤토리** 계약은
그 그래프를 채우고 신선하게 유지하는 방법. 코어는 단일 `Inventory` Protocol 만
보며 CSP-중립 레코드를 반환하는 두 연산을 가짐:

- `full_snapshot(since=None) -> AsyncIterator[InventoryBatch]` - 초기 또는 주기적
  reconciliation 로드, 타입된 `Resource` 레코드와 `contains` / `attached_to` /
  `depends_on` 링크 레코드 배치로 emit.
- `delta(cursor) -> AsyncIterator[InventoryBatch]` - 주어진 커서 이후의 증분 변경,
  provider 의 네이티브 변경 스트림이 구동. Azure 어댑터는 이를 주입된
  `ActivityLogFetchFn` seam 뒤에서 실현한다: 포워딩된 변경 스트림을 멱등 upsert
  배치로 페이징하며, 진행하는 커서와 `full_snapshot` 과 동일한 `final=True`
  atomic-promote 펜스를 emit 한다. 이 seam 을 만족하는 바인딩은 둘: 이벤트버스-네이티브
  경로(Diagnostic-Settings-포워딩된 Kafka 토픽 - 아래 MUST 에 따른 프로덕션 기본값)와,
  포워더가 아직 프로비저닝되지 않은 환경을 위한 직접 Activity Log REST 팩토리
  (`AzureActivityLogFactory`). fetch 가 바인딩되지 않으면 `delta` 는 빈 `final=True`
  펜스를 반환한다.

읽기 전용 콘솔은 승격된 그래프의 별도 프로젝션을 `GET /inventory/graph`를 통해
사용합니다. 이 경로는 `ReadApiConfig.inventory_graph_provider`가 주입된 경우에만
활성화됩니다. CSP-중립 `Resource` 레코드와 `contains` / `attached_to` / `depends_on`
링크, 스냅샷 신선도, 잘림 메타데이터를 반환합니다. 이 경로는 Azure Resource Graph를
직접 호출하지 않으며 실행자 ID를 전달받지 않습니다.

이 프로젝션은 이름이 지정된 아키텍처 뷰를 제공합니다. 기본 뷰는 FDAI 자체 컨트롤
플레인이며, 추가 `application` 뷰는 FDAI가 판단하고 관찰할 수 있는 서비스를
분리합니다. `scope=<view-id>`를 지정하면 동일한 CSP-중립 와이어 계약을 유지하면서
해당 뷰의 경계가 제한된 리소스와 링크 집합을 반환합니다.

| CSP / 서브스트레이트 | 인벤토리 소스 | Delta 소스 | 와이어 |
|---|---|---|---|
| Azure | **Azure Resource Graph** (ARM 위 Kusto) | Activity Log → [이벤트버스](#1-이벤트버스-계약--kafka-와이어-프로토콜) 계약 (Diagnostic-Settings-포워딩된 Kafka 토픽) | HTTPS + `Authorization: Bearer <OIDC>` |
| AWS *(TBD)* | AWS Config + Resource Explorer | Config configuration-item 스트림이 Kafka 로 포워드 | HTTPS + SigV4 |
| GCP *(TBD)* | Cloud Asset Inventory | Asset feed 가 Kafka 로 포워드 | HTTPS + Google IAM |
| Any K8s | 리소스-모델 번역기를 통한 `apiserver` list-watch | `watch` 스트림이 Kafka 로 포워드 | HTTPS + service-account token |

**규칙 (MUST):**

- 코어는 `shared/providers/` 에 주입된 `Inventory` 인터페이스를 통해서만 인벤토리를 읽음
  ([project-structure-ko.md § 주입 가능한 Seams](project-structure-ko.md#주입-가능한-seams)).
  `ResourceManagementClient`, `ArmClient`, `boto3.client("config")`, `google.cloud.asset`
  - 클라우드-인벤토리 SDK 는 `core/` 에 생김 안 함.
- 레코드는 와이어에서 **CSP-중립**: `Resource.type` 은 canonical `resource_type`
  어휘 ([rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md#수집-소스))
  이며 링크 종류는 `shared/contracts/ontology/link-type.json` 에 선언된 것. 벤더-네이티브
  id 는 Resource 의 redacted `provider_ref` 필드에 타고 올 수 있음 - 절대 primary key 아님.
- **초기 full snapshot 은 바운드된 동시성으로 병렬화**: 어댑터는 워크로드를
  `ResourceType` 으로 샤딩 (하나의 타입이 너무 넓으면 스코프로 더 세분화), semaphore 하에서
  fan-out 쿼리, 배치를 ingest 파이프라인으로 스트리밍. 코어는 절대 단일-연결 블로킹
  스캔을 가정하지 않음.
- 중립 `resource_id` 와 `(from_id, link_type, to_id)` 로 keyed 된 `ontology_resource` +
  `ontology_link` 에 **멱등 upsert**; full scan 을 재실행해도 그래프가 수렴할 뿐 중복
  안 함.
- **Fail-closed**: 부분 snapshot 은 stale 그래프가 자율 결정을 구동하는 상태에 절대
  런딩하지 않음. snapshot 이 완료되고 원자적으로 승격되거나, 이전 그래프가 유지되고
  실패가 감사됨.
- **Delta 는 별도 사이드-채널이 아니라 이벤트 버스를 통해 흐름**. Provider 변경 신호
  (Activity Log, Config item, Asset feed, apiserver watch) 는 Kafka 토픽으로 포워드되어
  다른 `Signal` 과 정확히 같이 소비 - 동일한 멱등성, 동일한 DLQ.
- **미인식 `ResourceType` 또는 LinkType** 은 이슈를 열고 드롭됨; 어댑터는 런타임에 새
  온톨로지 타입을 자동 등록하지 않음
  ([llm-strategy-ko.md § 포크 확장](llm-strategy-ko.md#포크-확장-self-extending-온톨로지)).
- 신뢰할 수 없는 벤더 속성 (태그, 설명) 은 추가 전에 redact 또는 길이-상한화되어
  있어야 하며 inert 데이터이지 지시가 아님.

**Anti-patterns (MUST NOT):**

- `core/` 에서 `azure-mgmt-*`, `boto3`, `google-cloud-*` 클라이언트 import.
  클라우드 인벤토리 SDK 는 provider 어댑터 패키지에만 살았.
- Kusto / ARG 쿼리를 `core/` 코드 경로에 임베드 (그것들은 manifest / 쿼리 템플릿이
  구동하는 Azure 어댑터에 속함).
- 초기 full scan 을 글로벌 락 하에 실행하거나, executor 의 per-resource 락 하에서 실행;
  인벤토리 sync 와 remediation 실행은 독립적 동시성 예산을 가진 별개 관심사.
- 부분 delta 스트림만을 authoritative 로 신뢰; 다운된 이벤트를 잡으려면 주기 full-snapshot
  reconciliation 이 필수.

## 6. Metric Query 계약 - CSP-Neutral Sample Iterator

외부 메트릭 (Prometheus, Azure Monitor Logs, CloudWatch, Datadog) 을
`MetricProvider.query(MetricQuery) -> AsyncIterator[MetricPoint]`
([`shared/providers/metric.py`](../../../src/fdai/shared/providers/metric.py))
로 소비. `MetricQuery` 는 vendor-neutral (`metric_name`, `labels`, `since`, `until`,
`aggregation` 힌트); 어댑터는 CSP-neutral 이름을 vendor namespace 로 매핑하고 힌트를
best-effort 로 honor. Upstream 은 `NoopMetricProvider` (빈 결과) + `StaticMetricProvider`
(테스트 double) 를 ship; Azure adapter 는 `delivery/azure/` 아래 land.

**Design rules:**

- Async by contract (외부 metric query 는 I/O-bound; 그렇지 않으면 event loop 를 block -
  § 1 / § 3 / § 4 / § 5 와 동일한 discipline).
- 빈 결과는 valid 답 (window 내 sample 없음 ≠ error).
- Caller 는 partial result 로 auto-remediate MUST NOT; abstain 하고 HIL 로 route -
  [architecture.instructions.md § Safety Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants)
  per.

## 7. Log Query 계약 - Structured Log Records

Structured log (Log Analytics KQL, Loki LogQL, Elasticsearch, CloudWatch Logs) 를
`LogQueryProvider.query(LogQuery) -> AsyncIterator[LogRecord]`
([`shared/providers/log_query.py`](../../../src/fdai/shared/providers/log_query.py))
로 소비. `expression` 필드는 vendor-specific 쿼리 문자열; `labels` 는 어댑터가 label
surface 에 매핑하는 CSP-neutral pre-filter. `core/` 에 tail 을 hard-code 하지 않고
CSP-neutral filter 와 vendor-specific tail 을 compose 할 수 있도록 분리 유지.

## 8. Trace Query 계약 - Distributed-Trace Spans

Span (App Insights, Tempo, Jaeger, Honeycomb) 을
`TraceQueryProvider.query(TraceQuery) -> AsyncIterator[Span]`
([`shared/providers/trace_query.py`](../../../src/fdai/shared/providers/trace_query.py))
로 소비. `Span` 은 `trace_id`, `span_id`, `parent_span_id`, `service`, `operation`,
`start`, `duration`, `status`, 그리고 CSP-neutral `labels` 를 carry - RCA 가 어떤
backend 가 기록했는지 모른 채 service 를 가로질러 request 를 walk 가능.

**§ 6 - § 8 공통 Design rules:**

- 세 telemetry-ingestion Protocol 은 anomaly detection, SLO burn-rate evaluation, RCA
  가 rule / policy citation 뿐만 아니라 real telemetry 에 ground 하도록 존재. Design
  contract 는 [scope-expansion-ko.md § 3.2](../fork-and-sequencing/scope-expansion-ko.md) 에.
- Upstream default 는 no-op provider - 어떤 concrete adapter 도 wire 되기 전에
  downstream consumer 가 안정된 interface 로 author 가능.
- Vendor SDK import 는 `delivery/<vendor>/` 에 confined; `core/` 는 Protocol 만 import -
  [`scripts/check-core-imports.sh`](../../../scripts/check-core-imports.sh) 에 의해 강제.

## Azure-Phase 실현 (요약)

오늘의 구현은 네 계약에 다음과 같이 슬롯됩니다. 명명된 각 서비스는 **채택 시점에 재확인할
권장사항** 이지만 ([tech-stack-ko.md](tech-stack-ko.md)) 계약 자체는 바뀌지 않습니다.

| 계약 | Azure 실현 | Idle 비용 자세 |
|---|---|---|
| 이벤트버스 | **Event Hubs Standard** (`:9093` Kafka endpoint, 1 TU, auto-inflate off) | 낮은 idle; TU 로 스케일 |
| 런타임 | **Container Apps** (Consumption, KEDA scale-to-zero) - 앱 하나 + 사이드카 | idle 시 `$0` |
| 시크릿 | Container Apps native secret + **Key Vault reference** | 무시할 수준 |
| 워크로드 아이덴티티 | **User-assigned MI** + CI/CD 를 위한 workload identity federation | 무료 |
| 인벤토리 | **Azure Resource Graph** (`resource_type` 으로 샤딩된 초기 병렬 full-scan) + 이벤트 버스로 포워드된 **Activity Log** delta | ARG 무료; Log 기반 delta 는 observability 인벤토리에 포함 |

`Service Bus` 와 `Event Grid` 는 앞으로 최소 인벤토리에 **포함되지 않습니다**. 이벤트버스는
Kafka 와이어 전용입니다. 프로바이더 네이티브 pub/sub 은 오직 **Kafka 버스로 이벤트를 넣는
소스** (예: Event Hubs Kafka 토픽으로 forward 하는 Event Grid subscription) 로만
사용되고, 절대 `core/` 의 런타임 의존이 아닙니다.

## 승인된 대안 Azure 구현(Approved Alternative Azure Implementations)

다섯 개의 와이어-레벨 계약이 이미 코어를 CSP-이식 가능하게 유지합니다. 이 표는 각 계약이
`core/` 를 건드리지 않고 스왑할 수 있는 **Azure 내부** 대안을 나열합니다. 스왑은
**infra 모듈 경계**에서 일어남 - fork 가 `infra/modules/<seam>/` 아래 다른 서브-모듈을
고르거나 (또는 순수 코드 레벨 변경이면 composition root에서 DI 바인딩 오버라이드).
"유지되는 것" 컬럼의 모든 것은 계약이지 구현이 아니며 스왑 전체에서 보존됩니다;
"변하는 것" 은 스왑된 모듈과 그 즉시 config 에 국한됩니다.

| Seam | Day-zero 기본 | 승인된 대안(Azure) | 스왑 시 변경 | 유지되는 것(계약) |
|------|--------------|-------------------|-------------|-------------------|
| Event bus | Event Hubs Standard (Kafka `:9093`) | **Strimzi** 통한 AKS 위 Kafka; **Confluent Cloud** (멀티 클라우드 관리형); AKS 위 **Redpanda** | broker 엔드포인트, 인증 메커니즘, 비용 프로파일 | Kafka 와이어 프로토콜, 토픽 + DLQ 명명(`<topic>.dlq`), idempotency key, partition-key로 순서 |
| Runtime | Container Apps (Consumption + KEDA) | **AKS** + Knative Serving + KEDA; 버스트/바인딩용 **Azure Functions** (Premium plan); 공개 HTTPS surface 필요 시 **App Service** | 스케일 트리거 렌더링, 프로브 배선, 사이드카 레이아웃 | OCI 이미지, Knative 호환 매니페스트 서브셋, `/healthz` + `/readyz` 계약, `scale-on:kafka-lag` 신호 |
| State store | PostgreSQL Flexible + `pgvector` | RU-미터링과 지역 write가 단일 primary를 초과할 때 **Cosmos DB** (SQL API); TDE / SQL-Server 호환이 필수일 때 **Azure SQL Managed Instance** | SQL 방언, 마이그레이션 도구, RU 비용 모델 | audit hash-chain 스키마, 버전된 event/action/rule 계약, `SchemaRegistry`+`ContractValidator` seam |
| Vector store | `pgvector` (state store와 co-located) | **Azure AI Search** 벡터 인덱스; AKS 위 **Qdrant** / **Milvus** | 인덱스 타입(HNSW/IVFFlat), 거리 metric, refresh 경로 | 임베딩 차원, 모델 선택(설정), T1 유사도 임계값 |
| Secret | Container Apps native `secret` + Key Vault reference | Key Vault 를 가리키는 `SecretStore` CRD 로 **AKS + External Secrets Operator**; FIPS-규제 데이터용 **Key Vault Premium** (HSM-backed) | 주입 레이어(Container Apps native ↔ ESO) | env-var-only 읽기, upper-snake env 이름, 시작 시 fail-closed, `core/` 에 SDK 호출 없음 |
| Workload identity | User-assigned MI | **Federated workload identity** (GH Actions OIDC ↔ Entra federated credential; AKS workload identity federation); 리소스 principal 이 단일-소유자일 때 **System-assigned MI** | trust 설정과 토큰 audience | `WorkloadIdentity` 인터페이스, JIT-스코프 롤, cross-domain assumption 거부 |
| Container registry | ACR Basic | **ACR Standard/Premium** (지역 replication, 프라이빗 엔드포인트); 외부 레지스트리로 **GHCR** 또는 **Docker Hub** | 티어 비용, 서명 + attestation 위치 | pin-by-digest, `latest` 없음, SBOM + provenance 기록 |
| Observability | Log Analytics workspace + 여기 바인딩된 App Insights | 독립형 Application Insights; **Grafana Managed for Azure** + Prometheus + Loki; OTel exporter 뒤의 벤더 APM | 대시보드, 알림 규칙, 보존 가격 | OpenTelemetry SDK, `correlation_id`, KPI 당 하나의 원격측정 소스 |
| HIL chat | Bot Framework / Teams 통한 Azure Bot(Free) | Container App 위 **커스텀 웹훅 어댑터**; [`chatops`] delivery 어댑터 통한 Slack 네이티브 봇 | 인증된 전송, Adaptive Card 렌더러 | approval-message 계약, action-bound HIL id, fail-closed 타임아웃 |
| Read-only 콘솔 호스팅 | Static Web Apps (Free) | Storage static-website + **Front Door**; **App Service Static Sites** | HTTPS surface, 커스텀 도메인 배선 | 읽기 전용 보장, Entra sign-in, privileged 호출 없음 |
| 인벤토리 | Azure Resource Graph + Activity Log delta | ARG 가 느린 테넌트용 **ARM list** 폴링 (per-resource-type, 샤딩된); 대상 집합에 authoritative 하다면 **Microsoft Defender for Cloud Inventory** | 쿼리 언어 (Kusto vs REST), delta 커서 시망틱스, freshness lag | `Inventory` Protocol 모양, CSP-중립 `resource_type` + 링크 종류, 멱등 upsert, 부분 snapshot fail-closed |

**전체 표에 걸친 규칙 (MUST):**

- 모든 대안은 기본 모듈이 노출하는 **같은 output 계약** 을 사용 (`endpoint`,
  `identity_resource_id`, `secret_ref_envelope`, `event_topic_names`, ...) 하므로 downstream
  Terraform / `main.tf` composition 이 대안에 따라 분기하지 않음.
- 대안은 **별도 Terraform 서브-모듈** 로 `infra/modules/<seam>/` 아래 배송, 최상위
  `var.<seam>_kind` (예: `var.runtime_kind = "container_apps"`) 로 선택.
- 어떤 대안도
  [deploy-and-onboard-ko.md § 리소스 명명 규약](../deployment/deploy-and-onboard-ko.md#리소스-명명-규약resource-naming-convention)
  을 지켜야 함; 스왑이 손으로 뽑은 이름을 허용하지 않음.
- 대안은 **필요할 때 빌드** - W4.1 과 함께 기본만 랜딩. 대안 추가는 자체 PR, 자체 shadow-mode
  검증.
- 어떤 대안도 `core/` 에 벤더 SDK 의존을 재도입할 수 없음. 이것은 원래의 CSP-중립성 규칙이고
  이깁니다.

## 비-Azure 경로 (Additive)

다른 CSP 를 추가하는 것은 **fork 수준 config 작업** 이며 코어 변경이 아닙니다:

1. Composition root 에서 `shared/providers/` 의 다섯 프로바이더 인터페이스의 새 구현을
   등록 ([project-structure-ko.md](project-structure-ko.md#customization-via-dependency-injection)).
2. `bootstrap.servers`, `SecretProvider`, `RuntimeAdapter`, `WorkloadIdentity`, `Inventory` 바인딩을 새 CSP 로 지시.
3. 같은 OCI 이미지 + Knative 호환 매니페스트를 대상 런타임으로 렌더링.
4. Azure 구현과의 parity 가 측정될 때까지 **shadow mode** 로 배송
   ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#safety-invariants)).

**비-Azure 대상은 TBD 로 남아있음**
([Implementation Focus](../../../.github/copilot-instructions.md#implementation-focus-must));
계약은 미래 어댑터가 additive 하도록 존재.

## Anti-Patterns (간결)

- 각 CSP 의 native pub/sub (`Service Bus` + `SQS/SNS` + `Pub/Sub`) 을 하나의 인터페이스
  뒤에 감싸는 것. Ack 시맨틱, ordering key, DLQ 모양, exactly-once 동작이 충분히 다르므로
  프로바이더 특이 버그가 새어나옴 - **대신 하나의 와이어 프로토콜 (Kafka) 사용**.
- **Dapr** 를 portability 레이어로 도입. 락인이 CSP 에서 Dapr 로 옮겨질 뿐이고 사이드카
  의존이 추가되며 로컬 개발이 복잡해짐.
- "Kafka 클라이언트 복잡성을 아끼려고" **Event Hubs 를 native AMQP SDK 로** 사용. 코드가
  다시 Azure 화됨. Kafka endpoint 를 쓰거나 Event Hubs 를 쓰지 마세요.
- 애플리케이션 코드에서 `SecretClient` 호출로 secret 읽기 (계약 3 참조).
- `core/` 안의 `DefaultAzureCredential()` (또는 동등물) (계약 4 참조).

## 관련 문서

| 학습 대상 | 문서 |
|-----------|------|
| 이 계약을 실현하는 구체 스택 | [tech-stack-ko.md](tech-stack-ko.md) |
| 계약에서 렌더링되는 Azure 리소스 인벤토리 | [deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) |
| 신원 모델과 secret 취급 심층 | [security-and-identity-ko.md](security-and-identity-ko.md) |
| 각 계약을 composition root에 노출하는 DI seam | [project-structure-ko.md#injectable-seams](project-structure-ko.md#injectable-seams) |
