---
title: 로컬 개발 빠른 시작
description: Linux 또는 WSL 워크스테이션에서 Docker, 로컬 상태, 인증 및 전체 FDAI Console 스택을 구성합니다.
translation_of: local-development-quickstart.md
translation_source_sha: c386f2e95a378517ae3836af19830e083b188bf6
translation_revised: 2026-09-22
---

# 로컬 개발 빠른 시작

FDAI 로컬 개발에서는 PostgreSQL, Redpanda 및 ClamAV를 Docker로 실행하고 Python과 Node.js
서비스는 호스트에서 실행합니다. 이 가이드를 사용해 Docker 전용 데이터 스택을 구성하거나
Azure 및 Microsoft Entra 연결이 포함된 전체 Console 스택을 준비할 수 있습니다.

## 로컬 경로 선택

| 경로 | 용도 | Azure 요구 사항 |
|------|------|-----------------|
| Docker 데이터 스택 | 영속성 테스트, 마이그레이션, Kafka 호환 이벤트 개발 및 문서 검사 | 없음 |
| 전체 Console 스택 | Console, 백엔드 서비스 5개, 인벤토리와 관찰 루프, 문서 처리 및 Manual Studio | 활성 Azure CLI 세션, 일치하는 Entra 앱 등록, 그리고 적용된 `infra/` 상태 또는 명시적으로 선택한 기존 조회 범위 리소스 그룹 |

전체 스택은 오프라인 데모가 아닙니다. 데이터베이스와 이벤트 전송은 로컬에서 실행되지만,
Azure 읽기와 환경 메타데이터는 선택한 배포에 근거합니다. 읽을 수 있는 배포 상태가 아직
없으면 Docker 데이터 스택과 결정론적 테스트부터 시작하세요.

> 공개 기여자 배포는 격리된 Terraform 상태를 `.fdai/deploy/public-dev-<suffix>/` 아래에
> 보관합니다. 현재 전체 로컬 스택 준비는 초기화된 `infra/` 백엔드를 읽으며 이 격리 상태를
> 자동으로 채택하지 않습니다. 이 경계를 우회하기 위해 상태 파일을 복사하거나 이동하지 마세요.

## 필수 구성 요소 설치

### 한 번에 워크스테이션 구성

x86_64 Ubuntu 또는 WSL에서는 리포지토리 루트에서 다음 설치 스크립트를 실행하세요.

```bash
bash scripts/automation/setup-local-development.sh
```

이 스크립트는 시스템 패키지와 리포지토리에 고정된 명령줄 도구를 설치하고, Docker 접근을
구성하며, 잠금 파일에 정의된 Python 및 Console 의존성을 설치합니다. 또한 Playwright Chromium을
다운로드하고, 추적되는 Git 후크를 활성화하며, 공유 VS Code 설정과 확장을 적용합니다. 런타임 및
검증용 PostgreSQL과 pgvector, Redpanda, ClamAV로 구성된 Docker 데이터 스택도 시작하고 준비될 때까지
기다립니다. 필요한 경우 터미널에서 `sudo` 입력을 요청합니다. Azure 또는 GitHub에 로그인하거나
테넌트별 구성을 만들지는 않습니다.

설치 스크립트는 새로 할당된 Docker 그룹을 사용해 첫 실행 중에도 데이터 스택을 시작할 수 있습니다.
Docker 명령을 직접 실행하기 전에는 기존 터미널에 그룹 멤버십을 반영하도록 WSL 창을 다시 여세요.
프로필 가져오기는 사용자가 확인해야 하는 VS Code 작업이므로 `Profiles: Import Profile`에서
`.vscode/fdai.code-profile`을 가져오세요. 다음 명령으로 도구 모음과 데이터 스택의 정상 상태를
변경 없이 검증할 수 있습니다.

```bash
bash scripts/automation/setup-local-development.sh --check
```

필수 구성 요소를 수동으로 설치하거나 실패한 검사를 진단해야 할 때는 다음 섹션을 사용하세요.

### Docker 데이터 스택

Docker Engine 또는 Docker Desktop과 Docker Compose v2를 설치합니다. WSL에서는 Docker Desktop의
[WSL 통합](https://docs.docker.com/desktop/features/wsl/)을 활성화하거나 같은 WSL 배포판에서 다른
Docker Engine을 사용할 수 있도록 구성합니다. VS Code와 FDAI를 실행하는 사용자가 `sudo` 없이
Docker를 실행할 수 있어야 합니다. 처음 시작할 때는 아래 이미지의 컨테이너 레지스트리에
접근할 수도 있어야 합니다.

시작 스크립트가 사용하는 기능을 정확히 확인합니다.

```bash
docker version
docker compose version
docker info
```

명령이 하나라도 실패하면 계속하기 전에 Docker
[설치 가이드](https://docs.docker.com/engine/install/)를 따르세요. FDAI에는 Docker CLI,
`docker compose` v2 플러그인 및 접근 가능한 데몬이 필요합니다.

### 전체 Console 스택

다음 도구도 설치합니다.

- 워크스페이스 환경을 위한 Python 3.13과 `uv`.
- Console과 Manual Studio를 위한 Node.js 22 이상 및 `npm`.
- 배포 환경 메타데이터를 위한 Terraform 1.9 이상과 Azure CLI.
- [Core 이미지](../../services/core-control-plane/docker/Dockerfile)의 `OPA_VERSION`과 같은 버전의 OPA.
  리포지토리 루트에서 `opa version`과 `opa check policies`를 실행하세요. VS Code 작업의
  `PATH`에서 OPA를 찾을 수 있어야 합니다. 워크스페이스는 사용자 설치 도구를 위해
  `~/.local/bin`을 포함합니다.
- 커밋과 푸시 전에 리포지토리 shell script를 검증하기 위한 ShellCheck.
- `git`, `bash`, `make`, `curl` 및 표준 Linux 명령줄 도구.
- 영어와 한국어 언어 데이터가 포함된 Tesseract. Document Processing Worker는 호스트에서
  실행되고 ClamAV는 Docker에서 실행됩니다.

Ubuntu 또는 WSL에서는 다음과 같이 ShellCheck와 Tesseract를 설치합니다.

```bash
sudo apt-get update
sudo apt-get install -y shellcheck tesseract-ocr tesseract-ocr-eng tesseract-ocr-kor
shellcheck --version
tesseract --list-langs
```

한 번에 설치하는 스크립트를 사용하지 않는 경우 리포지토리 의존성과 후크를 설치합니다.

```bash
uv sync --extra dev
make hooks-install
npm --prefix console ci --no-audit --no-fund
```

[VS Code 프로필 설정](../../DEVELOPING.md#1-vs-code-profile-recommended)을 권장하지만 이 프로필은
Docker, Python, Node.js, OPA, Terraform 또는 Azure CLI를 설치하지 않습니다.

### 처리 준비 상태 확인

관리형 `console: start full stack` 작업을 사용하세요. 프런트엔드의 HTTP `200`, API 생존 확인
응답, `pantheon_ready` 로그만으로 Core 소비자가 실행 중이라고 판단할 수는 없습니다. OPA가
없으면 Core 처리가 차단되므로 준비 스크립트는 의존 서비스를 시작하기 전에 OPA를 확인합니다.
현재 준비 상태 보고서와 최신 Pantheon heartbeat를 확인한 뒤 `http://localhost:5273`의
Console에서 대화를 검증하세요.

`resolved-models.json` 생성은 선택된 모델 배포의 존재나 접근 가능성을 보장하지 않습니다.
모델 구성을 완료로 판단하기 전에 배포 이름, 엔드포인트 바인딩, 신원 접근 권한, 시스템
프롬프트와 출력 토큰을 포함한 전체 요청에 필요한 용량을 확인하세요. 시작 검사를 우회하려고
생성된 모델 기록을 직접 편집하거나 필수 기능을 제거하지 마세요. `429`, 타임아웃 또는 플래너
사용 불가는 대화 검증 실패이며 구성 성공이 아닙니다. 실제 호출 재시도를 중단하고 보고된
전제 조건을 해결하세요. 네트워크 제한과 RBAC는 유지합니다.

## 인증 및 로컬 파일 구성

### Azure 및 Terraform 컨텍스트 선택

커밋된 전체 스택 실행기가 사용하는 기본 Azure CLI 프로필로 로그인하고 확인합니다.

```bash
az login --use-device-code
env -u AZURE_CONFIG_DIR az account show \
  --query '{subscription:name,subscriptionId:id,tenant:tenantId,user:user.name}' \
  --output table
```

로컬 Console 준비 과정은 Terraform 상태를 초기화하거나 읽지 않습니다. 선택한 배포에서 비공개
엔드포인트만 제공한다면 해당 Azure 기반 읽기를
사용하기 전에 선택 사항인 [개발 VPN](../../tools/dev-access/README.md)을 구성하세요.

#### Azure 읽기 범위 선택

모든 로컬 Console 스택에 `FDAI_LOCAL_RESOURCE_GROUP=<existing-read-scope>`를 설정하세요.
준비 스크립트는 활성 Azure CLI 구독에서 해당 그룹을 검증하고 리전을 읽습니다. 범위가 없거나
잘못되면 준비를 중단하며, 리소스 그룹을 만들어 내거나 구독 전체를 암묵적으로 선택하지 않습니다.

VS Code 작업에서 같은 명시적 범위를 재사용하려면 아래에서 설명하는 Git에서 무시되는
`console/.env.local` 파일에 이 설정을 추가합니다.

```dotenv
FDAI_LOCAL_RESOURCE_GROUP=<existing-read-scope>
```

프로세스 환경에 명시적으로 내보낸 값은 파일의 값보다 우선합니다. 선택한 리소스 그룹은 로컬
워크스테이션에만 보관하고 커밋하지 마세요. 한 번 성공적으로 실행한 뒤에는 소유자 전용으로 생성된
로컬 런타임 환경에서 같은 범위를 재사용할 수 있습니다.

PostgreSQL, Redpanda 및 ClamAV는 계속 로컬에서 실행됩니다. 준비 과정은 선택한 범위의 제한된
읽기에만 Azure CLI를 사용합니다. 일치하는 Function App이 정확히 하나이고 비공개
`VITE_MSAL_API_SCOPE`에서 검증된 Operator API audience를 제공할 때만 개발 운영 게이트웨이를
연결합니다. 후보가 없으면 관리 리소스 실행을 사용할 수 없고 여러 후보가 있으면
준비를 중단합니다. 로컬 Console에는 실행기 신원을 제공하지 않습니다. Azure 변경에는 별도로
배포된 실행기, ActionType별 영속 승격 근거, 필요한 사람 승인, 예행 실행, 롤백, 감사 및 독립 효과
검증이 필요합니다. 로그인은 기존 Entra 앱 등록 또는 명시적으로 선택한 Azure CLI principal 모드를
사용합니다.

### Console 환경 생성

Entra 앱 등록 값을 사용해 Git에서 무시되는 `console/.env.local`을 생성합니다.

```dotenv
VITE_MSAL_CLIENT_ID=<spa-app-client-id>
VITE_MSAL_TENANT_ID=<tenant-id>
VITE_MSAL_API_SCOPE=api://<operator-api-app-client-id>/access
VITE_OPERATOR_API_BASE_URL=http://127.0.0.1:8010
VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011
```

테넌트는 기본 Azure CLI 프로필과 일치해야 합니다. API 대상, SPA 등록, 위임 범위, App Role
또는 로컬 리디렉션 URI가 아직 없으면 [Entra 앱 등록 실행서](../runbooks/entra-app-registration-ko.md)를
따르세요. 값이 채워진 파일은 커밋하지 마세요. 전체 스택 준비는 두 루프백 SPA 리디렉션 URI를
안전하게 추가하며 로그인한 신원이 해당 앱 등록을 업데이트할 수 없으면 서비스 시작 전에
중단합니다.

준비 작업은 `.fdai/local-runtime.env`와 서비스별 `.fdai/local-*.env` 파일을 생성합니다.
이 파일은 생성된 비공개 파일이므로 편집하거나 배포 환경으로 복사하지 마세요.

### Docker 환경 이해

처음 `make dev-up`을 실행하면 `infra/local/.env.example`을 Git에서 무시되는
`infra/local/.env`로 복사합니다. 표준 스택은 로컬 DSN에도 같은 값이 사용되므로 커밋된 로컬
전용 PostgreSQL 암호 `devonly`를 사용합니다. 이 값은 루프백 개발 스택 밖에서 재사용하지 마세요.

루트의 `resolved-models.json`은 선택 사항입니다. 이 파일이 없으면 시작할 때 로컬 LLM 호출과
계량을 사용할 수 없다고 보고하지만 결정론적 경로는 계속 실행됩니다.
`resolved-models-local.json`은 전체 스택 작업에서 자동으로 선택되지 않습니다.

## Docker 시작 및 검사

Docker를 독립적으로 확인하려면 의존성을 먼저 시작할 수 있습니다.

```bash
make dev-up
docker compose -f infra/local/docker-compose.yml ps
```

전체 스택 준비 작업도 `make dev-up`을 실행하므로 이 별도 단계는 선택 사항입니다. 시작 과정은
모든 컨테이너 상태 검사를 기다리고 Redpanda 커뮤니티 구성과 로컬 토픽 기본 파티션 2개를
일치시킵니다.

| 컨테이너 | 이미지 | 루프백 포트 | 영속 볼륨 |
|----------|--------|-------------|-----------|
| 런타임 PostgreSQL | `pgvector/pgvector:pg16` | `5432` | `fdai-pgdata` |
| 검증 PostgreSQL | `pgvector/pgvector:pg16` | `5433` | `fdai-validation-pgdata` |
| Redpanda | `redpandadata/redpanda:latest` | Kafka `19092`, 관리 `9644` | `fdai-redpandadata` |
| ClamAV | `clamav/clamav:stable` | `3310` | `fdai-clamavdata` |

게시된 모든 컨테이너 포트는 `127.0.0.1`에 바인딩됩니다. Compose 프로젝트는 이름이 지정된
`fdai-local` 네트워크도 생성합니다. 다른 Compose 프로젝트의 컨테이너는 이 네트워크에
명시적으로 연결해야 합니다. 호스트 Kafka 클라이언트는 `127.0.0.1:19092`를 사용하고
`fdai-local`의 컨테이너는 `redpanda:29092`를 사용합니다.

## 전체 스택 시작

일반 개발에서는 VS Code에서 `Tasks: Run Task` -> `console: start full stack`을 실행합니다. 이
작업은 의존성을 준비하고 Docker를 시작하거나 재사용하며, 두 데이터베이스를 마이그레이션하고,
서비스 소유 역할을 생성하고, 로컬 변환 결과와 카탈로그를 구체화하고, 비공개 서비스 환경을
생성한 뒤 모든 서비스를 시작합니다. 기본 Git 체크아웃에서만 실행할 수 있습니다.

서비스 프로세스를 디버거가 소유해야 한다면 `Run and Debug` -> `Console Web: Full Stack`을
사용합니다. 두 경로는 같은 준비 스크립트를 사용합니다. 처음 실행할 때는 이미지와 의존성을
가져오므로 더 오래 걸릴 수 있습니다. 이후 실행에서는 입력과 출력이 바뀌지 않은 단계를
재사용합니다.

준비는 성공했지만 서비스 감독기가 시작되지 않으면 `Tasks: Run Task` ->
`console: start local services`를 실행합니다. 이 표시되는 백그라운드 작업은 준비된 환경을
재사용하고 준비를 반복하지 않은 채 전체 서비스 집합을 시작합니다. 그런 다음
`console: wait full stack ready`를 실행하세요. 전체 시작이 완료되면 `ready: 10/10`과
`unavailable: none`을 보고합니다.

| 화면 또는 서비스 | 주소 또는 준비 신호 |
|-------------------|----------------------|
| Console | `http://localhost:5273` |
| Manual Studio | `http://127.0.0.1:5474` |
| Operator API | `http://127.0.0.1:8010/healthz` |
| Document Ingestion API | `http://127.0.0.1:8011` |
| Document Processing Worker | `127.0.0.1:8012`의 상태 수신기 |
| Isolated Executor | `127.0.0.1:8013`의 상태 수신기 |
| Core Runtime | 새로운 Pantheon 하트비트 이후 준비 완료 |

준비 과정은 `http://localhost:5273`과 `http://127.0.0.1:5273`을 모두 로컬 SPA 리디렉션으로
등록합니다. 인증과 세션 상태가 호스트 이름에 따라 분리되지 않도록 표준 브라우저 원점인
`http://localhost:5273`을 사용하세요.

원격 WSL 워크스페이스에서는 VS Code 통합 브라우저가 원격 포트를 전달하면서 `localhost`를
`127.0.0.1`로 다시 쓸 수 있습니다. 이는 Console 서버 또는 Entra 구성이 바뀐 것이 아니라
브라우저의 포트 전달 동작입니다. 표준 인증 및 세션 원점이 필요하면 호스트의 일반 Chrome 또는
Edge 창에서 `http://localhost:5273`을 여세요.

`console: wait full stack ready` 작업은 시작에 성공한 후 범위가 제한된 진단에만 사용합니다.
서비스 로그는 `.fdai/logs/` 아래에 있습니다.

## 로컬 데이터 중지 또는 초기화

Docker 의존성을 중지하기 전에 VS Code 작업 또는 디버그 복합 구성을 중지합니다.

| 명령 | 효과 |
|------|------|
| `make dev-down` | Docker 컨테이너를 중지하고 이름이 지정된 볼륨 4개를 보존합니다. |
| `make dev-up` | 기존 데이터를 사용해 컨테이너를 다시 시작합니다. |
| `make dev-nuke` | 컨테이너를 중지하고 Docker 볼륨 4개를 영구적으로 제거합니다. |

`make dev-nuke` 이후 다음 전체 스택 준비에서 데이터베이스를 다시 만들고 마이그레이션을
재실행합니다. 이 명령은 `.fdai/document-store`, 생성된 환경 또는 서비스 로그를 삭제하지
않습니다.

## Docker 및 시작 문제 해결

### Docker 누락 또는 접근 불가

VS Code 작업을 실행하는 것과 같은 Linux 또는 WSL 셸에서 세 가지 확인 명령을 실행합니다.
`docker info`가 권한 거부를 보고하거나 데몬에 접근하지 못하면 FDAI 스택을 `sudo`로 실행하지
말고 해당 사용자의 데몬 접근을 수정합니다. 사용자를 `docker` 그룹에 추가한 후에는 작업을
실행하기 전에 WSL 창을 다시 열거나 VS Code를 재시작하여 확장 호스트에 새 그룹 멤버십을
반영합니다.

### 비정상 컨테이너

데이터를 삭제하지 않고 상태와 제한된 로그를 확인합니다.

```bash
docker compose -f infra/local/docker-compose.yml ps
docker compose -f infra/local/docker-compose.yml logs --tail=100 \
  postgres postgres-validation redpanda clamav
```

ClamAV는 처음 시작할 때 서명을 초기화하느라 시간이 더 필요할 수 있습니다. 모든 로컬
데이터베이스, 이벤트 및 검사기 상태를 의도적으로 폐기할 때만 `make dev-nuke`를 사용하세요.

### 필수 포트가 이미 사용 중임

Docker 포트는 `5432`, `5433`, `19092`, `9644`, `3310`입니다. 충돌하는 루프백 포트를 소유한
프로세스나 Compose 프로젝트를 중지하세요. 생성된 로컬 서비스 환경에서 이 고정 값을
사용하므로 FDAI 포트를 개별적으로 변경하지 마세요.

### 서비스 시작 전 Console 준비 중단

- **`console/.env.local` 누락**: 위 Entra 값으로 파일을 생성합니다.
- **Entra 테넌트 불일치**: `VITE_MSAL_TENANT_ID`를
  `env -u AZURE_CONFIG_DIR az account show --query tenantId -o tsv`와 비교합니다.
- **Terraform 출력 실패**: 의도한 `infra/` 백엔드를 초기화하고 배포 상태를 확인합니다. Azure
  PostgreSQL DSN을 대신 사용하거나 상태 파일을 복사하지 마세요.
- **연결된 작업 트리 거부**: 기본 체크아웃을 사용하거나 기본 스택을 먼저 중지합니다.
- **Tesseract 언어 실패**: `tesseract --list-langs`에 `eng`와 `kor`가 모두 표시되는지 확인합니다.

Azure 기반 화면을 사용할 수 없다는 사실이 자동으로 Docker 실패를 의미하지는 않습니다. 먼저
로컬 서비스 상태를 확인한 다음 선택한 Azure 원본과 기능이 실제로 배포되어 있고 읽을 수 있는지
확인합니다.

## 로컬 상태와 배포 상태 분리

Azure 읽기를 활성화해도 로컬 서비스는 루프백 PostgreSQL과 Redpanda를 사용합니다. Azure
PostgreSQL DSN을 생성된 로컬 환경에 복사하거나 로컬 DSN을 배포 구성으로 복사하거나 로컬
레코드를 배포 근거로 제시하지 마세요. 로컬 Isolated Executor는 관리 리소스 신원 없이 shadow
소비자로 유지됩니다.

## 다음 단계

| 학습 대상 | 문서 |
|-----------|------|
| 상세 로컬 점검 목록 | [로컬 개발 설정](../../DEVELOPING.md) |
| Console 인증 및 서비스 동작 | [Console 로컬 개발](../../console/README.md#local-development) |
| Entra 등록 및 App Role | [Entra 앱 등록](../runbooks/entra-app-registration-ko.md) |
| 선택적 비공개 엔드포인트 접근 | [격리된 개발 접근](../../tools/dev-access/README.md) |
| Azure 구독 배포 | [배포 빠른 시작](deploy-quickstart-ko.md) |
| 기여 및 검증 작업 흐름 | [기여](../../CONTRIBUTING.md) |
