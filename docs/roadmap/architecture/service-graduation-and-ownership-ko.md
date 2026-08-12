---
translation_of: service-graduation-and-ownership.md
translation_source_sha: 60334e7f074a94c378f2f67c5d5b9f34daeb7937
translation_revised: 2026-08-12
---
# 서비스 승격과 데이터 소유권

이 문서는 FDAI 패키지를 독립 배포 서비스로 전환할 수 있는 시점을 결정합니다. 또한 프로세스
분리가 숨은 권한 또는 두 번째 쓰기 담당을 만들지 않도록 프로세스 간 계약, 영속 데이터,
신원, 이행을 할당합니다.

> **결정 범위:** 패키지 경계가 서비스를 의미하지는 않습니다. 승격에는 측정된 forcing
> 트리거 하나와 아래의 모든 준비 상태 게이트가 필요합니다. 근거가 없으면 보류하고 권한,
> 소유권, 전송 계층 또는 롤백 위반이 있으면 거절합니다.
>
> **근거 범위:** Synthetic 테스트는 mechanics를 증명합니다. 운영 규모 증가는 승격할
> 정확한 이미지, 토폴로지, 신원, 스키마, 계약 버전의 현재 staging 또는 실제 운영 smoke
> 근거가 필요합니다.
>
> **프로그램 목표:** 현재 decomposition 프로그램은 5개 런타임 서비스로 완료합니다. Isolated
> 실행기는 필수 목표이지만 모든 binary 게이트를 통과한 후에만 효과 권한을 받습니다.
> 근거가 부족하면 안전하지 않은 전환을 허용하지 않고 프로그램 완료를 차단합니다.

## 설계 개요

후보는 scaling, 권한 격리, 실패 격리 트리거 중 하나 이상을 충족하고 모든
계약, 내구성, observability, 비용, 롤백 게이트를 통과해야 **승인**됩니다. 트리거가 측정되지
않았거나 근거가 불완전하면 **보류**됩니다. Direct 에이전트 호출, shared 변경 가능한 coordination,
여러 쓰기 담당, 실행기 신원 확산, unversioned wire 계약 또는 테스트된 롤백 부재를
만들면 **거절**됩니다. 현재 배포에는 shadow 모드 Isolated 실행기를 포함한 5개 런타임
서비스가 있습니다. 추적되는 전환은 exact 실제 운영 근거를 닫은 후에만 Core의 변경 역할을
제거합니다.

## 승격 점수표

모든 측정 행에 동일한 관측 구간과 후보 개정 번호를 사용합니다. Binary 권한
요구사항으로 기다리는 것이 안전하지 않은 경우를 제외하고 최소 구간은 연속 30일입니다. Raw
근거 링크, 조회 버전, 출처 최신성, 구간 시작/end, 측정 기준 시점, 후보
개정 번호, 검토자, 다이제스트, 승인 시간, 만료를 [아키텍처 검토 Board Packet](architecture-review-board-ko.md#ownership과-support)의 evidence-binding format에 기록합니다.

| 게이트 | 승인 임계값 | 근거 출처 |
|------|----------------|-----------------|
| Scaling 트리거 | 2주 동안 주 3개의 별도 30분 구간에서 p95 CPU >= 70% 또는 p95 기억 >= 75%, 또는 3개 구간에서 queue-delay p95가 SLO 초과 | Container Apps / OpenTelemetry 리소스 메트릭과 큐 대시보드 |
| 권한 트리거 | 분리가 상위 프로세스에서 cloud 역할 배정, 시크릿, 데이터베이스 쓰기 권한 부여 또는 공개 유입 권한을 하나 이상 제거 | Terraform 계획, 신원 그래프, 데이터베이스 권한 조회 |
| 실패 트리거 | 후보가 90일 동안 독립 검토된 인시던트 2개 이상 또는 상위 서비스 error-budget burn의 10% 이상 유발 | 인시던트 원장, SLO burn 보고, post-incident 검토 |
| 타입이 지정된 전송 계층 | 모든 프로세스 간 메시지에 소유자, versioned 스키마, 생산자, 소비자, 고정된 파티션 키, 가산 호환성 정책, 재시도/DLQ, 멱등성 룰, 보존 존재 | 계약 레지스트리, 호환성 테스트, event-bus 구성 |
| 내구성 | 프로세스 loss, 중복, reorder, 확장, 축소 테스트에서 중복 최종 효과 0건이며 권한 게이트를 건너뛰지 않음 | 영속 저장소/CAS 테스트와 재시작 smoke |
| Observability | 독립 생존/준비 상태와 지연 시간, 큐/lag, 오류, 재시도, DLQ, ownership-conflict 신호가 있고 필수 alert가 책임 소유자에게 경로 | Health 탐색, 텔레메트리 카탈로그, alert 룰, 런북 |
| 비용 | 월별 incremental 비용을 측정하고 승인된 환경 예산 안에 유지. 상위 서비스 비용의 20%를 넘는 delta는 FinOps 승인 필요 | Terraform 비용 추정치와 측정된 청구 기준선 |
| Rollback | Staging 예행 연습에서 오프셋 reset, 데이터 loss, 중복 최종 효과, 권한 변경 없이 15분 안에 이전 토폴로지 복원 | Timed 롤백 증적과 post-rollback smoke |
| 신원 상한 | 권한이 다르면 새 역할에 전용 신원을 사용하고 non-executor 역할은 Thor 신원 또는 실행기 역할을 획득할 수 없음 | Terraform 신원/RBAC assertion과 effective-access 탐색 |

두 graduated 서비스는 각자의 schema, producer identity, logical topic, hash 기반 consumer group,
준비 상태, offset 소유권 및 DLQ routing을 유지할 때 하나의 physical Event Hub에서 versioned logical
channel을 multiplex할 수 있습니다. Broker entity를 공유해도 서비스 소유권이나 상태는 병합되지 않으며,
그 자체로 graduation gate를 충족하지 않습니다.

실패한 binary 게이트를 weighted 점수로 보상할 수 없습니다. 승인된 분리는 exact 근거 기준 시점을
기록하며 90일 안에 배포가 시작되지 않으면 만료되어 다시 평가합니다.

## 후보 결정

다음 결정은 현재 Operator API 인벤토리와 deployed 앱 형태의 패키지/프로세스 후보에
점수표를 적용한 결과입니다.

| 후보 | 현재 결정 | 이유와 다음 근거 |
|-----------|-----------|----------------------|
| Isolated 실행기 | 필수 프로그램 목표, 전환은 게이트 적용 | 권한 격리가 forcing 트리거입니다. 효과 권한을 Core에서 이동하기 전에 versioned 명령/증적 전송 계층, 영속 중복/reorder/재시작 행동, 독립적인 텔레메트리, 비용, effective 접근, exact-topology smoke, timed 롤백을 통과해야 합니다. |
| Operator API `application` 서비스 | 보류 | 타입이 지정된 프로세스 내 경계가 있지만 독립 규모, 권한, 실패 트리거가 측정되지 않았습니다. |
| Operator API 읽기 변환 결과 | 보류 | 읽기 전용 패키지 소유권은 명확하지만 규모 트리거 또는 독립 저장소가 정당화되지 않았습니다. |
| Operator API SSE 스트리밍 | 보류 | Versioned 중계/재생 계약과 측정된 연결 격리 benefit이 필요합니다. |
| 문서 인제스트 API | 승인 | 권한과 scaling 격리, 타입이 지정된 전송 계층, role-scoped 데이터베이스 접근, 탐색, co-host 롤백이 구현됐습니다. |
| 문서 인제스트 워커 | 승인 | 영속 임차 기간/CAS 점유, 재시작/reorder/DLQ 테스트, 내부 상태, dedicated 신원, 규모 게이트가 구현됐습니다. |
| 대화 채널 런타임 | 보류 | 영속 전달 coordination은 프로세스 내이며 standalone 어댑터 유입, 신원, 영속성 연결, 배포 smoke가 아직 연결되지 않았습니다. |
| Background read-task 실행기 | 보류 | 영속 시도는 있지만 독립 비용/실패 트리거와 deployed 전송 계층 근거가 측정되지 않았습니다. |
| 스케줄러, 인벤토리, 측정, canary 작업 | 작업으로 승인 | 범위가 제한된 run-to-completion 계약과 dedicated 신원이 out-of-band Container Apps 작업을 이미 정당화합니다. |
| 권위 있는 control-loop 단계 | Ad hoc 서비스로 거절 | 에이전트 single-writer 소유권, 필수 의존성, 타입이 지정된 pub/sub, 완전한 실행 safeguard를 보존하지 않으면 단계를 분리할 수 없습니다. |

## 데이터 소유권 매트릭스

Logical 기록 또는 수명 주기 전이 하나에는 쓰기 담당 하나만 존재합니다. 매트릭스가 겹치지 않는
전이 또는 열을 이름으로 지정하고 데이터베이스 권한 부여와 개정 번호/CAS 검사가 분리를 강제할
때만 physical 표 공유를 허용합니다. 읽기 담당은 배포 proximity로 쓰기 담당이 되지 않습니다.

| 데이터 또는 표 | Single 쓰기 소유자 | 허용된 변환 결과 읽기 담당 | 이행 소유자 |
|-----------------|--------------------|--------------------------|-----------------|
| `audit_log` | 추가 전용 감사 저장소를 통한 Saga | Operator API 감사 변환 결과, Norns 검토된 intake, 검증 작업 | Alembic 이행 작업 |
| Operator API 읽기 변환 결과 | 영속 쓰기 없음. Pure 변환 결과 코드는 request-local 값만 소유 | 이름이 지정된 권위 있는 저장소를 사용하는 인증된 경로 | 해당 없음 |
| Operator API SSE 스트리밍 | 영속 쓰기 없음. Connection-local 커서/backpressure 상태만 소유 | Authorized 단계/활동 스트림과 영속 재생 변환 결과 | 해당 없음 |
| `conversation_record`, `conversation_turn`, `conversation_policy` ([이행 0019](../../../alembic/versions/20260716_0019_user_context_automation.py)) | Owning principal의 user-context/대화 애플리케이션 서비스 | Operator API 대화/이력 변환 결과 | Alembic 이행 작업 |
| `conversation_image` | principal 범위로 한정된 Operator API 이미지 저장소 | 인증된 owning-principal 이력 경로 | Alembic 이행 작업 |
| `conversation_outbound_delivery*`, `conversation_adapter_breaker` | 영속 conversation-delivery 조정기 | Operator API 전달 상태와 claimed 작업의 채널 어댑터 | Alembic 이행 작업 |
| `background_task_attempt`, `background_task_progress`, `background_task_completion` ([이행 0040/0051](../../../alembic/versions/20260720_0040_background_task.py)) | Background-task 조정기/저장소 | Owner-scoped Operator API 변환 결과와 완료 전달 | Alembic 이행 작업 |
| `scheduled_task`, `schedule_dispatch_run`, `scheduled_conversation_anchor` | 정의와 CAS-claimed 전달 실행의 스케줄러 서비스/저장소 | Operator API 스케줄러/실행 변환 결과와 이어가기 전달 | Alembic 이행 작업 |
| `inventory_snapshot*`, `inventory_active` | Full-snapshot 승격의 인벤토리 synchronization 작업 | Core 인벤토리 프로바이더와 authorized Operator API 인벤토리 변환 결과 | Alembic 이행 작업 |
| `inventory_realtime_resource`, `inventory_realtime_link` | 정규화된 프로바이더 이벤트의 realtime 인벤토리 projector | 인벤토리 materializer와 authorized 그래프 변환 결과 | Alembic 이행 작업 |
| `measurement.*` 추가 전용 감사/상태 이름 공간 | 추가 전용 감사와 namespaced StateStore 프로바이더를 통한 측정 실행기 | 승격 검토, KPI, Operator API 측정 변환 결과 | Shared StateStore/Alembic 이행 소유자 |
| Canary 브로커 이벤트와 resulting 최종 감사 | Canary 작업이 synthetic 이벤트를 쓰고 normal 에이전트 파이프라인과 Saga가 resulting 상태/감사를 소유 | 시작/배포 검증과 상태 변환 결과 | Event 스키마 소유자. Canary 표 없음 |
| `document_upload_session`, `document_version` - 생성/업로드/received/취소 전이 | 문서 인제스트 API 서비스 | 인제스트 API 상태/검색 권한 확인과 워커 처리 | Alembic 이행 작업 |
| `document_upload_session`, `document_version` - quarantined부터 최종 처리 전이 | 문서 인제스트 워커 | 인제스트 API 상태/검색 변환 결과 | Alembic 이행 작업 |
| `document_worker_claim` | 인제스트 워커 역할 아래 문서 메타데이터 점유 CAS | 조정과 operational 진단 | Alembic 이행 작업 |
| 통제된 문서의 `knowledge_chunk` | 문서 인제스트 워커/인덱스 어댑터 | Authorized Operator API 검색 변환 결과 | Alembic 이행 작업 |
| `document_api_outbox` | API 소유 수명 주기 및 deletion-request 이벤트의 문서 인제스트 API | API 발신함 drainer | 문서 인제스트 API 이행 가지 |
| `document_worker_outbox` | 워커 소유 수명 주기 이벤트의 문서 처리 워커 | 워커 발신함 drainer | 문서 처리 워커 이행 가지 |
| `executor_receipt_outbox` | 최종 증적 전달의 Isolated 실행기 | 실행기 증적 drainer | Isolated 실행기 이행 가지 |
| `state_kv` namespaced 기록 | 각 키 이름 공간이 이름으로 지정한 subsystem | 해당 subsystem 프로바이더 계약이 명시한 변환 결과 | Alembic 이행 작업 |
| Agent-owned control-loop 객체와 토픽 | 각 객체 타입에 선언된 single pantheon 에이전트 | 등록된 타입이 지정된 구독자와 cited 읽기 변환 결과 | Shared 계약/카탈로그 소유자. Service-local 이행 없음 |

새 후보는 구현 전에 데이터 행을 추가합니다. 쓰기 담당이 겹치는 행, 소유자가 "shared 서비스"인
행, 이름이 없는 이행 경로는 승격을 차단합니다.

## 프로세스 간 계약 매트릭스

| 계약 | 스키마 소유자 | 생산자 | 소비자 | 파티션 키 | 호환성 | 재시도, DLQ, 멱등성, 보존 |
|----------|--------------|----------|----------|---------------|---------------|------------------------------------|
| 문서 Saga 감사 이벤트 `1.0.0` | [문서 감사 스키마](../../../services/core-control-plane/src/fdai/shared/contracts/document-worker-audit/schema.json) | Saga | 인제스트 audit-gated 워커 | `upload_id` | 가산 필드, old/new producer-consumer 테스트 | At-least-once, 잘못된 기록은 형제 DLQ, [단계 점유](../../../alembic/versions/20260806_0075_document_worker_claims.py)이 멱등성 fence, 이벤트 1일/DLQ 7일 |
| 문서 Muninn 인덱스 명령 `1.0.0` | [문서 인덱스 스키마](../../../services/core-control-plane/src/fdai/shared/contracts/document-worker-index/schema.json) | Muninn | 인제스트 인덱스 워커 | `upload_id` | 가산 필드, 지원하지 않는 버전은 실패 시 차단 | At-least-once, 잘못된 기록은 형제 DLQ, completed 인덱스 점유는 최종 dedupe, 이벤트 1일/DLQ 7일 |
| 문서 deletion 요청 `1.0.0` | `fdai-service-contracts` packaged JSON 스키마 | 문서 인제스트 API | 문서 처리 워커 | `document_id` | 가산 필드, 지원하지 않는 버전은 실패 시 차단 | Transactional API 발신함, exact 업로드/버전 개정 번호 fence, 워커 stage-claim dedupe, 잘못된 기록은 형제 DLQ |
| 문서 수명 주기 활동 | [문서 서비스 계약](../../../packages/service-contracts/src/fdai_service_contracts/document.py) | Owned 전이의 인제스트 API 또는 워커 | 감사/진행 상황 소비자와 Huginn 유입 브리지 | `document_id` | 내용이 없는 가산 이벤트 묶음 | 고정된 액션/버전 멱등성, 조정이 저장된 사실 재발행, 이벤트 1일/DLQ 7일 |
| Operator 명령/제안 이벤트 | [Event](../../../services/core-control-plane/src/fdai/shared/contracts/event/schema.json)와 [액션](../../../services/core-control-plane/src/fdai/shared/contracts/action/schema.json) 계약 | Operator API 명령 신원 | Huginn/Forseti 타입이 지정된 파이프라인 | 정규화된 `resource_id` | 레지스트리 semver와 가산 호환성 | At-least-once, 카탈로그 멱등성 키, normal 이벤트/DLQ 보존 1일/7일 |
| Operator 의미 턴 `1.2.0` | `fdai-service-contracts` 의미 요청 및 변환 결과 codec | Operator API 영속 발신함 / Core 의미 런타임 | Core 의미 소비자 / Operator 변환 결과 소비자 | `request_id` | N은 `1.0.0`, `1.1.0`, `1.2.0`을 수락하며 `1.2.0` 페이로드를 downgrade하지 않음 | At-least-once, 멱등적 생산자, 변환 결과 영속성 이후 수동 커밋, malformed JSON은 형제 DLQ, 영속 요청/변환 결과 dedupe |
| 에이전트 introspection 요청/회신 | [Agent-introspection 전송 계층](../../../services/core-control-plane/src/fdai/delivery/agent_introspection_bus.py) | Bragi/Operator API 브리지 | Addressed 에이전트와 범위가 제한된 회신 소비자 | 상관관계 id | 프로세스 분리 전 versioned 요청/회신 묶음 | 범위가 제한된 시간 초과/재시도, 권한 없음, content-redacted 실패, 브로커 보존 1일 |
| 실행기 명령 `1.0.0` 및 증적 `1.0.0` / `1.1.0` | [실행기 전송 계층](../../../services/core-control-plane/src/fdai/shared/contracts/models/executor_transport.py) | Core Thor 실행 포트 | Isolated 실행기와 Core 증적 클라이언트 | exact 대상 리소스 참조 | `1.0.0` 증적은 효과가 없고 가산 `1.1.0`은 전달을 보고하지만 독립적인 검증을 주장할 수 없음 | At-least-once, poison DLQ, 고정된 Core 소비자 그룹, 프로바이더와 실행기 멱등성, normal/DLQ 보존 1일/7일 |

계약 보존은 감사 보존이 아닙니다. Event Hubs는 현재 normal 개체를 1일, 형제
DLQ를 [Event Hubs 모듈](../../../infra/modules/event-bus/event-hubs-kafka/main.tf)에서 7일 보존합니다. 영속 상태와 감사는 각각의 통제된 보존 정책을 따릅니다.

서비스 기준선 도입은 이전 방식 Alembic 헤드만 확인하지 않습니다. 이행 디스패처는 각
서비스가 소유한 표, 순서가 고정된 열, 제약, 필수 PostgreSQL 확장의 checked-in
지문을 제출된 근거 및 실제 운영 데이터베이스 카탈로그와 비교한 후 서비스 기준선을 각인합니다.
Rollback은 exact 서비스 가지 헤드에서만 시작하고 exact 기준선을 대상으로 사용합니다.
완료 후 resulting 스키마 지문과 헤드를 다시 확인하고, 해석 가능한 저장된 롤백
산출물을 가리키는 시각 포함 JSON 증적을 기록합니다.

## 신원과 배포 매트릭스

| 배포 역할 | 신원과 권한 | 실행기 권한 | Ingress / 형태 |
|-----------------|-----------------------|--------------------|-----------------|
| Core 컨트롤 플레인 | 결정, audit-intent, 복구, event-transport 역할. 현재 배포는 전환 전까지 실행기 UAMI를 임시로 보유 | 전환 후 없음 | 내부 headless Container App |
| Isolated 실행기 | 실행기 UAMI와 등록된 action-specific 역할 | 전환 후 유일한 보유자 | 내부 event-driven Container App |
| Operator API 읽기 역할 | 읽기 UAMI, 변환 결과 저장소, 명령 전송 계층 없음 | 없음 | 인증된 공개 API |
| Operator API 명령 역할 | 통제된 요청의 event-transport 전송/수신만 허용 | 없음, 요청은 타입이 지정된 게이트로 재진입 | Operator API 조립에 연결된 |
| 인제스트 API | 업로드/검색 DB 역할, ADLS 업로드/삭제, Event Hubs 전송 | 없음 | 공개 HTTPS Container App |
| 인제스트 워커 | 워커 DB 역할, ADLS 처리, Event Hubs 전송/수신, 임베딩/OCR | 없음 | ClamAV를 포함한 내부 Container App |
| 인제스트 이행 | `alembic upgrade head`용 administrator DSN 읽기와 ACR pull. 신원은 run-to-completion 작업에만 첨부 | 없음 | 수동 Container Apps 작업 |
| 채널 어댑터/런타임 | 채널 시크릿과 범위가 제한된 메시지 전송 계층만 허용 | 없음 | 완성된 경우 deployment-specific 유입 프로세스 |
| Scheduled 작업 | Job-specific 신원과 최소 data-plane 역할 | 타입이 지정된 액션이 Thor로 돌아가는 경우 외에는 없음 | Run-to-completion Container Apps 작업 |

런타임, 환경, 근거 프로파일, 포크 상태는 non-executor 신원을 실행기 권한으로
변환할 수 없습니다.

## 경계 docstring 계약

AST 검사기는 exact 검토된 architectural 모듈에만 적용합니다. 의미 truth를 추론하지 않으며
생성된 코드, 고정본, trivial 보조 로직, architectural responsibility가 없는 패키지 표시를 검사하지
않습니다. 범위에 포함된 모듈 docstring은 다음 비어 있지 않은 섹션을 사용합니다.

- **Responsibility:** 경계가 존재하는 한 가지 이유입니다.
- **경계:** 입력/출력과 외부에 남겨야 하는 행동입니다.
- **권한 and 상태:** 수행할 수 있는 결정/쓰기, 보유할 수 없는 권한, 영속 상태 소유자입니다.
- **의존성:** 의존할 수 있는 계약 또는 조립 입력입니다.
- **배포:** 프로세스 또는 패키지 역할과 네트워크 경계 생성 여부입니다.

범위 구성은 `report` 또는 `enforce`를 선택합니다. 보고 발견 사항은 표시되지만 차단하지
않습니다. Accountable 소유자가 가져오기, 상태 쓰기, 신원, 프로세스 배선과 대조해 다섯 섹션을
확인하고 exclusion이 남지 않은 범위만 강제 적용으로 이동합니다. Exact justification이 있는 exclusion은 기존
공백을 suppress할 수 있습니다. 누락된 파일, 범위 밖 exclusion, compliance 후 남은 exclusion은
stale로 처리되어 검사기가 실패합니다. AST 검사기 통과는 structure와 비어 있지 않은 텍스트만
증명합니다. 의미 accuracy는 아키텍처 검토와 executable 테스트가 계속 담당합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 5개 서비스 작업 패키지와 진행 상태 | [서비스 분해 실행 계획](service-decomposition-execution-plan-ko.md) |
| 저장소 패키지와 의존성 경계 | [프로젝트 구조](project-structure-ko.md) |
| Azure 프로세스 형태와 롤백 | [배포 및 온보딩](../deployment/deploy-and-onboard-ko.md) |
| Operator API 기준선 인벤토리 | [Operator Console 모듈 지도](../interfaces/operator-console-module-map-ko.md) |
| 에이전트 single-writer 권한 | [에이전트 Pantheon](../agents/agent-pantheon-ko.md) |
