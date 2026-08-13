---
title: Provisioning 실행 Profile
translation_of: provisioning-execution-profiles.md
translation_source_sha: 9f4dda7711986339fce6a1e4a6ce8a3232a99cab
translation_revised: 2026-08-14
---
# 프로비저닝 실행 프로파일

이 문서는 계획된 `fdaictl` 배포판이 프로비저닝 호스트, connectivity 모드, 명령 전송 계층, 접근 경로를
선택하는 방법을 정의합니다. 또한 Terraform이 infrastructure 또는 역할 배정을 변경하기
전에 적용되는 사람 승인과 workload-identity 경계를 정의합니다.

> **범위:** Azure가 구현된 대상입니다. 이 프로파일은 Terraform 정본을 변경하거나
> 비공개 엔드포인트를 우회하는 로컬 대체 경로를 허용하지 않습니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 읽기 전용 점검 및 프로파일 초기화 명령 | not-started | 저장소 패키지 메타데이터와 이 문서의 명령 계약 | 현재 전용 CLI 배포판이나 `fdaictl` 프로젝트 스크립트가 없습니다. |
| 관리 VM, 비공개 백엔드 및 보호된 실행기 | implemented | `infra/bootstrap/`, `.github/workflows/deploy-dev.yml` 및 집중 bootstrap/작업 흐름 테스트 | 영속 VNet 호스트, 워크로드 신원, 비공개 상태, 보호된 계획 및 exact-apply 동작은 로컬 CLI 파사드 없이 존재합니다. |
| Offline-kit 생성 및 검증 | in-progress | `scripts/deployment/release/build-offline-kit.py` 및 `stage-offline-kit.sh` | Release 스크립트는 있지만 가져오는 `fdai.deployment_cli.offline_kit` 구현이 없습니다. |
| Temporary 공개 접근 정리 | not-started | 이 문서의 접근 선호 설정 계약 | 범위가 제한된 생성, 자동 정리, 정리 실패 시 불완전 상태 및 감사 종결을 입증하는 조립 명령이 없습니다. |
| Pinned TUF 루트 및 교대 | not-started | `docs/runbooks/offline-trust-ceremony.md` | 첫 루트 의식, 패키지 리소스, 클라이언트 초기화 및 교대 근거가 남아 있습니다. |
| 배포 후 검증 | in-progress | 보호된 작업 흐름 검사 및 `docs/roadmap/operations/operating-and-verification.md` | 실행기 측 수렴, 마이그레이션, 상태 및 canary 검사는 있지만 완전한 CLI 기반 수명 주기와 폐쇄망 증적은 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 구현 원장을 도입했으며 이전 출처 이력은 재구성하지 않았습니다. 점검, 프로파일 영속성 및 offline 검증을 근거에 맞는 현재 상태로 바로잡았습니다. | 현재 변경과 구현 범위 표에 기재한 패키지 메타데이터, bootstrap 소스, release 스크립트 및 집중 작업 흐름 검사 | CLI 패키지를 만들고 offline 검증을 복원하며 trust 초기화를 완료한 뒤 전체 수명 주기를 검증해야 합니다. |

### 남은 작업

- [ ] 전용 CLI 패키지에 `provision inspect`와 `provision init`을 구현하고 무변경, mode-`0600`/`0700`, 덮어쓰기, symbolic link 및 안정적 JSON 테스트를 통과합니다.
- [ ] 주입된 release 루트 뒤에 offline-kit 검증을 복원하고 서명 우선 확인, exact 파일 집합, no-follow 다이제스트, 호환성 및 한계 테스트를 통과합니다.
- [ ] Temporary 공개 접근 생성과 정리를 구현하여 정리 실패가 감사된 불완전 작업으로 남게 하고 CIDR, 기간, 인증, 롤백 및 멱등성 테스트를 통과합니다.
- [ ] TUF 루트 의식과 패키지 초기화를 완료하고 inspect부터 plan, apply, cleanup, verification까지의 통제 증적을 보존합니다.

## 한눈에 보는 설계

프로비저닝은 네 가지 선택을 독립된 축으로 취급합니다. 명령은 먼저 근거를 평가하며,
`dev` 같은 환경 이름 또는 운영자가 휠을 설치한 머신에서 권한을 추론하지
않습니다.

| 축 | 지원 값 | 선택 규칙 |
|----|---------|-----------|
| Connectivity | `online`, `offline` | 제한된 TLS 검사를 통과한 후에만 online 출처를 사용하고, 그렇지 않으면 signed offline 키트를 요구합니다. |
| 실행 호스트 | `existing-host`, `managed-vm` | 적합한 private-network 호스트를 재사용하고, 적합한 호스트가 없으면 managed VM을 생성합니다. |
| 전송 계층 | `manual`, `github-actions` | 사람이 exact-plan 흐름을 직접 시작하거나 GitHub Actions를 통해 같은 흐름을 제출합니다. |
| 소유권 | `fdai-managed` | 승인 후 Terraform이 선언된 리소스와 역할 배정을 관리합니다. |

## 읽기 전용 검사

목표 명령은 초기화 계획을 만들기 전에 점검을 실행합니다.

```bash
fdaictl provision inspect --output json
```

점검은 로컬 Azure CLI, Terraform, GitHub CLI, 제한된 online 산출물 접근,
offline-kit 후보, Azure 워크로드 신원 엔드포인트를 검사합니다. `mutation_performed=false`,
필수 사람 승인자 한 명, 선택된 프로파일이 포함된 안정적인 JSON 계약을 반환합니다. 도구를
설치하거나 구성을 기록하거나 리소스를 생성하거나 실행기를 등록하거나 Terraform을
적용하지 않습니다.

결과는 다음 상태를 사용합니다.

| 상태 | 의미 |
|------|------|
| `ready` | 기존 호스트에 toolchain, 워크로드 신원, online 접근 또는 검증된 offline 키트가 있습니다. |
| `review` | Managed VM 또는 pinned 검증기가 없는 offline 키트에 운영자 검토가 필요합니다. |
| `incomplete` | 명시적으로 요청한 프로파일에 필수 의존성 또는 접근 경로가 없습니다. |

파일 존재만으로 trust가 성립하지 않습니다. Composition-injected pinned 검증기가 있으면 점검은
서명, 호환성, exact 파일, 다이제스트, 한계를 검사하고 non-secret 매니페스트 메타데이터만
반환합니다. Rejected 내용은 `incomplete`, 검증된 내용은 완전한 existing-host 프로파일을
`ready`로 만들 수 있습니다. 공개 루트 ceremony가 검증기를 패키지하기 전까지 목표 CLI는
offline 디렉터리를 `candidate` / `review`로 유지합니다.

## 프로파일 initialization

목표 초기화 명령은 명시적으로 결정된 값으로 검토한 프로파일을 저장합니다.

```bash
fdaictl provision init \
  --connectivity online \
  --host existing-host \
  --transport manual \
  --access-method internal_ssh
```

명령은 모든 `auto` 값을 거부하고 `.fdai/provisioning/profile.json`을 mode-`0700` 디렉터리
안에 파일 모드 `0600`으로 기록합니다. Offline 프로파일에는 `--artifact-source`가 필요합니다.
Temporary 공개 SSH에는 전체 주소 space보다 좁은 정본 출처 CIDR과 5-60분 접근
구간이 필요합니다. GitHub Actions 전송 계층에는 일치하는 `github_actions` 접근 메서드가
필요합니다.

기존 대상은 `--force`를 명시하지 않으면 initialization을 차단합니다. Force는 symbolic
링크를 따라가거나 non-file 대상을 교체하지 않습니다. 프로파일 initialization은 Azure
리소스를 변경하지 않으며 JSON 출력에 `mutation_performed=false`를 기록합니다.

## 실행 호스트

### 기존 호스트

다음 조건을 이미 갖춘 jumpbox 또는 배포 호스트에는 `existing-host`를 사용합니다.

- 필요한 모든 비공개 엔드포인트에 대한 네트워크 및 비공개 DNS 도달 가능성.
- Azure CLI와 Terraform.
- 승인된 배포 역할이 있는 별도 워크로드 신원.
- Protected Terraform 백엔드와 계획 저장소에 대한 영속 접근.

수동 실행은 운영자가 이 호스트에서 `fdaictl`을 시작한다는 의미입니다. Terraform이
운영자의 interactive Azure 신원을 사용한다는 의미가 아닙니다. 워크로드 신원이 없는
호스트는 불완전한으로 보고됩니다.

### Managed VM

Operator laptop이 비공개 네트워크 밖에 있거나, 기존 jumpbox가 적합하지 않거나, 정책이
dedicated 배포 호스트를 요구하면 `managed-vm`을 사용합니다. VM은 영속하게 유지하지만
일반적으로 deallocate합니다. Protected 상태, 계획, 승인, 감사 기록은 비공개 저장소에
남으므로 VM을 시작, 중지 또는 다시 빌드해도 배포 권한이 변경되지 않습니다.

목표 CLI는 managed VM을 권장하지만 점검 중에는 생성하지 않습니다. 초기화 계획 수립은 승인
전에 VM, 네트워크, 신원, 역할, 접근, 비용, stop, 정리 효과를 보여 줍니다.

## 접근 선호 설정

Managed-host 접근 순서는 다음과 같이 고정합니다.

1. 승인된 내부 SSH.
2. Azure Policy와 배포 프로파일이 허용하는 경우 temporary public-IP SSH.
3. 자체 호스팅 실행기의 GitHub Actions.
4. Azure Bastion.
5. 감사되는 비상 경로인 Azure Run Command.

Temporary 공개 접근은 silent 대체 경로로 사용하지 않습니다. 계획에는 허용 목록에 포함된
출처 CIDR, 키 또는 certificate만 사용하는 SSH, 제한된 접근 구간, 공개 IP와 temporary
network-security 룰의 자동 제거가 필요합니다. `0.0.0.0/0`, password authentication,
persistent 공개 IP는 허용되지 않습니다. 정리는 연산 성공 기준의 일부입니다.
정리에 실패하면 연산은 불완전한으로 남고 감사 기록이 생성됩니다.

## Online 및 offline 전달

Online 전달은 PyPI의 공개 `fdai` 패키지와 version-matched signed 배포 번들을
사용합니다. 실행기는 허용 목록 TLS 검사를 통과한 후에만 공개 출처를 사용할 수 있습니다.

목표 release 작업 흐름은 읽기 전용 작업에서 휠과 출처 분포를 한 번만 빌드하고 Python과
번들 버전이 일치하는지 검사합니다. 일치하는 signed 번들을 게시한 후에만 같은 산출물을
PyPI Trusted 발행으로 게시합니다. Publish 작업만 GitHub OIDC 권한을 받으며 장기
PyPI 토큰은 저장하지 않습니다.

공개 PyPI release 줄은 `0.1.0`에서 시작합니다. 기존 저장소 tag `v0.1.1`부터
`v0.1.12`까지는 pre-PyPI engineering 이정표이며 다시 작성하지 않습니다. 첫 공개 release는
정확한 게시 커밋에 `v0.1.0` tag를 생성합니다. `0.1.0`보다 높은 활성 pre-PyPI 번들
상태가 있는 installation은 fresh 공개 release 상태 또는 명시적 이행을 사용합니다.
`0.1.0`으로 semantic-version 업그레이드하는 것으로 처리하지 않습니다.

Disconnected 전달은 platform별 offline 키트에서 같은 `fdai` 휠과 명령 계약을
사용합니다. 키트에는 다음 항목이 포함됩니다.

- FDAI 휠과 모든 transitive Python 휠.
- Signed 배포 번들.
- Pinned Terraform binary와 프로바이더 mirror.
- OPA와 필요한 보조 로직 binary.
- SBOM, SHA-256 매니페스트, 서명, release trust 메타데이터.

Offline 모드는 PyPI, GitHub, 공개 Terraform 레지스트리 대체 경로를 차단합니다. 산출물 출처로
승인된 내부 mirror 또는 removable media를 사용할 수 있습니다. Installer와 `fdaictl`은 두
경우 모두 같은 pinned release 루트를 검증합니다.

목표 `verify_offline_kit` 구현은 매니페스트 파싱 전에 Ed25519 서명을 검사하고 exact CLI 및 platform
버전을 연결하며 symlink와 extra 파일을 거부합니다. 모든 파일 다이제스트를 스트리밍하고 휠,
signed 배포 번들, Terraform binary 및 프로바이더 mirror, OPA, SBOM을 요구합니다. release
루트 주입은 테스트, release construction, pinned 점검 조립에서만 사용합니다.
산출물 hashing은 no-follow 서술자 열림으로 경로 swap redirect를 막습니다. `fdaictl`은 `--release-root`
재정의를 제공하지 않습니다. 공개 루트가 휠에 pin될 때까지 점검은 `review`로
유지됩니다.

키트 내용을 **실행**하는 일은 그것을 **보고**하는 일보다 강한 증거를 요구합니다. `provision plan`은
키트의 Terraform 바이너리를 실행하므로, 운영자가 공급한 release 루트로 키트를 검증하고 검증이 실패하면
계획을 거부합니다. 두 경로 모두 산출물을 디렉터리 관례가 아니라 서명된 매니페스트에서 해석합니다.
Pinned 루트가 배포되면 `--release-root`는 계획 수립은 수락하고 점검은 여전히 수락하지 않는
재정의가 됩니다.

`build_offline_kit_manifest`는 그 검증기의 목표 release-side 역방향입니다. Staged 키트를 검증기와
동일한 검사로 읽으므로 symlink, 비정규 파일, 한계 초과 트리를 기술하는 대신 거부하며, 파일
목록을 운영자 입력이 아니라 단계에서 도출합니다. 단계에 없는 산출물 역할은 서명 이전에
실패하며, 동일한 내용을 두 번 빌드하면 서명 대상 바이트가 정확히 같습니다.
`scripts/deployment/release/build-offline-kit.py`는 검증기 모듈이 복원된 뒤 서명을 담당하도록
설계되어 있습니다. Operator가 보관한 Ed25519
비공개 키를 로드하고, 새 매니페스트를 쓰기 전에 오래된 서명을 제거해 중단된 실행이
그럴듯한 키트가 아니라 검증 불가 키트를 남기게 하며, 보고 전에 공개 release 루트로 재검증합니다.
비공개 키는 키트, 저장소, 로그 어느 곳에도 들어가지 않습니다.

### Trust 루트 및 교대

최종 offline 권한은 Python-TUF 7을 통해 The 갱신 Framework (TUF) 1.0을 사용합니다.
휠은 out-of-band trust 초기화로 initial signed `root.json`을 제공합니다. 루트 비공개
키는 offline에 보관합니다. CI는 targets, 스냅샷, 시각 메타데이터용 delegated online 키를
사용할 수 있지만 루트 비공개 키는 받지 않습니다.

클라이언트는 루트 메타데이터를 한 버전씩 갱신하고 각 new 루트가 old 루트와 new 루트 임계값을
모두 만족하는지 확인합니다. TUF 메타데이터 만료와 단조 증가 버전은 freeze, 롤백,
mix-and-match 공격을 방어합니다. 메타데이터 임계값과 키 ceremony는 release-security
정책이며 프로비저닝 적용의 one-person 승인과 독립적입니다.

현재 exact-content 검증기는 TUF가 대상을 인증한 이후 defense in 깊이로 유지됩니다.
Python-TUF 통합과 첫 루트 ceremony는 offline 루트를 만들고 CI 외부에 백업할 때까지
차단됩니다. 생성된 비공개 키를 커밋하거나 `fdaictl`을 통해 전달하지 않습니다.

## 승인 및 적용

Operator-initiated infrastructure 또는 role-assignment 적용에는 exact binary-plan 다이제스트에
연결된 인증된 사람 승인 한 명이 필요합니다. 실행기는 별도 워크로드 신원입니다. 계획이
변경되거나 만료되면 승인은 무효가 되며 적용은 `-auto-approve` 또는 caller-supplied
Terraform 인자를 허용하지 않습니다.

삭제, replacement, 역할 변경, state-backend 변경, temporary-access creation,
temporary-access 정리는 사람용 출력과 JSON 출력에서 별도로 강조합니다. 모두 같은
one-approver 프로비저닝 정책을 사용합니다. 이 배포 정책은 high-impact 자율
런타임 액션의 기존 정족수 룰을 낮추지 않습니다.

목표 수명 주기는 다음과 같습니다.

```text
inspect -> profile init -> bootstrap plan -> human approval -> exact apply
  -> access cleanup -> post-provision verification
```

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 설치 및 명령 계약 | [설치형 배포 CLI](installable-deployment-cli-ko.md) |
| Azure 인벤토리 및 초기화 리소스 | [배포 및 온보딩](deploy-and-onboard-ko.md) |
| 계획, release, 롤백 수명 주기 | [배포](deployment-ko.md) |
| 실행기와 human 신원 분리 | [보안 및 ID](../architecture/security-and-identity-ko.md) |
