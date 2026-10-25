---
title: 배포 빠른 시작
description: 서명된 Release Hub 이미지, 명시적 소스 빌드 또는 서명된 오프라인 패키지로 FDAI를 배포합니다.
translation_of: deploy-quickstart.md
translation_source_sha: 8877939ee076dc47d98bddfffed7e1d19b7a0620
translation_revised: 2026-10-25
---

# 배포 빠른 시작

> **배포 방식:** 일반적인 복제 후 배포는
> [Release Hub 이미지](../roadmap/deployment/hub-image-deployment-ko.md)를 선택합니다.
> 명시적 소스 빌드와 서명된 오프라인 패키지는
> [헌법의 기존 계약](../roadmap/architecture/fdai-constitution-ko.md#제1조-목적과-범위)을 유지합니다.
> 연결된 이미지 초기 설치가 [Hub 관리형 수명 주기](../roadmap/deployment/hub-managed-lifecycle-ko.md)
> 전체의 완성을 뜻하지는 않습니다.

한 번의 대화형 Azure 로그인 뒤 복제한 저장소에서 FDAI를 자신의 Azure 구독에 배포할 수 있습니다.
명령은 기본적으로 `https://hub.msfdai.com`을 통해 사전 빌드 이미지를 선택합니다.
독립적으로 신뢰한 Release 공개키와 호환되는 게시 Release가 필요합니다.
비공개 서명 키, 서명된 키트나 GitHub 설정은 필요하지 않습니다.
명시적 소스 모드는 Hub나 게시된 Release가 필요하지 않습니다. 업스트림
무결성 서명 키가 없으면 설치본은 30일 Trial로 동작하고 Trial이 끝나면 만료 워터마크를 표시합니다.
복제한 저장소의 `secrets/integrity-signing-key.pem`에 그 키가 있으면 전체 사용권을 받습니다.

Terraform은 인프라의 단일 기준으로 유지됩니다. 배포 명령은 서명되고 다이제스트로 고정된
서비스 이미지를 자신의 레지스트리에 가져오고, 적용하는 각 계획을 표시하고, 비공개 데이터 플레인 작업을 Virtual Network
내부로 옮기고, 배포 준비 상태를 보고하기 전에 애플리케이션 결과를 검증합니다.

기본적으로 계획은 전용 인벤토리 Managed Identity에 구독 범위 AKS Cluster User 및 RBAC
Reader 역할을 부여합니다. 그러면 인벤토리 작업은 현재 및 이후 생성된 AKS 클러스터를 찾고
Kubernetes 객체를 읽을 수 있으며 Core, Operator 또는 Thor에는 이 역할을 부여하지 않습니다.
계획에서 이 읽기 범위를 검토하세요.

## 배포 경로 선택

| 환경 | 시작 방법 | 필요한 것 |
|------|-----------|-----------|
| 연결된 환경의 복제 후 배포 | `az login` 뒤 복제한 저장소에서 `scripts/deployment/azure/fdai-up.sh --hub-public-key <trusted-public.pem> --region <region>` 실행 | 독립적으로 신뢰한 Release 공개키, 호환되는 게시 Release, 레지스트리 읽기 권한 |
| 자체 구독의 명시적 소스 빌드 | `az login` 뒤 `scripts/deployment/azure/fdai-up.sh --source . --region <region>` 실행 | Hub, 검증 키, 키트나 게시 Release가 필요하지 않음 |
| 인터넷에 연결되지 않은 Azure VM | 그 VM에서 `fdaictl provision azure --offline-kit <package>` 실행 | 키 보유자가 만든 서명된 오프라인 패키지 하나 |

GitHub Actions는 저장소를 테스트합니다. 대상 환경에 배포하는 전달 경로가 아닙니다.

> **Hub 개발 검증:** 별도의 [Release Hub](../../infra/release-hub/README.md)와
> [Lifecycle Hub](../../infra/lifecycle-hub/README.md) 안내는 각 제품의 UI/API/DB를 독립적으로
> 배포합니다. 로그인과 상대 카탈로그 연결은 기동의 전제조건이 아니며, 인증을 설정하기 전까지
> 관리 API는 사용할 수 없습니다. [기존 두 Hub 안내](../../infra/hubs-development/README.md)는
> 기존 인증된 검증 구성을 보존합니다. 어느 쪽도 완전한 Hub 관리형 FDAI 설치나 이 빠른 시작의
> 소스 및 오프라인 경로를 대체하지 않습니다. Hub 이미지 초기 설치는 별도로 문서화하며,
> 관리형 수명 주기 전체의 완성을 뜻하지 않습니다. 로컬 근거는 Azure나 프로덕션 신뢰 루트의 검증이 아니며,
> 클라우드 실행에는 별도 승인이 필요합니다.

> **현재 상태:** 단일 명령 소스 배포는 애플리케이션 수렴까지 구현되었습니다.
> [구현 원장](../roadmap-implementation/deployment/source-deployment.md)은 다음 상태를 기록합니다.
>
> - 소스 실행은 Foundation 이후 애플리케이션 단계로 계속 진행합니다. 레지스트리에서 서비스
>   이미지를 빌드하고, AKS 런타임과 워크로드를 적용하고, 마이그레이션을 실행한 뒤 30일 Trial을
>   시작합니다. 키가 없는 신규 구독 실행 하나와 변경 없는 재실행 하나가 최종 준비 상태에
>   도달했습니다. 각 신규 설치에는 현재 리비전의 인수 실행이 여전히 필요합니다.
> - `secrets/integrity-signing-key.pem`이 있으면 애플리케이션 단계는 Trial 대신 설치 사용권을
>   설치합니다. 실제 키 보유자의 신규 설치와 Trial에서 전체 사용권으로 전환하는 재실행은 아직
>   기록되지 않았습니다.
> - 확인한 설치 범위보다 오래 걸린 실행은 검토 상태로 멈춥니다. 보호된 해체 후 새 작업
>   디렉터리에서 새 실행을 시작하세요.

## Clone에서 배포

### 필수 조건

시작하기 전에 다음 요구 사항을 확인하세요.

- Bash, `git`, Azure CLI, `uv`가 설치된 Linux x86-64 워크스테이션. Windows에서는 WSL2를
  사용하고 해당 도구를 Linux 안에 설치합니다.
- Python 3.13 또는 `uv`가 이를 다운로드할 수 있는 권한. 최초 설치에는 구성된 Python 패키지
  인덱스와, 필요한 경우 Python 배포 호스트에 접근할 수 있어야 합니다. 이 절차는 연결된 환경용이며,
  인터넷에 연결되지 않은 Azure VM에서는 서명된 오프라인 패키지를 사용합니다.
- Console 추가 기능을 선택한 경우에만 Node.js와 npm
- 로컬 Terraform 설치는 필요하지 않습니다. 명령은 `PATH`의 `terraform`이 고정된 릴리스일 때만
  사용하고, 그렇지 않으면 해당 릴리스를 한 번 내려받아 커밋된 다이제스트를 검증합니다.
- 선택한 구독에서 Foundation 리소스를 만들고 문서화된 배포 역할을 할당할 수 있는 Azure 신원
- Console 또는 기업 신원 연동 추가 기능을 선택하는 경우 테넌트 내에서 공유하는 FDAI API,
  승인 봇, 역할 그룹의 표시 이름이 고유해야 합니다. 설치 관리자는 정확한 대상 바인딩에서
  별도 Console SPA를 파생하므로 다른 FDAI 설치가 해당 리디렉션을 소유하지 않습니다. 정확한
  공유 이름이나 파생 이름이 중복되면 Azure 리소스를 만들기 전에 실행이 멈춥니다.
- Console 또는 기업 신원 연동 추가 기능을 선택하는 경우 로그인한 계정에 활성 상태의 Microsoft Entra
  `Privileged Role Administrator` 또는 `Global Administrator` 역할이 필요합니다. 설치 관리자는 배포
  신원에 Microsoft Graph `Application.ReadWrite.OwnedBy` 애플리케이션 권한을 부여하는데, 더 낮은
  역할로는 이를 할당할 수 없습니다. Privileged Identity Management로 자격만 있는 경우 먼저
  활성화하세요. 역할이 없으면 Foundation은 완료되고 애플리케이션 신원 단계가 디렉터리 역할 거부로
  멈추며, 역할을 활성화한 뒤 같은 명령을 다시 실행하면 이어서 진행합니다.
- 선택한 Azure 리전에서 필요한 리소스 형식의 사용 가능한 용량
- 의도한 구독을 선택한 대화형 Azure 세션
- 기본 이미지 경로에는 독립적으로 승인한 Release Hub 공개 PEM과 서명된 Release 소스 커밋에
  일치하는 깨끗한 저장소가 필요합니다. 공개키만 사용하고 비공개 키를 제공하지 마세요.
  선택 채널과 서명된 이미지 위치에 접근할 수 있어야 합니다. 검사에 실패하면 대체 이미지를
  빌드하지 않고 멈춥니다. [Release Hub 이미지 배포](../roadmap/deployment/hub-image-deployment-ko.md)를
  참조하세요.

### 명령을 한 번 설치

이 단계는 선택 사항입니다. `fdai-up.sh` 래퍼는 아무것도 설치하지 않고 clone에서 실행됩니다. 같은
조정기를 어느 디렉터리에서나 실행하려는 경우에만 `fdaictl`을 설치합니다.

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
동명 패키지가 아니라 현재 복제본에서 설치합니다. Azure 로그인, FDAI 유지관리자 키, `sudo`, 전체
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

승인된 신뢰 경로로 Release 공개키를 받고 로그인한 뒤 선택한 구독을 확인하세요.
이어서 원하는 Azure 리전에 배포합니다.

```bash
az login
az account show --query '{subscription:id,name:name}' --output table
git clone https://github.com/dotnetpower/fdai.git
fdai/scripts/deployment/azure/fdai-up.sh \
  --hub-public-key /trusted/release-hub-public.pem --region koreacentral
```

이미 복제한 저장소가 있다면 같은 공개키와 리전 옵션으로 래퍼를 실행하세요.
래퍼는 저장소의 잠긴 환경을 준비하고 기본적으로 Hub 이미지를 선택합니다.
Hub와 독립적인 기존 빌드 경로에는
`scripts/deployment/azure/fdai-up.sh --source . --region koreacentral`을 명시적으로 실행하세요.
CLI를 설치했다면 `fdaictl provision azure --source <checkout>`도 사용할 수 있습니다.
대화형 터미널에서는
추가 전용 설치 이벤트가 자동으로 표시됩니다. 같은 스크롤 기록을 유지하면서 터미널 스타일을
제거하려면 `--progress plain`을 추가합니다. 출력이 없는 준비 및 사전 검사 작업은 10초마다
`still working` 기록을 내고, 이후 명시적인 완료 또는 실패 기록을 냅니다. 비공개 작업
디렉터리는 clone 밖에 있어야 합니다.

폐기 가능한 source AKS 개발 설치에서는
`--development-authority-profile <private-reviewed-profile.json>`을 추가할 수 있습니다. FDAI는
애플리케이션 plan에서만 프로필을 검증하고 전달하며, 해당 프로필에서 별도 실행기 principal을
도출합니다. 옵션을 생략하면 보존된 프로필을 유지합니다.
`--clear-development-profile`을 사용하면 이후 정확한 plan을 통해 제거할 수 있습니다.

조정기는 재개 가능한 단일 프로세스로 다음 작업을 수행합니다.

1. 명령줄로 비밀 값을 받지 않고 Azure CLI에서 활성 테넌트와 구독을 읽습니다.
2. clone의 깨끗하게 커밋된 스냅샷 하나를 고정합니다.
   Hub 모드에서는 서명된 카탈로그와 Release를 검증하고 소스 일치를 확인하며,
   Azure 배포 효과 전에 선택한 구독의 최소 배포 요청을 기록합니다.
3. clone의 `secrets/` 디렉터리를 보고 Trial 또는 전체 사용권 모드를 선택합니다.
4. 정책, 할당량, 프로바이더 및 대상을 읽기 전용으로 검사합니다.
5. Foundation 계획을 표시하고 적용합니다. 비공개 상태 경계, Virtual Network, Bastion 액세스,
   배포 신원 및 Managed Host를 만듭니다.
6. 서명된 이미지 다이제스트를 자신의 레지스트리에 가져오고 다시 조회합니다.
   명시적 소스 모드는 대신 스냅샷에서 서비스 이미지를 빌드합니다.
7. 마이그레이션과 카탈로그를 적용하고, Trial을 시작하거나 전체 사용권을 저장하고, 선택한 경우
   Entra를 구성한 뒤 애플리케이션을 digest로 배포합니다.
8. 이미지 digest, 마이그레이션과 카탈로그 상태, 서비스 상태 및 두 번째 변경 없음 계획을
   검증합니다.

명령 실행이 그 명령이 표시하는 각 계획을 승인합니다. 기존 리소스를 삭제하거나 교체할 때만
추가로 한 번 입력해 확인해야 합니다. 명령은 응답이 없다고 승인한 것으로 해석하지 않습니다.
적용 결과가 불분명하면 같은 명령을 다시 실행할 때 적용을 반복하지 않고 검증 전용 복구를
수행합니다. Hub 이미지 재실행은 정확한 선택 카탈로그를 유지합니다. 기존 설치본의 채널
업그레이드와 Hub 해체는 구현되지 않았습니다. 카탈로그 변경에는 별도로 검토한 실행이
필요하며, 모드를 바꾸거나 기존 리소스를 도입하는 방식으로 해결하지 않습니다.
명시적 소스 모드는 기존의 재개 및 갱신 계약을 유지합니다.
요청 행은 배포 성공이 아닙니다. Release Hub 운영자는
**Deployment requests**에서 `requested` / `self-reported` 기록을 확인합니다.
요청에는 구독, 리전, Release와 채널, 입력 다이제스트가 포함되며 Azure 자격 증명이나
고객 구성은 포함하지 않습니다. 구독 소유권도 증명하지 않습니다.

정확한 Foundation 복구는 복구 논리에 더 새로운 깨끗한 checkout을 사용할 수 있습니다. 검증된
상태 인계 후에도 애플리케이션 배포는 원래 보존된 소스 스냅샷과 원래 런타임 프로파일을 사용합니다.
복구는 애플리케이션 바이트를 자동으로 업그레이드하거나 서명된 키트를 선택하지 않습니다.

명시적 소스 모드에서 Azure 접근 없이 스냅샷만 고정하려면 `--prepare-only`를, 리소스를 바꾸지
않고 AKS SKU와 할당량을 읽는 `--preflight-only`를 추가합니다. 준비나 사전 점검의 성공은
애플리케이션 배포 완료를 뜻하지 않습니다.

새 대화형 실행은 시작할 때 한 번 설치 설정을 보여 줍니다. 구축 예상 비용 한도는
`--setup-cost-ceiling <USD>`로 지정하거나 그 검토 중에 입력합니다. 선택적 화면은 `--add-on`으로,
선택적 관찰 출처는 `--observation-source`로 고르며, 기본값은 헤드리스 관찰 우선 프로파일입니다.
AKS 컴퓨트 부분 비용 검토는 `--monthly-cost-ceiling <USD>`를 지정하지 않으면 월 1500 USD 한도를
사용합니다. 이 설정만으로 리소스를 배포하지는 않습니다.
`notifications` 추가 기능에는 `--notification-recipients <path>`도 필요합니다. 이 비공개 JSON 파일
`{"recipients": ["name@domain"]}`은 런타임 프로파일과 receipt에 들어가지 않습니다.

Foundation 계획 전에 Genesis는 지역 VM 카탈로그를 읽고 할당량 안에서 호환되는 Managed Host
크기를 선택합니다. 선택은 승인 전에 봉인하며 적용 중에는 바꾸지 않습니다. 호환되는 크기가
없으면 보고된 제한, 하드웨어 요건, 할당량을 검토하세요. 기존 적용 시작 기록이 있으면 검증만
재개합니다.

Foundation 계획은 먼저 비공개 로컬 백엔드를 사용합니다. 정확한 마이그레이션 아카이브만
검증된 호스트에서 서명된 원격 백엔드 예제를 활성화하며, 마이그레이션 승인과 재조회 확인은 필수입니다.
보존된 마이그레이션 `claim`이 완전한 아카이브보다 먼저 만들어져 같은 디렉터리의 지원 파일이 모두 없다면,
수정된 정확한 소스와 새로운 `foundation-state` 승인으로 재개하세요. 조정기는 원래 `claim`과
백엔드 효과를 유지하고, 검토된 복구 구성의 정확한 파일만 복원하며, Terraform 입력 트리 밖의
현재 소스 오버레이를 검증한 뒤 검증만 실행합니다. 일부 파일만 있거나 기존 파일이 다르면
복구가 중단됩니다.
정리 후에는 이후의 정확한 소스 실행이 검증된 관찰기를 비공개 Bastion 경로로 전송하고
다이제스트를 다시 읽어 확인한 뒤 Managed Identity로 실행합니다. 관찰기는 Azure CLI로 보호된
상태 blob을 직접 다운로드하고 보존된 권한 다이제스트와 비교한 다음, 삭제된 Terraform 작업
트리나 provider 미러를 다시 만들지 않고 임시 파일을 제거합니다.

### 검증된 공개 개발 배포 복구

`azd-up.sh`는 Core 전용 개발 진단 도구로 유지됩니다. FDAI 설치 경로가 아니며,
`fdaictl provision azure`는 연결형 릴리스 키트 획득으로 이 상태를 더 이상 채택하지 않습니다.
진단을 위해 작업 디렉터리와 증적을 보존하세요. 지원되는 설치가 필요하면 단일 명령 소스 경로나
서명된 오프라인 패키지를 사용하세요.

### Trial과 전체 사용권

명령은 Azure에서 무엇인가를 바꾸기 전에 작업 스테이션에서 사용권을 한 번 선택합니다.

| clone 상태 | 설치 결과 | 30일 이후 |
|------------|-----------|-----------|
| `secrets/integrity-signing-key.pem` 없음 | 첫 활성화 때 30일 Trial 하나를 시작 | 새 변경 작업은 차단되고 만료 워터마크가 나타나며, 관찰, 진단, 감사, 내보내기는 계속됨 |
| `secrets/integrity-signing-key.pem`에 업스트림 무결성 서명 키 있음 | 이 설치에 바인딩된 전체 사용권을 받음 | 변화 없음 |
| 사용할 수 없는 키 파일 | 없음. Azure를 바꾸기 전에 명령이 멈춤 | 해당 없음 |

명령은 무엇이든 바꾸기 전에 키를 확인합니다. 키 파일은 소유자 전용(`chmod 600`)이어야 하고
커밋된 `security/integrity/upstream-signing-key.pub`와 일치해야 합니다. 오프라인 패키지 서명 키는
전체 사용권을 선택하지 않습니다. 키는 작업 스테이션을 떠나지 않으며 서명된 사용권만 Key Vault에
저장됩니다. Trial 기록이 삭제되었더라도 명령을 다시 실행해 Trial이 갱신되지는 않으며, 나중에
키를 두고 실행하면 Trial 설치를 그대로 전체 사용권으로 올립니다.

사용권은 기능을 사용 가능하게 만들 뿐입니다. 런타임 승격, 위험 검사, 사람 승인은 계속
독립적인 제어입니다.

### Trial이 끝나면

30일이 지나면 FDAI는 관찰, 진단, 감사, 내보내기를 계속하지만 새 변경 작업은 차단합니다.
그때부터 모든 Console 페이지는 정품 인증되지 않은 운영 체제처럼 오른쪽 아래 모서리에 평가
기간이 만료되었다는 워터마크를 표시합니다. 워터마크는 닫을 수 없으며 설정, 데이터 변경, 재배포로
끌 수도 없습니다. 전체 사용권만 워터마크를 없애며, 그러려면 업스트림 무결성 서명 키가 있는
상태에서 배포를 다시 실행해야 합니다.

## 서명된 오프라인 패키지로 배포

대상 Azure VM이 GitHub, PyPI, 공개 Terraform 레지스트리 또는 공개 컨테이너 레지스트리에
연결할 수 없으면 오프라인 패키지를 사용하세요. 키 보유자는 배포 CLI와 그 wheel, Terraform
구성, Terraform과 provider 미러, `kubectl`과 `kubelogin`, 모든 서비스 및 의존성 이미지,
Console, 마이그레이션 지원을 담은 서명된 패키지 하나를 만듭니다.

```bash
scripts/deployment/release/build-standalone-deployment-kit.sh \
  --out <private-output-directory> --signing-key <package-signing-key>
```

패키지를 Azure VM으로 복사하고 [연결이 끊긴 배포](../roadmap/deployment/disconnected-deployment-ko.md)에
설명된 대로 서명된 wheelhouse에서 `fdaictl`을 설치한 뒤 다음을 실행합니다.

```bash
fdaictl provision azure --offline-kit <fdai-deployment-kit.tar.gz> --region <azure-region>
```

명령은 파일을 사용하기 전에 패키지의 분리형 Ed25519 서명과 모든 체크섬을 검증합니다.
패키지만으로 충분하며 다운로드, 공개 레지스트리, 패키지 인덱스, 빌드가 필요하지 않습니다.
Azure 관리 및 데이터 플레인 엔드포인트에는 Azure 네트워크 경로를 통해 계속 접근할 수 있어야 합니다.
패키지 서명 키는 산출물을 인증할 뿐 사용 권한을 뜻하지 않으므로, 별도로 발급한 사용권을
제공하지 않으면 오프라인 설치는 30일 Trial로 동작합니다.

> Azure 관리 플레인 경로가 없는 네트워크에서는 Azure 리소스를 배포할 수 없습니다. 해당
> 프로필에서는 패키지를 검증하고 준비할 수 있지만 명령은 배포 준비 상태를 보고할 수 없습니다.

기존 오프라인 설치를 업그레이드하려면 더 새 패키지와 설치 당시의 `--work-dir`로 같은 명령을
다시 실행합니다. 명령은 더 새 패키지를 검증하고, 이전 패키지 스냅숏은 검토용으로 보존하며,
기존 Foundation은 그것을 만든 리비전으로 이어서 실행합니다. 그런 다음 더 새 패키지로
애플리케이션을 배포합니다. 이전 리비전으로는 새 Foundation 계획을 승인하지 않습니다.

## 결과 이해

애플리케이션이 수렴하고 두 번째 Terraform 계획에 변경이 없으면 성공한 명령은
`deployment_ready=true`를 보고합니다. 전체 모델 용량 및 인벤토리 인증과 같은 더 넓은 보증
캠페인이 열려 있으면 `subscription_ready=false`가 유지될 수 있습니다. 이는 선택한
애플리케이션 배포가 실패했다는 의미가 아닙니다.

분석기 대상을 직접 구성할 때는 논리 FDAI Resource에 `resource_id`를 사용하고, 메트릭 조회에
사용하는 정확한 Azure 리소스 ID에는 `provider_resource_id`를 사용하세요. 인벤토리를 사용할 수
있으면 FDAI가 기존 Azure ID를 논리 Resource로 조정할 수 있습니다. 인벤토리가 없으면 두 필드를
메트릭 기반 대상에 모두 제공하여 발견된 문제와 Incident가 공급자 신원을 대상으로 노출하지
않도록 하세요. Pod 수명 주기 근거와 같은 비메트릭 대상은 논리 ID만 사용합니다.

역할 할당 검사에는 배포가 부여하지 않는 테넌트 권한이 필요합니다. 테넌트 관리자가 인벤토리 ID에
구독 할당을 판단하기 위한 Microsoft Graph `User.Read.All`과 `GroupMember.Read.All` 애플리케이션
권한을, 관리 ID 할당을 판단하기 위한 테넌트 루트 관리 그룹의 `Reader`를 부여해야 합니다. 그 전까지
이 검사는 통과하지 않고 `unknown`을 보고합니다. 자세한 내용은
[배포 및 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md)을 참조하세요.

비공개 작업 디렉터리에는 SSH 키, 대상별 입력, 계획, 복구 상태가 포함될 수 있습니다. 내용을
업로드하거나 공유하지 말고 민감한 값을 제거한 CLI 진단을 사용하세요. 검증 및 필요한 복구가
끝날 때까지 이 디렉터리를 유지하세요.

## 내부 및 고급 경로

다음 도구는 공개 대상 환경 배포 진입점이 아닙니다.

- `genesis-up.sh`는 저수준 Foundation 진단 및 복구 도구입니다.
- `azd-up.sh`는 Container Apps에 Core만 배포하는 공개 개발 bootstrap입니다. 단일 명령 소스
  배포가 아니며 공개 설치 프로그램은 이 상태를 채택하지 않습니다.
- `fdai-up.sh`는 폐기된 `--signing-key` 옵션을 거부하며 키트를 빌드하지 않습니다. 서명된 오프라인
  패키지는 따로 빌드해 `--offline-kit`로 전달합니다.
- `.github/workflows/` 아래 배포 워크플로는 저장소 CI, release 및 과거 자동화를 위한 것입니다. 대상 환경
  설치 프로그램으로 지원되지 않습니다.
- Terraform 직접 실행은 전문가용 통합 경로입니다. 동일한 계획, 승인, 신원, 롤백 및 검증
  계약을 유지해야 합니다.

## 다음 단계

| 알아볼 내용 | 참조 문서 |
|------------|-----------|
| 단일 명령 소스 배포와 사용권 | [단일 명령 소스 배포](../roadmap/deployment/source-deployment-ko.md) |
| 전체 배포 토폴로지 | [배포와 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md) |
| 연결 및 폐쇄망 실행 프로필 | [프로비저닝 실행 프로필](../roadmap/deployment/provisioning-execution-profiles-ko.md) |
| 서명된 오프라인 패키지와 신뢰 경계 | [연결이 끊긴 배포](../roadmap/deployment/disconnected-deployment-ko.md) |
| 완료되지 않은 실행 이후 복구 | [배포 복구](../runbooks/deployment-recovery-ko.md) |
