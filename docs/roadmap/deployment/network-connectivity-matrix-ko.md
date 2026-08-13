---
title: 네트워크 연결 매트릭스
translation_of: network-connectivity-matrix.md
translation_source_sha: aa6b5dac7d0de695caa20a6231b44f773b9ec27e
translation_revised: 2026-08-14
---
# 네트워크 연결 매트릭스

이 참조 문서는 공개, 비공개, provisioned-throughput, API 관리 및 완전 단절
네트워크 프로파일에서 FDAI를 Azure에서 실행하는 데 필요한 DNS, IP, 프로토콜 및 포트를
정의합니다. Firewall, NSG(네트워크 Security 그룹), 비공개 DNS 및 라우팅 정책을 구성하고
경로가 차단될 때 어떤 FDAI 기능이 사용할 수 없게 되는지 예측하는 데 사용하세요.

> **범위:** 이 문서의 값은 Azure 공개 Cloud를 대상으로 합니다. Azure Government와 Azure
> China는 다른 DNS 접미사 및 service-tag 주소 집합을 사용합니다. 접미사를 수동으로 변환하지
> 말고 최신 [Azure 비공개 엔드포인트 DNS 표](https://learn.microsoft.com/azure/private-link/private-endpoint-dns)에서
> 값을 확인하세요.
>
> **주소 규칙:** 공개 Azure 서비스 IP를 하드코딩하지 마세요. 비공개 엔드포인트 주소,
> 배포 출력, Azure 서비스 tag 또는 FQDN 애플리케이션 룰을 사용하세요. Microsoft는
> 서비스 tag 뒤의 공개 접두사를 갱신합니다. 비공개 엔드포인트 IP와 내부 API 관리
> virtual IP도 배포별로 다릅니다.

이 서비스 간 매트릭스의 실행 가능한 저장소 계약은
`tests/integration/scripts/test_check_network_connectivity.py`입니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| DNS, 주소 정책, TCP, 매니페스트 및 정보 제거 엔진 | implemented | `scripts/deployment/azure/network_connectivity.py` 및 `tests/integration/scripts/test_check_network_connectivity.py` | 집중 테스트는 엔드포인트 구문 분석, 프로파일 발견, 비공개/공개 주소 기대값, 필수/선택 실패, 조치 안내 및 정보 제거를 다룹니다. |
| 보호된 실행기 연결 게이트 | implemented | `.github/workflows/deploy-dev.yml` 및 네트워크 검사 계약 테스트 | 작업 흐름은 Terraform 출력을 `PREFLIGHT_NETWORK_CHECKS_JSON`과 조립하고 필수 실패를 차단하며, 임시 입력을 제거하고 정제된 리포트만 프리플라이트 근거에 연결합니다. |
| DNS, 프로토콜, 포트 및 실패 참조 매트릭스 | not-applicable | 이 문서의 표와 연결된 Azure 참조 | 설계 및 운영자 참조 자료이며 소스가 존재한다는 사실만으로 배포된 경로를 입증하지는 않습니다. |
| 런타임 서브넷, APIM, AMPLS 및 운영자 경로 근거 | not-started | 이 문서의 검증 검사 목록 | 실제 서브넷에서 모든 신원, DNS, TLS, APIM 헤더, 이미지 가져오기 및 실패 주입 검사를 입증하는 완전한 환경 중립 증적이 저장소에 없습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-14 | in-progress | 구현 원장을 도입했으며 이전 출처 이력은 재구성하지 않았습니다. 테스트된 엔드포인트 검사기와 배포별 네트워크 검증을 분리했습니다. | 현재 변경과 구현 범위 표에 기재한 집중 검사기 테스트 및 보호된 실행기 작업 흐름 근거 | 선택한 각 배포 프로파일에 대해 서브넷 수준의 정상 및 실패 연결 근거를 보존해야 합니다. |

### 남은 작업

- [ ] 실제 런타임, APIM 및 배포 호스트 서브넷에서 신원으로 인증된 DNS와 TLS 검사를 실행하고 모든 필수 경로의 정제된 통제 증적을 보존합니다.
- [ ] APIM PTU 및 강제 429 spillover 경로가 FDAI 근거 헤더 세 개를 모두 반환하며, 헤더가 없으면 실패 시 차단되는지 검증합니다.
- [ ] 승인된 검증 환경에서 각 필수 의존성을 차단하고 해당 기능이 실패 매트릭스에 지정된 그대로 저하됨을 입증하는 근거를 보존합니다.

## 한눈에 보는 설계

PTU(프로비저닝된 처리량 Units)는 Azure OpenAI 용량을 바꾸지만 네트워크 프로토콜은
바꾸지 않습니다. 따라서 Direct PTU와 Standard 배포는 동일한 Azure OpenAI hostname,
비공개 DNS 영역, Microsoft Entra authentication 경로 및 TCP 포트를 사용합니다. API
관리(APIM)는 별도 게이트웨이 홉과 자체 platform 의존성을 추가합니다.

| 프로파일 | 모델 경로 | 공개 internet egress | 지원 결과 |
|----------|-------------|------------------------|-----------|
| **완전 air 공백** | 자체 호스팅 어댑터가 제공될 때까지 없음 | 없음 | 결정론적 코어만 사용 가능, 실제 운영 Azure 근거와 cloud 액션 없음 |
| **비공개 Azure** | 비활성화 또는 비공개 Azure OpenAI | 승인된 Azure 컨트롤/신원 경로를 제외하고 없음 | 전체 결정론적 런타임, 모델 경로가 있을 때만 adaptive 기능 사용 가능 |
| **비공개 Azure + direct PTU** | FDAI -> 비공개 Azure OpenAI | 승인된 Azure 컨트롤/신원 경로 | 프로비저닝된 모델 용량을 사용하는 전체 런타임 |
| **비공개 Azure + APIM** | FDAI -> 비공개 APIM -> 비공개 PTU, 선택적 Standard spillover | APIM platform 경로와 승인된 Azure 컨트롤/신원 경로 | 두 홉과 APIM 근거 헤더가 모두 동작할 때 전체 런타임 |
| **공개 Azure** | 공개 Azure OpenAI 또는 공개 APIM | allow-list된 HTTPS egress | 비공개 엔드포인트 없이 전체 런타임, 서비스 firewall은 호출자를 계속 제한 |

"공개 internet 없음"은 "Azure 도달 가능성 없음"과 같지 않습니다. 비공개 Azure
배포도 해당 작업을 연결된 수집기로 옮기지 않는 한 Microsoft Entra 토큰 발급과
management-plane 경로가 필요합니다. 진정한 air 공백에는 둘 다 없으므로 실제 운영 cloud 관찰이나
cloud 변경을 주장할 수 없습니다.

## 공통 FDAI 런타임 경로

현재 Azure 기준선은 `Consumption` 워크로드 프로파일을 사용하는 workload-profile Container
Apps 환경입니다. 출처 포트는 일시적인입니다. Rule은 대상, 프로토콜 및
대상 포트를 제한하는 것이 좋습니다.

| 출발지 | 대상 또는 서비스 tag | 프로토콜과 포트 | FDAI에 필요한 이유 | 차단 시 결과 |
|--------|--------------------------------|-----------------|----------------------|--------------|
| Container Apps 서브넷 | Azure DNS `168.63.129.16` 또는 구성된 해석기 | UDP 및 TCP 53 | 공개 및 비공개 엔드포인트 이름 확인 | 개정 번호와 런타임 호출이 hostname 단계에서 실패하며 비공개 서비스가 공개 주소 또는 `NXDOMAIN`을 반환할 수 있음 |
| Container Apps platform | `MicrosoftContainerRegistry`, `AzureFrontDoor.FirstParty` | TCP 443 | system 이미지 및 Container Apps platform 산출물 | 환경 프로비저닝 또는 개정 번호 시작 실패 |
| FDAI 신원 | `AzureActiveDirectory`, `login.microsoftonline.com` 및 cloud별 login 호스트 | TCP 443 | 모든 RBAC 기반 서비스용 managed-identity 및 Entra 토큰 | Event Hubs, ARM, Azure OpenAI, Storage, ACR 및 Monitor 호출의 인증 상실 |
| FDAI 코어와 작업 | `<namespace>.servicebus.windows.net` | TCP 9093 | 필수 Event Hubs Kafka 전송 계층 | 이벤트 ingest, derived 이벤트 publish, canary 및 scheduled 생산자 중지 |
| FDAI 앱과 작업 | `<server>.postgres.database.azure.com` | TCP 5432 | 상태, 감사, 예약, 변환 결과 및 pgvector | 시작/준비 상태 실패 또는 관련 변환 결과 사용 불가 |
| FDAI 모델 클라이언트 | `<account>.openai.azure.com` | TCP 443 | direct Standard 또는 PTU inference, 임베딩, 서술기 및 managed 웹 검색 | adaptive 기능 사용 불가, 관련 작업은 deterministic-only 또는 사람 검토 필요 |
| Deploy 실행기 및 FDAI 웹 검색 클라이언트 | `<account>.services.ai.azure.com`, 비공개 모드에서는 `privatelink.services.ai.azure.com` | TCP 443 | deployment-owned Foundry 프롬프트 에이전트를 조정하고 호출하며 실제 도구 준비 상태 탐색 실행 | 에이전트 조정 또는 시작 준비 상태 실패, 웹 검색이 사용 불가 보고 |
| FDAI 모델 클라이언트 | 배포가 공급한 APIM 게이트웨이 FQDN | TCP 443 | APIM을 통한 PTU 또는 Standard inference | 게이트웨이 경로 기능 사용 불가 |
| FDAI 저장소 클라이언트 | `<account>.blob.core.windows.net` | TCP 443 | 사례 이력, 문서 블롭 및 배포 상태 | 관련 산출물, 재생 또는 배포 연산 실패 |
| FDAI 문서 클라이언트 | `<account>.dfs.core.windows.net` | TCP 443 | ADLS Gen2 이름 변경 및 hierarchical 이름 공간 연산 | 문서 인제스트가 격리 구역 내용을 통제된 저장소로 승격하지 못함 |
| Container Apps 시크릿 해석기와 deploy 호스트 | `<vault>.vault.azure.net` | TCP 443 | Container Apps Key Vault 참조 및 Terraform 시크릿 쓰기 | 새 개정 번호가 시크릿을 확인하지 못하고 deploy 시크릿 생성 실패 |
| Container Apps 이미지 pull | `<registry>.azurecr.io` 및 `<registry>.<region>.data.azurecr.io` | TCP 443 | 이미지 매니페스트 및 계층 download | 기존 개정 번호는 유지될 수 있지만 새 개정 번호는 image-pull 오류로 실패 |
| 인벤토리 및 액션 어댑터 | `management.azure.com` 또는 승인된 Resource Manager 비공개 링크 | TCP 443 | Resource Graph, ARM 읽기, what-if 및 통제된 액션 | 인벤토리가 stale 상태가 되고 cloud 액션 차단 |
| 텔레메트리 내보내기 도구 | Azure Monitor 인제스트 호스트 또는 AMPLS(Azure Monitor Private Link 범위) | TCP 443 | 로그, 메트릭, 추적 및 Application Insights | 컨트롤 결정은 계속되지만 텔레메트리와 operational 근거 사용 불가 |
| Operator 브라우저 | 콘솔 FQDN, Operator API FQDN 및 `login.microsoftonline.com` | TCP 443 | SPA 전달, 읽기 전용 근거 및 interactive Entra sign-in | 콘솔 또는 sign-in 사용 불가, headless 코어는 계속 동작 |
| 선택적 전달 어댑터 | 구성된 Teams, Slack, GitHub, 이메일, pager 또는 웹훅 FQDN | TCP 443 | 승인, 알림 및 교정 pull 요청 | 채널 큐 또는 장애 조치, 승인 요구사항은 우회하지 않음 |

HTTP 유입을 사용하는 내부 Container Apps 환경에서는 승인된 클라이언트에서
환경의 TCP 443 및 platform 내부 HTTPS 간선 포트 31443도 허용하세요. TCP
30000-32767에서 할당된 포트로 향하는 Azure Load Balancer 탐색도 허용하세요. FDAI 코어
자체에는 공개 인바운드 엔드포인트가 없습니다. 이 룰은 활성화된 읽기, 인제스트 또는 명령
API에 적용됩니다.

Closed-network 콘솔에는 SPA와 Operator API의 비공개 유입, 운영자에서 오는 VPN 또는
ExpressRoute 라우팅, 브라우저 호스트 operating system에서 볼 수 있는 비공개 DNS도 필요합니다.
현재 루트 Terraform은 Static Web Apps 비공개 엔드포인트를 provision하지 않습니다. 추가
deployment-owned 경로가 없으면 코어는 비공개로 실행되지만 콘솔에는 접근할 수 없습니다.

이전 방식 Consumption-only Container Apps 환경에는 더 넓은 platform 계약이 있습니다.
`AzureCloud.<region>`에 UDP 1194 및 TCP 9000, `AzureCloud`에 TCP 443,
`EventHub.<region>`에 TCP 5671-5672, NTP에 UDP 123이 필요합니다. 배포된 환경 타입이
요구하지 않으면 이 룰을 현재 workload-profile 기준선에 복사하지 마세요. 최신
[Container Apps NSG 표](https://learn.microsoft.com/azure/container-apps/firewall-integration)를
기준으로 사용하세요.

## 비공개 DNS 영역

애플리케이션은 계속 공개 서비스 FQDN을 사용합니다. Azure DNS는 연결된 비공개 영역의
CNAME을 따라 비공개 엔드포인트 주소를 반환합니다. 조회를 수행하는 모든 VNet, 피어링된
deploy-runner VNet, VPN DNS 해석기 및 on-premises conditional forwarder가 같은 기록에
도달할 수 있어야 합니다.

| FDAI 서비스 | 조회 접미사 | 비공개 DNS 영역 | 포트 | 현재 `infra/`가 provision |
|--------------|--------------|------------------|------|---------------------------|
| Key Vault | `vault.azure.net`, `vaultcore.azure.net`을 통한 CNAME chase 포함 | `privatelink.vaultcore.azure.net` | TCP 443 | 비공개 모드에서 예 |
| Event Hubs, 두 샤드 | `servicebus.windows.net` | `privatelink.servicebus.windows.net` | TCP 9093 | 비공개 모드에서 예 |
| PostgreSQL Flexible Server | `postgres.database.azure.com` | `privatelink.postgres.database.azure.com` | TCP 5432 | 비공개 모드에서 예 |
| Azure OpenAI, Standard 또는 PTU | `openai.azure.com` | `privatelink.openai.azure.com` | TCP 443 | LLM 및 비공개 모드 활성화 시 예 |
| ACR login 및 regional 데이터 기록 | `azurecr.io`, `<region>.data.azurecr.io` | `privatelink.azurecr.io` | TCP 443 | 비공개 모드의 Premium ACR에서 예 |
| Blob, 상태, 문서 및 사례 | `blob.core.windows.net` | `privatelink.blob.core.windows.net` | TCP 443 | 활성화된 각 저장소 경로에서 예 |
| ADLS Gen2 문서 | `dfs.core.windows.net` | `privatelink.dfs.core.windows.net` | TCP 443 | 문서 인제스트 및 비공개 모드 활성화 시 예 |
| Container Apps 비공개 유입 | `azurecontainerapps.io` | `privatelink.<region>.azurecontainerapps.io` | TCP 443 | 현재 루트 모듈에는 없음 |
| APIM 비공개 엔드포인트 게이트웨이 | `azure-api.net` | `privatelink.azure-api.net` | TCP 443 | 기존 APIM 소유자가 공급 |
| Azure Monitor | Monitor, OMS, ODS, 자동화 및 Blob 접미사 | 아래 5개 AMPLS 영역 | TCP 443 | 현재 루트 모듈에는 없음 |
| Azure Resource Manager | `management.azure.com` | `privatelink.azure.com` | TCP 443 | 현재 루트 모듈에는 없음 |
| Static Web Apps 비공개 유입 | `azurestaticapps.net` 및 파티션 접미사 | `privatelink.azurestaticapps.net` 및 파티션 영역 | TCP 443 | 현재 루트 모듈에는 없음 |

AMPLS에는 `privatelink.monitor.azure.com`, `privatelink.oms.opinsights.azure.com`,
`privatelink.ods.opinsights.azure.com`, `privatelink.agentsvc.azure-automation.net`,
`privatelink.blob.core.windows.net`의 5개 linked 영역이 모두 필요합니다. 하나만 누락되어도
인제스트는 동작하지만 조회, 실제 운영 메트릭 또는 에이전트 구성이 실패할 수 있습니다.

ACR 비공개 엔드포인트 하나는 레지스트리 주소와 복제본별 데이터 주소 하나를 할당합니다. 두 기록
모두 `privatelink.azurecr.io`에 속합니다. 별도
`<region>.data.privatelink.azurecr.io` 영역을 만들지 마세요. 이미지 pull에 사용되는 모든
복제본 데이터 엔드포인트를 허용하세요.

VNet이 같은 Azure 서비스 타입의 비공개 및 공개 리소스를 모두 사용해야 한다면 비공개
DNS 링크에 fallback-to-public 해석을 적용하세요. 요청된 A 기록이 없는 비공개 영역은
`NXDOMAIN`을 반환할 수 있습니다. Azure가 주소를 바꿀 수 있으므로 공개 A 기록을 수동으로
고정하는 방식은 안전하지 않습니다.
각 CNAME 뒤에 라우팅을 다시 평가하는 VPN split-DNS 클라이언트는 공개 조회 접미사와 CNAME
대상 접미사를 모두 경로해야 합니다. 예를 들어 Key Vault에는 `vault.azure.net`과
`vaultcore.azure.net`이 모두 필요합니다.

## 모델 라우팅 시나리오

### Direct Standard 또는 PTU

FDAI는 `<account>.openai.azure.com`을 확인하고 Entra 토큰으로 TCP 443을 호출합니다. 비공개
모드에서는 이름이 `privatelink.openai.azure.com`을 통해 엔드포인트 비공개 IP로 확인되어야
합니다. 토큰 경로에는 여전히 TCP 443의 `AzureActiveDirectory`가 필요합니다. PTU는 포트,
DNS 영역 또는 두 번째 엔드포인트를 추가하지 않습니다.

### APIM을 통한 PTU 및 Standard spillover

완전한 비공개 흐름은 다음과 같습니다.

```text
FDAI subnet -> APIM private VIP:443 -> Azure OpenAI private endpoint:443
             -> PTU first; one same-family Standard retry only after HTTP 429
```

- **첫 번째 홉:** FDAI는 배포가 공급한 APIM 게이트웨이 FQDN을 APIM 비공개 엔드포인트 또는
  내부 VNet-injection VIP로 확인하고 TCP 443을 호출합니다.
- **두 번째 홉:** APIM에는 아웃바운드 VNet 통합 또는 주입, 두 Azure OpenAI 계정의
  비공개 DNS 해석, 두 비공개 엔드포인트에 대한 TCP 443이 필요합니다. APIM managed
  신원에는 두 백엔드의 `Cognitive Services OpenAI User`가 필요합니다.
- **비공개 엔드포인트는 인바운드 전용:** APIM 앞에 비공개 엔드포인트를 배치해도 APIM에서 Azure
  OpenAI로 가는 트래픽이 자동으로 비공개가 되지 않습니다. 두 번째 홉을 명시적으로
  구성하세요.
- **근거 계약:** APIM은 `x-fdai-model-backend`, `x-fdai-capacity-unit`,
  `x-fdai-spillover`를 반환해야 합니다. FDAI는 이 값이 없거나 잘못된 경우 성공한 T2
  응답도 수락하지 않습니다.

Premium v2 VNet 주입에서는 APIM 아웃바운드에서 `Storage` 및 `AzureKeyVault` 서비스 tag로
TCP 443, 두 모델 백엔드로 TCP 443, 구성된 해석기로 DNS를 허용하세요. Classic
Developer/Premium VNet 주입의 platform 계약에는 인바운드 `ApiManagement` TCP 3443,
인바운드 `AzureLoadBalancer` TCP 6390, 아웃바운드 `Storage` TCP 443, `Sql` TCP 1433,
`AzureKeyVault` TCP 443, `AzureMonitor` TCP 1886 및 443, DNS TCP/UDP 53, NTP UDP 123,
certificate 검증용 TCP 80/443도 포함됩니다. 배포된 APIM 계층의 최신 표를 적용하세요.
이 platform 포트를 FDAI 애플리케이션 포트로 취급하지 마세요.

### 공개 모델 또는 공개 APIM

동일한 TCP 443 애플리케이션 경로를 사용하지만 공개 DNS가 서비스 주소를 반환하고 각 서비스
firewall이 FDAI egress 출처를 허용해야 합니다. Container Apps 환경에 안정적인 NAT
또는 firewall egress IP를 부여한 후 IP allow-list에 추가하세요. 서비스 firewall 또는 신원
컨트롤이 없는 unrestricted 공개 엔드포인트는 운영 프로파일로 적합하지 않습니다.

## 배포 및 운영자 경로

런타임 allow 룰만으로는 배포 호스트가 동작하지 않습니다. VNet 실행기 또는 jumpbox에는
다음 추가 경로가 필요합니다.

| 대상 | 프로토콜과 포트 | 목적 | Closed-network 대안 |
|-------------|-----------------|------|---------------------|
| DNS 해석기 | UDP 및 TCP 53 | 컨트롤, 데이터 및 비공개 엔드포인트 이름 확인 | conditional forwarding을 사용하는 비공개 해석기 |
| Azure 인스턴스 메타데이터 서비스 `169.254.169.254` | TCP 80 | 실행기 VM managed-identity 토큰 초기화 | Azure VM에는 대안 없음, link-local 트래픽은 Azure 내부 유지 |
| `login.microsoftonline.com` 및 필요한 테넌트/federation 호스트 | TCP 443 | Azure CLI 및 Terraform 토큰 획득 | 승인된 Entra 경로, Entra에는 테넌트 비공개 엔드포인트 equivalent가 없음 |
| `management.azure.com` | TCP 443 | Terraform 및 Azure CLI 컨트롤 플레인 | 현재 제한을 수용할 수 있을 때 Resource Manager 비공개 링크 |
| 상태 Blob, Key Vault, ACR login/데이터 | TCP 443 | Terraform 상태, 시크릿 쓰기, 이미지 push/pull | 위의 비공개 엔드포인트 및 영역 |
| GitHub 실행기 엔드포인트 | TCP 443 | 체크아웃, Actions 브로커, API, 산출물 및 release | 수동 jumpbox 전송 계층 또는 내부 출처/산출물 mirror |
| Terraform 레지스트리, Python 인덱스, base-image 레지스트리 | TCP 443 | 최초 도구 및 의존성 획득 | signed offline 키트 및 내부 mirror |

Connected GitHub 실행기에는 일반적으로 최소한 `github.com`, `api.github.com`,
`*.actions.githubusercontent.com`, `objects.githubusercontent.com` 및 저장소가 선택한 release와
패키지 호스트의 TCP 443이 필요합니다. GitHub는 공개 allow 목록을 변경합니다. FDAI 문서에 IP를
고정하지 말고 GitHub의 최신 실행기 communication 참조 또는 수동 전송 계층을 사용하세요.
Resource Manager 비공개 링크는 루트 management-group association에서 테넌트 전체에 적용되며
AKS를 포함한 모든 리소스 프로바이더를 지원하지는 않습니다. 이 경로만 관리 경로로
사용하기 전에 FDAI의 정확한 인벤토리 및 액션 집합을 검증하세요.

## 실패 및 기능 저하 매트릭스

| 차단된 경로 | 관찰 가능한 실패 | FDAI 동작 |
|-------------|------------------|-----------|
| DNS 53 또는 잘못된 private-zone 링크 | 시간 초과, 공개 IP 또는 `NXDOMAIN` | 필수 서비스의 시작/준비 상태 실패, 승인되지 않은 공개 엔드포인트로 대체 경로하지 않음 |
| Entra 443 | 토큰 시간 초과, `401` 또는 자격 증명 사용 불가 | 영향을 받는 모든 RBAC 기반 어댑터가 실패 시 차단 |
| Event Hubs 9093 | Kafka 연결 시간 초과 | 통제된 ingest 또는 게시 없음, 코어는 healthy 이벤트 처리를 주장할 수 없음 |
| PostgreSQL 5432 | 연결 시간 초과 | 영속 상태, 감사, 예약 및 변환 결과 사용 불가, 자율 작업 중지 |
| Azure OpenAI 또는 APIM 443 | 모델 시간 초과 또는 사용 불가 연결 | 결정론적 경로 계속, T1/T2, 서술기 및 managed 웹 검색은 사용 불가 또는 사람 검토 필요 |
| APIM 근거 헤더 | 잘못된 게이트웨이 근거를 포함한 HTTP 성공 | T2 결과를 거부하고 감사, direct-endpoint 대체 경로 없음 |
| ACR login 또는 데이터 443 | 매니페스트 또는 계층 pull 시간 초과 | 새 Container Apps 개정 번호 실패, 이미 실행 중인 개정 번호는 계속될 수 있음 |
| Key Vault 443 | Container Apps 시크릿 해석 또는 Terraform 403/시간 초과 | 개정 번호 활성화 또는 배포 실패, 시크릿 값 대체 경로 없음 |
| ARM/Resource Graph 443 | 인벤토리 조회 시간 초과 | 마지막 완전한 인벤토리를 stale 상태로 유지, evidence-dependent 액션 차단 |
| Blob/DFS 443 | 업로드, 이름 변경, 재생 또는 상태 실패 | 관련 문서, case-history 또는 배포 작업 흐름만 중지, 근거를 생성하지 않음 |
| Azure Monitor 443 | 텔레메트리 누락 | 런타임 결정은 계속되지만 상태와 observability를 사용 불가로 표시 |
| Approval/전달 호스트 443 | 채널 전달 실패 | 큐 또는 구성된 대체 경로 채널 사용, 자동 승인하지 않음 |
| Container Apps platform tag | 개정 번호 stuck 또는 환경 unhealthy | FDAI 엔드포인트가 열려 있어도 platform이 워크로드를 시작하거나 관리하지 못함 |
| APIM platform 포트 | APIM 배포, 상태, 관리 또는 게이트웨이 실패 | 모든 APIM 경로 모델 기능 사용 불가 |

## 자동 연결 검사

실제 워크로드가 있는 네트워크에서 검사기를 실행하세요. 알려진 환경 variable에서 기본
및 auxiliary Kafka 엔드포인트, PostgreSQL, Azure OpenAI, Prometheus, 이메일, 개발 게이트웨이를
찾습니다. 그런 다음 각 DNS 이름을 확인하고 resolved 주소 등급을 검증하며 구성된 TCP 포트를
연 뒤 필요한 조치를 출력합니다.

```bash
python3 scripts/deployment/azure/check-network-connectivity.py \
   --profile runtime-private \
   --env-file .fdai/local-runtime.env \
   --output tmp/network-connectivity.json
```

공개 런타임 네트워크에서는 `runtime-public`, 배포 호스트에서는 `deploy-runner`를 사용하세요.
환경 variable로 표현되지 않는 APIM, ACR 데이터 엔드포인트, 저장소, Key Vault 또는
배포별 경로에는 `custom`과 하나 이상의 매니페스트를 사용하세요.

환경에서 찾은 엔드포인트 값은 출처 또는 `host:port` 형식이어야 합니다. 마지막 루트 `/`는
허용하지만, 루트가 아닌 경로, 조회, 조각 또는 user information은 잘못된 입력입니다. 검사기는
DNS와 TCP 도달 가능성만 검사하므로 다른 대상을 조용히 검사해서는 안 됩니다. 명시적 포트는
`[1, 65535]` 범위여야 합니다. 빈 포트 또는 포트 `0`은 잘못된 입력이며 프로파일 기본값으로
대체하지 않습니다. 잘못된 URL은 exit 코드 `2`의 잘못된 입력으로 보고하며 파서 세부 정보가
처리되지 않은 실패로 노출되지 않습니다.

```json
{
   "schema_version": "fdai.network-connectivity-manifest.v1",
   "checks": [
      {"id": "apim-model-gateway", "host": "replace.example.com", "port": 443,
       "required": true, "expected_ip": "private"}
   ]
}
```

`--manifest <path>`로 파일을 전달하세요. 각 검사의 `expected_ip`에는 `private`, `public`, `any`를
사용할 수 있습니다. 필수 검사가 실패하면 명령은 `1`, 입력이 잘못되면 `2`로 종료합니다.
선택적 실패는 경고를 만들고 `0`으로 종료합니다. 일반 보고에는 실제 hostname과 resolved
주소가 있으므로 `tmp/` 같은 ignore된 로컬 저장소에 보관하세요. 보고를 공유하기 전에는
`--redact`를 추가하세요. 호스트는 해시로 바뀌고 주소는 제거됩니다.

액션 요약은 누락된 구성, DNS/private-zone 오류, 잘못된 공개 또는 비공개 주소
해석, 차단된 TCP 포트를 구분합니다.

Protected 계획은 Terraform 계획 수립 전에 VNet 배포 실행기에서 검사기를 자동으로
실행합니다. `PREFLIGHT_EGRESS_HOSTS_JSON`은 기존 TLS 검사를 계속 제어합니다. 작업 흐름은 기존
Terraform 출력에서 두 Event Hubs 샤드, PostgreSQL, Key Vault, ACR 및 Azure OpenAI를 자동으로
읽고 프로파일의 비공개 또는 공개 주소 expectation을 적용합니다. APIM 백엔드 또는 ACR
복제본 데이터 엔드포인트 같은 추가 경로에는 선택적 저장소 variable
`PREFLIGHT_NETWORK_CHECKS_JSON`에 완전한 매니페스트를 설정하세요. 작업 흐름은 모든 입력을
결합하고 필수 실패 시 차단하며 temporary 매니페스트를 제거합니다. 기존
`preflight-evidence.json` 다이제스트 계약에는 민감정보가 제거된 네트워크 보고만 병합합니다. 최초
배포에서는 아직 존재하지 않는 Terraform 출력을 건너뜁니다.

긍정 엔드포인트 검사기로 full air 공백을 증명할 수는 없습니다. 경로와 DNS가 없는
이름 공간에서 network-free release 경로를 검증하려면
`bash scripts/deployment/release/airgap-drill.sh`를 사용하세요.

## 검증 체크리스트

실제 Container Apps 서브넷, APIM 서브넷 및 deploy-host 서브넷에서 탐색을 실행하세요. Laptop
결과는 이러한 실행 경로를 증명하지 않습니다.

1. 모든 공개 조회 FQDN을 확인하고 비공개 프로파일에서 의도한 비공개 엔드포인트 또는
   내부 VIP 서브넷의 주소를 반환하는지 확인합니다.
2. 해당하는 포트 443, 9093 및 5432에 범위가 제한된 TCP 연결을 엽니다. 비공개 엔드포인트가
   ICMP에 응답하지 않을 수 있으므로 TLS 또는 프로토콜 authentication 오류가 ping보다 더
   유효한 증거입니다.
3. 정확한 워크로드 신원으로 Entra 토큰을 획득한 다음 서비스별 읽기 전용 요청 하나를
   수행합니다.
4. Pinned 이미지 다이제스트를 pull하여 ACR login과 데이터 엔드포인트를 모두 검증합니다.
5. APIM 모델 경로를 호출하고 PTU 및 forced-429 spillover 경로에서 FDAI 근거 헤더 3개를
   모두 검증합니다.
6. 의존성을 한 번에 하나씩 차단하고 stale 근거 및 direct-endpoint 대체 경로 없음까지
   실패 매트릭스의 해당 행과 일치하는지 확인합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| FDAI 비공개 엔드포인트, VNet 실행기 및 배포 인벤토리 | [배포 및 온보딩](deploy-and-onboard-ko.md) |
| 공개 egress 없음 및 full-air-gap 동작 | [단절 환경 배포](disconnected-deployment-ko.md) |
| Direct, APIM, PTU 및 mixed-model 연결 계약 | [LLM 전략](../architecture/llm-strategy-ko.md) |
| Azure 비공개 엔드포인트 DNS 접미사 | [Azure Private Endpoint DNS](https://learn.microsoft.com/azure/private-link/private-endpoint-dns) |
| Container Apps platform NSG 룰 | [Container Apps NSG 참조](https://learn.microsoft.com/azure/container-apps/firewall-integration) |
| APIM classic VNet platform 포트 | [APIM VNet 참조](https://learn.microsoft.com/azure/api-management/virtual-network-reference) |
| APIM Premium v2 VNet 주입 | [Inject APIM Premium v2](https://learn.microsoft.com/azure/api-management/inject-vnet-v2) |
| Event Hubs 프로토콜 포트 | [Event Hubs connectivity 문제 해결](https://learn.microsoft.com/azure/event-hubs/troubleshooting-guide#troubleshoot-permanent-connectivity-issues) |
