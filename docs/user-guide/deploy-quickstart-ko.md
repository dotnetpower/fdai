---
title: 배포 빠른 시작
description: clone에서 명령줄 한 줄로 FDAI를 자신의 Azure 구독에 배포하거나 서명된 오프라인 패키지로 설치합니다.
translation_of: deploy-quickstart.md
translation_source_sha: 6ee0ad87aaf75cb057c56f651692df2253b18505
translation_revised: 2026-10-01
---

# 배포 빠른 시작

> **배포 방식:** [헌법](../roadmap/architecture/fdai-constitution.md#article-1-purpose-and-scope)은 단일 명령 소스 배포와 서명된 오프라인 패키지라는 두 가지 설치 방식만 정의합니다. 이 문서의 설치 관문 중 헌법에 없는 것은 대체되었으며 더 이상 적용되지 않습니다.

한 번의 대화형 Azure 로그인 뒤 저장소 clone에서 명령줄 한 줄로 FDAI를 자신의 Azure 구독에
배포할 수 있습니다. 키, 서명된 키트, 게시된 릴리스, GitHub 설정은 필요하지 않습니다. 업스트림
무결성 서명 키가 없으면 설치는 30일 Trial로 동작하고 Trial이 끝나면 만료 워터마크를 표시합니다.
clone의 `secrets/integrity-signing-key.pem`에 그 키가 있으면 전체 사용권을 받습니다.

Terraform은 인프라 단일 기준으로 유지됩니다. 배포 명령은 clone에서 서비스 이미지를 자신의
레지스트리에 빌드하고, 적용하는 각 계획을 표시하고, 비공개 데이터 플레인 작업을 Virtual Network
내부로 옮기고, 배포 준비 상태를 보고하기 전에 애플리케이션 결과를 검증합니다.

기본적으로 계획은 전용 인벤토리 Managed Identity에 구독 범위 AKS Cluster User 및 RBAC
Reader 역할을 부여합니다. 그러면 인벤토리 작업은 현재 및 이후 생성된 AKS 클러스터를 찾고
Kubernetes 객체를 읽을 수 있으며 Core, Operator 또는 Thor에는 이 역할을 부여하지 않습니다.
계획에서 이 읽기 범위를 검토하세요.

## 배포 경로 선택

| 환경 | 시작 방법 | 필요한 것 |
|------|-----------|-----------|
| 로그인할 수 있는 모든 Azure 구독 | `az login`을 실행한 뒤 한 줄 실행: `git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --region <region>` | 다른 것은 필요 없음. 키, 키트, 릴리스도 필요 없음 |
| 인터넷에 연결되지 않은 Azure VM | 그 VM에서 `fdaictl provision azure --offline-kit <package>` 실행 | 키 보유자가 만든 서명된 오프라인 패키지 하나 |

GitHub Actions는 저장소를 테스트합니다. 두 배포 경로 어디에도 포함되지 않습니다.

> **현재 상태:** 단일 명령 소스 배포는 아직 완성되는 중이며,
> [구현 원장](../roadmap-implementation/deployment/source-deployment.md)이 다음 상태를 기록합니다.
>
> - 키 없는 실행은 Foundation을 만든 뒤 애플리케이션 단계 전에
>   `prebuilt_runtime_artifacts_required`로 멈춥니다.
> - 아직 어떤 배포 단계도 Trial을 시작하지 않으므로 토큰이 없는 설치는 관찰 전용으로 남습니다.
> - Core는 업스트림 무결성 키로 라이선스를 검증하지만, `secrets/integrity-signing-key.pem`이 있어도 배포는 아직
>   설치 사용권 대신 30일 토큰을 발급하며, 만료 워터마크도 아직 없습니다.
> - 이 항목들이 완료될 때까지 오프라인 패키지 서명 키 보유자는 서명된 오프라인 패키지를
>   빌드해 `--offline-kit`로 전달해야만 애플리케이션 단계에 도달합니다.

## Clone에서 배포

### 필수 조건

시작하기 전에 다음 요구 사항을 확인하세요.

- Bash, `git`, Azure CLI, `uv`가 설치된 Linux x86-64 워크스테이션. Windows에서는 WSL2를
  사용하고 해당 도구를 Linux 안에 설치합니다.
- Python 3.13 또는 `uv`가 이를 다운로드할 수 있는 권한. 최초 설치에는 구성된 Python 패키지
  인덱스와, 필요한 경우 Python 배포 호스트에 접근할 수 있어야 합니다. 이 절차는 연결된 환경용이며,
  인터넷에 연결되지 않은 Azure VM에서는 서명된 오프라인 패키지를 사용합니다.
- Console 추가 기능을 선택한 경우에만 Node.js와 npm
- 선택한 구독에서 Foundation 리소스를 만들고 문서화된 배포 역할을 할당할 수 있는 Azure 신원
- 선택한 Azure 리전에서 필요한 리소스 형식의 사용 가능한 용량
- 의도한 구독을 선택한 대화형 Azure 세션

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

로그인한 뒤 저장소를 clone하고 선택한 Azure 리전에 배포를 시작하는 한 줄을 실행합니다.

```bash
az login
git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --region koreacentral
```

이미 clone이 있다면 그 루트에서 `scripts/deployment/azure/fdai-up.sh --region koreacentral`을 대신
실행합니다. 래퍼는 clone의 잠긴 환경을 준비하고 지정한 옵션으로 `fdaictl provision azure --source .`를
실행합니다. CLI를 설치했다면 clone에서 그 명령을 직접 실행할 수 있습니다. 대화형 터미널에서는
활동 내역이 자동으로 표시되며, 줄 단위 로그가 필요하면 `--progress plain`을 추가합니다. 비공개
작업 디렉터리는 clone 밖에 있어야 합니다.

조정기는 재개할 수 있는 단일 프로세스에서 다음 작업을 수행합니다.

1. 명령줄 비밀로 값을 받지 않고 Azure CLI에서 활성 tenant와 subscription을 읽습니다.
2. clone의 깨끗하게 커밋된 스냅샷 하나를 고정합니다.
3. clone의 `secrets/` 디렉터리를 보고 Trial 또는 전체 사용권 모드를 선택합니다.
4. 정책, 할당량, provider 및 대상을 읽기 전용으로 검사합니다.
5. Foundation 계획을 표시하고 적용합니다. 비공개 상태 경계, Virtual Network, Bastion 액세스,
   배포 신원 및 Managed Host를 만듭니다.
6. 스냅샷에서 서비스 이미지를 자신의 레지스트리에 빌드하고 그 digest를 다시 읽습니다.
7. 마이그레이션과 카탈로그를 적용하고, Trial을 시작하거나 전체 사용권을 저장하고, 선택한 경우
   Entra를 구성한 뒤 애플리케이션을 digest로 배포합니다.
8. 이미지 digest, 마이그레이션과 카탈로그 상태, 서비스 상태 및 두 번째 변경 없음 계획을
   검증합니다.

명령 실행이 그 명령이 표시하는 각 계획을 승인합니다. 기존 리소스를 삭제하거나 교체할 때만
추가로 한 번 입력해 확인해야 합니다. 명령은 응답이 없다고 승인한 것으로 해석하지 않습니다.
적용 결과가 불분명하면 같은 명령을 다시 실행할 때 적용을 반복하지 않고 검증 전용 복구를
수행합니다. 나중에 명령을 다시 실행하면 현재 clone으로 같은 설치를 업그레이드합니다.

먼저 가능성을 확인하려면 Azure 접근 없이 스냅샷만 고정하는 `--prepare-only`나 리소스를 바꾸지
않고 AKS SKU와 할당량을 읽는 `--preflight-only`를 추가합니다. 준비나 사전 점검의 성공은
애플리케이션 배포 완료를 뜻하지 않습니다.

새 대화형 실행은 시작할 때 한 번 설치 설정을 보여 줍니다. 구축 예상 비용 한도는
`--setup-cost-ceiling <USD>`로 지정하거나 그 검토 중에 입력합니다. 선택적 화면은 `--add-on`으로,
선택적 관찰 출처는 `--observation-source`로 고르며, 기본값은 헤드리스 관찰 우선 프로파일입니다.
이 설정만으로 리소스를 배포하지는 않습니다.

Foundation 계획 전에 Genesis는 지역 VM 카탈로그를 읽고 할당량 안에서 호환되는 Managed Host
크기를 선택합니다. 선택은 승인 전에 봉인하며 적용 중에는 바꾸지 않습니다. 호환되는 크기가
없으면 보고된 제한, 하드웨어 요건, 할당량을 검토하세요. 기존 적용 시작 기록이 있으면 검증만
재개합니다.

Foundation 계획은 먼저 비공개 로컬 백엔드를 사용합니다. 정확한 마이그레이션 아카이브만
증명된 호스트에서 서명된 원격 백엔드 예제를 활성화하며, 마이그레이션 승인과 재확인은 필수입니다.
보존된 이행 `claim`이 완전한 아카이브보다 먼저 만들어져 같은 상위 지원 파일이 모두 없다면,
수정된 정확한 소스와 새로운 `foundation-state` 승인으로 재개하세요. 조정기는 원래 `claim`과
백엔드 효과를 유지하고, 검토된 복구 구성의 정확한 파일만 복원하며, Terraform 입력 트리 밖의
현재 소스 오버레이를 검증한 뒤 검증만 실행합니다. 일부 파일만 있거나 기존 파일이 다르면
복구가 중단됩니다.
정리 후에는 이후의 정확한 소스 실행이 검증된 관찰기를 비공개 Bastion 경로로 전송하고
다이제스트를 다시 읽어 확인한 뒤 Managed Identity로 실행합니다. 관찰기는 Azure CLI로 보호된
상태 blob을 직접 다운로드하고 보존된 권한 다이제스트와 비교한 다음, 삭제된 Terraform 작업
트리나 provider 미러를 다시 만들지 않고 임시 파일을 제거합니다.

### 검증된 공개 개발 배포 복구

이 복구 경로는 `azd-up.sh` 공개 개발 bootstrap의 상태를 채택하며, 제거될 예정인 기존 릴리스 키트
획득 경로를 여전히 사용합니다.

기여자 배포가 실패한 적용 이후 검증된 `fdai.contributor-recovery.v1` 증적을 생성한 경우에만
애플리케이션 상태 채택을 사용하세요. 채택 지원이 포함된 정확한 서명 키트 개정 번호에서 다음
명령을 실행합니다.

```bash
fdaictl provision azure \
  --online \
  --region <azure-region> \
  --adopt-runner-image-receipt <verified-runner-image-receipt> \
  --adopt-application-state <private-terraform-state> \
  --adopt-application-recovery <private-recovery-receipt> \
  --adopt-resolved-models <private-resolved-models>
```

runner 증적과 mode-0600 애플리케이션 파일 세 개를 모두 함께 제공하세요. 조정기는 다이제스트,
대상, 리소스 수, 리소스
접미사 및 모델 기능 계약을 검증합니다. 애플리케이션 리소스 그룹의 소유권 레코드 두 개만 제거한
비공개 단계 상태 복사본을 만듭니다. 원래 로컬 상태는 변경하지 않습니다.

runner 증적은 이미 독립 검증된 관리 이미지를 image apply 없이 재사용합니다. 새 Foundation
실행은 현재 서명 출처를 유지하고 이미지의 원래 출처, 서명 검증기 출처, 이미지 실행 및 정확한
증적 다이제스트를 별도 출처 정보로 기록합니다.

Managed Host는 Foundation이 소유한 원격 애플리케이션 백엔드에 상태 Blob이 없을 때만 단계
상태를 허용합니다. 강제하지 않는 상태 push 한 번 전에 변경 불가능한 claim을 기록하고, 이후
상태를 다시 읽어 lineage, serial, 내용 및 관리 리소스 수를 검증합니다. claim 이후 프로세스가
중단되면 같은 작업 디렉터리와 입력으로 같은 명령을 실행하세요. 호스트는 기존 원격 상태를
검증하고 push를 반복하지 않습니다. 입력, 대상, Foundation 연결이 다르거나 백엔드가 비어 있지
않거나 lineage가 바뀌면 운영자 검토를 위해 복구를 중단합니다.
복구 상태 경로는 이후 계획 중 하나에 삭제 또는 교체 작업이 포함되어 있어도 승인 전에
중단합니다.

채택 오류를 해결하기 위해 기존 Azure 리소스나 원래 로컬 상태를 삭제하지 마세요. 작업
디렉터리를 보존하고 유지된 claim 또는 receipt로 실패한 경계를 확인하세요.

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

명령은 파일을 사용하기 전에 패키지의 분리형 Ed25519 서명과 모든 checksum을 검증합니다.
패키지만으로 충분하며 다운로드, 공개 레지스트리, 패키지 인덱스, 빌드가 필요하지 않습니다.
Azure 관리 및 데이터 평면 엔드포인트는 Azure 네트워크 경로로 계속 도달할 수 있어야 합니다.
패키지 서명 키는 산출물을 인증할 뿐 사용 권한을 뜻하지 않으므로, 별도로 발급한 사용권을
제공하지 않으면 오프라인 설치는 30일 Trial로 동작합니다.

> Azure 관리 플레인 경로가 없는 네트워크에서는 Azure 리소스를 배포할 수 없습니다. 해당
> 프로필에서는 패키지를 검증하고 준비할 수 있지만 명령은 배포 준비 상태를 보고할 수 없습니다.

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

비공개 작업 디렉터리에는 SSH 키, 대상별 입력, 계획, 복구 상태가 포함될 수 있습니다. 내용을
업로드하거나 공유하지 말고 민감한 값을 제거한 CLI 진단을 사용하세요. 검증 및 필요한 복구가
끝날 때까지 이 디렉터리를 유지하세요.

## 내부 및 고급 경로

다음 도구는 공개 대상 환경 배포 진입점이 아닙니다.

- `genesis-up.sh`는 저수준 Foundation 진단 및 복구 도구입니다.
- `azd-up.sh`는 Container Apps에 Core만 배포하는 공개 개발 bootstrap입니다. 단일 명령 소스
  배포가 아닙니다.
- `fdaictl provision azure --online`은 게시된 릴리스 키트를 가져옵니다. 두 설치 방식에 속하지
  않으며 제거될 예정입니다.
- `fdai-up.sh`는 폐기된 `--signing-key` 옵션을 거부하며 키트를 빌드하지 않습니다. 서명된 오프라인
  패키지는 따로 빌드해 `--offline-kit`로 전달합니다.
- `.github/workflows/` 아래 배포 workflow는 저장소 CI, release 및 과거 자동화입니다. 대상 환경
  설치 프로그램으로 지원되지 않습니다.
- Terraform 직접 실행은 전문가 통합 경계입니다. 동일한 계획, 승인, 신원, rollback 및 검증
  계약을 유지해야 합니다.

## 다음 단계

| 알아볼 내용 | 참조 문서 |
|------------|-----------|
| 단일 명령 소스 배포와 사용권 | [단일 명령 소스 배포](../roadmap/deployment/source-deployment-ko.md) |
| 전체 배포 토폴로지 | [배포와 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md) |
| 연결 및 폐쇄망 실행 프로필 | [프로비저닝 실행 프로필](../roadmap/deployment/provisioning-execution-profiles-ko.md) |
| 서명된 오프라인 패키지와 신뢰 경계 | [연결이 끊긴 배포](../roadmap/deployment/disconnected-deployment-ko.md) |
| 완료되지 않은 실행 이후 복구 | [배포 복구](../runbooks/deployment-recovery-ko.md) |
