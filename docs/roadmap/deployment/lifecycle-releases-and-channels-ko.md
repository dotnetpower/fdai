---
title: Lifecycle Release와 채널
translation_of: lifecycle-releases-and-channels.md
translation_source_sha: f1f146f631701d8938cabcd218ce97ae664b9c37
translation_revised: 2026-10-02
---
# Lifecycle Release와 채널

이 문서는 FDAI Release에 무엇이 들어 있는지, Release가 release channel을 따라 어떻게 이동하는지
정의합니다. 또한 연결된 설치와 오프라인 설치가 Release를 받는 방법, 그리고 회수와 데이터베이스
스키마 호환성이 업그레이드를 안전하게 유지하는 방법을 정의합니다. 이 문서는 Release 매니페스트,
채널 모델, 업그레이드 번들, 회수를 소유합니다.

> **상태:** 설계만 되어 있습니다. 현재 FDAI에는 서명된 배포 번들과 오프라인 키트가 있으며, 그
> 서명된 매니페스트는 `development`, `beta`, `stable` 채널 이름을 사용합니다. 배포 CLI는
> `development`만 신뢰합니다. 나머지는
> [구현 ledger](../../roadmap-implementation/deployment/lifecycle-releases-and-channels.md)가
> 추적합니다.
>
> **범위:** 이 문서는 [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md)를 지원합니다.
> [소스 배포](source-deployment-ko.md)와 첫 설치용 오프라인 패키지는 현재 계약을 유지합니다.

## 설계 한눈에 보기

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

## Release 내용

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
| 서명 | 정규화된 매니페스트에 대한 공급업체 release 키의 분리 서명 |

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

Release가 적격해지기 전에 하나씩 검토하려는 규제 고객은 자기 Target Hub에 사용자 지정 채널을
만들고 `RELEASE`의 Release를 수동으로 추가할 수 있습니다. 채널 구성원 관리는 적격성을 선별하는
일이지 설치 승인이 아닙니다. 그 채널을 구독한 설치는 적격한 Release를 여전히 구간 안에서 자동으로
적용합니다.

채널 이름은 한 방향으로만 이전됩니다. `development`는 `DEV`로, `beta`는 `RELEASE_CANDIDATE`로,
`stable`은 `RELEASE`로 매핑됩니다. 이전 전에 서명된 산출물은 기존 이름을 유지하며, 배포 CLI는
검증할 때만 그 이름을 매핑합니다.

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

## 산출물 전달

### 연결된 설치

설치는 각 Release의 이미지를 경계 안의 자체 컨테이너 레지스트리로 가져옵니다.
[Apollo 제약 조건](https://www.palantir.com/docs/apollo/core/plans-and-constraints)처럼 산출물 누락
제약 조건은 필요한 모든 다이제스트가 있을 때까지 Plan을 차단합니다.

### 오프라인 설치

업그레이드 번들에는 Release, 채널 구성원, 회수 공지, Target Hub에 아직 없는 최소한의 이미지
레이어가 들어 있습니다. 공급업체 release 키가 번들의 체크섬 목록에 서명합니다. 고객은 전송
매체에 자체 서명한 구성 패키지를 함께 넣을 수 있으며, Target Hub는 각 패키지 서명을 따로
검증합니다.

1. 운영자가 번들을 Target Hub로 가져옵니다.
2. Target Hub는 서명과 모든 체크섬을 검증하고, 이미지를 경계 안의 레지스트리에 게시하며,
   카탈로그를 갱신합니다.
3. Plan은 일반적인 제약 조건 아래에서 진행됩니다.

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

- 서명된 배포 번들, 오프라인 키트, 기존 채널 이름 외에는 구현된 것이 없습니다.
- 프로덕션 신뢰 루트 절차를 아직 수행하지 않았습니다. Hub 경로가 Release를 검증하려면 먼저
  공급업체 release 키가 있어야 합니다.
- 서명된 번들의 재현 가능한 이중 빌드 검증이 남아 있습니다.
- Release는 아직 스키마 범위, 기능 최대값, 다운타임 필요 여부를 선언하지 않습니다.

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
