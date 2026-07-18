---
title: 설치형 배포 CLI
translation_of: installable-deployment-cli.md
translation_source_sha: 5021efcf331f5e1529babf110abb8ec947aaf49d
translation_revised: 2026-07-18
---
# 설치형 배포 CLI

이 문서는 FDAI의 목표 설치 및 배포 경험을 정의합니다. 운영자는 격리된 Python CLI 도구를
설치하고, 읽기 전용 배포 preflight를 실행한 다음, 로컬 머신을 통해 비밀을 이동하지 않고
승인된 Terraform plan을 배포 runner에 제출할 수 있습니다.

> **상태:** Increment C1과 C2의 static 부분은 source distribution에 구현되었습니다.
> `fdaictl` 진입점, deterministic `version` 및 `doctor` 출력, 안전한 `onboard init`, 활성 Azure
> target guard, network-free `deploy preflight`, Terraform plan JSON analysis, local
> `security audit`을 사용할 수 있습니다. Remote deployment contract, plan-only GitHub workflow
> dispatch, exact-plan apply guard도 구현되었습니다. Bounded live Azure Policy, Compute quota,
> Resource Graph identity, value-blind Key Vault secret probe를 사용할 수 있습니다. Network
> egress, signed release artifact, production workflow wiring은 계획 상태입니다.
>
> **실행 경계:** Terraform은 인프라 실행 엔진이자 source of truth로 유지됩니다. `fdaictl`은
> validation, plan 분석, workflow 제출, 배포 후 검사를 위한 얇은 orchestration 계층입니다.
>
> **구현 초점:** Azure가 유일한 구현 대상입니다. 비-Azure provider 지원은 연기됩니다.

## 한눈에 보는 설계

`uv`를 사용하여 `fdaictl`을 격리된 도구로 설치합니다. CLI는 버전이 일치하는 deployment
bundle을 확인하고, 로컬 toolchain과 Azure 환경을 검사하고, Terraform plan을 JSON으로
변환한 다음 기존 deployment preflight analyzer로 전달합니다. 실제 apply는 laptop에서
명령을 제출하는 경우에도 승인된 deployment runner에서만 실행됩니다.

| 관심사 | 결정 |
|--------|------|
| 운영자 명령 | `fdaictl` |
| 권장 설치 | `uv tool install fdai` |
| 일회성 및 CI 실행 | `uvx --from fdai fdaictl ...` |
| 인프라 엔진 | `infra/` 아래 Terraform |
| 기본 동작 | 읽기 전용 preflight 또는 plan |
| Apply 위치 | VNet-integrated self-hosted runner |
| 패키지 내용 | Python CLI wheel과 서명된 deployment bundle |
| 머신 출력 | 안정적인 JSON schema와 문서화된 exit code |
| 제품 언어 | locale fallback이 있는 영어 source catalog |

## 별도 명령을 사용하는 이유

저장소에는 이미 서로 다른 두 개의 command surface가 있습니다.

- `python -m fdai`는 headless control-plane process를 시작합니다.
- `cli/` package는 읽기 전용 operator console입니다.

배포는 세 번째 책임입니다. `fdaictl`은 배포 관리를 runtime process 및 conversational
console과 분리합니다. 또한 이 경계는 향후 operator-console 기능이 배포 credential을
획득하거나 execution surface가 되는 것을 방지합니다.

## 목표 운영자 경험

계획된 영구 설치 방식은 다음과 같습니다.

```bash
uv tool install fdai==<version>
fdaictl version
fdaictl doctor
```

Source checkout에서는 구현된 C1 명령을 `uv run fdaictl`로 실행합니다. Release hardening이
완료되면 게시된 wheel에 위의 영구 설치 형식을 사용할 수 있습니다.

일회성 실행 또는 CI job에는 임시 환경을 사용합니다.

```bash
uvx --from fdai==<version> fdaictl deploy preflight --environment dev
```

`uv`를 사용할 수 없을 때는 `pipx`를 권장 fallback으로 사용합니다. Virtual environment
안에서 직접 `pip install`하는 방식도 지원하지만 system Python에 설치하는 것은 권장하지
않습니다. Installer는 Azure CLI, Terraform, GitHub CLI 또는 다른 system tool을 자동으로
설치하거나 업그레이드하지 않습니다. `fdaictl doctor`는 누락되거나 호환되지 않는 tool과
수정 방법을 보고합니다.

> `version`, `doctor`, `onboard init`, guarded `onboard guided`, portable `backup create` 및
> `backup restore`, `deploy preflight`, plan-only `deploy plan` dispatch는 구현되었습니다.
> Sanitized plan metadata status는 `deploy status`로 조회할 수 있고 guarded exact-plan
> submission은 `deploy apply`로 사용할 수 있습니다. Teardown은 아직 unavailable입니다.

## 명령 모델

명령은 diagnosis, onboarding, deployment, status를 중심으로 구성됩니다. Mutation으로 이어질
수 있는 모든 명령은 remote execution boundary를 명확하게 표시합니다.

| 명령 | 목적 | Azure mutation |
|------|------|----------------|
| `fdaictl version` | CLI, bundle, schema, compatibility version 표시 | 없음 |
| `fdaictl doctor` | Python, Azure CLI, Terraform, GitHub CLI, 인증, local config 검사 | 없음 |
| `fdaictl onboard init` | Schema-validated, untracked environment configuration 생성 | 없음 |
| `fdaictl onboard guided` | Doctor, private config 생성, live preflight, plan-only runner 제출, sanitized status post-check를 순서대로 실행 | 없음 |
| `fdaictl security audit` | Runtime flag 조합, local config hygiene, 요청된 sandbox 가용성 검사 | 없음, `--fix-permissions`를 명시한 경우 제외 |
| `fdaictl bundle verify` | Bundle signature, compatibility, file set, digest, SBOM, size 검사 | 없음 |
| `fdaictl backup create` | 검증된 configuration, reference, audit metadata, user context로 private portable archive 생성 | 없음 |
| `fdaictl backup restore` | Portable archive를 검증하고 새로운 local directory에 atomic restore | 없음 |
| `fdaictl deploy preflight` | Static 및 live read-only deployment blocker 수집 | 없음 |
| `fdaictl deploy plan` | 승인된 runner에 plan-only workflow 제출 | 없음 |
| `fdaictl deploy apply --plan-id <id>` | 정확히 승인된 plan을 remote apply에 제출 | 있음, runner에서 실행 |
| `fdaictl deploy status` | Sanitized plan digest, expiry, status, workflow URL 조회 | 없음 |
| `fdaictl deploy teardown` | 보호된 environment teardown workflow 제출 | 있음, runner에서 실행 |

C1 명령은 자동화를 위해 안정적인 JSON schema를 사용합니다. `onboard init`은 활성 subscription
및 tenant identifier, environment, region, remote-runner 경계, shadow-mode 기본값만 gitignored
mode-`0600` 파일에 기록합니다. 사람용 출력에는 account identifier가 표시되지 않습니다.

## Local security audit

`fdaictl security audit`은 process 시작 전에 high-risk local 및 runtime 조합을 검사합니다.
Environment value 또는 configuration content를 출력하지 않고 stable check id를 보고합니다.
현재 검사는 다음 항목을 포함합니다.

- staging 또는 production에서 활성화된 development authentication bypass.
- development 외 환경에서 누락된 Entra verifier configuration.
- 필수 governed runtime context 없이 활성화된 VM-task 또는 chaos enforcement.
- bubblewrap command sandbox를 요청했지만 binary를 사용할 수 없는 상태.
- Symbolic link이거나 group/world permission이 있거나 parse할 수 없거나 secret-like field name이
  있는 deployment configuration.

자동화에서는 `--output json`을 사용합니다. 수정되지 않은 critical finding이 있으면 exit `3`,
critical finding이 없으면 exit `0`을 반환합니다. `--fix-permissions`는 의도적으로 범위가
좁습니다. Regular local config file을 mode `0600`, directory를 `0700`으로 설정할 수 있습니다.
Symlink를 따라가거나 configuration content를 편집하거나 feature를 disable하거나 credential을
rotate하거나 cloud resource를 변경하지 않습니다.

이 audit은 deployment preflight, OPA policy evaluation, secret scanning, Entra access review,
risk gate를 대체하지 않습니다. Local configuration drift를 일찍 찾고 이후 authoritative
control이 deployment 및 runtime decision을 수행합니다.

## Portable backup 및 restore

Workstation 또는 installation을 변경한 뒤 필요한 operator-owned deployment metadata를
이동하려면 `fdaictl backup create`를 사용하세요. 이 명령은 검증된 JSON input 4개를 읽고
결정론적인 mode-`0600` archive를 생성합니다.

- **Configuration:** Schema-validated environment, remote-runner boundary, shadow-mode 기본값을
  포함합니다.
- **Reference:** Opaque secret, document, policy, workflow, channel, bundle reference를
  포함합니다. Secret reference는 provider entry의 이름만 가리키며 secret value를 포함하지
  않습니다.
- **Audit metadata:** Source schema, record count, last sequence, audit hash-chain head를
  포함합니다. Audit entry body는 export하지 않습니다.
- **User context:** Locale, verbosity, timezone, learner-sharing preference, explicit consent를
  받은 memory record를 포함합니다. Conversation transcript와 생성된 briefing body는 이 archive
  format에 포함하지 않습니다.

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

Archive에는 정확히 4개의 allowlist file과 SHA-256 manifest만 포함됩니다. 생성 단계에서는
알 수 없는 schema field, credential-shaped value, private-key material, Terraform state marker,
symbolic link, 크기 제한을 넘는 input을 차단하며 `--force`를 명시하지 않은 accidental
overwrite도 차단합니다. Secret provider 또는 Terraform state file을 읽지 않습니다.

Restore는 같은 fixed member set과 stored ZIP format만 허용하고 file을 게시하기 전에 모든
schema와 digest를 검증하며 기존 destination을 거부합니다. Destination은 directory mode `0700`,
file mode `0600`으로 한 번의 atomic rename을 통해 나타나므로 validation 실패 시 partial restored
state가 남지 않습니다. 두 명령은 local-only이며 Azure 또는 Terraform call을 수행하지 않습니다.

## Guided deployment onboarding

기존의 안전한 deployment stage를 하나의 fail-closed sequence로 실행하려면 `fdaictl onboard
guided`를 사용하세요. 이 명령은 plan-only wizard입니다. Apply option을 노출하지 않으며 local에서
Terraform을 실행하지 않습니다.

Sequence는 다음 순서로 고정됩니다.

1. **Toolchain doctor:** Configuration을 기록하기 전에 Python, Azure CLI, Terraform, GitHub CLI,
  interactive Azure authentication을 검증합니다.
2. **Private configuration:** Schema-validated mode-`0600` environment file을 생성합니다. 기존
  file이 있으면 `--force-config`를 명시하지 않는 한 실행을 차단합니다.
3. **Target doctor:** 새 file로 doctor를 다시 실행하고 runner call 전에 active tenant 또는
  subscription mismatch를 차단합니다.
4. **Live preflight:** Static 및 configured read-only Azure probe를 실행합니다. Optional
  `--terraform-plan` file은 resource type을 얻기 위해 parse하지만 wizard가 `terraform plan`을
  실행하지 않습니다.
5. **Plan-only submission:** 기존 opaque context contract를 통해 `apply=false`로 approved runner
  workflow를 dispatch합니다.
6. **Post-check:** 일시적으로 누락된 plan metadata만 최대 60초 동안 poll합니다. Sanitized status가
  `planning` 또는 `ready`일 때만 계속하고 다른 모든 상태는 fail closed 처리합니다.

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

GitHub installation token은 `FDAI_GITHUB_TOKEN`에 유지하며 command argument로 전달하지 않습니다.
Machine output은 target identifier 또는 credential value 없이 완료된 step id, plan id, status,
workflow URL을 보고합니다. 실패 시 failed step과 sanitized reason만 보고합니다. 이전 stage가
실패하면 이후 stage를 호출하지 않으므로 doctor 또는 preflight blocker가 runner submission에
도달할 수 없습니다.

초기 구현은 임의의 Terraform argument를 노출하지 않는 것이 좋습니다. 지원되는 environment와
feature 설정은 validated configuration schema에서 가져옵니다. 향후 명시적인 escape hatch가
추가된다면 audit되어야 하며 command line에서 secret 값을 받지 않아야 합니다.

## Preflight 계약

`fdaictl deploy preflight`는 기존 `PreflightAnalyzer`의 읽기 전용 composition root입니다.
CLI 안에 두 번째 readiness rule 집합을 구현하지 않고 공유 report 및 probe 계약을 재사용하는
것이 좋습니다.

구현된 static path는 deployment의 neutral scope, resource type, 필요한 egress host, grounded
policy fact를 포함하는 versioned JSON input을 받습니다. Deterministic local probe만 실행하고
network call을 수행하지 않으며 analyzer의 stable ordering과 shadow-versus-enforce 의미를
유지합니다. Machine-readable `terraform show -json` output은 `--terraform-plan`으로 전달합니다.
Input의 explicit `terraform_resource_type_map`은 `create` action이 있는 managed resource만
replacement를 포함해 CSP-neutral type으로 변환합니다. Data source, no-op, read, update-only,
delete-only change는 제외합니다. Mapping되지 않은 created type이 있으면 run은 incomplete가
되며 resource address 또는 planned value는 report에 들어가지 않습니다.

Bounded live Azure check를 추가하려면 `--environment-config`를 전달합니다. CLI는 validated
onboarding target을 읽고 local Azure CLI identity를 통해 short-lived ARM token을 얻은 다음,
bounded read-only ARM 및 Resource Graph transport로 Azure Policy, configured Compute quota,
executor RBAC probe를 실행합니다. ARM GET request는 20초 및 8 page로 제한되고 role query는
20초 read-only ARG POST입니다. Neutral resource type은 Azure adapter 안에서 ARM type으로
변환됩니다. Mapping되지 않은 type 또는 실패한 probe는 run을 incomplete로 만들며 CLI error는
subscription, resource group, principal, role definition, Azure path를 노출하지 않습니다.
Optional `key_vault` block은 streamed GET을 열고 status code만 확인해 required secret reference를
검사합니다. Response body 또는 secret value는 읽지 않습니다. Missing reference는 SHA-256에서
파생한 id를 사용하므로 vault host와 secret name이 report에 들어가지 않습니다. Report는 finding이
없을 때도 stable `checks` array를 포함합니다. 각 entry는 probe category, `clear` 또는 `finding`
status, finding count만 기록하므로 automation이 성공한 check와 구성되지 않은 check를 구분할 수
있습니다. Live profile은 `required_categories`를 선언할 수 있으며 quota, identity, secret config가
누락되면 network call 전에 실패합니다. Bounded runner TLS reachability가 live egress evidence를
제공합니다. Static Firewall, NSG, UDR topology 분석은 별도 future adapter로 남습니다.

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

1. **Toolchain 및 artifact 검사:** 지원 version, lock file, CLI-to-bundle compatibility,
   checksum, signature, 선택된 environment를 확인합니다.
2. **Identity 및 target 검사:** 활성 Azure subscription, deployer role assignment, provider
   registration, target region, runner identity를 확인합니다.
3. **Static infrastructure 검사:** Terraform formatting, initialization, validation, plan
   generation을 실행합니다. Policy 및 dependency 분석을 위해 plan을 JSON으로 변환합니다.
4. **Bounded live 검사:** 읽기 전용 adapter를 통해 Azure Policy, Resource Graph, quota, network
   configuration, 필요한 secret의 존재 여부를 조회합니다.
5. **Readiness 결정:** 하나의 grounded report를 만들고, 각 finding이 enforce 상태인지 아직
   shadow mode인지 기록하고, 다음 안전한 작업을 출력합니다.

실패하거나 생략된 probe는 `clear` 결과를 만들지 않습니다. Report는 run을 incomplete로
표시하고 고객 값이나 credential을 노출하지 않고 실패한 probe 이름을 제공합니다.

### Finding category

CLI는 deployment preflight에 이미 정의된 category를 표시합니다.

- **Policy guardrail:** 거부된 resource type, 필수 network control, public-access restriction.
- **Supply-chain egress:** 승인된 mirror가 필요한 package, image, operating-system repository.
- **Identity 및 RBAC:** 의도한 scope에 누락된 deployer 또는 runner permission.
- **Quota 및 capacity:** Region, SKU, service quota blocker.
- **Dependency ordering:** prerequisite deployment stage가 필요한 resource.
- **Secret configuration:** Secret 값을 읽거나 출력하지 않는 missing reference 또는 도달할 수
  없는 secret provider.

### 출력 및 exit code

사람용 출력은 간결한 table입니다. 자동화는 display text와 독립적으로 versioning되는 schema를
사용하는 `--output json`을 사용합니다. Localized display string은 field name, verdict, evidence
identifier 또는 exit code를 변경하지 않습니다.

| Exit code | 의미 |
|-----------|------|
| `0` | Run이 완료되고 review 또는 enforced blocker가 남아 있지 않음 |
| `2` | Shadow-mode probe가 보고한 blocker를 포함하여 review 필요 |
| `3` | Enforce-mode blocker가 plan 또는 apply를 차단함 |
| `4` | 필수 probe 또는 dependency 실패로 run이 incomplete 상태임 |
| `64` | Command usage 또는 environment configuration이 올바르지 않음 |

Report의 실제 verdict는 finding이 현재 deploy를 차단하는지와 분리됩니다. 예를 들어
shadow-mode probe는 `blocked`를 보고하면서 enforcement용 `3` 대신 review용 `2`로 process를
종료할 수 있습니다.

Protected remote plan에서 private runner는 non-secret GitHub Variable
`DEPLOY_PREFLIGHT_INPUT_JSON`을 요구합니다. `azure_live.required_categories`에는
`policy_guardrail`, `quota_capacity`, `identity_rbac`, `secret_config`가 모두 있어야 하며 대응하는
resource-type map, quota check, principal/role reference, Key Vault metadata reference를 제공합니다.
Workflow는 mode를 `enforce`로 덮고 current timestamp를 설정하며 report scope를 neutral value로
교체합니다. Locked CLI를 설치하고 exact binary plan을 JSON으로 변환한 뒤 네 read-only live
category를 모두 실행합니다. Complete check coverage가 있는 `clear` report만 수락합니다. Plan
JSON, environment identifier, input profile은 step 종료 시 제거됩니다.

Sanitized report만 protected plan 옆에 저장됩니다. Metadata는 runner-egress evidence와 Azure live
evidence의 SHA-256 digest를 별도로 binding합니다. Exact apply는 claim 또는 Terraform 실행 전에
두 original file을 내려받아 digest를 다시 계산합니다. Binary plan digest가 일치해도 evidence
file 중 하나가 변경되면 apply가 차단됩니다.

## 읽기 전용 preflight와 bootstrap discovery

기본 preflight는 Azure resource를 생성하지 않습니다. 일부 tenant policy discovery는 policy
결과를 관찰하기 위해 throwaway resource가 필요합니다. 이 작업은 별도의 명시적 명령으로
유지합니다.

```bash
fdaictl bootstrap probe-policy --allow-probe-resources
```

이 명령은 실행 전에 resource scope, cleanup behavior, stop condition, 예상 비용을 표시하는 것이
좋습니다. 이 명령은 `fdaictl deploy preflight`의 일부가 아니며 preflight가 암시적으로 호출하지
않습니다.

## 배포 artifact 모델

현재 Python wheel에는 `src/fdai` package가 포함되지만 배포에는 Terraform module, policy,
schema, 선택된 rule-catalog data도 필요합니다. 변경 가능한 모든 infrastructure file을
import 가능한 Python resource로 packaging하면 version alignment와 inspection이 어려워집니다.
대신 버전이 일치하는 두 artifact를 사용합니다.

### Python wheel

Wheel에는 다음이 포함됩니다.

- `fdaictl` entry point와 command parser.
- Configuration 및 output schema.
- Preflight orchestration 및 report rendering.
- Artifact download 및 signature verification.
- Workflow submission 및 status client.

Deployment 전용 integration은 control-plane runtime import path 밖에 유지하는 것이 좋습니다.
첫 구현은 기존 distribution에 포함할 수 있습니다. Installation size 또는 dependency isolation이
측정된 문제가 되면 별도의 lightweight CLI distribution을 검토할 수 있습니다.

### 서명된 deployment bundle

Deployment bundle에는 다음이 포함됩니다.

- `infra/`의 Terraform root 및 module.
- Plan 검증에 사용하는 OPA policy.
- 필요한 rule-catalog schema 및 deployment profile.
- Version 및 SHA-256 digest를 기록하는 manifest.
- Software bill of materials와 release signature.

CLI version `<version>`은 기본적으로 bundle `<version>`을 확인합니다. CLI는 Terraform을 실행하기
전에 signature와 manifest를 검증합니다. Disconnected environment에서는 `--bundle <path>`를
제공할 수 있지만 동일한 verification을 적용합니다. 명시적으로 문서화된 compatibility range가
허용하지 않는 version mismatch는 plan generation 전에 실패합니다.

`fdaictl bundle verify --bundle <dir> --public-key <pem>`은 verification 측을 구현합니다.
Ed25519 public key만 받고 detached manifest signature를 검증하고 현재 CLI와 manifest
compatibility range를 비교하고 traversal 및 symlink를 차단합니다. 정확히 listed file set 및
listed JSON SBOM을 요구하고 모든 SHA-256 검사를 streaming하며 total-size cap을 적용합니다.
Signing-key 또는 bundle-building code는 포함하지 않습니다.

`scripts/deployment/release/build-deployment-bundle.py`는 release-only build 측을 구현합니다. `infra/`, `policies/`,
`rule-catalog/schema/`, `rule-catalog/profiles/`, `rule-catalog/risk-classification.yaml` 아래 tracked
file만 찾습니다. Plan, tfvars, tfstate, PEM/key, symlink, untracked, outside-root path는 차단합니다.
File mode, mtime, tar owner/group, gzip timestamp, ordering을 normalize하고 deterministic CycloneDX
file SBOM과 canonical manifest를 생성한 다음 external Ed25519 private key로 서명합니다. Private
key는 bundle에 들어가지 않습니다.

각 manifest는 `stable`, `beta`, `development` 중 하나의 release channel도 서명합니다. Release
workflow는 channel을 explicit choice로 요구하고 두 reproducibility build에 전달합니다. 따라서
서명 후 channel을 변경하면 signature가 무효화됩니다. Bundle verification은 version 및 manifest
digest와 함께 signed channel을 반환합니다.

Approval-gated `release-deployment-bundle` workflow는 `release` GitHub Environment의
`FDAI_BUNDLE_SIGNING_KEY_PEM`을 읽고 동일 commit 및 `SOURCE_DATE_EPOCH`에서 두 번 build합니다.
두 directory, archive, public key를 byte-for-byte 비교하고 `fdaictl bundle verify`를 실행한 뒤
archive, public key, manifest, signature, checksum을 30일 Actions artifact로 게시합니다.
`publish_release=true`는 GitHub Release를 생성하는 별도 explicit gate입니다. Temporary private
key는 mode-restricted 상태로 사용하고 shell trap으로 제거합니다.

`release` Environment가 signing key를 노출하기 전에 exact clean checkout에서 두 independent
job이 통과해야 합니다. Verification job은 locked Python 및 console dependency를 설치하고
disposable pgvector PostgreSQL service를 시작해 single Alembic head로 upgrade합니다. 이어서 live
integration test를 포함한 `scripts/verify.sh --full`과 productization, console, wheel build,
isolated CLI check를 실행합니다. 마지막 `git diff --exit-code`는 generator가 tracked source를
다시 쓰는 경우를 차단합니다. Dependency-audit job은 pinned Python vulnerability scanner를
실행합니다. Bundle job은 두 job을 `needs`로 선언하고 pinned Ubuntu runner image를 사용하며,
이 job만 `contents: write`를 받습니다. Verification 및 audit job은 read-only로 유지됩니다.

## Release channel, upgrade 및 rollback

더 새로운 signed bundle revision을 활성화하려면 `fdaictl release upgrade`를 사용합니다. Local
environment config, release-state path, bundle directory, trusted public key, expected channel을
전달합니다. Command는 state를 쓰기 전에 signature, file digest, CLI compatibility range, signed
channel을 검증합니다. Upgrade는 더 새로운 semantic version만 수락합니다. 이전 version에는
rollback을 사용합니다.

```bash
fdaictl release upgrade \
  --state .fdai/release-state.json \
  --config .fdai/environments/dev.json \
  --bundle <verified-bundle-directory> \
  --public-key <trusted-public-key.pem> \
  --channel stable \
  --output json
```

Release state는 active version, signed channel, manifest digest, 최대 20개 bounded history, current
config의 SHA-256 digest만 포함하는 atomic mode-`0600` JSON pointer입니다. Config content, secret
value, Terraform state, binary plan, host path는 저장하지 않습니다. CLI는 temporary state file을
쓰고 config digest를 다시 검사한 다음 active pointer를 교체합니다. Config 자체는 다시 쓰지
않습니다.

Exact prior signed bundle과 함께 `fdaictl release rollback`을 사용합니다. Candidate는 full bundle
verification 후 newest history entry와 version, channel, manifest digest가 일치해야 합니다. 다른
bundle, tampered bundle, incompatible bundle 또는 단순히 더 오래된 bundle은 state 변경 전에
차단됩니다.

```bash
fdaictl release rollback \
  --state .fdai/release-state.json \
  --config .fdai/environments/dev.json \
  --bundle <prior-verified-bundle-directory> \
  --public-key <trusted-public-key.pem> \
  --output json
```

## Plan 및 apply 무결성

`fdaictl deploy plan`은 plan-only workflow를 제출하고 현재 workflow run id와 URL을 반환합니다.
같은 environment config가 `doctor`를 통과해야 하고 GitHub credential은
`FDAI_GITHUB_TOKEN`에서만 읽습니다. Dispatch body에는 `apply=false`, environment, exact commit,
SHA-256 deployment-context fingerprint만 전달합니다. Tenant, subscription, backend, runner
identifier는 전달하지 않습니다. Workflow는 plan 전에 bounded request id, context digest, exact
checked-out commit을 검증합니다.

```bash
FDAI_GITHUB_TOKEN=<installation-token> fdaictl deploy plan \
  --config .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --bundle-digest <sha256> \
  --commit-sha <git-sha> \
  --output json
```

Terraform plan file에는 state에서 파생된 민감한 값이 포함될 수 있으므로 local CLI는 binary
Terraform plan을 download하거나 출력하지 않습니다. Runner는 CLI-requested plan과 sanitized
metadata를 private remote-state container 옆의 `deployment-plans` Blob container에 저장합니다.
Upload는 runner managed identity를 사용하고 public access는 off이며 `overwrite=false`가 각 run
path를 immutable하게 유지합니다. Metadata는 tenant, subscription, backend, runner, secret value
없이 plan digest, context digest, exact commit, workflow run, 1시간 logical expiry를 기록합니다.
`deploy plan`은 derived plan id를 반환하고 `deploy status --plan-id <id>`는 bounded
metadata-only artifact를 읽습니다. 각 새 plan run은 private blob을 최대 1001개 scan하고 24시간
지난 allowlisted plan path를 최대 1000개 삭제합니다. 두 bound 중 하나에 도달하면 unknown
path를 삭제하지 않고 fail closed합니다.

`fdaictl deploy apply --plan-id <id>`는 다음 검사를 모두 통과한 경우에만 정확히 저장된 plan을
적용합니다.

- Plan이 동일한 subscription, environment, bundle digest, commit에 대해 생성됨.
- Plan이 만료되지 않았고 이미 적용되지 않음.
- Preflight report에 enforce-mode blocker가 없음.
- 호출자가 apply를 명시적으로 요청했고 workflow approval policy를 충족함.
- Runner identity와 backend configuration이 기록된 plan context와 일치함.

CLI는 `doctor`를 다시 실행하고 bounded metadata를 조회해 context digest와 logical expiry를
검증하며 stored plan digest만 dispatch합니다. Apply workflow는 target GitHub Environment를 외부
approval 및 audit history 경계로 사용합니다. `terraform plan`을 건너뛰고 private Blob storage의
exact binary와 metadata를 복원해 모든 digest, id, status, timestamp, commit을 검증한 다음
`terraform apply` 전에 immutable `apply-claim.json`을 생성합니다. Duplicate 또는 failed prior
claim은 automatic retry를 차단합니다. 성공한 run은 immutable `apply-receipt.json`을 기록하며
`deploy status`는 claim에서 `applying`, receipt에서 `applied`를 투영합니다.

```bash
FDAI_GITHUB_TOKEN=<installation-token> fdaictl deploy apply \
  --config .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --plan-id <plan-id> \
  --bundle-digest <sha256> \
  --commit-sha <git-sha> \
  --output json
```

보호된 workflow store는 각 plan을 1시간 후 logical expired로 표시합니다. Log에는 plan id,
digest, expiry만 노출합니다. Plan file, state, credential 또는 secret 값은 노출하지 않습니다.
Physical cleanup이 아직 blob을 제거하지 않았더라도 apply는 logical expiry를 차단해야 합니다.

Transport-neutral foundation은 `fdai.deployment_cli.remote`에 구현되었습니다. `PlanRecord`는 opaque
metadata만 포함하며 `RemoteDeploymentService`는 apply 전에 이를 다시 load합니다. Local guard는
`ready` status, 유효한 retention, 정확한 tenant/subscription/environment/bundle/commit/backend/
runner context, clear enforced preflight, approved runner availability를 요구합니다. 이후
caller-supplied replacement가 아니라 workflow-owned stored digest를 제출합니다. Concrete GitHub
plan-only transport는 현재 dispatch run detail을 반환하고 runner는 protected binary plan과
metadata를 기록하며 CLI는 bounded run-scoped zip에서 sanitized status를 조회합니다. Exact-plan
apply transport, GitHub Environment approval boundary, immutable claim, audit receipt가 구현되어
있습니다. Runner egress preflight evidence는 immutable plan metadata에 고정되고 post-apply
check는 receipt 기록 전에 Terraform convergence, migration 성공, enabled endpoint health를
요구합니다. Apply increment 완료 전 comprehensive runner-side Policy, quota, identity, secret
evidence가 남아 있습니다.

## Private-everything tenant

Local command는 apply boundary를 laptop으로 옮기지 않습니다. Tenant가 Key Vault, state storage
또는 다른 data service를 private로 설정하는 경우 plan과 apply 모두 VNet-integrated self-hosted
runner에서 실행됩니다. Local CLI는 management-plane read를 사용하여 runner 경로가 필요한지
판단하고, 승인된 workflow를 시작하거나 찾고, 상태를 보고합니다.

Runner는 managed identity를 계속 사용합니다. `fdaictl`은 service-principal secret, Terraform
state, 생성된 database password 또는 Key Vault 값을 local machine으로 복사하지 않습니다.
Runner를 사용할 수 없으면 CLI는 local apply로 fallback하지 않고 blocker를 보고합니다.

## Configuration 및 secret 처리

Environment configuration은 schema validation을 거치며 package 외부에 저장됩니다. 생성된
config는 기본적으로 untracked 상태이며 secret 값 대신 reference를 포함합니다.

- **허용:** Environment name, region, feature flag, backend reference, repository name, approved
  artifact source.
- **허용되지 않음:** Password, access token, connection string, Terraform state, binary plan,
  upstream repository의 populated customer config.
- **Command history:** Secret 값을 command-line argument로 받지 않습니다.
- **Log:** Structured log는 correlation ID를 포함하며 구성된 sensitive field를 redact합니다.
- **Machine output:** JSON은 안정적인 영어 field name을 사용하며 secret material을 포함하지
  않습니다.

사용자가 보는 CLI text는 L2 product surface입니다. 영어 source message는 message catalog에,
한국어 translation은 일치하는 locale catalog에 보관하며 누락된 translation은 영어로
fallback합니다. Log, JSON field, verdict, evidence는 영어 전용 machine surface로 유지됩니다.

## 제공 순서

Remote apply를 노출하기 전에 읽기 전용 경계를 검증할 수 있도록 CLI를 작은 increment로
제공합니다.

| Increment | 상태 | 범위 | 종료 기준 |
|-----------|------|------|-----------|
| C1: Package, doctor 및 local security | 구현됨 | Console entry point, version output, toolchain 및 auth diagnostics, local onboarding config, local security audit | Source install이 deterministic text 및 JSON을 생성하고 target mismatch와 critical local posture가 identifier 또는 value를 노출하지 않고 fail closed 처리됨 |
| C2: 읽기 전용 preflight | 구현됨 | Static 및 Terraform-plan analysis, live Policy/quota/identity/secret probe, hash-only evidence를 사용하는 bounded runner TLS egress 구현 | Mock transport가 mutation 및 secret-value read가 없음을 입증하고 failed/incomplete probe가 clear result를 차단함 |
| C3: Plan workflow | 구현됨 | Opaque context digest, doctor/target guard, current GitHub dispatch API, exact-commit guard, private immutable plan upload, metadata-only status artifact, logical expiry, bounded physical cleanup 구현 | Plan-only가 기본이며 target identifier는 dispatch와 metadata에 없고 apply는 계속 unavailable |
| C4: Apply workflow | 구현됨 | Exact restore/verifier, complete runner Policy/quota/identity/secret 및 egress evidence, dual evidence digest, guard, approval, at-most-once claim, audit/status, Terraform convergence, migration, health check | Stale, mismatched, evidence-tampered, claimed, applied, expired, non-converged, unhealthy plan은 applied receipt를 생성할 수 없음 |
| C5: Release hardening | 부분 구현 | Ed25519 verification, signed stable/beta/development channel, atomic config-preserving upgrade/rollback state, deterministic tracked-file build, CycloneDX SBOM, double-build comparison, approval-gated artifact/optional GitHub Release 게시 구현, signed wheel, mirror, disconnected delivery는 남음 | 더 넓은 distribution channel 활성화 전 reproducible bundle publication 통과 |
| C6: Guided onboarding | 구현됨 | 순서가 고정된 doctor, private config, target guard, live preflight, plan-only runner dispatch, bounded sanitized status post-check | Stage-spy test가 fail-stop 순서와 guided path가 local apply를 import하거나 호출하지 않음을 입증 |

## 수락 기준

다음 기준을 test할 수 있으면 roadmap에서 implementation으로 승격할 준비가 된 것입니다.

- Clean host가 격리된 tool command 하나로 pinned CLI version을 설치할 수 있음.
- `doctor`가 workflow 제출 전에 잘못된 Azure subscription을 식별함.
- `deploy preflight`가 read-only이고 동일한 input에 byte-stable JSON을 생성함.
- `onboard guided`가 첫 failed stage에서 중지하고 local apply path를 노출하지 않음.
- Probe failure가 `clear`로 보고될 수 없음.
- Private-everything tenant가 항상 plan과 apply를 VNet runner로 routing함.
- Apply가 기록된 plan digest를 사용하고 stale 또는 mismatched plan을 차단함.
- Secret, state file, binary plan이 terminal output 또는 local machine에 도달하지 않음.
- CLI와 deployment bundle을 이전에 서명된 version으로 함께 rollback할 수 있음.

## 미결 질문

- 첫 wheel과 deployment bundle을 어떤 approved package index 및 release store에 게시할까요?
- Release pipeline에서 어떤 signature 및 attestation format을 표준으로 사용할까요?
- 각 environment의 최대 saved-plan retention period는 얼마인가요?
- `fdaictl deploy teardown`을 첫 apply release에 포함할까요? 아니면 teardown drill이 측정될
  때까지 별도의 guarded script로 유지할까요?

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구체적인 Azure inventory 및 onboarding | [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md) |
| Deployment lifecycle 및 rollback | [deployment-ko.md](deployment-ko.md) |
| Readiness finding 및 probe contract | [deployment-preflight-ko.md](deployment-preflight-ko.md) |
| Blocker를 Terraform toggle로 전환 | [preflight-active-reassembly-ko.md](preflight-active-reassembly-ko.md) |
| Private runner bootstrap | [../../../infra/bootstrap/README.md](../../../infra/bootstrap/README.md) |
| Product localization 규칙 | [../../../.github/instructions/language.instructions.md](../../../.github/instructions/language.instructions.md) |
