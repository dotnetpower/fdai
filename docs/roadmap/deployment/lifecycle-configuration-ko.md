---
title: 수명 주기 구성
translation_of: lifecycle-configuration.md
translation_source_sha: a1fd6149226d6a4d8a95fb1c23d27bb8149b15dc
translation_revised: 2026-10-21
---
# 수명 주기 구성

이 문서는 설치가 원하는 수명 주기 구성을 작성하고, 계층화하고, 패키지로 만들어 Lifecycle Hub에
전달하는 방법을 정의합니다. 또한 그 구성을 고객 식별자, 비밀, 정책, 권한과 분리합니다. 이 문서는
값 분류, 구성 계층, 서명된 구성 패키지를 소유합니다.

> **상태:** 스키마, 계층 및 비밀 참조 검증기, 오프라인 서명 패키지 생성기와 읽기 경로,
> 단일/다중 Entity 로컬 패키지 생성/검증 CLI, 설치 키 봉인과 명시적인 메모리 내 Hub 계획 소비
> 경로가 구현되어 있습니다. 자리 표시자 저장소 템플릿과 키 보관 런북도 제공합니다. 인증된 공개 키
> 등록/교체, 영구 저장된 키에 결합한 Hub 계획, 원자적 서명 패키지 가져오기, 독립적인 범위/변경
> 승인과 활성 개정의 영속 소비 경로를 로컬 검증용으로 구현했습니다. 실제 등록과 운영 Agent
> 전달은 아직 남아 있습니다.
> [구현 ledger](../../roadmap-implementation/deployment/lifecycle-configuration.md)가 제공 현황을
> 추적합니다.
>
> **범위:** Hub가 이 구성을 어떻게 쓰는지는 [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md)가
> 소유합니다. 승인 정책과 허용 정책은 구성이 아니며
> [운영자 거버넌스 프로필](../decisioning/operator-governance-profiles-ko.md)이 소유합니다.

## 설계 한눈에 보기

| 관심사 | 결정 |
|--------|------|
| 원본 | 고객 소유 Git 저장소입니다. 검토된 병합이 변경 요청입니다. |
| 전달 | 병합된 개정마다 서명된 구성 패키지 하나를 만듭니다. 패키지는 전체 개정을 담고 이전 개정을 명시합니다. |
| 계층 | Release 기본값, Environment Config, Release 버전 범위별 Entity 재정의 블록 순서입니다 |
| 재정의 누락 | 일치하는 재정의 블록이 없는 Release는 배포하지 않습니다 |
| 고객 식별자 | 설치 키로 봉인합니다. Hub는 암호문과 다이제스트만 저장합니다. |
| 비밀 | Key Vault 참조만 사용합니다. Azure가 허용하는 곳에서는 관리 ID가 자격 증명을 대신합니다. |
| 권한 | 절대 구성이 아닙니다. 정책 개정과 승격 레지스트리가 소유합니다. |

## 값 분류

설치에 필요한 모든 값은 정확히 하나의 분류에 속합니다. 분류에 따라 소유자, 저장 위치, 변경
방법, Hub가 볼 수 있는 범위가 정해집니다.

| 분류 | 예 | 소유자 | 저장 위치 | 변경 방법 | Hub가 보는 것 |
|------|-----|--------|-----------|-----------|---------------|
| 수명 주기 구성 | 리전, 채널, 구간, 크기, 복제본 수, 모델 용량 유형, 연동 종류 | 고객 | 고객 Git, 이어서 구성 패키지 | 검토된 병합 | 값 |
| 봉인된 식별자 | 테넌트 ID, 구독 ID, 리소스 이름, 엔드포인트 URL, 클라이언트 ID | 고객 | 패키지의 봉인 섹션 | 검토된 병합 | 암호문과 다이제스트 |
| 비밀 참조 | API 키나 연동 토큰을 담은 Key Vault 비밀의 이름 | 고객 | 이름은 패키지에, 값은 Key Vault에 | 이름은 병합으로, 값은 Key Vault에서 | 이름만 |
| 정책 개정 | 승인 정책, 허용(OPA/Rego) 정책 | 설치 운영자 | 설치 PostgreSQL | Console 정책 관리 | 다이제스트만 |
| 권한 상태 | 승격 상태, 상시 권한, kill switch, 승인 프로필 | 설치 거버넌스 | 설치 저장소 | 관리되는 권한 경로 | 다이제스트와 개수 |
| 런타임 상태 | 보고 상태, 증적, 운영 데이터 | 설치 | 설치 | 구성할 수 없음 | 수명 주기 메타데이터만 |

Release 구성 스키마의 각 구성 키는 `x-fdai-axis`와 `x-fdai-owner` 주석으로
[ADR-0002](../architecture/decisions/0002-independent-runtime-axes-ko.md)의 축과 소유자를
선언합니다. 패키지 생성기는 두 주석이 모두 없는 키를 거부합니다. 액션 수명 주기, 승인 프로필,
권한 확인 정책, 상시 권한 같은 권한 축에 속한 키도 거부합니다.

### Release 스키마 수락 설계와 검토

Runtime Release v3에는 선택적 `configuration_schema` 객체를 넣을 수 있습니다. 필드는
`format`(`fdai.release-configuration-schema.v1`), `release_version`, `schema_sha256`,
`keys`로 한정합니다. `keys`는 기존 `x-fdai-axis`, `x-fdai-owner`와 선택적 `default`를
사용합니다. 두 주석을 모두 명시하고 구성 소유자는 `customer`로 지정합니다.
알 수 없는 메타데이터, 공백뿐이거나 알 수 없는 소유자,
지원하지 않는 축이나 권한 축, 권한 상태 키는 수락하지 않습니다. `schema_sha256`은
정규화한 `keys` 바이트를 고정합니다. 전체 객체는 기존 매니페스트 다이제스트와 분리 서명에
포함됩니다.

**검토와 보완:** 매니페스트 옆의 스키마 파일, 호출자가 선택한 키, 다운로드와 함께 받은
다이제스트만으로는 Release를 신뢰할 수 없습니다. Release Hub는 등록과 발행 시 스키마와
정확한 Release 버전을 검증합니다. Lifecycle Hub는 별도로 승인된 export pin과 기존
매니페스트 서명을 먼저 검증한 뒤 같은 스키마와 버전의 결합을 확인합니다. 수락한 스키마는
해당 Release에서 제공하며, 독립적으로 신뢰할 수 있는 스키마 파일로 취급하지 않습니다.
기존 Hub 플래너는 Plan을 발행하기 전에 설치 구성의 스키마 다이제스트를 해당 Release
스키마와 비교합니다. 다르면 그 후보를 차단합니다. 발행 경로도 서명 전에 저장된 초안의
매니페스트 다이제스트를 다시 확인하므로 바이트가 바뀐 초안은 기존 식별자를 재사용할 수
없습니다.
서명 키, 채널 소속, 로컬 패키징 결과는 프로덕션 적격성을 부여하지 않습니다.

이 기능은 권한을 부여하지 않는 개발용 기능이며 프로덕션 신뢰 루트 설정이 아닙니다.
메타데이터가 없는 Release에서는 구성 스키마 기능을 사용할 수 없습니다. 기존 Release는
계속 읽을 수 있고 소스 및 오프라인 설치에 새 전제 조건이 생기지 않습니다. 프로덕션
Release 적격성 확인, 구성 가져오기, Agent 전달, 고객 키 등록은 별도 작업입니다.

## 일반 항목의 위치

| 항목 | 분류 | 위치 | 참고 |
|------|------|------|------|
| Azure 리전 | 구성 | Environment Config | 데이터 상주 제약 조건에 쓰입니다 |
| 구독 ID | 봉인 | Environment Config의 봉인 섹션 | 설치도 자기 바인딩으로 이를 증명합니다 |
| 리소스 그룹 | 봉인 | Environment Config의 봉인 섹션 | 이름은 [리소스 규칙](deployment-resource-conventions-ko.md)을 따릅니다 |
| 모델 엔드포인트 | 봉인 | 모델 바인딩의 `endpoint_ref`. 설치 안에서 해석합니다. | Hub는 URL을 보지 못합니다 |
| 모델과 배포 이름 | 구성 | 모델 바인딩 | 비밀이 아닙니다 |
| PTU | 구성 | 용량 종류가 `ptu`이고 단위 수가 있는 모델 바인딩 | Settings의 모델 인벤토리가 확인합니다 |
| 테넌트 ID | 봉인 | Environment Config의 봉인 섹션 | 비밀이 아니라 식별자입니다 |
| 클라이언트 ID | 봉인 | Entity 재정의 블록 | 클라이언트 비밀이 없는 관리 ID를 권장합니다 |
| 클라이언트 비밀 | 비밀 | 사용하지 않는 것이 좋습니다. 연동에 꼭 필요하면 Key Vault에 저장하고 이름으로 참조합니다. | 고객이 교체합니다 |
| API 키 | 비밀 | 이름으로 참조하는 Key Vault 비밀 | 런타임 T1과 T2 모델 바인딩은 키가 아니라 Microsoft Entra ID를 사용합니다 |
| 데이터베이스 연결 | 파생 | 관리 ID와 프라이빗 엔드포인트로 설치 안에서 만듭니다 | 서비스가 소유한 DSN에는 암호가 없습니다 |
| ITSM 엔드포인트 | 봉인 | 연동 바인딩 | 자격 증명은 별도의 비밀 참조입니다 |
| OPA 정책 | 정책 개정 | FDAI Console을 통한 설치 정책 저장소 | Release가 기준 정책을 제공합니다 |
| 승인 정책 | 정책 개정 | FDAI Console을 통한 설치 정책 저장소 | 그 안의 승인 프로필은 권한 상태입니다 |

## 구성 계층

설치는 다음 순서로 실제 구성을 결정합니다.

1. **Release 기본값:** 서명된 Release 안에 들어 있는 구성 스키마와 기본값입니다.
2. **Environment Config:** 리전, 상주, 네트워크 프로필, 모델 바인딩처럼 설치 전체에 적용되는
   값입니다. 채널, 버전 범위, 유지 관리 구간, Entity 목록 같은 설치 설정도 같은 패키지에 들어
   있습니다.
3. **Entity 재정의 블록:** Entity 하나와 Release 버전 범위 하나에 대한 값입니다.
   [Apollo config overrides](https://www.palantir.com/docs/apollo/managing-entities/set-config-overrides)처럼
   목표 Release를 포함하는 가장 구체적인 범위가 우선합니다. Entity 재정의는 Environment Config
   키를 참조할 수 있습니다.

뒤 계층의 키가 앞 계층의 같은 키를 대체합니다. 패키지 생성기는 결과를 목표 Release의 구성
스키마로 검증하고, 알 수 없는 키, 권한 키, 봉인 섹션 밖의 봉인 키를 거부합니다. 어떤 재정의
블록도 Release의 주 버전을 포함하지 않으면 그 Release는 해당 Entity에 배포할 수 없습니다. 이
규칙 덕분에 고객은 어떤 주 버전을 받아들일지 미리 정할 수 있습니다.

처음 제안된 5개 계층은 이 모델에 다음과 같이 대응합니다.

| 제안된 계층 | 위치 |
|-------------|------|
| 제품 기본값 | Release 기본값 |
| 환경 구성 | Environment Config와 설치 설정 |
| 고객 정책 | 정책 개정. 구성이 아닙니다. |
| Entity 구성 | Entity 재정의 블록 |
| 런타임 재정의 | 만료가 있는 명령. 구성 계층이 아닙니다. |

## 고객 Git과 구성 패키지

고객은 자기 Git 저장소에 설치마다 디렉터리 하나를 둡니다.

```text
installations/<installation-id>/
  installation.yaml   # channel, version range, maintenance windows, Entities
  environment.yaml    # Environment Config values that the Hub may read
  sealed.yaml         # identifiers and endpoints, sealed during packaging
  entities/
    core.yaml         # Entity override blocks by Release version range
```

저장소는 고객의 통제 아래 있으므로 `sealed.yaml`에는 읽을 수 있는 값을 둘 수 있습니다. 봉인은
그 값을 고객이 아니라 Hub로부터 보호합니다.

1. 보호된 브랜치에 검토된 병합이 들어오면 고객의 파이프라인이나 `fdaictl`에서 패키지 생성을
   시작합니다.
2. 패키지 생성기는 모든 계층을 검증하고, 등록할 때 받은 설치 공개 키로 봉인 섹션을 암호화하며,
   개정 ID, Git 커밋, 이전 개정 다이제스트, 내용 다이제스트를 기록합니다.
3. 고객 구성 키가 패키지에 서명합니다.
4. 패키지는 Hub에 업로드되거나, 오프라인 Target Hub용 업그레이드 번들에 함께 담겨 전달됩니다.
5. Hub는 서명과 이전 개정 다이제스트를 검증합니다. 누락되었거나 분기된 개정이 있으면 그 공백이
   해소될 때까지 가져오기를 차단합니다.
6. Hub가 Plan을 다시 계산합니다. 설치 에이전트는 서명을 다시 검증하고 봉인된 값을 설치 안에서만
   복호화합니다.

구성 롤백은 새 개정을 만드는 되돌리기 커밋입니다. 오래된 패키지를 현재 개정으로 다시 가져오지
않습니다. 비상 해제 변경은 병합된 변경이 이를 채택하지 않은 한 만료될 때 승인된 개정으로
조정됩니다.

## 오프라인 패키지 경계와 설계 검토

배포 CLI 라이브러리는 오프라인 패키지 생성기와 읽기 경로를 소유합니다. 정규 JSON
매니페스트는 기존 `schema`, `environment`, `entity_overrides` 문서 전체와 대상 Release
버전, 전체 Git 개정, 이전 패키지 다이제스트, 설치 암호화 키 다이제스트, 봉인된 식별자를
결합합니다. 고객의 분리된 Ed25519 서명이 정확한 매니페스트 바이트를 보호합니다. 이 컨테이너는
기존 Hub/Agent 구성 입력 계약을 대체하지 않습니다. 가져오기와 독립적으로 검증된 입력 추출은
별도 연결 작업이 필요합니다.

읽기 경로는 신뢰할 수 있는 Release 스키마와 고객 검증 키를 패키지가 아닌 호출자에게 받습니다.
호출자는 신뢰할 수 있는 봉인 키 분류도 제공하므로 패키지가 식별자를 공개 구성으로 재분류할 수
없습니다. 서명하거나 패키지를 수락하기 전에 일치하지 않는 재정의와 기본값을 포함한 모든 계층을 검증합니다.
적용 범위가 없으면 패키지 생성을 보류합니다. 호출자는 이전에 수락한 전체 체인을 제공합니다.
누락된 개정, 경쟁하는 후속 개정, 재사용한 개정, 순서 변경은 차단됩니다. 동일한 입력으로 같은
개정을 재시도하면 무작위 암호문을 포함한 원래 서명 바이트를 반환합니다. 영구 저장과 체인 끝의
원자적 갱신은 가져오기 경로의 책임으로 남습니다.

식별자 암호화는 설치가 소유하는 X25519 암호화 키, HKDF-SHA256, 인증된 AES-256-GCM을
사용합니다. 등록용 Ed25519 ID 키는 서명 키이며 암호화 키가 아닙니다. 변환하거나 재사용하지
않습니다. 운영에 사용하려면 등록 경로에서 암호화 공개 키를 설치에 연결해야 합니다. 암호화와
서명 전에 평문 값의 비밀 필드를 검사하며, 패키지 메타데이터에는 암호문과 다이제스트만 남습니다.

설계 검토와 수정(2026-10-21): 내장 스키마를 신뢰하면 고객이 권한 키를 잘못 분류할 수 있으므로
읽기 경로는 독립적으로 제공된 스키마를 요구합니다. 무작위 봉인은 재시도마다 다른 패키지를
만들 수 있으므로 검증된 이력과 입력 다이제스트로 원래 바이트를 유지합니다. 호출자가 제공한
이력만으로 동시 쓰기를 막을 수 없으므로 이 오프라인 라이브러리는 영구 가져오기나 운영 전달을
보장하지 않습니다.
비교 연산자 순서가 달라도 동일한 재정의 구간은 모호한 입력으로 처리합니다. 기본값도 봉인
섹션 경계를 우회할 수 없습니다.

구현은 `fdai_deployment_cli.lifecycle_configuration_package`와
`fdai_deployment_cli.lifecycle_configuration_sealing`에 있습니다. 기존 단일 Entity 구성
문서는 바뀌지 않습니다. 전체 다중 Entity 소스 경로는 아래에서 정의합니다. 실제 암호화 키
등록과 Agent 전송 및 복호화 연결은 아직 남아 있습니다. 아래의 원자적 Hub 가져오기 경로가
오프라인 라이브러리와 별도로 소스의 영속 저장을 담당합니다.

### 전체 다중 Entity 개정 설계와 검토

권한을 바꾸지 않는 `fdai.lifecycle-configuration-package.v2` 형식은 v1의 서명 묶음 필드와
암호화 방식을 유지하며, 정확한 Release 매니페스트의 `release_digest`를 추가합니다.
`configuration`에는 `schema`, `environment`, `entities` 배열이
있습니다. 각 항목은 `entity_id`와 `entity_overrides`만 포함하며 `entity_id` 순으로 정렬합니다.
중복과 정규 순서가 아닌 배열은 수락하지 않습니다. 패키지의 `entity_id`는 설치가 독립적으로
제공한 소문자 16진수 64자리의 불투명한 연결 값입니다. 고객 이름, 리소스 ID나 고객 이름의
해시를 사용하지 않습니다. 이 값은 구성을 구별할 뿐 소유권이나 권한을 입증하지 않습니다.

Hub에 등록된 기존 Entity 식별자는 다른 어휘이며, 소문자, 숫자와 하이픈으로 최대 63자입니다.
등록, 저장소와 서명된 Plan에서 이 식별자를 바꾸지 않습니다. 일시적인 플래너 후보에는 정확한
설치 식별자와, 이미 관리 중인 Entity 식별자를 패키지 연결 값에 일대일로 대응시키는 독립적인
매핑이 필요합니다. 고객 이름에서 불투명한 연결 값을 만들지 않고 매핑의 두 집합을 검사합니다.
누락, 중복 또는 다른 설치의 매핑은 보류하며 패키지가 자신의 신뢰 매핑을 제공할 수 없습니다.
이는 명시적인 소스 조립 입력이며 영속 키/매핑 등록이나 Hub 가져오기가 아닙니다.

선택한 각 Entity는 동일한 정확한 Release 스키마와 Environment Config에 자신의 가장 구체적인
재정의만 적용합니다. 어느 블록이든 적용 범위 누락, 모호한 구간이나 알 수 없는 키가 있으면 전체
개정을 차단합니다. 공통 봉인 입력에는 해당 Entity의 봉인 입력만 덮어씁니다. 각 최종 식별자 맵은
독립적으로 분류한 봉인 키를 정확히 포함해야 합니다. 하나의 인증된 암호화 객체가 불투명한
Entity 연결 값과 완전한 식별자 맵을 연결합니다. 고객 서명과 암호화 문맥은 전체 개정과 Entity
매핑을 보호합니다.

**설계 검토와 수정(2026-10-21):** 서명한 목록만으로 완전성을 확인할 수 없고, 개별 패키지는
다른 Entity의 패키지로 바꿔 표시할 위험이 있습니다. 따라서 읽기 경로는 독립적으로 선택한 정확한
Entity 집합, Release 버전과 매니페스트 다이제스트를 요구하고, 전체 서명 문서 하나를 검증하며, 모든 Entity 매핑을
인증된 암호화에 결합합니다. 패키지는 자체 신뢰, 분류나 선택을 제공할 수 없습니다.
버전만으로는 서로 다른 매니페스트 빌드를 구별할 수 없습니다. 재시도 입력
다이제스트를 계산하기 전에 순서를 정규화하며, 기존 v1 선행 개정을 포함한 전체 체인 검증을
유지합니다. 기존 읽기 경로는 v2의 첫 Entity만 반환하지 않고 v2를 차단합니다.

호환성과 의도적인 차단 변경은 다음과 같습니다.

- 기존 v1 패키지 바이트와 단일 Entity CLI 입력 형식을 계속 지원합니다. 새 형식은 명시적으로
  선택하며, 로컬 Release의 자격을 높이지 않습니다.
- 두 형식 모두 일치하는 구간이 교차하여 가장 구체적인 구간을 하나로 정할 수 없으면 차단합니다.
  비교 연산자 순서가 달라도 동일한 구간은 중복입니다.
- 현재 체인 끝만 재시도할 수 있습니다. 이미 후속 개정이 있는 Git 개정의 생성 요청에는 오래된
  산출물을 반환하지 않고 차단합니다. 되돌리기는 새 Git 개정을 사용합니다.
- 전체 개정은 Entity 1-256개를 포함하고, 수락한 전체 이력은 패키지 256개 이하로 제한합니다.
  연결 값이 누락되거나 추가되거나 중복되면 일부만 잘라 수락하지 않습니다.

기존 Hub 업그레이드 플래너는 호출자가 명시적으로 제공한 검증 입력과 정확한 카탈로그 Release 스키마로
이 후보를 사용할 수 있습니다. 이미 관리 중인 모든 Entity의 적용 범위를 확인하고 Plan을
패키지 다이제스트에 연결합니다. 소유권, 회수, 영향 범위와 시간 검사를 유지합니다.
이 메모리 내 소비 경로는 키 등록, 구성 가져오기나 영구 저장을 수행하지 않으며 프로덕션 자격도
바꾸지 않습니다. 원자적 Hub 가져오기는 아래의 별도 통제 소스 경로가 담당합니다. 실제 키
등록, Agent 전송, CSI 비밀 참조 해석과 프로덕션 자격 검증은 남아 있습니다. 이 소스 API는 같은 Release의 구성 변경 일정을
영구 저장하는 기능을 구현하지 않습니다.

### 로컬 패키지 생성과 검증 명령

명시적으로 지정한 로컬 파일에는 `fdaictl configuration build`와
`fdaictl configuration verify`를 사용합니다. 두 명령은 Hub, Azure, 모델이나 키 공급자에
접속하지 않습니다. 두 명령 모두 독립적으로 제공한 Ed25519 검증 공개 키와 X25519 암호화
공개 키를 PEM 파일로 받습니다. 생성 명령은 암호화하지 않은 PKCS8 Ed25519 서명 키 파일도
읽고 검증 키와 대조합니다. 인자에는 파일 경로만 지정하고 키 바이트나 식별자 값은 넣지 마세요.
모든 입력 파일은 절대 경로, 현재 사용자 소유, `0600` 권한, 단일 링크 조건을 충족해야 하며,
`0700` 비공개 디렉터리에 둡니다. 심볼릭 링크, 일반 파일이 아닌 입력, 안전하지 않은 상위
디렉터리는 수락하지 않습니다.

기존 단일 Entity 패키지의 비공개 `--release-input` JSON 객체에는 `release_version`, `configuration_schema`(주석이 있는
키 맵), `sealed_keys`(중복 없는 식별자 키 이름 배열)만 포함합니다. 이 입력은 패키지와 독립된
경로에서 확보하세요. 파일을 제공하는 것만으로 프로덕션 Release를 검증하거나 신뢰를 등록하지
않습니다. 비공개 `--input` JSON 객체에는 `revision_id`(전체 Git 커밋),
`environment`(객체), `entity_overrides`(`versions`/`values` 블록 배열),
`sealed`(식별자 객체)만 포함합니다. 이 기존 입력은 v1을 만듭니다.

전체 다중 Entity 개정에는 독립 Release 입력에 `entity_ids`와 `release_digest`만 추가합니다.
`entity_ids`는 설치가 선택한 불투명한 연결 값의 중복 없는 배열이고, `release_digest`는 정확한
Release 매니페스트의 SHA-256입니다. 이 로컬 입력만으로 Release나 키 신뢰를 확보하지는
않습니다. 구성 입력에는 `revision_id`, `environment`, `sealed`, `entities`만 포함합니다.
각 Entity는 `entity_id`, `entity_overrides`, `sealed`만 포함합니다. 공통 봉인 값에는
각 Entity의 봉인 객체를 따로 덮어쓰며, 모든 결과가 신뢰한 봉인 키를 정확히 포함해야 합니다.
CLI는 v2를 만든 뒤 전체 선택 집합, Release 버전과 다이제스트, 스키마, 키, 수락한 체인에
대조하여 독립적으로 다시 읽습니다. 검증에 성공해야 비공개 파일을 만듭니다. 기존 형식과 다중
Entity 형식을 섞은 입력은 수락하지 않습니다.

```bash
fdaictl configuration build \
  --release-input /private/release-input.json \
  --configuration-key /private/configuration-public.pem \
  --installation-key /private/installation-encryption-public.pem \
  --input /private/configuration-input.json \
  --signing-key /private/configuration-signing.pem \
  --initial-revision --destination /private/configuration-package.json --output json
fdaictl configuration verify \
  --release-input /private/release-input.json \
  --configuration-key /private/configuration-public.pem \
  --installation-key /private/installation-encryption-public.pem \
  --initial-revision --package /private/configuration-package.json --output json
```

`--initial-revision`은 수락한 체인이 비어 있음을 명시적으로 선언합니다. 후속 개정에서는
이를 `--expected-predecessor <independently-retained-head-sha256>`로 바꾸고, 수락한 전체
체인을 오래된 순서대로 `--history <file>`에 반복 지정합니다(최대 256개). 이력 누락,
체인 끝 불일치, 분기, 순서 변경, 과거 개정을 현재 개정으로 되돌리는 시도는 차단됩니다.
동일한 입력으로 현재 개정을 재시도하면 원래 서명 바이트를 유지합니다.

출력 대상은 새로운 `0600` 파일이며 기존 파일을 덮어쓰지 않습니다.
`fdai.lifecycle-configuration-file.v1` JSON 컨테이너에는 `format`, `payload`,
`signature`만 있습니다. 뒤의 두 필드는 기존 서명 매니페스트와 분리 서명을 엄격한 base64
형식으로 담습니다. 읽기 경로는 스키마, 분류, 예상 Release 버전, 서명과 체인을 검증한 뒤에만
파일을 생성하거나 검증 성공을 보고합니다. 생성 성공에는 파일을 다시 읽어 정확히 일치하는지
확인하는 절차도 필요합니다. 결과에는 구성 값이나 키 값 대신 다이제스트와 검증 상태만
표시하며, 오류에는 입력에서 가져온 진단 내용을 포함하지 않습니다. 성공은 검증된 로컬
산출물만을 뜻합니다.

CLI 설계 검토와 보강(2026-10-21): 페이로드와 서명을 별도 파일로 쓰면 불완전한 산출물이
노출될 수 있으므로 하나의 완결된 컨테이너에 기록합니다. 서명 키에서 신뢰를 도출하면 스스로
키를 허용하게 되므로 별도 검증 키 입력을 요구합니다. 빈 체인이나 보관한 체인 끝을 명시하면
실수로 이력을 빠뜨리는 일을 막을 수 있지만, 호출자가 최신 영구 체인 끝을 제공했는지
입증하거나 동시 생성을 직렬화하지는 못합니다. 검증된 Release 허용, 키 등록/교체,
원자적 Hub 가져오기와 활성화는 별도의 통제 작업으로 남습니다.

## 비밀

- 비밀 값은 Git, 구성 패키지, Hub, Plan, 로그, 명령줄에 들어가지 않습니다.
- Azure 접근에는 클라이언트 비밀 대신 관리 ID와 워크로드 ID 페더레이션을 사용합니다.
- 피할 수 없는 타사 비밀은 설치의 Key Vault에 둡니다. 워크로드는 현재 런타임과 마찬가지로
  워크로드 ID를 사용하는 Key Vault CSI 드라이버로 비밀을 읽습니다.
- 고객은 Key Vault에서 비밀을 교체합니다. 교체는 구성 개정을 만들지 않으며, 보고 상태에는 각
  참조가 해석되는지만 표시됩니다.
- Apollo는 Plan으로 Kubernetes 비밀을 만듭니다
  ([Apollo secrets](https://www.palantir.com/docs/apollo/managing-secrets/add-edit-delete-secrets)).
  FDAI는 Hub가 비밀 값을 다루지 않도록 이 방식을 의도적으로 쓰지 않습니다.

## 정책과 권한은 구성이 아닙니다

- 승인 정책과 허용 정책 개정은
  [운영자 거버넌스 프로필](../decisioning/operator-governance-profiles-ko.md)에 따라 FDAI
  Console에서 작성하며 설치 안에 남습니다.
- 승격 상태, 상시 권한, kill switch, 승인 프로필은 관리되는 권한 경로로만 바뀝니다.
- Hub는 보고 상태에서 정책과 권한 상태의 다이제스트만 봅니다. Release는 ActionType의 최대
  모드를 선언할 수 있으며, 어떤 정책 개정도 이를 넘을 수 없습니다.

## 예시

다음 예시는 자리 표시자를 사용합니다. Customer A는 Korea Central에서 PTU 용량과 국내 처리를
사용하는 온라인 Target Hub를 운영합니다.

```yaml
# installations/<customer-a-installation>/installation.yaml
hub: target-hub-online
channel: RELEASE
version_range: ">=1.5.0 <2.0.0"
maintenance_windows:
  downtime: "Sun 02:00-04:00 Asia/Seoul"
  no_downtime: "daily 01:00-05:00 Asia/Seoul"
entities: [core, operator-api, document-ingestion-api, document-processing-worker,
           isolated-executor, console]
```

```yaml
# installations/<customer-a-installation>/environment.yaml
region: koreacentral
data_residency:
  processing_scope: geography       # geography | data-zone | global
network:
  profile: private-endpoints-only
model_bindings:
  diversity_policy: same-publisher-distinct-models
  primary:
    provider: azure-openai
    deployment_type: ProvisionedManaged
    capacity: { kind: ptu, units: 100 }
    endpoint_ref: model-primary
  secondary:
    provider: azure-openai
    deployment_type: ProvisionedManaged
    capacity: { kind: ptu, units: 50 }
    endpoint_ref: model-secondary
integrations:
  itsm:
    endpoint_ref: itsm-primary
    credential_ref: itsm-token      # Key Vault secret name
```

```yaml
# installations/<customer-a-installation>/sealed.yaml
tenant_id: 00000000-0000-0000-0000-000000000000
subscription_id: 00000000-0000-0000-0000-000000000000
resource_group: <customer-a-application-rg>
endpoints:
  model-primary: https://model-primary.example.com
  model-secondary: https://model-secondary.example.com
  itsm-primary: https://itsm.example.com
```

```yaml
# installations/<customer-a-installation>/entities/core.yaml
overrides:
  - versions: ">=1.5.0 <2.0.0"
    values:
      replicas: 2
      resources: { cpu: "2", memory: 4Gi }
```

Customer B는 East US의 중앙 Hub cell을 사용하고, `RELEASE_CANDIDATE`를 구독하며, Standard 종량제
용량과 함께 `processing_scope: global`을 설정하고, 기본 `mixed-publisher` 다양성 정책을
유지합니다. Customer C는 `version_range: ">=1.4.0 <1.5.0"`으로 버전을 고정하고, 용량 종류가
`gpu`인 `apim-gateway` 경로로 `self-hosted` 공급자를 바인딩합니다.

## 구성 데이터 모델

| 테이블 | 키 | 용도 | 시간 필드 | 변경 방식 |
|--------|-----|------|-----------|-----------|
| `configuration_revision` | `installation_id`, `revision_id` | Git 커밋, 이전 개정 다이제스트, 패키지 다이제스트, 서명 키 | `committed_at`, `imported_at`, `recorded_at` | 추가 전용 |
| `installation_settings` | `revision_id` | 채널, 버전 범위, 구간, Entity 목록 | 개정을 따름 | 개정별로 변경 불가 |
| `environment_config_value` | `revision_id`, `key` | 값, 축 주석, 소유자 주석 | 개정을 따름 | 개정별로 변경 불가 |
| `sealed_value` | `revision_id`, `key` | 암호문 참조와 다이제스트 | 개정을 따름 | 개정별로 변경 불가 |
| `entity_override_block` | `revision_id`, `entity_id`, `version_range` | 재정의 값과 다이제스트 | 개정을 따름 | 개정별로 변경 불가 |
| `package_import` | `import_id` | 업로드나 번들 같은 출처와 검증 결과 | `imported_at` | 추가 전용 |

## 고객 저장소 템플릿과 키 등록

[자리 표시자 템플릿](../../../config/lifecycle-configuration-template/README.md)은 위의 설치,
Environment Config, 비공개 봉인 입력과 Entity 구조에 합성 주석 Release 스키마를 더해
제공합니다. 집중 오프라인 검사는 기존 검증기를 호출할 뿐 패키지, 키, 서명, 업로드나 배포를
만들지 않습니다. [구성 키 런북](../../runbooks/lifecycle-configuration-key-onboarding-ko.md)은
고객 키 보관과 로컬 패키지 생성을 독립 신뢰 등록과 Hub 가져오기에서 구분합니다.
읽을 수 있는 `sealed.yaml` 입력을 업로드하거나 예제 스키마를 신뢰된 Release로 취급하지 마세요.

## 승인된 구성 키: 설계와 검토

이 소스 변경은 공개 신뢰 메타데이터를 등록하는 경로만 구현합니다. 실제 고객 키나 프로덕션
신뢰 루트를 등록하지 않습니다. 기존 등록과 소스 및 오프라인 설치 경로도 바꾸지 않습니다.

1. 인증된 고객 운영자는 정규화된 `fdai.configuration-keys.v1` 바이트를 제출합니다. 설치의
   기존 Ed25519 신원 키와 제안한 구성 Ed25519 서명 키가 각각 같은 바이트에 서명합니다.
   요청은 설치, 요청자 principal, 고유 요청 ID, 다음 버전, 이전 바인딩 다이제스트,
   역할을 구분한 32바이트 공개 키 두 개, 요청 시각, 승인 기한과 바인딩 만료를 결합합니다.
   X25519 암호화 수신 키는 두 서명 신원과 별개입니다. 역할 간 공개 키 바이트 재사용은
   허용되지 않습니다.
2. 요청 증명의 시계 차이는 5분 이내여야 하며 승인 기한은 요청 후 10분 이내입니다.
   바인딩은 승인 기한 이후, 요청 후 90일 이내에 만료됩니다. 기존 Hub 액세스 토큰 경계에서
   인증된 다른 운영자가 정확한 요청 다이제스트를 승인합니다. 본문의 행위자 문자열,
   프록시 헤더, 인증되지 않은 로컬 승인, 서비스 토큰이나 패키지의 키로는 신뢰를
   확립할 수 없습니다.
3. 기존 설치 행 잠금이 요청, 승인, 회수와 계획 수립을 직렬화합니다. 승인은 등록 신원,
   기한, 요청자와의 분리, 다음 버전과 정확한 이전 바인딩을 다시 검사합니다. 수락된 버전과
   증명은 변경하지 않습니다. 승인 재전송과 오래된 이전 바인딩을 사용한 동시 요청은
   신뢰를 바꾸지 않고 차단됩니다. 인증된 운영자는 정확한 현재 다이제스트를 회수할 수
   있습니다. 회수는 구성 기능만 제거합니다.
4. 공개 바인딩과 행위자를 기록한 결정은 추가 Hub 테이블과 기존 해시 체인 감사 기록에
   하나의 트랜잭션으로 저장합니다. 차단 사유는 반환 전에 영구 기록합니다. 기존 데이터베이스는
   명시적 마이그레이션으로 갱신합니다. 서비스 시작은 테이블이나 바인딩을 만들지 않습니다.
5. 실제 Hub 구성 계획 저장소는 같은 잠금 안에서 요청한 활성 버전을 이 테이블에서
   확인합니다. 바인딩이 없거나 만료, 회수, 설치 불일치나 내용 불일치가 있으면 구성 계획을
   보류합니다. 기존 등록과 계획은 그대로 유지합니다. 이전 버전은 보존하며 현재 서명 키로
   대체하지 않습니다. 발행된 구성 Plan은 승인된 바인딩 버전과 요청 다이제스트를 고정합니다.
   만료, 교체나 회수 후에는 현재 Plan 조회도 보류합니다. 아래의 원자적 가져오기 경로는
   이전 패키지를 당시의 정확한 바인딩으로 검증합니다. 검증할 수 없는 체인은 새 키로
   재해석하지 않고 보류합니다. 키 등록은 패키지 가져오기나 구성 활성화를 뜻하지 않습니다.

**구현 전 검토와 수정:** 호출자가 선택한 키와 행위자 필드만으로는 패키지 서명이 유효해도
독립 신뢰가 성립하지 않습니다. 따라서 기존 경계에서 검증한 운영자 principal만 승인에
사용하고 다른 principal의 승인을 요구합니다. 설치 신원 증명은 정규화된 요청 전체에
서명합니다. 레지스트리만 추가하면 소비 경로가 여전히 호출자의 키를 신뢰하므로 구성 계획은
자체 트랜잭션 안에서 영구 저장된 신뢰를 확인합니다. 키 교체는 기존 행을 덮어쓰거나 회수 후
버전을 초기화할 수 없습니다. 암호 라이브러리의 서명 성공만으로는 차수가 작은 Ed25519
항등원 점을 이용한 위조를 배제할 수 없습니다. 따라서 새 바인딩 경계는 두 소유 증명 전에
서명 공개 점의 정규 인코딩, 곡선 포함 여부와 차수를 검사합니다. 서명 신원에서 암호화 키를
파생하지 않습니다. 스키마 초기화를 마이그레이션으로 취급하지도 않습니다.
개인 키, 자격 증명과 고객 식별자는 저장하지 않습니다. 실제 등록, Azure 작업, Agent/CSI
전달이나 프로덕션 적격성 확인은 포함하지 않습니다.

## 원자적 가져오기와 구성 소비: 설계와 검토

이 제한된 소스 경로는 범위 바인딩, 패키지 가져오기, 구성 변경 승인, 활성화, 업그레이드 계획의
다섯 결정을 분리합니다. 어느 결정도 실행이나 승격 권한을 부여하지 않습니다.

### 제안 계약

- 등록된 설치는 기존 관리 Entity 식별자와 독립적으로 선택한 불투명 패키지 식별자의 매핑,
  봉인 키 분류, 정확히 수락한 Release/스키마를 결합한 단기 범위 요청에 서명합니다.
  JWT로 인증된 다른 고객 운영자가 정확한 요청 다이제스트를 승인합니다. 패키지는 이 바인딩을
  만들거나 새 Entity를 관리 대상으로 등록할 수 없습니다.
- 크기가 제한된 인증된 가져오기 요청은 원본 서명 파일 컨테이너 전체, 명시적인 현재 키
  바인딩 버전, 승인된 범위 다이제스트와 이 전체 맥락에 대한 설치 신원 증명을 제공합니다.
  서버는 독립 pin으로 검증한 카탈로그에서 Release/스키마를, 영구 승인 레지스트리에서 키를
  확인합니다. Hub는 봉인 값을 복호화하지 않습니다.
- 기존 설치 잠금 안에서 검증에 성공하면 불변 가져오기 증적을 추가하고, 수락한 체인 끝과
  기존 감사 체인을 함께 갱신합니다. 보존한 이전 다이제스트가 기준입니다. 현재 끝에 대한
  동일 요청은 원본 컨테이너 바이트를 유지합니다. 경쟁 후속 개정, Git 개정 재사용, 이력
  재정렬과 서로 다른 재시도 바이트는 차단합니다. 카탈로그와 설치 잠금은 같은 DB 트랜잭션을
  사용합니다. 검증 차단 사유는 API 오류 전에 감사 기록을 커밋하고, 예상하지 못한 저장이나
  감사 실패는 변경 전체를 롤백합니다.
- 증적마다 당시 수락한 키 버전, 키 요청 다이제스트, 범위 다이제스트, 원본 서명 바이트와 이전
  다이제스트를 고정합니다. 이력은 각 수락 시점에 독립 승인된 보존 바인딩으로 서명을 검증합니다.
  키 교체는 이력을 다시 쓸 권한이 아닙니다. 이전 바인딩이 회수되었거나 없거나 검증할 수
  없으면 정해진 사유와 함께 보류합니다.
  가져온 구성으로 발행한 Plan도 정확한 가져오기와 수락 증적을 보존합니다. Plan, 가져오기나
  체인 끝의 출처를 확인할 수 없으면 키만 확인하는 경로로 대체하지 않고 보류합니다.
  이전 개정의 Entity 적용 범위는 당시 증적의 독립 승인된 매핑으로 확인합니다. 오늘의 관리
  집합을 다시 적용하면 Entity를 관리 대상으로 추가한 뒤 올바른 전체 후속 개정을 수락할 수
  없게 됩니다. 현재 가져오기, 승인, 활성화와 소비는 여전히 오늘의 정확한 관리 집합을
  요구합니다. 과거 수락은 새 Entity 권한을 부여하지 않습니다. 카탈로그를 사용하는 가져오기와
  계획에서는 이전 Release/스키마도 정확히 수락한 카탈로그 항목이 필요합니다. 이전 Release가
  없으면 보류하며 과거 증적만으로 수락 근거를 만들지 않습니다.
- 가져오기는 변경 요청이지 승인이 아닙니다. 다른 인증 운영자가 10분 이내에 정확한 증적을
  승인합니다. 명시적 활성화는 현재 신뢰, 전체 이력, 선택 범위와 수락한 체인 끝의
  비교 후 교환(CAS)을 다시 확인합니다. 활성화는 기존 업그레이드 플래너의 구성 입력만 선택하며
  같은 Release의 작업을 예약하거나 어떤 변경도 적용하지 않습니다.
- 구성된 기본 재계산 경로는 후보 주입 없이 계획 트랜잭션 안에서 영구 저장된 활성 개정을
  읽습니다. 구성이 없으면 기존 계획을 유지합니다. 가져왔지만 활성화하지 않은 구성은 이
  기능만 보류하고 관련 없는 기존 Plan은 보존합니다. 회수, 시간 구간, 소유권, 설치 내부
  영향 범위와 명시적 승인 검사는 그대로 유지합니다.

### 구현 전 검토와 수정

패키지 서명이 유효하더라도 HTTP 본문의 매핑 자체는 독립 신뢰가 아닙니다. 따라서 매핑과
봉인 분류는 별도의 설치 신원 증명과 정확한 다이제스트에 대한 독립 승인을 요구합니다.
키 승인에 쓰는 principal 분리 규칙을 재사용하며 등록 권한을 새로 가정하지 않습니다. 기존
등록 식별자와 서명된 Plan 식별자는 바꾸지 않고 고객 식별자의 해시도 만들지 않습니다.

모든 이전 패키지를 최신 서명 키로 검증하면 올바른 키 교체 이력이 깨집니다. 반대로 전에
해석한 사전을 그대로 신뢰하면 변조를 숨깁니다. 공통 패키지 읽기 경로와 생성기는 이전 개정별
공개 검증 바인딩을 명시적으로 받고, 원본 바이트와 전체 체인을 계속 검증합니다. Hub는 불변
가져오기 증적과 승인 키 기록에서만 이 바인딩을 확인합니다. 과거 수락은 이전 키를 현재
권한으로 만들지 않습니다.
Plan과 가져오기 증적의 명시적 연결은 영속 패키지가 없어졌을 때 이전의 일시적 호환 경로로
오인하는 일을 막습니다.

도우미나 선택적 조합 후보만 추가하면 기본 시작 경로는 연결되지 않습니다. 따라서 실제
pin 카탈로그 재계산 경로가 기본적으로 영속 상태를 확인합니다. 추가 전용 Hub 스키마 개정은
기존 원시 구성 기록을 보존하며, 이 기록이 암호문 전용이 되는 것은 아닙니다. 새 가져오기
경로만 암호문/공개 메타데이터 저장을 보장합니다. 로컬 테스트는 실제 등록, 배포된
마이그레이션, Agent 전달, CSI 연결이나 프로덕션 적격성을 입증하지 않습니다.

### 인증된 소스 API

구성된 Target Lifecycle Hub는 `/v1/installations/{installation_id}` 아래에 다음 운영자
전용 경로를 제공합니다. 기존 JWT 발급자, 대상, 클라이언트, scope와 principal 검사를 적용합니다.
로컬 호출자 이름, 서비스 토큰이나 행위자 필드로는 승인할 수 없습니다.

| 경로 | 입력과 효과 |
|------|-------------|
| `POST /configuration-scope/request` | Base64 정규 `fdai.configuration-scope.v1` 페이로드와 등록된 설치 신원 증명입니다. 정확한 Release/스키마, 일대일 Entity 매핑, 봉인 키 이름과 제한된 기한을 결합합니다. |
| `POST /configuration-scope/approve` | 다른 인증 운영자가 정확한 `digest`를 승인합니다. |
| `GET /configuration-scope/requests/{digest}` | 독립 검토용 공개 요청 메타데이터를 반환합니다. |
| `POST /configuration/import` | Base64 원본 파일 컨테이너, 정규 `fdai.configuration-import.v1` 맥락과 신원 증명입니다. 설치, 요청자, 현재 키 버전, 범위, 컨테이너/패키지 다이제스트와 보존한 이전 다이제스트를 결합합니다. |
| `POST /configuration/approve` | 정확한 패키지 `digest`와 `receipt_digest`로 구성 변경을 독립 승인합니다. |
| `POST /configuration/activate` | 같은 정확한 쌍에 대해 현재 체인 끝, 신뢰, 이력과 승인 유효 시간을 다시 확인합니다. |
| `GET /configuration` | 서로 구분되는 수락 다이제스트와 활성 다이제스트를 반환합니다. |
| `GET /configuration/revisions/{digest}` | 원본 암호문 컨테이너와 공개 수락 다이제스트를 반환하며 복호화한 값은 반환하지 않습니다. |

서비스 시작은 자동으로 마이그레이션하지 않습니다. 명시적 Hub 스키마 개정 3은
`lifecycle_configuration_scope_request`, `lifecycle_configuration_scope_approval`,
`lifecycle_configuration_import`, `lifecycle_configuration_head`,
`lifecycle_configuration_change_approval`과 발행된 Plan의 출처를 보존하는
`lifecycle_configuration_plan_import`를 추가합니다. 개정 1과 2는 기존 등록, 키나 원시
구성을 다시 초기화하지 않고 갱신합니다. 수락 이력은 패키지 256개와 서명 페이로드 16 MiB로
제한하며 초과하면 자르지 않고 보류합니다. 공통 생성기, 읽기 경로와 설치 내부 복호화 API는
이전 개정별 `ConfigurationHistoryBinding` 입력을 받습니다. 이 입력은 이력만 인증하며
현재 키 권한을 부여하지 않습니다.

## 현재 한계

- 오프라인 생성기는 실제 패키지에 서명하고 이전 개정 체인을 검사하며 식별자를 암호화합니다.
  집중 테스트는 메모리에만 있는 합성 키로 읽기 경로와 설치 내부 복호화를 실행합니다.
  운영 패키지 전달은 아직 구현되지 않았습니다.
- 예제 스키마에는 주석이 있지만 프로덕션 Release에는 아직 검증된 구성 패키지 스키마가 없습니다.
  Runtime v3 개발용 발행과 독립 pin을 검증하는 Hub 수락 경로는 선택적 스키마를 정확한
  Release 아티팩트에 결합합니다. 프로덕션 적격성 확인을 뜻하지는 않습니다.
- 로컬 패키지 생성과 검증 명령은 신뢰 키를 등록하거나 Hub에 영구 저장된 체인의 끝을
  갱신하지 않습니다. 별도로 인증하는 Hub 공개 키 요청, 승인과 회수 API는 이제 신뢰를
  영구 저장하고 구성 계획을 통제합니다. 이미 등록된 설치와 독립적으로 인증된 고객
  운영자가 필요합니다. 이 변경에서는 실제 운영 등록을 수행하지 않았으며 운영 Agent 전달도
  주장하지 않습니다. 별도의 원자적 소스 가져오기 경로가 원본 서명 컨테이너, 독립 승인된
  매핑과 수락/활성 체인 끝을 보존합니다. 기존 원시 구성 기록이 암호문 전용이 되지는 않습니다.
- 구성 키를 잃어버린 고객은 키 교체가 Hub에 등록될 때까지 새 개정을 게시할 수 없습니다.

## 관련 문서

| 알아볼 내용 | 참고 문서 |
|-------------|-----------|
| 수명 주기 아키텍처와 Plan | [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md) |
| Release, 채널, 번들 | [Lifecycle Release와 채널](lifecycle-releases-and-channels-ko.md) |
| 승인 정책과 허용 정책 | [운영자 거버넌스 프로필](../decisioning/operator-governance-profiles-ko.md) |
| 모델 바인딩, 용량, 다양성 | [모델 기능 수명 주기](../architecture/model-capability-lifecycle-ko.md) |
| 결정 기록 | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance-ko.md) |
| 고객 키 보관과 등록 선행 조건 | [구성 키 런북](../../runbooks/lifecycle-configuration-key-onboarding-ko.md) |
| 제공 현황과 남은 작업 | [구현 ledger](../../roadmap-implementation/deployment/lifecycle-configuration.md) |
