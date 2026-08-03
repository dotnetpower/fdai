---
title: 네트워크 연결 매트릭스
translation_of: network-connectivity-matrix.md
translation_source_sha: 338997ab719a8cf218613be027e7b29a9b843b26
translation_revised: 2026-08-03
---
# 네트워크 연결 매트릭스

이 참조 문서는 public, private, provisioned-throughput, API Management 및 완전 단절
네트워크 프로파일에서 FDAI를 Azure에서 실행하는 데 필요한 DNS, IP, protocol 및 port를
정의합니다. Firewall, NSG(Network Security Group), Private DNS 및 routing policy를 구성하고
경로가 차단될 때 어떤 FDAI 기능이 사용할 수 없게 되는지 예측하는 데 사용하세요.

> **범위:** 이 문서의 값은 Azure Public Cloud를 대상으로 합니다. Azure Government와 Azure
> China는 다른 DNS suffix 및 service-tag 주소 집합을 사용합니다. Suffix를 수동으로 변환하지
> 말고 최신 [Azure private endpoint DNS 표](https://learn.microsoft.com/azure/private-link/private-endpoint-dns)에서
> 값을 확인하세요.
>
> **주소 규칙:** Public Azure service IP를 하드코딩하지 마세요. Private endpoint 주소,
> deployment output, Azure service tag 또는 FQDN application rule을 사용하세요. Microsoft는
> service tag 뒤의 public prefix를 갱신합니다. Private endpoint IP와 internal API Management
> virtual IP도 deployment별로 다릅니다.

## 한눈에 보는 설계

PTU(Provisioned Throughput Units)는 Azure OpenAI capacity를 바꾸지만 network protocol은
바꾸지 않습니다. 따라서 Direct PTU와 Standard deployment는 동일한 Azure OpenAI hostname,
Private DNS zone, Microsoft Entra authentication 경로 및 TCP port를 사용합니다. API
Management(APIM)는 별도 gateway hop과 자체 platform dependency를 추가합니다.

| 프로파일 | Model route | Public internet egress | 지원 결과 |
|----------|-------------|------------------------|-----------|
| **완전 air gap** | self-hosted adapter가 제공될 때까지 없음 | 없음 | deterministic core만 사용 가능, live Azure evidence와 cloud action 없음 |
| **Private Azure** | 비활성화 또는 private Azure OpenAI | 승인된 Azure control/identity route를 제외하고 없음 | 전체 deterministic runtime, model route가 있을 때만 adaptive 기능 사용 가능 |
| **Private Azure + direct PTU** | FDAI -> private Azure OpenAI | 승인된 Azure control/identity route | provisioned model capacity를 사용하는 전체 runtime |
| **Private Azure + APIM** | FDAI -> private APIM -> private PTU, 선택적 Standard spillover | APIM platform route와 승인된 Azure control/identity route | 두 hop과 APIM evidence header가 모두 동작할 때 전체 runtime |
| **Public Azure** | public Azure OpenAI 또는 public APIM | allow-list된 HTTPS egress | private endpoint 없이 전체 runtime, service firewall은 caller를 계속 제한 |

"Public internet 없음"은 "Azure reachability 없음"과 같지 않습니다. Private Azure
deployment도 해당 작업을 연결된 collector로 옮기지 않는 한 Microsoft Entra token 발급과
management-plane route가 필요합니다. 진정한 air gap에는 둘 다 없으므로 live cloud 관찰이나
cloud mutation을 주장할 수 없습니다.

## 공통 FDAI runtime 경로

현재 Azure baseline은 `Consumption` workload profile을 사용하는 workload-profile Container
Apps environment입니다. Source port는 ephemeral입니다. Rule은 destination, protocol 및
destination port를 제한하는 것이 좋습니다.

| 출발지 | Destination 또는 service tag | Protocol과 port | FDAI에 필요한 이유 | 차단 시 결과 |
|--------|--------------------------------|-----------------|----------------------|--------------|
| Container Apps subnet | Azure DNS `168.63.129.16` 또는 구성된 resolver | UDP 및 TCP 53 | public 및 private endpoint 이름 확인 | revision과 runtime 호출이 hostname 단계에서 실패하며 private service가 public 주소 또는 `NXDOMAIN`을 반환할 수 있음 |
| Container Apps platform | `MicrosoftContainerRegistry`, `AzureFrontDoor.FirstParty` | TCP 443 | system image 및 Container Apps platform artifact | environment provisioning 또는 revision 시작 실패 |
| FDAI identity | `AzureActiveDirectory`, `login.microsoftonline.com` 및 cloud별 login host | TCP 443 | 모든 RBAC 기반 service용 managed-identity 및 Entra token | Event Hubs, ARM, Azure OpenAI, Storage, ACR 및 Monitor 호출의 인증 상실 |
| FDAI core와 job | `<namespace>.servicebus.windows.net` | TCP 9093 | 필수 Event Hubs Kafka transport | event ingest, derived event publish, canary 및 scheduled producer 중지 |
| FDAI app과 job | `<server>.postgres.database.azure.com` | TCP 5432 | state, audit, schedule, projection 및 pgvector | startup/readiness 실패 또는 관련 projection 사용 불가 |
| FDAI model client | `<account>.openai.azure.com` | TCP 443 | direct Standard 또는 PTU inference, embedding, narrator 및 managed web search | adaptive 기능 사용 불가, 관련 작업은 deterministic-only 또는 사람 검토 필요 |
| Deploy runner 및 FDAI web-search client | `<account>.services.ai.azure.com`, private mode에서는 `privatelink.services.ai.azure.com` | TCP 443 | deployment-owned Foundry prompt agent를 reconcile하고 호출하며 실제 tool readiness probe 실행 | Agent reconcile 또는 startup readiness 실패, web search가 unavailable 보고 |
| FDAI model client | deployment가 공급한 APIM gateway FQDN | TCP 443 | APIM을 통한 PTU 또는 Standard inference | gateway route 기능 사용 불가 |
| FDAI storage client | `<account>.blob.core.windows.net` | TCP 443 | case history, document blob 및 deployment state | 관련 artifact, replay 또는 deployment operation 실패 |
| FDAI document client | `<account>.dfs.core.windows.net` | TCP 443 | ADLS Gen2 rename 및 hierarchical namespace operation | document ingestion이 quarantine content를 governed storage로 승격하지 못함 |
| Container Apps secret resolver와 deploy host | `<vault>.vault.azure.net` | TCP 443 | Container Apps Key Vault reference 및 Terraform secret write | 새 revision이 secret을 확인하지 못하고 deploy secret 생성 실패 |
| Container Apps image pull | `<registry>.azurecr.io` 및 `<registry>.<region>.data.azurecr.io` | TCP 443 | image manifest 및 layer download | 기존 revision은 유지될 수 있지만 새 revision은 image-pull 오류로 실패 |
| Inventory 및 action adapter | `management.azure.com` 또는 승인된 Resource Manager private link | TCP 443 | Resource Graph, ARM read, what-if 및 governed action | inventory가 stale 상태가 되고 cloud action 차단 |
| Telemetry exporter | Azure Monitor ingestion host 또는 AMPLS(Azure Monitor Private Link Scope) | TCP 443 | log, metric, trace 및 Application Insights | control decision은 계속되지만 telemetry와 operational evidence 사용 불가 |
| Operator browser | console FQDN, Operator API FQDN 및 `login.microsoftonline.com` | TCP 443 | SPA delivery, read-only evidence 및 interactive Entra sign-in | console 또는 sign-in 사용 불가, headless core는 계속 동작 |
| 선택적 delivery adapter | 구성된 Teams, Slack, GitHub, email, pager 또는 webhook FQDN | TCP 443 | approval, notification 및 remediation pull request | channel queue 또는 failover, approval 요구사항은 우회하지 않음 |

HTTP ingress를 사용하는 internal Container Apps environment에서는 승인된 client에서
environment의 TCP 443 및 platform internal HTTPS edge port 31443도 허용하세요. TCP
30000-32767에서 할당된 port로 향하는 Azure Load Balancer probe도 허용하세요. FDAI core
자체에는 public inbound endpoint가 없습니다. 이 rule은 활성화된 read, ingestion 또는 command
API에 적용됩니다.

Closed-network console에는 SPA와 Operator API의 private ingress, operator에서 오는 VPN 또는
ExpressRoute routing, browser host operating system에서 볼 수 있는 Private DNS도 필요합니다.
현재 root Terraform은 Static Web Apps private endpoint를 provision하지 않습니다. 추가
deployment-owned 경로가 없으면 core는 private으로 실행되지만 console에는 접근할 수 없습니다.

Legacy Consumption-only Container Apps environment에는 더 넓은 platform contract가 있습니다.
`AzureCloud.<region>`에 UDP 1194 및 TCP 9000, `AzureCloud`에 TCP 443,
`EventHub.<region>`에 TCP 5671-5672, NTP에 UDP 123이 필요합니다. 배포된 environment type이
요구하지 않으면 이 rule을 현재 workload-profile baseline에 복사하지 마세요. 최신
[Container Apps NSG 표](https://learn.microsoft.com/azure/container-apps/firewall-integration)를
기준으로 사용하세요.

## Private DNS zone

Application은 계속 public service FQDN을 사용합니다. Azure DNS는 연결된 private zone의
CNAME을 따라 private endpoint 주소를 반환합니다. Query를 수행하는 모든 VNet, peering된
deploy-runner VNet, VPN DNS resolver 및 on-premises conditional forwarder가 같은 record에
도달할 수 있어야 합니다.

| FDAI service | Query suffix | Private DNS zone | Port | 현재 `infra/`가 provision |
|--------------|--------------|------------------|------|---------------------------|
| Key Vault | `vault.azure.net`, `vaultcore.azure.net`을 통한 CNAME chase 포함 | `privatelink.vaultcore.azure.net` | TCP 443 | private mode에서 예 |
| Event Hubs, 두 shard | `servicebus.windows.net` | `privatelink.servicebus.windows.net` | TCP 9093 | private mode에서 예 |
| PostgreSQL Flexible Server | `postgres.database.azure.com` | `privatelink.postgres.database.azure.com` | TCP 5432 | private mode에서 예 |
| Azure OpenAI, Standard 또는 PTU | `openai.azure.com` | `privatelink.openai.azure.com` | TCP 443 | LLM 및 private mode 활성화 시 예 |
| ACR login 및 regional data record | `azurecr.io`, `<region>.data.azurecr.io` | `privatelink.azurecr.io` | TCP 443 | private mode의 Premium ACR에서 예 |
| Blob, state, document 및 case | `blob.core.windows.net` | `privatelink.blob.core.windows.net` | TCP 443 | 활성화된 각 storage 경로에서 예 |
| ADLS Gen2 document | `dfs.core.windows.net` | `privatelink.dfs.core.windows.net` | TCP 443 | document ingestion 및 private mode 활성화 시 예 |
| Container Apps private ingress | `azurecontainerapps.io` | `privatelink.<region>.azurecontainerapps.io` | TCP 443 | 현재 root module에는 없음 |
| APIM private endpoint gateway | `azure-api.net` | `privatelink.azure-api.net` | TCP 443 | 기존 APIM owner가 공급 |
| Azure Monitor | Monitor, OMS, ODS, automation 및 Blob suffix | 아래 5개 AMPLS zone | TCP 443 | 현재 root module에는 없음 |
| Azure Resource Manager | `management.azure.com` | `privatelink.azure.com` | TCP 443 | 현재 root module에는 없음 |
| Static Web Apps private ingress | `azurestaticapps.net` 및 partition suffix | `privatelink.azurestaticapps.net` 및 partition zone | TCP 443 | 현재 root module에는 없음 |

AMPLS에는 `privatelink.monitor.azure.com`, `privatelink.oms.opinsights.azure.com`,
`privatelink.ods.opinsights.azure.com`, `privatelink.agentsvc.azure-automation.net`,
`privatelink.blob.core.windows.net`의 5개 linked zone이 모두 필요합니다. 하나만 누락되어도
ingestion은 동작하지만 query, live metric 또는 agent configuration이 실패할 수 있습니다.

ACR private endpoint 하나는 registry 주소와 replica별 data 주소 하나를 할당합니다. 두 record
모두 `privatelink.azurecr.io`에 속합니다. 별도
`<region>.data.privatelink.azurecr.io` zone을 만들지 마세요. Image pull에 사용되는 모든
replica data endpoint를 허용하세요.

VNet이 같은 Azure service type의 private 및 public resource를 모두 사용해야 한다면 Private
DNS link에 fallback-to-public resolution을 적용하세요. 요청된 A record가 없는 private zone은
`NXDOMAIN`을 반환할 수 있습니다. Azure가 주소를 바꿀 수 있으므로 public A record를 수동으로
고정하는 방식은 안전하지 않습니다.
각 CNAME 뒤에 routing을 다시 평가하는 VPN split-DNS client는 public query suffix와 CNAME
target suffix를 모두 route해야 합니다. 예를 들어 Key Vault에는 `vault.azure.net`과
`vaultcore.azure.net`이 모두 필요합니다.

## Model routing scenario

### Direct Standard 또는 PTU

FDAI는 `<account>.openai.azure.com`을 확인하고 Entra token으로 TCP 443을 호출합니다. Private
mode에서는 이름이 `privatelink.openai.azure.com`을 통해 endpoint private IP로 확인되어야
합니다. Token 경로에는 여전히 TCP 443의 `AzureActiveDirectory`가 필요합니다. PTU는 port,
DNS zone 또는 두 번째 endpoint를 추가하지 않습니다.

### APIM을 통한 PTU 및 Standard spillover

완전한 private flow는 다음과 같습니다.

```text
FDAI subnet -> APIM private VIP:443 -> Azure OpenAI private endpoint:443
             -> PTU first; one same-family Standard retry only after HTTP 429
```

- **첫 번째 hop:** FDAI는 deployment가 공급한 APIM gateway FQDN을 APIM private endpoint 또는
  internal VNet-injection VIP로 확인하고 TCP 443을 호출합니다.
- **두 번째 hop:** APIM에는 outbound VNet integration 또는 injection, 두 Azure OpenAI account의
  Private DNS resolution, 두 private endpoint에 대한 TCP 443이 필요합니다. APIM managed
  identity에는 두 backend의 `Cognitive Services OpenAI User`가 필요합니다.
- **Private endpoint는 inbound 전용:** APIM 앞에 private endpoint를 배치해도 APIM에서 Azure
  OpenAI로 가는 traffic이 자동으로 private이 되지 않습니다. 두 번째 hop을 명시적으로
  구성하세요.
- **Evidence contract:** APIM은 `x-fdai-model-backend`, `x-fdai-capacity-unit`,
  `x-fdai-spillover`를 반환해야 합니다. FDAI는 이 값이 없거나 잘못된 경우 성공한 T2
  response도 수락하지 않습니다.

Premium v2 VNet injection에서는 APIM outbound에서 `Storage` 및 `AzureKeyVault` service tag로
TCP 443, 두 model backend로 TCP 443, 구성된 resolver로 DNS를 허용하세요. Classic
Developer/Premium VNet injection의 platform contract에는 inbound `ApiManagement` TCP 3443,
inbound `AzureLoadBalancer` TCP 6390, outbound `Storage` TCP 443, `Sql` TCP 1433,
`AzureKeyVault` TCP 443, `AzureMonitor` TCP 1886 및 443, DNS TCP/UDP 53, NTP UDP 123,
certificate validation용 TCP 80/443도 포함됩니다. 배포된 APIM tier의 최신 표를 적용하세요.
이 platform port를 FDAI application port로 취급하지 마세요.

### Public model 또는 public APIM

동일한 TCP 443 application 경로를 사용하지만 public DNS가 service 주소를 반환하고 각 service
firewall이 FDAI egress source를 허용해야 합니다. Container Apps environment에 안정적인 NAT
또는 firewall egress IP를 부여한 후 IP allow-list에 추가하세요. Service firewall 또는 identity
control이 없는 unrestricted public endpoint는 production profile로 적합하지 않습니다.

## Deployment 및 operator 경로

Runtime allow rule만으로는 deployment host가 동작하지 않습니다. VNet runner 또는 jumpbox에는
다음 추가 경로가 필요합니다.

| Destination | Protocol과 port | 목적 | Closed-network 대안 |
|-------------|-----------------|------|---------------------|
| DNS resolver | UDP 및 TCP 53 | control, data 및 private endpoint 이름 확인 | conditional forwarding을 사용하는 private resolver |
| Azure Instance Metadata Service `169.254.169.254` | TCP 80 | runner VM managed-identity token bootstrap | Azure VM에는 대안 없음, link-local traffic은 Azure 내부 유지 |
| `login.microsoftonline.com` 및 필요한 tenant/federation host | TCP 443 | Azure CLI 및 Terraform token 획득 | 승인된 Entra route, Entra에는 tenant private endpoint equivalent가 없음 |
| `management.azure.com` | TCP 443 | Terraform 및 Azure CLI control plane | 현재 제한을 수용할 수 있을 때 Resource Manager private link |
| state Blob, Key Vault, ACR login/data | TCP 443 | Terraform state, secret write, image push/pull | 위의 private endpoint 및 zone |
| GitHub runner endpoint | TCP 443 | checkout, Actions broker, API, artifact 및 release | manual jumpbox transport 또는 internal source/artifact mirror |
| Terraform registry, Python index, base-image registry | TCP 443 | 최초 tool 및 dependency 획득 | signed offline kit 및 internal mirror |

Connected GitHub runner에는 일반적으로 최소한 `github.com`, `api.github.com`,
`*.actions.githubusercontent.com`, `objects.githubusercontent.com` 및 repository가 선택한 release와
package host의 TCP 443이 필요합니다. GitHub는 공개 allow list를 변경합니다. FDAI 문서에 IP를
고정하지 말고 GitHub의 최신 runner communication reference 또는 manual transport를 사용하세요.
Resource Manager private link는 root management-group association에서 tenant 전체에 적용되며
AKS를 포함한 모든 resource provider를 지원하지는 않습니다. 이 경로만 management route로
사용하기 전에 FDAI의 정확한 inventory 및 action set을 검증하세요.

## 실패 및 기능 저하 매트릭스

| 차단된 경로 | 관찰 가능한 실패 | FDAI 동작 |
|-------------|------------------|-----------|
| DNS 53 또는 잘못된 private-zone link | timeout, public IP 또는 `NXDOMAIN` | 필수 service의 startup/readiness 실패, 승인되지 않은 public endpoint로 fallback하지 않음 |
| Entra 443 | token timeout, `401` 또는 credential unavailable | 영향을 받는 모든 RBAC 기반 adapter가 fail-closed |
| Event Hubs 9093 | Kafka connection timeout | governed ingest 또는 publication 없음, core는 healthy event processing을 주장할 수 없음 |
| PostgreSQL 5432 | connection timeout | durable state, audit, schedule 및 projection 사용 불가, autonomous work 중지 |
| Azure OpenAI 또는 APIM 443 | model timeout 또는 unavailable binding | deterministic 경로 계속, T1/T2, narrator 및 managed web search는 unavailable 또는 사람 검토 필요 |
| APIM evidence header | 잘못된 gateway evidence를 포함한 HTTP success | T2 result를 거부하고 audit, direct-endpoint fallback 없음 |
| ACR login 또는 data 443 | manifest 또는 layer pull timeout | 새 Container Apps revision 실패, 이미 실행 중인 revision은 계속될 수 있음 |
| Key Vault 443 | Container Apps secret resolution 또는 Terraform 403/timeout | revision 활성화 또는 deployment 실패, secret value fallback 없음 |
| ARM/Resource Graph 443 | inventory query timeout | 마지막 complete inventory를 stale 상태로 유지, evidence-dependent action 차단 |
| Blob/DFS 443 | upload, rename, replay 또는 state 실패 | 관련 document, case-history 또는 deployment workflow만 중지, evidence를 생성하지 않음 |
| Azure Monitor 443 | telemetry 누락 | runtime decision은 계속되지만 health와 observability를 unavailable로 표시 |
| Approval/delivery host 443 | channel delivery 실패 | queue 또는 구성된 fallback channel 사용, 자동 승인하지 않음 |
| Container Apps platform tag | revision stuck 또는 environment unhealthy | FDAI endpoint가 열려 있어도 platform이 workload를 시작하거나 관리하지 못함 |
| APIM platform port | APIM deployment, health, management 또는 gateway 실패 | 모든 APIM route model 기능 사용 불가 |

## 자동 연결 검사

실제 workload가 있는 network에서 checker를 실행하세요. 알려진 environment variable에서 primary
및 auxiliary Kafka endpoint, PostgreSQL, Azure OpenAI, Prometheus, email, development gateway를
찾습니다. 그런 다음 각 DNS 이름을 확인하고 resolved address class를 검증하며 구성된 TCP port를
연 뒤 필요한 조치를 출력합니다.

```bash
python3 scripts/deployment/azure/check-network-connectivity.py \
   --profile runtime-private \
   --env-file .fdai/local-runtime.env \
   --output tmp/network-connectivity.json
```

Public runtime network에서는 `runtime-public`, deployment host에서는 `deploy-runner`를 사용하세요.
Environment variable로 표현되지 않는 APIM, ACR data endpoint, storage, Key Vault 또는
deployment별 route에는 `custom`과 하나 이상의 manifest를 사용하세요.

Environment에서 찾은 endpoint 값은 origin 또는 `host:port` 형식이어야 합니다. 마지막 root `/`는
허용하지만, root가 아닌 path, query, fragment 또는 user information은 잘못된 입력입니다. Checker는
DNS와 TCP reachability만 검사하므로 다른 target을 조용히 검사해서는 안 됩니다.

```json
{
   "schema_version": "fdai.network-connectivity-manifest.v1",
   "checks": [
      {"id": "apim-model-gateway", "host": "replace.example.com", "port": 443,
       "required": true, "expected_ip": "private"}
   ]
}
```

`--manifest <path>`로 파일을 전달하세요. 각 check의 `expected_ip`에는 `private`, `public`, `any`를
사용할 수 있습니다. 필수 check가 실패하면 command는 `1`, input이 잘못되면 `2`로 종료합니다.
Optional 실패는 warning을 만들고 `0`으로 종료합니다. 일반 report에는 실제 hostname과 resolved
address가 있으므로 `tmp/` 같은 ignore된 local storage에 보관하세요. Report를 공유하기 전에는
`--redact`를 추가하세요. Host는 hash로 바뀌고 address는 제거됩니다.

Action summary는 누락된 configuration, DNS/private-zone 오류, 잘못된 public 또는 private address
resolution, 차단된 TCP port를 구분합니다.

Protected plan은 Terraform planning 전에 VNet deployment runner에서 checker를 자동으로
실행합니다. `PREFLIGHT_EGRESS_HOSTS_JSON`은 기존 TLS check를 계속 제어합니다. Workflow는 기존
Terraform output에서 두 Event Hubs shard, PostgreSQL, Key Vault, ACR 및 Azure OpenAI를 자동으로
읽고 profile의 private 또는 public address expectation을 적용합니다. APIM backend 또는 ACR
replica data endpoint 같은 추가 route에는 optional repository variable
`PREFLIGHT_NETWORK_CHECKS_JSON`에 complete manifest를 설정하세요. Workflow는 모든 input을
결합하고 required 실패 시 차단하며 temporary manifest를 제거합니다. 기존
`preflight-evidence.json` digest contract에는 redacted network report만 병합합니다. 최초
deployment에서는 아직 존재하지 않는 Terraform output을 건너뜁니다.

Positive endpoint checker로 full air gap을 증명할 수는 없습니다. Route와 DNS가 없는
namespace에서 network-free release 경로를 검증하려면
`bash scripts/deployment/release/airgap-drill.sh`를 사용하세요.

## 검증 체크리스트

실제 Container Apps subnet, APIM subnet 및 deploy-host subnet에서 probe를 실행하세요. Laptop
결과는 이러한 실행 경로를 증명하지 않습니다.

1. 모든 public query FQDN을 확인하고 private profile에서 의도한 private endpoint 또는
   internal VIP subnet의 주소를 반환하는지 확인합니다.
2. 해당하는 port 443, 9093 및 5432에 bounded TCP connection을 엽니다. Private endpoint가
   ICMP에 응답하지 않을 수 있으므로 TLS 또는 protocol authentication 오류가 ping보다 더
   유효한 증거입니다.
3. 정확한 workload identity로 Entra token을 획득한 다음 service별 read-only 요청 하나를
   수행합니다.
4. Pinned image digest를 pull하여 ACR login과 data endpoint를 모두 검증합니다.
5. APIM model route를 호출하고 PTU 및 forced-429 spillover 경로에서 FDAI evidence header 3개를
   모두 검증합니다.
6. Dependency를 한 번에 하나씩 차단하고 stale evidence 및 direct-endpoint fallback 없음까지
   실패 매트릭스의 해당 행과 일치하는지 확인합니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| FDAI private endpoint, VNet runner 및 deployment inventory | [배포 및 온보딩](deploy-and-onboard-ko.md) |
| Public egress 없음 및 full-air-gap 동작 | [단절 환경 배포](disconnected-deployment-ko.md) |
| Direct, APIM, PTU 및 mixed-model binding contract | [LLM 전략](../architecture/llm-strategy-ko.md) |
| Azure private endpoint DNS suffix | [Azure Private Endpoint DNS](https://learn.microsoft.com/azure/private-link/private-endpoint-dns) |
| Container Apps platform NSG rule | [Container Apps NSG reference](https://learn.microsoft.com/azure/container-apps/firewall-integration) |
| APIM classic VNet platform port | [APIM VNet reference](https://learn.microsoft.com/azure/api-management/virtual-network-reference) |
| APIM Premium v2 VNet injection | [Inject APIM Premium v2](https://learn.microsoft.com/azure/api-management/inject-vnet-v2) |
| Event Hubs protocol port | [Event Hubs connectivity 문제 해결](https://learn.microsoft.com/azure/event-hubs/troubleshooting-guide#troubleshoot-permanent-connectivity-issues) |
