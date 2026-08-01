---
title: Network Connectivity Matrix
---
# Network Connectivity Matrix

This reference defines the DNS, IP, protocol, and port requirements for running FDAI on Azure
across public, private, provisioned-throughput, API Management, and fully disconnected network
profiles. Use it to build firewall, network security group (NSG), private DNS, and routing policy,
and to predict which FDAI capability becomes unavailable when a path is blocked.

> **Scope:** Values in this document target Azure Public Cloud. Azure Government and Azure China
> use different DNS suffixes and service-tag address sets. Resolve those values from the current
> [Azure private endpoint DNS table](https://learn.microsoft.com/azure/private-link/private-endpoint-dns)
> instead of translating suffixes by hand.
>
> **Address rule:** Don't hard-code public Azure service IPs. Use private endpoint addresses,
> deployment outputs, Azure service tags, or FQDN application rules. Microsoft updates the public
> prefixes behind service tags. A private endpoint IP and an internal API Management virtual IP
> are also deployment-specific.

## Design at a glance

Provisioned Throughput Units (PTU) change Azure OpenAI capacity, not its network protocol. Direct
PTU and Standard deployments therefore use the same Azure OpenAI hostname, private DNS zone,
Microsoft Entra authentication path, and TCP port. API Management (APIM) adds a separate gateway
hop and its own platform dependencies.

| Profile | Model route | Public internet egress | Supported outcome |
|---------|-------------|------------------------|-------------------|
| **Full air gap** | none until a self-hosted adapter exists | none | deterministic core only; no live Azure evidence or cloud action |
| **Private Azure** | disabled or private Azure OpenAI | none except approved Azure control/identity routes | full deterministic runtime; adaptive features only when the model route is present |
| **Private Azure + direct PTU** | FDAI -> private Azure OpenAI | approved Azure control/identity routes | full runtime with provisioned model capacity |
| **Private Azure + APIM** | FDAI -> private APIM -> private PTU, with optional Standard spillover | APIM platform routes plus approved Azure control/identity routes | full runtime when both hops and APIM evidence headers work |
| **Public Azure** | public Azure OpenAI or public APIM | allow-listed HTTPS egress | full runtime without private endpoints; service firewalls still restrict callers |

"No public internet" is not the same as "no Azure reachability." A private Azure deployment still
needs Microsoft Entra token issuance and a management-plane route unless those operations are moved
to a connected collector. A true air gap has neither and cannot claim live cloud observation or
cloud mutation.

## Common FDAI runtime paths

The current Azure baseline is a workload-profile Container Apps environment using the
`Consumption` workload profile. Source ports are ephemeral. Rules should constrain destination,
protocol, and destination port.

| From | Destination or service tag | Protocol and port | Why FDAI needs it | If blocked |
|------|----------------------------|-------------------|-------------------|------------|
| Container Apps subnet | Azure DNS `168.63.129.16`, or the configured resolver | UDP and TCP 53 | public and private endpoint name resolution | revisions and runtime calls fail by hostname; private services may return public addresses or `NXDOMAIN` |
| Container Apps platform | `MicrosoftContainerRegistry`, `AzureFrontDoor.FirstParty` | TCP 443 | system image and Container Apps platform artifacts | environment provisioning or revision start fails |
| FDAI identities | `AzureActiveDirectory`; `login.microsoftonline.com` and cloud-specific login hosts | TCP 443 | managed-identity and Entra tokens for every RBAC-backed service | Event Hubs, ARM, Azure OpenAI, Storage, ACR, and Monitor calls lose authentication |
| FDAI core and jobs | `<namespace>.servicebus.windows.net` | TCP 9093 | required Event Hubs Kafka transport | event ingest, derived event publication, canary, and scheduled producers stop |
| FDAI apps and jobs | `<server>.postgres.database.azure.com` | TCP 5432 | state, audit, schedules, projections, and pgvector | startup/readiness fails or the affected projection becomes unavailable |
| FDAI model clients | `<account>.openai.azure.com` | TCP 443 | direct Standard or PTU inference, embeddings, narrator, and managed web search | adaptive capabilities become unavailable; affected work stays deterministic-only or requires human review |
| Deploy runner and FDAI web-search client | `<account>.services.ai.azure.com`, or `privatelink.services.ai.azure.com` in private mode | TCP 443 | reconcile and invoke the deployment-owned Foundry prompt agent and run real-tool readiness probes | agent reconciliation or startup readiness fails; web search reports unavailable |
| FDAI model clients | deployment-supplied APIM gateway FQDN | TCP 443 | APIM-fronted PTU or Standard inference | gateway-routed capabilities become unavailable |
| FDAI storage clients | `<account>.blob.core.windows.net` | TCP 443 | case history, document blobs, and deployment state | the owning artifact, replay, or deployment operation fails |
| FDAI document clients | `<account>.dfs.core.windows.net` | TCP 443 | ADLS Gen2 rename and hierarchical namespace operations | document ingestion cannot promote quarantine content to governed storage |
| Container Apps secret resolver and deploy host | `<vault>.vault.azure.net` | TCP 443 | Container Apps Key Vault references and Terraform secret writes | a new revision cannot resolve secrets; deploy secret creation fails |
| Container Apps image pull | `<registry>.azurecr.io` and `<registry>.<region>.data.azurecr.io` | TCP 443 | image manifest and layer download | new revisions fail with image-pull errors even when an old revision remains healthy |
| Inventory and action adapters | `management.azure.com` or an approved Resource Manager private link | TCP 443 | Resource Graph, ARM reads, what-if, and governed actions | inventory becomes stale and cloud actions are blocked |
| Telemetry exporters | Azure Monitor ingestion hosts or Azure Monitor Private Link Scope (AMPLS) | TCP 443 | logs, metrics, traces, and Application Insights | control decisions continue, but telemetry and operational evidence become unavailable |
| Operator browser | console FQDN, read API FQDN, and `login.microsoftonline.com` | TCP 443 | SPA delivery, read-only evidence, and interactive Entra sign-in | console or sign-in is unavailable; the headless core continues |
| Optional delivery adapters | configured Teams, Slack, GitHub, email, pager, or webhook FQDN | TCP 443 | approvals, notifications, and remediation pull requests | the channel queues or fails over; approval requirements are never bypassed |

For an internal Container Apps environment with HTTP ingress, also allow approved clients to the
environment on TCP 443 and the platform's internal HTTPS edge port 31443. Allow the Azure Load
Balancer probes to the assigned ports in TCP 30000-32767. FDAI core itself has no public inbound
endpoint; these rules apply to enabled read, ingestion, or command APIs.

A closed-network console additionally needs private ingress for both the SPA and read API, VPN or
ExpressRoute routing from the operator, and private DNS visible to the browser's host operating
system. The current root Terraform does not provision a Static Web Apps private endpoint. Without
that additional deployment-owned path, the core can run privately while the console stays
unreachable.

Legacy Consumption-only Container Apps environments have a broader platform contract: UDP 1194 and
TCP 9000 to `AzureCloud.<region>`, TCP 443 to `AzureCloud`, TCP 5671-5672 to
`EventHub.<region>`, and UDP 123 for NTP. Do not copy those rules into the current workload-profile
baseline unless the deployed environment type requires them. Use the current
[Container Apps NSG table](https://learn.microsoft.com/azure/container-apps/firewall-integration)
as the authority.

## Private DNS zones

Applications continue to use the public service FQDN. Azure DNS follows a CNAME into the linked
private zone and returns the private endpoint address. Every querying VNet, peered deploy-runner
VNet, VPN DNS resolver, and on-premises conditional forwarder must have a path to the same records.

| FDAI service | Query suffix | Private DNS zone | Port | Provisioned by current `infra/` |
|--------------|--------------|------------------|------|---------------------------------|
| Key Vault | `vault.azure.net`, plus CNAME chase through `vaultcore.azure.net` | `privatelink.vaultcore.azure.net` | TCP 443 | yes in private mode |
| Event Hubs, both shards | `servicebus.windows.net` | `privatelink.servicebus.windows.net` | TCP 9093 | yes in private mode |
| PostgreSQL Flexible Server | `postgres.database.azure.com` | `privatelink.postgres.database.azure.com` | TCP 5432 | yes in private mode |
| Azure OpenAI, Standard or PTU | `openai.azure.com` | `privatelink.openai.azure.com` | TCP 443 | yes when LLM and private mode are enabled |
| ACR login and regional data records | `azurecr.io`, `<region>.data.azurecr.io` | `privatelink.azurecr.io` | TCP 443 | yes for Premium ACR in private mode |
| Blob, state, documents, and cases | `blob.core.windows.net` | `privatelink.blob.core.windows.net` | TCP 443 | yes for each enabled storage path |
| ADLS Gen2 documents | `dfs.core.windows.net` | `privatelink.dfs.core.windows.net` | TCP 443 | yes when document ingestion and private mode are enabled |
| Container Apps private ingress | `azurecontainerapps.io` | `privatelink.<region>.azurecontainerapps.io` | TCP 443 | not in the current root module |
| APIM private endpoint gateway | `azure-api.net` | `privatelink.azure-api.net` | TCP 443 | supplied by the existing APIM owner |
| Azure Monitor | Monitor, OMS, ODS, automation, and Blob suffixes | five AMPLS zones listed below | TCP 443 | not in the current root module |
| Azure Resource Manager | `management.azure.com` | `privatelink.azure.com` | TCP 443 | not in the current root module |
| Static Web Apps private ingress | `azurestaticapps.net` and partition suffix | `privatelink.azurestaticapps.net` and partition zone | TCP 443 | not in the current root module |

AMPLS needs all five linked zones: `privatelink.monitor.azure.com`,
`privatelink.oms.opinsights.azure.com`, `privatelink.ods.opinsights.azure.com`,
`privatelink.agentsvc.azure-automation.net`, and `privatelink.blob.core.windows.net`. Missing only
one can make ingestion work while queries, live metrics, or agent configuration fails.

For ACR, one private endpoint allocates a registry address and one data address per replica. Both
records belong in `privatelink.azurecr.io`; don't create a separate
`<region>.data.privatelink.azurecr.io` zone. Allow every replica data endpoint used by image pulls.

Private DNS links must use fallback-to-public resolution when a VNet needs private and public
resources of the same Azure service type. A private zone without the requested A record can return
`NXDOMAIN`; a manually pinned public A record is unsafe because Azure can change the address.
VPN split-DNS clients that re-evaluate routing after each CNAME must route both the public query
suffix and its CNAME target suffix. Key Vault needs both `vault.azure.net` and
`vaultcore.azure.net`, for example.

## Model routing scenarios

### Direct Standard or PTU

FDAI resolves `<account>.openai.azure.com` and calls it on TCP 443 with an Entra token. In private
mode, the name must resolve through `privatelink.openai.azure.com` to the endpoint's private IP.
The token path still needs `AzureActiveDirectory` on TCP 443. PTU doesn't add a port, DNS zone, or
second endpoint.

### APIM-fronted PTU and Standard spillover

The complete private flow is:

```text
FDAI subnet -> APIM private VIP:443 -> Azure OpenAI private endpoint:443
             -> PTU first; one same-family Standard retry only after HTTP 429
```

- **First hop:** FDAI resolves the deployment-supplied APIM gateway FQDN to an APIM private
  endpoint or internal VNet-injection VIP and calls TCP 443.
- **Second hop:** APIM needs outbound VNet integration or injection, private DNS resolution for
  both Azure OpenAI accounts, TCP 443 to both private endpoints, and its managed identity needs
  `Cognitive Services OpenAI User` on both backends.
- **Private endpoint is inbound only:** placing a private endpoint in front of APIM does not make
  APIM-to-Azure-OpenAI traffic private. Configure the second hop explicitly.
- **Evidence contract:** APIM must return `x-fdai-model-backend`, `x-fdai-capacity-unit`, and
  `x-fdai-spillover`. FDAI rejects a successful T2 response when these are absent or malformed.

For Premium v2 VNet injection, allow APIM outbound TCP 443 to the `Storage` and `AzureKeyVault`
service tags, plus TCP 443 to both model backends and DNS to the configured resolver. For classic
Developer/Premium VNet injection, the platform contract additionally includes inbound
`ApiManagement` TCP 3443, inbound `AzureLoadBalancer` TCP 6390, outbound `Storage` TCP 443,
`Sql` TCP 1433, `AzureKeyVault` TCP 443, `AzureMonitor` TCP 1886 and 443, DNS TCP/UDP 53, NTP UDP
123, and certificate validation over TCP 80/443. Apply the exact current table for the deployed
APIM tier; don't treat these platform ports as FDAI application ports.

### Public model or public APIM

Use the same TCP 443 application paths, but public DNS returns service addresses and each service
firewall must admit the FDAI egress source. Give the Container Apps environment a stable NAT or
firewall egress IP before IP-allowlisting it. An unrestricted public endpoint without service
firewall or identity controls is not an acceptable production profile.

## Deployment and operator paths

Runtime allow rules do not make a deployment host work. A VNet runner or jumpbox needs these
additional paths.

| Destination | Protocol and port | Purpose | Closed-network alternative |
|-------------|-------------------|---------|----------------------------|
| DNS resolver | UDP and TCP 53 | resolve control, data, and private endpoint names | private resolver with conditional forwarding |
| Azure Instance Metadata Service `169.254.169.254` | TCP 80 | runner VM managed-identity token bootstrap | none for an Azure VM; link-local traffic stays inside Azure |
| `login.microsoftonline.com` and required tenant/federation hosts | TCP 443 | Azure CLI and Terraform token acquisition | approved Entra route; Entra has no tenant private endpoint equivalent |
| `management.azure.com` | TCP 443 | Terraform and Azure CLI control plane | Resource Manager private link where its current limitations are acceptable |
| state Blob, Key Vault, ACR login/data | TCP 443 | Terraform state, secret writes, image push/pull | the private endpoints and zones above |
| GitHub runner endpoints | TCP 443 | checkout, Actions broker, API, artifacts, and releases | manual jumpbox transport or an internal source/artifact mirror |
| Terraform registry, Python index, base-image registry | TCP 443 | first-time tool and dependency acquisition | signed offline kit and internal mirrors |

At minimum, a connected GitHub runner commonly needs `github.com`, `api.github.com`,
`*.actions.githubusercontent.com`, `objects.githubusercontent.com`, and the repository's chosen
release and package hosts on TCP 443. GitHub changes its published allow list; use GitHub's current
runner communication reference or the manual transport instead of freezing its IPs in FDAI docs.
Resource Manager private link is tenant-wide at the root management-group association and does not
support every resource provider, including AKS. Validate FDAI's exact inventory and action set
before using it as the only management route.

## Failure and degradation matrix

| Blocked path | Observable failure | FDAI behavior |
|--------------|--------------------|---------------|
| DNS 53 or wrong private-zone link | timeout, public IP, or `NXDOMAIN` | startup/readiness fails for required services; never falls back to an unapproved public endpoint |
| Entra 443 | token timeout, `401`, or credential unavailable | all affected RBAC-backed adapters fail closed |
| Event Hubs 9093 | Kafka connection timeout | no governed ingest or publication; core cannot claim healthy event processing |
| PostgreSQL 5432 | connection timeout | durable state, audit, schedules, and projections are unavailable; autonomous work stops |
| Azure OpenAI or APIM 443 | model timeout or unavailable binding | deterministic paths continue; T1/T2, narrator, and managed web search report unavailable or require human review |
| APIM evidence headers | HTTP success with invalid gateway evidence | T2 result is rejected and audited; no direct-endpoint fallback |
| ACR login or data 443 | manifest or layer pull timeout | new Container Apps revision fails; an already running revision may continue |
| Key Vault 443 | Container Apps secret resolution or Terraform 403/timeout | revision activation or deployment fails; no secret value fallback |
| ARM/Resource Graph 443 | inventory query timeout | retain the last complete inventory as stale; block evidence-dependent actions |
| Blob/DFS 443 | upload, rename, replay, or state failure | only the owning document, case-history, or deployment workflow stops; no fabricated evidence |
| Azure Monitor 443 | missing telemetry | runtime decisions continue, but health and observability are explicitly unavailable |
| Approval/delivery host 443 | channel delivery failure | queue or configured fallback channel; never auto-approve |
| Container Apps platform tags | revision stuck or environment unhealthy | platform cannot start or manage the workload even if FDAI endpoints are open |
| APIM platform ports | APIM deployment, health, management, or gateway failure | every APIM-routed model capability is unavailable |

## Automated connectivity check

Run the checker from the network that actually hosts the workload. It discovers the primary and
auxiliary Kafka endpoints, PostgreSQL, Azure OpenAI, Prometheus, email, and the development gateway
from known environment variables. It then resolves every DNS name, verifies the resolved address
class, opens the configured TCP port, and prints required actions.

```bash
python3 scripts/deployment/azure/check-network-connectivity.py \
   --profile runtime-private \
   --env-file .fdai/local-runtime.env \
   --output tmp/network-connectivity.json
```

Use `runtime-public` from a public runtime network and `deploy-runner` from the deployment host.
Use `custom` plus one or more manifests for APIM, ACR data endpoints, storage, Key Vault, or any
deployment-specific route that isn't represented by an environment variable.

```json
{
   "schema_version": "fdai.network-connectivity-manifest.v1",
   "checks": [
      {"id": "apim-model-gateway", "host": "replace.example.com", "port": 443,
       "required": true, "expected_ip": "private"}
   ]
}
```

Pass the file with `--manifest <path>`. Each check accepts `expected_ip` values `private`, `public`,
or `any`. The command exits `1` when a required check fails and `2` for invalid input. Optional
failures produce warnings and exit `0`. The normal report contains actual hostnames and resolved
addresses, so keep it under ignored local storage such as `tmp/`. Add `--redact` before sharing a
report; this replaces hosts with hashes and removes addresses.

The action summary distinguishes missing configuration, DNS/private-zone errors, wrong public or
private address resolution, and blocked TCP ports.

Protected plans run the checker automatically from the VNet deployment runner before Terraform
planning. `PREFLIGHT_EGRESS_HOSTS_JSON` continues to drive the existing TLS checks. The workflow
automatically reads existing Terraform outputs for both Event Hubs shards, PostgreSQL, Key Vault,
ACR, and Azure OpenAI, and applies the profile's private or public address expectation. Set the
optional repository variable `PREFLIGHT_NETWORK_CHECKS_JSON` to a complete manifest for additional
routes such as APIM backends or ACR replica data endpoints. The workflow combines all inputs, blocks
on any required failure, removes the temporary manifest, and merges only the redacted network
report into the existing `preflight-evidence.json` digest contract. On an initial deployment,
Terraform outputs that do not exist yet are skipped.

A positive endpoint checker cannot prove a full air gap. Use
`bash scripts/deployment/release/airgap-drill.sh` to verify the network-free release path inside a
namespace with no route or DNS.

## Validation checklist

Run probes from the actual Container Apps subnet, APIM subnet, and deploy-host subnet. A laptop
result does not prove those execution paths.

1. Resolve every public query FQDN and confirm private profiles return an address from the intended
   private endpoint or internal VIP subnet.
2. Open a bounded TCP connection to ports 443, 9093, and 5432 as applicable. A TLS or protocol
   authentication error proves more than a ping because private endpoints may not answer ICMP.
3. Acquire an Entra token with the exact workload identity, then perform one read-only request per
   service.
4. Pull the pinned image digest to verify both ACR login and data endpoints.
5. Call the APIM model route and verify all three FDAI evidence headers for PTU and forced-429
   spillover paths.
6. Deny one dependency at a time and confirm the matching row in the failure matrix, including
   stale evidence and no direct-endpoint fallback.

## Related docs

| To learn about | Read |
|----------------|------|
| FDAI private endpoints, VNet runner, and deployment inventory | [Deploy and Onboard](deploy-and-onboard.md) |
| No-public-egress and full-air-gap behavior | [Disconnected Deployment](disconnected-deployment.md) |
| Direct, APIM, PTU, and mixed-model binding contracts | [LLM Strategy](../architecture/llm-strategy.md) |
| Azure private endpoint DNS suffixes | [Azure Private Endpoint DNS](https://learn.microsoft.com/azure/private-link/private-endpoint-dns) |
| Container Apps platform NSG rules | [Container Apps NSG reference](https://learn.microsoft.com/azure/container-apps/firewall-integration) |
| APIM classic VNet platform ports | [APIM VNet reference](https://learn.microsoft.com/azure/api-management/virtual-network-reference) |
| APIM Premium v2 VNet injection | [Inject APIM Premium v2](https://learn.microsoft.com/azure/api-management/inject-vnet-v2) |
| Event Hubs protocol ports | [Troubleshoot Event Hubs connectivity](https://learn.microsoft.com/azure/event-hubs/troubleshooting-guide#troubleshoot-permanent-connectivity-issues) |
