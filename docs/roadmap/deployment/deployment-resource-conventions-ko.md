---
title: 배포 리소스 규약
translation_of: deployment-resource-conventions.md
translation_source_sha: 0f1d6555d57f37af2379fad6fb7a469cd8b26a52
translation_revised: 2026-10-31
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

### 지역 토큰 설계와 비평

**초기 설계:** 알 수 없는 Azure 지역 토큰은 지역 이름을 다섯 글자로 잘라 파생합니다.

**비평:** 잘라내기는 명명 계약이 아닙니다. `westus`와 `westus3`가 모두 `westu`가 되는 것처럼
서로 다른 공용 지역을 같은 토큰으로 매핑할 수 있고, 한 구독의 두 설치가 같은 리소스 그룹을
대상으로 삼을 수 있습니다. 새 Azure 지역도 검토된 토큰 없이 지원되는 것처럼 보입니다.

**개정된 계약:** 새 설치는 `azure_naming.py`의 검토된 Azure 공용 지역 토큰 표만 사용합니다.
표에 없는 지역은 Azure 효과 전에 실패합니다. 기존 설치는 보존된 Foundation 변수와 프로파일에
기록된 토큰을 유지합니다. 같은 작업 디렉터리의 연속 실행은 새 표에서 토큰을 다시 계산하지
않습니다. 보존된 상태 없이 실행을 시작하면 조정기는 계획 전에 같은 구독, 환경, 워크로드 및
Azure 위치에 대해 읽기 전용 리소스 그룹 검색을 수행합니다. FDAI 소유 태그와 이름에서 단일로
일치하는 토큰을 재사용하며, 이후 설치가 명시적 `fdai:region-token` 태그를 기록하면 그 태그를
사용합니다. 후보 토큰이 둘 이상이면 검색은 실패로 닫힙니다. 자동 이름 변경이나 마이그레이션은
수행하지 않습니다.

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
| `fdai:region-token` | `wus3` 같은 검토된 짧은 토큰 또는 `westu` 같은 보존된 legacy 토큰 | Foundation 변수 / Terraform 입력 | 향후 검색을 위한 명시적 명명 토큰입니다. 이전 설치에는 이 태그가 없을 수 있으므로, 검색은 FDAI 소유 리소스 그룹 이름을 파싱하고 모호하면 실패로 닫힙니다. |
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

## CI 전용 SSD 러너 경계

독립적인 [`infra/ci-runner`](../../../infra/ci-runner/README.md) 루트는 별도의
CI 리소스 그룹과 피어링하지 않은 네트워크를 소유합니다. VM에는 공인 IP, Managed Identity,
배포 역할 할당 또는 배포 러너 라벨을 부여하지 않습니다. 인터넷에는 아웃바운드 전용 NAT
주소로 접근합니다. Terraform 변수와 명시적인 로컬 백엔드 상태 경로는 소스 관리 대상에서
제외합니다. 정책이 추가한 IP 태그는 관측된 값을 입력하며, 태그를 제거하려고 주소를 교체하지 않습니다.

서브넷 수준의 네트워크 보안 그룹(NSG)이 접근을 제어하며, VM은 해당 연결이 완료된 후 생성됩니다.
NIC에 한정된 Trivy `AZU-0068` 주석은 검사기의 한계를 기록합니다. 회귀 테스트는 인바운드 접근을
허용하는 대신 서브넷 연결과 생성 의존성이 유지되는지 확인합니다.

OS 디스크는 Premium SSD를 사용합니다. 로컬 임시 SSD에는 삭제되어도 재생성할 수 있는 작업 공간과
캐시를 저장합니다. 해당 디스크가 마운트되지 않으면 러너가 시작되지 않습니다. 등록할 때는 수명이 짧은
토큰을 Azure의 보호된 환경 매개변수로 전달하며, Terraform이나 명령줄 값에 넣지 않습니다.

매니페스트에는 시간대 데이터와 필요한 IANA 이름도 포함합니다. 컨테이너 기반 러너는 초기화 프로세스로
고아 자식 프로세스를 회수합니다. 서비스 러너의 정리 검사는 컨테이너 안에 호스트 VM의 초기화 시스템이
있다고 가정하지 않습니다.

모든 러너는 선언된 하나의 도구 체인으로 수렴합니다. `toolchain.json`에 회귀 테스트 작업에 필요한 패키지,
공유 라이브러리, 체크섬 또는 지문으로 고정한 도구를 나열합니다. 멱등 프로비저너가 cloud-init이나
보호된 Run Command로 이를 적용하며, 실패 시 닫히는 검증기가 등록 전과 모든 자체 호스팅 회귀 테스트 작업
시작 시점에 실행됩니다. 항목이 없거나, 고정 버전이 다르거나, 다른 계정이 쓸 수 있는 도구가 있는 러너는
테스트를 실행하기 전에 거부됩니다. 따라서 새로 만들거나 재구성한 러너가 실행 도중에 실패하지 않습니다.

선택적 탄력 러너는 [`infra/ci-runner-aca`](../../../infra/ci-runner-aca/README.md)에서 고정 풀을 대체하며,
대기 중인 작업 수에 따라 0개에서 선언된 상한까지 확장되는 일회용 Container Apps Job 실행으로 구성합니다.
이미지는 같은 도구 체인 매니페스트로 빌드하고, 레지스트리 풀 외의 배포 ID를 갖지 않으며, GitHub
자격 증명을 Terraform과 워크플로 코드에 노출하지 않습니다. 보호된 main의 회귀 테스트는 샤드 4개 대신
8개로 실행됩니다. 초기 측정에서는 667초와 약 330초를 기록했지만, 실패한 테스트와 서로 다른
크기의 러너가 포함되어 성공한 전환이나 통제된 처리량 비교를 보여 주지는 못합니다.
`FDAI_CI_ELASTIC_RUNNER_ENABLED` 변수가 SSD 풀보다 먼저 이 러너를 선택하며, 포크에도 안전한
풀 리퀘스트 가드가 마련되기 전까지 풀 리퀘스트는 GitHub 호스팅 실행을 유지합니다.

호스팅 러너를 없애는 전환에서는 신뢰할 수 있는 제어 작업, Docker를 쓰지 않는 일회용 테스트,
Docker를 지원하는 격리 VM 작업을 분리합니다. `scripts/quality/ci/check-runner-cutover.py`는 완전한
스냅샷에서 남아 있는 호스팅 작업과 부족한 풀을 보고하며, 자격 증명을 읽거나 권한을 변경하지 않습니다.
실제 GitHub 작업으로 등록, 성공한 실행, 상한이 있는 큐 기반 확장, 등록 해제, 축소를 확인하기 전까지
기존 용량을 유지합니다. 자격 증명이나 실행 허용 설계가 준비되지 않았다면 운영 전환은 완료가 아니라 차단 상태입니다.

### 성능 우선의 준비 용량

[`ci-runner-pools.json`](../../../config/ci-runner-pools.json)의 목표 정책은 제어 풀, 일반 컨테이너 풀,
Docker를 지원하는 VM 풀을 분리합니다. 계획 CLI의 `plan` 모드는 실행하지 않고 권고만 합니다.
별도 활성화 절차를 따르는 조정기의 기본값은 `FDAI_RUNNER_CONTROLLER_APPLY=0`입니다.
정책이나 로컬 구현 근거만으로 워크플로 경로가 활성화되지는 않습니다.

| 풀 | 준비된 유휴 러너 목표 | 수요 감소가 지속될 때의 준비 용량 | 상한 | 초기 러너별 CPU |
|---|---:|---:|---:|---:|
| 제어 | 2 | 2 | 4 | 1 |
| 일반 컨테이너 | 8 | 2 | 64 | 4 |
| Docker 지원 VM | 2 | 1 | 16 | 4 |

`scripts/automation/plan_runner_pools.py`는 완전하고 최신인 스냅샷으로 즉시 계획합니다.
목표 용량은 실행 중 작업, 지금 실행할 수 있는 대기 작업, 준비 용량의 합입니다. 유휴, 시작 중,
사용 중, 회수 중 러너를 각각 한 번만 셉니다. 시작 상태를 확인할 수 없으면 중복 용량을 만들지 않도록
대체 계획을 차단합니다. 수요 감소가 지속되고 유휴 유지 시간이 지난 러너만 축소 대상으로 선택합니다.
사용 중이거나 시작 중인 러너는 회수 대상으로 선택하지 않습니다.

수요 감소가 지속되고 유휴 유지 시간이 지나면 준비 용량을 `2/8/2`에서 `2/2/1`로 줄입니다.
수요가 다시 늘면 같은 상한 안에서 높은 준비 용량으로 복원합니다. 각 풀은 권한을 받은 조정기 하나가
관리합니다. 새 일반 풀은 기존 KEDA 수요 라벨 대신 `fdai-ci-general`을 사용합니다.
명시적으로 이전하기 전까지 기존 KEDA 이벤트 트리거는 이전 풀을 관리하고, 조정기는 새 Manual Job만
관리합니다. 두 스케일러가 같은 수요를 기준으로 실행을 생성하는 구성은 지원하지 않습니다.

`scripts/quality/ci/runner-pool-readiness.py`는 전체 CI 작업 매핑, 풀 기능, 공유 할당량,
준비 용량, 관리 ID 격리, PR 실행 허용, 실제 실행과 회수 결과를 검사합니다. 제어 러너와 일반
러너는 컨테이너 CPU 예산을 공유하며, VM 작업은 별도의 지역 Compute 예산을 사용합니다.
같은 가용 할당량을 중복 계산하지 않습니다. 설정된 예산은 컨테이너 CPU 260개와 VM CPU 64개입니다.
이 상한은 할당량을 예약하거나 공급자 용량을 보장하지 않습니다. 활성화하기 전에 실제 지역별,
컨테이너 환경별, VM 제품군별 할당량 여유, 기존 사용량, 선택한 VM SKU의 가용 용량을 확인합니다.
사전 구성한 VM 이미지가 설정되지 않으면 Docker를 명시적으로 사용할 수 없는 상태로 유지합니다.

할당량과 앞 단계 검증이 유효할 때만 동시 작업 수를 8, 16, 32, 64개 순서로 늘립니다.
인수 검증 목표는 준비된 러너의 대기시간 p95 15초 이하, 버스트 대기시간 p99 90초 이하,
최대 120초 이하입니다. 예상한 모든 작업이 정확히 한 번 성공하고 실제 동시 실행 수가
요청한 단계에 도달해야 합니다. 사용 중 작업을 중단하지 않고 준비 용량으로 축소되는지도 확인합니다.
단일 버스트는 최근접 순위로 관측값을 보고하며 전체 모집단의 지연시간을 보장하지 않습니다.
새 조정기의 큐 SLO를 측정했거나 운영 전환을 완료했다고 주장하지 않습니다.

### 1단계: 격리된 PAT 조정기

1단계에는 아래의 격리된 실행 환경과 인프라가 포함됩니다. 실제 배포와 풀 수용 검증은
별도의 단계이며 아직 확인하지 않았습니다.
[`infra/ci-runner-controller`](../../../infra/ci-runner-controller/README.md)는 빌드를 실행하지 않는
조정기 하나, 조정기와 작업 실행기를 분리한 Container Apps 환경, 작업 실행기용 Manual Job 두 개를
정의합니다. 세분화된 개인용 액세스 토큰(PAT)은 조정기만 보유하며 GitHub App을 만들거나 요구하지 않습니다.
조정기의 Managed Identity에는 범위를 제한한 실행 요청 및 상태 접근 권한을 부여하고, 작업 실행기
ID에는 해당 레지스트리의 `AcrPull`만 부여합니다. VM 작업 실행기에는 Managed Identity나 공인 IP를
부여하지 않습니다. 레지스트리 전용 ID의 런타임 엔드포인트 제한은 플랫폼에서 별도로 확인해야 합니다.

`scripts/automation/runner_controller/`의 런타임은 Blob 임대와 조건부 상태 갱신으로 실행 요청 전에
시작 의도를 저장합니다. 일회용 브로커 티켓으로 수명이 짧은 JIT 등록 정보를 전달하며, 작업 실행기
코드에는 PAT을 전달하지 않습니다. 소유 기록은 리소스를 조정기의 이름 접두사에 연결합니다.
시작 결과가 불확실할 때는 공급자 상태를 다시 조회해 리소스 참조를 복구할 수 있습니다.
시작이나 JIT 교환 결과를 확인할 수 없으면 용량 슬롯을 유지하고 `starting_timeout`을 보고합니다.
등록을 무작정 재시도하거나 중복 용량을 만들거나 작업 실행기를 강제 종료하지 않습니다.
GitHub 조건부 GET 캐시는 인증된 `304` 응답을 받은 경우에만 스냅샷을 재사용합니다.
ETag가 있다는 이유만으로 오래된 데이터를 현재 상태로 취급하지 않습니다.

회수 절차는 상태 잠금으로 유휴 러너의 회수와 작업 실행기 콜백이 동시에 처리되지 않도록 하며,
사용 중이라는 거부 응답을 따릅니다. GitHub 등록을 해제했다고 프로세스나 작업이 끝난 것은 아닙니다. 소유한 VM/NIC 리소스를
삭제하기 전에 자연 종료를 기다리고 공급자와 GitHub의 신뢰할 수 있는 종료 상태를 확인합니다.
결과가 불확실하거나 아직 실행 중이면 슬롯을 유지합니다. 등록 해제 응답만으로 강제 중지하지 않습니다.

생성 후 한 시간이 지난 유휴 작업 실행기는 대체 실행기의 준비 상태를 확인한 뒤 회수합니다.
컨테이너 실행 상한인 24시간과 이 유휴 실행기 교체 절차는 별개이며, 지원하는 CI 작업은
6시간 안에 끝나야 합니다. VM 게스트는 시작 프로세스가 종료된 뒤에만 전원을 끕니다.
공급자가 확인한 중지 또는 할당 해제 상태로 누락된 종료 콜백을 복구할 수 있지만,
삭제하기 전에는 GitHub에 실행 중인 작업이 없는지와 리소스 소유권을 다시 확인합니다.
시작 상태를 확인할 수 없다는 이유만으로 종료되었다고 판단하지 않습니다.

컨트롤러 앱은 비밀값을 조회하는 AzureRM 새로고침 대신 AzAPI의 일반 ARM GET을 사용합니다.
Terraform은 초기 `unset` 자리표시자만 관리하고 이후 비밀값 변경은 제외합니다.
실제 자격증명은 대화형 설정 스크립트로 관리하며, ARM `PUT`이 `value`가 생략된 `GET` 마스킹
비밀 항목을 거부하므로 `ignore_body_changes` 없이 `ignore_changes`만 사용하고 `202 Accepted`
장기 실행 업데이트가 `Succeeded`로 완료될 때까지 확인합니다. 컨트롤러 Container Apps 환경은
전용 컨트롤러 VNet과 Blob 프라이빗 엔드포인트 및 프라이빗 DNS 영역을 사용하여 워커나
애플리케이션 네트워크를 공유하지 않고도 상태 스토리지의 `public_network_access_enabled = false`를
유지합니다. 사용자 할당 관리 ID 토큰 요청은 `AZURE_CLIENT_ID`를 전달하고 만료 전 토큰을
캐시하며, 동시 상태 쓰기는 활성 Blob 임대 아래에서 병합 커밋됩니다. CI는 공통 러너 매니페스트의 Terraform
버전을 사용하며 모의 공급자로 이 루트를 검증하고 테스트합니다.
계획과 Terraform 상태에 PAT나 웹후크 키를 저장할 필요가 없습니다.

Terraform 상태는 운영자가 승인한 암호화 저장 위치에 보관하고, 애플리케이션과 기존 러너의
상태와 분리합니다. 비공개 backend가 접근을 차단하면 네트워크 통제를 유지합니다.
승인된 접근 경로나 암호화된 로컬 저장 위치가 준비될 때까지 프로비저닝을 중단합니다.
이미지 게시 성공만으로 컨트롤러나 풀이 프로비저닝되었다고 판단하지 않습니다.

새 CI 전용 소스 가드 `.github/actions/verify-ci-runner-source`는 기존 검증기에 추가하는 기능입니다.
신뢰할 수 있는 소스를 먼저 게시한 뒤, 별도로 검토할 2단계 PR 경로 변경에서 게시된 가드를 사용합니다.
경로 전환은 명시적으로 활성화하며, 실제 운영 활성화는 별도 단계입니다. 프로덕션/main 전용 소스 검증기와 그 권한은 변경하지 않으며,
후보 코드가 제어하는 검증 코드로 대체하지 않습니다. 자격 증명 입력, 이미지 빌드, 정확한 대상에 대한
적용, 할당량 확인, ID 격리, 실제 실행 및 회수 증적은 운영 단계의 완료 조건으로 남아 있습니다.

### 명시적 CI 경로 전환과 독립 canary 검증

`FDAI_CI_POOLS_ENABLED=true`를 설정하면 `ci.yml`과 `container-supply-chain.yml`의 대상 검증,
PR 이미지 빌드, main 이미지 게시 작업을 정의된 control/general/Docker 풀로 보냅니다.
플래그를 설정하지 않거나 false로 두면 기존 경로를 유지합니다. 8개 샤드 경로는 일반 회귀
테스트를 대체하며 중복 실행하지 않습니다. 서비스 컨테이너 작업은 Docker VM을 사용하고,
의존하는 권한 작업을 시작하기 전에 소스 승인을 완료합니다. 최종 필수 작업은 상위 검사가
실패해도 자체 소스를 검증합니다.

이미지 게시 작업은 자체 프로덕션 소스 검증 단계, 기존 권한과 환경, main 전용 조건을 유지합니다.
릴리스, 배포, Pages, 운영 관리 워크플로는 별도 권한 경로를 유지하며,
이 플래그가 저장소 전체의 실행 권한을 옮기는 것은 아닙니다.

전체 경로를 활성화하기 전에 보호된 main의 컨테이너 워크플로를 수동 실행합니다.
`canary=true`, `images=canary`, 현재의 정확한 `commit_sha`와 함께 `canary_pool`,
`canary_count`, `canary_hold_seconds`, `canary_kind`를 명시합니다.
이 경로는 이미지를 게시하거나 다른 실행을 취소하지 않습니다. 작업 수 상한은
control/general/Docker별 4/64/16이며, 유지 시간은 120-180초입니다.
독립적인 GitHub 관측으로 모든 예상 작업의 정확한 성공 집계, 요청한 실제 동시 실행 수,
선택한 warm/burst 대기 시간 기준을 확인해야 합니다.
모의 증적이나 실행 요청 성공만으로 수용 검증을 완료했다고 판단하지 않습니다.

푸시 전 워크플로 집중 검사는 새 풀과 canary 테스트뿐 아니라 기존 SSD/탄력적 러너와 이미지
게시 계약을 검증하는 테스트도 실행합니다. 정적 워크플로 검사만으로는 기존 선택 식과 소스
리비전 검증이 활성화 경로와 롤백 경로에 모두 맞는지 확인할 수 없습니다.

### 설계 비평과 수정

- **디스패치와 인계**: 작업 실행기별 예약을 먼저 저장하고, 공급자 시작 요청은 최대 8개까지
  동시에 처리합니다. 디스패치 제한 시간은 120초이며, 대기 중인 요청을 취소하더라도 실행 중인
  CI 작업은 중지하지 않습니다. 준비되지 않은 HTTP 프런트는 실행 권한을 부여하지 않습니다.
  임대를 획득하고 범위를 검증한 뒤 브로커를 활성화하며, 예상된 임대 충돌의 인계 대기는 최대 90초입니다.
- **컨트롤러 중단**: 작업 시작 콜백이 실패하면 경고를 남기되 실행 중인 리스너는 유지합니다.
  자격증명이 없으면 입력 후 재시작할 때까지 명시적으로 사용 불가 상태를 유지합니다.
- **CI 이미지 빌드**: 허용 목록에 있는 CI 검증 작업만 승인합니다. 아티팩트 게시 작업은 자체
  프로덕션 소스 검증기, 권한, main 전용 조건을 유지합니다. 추가 워크플로를 연결하기 전에
  확장된 검증기를 게시하며, CI 승인 작업에 대한 의존성만으로 게시 권한을 부여하지 않습니다.
- **중복 확장**: Manual Job 소유권과 `fdai-ci-general` 수요를 기존 KEDA에서 분리합니다.
- **회수 경합**: 상태 잠금 안에서 회수를 예약하되, 등록 해제를 완료로 간주하지 않고 자연 종료를 확인합니다.
- **오래된 캐시와 불확실한 결과**: 인증된 `304`로 캐시를 재검증하고 공급자 상태를 다시 조회합니다.
  시작 결과를 모르면 대체 실행을 생성하지 않고 기존 슬롯을 유지합니다.
- **비밀 경계**: PAT과 관리 ID는 빌드를 실행하지 않는 조정기의 별도 환경에 둡니다.
  작업 실행기에는 일회용 초기화 정보와 레지스트리 풀 권한만 전달합니다.

선택적 가속은 회귀 테스트 샤드 4개를 같은 VM의 리스너 최대 5개로 구성한 풀로 이동합니다.
각 샤드는 pytest 워커 3개를 사용합니다. 리스너마다 실행 파일, 작업 공간, 캐시 경로를 분리하고,
systemd에서 CPU 3개와 RAM 12 GiB로 제한합니다.
등록 과정에서는 대상이 일치하는 유휴 러너를 유지하며, 작업 중이거나 대상이 다른 러너는 변경하지 않습니다.
공통 테스트 도구도 작업별로 설치합니다. OPA는 sudo나 공용 `/tmp/opa` 바이너리 대신
`RUNNER_TEMP`와 `GITHUB_PATH`를 사용하므로, 병렬 리스너에 관리 권한을 부여할 필요가 없습니다.
보호된 main의 소스 출처 검증을 통과하고 `FDAI_CI_SSD_RUNNER_ENABLED=true`가 설정되어야 합니다.
모든 끌어오기 요청과 비활성화 경로는 GitHub 호스팅 러너를 계속 사용합니다. 러너 준비 상태,
워크플로 게시, 경로 활성화, 측정된 CI 개선은 각각 별도의 근거가 필요하며, 한 단계의 확인이
다음 단계의 완료를 의미하지 않습니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/deployment/deployment-resource-conventions.md) |
| 구체적인 리소스 인벤토리 및 초기화 순서 | [배포 및 온보딩](deploy-and-onboard-ko.md) |
| 배포 수명 주기 및 환경 모델 | [배포](deployment-ko.md) |
| 고객 비종속 배포 설정 | [Customer-Agnostic 범위](../../../.github/instructions/generic-scope.instructions.md) |
