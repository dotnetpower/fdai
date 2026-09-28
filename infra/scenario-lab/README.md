# SRE Demo Scenario Lab

This Terraform root creates a disposable, non-production Azure target for the ten reference fault
scenarios that cover S1-S12. Its child resources use an existing protected holding resource group,
but remain isolated in one Terraform state and tagged resource set. It is separate from the FDAI
application deployment and does not promote a scenario, grant standing execution authority, or
prove a live outcome by itself.

## Scope

The root creates these resources under one protected holding resource group and one remote state
key. Destroy removes only the child resources in this state; it never deletes the holding group or
unrelated resources in that group.

| Area | Resources |
|------|-----------|
| Compute | Dedicated `aks-store-demo` two-node cluster with an authenticated public API endpoint, Chaos Mesh installed after apply, AKS Store Demo with a three-replica order service, private Linux stress VM |
| Data and AI | Private MySQL Flexible Server, private Azure OpenAI account and one deployment |
| Security | Microsoft Entra and Azure RBAC for AKS with local accounts disabled, generated MySQL password in encrypted private state and a mode-0600 runner file, managed-identity role assignments, no VM public IP |
| Network | Isolated VNet, delegated and private-endpoint subnets, egress-only NAT gateway, bidirectional peering to the VNet-integrated deploy runner, deployment-owned private-endpoint NSG association, and policy-owned NSGs on the AKS, MySQL, and stress subnets |
| Evidence | Log Analytics, Application Insights, AKS monitoring, MySQL and Azure OpenAI metrics |
| Optional commerce | Private Service Bus and Cosmos DB, workload identity, public HTTPS storefront, private administration and backend services |

This root does not deploy the full C1-C4 path through Application Gateway and API Management. It
also does not deploy FDAI itself. S13 uses the existing configuration-baseline and scheduling
paths, while S14 uses the existing alert ingress and investigation path.

## Prerequisites

Use an existing self-hosted runner labeled `fdai-deploy`, `fdai-deploy-candidate`, and
`fdai-scenario-lab`. The workflow selects all three labels, so only runners that carry the
additive `fdai-scenario-lab` label run lab jobs; other workflows ignore that label. The label exists
because two lab `terraform plan` runs failed only on a runner built from a different image, while
every plan on the specialized-image runners succeeded. Add it only to a runner built from the same
specialized image as the runners that already carry it, and remove it from any runner whose
environment is in doubt.
The runner must have `az`, `terraform`,
`kubectl`, `helm`, and `jq`, and must reach the private state account and the peered lab VNet. The
protected workflow installs a checksum-pinned `kubelogin` in runner-temporary storage so Azure RBAC
kubeconfigs can authenticate without changing the runner image.
Its managed identity needs Network Contributor on the operations resource group for the reverse
VNet peering, Storage Blob Data Contributor on the private state account, and RBAC Administrator
for the bounded role assignments. Protected apply and destroy grant Contributor only on the
configured holding resource group for the run, then remove that assignment when the workflow
created it. The workflow binds Terraform provider and backend authentication explicitly to this
identity with `ARM_USE_MSI=true` and its exact client ID; an Azure CLI Managed Identity login is
not treated as a user login or an implicit Terraform credential.

Configure these repository variables before running the workflow:

| Variable | Purpose |
|----------|---------|
| `ARM_SUBSCRIPTION_ID`, `AZURE_TENANT_ID` | Exact Azure deployment context |
| `STATE_RESOURCE_GROUP`, `STATE_STORAGE_ACCOUNT` | Private Terraform state backend |
| `AZURE_REGION`, `AZURE_REGION_SHORT` | Target region and CAF naming token |
| `SCENARIO_LAB_RESOURCE_GROUP_NAME` | Existing protected holding resource group for disposable child resources |
| `SCENARIO_LAB_RUNNER_PRINCIPAL_ID` | Entra object id of the self-hosted runner Managed Identity |
| `OPS_VNET_ID`, `OPS_VNET_NAME`, `OPS_RESOURCE_GROUP_NAME` | Existing runner VNet peering target |
| `SCENARIO_LAB_SSH_PUBLIC_KEY` | Public key for the private stress VM |
| `SCENARIO_LAB_VM_IMAGE_VERSION` | Exact region-available Ubuntu image version |
| `SCENARIO_LAB_AKS_NODE_VM_SIZE`, `SCENARIO_LAB_STRESS_VM_SIZE` | Optional subscription-compatible VM SKU overrides; defaults remain `Standard_D2s_v5` and `Standard_B2s` |
| `SCENARIO_LAB_CHAOS_MESH_CHART_VERSION` | Exact Chaos Mesh chart version |
| `SCENARIO_LAB_AOAI_MODEL_FAMILY`, `SCENARIO_LAB_AOAI_DEPLOYMENT_SKU` | Optional region and quota overrides |
| `SCENARIO_LAB_OPENAI_PRIVATE_DNS_ZONE_ID`, `SCENARIO_LAB_OPENAI_PRIVATE_DNS_RESOURCE_GROUP_NAME` | Existing central `privatelink.openai.azure.com` zone already linked to the runner and P2S VNets |
| `SCENARIO_LAB_OPERATOR_PRINCIPAL_ID` | Operator Entra object id used only when VPN operator access is enabled |
| `DEV_ACCESS_VNET_ID`, `DEV_ACCESS_VNET_NAME`, `DEV_ACCESS_RESOURCE_GROUP_NAME` | Existing P2S VPN VNet identity used only for direct workstation testing |

Configure a protected GitHub environment named `scenario-lab` with a required reviewer. Keep the
existing `plan-only` environment for non-mutating plans. Before any temporary role grant, the
workflow requires the configured runner principal to match the `oid` claim in its active Azure
Resource Manager access token.

## Deployment flow

Run [.github/workflows/sre-demo-lab.yml](../../.github/workflows/sre-demo-lab.yml) from an exact
commit already present on protected `main`:

1. Run `action=plan` and review the resource counts and any quota or policy failures. A failed plan
   reports only an error count and the allowlisted categories, Terraform addresses, and Azure error
   codes taken from Terraform's structured error diagnostics; refresh and progress output never
   contributes a token. The raw provider log stays runner-local and is shredded during cleanup. The
   plan also lists every retained-resource import and every scope-case grant replacement described
   in [Retained resource adoption](#retained-resource-adoption).
2. Run `action=apply` with an RFC 3339 `expires_at_utc`. The protected environment approval gates
   the apply, and ordinary apply refuses delete or replacement actions except the scope-case grant
   replacements that the plan lists. A failed apply reports the same allowlisted projection as a
   failed plan, adding addresses from Terraform's `apply_errored` hooks. Both come from
   `scripts/deployment/scenario-lab/terraform_diagnostics.py`. For the one-time transition
   from the earlier private cluster, first review `action=plan`, then run `action=recreate-aks` with
   `confirm_aks_recreation=recreate-aks-store-demo`. That action accepts only replacement of the
   exact scenario cluster and its cluster-scoped role assignments, and rejects any other delete.
3. Set `run_reference_sweep=true` only with a current `approval_ref`. Keep `scenario_id=all` for the
  complete sweep or select one allowlisted scenario for a bounded rehearsal. Every approved apply
  starts the exact AKS target before planning only when it was stopped, prepares the authenticated
  context, runs the selected scenarios sequentially, and restores `Stopped` before cleanup when this
  run started the cluster.
4. Run `action=destroy-plan` in the `plan-only` environment and review the exact delete count,
   Terraform addresses, and replacement paths without granting deployment authority.
5. Run `action=destroy` with `confirm_destroy=destroy-sre-demo-lab` only after that review. Destroy
   creates and applies its exact destroy plan in the protected `scenario-lab` environment.

## AKS Store Demo workload

Every approved apply prepares the official
[AKS Store Demo](https://github.com/Azure-Samples/aks-store-demo) in the `fdai-sre-demo`
namespace. The renderer fixes the upstream source at commit
`61b033448904a930f01d497ce7139aca87a1b12d`, verifies the complete manifest SHA-256, and replaces
each version tag with its reviewed multi-platform image digest before `kubectl apply`.
The Terraform root creates the exact dedicated cluster name `aks-store-demo`; it never deploys the
commerce workload to another FDAI, shared, or pre-existing cluster.
The AKS management API is reachable from public networks. Entra RBAC remains enabled and local
Kubernetes accounts remain disabled, so management operations still require an authenticated
authorized principal.

The lab applies only these safety overlays:

- `order-service` runs with three replicas and is the target for the existing AKS fault scenarios.
- `store-front` keeps one public Azure Load Balancer and receives a deterministic Azure-provided
  hostname in the form `fdai-store-<environment>-<region>-<hash>.<azure-region>.cloudapp.azure.com`.
- `store-admin` becomes a private `ClusterIP` service and is not reachable from the public endpoint.
- The previous `api-backend` Deployment and Service are removed from the dedicated namespace.

The application remains an external MIT-licensed demonstration workload and is not an FDAI
runtime component. It retains the upstream synthetic credentials and data, so do not use it for
production or real customer information. The public endpoint uses HTTP and exists only for the
approved disposable lab window. The expiry tag does not remove it automatically; run the protected
destroy operation after the demo.

After an approved apply, the workflow waits for the Load Balancer address, verifies that the Azure
hostname resolves to that exact address, checks `http://<hostname>/health`, and prints the browser
URL in the workflow summary. No VPN or port forwarding is required to open the store front.
It then retains the `sre-demo-lab-store-demo-<run>-<attempt>` artifact for 30 days. The artifact
records the public DNS answer, the Kubernetes and Azure Load Balancer addresses, the HTTP health
status, the readiness of every expected workload including three `order-service` replicas, the
digest of every running image, and the private `ClusterIP` Store Admin service. Any failed check
fails the run before a fault sweep starts.

Azure Policy may attach one deployment-external NSG to each workload subnet. Terraform preserves
those effective AKS, MySQL, and stress-subnet associations instead of replacing them with the
lab's shared NSG. The lab still owns the private-endpoint subnet association, and the stress VM
NIC retains its separate deployment-owned NSG. Deployment preflight must observe the default
inbound deny rule on every effective subnet NSG.

## Retained resource adoption

An interrupted apply or an out-of-band recovery can leave a lab resource in Azure after Terraform
state stops recording it. The next plan would then try to create a resource that already exists.
Before every `plan`, `apply`, and `recreate-aks`, the workflow observes only these exact resources:
the `aks-store-demo` cluster, the recorded MySQL server, the runner's two cluster-scoped AKS
grants, and the stress VM NIC association with the lab NSG. It writes a Terraform `import` block
for each one that exists outside state. The cluster, server, and NIC must match the exact lab
resource ID and carry the `fdai:managed`, `fdai:layer`, `fdai:env`, and `fdai:workload`
ownership tags. A grant must match the exact runner principal, role, and cluster scope, and the
NIC must use the lab NSG. Any mismatch stops the run.

The plan shows each import before approval, and the approved apply performs it. The helper never
imports into state directly. When an Azure CLI recovery recorded a grant scope with different
letter case, Terraform replaces that grant with the same principal, role, and scope. Ordinary apply
accepts only that exact case-normalizing replacement. Preparation then waits up to five minutes
for the replaced grant to reach the Kubernetes API before it installs or changes any workload.

Apply also starts a stopped cluster or MySQL server before planning, because Azure rejects updates
to stopped resources. The run restores `Stopped` on a cluster it started. It leaves a started MySQL
server `Ready`, because a stopped flexible server rejects the parameter reads that every refreshed
plan requires.

## Deploy the optional commerce scenario

Set `commerce_enabled=true` in the reviewed Terraform plan to provision private Service Bus and
Cosmos DB dependencies plus one workload identity. After apply, create or bind the reviewed TLS
secret for the public hostname, then run:

```bash
export SCENARIO_LAB_STOREFRONT_HOSTNAME="<public-hostname>"
export SCENARIO_LAB_STOREFRONT_TLS_SECRET_NAME="<tls-secret-name>"
export SCENARIO_LAB_SYNTHETIC_AUTHORIZATION_REF="<standing-authorization-reference>"
export SCENARIO_LAB_SYNTHETIC_AUTHORIZATION_EXPIRES_AT="<yyyy-mm-ddThh:mm:ssZ>"
bash scripts/deployment/scenario-lab/prepare-commerce.sh "$runtime_dir"
```

The script installs the exact pinned AKS Store Demo commit with prebuilt images, exposes only
`store-front` through HTTPS, keeps `store-admin` and the APIs on `ClusterIP`, applies an ingress
policy for the administration workload, verifies the public health path, and writes a mode-0600
`commerce.env`. It never creates a certificate or chooses a DNS zone. Those values remain part of
the approved deployment plan.

## Test from the operator PC

Set `enable_vpn_operator_access=true` on the plan and apply runs to add direct peering, gateway
transit, private DNS links, and minimum operator roles for the private data services. The AKS API
endpoint is public so the local FDAI inventory can reach it from changing operator egress, but it
still requires Microsoft Entra authentication and Azure RBAC, and local accounts remain disabled.
Public access for MySQL and Azure OpenAI remains disabled.

After apply, regenerate the P2S profile so the client receives the lab route and private service
suffixes. First initialize the workstation root against the same private state key used by the
workflow:

```bash
export ARM_USE_AZUREAD=true
cp infra/scenario-lab/backend.azurerm.tf.example infra/scenario-lab/backend.tf
terraform -chdir=infra/scenario-lab init -reconfigure -input=false \
  -backend-config="resource_group_name=$STATE_RESOURCE_GROUP" \
  -backend-config="storage_account_name=$STATE_STORAGE_ACCOUNT" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=scenario-lab/fdai-sre-lab.tfstate" \
  -backend-config="use_azuread_auth=true"
```

The existing VPN profile already provides the route to the private state account. Then generate
the replacement profile with the scenario service suffixes:

```bash
export FDAI_DEV_ACCESS_EXTRA_DNS_DOMAINS_JSON="$(
  terraform -chdir=infra/scenario-lab output -json operator_dns_routing_domains
)"
bash tools/dev-access/scripts/profile.sh
```

Import the generated `tools/dev-access/.profiles/azurevpnconfig.xml` into Azure VPN Client, replace
the previous profile, and reconnect. In WSL, apply the same split-DNS suffixes:

```bash
export FDAI_DEV_ACCESS_EXTRA_DNS_DOMAINS_JSON="$(
  terraform -chdir=infra/scenario-lab output -json operator_dns_routing_domains
)"
bash tools/dev-access/scripts/wsl-dns.sh apply
```

The workstation can then prepare the same environment. The reference sweep now runs only through
`scripts/catalog/run-catalog-scenario.py`, which delegates every live run to
`GovernedChaosExecutionAdapter`. `SCENARIO_LAB_SCENARIO_ID=all` selects the reference sweep in demo
order; any other allowlisted value selects that one reference scenario. Until a deployment installs
the `fdai.governed_chaos` provider and the selected scenarios are promoted, the sweep below and the
protected workflow's sweep step refuse with exit status 3 before touching the substrate:

```bash
runtime_dir="$(mktemp -d)"
bash scripts/deployment/scenario-lab/prepare-runner.sh "$runtime_dir"

export SCENARIO_LAB_CONFIRM_ENFORCE=true
export SCENARIO_LAB_APPROVAL_REF="<current-approval-reference>"
bash scripts/deployment/scenario-lab/run-reference-sweep.sh "$runtime_dir/enforce.env"

bash scripts/deployment/scenario-lab/cleanup-runner.sh "$runtime_dir"
```

Run `cleanup-runner.sh` in a shell trap when iterating manually so the temporary kubeconfig and
MySQL password are removed after failures too.

The state key is `scenario-lab/fdai-sre-lab.tfstate`. Terraform plans, kubeconfig, temporary secret
files, and raw reports are shredded from the runner. The workflow retains only a repository-safe
summary artifact with no environment identifiers or secret values.

## Safety boundary

- Plan is the default operation. Apply, live testing, and destroy require the protected
  `scenario-lab` environment.
- A live sweep requires both `SCENARIO_LAB_CONFIRM_ENFORCE=true` and a bounded human approval
  reference, and it cannot inject until the sweep is ported onto the governed chaos adapter.
- Terraform generates the MySQL password inside encrypted private state. The sensitive composite
  output is read only on the private runner and writes the value directly to a mode-0600 temporary
  file; it is never a workflow input, command-line argument, repository-safe artifact, or committed
  value. No persistent secret store is created solely for the fault sweep.
- The default lab VNet uses `10.73.0.0/20`; change it only after checking every peered and local
  address space for overlap.
- The expiry tag supports cost review but does not delete resources automatically. Explicit
  destroy remains required so cleanup is reviewable and state-consistent.
- Raw plan, apply, destroy, and enforce reports remain runner-local and are shredded. The workflow
  retains only repository-safe summaries: scenario outcomes with rollback status, and the Store
  Demo readback.
- No live Azure plan, apply, fault injection, or destroy is evidence for this source change until
  it runs against an exact committed revision and its receipts are retained.
