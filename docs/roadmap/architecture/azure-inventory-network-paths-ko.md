---
title: 제한된 네트워크의 Azure 인벤토리
translation_of: azure-inventory-network-paths.md
translation_source_sha: dfbb6978ef5744b6c675e68f1e03482235af6080
translation_revised: 2026-09-27
---
# 제한된 네트워크의 Azure 인벤토리

이 문서는 NSG, 경로, DNS 정책 또는 비공개 엔드포인트가 관리 평면 접근을 제한할 때 Azure
인벤토리 발견이 명시적이고 실패 시 차단 상태를 유지하는 방법을 정의합니다. 와이어 계약을
변경하거나 발견 경로에 작업 권한을 부여하지 않으면서 프로바이더 중립
[인벤토리 계약](csp-neutrality-ko.md#5-인벤토리-계약---리소스-그래프)을 구체화합니다.

> **범위:** 이 경로는 구현된 Azure 어댑터에 적용됩니다. 미래의 프로바이더는 코어 동작을
> 변경하지 않고 자체 계약 동등 전송 및 근거를 제공합니다.

## 설계 요약

NSG로 잠긴 서브넷 때문에 도달할 수 없는 디스커버리 소스가 빈 인벤토리로 바뀌면 안 됩니다.
FDAI는 네트워크 도달성, 아이덴티티, 수집, 프로젝션을 별도 단계로 취급하고 실패한 단계를
기록합니다. 성공한 빈 스냅샷은 "범위에 리소스 없음"을 의미합니다. 차단된 엔드포인트, 토큰
실패, 불완전한 페이지 집합, 사용할 수 없는 수집기는 "인벤토리 사용 불가"를 의미하며 마지막
완전한 스냅샷을 유지합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 제한된 네트워크 발견 및 순서가 지정된 출처 대체 경로 | in-progress | `delivery/azure/` 아래 Azure 인벤토리 어댑터, 배포 preflight 및 연결 계약 | 범위가 제한된 어댑터와 실패 분류가 있습니다. 이 문서는 모든 대체 단계를 입증하는 exact-revision 보호 배포를 하나로 보존하지 않습니다. |
| 격리된 대체 경로 인증 | implemented | `inventory_network_certification.py`, `infra/inventory-network-certification/`, 정확한 생성 및 정리 계획 검증기, 집중 검사 | 작업 전용 샌드박스는 기존 개발 네트워크를 변경하지 않고 토큰, DNS, TLS, 범위가 제한된 ARG, 비공개 변환 결과, ARG에서 ARM으로 한 번 전환, 활성 세대 유지, 복구, 독립적인 비공개 증적 조회, 정확한 정리를 입증할 수 있습니다. 관리되는 실행은 아직 남아 있습니다. |
| 스냅샷 권위 및 stale 상태 처리 | implemented | [CSP-중립성 계약](csp-neutrality-ko.md#구현-상태)이 인용하는 인벤토리 동기화, 프로젝션 및 재조정 테스트 | 부분 수집은 마지막 완전 승격 세대를 교체하거나 부재 주장을 승인할 수 없습니다. |
| 서브넷별 네트워크 제어 | implemented | `infra/modules/network/main.tf`, `infra/bootstrap/main.tf`, 집중 네트워크 강화 테스트 | VM이 있는 서브넷은 명시적인 NSG로 Internet inbound를 거부합니다. Azure 관리형 delegated 및 private-endpoint 서브넷은 서비스 소유 네트워크 정책 계약을 유지합니다. |
| AKS fleet 관측 연결 | implemented | `infra/main.tf`, `infra/scenario-lab/aks.tf`, Container Apps Inventory Job, 집중 AKS 신원 및 시나리오 검사 | 정확한 workload-identity 연결은 읽기 전용으로 유지됩니다. 폐기 가능한 시나리오는 Microsoft Entra와 Azure RBAC로 보호되고 로컬 계정이 비활성화된 공개 API 하나를 사용할 수 있으며, Trivy 및 Checkov 공개 접근 예외는 해당 리소스에만 적용됩니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-27 | implemented | migration이 데이터베이스에 도달한 뒤 `vector` 생성이 거부된 결과에 따라 정확한 Azure PostgreSQL 확장 허용 목록과 단일 주소 복구 계획 게이트를 추가했습니다. | `current change`, 집중 계획 게이트 검사와 Terraform 검증. | 병합한 뒤 migration을 다시 실행하기 전에 확장 configuration만 적용합니다. |
| 2026-09-27 | in-progress | 두 번째 migration 실행은 DSN 구문 분석과 비공개 연결을 통과했지만 `vector`가 허용 목록에 없어 스키마 생성 전에 중단됐습니다. 후보 migration 이미지는 검토를 위해 연결된 상태로 남았고 캠페인 작업은 시작하지 않았습니다. | 정확한 migration 실행과 정제된 데이터베이스 오류. | 범위가 제한된 확장 복구 계획을 적용하고 변경 0건을 검증한 뒤 migration을 다시 실행합니다. |
| 2026-09-27 | implemented | 추가 apply 없이 인증 루트를 권위 있는 Azure 재확인과 맞췄습니다. 명시적인 Consumption 워크로드 프로필과 delegation actions, 보존된 PostgreSQL zone, 정책 관리 태그 및 service endpoint의 수명 주기 보존을 추가했습니다. | `current change`, apply 후 표류 필드 재확인과 집중 Terraform 검사. | 병합한 뒤 보존된 복구 state에서 plan-only 검증을 실행합니다. |
| 2026-09-27 | in-progress | 복구 create 계획은 성공적으로 적용돼 Terraform state 주소 37개와 태그가 있는 Azure 리소스 13개를 만들었지만, 첫 apply 후 계획에서 프로바이더 또는 정책 정규화 update 6개를 발견했습니다. 캠페인 작업은 시작하지 않았습니다. | 관리 호스트 apply claim, state, Azure 재확인, apply 후 계획 로그. | 수정된 원본이 변경 0건인 계획을 만들 때까지 샌드박스를 그대로 유지합니다. |
| 2026-09-27 | implemented | 공유 DNS를 건드리지 않도록 샌드박스 설계를 복구했습니다. PostgreSQL은 요청마다 고유한 비공개 영역을 사용하고, Blob은 원래 hostname을 TLS SNI와 HTTP Host로 검증하면서 정확한 비공개 엔드포인트 IP에 연결하며, 캠페인 Reader는 애플리케이션 리소스 그룹으로 제한합니다. | `current change`, 집중 전송 검사, Terraform 검증, Trivy 및 Checkov 실패 발견 사항 0건. | 새 exact 요청을 병합하고 실행하며 실패한 계획은 재사용하지 않습니다. |
| 2026-09-27 | in-progress | 첫 관리 create 계획은 공유 비공개 DNS 영역 이름 충돌과 구독 범위 Reader 할당 거부로 부분 효과 뒤에 중단됐습니다. 변경할 수 없는 claim, 계획, 로그, Terraform state 주소 24개, 태그가 있는 Azure 리소스 7개를 보존했습니다. | 비공개 apply claim과 계획 다이제스트 `90e269aac3fb606fef0e7a9d9b6fa2d43f6eabdbfbf0a858cc3cc620956f79d8`, 권위 있는 리소스 및 state 재확인. | 복구 검토를 위해 실패한 샌드박스를 보존하고 새 요청으로 인증합니다. |
| 2026-09-27 | implemented | 관리 호스트 UAMI가 기존 개발 애플리케이션 리소스 그룹에서 정확한 Contributor 및 역할 할당 권한을 이미 보유하므로 샌드박스 생성을 해당 그룹에 결속했습니다. 계획은 더 이상 리소스 그룹을 생성하거나 태그를 바꾸거나 삭제하지 않습니다. | `current change`, Terraform 대상 경계와 정확한 생성/삭제 주소 게이트. | 관리되는 캠페인을 실행하고 작업 태그가 있는 샌드박스 리소스만 제거됐는지 검증합니다. |
| 2026-09-27 | implemented | 인프라 이중 암호화를 적용한 비공개 증적 저장소, 기본 거부 네트워크 규칙, Blob 진단, PostgreSQL 감사 설정, 모든 작업 전용 서브넷의 NSG로 격리된 인증 샌드박스를 강화했습니다. | `current change`, Low 초과 Trivy 발견 사항 0건, Checkov 실패 검사 0건, Terraform 검증 및 정확한 계획 게이트 검사 통과. | 관리되는 정확한 revision 캠페인을 실행하고 작업 전용 정리를 검증합니다. |
| 2026-09-17 | implemented | API, 신원 또는 권한 부여 경계를 넓히지 않고 폐기 가능한 시나리오의 리소스 한정 공개 접근 예외를 Checkov까지 확장했습니다. | `current change`, `infra/scenario-lab/aks.tf`, 집중 Trivy 및 Checkov 스캔과 시나리오 랩 검사. | 보호된 재생성과 FDAI Pod 인벤토리 조회 결과를 보존합니다. |
| 2026-09-17 | implemented | 폐기 가능한 시나리오에 인증된 공개 AKS API 경로를 추가하고 두 공개 접근 스캐너 예외를 해당 리소스 하나로 제한했습니다. | `current change`, `infra/scenario-lab/aks.tf`, 집중 Trivy 스캔 및 시나리오 랩 검사. | 보호된 재생성과 FDAI Pod 인벤토리 조회 결과를 보존합니다. |
| 2026-09-10 | implemented | 기존 및 fleet AKS 관측 연결을 상호 배타적으로 추가하고 정확한 클러스터별 Reader를 부여했습니다. | `current change`, Terraform 형식 검사 및 집중 신원 검사 | 보호된 배포 근거는 별도로 보존합니다. |
| 2026-08-21 | in-progress | 런타임 동작이나 권한을 변경하지 않고 기존 제한 네트워크 인벤토리 설계를 집중 소유 문서로 옮겼습니다. | `current change`; 문서 크기, 번역, 경로 및 링크 검사입니다. | 실제 네트워크 경로와 하나 이상의 대체 및 복구 전환에 대한 exact-revision 보호 근거를 보존합니다. |
| 2026-08-25 | implemented | OHL 근거 VM 서브넷에 명시적인 NSG 보호를 추가하고 기존 배포 runner 서브넷 연결을 검증하면서 Azure 관리형 delegated 서브넷 제약을 유지했습니다. | `current change`; `tests/integration/infra/test_network_hardening.py`, `tests/integration/infra/test_bootstrap_network_hardening.py`, Checkov와 Trivy의 Low 초과 활성 점검 결과 0건. | 실제 NSG와 route 정책이 필수 관리 경로를 계속 허용한다는 배포 근거를 보존합니다. |
| 2026-08-24 | implemented | 일회용 시나리오 경로가 사용하는 양방향 게이트웨이 전송 피어링의 생성 순서를 직렬화했습니다. | 실패한 보호 apply `32773217323`, `32774040807`, 비대칭 피어링 조회 결과, `infra/scenario-lab/main.tf`, 집중 시나리오 랩 계약. | 워크스테이션 경로 검증 전에 두 피어링이 모두 Connected 상태임을 보여 주는 보호 증적을 보존합니다. |
| 2026-08-25 | implemented | 프로바이더가 펼친 업그레이드 기본값이 반복 update를 만들지 않도록 일회용 AKS 노드 풀의 관측된 surge 정책을 pin했습니다. | 값이 없는 계획 `32793483505`, `infra/scenario-lab/aks.tf`, 집중 시나리오 랩 및 Terraform 검사. | 실제 sweep 전에 변경 0건인 보호 계획을 보존합니다. |

### 남은 작업

- [ ] 토큰, DNS, TCP/TLS, 제한된 ARG 조회, 비공개 프로젝션 쓰기, 사용할 수 없는 출처의
  대체 경로 하나, stale 유지 및 발견 또는 실행기 신원을 넓히지 않는 성공적 복구를 입증하는
  exact-revision 보호 배포 증적을 보존합니다.

## 격리된 인증 샌드박스

제한된 네트워크 장애 근거는 기존 개발 애플리케이션 리소스 그룹 안의 작업 전용 리소스 집합을
사용합니다. 자체 Virtual Network, 위임된 Container Apps 및 PostgreSQL 서브넷, 비공개 DNS
영역, 비공개 PostgreSQL 서버, 비공개 Blob 증적 저장소를 생성합니다. 기존 리소스 그룹을
태그하거나 삭제하지 않으며 기존 개발 Virtual Network, DNS, NSG, Private Endpoint, 신원,
공급자 등록 또는 활성 인벤토리 세대와 피어링하거나 이를 경유하거나 변경하지 않습니다.

PostgreSQL 비공개 DNS 영역은 요청마다 고유합니다. Blob 증적 I/O는 TLS SNI와 HTTP Host
헤더를 계정 hostname에 결속한 채 정확한 비공개 엔드포인트 주소에 연결하므로, 캠페인은 공유
Blob 영역을 연결하거나 그 안에 레코드를 쓰지 않습니다.

정확한 생성 계획은 검토된 샌드박스 주소만 허용합니다. 한 워크로드 신원은 범위가 제한된
`resource-group` 타입에 대해 `arg,arm` 캠페인을 실행하고, 별도의 읽기 전용 신원은 비공개
증적을 검증합니다. 캠페인은 워크로드 토큰, DNS, TCP/TLS, 범위가 제한된 ARG, 비공개 변환
결과 쓰기, ARG 사용 불가, 한 번의 ARM 대체, 활성 세대 유지, 우선순위가 높은 ARG 복구를
기록합니다. 같은 정확한 이미지는 완전, 불완전, 오래됨, 충돌, 사용 불가 의미 새로 고침
상태를 감사하고, 표준 부분 overlay 쓰기를 한 번만 허용하고, 권한을 부여하지 않은 채 정확한
활성 세대를 다시 조회합니다. 효과 검증이 성공한 뒤 별도의 정확한 삭제 전용 계획으로
정리합니다. 캠페인이나 정리 결과가 모호하면 복구 검토를 위해 샌드박스를 보존합니다.

## 필수 네트워크 경로

운영자 랩톱이 아니라 디스커버리를 실행할 서브넷과 아이덴티티에서 도달성 프로브를 실행하는
것이 좋습니다. 정확한 규칙은 런타임과 Azure 클라우드에 따라 다르지만 배포에서는 다음 경로를
고려합니다.

| 목적 | 기본 경로 | 제한된 네트워크 옵션 | 참고 |
|---|---|---|---|
| ARG 및 ARM 관리 읽기 | Azure Resource Manager 엔드포인트로 HTTPS `:443` | `AzureResourceManager` 서비스 태그로 NSG egress 허용; 좁은 관리 엔드포인트 허용 목록이 있는 Azure Firewall 또는 승인된 프록시를 통한 UDR; 대상 클라우드, 리전, 필수 ARG 작업이 지원하는 경우 Resource 관리 Private Link | 데이터 서비스용 비공개 엔드포인트는 ARM 또는 ARG 연결을 제공하지 않습니다. Azure 서비스 엔드포인트는 ARM 관리 경로를 대체하지 않습니다. |
| AKS 개체 인벤토리 | 정확한 클러스터 API로 HTTPS `:443` | 비공개 경로를 권장하지만 폐기 가능한 시나리오는 변하는 로컬 egress를 위해 고정 IP 허용 목록 없는 인증된 공개 API를 허용합니다. | 공개 도달성은 자격 증명, Kubernetes 권한 또는 실행 권한을 부여하지 않습니다. Microsoft Entra, Azure RBAC 및 로컬 계정 비활성화는 계속 필수입니다. |
| 워크로드 토큰 | 런타임 제공 managed 신원 또는 워크로드 신원 엔드포인트 | IMDS를 사용하는 경우 `AzurePlatformIMDS`를 포함한 런타임 플랫폼 아이덴티티 경로 허용; 앱 서브넷에서 토큰을 발급할 수 없으면 승인된 러너의 federated 워크로드 신원 사용 | 디스커버리만을 위해 광범위한 인터넷 egress나 클라이언트 시크릿을 추가하지 않습니다. |
| DNS | Azure 제공 DNS 또는 승인된 custom 해석기 | 해당되는 경우 `AzurePlatformDNS`를 포함한 런타임 플랫폼 DNS 경로 허용; 허브 해석기를 통해 필요한 공개 또는 Private Link 영역 전달 | 스캔을 시작하기 전에 엔드포인트 해석 및 TLS 프로브를 실행합니다. DNS 성공만으로 도달성이 증명되지는 않습니다. |
| 스냅샷 게시 | 비공개 PostgreSQL 및 Event Hubs 경로 | 디스커버리 러너에서 비공개 엔드포인트, VNet 피어링 또는 허브 라우팅 사용 | 수집기는 공개 콘솔 엔드포인트를 통해 인벤토리를 보내지 않습니다. |
| 초기 구성 진행률 근거 | 비공개 Foundation Blob 서비스 및 PostgreSQL | Bastion으로 접근 가능한 Managed Host는 기존 상태 계정 데이터 역할과 비공개 엔드포인트를 사용하고 Operator는 PostgreSQL만 읽습니다. | Blob 개체에는 개수 전용 해시 체인 레코드만 있으며 인벤토리 행이나 실행 권한은 없습니다. 반복 인벤토리는 이 부트스트랩 Blob 경로를 요구하지 않습니다. |

게이트웨이 전송에는 양방향 피어링이 필요합니다. 게이트웨이 VNet 방향에
`allow_gateway_transit`를 먼저 설정한 후 워크로드 VNet 방향에서 `use_remote_gateways`를
활성화하도록 Terraform 의존성 그래프에 순서를 명시하고, 양방향 모두 Connected 상태인지 검증합니다.

Terraform은 서브넷 소유권에 따라 NSG를 적용합니다. 배포 runner 또는 OHL 근거 VM을 호스팅하는
서브넷은 Internet inbound를 명시적으로 거부합니다. `GatewaySubnet`, Private DNS Resolver,
private endpoint, Container Apps 및 PostgreSQL delegated 서브넷은 Azure 관리형 서비스 계약을
유지합니다. 일반 NSG를 추가하는 방식은 서비스별 route 및 네트워크 정책 검증을 대체하지 않습니다.

서비스 태그와 Resource 관리 Private Link 기능은 Azure 클라우드에 따라 다를 수 있고 시간이
지나면서 변경될 수 있습니다. 배포 preflight에서 유효 경로, DNS 응답, 지원되는 작업을
확인하는 것이 좋습니다. 복사한 IP 범위보다 서비스 태그 또는 비공개 연결을 우선하고 Azure
엔드포인트와 클라이언트 신뢰 모델을 명시적으로 검증하지 않았다면 TLS interception을 피합니다.

## 순서가 지정된 폴백 단계

선언된 범위에 대해 완전하고 제한된 스냅샷을 생성할 수 있는 첫 번째 방법을 사용합니다. 전송
방식이 바뀌어도 `Inventory` 계약은 바뀌지 않습니다.

1. **런타임 서브넷의 ARG** - 명시적으로 허용된 ARM 관리 경로에서 managed 신원으로 샤딩된
   `Resources` 쿼리를 실행합니다. 광범위한 리소스 간 디스커버리와 제한된 페이지 처리를
   제공하므로 기본값으로 유지합니다.
2. **연결된 디스커버리 작업의 ARG** - 애플리케이션 서브넷에 의도적으로 관리 평면 egress가
   없다면 동일한 읽기 전용 어댑터를 VNet 통합 Container Apps 작업 또는 자체 호스팅 ops
   실행기로 이동합니다. 배치를 비공개 상태 저장소 또는 Kafka 유입에 게시하고 이 작업에 콘솔
   또는 코어 실행기 신원을 부여하지 않습니다.
3. **Resource 관리 Private Link 경로** - Azure가 필요한 ARG 호출을 지원하는 곳에서는 연결된
   작업을 승인된 비공개 엔드포인트 및 비공개 DNS를 통해 라우팅합니다. 비공개 DNS 해석만으로
   작업 지원을 증명할 수 없으므로 preflight에서 실제 제한된 ARG 쿼리를 실행합니다.
4. **직접 ARM 목록 어댑터** - ARG를 사용할 수 없거나 최신성 예산을 초과하면 등록된 각 리소스
   프로바이더 및 리소스 타입을 제한된 페이지 단위 샤드로 나열합니다. 어댑터는 동일한 리소스
   및 링크 기록으로 정규화하고 지원되지 않는 타입을 커버리지 공백으로 보고합니다. Azure CLI와
   Azure SDK 클라이언트는 이 방법의 전송 수단이며 독립 인벤토리 소스가 아닙니다.
5. **범위가 명시된 권위 있는 인벤토리** - 커버리지 매니페스트가 권위 있다고 선언한 리소스
   타입 및 구독에만 Microsoft Defender for Cloud 인벤토리 또는 승인된 다른 Azure 인벤토리
   프로젝션을 사용합니다. 보조 발견 사항은 전체 estate 커버리지를 의미하지 않습니다.
6. **변경 스트림 연속성** - full-snapshot 출처를 일시적으로 사용할 수 없는 동안 Event Hubs를
   통해 전달된 Activity Log 변경을 계속 소비합니다. Delta는 알려진 리소스의 최신성을
   유지하지만 그래프를 초기화하거나 보이지 않는 리소스가 없음을 증명할 수 없습니다.
7. **선언적 복구 스냅샷** - 실제 운영 관리 경로를 사용할 수 없으면 승인된 Terraform 상태/계획
   내보내기, Azure 배포 내보내기 또는 서명된 declarative 인벤토리 파일을 가져옵니다. 이를
   `observed`가 아닌 `expected`로 표시하고 생성 시간과 범위를 첨부하며 읽기 전용 맥락에만
   사용합니다. 자율 교정을 승인할 수 없습니다.

이 단계는 "모든 소스를 시도하고 행을 합치는 방식"이 아닙니다. 각 시도는 출처, 구독 또는
management-group 범위, 리소스 타입, 시작 및 완료 시간, 페이지 수, 오류를 포함하는 커버리지
매니페스트를 생성합니다. FDAI는 선언된 모든 샤드가 최종 fence에 도달한 뒤에만 소스를
승격합니다. 우선순위가 낮은 소스는 선언된 커버리지에서 사용할 수 없는 소스를 대체할 수 있지만
알 수 없는 공백을 조용히 채우거나 더 최신 권위 있는 기록을 덮어쓸 수 없습니다.

Azure 구현은 모든 neutral 리소스 id 앞에 구독 범위의 opaque 해시를 붙입니다. 따라서 서로 다른
구독에서 동일한 resource-group 및 리소스 경로를 사용해도 충돌하지 않고 온톨로지 키에 구독 id를
노출하지 않습니다. ARG는 `contains`, `attached_to`, `depends_on` 토폴로지를 제공합니다. Direct
ARM 대체 경로는 현재 `contains` 커버리지만 선언하므로 활성 프로젝션은 누락된 링크 종류를
보고하고 의존성 부재 결정에서 degraded 상태를 유지합니다.

## 실패 및 최신성 정책

- **Preflight 우선:** 예약을 활성화하기 전에 토큰 발급, DNS, TCP/TLS, 제한된 쿼리 하나, 페이지
  나누기, 비공개 프로젝션 쓰기 접근을 검증합니다.
- **실패 분류:** `network_blocked`, `dns_failed`, `token_failed`, `forbidden`, `throttled`,
  `partial`, `source_unavailable`을 구분합니다. Zero-row 결과를 오류 폴백으로 사용하지 않습니다.
- **마지막 정상 상태 유지:** 실패하거나 부분적인 스캔은 마지막 완전한 스냅샷을 유지하고 stale로
  표시합니다. 빈 그래프로 교체하지 않습니다.
- **권한 유지:** 오래된 시도, 같은 실행의 낮은 우선순위 출처 또는 `expected` declarative 후보는
  더 최신 관찰된 스냅샷을 교체할 수 없습니다.
- **자율성 저하:** 스냅샷 age가 설정된 최신성 예산을 초과하면 그래프 기반 영향 범위 결정과 부재
  주장을 사람 검토로 이동합니다. 읽기 전용 화면은 출처, age, 범위, degraded 상태를 표시하는
  경우 stale 그래프를 사용할 수 있습니다.
- **principal 분리 유지:** 발견 신원에는 선언된 범위의 최소 읽기 권한만 부여합니다. Privileged
  실행기, 콘솔 신원, 승인 principal과 분리합니다.
- **전환 감사:** 출처 선택, 대체 경로 활성화, 커버리지 손실, 복구, 스냅샷 승격은 구조화된 감사
  기록과 메트릭을 생성합니다.

예: NSG가 애플리케이션 서브넷에서 ARM으로 향하는 직접 egress를 거부합니다. Preflight는
`network_blocked`를 보고하고 예약된 스캔은 VNet 통합 ops 실행기로 이동합니다. ARG는 허브의
승인된 관리 경로를 통해 완료되고 최종 완전한 스냅샷만 승격됩니다. 실행기도 도달성을 잃으면
FDAI는 이전 그래프를 유지하고 stale로 표시하며 영향 범위 종속 작업을 사람 검토로 라우팅합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 프로바이더 중립 인벤토리 기록과 세대 규칙 | [CSP-중립성 계약](csp-neutrality-ko.md#5-인벤토리-계약---리소스-그래프) |
| 배포 연결 검사 | [네트워크 연결 매트릭스](../deployment/network-connectivity-matrix-ko.md) |
| 보호 배포 preflight | [배포 Preflight](../deployment/deployment-preflight-ko.md) |
