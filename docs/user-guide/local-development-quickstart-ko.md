---
title: 로컬 개발 빠른 시작
description: 저장소를 복제한 뒤 FDAI 콘솔 웹, Release Hub, 9개 Pure-Rust 로컬 스택 및 선택적 Docker 데이터 스택을 실행하는 방법을 알아봅니다.
translation_of: local-development-quickstart.md
translation_source_sha: c3e223ab76a9655535939f4d1a25b834407a1a8c
translation_revised: 2026-11-27
---

# 로컬 개발 빠른 시작

FDAI 저장소를 복제한 뒤 Rust stable 도구 모음과 `make`만 있으면 Pure-Rust **콘솔 웹**
(`fdai-console-v4`, 포트 `5290`), **Release Hub**(`fdai-release-hub`, 포트 `8022`), 또는 9개
Pure-Rust 전체 스택을 바로 실행할 수 있습니다. Docker는 로컬 PostgreSQL, Redpanda, ClamAV
연동이 필요할 때만 선택적으로 사용하며, Node.js는 SPA 소스를 직접 수정할 때만 필요합니다.

## 로컬 경로 선택

| 경로 | 명령 | 브라우저 / 상태 확인 URL | 외부 필수 도구 |
|------|------|--------------------------|----------------|
| 콘솔 웹 단독 실행 | `make console-v4-up` | `http://127.0.0.1:5290` | Rust stable (`cargo`), `make` |
| Release Hub 단독 실행 | `make release-hub-up` | `http://127.0.0.1:8022` | Rust stable (`cargo`), `make` |
| Lifecycle Hub 단독 실행 | `make lifecycle-hub-up` | `http://127.0.0.1:8021` | Rust stable (`cargo`), `make` |
| Pure-Rust 전체 스택(9개 서비스) | `make rust-fullstack-up` | Console `5290`, Release Hub `8022`, Lifecycle Hub `8021`, Operator API `8010` | Rust stable (`cargo`), `make` |
| Docker 데이터 스택 | `make dev-up` | PostgreSQL `5432` / `5433`, Redpanda `19092`, ClamAV `3310` | Docker Engine + Compose v2 |
| 선택적 SPA UI 실시간 리로드 개발 | `npm --prefix console run dev` 또는 `npm --prefix lifecycle_rs/release-hub/ui run dev` | Console SPA `5273`, Release Hub UI `5291` | Node.js 22+ 및 `npm` |

콘솔 웹(`fdai-console-v4`)과 Release Hub(`fdai-release-hub`)는 Azure 로그인, Entra 앱 등록,
Python 없이도 루프백에서 정상적으로 시작됩니다. PostgreSQL이나 업스트림 Azure 원본이 구성되지
않은 경우, 콘솔 웹은 가짜 런타임 데이터를 만들지 않고 `not-measured` 또는 오프라인 상태를 그대로
표시합니다.

## 필수 구성 요소 설치

### 콘솔 웹 및 Release Hub 실행 필수 도구

1. **Git 및 Make**: `git`, `bash`, `make`, `curl`을 준비합니다.
2. **Rust stable 도구 모음**: `PATH`에 `cargo`가 없다면 [rustup](https://rustup.rs/)으로
   설치합니다.

   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
   source "$HOME/.cargo/env"
   rustc --version
   cargo --version
   ```

3. **선택적 추적 Git 후크**(변경 사항을 커밋할 계획이라면 권장합니다):

   ```bash
   make hooks-install
   ```

새로 복제한 저장소에서는 기본적으로 `cargo ... --locked`를 사용하므로 Cargo가 `Cargo.lock`에
고정된 정확한 크레이트 버전을 최초 1회 다운로드한 뒤 이후 실행에서는 로컬 캐시를 재사용합니다.
Cargo 캐시가 이미 채워진 오프라인 환경에서는 `make` 실행 시 `CARGO_FLAGS="--locked --offline"`을
전달하거나 `make rust-fullstack-up` 전에 `FDAI_CARGO_OFFLINE=1`을 설정하세요.

### 선택 사항: Docker 데이터 스택

콘솔 웹에 실시간 로컬 PostgreSQL 데이터를 연결하거나 Redpanda 이벤트 전송, ClamAV 문서 검사를
사용하려면 Docker Engine 또는 Docker Desktop과 Docker Compose v2를 설치합니다. WSL에서는 Docker
Desktop의 [WSL 통합](https://docs.docker.com/desktop/features/wsl/)을 활성화하고 `sudo` 없이
Docker가 동작하는지 확인하세요.

```bash
docker version
docker compose version
docker info
```

### 선택 사항: SPA 소스 편집용 Node.js 22+

사전 빌드된 Release Hub UI(`lifecycle_rs/release-hub/ui/dist`)와 Lifecycle Hub UI
(`lifecycle_rs/hub/ui/dist`)는 저장소에 함께 추적되며, Console v4(`console_rs/`)는 HTML
템플릿과 정적 에셋을 Rust 바이너리에서 직접 제공합니다. Node.js 22 이상은 `console/`,
`lifecycle_rs/release-hub/ui/`, `lifecycle_rs/hub/ui/`의 TypeScript 또는 Preact UI 소스를
수정할 때만 설치하세요.

## 콘솔 웹 실행 (`http://127.0.0.1:5290`)

저장소 루트에서 독립 실행형 Pure-Rust Console v4 서버를 시작합니다.

```bash
make console-v4-up
```

동일한 직접 Cargo 명령은 다음과 같습니다.

```bash
cargo run --locked -p fdai-console-v4 -- --host 127.0.0.1 --port 5290
```

브라우저에서 `http://127.0.0.1:5290`을 열거나 다른 터미널에서 준비 상태를 확인하세요.

```bash
cargo run --locked -p fdai-console-v4 -- --check
curl -sS http://127.0.0.1:5290/api/v4/meta
```

### 콘솔 웹 옵션 및 실시간 PostgreSQL 연동

- **사용자 지정 호스트/포트**: `--host` / `--port` 인수를 전달하거나 `FDAI_CONSOLE_V4_HOST`,
  `FDAI_CONSOLE_V4_PORT` 환경 변수를 설정합니다.
- **실시간 로컬 PostgreSQL 연결**: `make dev-up`으로 Docker를 시작한 뒤 `FDAI_DATABASE_URL`을
  내보내거나 `.fdai/local-runtime.env`의 루프백 `FDAI_DATABASE_URL`을 `fdai-console-v4`가
  자동으로 읽도록 합니다. 로컬 루프백 쓰기 엔드포인트를 명시적으로 허용할 때만
  `FDAI_CONSOLE_V4_ALLOW_DB_WRITES=1`을 설정하세요.
- **Operator API 업스트림 프록시**: `fdai-console-v4`는 운영자 경로를 `FDAI_OPERATOR_URL`
  (기본값 `http://127.0.0.1:8010`)로 프록시합니다.

## Release Hub 실행 (`http://127.0.0.1:8022`)

저장소 루트에서 사전 빌드 UI가 포함된 Pure-Rust Release Hub 서버를 시작합니다.

```bash
make release-hub-up
```

동일한 직접 Cargo 명령은 다음과 같습니다.

```bash
cargo run --locked -p fdai-release-hub -- \
  --host 127.0.0.1 \
  --port 8022 \
  --static-dir lifecycle_rs/release-hub/ui/dist
```

브라우저에서 `http://127.0.0.1:8022`를 열거나 다른 터미널에서 준비 상태를 확인하세요.

```bash
cargo run --locked -p fdai-release-hub -- --check
curl -sS http://127.0.0.1:8022/healthz
curl -sS http://127.0.0.1:8022/auth/config
```

### Release Hub 옵션 및 UI 개발

- **로컬 프로필 및 상태 파일**: Entra 환경 변수가 설정되지 않으면 Release Hub는 루프백
  `local-development` 모드(`{"profile":"local-development"}`)로 시작하며 기본적으로
  `.fdai/release-hub-state.json`에 상태를 저장합니다. 파일 경로는 `FDAI_RELEASE_HUB_STATE_PATH`,
  포트는 `FDAI_RELEASE_HUB_PORT` 또는 `--port`로 변경할 수 있습니다.
- **프런트엔드 수정 후 Release Hub UI 다시 빌드**:

  ```bash
  npm --prefix lifecycle_rs/release-hub/ui ci
  npm --prefix lifecycle_rs/release-hub/ui run build
  ```

- **실시간 리로드 UI 개발 서버**: `lifecycle_rs/release-hub/ui/vite.config.ts`의 Vite 서버는
  `http://127.0.0.1:5291`에서 동작하며 `/v1`, `/healthz`, `/auth`를 `http://127.0.0.1:8091`로
  프록시합니다. Vite HMR을 사용하려면 한 터미널에서 Release Hub를 포트 `8091`로 실행하고 다른
  터미널에서 Vite를 실행하세요.

  ```bash
  cargo run --locked -p fdai-release-hub -- --host 127.0.0.1 --port 8091
  npm --prefix lifecycle_rs/release-hub/ui run dev
  ```

- **Lifecycle Hub**: `make lifecycle-hub-up`으로 `http://127.0.0.1:8021`에서 `fdai-hub`를
  실행합니다. 카탈로그 신뢰 모델과 운영자 경계는
  [lifecycle_rs/release-hub/README.md](../../lifecycle_rs/release-hub/README.md)와
  [Hub 수명 주기 운영자 가이드](../runbooks/hub-lifecycle-operator-guide-ko.md)를 참조하세요.

## 9개 Pure-Rust 서비스 전체 동시 실행

콘솔 웹, Release Hub, Lifecycle Hub와 6개 핵심 Pure-Rust Axum 서비스를 한 번에 실행하려면 다음
명령을 사용합니다.

```bash
make rust-fullstack-up
```

이 명령은 [`deploy_rs/start-fullstack-rust.sh`](../../deploy_rs/start-fullstack-rust.sh)를 실행해
9개 바이너리를 모두 빌드하고 백그라운드로 시작한 뒤 모든 상태 확인 엔드포인트를 검증합니다.
로그는 `.fdai/logs/<service>.log`, PID 목록은 `.fdai/rust-fullstack.pids`에 기록됩니다. 전체
스택을 중지하려면 다음 명령을 실행하세요.

```bash
make rust-fullstack-down
```

| 서비스 | 기본 주소 | 상태 / 메타데이터 엔드포인트 |
|--------|-----------|------------------------------|
| 콘솔 웹 (`fdai-console-v4`) | `http://127.0.0.1:5290` | `http://127.0.0.1:5290/api/v4/meta` |
| Release Hub (`fdai-release-hub`) | `http://127.0.0.1:8022` | `http://127.0.0.1:8022/healthz` |
| Lifecycle Hub (`fdai-hub`) | `http://127.0.0.1:8021` | `http://127.0.0.1:8021/healthz` |
| Operator API (`fdai-operator-service`) | `http://127.0.0.1:8010` | `http://127.0.0.1:8010/healthz` |
| Document Ingestion API | `http://127.0.0.1:8011` | `http://127.0.0.1:8011/healthz` |
| Document Processing Worker | `http://127.0.0.1:8012` | `http://127.0.0.1:8012/healthz` |
| Isolated Executor | `http://127.0.0.1:8013` | `http://127.0.0.1:8013/healthz` |
| Core Control Plane | `http://127.0.0.1:8014` | `http://127.0.0.1:8014/healthz` |
| System Knowledge Service | `http://127.0.0.1:8016` | `http://127.0.0.1:8016/healthz` |

VS Code에서는 **Tasks: Run Task**에서 `console-v4: serve (5290)`, `release-hub: serve (8022)`,
`lifecycle-hub: serve (8021)`, `fullstack: start Pure-Rust stack`, `fullstack: stop Pure-Rust stack`
작업을 선택해 실행할 수 있습니다.

## 선택적 Docker 데이터 스택 시작 및 검사

실시간 로컬 데이터베이스 테이블이나 통합 테스트가 필요할 때 PostgreSQL, Redpanda, ClamAV를
시작합니다.

```bash
make dev-up
docker compose -f infra/local/docker-compose.yml ps
```

처음 `make dev-up`을 실행하면 `infra/local/.env.example`을 Git에서 무시되는 `infra/local/.env`
(로컬 전용 `devonly` 암호 사용)로 복사하고 모든 컨테이너가 정상 상태가 될 때까지 기다립니다.

| 컨테이너 | 이미지 | 루프백 포트 | 영속 볼륨 |
|----------|--------|-------------|-----------|
| 런타임 PostgreSQL | `pgvector/pgvector:pg16` | `5432` | `fdai-pgdata` |
| 검증 PostgreSQL | `pgvector/pgvector:pg16` | `5433` | `fdai-validation-pgdata` |
| Redpanda | `redpandadata/redpanda:v26.2.2` (digest 고정) | Kafka `19092`, 관리 `9644` | `fdai-redpandadata` |
| ClamAV | `clamav/clamav:stable` | `3310` | `fdai-clamavdata` |

게시된 모든 컨테이너 포트는 `127.0.0.1`에 바인딩됩니다. 호스트 Kafka 클라이언트는
`127.0.0.1:19092`를 사용하고, `fdai-local` Docker 네트워크의 컨테이너는 `redpanda:29092`를
사용합니다.

### Docker 데이터 중지 또는 초기화

| 명령 | 효과 |
|------|------|
| `make dev-down` | Docker 컨테이너를 중지하고 이름이 지정된 볼륨 4개를 보존합니다. |
| `make dev-up` | 기존 데이터를 사용해 컨테이너를 다시 시작합니다. |
| `make dev-nuke` | 컨테이너를 중지하고 Docker 볼륨 4개를 영구적으로 제거합니다. |

## 선택 사항: Azure, Entra 및 레거시 SPA 구성

실제 Azure 구독을 대상으로 Browser Entra 로그인이나 Azure 기반 조회를 사용하려면
`az login --use-device-code`로 로그인한 뒤 [Entra 앱 등록 실행서](../runbooks/entra-app-registration-ko.md)의
값을 사용해 Git에서 무시되는 `console/.env.local`을 생성합니다.

```dotenv
VITE_MSAL_CLIENT_ID=<spa-app-client-id>
VITE_MSAL_TENANT_ID=<tenant-id>
VITE_MSAL_API_SCOPE=api://<operator-api-app-client-id>/access
VITE_OPERATOR_API_BASE_URL=http://127.0.0.1:8010
VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011
```

`deploy_rs/start-fullstack-rust.sh`는 `.fdai/local-operator-service.env` 또는 `console/.env.local`이
있으면 로컬 Operator API에 맞는 Entra 테넌트와 대상(audience) 설정을 자동으로 불러옵니다. 레거시
Preact SPA(`console/`, 포트 `5273`)를 개발하려면 `npm --prefix console ci --no-audit --no-fund` 후
`npm --prefix console run dev`를 실행하세요.

## 시작 문제 해결

### `cargo`를 찾을 수 없거나 오프라인 캐시 오류가 발생함

- `rustup`으로 Rust stable 도구 모음을 설치하고 `$HOME/.cargo/bin`을 `PATH`에 추가하세요.
- 저장소를 새로 복제한 직후에는 기본 `--locked` 빌드(`make console-v4-up`, `make release-hub-up`,
  `make rust-fullstack-up`)를 사용합니다. Cargo가 워크스페이스 크레이트를 한 번 다운로드하기 전에는
  `--offline` 옵션을 지정하지 마세요.

### 필수 포트가 이미 사용 중임

- 기본 Pure-Rust 서비스 포트는 `5290`(콘솔 웹), `8022`(Release Hub), `8021`(Lifecycle Hub),
  `8010`-`8016`(Core 및 Operator 서비스)입니다.
- 이전 전체 스택 실행은 `make rust-fullstack-down`으로 중지하거나, `FDAI_CONSOLE_PORT`,
  `FDAI_RELEASE_HUB_PORT`, `FDAI_LIFECYCLE_HUB_PORT` 또는 `--port`로 포트를 변경하세요.
- Docker 포트는 `5432`, `5433`, `19092`, `9644`, `3310`으로 고정되어 있습니다. Compose 포트를
  바꾸지 말고 충돌하는 프로세스를 중지하세요.

### Docker가 없거나 컨테이너가 비정상 상태임

- 같은 셸에서 `sudo` 없이 `docker version`, `docker compose version`, `docker info`를 실행합니다.
  사용자를 `docker` 그룹에 추가한 뒤에는 WSL 창을 다시 열거나 VS Code를 재시작하세요.
- 데이터를 삭제하지 않고 컨테이너 로그를 확인합니다.

  ```bash
  docker compose -f infra/local/docker-compose.yml ps
  docker compose -f infra/local/docker-compose.yml logs --tail=100 \
    postgres postgres-validation redpanda clamav
  ```

## 로컬 상태와 배포 상태 분리

Azure 조회를 활성화해도 로컬 서비스는 루프백 PostgreSQL(`127.0.0.1:5432`)과 `.fdai/` 아래의
로컬 상태 파일을 사용합니다. Azure PostgreSQL DSN을 로컬 환경 파일에 복사하거나, 로컬 DSN을 배포
구성에 복사하거나, 로컬 기록을 배포 근거로 제시하지 마세요.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 상세 로컬 점검 목록 및 검증 명령 | [로컬 개발 설정](../../DEVELOPING.md) |
| Release Hub 로컬 실행, 경로 및 UI | [Release Hub README](../../lifecycle_rs/release-hub/README.md) |
| Console SPA 아키텍처 및 로컬 인증 동작 | [Console README](../../console/README.md) |
| Entra 등록 및 App Role | [Entra 앱 등록](../runbooks/entra-app-registration-ko.md) |
| 선택적 비공개 엔드포인트 VPN 접근 | [격리된 개발 접근](../../tools/dev-access/README.md) |
| Azure 구독 배포 | [배포 빠른 시작](deploy-quickstart-ko.md) |
| 기여 및 검증 작업 흐름 | [기여](../../CONTRIBUTING.md) |
