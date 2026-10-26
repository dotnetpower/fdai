---
title: Release Hub 이미지로 배포
translation_of: hub-image-deployment.md
translation_source_sha: cb4c8047aa6e1165ea6bfa7326341957d7de9fea
translation_revised: 2026-10-26
---
# Release Hub 이미지로 배포

복제한 저장소에서 `https://hub.msfdai.com`의 사전 빌드 이미지를 선택해 FDAI를 설치합니다.
로컬 배포 조정기는 Azure 로그인, Terraform 계획, 애플리케이션 설정과 독립적인 상태 검증을
계속 담당합니다. Release Hub는 서명된 메타데이터를 제공하고 배포 요청을 기록하며,
Azure 자격 증명을 받거나 배포를 적용하지 않습니다.

> **범위:** 이 경로는 연결된 환경의 이미지 초기 설치이며,
> [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md) 전체의 완성을 뜻하지 않습니다.
> 등록, 고객 구성 승인, 설치본 로컬 정책과 Agent 실행은 각자의 계약을 유지합니다.
> [소스 배포](source-deployment-ko.md)와 서명된 오프라인 패키지는 Hub에 의존하지 않고
> 명시적으로 선택할 수 있습니다.

## 한눈에 보는 설계

| 관심사 | 결정 |
|--------|------|
| 일반적인 복제 후 배포 | 서비스 이미지를 빌드하는 대신 Release Hub 이미지를 선택 |
| 배포 엔드포인트 | `https://hub.msfdai.com`. 다른 승인된 Release Hub는 명시적인 HTTPS 옵션으로 선택 |
| 신뢰 | 독립적으로 승인한 Ed25519 Release 공개키. 카탈로그와 함께 받았다는 이유만으로 키를 신뢰하지 않음 |
| Release 선택 | 선택 채널의 적격 버전과 서명된 다이제스트 고정 이미지 위치 |
| 로컬 소스 | 서명된 Release 소스 커밋과 일치하는 깨끗한 저장소. 마이그레이션과 Console이 조용히 달라지는 일을 방지 |
| 이미지 전달 | 설치본 자체 레지스트리로 이미지를 가져오고 워크로드 적용 전에 정확한 다이제스트를 다시 조회 |
| 실패 | 신뢰 누락, 잘못된 서명, 만료, 이전 개정, 회수, 소스 불일치나 이미지 관측 실패 시 중단. 소스 빌드로 자동 전환하지 않음 |
| 요청 가시성 | Release Hub 운영자는 신고된 구독 요청 목록 조회 가능. 카탈로그와 공개 호출자는 목록 조회 불가 |
| 라이선싱 | 기존 설치본 바인딩 Trial 및 사용권 규칙 유지. 카탈로그 서명은 사용권이나 실행 권한을 부여하지 않음 |

## 설계, 비판과 수정된 경계

**초기 설계:** 모든 소스 빌드를 레지스트리 가져오기로 바꾸고 Release Hub에 Azure 구독을 표시합니다.

**비판:** 변경 가능한 이미지 태그나 신뢰하지 않는 다운로드와 함께 받은 다이제스트만으로는
신뢰를 확보할 수 없습니다. 서명된 이미지도 저장소의 마이그레이션과 다를 수 있습니다.
구독 ID 제출은 소유권 증명이 아니며, 요청 기록은 배포 성공 증거가 아닙니다. 소스 모드를
묵시적으로 바꾸면 키 없이 Hub와 독립적으로 설치하는 기존 계약도 사라집니다.

**수정된 경계:** 명시적 소스 모드와 오프라인 모드는 유지합니다. 일반적인 복제 후 진입점은
별도의 Hub 이미지 옵션을 선택합니다. Azure에 영향을 주기 전에 서명된 카탈로그와 정확한
매니페스트, 채널 구성, 만료, 회수, 보존된 개정과 소스 호환성을 검증합니다.
정확한 선택을 Managed Host로 전달하고, 서명된 이미지의 출처와 저장소에서 제공하는 인프라,
마이그레이션, Console을 구분합니다. 변경 가능한 태그가 아니라 다이제스트로 가져옵니다.
요청 수신 경로는 자체 신고 메타데이터만 저장하며 어떤 작업도 승인하지 않습니다.

## 복제한 저장소에서 배포

### 게시자 입력

기존 Release Hub 게시 및 채널 절차로 호환되는 `fdai.application-release.v2` 매니페스트를
게시합니다. 각 `components.<name>.image_ref`는 변경 불가능한 다이제스트로 레지스트리 이미지를
지정합니다. 예를 들면
`registry.example.com/fdai/core-control-plane@sha256:<64-lowercase-hex>`입니다.
참조의 다이제스트는 서명된 구성 요소의 이미지 다이제스트와 일치해야 합니다.

초기 설치에는 정확히 일곱 구성 요소가 필요합니다. `core-control-plane`, `operator-service`,
`document-ingestion-api`, `document-processing-worker`, `isolated-executor`, `clamav`,
`pgvector`입니다. Release 소스 커밋은 저장소와 일치해야 합니다.
서명된 이미지 위치가 없는 기존 매니페스트는 기존 소비자에게는 계속 유효하지만 이 초기
설치에는 사용할 수 없습니다. 메타데이터 게시는 이미지를 빌드하거나 레지스트리 가용성을
증명하거나 읽기 권한을 부여하지 않습니다.

### 설치 입력

먼저 승인된 독립 신뢰 경로로 Release 공개키를 받으세요. 공개 PEM은 저장소 밖에 보관합니다.
이 키는 검증용이며 서명 키나 Azure 자격 증명이 아닙니다. 서명 실패를 없애려고 검증하지 않은
대체 키를 내려받지 마세요.

```bash
az login
az account show --query '{subscription:id,name:name}' --output table
git clone https://github.com/dotnetpower/fdai.git
fdai/scripts/deployment/azure/fdai-up.sh \
  --hub-public-key /trusted/release-hub-public.pem \
  --region <azure-region>
```

선택 채널에는 게시된 호환 Release가 있어야 하며 이미지에 접근할 수 있어야 합니다.
저장소가 서명된 소스 커밋과 다르면 중단하고 검토한 해당 커밋을 선택한 뒤 다시 실행하세요.
현재 저장소의 마이그레이션과 이전 이미지를 섞거나 개발 채널로 조용히 바꾸지 마세요.

설치한 CLI에서는 `fdaictl provision azure --hub <checkout>`으로 이 모드를 선택합니다.
`--hub-public-key <public.pem>` 또는 `FDAI_HUB_PUBLIC_KEY`의 공개키 파일 경로,
`--hub-channel <channel>`(기본 `RELEASE`), 정확한 버전을 선택하는 `--hub-release <version>`,
배포 엔드포인트를 바꾸는 `--hub-url <approved-https-origin>`을 사용할 수 있습니다.

워크스테이션과 Managed Host에는 패키지 및 Terraform 공급자 접근 등 연결된 배포의 기존
전제조건이 필요합니다. 달라지는 것은 런타임 이미지 빌드뿐입니다. 이 경로는 폐쇄망 설치가
아니며, 모든 산출물을 Hub 호스트 이름에서 내려받는다는 보장도 아닙니다.
Release Hub는 서명된 이미지 위치를 제공하고 해당 레지스트리가 이미지 계층을 제공합니다.
레지스트리 읽기 권한은 설치본 내부에서 관리합니다.

### 다른 경로를 명시적으로 선택

Hub와 독립적인 소스 빌드에는 기존의 명시적 소스 옵션을 사용합니다.

```bash
fdai/scripts/deployment/azure/fdai-up.sh --source . --region <azure-region>
```

래퍼는 자신의 저장소 경로를 찾은 뒤 `--source .`을 해석합니다. 설치한 CLI에서는 대신
`fdaictl provision azure --source <checkout>`을 사용하세요. 소스 모드는 카탈로그를 내려받거나
배포 요청을 등록하지 않습니다. 오프라인 설치 명령은 그대로 유지됩니다.

```bash
fdaictl provision azure --offline-kit /private/fdai-deployment-kit.tar.gz
```

두 경로에 Release Hub 전제조건이 추가되지는 않습니다. 모드나 대상 입력 변경은 복구 방법이
아닙니다. 기존 비공개 작업 디렉터리를 보존하고 원래 봉인된 입력을 사용하거나 별도 실행을
시작하세요.

## 구독별 배포 요청 확인

연결된 Hub 이미지 명령은 Release 선택을 검증하고 선택한 Azure 계정을 읽은 뒤,
첫 Azure 배포 효과 전에 최소한의 요청을 신고합니다.

| 필드 | 의미 |
|------|------|
| `request_id` | 정확한 재시도를 구분하는 안정적인 요청 다이제스트 |
| `subscription_id` | 배포 클라이언트가 신고한 구독 |
| `release_id`, `channel` | 선택한 게시 Release와 채널 |
| `region` | 요청한 Azure 위치 |
| `source_commit`, `catalog_digest` | 정확한 저장소와 카탈로그 입력 식별값 |
| `recorded_at` | 서버가 기록한 수신 시각 |
| `status`, `trust` | `requested`와 `self-reported`. 배포 성공이나 검증된 소유권을 뜻하지 않음 |

`POST /v1/deployment-requests`는 크기와 필드가 제한된 이 메타데이터를 받습니다.
명시적 공개 카탈로그 프로필은 공급자 관리 API를 공개하지 않고도 복제 사용자의 요청을 받을 수
있습니다. `GET /v1/deployment-requests`는 운영자 전용입니다. **Deployment requests** 화면은
구독 필터와 페이지 이동을 제공합니다. 요청 기록은 카탈로그 게시와 분리됩니다.
카탈로그 개정을 올리거나 만료를 갱신하지 않으며, 카탈로그 내보내기에 포함되거나 고객 리소스
접근 권한을 부여하지 않습니다.

요청을 확인하기 위해 공급자 측 메타데이터를 카탈로그로 제한하던 경계에 이 예외를 명시적으로
추가합니다. 테넌트 ID, 실행 신원, 자격 증명, 구성 내용, 리소스 이름, 콜백 주소나 운영 데이터는
허용하지 않습니다. 구독 ID는 Hub의 비공개 런타임 데이터베이스에만 저장하고 이 저장소에
넣지 않습니다.

같은 요청을 정확히 반복하면 원래 기록을 유지합니다. 같은 ID에 다른 필드를 보내면 충돌입니다.
제출 결과가 불분명하면 ID를 보존하고 기록을 확인하세요. 새 요청을 만들거나 시간 초과된
변경 요청을 자동 재시도하지 마세요. 요청 목록은 수신 원장이지 설치 인벤토리나 효과 검증
피드가 아닙니다.

## 현재 초기 설치의 한계

재실행은 정확한 카탈로그 선택과 대상 바인딩을 유지합니다. 카탈로그 바이트, Release나 신뢰
입력을 바꾸려면 별도로 검토한 실행과 비공개 작업 디렉터리가 필요합니다.
이 초기 설치 경로는 기존 설치본의 채널 업그레이드를 구현하지 않습니다.
새 디렉터리는 기존 설치 도입을 승인하지 않으므로 보존 상태나 불확실한 적용을 피하려고
사용하지 마세요.

Hub 모드의 해체는 구현되지 않았습니다. Hub 실행을 해체하거나 봉인된 입력 바인딩을
우회하려고 소스 모드로 바꾸지 마세요. 기존의 명시적 소스 해체 계약은 소스 설치에만 적용됩니다.

## 검증과 전달의 한계

집중 로컬 테스트로 카탈로그 검증, 이미지 가져오기와 재조회, 요청 영속성, 인증 분리와 UI 동작을
확인할 수 있습니다. 실제 Hub 가용성, 호환 Release 게시 여부, 다른 구독에서의 레지스트리
접근이나 Azure 설치 인수를 입증하지는 못합니다. 새 Hub와 CLI 빌드의 게시와 배포에는
별도의 승인이 필요합니다.

## 기존 워크로드 인수인계

워크로드 상태가 보존되지 않은 설치는 전용 인수인계 루트로 승인된 Kubernetes 객체 재고를
정확히 가져온 뒤 forget-only 해제 계획을 만듭니다. 해제 계획은 모든 객체에 대해
`destroy=false`를 보고해야 합니다. 롤백은 생성된 정확한 가져오기 선언을 사용하며 변경 없음
계획으로 끝납니다. 어느 루트도 실제 워크로드를 편집하거나 Terraform 상태를 직접 수정하지
않습니다.

## 관련 문서

| 학습 대상 | 문서 |
|-----------|------|
| 복제 후 배포 전제조건 | [배포 빠른 시작](../../user-guide/deploy-quickstart-ko.md) |
| 명시적 소스 빌드와 라이선싱 | [소스 배포](source-deployment-ko.md) |
| 서명된 카탈로그와 채널 계약 | [수명 주기 Release와 채널](lifecycle-releases-and-channels-ko.md) |
| 설치 에이전트 실행 | [Hub 수명 주기 운영자 가이드](../../runbooks/hub-lifecycle-operator-guide-ko.md) |
| 전달 근거와 남은 작업 | [구현 원장](../../roadmap-implementation/deployment/hub-image-deployment.md) |
