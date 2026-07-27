---
title: 폐쇄망 배포
translation_of: disconnected-deployment.md
translation_source_sha: 39ae7f41513d42706b511438e04a576f2278c6a4
translation_revised: 2026-07-28
---
# 폐쇄망 배포

이 문서는 공용 인터넷 egress가 차단된 네트워크 - 규제받는 금융 테난트, sovereign enclave,
완전 air-gap 사이트 - 에 FDAI를 배포하는 단일 소유 문서입니다. 리포지토리가 이미 지원하는 것,
운영자가 직접 공급해야 하는 것, 완전한 폐쇄망 설치를 아직 막고 있는 gap을 명시합니다.

> **범위:** Azure가 구현된 대상입니다. 이 문서는 private networking Terraform 계층
> ([deploy-and-onboard-ko.md](deploy-and-onboard-ko.md)), artifact contract
> ([installable-deployment-cli-ko.md](installable-deployment-cli-ko.md)), profile 선택 규칙
> ([provisioning-execution-profiles-ko.md](provisioning-execution-profiles-ko.md))을 다시
> 서술하지 않습니다. 그것들을 순서로 엮습니다.

## 한눈에 보는 설계

"폐쇄망"은 하나의 설정이 아닙니다. 두 개의 독립된 속성이 이 문서가 얼마나 적용되는지를 결정하며,
테난트는 그 격자의 어느 위치에나 있을 수 있습니다.

| 속성 | 값 | 결정하는 것 |
|------|-----|-------------|
| **Azure 도달성** | private endpoint, 또는 전혀 없음 | 컨트롤 플레인이 management plane, secret store, event bus, state store를 호출할 수 있는지 |
| **공용 artifact egress** | allow-list, mirror, 또는 없음 | 공용 package index, Terraform registry, 공용 container registry에 도달할 수 있는지 |

대부분의 규제 테난트는 **private Azure 도달성 + 공용 artifact egress 없음**에 위치합니다.
컨트롤 플레인은 private endpoint 위에서 정상 동작하고, 모든 build/install 입력은 내부 mirror나
서명된 매체에서 와야 합니다. 진짜 air gap - Azure 도달성도 없음 - 은
[완전 air gap](#완전-air-gap)에서 다루는 더 좁은 profile입니다.

## Private Azure, 공용 egress 없음

리포지토리가 처음부터 끝까지 지원하는 profile입니다.

### 1. 모든 서비스를 private으로 provision

`enable_private_networking = true`로 설정합니다. 배포는 secret store, 두 event-bus shard,
state store, blob 및 data lake storage, model endpoint에 virtual network, private endpoint,
linked private DNS를 provision합니다. Delegated-subnet state-store mode가 필요하면
`enable_private_postgres = true`를 추가합니다.

`acr_sku = "Premium"`도 설정합니다. Private link는 Premium 전용 registry 기능이므로 Basic이나
Standard registry는 의도적으로 public으로 남습니다. Private 경로 없이 닫으면 모든 image pull이
깨지기 때문입니다. Premium이면 registry는 public network access를 잃고 자체 private endpoint를
받습니다.

코어 엔진과 executor는 어떤 profile에서도 public inbound endpoint가 없습니다. Ingress는 event
bus이고 egress는 allow-list 기반 기본 거부입니다
([security-and-identity-ko.md](../architecture/security-and-identity-ko.md)).

### 2. 네트워크 내부에서 배포

Private 전용 secret store와 private state account는 운영자 워크스테이션에서 도달할 수 없습니다.
`terraform apply`는 그 endpoint에 네트워크 시야가 있는 호스트 - virtual network 내부의
self-hosted runner 또는 점프박스 - 에서 실행해야 합니다. `infra/bootstrap` 계층이 그 지속적 hub를
세우고, `scripts/deployment/azure/check-runner-egress.py`가 runner가 실제로 도달 가능한
allow-list 호스트를 기록합니다. 따라서 plan은 자신의 네트워크 위치를 가정이 아니라 증거로
가지고 다닙니다.

그 계층은 기본적으로 outbound 경로 하나 - static public IP를 가진 NAT gateway - 를 만듭니다.
GitHub에 등록된 runner는 GitHub, management plane, identity plane에 도달해야 하기 때문입니다.
폐쇄망은 `enable_public_egress = false`로 설정합니다. Public 주소를 전혀 만들지 않고, 호스트는
등록된 runner가 아니라 점프박스가 되며, 테난트가 management 및 identity plane으로 가는 자체
승인 경로를 공급합니다.

Registry가 private이 되면 runtime image 빌드와 push도 같은 호스트에서 합니다.

### 3. 모든 build 입력을 내부 mirror로

| 입력 | 메커니즘 |
|------|----------|
| Base container image | `--build-arg BASE_IMAGE_REGISTRY=<mirror>`. sha256 digest는 `Dockerfile`에 pin된 채 남으므로 mirror는 바이트의 출처만 바꾸고 어떤 바이트가 수락되는지는 바꾸지 못합니다 |
| Python package | `infra/modules/preflight-toggles/python_index_url`이 내부 feed용 package-index 설정을 emit합니다 |
| 배포 시점 registry pull | `infra/modules/preflight-toggles/registry_source`가 public 기본값에서 내부 registry mirror로 전환합니다 |
| Terraform provider | offline kit이 pinned provider mirror를 담고, offline mode는 public registry fallback을 차단합니다 |

Base image가 digest pin을 잃거나 registry host를 하드코딩하면
`scripts/quality/ci/check-ci-contracts.py`가 빌드를 실패시킵니다. Mirror seam이 pin 없는 pull로
퇴화할 수 없습니다.

### 4. CLI와 bundle을 서명된 offline kit으로 전달

Release 엔지니어링이 connected host에서 `scripts/deployment/release/stage-offline-kit.sh`로 kit을
staging합니다. 이 스크립트가 `fdai` wheel과 모든 transitive wheel, 서명된 deployment bundle,
pinned Terraform binary 및 provider mirror, 정책 엔진 binary, software bill of materials를 모으고
`scripts/deployment/release/build-offline-kit.py`로 서명합니다. Manifest는 staged tree에서
생성되므로 verifier가 거부할 내용을 증언할 수 없고, release private key는 kit에 들어가지
않습니다.

폐쇄망 쪽에서 `fdaictl provision inspect`는 manifest를 파싱하기 전에 signature를 검증하고, 정확한
CLI 및 platform version을 binding하며, symlink와 추가 file을 거부하고, 모든 digest를 streaming
합니다. 존재는 결코 신뢰가 아닙니다. 검증되지 않은 kit은 `candidate`로 남고, 거부된 내용은
`incomplete`입니다.

### 5. 공용 egress 없이 rule catalog 최신화

서명된 deployment bundle은 이미 rule-catalog schema, deployment profile, risk classification을
담고 있으므로, catalog 갱신은 코드와 같은 방식 - 새 서명 bundle - 으로 전달됩니다. 테난트가
collection pipeline을 직접 돌리고 싶으면 fetcher가 local directory 또는 git remote를 받으므로
upstream source의 내부 mirror가 지원되는 입력입니다. 런타임에 public source URL은 필요하지
않습니다
([rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md)).

### 6. 조작된 증거가 아니라 저하된 증거를 기대할 것

제한된 egress는 컨트롤 플레인이 관찰할 수 있는 것을 바꾸며, 모든 fallback은 순서가 있고
fail-closed입니다.

- **인벤토리**: resource-graph query 경로가 먼저, 그다음 검증된 private-link management 경로,
  shard된 management list 작업, 범위가 명시된 authoritative inventory, activity-log 연속성,
  마지막으로 서명된 declarative snapshot입니다. 실패한 경로는 마지막 완전한 graph를 유지하고
  stale로 표시하며, 빈 graph를 절대 게시하지 않습니다.
- **아이덴티티**: 테난트 discovery endpoint에 도달할 수 없으면 `FDAI_ENTRA_JWKS_URI`를
  override합니다 ([user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md)).
- **적응형 결정**: model 경로를 사용할 수 없으면 적응형 능력은 unavailable을 보고하고 해당 작업은
  deterministic-only로 남습니다. 자율성은 저하될 뿐 fail-open하지 않습니다.

## 이미지로 전달된 distribution의 provisioning

이미지를 넘기는 distribution도 먼저 Azure 인벤토리를 만들어야 하는데, 런타임 이미지는 그것을 할 수
없습니다. `infra/`는 빌드 컨텍스트에서 제외되고, Terraform 바이너리는 설치되지 않으며, 진입점은
provisioner가 아니라 컨트롤 플레인입니다. `fdaictl` console script는 `fdai` 패키지와 함께 배포되어
이미지 안에 존재합니다. 그래서 이 간극은 오해하기 쉽습니다. 명령은 있고, 인프라 소스와 Terraform
바이너리는 없습니다.

따라서 폐쇄망 인계는 **아티팩트 두 개**입니다. 런타임 이미지, 그리고 wheel, `infra/`를 담은
deployment bundle, pinned Terraform 바이너리 및 provider mirror, 정책 엔진, bill of materials를
싣고 있는 서명된 offline kit입니다.

| # | 단계 | 도구 | 상태 |
|---|------|------|------|
| 1 | Kit 검증 | `fdaictl provision inspect` | 구현됨. Trust root 배포 전까지 `candidate`로 보고 |
| 2 | Deployment bundle 검증 | `fdaictl bundle verify` | 구현됨 |
| 3 | 런타임 이미지 load 후 테난트 registry에 push | VNet 호스트의 컨테이너 도구 | 운영자 단계 |
| 4 | Ops hub 구축: state account, VNet, 배포 호스트 | `infra/bootstrap` | 구현됨. 테난트당 1회 |
| 5 | Bundle에서 app 계층 plan | `fdaictl provision plan` | 구현됨. Kit의 pinned Terraform으로 bundle `infra/` 를 실행 |
| 6 | Apply 전에 plan 분석 | `fdaictl deploy preflight --terraform-plan` | 구현됨, 네트워크 불필요 |
| 7 | Apply | 배포 호스트의 Terraform | 운영자 주도 |
| 8 | State store 마이그레이션 | 같은 이미지를 실행하는 일회성 job | 구현됨 |
| 9 | License token 주입 및 확인 | Secret 경로 + `fdaictl license inspect` | 구현됨 ([capability-licensing-ko.md](../fork-and-sequencing/capability-licensing-ko.md)) |
| 10 | 컨트롤 플레인 시작 | 이미지 진입점 | 구현됨 |

5단계는 예전에 체크리스트였습니다. Kit을 풀고, Terraform 바이너리를 찾고, provider mirror 설정을
손으로 쓰고, public registry fallback을 닫는 것을 잊지 않아야 했습니다. 이제 `fdaictl provision plan`이
그 단계를 소유합니다. Terraform 바이너리와 mirror를 **서명된 manifest**에서 해석하므로 kit 옆에 추가된
트리가 실행 대상을 결정할 수 없습니다. 생성되는 CLI 설정의 `direct` 블록은 모든 provider를 제외하므로,
mirror에 없는 항목은 public registry로 가는 대신 plan을 실패시킵니다. 자격증명 형태의 환경 변수만
통과시키며, binary plan 과 그 SHA-256 digest, 6단계가 소비하는 plan JSON 을 산출합니다.

Kit의 내용을 **실행**하는 일은 그것을 **보고**하는 일보다 강한 증거를 요구합니다. `provision inspect`는
여전히 trust-root override가 없고 검증되지 않은 kit을 `candidate`로 보고합니다. 운영자가 그 판단을
저울질할 수 있기 때문입니다. `provision plan`은 그럴 수 없습니다. 공급된 release root로 kit을 검증하고,
검증이 실패하면 plan을 거부합니다. Root가 wheel에 pinned 상태로 배포되면 `--release-root`는 planning은
수락하고 inspection은 여전히 수락하지 않는 override가 됩니다.

인계를 계획하기 전에 짚어야 할 결과가 하나 있습니다. `fdaictl deploy plan`과 `deploy apply`는 GitHub
workflow에 작업을 제출하므로, 그 도달성이 없는 테난트는 `manual` transport를 씁니다. 5단계는
`provision plan`, 7단계는 배포 호스트의 Terraform이며, 7단계의 exact-plan 승인 바인딩은 목표 동작으로
남아 있습니다.

## 네트워크 없이 전 경로 예행연습

`scripts/deployment/release/airgap-drill.sh`는 고객이 받는 것과 같은 두 단계로 인계를 실행합니다.
그래서 폐쇄망 경로가 주장이 아니라 실증됩니다. Stage 단계는 실제 `stage-offline-kit.sh`를
일회용 key로 실행하므로, 드릴 통과는 release 경로 자체를 실증합니다. Verify 단계는 route도
name resolution도 없는 network namespace 안에서 모든 폐쇄망 단계를 다시 실행합니다.

```bash
bash scripts/deployment/release/airgap-drill.sh
```

Verify 단계가 순서대로 단정하는 것: namespace에 정말로 egress와 DNS가 없다, 서명된 kit이 검증된다,
서명된 bundle이 검증된다, `terraform init`이 kit mirror만으로 모든 provider를 해석한다,
`terraform validate`가 bundle을 수락한다, `terraform test`가 mock provider로 plan graph를
평가한다, mirror 없이는 같은 `init`이 **실패한다**, `fdaictl license inspect`가 entitlement를
해석한다. 일곱 번째가 중요한 대조군입니다. 이것이 없으면 캐시된 plugin 디렉터리가 아무것도 증명하지
않은 채 드릴을 통과시킬 수 있습니다.

드릴은 의도적으로 plan 평가에서 멈춥니다. 실제 `terraform apply`는 여전히 테난트의 승인된 private
관리 평면 경로가 필요하며, 그것을 로컬에서 시뮬레이션했다고 주장하는 것은 이 설계가 피하려는 종류의
주장입니다. 드릴의 서명 key는 work 디렉터리 안의 일회용 key이며 리포지토리 자산이 되지 않습니다.

## 완전 air gap

Azure 도달성이 전혀 없는 사이트도 결정론적 코어는 돌릴 수 있습니다. 정책 엔진은 image 안의 정적
binary이고, rule catalog와 ontology는 파일이며, declarative inventory 어댑터는 클라우드 어댑터가
만족하는 것과 같은 `Inventory` contract로 손으로 작성한 resource graph를 제공합니다. 그 사이트가
얻지 못하는 것은 실시간 클라우드 증거이므로, 클라우드 리소스에 대한 자율 조치는 구조적으로 범위
밖입니다.

이 profile은 아래의 trust root가 확립될 때까지 **참고용**이며, sovereign 배포는 별도의 규제 및
residency 검토를 추가로 요구합니다
([architecture-review-board-ko.md](../architecture/architecture-review-board-ko.md)).

## 완전한 폐쇄망 설치를 아직 막는 것

| Gap | 오늘의 영향 | 소유 문서 |
|-----|-------------|-----------|
| Trust-root 의식이 실행되지 않아 wheel에 pinned public root가 없음 | inspection이 offline kit을 verified로 보고할 수 없고 `candidate` 또는 `review`로 남음 | [offline-trust-ceremony-ko.md](../../runbooks/offline-trust-ceremony-ko.md) |
| Kit staging이 release workflow에 연결되지 않음 | `stage-offline-kit.sh`가 kit을 조립하고 서명하지만, release는 여전히 operator 보관 key로 수동 실행 | [provisioning-execution-profiles-ko.md](provisioning-execution-profiles-ko.md) |
| Bootstrap apply orchestration과 teardown이 목표 동작으로 남음 | 운영자가 exact-plan 승인과 apply를 수동으로 진행 | [installable-deployment-cli-ko.md](installable-deployment-cli-ko.md) |
| Self-hosted model 어댑터 없음 | 클라우드 도달성이 없는 사이트는 적응형 경로가 아예 없음 | [tech-stack-ko.md](../architecture/tech-stack-ko.md) |

서명과 검증은 이미 네트워크와 무관합니다. Framework-surface manifest와 offline kit 모두 커밋된
public key로 검증되며, revocation 조회도 인증서 체인도 필요 없습니다.

## 관련 문서

| 알아보려는 것 | 읽을 문서 |
|---------------|-----------|
| Private networking Terraform 계층과 hardening knob | [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md) |
| Offline kit contract, build, verification | [provisioning-execution-profiles-ko.md](provisioning-execution-profiles-ko.md) |
| CLI facade, 서명된 bundle, exact-plan apply | [installable-deployment-cli-ko.md](installable-deployment-cli-ko.md) |
| Offline trust root 확립과 rotation | [offline-trust-ceremony-ko.md](../../runbooks/offline-trust-ceremony-ko.md) |
| 거부된 kit 또는 차단된 plan에서 복구 | [deployment-recovery-ko.md](../../runbooks/deployment-recovery-ko.md) |
