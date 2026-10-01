---
title: Provisioning 실행 Profile
translation_of: provisioning-execution-profiles.md
translation_source_sha: 788fb5c966a993a40f391b8c95ffb45a97b64e86
translation_revised: 2026-10-01
---
# 프로비저닝 실행 프로파일

> **배포 방식:** [헌법](../architecture/fdai-constitution.md#article-1-purpose-and-scope)은 기여자 소스 배포와 서명된 오프라인 패키지라는 두 가지 설치 방식만 정의합니다. 이 문서의 설치 관문 중 헌법에 없는 것은 대체되었으며 더 이상 적용되지 않습니다.

이 문서는 계획된 `fdaictl` 배포판이 프로비저닝 호스트, connectivity 모드, 명령 전송 계층, 접근 경로를
선택하는 방법을 정의합니다. 또한 Terraform이 infrastructure 또는 역할 배정을 변경하기
전에 적용되는 사람 승인과 workload-identity 경계를 정의합니다.

> **범위:** Azure가 구현된 대상입니다. 이 프로파일은 Terraform 정본을 변경하거나
> 비공개 엔드포인트를 우회하는 로컬 대체 경로를 허용하지 않습니다.

패키지는 이미 보호된 저장소 workflow를 위한 내부 개발 및 스테이징 client를 유지합니다. 이
라이브러리는 맥락에 결속된 plan 또는 apply 요청을 전달하고 범위가 제한된 상태 산출물을
검증하며, 공개 tenant 프로비저닝 전송 수단이 아닙니다. 파사드는 변경 불가능한 요청 값, 하위
프로세스 전송, 전달, plan 메타데이터, apply 증적 및 provider-schema 근거를 목적별 모듈에
위임합니다. 이 분리는 명령, 자격 증명, Azure 역할 또는 apply 권한을 추가하지 않습니다.
명령 파사드는 source 및 offline-kit Foundation plan, 비공개 파일 시스템 처리, 대상 검사,
provider lock 검증 및 범위가 제한된 Terraform 실행도 하나의 목적별 plan 모듈에 위임합니다.
Parser handler, 출력 계약, 정확한 승인 요건 및 변경 권한은 바뀌지 않습니다.
## 한눈에 보는 설계

프로비저닝은 네 가지 선택을 독립된 축으로 취급합니다. 명령은 먼저 근거를 평가하며,
`dev` 같은 환경 이름 또는 운영자가 휠을 설치한 머신에서 권한을 추론하지
않습니다.

| 축 | 지원 값 | 선택 규칙 |
|----|---------|-----------|
| Connectivity | `online`, `offline` | 제한된 TLS 검사를 통과한 후에만 online 출처를 사용하고, 그렇지 않으면 signed offline 키트를 요구합니다. |
| 실행 호스트 | `existing-host`, `managed-vm` | 적합한 private-network 호스트를 재사용하고, 적합한 호스트가 없으면 managed VM을 생성합니다. |
| 전송 계층 | `manual` | 대상 환경 배포는 항상 로컬 조정기와 Managed Host를 사용합니다. GitHub Actions는 release를 빌드하고 게시할 수 있지만 대상 환경을 계획하거나 적용할 수 없습니다. |
| 소유권 | `fdai-managed` | 승인 후 Terraform이 선언된 리소스와 역할 배정을 관리합니다. |

### 활성 로그인 기반 독립 실행형 배포

제품의 기본 경험은 일반 PC에서 기본 배포를 한 뒤 같은 설치에 상세 프로비저닝을 진행하는 것입니다.
현재 명령 이름이 `provision azure`라고 해서 기본 서비스 가동 전에 모든 고급 구성을 끝내야 하는
것은 아닙니다. 단계 분리는 아래 목표 계약이며 이번 문서에서 구현된 CLI 옵션이나 명령을 추가하지 않습니다.

설치 패키지는 `az login` 후 하나의 기본 구독 배포 경계를 지원합니다.

```bash
fdaictl provision azure --offline-kit /media/fdai/fdai-kit.tar
# 같은 로컬 키트를 사용하는 소스 checkout 편의 wrapper입니다.
scripts/deployment/azure/fdai-up.sh --offline-kit /media/fdai/fdai-kit.tar
# 범위가 제한된 HTTPS 배포판을 위한 선택적 경로입니다.
fdaictl provision azure --online
```

두 명령은 활성 Azure CLI 사용자 컨텍스트에서만 테넌트와 구독을 결정합니다. 소스 checkout,
Git remote, GitHub 계정, GitHub 저장소, required CI 검사, 저장소 변수, 저장소 비밀, 작업 흐름
dispatch 또는 GitHub runner 등록이 필요하지 않습니다. Offline 모드는 완전한 키트를 로컬
경로에서 읽고 모든 공개 아티팩트 대체 경로를 차단합니다. Online 모드는 선택 사항으로 유지되며
각 리다이렉트에 접촉하기 전에 검증하는 제한된 HTTPS로 같은 형식을 다운로드합니다. 여기서
offline은 아티팩트가
오프라인이라는 뜻이며 선택한 Azure control plane 또는 Bastion 엔드포인트와 단절된다는 뜻은
아닙니다.

오프라인 재시도는 지정한 출처를 다시 읽고 보존된 스냅샷을 재검증하며 이전 상태를 교체하지 않고
새 실행 복사본을 사용합니다. 바이트가 바뀌거나 불완전하면 재시도를 중단합니다.
온라인 전송 진행 상황으로 전체 다운로드 예산 15분을 연장하지 않습니다. 소켓 읽기는 30초
제한을 유지하며 각 원시 읽기 사이에 사용 가능한 데이터를 반환합니다. 만료 시 새로 만든
부분 다운로드만 삭제하고 재시도하지 않습니다. 진행 중인 소켓 읽기로 전체 기한을 넘는 시간은 해당 읽기 한 번의 제한 이내입니다.

패키지는 키트와 별도로 release 및 bundle 검증 루트를 고정합니다. 완전한 키트에는 배포
bundle, Terraform과 OPA, provider mirror, runtime OCI archive, Console 콘텐츠, migration 지원
및 각 SBOM이 포함됩니다. Azure 변경 전에 서명, 정확한 파일 집합, 플랫폼, 소스 revision,
runtime 콘텐츠 검증을 완료합니다.
현재 관리 호스트 이미지와 완전한 키트 builder는 Linux x86_64를 지원합니다. 다른 호스트
운영체제나 아키텍처는 두 획득 모드 모두 시작 전에 차단하며 POSIX라는 사실만으로 Linux로 판단하지 않습니다.

Foundation 네트워크 검색은 안정 버전 Network API `2024-05-01`로 선택한 구독 전체의 기존
라우팅 테이블과 로컬 네트워크 게이트웨이를 읽습니다. 기존 리소스의 지역에서 지원하지 않을 수
있는 최신 버전을 Azure CLI가 자동 선택하게 두지 않습니다. 조회가 실패하면 검색을 중단하며
예약된 주소 범위를 누락하거나 공급자를 등록하거나 다른 버전으로 재시도하지 않습니다.

기본 배포는 미리 빌드하고 서명한 이미지 집합을 검증하고, API Server VNet Integration이 적용된
AKS 기반을 만들며, 기본 서비스 다섯 개를 배포합니다. 또한 배포에 연결된 라이선스를 설치하고
애플리케이션 활성화 전에 migration을 실행한 뒤 상태 검사와 두 번째 변경 없음 계획을 요구합니다.
테넌트 프로비저닝은 이미지를 빌드하거나 캡처하지 않습니다. 구독 정책이 첫 효과부터 비공개 접근을
요구하지 않는 한 기본 경로는 인증되고 제한된 공개 관리 접근을 유지합니다.

완전한 기본 이미지 집합은 설치 입력이며 이후 모든 변경의 배포 단위가 아닙니다. 기본 상태가
확인된 뒤에는 운영자가 선택한 서비스 후보 하나만 상위 공급망에서 빌드하고 게시한 다음, 변경하지
않은 서비스를 다시 빌드하거나 서명하거나 배포하지 않고 해당 digest 고정 서비스만 배포할 수
있습니다. 업데이트는 선택한 서비스 소유 상태만 계획하고 다른 서비스 상태를 보존하며 선택한
이미지와 상태를 다시 확인합니다. 변경된 wire contract, schema 또는 migration, sidecar, 공유 런타임
의존성 때문에 호환성 업데이트가 필요한 경우에만 여러 서비스를 함께 선택합니다.

선택한 비공개 애플리케이션 백엔드, 비공개 레지스트리 경로와 비공개 서비스 엔드포인트는 후속 상세
프로비저닝 계획에 포함합니다. 조건을 갖춘 현재 VM은 `existing-host`로 조정기와 실행 역할을 함께
맡을 수 있습니다. 정책이 기본 배포부터 비공개 접근을 요구하면 해당 호스트 또는 최소
`managed-vm` 경로가 변경 전에 접근 가능성을 검증해야 합니다. 비공개 작업을 부적합한 호스트로
우회하지 않습니다.

모든 변경 checkpoint는 exact-plan 승인, 변경 전 불변 claim, 범위가 제한된 중지 및 정리 경로,
대상 lock, 안정적 멱등성 및 독립적인 효과 재확인을 유지합니다. 기본 standalone `dev` 경로는
각 exact plan마다 현재 로컬 사용자 승인 하나를 받습니다. Staging과 production은 구성된 독립
정족수와 승인된 실행 호스트를 계속 요구합니다.
Apply 결과가 모호하면 다음 호출은 변경 없음 plan과 권위 있는 재확인만 실행합니다. 보존된
claim으로 apply를 반복하지 않습니다. Foundation run, network/state handoff, Entra binding,
provider 구성 또는 서명 키트가 바뀌면 별도의 준비 context가 필요합니다.
검증 plan이 zero change가 아니라 잔여 변경을 입증하면 원 claim은 불변으로 남습니다. 조정기는 원 claim과 갱신된 state에 연결한 별도 이름의 residual plan 하나만 제시할 수 있습니다. 새 exact residual 승인과 효과 전 residual claim이 필요하며 잔여 효과는 자동으로 실행되지 않습니다. Residual 효과가 모호하면 다른 apply가 아니라 검증만 허용합니다. 단계 완료에는 독립 재조회와 residual zero change가 필요합니다.
AKS baseline 복구에서 권위 있는 management-plane 재조회가 현재 기존 Key Vault 또는 document storage account를 public-disabled 상태로 보고하면 해당 focused private-access 복구를 선택할 수 있습니다. 복구는 검증된 Managed Host VNet을 결속하고 공유 양방향 애플리케이션 peering과 선택된 Key Vault 또는 Blob/DFS private endpoint 및 DNS link만 만들며 각 선택을 retained context에 기록합니다. 전체 설치를 상세 private-network profile로 묵시적으로 승격하지 않으며 각각 별도로 검토하는 residual plan에 계속 포함합니다. Focused 복구는 일반 substrate plan 전에 별도의 정확한 `access` plan과 승인을 거칩니다. Managed Host의 읽기 전용 data-plane probe가 성공해야 완료되므로 secret 및 filesystem 생성이 endpoint, DNS 또는 peering 전파와 경합할 수 없습니다.
Foundation이 실행기 VNet의 Blob 영역 링크를 이미 소유하면 집중 복구는 해당 링크를 하나로 유지하고 문서 엔드포인트 A 레코드를 기존 운영 영역에 씁니다. DFS 영역은 별도의 실행기 링크를 유지합니다.
호출 시간 예산은 준비 전에 시작합니다. 승인 대기와 애플리케이션 인계에는 현재 남은 시간을
사용하며 예산이 만료되면 다음 단계를 시작하거나 준비 완료 결과를 만들지 않습니다.
애플리케이션 확인에는 실제 터미널이 필요하며 두 확인 입력과 사용자 조회가 최대 10분의
한 구간을 공유합니다. 계획 만료나 호출 잔여 예산이 더 짧으면 그 시간으로 제한합니다.
`DeadlineTransport`는 기존 Bastion 명령과 파일 전송 각각을 같은 현재 예산으로 제한하고
입출력 후에도 만료를 검사합니다. 원래 터널은 자체적인 제한 시간 내 정리를 유지합니다.
신원 및 전송 실패에는 고정된 진단 메시지를 사용하며 원시 OS 및 자식 프로세스 예외의 명령
인자나 경로를 출력하지 않습니다. 효과 결과가 불명확하면 여전히 보존된 상태를 검토해야 합니다.

명령은 명시적 옵션 또는 문서화된 사용자 구성 경로에서 운영자 소유 mode-`0600` license issuer
key를 찾습니다. 키가 있으면 키를 복사하지 않고 배포 및 이미지에 연결된 token을 발급합니다.
미리 발급된 Trial token을 제공하면 같은 검증 및 전달 경로를 사용합니다. 둘 다 없으면 license
secret을 만들지 않고 관찰 전용 모드로 배포를 완료합니다. Token은 Bastion 표준 입력으로
전달되고 Managed Identity가 Key Vault에 기록합니다. 인자, Terraform 상태, portable 상태 또는
로그에는 포함되지 않습니다.

## 읽기 전용 검사

목표 명령은 초기화 계획을 만들기 전에 점검을 실행합니다.

```bash
fdaictl provision inspect --output json
```

점검은 로컬 Azure CLI, Terraform, 제한된 online 산출물 접근,
offline-kit 후보, Azure 워크로드 신원 엔드포인트를 검사합니다. `mutation_performed=false`,
필수 승인 정책과 정족수, 선택된 프로파일이 포함된 안정적인 JSON 계약을 반환합니다. 도구를
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
  --target-binding <sha256> \
  --connectivity online \
  --host existing-host \
  --transport manual \
  --access-method internal_ssh
```

대상 연결은 의도한 테넌트와 구독 쌍의 배포 로컬 다이제스트이며 원시 식별자가 아닙니다.
명령은 모든 `auto` 값을 거부하고 `.fdai/provisioning/profile.json`을 mode-`0700` 디렉터리
안에 파일 모드 `0600`으로 기록합니다. Offline 프로파일에는 `--artifact-source`가 필요합니다.
Temporary 공개 SSH에는 전체 주소 space보다 좁은 정본 출처 CIDR과 5-60분 접근
구간이 필요합니다. 대상 환경 배포 프로필은 `manual` 전송 계층만 허용합니다.

기존 대상은 `--force`를 명시하지 않으면 initialization을 차단합니다. Force는 symbolic
링크를 따라가거나 non-file 대상을 교체하지 않습니다. 프로파일 initialization은 Azure
리소스를 변경하지 않으며 JSON 출력에 `mutation_performed=false`를 기록합니다.

## 실행 호스트

### 기본 배포와 상세 프로비저닝

**설계와 검토:** 시작 전에 사설 인프라와 모든 운영 연동을 요구하면 설치 준비가 다시 설치의
선행 조건이 됩니다. 반대로 인증, 데이터 보호나 테넌트 필수 정책을 뒤로 미루면 안전하지 않은
기본 구성이 됩니다. PC의 Azure 내부 여부가 아니라 제품의 안전한 가동에 필요한 항목을 기준으로
단계를 나눕니다.

지원되는 CLI 실행 환경과 Azure 관리·신원 엔드포인트 접근이 있으면 일반 PC에서 배포를 시작할 수
있어야 합니다. 내부 VM, VPN, IMDS, PC에 연결한 Managed Identity나 미리 만든 Foundation은
모든 PC에 필요한 선행 조건이 아닙니다. 네이티브 운영체제 지원은 구현된 도구에 따르며, 지원되는
Linux 환경을 사용한다고 물리적 PC까지 Azure VM이어야 하는 것은 아닙니다.

| 단계 | 필요한 결과 | 이 단계의 선행 조건이 아닌 항목 |
|------|-------------|------------------------------|
| 기본 배포 | API Server VNet Integration, 워크로드 및 API 서버 전용 서브넷을 포함한 AKS Standard, 기본 서비스 5개와 필수 의존성, 영속 상태와 마이그레이션, 최소 워크로드 신원·RBAC, 인증된 Console URL, 제한된 공개 관리 접근, 독립적인 기본 상태 검증과 재시작 후 데이터 보존. | 비공개 엔드포인트, VNet 피어링, 비공개 DNS, 비공개 클러스터 모드, 전체 리소스 검색, 모델 용량 인증, 선택 연동·ChatOps, 조직별 정책, 운영 규모 튜닝이나 자율 실행 승격. |
| 상세 프로비저닝 | 기존 설치에 선택한 비공개 네트워크, 운영 범위, 모델, 연동, 정책과 용량을 추가하고 기능별 정확한 계획, 준비 상태와 승인을 검증. | 기본 구성 재설치, 검증된 리소스 재생성, 영속 데이터나 Trial 시작 시점 초기화. |

기본 배포에서는 대상·리전·런타임과 DB 선택·필수 비용 및 접근 결정만 수집하고 바뀌지 않은 선택은
재사용합니다. 최소 의존성과 구독의 필수 정책은 미룰 수 없습니다. 선택 설정은 사용할 수 없음으로
표시하며 가짜 상태나 근거로 대체하지 않습니다. [Trial 계약](installable-deployment-cli-ko.md#소스-출처와-trial)에
따라 기본 설치는 게시자 서명 키를 요구하지 않으며 이후 프로비저닝으로 Trial을 갱신하지 않습니다.

조정기는 PC에서 허용되는 관리 플레인 단계를 실행합니다. 기본 배포는 이후 네트워크 강화를 위한
구조를 예약하지만 시작 전에 PC 피어링, VM 신원 연결, 비공개 엔드포인트 생성 또는 Foundation
수동 구축을 요구하지 않습니다. 정책상 필요한 비공개 데이터 플레인 단계는 적합한 기존 호스트나
승인된 계획에 포함된 최소한의 설치기 관리 실행 경로를 사용합니다. 정책상 비공개여야 하는 서비스를
내부 실행 경로를 피하려고 공개하거나 기존 백엔드를 바꾸지 않습니다. 호스트 준비는 설치기의 작업이지
별도의 제품 단계가 아닙니다.

기본 Console 상태 검사가 통과하면 `/provisioning`에서 대상 피어 VNet, 주소 범위, 비공개 서비스,
DNS와 송신 정책을 수집할 수 있습니다. 브라우저는 내용 주소 기반 요청을 제출하며 배포 신원을
받거나 Terraform을 실행하지 않습니다. 보호된 실행기는 주소 겹침을 검증하고 정확한 계획을 만든
뒤 별도 사람 승인을 기다려 적용합니다. 공개 접근을 제거하기 전에 피어링, 경로, DNS, TLS, 신원과
엔드포인트 접근을 독립적으로 검증합니다. 효과가 불명확하면 검증만 재개합니다.

권위 있는 서비스 및 접근 검사가 통과한 뒤에만 기본 배포 성공을 보고합니다. 기본 서비스가
정상이면서 상세 프로비저닝은 미완료일 수 있으므로 `subscription_ready=false`만으로 기본 배포
실패로 보지 않습니다. 반대로 클러스터나 Console 화면만 있다고 기본 배포가 성공한 것은 아닙니다.
기존 결과 필드의 의미를 유지하고 새 단계별 계약은 구현 전에 정의합니다. 근거 없이 기존 전체
실행 증적을 기본 배포 성공으로 바꾸어 부르지 않습니다.

예: 노트북에서 기본 계획을 검토하고 서비스 검사 후 인증된 Console에 접속합니다. 이후 상세
프로비저닝에서 모델과 관리 리소스 범위를 설정하되 가동 중인 기본 구성을 다시 배포하거나 자율
실행 권한을 암묵적으로 부여하지 않습니다.

### 기존 호스트

조건을 갖춘 현재 내부 VM, 점프 서버 또는 배포 호스트에는 `existing-host`를 우선 사용합니다.
PC라고 부르거나 로컬 터미널을 사용한다고 외부 장비인 것은 아닙니다. 데스크톱 운영체제만으로
적합성을 추정하지 말고, 해당하는 경우 WSL의 Linux 도구를 포함해 실제 실행 환경을 확인합니다.
선택한 호스트에는 다음 조건이 필요합니다.

- 필요한 모든 비공개 엔드포인트에 대한 네트워크 및 비공개 DNS 도달 가능성.
- Azure CLI와 Terraform.
- 승인된 배포 역할이 있는 별도 워크로드 신원.
- Protected Terraform 백엔드와 계획 저장소에 대한 영속 접근.

수동 실행은 운영자가 이 호스트에서 `fdaictl`을 시작한다는 의미입니다. Terraform이
운영자의 interactive Azure 신원을 사용한다는 의미가 아닙니다. 필수 워크로드 신원이 없는 실행
호스트는 준비 미완료이지만, 조정기 역할만 하는 일반 PC까지 거부하지는 않습니다.
실행 Host에서 Azure CLI는 CLI 작업에 사용할 정확한 user-assigned identity를 검증합니다.
Terraform backend 및 provider 프로세스는 Azure CLI service-principal 세션이 아니라 해당하는
정확한 client ID의 네이티브 Managed Identity 인증을 사용하며, 실행 전에 상속된 다른 인증
선택자를 제거합니다.
허용되는 경우 적절한 범위의 기존 배포 신원을 재사용하며,
현재 Foundation 실행이 만든 호스트나 신원만 요구하지 않습니다. 신원 연결, 역할 변경과 네트워크
변경에는 여전히 검토된 범위와 정확한 승인이 필요합니다.

**설계와 검토:** 별도 관리 VM은 구현 방식 중 하나이지 현재 VM이 부적합하다는 근거가 아닙니다.
반대로 Azure 내부라는 사실만으로 특정 비공개 엔드포인트 접근이 증명되지는 않습니다. 대상, DNS,
경로, TLS, 백엔드 접근 권한과 실행 신원을 각각 확인합니다. 직접 VNet 피어링이 없다는 사실만으로
승인된 다른 경로까지 없다고 판단하지 않습니다. 다른 호스트 생성을 일률적으로 요구하는 대신
실패한 검사와 최소한의 수정 사항을 보고합니다.

적합한 동일 호스트에서 조정기와 실행을 함께 수행하면 두 번째 장비로의 SSH/Bastion 연결이나
소스 전송은 필요하지 않습니다. Foundation 인계는 검증된 리소스 정보와 권위 있는 Terraform
상태를 이어받는 절차이며 리소스나 애플리케이션 데이터 이동을 뜻하지 않습니다. 올바르게 보호된
기존 백엔드는 재사용합니다. 실제 이행이 필요한 경우에는 정확한 승인과 단일 소유권 검증을 유지합니다.
설치기의 완료 기록이 없다는 이유로 완료된 적용을 반복하거나 증적을 만들어내지 않습니다.

기존 호스트를 선택할 수 있다고 모든 공개 조정기 경로가 이를 구현한 것은 아닙니다. 지원하지 않는
진입점이나 복구 증적 경로는 호스트 적합성과 별개인 설치기 미구현 사항으로 보고합니다.
이번 문서 변경으로 해당 구현이나 배포까지 완료됐다고 주장하지 않습니다.

### Managed VM

적합한 기존 호스트가 없거나 정책상 전용 배포 호스트가 필요한 경우 `managed-vm`을 사용합니다.
조정기가 외부에 있다는 이유만으로 적합한 기존 호스트를 교체하지 않습니다. VM은 영속하게 유지하지만
일반적으로 deallocate합니다. Protected 상태, 계획, 승인, 감사 기록은 비공개 저장소에
남으므로 VM을 시작, 중지 또는 다시 빌드해도 배포 권한이 변경되지 않습니다.

점검은 기존 호스트의 적합성을 먼저 평가하며 VM을 생성하지 않습니다. 초기화 계획 수립은 승인
전에 VM, 네트워크, 신원, 역할, 접근, 비용, stop, 정리 효과를 보여 줍니다.

## 접근 선호 설정

Managed-host 접근 순서는 다음과 같이 고정합니다.

1. 승인된 내부 SSH.
2. Azure Policy와 배포 프로파일이 허용하는 경우 temporary public-IP SSH.
3. Azure Bastion.
4. 감사되는 비상 경로인 Azure Run Command 또는 등록된
   [범위 지정 Terraform 작업](#범위-지정-run-command-terraform).

신규 구독 Genesis는 이 목록을 차례로 대체 시도하지 않습니다. `access_method=bastion`인
프로파일은 기반 계층이 만든 정확한 Standard Bastion 네이티브 터널을 선택합니다. 등록 자료는
SSH 표준 입력으로만 전달하며 상태 인계는 고정된 같은 호스트 키 경계를 사용합니다.

`access_method=run_command`는 명시적으로 선택하며 Bastion의 자동 대체 경로가 아닙니다.
적격 Linux 배포 호스트에서 이미 연결되고 피어링된 비공개 경로를 통해 선택한 WSL 호스트로만
digest가 고정된 실행 묶음을 staging할 수 있습니다. 정확한 프로파일과 현재 사람 승인은 전체 대상
서술자, 작업 ID, 실행 묶음 증적 digest, 수신기 digest에 연결됩니다. 활성 사람 계정은 계산된 테넌트와 구독 binding에 일치해야 하며, 실제 Azure
재조회는 VM 리소스 ID, 비공개 주소, 배포 UAMI와 일치해야 합니다. 이 검증을 마친 뒤에만 조정기는
일회성 TLS 중계가 수신을 시작하거나 Action Run Command가 시작하기 전에 변경 불가능한 시작 기록을 남깁니다. 중계는 선택한 호스트의
비공개 출발지 주소만 허용합니다. WSL은 임시 인증서 digest를 고정하고, 고정 수신기와 묶음을
검증한 뒤 같은 중계로 형식이 지정된 근거를 반환합니다. SAS, 계정 키, bearer token, 임의 원격
스크립트, 클라우드 staging 산출물은 이 전송 경로의 범위 밖입니다. 결과가 불명확한 호출은 별도로
시작 기록을 남긴 검증 전용 호출을 한 번만 허용하며 추출이나 새 전송을 반복하지 않습니다. VM
수명 주기 승인은 별도 작업으로 유지하고 staging 증적은 Terraform 적용 권한을 부여하지 않습니다.
구현은 관리형 command 리소스가 아니라 Action Run Command(`az vm run-command invoke`)를
사용합니다. 정상 VM agent, WSL에서 중계 주소로 이어지는 기존 비공개 경로, 동시 command 1개,
4 KiB 응답 범위 안의 완료 표식, 서비스의 90분 상한 안에서 완료가 필요합니다. Linux 호스트는
검토된 비공개 주소와 포트를 바인딩할 수 있고 Python과 OpenSSL을 제공해야 합니다. 이 제한은
조정기의 더 짧은 기한을 완화하지 않습니다.
명시적 adapter는 승인 정족수 1인 `dev`에서만 사용할 수 있습니다. staging과 production은 이
전송 경로가 보호된 승인 정족수를 지원하고 검증할 때까지 차단합니다.

대상 지정 substrate 계획에는 격리 실행기 Event Hubs 역할과 수집 송신 역할처럼 AKS 워크로드가
시작할 때 필요한 모든 역할 할당이 포함됩니다. 배포 ID가 위임할 수 없는 구독 범위 역할은 대상에서
제외합니다.

### 범위 지정 Run Command Terraform

**설계와 검토:** Terraform 백엔드는 비공개이고 구독 정책이 공개 예외를 거부할 수 있으므로,
작업용 PC에서는 이 백엔드를 쓰는 루트를 초기화할 수 없습니다. 상태를 PC로 복사하거나 계정을
공개하면 상태 소유자가 둘이 되거나 정책이 약해집니다. 작은 변경마다 VPN, Bastion, SSH 대화형
세션을 열면 비공개 네트워크가 개발 병목이 됩니다. 직접 작성한 Run Command 스크립트는 네트워크
경로 문제는 피하지만 정확한 소스, 계획 연결, 복구 근거를 잃습니다.

`scripts/deployment/azure/scoped_terraform.py`를 사용하면 Azure Resource Manager에만 접근할 수
있는 일반 PC가 기존 관리형 배포 호스트에서 등록된 Terraform 범위 하나를 실행할 수 있습니다.

- 비공개 운영자 프로파일에는 정확한 테넌트, 구독, VM, 실행 주체 클라이언트 ID와 백엔드 계정,
  컨테이너, 상태 키, 리소스 그룹을 지정합니다. 승인 프로파일은 `dev-single-operator`만
  허용합니다. staging과 production은 이 경로가 보호된 승인 정족수를 지원할 때까지 차단합니다.
- 소스는 새로 fetch한 뒤 `origin/main`에 포함된 커밋에서 범위 루트를 `git archive`로 가져옵니다.
  고정 수신기 `scoped_terraform_receiver.py`도 같은 커밋에서 가져옵니다. 소스, 수신기, 변수
  digest와 백엔드, 실행 주체, VM은 내용 기반 작업 ID에 연결되며 수신기가 이 ID를 다시
  계산합니다.
- 변수 파일은 비공개여야 하고, 루트에 선언된 변수만 포함해야 하며, 비밀처럼 보이는 값을 담을 수
  없습니다. 백엔드 입력은 계정, 컨테이너, 키, 리소스 그룹만 허용합니다. SAS, 계정 키, bearer
  token, 클라이언트 비밀은 전송 경로를 지나지 않습니다.
- Action Run Command는 포함된 수신기와 payload의 digest를 검증하는 고정 부트스트랩 하나만
  전달합니다. 조정기는 스크립트를 명령줄 인수가 아니라 비공개 파일로 전달하고 크기를 192 KiB로
  제한합니다. 수신기는 3 KiB 이내의 결과 한 줄만 반환하며 Terraform 출력은 root 전용 호스트
  파일에 남습니다.
- 수신기는 정확한 실행 주체 클라이언트 ID와 테넌트로 IMDS 토큰을 요청하고, 상속된 자격 증명을
  지운 뒤 백엔드와 provider 모두 Managed Identity를 사용하도록 지정합니다. `backend "azurerm" {}`
  블록을 생성하고, 소스에 백엔드 블록이 있으면 거부하며, 초기화된 백엔드 연결을 검증합니다.
- `plan`은 등록된 주소만 대상으로 하고 다른 주소, 삭제, 교체를 모두 거부합니다. 삭제 모드는
  등록된 주소의 삭제만 허용합니다. PC는 검토 내용을 보여 주고, 로그인한 사람이
  `<mode> <계획 digest 앞 12자>`를 입력합니다. 승인에는 사람 개체 ID, 작업 ID, 계획 digest,
  1시간 만료 시각을 기록합니다.
- `apply`는 승인된 digest를 확인하고, 새로 만들기만 가능한 효과 전 시작 기록을 쓰고, 저장된
  계획을 한 번 적용하고, 완료 기록을 쓴 뒤 대상 범위 무변경 계획을 실행합니다. 완료 기록 없이
  시작 기록만 있으면 소스 리비전과 관계없이 같은 상태 대상의 새 계획과 적용을 막고, `verify`는
  절대 적용하지 않습니다. `apply`와 `verify`는 계획 시점에 보존한 소스 커밋을 다시 사용하므로
  이후 `main`에 병합이 생겨도 작업 하나가 나뉘지 않습니다. 이후 PC는 Azure
  Resource Manager로 결과 리소스를 읽고 범위별 권위 있는 속성을 비교합니다. 전송 시간 초과, 연결 끊김, 결과 줄 누락이 생기면 상태 대상에 비공개 모호성 표식을 남깁니다. 이후 계획과 적용은 막히며, 해당 호출 시작 이후의 모든 Run Command가 Azure Activity Log에서 종료 상태가 된 뒤에만 같은 작업의 `verify`를 실행합니다. 이미 실행 중인 명령에 대한 Azure `Conflict`는 모호성이 아니라 사용 중으로 보고합니다.

첫 범위인 `aks-container-insights`는 AKS Container Insights 데이터 수집 규칙과 클러스터 연결을
대상으로 합니다. `aks-inventory-observation-roles`는 substrate inventory의 Reader, Monitoring Reader, Log Analytics Reader, pipeline-stage Event Hubs 송신자 할당을 대상으로 하며, 조정기는 루트의 로컬 모듈 closure만 보내고 선언된 기존 상태 이동은 주소만 바꿀 수 있습니다. 거부된 계획은 범위 밖 주소를 최대 12개까지 반환합니다. 범위를 추가하려면 집중 테스트를 포함한 검토된 소스 변경이 필요합니다. Run
Command 권한은 이미 VM의 root 권한을 부여하므로 이 경로는 VM 권한을 늘리지 않습니다. 대신 기록되지
않던 수동 명령을 연결되고 복구 가능한 작업으로 대체합니다.

이 경로에는 다음 제한이 있습니다.

- 호스트에는 Terraform, Python 3, 커밋된 잠금 파일로 검증되는 provider 다운로드용 외부 연결이
  필요합니다.
- Action Run Command는 VM당 명령 하나, 4 KiB 응답, 90분 상한을 허용합니다.
- 계획, 시작 기록, 완료 기록은 현재 호스트에만 저장됩니다.

Temporary 공개 접근은 silent 대체 경로로 사용하지 않습니다. 계획에는 허용 목록에 포함된
출처 CIDR, 키 또는 certificate만 사용하는 SSH, 제한된 접근 구간, 공개 IP와 temporary
network-security 룰의 자동 제거가 필요합니다. `0.0.0.0/0`, password authentication,
persistent 공개 IP는 허용되지 않습니다. 정리는 연산 성공 기준의 일부입니다.
정리에 실패하면 연산은 불완전한으로 남고 감사 기록이 생성됩니다.

## Online 및 offline 전달

Online 전달은 선택적인 배포판 경로입니다. 공개 `fdai-deployment-cli` 패키지와 버전이
일치하는 완전한 서명 배포 키트를 사용합니다. 관리 호스트는 키트의 인증된 binary, provider,
runtime image 및 migration wheel만 사용합니다.

운영 검증에는 이 게시 경로가 필요하지 않습니다. 로컬에서 빌드하고 독립적으로 검증한 완전한
서명 키트 하나를 로컬 조정기에 제공하며, 어플라이언스 이미지는 만들지 않습니다.

목표 release 작업 흐름은 읽기 전용 작업에서 휠과 출처 분포를 한 번만 빌드하고 Python과
번들 버전이 일치하는지 검사합니다. 일치하는 signed 번들을 게시한 후에만 같은 산출물을
PyPI Trusted 발행으로 게시합니다. Publish 작업만 GitHub OIDC 권한을 받으며 장기
PyPI 토큰은 저장하지 않습니다.

공개 PyPI release 줄은 `0.1.0`에서 시작합니다. 기존 저장소 tag `v0.1.1`부터
`v0.1.12`까지는 pre-PyPI engineering 이정표이며 다시 작성하지 않습니다. 첫 공개 release는
정확한 게시 커밋에 `v0.1.0` tag를 생성합니다. `0.1.0`보다 높은 활성 pre-PyPI 번들
상태가 있는 installation은 fresh 공개 release 상태 또는 명시적 이행을 사용합니다.
`0.1.0`으로 semantic-version 업그레이드하는 것으로 처리하지 않습니다.

연결이 끊긴 Python 설치는 [패키지 보증](../architecture/package-assurance-ko.md)에 설명한
서명된 wheel 모음을 사용합니다. Deployment CLI wheel, 로컬 의존성 wheel,
`requirements.txt`, `SHA256SUMS`, detached Ed25519 서명 하나를 포함합니다. 표준 OpenSSL,
`sha256sum`, pip 명령으로 네트워크 호출 없이 검증하고 설치합니다.

개인 서명 키는 저장소와 패키지 외부에 보관하며 신뢰하는 공개 키는 별도로 제공합니다. Python
인터프리터, ABI, 플랫폼, 의존성 및 설치 검사는 pip가 담당합니다.

Terraform 바이너리, 공급자, 런타임 이미지, Console 파일 및 마이그레이션 산출물은 Python
패키지 내용이 아니라 배포 페이로드입니다. 배포 소유자는 배포가 해당 입력을 선택할 때 검증할 수
있지만, 패키지 완료에는 complete kit, signed root, TUF 의식, 중첩된 묶음 서명, SBOM, 출처
문서, 어플라이언스 또는 Azure 증적이 필요하지 않습니다.

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
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/deployment/provisioning-execution-profiles.md) |
| 설치 및 명령 계약 | [설치형 배포 CLI](installable-deployment-cli-ko.md) |
| Azure 인벤토리 및 초기화 리소스 | [배포 및 온보딩](deploy-and-onboard-ko.md) |
| 계획, release, 롤백 수명 주기 | [배포](deployment-ko.md) |
| 실행기와 human 신원 분리 | [보안 및 ID](../architecture/security-and-identity-ko.md) |
