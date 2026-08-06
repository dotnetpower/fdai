---
translation_of: service-graduation-and-ownership.md
translation_source_sha: 41bc75a0c6dbef92d5cd7bf6c2383868482145df
translation_revised: 2026-08-07
---
# 서비스 승격과 데이터 소유권

이 문서는 FDAI package를 독립 배포 service로 전환할 수 있는 시점을 결정합니다. 또한 process
분리가 숨은 authority 또는 두 번째 writer를 만들지 않도록 cross-process contract, durable data,
identity, migration을 할당합니다.

> **결정 범위:** Package boundary가 service를 의미하지는 않습니다. 승격에는 측정된 forcing
> trigger 하나와 아래의 모든 readiness gate가 필요합니다. Evidence가 없으면 보류하고 authority,
> ownership, transport 또는 rollback 위반이 있으면 거절합니다.
>
> **Evidence 범위:** Synthetic test는 mechanics를 증명합니다. Production scale 증가는 승격할
> 정확한 image, topology, identity, schema, contract version의 현재 staging 또는 live smoke
> evidence가 필요합니다.
>
> **프로그램 목표:** 현재 decomposition 프로그램은 5개 runtime service로 완료합니다. Isolated
> Executor는 필수 목표이지만 모든 binary gate를 통과한 후에만 effect authority를 받습니다.
> Evidence가 부족하면 안전하지 않은 cutover를 허용하지 않고 프로그램 완료를 차단합니다.

## 설계 개요

Candidate는 scaling, privilege isolation, failure isolation trigger 중 하나 이상을 충족하고 모든
contract, durability, observability, cost, rollback gate를 통과해야 **승인**됩니다. Trigger가 측정되지
않았거나 evidence가 불완전하면 **보류**됩니다. Direct agent call, shared mutable coordination,
multiple writer, executor identity 확산, unversioned wire contract 또는 테스트된 rollback 부재를
만들면 **거절**됩니다. 현재 deployment에는 4개 runtime service가 있습니다. 추적되는 목표는
Isolated Executor를 다섯 번째 service로 추가하고 authority cutover에서 Core의 mutation role을
제거합니다.

## 승격 scorecard

모든 측정 row에 동일한 observation window와 candidate revision을 사용합니다. Binary privilege
requirement로 기다리는 것이 안전하지 않은 경우를 제외하고 최소 window는 연속 30일입니다. Raw
evidence link, query version, source freshness, window start/end, measurement cutoff, candidate
revision, reviewer, digest, approval time, expiry를 [Architecture Review Board Packet](architecture-review-board-ko.md#ownership과-support)의 evidence-binding format에 기록합니다.

| Gate | 승인 threshold | Evidence source |
|------|----------------|-----------------|
| Scaling trigger | 2주 동안 주 3개의 별도 30분 window에서 p95 CPU >= 70% 또는 p95 memory >= 75%, 또는 3개 window에서 queue-delay p95가 SLO 초과 | Container Apps / OpenTelemetry resource metric과 queue dashboard |
| Privilege trigger | Split이 parent process에서 cloud role assignment, secret, database write grant 또는 public ingress permission을 하나 이상 제거 | Terraform plan, identity graph, database privilege query |
| Failure trigger | Candidate가 90일 동안 독립 검토된 incident 2개 이상 또는 parent service error-budget burn의 10% 이상 유발 | Incident ledger, SLO burn report, post-incident review |
| Typed transport | 모든 cross-process message에 owner, versioned schema, producer, consumer, stable partition key, additive compatibility policy, retry/DLQ, idempotency rule, retention 존재 | Contract registry, compatibility test, event-bus configuration |
| Durability | Process loss, duplicate, reorder, scale-out, scale-in test에서 duplicate terminal effect 0건이며 authority gate를 건너뛰지 않음 | Durable store/CAS test와 restart smoke |
| Observability | 독립 liveness/readiness와 latency, queue/lag, error, retry, DLQ, ownership-conflict signal이 있고 필수 alert가 책임 owner에게 route | Health probe, telemetry catalog, alert rule, runbook |
| Cost | 월별 incremental cost를 측정하고 승인된 environment budget 안에 유지. Parent service cost의 20%를 넘는 delta는 FinOps 승인 필요 | Terraform cost estimate와 측정된 billing baseline |
| Rollback | Staging rehearsal에서 offset reset, data loss, duplicate terminal effect, authority 변경 없이 15분 안에 이전 topology 복원 | Timed rollback receipt와 post-rollback smoke |
| Identity ceiling | Privilege가 다르면 새 role에 전용 identity를 사용하고 non-executor role은 Thor identity 또는 executor role을 획득할 수 없음 | Terraform identity/RBAC assertion과 effective-access probe |

실패한 binary gate를 weighted score로 보상할 수 없습니다. 승인된 split은 exact evidence cutoff을
기록하며 90일 안에 deployment가 시작되지 않으면 만료되어 다시 평가합니다.

## Candidate 결정

다음 결정은 현재 Operator API inventory와 deployed app shape의 package/process candidate에
scorecard를 적용한 결과입니다.

| Candidate | 현재 결정 | 이유와 다음 evidence |
|-----------|-----------|----------------------|
| Isolated Executor | 필수 프로그램 목표, cutover는 gate 적용 | Privilege isolation이 forcing trigger입니다. Effect authority를 Core에서 이동하기 전에 versioned command/receipt transport, durable duplicate/reorder/restart behavior, independent telemetry, cost, effective access, exact-topology smoke, timed rollback을 통과해야 합니다. |
| Operator API `application` service | 보류 | Typed in-process boundary가 있지만 독립 scale, privilege, failure trigger가 측정되지 않았습니다. |
| Operator API read projection | 보류 | Read-only package ownership은 명확하지만 scale trigger 또는 독립 store가 정당화되지 않았습니다. |
| Operator API SSE streaming | 보류 | Versioned relay/replay contract와 측정된 connection isolation benefit이 필요합니다. |
| Document ingestion API | 승인 | Privilege와 scaling isolation, typed transport, role-scoped database access, probe, co-host rollback이 구현됐습니다. |
| Document ingestion worker | 승인 | Durable lease/CAS claim, restart/reorder/DLQ test, internal health, dedicated identity, scale gate가 구현됐습니다. |
| Conversation channel runtime | 보류 | Durable delivery coordination은 in-process이며 standalone adapter ingress, identity, persistence binding, deployment smoke가 아직 bind되지 않았습니다. |
| Background read-task executor | 보류 | Durable attempt는 있지만 독립 cost/failure trigger와 deployed transport evidence가 측정되지 않았습니다. |
| Scheduler, inventory, measurement, canary job | Job으로 승인 | Bounded run-to-completion contract와 dedicated identity가 out-of-band Container Apps Job을 이미 정당화합니다. |
| Authoritative control-loop stage | Ad hoc service로 거절 | Agent single-writer ownership, hard dependency, typed pub/sub, 완전한 execution safeguard를 보존하지 않으면 stage를 분리할 수 없습니다. |

## 데이터 소유권 matrix

Logical record 또는 lifecycle transition 하나에는 writer 하나만 존재합니다. Matrix가 겹치지 않는
transition 또는 column을 이름으로 지정하고 database grant와 revision/CAS check가 분리를 강제할
때만 physical table 공유를 허용합니다. Reader는 deployment proximity로 writer가 되지 않습니다.

| Data 또는 table | Single write owner | 허용된 projection reader | Migration owner |
|-----------------|--------------------|--------------------------|-----------------|
| `audit_log` | Append-only audit store를 통한 Saga | Operator API audit projection, Norns reviewed intake, verification job | Alembic migration job |
| Operator API read projection | Durable write 없음. Pure projection code는 request-local value만 소유 | 이름이 지정된 authoritative store를 사용하는 authenticated route | 해당 없음 |
| Operator API SSE streaming | Durable write 없음. Connection-local cursor/backpressure state만 소유 | Authorized stage/activity stream과 durable replay projection | 해당 없음 |
| `conversation_record`, `conversation_turn`, `conversation_policy` ([migration 0019](../../../alembic/versions/20260716_0019_user_context_automation.py)) | Owning principal의 user-context/conversation application service | Operator API conversation/history projection | Alembic migration job |
| `conversation_image` | Principal-scoped Operator API image repository | 인증된 owning-principal history route | Alembic migration job |
| `conversation_outbound_delivery*`, `conversation_adapter_breaker` | Durable conversation-delivery coordinator | Operator API delivery status와 claimed work의 channel adapter | Alembic migration job |
| `background_task_attempt`, `background_task_progress`, `background_task_completion` ([migration 0040/0051](../../../alembic/versions/20260720_0040_background_task.py)) | Background-task coordinator/store | Owner-scoped Operator API projection과 completion delivery | Alembic migration job |
| `scheduled_task`, `schedule_dispatch_run`, `scheduled_conversation_anchor` | Definition과 CAS-claimed dispatch run의 scheduler service/store | Operator API scheduler/run projection과 continuation delivery | Alembic migration job |
| `inventory_snapshot*`, `inventory_active` | Full-snapshot promotion의 inventory synchronization job | Core inventory provider와 authorized Operator API inventory projection | Alembic migration job |
| `inventory_realtime_resource`, `inventory_realtime_link` | Normalized provider event의 realtime inventory projector | Inventory materializer와 authorized graph projection | Alembic migration job |
| `measurement.*` append-only audit/state namespace | Append-only audit와 namespaced StateStore provider를 통한 measurement runner | Promotion review, KPI, Operator API measurement projection | Shared StateStore/Alembic migration owner |
| Canary broker event와 resulting terminal audit | Canary job이 synthetic event를 쓰고 normal agent pipeline과 Saga가 resulting state/audit를 소유 | Startup/deployment verification과 health projection | Event schema owner. Canary table 없음 |
| `document_upload_session`, `document_version` - create/upload/received/cancel transition | Document ingestion API service | Ingestion API status/search authorization과 worker processing | Alembic migration job |
| `document_upload_session`, `document_version` - quarantined부터 terminal processing transition | Document ingestion worker | Ingestion API status/search projection | Alembic migration job |
| `document_worker_claim` | Ingestion worker role 아래 document metadata claim CAS | Reconciliation과 operational diagnostic | Alembic migration job |
| Governed document의 `knowledge_chunk` | Document ingestion worker/index adapter | Authorized Operator API search projection | Alembic migration job |
| `state_kv` namespaced record | 각 key namespace가 이름으로 지정한 subsystem | 해당 subsystem provider contract가 명시한 projection | Alembic migration job |
| Agent-owned control-loop object와 topic | 각 object type에 선언된 single pantheon agent | Registered typed subscriber와 cited read projection | Shared contract/catalog owner. Service-local migration 없음 |

새 candidate는 구현 전에 data row를 추가합니다. Writer가 겹치는 row, owner가 "shared service"인
row, 이름이 없는 migration path는 승격을 차단합니다.

## Cross-process contract matrix

| Contract | Schema owner | Producer | Consumer | Partition key | Compatibility | Retry, DLQ, idempotency, retention |
|----------|--------------|----------|----------|---------------|---------------|------------------------------------|
| Document Saga audit event `1.0.0` | [Document audit schema](../../../src/fdai/shared/contracts/document-worker-audit/schema.json) | Saga | Ingestion audit-gated worker | `upload_id` | Additive field, old/new producer-consumer test | At-least-once, invalid record는 sibling DLQ, [stage claim](../../../alembic/versions/20260806_0075_document_worker_claims.py)이 idempotency fence, event 1일/DLQ 7일 |
| Document Muninn index command `1.0.0` | [Document index schema](../../../src/fdai/shared/contracts/document-worker-index/schema.json) | Muninn | Ingestion index worker | `upload_id` | Additive field, unsupported version은 fail closed | At-least-once, invalid record는 sibling DLQ, completed index claim은 terminal dedupe, event 1일/DLQ 7일 |
| Document lifecycle activity | [Document activity contract](../../../src/fdai/delivery/ingestion_gateway/activity.py) | Owned transition의 ingestion API 또는 worker | Audit/progress consumer와 Huginn ingress bridge | `document_id` | Content-free additive event envelope | Stable action/version idempotency, reconciliation이 persisted fact 재발행, event 1일/DLQ 7일 |
| Operator command/proposal event | [Event](../../../src/fdai/shared/contracts/event/schema.json)와 [Action](../../../src/fdai/shared/contracts/action/schema.json) contract | Operator API command identity | Huginn/Forseti typed pipeline | normalized `resource_id` | Registry semver와 additive compatibility | At-least-once, catalog idempotency key, normal event/DLQ retention 1일/7일 |
| Agent introspection request/reply | [Agent-introspection transport](../../../src/fdai/delivery/agent_introspection_bus.py) | Bragi/Operator API bridge | Addressed agent와 bounded reply consumer | correlation id | Process split 전 versioned request/reply envelope | Bounded timeout/retry, authority 없음, content-redacted failure, broker retention 1일 |

Contract retention은 audit retention이 아닙니다. Event Hubs는 현재 normal entity를 1일, sibling
DLQ를 [Event Hubs module](../../../infra/modules/event-bus/event-hubs-kafka/main.tf)에서 7일 보존합니다. Durable state와 audit는 각각의 governed retention policy를 따릅니다.

## Identity와 deployment matrix

| Deployment role | Identity와 permission | Executor authority | Ingress / shape |
|-----------------|-----------------------|--------------------|-----------------|
| Core Control Plane | Decision, audit-intent, recovery, event-transport role. 현재 deployment는 cutover 전까지 executor UAMI를 임시로 보유 | Cutover 후 없음 | Internal headless Container App |
| Isolated Executor | Executor UAMI와 등록된 action-specific role | Cutover 후 유일한 보유자 | Internal event-driven Container App |
| Operator API read role | Read UAMI, projection store, command transport 없음 | 없음 | 인증된 public API |
| Operator API command role | Governed request의 event-transport send/receive만 허용 | 없음, request는 typed gate로 재진입 | Operator API composition에 attached |
| Ingestion API | Upload/search DB role, ADLS upload/delete, Event Hubs send | 없음 | Public HTTPS Container App |
| Ingestion worker | Worker DB role, ADLS processing, Event Hubs send/receive, embedding/OCR | 없음 | ClamAV를 포함한 internal Container App |
| Ingestion migration | `alembic upgrade head`용 administrator DSN read와 ACR pull. Identity는 run-to-completion job에만 attach | 없음 | Manual Container Apps Job |
| Channel adapter/runtime | Channel secret과 bounded message transport만 허용 | 없음 | 완성된 경우 deployment-specific ingress process |
| Scheduled job | Job-specific identity와 최소 data-plane role | Typed action이 Thor로 돌아가는 경우 외에는 없음 | Run-to-completion Container Apps Job |

Runtime, environment, evidence profile, fork status는 non-executor identity를 executor authority로
변환할 수 없습니다.

## Boundary docstring contract

AST checker는 exact reviewed architectural module에만 적용합니다. Semantic truth를 추론하지 않으며
generated code, fixture, trivial helper, architectural responsibility가 없는 package marker를 scan하지
않습니다. Scope에 포함된 module docstring은 다음 non-empty section을 사용합니다.

- **Responsibility:** Boundary가 존재하는 한 가지 이유입니다.
- **Boundary:** Input/output과 외부에 남겨야 하는 behavior입니다.
- **Authority and state:** 수행할 수 있는 decision/write, 보유할 수 없는 authority, durable state owner입니다.
- **Dependencies:** 의존할 수 있는 contract 또는 composition input입니다.
- **Deployment:** Process 또는 package role과 network boundary 생성 여부입니다.

Scope configuration은 `report` 또는 `enforce`를 선택합니다. Report finding은 표시되지만 차단하지
않습니다. Accountable owner가 import, state write, identity, process wiring과 대조해 다섯 section을
확인하고 exclusion이 남지 않은 scope만 enforce로 이동합니다. Exact justification이 있는 exclusion은 기존
gap을 suppress할 수 있습니다. Missing file, scope 밖 exclusion, compliance 후 남은 exclusion은
stale로 처리되어 checker가 실패합니다. AST checker 통과는 structure와 non-empty text만
증명합니다. Semantic accuracy는 architecture review와 executable test가 계속 담당합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 5개 service work package와 진행 상태 | [서비스 분해 실행 계획](service-decomposition-execution-plan-ko.md) |
| Repository package와 dependency boundary | [프로젝트 구조](project-structure-ko.md) |
| Azure process shape와 rollback | [배포 및 온보딩](../deployment/deploy-and-onboard-ko.md) |
| Operator API baseline inventory | [Operator Console Module Map](../interfaces/operator-console-module-map-ko.md) |
| Agent single-writer authority | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
