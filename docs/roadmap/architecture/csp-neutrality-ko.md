---
title: CSP-중립성 계약
translation_of: csp-neutrality.md
translation_source_sha: 4e93c33acb83df96a0bcea143e8d0b0516bd7bd5
translation_revised: 2026-08-11
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
포크 나 미래 단계 는 `core/` 를 편집하지 않고 **같은 계약** 의 새 구현을 등록해서 다른 CSP 를 추가합니다.

**동시성(동시성)**: I/O를 수행하는 프로바이더 경계는 **기본 비동기** 입니다 (Kafka poll
루프, Postgres asyncpg, Key Vault HTTP, OIDC 토큰 교환, inventory-graph 쿼리, 그리고
§ 6-8 의 세 telemetry-ingestion 쿼리는 모두 I/O 한계). Sync 는 이벤트 루프 를 블록하지
않도록 CPU / 시작 전용 경계 - `SchemaRegistry`, `ContractValidator`, `ConfigProvider` -
에만 남겨둡니다. 정본 경계 리스트는
[project-structure-ko.md § 주입 가능한 Seams](project-structure-ko.md#주입-가능한-seams)
참조.

CSP 접촉면을 지배하는 여덟 개의 계약 (다섯 wire-level 기반 +
[scope-expansion-ko.md § 3.2](../fork-and-sequencing/scope-expansion-ko.md) 로 추가된 세 telemetry-ingestion
경계):

| # | 계약 | 와이어 / 아티팩트 | Azure 구현 |
|---|------|---------------------|-------------|
| 1 | **이벤트 버스** | Apache Kafka 와이어 프로토콜 | Event Hubs (Kafka 엔드포인트 on 포트 `9093`) |
| 2 | **런타임** | OCI 컨테이너 이미지 + Knative 호환 매니페스트 서브셋 | Container Apps (Consumption, KEDA) |
| 3 | **시크릿** | 환경변수 (또는 K8s 시크릿 마운트) - 앱에서 CSP 시크릿 SDK 호출 안 함 | Container Apps native 시크릿 + Key Vault 참조 |
| 4 | **워크로드 아이덴티티** | OIDC 토큰 (federated) | User-assigned Managed Identity + 워크로드 신원 federation |
| 5 | **인벤토리** | HTTP + OIDC-bearer 와이어로 `(Resource, Link[])` 배치를 반환하는 리소스-그래프 쿼리 표면 | Azure Resource Graph (ARG) + Activity Log delta |
| 6 | **메트릭 인제스트** | `MetricProvider.query(MetricQuery) -> AsyncIterator[MetricPoint]` (CSP-neutral 이름 + 라벨) | Azure Monitor Logs (KQL) - 업스트림 은 `FDAI_MONITOR_WORKSPACE_ID` 가 세팅되면 `AzureMonitorLogsMetricProvider` 를 자동 바인딩, 아니면 `NoopMetricProvider` 유지 |
| 7 | **로그 인제스트** | `LogQueryProvider.query(LogQuery) -> AsyncIterator[LogRecord]` (벤더 `expression` + CSP-neutral 라벨 필터) | Log Analytics (KQL) - 업스트림 은 `NoopLogQueryProvider` ship |
| 8 | **추적 인제스트** | `TraceQueryProvider.query(TraceQuery) -> AsyncIterator[Span]` (`trace_id`, `service`, `operation`, `min_duration`) | Application Insights - 업스트림 은 `NoopTraceQueryProvider` ship |

여덟 개 모두 `core/` 에 프로바이더 특이를 누출하지 MUST NOT.
거부해야 하는 구체적 위반은 [Anti-Patterns](#anti-patterns) 참조.

## 1. 이벤트버스 계약 - Kafka 와이어 프로토콜

이벤트버스는 작고 프로바이더 독립적인 표면 (`bootstrap.servers`, `sasl.mechanism`,
`security.protocol`, 프로바이더별 토큰/자격증명 소스) 을 가진 **Kafka 프로듀서/컨슈머** 로
표현됩니다. 3대 CSP 모두와 여러 멀티클라우드 벤더가 Kafka 호환 엔드포인트 를 노출하므로, 같은
클라이언트 라이브러리와 같은 코드 경로가 모든 대상을 커버합니다.

| CSP / 벤더 | 관리형 Kafka 엔드포인트 | 인증 방식 | 비고 |
|---|---|---|---|
| Azure | **Event Hubs** (Kafka 1.0+ 엔드포인트, `<ns>.servicebus.windows.net:9093`) | SASL/OAUTHBEARER + Entra 토큰 | Standard 1-TU 이름 공간 샤드로 통제된 유입과 파서별 operational 신호를 분리 |
| AWS | **MSK Serverless** | SASL/OAUTHBEARER + AWS IAM SigV4 | 실제 serverless (partition-hour 과금) |
| GCP | **Managed Service for Apache Kafka** (GA) | SASL/OAUTHBEARER + Google IAM 토큰 | 브로커 fleet 는 항상 켜져있음; 최소 클러스터 사용 |
| Multi-cloud | **Confluent Cloud** / **Redpanda Cloud** / **Aiven Kafka** | SASL/PLAIN 또는 SASL/OAUTHBEARER | 하이퍼스케일러에 대한 벤더 락인도 받아들일 수 없을 때의 escape hatch |
| 자체 호스팅 | AKS/EKS/GKE 위의 **Strimzi Kafka**, 또는 **Redpanda** | SASL 또는 mTLS | 최후 수단; 운영 부담 큼 |

**규칙 (MUST):**

- 코어는 **Kafka 클라이언트로만** 프로듀스/컨슘 (예: `librdkafka`, `kafka-python`,
  `KafkaJS`, `Sarama`); `ServiceBusClient`, `SqsClient`, `PubSubClient`, 기타 어떤
  벤더 SDK 도 가져오기 하지 않음.
- Azure 어댑터는 Kafka `connections.max.idle.ms` 및 `metadata.max.age.ms` equivalent를
  180,000 ms로 설정하고 240,000 ms 이상 값을 차단합니다. 이 값은
  [Event Hubs Kafka 클라이언트 구성](https://learn.microsoft.com/azure/event-hubs/apache-kafka-configurations)
  제약을 따르며 managed 브로커가 이미 닫은 소켓의 재사용을 방지합니다.
- 같은 어댑터는 문서화된 Event Hubs 생산자 요청 시간 초과를 60,000 ms로 설정하고 요청을
  1,000,000 바이트로 제한하며 소비자 하트비트/세션 쌍을 3,000/30,000 ms로 유지하고 전송 계층
  실패 후 1초 재시도 재시도 대기를 적용합니다. aiokafka OAUTHBEARER 경계는 토큰 문자열만 받으므로
  어댑터가 주입된 `IdentityToken.expires_at`을 보존하고 만료 30-45초 전에 소비자 재시작을
  결정적으로 분산합니다. 재시작은 poll 사이에서만 일어나 호출자 처리를 가로지르지 않으며
  commit-after-yield at-least-once 전달을 보존합니다.
- 이벤트 스키마는 JSON 스키마 위에 **CloudEvents 묶음** 사용
  ([tech-stack-ko.md](tech-stack-ko.md)); 모든 프로바이더에서 동일 유지.
- **스키마 진화** 는 `check_schema_compatibility`
  (`shared/contracts/compatibility.py`)로 가드된다: 버전별 스키마
  (`event/1.0.0` -> `event/1.1.0`)는 불변이며, catalog-validation 게이트가
  additive-only 가 아닌 bump(필드 제거, 타입/`enum` 제약의 변경 또는 신규
  추가, 신규 필수, enum 축소는 `BREAKING`이며 객체 속성이나 array
  `items` 내부 중첩 변경도 포함)를 거부한다. 이로써 rolling deploy 나 혼합 버전 복제본 가 조용히
  디코딩 실패하는 것을 막아 - 구/신 생산자/소비자 가 상호운용을 유지한다.
- **DLQ** = 명명 규약을 따르는 Kafka **dead-letter 토픽** (예: `<topic>.dlq`) + redrive
  워커. 모든 프로바이더는 `original_topic`, `reason`, 원본 객체를 담은 `payload`로 구성된
  동일한 JSON 묶음을 기록하며 전송 계층 헤더는 redrive 계약에 포함되지 않습니다.
  Native DLQ를 제공하는 프로바이더(Event Hubs는 제공하지 않음)도 동작을 균일하게 유지하기
  위해 토픽 규약을 사용하고 native DLQ는 무시합니다. Multiplexing 어댑터는 logical DLQ
  구독을 physical DLQ로 매핑하고 redrive 전에 logical 토픽을 복원합니다.
- **순서** 는 파티션 키 로 보장 (per-resource 키 ⇒ per-resource 정렬).
  프로바이더 특이 순서 프리미티브 (Service Bus sessions, FIFO groups) 는 코어로 흘러선 안됨.
- **멱등성** 은 이벤트의 앱 수준 멱등성 키 로 강제하지 프로바이더의 "exactly-once"
  플래그로 하지 않음. 실행기 는 인-프로세스 L1 캐시를 유지하고,
  `IdempotencyStore` 경계(`shared/providers/idempotency.py`)이 배선되면 영속
  L2 가드(`PostgresIdempotencyStore`, `INSERT ... ON CONFLICT DO NOTHING`)를
  둔다: 재시작 후 또는 복제본 간에서 *mutating* 액션 이 재전달되면
  재실행 대신 저장소 에서 반환된다. mutating 결과 만 기록된다 - abstain 은
  mutate 하지 않으므로 재평가해도 무해. "변경 적용"과 "결과 기록" 사이의
  좁은 창은 `OutboxStore` 경계(`shared/providers/outbox.py`;
  `PostgresOutboxStore` 백업)이 닫는다: 변경 *전* 에 쓴 점유 이 있으므로
  crash-suspect 재시도는 `IN_PROGRESS` 마커를 발견해 멱등적 변경 을
  완료까지 재실행하며 잃거나 이중 적용하지 않는다. 발신함 는 액션 이
  mutate 할 때(강제 적용 / P2) 의미가 있다; P1 은 shadow 전용이라 거기서는
  아무것도 이중 적용되지 않는다.
- **복제본 간 per-resource 상호배제** 는 `ResourceLock` 경계
  (`shared/providers/resource_lock.py`)으로 강제한다: 인-프로세스 `asyncio.Lock`
  (`ResourceLockManager`)이 단일 복제본 기본값이고,
  `PostgresAdvisoryResourceLock`(`hashtextextended(resource_id)` 로 키잉된 Postgres
  세션 참고용 잠금)이 실행기 가 복제본 하나를 넘어 스케일아웃하면 복제본 간
  상호배제를 준다. partition-key 순서는 *스트림* 을 직렬화하고, 락은 같은 리소스의
  동시 *액션* 을 직렬화한다 - 스케일아웃에선 둘 다 필요하다. 락은 crash-safe
  (연결이 끊기면 세션 락 해제)이며 `lock_timeout` 으로 한계 되어 stuck 보유자 가
  복제본 를 wedge 하지 않고 실패 시 차단 한다.
- **다운스트림 장애 격리** 는 `CircuitBreaker` 기본 요소
  (`shared/resilience/circuit_breaker.py`)를 쓴다: 조립 루트 가 프로바이더
  어댑터의 아웃바운드 호출(Azure ARM, GitHub, Postgres, Kafka)을 감싸, 실패가
  이어지면 회로를 열림 으로 트립해 죽은 의존성을 두드리는(재시도 폭풍) 대신 즉시
  실패하고, HALF_OPEN 단일 탐색 로 탐침 후 닫는다. 시계 주입 가능한 순수 I/O-free
  상태머신이며 조립 루트 에서 배선(`core` 에선 안 함)되어 CSP-neutral 을
  유지하고 판테온 브리지의 자가치유 재시작을 보완한다.
- **시스템 레벨 fail-toward-safety** 는 `DegradationController`
  (`shared/resilience/degradation.py`)다: circuit 차단기 들을 종합해
  `NORMAL` / `DEGRADED` 모드로 판정하고, 중요 의존성이 열림 이면 자율성 를
  shadow 로 캡한다 - 망가진 감사 저장소 나 도달 불가 기반 가 강제 적용 변경
  을 몰아선 안 된다. 컨트롤 루프 이 `autonomy_permitted()` 를 참조해 그 결과를
  risk-gate 권한 에 `system_degraded` 로 전달하고, 이는 shadow 로 캡된
  `system_health` 상한 축 를 추가한다 (execution-model.md 2.6a) - 액션
  승격 전에 적용된다.
- **backpressure** (`shared/resilience/backpressure.py`)는 세마포어로 동시성을
  한계 하고, in-flight 슬롯과 범위가 제한된 대기 큐가 모두 차면 *shed*(즉시 거부,
  브로커 / DLQ 로 재큐잉)해서 이벤트 폭주가 프로세스를 고갈시키는 대신 예측
  가능하게 저하되게 한다.

**Anti-patterns (MUST NOT):**

- Event Hubs 를 native AMQP SDK (또는 Service Bus SDK) 로 사용. Event Hubs 를 쓸 거면
  **`:9093` 의 Kafka 엔드포인트 만** 허용.
- Dapr 의 pub/sub building 블록 사용 - 사이드카 의존성이 추가되고 런타임 레이어를
  다시 락인.

## 2. 런타임 계약 - OCI 이미지 + Knative 호환 매니페스트

코어는 하나 이상의 **OCI 컨테이너 이미지** 와 트래픽 / revisions / autoscaling
트리거 / 상태 탐색 / env·시크릿 바인딩을 기술하는 작은 **Knative 호환 매니페스트 서브셋**
으로 배포됩니다. 프로바이더 어댑터가 이를 CSP 특이 리소스 모양으로 렌더링합니다.

| CSP / 서브스트레이트 | 런타임 | scale-to-zero | 계약에서 렌더링되는 배포 모양 |
|---|---|---|---|
| Azure | **Container Apps** (Consumption + KEDA) | ✓ | Bicep/Terraform 이 매니페스트에서 `containerapp` 리소스 생성 |
| AWS | **App 실행기** (요청 기반) 또는 **ECS Fargate** + KEDA | App 실행기 ✓ / Fargate - | 같은 매니페스트에서 렌더링 |
| GCP | **Cloud 실행** (services & jobs) | ✓ | Cloud 실행 은 native Knative; 매니페스트 직접 적용 |
| Any K8s (AKS/EKS/GKE) | **Knative Serving** + KEDA | ✓ | 매니페스트 직접 적용 |
| 대체 경로 | bare `Deployment` + HPA + KEDA | - (idle ≥ 1 복제본) | scale-to-zero 불가시 렌더링 |

**규칙 (MUST):**

- 이미지는 표준 **`/healthz` 및 `/readyz`** 엔드포인트 노출. Container Apps 탐색, K8s
  탐색, App 실행기 탐색, Cloud 실행 탐색 모두 이 둘을 가리킴.
- **스케일 트리거는 계약 수준 시그널** (예: `scale-on: kafka-lag`, 또는 CPU 대상).
  프로바이더 어댑터가 KEDA CRD, App 실행기 동시성, Cloud 실행 CPU 사용률 등으로 번역.
- 코어는 Dapr 사이드카, Envoy-특이 유입 annotation, Container Apps 전용 기능 (예:
  Container Apps YAML 에만 존재하는 native KEDA scaler 참조) 에 의존하지 **않음**.
- Azure 에서 스케줄 워커를 Container Apps 작업 으로 배송하는 곳에서, 다른 프로바이더는 같은
  계약을 K8s `CronJob`, AWS EventBridge 트리거 태스크, 또는 Cloud 실행 작업 으로 렌더링 -
  모두 상호교환 가능.

**Anti-patterns (MUST NOT):**

- 애플리케이션의 자체 레포에 Container Apps 전용 YAML (Dapr components, native KEDA scaler
  refs) 을 굽는 것.
- Envoy 스타일 유입 규칙 요구; 이식 가능한 유입 추상화를 쓰거나 앱 안에서 라우팅 처리.

## 3. 시크릿 계약 - 환경변수 / K8s 시크릿

애플리케이션은 **환경변수만** 읽거나, Kubernetes 위에서는 `Secret` 에서 마운트된 파일만
읽습니다. CSP 시크릿 SDK 를 **직접 호출하지 않습니다**. 주입 레이어가 CSP 시크릿 백엔드 를
컨테이너의 환경으로 이어줍니다.

| CSP / 서브스트레이트 | 주입 레이어 | 백엔드 | 인증 |
|---|---|---|---|
| Azure Container Apps | **Key Vault 참조** 를 사용하는 native `secret` 필드 | Key Vault | user-assigned MI |
| Any K8s | `SecretStore` CRD 를 가진 **외부 Secrets Operator (ESO)** | Key Vault / AWS Secrets Manager / GCP 시크릿 Manager / Vault | CSP 별 워크로드 신원 |
| AWS (ECS/App 실행기) | native task-def 시크릿 참조 | Secrets Manager / 매개변수 저장소 | IRSA |
| GCP (Cloud 실행) | native environment-from-secret 참조 | 시크릿 Manager | 워크로드 신원 |
| Multi-cloud OSS | **ESO + HashiCorp Vault** | Vault | JWT/OIDC |
| Dev/로컬 | 파일 / `sops`-encrypted git | files | GPG/age |

**규칙 (MUST):**

- 코어는 `shared/providers/` 의 주입된 `SecretProvider` 인터페이스 **를 통해서만** 시크릿
  을 읽음 ([project-structure-ko.md](project-structure-ko.md#주입-가능한-seams));
  어떤 벤더 SDK 의 `SecretClient` 도 `core/` 에 나타나지 않음.
- **시크릿 이름은 프로바이더 전체에서 안정적 스키마** 를 따름 (upper-snake env var 이름) -
  앱이 프로바이더를 모르게.
- **실패 시 차단**: 주입 레이어가 부팅 시 필수 시크릿 을 해결하지 못하면 프로세스가 fail
  fast - 캐시된 값이나 임베디드 값으로 대체 경로 하지 않음
  ([security-and-identity-ko.md](security-and-identity-ko.md#secrets-and-config)).
- **로테이션** 은 주입 레이어의 일; 앱은 프로세스 재시작 시 env 를 다시 읽어서 롤된 시크릿 을
  수용. 복호화된 시크릿 자재의 장기 캐시는 금지.

**Anti-patterns (MUST NOT):**

- 애플리케이션 코드에서 `SecretClient.GetSecret()` (또는 동등물) 호출.
- 평문 또는 암호화된 시크릿 을 출처 에 커밋 (git 내 SOPS 는 dev/로컬 에서만 허용;
  staging/prod 에서는 절대 안됨).

## 4. 워크로드 아이덴티티 계약 - OIDC 토큰

실행기 는 런타임 서브스트레이트에서 얻은 **짧은 수명의 OIDC 토큰** 으로 CSP 에 인증합니다.
어댑터 경계에서 이 토큰이 CSP 자격증명으로 교환됩니다. 실행기 는 장기 키나 공유 시크릿을
보유하지 않습니다.

| CSP / 서브스트레이트 | 워크로드 아이덴티티 프리미티브 | 토큰 교환 |
|---|---|---|
| Azure | User-assigned Managed Identity | IMDS → Entra 토큰 (SASL/OAUTHBEARER, ARM, KV) |
| AWS | IAM Roles for 서비스 Accounts (IRSA) | pod 토큰 → `AssumeRoleWithWebIdentity` |
| GCP | 워크로드 신원 Federation | K8s SA 토큰 → GCP STS |
| Any K8s | **SPIFFE/SPIRE** | SVID (JWT/X.509) 를 어댑터별 교환 |
| CI/CD | GitHub Actions OIDC / Azure DevOps federated 자격 증명 | 발급자 → CSP-side federation trust |

**규칙 (MUST):**

- 코어는 "X 로 audience-scoped 된 토큰을 가져와"를 노출하는 `WorkloadIdentity` 인터페이스만
  봄; 구체적 토큰 발급자 는 프로바이더 어댑터의 관심사.
- **승인 신원 ≠ 실행 신원** ([security-and-identity-ko.md](security-and-identity-ko.md#execution-identity)).
  위 모든 CSP 매핑에서 유지.
- 실행기 프로세스, 구성, 시크릿 저장소 어디에도 **장기 키 없음**. CSP-side 자격증명이
  불가피한 경우 (예: 이전 방식 서비스) 짧은 수명과 자동 로테이션 필수이며 사용은 감사 로그 에 기록.

**Anti-patterns (MUST NOT):**

- `core/` 안의 `DefaultAzureCredential()` 또는 유사한 이름의 SDK 진입점 - 그건 벤더 SDK
  호출이지 계약이 아님. 인터페이스 뒤의 Azure 프로바이더 어댑터에서 **만** 허용.
- 실행기 의 신원을 콘솔, ChatOps, 또는 다른 읽기 전용 표면과 공유.

## 5. 인벤토리 계약 - 리소스 그래프

코어는 리소스와 타입된 엣지의 온톨로지 그래프를 가지고 추론함
([llm-strategy-ko.md § 온톨로지 기반](llm-strategy-ko.md#온톨로지-기반)); **인벤토리** 계약은
그 그래프를 채우고 신선하게 유지하는 방법. 코어는 단일 `Inventory` 프로토콜 만
보며 CSP-중립 레코드를 반환하는 두 연산을 가짐:

- `full_snapshot(since=None) -> AsyncIterator[InventoryBatch]` - 초기 또는 주기적
  조정 로드, 타입된 `Resource` 레코드와 `contains` / `attached_to` /
  `depends_on` 링크 레코드 배치로 발행.
- `delta(cursor) -> AsyncIterator[InventoryBatch]` - 주어진 커서 이후의 증분 변경이며
  프로바이더의 native 변경 스트림이 구동합니다. 운영에서는 리소스 생성,
  갱신, 삭제 신호가 정본 Kafka 유입으로 계속 들어옵니다. Huginn은 실시간
  발견 유입을 소유하고 정규화된 `Event` 기록을 publish하며, 주입된 인벤토리
  projector는 순서가 보장된 리소스, 링크, tombstone delta를 영속 오버레이에
  적용합니다. Azure 어댑터는 범위가 제한된 복구 출처로 direct Activity Log REST factory
  (`AzureActivityLogFactory`)도 유지합니다. 주기적 full 스냅샷은 조정의
  권위 있는 출처로 남으며 누락된 신호를 복구한 뒤 base 세대를 원자적으로
  교체합니다.

읽기 전용 콘솔은 승격된 그래프의 별도 프로젝션을 `GET /inventory/graph`를 통해
사용합니다. 이 경로는 `OperatorApiConfig.inventory_graph_provider`가 주입된 경우에만
활성화됩니다. CSP-중립 `Resource` 레코드와 `contains` / `attached_to` / `depends_on`
링크, 스냅샷 신선도, 잘림 메타데이터를 반환합니다. 이 경로는 Azure Resource Graph를
직접 호출하지 않으며 실행자 ID를 전달받지 않습니다.

리소스 중심 요청은 `root=<resource-id>`, `depth=1..8`, `limit=1..1000`을 지정합니다.
프로바이더는 활성 스냅샷과 순서가 보장된 실시간 오버레이에서 허용된 들어오는 및
나가는 링크를 하나의 repeatable-read, 읽기 전용 데이터베이스 트랜잭션 안에서 모두
탐색합니다. 경계가 제한된 neighborhood만 반환하며 리소스 또는 관계 상한에
도달하면 `truncated=true`로 표시합니다. 알 수 없는 루트는 named 화면나
전체 인벤토리로 범위를 넓히지 않고 `404`를 반환합니다. 이 rooted 모드를 사용하면 큰
테넌트 그래프를 전부 로드하지 않고 콘솔에서 리소스를 하나씩 확장할 수 있습니다.
`scope`와 `root`는 함께 사용할 수 없으며 custom `limit`은 `root`와 함께만 허용됩니다.
관계 필터는 반복 `link` 값을 최대 64개까지 허용하며, 각 `link` 또는 comma로
구분된 `include` 값은 파싱 전에 512자로 제한합니다. 같은 깊이에서는 간선을
결정론적으로 정렬하고 frontier 리소스별로 보이지 않은 neighbor를 round-robin 확장하므로,
하나의 high-degree 리소스가 남은 결과 자리를 모두 차지할 수 없습니다. 로컬 및 deployed
프로바이더는 내부 관계도 정렬하고 최대 `max(64, limit * 8)`개 간선을 반환하며,
더 많은 간선이 있으면 neighborhood를 잘린으로 표시합니다.
잘린 상태이면 프로바이더는 `resource_limit`, `adjacent_edge_limit`,
`internal_edge_limit`, `source_limit` 중 안정된 머신 사유를 반환합니다. 알 수 없거나
서로 모순되는 사유 메타데이터는 읽기 경로에서 실패 시 차단 처리합니다.

이 프로젝션은 이름이 지정된 아키텍처 뷰를 제공합니다. `scope` 없는 요청은 권위 있는
`fdai:managed=true`와 `fdai:workload=fdai` 인벤토리 tag 쌍으로 식별된 FDAI 자체
컨트롤 플레인만 반환합니다. 값이 정확히 `fdai`인 모호하지 않은 허용 서비스 tag도 전체
쌍이 없는 보조 로직 리소스를 위한 FDAI 소유권 신호로 예약합니다. containment를
보존하기 위해 상위 리소스 그룹 및 구독 경계를 포함할 수 있지만 관련 없는
리소스는 포함하지 않습니다. 두 소유권 신호가 모두 없으면 전체 구독으로 범위를
넓히지 않고 빈 FDAI 뷰를 유지합니다.

추가 뷰는 결정적 근거를 사용하여 FDAI 외 리소스를 분리합니다.

- **서비스 뷰**: 비어 있지 않은 서비스 tag가 서비스를 식별합니다. 허용되는 키는
  `fdai:service`, `service`, `application`, `app`, `workload`, `azd-service-name`입니다.
  프로바이더는 리소스 이름에서 서비스 ID를 추론하지 않습니다. 허용된 키가 서로 다른
  값으로 확인되면 분류를 모호한 것으로 처리하고 리소스 그룹 대체 경로를
  사용합니다. 하나의 서비스 뷰는 여러 리소스 그룹의 리소스를 포함할 수 있으며
  필요한 상위 경계를 함께 포함합니다.
- **Resource 그룹 대체 경로 뷰**: 리소스에 사용할 수 있는 서비스 tag가 없으면 해당
  리소스를 포함하는 리소스 그룹을 뷰 경계로 사용합니다. 이 대체 경로는 서비스 ID를
  만들어 내지 않고 관찰된 구조를 보존합니다.

`scope=<view-id>`를 지정하면 동일한 CSP-중립 와이어 계약을 유지하면서 해당 뷰의
경계가 제한된 리소스와 링크 집합을 반환합니다. 화면 메타데이터는
`kind=fdai|service|resource_group`과 분류 근거(`ownership_tag`, `service_tag`,
`resource_group_fallback`)를 기록합니다. Named-view 프로바이더는 명시된 화면 id가
등록되지 않았으면 기본값 화면으로 대체하지 않고 `404`를 반환합니다. Console은 기본값
매니페스트를 다시 불러와 등록된 복구 링크를 표시할 수 있습니다. Postgres 운영
변환 결과와 로컬 Azure CLI 변환 결과는 동일한 화면 분류 규칙을 사용하여
로컬 및 deployed 콘솔의 의미를 일치시킵니다.

| CSP / 서브스트레이트 | 인벤토리 소스 | Delta 소스 | 와이어 |
|---|---|---|---|
| Azure | **Azure Resource Graph** (ARM 위 Kusto) | [이벤트버스](#1-이벤트버스-계약--kafka-와이어-프로토콜)를 통한 Activity Log 리소스 변경, Huginn 정규화, ordered 오버레이 변환 결과 | HTTPS + `Authorization: Bearer <OIDC>` |
| AWS *(TBD)* | AWS 구성 + Resource Explorer | 구성 configuration-item 스트림이 Kafka 로 포워드 | HTTPS + SigV4 |
| GCP *(TBD)* | Cloud Asset 인벤토리 | Asset 피드 가 Kafka 로 포워드 | HTTPS + Google IAM |
| Any K8s | 리소스-모델 번역기를 통한 `apiserver` list-watch | `watch` 스트림이 Kafka 로 포워드 | HTTPS + service-account 토큰 |

**규칙 (MUST):**

- 코어는 `shared/providers/` 에 주입된 `Inventory` 인터페이스를 통해서만 인벤토리를 읽음
  ([project-structure-ko.md § 주입 가능한 Seams](project-structure-ko.md#주입-가능한-seams)).
  `ResourceManagementClient`, `ArmClient`, `boto3.client("config")`, `google.cloud.asset`
  - 클라우드-인벤토리 SDK 는 `core/` 에 생김 안 함.
- 레코드는 와이어에서 **CSP-중립**: `Resource.type` 은 정본 `resource_type`
  어휘 ([rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md#수집-소스))
  이며 링크 종류는 `shared/contracts/ontology/link-type.json` 에 선언된 것. 벤더-네이티브
  id 는 Resource 의 민감정보가 제거된 `provider_ref` 필드에 타고 올 수 있음 - 절대 기본 키 아님.
- **초기 full 스냅샷 은 바운드된 동시성으로 병렬화**: 어댑터는 워크로드를
  `ResourceType` 으로 샤딩 (하나의 타입이 너무 넓으면 스코프로 더 세분화), semaphore 하에서
  동시 확산 쿼리, 배치를 ingest 파이프라인으로 스트리밍. 코어는 절대 단일-연결 블로킹
  스캔을 가정하지 않음.
- **완전한 ARG 읽기는 1,000개 이후에도 페이지를 계속 조회합니다.** Azure Resource Graph는
  응답 하나에 최대 1,000개 레코드를 반환합니다. 완전한 결과가 필요한 어댑터는 `$top`을
  최대 1,000으로 설정하고, 구성된 페이지 상한 안에서 각 `$skipToken`을 끝까지 따라가며,
  인벤토리 `id` 또는 deployment-history `row_id` 같은 고유 projected 키로 정렬합니다.
  각 페이지는 조회 할당량 하나를
  소비합니다. JSON 변환 결과 전에 raw 응답을 페이지당 10 MB, 조회당 64 MB로 제한합니다.
  토큰 반복, 페이지 상한 초과, 이어가기 토큰 없는 `resultTruncated=true`는
  읽기가 불완전한 것으로 보고 실패 시 차단 처리합니다. 반면 범위가 제한된 interactive 읽기는 명시된
  결과 상한보다 하나 더 요청하고 잘림을 표시합니다. 자세한 내용은
  [페이지 나누기 지침](https://learn.microsoft.com/azure/governance/resource-graph/concepts/paging-results)을
  참조하세요.
- **ARG 호출은 서비스 할당량 신호를 따릅니다.** 어댑터별 shared 게이트는 모든 응답의
  `x-ms-user-quota-remaining`과 `x-ms-user-quota-resets-after`를 읽고 할당량이 0이면 동시
  샤드를 지연합니다. HTTP `429` 재시도는 `Retry-After`만큼 기다립니다. 전송 계층 실패,
  `408`, 일부 `5xx` 응답에는 범위가 제한된 exponential 재시도 대기를 적용합니다. 재시도를 모두 사용하면
  부분 결과를 publish하지 않고 실패 시 차단 처리합니다. Azure가 할당 할당량을 변경할 수
  있으므로 고정 query-rate 상수는 사용하지 않습니다. 자세한 내용은
  [Throttled 요청 지침](https://learn.microsoft.com/azure/governance/resource-graph/concepts/guidance-for-throttled-requests)을
  참조하세요.
- **멱등 세대 저장**은 완전한 검사를 `inventory_snapshot_resource`와
  `inventory_snapshot_link`에 단계하며, 세대와 중립 `resource_id` 또는
  `(from_id, link_type, to_id)`를 키로 사용합니다. 완전한 fence가 `inventory_active`
  포인터를 원자적으로 교체합니다. 순서가 보장된 변경은 다음 세대가 포함할 때까지
  `inventory_realtime_resource`와 `inventory_realtime_link`에 저장됩니다. 읽기 담당은 활성
  세대와 오버레이를 하나의 유효한 온톨로지 형태 리소스 그래프로 병합하며, 스캔된
  리소스를 범용 `ontology_resource` 및 `ontology_link` 인스턴스 저장소에 이중 기록하지
  않습니다. 스냅샷 staging은 리소스와 링크를 기본 1,000-row 조각으로 변환하고 기록하며,
  검증된 상한은 10,000입니다. 하나의 입력 배치에 속한 모든 조각은 같은 데이터베이스
  트랜잭션 안에서 처리합니다. 검증과 엔드포인트 locking 이후 하나의 delta 이벤트는
  reconciled realtime 링크 upsert 전체를 한 번의 batched `executemany` 파이프라인으로 보내며,
  집계 applied-row 개수를 유지합니다. 엔드포인트 리소스 id는 deduplicate 및 sort한 뒤
  하나의 ordered PostgreSQL 구문으로 잠금하므로, 엔드포인트마다 클라이언트 왕복을 만들지
  않으면서 deadlock-safe 순서를 보존합니다.
- **실패 시 차단**: 부분 스냅샷 은 stale 그래프가 자율 결정을 구동하는 상태에 절대
  런딩하지 않음. 스냅샷 이 완료되고 원자적으로 승격되거나, 이전 그래프가 유지되고
  실패가 감사됨.
- **Delta 는 별도 사이드-채널이 아니라 이벤트 버스를 통해 흐름**. 프로바이더 변경 신호
  (Activity Log, 구성 항목, Asset 피드, apiserver watch) 는 Kafka 토픽으로 포워드되어
  다른 `Signal` 과 정확히 같이 소비 - 동일한 멱등성, 동일한 DLQ.
- **Delta 정렬은 활성 스냅샷으로 fence합니다.** 활성 세대 시작 시각 이전 또는
  같은 관측은 이미 반영된 것으로 보고 no-op 처리하며, 설정된 server-clock skew보다
  미래인 관측은 거부합니다. Resource와 링크 엔드포인트 타입은 모두 활성 커버리지에
  속해야 하고 이벤트별 링크 개수를 제한합니다. 관측 시각이 같으면 삭제가 upsert보다
  우선하므로 재생이 tombstone 리소스를 되살리지 않으며 같은 종류는 이벤트 id로 결정합니다.
- **Huginn은 실시간 발견 유입을 소유**하고 프로바이더 어댑터는 cloud 파싱과
  지점 enrichment를 소유합니다. 인벤토리 projector는 영속 리소스, 링크, tombstone
  적용을 소유합니다. Heimdall은 최신성, 전달 lag, 대체 경로, 커버리지 성능 저하를
  관찰하며 cloud 인벤토리를 직접 조회하지 않습니다.
- **주기적 조정은 계속 필요합니다.** 인벤토리 sync 작업은 기본 6시간 주기로
  완전한 ARG/ARM 세대를 만들고 원자적으로 promote하며, 해당 세대에 이미
  반영된 오버레이 항목을 정리합니다. Delta 스트림만으로 완전성을 증명하지 않습니다.
  작업은 10분마다 영속 시도 상태를 확인하지만 6시간 간격이 due이거나 newer 시도가
  실패 또는 포기된 경우에만 검사합니다. 읽기 전용 인벤토리 신원을 유지하며 Heimdall은 프로바이더를
  직접 조회하거나 작업을 시작하지 않습니다.
- **미인식 `ResourceType` 또는 LinkType** 은 이슈를 열고 드롭됨; 어댑터는 런타임에 새
  온톨로지 타입을 자동 등록하지 않음
  ([llm-strategy-ko.md § 포크 확장](llm-strategy-ko.md#포크-확장-self-extending-온톨로지)).
- 신뢰할 수 없는 벤더 속성 (태그, 설명) 은 추가 전에 redact 또는 길이-상한화되어
  있어야 하며 inert 데이터이지 지시가 아님.

**Anti-patterns (MUST NOT):**

- `core/` 에서 `azure-mgmt-*`, `boto3`, `google-cloud-*` 클라이언트 가져오기.
  클라우드 인벤토리 SDK 는 프로바이더 어댑터 패키지에만 있어야 함.
- Kusto / ARG 쿼리를 `core/` 코드 경로에 임베드 (그것들은 매니페스트 / 쿼리 템플릿이
  구동하는 Azure 어댑터에 속함).
- 초기 full 검사 을 글로벌 락 하에 실행하거나, 실행기 의 per-resource 락 하에서 실행;
  인벤토리 sync 와 교정 실행은 독립적 동시성 예산을 가진 별개 관심사.
- 부분 delta 스트림만을 권위 있는 로 신뢰; 다운된 이벤트를 잡으려면 주기 full-snapshot
  조정 이 필수.

### 제한적인 NSG egress 환경의 Azure 인벤토리

NSG로 잠긴 서브넷 때문에 도달할 수 없는 디스커버리 소스가 빈 인벤토리로 바뀌면 안 됩니다.
FDAI는 네트워크 도달성, 아이덴티티, 수집, 프로젝션을 별도 단계로 취급하고 실패한 단계를
기록합니다. 성공한 빈 스냅샷은 "범위에 리소스 없음"을 의미합니다. 차단된 엔드포인트, 토큰
실패, 불완전한 페이지 집합, 사용할 수 없는 수집기는 "인벤토리 사용 불가"를 의미하며 마지막
완전한 스냅샷을 유지합니다.

#### 필수 네트워크 경로

운영자 랩톱이 아니라 디스커버리를 실행할 서브넷과 아이덴티티에서 도달성 프로브를 실행하는
것이 좋습니다. 정확한 규칙은 런타임과 Azure 클라우드에 따라 다르지만 배포에서는 다음 경로를
고려합니다.

| 목적 | 기본 경로 | 제한된 네트워크 옵션 | 참고 |
|---|---|---|---|
| ARG 및 ARM 관리 읽기 | Azure Resource Manager 엔드포인트로 HTTPS `:443` | `AzureResourceManager` 서비스 태그로 NSG egress 허용; 좁은 관리 엔드포인트 허용 목록이 있는 Azure Firewall 또는 승인된 프록시를 통한 UDR; 대상 클라우드, 리전, 필수 ARG 작업이 지원하는 경우 Resource 관리 Private Link | 데이터 서비스용 비공개 엔드포인트는 ARM 또는 ARG 연결을 제공하지 않습니다. Azure 서비스 엔드포인트는 ARM 관리 경로를 대체하지 않습니다. |
| 워크로드 토큰 | 런타임 제공 managed 신원 또는 워크로드 신원 엔드포인트 | IMDS를 사용하는 경우 `AzurePlatformIMDS`를 포함한 런타임 플랫폼 아이덴티티 경로 허용; 앱 서브넷에서 토큰을 발급할 수 없으면 승인된 러너의 federated 워크로드 신원 사용 | 디스커버리만을 위해 광범위한 인터넷 egress나 클라이언트 시크릿을 추가하지 않습니다. |
| DNS | Azure 제공 DNS 또는 승인된 custom 해석기 | 해당되는 경우 `AzurePlatformDNS`를 포함한 런타임 플랫폼 DNS 경로 허용; 허브 해석기를 통해 필요한 공개 또는 Private Link 영역 전달 | 스캔을 시작하기 전에 엔드포인트 해석 및 TLS 프로브를 실행합니다. DNS 성공만으로 도달성이 증명되지는 않습니다. |
| 스냅샷 게시 | 비공개 PostgreSQL 및 Event Hubs 경로 | 디스커버리 러너에서 비공개 엔드포인트, VNet 피어링 또는 허브 라우팅 사용 | 수집기는 공개 콘솔 엔드포인트를 통해 인벤토리를 보내지 않습니다. |

서비스 태그와 Resource 관리 Private Link 기능은 Azure 클라우드에 따라 다를 수 있고
시간이 지나면서 변경될 수 있습니다. 배포 preflight에서 effective 경로, DNS 응답, 지원되는
작업을 확인하는 것이 좋습니다. 복사한 IP 범위보다 서비스 태그 또는 비공개 연결을 우선하고,
Azure 엔드포인트와 클라이언트 trust 모델을 명시적으로 검증하지 않았다면 TLS interception을
피합니다.

#### 순서가 지정된 폴백 단계

선언된 범위에 대해 완전하고 제한된 스냅샷을 생성할 수 있는 첫 번째 방법을 사용합니다. 전송
방식이 바뀌어도 `Inventory` 계약은 바뀌지 않습니다.

1. **런타임 서브넷의 ARG** - 명시적으로 허용된 ARM 관리 경로에서 managed 신원으로
   샤딩된 `Resources` 쿼리를 실행합니다. 광범위한 리소스 간 디스커버리와 제한된 페이지
   처리를 제공하므로 기본값으로 유지합니다.
2. **연결된 디스커버리 작업의 ARG** - 애플리케이션 서브넷에 의도적으로 관리 평면 egress가
   없다면 동일한 읽기 전용 어댑터를 VNet 통합 Container Apps 작업 또는 자체 호스팅 ops
   실행기로 이동합니다. 배치를 비공개 상태 저장소 또는 Kafka 유입에 게시합니다.
   이 작업에 콘솔 또는 코어 실행기 신원을 부여하지 않습니다.
3. **Resource 관리 Private Link 경로** - Azure가 필요한 ARG 호출을 지원하는 곳에서는
   연결된 작업을 승인된 비공개 엔드포인트 및 비공개 DNS를 통해 라우팅합니다. 비공개 DNS
   해석만으로 작업 지원을 증명할 수 없으므로 preflight에서 실제 제한된 ARG 쿼리를
   실행합니다.
4. **직접 ARM 목록 어댑터** - ARG를 사용할 수 없거나 최신성 예산을 초과하면 등록된 각
   리소스 프로바이더 및 리소스 타입을 제한된 페이지 단위 샤드로 나열합니다. 어댑터는
   동일한 리소스 및 링크 기록으로 정규화하고 지원되지 않는 타입을 커버리지 공백으로
   보고합니다. Azure CLI와 Azure SDK 클라이언트는 이 방법의 전송 수단이며 독립 인벤토리 소스가
   아닙니다.
5. **범위가 명시된 권위 있는 인벤토리** - 커버리지 매니페스트가 권위 있는으로 선언한
   리소스 타입 및 구독에만 Microsoft Defender for Cloud 인벤토리 또는 승인된
   다른 Azure 인벤토리 변환 결과를 사용합니다. 보조 발견 사항은 전체 estate 커버리지를
   의미하지 않습니다.
6. **변경 스트림 연속성** - full-snapshot 출처를 일시적으로 사용할 수 없는 동안 Event
   Hubs를 통해 전달된 Activity Log 변경을 계속 소비합니다. Delta는 알려진 리소스의
   최신성을 유지하지만 그래프를 초기화하거나 보이지 않는 리소스가 없음을 증명할 수
   없습니다.
7. **선언적 복구 스냅샷** - 실제 운영 관리 경로를 사용할 수 없으면 승인된 Terraform
   상태/계획 내보내기, Azure 배포 내보내기 또는 서명된 declarative 인벤토리 파일을
   가져옵니다. 이를 `observed`가 아닌 `expected`로 표시하고 생성 시간과 범위를
   첨부하며 읽기 전용 맥락에만 사용합니다. 자율 교정을 승인할 수 없습니다.

이 단계는 "모든 소스를 시도하고 행을 합치는 방식"이 아닙니다. 각 시도는 출처,
구독 또는 management-group 범위, 리소스 타입, 시작 및 완료 시간, 페이지 수,
오류를 포함하는 커버리지 매니페스트를 생성합니다. FDAI는 선언된 모든 샤드가 최종 fence에
도달한 뒤에만 소스를 승격합니다. 우선순위가 낮은 소스는 선언된 커버리지에서 사용할 수 없는
소스를 대체할 수 있지만 알 수 없는 공백을 조용히 채우거나 더 최신 권위 있는 기록을
덮어쓸 수 없습니다.

Azure 구현은 모든 neutral 리소스 id 앞에 구독 범위의 opaque 해시를 붙입니다.
따라서 서로 다른 구독에서 동일한 resource-group 및 리소스 경로를 사용해도 충돌하지
않고 온톨로지 키에 구독 id를 노출하지 않습니다. ARG는 `contains`, `attached_to`,
`depends_on` 토폴로지를 제공합니다. Direct ARM 대체 경로는 현재 `contains` 커버리지만 선언하므로
활성 변환 결과는 누락된 링크 종류를 보고하고 의존성 부재 결정에서 degraded 상태를
유지합니다.

#### 실패 및 최신성 정책

- **Preflight 우선:** 예약을 활성화하기 전에 토큰 발급, DNS, TCP/TLS, 제한된 쿼리 하나,
  페이지 나누기, 비공개 변환 결과 쓰기 접근을 검증합니다.
- **실패 분류:** `network_blocked`, `dns_failed`, `token_failed`, `forbidden`, `throttled`,
  `partial`, `source_unavailable`을 구분합니다. Zero-row 결과를 오류 폴백으로 사용하지 않습니다.
- **마지막 정상 상태 유지:** 실패하거나 부분적인 스캔은 마지막 완전한 스냅샷을 유지하고
  stale로 표시합니다. 빈 그래프로 교체하지 않습니다.
- **권한 유지:** 오래된 시도, 같은 실행의 낮은 우선순위 출처 또는 `expected`
  declarative 후보는 더 최신 관찰된 스냅샷을 교체할 수 없습니다.
- **자율성 저하:** 스냅샷 age가 설정된 최신성 예산을 초과하면 그래프 기반 영향
  radius 결정과 부재 주장을 사람 검토로 이동합니다. 읽기 전용 화면은 출처, age, 범위,
  degraded 상태를 표시하는 경우 stale 그래프를 사용할 수 있습니다.
- **principal 분리 유지:** 발견 신원에는 선언된 범위의 최소 읽기 권한만
  부여합니다. Privileged 실행기, 콘솔 신원, 승인 principal과 분리합니다.
- **전환 감사:** 출처 선택, 대체 경로 활성화, 커버리지 손실, 복구, 스냅샷 승격은
  구조화된 감사 기록과 메트릭을 생성합니다.

예: NSG가 애플리케이션 서브넷에서 ARM으로 향하는 직접 egress를 거부합니다. Preflight는
`network_blocked`를 보고하고 예약된 스캔은 VNet 통합 ops 실행기로 이동합니다. ARG는 허브의
승인된 관리 경로를 통해 완료되고 최종 완전한 스냅샷만 승격됩니다. 실행기도 도달성을 잃으면
FDAI는 이전 그래프를 유지하고 stale로 표시하며 blast-radius 종속 액션을 사람 검토로
라우팅합니다.

## 6. 메트릭 조회 계약 - CSP-Neutral 샘플 Iterator

외부 메트릭 (Prometheus, Azure Monitor Logs, CloudWatch, Datadog) 을
`MetricProvider.query(MetricQuery) -> AsyncIterator[MetricPoint]`
([`shared/providers/metric.py`](../../../services/core-control-plane/src/fdai/shared/providers/metric.py))
로 소비. `MetricQuery` 는 벤더 중립적인 (`metric_name`, `labels`, `since`, `until`,
`aggregation` 힌트); 어댑터는 CSP-neutral 이름을 벤더 이름 공간 로 매핑하고 힌트를
최선 노력 로 honor. 업스트림 은 `NoopMetricProvider` (빈 결과) + `StaticMetricProvider`
(테스트 double) 를 ship; Azure 어댑터 는 `delivery/azure/` 아래 land.

**Design 룰:**

- 비동기 by 계약 (외부 메트릭 조회 는 I/O-bound; 그렇지 않으면 이벤트 루프 를 블록 -
  § 1 / § 3 / § 4 / § 5 와 동일한 discipline).
- 빈 결과는 valid 답 (구간 내 샘플 없음 ≠ 오류).
- 호출자 는 부분 결과 로 auto-remediate MUST NOT; abstain 하고 HIL 로 경로 -
  [architecture.instructions.md § 안전성 Invariants](../../../.github/instructions/architecture.instructions.md#safety-invariants)
  per.

## 7. 로그 조회 계약 - 구조화된 로그 Records

구조화된 로그 (Log Analytics KQL, Loki LogQL, Elasticsearch, CloudWatch Logs) 를
`LogQueryProvider.query(LogQuery) -> AsyncIterator[LogRecord]`
([`shared/providers/log_query.py`](../../../services/core-control-plane/src/fdai/shared/providers/log_query.py))
로 소비. `expression` 필드는 vendor-specific 쿼리 문자열; `labels` 는 어댑터가 라벨
표면 에 매핑하는 CSP-neutral pre-filter. `core/` 에 tail 을 hard-code 하지 않고
CSP-neutral 필터 와 vendor-specific tail 을 compose 할 수 있도록 분리 유지.

## 8. 추적 조회 계약 - Distributed-Trace Spans

구간 (App Insights, Tempo, Jaeger, Honeycomb) 을
`TraceQueryProvider.query(TraceQuery) -> AsyncIterator[Span]`
([`shared/providers/trace_query.py`](../../../services/core-control-plane/src/fdai/shared/providers/trace_query.py))
로 소비. `Span` 은 `trace_id`, `span_id`, `parent_span_id`, `service`, `operation`,
`start`, `duration`, `status`, 그리고 CSP-neutral `labels` 를 carry - RCA 가 어떤
백엔드 가 기록했는지 모른 채 서비스 를 가로질러 요청 를 walk 가능.

**§ 6 - § 8 공통 Design 룰:**

- 세 telemetry-ingestion 프로토콜 은 anomaly detection, SLO burn-rate evaluation, RCA
  가 룰 / 정책 인용 뿐만 아니라 real 텔레메트리 에 ground 하도록 존재. Design
  계약 는 [scope-expansion-ko.md § 3.2](../fork-and-sequencing/scope-expansion-ko.md) 에.
- 업스트림 기본값 는 no-op 프로바이더 - 어떤 구체적인 어댑터 도 wire 되기 전에
  다운스트림 소비자 가 안정된 인터페이스 로 작성자 가능.
- 벤더 SDK 가져오기 는 `delivery/<vendor>/` 에 confined; `core/` 는 프로토콜 만 가져오기 -
  [`scripts/quality/architecture/check-core-imports.sh`](../../../scripts/quality/architecture/check-core-imports.sh) 에 의해 강제.

## Azure-Phase 실현 (요약)

오늘의 구현은 다섯 foundational 계약에 다음과 같이 슬롯됩니다. 명명된 각 서비스는 **채택 시점에 재확인할
권장사항** 이지만 ([tech-stack-ko.md](tech-stack-ko.md)) 계약 자체는 바뀌지 않습니다.

| 계약 | Azure 실현 | Idle 비용 자세 |
|---|---|---|
| 이벤트버스 | **Event Hubs Standard** (`:9093` Kafka 엔드포인트, 1 TU, auto-inflate off) | 낮은 idle; TU 로 스케일 |
| 런타임 | **Container Apps** (Consumption, KEDA scale-to-zero) - 앱 하나 + 사이드카 | idle 시 `$0` |
| 시크릿 | Container Apps native 시크릿 + **Key Vault 참조** | 무시할 수준 |
| 워크로드 아이덴티티 | **User-assigned MI** + CI/CD 를 위한 워크로드 신원 federation | 무료 |
| 인벤토리 | **Azure Resource Graph** (`resource_type` 으로 샤딩된 초기 병렬 full-scan) + 이벤트 버스로 포워드된 **Activity Log** delta | ARG 무료; 로그 기반 delta 는 observability 인벤토리에 포함 |

`Service Bus` 와 `Event Grid` 는 앞으로 최소 인벤토리에 **포함되지 않습니다**. 이벤트버스는
Kafka 와이어 전용입니다. 프로바이더 네이티브 pub/sub 은 오직 **Kafka 버스로 이벤트를 넣는
소스** (예: Event Hubs Kafka 토픽으로 forward 하는 Event Grid 구독) 로만
사용되고, 절대 `core/` 의 런타임 의존이 아닙니다.

## 승인된 대안 Azure 구현(Approved 대안 Azure Implementations)

Foundational 계약과 인접 platform 경계가 코어를 CSP-이식 가능하게 유지합니다. 이 표는
각 경계가 `core/`를 건드리지 않고 스왑할 수 있는 **Azure 내부** 대안을 나열합니다. 스왑은
**infra 모듈 경계**에서 일어남 - 포크 가 `infra/modules/<seam>/` 아래 다른 서브-모듈을
고르거나 (또는 순수 코드 레벨 변경이면 조립 루트에서 DI 바인딩 오버라이드).
"유지되는 것" 컬럼의 모든 것은 계약이지 구현이 아니며 스왑 전체에서 보존됩니다;
"변하는 것" 은 스왑된 모듈과 그 즉시 구성 에 국한됩니다.

| 경계 | Day-zero 기본 | 승인된 대안(Azure) | 스왑 시 변경 | 유지되는 것(계약) |
|------|--------------|-------------------|-------------|-------------------|
| Event 버스 | Event Hubs Standard (Kafka `:9093`) | **Strimzi** 통한 AKS 위 Kafka; **Confluent Cloud** (멀티 클라우드 관리형); AKS 위 **Redpanda** | 브로커 엔드포인트, 인증 메커니즘, 비용 프로파일 | Kafka 와이어 프로토콜, 토픽 + DLQ 명명(`<topic>.dlq`), 멱등성 키, partition-key로 순서 |
| 런타임 | Container Apps (Consumption + KEDA) | **AKS** + Knative Serving + KEDA; 버스트/바인딩용 **Azure Functions** (Premium 계획); 공개 HTTPS 표면 필요 시 **App Service** | 스케일 트리거 렌더링, 프로브 배선, 사이드카 레이아웃 | OCI 이미지, Knative 호환 매니페스트 서브셋, `/healthz` + `/readyz` 계약, `scale-on:kafka-lag` 신호 |
| 상태 저장소 | PostgreSQL Flexible + `pgvector` | RU-미터링과 지역 쓰기가 단일 기본을 초과할 때 **Cosmos DB** (SQL API); TDE / SQL-Server 호환이 필수일 때 **Azure SQL Managed Instance** | SQL 방언, 마이그레이션 도구, RU 비용 모델 | 감사 hash-chain 스키마, 버전된 이벤트/액션/룰 계약, `SchemaRegistry`+`ContractValidator` 경계 |
| Vector 저장소 | `pgvector` (상태 저장소와 co-located) | **Azure AI Search** 벡터 인덱스; AKS 위 **Qdrant** / **Milvus** | 인덱스 타입(HNSW/IVFFlat), 거리 메트릭, 새로 고침 경로 | 임베딩 차원, 모델 선택(설정), T1 유사도 임계값 |
| 시크릿 | Container Apps native `secret` + Key Vault 참조 | Key Vault 를 가리키는 `SecretStore` CRD 로 **AKS + 외부 Secrets Operator**; FIPS-규제 데이터용 **Key Vault Premium** (HSM-backed) | 주입 레이어(Container Apps native ↔ ESO) | env-var-only 읽기, upper-snake env 이름, 시작 시 실패 시 차단, `core/` 에 SDK 호출 없음 |
| 워크로드 신원 | User-assigned MI | **Federated 워크로드 신원** (GH Actions OIDC ↔ Entra federated 자격 증명; AKS 워크로드 신원 federation); 리소스 principal 이 단일-소유자일 때 **System-assigned MI** | trust 설정과 토큰 대상 | `WorkloadIdentity` 인터페이스, JIT-스코프 롤, cross-domain assumption 거부 |
| Container 레지스트리 | ACR Basic | **ACR Standard/Premium** (지역 replication, 프라이빗 엔드포인트); 외부 레지스트리로 **GHCR** 또는 **Docker 허브** | 티어 비용, 서명 + 증명 위치 | pin-by-digest, `latest` 없음, SBOM + 출처 이력 기록 |
| Observability | Log Analytics workspace + 여기 바인딩된 App Insights | 독립형 Application Insights; **Grafana Managed for Azure** + Prometheus + Loki; OTel 내보내기 도구 뒤의 벤더 APM | 대시보드, 알림 규칙, 보존 가격 | OpenTelemetry SDK, `correlation_id`, KPI 당 하나의 원격측정 소스 |
| HIL 채팅 | Bot Framework / Teams 통한 Azure Bot(Free) | Container App 위 **커스텀 웹훅 어댑터**; [`chatops`] 전달 어댑터 통한 Slack 네이티브 봇 | 인증된 전송, Adaptive 카드 렌더러 | approval-message 계약, action-bound HIL id, 실패 시 차단 타임아웃 |
| 읽기 전용 콘솔 호스팅 | Static Web Apps (Free) | Storage static-website + **Front Door**; **App Service Static Sites** | HTTPS 표면, 커스텀 도메인 배선 | 읽기 전용 보장, Entra sign-in, privileged 호출 없음 |
| 인벤토리 | Azure Resource Graph + Activity Log delta | ARG 가 느린 테넌트용 **ARM 목록** 폴링 (per-resource-type, 샤딩된); 대상 집합에 권위 있는 하다면 **Microsoft Defender for Cloud 인벤토리** | 쿼리 언어 (Kusto vs REST), delta 커서 시망틱스, 최신성 lag | `Inventory` 프로토콜 모양, CSP-중립 `resource_type` + 링크 종류, 멱등 upsert, 부분 스냅샷 실패 시 차단 |

**전체 표에 걸친 규칙 (MUST):**

- 모든 대안은 기본 모듈이 노출하는 **같은 출력 계약** 을 사용 (`endpoint`,
  `identity_resource_id`, `secret_ref_envelope`, `event_topic_names`, ...) 하므로 다운스트림
  Terraform / `main.tf` 조립 이 대안에 따라 분기하지 않음.
- 대안은 **별도 Terraform 서브-모듈** 로 `infra/modules/<seam>/` 아래 배송, 최상위
  `var.<seam>_kind` (예: `var.runtime_kind = "container_apps"`) 로 선택.
- 어떤 대안도
  [deploy-and-onboard-ko.md § 리소스 명명 규약](../deployment/deploy-and-onboard-ko.md#리소스-명명-규약resource-naming-convention)
  을 지켜야 함; 스왑이 손으로 뽑은 이름을 허용하지 않음.
- 대안은 **필요할 때 빌드** - W4.1 과 함께 기본만 랜딩. 대안 추가는 자체 PR, 자체 shadow-mode
  검증.
- 어떤 대안도 `core/` 에 벤더 SDK 의존을 재도입할 수 없음. 이것은 원래의 CSP-중립성 규칙이고
  이깁니다.

## 비-Azure 경로 (가산)

다른 CSP 를 추가하는 것은 **포크 수준 구성 작업** 이며 코어 변경이 아닙니다:

1. 조립 루트 에서 `shared/providers/` 의 여덟 프로바이더 인터페이스 새 구현을
   등록 ([project-structure-ko.md](project-structure-ko.md#customization-via-dependency-injection)).
2. `bootstrap.servers`, `SecretProvider`, `RuntimeAdapter`, `WorkloadIdentity`, `Inventory`,
   `MetricProvider`, `LogQueryProvider`, `TraceQueryProvider` 바인딩을 새 CSP로 지시.
3. 같은 OCI 이미지 + Knative 호환 매니페스트를 대상 런타임으로 렌더링.
4. Azure 구현과의 동등성 가 측정될 때까지 **shadow 모드** 로 배송
   ([architecture.instructions.md](../../../.github/instructions/architecture.instructions.md#safety-invariants)).

**비-Azure 대상은 TBD 로 남아있음**
([구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must));
계약은 미래 어댑터가 가산 하도록 존재.

## Anti-Patterns (간결)

- 각 CSP 의 native pub/sub (`Service Bus` + `SQS/SNS` + `Pub/Sub`) 을 하나의 인터페이스
  뒤에 감싸는 것. Ack 시맨틱, 정렬 키, DLQ 모양, exactly-once 동작이 충분히 다르므로
  프로바이더 특이 버그가 새어나옴 - **대신 하나의 와이어 프로토콜 (Kafka) 사용**.
- **Dapr** 를 portability 레이어로 도입. 락인이 CSP 에서 Dapr 로 옮겨질 뿐이고 사이드카
  의존이 추가되며 로컬 개발이 복잡해짐.
- "Kafka 클라이언트 복잡성을 아끼려고" **Event Hubs 를 native AMQP SDK 로** 사용. 코드가
  다시 Azure 화됨. Kafka 엔드포인트 를 쓰거나 Event Hubs 를 쓰지 마세요.
- 애플리케이션 코드에서 `SecretClient` 호출로 시크릿 읽기 (계약 3 참조).
- `core/` 안의 `DefaultAzureCredential()` (또는 동등물) (계약 4 참조).

## 관련 문서

| 학습 대상 | 문서 |
|-----------|------|
| 이 계약을 실현하는 구체 스택 | [tech-stack-ko.md](tech-stack-ko.md) |
| 계약에서 렌더링되는 Azure 리소스 인벤토리 | [deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set](../deployment/deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set) |
| 신원 모델과 시크릿 취급 심층 | [security-and-identity-ko.md](security-and-identity-ko.md) |
| 각 계약을 조립 루트에 노출하는 DI 경계 | [project-structure-ko.md#주입-가능한-seams](project-structure-ko.md#주입-가능한-seams) |
