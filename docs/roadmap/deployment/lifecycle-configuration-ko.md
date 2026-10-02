---
title: 수명 주기 구성
translation_of: lifecycle-configuration.md
translation_source_sha: 790920c902a602cc70a32217ec746eaa7ba0b519
translation_revised: 2026-10-02
---
# 수명 주기 구성

이 문서는 설치가 원하는 수명 주기 구성을 작성하고, 계층화하고, 패키지로 만들어 Lifecycle Hub에
전달하는 방법을 정의합니다. 또한 그 구성을 고객 식별자, 비밀, 정책, 권한과 분리합니다. 이 문서는
값 분류, 구성 계층, 서명된 구성 패키지를 소유합니다.

> **상태:** 설계만 되어 있습니다. 구성 패키지, 봉인된 값, 구성 스키마 주석은 아직 없습니다.
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

## 현재 한계

- 이 문서의 어떤 내용도 아직 구현되지 않았습니다.
- Release에는 아직 축과 소유자 주석이 있는 구성 스키마가 없습니다.
- 패키지 생성 명령이 없습니다. 고객 구성 키 등록에는 별도의 런북이 필요합니다.
- 구성 키를 잃어버린 고객은 키 교체가 Hub에 등록될 때까지 새 개정을 게시할 수 없습니다.

## 관련 문서

| 알아볼 내용 | 참고 문서 |
|-------------|-----------|
| 수명 주기 아키텍처와 Plan | [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md) |
| Release, 채널, 번들 | [Lifecycle Release와 채널](lifecycle-releases-and-channels-ko.md) |
| 승인 정책과 허용 정책 | [운영자 거버넌스 프로필](../decisioning/operator-governance-profiles-ko.md) |
| 모델 바인딩, 용량, 다양성 | [모델 기능 수명 주기](../architecture/model-capability-lifecycle-ko.md) |
| 결정 기록 | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance-ko.md) |
| 제공 현황과 남은 작업 | [구현 ledger](../../roadmap-implementation/deployment/lifecycle-configuration.md) |
