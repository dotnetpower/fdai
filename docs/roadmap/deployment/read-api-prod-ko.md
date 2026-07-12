---
title: 콘솔 read-API 프로덕션 배포
translation_of: read-api-prod.md
translation_source_sha: 7cde510929777f98b48081d261e3191d220677aa
translation_revised: 2026-07-13
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
  `dev_mode=False`로 호출한다. 그 결과 read-only 불변식(POST 라우트 없음)과
  staging/prod 트립와이어(CORS `*` 거부, dev-mode 거부)가 그대로 적용된다.
- **환경변수 전용 조립.** 팩토리가 필요로 하는 모든 값은 포크의 IaC가 Key Vault
  참조에서 채우는 환경변수로 도착한다. 설정 파일이 필요 없고, 고객 식별자가
  이미지에 박히지 않는다.
- **누락된 config는 즉시 실패.** 필수 env가 없으면 시작 시점에
  :class:`ProdReadApiConfigError`(`ValueError`의 서브클래스)가 발생한다.
  깨진 리비전은 절대 소켓을 바인딩하지 못한다. env가 통째로 비어있는
  콜드 부트에서는 누락된 슬롯 8개를 순차 실패로 겪는 대신 한 번의
  에러로 모두 열거되어 보인다.

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

## 테스트

- `tests/delivery/read_api/test_prod.py` - env 파싱 + 조립 가드
  (DB 왕복 없음).
- `tests/delivery/read_api/test_postgres_read_model_units.py` - row 매퍼,
  커서 파싱, KPI 집계 (DB 왕복 없음).
- `tests/persistence/test_postgres_console_read_model.py` -
  라이브 Postgres 대상 end-to-end 라운드트립. `FDAI_DATABASE_URL`이 없으면
  스킵. 로컬 `docker-compose` dev 스택 (`bash scripts/dev-up.sh`)이
  `postgresql+psycopg://fdai:devonly@localhost:5432/fdai`로 노출한다.

## 관련 문서

| 알고 싶은 내용 | 읽을 문서 |
|----------------|-----------|
| dev/prod 패리티 계약 | [dev-and-deploy-parity-ko.md](dev-and-deploy-parity-ko.md) |
| 배포 토폴로지 | [deployment-ko.md](deployment-ko.md) |
| RBAC + identity 흐름 | [../interfaces/user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md) |
| 콘솔 read-only 불변식 | [../../../.github/instructions/app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) |
