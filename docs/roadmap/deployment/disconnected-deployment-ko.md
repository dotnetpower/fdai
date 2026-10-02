---
title: 폐쇄망 배포
translation_of: disconnected-deployment.md
translation_source_sha: 023717ed285070f8bf328dcda3bb0c46314aef5b
translation_revised: 2026-10-02
---
# 폐쇄망 배포

> **배포 방식:** [헌법](../architecture/fdai-constitution.md#article-1-purpose-and-scope)은 단일 명령 소스 배포와 서명된 오프라인 패키지라는 두 가지 설치 방식만 정의합니다. 이 문서의 설치 관문 중 헌법에 없는 것은 대체되었으며 더 이상 적용되지 않습니다.

이 문서는 공용 인터넷 egress가 차단된 네트워크 - 규제받는 금융 테난트, sovereign enclave,
완전 air-gap 사이트 - 에 FDAI를 배포하는 단일 소유 문서입니다. 리포지토리가 이미 지원하는 것,
운영자가 직접 공급해야 하는 것, 완전한 폐쇄망 설치를 아직 막고 있는 공백을 명시합니다.

> **범위:** Azure가 구현된 대상입니다. 이 문서는 비공개 networking Terraform 계층
> ([deploy-and-onboard-ko.md](deploy-and-onboard-ko.md)), 산출물 계약
> ([installable-deployment-cli-ko.md](installable-deployment-cli-ko.md)), 프로파일 선택 규칙
> ([provisioning-execution-profiles-ko.md](provisioning-execution-profiles-ko.md))을 다시
> 서술하지 않습니다. 그것들을 순서로 엮습니다.
## 한눈에 보는 설계

"폐쇄망"은 하나의 설정이 아닙니다. 두 개의 독립된 속성이 이 문서가 얼마나 적용되는지를 결정하며,
테난트는 그 격자의 어느 위치에나 있을 수 있습니다.

| 속성 | 값 | 결정하는 것 |
|------|-----|-------------|
| **Azure 도달성** | 비공개 엔드포인트, 또는 전혀 없음 | 컨트롤 플레인이 관리 평면, 시크릿 저장소, 이벤트 버스, 상태 저장소를 호출할 수 있는지 |
| **공용 산출물 egress** | allow-list, mirror, 또는 없음 | 공용 패키지 인덱스, Terraform 레지스트리, 공용 컨테이너 레지스트리에 도달할 수 있는지 |

대부분의 규제 테난트는 **비공개 Azure 도달성 + 공용 산출물 egress 없음**에 위치합니다.
컨트롤 플레인은 비공개 엔드포인트 위에서 정상 동작하고, 모든 런타임 산출물과 설치 입력은 내부
mirror나 서명된 매체에서 와야 합니다. 진짜 air 공백 - Azure 도달성도 없음 - 은
[완전 air 공백](#완전-air-gap)에서 다루는 더 좁은 프로파일입니다.

## 비공개 Azure, 공용 egress 없음

비공개 Azure 인프라 경로는 구현되어 있습니다. Offline 배포판과 CLI 경로는 위 원장에
기록된 대로 아직 구현 중입니다.

### 전체 로컬 산출물 준비

독립적으로 신뢰가 확립된 `fdaictl` 설치와 승인된 신뢰 절차로 전달된 검증 키를 사용합니다.
신뢰할 수 없는 키트에 함께 담긴 키만으로 해당 키트의 신뢰를 확립할 수 없습니다.
운영용 신뢰 루트 확립과 배포 적격성은 별도의 사전 조건입니다.

연결된 release 호스트에서 외부 키트를 서명하기 전에 사전 빌드된 OCI 아카이브와 공급망
근거를 하나의 런타임 v2 디렉터리로 기술합니다. 비공개 빌드 서술자는 소스 루트 아래의 상대
경로를 사용하고 모든 아카이브, SBOM, 출처, OCI 매니페스트 다이제스트를 고정합니다.

```bash
uv run --project packages/deployment-cli python \
  scripts/deployment/release/build-runtime-release.py \
  --source-root /private/release-inputs \
  --descriptor /private/runtime-release-build.json \
  --deployment-bundle /private/fdai-deployment-bundle-0.1.0.tar.gz \
  --output /private/runtime-release
```

조립기는 다운로드, 이미지 빌드, 서명, 증명, 레지스트리 호출, Azure 작업을 수행하지 않습니다.
사전 빌드된 입력만 받아 OCI 아카이브 6개를 검증하고
`production_release_eligibility=unverified`인 닫힌 트리를 게시합니다. Release 정책은 이
트리를 구성하고 서명하기 전에 소스와 근거의 적격성을 독립적으로 확립해야 합니다.
전체 키트에는 staging 스크립트의 `--runtime-descriptor`와 `--runtime-source-root`를
사용합니다. 스크립트가 정확한 서명 배포 번들을 먼저 만들고 그 바이트를 런타임 조립기에
전달하므로 다른 서명 시도의 번들에 의존하는 순환을 방지합니다.

```bash
fdaictl offline prepare \
  --offline-kit /media/fdai-kit \
  --release-root /trusted/release-root.pub \
  --bundle-public-key /trusted/bundle-key.pub \
  --profile /private/offline-profile.json \
  --source-commit <git-sha> \
  --work-dir /private/fdai-preparation \
  --output json
```

프로필은 `offline`, 대상 바인딩, 양수인 월 비용 상한을 선택합니다. 작업 디렉터리는 아직
존재하지 않아야 합니다. 준비 과정은 Azure, 레지스트리, 모델, 작업 흐름을 호출하거나
아카이브를 실행하지 않습니다. 도구만 담긴 키트는 차단됩니다.

전체 준비에는 `fdai.runtime-release.v2` 스키마의 `runtime/release.json`이 필요합니다.
기존 v1 목록은 점검을 위해 읽고 구성할 수 있지만, 필수 사이드카가 선언되어 있지 않아
전체 준비 검증을 통과할 수 없습니다.

| 필드 | 필수 내용 |
|------|-----------|
| `source_commit`, `platform_tag` | 정확한 소스 버전과 지원되는 Linux CPU 플랫폼 |
| `deployment_bundle_sha256` | 짝을 이루는 서명된 배포 번들 아카이브의 다이제스트 |
| `services` | Core, Operator, 수집 API, 문서 작업자, 격리 실행기의 정확한 5개 항목 |
| 각 서비스 | 로컬 아카이브, SBOM, 출처 경로 및 SHA-256 다이제스트, OCI 이미지 다이제스트 |
| `sidecars` | 정확히 `clamav` 한 항목. 서비스와 동일한 아카이브, SBOM, 출처, 이미지 다이제스트 필드 |
| `console`, `deployment_support` | SHA-256 다이제스트가 있는 로컬 아카이브와 SBOM |

모든 페이로드 경로는 `runtime/` 아래에 있습니다. 누락, 추가, 링크, 중복, 불일치, 크기
초과 입력은 차단됩니다. 기존 키트 제한은 파일당 512 MiB, 전체 8 GiB로 유지합니다.
더 큰 배포판은 제한 해제가 아니라 검토된 형식 변경이 필요합니다. V2 구성과 준비 과정은
계층을 추출하거나 실행하지 않고 각 이미지의 OCI 구조, 블롭 해시, 매니페스트 다이제스트,
CPU 플랫폼을 검증합니다. 서비스 이미지는 선언된 FDAI 소스 버전도 포함해야 합니다.
의존성 이미지에는 FDAI 버전을 적용하지 않습니다. 해당 내용은 다이제스트로 연결되지만
소스 출처까지 입증하지는 않습니다. 출처와 SBOM의 의미, 계층 내용, Console 구성,
마이그레이션 완전성은 여전히 별도 검증이 필요합니다.
구조는 레지스트리 매니페스트 바이트를 그대로 유지합니다. OCI 이미지 미디어 계열 또는
보호된 게시자가 생성한, 계열이 일관된 Docker 스키마 2 매니페스트, 구성, gzip 계층 미디어
형식을 수락합니다. 스키마 1, 혼합 계열, 외부 배포 계층은 계속 차단되므로 `image_digest`는
변환 결과가 아니라 원본 레지스트리 및 출처 증명 대상에 결속됩니다.
OPA는 Core 이미지에 내장되어 있고 키트에도 배포 도구 바이너리로 포함되므로,
별도로 배포하는 사이드카가 아닙니다.
ACR 어댑터는 검증된 의존성을 게시할 때 FDAI 소스 버전을 만들어 넣지 않습니다.
증적은 `source_commit=None`을 사용하고 서비스 게시와 동일하게 정확한 매니페스트의 GET
재확인을 요구합니다. 두 경로 모두 보호된 실행기용 저수준 API입니다. 준비된 목록만으로
업로드가 승인되거나 의존성 출처가 입증되지는 않습니다.

배포 담당자는 `stage-offline-kit.sh`에 `--runtime-release <directory>`를 전달해 키트의
SBOM과 서명을 생성하기 전에 목록과 실제 로컬 페이로드를 포함합니다. 이 옵션은 목록의
소스 버전과 일치하는 깨끗한 체크아웃을 요구합니다. 런타임 이미지 다운로드·빌드나 출처
생성을 수행하지 않으며 보호된 배포 검증을 대체하지 않습니다.

완전히 검사된 비공개 스냅샷만 `prepared/`에 게시합니다. `preparation.json`은 프로필,
대상, 비용 상한, 소스, 키트, 런타임 목록, 배포 번들, 초기 구성 매니페스트를 연결합니다.
`fdai.offline-preparation.v2` 증적은 검증한 이미지 6개의 다이제스트도 연결합니다.
`state=prepared`, `subscription_ready=false`는 입력 준비를 뜻하며 설치 완료가 아닙니다.
비용을 추정하거나 승인된 실행 가능 Terraform 계획을 생성하지 않습니다.

Offline 준비는 배포를 수행하지 않습니다. 공개 CLI에는 workflow dispatch 경로가 없으며,
`fdaictl provision azure --offline-kit`과 배포 어플라이언스가 실제 설치를 담당합니다. 전체
경로에는 승인된 Foundation 생성, 비공개 상태 이전, 애플리케이션 배포, 데이터베이스 초기화,
인증된 Console 재확인, 최초 전체 리소스 검색 및 독립적인 최종 준비도 검증이 필요합니다.
[구독 초기 프로비저닝](subscription-genesis-provisioning-ko.md)을 참조하세요.

패키지 제작 호스트에서 `--with-runtime-wheels`를 추가하면 고정된 지원 인터프리터 입력을
`support/python/`에 포함합니다. `fdaictl offline install-support`는 입력을 인증하고,
패키지 인덱스나 캐시 없이 설치한 뒤 실제 설치 버전을 재확인합니다. 이는 배포 도구이며
5개 런타임 서비스를 하나의 프로세스로 대체하지 않습니다.
서명된 지원 목록은 서비스 계약 배포판과 이 5개 배포판만 런타임 루트로 허용합니다.
System Knowledge처럼 독립적으로 선택 배포되는 서비스는 제외하며, 공통 GitHub 인증
라이브러리는 전이적 지원 패키지로만 포함될 수 있습니다.
[CLI 설치 명령](../../../packages/deployment-cli/README.md)을 참조하세요.

### 설치 시 범용 Console 빌드에 설정 적용

패키지 제작 호스트에서 `npm --prefix console run build:offline`을 실행합니다. 결과는
`console/dist/offline/`에 생성되며 로컬 환경 파일과 프로세스의 `VITE_*` 값은 제외됩니다.
이 빌드는 설치 시 설정을 요구하고, 설정이 없을 때 로컬 API 기본값으로 대체하지 않습니다.
설치 호스트에는 사전 빌드된 파일의 설정을 위해 npm을 설치할 필요가 없습니다.

현재 사용자 소유의 mode-`0700` 작업 디렉터리에 빌드를 복사하고 비공개 디렉터리 아래에
mode-`0600` 설정 파일을 준비합니다. 이후 다음 명령을 실행합니다.

```bash
fdaictl offline configure-console \
  --directory /private/console \
  --settings /private/console-settings.json \
  --output json
```

설정 스키마는 `fdai.console-runtime.v1`이며 `schema_version` 외에
`operator_api_base_url`, `ingestion_api_base_url`, `tenant_id`, `spa_client_id`,
`api_scope`만 포함합니다. API URL은 자격 증명과 쿼리 문자열이 없는 HTTPS를 사용하고,
식별자는 UUID, 범위는 `api://<API-application-id>/<scope>` 형식입니다.
이 값은 공개 설정이며 비밀이나 역할 부여가 아닙니다.
[CLI README](../../../packages/deployment-cli/README.md)에 합성 예제가 있습니다.

명령은 배포된 `fdai-config.js` 자리표시자만 원자적으로 교체합니다. 동일 설정으로 반복하면
변경하지 않으며, 테넌트나 엔드포인트를 바꾸려면 원본 빌드를 새로 복사해야 합니다.
이 설정은 이전 빌드에 인증 우회 플래그가 있어도 Entra 인증을 강제하며, 호스팅 설정은
해당 파일에 `no-store`를 지정합니다. 파일 설정만으로 Entra 등록, 사이트 게시,
API CORS 설정, 인증된 접근 검증을 수행하지는 않습니다.

### 오프라인 실행 호스트 시작

초기 구성 입력에 `runner_bootstrap_mode = "offline"`을 설정하고 버전이 지정된
`runner_source_image_id`를 제공합니다. GitHub 등록 필드 두 개는 비워 둡니다.
오프라인 모드는 초기화 스크립트 다운로드 없이 사전 준비된 이미지를 사용하며,
기존 온라인 기본 동작은 유지됩니다. 이미지에는 승인된 도구가 필요하고 캐시된 자격
증명을 포함하면 안 됩니다. 네트워크 접근과 이미지 검증은 여전히 독립적인 확인이
필요합니다. `enable_public_egress`는 별도로 명시적으로 선택합니다.
[bootstrap README](../../../infra/bootstrap/README.md)를 참조하세요.

새 플랫폼 계획은 `generate_initial_postgres_password = true`와
`postgres_admin_password = null`을 사용할 수 있습니다. 민감한 32자 자격 증명은 승인된
비공개 호스트 적용에서 생성하고 비공개 상태에 보존합니다. 이 선택을 유지하세요.
기존 서버를 생성된 자격 증명으로 바꾸는 작업은 별도 검토된 교체이며, 조용한 최초 설치 재시도가 아닙니다.

### 1. 모든 서비스를 비공개로 provision

`enable_private_networking = true`로 설정합니다. 배포는 시크릿 저장소, 두 event-bus 샤드,
상태 저장소, 블롭 및 데이터 lake 저장소, 모델 엔드포인트에 virtual 네트워크, 비공개 엔드포인트,
linked 비공개 DNS를 provision합니다. Delegated-subnet state-store 모드가 필요하면
`enable_private_postgres = true`를 추가합니다.

`acr_sku = "Premium"`도 설정합니다. 비공개 링크는 Premium 전용 레지스트리 기능이므로 Basic이나
Standard 레지스트리는 의도적으로 공개로 남습니다. 비공개 경로 없이 닫으면 모든 이미지 pull이
깨지기 때문입니다. Premium이면 레지스트리는 공개 네트워크 접근을 잃고 자체 비공개 엔드포인트를
받습니다.

코어 엔진과 실행기는 어떤 프로파일에서도 공개 인바운드 엔드포인트가 없습니다. Ingress는 이벤트
버스이고 egress는 allow-list 기반 기본 거부입니다
([security-and-identity-ko.md](../architecture/security-and-identity-ko.md)).

### 2. 네트워크 내부에서 배포

비공개 전용 시크릿 저장소와 비공개 상태 계정은 운영자 워크스테이션에서 도달할 수 없습니다.
`terraform apply`는 그 엔드포인트에 네트워크 시야가 있는 호스트 - virtual 네트워크 내부의
자체 호스팅 실행기 또는 점프박스 - 에서 실행해야 합니다. `infra/bootstrap` 계층이 그 지속적 허브를
세우고, `scripts/deployment/azure/check-runner-egress.py`가 실행기가 실제로 도달 가능한
allow-list 호스트를 기록합니다. 따라서 계획은 자신의 네트워크 위치를 가정이 아니라 증거로
가지고 다닙니다.

그 계층은 기본적으로 아웃바운드 경로 하나 - static 공개 IP를 가진 NAT 게이트웨이 - 를 만듭니다.
GitHub에 등록된 실행기는 GitHub, 관리 평면, 신원 평면에 도달해야 하기 때문입니다.
폐쇄망은 `enable_public_egress = false`로 설정합니다. 공개 주소를 전혀 만들지 않고, 호스트는
등록된 실행기가 아니라 점프박스가 되며, 테난트가 관리 및 신원 평면으로 가는 자체
승인 경로를 공급합니다.

레지스트리가 비공개가 되면 같은 호스트에서 사전 빌드 서명 런타임 이미지를 미러링하거나
반입합니다. 작업은 소스 매니페스트를 검증하고 대상의 동일한 digest를 다시 확인합니다. 이미지를
빌드하거나 변경 가능한 참조로 태그하거나 이미지 바이트를 바꾸지 않습니다.

### 3. 모든 산출물 입력을 내부 mirror로

| 입력 | 메커니즘 |
|------|----------|
| 런타임 및 의존성 이미지 | 서명된 런타임 매니페스트가 수락할 모든 sha256 digest를 지정합니다. 내부 mirror는 레지스트리 위치만 바꾸며 같은 매니페스트 digest를 반환해야 합니다. |
| Python 패키지 | `infra/modules/preflight-toggles/python_index_url`이 내부 피드용 package-index 설정을 발행합니다 |
| 배포 시점 레지스트리 pull | `infra/modules/preflight-toggles/registry_source`가 공개 기본값에서 내부 레지스트리 mirror로 전환합니다 |
| Terraform 프로바이더 | offline 키트가 pinned 프로바이더 mirror를 담고, offline 모드는 공개 레지스트리 대체 경로를 차단합니다 |

업스트림 release gate는 base 이미지가 digest 고정을 잃거나 레지스트리 호스트를 하드코딩하면
차단합니다. 따라서 mirror 경계가 고정되지 않은 pull로 바뀔 수 없습니다. 테넌트 프로비저닝은
해당 release 근거를 사용하며 빌드를 다시 실행하지 않습니다.

### 4. CLI와 번들을 서명된 offline 키트로 전달

release 스크립트는 connected 호스트에서 `scripts/deployment/release/stage-offline-kit.sh`로 키트를
구성하도록 설계되어 있습니다. 이 스크립트가 `fdai-deployment-cli` 휠과 모든 전이 의존성 휠, 서명된 배포 번들,
pinned Terraform binary 및 프로바이더 mirror, 정책 엔진 binary, software bill of materials를 모으고
`scripts/deployment/release/build-offline-kit.py`로 서명합니다. 매니페스트는 staged 트리에서
생성되므로 검증기가 거부할 내용을 증언할 수 없고, release 비공개 키는 키트에 들어가지
않습니다.
서명된 번들에는 마이그레이션 중 카탈로그 구체화가 읽는 검토된 `config/agent-stewardship.yaml`과
`config/architecture-review.yaml`도 들어 있습니다.

패키지에 포함된 release 및 bundle 루트와 일치하는 로컬 비공개 키를 확인하려면
`scripts/deployment/release/check-signing-key.py --key <path>`를 실행합니다. 이 스크립트는 지문과
역할만 출력합니다. 일치하는 키에 대해서는 그 키를 받는 `build-standalone-deployment-kit.sh` 옵션인
`--signing-key`, `--release-key` 또는 `--bundle-key`를 알려 줍니다. `fdai-up.sh`는 더 이상 서명 키를
받지 않습니다.

목표 폐쇄망 명령인 `fdaictl provision inspect`는 매니페스트를 파싱하기 전에 서명을 검증하고, 정확한
CLI 및 platform 버전을 연결하며, symlink와 추가 파일을 거부하고, 모든 다이제스트를 스트리밍
합니다. 존재는 결코 신뢰가 아닙니다. 검증되지 않은 키트는 `candidate`로 남고, 거부된 내용은
`incomplete`입니다.

키트의 CycloneDX 문서는 키트가 담은 모든 파일을 SHA-256과 함께 나열합니다. 키트는 인계에서
외부 공급망을 담는 쪽입니다. Terraform binary, 정책 엔진 binary, 그리고 mirror된 모든
프로바이더와 그 정확한 버전이 여기 있습니다. 서명은 문서가 변조되지 않았음을 증명하지만
아무것도 기술하지 않는 문서를 알아채지는 못합니다. 그래서 훈련은 SBOM이 매니페스트가 나열한
모든 파일을 설명하는지 단정합니다.

#### 배포 제어 패키지

배포 제어 코드를 수정할 때 전체 키트를 새로 만들 필요는 없습니다. 운영자는 `--offline-kit`과
함께 `--control-package <signed-wheelhouse.tar.gz>`를 지정할 수 있습니다. 조정기는 패키지에
고정된 릴리스 루트로 `SHA256SUMS`에 대한 분리형 Ed25519 서명, 목록과 정확히 일치하는 파일
구성, 모든 파일 다이제스트, 고정된 `fdai-deployment-cli` wheel 하나를 검증합니다. 관리형
호스트는 같은 아카이브를 받아 같은 SHA-256 다이제스트를 보고해야 하며, 새 환경에 이
wheelhouse만 사용해 CLI를 설치합니다.

런타임 이미지, Terraform 번들, 도구 모음, Console은 계속 검증된 키트가 제공합니다. 실행
바인딩과 관리형 호스트 작업 디렉터리에는 제어 패키지 다이제스트가 포함되므로 패키지가 바뀌면
새 준비 컨텍스트가 필요합니다. 배포 결과는 키트 소스 커밋과 함께 제어 패키지 다이제스트와
버전을 보고합니다. 제어 패키지는 승인, 적용 또는 런타임 권한을 부여하지 않습니다.

#### 기존 오프라인 설치 업그레이드

더 새 서명 키트로 오프라인 패키지 설치를 계속하려면 같은 작업 디렉터리로 다시 실행합니다.

```bash
scripts/deployment/azure/fdai-up.sh \
  --offline-kit <newer-kit.tar.gz> \
  --work-dir <existing-work-dir>
```

조정기는 새 키트를 검증하고, 이전에 보존된 키트 스냅샷과 Managed Host 전송 아카이브를 로컬
검토 디렉터리로 회전한 다음 기존 Foundation 신원을 유지합니다. Foundation 변수는 Foundation을
만든 소스 버전을 유지합니다. 새 키트 소스는 애플리케이션 버전으로 기록되므로 애플리케이션
단계와 Managed Host 작업 컨텍스트는 키트 매니페스트 다이제스트를 기준으로 새 Terraform,
런타임 페이로드, CLI를 사용합니다. 비파괴 Foundation 계획은 그 계획을 표시한 호출로 승인됩니다.
기존 리소스를 삭제하거나 교체하는 계획은 효과 전에 기존의 명시적 추가 확인이 계속 필요합니다.

### 5. 공용 egress 없이 룰 카탈로그 최신화

서명된 배포 번들은 이미 rule-catalog 스키마, 배포 프로파일, risk 분류를
담고 있으므로, 카탈로그 갱신은 코드와 같은 방식 - 새 서명 번들 - 으로 전달됩니다. 테난트가
수집 파이프라인을 직접 돌리고 싶으면 가져오기 도구가 로컬 디렉터리 또는 git 원격을 받으므로
업스트림 출처의 내부 mirror가 지원되는 입력입니다. 런타임에 공개 출처 URL은 필요하지
않습니다
([rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md)).

오프라인 키트는 `--rule-activation-profile`, `--rule-activation-profile-id`,
`--rule-activation-profile-created-at`으로 하나의 Rule 활성화 profile을 바인딩할 수 있습니다.
서명된 매니페스트는 정확한 profile 바이트, ID 및 source 시각을 포함합니다. `offline prepare`는
검토된 멤버십을 배포 로컬 PostgreSQL 세대에 조정하는 데 필요한 profile digest와 Core 환경
바인딩을 반환합니다. 준비 단계에서는 profile을 적용하거나 enforce 권한을 부여하지 않습니다.

### 6. 조작된 증거가 아니라 저하된 증거를 기대할 것

제한된 egress는 컨트롤 플레인이 관찰할 수 있는 것을 바꾸며, 모든 대체 경로는 순서가 있고
실패 시 차단입니다.

- **인벤토리**: resource-graph 조회 경로가 먼저, 그다음 검증된 private-link 관리 경로,
  샤드된 관리 목록 작업, 범위가 명시된 권위 있는 인벤토리, activity-log 연속성,
  마지막으로 서명된 declarative 스냅샷입니다. 실패한 경로는 마지막 완전한 그래프를 유지하고
  stale로 표시하며, 빈 그래프를 절대 게시하지 않습니다.
- **아이덴티티**: 테난트 발견 엔드포인트에 도달할 수 없으면 `FDAI_ENTRA_JWKS_URI`를
  재정의합니다 ([user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md)).
- **적응형 결정**: 모델 경로를 사용할 수 없으면 적응형 능력은 사용 불가를 보고하고 해당 작업은
  deterministic-only로 남습니다. 자율성은 저하될 뿐 fail-open하지 않습니다.

## 이미지 배포판 프로비저닝

서비스 런타임 이미지는 Azure 인프라를 구성하지 않습니다. `infra/`와 Terraform을 포함하지
않고 서비스 하나를 시작합니다. **배포 어플라이언스**는 설치된 CLI와 선택적 배포 페이로드를
포함하고 승인된 네트워크 내부에서 standalone 배포를 시작하는 별도 이미지입니다. Python 패키지
형식이나 패키지 보증 요구 사항이 아닙니다.

가장 단순한 폐쇄망 인계는 서명된 Python wheel 모음과 배포 소유자가 선택한 배포 페이로드입니다.
OCI 어플라이언스는 편의를 위해 이 입력을 결합할 수 있지만 생성과 실행은 선택 사항입니다.

| # | 단계 | 도구 | 상태 |
|---|------|------|------|
| 1 | 선택적으로 어플라이언스 적재 | OCI 호환 컨테이너 도구 | 선택적 편의 기능 |
| 2 | Azure 인증 | 대화형 Azure CLI 사용자 또는 어플라이언스 Managed Identity | 진입점 선택 구현됨 |
| 3 | Standalone 배포 시작 | 설치된 CLI 또는 선택적 어플라이언스 진입점 | 구현됨 |
| 4 | Foundation 생성 또는 검증 | 로컬 조정기와 `infra/genesis-foundation` | 정확한 계획 및 Bastion 경로 구현됨 |
| 5 | 런타임 이미지 가져오기 및 애플리케이션 계획 | VNet 내부 Managed Host | digest 재확인 구현됨 |
| 6 | 적용, 마이그레이션 및 서비스 시작 | Managed Host Terraform과 마이그레이션 지원 | 구현됨 |
| 7 | 배포 준비 상태 검증 | 서비스 상태와 두 번째 변경 없음 계획 | 구현됨. 더 넓은 구독 보증은 별도임 |

어플라이언스는 **서명된 매니페스트**에서 Terraform 바이너리와 provider 미러를 해석하므로
포함된 키트 옆에 추가된 트리가 실행 대상을 결정할 수 없습니다. CLI 설정은 모든 직접 provider
원본을 제외하므로 미러에 없는 항목은 공개 레지스트리로 이동하지 않고 계획을 실패시킵니다.
허용 목록에 포함된 인증 변수만 Terraform에 전달하며 모든 적용은 검토한 정확한 binary 계획과
SHA-256 digest를 사용합니다.

키트의 내용을 **실행**하는 일은 그것을 **보고**하는 일보다 강한 증거를 요구합니다. `provision inspect`는
여전히 trust-root 재정의가 없고 검증되지 않은 키트를 `candidate`로 보고합니다. 운영자가 그 판단을
저울질할 수 있기 때문입니다. `provision plan`은 그럴 수 없습니다. 공급된 release 루트로 키트를 검증하고,
검증이 실패하면 계획을 거부합니다. 루트가 휠에 pinned 상태로 배포되면 `--release-root`는 계획 수립은
수락하고 점검은 여전히 수락하지 않는 재정의가 됩니다.

대상 환경 배포는 `manual` 전송 계층만 허용합니다. 공개 CLI에는 GitHub workflow dispatch
명령이 없습니다. GitHub는 어플라이언스를 빌드하고 게시할 수 있지만 대상 환경 내부의 배포
실행기로 접근되거나 신뢰되지 않습니다.

## 네트워크 없이 전 경로 예행연습

`scripts/deployment/release/airgap-drill.sh`는 고객이 받아야 하는 두 단계 인계 훈련을 정의합니다.
전용 CLI 검증기를 사용할 수 있으며 기존 도구 훈련 근거는 배포 CLI 원장에 기록돼 있습니다.
Stage 단계는 실제 `stage-offline-kit.sh`를
일회용 키로 실행하므로, 드릴 통과는 release 경로 자체를 실증합니다. Verify 단계는 경로도
이름 해석도 없는 네트워크 이름 공간 안에서 모든 폐쇄망 단계를 다시 실행합니다.

런타임 v2 디렉터리가 준비되면 명시적인 전체 모드를 실행합니다.

```bash
bash scripts/deployment/release/airgap-drill.sh \
  --runtime-descriptor /private/runtime-release-build.json \
  --runtime-source-root /private/release-inputs \
  --require-runtime
```

이 옵션이 없으면 스크립트는 기존 도구 전용 예행연습을 유지하고 런타임 준비를 실행하지 않았다고
명시합니다. 해당 결과는 전체 release 근거가 아닙니다.

Verify 단계가 순서대로 단정하는 것: 이름 공간에 정말로 egress와 DNS가 없다, 서명된 키트가 검증된다,
서명된 번들이 검증된다, `terraform init`이 키트 mirror만으로 모든 프로바이더를 해석한다,
`terraform validate`가 번들을 수락한다, `terraform test`가 mock 프로바이더로 계획 그래프를
평가한다, mirror 없이는 같은 `init`이 **실패한다**, `fdaictl license inspect`가 권한을
해석한다, 그리고 운영자가 실제로 실행하는 명령인 `fdaictl provision plan`이 스스로 같은 지점까지
도달하며 남은 것은 배포 입력뿐이다. 일곱 번째가 중요한 대조군입니다. 이것이 없으면 캐시된 플러그인
디렉터리가 아무것도 증명하지 않은 채 드릴을 통과시킬 수 있습니다. 아홉 번째는 해석되지 않은
프로바이더나 공개 레지스트리로 향하는 어떤 시도든 드릴을 실패시키도록 요구하므로, 깨진 mirror 고정이
누락된 변수인 척 통과할 수 없습니다.

드릴은 반복 실행할 수 있습니다. `--skip-stage`는 기존 키트로 재검증하고, 번들 트리는 매 실행마다
다시 풉니다. Terraform이 그 안에 쓰기 때문입니다. 한 번만 통과하는 드릴은 회귀 검사가 아니라
시연입니다.

## 도구가 먼저 손을 뻗지 않습니다

목표 `fdaictl provision inspect` 명령은 공용 호스트 세 곳에 TLS 연결을 열어 connectivity를 판정합니다.
`--connectivity offline`이면 그 판정을 아예 건너뜁니다. 운영자가 이미 답을 줬기 때문입니다.
폐쇄망에서 불필요한 탐색은 보안팀에 설명해야 할 아웃바운드 시도 세 건이고, egress 로그의 항목
세 개이며, DNS가 질의를 받고 응답하지 않는 환경에서는 빠른 로컬 점검이어야 할 명령의 긴 정지입니다.
`auto`는 여전히 탐색합니다. 정말로 듣지 못했기 때문입니다.

## 검증기가 거부하는 것

키트 검증기와 번들 검증기는 모두 아직 신뢰되지 않은 입력을 읽습니다. 그래서 둘 다 서명을
확인한 **뒤**가 아니라 **전에** 읽을 양을 제한하고, symlink를 통해 도달한 메타데이터를 거부하며,
나열할 수 없는 디렉터리에서 실패합니다. 마지막 항목이 보기보다 중요합니다. 경로 globbing은 볼 수
있었던 것만 조용히 돌려주므로, 서명자가 읽을 수 없는 디렉터리 아래의 내용이 빠진 트리에 서명하게
되고, 검증기는 잘린 트리를 완전한 것으로 수락하게 됩니다.

두 검증기는 의도적으로 대칭입니다. 같은 인계를 지키므로, 한쪽의 빈틈은 곧 양쪽의 빈틈입니다.

전체 모드는 인증된 휠 스냅샷에서 `fdaictl`을 설치하고 서비스 이미지 5개, ClamAV, Console,
배포 지원 자료를 대상으로 `offline prepare`도 실행합니다. 확인된 이미지 다이제스트 6개와
`subscription_ready=false`를 담은 `fdai.offline-preparation.v2` 증적이 필요합니다. 이어서
인덱스, 다운로드, 소스 빌드, 캐시를 비활성화한 상태로 해시가 고정된 모든 런타임 지원 배포판을
설치하고 재확인합니다.

드릴은 의도적으로 계획 평가에서 멈춥니다. 실제 `terraform apply`는 여전히 테난트의 승인된 비공개
관리 평면 경로가 필요하며, 그것을 로컬에서 시뮬레이션했다고 주장하는 것은 이 설계가 피하려는 종류의
주장입니다. 드릴의 서명 키는 작업 디렉터리 안의 일회용 키이며 리포지토리 자산이 되지 않습니다.

## 완전 air 공백

Azure 도달성이 전혀 없는 사이트도 결정론적 코어는 돌릴 수 있습니다. 정책 엔진은 이미지 안의 정적
binary이고, 룰 카탈로그와 온톨로지는 파일이며, declarative 인벤토리 어댑터는 클라우드 어댑터가
만족하는 것과 같은 `Inventory` 계약으로 손으로 작성한 리소스 그래프를 제공합니다. 그 사이트가
얻지 못하는 것은 실시간 클라우드 증거이므로, 클라우드 리소스에 대한 자율 조치는 구조적으로 범위
밖입니다.

이 프로파일은 아래의 trust 루트가 확립될 때까지 **참고용**이며, sovereign 배포는 별도의 규제 및
residency 검토를 추가로 요구합니다
([architecture-review-board-ko.md](../architecture/architecture-review-board-ko.md)).

## 완전한 폐쇄망 설치를 아직 막는 것

| 공백 | 오늘의 영향 | 소유 문서 |
|-----|-------------|-----------|
| 배포 가능한 전체 런타임 배포판이 게시되지 않음 | 로컬 준비는 실제 페이로드 목록을 지원하지만 승인된 이미지, Console 배포 입력, 그 근거를 만들어 내지는 않음 | [설치형 배포 CLI](installable-deployment-cli-ko.md) |
| Trust-root 의식이 실행되지 않아 휠에 pinned 공개 루트가 없음 | 점검이 offline 키트를 검증된으로 보고할 수 없고 `candidate` 또는 `review`로 남음 | [offline-trust-ceremony-ko.md](../../runbooks/offline-trust-ceremony-ko.md) |
| 오프라인 애플리케이션 실행이 연결되지 않음 | 공개 산출물 작업 흐름 제출은 차단되며 검증된 스냅샷만으로 애플리케이션을 배포할 수 없음 | [subscription-genesis-provisioning-ko.md](subscription-genesis-provisioning-ko.md) |
| 초기화 적용 orchestration과 정리가 목표 동작으로 남음 | 운영자가 exact-plan 승인과 적용을 수동으로 진행 | [installable-deployment-cli-ko.md](installable-deployment-cli-ko.md) |
| 자체 호스팅 모델 어댑터 없음 | 클라우드 도달성이 없는 사이트는 적응형 경로가 아예 없음 | [tech-stack-ko.md](../architecture/tech-stack-ko.md) |

프레임워크 표면과 오프라인 산출물 검증은 네트워크와 무관합니다. 운영용 신뢰 확립과
새 구독의 전체 런타임 설치는 별도의 미완료 요구 사항입니다.

## 관련 문서

| 알아보려는 것 | 읽을 문서 |
|---------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/deployment/disconnected-deployment.md) |
| 비공개 networking Terraform 계층과 강화 knob | [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md) |
| Offline 키트 계약, 빌드, 검증 | [provisioning-execution-profiles-ko.md](provisioning-execution-profiles-ko.md) |
| CLI 파사드, 서명된 번들, exact-plan 적용 | [installable-deployment-cli-ko.md](installable-deployment-cli-ko.md) |
| Offline trust 루트 확립과 교대 | [offline-trust-ceremony-ko.md](../../runbooks/offline-trust-ceremony-ko.md) |
| 거부된 키트 또는 차단된 계획에서 복구 | [deployment-recovery-ko.md](../../runbooks/deployment-recovery-ko.md) |
