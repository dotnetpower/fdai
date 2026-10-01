---
title: 배포 리소스 규약
translation_of: deployment-resource-conventions.md
translation_source_sha: 98b8d29806514c3234e5c921cce2aab2b557daa0
translation_revised: 2026-10-01
---
# 배포 리소스 규약

이 문서는 FDAI가 프로비저닝하는 인프라의 리소스 명명 및 태깅 규약을 정의합니다.
Terraform 플랜을 결정론적으로 유지하고, 리소스 소유권을 질의 가능하게 만들며, 배포별 값을
업스트림 분포 외부에 두는 데 사용하세요.

> 이 계약은 프로비저닝된 인프라에 적용됩니다. 런타임 코드는 설정을 통해 리소스 식별자를
> 사용하며 이름이나 소유권 태그를 계산하지 않습니다.

Teams A1 승인 봇은 재사용 모듈 `infra/modules/teams-a1-approval-bot`이 프로비저닝합니다.
이 모듈은 전용 non-executor user-assigned identity, Azure Bot, Teams 채널 등록을 만들고
`teams_approval_destination` 계약 값을 반환합니다. 그룹 연결 team id, channel id 및 Operator
activity 엔드포인트는 azurerm 프로바이더가 생성할 수 없으므로 사람이 제공하는 입력으로 유지됩니다.

## 기반 계층과 애플리케이션 계획 경계

신규 구독 초기 구성은 첫 번째 비공개 실행기가 존재하기 전에 운영 리소스 그룹, 애플리케이션
리소스 그룹, 상태 스토리지 계정 이름을 결정합니다. `fdaictl provision
bootstrap-reconcile`은 해당 이름을 검토된 프로필 및 소스 커밋에 연결하고, 모든 Azure 관리
플레인 읽기를 검증된 구독에 고정하며, 만료 시간이 있는 비공개 계획만 기록합니다. 공급자를
등록하거나, 리소스를 만들거나, Terraform 상태를 쓰거나, 워크플로를 제출하지 않습니다.

별도로 승인된 기반 단계가 비공개 `tfstate` 및 `deployment-plans` 컨테이너 생성과 원격 상태
인계를 소유합니다. 애플리케이션 계획 전용 실행은 두 컨테이너를 전제 조건으로 취급하며,
하나라도 없으면 중지합니다. 계획의 부수 효과로 기반 리소스를 만들지 않습니다.

기반 리소스는 테넌트 정책이 생성 시점에 부여할 수 있는 설정도 함께 선언해 적용 후 계획이 변경
없음이 되도록 합니다. 운영 공인 IP는 정책이 소유한 `ip_tags`를 받고, runner 가상 머신은 게스트
패치 모드와 플랫폼 안전 점검 우회를 선언합니다. 각 값은 기본값이 아니라 정확히 관측한 입력입니다.
선택이 비어 있으면 공급자 동작을 유지하고, 지원하지 않는 값은 받아들이지 않고 실행을 중단합니다.
이 선언이 없으면 모든 공인 IP에 태그를 부여하는 구독이나 플랫폼 관리 패치를 강제하는 테넌트에서
신규 설치가 수렴할 수 없습니다.

초기 구성 호스트의 임시 OS 디스크는 AzureRM의 `diff_disk_settings` 요구에 따라 `ReadOnly`
캐시를 사용합니다. 범위가 포함된 역할 정의 식별자는 GUID 부분만 추출해 ABAC `GuidEquals`로
비교합니다. 관측 역할 위임은 쓰기와 삭제 모두에서 `ServicePrincipal` 대상의 Cost Management
Reader, Monitoring Reader와 Reader만 허용합니다. 부분 적용 실패 시 상태와 실행 전 기록을
보존하고 [설치 가능한 배포 CLI](installable-deployment-cli-ko.md)의 제한된 복구 계약을 사용합니다.
실행 전 기록이 있는 적용을 반복하지 않습니다.

애플리케이션 기능 입력은 전체 계획에서 원하는 플랫폼 상태를 나타냅니다. 모니터링이 유일하게
선택된 기능일 때만 범위가 제한된 `module.monitoring` 대상을 사용합니다. 애플리케이션 기능과 함께
선택하면 모니터링을 활성 상태로 유지하고 전체 비파괴 계획에 포함합니다.
운영 이력 전용 계획에는 애플리케이션 리소스 그룹의 이전 이동 주소를 포함합니다. Terraform은 이
무변경 상태 전환을 조정한 뒤 이력 저장소, 비공개 엔드포인트 및 수명 주기 Job 대상만 평가합니다.
정확한 내부 소유권 마커 대상도 같은 범위에 포함합니다.
dev 운영 게이트웨이 대상 집합도 게이트웨이, 런타임, 신원 및 역할 대상보다 먼저 같은 리소스
그룹 이동 주소를 포함합니다. 따라서 보호된 이미지 업데이트는 대상이 없는 파괴적 계획으로
범위를 넓히지 않고 상태 이동을 조정할 수 있습니다.
compute 대상 종결 집합은 선택한 측정 실행기를 Terraform이 평가하기 전에 기존 out-of-band Job과
rule-watcher Job도 포함합니다.
배포자 신원을 이행하는 동안 모듈은 이전 데이터 소유자 할당을 보존하고 별도 주소에 안정적인
runner 할당을 추가합니다. 두 할당 중 하나라도 교체하는 파괴적 계획은 차단됩니다.
보호된 Console release workflow는 CI로 검증된 정확한 Core image를 연결하고 기존 catalog 구체화
Job을 rollback과 함께 갱신한 뒤 schema migration을 실행합니다. 일치하는 Console 산출물을
게시하기 전에 선택한 revision의 변경할 수 없는 Rule 및 Ontology 변환 결과를 PostgreSQL
readback으로 검증합니다. 하나의 공유 요청 workflow는 허용 목록의 작업과 정확한 revision을
검증한 뒤 repository 자동화 identity로 Console 게시 또는 catalog 새로 고침을 제출합니다. 같은
요청 경계는 Environment 정책을 검증한 후 exact protected RCA reader apply 또는 검증 재개
좌표나 유효 기간이 남은 Core model-binding service plan 하나만 제출할 수 있습니다. Core 경로는
제출 전에 service와 전환 모드를 고정하고 정확한 실행, 시도, digest, image 및 아티팩트 metadata를
검증합니다. `fdaictl`은 exclusive RCA apply를 이 요청 경계를 통해 라우팅합니다.
관련 없는 커밋으로 `main`이 전진해도 plan revision이 여전히 ancestor이고 보호된 요청 control이
같을 때만 유효 기간이 남은 plan을 사용할 수 있습니다. 따라서 사람 유지관리자는 자체 검토 또는
관리자 우회를 활성화하지 않고 bot 소유 배포를 승인할 수 있습니다.

알림 과다 수신 검증 선행 조건은 광범위한 모니터링에 포함되지 않는 개발 환경 전용 대상입니다.
기존 `ca-<workload>-<env>-<region>-core` Container App의 `Replicas` 메트릭을 대상으로 정확히
`ag-<workload>-noise-pilot-<env>-<region>`과
`alert-<workload>-noise-pilot-<env>-<region>`을 만듭니다. 대상은 임의의 리소스 ID 입력을 받지
않고 내부에서 파생합니다. 수신자는 소유자 전용 배포 구성에 유지합니다. 파일럿은 Core 앱을
변경하거나 애플리케이션 데이터, 자격 증명, 연결 문자열 또는 Key Vault 내용을 읽지 않습니다.
로컬 적용 전에 기준선, 조정안, 복구 및 정리 계획의 범위를 각각 독립적으로 검증하고 운영자가
각 로컬 배포 계획을 확인합니다. 이 확인과 Terraform 기록은 Var 승인, FDAI 런타임 권한, 효과
근거 또는 승격 근거가 아닙니다. 공용 또는 프로덕션 경보 변경은 기존 런타임 승인 정족수를
유지합니다.

A3-E 근거 대상은 별도의 개발 환경 전용 Terraform root입니다. 기존 보호 보유 리소스 그룹을
참조하고 별도 상태에서 비공개 네트워크, 단일 VM, 신원 2개 및 대상 범위 역할만 소유합니다.
이름은 `fdai-a3e-<env>-<region>` 접미사를 사용합니다. 구독, 보유 그룹, 작업자, 리전, SKU,
정확한 이미지 버전, 만료 시각, 주소 공간 및 SSH 공개키는 보호된 배포 입력으로 유지합니다.
실행기 역할은 VM 읽기, 시작 및 할당 해제만 허용하고 관측자는 같은 VM에서 Reader 역할을
받습니다. Subnet과 VM NIC는 모두 외부 송신을 거부하는 NSG에 연결하고 VM extension 작업은
비활성화합니다. 값을 노출하지 않는 gate는 정확한 생성 집합만 수락합니다. 적용, 초기 할당
해제, 캠페인 효과, rollback 및 정리는 각각 별도의 승인 단계로 유지합니다.
## 리소스 명명 규약(Resource Naming Convention)

이 리포지토리가 프로비저닝하는 모든 Azure 리소스는 **Microsoft Cloud 도입 Framework
(CAF)** 축약 규약을 따릅니다. 이름은 결정론적이고 배포에 종속되지 않으며 grep할 수 있습니다.
이름 변경은 Terraform 차이로 처리하고 손으로 편집하지 않습니다.

패턴:

```
<caf-prefix>-<workload>[-<component>][-<env>][-<region>][-<instance>]
```

- **워크로드**: 고정 리터럴 `fdai`입니다. 제품 이름이며 고객 식별자가 아니므로
  [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)에
  따라 허용됩니다.
- **컴포넌트**: 같은 리소스 종류를 두 개 이상 프로비저닝할 때만 추가합니다. 예를 들어
  `ca-fdai-core`와 향후 `ca-fdai-worker`를 구분합니다.
- **env** (`dev`/`staging`/`prod`)와 **지역** (`krc`/`weu`/`eus`): 리소스를 나란히
  배포할 때만 접미사로 추가합니다. Day-zero 배포는 접미사를 사용하지 않습니다.
- **인스턴스** (`01`, `02`, ...): 한 환경에 여러 복사본이 있을 때만 추가합니다.

Operator API는 물리 구성 요소로 `operator-api`를 사용합니다. 워크로드 신원 이름은
`id-<workload>[-<env>][-<region>]-operator-api`이고 Container App 이름은
`ca-<workload>[-<env>][-<region>]-operator-api`입니다. 이전 `readapi` 토큰은 과거 Terraform
`moved` 주소와 보존된 근거에서만 유효합니다. 기존 배포는 검토된 보호 계획을 통해 물리 리소스를
교체하며 제자리에서 이름을 바꾸지 않습니다.

일회성 A3-E 대상은 각 CAF 접두사 뒤에 `fdai-a3e-<env>-<region>`을 사용합니다. 실행기와
관측자 신원에는 각각 `-executor`와 `-observer`를 추가합니다. Root는 새 리소스 그룹을 명명하거나
소유하지 않고 보유 리소스 그룹을 참조하며, 배포 값은 소스 제어 외부에 유지합니다.

기본 **리소스 그룹**은 `rg-fdai`입니다. 구독 범위 배치가 필요한 리소스 종류를 제외하면
시스템이 프로비저닝하는 모든 리소스가 이 리소스 그룹에 속합니다. 현재 해당 예외는 없습니다.

### Event Bus 제품 토픽 namespace

FDAI 제품 namespace를 사용하는 Event Bus 토픽은 `fdai.`로 시작하고
`fdai.<domain>.<purpose>` 형식을 따릅니다. 현재 예로 `fdai.change.events`,
`fdai.pantheon.objects`, `fdai.pipeline.stages`가 있습니다. Dead-letter entity는 전체 토픽
이름에 `.dlq`를 추가합니다. 예를 들면 `fdai.change.events.dlq`입니다.

Terraform이 provision된 토픽 이름을 소유하고 각 런타임에 설정으로 전달합니다. 애플리케이션
기본값은 로컬 기동을 지원하며 Terraform에서 선택한 이름과 일치해야 합니다. 별도의 명명 권위를
만들지 않습니다. 문서화되지 않은 `aw.` 제품 접두사는 legacy이며 활성 토픽 기본값이나 새 인프라
선언에서 허용되지 않습니다. 과거 근거는 실제로 관찰한 `aw.*` 이름을 유지하므로 이후 이름 변경이
이전 검증 주장을 다시 쓰지 않습니다.

이 제품 접두사 규칙은 계약별 `runtime.*`, `object.*`, `operator.*`, `core.*` 토픽의 이름을
바꾸지 않으며 SSE 채널, OpenTelemetry 키, Entra 그룹 또는 chat 명령에도 적용되지 않습니다.
Provision된 Event Hub entity 이름 변경은 제자리 이름 변경이 아니라 교체입니다. 따라서 배포는
보호된 계획과 exact apply를 사용하고, 모든 role scope와 producer/consumer binding을 검증하며,
이전 entity의 보존 record를 drain하거나 만료시키고, 이전 경로를 삭제하기 전에 post-apply
transport 근거를 기록합니다.
명시적으로 폐기 승인된 비권위 개발 backlog는 exact apply에서 legacy entity를 삭제할 때 대신
제거할 수 있습니다.
검증된 전환이 완료되어 일회성 이행 제어는 제거했습니다. 현재 platform 및 service 계획은 정본
`fdai.*` 연결만 수락합니다. 과거 Terraform `moved` 블록 3개는 이전 state 주소만 해석합니다.
State가 정본 key에 도달한 뒤 legacy 토픽을 프로비저닝하거나 반복 replacement 작업을 계획하지
않습니다.

### Day-zero 인벤토리용 CAF 접두사

| 리소스 | CAF 접두사 | 문자 규칙 | 예시 이름 |
|--------|------------|-----------|-----------|
| Resource Group | `rg-` | 1-90; 영숫자 + 하이픈/밑줄 | `rg-fdai` |
| User-assigned Managed Identity | `id-` | 3-128 | `id-fdai-executor` |
| Container Apps 환경 | `cae-` | 2-32; 영숫자 + 하이픈 | `cae-fdai` |
| Container App (코어) | `ca-` | 2-32 | `ca-fdai-core` |
| Container Apps 작업 (out-of-band) | `caj-` | 2-32 | `caj-fdai-oob`, `caj-fdai-browser-gc` |
| Virtual Network | `vnet-` | 2-64 | `vnet-fdai-a3e-dev-wus2` |
| Subnet | `snet-` | 1-80 | `snet-fdai-a3e-dev-wus2` |
| Network Security Group | `nsg-` | 1-80 | `nsg-fdai-a3e-dev-wus2` |
| Virtual Machine | `vm-` | 1-64 | `vm-fdai-a3e-dev-wus2` |
| Virtual Machine Scale Set | `vmss-` | 1-64 | `vmss-fdai-ohl-dev-krc` |
| Event Hubs 이름 공간 | `evhns-` | 6-50 | `evhns-fdai` |
| PostgreSQL Flexible Server | `psql-` | 3-63; 소문자 | `psql-fdai` |
| Key Vault | `kv-` | 3-24; 영숫자 + 하이픈 | `kv-fdai` |
| **Container Registry (ACR)** | `cr` | 5-50; **영숫자만 허용, 하이픈 불가** | `crfdai` |
| Log Analytics workspace | `log-` | 4-63 | `log-fdai` |
| Azure Monitor 경고 / 작업 그룹 | `alert-` / `ag-` | 1-260 / 1-260 | `alert-fdai-event-bus-consumer-lag`, `ag-fdai` |
| Foundry 계정 (`AIServices`) | `aif-` | 2-64; 영숫자 + 하이픈 | `aif-fdai-search` |
| Foundry 계정 project | `proj-` | 2-64; 영숫자 + 하이픈 | `proj-fdai-search` |
| Azure Bot (HIL Adaptive Cards) | `bot-` | 2-64 | `bot-fdai` |
| Static Web App | `stapp-` | 2-40 | `stapp-fdai`, `stapp-fdai-design-mocks-dev-ea` |

### 길이 안전 규칙

- **ACR 이름에는 하이픈을 넣지 않습니다**. 접두사 `cr`를 워크로드 토큰과 결합해
  `crfdai`로 사용합니다. env/지역 접미사를 추가할 때도 하이픈을 다시 넣지 않고
  `crfdaidevkrc01`처럼 연속된 소문자 영숫자 문자열을 사용합니다.
- **Storage 계정**는 최대 24자의 소문자 영숫자를 사용합니다. 문서 저장소는
  전역 고유성을 위해 구독 + 환경에서 파생한 안정적인 6자 해시를 추가합니다.
- **새 공개 기여자 배포**는 검증된 구독의 안정적인 6자 소문자 해시를
  `resource_name_suffix`로 설정합니다. Terraform은 전역 범위 registry, vault, event bus,
  database, communication 및 AI account 이름에만 이 값을 추가합니다. 빈 기본값은 기존 배포
  이름을 모두 보존하며 in-place rename을 만들지 않습니다.
- **Static Web Apps는 호스팅 지역 접미사를 사용합니다.** Design-mocks 리소스는
  `design-mocks` 컴포넌트와 Static Web Apps 지역을 포함합니다. 예를 들면
  `stapp-fdai-design-mocks-dev-ea`입니다. Static Web Apps는 모든 Azure 지역에서 제공되지
  않으므로 이 지역은 컨트롤 플레인 지역과 다를 수 있습니다.
- 브라우저 근거 정리 Job은 짧은 컴포넌트 `browser-gc`를 사용하므로 가장 긴 허용 형식인
  `caj-fdai-staging-<region>-browser-gc`도 32자를 넘지 않습니다.
- env/지역/인스턴스를 추가한 합법적 이름이 문자 제한을 넘으면 해당 리소스 종류에만
  문서화된 짧은 이름 `aip`를 `fdai` 대신 사용합니다. 전체 이름이 제한 안에 있으면
  `aip`를 사용하지 않습니다.
- **Key Vault는 기존의 유효한 이름을 모두 보존합니다.** 전체 후보가 24자를 넘을 때만
  Terraform은 `kv-aip-<8hex>`를 사용합니다. `<8hex>`는 워크로드, 환경, 지역 및 전역 접미사를
  포함한 전체 후보의 안정적인 SHA-256 접두사입니다.

### 이 규칙이 방지하는 항목

- **무작위 접미사**: Storage 또는 새 공개 기여자 배포처럼 전역 고유 이름이 필요한 경우
  짧고 결정론적인 해시는 허용됩니다. 플랜마다 바뀌는 접미사는 리뷰를 차단합니다.
- **식별자 안의 고객 이름 또는 환경 값**: 이 값은 리소스 이름이 아니라 `*.tfvars`와
  태그 맵에 둡니다.
- **Python의 인라인 명명 로직**: 앱은 환경 변수에서 식별자를 읽고, `infra/`가 플랜 시점에
  이름을 결정합니다.

## Terraform 상태 루트 규약

재사용 모듈은 호출자의 우발적인 provider 선택을 상속하지 않고 자체 호환성 하한을 선언합니다.
Azure 리소스 모듈은 Terraform `>= 1.9` 및 AzureRM `~> 4.14`를 요구하고 provider가 없는 rendering
모듈은 Terraform 하한만 선언합니다. 따라서 provider major upgrade에는 명시적인 모듈 계약 변경과
독립 검증이 필요합니다.

모든 운영 Terraform 루트는 안정적인 루트 id, 환경별 백엔드 키, 스케줄된 표류 계획을
각각 하나씩 가집니다. 현재 배포 계약에는 루트 7개가 있습니다.

| 루트 종류 | 개수 | 백엔드 키 패턴 |
|-----------|------|------------------|
| 이전 방식 platform | 1 | `fdai-<environment>.tfstate` |
| 독립 서비스 | 5 | `services/<service>/<environment>.tfstate` |
| Ops 초기화 | 1 | `ops/bootstrap/<environment>.tfstate` |

첫 초기화 적용은 비공개 백엔드를 만드는 동안에만 로컬 상태를 사용할 수 있습니다.
이행 이후에는 원격 초기화 키가 권위 상태입니다. 고유 백엔드 키와 drift-plan
좌표 없이 운영 루트를 추가하는 방식은 지원되지 않습니다. 표류 검사는 근거가 없거나
읽을 수 없으면 실패하며, 등록된 루트를 생략한 채 성공으로 보고하지 않습니다.

Core 및 Operator 서비스 루트는 semantic-turn 요청과 변환 결과 토픽 이름을 환경별 Terraform
입력으로 받습니다. Terraform은 검토된 이름을 `FDAI_SEMANTIC_TURN_REQUEST_TOPIC`과
`FDAI_SEMANTIC_TURN_PROJECTION_TOPIC`으로 전달하며, 애플리케이션 코드는 이 서비스 간 채널을
파생하거나 이름을 바꾸거나 다른 채널로 대체하지 않습니다. 각 Container App은 각 이름을 한 번만
받으므로 이전 방식 리터럴이 Terraform-selected 토픽을 가릴 수 없습니다.
루트 변수와 하위 서비스 모듈은 동일한 optional `semantic_requests` 및
`semantic_projections` 필드를 선언합니다. 또한 두 logical topic을 운반하는 provision된 Event Hub인
`semantic_physical`을 선언합니다. 기본 physical topic은 `fdai.pantheon.objects`입니다. 기존
logical-topic envelope와 `.dlq` sibling은 Event Hubs entity를 추가로 소비하지 않으면서 schema 격리,
안정적인 partition key, logical topic별 hash consumer group 및 dead-letter routing을 유지합니다.
logical request와 projection 이름은 서로 다른 contract 및 설정 값으로 유지되며, 어느 쪽도 독립된
Azure Event Hub가 되지 않습니다. 상태 이행 또는 보호된 플랜 전에 두 독립 루트 모두
`terraform validate`를 통과해야 합니다. 루트에만 있고 하위 모듈에서 빠진 필드는 선택적인 런타임
성능 저하가 아니라 배포 계약 실패입니다.
로컬 런타임 준비는 동일한 bootstrap, logical 이름 및 physical-topic marker를 독립 Operator 환경에
전달합니다. 일부만 있는 세 값은 어느 서비스도 시작하기 전에 차단됩니다.
Operator와 문서 인제스트 migration Job은 각각 별도의 digest-pinned migration image를 받을 수
있습니다. 빈 값은 호환성을 위해 해당 서비스 image를 유지하며, protected 배포는 검토된 migration
digest를 bind해 schema 진행이 runtime image 주기에 의존하지 않도록 합니다.
Core 서비스 입력 구체화는 비어 있는 선택적 platform endpoint 출력을 제거한 뒤 모든 활성 model
binding에 정확한 provider endpoint가 있는지 검증합니다.

Operator App 이미지와 일회성 schema migration 이미지는 서로 독립적으로 digest pinning됩니다.
Migration 이미지는 데이터베이스의 현재 Alembic revision 집합을 포함해야 합니다. Migration 이미지가
설정되지 않았을 때 App 이미지로 fallback하는 동작은 하위 호환성용이며 승격 우회로가 아닙니다.

Operator module은 `caj-<workload>-catalog`를 별도의 수동 Container Apps Job으로 선언합니다.
이 Job은 검토된 Rule 및 Ontology 카탈로그를 소유하는 digest-pinned Core image를 사용합니다.
배포 workflow는 명시적으로 선택한 Core 소스 revision을 격리된 Executor와 독립적으로 바인딩한 뒤
`caj-<workload>-migrate`가 성공한 경우에만 catalog Job을 시작합니다. 두 Job은 Operator Managed
Identity 및 PostgreSQL secret reference를 사용하지만 catalog 구체화는 참조 변환 결과만 만들며
런타임에서 발견된 문제, 준비 상태 또는 실행 권한을 만들지 않습니다.

Core 상태 소유권이 `services/core-control-plane/<environment>.tfstate`로 이동한 후 이전 방식
platform 루트는 공유 Container Apps 환경과 예약된 Job을 유지하지만 Core Container App 리소스는
더 이상 선언하지 않습니다. 상태 및 작업 검사를 위해 결정론적인 Core 이름은 계속 제공하며,
monitoring은 이 이름으로 실제 ARM id를 구성합니다. 과거 source 주소는 상태 이행 manifest와 이전
방식 플랜 guard에만 남습니다. 이 주소에서 생성, 업데이트, 교체 또는 삭제를 제안하는 platform
플랜은 차단됩니다.

이전 방식 platform 루트는 롤백 호환 배포 표면으로만 격리 Executor wrapper를 유지할 수 있습니다.
이 wrapper는 `service_distribution`과 `service_entrypoint`를 모두
`fdai-isolated-executor-service`에 bind합니다. 빈 값이나 Core co-located 값은 플랜 승인 전에
모듈 precondition에서 실패합니다. 5개 런타임의 상태 이동이 모두 끝나면 이전 방식 Container App
리소스는 전부 비활성화되고 Operator 및 ingestion migration Job은 이전 방식 상태 소유로 유지됩니다.
배포 검증은 결정론적 이름으로 Azure에서 독립 App의 실제 FQDN을 읽으며, 해당 리소스를 platform
상태에 다시 도입하지 않습니다.

## 리소스 태깅 규약(Resource Tagging Convention)

명명은 리소스를 읽기 쉽게 만들고, 태깅은 플릿을 질의 가능하게 만듭니다. 이 리포지토리가
프로비저닝하는 모든 리소스는 작고 기계 파싱 가능한 태그 세트를 가집니다. FDAI 소유 키는
모두 `fdai:` 접두사 아래에 네임스페이스되므로 전체 세트를 grep할 수 있고, 다른 팀의 리소스가
함께 있는 **공유 구독**에서도 FDAI가 프로비저닝한 리소스를 구분할 수 있습니다. 태그 맵은
Terraform의 `infra/main.tf` `base_tags`에서 결정하며 Python에서 계산하지 않습니다.

### 기본 태그 세트

| 태그 키 | 값 | 소스 | 목적 |
|---------|----|------|------|
| `fdai:managed` | `true` | 상수 | **소유권 마커.** "FDAI가 이 리소스를 프로비저닝했다"는 것을 나타내는 단일 권위 플래그입니다. `az resource list --tag fdai:managed=true`는 FDAI 소유 리소스를 정확히 열거하며 영향 범위 제한, 정리/감사 교차 확인, 비용 귀속의 기반이 됩니다. |
| `fdai:workload` | `fdai` | `var.workload` | 제품/워크로드 토큰이며 CAF 이름 토큰과 일치합니다. |
| `fdai:env` | `day-zero` / `dev` / `staging` / `prod` | `var.env` | 환경입니다. `day-zero`는 한정되지 않은 배포입니다. |
| `fdai:layer` | `control-plane` / `ops-bootstrap` | 설정별 | 앱 spoke인 `infra/main.tf`와 ops/허브 초기화인 `infra/bootstrap`을 구분하는 아키텍처 계층입니다. |
| `fdai:managed-by` | `terraform` | 상수 | 프로비저닝 도구입니다. |
| `fdai:vertical` | `shared` / `resilience` / `change-safety` / `cost-governance` | `var.cost_vertical` (기본값 `shared`) | 리소스 비용을 귀속할 AIOps 버티컬입니다. 여러 버티컬이 공유하는 컨트롤 플레인 인프라는 `shared`를 유지하고, 세 실행기 MI 같은 버티컬별 리소스가 이 키를 재정의합니다. |

### `fdai:managed`가 중요한 이유

실행기는 FDAI가 소유하지 않는 리소스도 호스팅하는 구독 안에서 실행될 수 있습니다.
소유권 마커를 사용하면 컨트롤 플레인이 이 경계를 그을 수 있습니다. 이 마커는 한 스크립트에
하드코딩한 동작이 아니라 다음 기능이 사용하는 질의 키입니다.

- **영향 범위 제한**: 자율 액션이 대상 집합을 제한해야 한다는 안전 불변식을
  `fdai:managed=true`에 대해 표현합니다. 따라서 수정 작업은 FDAI가 만든 리소스로 제한되고
  FDAI가 만들지 않은 리소스에는 도달하지 않습니다.
- **정리와 감사**: `terraform destroy`는 상태를 기준으로 프로비저닝된 플릿을 제거합니다.
  마커는 일괄 점검 또는 감사에서 리소스를 삭제 대상으로 고려하기 전에 FDAI 소유인지 확인하는
  out-of-band 교차 확인 수단입니다.
- **비용 귀속**: 비용 관리와 Resource Graph는 `fdai:vertical`로 지출을 그룹화하고
  전체 FDAI 사용량을 `fdai:managed=true` 슬라이스로 분리할 수 있습니다.

### 배포 공급 태그(`additional_tags`)

고객별 및 환경별 키는 `base_tags`에 하드코딩하지 않습니다. 배포는 커밋하지 않은
`*.tfvars`의 `additional_tags` 맵을 통해 값을 공급하며 `fdai:` 네임스페이스를 유지합니다.

```hcl
additional_tags = {
  "fdai:cost-center"         = "cc-1234"
  "fdai:owner"               = "team-platform"
  "fdai:criticality"         = "high"
  "fdai:data-classification" = "internal"
}
```

`additional_tags`는 `base_tags` 위에 병합되므로 배포에서 코어를 편집하지 않고
`fdai:vertical` 고정과 같은 기본값 재정의도 할 수 있습니다.

### 리소스별 재정의

모듈 호출은 로컬 `merge`로 단일 키를 좁힐 수 있습니다. 예를 들어 버티컬별 실행기 MI는
`merge(local.tags, { "fdai:vertical" = "resilience" })`를 설정합니다. 한 리소스가 한 개념에
대해 경쟁하는 키 두 개를 가지지 않도록 같은 `fdai:` 네임스페이스를 사용하세요. 같은 리소스
종류를 여러 번 프로비저닝할 때는 `core`와 `worker` 같은 CAF 컴포넌트 토큰을 위해
`fdai:component`를 예약합니다.

### 규칙

- **모든 FDAI 키에 `fdai:` 네임스페이스를 사용합니다**: `env` 또는 `vertical` 같은 bare
  키는 다른 팀과 충돌하고 grep 가능성 보장을 깨뜨립니다.
- **고객 및 시크릿 값을 `base_tags`에 넣지 않습니다**: 배포별 이름과 마찬가지로 커밋하지
  않은 `*.tfvars`의 `additional_tags`에 둡니다.
- **질의 값을 안정적인 소문자로 유지합니다**: 비용 관리와 Resource Graph는 `true`,
  `dev`, `resilience` 같은 리터럴 값으로 그룹화하므로 표류가 발생하면 집계가 깨집니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/deployment/deployment-resource-conventions.md) |
| 구체적인 리소스 인벤토리 및 초기화 순서 | [배포 및 온보딩](deploy-and-onboard-ko.md) |
| 배포 수명 주기 및 환경 모델 | [배포](deployment-ko.md) |
| 고객 비종속 배포 설정 | [Customer-Agnostic 범위](../../../.github/instructions/generic-scope.instructions.md) |
