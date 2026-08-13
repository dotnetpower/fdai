---
title: 콘솔 Operator API 프로덕션 배포
translation_of: operator-api-prod.md
translation_source_sha: d85b861fc62956fa3322ae6c791e04cf87f4b9e5
translation_revised: 2026-08-14
---
# 콘솔 Operator API 프로덕션 배포

업스트림 저장소는 콘솔 Operator API를 독립
[`fdai-operator-service`](../../../services/operator-service/) 배포판으로 제공합니다. 로컬과
배포 프로파일은 같은 공개 ASGI 팩토리 `fdai_operator_service.main:create_app`을 사용하며,
명시적 환경값으로 실행 위치, Entra 검증기, PostgreSQL 저장소 및 Kafka 전송 계층을 선택합니다.
이 문서는 배포된 프로덕션 조립을 다룹니다.

> **범위**: Tier B 참조 문서다. 전체 dev/prod 패리티 계약은
> [dev-and-deploy-parity.md](dev-and-deploy-parity.md)에, 배포 토폴로지는
> [deployment.md](deployment.md)에 있다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 독립 서비스 진입점 및 환경 검증 | implemented | `services/operator-service/src/fdai_operator_service/main.py`, `production.py`, `environment.py` 및 조립 테스트 | 서비스는 팩토리 하나를 소유하며 프로바이더 사용 전에 수신기, Entra, RBAC, CORS, 데이터베이스 및 의미 전송 조합을 검증합니다. |
| Entra 인증 및 범위가 제한된 운영자 권한 부여 | implemented | `services/operator-service/src/fdai_operator_service/auth.py`, 경로 기능군 권한 부여 및 집중 서비스 테스트 | 사람 신원은 실행기 신원과 분리되며 와일드카드 CORS와 부분 의미 전송 구성은 실패 시 차단됩니다. |
| PostgreSQL 읽기 및 기능군 저장소 | implemented | `postgres.py`, `postgres_family_store.py` 및 `test_operator_service_postgres.py` | DSN 정규화, 연결 한계, 역할 연결, 트랜잭션별 명령문 시간 제한 및 사용할 수 없는 변환 결과가 구현되어 있습니다. |
| Kafka 의미 전송 및 실시간/에이전트 중계 | implemented | `adapters/`, `streaming/`, `test_semantic_kafka_adapter.py`, `test_semantic_turn_bridge.py` 및 `test_live_stream.py` | 로컬 평문 전송과 배포된 관리 신원 전송은 명시적인 실행 위치 선택으로 유지됩니다. |
| 독립 배포된 Operator 서비스 | validated | `.github/workflows/service-deploy.yml` 및 `config/independent-service-live-evidence-manifest.json` | 저장소 보관 가능한 실제 운영 근거가 독립 패키지 서비스, 마이그레이션 분기, 상태 검사 및 롤백 경계를 다룹니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | validated | 구현 원장을 도입했으며 이전 출처 이력은 재구성하지 않았습니다. 사용 중단된 공동 호스팅 파사드 참조를 독립 Operator 서비스로 갱신했습니다. | 현재 변경, 집중 Operator 서비스 검사 및 독립 서비스 실제 운영 근거 매니페스트 | 서비스가 발전함에 따라 환경 계약, 서비스 테스트, 배포 작업 흐름 및 실제 운영 근거 매니페스트를 함께 갱신해야 합니다. |

### 남은 작업

- [x] 이 문서의 범위가 제한된 프로덕션 조립에는 남은 구현 작업이 없습니다. 집중 서비스 테스트와 `config/independent-service-live-evidence-manifest.json`이 현재 구현 및 운영 근거를 제공합니다.

## 한눈에 보는 설계

- **서비스 소유 팩토리.** 배포된 프로세스는
  [`fdai_operator_service.main:create_app`](../../../services/operator-service/src/fdai_operator_service/main.py)을
  호출하며 컨트롤 플레인 구현을 가져오지 않고 서비스 소유 런타임을 구성합니다.
  클라우드 리소스 변경은 API 외부에 유지됩니다. 명시적 선택 게시 경로는 제안, 승인 또는 접근 요청을 기록하지만
  실행기 ID를 보유하지 않습니다. 또한
  staging/prod 트립와이어(CORS `*` 거부, dev-mode 거부)가 그대로 적용된다.
- **환경변수 전용 조립.** 팩토리가 필요로 하는 값은 환경변수로 도착합니다. 데이터베이스 DSN과
  웹훅 시크릿은 Key Vault 참조를 사용하고 테넌트/대상/그룹/토픽 같은 non-secret
  값은 IaC가 plain env로 주입합니다. 설정 파일이나 고객 식별자는 이미지에 박히지 않습니다.
- **잘못된 구성은 즉시 실패.** 필수 신원 또는 전송 값이 누락되거나 잘못되면 프로바이더
  구성 전에 `OperatorServiceConfigurationError`가 발생합니다. PostgreSQL을 구성하지 않은
  프로파일은 데이터베이스 기반 변환 결과를 명시적으로 사용할 수 없는 상태로 둡니다. 배포된
  프로덕션은 DSN과 정확한 `fdai_operator` 역할을 모두 제공합니다.
- **데이터베이스 준비 상태는 즉시 실패.** User 맥락, 스킬, 스트림 또는 다른 런타임 서비스를
  시작하기 전에 Postgres 읽기 모델이 범위가 제한된 `SELECT 1`을 실행합니다. 연결에 실패하면 lifespan
  시작을 중단하므로 연결되지 않은 개정 번호가 `/healthz`에서 준비된으로 표시되지 않습니다.
- **접근 실패를 관찰할 수 있습니다.** 모든 `401`과 `403`은 요청 경로와 exception 등급만
  포함하는 구조화된 경고를 기록합니다. 권한 확인 헤더, bearer 토큰, principal id 및
  exception 텍스트는 기록하지 않습니다.
- **Kafka 기반 실시간 및 에이전트 관찰.** 팩토리는 인증된 `/live/stream`과
  `/agents/stream` 읽기 경로를 항상 등록합니다. Kafka 초기화 엔드포인트가 구성되면
  하나의 서비스 소유 소비자 그룹이 `aw.pipeline.stages`를 읽고 단계 및 Pantheon 런타임
  상태 레코드를 검증한 뒤 허용된 레코드를 별도의 범위 제한 프로세스 내부 SSE 싱크로 전달합니다. 앱 수명 주기는 중계를 시작하고
  중지하며 중계가 독립적으로 소유한 Kafka 소비자를 닫습니다. Kafka 구성이 없으면
  경로는 연결 유지 신호를 보내며 `Awaiting source`를 표시합니다. 전송 연결을
  런타임 근거로 표시하지 않습니다. 브라우저의 native `EventSource` API는
  `Authorization` 헤더를 첨부할 수 없으므로 콘솔은 인증된 fetch 스트리밍으로 이를
  소비합니다.
- **영속 에이전트 초기화.** 에이전트 페이지는 서버에서 참여 에이전트를 도출한
  Postgres 기반 인시던트 명단을 먼저 로드한 다음 `/agents/stream`의 더 새로운
  단계 이벤트를 오버레이합니다. Audit-stage 프레임은 기록된 교정 결과가
  있을 때만 티켓을 해석합니다. HIL, 거부, abstain은 활성으로 유지되고 완료된
  단계 소유자는 idle로 돌아갑니다.

## 환경변수 계약

필수 (시작 시 즉시 실패):

| 변수 | 용도 |
|------|------|
| `FDAI_DATABASE_URL` | 배포된 프로덕션 psycopg 3 DSN입니다. 허용 스킴은 `postgresql://`, `postgres://` 및 `postgresql+psycopg://`입니다. 생략하면 데이터베이스 기반 변환 결과를 명시적으로 사용할 수 없습니다. |
| `FDAI_DATABASE_ROLE` | `FDAI_DATABASE_URL`을 설정할 때 반드시 `fdai_operator`여야 합니다. |
| `FDAI_ENTRA_TENANT_ID` | [`EntraJwtVerifier.from_env`](../../../services/operator-service/src/fdai_operator_service/)가 소비. |
| `FDAI_API_AUDIENCE` | `fdai-api` App ID URI (`api://<guid>`). |
| `FDAI_RBAC_READERS_GROUP_ID` | 읽기 담당 역할에 매핑되는 Entra 그룹 `objectId`. |
| `FDAI_RBAC_CONTRIBUTORS_GROUP_ID` | 기여자 매핑. |
| `FDAI_RBAC_APPROVERS_GROUP_ID` | Approver 매핑. |
| `FDAI_RBAC_OWNERS_GROUP_ID` | Owner 매핑. |
| `FDAI_RBAC_BREAK_GLASS_GROUP_ID` | Break-Glass 매핑. |

선택 (기본값 적용):

| 변수 | 기본값 | 용도 |
|------|--------|------|
| `FDAI_ENTRA_ISSUER` | `https://login.microsoftonline.com/<tenant>/v2.0` | v1 토큰이나 소버린 클라우드 대응. |
| `FDAI_ENTRA_JWKS_URI` | 테넌트 디스커버리 엔드포인트 | 에어갭 클라우드 대응. |
| `FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS` | 비어있음 (same-origin) | 콤마로 구분된 출처 목록. bare `*` 원소는 이 팩토리가 `RUNTIME_ENV`와 무관하게 무조건 거부한다 - 크로스-오리진 배포는 콘솔 출처를 명시적으로 나열해야 한다. |
| `FDAI_OPERATOR_DATABASE_STATEMENT_TIMEOUT_MS` | `20000` | 데이터베이스 작업에 `set_config('statement_timeout', ..., true)`로 트랜잭션 범위에서 적용합니다. |
| `FDAI_OPERATOR_DATABASE_CONNECT_TIMEOUT_S` | `10` | TCP와 인증 연결 시간을 제한하여 사용할 수 없는 데이터베이스가 신속히 실패하도록 합니다. |
| `FDAI_KAFKA_BOOTSTRAP_SERVERS` | 비어 있음 | 의미 전송과 공유 실시간/에이전트 관찰 중계를 시작합니다. `:9093`의 Event Hubs Kafka 엔드포인트를 사용합니다. 값이 비어 있으면 두 SSE 경로는 런타임 근거를 날조하지 않고 `Awaiting source` 상태로 연결을 유지합니다. |
| `KAFKA_TOPIC_EVENTS` | 비어 있음 | Kafka 초기화와 함께 타입이 지정된 액션 및 confirmed 인시던트 작업 흐름용 `POST /chat/action`을 활성화합니다. Huginn이 consume하는 raw 유입 토픽과 같은 값을 사용합니다. |
| `FDAI_STAGE_TOPIC` | `aw.pipeline.stages` | 워커가 게시하고 실제 운영 및 에이전트 중계가 소비하는 단계 토픽입니다. 워커와 Operator API는 같은 값을 사용하는 것이 좋습니다. |
| `FDAI_INCIDENT_SLA_POLICY_JSON` | 비어 있음(비활성화된) | 모든 `sev1`부터 `sev5`까지 긍정 `acknowledge_seconds` 및 `resolve_seconds` 값을 가진 strict JSON 객체입니다. 영속 A2 SLA-breach 모니터링을 활성화합니다. |
| `FDAI_INCIDENT_SLA_INTERVAL_SECONDS` | `60` | 긍정 SLA 검사 간격입니다. Policy JSON이 있을 때만 사용합니다. |
| `FDAI_IAM_DIRECTORY_PROVIDER` | 비어 있음 (디렉터리 검색 비활성화) | Owner 전용 사용자 디렉터리 검색을 활성화합니다. 구현된 값은 `entra`이며 지원되지 않는 향후 프로바이더 이름은 시작을 차단합니다. |
| `FDAI_IAM_ENTRA_GRAPH_BASE_URL` | `https://graph.microsoft.com/v1.0` | Sovereign cloud 또는 테스트 재정의용 Microsoft Graph base URL입니다. 디렉터리 프로바이더가 `entra`일 때만 사용합니다. |
| `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS` | `300` | Routed 서술기 지연 시간 탐색 간격(초)입니다. 최솟값은 `30`이며 주기 라운드마다 후보별 모델 지식만 쓴 샘플을 하나 추가합니다. |
| `FDAI_WEB_SEARCH_ENABLED` | `false` | 조건을 충족한 Chat T2 턴에서 통제된 Azure Responses 웹 검색을 활성화합니다. Resolved 웹 검색 후보와 allowed-domain 목록이 필요합니다. |
| `FDAI_WEB_SEARCH_ALLOWED_DOMAINS` | 비어 있음 | 콤마로 구분된 공개 출처 도메인입니다. 웹 검색을 활성화할 때 필요하며 최대 100개까지 설정할 수 있습니다. 각 항목은 DNS 하위 도메인도 허용합니다. |
| `FDAI_WEB_SEARCH_FOUNDRY_PROJECT_ENDPOINT` | 비어 있음 | 선택적 Foundry project HTTPS 엔드포인트입니다. 정확한 allowed-domain 목록을 가진 웹 검색 도구의 프롬프트 에이전트를 사용하려면 `FDAI_WEB_SEARCH_FOUNDRY_AGENT_NAME`과 함께 구성합니다. |
| `FDAI_WEB_SEARCH_FOUNDRY_AGENT_NAME` | 비어 있음 | 선택적 Foundry prompt-agent 이름입니다. Foundry 구성이 불완전하면 시작이 실패합니다. Provision된 에이전트와 일치하지 않는 런타임 도메인 변경은 실패 시 차단합니다. |
| `FDAI_WEB_SEARCH_FOUNDRY_MODEL_DEPLOYMENT` | resolved direct 후보 | Foundry 프롬프트 에이전트가 참조하고 Settings가 표시하는 정제된 모델 배포입니다. Foundry 검색을 활성화하면 Terraform이 deployment-owned 값을 공급합니다. |
| `FDAI_WEB_SEARCH_MAX_RESULTS` | `3` | 한 검색에서 유지할 인용 수입니다. `1`부터 `10`까지 허용합니다. |
| `FDAI_WEB_SEARCH_BUDGET_MS` | `15000` | 검색별 엔드포인트 시간 초과(ms)입니다. |
| `FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS` | `300` | 웹 검색 후보 모델 탐색 간격(초)입니다. 최솟값은 `30`이며 탐색은 검색 툴을 호출하지 않습니다. |

웹 검색은 제한된 운영자 조회만 Azure Responses로 전송합니다. 현재 화면
스냅샷과 대화 이력은 전송하지 않습니다. Azure 웹 검색은 Grounding with
Bing을 사용합니다. 이 전송은 배포의 compliance 및 geography 경계 밖으로 나갈
수 있고 Microsoft 데이터 Protection Addendum의 적용을 받지 않습니다. 배포 소유자가
해당 조건을 수락하고 primary-source 허용 목록을 구성하기 전에는 비활성 상태를
유지하는 것이 좋습니다.

Terraform은 프로바이더를 `operator_api_iam_directory_provider`로 노출하며 기본값은 비어 있습니다.
Operator API managed 신원에 필요한 Graph consent를 부여한 후에만 `entra`로 설정합니다.

Entra 디렉터리 어댑터는 Operator API managed 신원을 통해
`https://graph.microsoft.com/.default`를 요청하며 admin consent가 적용된 Microsoft Graph
애플리케이션 권한 `User.Read.All`이 필요합니다. 이 권한은 읽기 전용이며 브라우저에
전달되지 않습니다. 구성된 FDAI 역할 그룹과 사람 멤버를 변환 결과하려면
`GroupMember.Read.All`도 필요합니다. 두 권한 모두 읽기 전용이며 그룹 멤버십 쓰기 권한은
포함하지 않습니다.

## 실행

```bash
uvicorn fdai_operator_service.main:create_app \
    --factory --host 0.0.0.0 --port 8000
```

`app` 팩토리는 워커당 한 번 호출된다. 위 모든 env가 프로세스 스코프에 있어야
한다. Container Apps 리비전에서 env는 Key Vault 시크릿을 직접 참조하는
`containerapp.secrets` 항목에서 프로젝션된다
([app-shape.instructions.md § Azure 대응](../../../.github/instructions/app-shape.instructions.md#azure-mapping-draft---reconfirm-preview-services-at-adoption-time)).

## 어디에 뭐가 있나

- [`main.py`](../../../services/operator-service/src/fdai_operator_service/main.py) - 공개 ASGI 팩토리 내보내기 및 서비스 진입점.
- [`production.py`](../../../services/operator-service/src/fdai_operator_service/production.py) - 검증된 uvicorn 수명 주기.
- [`environment.py`](../../../services/operator-service/src/fdai_operator_service/environment.py) - 변경할 수 없는 환경 검증.
- [`composition.py`](../../../services/operator-service/src/fdai_operator_service/composition.py) - Entra, PostgreSQL, 경로 기능군, 의미 버스, 중계, 준비 상태 및 수명 주기 조립.
- [`postgres.py`](../../../services/operator-service/src/fdai_operator_service/postgres.py) 및 [`postgres_family_store.py`](../../../services/operator-service/src/fdai_operator_service/postgres_family_store.py) - 권위 있는 읽기 및 기능군 저장소.
- [`adapters/live_stage_kafka.py`](../../../services/operator-service/src/fdai_operator_service/adapters/live_stage_kafka.py)
  - Kafka 소비자 수명 주기와 처리 후 커밋 동작을 소유합니다.
- [`streaming/live_stream.py`](../../../services/operator-service/src/fdai_operator_service/) 및
  [`streaming/stage_frames.py`](../../../services/operator-service/src/fdai_operator_service/) 및
  [`streaming/agent_frames.py`](../../../services/operator-service/src/fdai_operator_service/)
  - 범위가 제한된 SSE 전달을 제공하고 신뢰할 수 없는 단계/런타임 레코드를 검증하며
  브라우저가 기대하는 `event: stage`와 에이전트 `event: message` 계약을 유지합니다.

## 테스트

- `services/operator-service/tests/test_operator_service_composition.py` - 환경 및 조립 가드.
- `services/operator-service/tests/test_operator_service_postgres.py` - DSN, 쿼리, 시간 제한 및 행 매핑 계약.
- `services/operator-service/tests/test_live_stream.py` - 단계 중계, 잘못된 프레임 거부 및 수명 주기 동작.
- `services/operator-service/tests/test_semantic_kafka_adapter.py` 및 `test_semantic_turn_bridge.py` - 의미 전송, 재생, 임대 및 수명 주기 동작.

## 관련 문서

| 알고 싶은 내용 | 읽을 문서 |
|----------------|-----------|
| dev/prod 패리티 계약 | [dev-and-deploy-parity-ko.md](dev-and-deploy-parity-ko.md) |
| 배포 토폴로지 | [deployment-ko.md](deployment-ko.md) |
| RBAC + 신원 흐름 | [../interfaces/user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md) |
| 콘솔 읽기 전용 불변식 | [../../../.github/instructions/app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) |
