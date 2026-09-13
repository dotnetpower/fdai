---
title: 배포 빠른 시작
description: 단일 로컬 명령 또는 digest로 고정된 폐쇄망 배포 어플라이언스로 FDAI를 Azure에 배포합니다.
translation_of: deploy-quickstart.md
translation_source_sha: a3a83aead0d2667826bfeb2a4e1d5abd2b3007f6
translation_revised: 2026-09-13
---

# 배포 빠른 시작

한 번의 대화형 Azure 로그인으로 FDAI를 Azure 구독에 배포할 수 있습니다. 대상 환경 배포는
로컬 `fdaictl` 조정기와 대상 Virtual Network 내부의 Managed Host에서 실행됩니다. GitHub
Actions, 저장소 변수, 저장소 비밀 또는 GitHub runner를 사용하지 않습니다.

Terraform은 인프라 단일 기준으로 유지됩니다. 배포 명령은 서명된 release를 검증하고, 승인할
정확한 계획을 표시하고, 비공개 데이터 플레인 작업을 Virtual Network 내부로 옮기고, 배포
준비 상태를 보고하기 전에 애플리케이션 결과를 검증합니다.

## 배포 경로 선택

| 환경 | 시작 방법 | 산출물 원본 |
|------|-----------|-------------|
| 연결된 Azure 환경 | 저장소를 복제하고 `fdaictl`을 설치한 뒤 `az login`, `fdaictl provision azure --online` 순서로 실행 | 버전이 지정된 서명된 release 키트 |
| 공개 산출물 송신이 없는 환경 | digest로 고정된 FDAI 배포 어플라이언스를 적재하고 이미지 진입점 실행 | 어플라이언스 이미지에 포함된 완전한 서명 키트 |

GitHub Actions는 release를 빌드, 테스트, 서명 및 게시하는 데 사용할 수 있습니다. 대상 환경
배포 경로에는 포함되지 않습니다.

## Clone에서 배포

### 필수 조건

시작하기 전에 다음 요구 사항을 확인하세요.

- Bash, `git`, Azure CLI, `uv`가 설치된 Linux x86-64 워크스테이션. Windows에서는 WSL2를
  사용하고 해당 도구를 Linux 안에 설치합니다.
- Python 3.13 또는 `uv`가 이를 다운로드할 수 있는 권한. 최초 설치에는 구성된 Python 패키지
  인덱스와, 필요한 경우 Python 배포 호스트에 접근할 수 있어야 합니다. 이 설치 절차는 연결된
  환경용이며, 산출물 오프라인 배포에는 어플라이언스 경로를 사용합니다.
- 선택한 구독에서 Foundation 리소스를 만들고 문서화된 배포 역할을 할당할 수 있는 Azure 신원
- 선택한 Azure 리전에서 필요한 리소스 형식의 사용 가능한 용량
- 의도한 구독을 선택한 대화형 Azure 세션

### 명령을 한 번 설치

저장소를 복제하는 것만으로 셸 명령이 자동 등록되지는 않습니다. 복제한 저장소 루트에서 로컬
배포 CLI를 사용자 소유의 격리된 `uv` 도구 환경에 설치합니다.
이미 FDAI를 복제했다면 처음 두 명령을 건너뛰고 저장소 루트에서 시작합니다.

```bash
git clone https://github.com/dotnetpower/fdai.git
cd fdai
set -o pipefail
uv export --project packages/deployment-cli --locked --no-dev --no-emit-project \
  --format requirements-txt --no-hashes | \
  uv tool install --python 3.13 --constraints - ./packages/deployment-cli
uv tool update-shell
```

내보낸 제약 조건은 런타임 의존성 버전을 저장소 잠금 파일과 일치시킵니다. 패키지는 PyPI의
동명 패키지가 아니라 현재 복제본에서 설치합니다. Azure 로그인, 유지관리자 키, `sudo`, 전체
애플리케이션 환경, 가상 환경 활성화는 필요하지 않으며 Azure 리소스를 배포하지 않습니다.
설치가 실패하면 중단하고, 이전 실행 파일로 계속 진행하지 마세요.

`uv tool update-shell`은 필요한 경우 사용자 명령 디렉터리를 셸 설정에 추가합니다. 새 터미널을
열거나 현재 Bash 세션에 다음 설정을 적용한 뒤 명령을 확인합니다.

```bash
export PATH="$(uv tool dir --bin):$PATH"
command -v fdaictl
fdaictl
fdaictl version
fdaictl provision azure --help
```

`command -v` 결과는 `uv tool dir --bin`이 표시하는 디렉터리 안의 `fdaictl`이어야 합니다.
Linux에서는 보통 `~/.local/bin`입니다. 이후에는 복제한 디렉터리 밖에서도 명령을 사용할 수
있습니다. 인자 없는 `fdaictl`, `version`, `--help`는 로그인이나 배포를 수행하지 않습니다.

| 증상 | 확인 또는 조치 |
|------|----------------|
| `uv: command not found` | [공식 설치 가이드](https://docs.astral.sh/uv/getting-started/installation/)에 따라 `uv`를 설치한 뒤 터미널을 다시 엽니다. |
| `fdaictl: command not found` | `uv tool list`로 설치를 확인하고 `uv tool update-shell`을 실행한 뒤 터미널을 다시 열거나 위 PATH 명령을 적용합니다. |
| 다른 `fdaictl`이 선택됨 | `type -a fdaictl`과 `uv tool list`를 확인합니다. `--force`로 무조건 덮어쓰지 말고 충돌한 실행 파일을 먼저 확인합니다. |
| 복제본의 변경이 반영되지 않음 | 일반 설치는 특정 시점의 복사본입니다. 갱신한 저장소 루트에서 위 설치 파이프라인의 `uv tool install`에 `--reinstall`을 추가해 다시 실행합니다. |
| 인자 없는 `fdaictl`이 여전히 필수 명령 오류를 표시함 | 선택된 설치본에 새 탐색 도움말이 반영되지 않은 상태입니다. `command -v fdaictl`을 확인하고 갱신한 복제본에서 같은 잠금 기반 설치 파이프라인으로 다시 설치합니다. |

로컬 CLI를 개발할 때는 같은 설치 명령에 `--editable`을 추가합니다. 패키지 소스 수정이 즉시
반영되므로 복제본 위치를 유지해야 하며, 의존성이 바뀌면 다시 설치해야 합니다. 일반 사용자는
위의 특정 시점 복사본 설치를 사용하는 것이 좋습니다.

### 명령을 안전하게 탐색

| 명령 | 표시 내용 |
|------|-----------|
| `fdaictl` 또는 `fdaictl --help` | 명령별 설명과 짧은 시작 예제 |
| `fdaictl provision` | 배포 및 준비 명령 목록 |
| `fdaictl provision azure --help` | 필수 산출물 원본 선택, 기본값, 단위, 출력 모드, 고급 입력 |
| `fdaictl --version` | 설치된 버전. 스크립트에서는 기존 `fdaictl version --output json`도 사용 가능 |

이 탐색 명령은 Azure 접근, 다운로드, 배포 상태 변경, 입력 요청 없이 정적 텍스트를 표시하고
정상 종료합니다. 개별 명령을 실행하려면 필수 옵션을 제공하세요. 잘못된 명령, 불완전한 인자,
충돌하는 산출물 원본은 다음 도움말 안내와 함께 사용법 오류 `2`를 반환하며 배포를 시작하지
않습니다. 긴 옵션은 축약하지 않고 전체 이름을 입력하세요.

### 배포 실행

설치 후에는 어느 디렉터리에서든 다음 명령을 실행하고 Azure 리전을 선택합니다.

```bash
az login
fdaictl provision azure --online --region koreacentral
```

대화형 터미널에서는 활동 내역이 자동으로 표시됩니다. 줄 단위 로그가 필요하면
`--progress plain`을 추가합니다. 산출물 원본은 `--online` 또는 `--offline-kit <path>` 중 하나를
명시합니다. 명령을 영구 설치하지 않으려면 기존 복제본의 래퍼를 사용할 수 있습니다.

```bash
bash scripts/deployment/azure/fdai-up.sh --region koreacentral
```

두 명령은 같은 조정기를 사용합니다. CLI를 설치하거나 갱신해도 서명된 배포 키트가 갱신되지는
않습니다. Genesis 스크립트는 복제본이 아니라 검증된 릴리스에서 가져옵니다. 키트 내부 코드의
수정에는 수정된 서명 키트가 필요하며, 추출된 파일을 직접 수정하거나 검증을 끄면 안 됩니다.
명령 등록 성공은 배포 성공의 근거가 아닙니다.

조정기는 재개할 수 있는 단일 프로세스에서 다음 작업을 수행합니다.

1. 명령줄 비밀로 값을 받지 않고 Azure CLI에서 활성 tenant와 subscription을 읽습니다.
2. 버전이 지정된 완전한 배포 키트 하나를 다운로드하고 검증하거나 보존된 키트를 다시 검증합니다.
3. 정책, 할당량, provider 및 대상을 읽기 전용으로 검사합니다.
4. 정확한 Foundation 계획을 표시하고 명시적 승인을 기다립니다.
5. 비공개 상태 경계, Virtual Network, Bastion 액세스, 배포 신원 및 Managed Host를 만듭니다.
6. 검증된 키트를 해당 호스트로 전달하고 Managed Identity로 비공개 Terraform 작업을 실행합니다.
7. 서명된 서비스 이미지를 가져오고, 마이그레이션을 적용하고, Entra를 구성하고,
   애플리케이션을 배포합니다.
8. 이미지 digest, 마이그레이션과 카탈로그 상태, 서비스 상태 및 두 번째 변경 없음 계획을
   검증합니다.

명령은 응답이 없다고 승인한 것으로 해석하지 않습니다. 적용 결과가 불분명하면 같은 명령을 다시
실행할 때 적용을 반복하지 않고 검증 전용 복구를 수행합니다.

새 이미지 계획 전에 Genesis는 요청한 지역에서 호환되는 비공개 빌더와 검증기 VM 크기를
선택하고 합산 할당량을 확인한 뒤 봉인된 선택을 승인 전에 표시합니다. 적용 중에는 크기를
바꾸지 않습니다. 이 선택 기능이 포함된 서명 키트가 필요하며, Foundation VM 선택과 이전에
일부만 완료된 시도의 복구는 별도로 검토합니다.

### 키트 획득에 실패한 경우

온라인 재시도는 보존된 키트 파일을 교체하지 않고 다시 검증합니다. 모든 서명, 정확한 파일
목록, 다이제스트, 런타임 이미지, 번들 연결을 다시 확인합니다. 다운로드 파일이 있다는
이유만으로 신뢰할 수 있거나 최신인 릴리스로 간주하지 않습니다. 기존 실행 복사본, 실행 상태,
SSH 키, 계획, 승인은 보존합니다.

| 오류 유형 | 확인 또는 조치 |
|-----------|----------------|
| `HTTP 404` | 선택한 CLI 버전과 플랫폼에 해당하는 완전한 키트가 게시되어 있는지 확인합니다. Azure 로그인은 GitHub 릴리스를 게시하거나 인증하지 않습니다. |
| `HTTP 401` 또는 `HTTP 403` | 릴리스 접근 권한과 네트워크 정책을 확인합니다. 토큰을 URL이나 명령줄에 넣지 마세요. |
| `HTTP 429`, `HTTP 503`, 연결 실패 또는 시간 초과 | 이번 시도를 중단합니다. 다시 명시적으로 시도하기 전에 릴리스 호스트의 DNS, HTTPS, 프록시, TLS 신뢰를 확인하며 인증서 검증을 끄지 않습니다. |
| 로컬 경로 충돌, 권한 거부 또는 저장 공간 부족 | 배포 작업 디렉터리를 보존합니다. 이전 CLI는 잠금 기반 설치 절차로 갱신하고, 실행 근거를 삭제하지 않은 채 해당 로컬 접근 또는 저장 공간 문제를 해결합니다. |
| 보존된 원본 불일치, 서명 실패 또는 불완전한 내용 | 중단하고 선택한 원본과 보존된 입력을 검토합니다. CLI는 서명된 파일을 덮어쓰거나 고치지 않으며, 몰래 원본을 바꾸거나 검증을 건너뛰지 않습니다. |

기본 버전별 원본은 요청 원본 기록이 없는 이전 캐시도 다시 검증할 수 있습니다. 다른
`--online-url`은 이 캐시를 사용할 수 없습니다. 기록이 생기면 해당 작업 디렉터리의 요청
원본은 고정됩니다. 재검증은 더 새로운 릴리스를 가져오거나 서명된 키트의 스크립트를 바꾸지
않습니다. 키트 내부 코드의 수정에는 여전히 수정된 서명 릴리스가 필요합니다.

### 기능 모드

배포에 연결된 기능 토큰이 없는 설치는 관찰 전용 모드로 시작합니다. 관리 대상 리소스를 변경할
권한이 없지만 배포 자체는 완료된 상태입니다. 검증된 토큰을 제공하면 토큰에 선언된 기능만 사용할
수 있습니다. 런타임 승격, 위험 검사 및 사람 승인은 계속 독립적인 제어입니다.

## 어플라이언스 이미지에서 배포

대상 네트워크에서 GitHub, PyPI, 공개 Terraform 레지스트리 또는 공개 컨테이너 레지스트리에
연결할 수 없으면 배포 어플라이언스를 사용하세요. release 담당자는 다음 항목을 포함하는 하나의
서명된 OCI 아카이브를 제공합니다.

- `fdaictl`과 잠긴 Python 의존성
- 서명된 Terraform 배포 번들
- Terraform, OPA 및 완전한 provider 미러
- 필요한 모든 FDAI 서비스 및 의존성 OCI 이미지
- Console, 마이그레이션 및 배포 지원 산출물
- SBOM, provenance, 매니페스트 및 서명 레코드

승인된 호스트에서 OCI 호환 컨테이너 도구로 이미지를 적재하세요. 이미지 진입점은 대화형 Azure
로그인 또는 자체 Managed Identity를 사용하고 포함된 키트로 동일한 standalone 조정기를
실행합니다. 공개 산출물 대체 경로는 지원되지 않습니다.

새 비공개 구독에서는 최소 Foundation bootstrap이 Bastion으로 연결할 수 있는 호스트를 먼저
만들 수 있습니다. 완전한 애플리케이션 계획과 적용은 대상 네트워크 내부의 배포 어플라이언스에서
계속 실행됩니다.

> Azure 관리 플레인 경로가 없는 네트워크에서는 Azure 리소스를 배포할 수 없습니다. 해당
> 프로필에서 어플라이언스는 산출물을 검증하고 준비할 수 있지만 배포 준비 상태를 보고할 수 없습니다.

## 결과 이해

애플리케이션이 수렴하고 두 번째 Terraform 계획에 변경이 없으면 성공한 명령은
`deployment_ready=true`를 보고합니다. 전체 모델 용량 및 인벤토리 인증과 같은 더 넓은 보증
캠페인이 열려 있으면 `subscription_ready=false`가 유지될 수 있습니다. 이는 선택한
애플리케이션 배포가 실패했다는 의미가 아닙니다.

비공개 작업 디렉터리에는 SSH 키, 대상별 입력, 계획, 복구 상태가 포함될 수 있습니다. 내용을
업로드하거나 공유하지 말고 민감한 값을 제거한 CLI 진단을 사용하세요. 검증 및 필요한 복구가
끝날 때까지 이 디렉터리를 유지하세요.

## 내부 및 고급 경로

다음 도구는 공개 대상 환경 배포 진입점이 아닙니다.

- `genesis-up.sh`는 저수준 Foundation 진단 및 복구 도구입니다.
- `azd-up.sh`는 기여자 전용 공개 개발 bootstrap입니다.
- `.github/workflows/` 아래 배포 workflow는 저장소 CI, release 및 과거 자동화입니다. 대상 환경
  설치 프로그램으로 지원되지 않습니다.
- Terraform 직접 실행은 전문가 통합 경계입니다. 동일한 계획, 승인, 신원, rollback 및 검증
  계약을 유지해야 합니다.

## 다음 단계

| 알아볼 내용 | 참조 문서 |
|------------|-----------|
| 전체 배포 토폴로지 | [배포와 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md) |
| 연결 및 폐쇄망 실행 프로필 | [프로비저닝 실행 프로필](../roadmap/deployment/provisioning-execution-profiles-ko.md) |
| 어플라이언스와 오프라인 신뢰 경계 | [연결이 끊긴 배포](../roadmap/deployment/disconnected-deployment-ko.md) |
| 완료되지 않은 실행 이후 복구 | [배포 복구](../runbooks/deployment-recovery-ko.md) |
