---
title: 콘솔 read-API 프로덕션 배포
translation_of: read-api-prod.md
translation_source_sha: 1b3baac16a3df26c3f9cd5015a30554dcdfab2cb
translation_revised: 2026-07-18
---
# 콘솔 read-API 프로덕션 배포

업스트림 리포는 콘솔 read API용 ASGI 진입점 두 개를 제공한다:
개발용 하네스 ([`src/fdai/delivery/read_api/dev/local.py`](../../../src/fdai/delivery/read_api/dev/local.py))는
:class:`UnsafeClaimsExtractor` 뒤에 :class:`InMemoryConsoleReadModel`을
띄우고, 프로덕션 진입점 ([`src/fdai/delivery/read_api/prod.py`](../../../src/fdai/delivery/read_api/prod.py))은
실제 Entra JWT 검증과 Postgres 기반 read 모델을 환경변수만으로 조립한다.
이 문서는 프로덕션 진입점을 다룬다.

> **범위**: Tier B 참조 문서다. 전체 dev/prod 패리티 계약은
> [dev-and-deploy-parity.md](dev-and-deploy-parity.md)에, 배포 토폴로지는
> [deployment.md](deployment.md)에 있다.

## 한눈에 보는 설계

- **동일한 `build_app` 글루.** 프로덕션 팩토리는 공용
  [`build_app`](../../../src/fdai/delivery/read_api/main.py)을
  `dev_mode=False`로 호출합니다. 그 결과 cloud-resource mutation은 API 외부에
  유지됩니다. Opt-in POST route는 proposal, approval 또는 access request를 기록하지만
  executor ID를 보유하지 않습니다. 또한
  staging/prod 트립와이어(CORS `*` 거부, dev-mode 거부)가 그대로 적용된다.
- **환경변수 전용 조립.** 팩토리가 필요로 하는 모든 값은 포크의 IaC가 Key Vault
  참조에서 채우는 환경변수로 도착한다. 설정 파일이 필요 없고, 고객 식별자가
  이미지에 박히지 않는다.
- **누락된 config는 즉시 실패.** 필수 env가 없으면 시작 시점에
  :class:`ProdReadApiConfigError`(`ValueError`의 서브클래스)가 발생한다.
  깨진 리비전은 절대 소켓을 바인딩하지 못한다. env가 통째로 비어있는
  콜드 부트에서는 누락된 슬롯 8개를 순차 실패로 겪는 대신 한 번의
  에러로 모두 열거되어 보인다.
- **Kafka 기반 실시간 관찰.** Kafka bootstrap endpoint가 구성되면 팩토리는
  `/live/stream`과 `/agents/stream`을 등록합니다. 별도 consumer group이 공유
  `aw.pipeline.stages` 토픽을 읽고 검증된 단계 레코드를 프로세스 내부 SSE sink로
  전달합니다. 앱 lifespan은 두 relay를 시작하고 중지하며 공유 EventBus 전송을
  닫습니다. 이 SSE GET route는 snapshot GET route와 동일한 Entra bearer 인증을
  사용합니다. 브라우저의 native `EventSource` API는 `Authorization` header를 첨부할 수
  없으므로 콘솔은 인증된 fetch streaming으로 이를 소비합니다.
- **Durable Agents bootstrap.** Agents 페이지는 server에서 참여 agent를 도출한
  Postgres 기반 incident roster를 먼저 로드한 다음 `/agents/stream`의 더 새로운
  stage event를 overlay합니다. Audit-stage frame은 기록된 remediation outcome이
  있을 때만 ticket을 resolve합니다. HIL, deny, abstain은 active로 유지되고 완료된
  stage owner는 idle로 돌아갑니다.

## 환경변수 계약

필수 (시작 시 즉시 실패):

| 변수 | 용도 |
|------|------|
| `FDAI_DATABASE_URL` | psycopg 3 DSN. 허용 스킴: `postgresql://`, `postgres://`, `postgresql+psycopg://`. 그 외 `+<driver>` 접미사(`+asyncpg`, `+psycopg2` 등)는 시작 시점에 `ProdReadApiConfigError`로 거부된다. 라이터가 `alembic upgrade head`로 이미 프로비저닝한 `audit_log` + `state_kv` 스키마 대상. |
| `FDAI_ENTRA_TENANT_ID` | [`EntraJwtVerifier.from_env`](../../../src/fdai/delivery/read_api/entra_verifier.py)가 소비. |
| `FDAI_API_AUDIENCE` | `fdai-api` App ID URI (`api://<guid>`). |
| `FDAI_RBAC_READERS_GROUP_ID` | Reader 역할에 매핑되는 Entra 그룹 `objectId`. |
| `FDAI_RBAC_CONTRIBUTORS_GROUP_ID` | Contributor 매핑. |
| `FDAI_RBAC_APPROVERS_GROUP_ID` | Approver 매핑. |
| `FDAI_RBAC_OWNERS_GROUP_ID` | Owner 매핑. |
| `FDAI_RBAC_BREAK_GLASS_GROUP_ID` | Break-Glass 매핑. |

선택 (기본값 적용):

| 변수 | 기본값 | 용도 |
|------|--------|------|
| `FDAI_ENTRA_ISSUER` | `https://login.microsoftonline.com/<tenant>/v2.0` | v1 토큰이나 소버린 클라우드 대응. |
| `FDAI_ENTRA_JWKS_URI` | 테넌트 디스커버리 엔드포인트 | 에어갭 클라우드 대응. |
| `FDAI_READ_API_CORS_ALLOW_ORIGINS` | 비어있음 (same-origin) | 콤마로 구분된 origin 목록. bare `*` 원소는 이 팩토리가 `RUNTIME_ENV`와 무관하게 무조건 거부한다 - 크로스-오리진 배포는 콘솔 origin을 명시적으로 나열해야 한다. |
| `FDAI_READ_API_STATEMENT_TIMEOUT_MS` | `20000` | 모든 read 쿼리에 `SET LOCAL statement_timeout`으로 적용. |
| `FDAI_READ_API_CONNECT_TIMEOUT_S` | `10` | TCP + auth 핸드셰이크를 제한해 죽은 DB가 빠르게 실패하도록. |
| `FDAI_KAFKA_BOOTSTRAP_SERVERS` | 비어 있음 | 프로덕션 Live 및 Agents SSE relay를 활성화합니다. `:9093`의 Event Hubs Kafka endpoint를 사용하며, 값이 비어 있으면 두 선택적 route를 등록하지 않습니다. |
| `KAFKA_TOPIC_EVENTS` | 비어 있음 | Kafka bootstrap과 함께 typed action 및 confirmed incident workflow용 `POST /chat/action`을 활성화합니다. Huginn이 consume하는 raw ingress topic과 같은 값을 사용합니다. |
| `FDAI_STAGE_TOPIC` | `aw.pipeline.stages` | worker가 게시하고 Live 및 Agents relay가 소비하는 단계 토픽입니다. worker와 read API는 같은 값을 사용하는 것이 좋습니다. |
| `FDAI_INCIDENT_SLA_POLICY_JSON` | 비어 있음(disabled) | 모든 `sev1`부터 `sev5`까지 positive `acknowledge_seconds` 및 `resolve_seconds` 값을 가진 strict JSON object입니다. Durable A2 SLA-breach monitoring을 활성화합니다. |
| `FDAI_INCIDENT_SLA_INTERVAL_SECONDS` | `60` | Positive SLA scan interval입니다. Policy JSON이 있을 때만 사용합니다. |
| `FDAI_IAM_DIRECTORY_PROVIDER` | 비어 있음 (directory 검색 비활성화) | Owner 전용 사용자 directory 검색을 활성화합니다. 구현된 값은 `entra`이며 지원되지 않는 향후 provider 이름은 startup을 차단합니다. |
| `FDAI_IAM_ENTRA_GRAPH_BASE_URL` | `https://graph.microsoft.com/v1.0` | Sovereign cloud 또는 테스트 override용 Microsoft Graph base URL입니다. Directory provider가 `entra`일 때만 사용합니다. |
| `FDAI_NARRATOR_PROBE_INTERVAL_SECONDS` | `300` | Routed narrator latency probe 간격(초)입니다. 최솟값은 `30`이며 주기 round마다 후보별 model-only sample을 하나 추가합니다. |
| `FDAI_WEB_SEARCH_ENABLED` | `false` | 조건을 충족한 Chat T2 turn에서 통제된 Azure Responses web search를 활성화합니다. Resolved narrator candidate와 allowed-domain 목록이 필요합니다. |
| `FDAI_WEB_SEARCH_ALLOWED_DOMAINS` | 비어 있음 | 콤마로 구분된 public source host입니다. Web search를 활성화할 때 필요하며 정확한 host를 최대 100개까지 허용합니다. |
| `FDAI_WEB_SEARCH_MAX_RESULTS` | `3` | 한 검색에서 유지할 citation 수입니다. `1`부터 `10`까지 허용합니다. |
| `FDAI_WEB_SEARCH_BUDGET_MS` | `15000` | 검색별 endpoint timeout(ms)입니다. |
| `FDAI_WEB_SEARCH_PROBE_INTERVAL_SECONDS` | `300` | Web-search candidate model probe 간격(초)입니다. 최솟값은 `30`이며 probe는 검색 툴을 호출하지 않습니다. |

Web search는 제한된 operator query만 Azure Responses로 전송합니다. 현재 화면
snapshot과 대화 history는 전송하지 않습니다. Azure web search는 Grounding with
Bing을 사용합니다. 이 전송은 배포의 compliance 및 geography boundary 밖으로 나갈
수 있고 Microsoft Data Protection Addendum의 적용을 받지 않습니다. 배포 owner가
해당 조건을 수락하고 primary-source allowlist를 구성하기 전에는 비활성 상태를
유지하는 것이 좋습니다.

Terraform은 provider를 `read_api_iam_directory_provider`로 노출하며 기본값은 비어 있습니다.
Read API managed identity에 필요한 Graph consent를 부여한 후에만 `entra`로 설정합니다.

Entra directory adapter는 read API managed identity를 통해
`https://graph.microsoft.com/.default`를 요청하며 admin consent가 적용된 Microsoft Graph
application permission `User.Read.All`이 필요합니다. 이 권한은 읽기 전용이며 브라우저에
전달되지 않습니다. 구성된 FDAI 역할 그룹과 사람 멤버를 projection하려면
`GroupMember.Read.All`도 필요합니다. 두 권한 모두 읽기 전용이며 그룹 멤버십 쓰기 권한은
포함하지 않습니다.

## 실행

```bash
uvicorn fdai.delivery.read_api.prod:app \
    --factory --host 0.0.0.0 --port 8000
```

`app` 팩토리는 워커당 한 번 호출된다. 위 모든 env가 프로세스 스코프에 있어야
한다. Container Apps 리비전에서 env는 Key Vault 시크릿을 직접 참조하는
`containerapp.secrets` 항목에서 프로젝션된다
([app-shape.instructions.md § Azure Mapping](../../../.github/instructions/app-shape.instructions.md#azure-mapping-draft---reconfirm-preview-services-at-adoption-time)).

## 어디에 뭐가 있나

- [`prod.py`](../../../src/fdai/delivery/read_api/prod.py) - 환경변수 전용
  composition root와 `app()` 팩토리.
- [`postgres_read_model.py`](../../../src/fdai/delivery/read_api/postgres_read_model.py)
  - `audit_log` + `state_kv` 위의 구체 :class:`ConsoleReadModel`. row -> dataclass
    매퍼와 경계가 정해진 KPI 집계는 같은 모듈의 순수함수로 분리되어 있어
    라이브 DB 없이 유닛테스트가 가능하다.
- [`main.py`](../../../src/fdai/delivery/read_api/main.py) - 공용 `build_app`
  글루 (라우트 등록, `_authorize` 게이트, staging/prod 트립와이어).
- [`streaming/live_stage_broadcaster.py`](../../../src/fdai/delivery/read_api/streaming/live_stage_broadcaster.py)
  - Kafka 단계 레코드를 검증하고 브라우저가 기대하는 원시 `event: stage` SSE
  계약을 유지합니다.

## 테스트

- `tests/delivery/read_api/test_prod.py` - env 파싱 + 조립 가드
  (DB 왕복 없음).
- `tests/delivery/read_api/streaming/test_live_stage_broadcaster.py` - 원시 단계
  relay, 잘못된 프레임 거부, lifecycle 동작.
- `tests/delivery/read_api/test_postgres_read_model_units.py` - row 매퍼,
  커서 파싱, KPI 집계 (DB 왕복 없음).
- `tests/persistence/test_postgres_console_read_model.py` -
  라이브 Postgres 대상 end-to-end 라운드트립. `FDAI_DATABASE_URL`이 없으면
  스킵. 로컬 `docker-compose` dev 스택 (`bash scripts/deployment/local/dev-up.sh`)이
  `postgresql+psycopg://fdai:devonly@localhost:5432/fdai`로 노출한다.

## 관련 문서

| 알고 싶은 내용 | 읽을 문서 |
|----------------|-----------|
| dev/prod 패리티 계약 | [dev-and-deploy-parity-ko.md](dev-and-deploy-parity-ko.md) |
| 배포 토폴로지 | [deployment-ko.md](deployment-ko.md) |
| RBAC + identity 흐름 | [../interfaces/user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md) |
| 콘솔 read-only 불변식 | [../../../.github/instructions/app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) |
