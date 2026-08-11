---
title: 폐쇄망 배포
translation_of: disconnected-deployment.md
translation_source_sha: c15a58bc0e48ba24d84aad8c7052f42957410063
translation_revised: 2026-08-11
---
# 폐쇄망 배포

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
| **Azure 도달성** | 비공개 엔드포인트, 또는 전혀 없음 | 컨트롤 플레인이 관리 plane, 시크릿 저장소, 이벤트 버스, 상태 저장소를 호출할 수 있는지 |
| **공용 산출물 egress** | allow-list, mirror, 또는 없음 | 공용 패키지 인덱스, Terraform 레지스트리, 공용 컨테이너 레지스트리에 도달할 수 있는지 |

대부분의 규제 테난트는 **비공개 Azure 도달성 + 공용 산출물 egress 없음**에 위치합니다.
컨트롤 플레인은 비공개 엔드포인트 위에서 정상 동작하고, 모든 빌드/install 입력은 내부 mirror나
서명된 매체에서 와야 합니다. 진짜 air 공백 - Azure 도달성도 없음 - 은
[완전 air 공백](#완전-air-gap)에서 다루는 더 좁은 프로파일입니다.

## 비공개 Azure, 공용 egress 없음

리포지토리가 처음부터 끝까지 지원하는 프로파일입니다.

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
GitHub에 등록된 실행기는 GitHub, 관리 plane, 신원 plane에 도달해야 하기 때문입니다.
폐쇄망은 `enable_public_egress = false`로 설정합니다. 공개 주소를 전혀 만들지 않고, 호스트는
등록된 실행기가 아니라 점프박스가 되며, 테난트가 관리 및 신원 plane으로 가는 자체
승인 경로를 공급합니다.

레지스트리가 비공개가 되면 런타임 이미지 빌드와 push도 같은 호스트에서 합니다.

### 3. 모든 빌드 입력을 내부 mirror로

| 입력 | 메커니즘 |
|------|----------|
| Base 컨테이너 이미지 | `--build-arg BASE_IMAGE_REGISTRY=<mirror>`. sha256 다이제스트는 `Dockerfile`에 pin된 채 남으므로 mirror는 바이트의 출처만 바꾸고 어떤 바이트가 수락되는지는 바꾸지 못합니다 |
| Python 패키지 | `infra/modules/preflight-toggles/python_index_url`이 내부 피드용 package-index 설정을 발행합니다 |
| 배포 시점 레지스트리 pull | `infra/modules/preflight-toggles/registry_source`가 공개 기본값에서 내부 레지스트리 mirror로 전환합니다 |
| Terraform 프로바이더 | offline kit이 pinned 프로바이더 mirror를 담고, offline 모드는 공개 레지스트리 대체 경로를 차단합니다 |

Base 이미지가 다이제스트 pin을 잃거나 레지스트리 호스트를 하드코딩하면
`scripts/quality/ci/check-ci-contracts.py`가 빌드를 실패시킵니다. Mirror 경계가 pin 없는 pull로
퇴화할 수 없습니다.

### 4. CLI와 번들을 서명된 offline kit으로 전달

release 엔지니어링이 connected 호스트에서 `scripts/deployment/release/stage-offline-kit.sh`로 kit을
staging합니다. 이 스크립트가 `fdai` wheel과 모든 transitive wheel, 서명된 배포 번들,
pinned Terraform binary 및 프로바이더 mirror, 정책 엔진 binary, software bill of materials를 모으고
`scripts/deployment/release/build-offline-kit.py`로 서명합니다. 매니페스트는 staged 트리에서
생성되므로 검증기가 거부할 내용을 증언할 수 없고, release 비공개 키는 kit에 들어가지
않습니다.

폐쇄망 쪽에서 `fdaictl provision inspect`는 매니페스트를 파싱하기 전에 서명을 검증하고, 정확한
CLI 및 platform 버전을 연결하며, symlink와 추가 파일을 거부하고, 모든 다이제스트를 스트리밍
합니다. 존재는 결코 신뢰가 아닙니다. 검증되지 않은 kit은 `candidate`로 남고, 거부된 내용은
`incomplete`입니다.

Kit의 CycloneDX 문서는 kit이 담은 모든 파일을 SHA-256과 함께 나열합니다. Kit은 인계에서
외부 공급망을 담는 쪽입니다. Terraform binary, 정책 엔진 binary, 그리고 mirror된 모든
프로바이더와 그 정확한 버전이 여기 있습니다. 서명은 문서가 변조되지 않았음을 증명하지만
아무것도 기술하지 않는 문서를 알아채지는 못합니다. 그래서 drill은 SBOM이 매니페스트가 나열한
모든 파일을 설명하는지 단정합니다.

### 5. 공용 egress 없이 룰 카탈로그 최신화

서명된 배포 번들은 이미 rule-catalog 스키마, 배포 프로파일, risk 분류를
담고 있으므로, 카탈로그 갱신은 코드와 같은 방식 - 새 서명 번들 - 으로 전달됩니다. 테난트가
수집 파이프라인을 직접 돌리고 싶으면 가져오기 도구가 로컬 디렉터리 또는 git 원격을 받으므로
upstream 출처의 내부 mirror가 지원되는 입력입니다. 런타임에 공개 출처 URL은 필요하지
않습니다
([rule-catalog-collection-ko.md](../rules-and-detection/rule-catalog-collection-ko.md)).

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

## 이미지로 전달된 분포의 프로비저닝

이미지를 넘기는 분포도 먼저 Azure 인벤토리를 만들어야 하는데, 런타임 이미지는 그것을 할 수
없습니다. `infra/`는 빌드 컨텍스트에서 제외되고, Terraform 바이너리는 설치되지 않으며, 진입점은
provisioner가 아니라 컨트롤 플레인입니다. `fdaictl` 콘솔 스크립트는 `fdai` 패키지와 함께 배포되어
이미지 안에 존재합니다. 그래서 이 간극은 오해하기 쉽습니다. 명령은 있고, 인프라 소스와 Terraform
바이너리는 없습니다.

따라서 폐쇄망 인계는 **아티팩트 두 개**입니다. 런타임 이미지, 그리고 wheel, `infra/`를 담은
배포 번들, pinned Terraform 바이너리 및 프로바이더 mirror, 정책 엔진, bill of materials를
싣고 있는 서명된 offline kit입니다.

| # | 단계 | 도구 | 상태 |
|---|------|------|------|
| 1 | Kit 검증 | `fdaictl provision inspect` | 구현됨. Trust 루트 배포 전까지 `candidate`로 보고 |
| 2 | 배포 번들 검증 | `fdaictl bundle verify` | 구현됨 |
| 3 | 런타임 이미지 부하 후 테난트 레지스트리에 push | VNet 호스트의 컨테이너 도구 | 운영자 단계 |
| 4 | Ops 허브 구축: 상태 계정, VNet, 배포 호스트 | `infra/bootstrap` | 구현됨. 테난트당 1회 |
| 5 | 번들에서 앱 계층 계획 | `fdaictl provision plan` | 구현됨. Kit의 pinned Terraform으로 번들 `infra/` 를 실행 |
| 6 | 적용 전에 계획 분석 | `fdaictl deploy preflight --terraform-plan` | 구현됨, 네트워크 불필요 |
| 7 | 적용 | 배포 호스트의 Terraform | 운영자 주도 |
| 8 | 상태 저장소 마이그레이션 | 같은 이미지를 실행하는 일회성 작업 | 구현됨 |
| 9 | License 토큰 주입 및 확인 | 시크릿 경로 + `fdaictl license inspect` | 구현됨 ([capability-licensing-ko.md](../fork-and-sequencing/capability-licensing-ko.md)) |
| 10 | 컨트롤 플레인 시작 | 이미지 진입점 | 구현됨 |

5단계는 예전에 체크리스트였습니다. Kit을 풀고, Terraform 바이너리를 찾고, 프로바이더 mirror 설정을
손으로 쓰고, 공개 레지스트리 대체 경로를 닫는 것을 잊지 않아야 했습니다. 이제 `fdaictl provision plan`이
그 단계를 소유합니다. Terraform 바이너리와 mirror를 **서명된 매니페스트**에서 해석하므로 kit 옆에 추가된
트리가 실행 대상을 결정할 수 없습니다. 생성되는 CLI 설정의 `direct` 블록은 모든 프로바이더를 제외하므로,
mirror에 없는 항목은 공개 레지스트리로 가는 대신 계획을 실패시킵니다. 자격증명 형태의 환경 변수만
통과시키며, binary 계획 과 그 SHA-256 다이제스트, 6단계가 소비하는 계획 JSON 을 산출합니다.

Kit의 내용을 **실행**하는 일은 그것을 **보고**하는 일보다 강한 증거를 요구합니다. `provision inspect`는
여전히 trust-root 재정의가 없고 검증되지 않은 kit을 `candidate`로 보고합니다. 운영자가 그 판단을
저울질할 수 있기 때문입니다. `provision plan`은 그럴 수 없습니다. 공급된 release 루트로 kit을 검증하고,
검증이 실패하면 계획을 거부합니다. 루트가 wheel에 pinned 상태로 배포되면 `--release-root`는 계획 수립은
수락하고 점검은 여전히 수락하지 않는 재정의가 됩니다.

인계를 계획하기 전에 짚어야 할 결과가 하나 있습니다. `fdaictl deploy plan`과 `deploy apply`는 GitHub
작업 흐름에 작업을 제출하므로, 그 도달성이 없는 테난트는 `manual` 전송 계층을 씁니다. 5단계는
`provision plan`, 7단계는 배포 호스트의 Terraform이며, 7단계의 exact-plan 승인 바인딩은 목표 동작으로
남아 있습니다.

## 네트워크 없이 전 경로 예행연습

`scripts/deployment/release/airgap-drill.sh`는 고객이 받는 것과 같은 두 단계로 인계를 실행합니다.
그래서 폐쇄망 경로가 주장이 아니라 실증됩니다. 단계 단계는 실제 `stage-offline-kit.sh`를
일회용 키로 실행하므로, 드릴 통과는 release 경로 자체를 실증합니다. Verify 단계는 경로도
이름 해석도 없는 네트워크 이름 공간 안에서 모든 폐쇄망 단계를 다시 실행합니다.

```bash
bash scripts/deployment/release/airgap-drill.sh
```

Verify 단계가 순서대로 단정하는 것: 이름 공간에 정말로 egress와 DNS가 없다, 서명된 kit이 검증된다,
서명된 번들이 검증된다, `terraform init`이 kit mirror만으로 모든 프로바이더를 해석한다,
`terraform validate`가 번들을 수락한다, `terraform test`가 mock 프로바이더로 계획 그래프를
평가한다, mirror 없이는 같은 `init`이 **실패한다**, `fdaictl license inspect`가 권한을
해석한다, 그리고 운영자가 실제로 실행하는 명령인 `fdaictl provision plan`이 스스로 같은 지점까지
도달하며 남은 것은 배포 입력뿐이다. 일곱 번째가 중요한 대조군입니다. 이것이 없으면 캐시된 플러그인
디렉터리가 아무것도 증명하지 않은 채 드릴을 통과시킬 수 있습니다. 아홉 번째는 해석되지 않은
프로바이더나 공개 레지스트리로 향하는 어떤 시도든 드릴을 실패시키도록 요구하므로, 깨진 mirror 고정이
누락된 변수인 척 통과할 수 없습니다.

드릴은 반복 실행할 수 있습니다. `--skip-stage`는 기존 kit으로 재검증하고, 번들 트리는 매 실행마다
다시 풉니다. Terraform이 그 안에 쓰기 때문입니다. 한 번만 통과하는 드릴은 회귀 검사가 아니라
시연입니다.

## 도구가 먼저 손을 뻗지 않습니다

`fdaictl provision inspect`는 공용 호스트 세 곳에 TLS 연결을 열어 connectivity를 판정합니다.
`--connectivity offline`이면 그 판정을 아예 건너뜁니다. 운영자가 이미 답을 줬기 때문입니다.
폐쇄망에서 불필요한 탐색은 보안팀에 설명해야 할 아웃바운드 시도 세 건이고, egress 로그의 항목
세 개이며, DNS가 질의를 받고 응답하지 않는 환경에서는 빠른 로컬 점검이어야 할 명령의 긴 정지입니다.
`auto`는 여전히 탐색합니다. 정말로 듣지 못했기 때문입니다.

## 검증기가 거부하는 것

Kit 검증기와 번들 검증기는 모두 아직 신뢰되지 않은 입력을 읽습니다. 그래서 둘 다 서명을
확인한 **뒤**가 아니라 **전에** 읽을 양을 제한하고, symlink를 통해 도달한 메타데이터를 거부하며,
나열할 수 없는 디렉터리에서 실패합니다. 마지막 항목이 보기보다 중요합니다. 경로 globbing은 볼 수
있었던 것만 조용히 돌려주므로, 서명자가 읽을 수 없는 디렉터리 아래의 내용이 빠진 트리에 서명하게
되고, 검증기는 잘린 트리를 완전한 것으로 수락하게 됩니다.

두 검증기는 의도적으로 대칭입니다. 같은 인계를 지키므로, 한쪽의 빈틈은 곧 양쪽의 빈틈입니다.

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
| Trust-root 의식이 실행되지 않아 wheel에 pinned 공개 루트가 없음 | 점검이 offline kit을 검증된으로 보고할 수 없고 `candidate` 또는 `review`로 남음 | [offline-trust-ceremony-ko.md](../../runbooks/offline-trust-ceremony-ko.md) |
| Kit staging이 release 작업 흐름에 연결되지 않음 | `stage-offline-kit.sh`가 kit을 조립하고 서명하지만, release는 여전히 운영자 보관 키로 수동 실행 | [provisioning-execution-profiles-ko.md](provisioning-execution-profiles-ko.md) |
| 초기화 적용 orchestration과 정리가 목표 동작으로 남음 | 운영자가 exact-plan 승인과 적용을 수동으로 진행 | [installable-deployment-cli-ko.md](installable-deployment-cli-ko.md) |
| 자체 호스팅 모델 어댑터 없음 | 클라우드 도달성이 없는 사이트는 적응형 경로가 아예 없음 | [tech-stack-ko.md](../architecture/tech-stack-ko.md) |

서명과 검증은 이미 네트워크와 무관합니다. Framework-surface 매니페스트와 offline kit 모두 커밋된
공개 키로 검증되며, 철회 조회도 인증서 체인도 필요 없습니다.

## 관련 문서

| 알아보려는 것 | 읽을 문서 |
|---------------|-----------|
| 비공개 networking Terraform 계층과 강화 knob | [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md) |
| Offline kit 계약, 빌드, 검증 | [provisioning-execution-profiles-ko.md](provisioning-execution-profiles-ko.md) |
| CLI 파사드, 서명된 번들, exact-plan 적용 | [installable-deployment-cli-ko.md](installable-deployment-cli-ko.md) |
| Offline trust 루트 확립과 교대 | [offline-trust-ceremony-ko.md](../../runbooks/offline-trust-ceremony-ko.md) |
| 거부된 kit 또는 차단된 계획에서 복구 | [deployment-recovery-ko.md](../../runbooks/deployment-recovery-ko.md) |
