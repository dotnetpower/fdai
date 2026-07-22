---
title: Provisioning 실행 Profile
translation_of: provisioning-execution-profiles.md
translation_source_sha: 92dadca9511d9f9e0b4bcc80492af4195628d138
translation_revised: 2026-07-22
---
# Provisioning 실행 Profile

이 문서는 `fdaictl`이 provisioning host, connectivity mode, command transport, access path를
선택하는 방법을 정의합니다. 또한 Terraform이 infrastructure 또는 role assignment를 변경하기
전에 적용되는 사람 승인과 workload-identity 경계를 정의합니다.

> **구현 상태:** 읽기 전용 `fdaictl provision inspect`와 private `provision init` profile
> persistence가 구현되었습니다. Injected release root를 사용하는 offline-kit manifest,
> signature, compatibility, exact file-set verification이 구현되었습니다. Pinned root packaging,
> kit construction, bootstrap plan/apply orchestration, temporary public-access cleanup,
> post-provision verification은 목표 동작으로 남아 있습니다.
>
> **범위:** Azure가 구현된 대상입니다. 이 profile은 Terraform source of truth를 변경하거나
> private endpoint를 우회하는 local fallback을 허용하지 않습니다.

## 한눈에 보는 설계

Provisioning은 네 가지 선택을 독립된 축으로 취급합니다. 명령은 먼저 evidence를 평가하며,
`dev` 같은 environment name 또는 operator가 wheel을 설치한 machine에서 authority를 추론하지
않습니다.

| 축 | 지원 값 | 선택 규칙 |
|----|---------|-----------|
| Connectivity | `online`, `offline` | 제한된 TLS 검사를 통과한 후에만 online source를 사용하고, 그렇지 않으면 signed offline kit를 요구합니다. |
| Execution host | `existing-host`, `managed-vm` | 적합한 private-network host를 재사용하고, 적합한 host가 없으면 managed VM을 생성합니다. |
| Transport | `manual`, `github-actions` | 사람이 exact-plan flow를 직접 시작하거나 GitHub Actions를 통해 같은 flow를 제출합니다. |
| Ownership | `fdai-managed` | 승인 후 Terraform이 선언된 resource와 role assignment를 관리합니다. |

## 읽기 전용 검사

Bootstrap plan을 만들기 전에 inspection을 실행합니다.

```bash
fdaictl provision inspect --output json
```

Inspection은 local Azure CLI, Terraform, GitHub CLI, 제한된 online artifact access,
offline-kit candidate, Azure workload identity endpoint를 검사합니다. `mutation_performed=false`,
필수 사람 승인자 한 명, 선택된 profile이 포함된 안정적인 JSON contract를 반환합니다. Tool을
설치하거나 configuration을 기록하거나 resource를 생성하거나 runner를 등록하거나 Terraform을
apply하지 않습니다.

Result는 다음 상태를 사용합니다.

| 상태 | 의미 |
|------|------|
| `ready` | Existing host에 필요한 toolchain, connectivity, workload identity가 있습니다. |
| `review` | Managed VM 또는 검증되지 않은 offline kit가 권장되며 operator review가 필요합니다. |
| `incomplete` | 명시적으로 요청한 profile에 필수 dependency 또는 access path가 없습니다. |

Offline-kit directory는 이후 단계가 pinned release root로 manifest와 signature를 검증할 때까지
`review`로 유지됩니다. File이 존재한다는 사실만으로 trust가 성립하지 않습니다.

## Profile initialization

명시적으로 결정된 값으로 검토한 profile을 저장합니다.

```bash
fdaictl provision init \
        --connectivity online \
        --host existing-host \
        --transport manual \
        --access-method internal_ssh
```

명령은 모든 `auto` 값을 거부하고 `.fdai/provisioning/profile.json`을 mode-`0700` directory
안에 file mode `0600`으로 기록합니다. Offline profile에는 `--artifact-source`가 필요합니다.
Temporary public SSH에는 전체 address space보다 좁은 canonical source CIDR과 5-60분 access
window가 필요합니다. GitHub Actions transport에는 일치하는 `github_actions` access method가
필요합니다.

기존 destination은 `--force`를 명시하지 않으면 initialization을 차단합니다. Force는 symbolic
link를 따라가거나 non-file destination을 교체하지 않습니다. Profile initialization은 Azure
resource를 변경하지 않으며 JSON 출력에 `mutation_performed=false`를 기록합니다.

## Execution host

### Existing host

다음 조건을 이미 갖춘 jumpbox 또는 deployment host에는 `existing-host`를 사용합니다.

- 필요한 모든 private endpoint에 대한 network 및 private DNS reachability.
- Azure CLI와 Terraform.
- 승인된 deployment role이 있는 별도 workload identity.
- Protected Terraform backend와 plan store에 대한 durable access.

Manual execution은 operator가 이 host에서 `fdaictl`을 시작한다는 의미입니다. Terraform이
operator의 interactive Azure identity를 사용한다는 의미가 아닙니다. Workload identity가 없는
host는 incomplete로 보고됩니다.

### Managed VM

Operator laptop이 private network 밖에 있거나, existing jumpbox가 적합하지 않거나, policy가
dedicated deployment host를 요구하면 `managed-vm`을 사용합니다. VM은 durable하게 유지하지만
일반적으로 deallocate합니다. Protected state, plan, approval, audit record는 private storage에
남으므로 VM을 시작, 중지 또는 다시 빌드해도 deployment authority가 변경되지 않습니다.

CLI는 managed VM을 권장하지만 inspection 중에는 생성하지 않습니다. Bootstrap planning은 승인
전에 VM, network, identity, role, access, cost, stop, cleanup effect를 보여 줍니다.

## Access preference

Managed-host access order는 다음과 같이 고정합니다.

1. 승인된 internal SSH.
2. Azure Policy와 deployment profile이 허용하는 경우 temporary public-IP SSH.
3. Self-hosted runner의 GitHub Actions.
4. Azure Bastion.
5. 감사되는 비상 경로인 Azure Run Command.

Temporary public access는 silent fallback으로 사용하지 않습니다. Plan에는 allowlist에 포함된
source CIDR, key 또는 certificate만 사용하는 SSH, 제한된 access window, public IP와 temporary
network-security rule의 자동 제거가 필요합니다. `0.0.0.0/0`, password authentication,
persistent public IP는 허용되지 않습니다. Cleanup은 operation 성공 기준의 일부입니다.
Cleanup에 실패하면 operation은 incomplete로 남고 audit record가 생성됩니다.

## Online 및 offline delivery

Online delivery는 PyPI의 public `fdai` package와 version-matched signed deployment bundle을
사용합니다. Runner는 allowlist TLS 검사를 통과한 후에만 public source를 사용할 수 있습니다.

Release workflow는 read-only job에서 wheel과 source distribution을 한 번만 빌드하고 Python과
bundle version이 일치하는지 검사합니다. 일치하는 signed bundle을 게시한 후에만 같은 artifact를
PyPI Trusted Publishing으로 게시합니다. Publish job만 GitHub OIDC permission을 받으며 장기
PyPI token은 저장하지 않습니다.

Disconnected delivery는 platform별 offline kit에서 같은 `fdai` wheel과 command contract를
사용합니다. Kit에는 다음 항목이 포함됩니다.

- FDAI wheel과 모든 transitive Python wheel.
- Signed deployment bundle.
- Pinned Terraform binary와 provider mirror.
- OPA와 필요한 helper binary.
- SBOM, SHA-256 manifest, signature, release trust metadata.

Offline mode는 PyPI, GitHub, public Terraform registry fallback을 차단합니다. Artifact source로
승인된 internal mirror 또는 removable media를 사용할 수 있습니다. Installer와 `fdaictl`은 두
경우 모두 같은 pinned release root를 검증합니다.

`verify_offline_kit`은 manifest parsing 전에 Ed25519 signature를 검사하고 exact CLI 및 platform
version을 binding하며 symlink와 extra file을 거부합니다. 모든 file digest를 streaming하고 wheel,
signed deployment bundle, Terraform binary 및 provider mirror, OPA, SBOM을 요구합니다. Release
root injection은 test와 release construction에서만 사용합니다. `fdaictl`은 `--release-root`
override를 제공하지 않습니다. Public root가 wheel에 pin될 때까지 inspection은 `review`로
유지됩니다.

### Trust root 및 rotation

최종 offline authority는 Python-TUF 7을 통해 The Update Framework (TUF) 1.0을 사용합니다.
Wheel은 out-of-band trust bootstrap으로 initial signed `root.json`을 제공합니다. Root private
key는 offline에 보관합니다. CI는 targets, snapshot, timestamp metadata용 delegated online key를
사용할 수 있지만 root private key는 받지 않습니다.

Client는 root metadata를 한 version씩 update하고 각 new root가 old root와 new root threshold를
모두 만족하는지 확인합니다. TUF metadata expiry와 monotonic version은 freeze, rollback,
mix-and-match 공격을 방어합니다. Metadata threshold와 key ceremony는 release-security
policy이며 provisioning apply의 one-person approval과 독립적입니다.

현재 exact-content verifier는 TUF가 target을 인증한 이후 defense in depth로 유지됩니다.
Python-TUF integration과 첫 root ceremony는 offline root를 만들고 CI 외부에 backup할 때까지
차단됩니다. Generated private key를 commit하거나 `fdaictl`을 통해 전달하지 않습니다.

## 승인 및 apply

Operator-initiated infrastructure 또는 role-assignment apply에는 exact binary-plan digest에
연결된 인증된 사람 승인 한 명이 필요합니다. Executor는 별도 workload identity입니다. Plan이
변경되거나 만료되면 approval은 무효가 되며 apply는 `-auto-approve` 또는 caller-supplied
Terraform argument를 허용하지 않습니다.

Delete, replacement, role change, state-backend change, temporary-access creation,
temporary-access cleanup은 사람용 출력과 JSON 출력에서 별도로 강조합니다. 모두 같은
one-approver provisioning policy를 사용합니다. 이 deployment policy는 high-impact autonomous
runtime action의 기존 quorum rule을 낮추지 않습니다.

목표 lifecycle은 다음과 같습니다.

```text
inspect -> profile init -> bootstrap plan -> human approval -> exact apply
        -> access cleanup -> post-provision verification
```

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 설치 및 command contract | [설치형 배포 CLI](installable-deployment-cli-ko.md) |
| Azure inventory 및 bootstrap resource | [배포 및 온보딩](deploy-and-onboard-ko.md) |
| Plan, release, rollback lifecycle | [배포](deployment-ko.md) |
| Executor와 human identity 분리 | [보안 및 ID](../architecture/security-and-identity-ko.md) |
