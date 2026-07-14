---
title: 설치형 배포 CLI
translation_of: installable-deployment-cli.md
translation_source_sha: ada8f4c995cb6a6096a87ca064cfb1c502b3bf95
translation_revised: 2026-07-14
---
# 설치형 배포 CLI

이 문서는 FDAI의 목표 설치 및 배포 경험을 정의합니다. 운영자는 격리된 Python CLI 도구를
설치하고, 읽기 전용 배포 preflight를 실행한 다음, 로컬 머신을 통해 비밀을 이동하지 않고
승인된 Terraform plan을 배포 runner에 제출할 수 있습니다.

> **상태:** 이 문서는 목표 설계입니다. 여기에서 설명하는 `fdaictl` 진입점, release bundle,
> 명령은 아직 제공되지 않습니다.
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

일회성 실행 또는 CI job에는 임시 환경을 사용합니다.

```bash
uvx --from fdai==<version> fdaictl deploy preflight --environment dev
```

`uv`를 사용할 수 없을 때는 `pipx`를 권장 fallback으로 사용합니다. Virtual environment
안에서 직접 `pip install`하는 방식도 지원하지만 system Python에 설치하는 것은 권장하지
않습니다. Installer는 Azure CLI, Terraform, GitHub CLI 또는 다른 system tool을 자동으로
설치하거나 업그레이드하지 않습니다. `fdaictl doctor`는 누락되거나 호환되지 않는 tool과
수정 방법을 보고합니다.

> 이 명령들은 목표 interface입니다. Package와 console entry point가 release로 게시되기
> 전에는 실행하지 마세요.

## 명령 모델

명령은 diagnosis, onboarding, deployment, status를 중심으로 구성됩니다. Mutation으로 이어질
수 있는 모든 명령은 remote execution boundary를 명확하게 표시합니다.

| 명령 | 목적 | Azure mutation |
|------|------|----------------|
| `fdaictl version` | CLI, bundle, schema, compatibility version 표시 | 없음 |
| `fdaictl doctor` | Python, Azure CLI, Terraform, GitHub CLI, 인증, local config 검사 | 없음 |
| `fdaictl onboard init` | Schema-validated, untracked environment configuration 생성 | 없음 |
| `fdaictl deploy preflight` | Static 및 live read-only deployment blocker 수집 | 없음 |
| `fdaictl deploy plan` | 승인된 runner에서 Terraform plan 생성 및 분석 | 없음 |
| `fdaictl deploy apply --plan-id <id>` | 정확히 승인된 plan을 remote apply에 제출 | 있음, runner에서 실행 |
| `fdaictl deploy status` | Workflow, runner, plan, deployment status 조회 | 없음 |
| `fdaictl deploy teardown` | 보호된 environment teardown workflow 제출 | 있음, runner에서 실행 |

초기 구현은 임의의 Terraform argument를 노출하지 않는 것이 좋습니다. 지원되는 environment와
feature 설정은 validated configuration schema에서 가져옵니다. 향후 명시적인 escape hatch가
추가된다면 audit되어야 하며 command line에서 secret 값을 받지 않아야 합니다.

## Preflight 계약

`fdaictl deploy preflight`는 기존 `PreflightAnalyzer`의 읽기 전용 composition root입니다.
CLI 안에 두 번째 readiness rule 집합을 구현하지 않고 공유 report 및 probe 계약을 재사용하는
것이 좋습니다.

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

## Plan 및 apply 무결성

`fdaictl deploy plan`은 plan-only workflow를 제출하고 opaque plan ID, plan digest, expiry time,
workflow URL을 반환합니다. Terraform plan file에는 state에서 파생된 민감한 값이 포함될 수
있으므로 local CLI는 binary Terraform plan을 download하거나 출력하지 않습니다.

`fdaictl deploy apply --plan-id <id>`는 다음 검사를 모두 통과한 경우에만 정확히 저장된 plan을
적용합니다.

- Plan이 동일한 subscription, environment, bundle digest, commit에 대해 생성됨.
- Plan이 만료되지 않았고 이미 적용되지 않음.
- Preflight report에 enforce-mode blocker가 없음.
- 호출자가 apply를 명시적으로 요청했고 workflow approval policy를 충족함.
- Runner identity와 backend configuration이 기록된 plan context와 일치함.

보호된 workflow store는 짧게 구성된 retention period 동안 plan을 유지합니다. Log에는 plan
summary와 digest만 노출합니다. Plan file, state, credential 또는 secret 값은 노출하지 않습니다.

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

| Increment | 범위 | 종료 기준 |
|-----------|------|-----------|
| C1: Package 및 doctor | Console entry point, version output, toolchain 및 auth diagnostics | 격리된 환경에 설치되고 deterministic text 및 JSON 생성 |
| C2: 읽기 전용 preflight | 기존 analyzer, Terraform plan JSON, Azure read adapter | Network-free test가 통과하고 live probe가 Azure를 mutate할 수 없음 |
| C3: Plan workflow | Bundle 확인, signature 검사, remote plan 제출, status | Plan-only가 기본이고 검증 가능한 digest 반환 |
| C4: Apply workflow | Exact-plan apply, approval, expiry, audit, post-check | Stale, mismatched 또는 blocked plan을 apply할 수 없음 |
| C5: Release hardening | Signed wheel 및 bundle, SBOM, internal mirror 및 disconnected bundle 지원 | 재현 가능한 install 및 rollback 입증 |

## 수락 기준

다음 기준을 test할 수 있으면 roadmap에서 implementation으로 승격할 준비가 된 것입니다.

- Clean host가 격리된 tool command 하나로 pinned CLI version을 설치할 수 있음.
- `doctor`가 workflow 제출 전에 잘못된 Azure subscription을 식별함.
- `deploy preflight`가 read-only이고 동일한 input에 byte-stable JSON을 생성함.
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
