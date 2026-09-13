---
title: 설치형 배포 CLI
translation_of: installable-deployment-cli.md
translation_source_sha: 547aa0d8da6d5584b5f028ecc618f804bd1438c8
translation_revised: 2026-09-13
---

# 설치형 배포 CLI

이 문서는 공개 FDAI 배포 명령을 정의합니다. 운영자는 Azure 로그인 후 하나의 로컬 조정기를
실행하고, Terraform 적용과 비공개 데이터 플레인 작업은 대상 Virtual Network 내부의 Managed
Host에서 실행됩니다.

> **실행 경계:** Terraform은 인프라 단일 기준으로 유지됩니다. `fdaictl`은 검증, 산출물 확인,
> 정확한 계획 승인, Managed Host 조정, 복구 및 배포 후 검사를 담당합니다. 대상 환경 배포에는
> GitHub Actions를 사용하지 않습니다.
>
> **구현 대상:** Azure만 구현되어 있습니다. Azure 이외 provider는 연기되었습니다.

## 한눈에 보는 설계

| 항목 | 결정 |
|------|------|
| 운영자 명령 | `fdaictl provision azure` |
| 소스 checkout 명령 | `scripts/deployment/azure/fdai-up.sh` |
| 인프라 엔진 | 서명된 완전한 키트의 Terraform |
| 대상 선택 | 활성 대화형 Azure CLI 사용자 |
| 적용 위치 | 대상 VNet 내부의 Managed Host |
| 연결된 산출물 원본 | 범위가 제한된 HTTPS로 받는 버전 지정 서명 키트 |
| 폐쇄망 산출물 원본 | digest로 고정된 배포 어플라이언스에 포함된 완전한 서명 키트 |
| 승인 | 각 정확한 계획 digest에 연결된 현재 사람 승인 |
| 실행 신원 | Managed Host의 사용자 할당 Managed Identity |
| GitHub 의존성 | 대상 환경 배포에는 없음 |

GitHub Actions는 소스를 검증하고 이미지를 빌드하며 서명된 release를 게시할 수 있습니다. 대상
환경을 계획, 적용, 재개 또는 제거할 수 없습니다.

## 운영자 경험

소스 checkout에서는 다음 명령을 실행합니다.

```bash
az login
scripts/deployment/azure/fdai-up.sh --region <azure-region>
```

래퍼는 필요할 때 잠긴 로컬 환경을 만들고 다음 명령을 호출합니다.

```bash
fdaictl provision azure --online --region <azure-region>
```

산출물 오프라인 배포에는 로컬 완전한 키트와 동일한 조정기를 사용합니다.

```bash
fdaictl provision azure \
  --offline-kit /media/fdai/fdai-deployment-kit.tar.gz \
  --region <azure-region>
```

명령은 활성 Azure CLI 사용자에서만 tenant와 subscription을 결정합니다. GitHub 계정, Git
remote, 저장소 변수, 저장소 비밀, workflow dispatch 또는 등록된 GitHub runner가 필요하지
않습니다.

### 명령을 안전하게 탐색

인자 없이 `fdaictl`을 실행하면 `fdaictl --help`와 같은 개요를 표시하고 종료 코드 `0`으로
끝납니다. `fdaictl provision`처럼 명령 그룹만 입력하면 해당 그룹의 도움말을 표시합니다.
도움말과 최상위 `--version` 별칭은 로그인, Azure 조회, 산출물 다운로드, 배포 상태 생성을
수행하지 않습니다. 기존 `version --output json` 계약도 유지합니다.

개요는 각 명령의 역할과 로그인, 도구 점검, 배포의 짧은 예제를 제공합니다. 개별 명령 도움말은
필수 산출물 원본 선택, 기본값, 단위, 출력 모드, 고급 선택 입력을 설명합니다.
`onboard guided`는 실제 배포가 아니라 모의 실행임을 명시합니다. 도움말은 stdout의 정적 일반
텍스트이며 대시보드를 시작하거나 stdin을 읽지 않습니다.
파서는 실제 Azure 배포가 시작될 때까지 기본 홈 디렉터리를 조회하지 않습니다.

명시적인 도움말 또는 버전 요청이 없으면, 알 수 없는 명령과 옵션, 불완전한 개별 명령 인자,
충돌하는 산출물 원본은 다음 도움말 안내와 함께 stderr의 사용법 오류로 처리하고 종료 코드
`2`를 반환합니다. 오류가 기본 배포나 자동 재시도로 바뀌지 않습니다. 긴 옵션은 축약하지 않고
전체 이름을 입력해야 합니다.

### 터미널 진행 상태

대화형 텍스트 출력은 stderr에 박스 없이 활동 내역을 순서대로 표시합니다. 색상과 상태 이름을
함께 사용해 진행 중인 작업, 완료한 단계, 승인 대기, 실패를 구분합니다. 단계 전환과 길이가
제한된 상세 메시지는 터미널 이력에 남습니다. 작은 임시 표시 영역에서는 현재 단계, 경과 시간,
실제로 다운로드한 용량, 기반 환경 점검 단계만 갱신합니다. 고정 패널을 두거나 시작하지 않은
작업을 나열하지 않습니다. 완료한 조정기 단계와 하위 프로세스가 보고한 점검 단계는 별도 개수이며,
예상 시간이나 구독 준비 상태를 의미하지 않습니다.

기본값은 `--progress auto`입니다. 출력을 리디렉션하거나 `TERM=dumb` 또는 `NO_COLOR`를
설정하면 터미널 제어 문자가 없는 일반 단계 메시지를 사용합니다. 읽기 쉬운 로그에는
`--progress plain`을 사용하고 진행 표시를 숨기려면 `--progress off`를 사용합니다.
`--output json`은 진행 표시를 끄고 stdout에 최종 결과 하나만 유지합니다. 중간 기반 환경
JSON은 stdout에 반복하지 않습니다.

대화형 `auto` 출력은 기반 환경 점검 상태가 바뀔 때마다 해당 전환을 한 번만 추가합니다.
활동 확인 신호는 마지막 관측 시각만 갱신하며 새 줄을 추가하지 않습니다. 크기를 제한한 어댑터는
알려진 Genesis 소개 전체와 정확한 진행 출력 형식만 식별합니다. 중복 배너와 ASCII 막대를
바꾸되, 이 표시 정보로 조정기 상태나 준비 완료 여부를 변경하지 않습니다. 높이가 낮은 터미널도
현재 작업을 간결하게 표시하며, 최종 실패 내용은 스크롤할 수 있는 출력에 남깁니다.

알 수 없거나 형식이 잘못된 출력은 원래 진단 내용으로 표시합니다. 줄바꿈으로 끝나지 않는 경고나
입력 안내도 숨기지 않습니다. 이런 상세 내용과 별도의 정확한 승인 절차가 터미널을 사용할 때는
실시간 화면 갱신을 멈춥니다. 기존 검토 내용과 확인 절차는 변경하지 않고 그대로 표시합니다.
일반 텍스트, 출력 끄기, JSON 모드의 하위 프로세스 출력 방식은 유지합니다. 실패하거나 중단하면
현재 단계를 미완료로 남기고 터미널을 복원하며, 롤백 완료나 안전한 재시도를 주장하지 않습니다.
기존 검증된 배포 결과가 있을 때만 준비 완료 요약을 표시합니다.

조정기는 보존된 상태를 인계 근거로 수락하기 전에 오케스트레이션 종료 코드를 확인합니다. 하위 프로세스가
실패하거나 신호로 종료되면 이전 인계 기록을 근거로 신원 또는 애플리케이션 구성을 진행하지
않습니다.
수락하는 상태는 정확히 다음 시도, 서명된 소스, 준비된 실행, 적용 모드와 일치해야 합니다.
비공개 실행기 인계가 확인된 경우에만 애플리케이션 구성을 진행합니다. 상태가 누락되거나 오래됐거나
형식이 잘못되면 진행으로 간주하지 않고 차단합니다.

하위 프로세스가 실패로 종료된 뒤에는 별도 진단 읽기 기능이 해당 시도의 알려진 차단 원인을
설명할 수 있습니다. 크기가 제한된 비공개 입력을 읽고, 중복 JSON 키나 실행 맥락 불일치를
거부하며, 민감한 값이 없는 고정 안내 문구만 출력합니다. 근거가 없거나 인식할 수 없으면 일반
오류를 유지합니다. 실행기 이미지가 미완료이면 보존된 상태 검토와 별도로 승인한 복구 계획이
필요합니다. 기존 적용 시작 기록이 있으면 검증만 재개할 수 있고 적용을 반복할 수 없습니다.
진단은 인계, 정리, 승인, 상태 삭제 또는 작업 디렉터리 변경 권한을 부여하지 않습니다.

애플리케이션 승인을 표시하기 전에 검토 스키마, 단계, 다이제스트, 작업 개수, 만료를 검증합니다.
확인 입력 후 만료를 다시 검사하며, 입력이 닫혀도 승인을 부여하지 않습니다. 각 승인 입력 후에는
이전 화면의 커서 이동 정보를 재사용하지 않아 검토 텍스트가 지워지지 않습니다. 초기 시작 또는
재개 중 중단돼도 커서를 복원하며, 뒤따른 출력 장애가 원래 배포 오류를 덮어쓰지 않습니다.

화면 표시는 설치된 로컬 CLI가 담당합니다. 서명된 번들 코드를 수정하거나 원시 공급자 로그를
진행 근거로 해석하지 않으며, 배포 상태를 기록하거나 승인을 부여하지도 않습니다. 터미널 표시는
Rich를 사용하며, 잠긴 의존성은 기존 오프라인 wheel 모음 내보내기 과정에 포함됩니다.
배포가 실행 중일 때는 설치된 조정기를 교체하지 않습니다. 검토된 CLI를 배포가 멈춘 상태에서
설치해야 새 표시가 적용되며, 이미 실행 중인 프로세스의 화면은 바뀌지 않습니다.

## 공개 명령 모델

| 명령 | 용도 | Azure 변경 |
|------|------|------------|
| `fdaictl version` | 설치된 CLI 버전 표시 | 아니요 |
| `fdaictl doctor` | Azure CLI와 활성 인증 검사 | 아니요 |
| `fdaictl provision inspect` | 수동 실행 프로필과 로컬 필수 조건 검사 | 아니요 |
| `fdaictl provision init` | 비공개 수동 실행 프로필 생성 | 아니요 |
| `fdaictl provision bootstrap-reconcile` | 대상과 Foundation 상태를 만료되는 계획으로 읽기 | 아니요 |
| `fdaictl provision plan` | 검증된 offline-kit Terraform 루트 계획 | 아니요 |
| `fdaictl provision azure --online` | 서명 키트를 획득하고 standalone Azure 배포 실행 | 정확한 승인 후 예 |
| `fdaictl provision azure --offline-kit <path>` | 공개 산출물 획득 없이 동일한 배포 실행 | 정확한 승인 후 예 |
| `fdaictl onboard guided --simulate` | 유한한 단계 그래프 예행연습 | 아니요 |
| `fdaictl onboard status` | 로컬 해시 체인 예행연습 저널 읽기 | 아니요 |
| `fdaictl bundle verify` | 번들 서명, 호환성, 파일, SBOM 및 digest 검증 | 아니요 |
| `fdaictl offline prepare` | 검증된 비공개 오프라인 스냅샷 생성 | 아니요 |
| `fdaictl offline install-support` | 서명된 wheel에서만 마이그레이션 지원 설치 | 아니요 |
| `fdaictl license inspect` | 네트워크 호출 없이 기능 토큰 검증 | 아니요 |

공개 CLI는 `deploy plan`, `deploy apply` 또는 `deploy status`를 등록하지 않습니다. 이 명령들은
이전에 GitHub workflow를 dispatch했으며 standalone 배포 계약에 포함되지 않습니다. 실제
온보딩은 `provision azure`를 사용하고 `onboard guided`는 예행연습 전용입니다.

## Standalone 배포 순서

조정기는 다음 단계를 순서대로 수행합니다.

1. 활성 Azure 사용자 대상을 읽고 검증합니다.
2. 온라인 또는 로컬의 완전한 서명 키트 하나를 획득하고 모든 실행 입력을 검증합니다.
3. 정책, provider, 할당량, 리전 및 Foundation 상태를 검사합니다.
4. 정확한 Foundation 계획을 만들고 현재 터미널 승인을 받습니다.
5. 비공개 상태 계정, 허브 네트워크, Bastion, 배포 신원 및 Managed Host를 만듭니다.
6. 상태 인계와 Managed Host 이미지를 검증합니다.
7. 동일한 검증 키트를 Bastion을 통해 전달합니다.
8. Managed Identity로 substrate 및 애플리케이션 계획을 실행하고 적용합니다.
9. 모든 런타임 이미지 digest를 가져오고 재확인합니다.
10. 데이터베이스 마이그레이션을 실행하고 권위 있는 카탈로그를 구체화합니다.
11. 서비스를 배포하고 런타임 상태를 검증합니다.
12. 배포 준비 상태를 보고하기 전에 두 번째 Terraform 계획에 변경이 없는지 확인합니다.

독립적인 준비와 읽기 전용 probe는 병렬로 실행할 수 있습니다. 승인, 적용, 정리, 상태 전환,
인계, 마이그레이션 및 애플리케이션 활성화는 직렬로 유지됩니다.

## 승인 및 복구

모든 변경 checkpoint는 승인과 만료를 정확한 binary 계획 하나에 연결합니다. 계획이 바뀌면 새
승인이 필요합니다. 파괴적인 계획에는 두 번째 정확한 확인이 필요합니다. 응답이 없다고 권한을
부여하지 않습니다.

효과를 적용하기 전에 조정기는 변경할 수 없는 claim을 기록합니다. 결과가 불분명하면 나중 호출은
권위 있는 재확인과 변경 없음 계획을 수행합니다. 보존된 claim으로 적용을 반복하지 않습니다.
대상, 키트, Foundation, Entra 또는 provider 컨텍스트가 바뀌면 새 준비 컨텍스트가 필요합니다.

### 보존된 키트 다시 획득

온라인 재시도는 작업 디렉터리를 유지하고 보존된 키트를 아직 신뢰할 수 없는 입력으로
취급합니다. 다음 단계로 진행하기 전에 패키지에 고정된 공개 키로 릴리스 서명, 호환성, 정확한
파일 목록, 모든 다이제스트, 런타임 이미지, 번들 연결을 다시 검증합니다. 기존에 복사한
산출물은 검증된 파일과 정확히 일치할 때만 재사용합니다. 서명된 번들의 새 실행 복사본을
만들어 이전 실행 복사본의 Python 바이트코드, Terraform 임시 파일, 기타 잔여물을 사용하지
않습니다.

캐시는 요청한 산출물 URL의 다이제스트를 기록해 원본이 암묵적으로 바뀌는 것을 차단합니다.
이 로컬 기록은 서명이나 원격 출처의 근거가 아닙니다. 기록이 없는 이전 캐시는 기본 버전별
원본에 대해서만 전체 검증 후 사용할 수 있으며, 게시된 릴리스가 최신임을 입증하지 않습니다.
출처가 연결되지 않은 캐시에 다른 URL을 지정하면 차단합니다. 키트 획득은 작업 디렉터리별로
직렬화하며 배포 대상 잠금을 대신하지 않습니다.

HTTP 상태, 연결 실패, 로컬 경로 충돌, 권한, 저장 공간 부족은 민감한 값을 노출하지 않는
별도 오류로 표시합니다. 손상되거나 불완전한 보존 파일은 유지한 채 차단하며 몰래 교체하거나
수락하지 않습니다. 재시도는 실행 상태, SSH 키, 계획, 승인을 삭제하거나 서명된 소스를
바꾸지 않으며, 키트 캐시를 근거로 Azure 작업을 반복하지 않습니다.

## 기능 토큰 동작

유지관리자 서명 키는 도입자 필수 조건이 아닙니다. 명시적으로 사용할 수 있으면 일치하는 운영자
소유 발급 키를 사용하고, 사전 발급된 Trial token을 제공하면 이를 검증합니다. 둘 다 없으면
새 설치는 라이선스 비밀을 만들지 않고 관찰 전용 모드로 시작할 수 있습니다. 재개한 설치에서
토큰 입력을 생략해도 이전에 설치한 토큰이 폐기되지는 않습니다. 작업 권한이 없으면 Core는
관찰하고 보고할 수 있지만 관리 대상 리소스 작업을 실행할 수 없습니다.

토큰 자체는 배포 또는 런타임 권한을 부여하지 않습니다. 승격 상태, 위험 정책, 사람 승인, 실행기
신원 및 효과 검증은 독립된 제어로 유지됩니다.

## 배포 어플라이언스

폐쇄망 release는 같은 완전한 서명 키트를 하나의 OCI 배포 어플라이언스에 포함합니다.

```bash
bash scripts/deployment/release/build-deployment-appliance.sh \
  --kit /private/fdai-deployment-kit.tar.gz \
  --base-image <approved-deployer-base>@sha256:<digest> \
  --output /private/fdai-deployment-appliance.oci.tar
```

승인된 기본 이미지는 pip가 포함된 Python 3, Azure CLI, OpenSSH 및 `tar`를 포함합니다. 빌더는 이미지를 만들기
전에 키트를 검증하고, 키트 wheelhouse에서만 CLI를 설치하고, 네트워크 없이 이미지를 빌드하고,
SBOM 및 provenance가 있는 OCI 아카이브를 생성합니다.

`build-standalone-deployment-kit.sh --appliance-base-image <image>@sha256:<digest>`는 깨끗한
checkout의 단일 release 실행에서 키트와 어플라이언스 생성을 조립합니다. 이미 검증된 키트를
어플라이언스로 감쌀 때는 별도 빌더를 사용할 수 있습니다.

이미지 진입점은 대화형 Azure 인증 또는 명시적으로 선택한 사용자 할당 Managed Identity를
사용합니다. 공개 산출물 대체 경로를 차단하고
`fdaictl provision azure --offline-kit /opt/fdai/kit.tar.gz`를 호출합니다.
`FDAI_DEPLOYMENT_APPLIANCE_KIT`은 다른 비공개 일반 아카이브를 선택할 수 있고,
`FDAI_DEPLOYMENT_APPLIANCE_WORK_DIR`은 다른 절대 private 작업 디렉터리를 선택할 수 있습니다.
Managed Identity 모드에는 `FDAI_DEPLOYMENT_APPLIANCE_USE_MANAGED_IDENTITY=1`과 정확한
`FDAI_DEPLOYMENT_APPLIANCE_MI_CLIENT_ID`가 모두 필요합니다. 포함된 키트는 Terraform, OPA,
provider 미러, 런타임 이미지, Console, 마이그레이션 지원, 서명 및 SBOM을 포함합니다.

## 결과 계약

`deployment_ready=true`는 선택한 애플리케이션이 수렴하고, 서비스 상태 검사를 통과하고, 두 번째
Terraform 계획에 변경이 없음을 의미합니다. 더 넓은 구독 보증, 모델 용량 인증 또는 완전한
인벤토리 근거가 열려 있으면 `subscription_ready=false`가 유지될 수 있습니다. 배포된
애플리케이션과 완전히 인증된 구독을 구분하기 위한 상태입니다.

모든 기계 출력은 안정적인 영어 key를 사용하고 자격 증명, 원시 상태, tenant 값 및 비밀 내용을
제외합니다. 비공개 로컬 및 Managed Host 디렉터리는 mode `0700`, 민감한 파일은 mode `0600`을
사용합니다.

## 관련 문서

| 알아볼 내용 | 참조 문서 |
|------------|-----------|
| 구현 상태와 남은 근거 | [구현 원장](../../roadmap-implementation/deployment/installable-deployment-cli.md) |
| 실행 호스트와 연결 선택 | [프로비저닝 실행 프로필](provisioning-execution-profiles-ko.md) |
| 폐쇄망 신뢰와 산출물 전달 | [연결이 끊긴 배포](disconnected-deployment-ko.md) |
| Azure 리소스 인벤토리와 bootstrap | [배포와 온보딩](deploy-and-onboard-ko.md) |
| 신원과 승인 분리 | [보안과 신원](../architecture/security-and-identity-ko.md) |
