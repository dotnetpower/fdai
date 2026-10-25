---
title: Lifecycle Release와 채널
translation_of: lifecycle-releases-and-channels.md
translation_source_sha: 62623acd8d492af922b8c40d5f3c696e36e1af22
translation_revised: 2026-10-25
---
# Lifecycle Release와 채널

이 문서는 애플리케이션 Release에 무엇이 들어 있는지, Release가 release channel을 따라 어떻게 이동하는지
정의합니다. 또한 연결된 설치와 오프라인 설치가 Release를 받는 방법, 그리고 회수와 데이터베이스
스키마 호환성이 업그레이드를 안전하게 유지하는 방법을 정의합니다. 이 문서는 Release 매니페스트,
채널 모델, 업그레이드 번들, 회수를 소유합니다.

> **상태:** 로컬 및 명시적 원격 개발용으로 일부 구현되었으며, 프로덕션 수명 주기 전달은 설계 단계입니다.
> [로컬 Release Hub](../../../lifecycle/release-hub/README.md)는 매니페스트 등록, 개발용 서명,
> 기본/사용자 지정 채널의 수동 관리, 회수, 공급업체 UI와 명시적으로 선택하는 Lifecycle Hub의 고정 다이제스트
> 기반 내보내기 파일 검증을 제공합니다. 프로덕션 인증, 프로덕션 루트 키 보관, 레지스트리 발행,
> 회수에 따른 실행 중 설치본의 교체는 구현하지 않습니다.
> FDAI에는 서명된 배포 번들과 오프라인 키트도 있으며, 그
> 새 번들 서명은 `DEV`, `RELEASE_CANDIDATE`, `RELEASE`를 사용합니다. 검증 시에는 서명된 바이트를
> 다시 쓰지 않고 기존 `development`, `beta`, `stable` 이름을 매핑합니다. 배포 CLI는 여전히
> `DEV`와 인증된 기존 대응 이름만 허용합니다. 나머지는
> [구현 ledger](../../roadmap-implementation/deployment/lifecycle-releases-and-channels.md)가
> 추적합니다.
>
> **범위:** 이 문서는 [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md)를 지원합니다.
> [소스 배포](source-deployment-ko.md)와 첫 설치용 오프라인 패키지는 현재 계약을 유지합니다.

## 설계 한눈에 보기

**FDAI Release Hub**는 릴리스 발행, 서명, 채널 승격, 회수를 관리하는 공급업체
애플리케이션입니다. **Release Catalog**는 앱 이름이 아니라 Release Hub가 제공하는 릴리스
목록, 데이터 또는 피드를 뜻합니다. **FDAI Lifecycle Hub**는 설치본별 배포를 관리하는 별도
애플리케이션이며 이름을 유지합니다.

로컬 Release Hub는 API 작업 흐름과 웹 UI를 제공합니다. 기존 서명된 번들과
로컬 `shadow` 전용 검증기만 있다고 해서 프로덕션 Release Hub 서비스가 구현된 것은 아닙니다.
카탈로그 디렉터리, API, 스키마, 식별자는 기존 기술 명칭을 유지합니다.

명시적으로 선택하는 [두 Hub 개발 경로](../../../infra/hubs-development/README.md)는 Entra
운영자 인증과 서비스 ID의 분리, 명시적 migration을 사용하는 PostgreSQL 발행 저장소,
독립적인 개발용 서명 키 제공, UI 포함 이미지, 고객 측 pin/revision 영속 상태를 추가합니다.
고객 운영자는 제한된 import 전에 별도의 인증된 신뢰 승인 작업으로 정확한 export pin을
승인해야 합니다. 다운로드와 함께 받은 digest는 신뢰 근거가 아닙니다.
기존 loopback 기본값과 매니페스트/서명/카탈로그 계약은 유지합니다.
선택적으로 켜는 TUF 방식 카탈로그 역할([카탈로그 무결성](#카탈로그-무결성) 참고)은 개발용 키
하나를 임계값 오프라인 root 키와 별도의 온라인 snapshot, timestamp 키로 대체합니다.
프로덕션 루트 설정 의식, 레지스트리 발행, Agent 적용을 구현한 것은 아니며 Azure 배포 성공의
증거도 아닙니다.

| 관심사 | 결정 |
|--------|------|
| Release | 미리 빌드된 이미지 다이제스트, 스키마 범위, 의존성, 구성 스키마, 기능 최대값을 담은 서명된 매니페스트 |
| 한 번 빌드 | 공급업체가 각 이미지를 한 번 빌드하고, 모든 설치가 같은 다이제스트를 실행합니다 |
| 채널 | `DEV`, `RELEASE_CANDIDATE`, `RELEASE`, 사용자 지정 채널 |
| 구독 | 각 설치는 채널 하나를 구독하며, 버전 범위를 함께 지정할 수 있습니다 |
| 업그레이드 | 자동: 유지 관리 구간 안의 적격한 최신 Release |
| 연결된 전달 | 이미지를 고객 경계 안의 레지스트리로 미러링합니다 |
| 오프라인 전달 | 운영자가 Target Hub로 가져오는 서명된 업그레이드 번들 |
| 회수 | Release 회수는 roll-off를 시작합니다. 기능 회수는 ActionType이나 Workflow를 모든 곳에서 `shadow` 모드로 되돌립니다. |
| 카탈로그 무결성 | 버전이 증가하는 서명된 root, snapshot, timestamp 기록과 회수 순번 |
| 스키마 | expand/contract 방식과 전진 전용입니다. 각 Release는 허용하는 스키마 개정을 선언합니다. |

## 개발용 카탈로그의 명시적 유효기간 갱신

개발용 내보내기 파일은 마지막 발행 이벤트로부터 24시간 뒤에 만료됩니다.
카탈로그 읽기, 화면 새로고침, 같은 파일의 재다운로드로는 갱신되지 않습니다.
release 목록이 같아도 신선도를 다시 발행하려면 검토가 필요합니다.
갱신을 위해 불필요한 채널 변경이나 회수를 만들지 않습니다.

`POST /v1/catalog/renew`에는 기존 공급자 운영자 신원, 현재 카탈로그 리비전,
공백이 아닌 사유, 정확한 확인문 `renew <revision>`이 필요합니다.
등록, 발행, 채널 추가, 회수와 같은 발행 잠금과 리비전 검사로 직렬화합니다.
쓰기 전에 현재 키로 발행된 모든 매니페스트 서명을 다시 검증하고 발행 시계가
앞으로 진행했는지 확인합니다. 잘못된 서명, 이전 리비전, 다른 확인문, 시계 역행이
있으면 발행 상태를 변경하지 않습니다.

갱신은 `catalog`를 대상으로 행위자가 기록된 `renew` 이벤트를 추가합니다.
리비전과 24시간 유효기간이 바뀌므로 내보내기 다이제스트도 달라집니다.
매니페스트, 서명, 채널, 회수, 서명 키는 변경하지 않습니다.
고객 Hub는 운영자가 새 고정값을 독립적으로 승인하고 명시적으로 가져오거나,
[자동 카탈로그 채택](#자동-카탈로그-채택)이 서명을 검증하고 정책이 허용하기 전까지
기존 수락 바이트를 유지합니다. 갱신은 설치본 가져오기, 계획, 적용을 수행하지 않으며
운영용 서명된 카탈로그 역할을 대신하지 않습니다. 선택적 Release Hub 작업이
갱신을 자동으로 수행할 수도 있습니다.
UI는 읽기 전용 **Refresh catalog**와 **Renew catalog freshness**를 구분합니다.

## 자동 카탈로그 채택

위의 수동 고정값 흐름에서는 내보내기 파일의 메타데이터가 서명되지 않으므로, 카탈로그가 바뀔
때마다 사람이 리비전과 다이제스트를 옮겨 적어야 합니다. 이 절은 옮겨 적기를 검증과 정책으로
대체합니다. 신뢰 기준은 그대로입니다. 고객 Hub가 배포 시점에 묶어 둔 Release 공개키입니다.

**방향 규칙.** Release Hub는 고객에게 요청하지 않습니다. Lifecycle Hub가 Release Hub를
조회하고, 설치 Agent가 Lifecycle Hub를 조회하며, 모든 연결은 고객 경계 안에서 시작합니다.
Release Hub는 고객의 콜백 주소, 실행 신원, 일정을 저장하지 않습니다.
명시적 [배포 요청 수신 경로](hub-image-deployment-ko.md#구독별-배포-요청-확인)만 별도의 최소
예외입니다. 신고된 구독 ID, 리전, Release와 채널, 입력 다이제스트, 서버 수신 시각을 운영자
전용 목록에 보관합니다. 자체 신고 요청은 공개 카탈로그에 포함되지 않으며 구독 소유권을
증명하거나 배포를 승인하거나 운영 성공을 보고하지 않습니다.
고객 구성의 식별자는 기존 계약에 따라 봉인된 상태를 유지합니다.

| 관심사 | 결정 |
|--------|------|
| 서명된 내보내기 | Release Hub가 내보내기 바이트 전체를 Release 키로 서명합니다. 서명 대상 메시지는 `fdai.catalog-export.v1`, 줄바꿈, 본문 순서입니다. 분리 서명과 키 ID는 같은 응답의 `X-FDAI-Export-Signature`와 `X-FDAI-Export-Key-Id`로 전달하므로 본문과 서명이 서로 다른 리비전에서 올 수 없습니다. 본문과 `ETag` 다이제스트는 바뀌지 않습니다. |
| 조건부 조회 | Lifecycle Hub는 수락한 다이제스트를 `If-None-Match`로 보냅니다. 카탈로그가 같으면 위치 조회 한 번 뒤에 `304`를 반환합니다. Release Hub는 마지막 서명된 내보내기를 리비전 기준으로 캐시하고 한 번에 하나만 만듭니다. |
| 공개 읽기 | `public_catalog_export`를 켜면 Release Hub는 베어러 토큰 없이 `GET /v1/catalog/export`를 제공합니다. 내보내기에는 매니페스트, 서명, 채널 구성, 회수만 들어 있습니다. 무결성은 서명이 보장하고 이미지는 레지스트리 권한 뒤에 있습니다. 기본값은 인증 필요입니다. |
| 자동 유효기간 갱신 | 선택 사항인 Release Hub 갱신 작업은 유효기간이 절반 미만으로 남으면 `system:timestamp-renewal` 이름으로 `renew` 이벤트를 추가합니다. 이미 발행한 내용을 다시 확인할 뿐이며 Release, 채널, 회수를 추가할 수 없습니다. [서명된 카탈로그 역할](#hub의-서명된-카탈로그-역할)을 쓰면 timestamp만 다시 서명하고 이벤트를 추가하지 않습니다. |
| 주기 확인 | Lifecycle Hub는 `check_interval_seconds`(300~86400초, 기본 3600, 0이면 끔) 간격으로 확인합니다. 지터와 상한이 있는 재시도를 쓰며, 각 시도는 리디렉션 없는 한 번의 제한된 요청입니다. |
| 채택 정책 | 검증된 후보가 사람 없이 수락 카탈로그를 대체해도 되는지 Rego가 결정합니다. 입력은 서명 결과, 변경 요약, 소유자의 상시 승인이고 출력은 `allow`와 검토가 필요한 이유입니다. 기본값은 `review`입니다. |
| 실패 시 거부 | 서명 누락, 다른 키, 만료된 후보, 낮은 리비전, 사용할 수 없는 정책 엔진, 만료된 상시 승인은 자동 채택하지 않습니다. 후보는 검토를 기다립니다. |
| 검토 | **Updates** 화면 하나가 후보 리비전, 만료, 서명 결과, 변경 요약을 보여 줍니다. **Review and apply**는 Hub가 직접 검증한 정확한 리비전과 다이제스트를 지정합니다. 그사이 원본이 바뀌었으면 Hub가 거부하고 새 후보를 보여 줍니다. |
| 원자적 채택 | 하나의 트랜잭션에서 서명과 매니페스트를 검증하고, 리비전 하한을 확인하며, 수락한 카탈로그가 정책이 평가한 그 카탈로그인지 확인하고, 같은 리비전에 운영자가 승인한 고정값을 덮어쓰지 않으며, 수락 바이트를 기록하고, 정책 또는 검토한 운영자 이름으로 감사 이벤트를 추가합니다. |
| 채택 이후 | Hub가 등록된 모든 설치본의 Plan을 계산합니다. Plan을 발행해도 적용하지 않습니다. 효과가 생기기 전에 Agent가 서명과 로컬 범위를 다시 검증합니다. |

상시 승인은 헌법이 정한 기존 인간 승인입니다. `authorized_by`와
`authorization_expires_at`은 설정값이므로 변경하려면 검토된 배포 변경이 필요합니다.
만료되면 채택은 검토 방식으로 돌아갑니다. 침묵은 승인이 아닙니다.

`auto` 모드에서 서명이 유효한 후보의 결과는 다음과 같습니다. 기본값인 `review` 모드에서는
모든 변경이 사람을 기다립니다.

| 변경 | 결과 |
|------|------|
| 첫 카탈로그, 또는 Release, 채널, 회수가 같고 만료만 늦어진 경우 | 채택 |
| `allowed_channels`의 채널에 새 Release가 들어오고 `max_new_releases` 이하인 경우(첫 카탈로그는 개수 제외) | 채택 |
| 다른 변경 없이 새 회수만 있는 경우 | 채택 |
| `allowed_channels` 밖 채널 구성, 그 목록 밖의 새 채널, 제거되거나 교체된 Release, 제거된 구성, 해제되거나 누락된 회수, 넓어진 스키마 범위 | 검토 |
| 상시 승인이 없거나 만료된 경우, 정책 엔진을 쓸 수 없거나 결과가 잘못된 경우 | 검토 |
| 서명 누락, 다른 키의 서명, 낮은 리비전, 만료된 후보, 접근할 수 없는 원본 | 후보 없음. Updates 화면에 실패가 표시되고 기존 고정값 흐름이 남습니다. |

다른 변경과 섞인 회수는 검토를 기다리며 화면에 긴급으로 표시됩니다.

### 설정과 인터페이스

배포는 Lifecycle Hub `catalog` 설정으로 상시 승인을 제공합니다. `access`(기본값
`managed-identity`, 또는 `anonymous`), `check_interval_seconds`, 그리고 `mode`,
`allowed_channels`, `max_new_releases`, `authorized_by`, `authorization_expires_at`을 가진
`adoption` 객체입니다. `auto`에는 두 승인 필드가 모두 필요합니다. Release Hub에는
`auth.public_catalog_export`와 `timestamp_renewal_check_seconds`가 추가됩니다. 새 필드는
모두 선택 사항이므로 기존 설정의 동작은 유지됩니다. 선택적 `trust` 설정과 Release Hub의
`catalog_roles` 설정은 [서명된 카탈로그 역할](#hub의-서명된-카탈로그-역할)을 선택합니다.

| 인터페이스 | 목적 |
|-----------|------|
| `GET /v1/catalog/updates` | 정책, 수락한 카탈로그, 마지막 확인, 결정과 변경 요약이 있는 후보, 최근 이벤트 |
| `POST /v1/catalog/updates/check` | 제한된 확인을 지금 한 번 실행 |
| `POST /v1/catalog/updates/apply` | 원본이 여전히 같은 후보를 제공하면 검토한 `revision`과 `sha256`을 채택하고, 아니면 `409 candidate_changed` |
| `fdai-lifecycle-hub sign-enrollment` | 설치 경계 안에서 등록 요청에 서명하고 운영자가 올릴 파일만 기록 |
| `GET /v1/enrollments/bindable` | 배포가 Agent에 묶어 둔 설치본을 나열해 운영자가 입력 없이 선택 |

**사람의 결정으로 남는 것.** 공급자 키를 처음 신뢰하는 일, 채널과 상시 승인의 선택, 설치본
등록, 소유권, 구성 서명, 워크로드에 대한 모든 효과입니다. **선택 사항으로 남는 것.** 임계값 루트
키와 TUF snapshot, timestamp 역할은 선택적으로 켜는 모드로 존재합니다([카탈로그 무결성](#카탈로그-무결성)
참고). 켜지 않으면 개발용 키 하나가 내보내기에 서명하며 개발용 표시는 유지됩니다. 프로덕션 루트 설정
의식은 여전히 운영자 절차입니다.

**검토와 수정.** 다운로드 응답의 다이제스트를 자동 채택하면 서명되지 않은 메타데이터의
허점이 되살아나므로 증거는 다이제스트가 아니라 서명입니다. 공개 읽기는 Release 메타데이터를
누구에게나 노출하지만, 이미지 내용이나 고객 데이터가 없고 서명이 변조를 막으므로 공급자가
수용합니다. 채택은 원자적이라서 회수와 릴리스가 섞인 변경을 나눌 수 없습니다. 나누면 검토되지
않은 내용이 회수에 편승하므로, 채택을 미루고 회수를 화면에 드러내도록 설계했습니다.
갱신 작업은 축소판 timestamp 역할입니다. 내용을 넓힐 수 없고 검토된 내용의 신선도만
유지합니다. 기존 고정값 승인과 가져오기는 서명되지 않은 내보내기와 오프라인용으로 남습니다.

## 애플리케이션 패키지 계약

Hub 엔진은 앱별 고정 서비스 목록 없이 `fdai.application-release.v1`을 받습니다.
FDAI도 하나의 배포 대상입니다. 발행, 정확한 고정값을 사용한 검증, 회수와 채널 선택은 모든
`product`에 같은 경로를 사용합니다. 채널이 프로덕션 자격 검증을 대신하지는 않습니다.

| 필드 | 현재 계약 |
|------|-----------|
| `schema_version` | `fdai.application-release.v1` |
| `product` | 독립적인 앱 ID: `[a-z][a-z0-9-]{0,62}` |
| `release_version`, `source_commit`, `platform_tag` | 시맨틱 버전, 정확한 앱 소스 개정과 산출물 플랫폼 |
| `workloads` | 이름이 있는 HTTP 구성요소 1-64개. 이름은 소문자로 시작하는 Service 호환 DNS 레이블입니다 |
| `workloads.<component>.image_digest` | 필수 불변 `sha256:` 이미지 다이제스트 |
| `workloads.<component>.port` | 정수 1-65535. 기본값 8080 |
| `workloads.<component>.health_path` | 길이가 제한된 ASCII 절대 상태 확인 경로. URL과 `//` 경로는 허용하지 않으며 기본값은 `/`입니다 |
| `workloads.<component>.replicas` | 정수 1-3. 기본값 1 |
| `configuration_schema`, `schema` | 선택적인 기존 버전/다이제스트 연계 구성 스키마와 데이터베이스 호환성 정보 |

엄격한 UTF-8 JSON 검사로 중복 키, 유한하지 않은 수와 지수 오버플로를 차단합니다.
들어오는 UTF-8 입력과 저장할 정규화 표현 모두 같은 디코더의 1 MiB 제한을 지켜야 합니다.
정규화하면서 이 제한을 넘는 유니코드 기본값은 발행 전에 거부합니다. 정의되지 않은
필드로 템플릿, 권한이나 네임스페이스를 주입할 수 없습니다. 기존 워크로드 프로필은 차단하며,
앱 렌더러는 범위가 제한된 Deployment와 ClusterIP Service만 만듭니다. 임의 앱의 모든 배포 방식을 지원하지는
않습니다. 공급망 근거가 없으면 **Not declared**로 표시하며 근거를 만들거나 검증했다고
주장하지 않습니다. 제품 ID는 독립적으로 승인된 설치 Settings 및 Agent 로컬 정책과 모두
일치해야 합니다. 데이터베이스 정보가 없으면 개정 0을 선택하며 기존 데이터베이스를 초기화할 수
없습니다. 릴리스 버전은 제품별로 나누지 않고 카탈로그 전체에서 고유합니다.
별도의 `fdai.runtime-release.v3` 어댑터는 기존 FDAI 전체 서비스 목록과 소스/오프라인 계약을
유지합니다. 관련 없는 앱에 이 형식을 요구하지는 않습니다.

## FDAI 런타임 어댑터 내용

| 필드 | 내용 |
|------|------|
| `product`, `version`, `source_commit` | 제품 식별자, 시맨틱 버전, 정확한 소스 개정 |
| `images` | Core, Operator API, Document Ingestion API, Document Processing Worker, isolated Executor, ClamAV 사이드카, Console 번들, 두 설치 에이전트의 OCI 다이제스트 |
| `sbom`, `provenance` | 각 이미지의 공급망 증거 다이제스트 |
| `schema` | 마이그레이션이 만드는 개정인 `target`과 코드가 받아들이는 개정 범위인 `tolerates` |
| `dependencies` | Hub와 두 설치 에이전트의 지원 버전 범위 |
| `configuration_schema` | 키, 기본값, [수명 주기 구성](lifecycle-configuration-ko.md)에 설명한 `x-fdai-axis` 및 `x-fdai-owner` 주석 |
| `capabilities` | 각 ActionType과 Workflow의 최대 모드, 그리고 기능 회수 |
| `downtime` | 이 업그레이드에 다운타임 구간이 필요한 Entity |
| `workloads` | [워크로드 렌더링 마이그레이션](hub-managed-lifecycle-ko.md#워크로드-렌더링-마이그레이션)에 정의된 대로 수명 주기 에이전트가 렌더링하는 워크로드 템플릿과 스키마 확장 마이그레이션 Job 템플릿 |
| 서명 | 정규화된 매니페스트에 대한 공급업체 release 키의 분리 서명 |

구현된 runtime v3 매니페스트에는 다이제스트와 버전을 고정한 `configuration_schema`
아티팩트를 선택적으로 포함할 수 있습니다.
[Release 스키마 수락 설계와 검토](lifecycle-configuration-ko.md#release-스키마-수락-설계와-검토)에서
이 형식을 정의합니다. Release Hub의 등록과 발행, 독립 pin을 검증하는 Lifecycle Hub의
수락 경로는 공통 구성 검증기로 이 객체를 검증합니다. 기존 매니페스트 서명이 이 바이트도
보호합니다. 객체가 없는 Release는 기존 동작을 유지하지만 이 구성 기능은 제공하지 않습니다.
이 개발용 계약은 프로덕션 Release 적격성을 확립하지 않으며 소스 및 오프라인 설치를 바꾸지
않습니다.

구성된 Lifecycle Hub는 같은 독립 pin의 Release/스키마를
[원자적 구성 가져오기](lifecycle-configuration-ko.md#원자적-가져오기와-구성-소비-설계와-검토)와
영구 저장된 활성 개정 소비 경로에 사용합니다. 카탈로그와 설치의 결정은 같은 트랜잭션을
사용하므로 교체나 회수와 오래된 가져오기/계획 스냅샷 사이의 경쟁을 막습니다. 구성 범위,
서명, 키 버전 이력과 독립 변경 승인은 Release 수락과 별개입니다. 가져오기나 활성화는
Release를 발행하거나 실행 권한을 부여하지 않습니다.

소스 checkout에서 빌드한 이미지에는 공급업체 서명이 없으며 `unverified-source-build`로
표시됩니다. 이런 설치도 Hub에 등록할 수 있습니다. Hub는 검증되지 않은 이미지를 실행하는 모든
Entity를 드리프트 상태로 취급하며, 첫 Plan이 구독한 채널의 서명된 Release로 그 이미지를
바꿉니다.

## 버전

- 버전은 순서가 정해진 시맨틱 버전입니다. [Apollo 버전](https://www.palantir.com/docs/apollo/core/products-releases-versions)과
  마찬가지로 `1.5.0-rc1` 같은 release 후보는 `1.5.0`보다 앞에 정렬됩니다.
- 새 주 버전은 고객이 그 버전을 포함하는 Entity 재정의 블록을 추가한 뒤에만 배포할 수 있습니다.
- 설치는 공급업체가 서명한 회수가 허용하고 더 오래된 Release가 현재 스키마 개정을 허용할 때만
  더 오래된 버전으로 이동합니다.

## Release channel

| 채널 | 받는 Release | 일반적인 구독자 |
|------|--------------|-----------------|
| `DEV` | 게시된 모든 빌드 | 공급업체 테스트 설치 |
| `RELEASE_CANDIDATE` | release 후보와 release | Customer B 같은 얼리 어답터 |
| `RELEASE` | 승격 파이프라인을 통과한 release | 프로덕션 설치 |
| 사용자 지정 | 채널 기여자가 수동으로 추가하거나 파이프라인이 승격한 Release | 적격한 Release를 직접 선별하는 고객, 또는 시범 그룹 |

승격 파이프라인은 채널 순서와 단계별 기준을 정의합니다. 기준에는 보안 검토 완료 같은 필수
라벨, 정상적인 카나리 설치에서의 안정화 시간, 제품 유지 관리 구간, 범위가 정해진 시간 제한이
있습니다. [Apollo 채널 승격](https://www.palantir.com/docs/apollo/core/release-channels)처럼
채널 기여자가 인시던트 수정을 배포하기 위해 Release를 수동으로 추가할 수도 있습니다.
`evaluate_promotion_stage`와 `ReleaseStore.promote_stage`는 Release를 목표 채널로 승격하기 전에
원본 채널 포함 여부, 필수 라벨, 카나리 정상 여부, 최소 안정화 시간, 단계 시간 제한 및 활성
Release/기능 회수 여부를 검증합니다.

Release가 적격해지기 전에 하나씩 검토하려는 규제 고객은 자기 Target Hub에 사용자 지정 채널을
만들고 `RELEASE`의 Release를 수동으로 추가할 수 있습니다. 채널 구성원 관리는 적격성을 선별하는
일이지 설치 승인이 아닙니다. 그 채널을 구독한 설치는 적격한 Release를 여전히 구간 안에서 자동으로
적용합니다.

채널 이름은 한 방향으로만 이전됩니다. `development`는 `DEV`로, `beta`는 `RELEASE_CANDIDATE`로,
`stable`은 `RELEASE`로 매핑됩니다. 이전 전에 서명된 산출물은 기존 이름을 유지하며, 배포 CLI는
검증할 때만 그 이름을 매핑합니다.

**이전 설계 및 검토:** 원래 서명과 정규 형식의 바이트를 검증한 뒤에만 메타데이터를 정규화합니다.
서명된 문서를 다시 쓰면 원본 계보가 무효화됩니다. 새 번들 생산자는 정식 이름만 수락하며,
패키지가 허용하는 채널은 인증된 기존 `development`를 포함한 `DEV`로 유지됩니다.
`beta`나 `stable`을 매핑해도 해당 채널이 허용되지는 않습니다. 알 수 없는 이름은 사용자 지정
채널로 간주하지 않고 보류합니다. 호환성은 한 방향입니다. 이전 바이너리가 정식 이름으로 새로
서명된 산출물을 수락한다고 보장하지 않습니다. 설치 검사, 신뢰 루트, 승격 또는 프로덕션 검증은
추가하지 않습니다.

## 개발용 사용자 지정 채널 관리 설계 및 검토

Release Hub의 기존 운영자 기여 경로는 첫 번째 검토된 구성원 추가와 함께 비어 있지 않은 사용자
지정 채널을 만들 수 있습니다. 이름은 `custom-` 뒤에 소문자 ASCII 영숫자 구간을 단일 하이픈으로
연결하며 전체 길이는 64자 이하입니다. 서명된 번들의 채널 이름을 바꾸지 않고 기본 및 기존
이름과의 충돌을 방지합니다.

기존의 정확한 Release 확인, 카탈로그 리비전, 사유 및 인증된 운영자는 계속 필요합니다.
사용자 지정 기여는 `channel_confirmation`으로 정확한 대상 채널도 확인합니다. 구성원 추가와
담당자가 기록된 이벤트는 한 트랜잭션에서 커밋됩니다. 초안, 회수, 중복, 오래된 리비전 및 잘못된
입력은 둘 다 바꾸지 않습니다. 사용자 지정 구성원은 재시작 후에도 보존되며 내보내기 핀을
바꿉니다. 고객은 해당 정확한 핀을 독립적으로 승인하고 가져온 뒤에야 자신의 카탈로그에 반영합니다.
빈 채널 생성, 이름 변경/삭제, 고객의 Target Hub 자체 채널 관리 및 자동 승격은 이번 범위가 아닙니다.

**검토 및 수정:** 임의 문자열은 기본 이름과 충돌하거나 공백을 숨길 수 있으므로 별도의 제한된
이름 공간을 사용합니다. Release만 확인해서는 새로 입력한 대상을 확인할 수 없으므로 기본 요청은
바꾸지 않고 두 값을 모두 요구합니다. 새 내보내기 해시를 승인으로 간주하거나 채널로 회수, 스키마
제약, 로컬 Plan 권한 또는 효과 검사를 우회하지 않습니다.

## 고객 로컬 채널 관리 설계 및 검토

기존의 인증된 Target Hub 운영자는 가져온 `RELEASE`의 정확한 구성원을 `local-` 채널에 추가할
수 있습니다. 이름은 소문자 ASCII 영숫자 구간을 단일 하이픈으로 연결하며 전체 길이는 64자
이하입니다. 요청은 수락한 카탈로그 해시, 정확한 Release ID/해시, 로컬 리비전, 사유 및 직접
입력한 `add <release> to <channel>` 확인을 결합합니다. 설치의 구독, 원본, 키, 최대 영향 범위
또는 승인 정책을 선택하거나 변경할 수 없습니다.
개발 저장소는 변경 불가능한 로컬 구성원을 최대 1024개까지 지원합니다. 한도에 도달하면 추가를
명시적으로 보류하며, 보존된 집합이 한도를 넘으면 자르지 않고 사용 불가 상태로 처리합니다.

변경 불가능한 구성원 레코드 하나가 담당자를 기록한 감사 레코드이기도 합니다. 명시적 Hub
마이그레이션은 스키마 리비전 4에서 이 테이블을 추가하며, 서비스 제공 중에는 마이그레이션하지
않습니다. 이전 바이너리는 채널 관리를 무시하지 않고 새 스키마를 수락하지 않습니다. 복구는
테이블과 이력을 보존하며 다운그레이드나 파괴적 롤백을 제공하지 않습니다. 기존 배포가 새
바이너리를 사용하려면 명시적 마이그레이션이 필요하지만, 소스/오프라인 설치에 Hub나 새 신뢰
검사를 추가하지 않습니다.

로컬 구성원은 범위를 좁히는 보기입니다. 현재 독립적으로 검증한 카탈로그의 `RELEASE`에 같은
키와 Release 해시를 가진 구성원이 남아 있어야 하며 활성 회수가 없어야 합니다. 알 수 없거나
변경, 철회 또는 회수된 구성원은 허용된 대체값이 아니라 보류된 계보로 표시합니다. 공급업체와
로컬 이름 공간이 충돌하면 어느 쪽도 덮어쓰지 않고 보류합니다. 가져오기, 채널 관리 및 계획은
같은 카탈로그 잠금과 트랜잭션을 사용합니다. 계획 감사는 정확한 수락 핀과 로컬 리비전/해시를
기록하며 공급업체의 원래 바이트와 해시를 다시 쓰지 않습니다.

**검토 및 수정:** 채널 사전을 복사하면 지속적인 승인 근거를 잃고 원본 변경 후에도 오래된
구성원이 남을 수 있습니다. 정확한 바인딩을 저장하고 새로운 보기를 만들 때마다 다시 검사합니다.
채널은 설치 승인, 승격 또는 실행기 권한을 부여하지 않습니다. 이번 추가 전용 개발 범위는
채널 이름 변경/삭제나 이미 발급된 Plan의 자동 회수 교체를 구현하지 않으며, 해당 Plan에는
기존 수명 주기 안전장치가 계속 적용됩니다.

## 구독과 자동 업그레이드

- 설치 설정에는 채널 하나와 선택적인 버전 범위를 지정합니다. FDAI 서비스는 함께 release되므로
  모든 Entity는 설치의 채널을 따릅니다.
- Hub는 각 유지 관리 구간 안에서 채널에 있고 모든 제약 조건을 통과하는 최신 Release를 계획합니다.
  Release가 다운타임이 필요하다고 표시한 Entity는 다운타임 구간을 기다립니다.
- 버전 고정은 `>=1.4.0 <1.5.0` 같은 버전 범위이며, 정확한 버전은 `=1.4.3`처럼 지정합니다.
- 회수 때문에 고정된 범위 안에 적격한 Release가 없으면 Hub는 적격한 Release가 없다고 보고하고
  운영자에게 알립니다. 설치를 범위 밖으로 옮기지는 않습니다.

| 상황 | 권장 구독 |
|------|-----------|
| 표준 프로덕션 | `RELEASE` |
| 변경 위원회가 각 버전을 적격해지기 전에 검토 | 수동으로 추가하는 사용자 지정 채널 |
| 새 기능의 조기 사용 | `RELEASE_CANDIDATE` |
| 인증된 버전이나 연동 때문에 release 계열 하나가 필요 | 검토된 병합으로 넓히는 버전 범위 고정 |
| 공급업체나 고객의 테스트 설치 | `DEV` |

## 회수

- **Release 회수:** 공급업체가 서명한 회수 공지가 나오면 Hub는 그 Release를 더 이상 제안하지
  않고 그 Release를 목표로 하는 대기 중인 Plan을 취소합니다. 그 Release를 실행하는 설치는 회수되지
  않은 적격한 최신 Release로 옮기는 roll-off Plan을 받습니다. roll-off는 다른 Plan보다 우선합니다.
  수동 억제 구간은 여전히 roll-off를 막으며, 이때 Hub는 알림을 보냅니다.
- **기능 회수:** Release나 서명된 회수 공지는 `shadow` 모드로 돌아가야 하는 ActionType과
  Workflow를 지정할 수 있습니다. 권한을 낮추는 일은 항상 허용되므로 설치는 유지 관리 구간과
  관계없이 즉시 강등합니다. 이후 Release가 회수를 해제할 때까지 같은 기능의 새 승격을 막으며, 이
  우선순위는 운영자 재정의 승격에도 적용됩니다.
- 오프라인 설치는 운영자가 회수를 담은 번들을 가져올 때 회수를 적용합니다.

Release Hub는 Release 범위 회수와 기능 범위 회수·해제 이벤트를 모두 기록하고 서명된
`RecallRecord` 항목으로 내보내며, Release 자체나 선언된 `capability_maximums` 중 하나가 해제
Release 미만의 활성 회수 상태이면 수동 채널 승격(`contribute`)을 거부합니다. 관리 대상 Entity가
직접 회수되었거나 선언된 기능 회수에 걸린 Release를 실행 중이면 Lifecycle Hub 플래너는 구독
채널에서 스키마, 구간, 재정의 제약을 통과하는 회수되지 않은 최신 Release로 `recall-rolloff`
Plan을 발급합니다. 이 Plan은 열려 있는 `upgrade` Plan을 대체하고 `plan:upgrade` 억제를
우회하되 수동 설치 및 Entity 억제는 그대로 존중합니다.

## 카탈로그 무결성

서명은 누가 기록을 게시했는지를 증명하지만 그 기록이 최신이라는 것은 증명하지 않습니다. 그래서
공급업체는 [The Update Framework(TUF)](https://theupdateframework.io/)를 따라 카탈로그 메타데이터를
역할별로 나누어 서명합니다.

- root 기록은 다른 모든 기록에 서명할 수 있는 키를 지정합니다. 오프라인 키의 임계값을 통해서만
  바뀝니다.
- snapshot 기록은 모든 채널 구성원 기록과 회수 기록의 현재 버전을 나열합니다.
- timestamp 기록은 현재 snapshot을 지정하며, 공개된 짧은 간격이 지나면 만료됩니다.
- 모든 기록은 증가만 하는 버전을 가집니다. 설치와 Target Hub는 더 낮은 버전을 거부하며, 각
  업그레이드 번들은 자신이 확장하는 이전 번들을 명시합니다.
- 회수 공지는 제품별 순번을 가지므로 보류된 회수는 순번 공백으로 드러납니다.

timestamp 기록이 만료되면 설치는 회수 roll-off Plan만 받아들이고 알림을 보냅니다. 또한 운영자
재정의 승격은 회수를 안전망으로 삼으므로, 새 메타데이터가 도착할 때까지 이를 `shadow` 모드로
되돌립니다. 오프라인 Target Hub는 번들 주기에 맞춰 만료 간격을 정합니다.
`evaluate_catalog_integrity`는 임계값 root 서명, 단조 증가 버전 및 회수 순번 연속성
(`recall_sequence_gap`)을 검증하며, `StateStoreActionPromotionRegistry.set_catalog_timestamp_expired`는
timestamp 메타데이터가 만료된 동안 운영자 재정의 승격을 `shadow` 모드로 되돌립니다.

### Hub의 서명된 카탈로그 역할

Hub는 이 역할을 개발용 키 하나를 대체하는 선택적 모드로 구현합니다. Lifecycle Hub는
`catalog.trust`가 `mode: "tuf"`일 때 이 모드로 들어갑니다. 설정하지 않으면 단일 키 서명 내보내기와
서명되지 않은 pin 흐름은 이전과 똑같이 동작합니다. Release Hub는 고객을 호출하지 않고, Lifecycle
Hub가 계속 polling하며, 자동 채택은 여전히 Rego가 결정하고, 모든 실패는 후보를 거부합니다.

| 역할 | 보유자 | 서명하는 대상 |
|------|--------|---------------|
| Root | 사람이 보관하는 오프라인 키의 임계값. 어떤 Hub 데이터베이스나 프로세스도 root 개인 키를 갖지 않습니다. | 모든 역할의 키 id와 공개 키, 임계값, 버전, 만료. 새 root는 이전 root 키의 임계값과 자신의 키 임계값이 모두 서명해야 효력이 생깁니다. |
| Snapshot | 다른 모든 키와 분리된 온라인 키 하나 | 내보내기 다이제스트와 revision, 채널 목록별 버전, 각 Release 매니페스트의 다이제스트, 회수 순번 `1..N` |
| Timestamp | 두 번째 온라인 키 | 현재 snapshot의 버전과 다이제스트, 그리고 짧은 만료(기본 24시간) |
| Export(targets) | 기존 내보내기 키. 이제 root가 `export_key_ids`로 지정합니다. | `fdai.catalog-export.v1` 아래의 정확한 내보내기 바이트와 각 Release 매니페스트 |

각 역할은 자신의 도메인으로 서명합니다. `fdai.catalog-root.v1`, `fdai.catalog-snapshot.v1`,
`fdai.catalog-timestamp.v1` 중 하나, 줄바꿈, 그다음 정규 payload입니다. 한 역할의 서명은 다른
역할이나 내보내기 서명을 대신할 수 없습니다. 키는 Ed25519입니다. 키 id는 `ed25519-`와 원시 공개 키의
SHA-256이므로 id가 다른 키를 가리킬 수 없습니다. root는 공개 키를 담습니다. 새 선택 필드
`export_key_ids`, `public_keys`, `export_digest`, `export_revision`을 생략한 기존 root와 snapshot
기록은 정규 payload를 그대로 유지합니다.

| 항목 | 결정 |
|------|------|
| 메타데이터 | `GET /v1/catalog/metadata`는 root 체인, snapshot, timestamp를 `ETag`가 있는 문서 하나로 반환하며, 내보내기와 같은 공개 또는 인증 규칙을 따릅니다. Release Hub는 내보내기 다이제스트가 바뀌거나, 기록이 없거나, snapshot 유효기간이 3분의 1만 남았을 때만 서명합니다. 응답은 내보내기 다이제스트와 영속 버전 카운터로 캐시하므로 요청이 몰려도 작은 상태 조회 한 번이고 서명은 하지 않습니다. |
| Timestamp 갱신 | 갱신 작업은 만료 전에 timestamp만 다시 서명합니다. `renew` 이벤트를 추가하지 않고, 내보내기와 revision은 바이트 단위로 같으며, 카운터를 잠긴 행 하나가 보관하므로 복제본이 여럿이어도 버전은 증가만 합니다. |
| Root 설정 의식 | `fdai-release-hub root keygen`, `build`, `sign`, `verify`는 오프라인으로 실행합니다. 각 보유자는 권한 `0600`의 개인 키 파일로 서명합니다. `install-catalog-root`는 체인과, root가 Hub 자신의 snapshot, timestamp, export 키를 승인하는지 확인한 뒤에야 공개 기록을 저장합니다. |
| 신뢰 pin | `catalog.trust`는 `release_public_key` 대신 `mode`, `root_key_ids`, `root_threshold`를 가집니다. 첫 root는 정확히 그 키와 임계값을 지정해야 합니다(MUST). 이후 root가 pin을 바꾸지는 않습니다. |
| 검증 | Lifecycle Hub는 pin에서 시작해 root 체인, snapshot과 timestamp, root가 지정한 export 키의 내보내기 서명, snapshot이 묶는 내보내기 다이제스트와 revision, 채널 목록, 매니페스트 다이제스트, 회수 순번을 검증하고, 임계값, 버전, 회수 연속성, 만료는 `evaluate_catalog_integrity`로 검증합니다. |
| 영속 하한 | Hub는 검증한 root, snapshot, timestamp의 최고 버전과 다이제스트, 최고 회수 순번, 채널 버전을 영속합니다. 낮은 버전은 롤백입니다. 같은 버전에 내용이 다르면 이중 서명(equivocation)입니다. 하한은 재시작 후에도 유지되고 채택과 함께 전진합니다. |
| 정책 입력 | Rego는 `verified`, `expired`, `root_rotation`을 가진 `integrity`를 받습니다. 새 거부 사유는 `integrity_not_verified`, `timestamp_expired`, `root_rotation_requires_review`입니다. `integrity`가 없으면 어느 것도 발동하지 않습니다. |
| 만료된 timestamp | Hub는 여전히 역할을 검증합니다. 회수로만 이루어진 후보만 채택하고, 그 밖의 변경은 운영자 apply도 거부하며, `recall-rolloff`만 계획합니다. 수락한 카탈로그가 허용 계획 유형 집합을 가지며 플래너는 다른 모든 계획 유형을 `catalog_timestamp_expired`로 막습니다. Updates 화면이 이를 알려 줍니다. |
| Root 교체 | 교체는 다른 root처럼 검증되지만 자동으로 채택되지 않으며, 사람이 Updates에서 적용하기 전에는 영속 root가 전진하지 않습니다. |
| 저장소 | 선택 테이블 `catalog_integrity_state`(Lifecycle Hub, `bind-catalog`가 생성)와 `catalog_role_root`, `catalog_role_state`(Release Hub, `install-catalog-root`가 생성)는 어느 스키마 revision도 올리지 않으므로 이전 바이너리는 무시합니다. |
| 호환성 | 역할을 설치한 Release Hub는 기존 내보내기 유효기간 연장을 멈추므로 소비자를 먼저 `tuf`로 옮겨야 합니다. 이미 묶은 데이터베이스는 바뀐 신뢰를 거부하므로(`bind-catalog`가 명시적 재바인딩을 요구) 기존 설치를 전환하려면 신뢰를 새로 묶어야 합니다. |

**검토와 수정.** 온라인 키를 설정이 아닌 root에 명시하면 교체로 그 키를 폐기할 수 있으므로, root가 더는
승인하지 않는 키를 가진 Release Hub는 승인되지 않은 키로 서명하는 대신 메타데이터 제공을 거부합니다.
역할을 쓰면 신선도는 서명된 timestamp와 snapshot에서 나오므로 `tuf` 모드에서는 내보내기 자체의
`expires_at`을 강제하지 않습니다. 이벤트 revision이 연속적이지 않으므로 회수 순번은 내보내기에 담긴
회수의 개수를 셉니다. 연속성 검사는 보류되거나 누락된 회수를 잡지만 snapshot 키와 내보내기 키가
모두 탈취된 경우에는 도움이 되지 않습니다. 내보내기 키 하나가 모든 매니페스트에 서명하므로 이를
폐기하려면 모든 매니페스트를 다시 서명해야 하며, 그때까지 `export_key_ids`에 남습니다. root 체인은 최대
32개로 제한합니다. snapshot과 timestamp 키는 비밀 참조에서 오므로 하드웨어 보관 키는 운영자의
선택이며 이 설계가 강제하지 않습니다.

**아직 구현하지 않은 것.** 보관 영수증을 남기는 프로덕션 root 설정 의식은 운영자 절차로 남습니다.
설치본의 승격 레지스트리에 `demote_operator_overrides_to_shadow`를 연결하는 일, 개발 스택에서
root를 설치하는 전용 작업 Job, 데이터베이스 검사에서 선택 테이블의 지문을 계산하는 일도 남아 있습니다.

## 스키마 호환성

데이터베이스 마이그레이션은 expand/contract 방식과 전진 전용을 유지합니다. [배포](deployment-ko.md)는
이미 데이터베이스 범위 잠금으로 마이그레이션을 직렬화하고, 기한을 제한하며, 새 개정이 트래픽을
받기 전에 실행합니다.

| 단계 | 변경 | 실행 방식 | 롤백 대상 |
|------|------|-----------|-----------|
| 확장 | 추가 스키마만 변경 | 워크로드가 전환되기 전에 Release의 마이그레이션 작업으로 실행 | 확장된 스키마를 허용하는 이전 Release |
| 전환 | 워크로드가 새 Release로 이동 | 수명 주기 에이전트의 워크로드 단계 | 이전 Release |
| 축소 | 이후 Release에서 이전 형태를 제거 | 특정 시점 복원 체크포인트 후의 마이그레이션 작업 | 그 형태에는 없음. 전진 수정만 가능 |

- 업그레이드는 목표 Release가 현재 스키마 개정을 허용하고, 그 마이그레이션이 현재 개정에서 앞으로만
  진행할 때 적격합니다.
- 롤백은 더 오래된 Release가 현재 스키마 개정을 허용할 때만 적격합니다. 그렇지 않으면 설치는
  운영자 판단과 전진 수정을 기다립니다.
- 축소 Release는 설치가 지원 기간 안에 롤백할 수 있는 모든 Release가 축소된 형태를 허용하고,
  복원 체크포인트가 기록된 뒤에만 예약됩니다.
- 중간에 멈춘 마이그레이션은 설치를 억제합니다. 다음 Plan은 같은 잠금 아래에서 같은 전진
  마이그레이션을 재개하며, 어떤 Release도 허용하지 않는 형태에서 실행하지 않습니다.

현재 Hub 플래너는 Plan에 서명하기 전에 파싱한 Release와 설치가 보고한 스키마 개정을
공유 전환 검증기에 전달합니다. 허용 범위는 양 끝값을 포함하며, 업그레이드는 현재 개정보다
낮은 목표 스키마도 수락하지 않습니다. 롤백과 회수 roll-off에는 별도의 방향 규칙을 유지합니다.
에이전트의 워크로드 검증기는 클러스터 호출 전에 지원하지 않는 스키마 변경을 보류합니다.

애플리케이션 구성 요소 Release에는 엄격한 `fdai.schema-expand-job.v1` 객체를 포함할 수 있습니다.
이 객체는 `fdai.migration-classification.v1`의 확장 전용 개정 맵과 실행 기한을 서명된 매니페스트에
결속합니다. Agent는 이 객체에서 임의 명령을 렌더링하지 않고, 고정된 Core 이미지 실행기와 설치에서
검토한 런타임 참조를 사용합니다. 완료한 Kubernetes Job이 스키마 증적이며 워크로드 롤백 후에도
유지됩니다. 보고하는 스키마 개정은 이 Job의 유효한 완료 증적이 있을 때만 앞으로 이동합니다.
축소 개정은 이 단계에서 지원하지 않으며 이후 복원 체크포인트 Plan이 필요합니다.

## 산출물 전달

### 연결된 설치

설치는 각 Release의 이미지를 경계 안의 자체 컨테이너 레지스트리로 가져옵니다.
[Apollo 제약 조건](https://www.palantir.com/docs/apollo/core/plans-and-constraints)처럼 산출물 누락
제약 조건은 필요한 모든 다이제스트가 있을 때까지 Plan을 차단합니다.
`BoundaryRegistryMirror`는 경계 안에 미러링된 변경 불가능한 `sha256:<hex>` 다이제스트를 추적하여
`available_artifact_digests`에 반영하며, 필요한 모든 이미지 다이제스트가 미러링될 때까지
`plan_next`가 `artifact_unavailable`로 해당 Release를 차단합니다.

### 오프라인 설치

업그레이드 번들에는 Release, 채널 구성원, 회수 공지, Target Hub에 아직 없는 최소한의 이미지
레이어가 들어 있습니다. 공급업체 release 키가 번들의 체크섬 목록에 서명합니다. 고객은 전송
매체에 자체 서명한 구성 패키지를 함께 넣을 수 있으며, Target Hub는 각 패키지 서명을 따로
검증합니다.

1. 운영자가 번들을 Target Hub로 가져옵니다.
2. Target Hub는 서명과 모든 체크섬을 검증하고, 이미지를 경계 안의 레지스트리에 게시하며,
   카탈로그를 갱신합니다.
3. Plan은 일반적인 제약 조건 아래에서 진행됩니다.

`verify_and_import_upgrade_bundle`은 정규 체크섬 매니페스트의 공급업체 서명을 검증하고, 카탈로그
내보내기와 모든 최소 이미지 레이어의 다이제스트를 대조하며, 함께 첨부된 각 고객 구성 패키지 서명을
개별적으로 검증한 뒤 검증된 레이어 다이제스트를 `BoundaryRegistryMirror`에 게시합니다.

첫 설치용 오프라인 패키지는 현재 계약을 유지합니다. Hub 관리형 오프라인 사이트에서는 이 패키지에
Target Hub도 들어 있습니다.

## Release 데이터 모델

| 테이블 | 키 | 용도 | 시간 필드 | 변경 방식 |
|--------|-----|------|-----------|-----------|
| `release` | `release_id` | 제품, 버전, 매니페스트 다이제스트, 서명, 스키마 범위, 의존성 | `published_at`, `recorded_at` | 변경 불가 |
| `release_artifact` | `release_id`, `artifact` | 이미지 다이제스트, SBOM 다이제스트, provenance 다이제스트 | `recorded_at` | 변경 불가 |
| `release_channel` | `channel_id` | 이름, 기본 또는 사용자 지정 여부, 소유 Hub | `effective_from` | 개정 관리 |
| `channel_membership` | `channel_id`, `release_id` | 파이프라인 또는 수동 추가 여부와 수행자 | `added_at` | 추가 전용. 제거는 새 행입니다. |
| `promotion_pipeline` | `product`, `revision` | 단계 순서와 기준 | `effective_from` | 개정 관리 |
| `promotion_run` | `run_id` | 단계 결과와 안정화 관측 | `started_at`, `finished_at` | 추가 전용 |
| `recall` | `recall_id` | Release 또는 기능 범위, 사유, 순번, 서명된 공지 다이제스트 | `issued_at`, `recorded_at` | 추가 전용. 해제는 새 행입니다. |
| `catalog_record` | `role`, `version` | root, snapshot, timestamp 기록과 그 서명 | `signed_at`, `expires_at`, `recorded_at` | 추가 전용 |
| `bundle_import` | `bundle_id` | Target Hub의 체크섬 다이제스트와 가져오기 결과 | `imported_at` | 추가 전용 |

## 현재 한계

- 서명된 배포 번들과 오프라인 키트는 한 방향 채널 이전을 구현합니다. 로컬 Release Hub도
  위에서 명시한 제한된 개발 기능을 제공하지만, 프로덕션 카탈로그 신뢰, 자동 승격 및 배포는
  미완료입니다.
- 프로덕션 신뢰 루트 절차를 아직 수행하지 않았습니다. Hub 경로가 Release를 검증하려면 먼저
  공급업체 release 키가 있어야 합니다.
- 서명된 번들의 재현 가능한 이중 빌드 검증이 남아 있습니다.
- runtime v3 Release는 스키마 범위, 기능 최대값과 다운타임 메타데이터를 선언합니다.
  로컬 계획과 효과 발생 전 검증은 구현되어 있습니다. 실제 스키마 마이그레이션과 이전
  바이너리의 롤백 검증은 별도 운영 작업으로 남아 있습니다.

## 관련 문서

| 알아볼 내용 | 참고 문서 |
|-------------|-----------|
| 수명 주기 아키텍처와 Plan | [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md) |
| 구성 계층과 패키지 | [수명 주기 구성](lifecycle-configuration-ko.md) |
| 서명된 번들과 배포 CLI | [설치 가능한 배포 CLI](installable-deployment-cli-ko.md) |
| 현재의 오프라인 전달 | [연결 끊김 배포](disconnected-deployment-ko.md) |
| 제품화 계획의 채널 이력 | [제품화 및 확장성](../fork-and-sequencing/productization-and-extensibility-ko.md) |
| 결정 기록 | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance-ko.md) |
| 제공 현황과 남은 작업 | [구현 ledger](../../roadmap-implementation/deployment/lifecycle-releases-and-channels.md) |
