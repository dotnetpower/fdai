---
title: 설치형 배포 CLI
translation_of: installable-deployment-cli.md
translation_source_sha: 528b75bdd3fdf1b964e8c97c00d4793f8d1e5f74
translation_revised: 2026-08-11
---
# 설치형 배포 CLI

이 문서는 FDAI의 목표 설치 및 배포 경험을 정의합니다. 운영자는 격리된 Python CLI 도구를
설치하고, 읽기 전용 배포 preflight를 실행한 다음, 로컬 머신을 통해 비밀을 이동하지 않고
승인된 Terraform 계획을 배포 실행기에 제출할 수 있습니다.

> **상태:** Increment C1과 C2의 static 부분은 출처 분포에 구현되었습니다.
> `fdaictl` 진입점, 결정론적 `version` 및 `doctor` 출력, 안전한 `onboard init`, 활성 Azure
> 대상 가드, network-free `deploy preflight`, Terraform 계획 JSON analysis, 로컬
> `security audit`을 사용할 수 있습니다. 원격 배포 계약, plan-only GitHub 작업 흐름
> 전달, exact-plan 적용 가드도 구현되었습니다. 범위가 제한된 실제 운영 Azure Policy, Compute 할당량,
> Resource Graph 신원, value-blind Key Vault 시크릿 탐색과 실행기 TLS egress 근거를
> 사용할 수 있습니다. 읽기 전용 `provision inspect`, signed 번들 빌드/verify/release
> 작업 흐름, 운영 exact-plan 적용 배선, 프로파일 영속성, PyPI Trusted 발행도
> 구현됐습니다. Offline 점검은 composition-injected pinned 검증기로 trusted 또는 rejected
> 키트 근거를 보고하며 운영자 trust-root 재정의를 노출하지 않습니다. Offline-kit 빌드, 서명,
> 검증도 구현됐습니다. `provision plan` 은 검증된 킷에서 disconnected 앱 계층 계획 을
> 오케스트레이션합니다. 첫 PyPI 게시, pinned offline 루트 packaging,
> 내부 mirror/disconnected 전달, 적용 orchestration, 정리는 남았습니다.
>
> **실행 경계:** Terraform은 인프라 실행 엔진이자 정본으로 유지됩니다. `fdaictl`은
> 검증, 계획 분석, 작업 흐름 제출, 배포 후 검사를 위한 얇은 orchestration 계층입니다.
>
> **구현 초점:** Azure가 유일한 구현 대상입니다. 비-Azure 프로바이더 지원은 연기됩니다.

## 한눈에 보는 설계

`fdaictl`을 격리된 `uv` 도구로 설치합니다. 승인된 실행 호스트가 exact Terraform 계획을
적용하기 전에 version-matched 번들과 대상 환경을 검증합니다.

| 관심사 | 결정 |
|--------|------|
| 운영자 명령 | `fdaictl` |
| 권장 설치 | `uv tool install fdai` |
| 일회성 및 CI 실행 | `uvx --from fdai fdaictl ...` |
| 인프라 엔진 | `infra/` 아래 Terraform |
| 기본 동작 | 읽기 전용 preflight 또는 계획 |
| 적용 위치 | VNet-integrated 자체 호스팅 실행기 |
| 패키지 내용 | Python CLI 휠과 서명된 배포 번들 |
| 머신 출력 | 안정적인 JSON 스키마와 문서화된 exit 코드 |
| 제품 언어 | 로케일 대체 경로가 있는 영어 출처 카탈로그 |

## 프로비저닝 실행 프로파일

프로비저닝은 connectivity, 실행 호스트, 전송 계층, 접근을 독립적으로 선택합니다.
[프로비저닝 실행 프로파일](provisioning-execution-profiles-ko.md) 문서가 읽기 전용 점검
계약, existing-host 및 managed-VM 룰, online 및 offline 전달, 접근 선호 설정,
one-person 승인, 별도 workload-identity 경계를 정의합니다.

## 별도 명령을 사용하는 이유

FDAI에는 서로 다른 세 개의 명령 표면이 있습니다.

- `python -m fdai`는 headless control-plane 프로세스를 시작합니다.
- `cli/` 패키지는 읽기 전용 운영자 콘솔입니다.
- `fdaictl`은 배포를 관리합니다.

이 표면을 분리하면 운영자 콘솔이 배포 자격 증명을 획득하거나 실행
표면이 되는 것을 방지할 수 있습니다.

## 목표 운영자 경험

계획된 영구 설치 방식은 다음과 같습니다.

```bash
uv tool install fdai==<version>
fdaictl version
fdaictl doctor
```

출처 체크아웃에서는 `uv run fdaictl`을 사용합니다. 게시된 휠은 위의 pinned 설치를
사용합니다.

일회성 실행 또는 CI 작업에는 임시 환경을 사용합니다.

```bash
uvx --from fdai==<version> fdaictl deploy preflight --environment dev
```

`uv`를 사용할 수 없으면 `pipx`를 사용하거나 virtual 환경 안에서 `pip`로 설치합니다.
Installer는 system 도구를 변경하지 않습니다. `fdaictl doctor`가 누락되거나 호환되지 않는
도구를 보고합니다.

> `version`, `doctor`, `onboard init`, guarded `onboard guided`, portable `backup create` 및
> `backup restore`, `deploy preflight`, plan-only `deploy plan` 전달은 구현되었습니다.
> 정제된 계획 메타데이터 상태는 `deploy status`로 조회할 수 있고 guarded exact-plan
> 제출은 `deploy apply`로 사용할 수 있습니다. `release upgrade|rollback`,
> `extension validate`, `trajectory validate`도 구현됐고 정리는 아직 사용 불가입니다.

## 명령 모델

명령은 diagnosis, onboarding, 배포, 상태를 중심으로 구성됩니다. 변경으로 이어질
수 있는 모든 명령은 원격 실행 경계를 명확하게 표시합니다.

| 명령 | 목적 | Azure 변경 |
|------|------|----------------|
| `fdaictl version` | CLI, 번들, 스키마, 호환성 버전 표시 | 없음 |
| `fdaictl doctor` | Python, Azure CLI, Terraform, GitHub CLI, 인증, 로컬 구성 검사 | 없음 |
| `fdaictl provision inspect` | Online/offline, signed-kit trust, 기존/managed 호스트, 전송 계층, 접근, workload-identity 준비 상태 검사 | 없음 |
| `fdaictl provision plan` | 검증된 offline 키트 의 pinned Terraform 바이너리와 프로바이더 mirror 로 앱 계층 를 계획 | 없음 |
| `fdaictl onboard init` | 스키마로 검증한, untracked 환경 구성 생성 | 없음 |
| `fdaictl onboard guided` | Doctor, 비공개 구성 생성, 실제 운영 preflight, plan-only 실행기 제출, 정제된 상태 post-check를 순서대로 실행 | 없음 |
| `fdaictl security audit` | 런타임 플래그 조합, 로컬 구성 hygiene, 요청된 샌드박스 가용성 검사 | 없음, `--fix-permissions`를 명시한 경우 제외 |
| `fdaictl bundle verify` | 번들 서명, 호환성, 파일 집합, 다이제스트, SBOM, 크기 검사 | 없음 |
| `fdaictl backup create` | 검증된 구성, 참조, 감사 메타데이터, user 맥락으로 비공개 portable 보관 생성 | 없음 |
| `fdaictl backup restore` | Portable 보관을 검증하고 새로운 로컬 디렉터리에 atomic 복원 | 없음 |
| `fdaictl deploy preflight` | Static 및 실제 운영 읽기 전용 배포 차단 요인 수집 | 없음 |
| `fdaictl deploy plan` | 승인된 실행기에 plan-only 작업 흐름 제출 | 없음 |
| `fdaictl deploy apply --plan-id <id>` | 정확히 승인된 계획을 원격 적용에 제출 | 있음, 실행기에서 실행 |
| `fdaictl deploy status` | 정제된 계획 다이제스트, 만료, 상태, 작업 흐름 URL 조회 | 없음 |
| `fdaictl deploy teardown` | 보호된 환경 정리 작업 흐름 제출 | 있음, 실행기에서 실행 |
| `fdaictl release upgrade` / `rollback` | 서명된 번들 활성 포인터를 검증 후 atomic 전환 | 없음 |
| `fdaictl extension validate` | 확장 매니페스트/보관 호환성 및 security offline 검사 | 없음 |
| `fdaictl trajectory validate` | 통제된 trajectory 데이터셋 체크섬/스키마/순서/출처 대응 검사 | 없음 |
| `fdaictl license inspect` | 기능 license 토큰을 packaged 공개 키로 검증하고 권한 상태 보고 | 없음 |

C1 명령은 자동화를 위해 안정적인 JSON 스키마를 사용합니다. `onboard init`은 활성 구독
및 테넌트 식별자, 환경, 지역, remote-runner 경계, shadow-mode 기본값만 gitignored
mode-`0600` 파일에 기록합니다. 사람용 출력에는 계정 식별자가 표시되지 않습니다.

`license inspect`는 번들 및 키트 검증과 같은 의미에서 오프라인입니다. 공개 키가 분포와
함께 배포되므로 네트워크 호출, 철회 조회, 인증서 체인이 관여하지 않습니다. 상태와 비밀이
아닌 메타데이터만 보고하며 토큰, 문서, 서명을 절대 출력하지 않습니다. 권한 계약
자체는 [capability-licensing-ko.md](../fork-and-sequencing/capability-licensing-ko.md)에 있습니다.

## 로컬 security 감사

`fdaictl security audit`은 프로세스 시작 전에 high-risk 로컬 및 런타임 조합을 검사합니다.
환경 값 또는 구성 내용을 출력하지 않고 고정된 검사 id를 보고합니다.
현재 검사는 다음 항목을 포함합니다.

- staging 또는 운영에서 활성화된 개발 authentication bypass.
- 개발 외 환경에서 누락된 Entra 검증기 구성.
- 필수 통제된 런타임 맥락 없이 활성화된 VM-task 또는 chaos 적용.
- bubblewrap 명령 샌드박스를 요청했지만 binary를 사용할 수 없는 상태.
- Symbolic 링크이거나 그룹/세계 권한이 있거나 parse할 수 없거나 secret-like 필드 이름이
  있는 배포 구성.

자동화에서는 `--output json`을 사용합니다. 수정되지 않은 critical 발견 사항이 있으면 exit `3`,
critical 발견 사항이 없으면 exit `0`을 반환합니다. `--fix-permissions`는 의도적으로 범위가
좁습니다. Regular 로컬 구성 파일을 모드 `0600`, 디렉터리를 `0700`으로 설정할 수 있습니다.
Symlink를 따라가거나 구성 내용을 편집하거나 feature를 비활성화하거나 자격 증명을
rotate하거나 cloud 리소스를 변경하지 않습니다.

이 감사는 배포 preflight, OPA 정책 evaluation, 시크릿 검사, Entra 접근 검토,
risk 게이트를 대체하지 않습니다. 로컬 구성 표류를 일찍 찾고 이후 권위 있는
컨트롤이 배포 및 런타임 결정을 수행합니다.

## Portable 백업 및 복원

Workstation 또는 installation을 변경한 뒤 필요한 operator-owned 배포 메타데이터를
이동하려면 `fdaictl backup create`를 사용하세요. 이 명령은 검증된 JSON 입력 4개를 읽고
결정론적인 mode-`0600` 보관을 생성합니다.

- **구성:** 스키마로 검증한 환경, remote-runner 경계, shadow-mode 기본값을
  포함합니다.
- **참조:** Opaque 시크릿, 문서, 정책, 작업 흐름, 채널, 번들 참조를
  포함합니다. 시크릿 참조는 프로바이더 항목의 이름만 가리키며 시크릿 값을 포함하지
  않습니다.
- **감사 메타데이터:** 출처 스키마, 기록 개수, last 순서, 감사 hash-chain 헤드를
  포함합니다. 감사 항목 본문은 내보내기하지 않습니다.
- **User 맥락:** 로케일, verbosity, `chart`를 포함한 답변 상세 및 format 선호 설정,
  표준 시간대, learner-sharing 선호 설정, 명시적 consent를 받은 기억 기록을 포함합니다.
  대화 대화 기록과 생성된 briefing 본문은 이 보관 format에 포함하지 않습니다.

예시:

```bash
fdaictl backup create \
  --config .fdai/environments/dev.json \
  --references .fdai/portable/references.json \
  --audit-metadata .fdai/portable/audit-metadata.json \
  --user-context .fdai/portable/user-context.json \
  --archive fdai-dev.fdai-backup

fdaictl backup restore \
  --archive fdai-dev.fdai-backup \
  --destination .fdai/restored/dev
```

보관에는 정확히 4개의 허용 목록 파일과 SHA-256 매니페스트만 포함됩니다. 생성 단계에서는
알 수 없는 스키마 필드, credential-shaped 값, private-key 자료, Terraform 상태 표시,
symbolic 링크, 크기 제한을 넘는 입력을 차단하며 `--force`를 명시하지 않은 accidental
overwrite도 차단합니다. 시크릿 프로바이더 또는 Terraform 상태 파일을 읽지 않습니다.

복원은 같은 fixed 구성원 집합과 stored ZIP format만 허용하고 파일을 게시하기 전에 모든
스키마와 다이제스트를 검증하며 기존 대상을 거부합니다. 대상은 디렉터리 모드 `0700`,
파일 모드 `0600`으로 한 번의 atomic 이름 변경을 통해 나타나므로 검증 실패 시 부분 restored
상태가 남지 않습니다. 두 명령은 local-only이며 Azure 또는 Terraform 호출을 수행하지 않습니다.

## Guided 배포 onboarding

기존의 안전한 배포 단계를 하나의 실패 시 차단 순서로 실행하려면 `fdaictl onboard
guided`를 사용하세요. 이 명령은 plan-only wizard입니다. 적용 옵션을 노출하지 않으며 로컬에서
Terraform을 실행하지 않습니다.

순서는 다음 순서로 고정됩니다.

1. **Toolchain doctor:** 구성을 기록하기 전에 Python, Azure CLI, Terraform, GitHub CLI,
  interactive Azure authentication을 검증합니다.
2. **비공개 구성:** 스키마로 검증한 mode-`0600` 환경 파일을 생성합니다. 기존
  파일이 있으면 `--force-config`를 명시하지 않는 한 실행을 차단합니다.
3. **대상 doctor:** 새 파일로 doctor를 다시 실행하고 실행기 호출 전에 활성 테넌트 또는
  구독 mismatch를 차단합니다.
4. **실제 운영 preflight:** Static 및 구성된 읽기 전용 Azure 탐색을 실행합니다. 선택적
  `--terraform-plan` 파일은 리소스 타입을 얻기 위해 parse하지만 wizard가 `terraform plan`을
  실행하지 않습니다.
5. **Plan-only 제출:** 기존 opaque 맥락 계약을 통해 `apply=false`로 approved 실행기
  작업 흐름을 전달합니다.
6. **Post-check:** 일시적으로 누락된 계획 메타데이터만 최대 60초 동안 poll합니다. 정제된 상태가
  `planning` 또는 `ready`일 때만 계속하고 다른 모든 상태는 실패 시 차단 처리합니다.

예시:

```bash
fdaictl onboard guided \
  --environment dev \
  --region koreacentral \
  --config .fdai/environments/dev.json \
  --preflight-input .fdai/preflight/dev.json \
  --repository <owner>/<repository> \
  --bundle-digest <sha256> \
  --commit-sha <git-sha> \
  --output json
```

GitHub installation 토큰은 `FDAI_GITHUB_TOKEN`에 유지하며 명령 인자로 전달하지 않습니다.
머신 출력은 대상 식별자 또는 자격 증명 값 없이 완료된 단계 id, 계획 id, 상태,
작업 흐름 URL을 보고합니다. 실패 시 실패한 단계와 정제된 사유만 보고합니다. 이전 단계가
실패하면 이후 단계를 호출하지 않으므로 doctor 또는 preflight 차단 요인이 실행기 제출에
도달할 수 없습니다.

초기 구현은 임의의 Terraform 인자를 노출하지 않는 것이 좋습니다. 지원되는 환경과
feature 설정은 검증된 구성 스키마에서 가져옵니다. 향후 명시적인 escape hatch가
추가된다면 감사되어야 하며 명령 줄에서 시크릿 값을 받지 않아야 합니다.

## Preflight 계약

`fdaictl deploy preflight`는 기존 `PreflightAnalyzer`의 읽기 전용 조립 루트입니다.
CLI 안에 두 번째 준비 상태 룰 집합을 구현하지 않고 공유 보고 및 탐색 계약을 재사용하는
것이 좋습니다.

구현된 static 경로는 배포의 neutral 범위, 리소스 타입, 필요한 egress 호스트, 근거에 기반한
정책 사실을 포함하는 versioned JSON 입력을 받습니다. 결정론적 로컬 탐색만 실행하고
네트워크 호출을 수행하지 않으며 analyzer의 고정된 정렬과 shadow-versus-enforce 의미를
유지합니다. 기계가 읽는 `terraform show -json` 출력은 `--terraform-plan`으로 전달합니다.
입력의 명시적 `terraform_resource_type_map`은 `create` 액션이 있는 managed 리소스만
replacement를 포함해 CSP-neutral 타입으로 변환합니다. 데이터 출처, no-op, 읽기, update-only,
delete-only 변경과 `terraform_data` 같은 Terraform built-in 메타데이터는 제외합니다. 대응되지
않은 created 프로바이더 리소스가 있으면 실행은 불완전한이 되며 리소스 주소 또는 planned
값은 보고에 들어가지 않습니다.

범위가 제한된 실제 운영 Azure 검사를 추가하려면 `--environment-config`를 전달합니다. CLI는 검증된
onboarding 대상을 읽고 로컬 Azure CLI 신원을 통해 수명이 짧은 ARM 토큰을 얻은 다음,
범위가 제한된 읽기 전용 ARM 및 Resource Graph 전송 계층으로 Azure Policy, 구성된 Compute 할당량,
실행기 RBAC 탐색을 실행합니다. ARM GET 요청은 20초 및 8 페이지로 제한되고 역할 조회는
20초 읽기 전용 ARG 게시입니다. Neutral 리소스 타입은 Azure 어댑터 안에서 ARM 타입으로
변환됩니다. 대응되지 않은 타입 또는 실패한 탐색은 실행을 불완전한으로 만들며 CLI 오류는
구독, 리소스 그룹, principal, 역할 정의, Azure 경로를 노출하지 않습니다.
선택적 `key_vault` 블록은 streamed GET을 열고 상태 코드만 확인해 필수 시크릿 참조를
검사합니다. 응답 본문 또는 시크릿 값은 읽지 않습니다. 누락된 참조는 SHA-256에서
파생한 id를 사용하므로 금고 호스트와 시크릿 이름이 보고에 들어가지 않습니다. 보고는 발견 사항이
없을 때도 고정된 `checks` array를 포함합니다. 각 항목은 탐색 category, `clear` 또는 `finding`
상태, 발견 사항 개수만 기록하므로 자동화가 성공한 검사와 구성되지 않은 검사를 구분할 수
있습니다. 실제 운영 프로파일은 `required_categories`를 선언할 수 있으며 할당량, 신원, 시크릿 구성이
누락되면 네트워크 호출 전에 실패합니다. 범위가 제한된 실행기 TLS 도달 가능성이 실제 운영 egress 근거를
제공합니다. Static Firewall, NSG, UDR 토폴로지 분석은 별도 future 어댑터로 남습니다.

```bash
terraform -chdir=infra show -json dev.plan > dev.plan.json
fdaictl deploy preflight \
  --input preflight-input.json \
  --terraform-plan dev.plan.json \
  --environment-config .fdai/environments/dev.json \
  --output json
```

### 단계

명령은 다음 단계를 순서대로 실행합니다.

1. **Toolchain 및 산출물 검사:** 지원 버전, 잠금 파일, CLI-to-bundle 호환성,
   체크섬, 서명, 선택된 환경을 확인합니다.
2. **신원 및 대상 검사:** 활성 Azure 구독, deployer 역할 배정, 프로바이더
   등록, 대상 지역, 실행기 신원을 확인합니다.
3. **Static infrastructure 검사:** 제공된 `terraform show -json` 계획을 검증합니다. 실제
  fmt/init/validate/계획 생성은 approved 실행기의 `deploy plan` 작업 흐름이 소유합니다.
4. **범위가 제한된 실제 운영 검사:** 읽기 전용 어댑터를 통해 Azure Policy, Resource Graph, 할당량, 네트워크
   구성, 필요한 시크릿의 존재 여부를 조회합니다.
5. **준비 상태 결정:** 하나의 근거에 기반한 보고를 만들고, 각 발견 사항이 강제 적용 상태인지 아직
   shadow 모드인지 기록하고, 다음 안전한 작업을 출력합니다.

실패하거나 생략된 탐색은 `clear` 결과를 만들지 않습니다. 보고는 실행을 불완전한으로
표시하고 고객 값이나 자격 증명을 노출하지 않고 실패한 탐색 이름을 제공합니다.

### 발견된 문제 category

CLI는 배포 preflight에 이미 정의된 category를 표시합니다.

- **Policy guardrail:** 거부된 리소스 타입, 필수 네트워크 컨트롤, public-access restriction.
- **Supply-chain egress:** 승인된 mirror가 필요한 패키지, 이미지, operating-system 저장소.
- **신원 및 RBAC:** 의도한 범위에 누락된 deployer 또는 실행기 권한.
- **할당량 및 용량:** 지역, SKU, 서비스 할당량 차단 요인.
- **의존성 정렬:** 선행 조건 배포 단계가 필요한 리소스.
- **시크릿 구성:** 시크릿 값을 읽거나 출력하지 않는 누락된 참조 또는 도달할 수
  없는 시크릿 프로바이더.

### 출력 및 exit 코드

사람용 출력은 간결한 표입니다. 자동화는 display 텍스트와 독립적으로 versioning되는 스키마를
사용하는 `--output json`을 사용합니다. Localized display 문자열은 필드 이름, 판정, 근거
식별자 또는 exit 코드를 변경하지 않습니다.

| Exit 코드 | 의미 |
|-----------|------|
| `0` | 실행이 완료되고 검토 또는 enforced 차단 요인이 남아 있지 않음 |
| `2` | Shadow-mode 탐색이 보고한 차단 요인을 포함하여 검토 필요 |
| `3` | Enforce-mode 차단 요인이 계획 또는 적용을 차단함 |
| `4` | 필수 탐색 또는 의존성 실패로 실행이 불완전한 상태임 |
| `64` | Command 사용량 또는 환경 구성이 올바르지 않음 |

보고의 실제 판정은 발견 사항이 현재 deploy를 차단하는지와 분리됩니다. 예를 들어
shadow-mode 탐색은 `blocked`를 보고하면서 적용용 `3` 대신 검토용 `2`로 프로세스를
종료할 수 있습니다.

Protected 원격 계획에서 비공개 실행기는 non-secret GitHub Variable
`DEPLOY_PREFLIGHT_INPUT_JSON`을 요구합니다. `azure_live.required_categories`에는
`policy_guardrail`, `quota_capacity`, `identity_rbac`, `secret_config`가 모두 있어야 하며 대응하는
resource-type 지도, 할당량 검사, principal/역할 참조, Key Vault 메타데이터 참조를 제공합니다.
작업 흐름은 모드를 `enforce`로 덮고 현재 시각을 설정하며 보고 범위를 neutral 값으로
교체합니다. Locked CLI를 설치하고 exact binary 계획을 JSON으로 변환한 뒤 네 읽기 전용 실제 운영
category를 모두 실행합니다. 완전한 검사 커버리지가 있는 `clear` 보고만 수락합니다. 계획
JSON, 환경 식별자, 입력 프로파일은 단계 종료 시 제거됩니다.

`deploy_operator_api`를 사용하면 non-secret `STEWARDSHIP_MAINTAINERS`와
`STEWARDSHIP_AGENT_BINDINGS_JSON` 저장소 Variable을 설정합니다. 후자는 Loki를 제외한 모든
non-autonomous Pantheon 에이전트를 하나 이상의 `user:<oid>` 또는 `group:<oid>` 토큰에 매핑합니다.
Loki는 명시적 자율 acceptance를 유지할 수 있습니다. 작업 흐름은 Entra 디렉터리 프로바이더와
이 값을 Terraform에 연결합니다. Resource precondition은 빈 관리자 또는 누락된 에이전트 연결을
broken Operator API 개정 번호 생성 전에 거부합니다.

정제된 보고만 protected 계획 옆에 저장됩니다. 메타데이터는 runner-egress 근거와 Azure 실제 운영
근거의 SHA-256 다이제스트를 별도로 연결합니다. Exact 적용은 점유 또는 Terraform 실행 전에
두 original 파일을 내려받아 다이제스트를 다시 계산합니다. Binary 계획 다이제스트가 일치해도 근거
파일 중 하나가 변경되면 적용이 차단됩니다.

## 읽기 전용 preflight와 초기화 발견

기본 preflight는 Azure 리소스를 생성하지 않습니다. 일부 테넌트 정책 발견은 정책
결과를 관찰하기 위해 throwaway 리소스가 필요합니다. 이 작업은 별도의 명시적 명령으로
유지합니다.

```bash
fdaictl bootstrap probe-policy --allow-probe-resources
```

이 초기화 변경 명령은 **계획됨**이며 현재 CLI 파서에 등록되지 않았습니다. 지금은
`infra/bootstrap/preflight-policy-check.sh`를 명시적으로 실행합니다.

이 명령은 실행 전에 리소스 범위, 정리 행동, stop 조건, 예상 비용을 표시하는 것이
좋습니다. 이 명령은 `fdaictl deploy preflight`의 일부가 아니며 preflight가 암시적으로 호출하지
않습니다.

## 배포 산출물 모델

런타임은 이제 5개 서비스 휠과 versioned service-contract SDK로 제공됩니다. 이 런타임
분포에는 계획된 `fdaictl` 배포 명령이 포함되지 않습니다. 배포에는 Terraform
모듈, 정책, 스키마, 선택된 rule-catalog 데이터도 필요합니다. 변경 가능한 모든 infrastructure
파일을 가져오기 가능한 Python 리소스로 packaging하면 버전 alignment와 점검이
어려워집니다. 대신 전용 CLI 휠과 버전이 일치하는 배포 번들을 사용합니다.

### 계획된 배포 CLI 휠

전용 휠에는 다음이 포함될 예정입니다.

- `fdaictl` 항목 지점과 명령 파서.
- 구성 및 출력 스키마.
- Preflight orchestration 및 보고 렌더링.
- 산출물 download 및 서명 검증.
- 작업 흐름 제출 및 상태 클라이언트.

배포 전용 통합은 모든 서비스 런타임 가져오기 경로 밖에 유지합니다. 폐기된 최상위
`fdai.deployment_cli` 패키지를 런타임 휠에 복원하지 마세요. 이 계획된 인터페이스를 구현할
때 명령 표면은 전용 lightweight CLI 분포으로만 제공합니다.

### 서명된 배포 번들

배포 번들에는 다음이 포함됩니다.

- `infra/`의 Terraform 루트 및 모듈.
- 계획 검증에 사용하는 OPA 정책.
- 필요한 rule-catalog 스키마 및 배포 프로파일.
- 버전 및 SHA-256 다이제스트를 기록하는 매니페스트.
- Software bill of materials와 release 서명.

CLI 버전 `<version>`은 기본적으로 번들 `<version>`을 확인합니다. CLI는 Terraform을 실행하기
전에 서명과 매니페스트를 검증합니다. Disconnected 환경에서는 `--bundle <path>`를
제공할 수 있지만 동일한 검증을 적용합니다. 명시적으로 문서화된 호환성 범위가
허용하지 않는 버전 mismatch는 계획 세대 전에 실패합니다.

`fdaictl bundle verify --bundle <dir> --public-key <pem>`은 검증 측을 구현합니다.
Ed25519 공개 키만 받고 detached 매니페스트 서명을 검증하고 현재 CLI와 매니페스트
호환성 범위를 비교하고 탐색 및 symlink를 차단합니다. 정확히 listed 파일 집합 및
listed JSON SBOM을 요구하고 모든 SHA-256 검사를 스트리밍하며 total-size 상한을 적용합니다.
Signing-key 또는 bundle-building 코드는 포함하지 않습니다.

`scripts/deployment/release/build-deployment-bundle.py`는 release-only 빌드 측을 구현합니다. `infra/`, `policies/`,
`rule-catalog/schema/`, `rule-catalog/profiles/`, `rule-catalog/risk-classification.yaml` 아래 tracked
파일만 찾습니다. 계획, tfvars, tfstate, PEM/키, symlink, untracked, outside-root 경로는 차단합니다.
파일 모드, mtime, tar 소유자/그룹, gzip 시각, 정렬을 normalize하고 결정론적 CycloneDX
파일 SBOM과 정본 매니페스트를 생성한 다음 외부 Ed25519 비공개 키로 서명합니다. 비공개
키는 번들에 들어가지 않습니다.

각 매니페스트는 `stable`, `beta`, `development` 중 하나의 release 채널도 서명합니다. release
작업 흐름은 채널을 명시적 choice로 요구하고 두 reproducibility 빌드에 전달합니다. 따라서
서명 후 채널을 변경하면 서명이 무효화됩니다. 번들 검증은 버전 및 매니페스트
다이제스트와 함께 signed 채널을 반환합니다.

Approval-gated `release-deployment-bundle` 작업 흐름은 `release` GitHub 환경의
`FDAI_BUNDLE_SIGNING_KEY_PEM`을 읽고 동일 커밋 및 `SOURCE_DATE_EPOCH`에서 두 번 빌드합니다.
두 디렉터리, 보관, 공개 키를 byte-for-byte 비교하고 `fdaictl bundle verify`를 실행한 뒤
보관, 공개 키, 매니페스트, 서명, 체크섬을 30일 Actions 산출물로 게시합니다.
`publish_release=true`는 GitHub release를 생성하는 별도 명시적 게이트입니다. Temporary 비공개
키는 mode-restricted 상태로 사용하고 셸 trap으로 제거합니다.

`release` 환경이 서명 키를 노출하기 전에 exact clean 체크아웃에서 두 독립적인
작업이 통과해야 합니다. 검증 작업은 locked Python 및 콘솔 의존성을 설치하고
disposable pgvector PostgreSQL 서비스를 시작해 single Alembic 헤드로 업그레이드합니다. 이어서 실제 운영
통합 테스트를 포함한 `scripts/verify.sh --all`과 productization, 콘솔, 휠 빌드,
isolated CLI 검사를 실행합니다. 마지막 `git diff --exit-code`는 generator가 tracked 출처를
다시 쓰는 경우를 차단합니다. Dependency-audit 작업은 pinned Python vulnerability scanner를
실행합니다. 번들 작업은 두 작업을 `needs`로 선언하고 pinned Ubuntu 실행기 이미지를 사용하며,
이 작업만 `contents: write`를 받습니다. 검증 및 감사 작업은 읽기 전용으로 유지됩니다.

## release 채널, 업그레이드 및 롤백

더 새로운 signed 번들 개정 번호를 활성화하려면 `fdaictl release upgrade`를 사용합니다. 로컬
환경 구성, release-state 경로, 번들 디렉터리, trusted 공개 키, 예상 채널을
전달합니다. Command는 상태를 쓰기 전에 서명, 파일 다이제스트, CLI 호환성 범위, signed
채널을 검증합니다. 업그레이드는 더 새로운 의미 버전만 수락합니다. 이전 버전에는
롤백을 사용합니다.

```bash
fdaictl release upgrade \
  --state .fdai/release-state.json \
  --config .fdai/environments/dev.json \
  --bundle <verified-bundle-directory> \
  --public-key <trusted-public-key.pem> \
  --channel stable \
  --output json
```

release 상태는 활성 버전, signed 채널, 매니페스트 다이제스트, 최대 20개 범위가 제한된 이력, 현재
구성의 SHA-256 다이제스트만 포함하는 atomic mode-`0600` JSON 포인터입니다. 구성 내용, 시크릿
값, Terraform 상태, binary 계획, 호스트 경로는 저장하지 않습니다. CLI는 temporary 상태 파일을
쓰고 구성 다이제스트를 다시 검사한 다음 활성 포인터를 교체합니다. 구성 자체는 다시 쓰지
않습니다.

Exact 이전 signed 번들과 함께 `fdaictl release rollback`을 사용합니다. 후보는 full 번들
검증 후 newest 이력 항목과 버전, 채널, 매니페스트 다이제스트가 일치해야 합니다. 다른
번들, tampered 번들, incompatible 번들 또는 단순히 더 오래된 번들은 상태 변경 전에
차단됩니다.

```bash
fdaictl release rollback \
  --state .fdai/release-state.json \
  --config .fdai/environments/dev.json \
  --bundle <prior-verified-bundle-directory> \
  --public-key <trusted-public-key.pem> \
  --output json
```

## 계획 및 적용 무결성

`fdaictl deploy plan`은 plan-only 작업 흐름을 제출하고 현재 작업 흐름 실행 id와 URL을 반환합니다.
같은 환경 구성이 `doctor`를 통과해야 하고 GitHub 자격 증명은
`FDAI_GITHUB_TOKEN`에서만 읽습니다. 전달 본문에는 `apply=false`, 환경, exact 커밋,
SHA-256 deployment-context 지문을 전달합니다. Console, design mocks, Operator API,
개발 게이트웨이, document-ingestion 플래그는 지문에 포함되며 계획과 적용에 동일하게
전달됩니다. 플래그가 달라지면 계획은 무효입니다. 테넌트, 구독, 백엔드, 실행기
식별자는 전달하지 않습니다. 작업 흐름은 계획 전에 범위가 제한된 요청 id, 맥락 다이제스트,
exact checked-out 커밋을 검증합니다.

`--deploy-design-mocks`는 dev 전용의 단독 대상입니다. 다른 배포 feature 플래그와 함께
사용할 수 없습니다. 실행기는 `module.design_mocks`만 대상으로 하며, design-mocks Static Web
App 외부의 리소스 변경이 계획에 포함되면 차단합니다.

```bash
FDAI_GITHUB_TOKEN=<installation-token> fdaictl deploy plan \
  --config .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --bundle-digest <sha256> \
  --commit-sha <git-sha> \
  --deploy-design-mocks \
  --output json
```

Terraform 계획 파일에는 상태에서 파생된 민감한 값이 포함될 수 있으므로 로컬 CLI는 binary
Terraform 계획을 download하거나 출력하지 않습니다. 실행기는 CLI-requested 계획과 정제된
메타데이터를 비공개 remote-state 컨테이너 옆의 `deployment-plans` Blob 컨테이너에 저장합니다.
업로드는 실행기 managed 신원을 사용하고 공개 접근은 off이며 `overwrite=false`가 각 실행
경로를 변경할 수 없는하게 유지합니다. 메타데이터는 테넌트, 구독, 백엔드, 실행기, 시크릿 값
없이 계획 다이제스트, 맥락 다이제스트, exact 커밋, 작업 흐름 실행, 1시간 logical 만료를 기록합니다.
Isolated 실행기 계획은 레지스트리 엔드포인트 또는 변경 가능한 tag 없이 검증된 런타임 출처 개정 번호와
OCI 다이제스트도 기록합니다. `deploy plan`은 derived 계획 id를 반환하고 `deploy 상태 --plan-id
<id>`는 해당 선택적 런타임 이미지 근거를 포함한 범위가 제한된 metadata-only 산출물을 읽습니다.
각 새 계획 실행은 비공개 블롭을 최대 1001개 검사하고 24시간
지난 허용 목록에 있는 계획 경로를 최대 1000개 삭제합니다. 두 한계 중 하나에 도달하면 알 수 없음
경로를 삭제하지 않고 실패 시 차단합니다.

`fdaictl deploy apply --plan-id <id>`는 다음 검사를 모두 통과한 경우에만 정확히 저장된 계획을
적용합니다.

- 계획이 동일한 구독, 환경, 번들 다이제스트, 커밋에 대해 생성됨.
- 계획이 만료되지 않았고 이미 적용되지 않음.
- Preflight 보고에 enforce-mode 차단 요인이 없음.
- 호출자가 적용을 명시적으로 요청했고 작업 흐름 승인 정책을 충족함.
- 실행기 신원과 백엔드 구성이 기록된 계획 맥락과 일치함.

CLI는 `doctor`를 다시 실행하고 범위가 제한된 메타데이터를 조회해 맥락 다이제스트와 logical 만료를
검증하며 stored 계획 다이제스트만 전달합니다. 적용 작업 흐름은 대상 GitHub 환경을 외부
승인 및 감사 이력 경계로 사용합니다. `terraform plan`을 건너뛰고 비공개 Blob 저장소의
exact binary와 메타데이터를 복원해 모든 다이제스트, id, 상태, 시각, 커밋을 검증한 다음
`terraform apply` 전에 변경할 수 없는 `apply-claim.json`을 생성합니다. 중복 또는 실패한 이전
점유는 automatic 재시도를 차단합니다. 성공한 실행은 변경할 수 없는 `apply-receipt.json`을 기록하며
`deploy status`는 점유에서 `applying`, 증적에서 `applied`를 투영합니다.

Terraform 적용 성공 뒤 신원, 이행, 상태 또는 canary 검사가 실패하면 동일 명령에
`--resume-verification`을 추가합니다. 재개는 exact 계획이 `applying`으로 표시되어야 하며
기존 점유와 증적 부재를 검증하고 Terraform 적용을 건너뛰며 convergence와 post-apply
검사를 다시 수행한 뒤 증적을 기록합니다. 맥락 변경, 누락된 점유, 기존 증적은
재개를 차단합니다. Targeted 계획이 콘솔 hostname 출력을 비워 두면 Entra sync는 Terraform
상태의 exact Static Web App id를 사용해 Azure 관리 평면에서 hostname을 읽습니다.

Post-apply 이행은 같은 작업 흐름 문서가 서로 다른 action-catalog 다이제스트를 pin할 때 변경할 수 없는
built-in 작업 흐름 정의가 coexist하도록 허용합니다. Unique 데이터베이스 신원은 작업 흐름 이름,
작업 흐름 버전, 정의 해시, action-catalog 다이제스트를 포함합니다. 이전 정의를 덮어쓰지
않으면서 카탈로그 release 간 시작 멱등성을 유지합니다.

```bash
FDAI_GITHUB_TOKEN=<installation-token> fdaictl deploy apply \
  --config .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --plan-id <plan-id> \
  --bundle-digest <sha256> \
  --commit-sha <git-sha> \
  --output json
```

보호된 작업 흐름 저장소는 각 계획을 1시간 후 logical 만료된으로 표시합니다. 로그에는 계획 id,
다이제스트, 만료만 노출합니다. 계획 파일, 상태, 자격 증명 또는 시크릿 값은 노출하지 않습니다.
Physical 정리가 아직 블롭을 제거하지 않았더라도 적용은 logical 만료를 차단해야 합니다.

Transport-neutral 기반은 `fdai.deployment_cli.remote`에 구현되었습니다. `PlanRecord`는 opaque
메타데이터만 포함하며 `RemoteDeploymentService`는 적용 전에 이를 다시 부하합니다. 로컬 가드는
`ready` 상태, 유효한 보존, 정확한 테넌트/구독/환경/번들/커밋/백엔드/
실행기 맥락, clear enforced preflight, approved 실행기 가용성을 요구합니다. 이후
caller-supplied replacement가 아니라 workflow-owned stored 다이제스트를 제출합니다. 구체적인 GitHub
plan-only 전송 계층은 현재 전달 실행 상세를 반환하고 실행기는 protected binary 계획과
메타데이터를 기록하며 CLI는 범위가 제한된 run-scoped zip에서 정제된 상태를 조회합니다. Exact-plan
적용 전송 계층, GitHub 환경 승인 경계, 변경할 수 없는 점유, 감사 증적이 구현되어
있습니다. 실행기 egress preflight 근거는 변경할 수 없는 계획 메타데이터에 고정되고 post-apply
검사는 증적 기록 전에 Terraform convergence, 이행 성공, 활성화된 엔드포인트 상태를
요구합니다. Runner-side Policy, 할당량, 신원, 시크릿, egress 근거는 C4 exact-plan 게이트의
필수 입력입니다.

## Private-everything 테넌트

로컬 명령은 적용 경계를 laptop으로 옮기지 않습니다. 테넌트가 Key Vault, 상태 저장소
또는 다른 데이터 서비스를 비공개로 설정하는 경우 계획과 적용 모두 VNet-integrated 자체 호스팅
실행기에서 실행됩니다. 로컬 CLI는 management-plane 읽기를 사용하여 실행기 경로가 필요한지
판단하고, 승인된 작업 흐름을 시작하거나 찾고, 상태를 보고합니다.

실행기는 managed 신원을 계속 사용합니다. `fdaictl`은 service-principal 시크릿, Terraform
상태, 생성된 데이터베이스 password 또는 Key Vault 값을 로컬 머신으로 복사하지 않습니다.
실행기를 사용할 수 없으면 CLI는 로컬 적용으로 대체 경로하지 않고 차단 요인을 보고합니다.

## 구성 및 시크릿 처리

환경 구성은 스키마 검증을 거치며 패키지 외부에 저장됩니다. 생성된
구성은 기본적으로 untracked 상태이며 시크릿 값 대신 참조를 포함합니다.

- **허용:** 환경 이름, 지역, feature 플래그, 백엔드 참조, 저장소 이름, approved
  산출물 출처.
- **허용되지 않음:** Password, 접근 토큰, 연결 문자열, Terraform 상태, binary 계획,
  업스트림 저장소의 populated customer 구성.
- **Command 이력:** 시크릿 값을 command-line 인자로 받지 않습니다.
- **로그:** 구조화된 로그는 상관관계 ID를 포함하며 구성된 민감한 필드를 redact합니다.
- **머신 출력:** JSON은 안정적인 영어 필드 이름을 사용하며 시크릿 자료를 포함하지
  않습니다.

사용자가 보는 CLI 텍스트는 L2 product 표면입니다. 영어 출처 메시지는 메시지 카탈로그에,
한국어 translation은 일치하는 로케일 카탈로그에 보관하며 누락된 translation은 영어로
대체 경로합니다. 로그, JSON 필드, 판정, 근거는 영어 전용 머신 표면으로 유지됩니다.

## 제공 순서

원격 적용을 노출하기 전에 읽기 전용 경계를 검증할 수 있도록 CLI를 작은 increment로
제공합니다.

| Increment | 상태 | 범위 | 종료 기준 |
|-----------|------|------|-----------|
| C1: 패키지, doctor 및 로컬 security | 구현됨 | Console 항목 지점, 버전 출력, toolchain 및 auth 진단, 로컬 onboarding 구성, 로컬 security 감사 | 출처 install이 결정론적 텍스트 및 JSON을 생성하고 대상 mismatch와 critical 로컬 자세가 식별자 또는 값을 노출하지 않고 실패 시 차단 처리됨 |
| C2: 읽기 전용 preflight | 구현됨 | Static 및 Terraform-plan analysis, 실제 운영 Policy/할당량/신원/시크릿 탐색, hash-only 근거를 사용하는 범위가 제한된 실행기 TLS egress 구현 | Mock 전송 계층이 변경 및 secret-value 읽기가 없음을 입증하고 실패한/불완전한 탐색이 clear 결과를 차단함 |
| C3: 계획 작업 흐름 | 구현됨 | Opaque 맥락 다이제스트, doctor/대상 가드, 현재 GitHub 전달 API, exact-commit 가드, 비공개 변경할 수 없는 계획 업로드, metadata-only 상태 산출물, logical 만료, 범위가 제한된 physical 정리 구현 | Plan-only가 기본이며 대상 식별자는 전달과 메타데이터에 없고 적용은 계속 사용 불가 |
| C4: 적용 작업 흐름 | 구현됨 | Exact 복원/검증기, 완전한 실행기 Policy/할당량/신원/시크릿 및 egress 근거, dual 근거 다이제스트, 가드, 승인, at-most-once 점유, 감사/상태, Terraform convergence, 이행, 상태 검사 | Stale, mismatched, evidence-tampered, claimed, applied, 만료된, non-converged, unhealthy 계획은 applied 증적을 생성할 수 없음 |
| C5: release 강화 | 부분 구현 | Ed25519 번들 검증, signed release 채널, atomic 업그레이드/롤백 상태, reproducible 번들 및 Python 분포 빌드, SBOM, GitHub release, OIDC PyPI 게시 구현, 첫 게시, 내부 mirror, disconnected 전달은 남음 | Version-matched 번들과 Python 산출물이 게시 전 검증 통과 |
| C6: Guided onboarding | 구현됨 | 순서가 고정된 doctor, 비공개 구성, 대상 가드, 실제 운영 preflight, plan-only 실행기 전달, 범위가 제한된 정제된 상태 post-check | Stage-spy 테스트가 fail-stop 순서와 guided 경로가 로컬 적용을 가져오기하거나 호출하지 않음을 입증 |

## 수락 기준

다음 기준을 테스트할 수 있으면 roadmap에서 구현으로 승격할 준비가 된 것입니다.

- Clean 호스트가 격리된 도구 명령 하나로 pinned CLI 버전을 설치할 수 있음.
- `doctor`가 작업 흐름 제출 전에 잘못된 Azure 구독을 식별함.
- `deploy preflight`가 읽기 전용이고 동일한 입력에 byte-stable JSON을 생성함.
- `onboard guided`가 첫 실패한 단계에서 중지하고 로컬 적용 경로를 노출하지 않음.
- 탐색 실패가 `clear`로 보고될 수 없음.
- Private-everything 테넌트가 항상 계획과 적용을 VNet 실행기로 라우팅함.
- 적용이 기록된 계획 다이제스트를 사용하고 stale 또는 mismatched 계획을 차단함.
- 시크릿, 상태 파일, binary 계획이 최종 출력 또는 로컬 머신에 도달하지 않음.
- CLI와 배포 번들을 이전에 서명된 버전으로 함께 롤백할 수 있음.

## 미결 질문 및 결정

- [x] 공개 패키지 인덱스 - Trusted 발행을 사용하는 PyPI이며 version-matched signed 번들은 GitHub Releases를 사용합니다.
- [x] 서명/증명 - detached Ed25519 매니페스트 서명 + 결정론적 CycloneDX
  파일 SBOM + GitHub 빌드 출처 이력/SBOM 증명.
- [x] Saved-plan 보존 - 1시간 logical 만료, 24시간 뒤 범위가 제한된 physical 정리 대상.
- `fdaictl deploy teardown`을 첫 적용 release에 포함할까요? 아니면 정리 훈련이 측정될
  때까지 별도의 guarded 스크립트로 유지할까요?

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구체적인 Azure 인벤토리 및 onboarding | [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md) |
| 배포 수명 주기 및 롤백 | [deployment-ko.md](deployment-ko.md) |
| 준비 상태 발견 사항 및 탐색 계약 | [deployment-preflight-ko.md](deployment-preflight-ko.md) |
| 차단 요인을 Terraform 토글로 전환 | [preflight-active-reassembly-ko.md](preflight-active-reassembly-ko.md) |
| 비공개 실행기 초기화 | [../../../infra/bootstrap/README.md](../../../infra/bootstrap/README.md) |
| Product localization 규칙 | [../../../.github/instructions/language.instructions.md](../../../.github/instructions/language.instructions.md) |
