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
| Compute | One-node private AKS cluster, Chaos Mesh installed after apply, three-replica NGINX backend, private Linux stress VM |
| Data and AI | Private MySQL Flexible Server, private Azure OpenAI account and one deployment |
| Security | Generated MySQL password in encrypted private state and a mode-0600 runner file, managed-identity role assignments, no VM public IP |
| Network | Isolated VNet, delegated and private-endpoint subnets, egress-only NAT gateway, bidirectional peering to the VNet-integrated deploy runner |
| Evidence | Log Analytics, Application Insights, AKS monitoring, MySQL and Azure OpenAI metrics |

This root does not deploy the full C1-C4 path through Application Gateway and API Management. It
also does not deploy FDAI itself. S13 uses the existing configuration-baseline and scheduling
paths, while S14 uses the existing alert ingress and investigation path.

## Prerequisites

Use the existing self-hosted runner labeled `fdai-deploy`. The runner must have `az`, `terraform`,
`kubectl`, `helm`, and `jq`, and must reach the private state account and the peered lab VNet.
Its managed identity needs Network Contributor on the operations resource group for the reverse
VNet peering, Storage Blob Data Contributor on the private state account, and RBAC Administrator
for the bounded role assignments. Protected apply and destroy grant Contributor only on the
configured holding resource group for the run, then remove that assignment when the workflow
created it.

Configure these repository variables before running the workflow:

| Variable | Purpose |
|----------|---------|
| `ARM_SUBSCRIPTION_ID`, `AZURE_TENANT_ID` | Exact Azure deployment context |
| `STATE_RESOURCE_GROUP`, `STATE_STORAGE_ACCOUNT` | Private Terraform state backend |
| `AZURE_REGION`, `AZURE_REGION_SHORT` | Target region and CAF naming token |
| `SCENARIO_LAB_RESOURCE_GROUP_NAME` | Existing protected holding resource group for disposable child resources |
| `OPS_VNET_ID`, `OPS_VNET_NAME`, `OPS_RESOURCE_GROUP_NAME` | Existing runner VNet peering target |
| `SCENARIO_LAB_SSH_PUBLIC_KEY` | Public key for the private stress VM |
| `SCENARIO_LAB_VM_IMAGE_VERSION` | Exact region-available Ubuntu image version |
| `SCENARIO_LAB_BACKEND_IMAGE` | Demo backend image pinned by `sha256` digest |
| `SCENARIO_LAB_CHAOS_MESH_CHART_VERSION` | Exact Chaos Mesh chart version |
| `SCENARIO_LAB_AOAI_MODEL_FAMILY`, `SCENARIO_LAB_AOAI_DEPLOYMENT_SKU` | Optional region and quota overrides |
| `SCENARIO_LAB_OPERATOR_PRINCIPAL_ID` | Operator Entra object id used only when VPN operator access is enabled |
| `DEV_ACCESS_VNET_ID`, `DEV_ACCESS_VNET_NAME`, `DEV_ACCESS_RESOURCE_GROUP_NAME` | Existing P2S VPN VNet identity used only for direct workstation testing |

Configure a protected GitHub environment named `scenario-lab` with a required reviewer. Keep the
existing `plan-only` environment for non-mutating plans.

## Deployment flow

Run [.github/workflows/sre-demo-lab.yml](../../.github/workflows/sre-demo-lab.yml) from an exact
commit already present on protected `main`:

1. Run `action=plan` and review the resource counts and any quota or policy failures.
2. Run `action=apply` with an RFC 3339 `expires_at_utc`. The protected environment approval gates
   the apply, and the workflow refuses delete or replacement actions.
3. Set `run_reference_sweep=true` only with a current `approval_ref`. The workflow prepares the
   private AKS context, retrieves the MySQL password into a mode-0600 temporary file, and runs the
   reference sweep sequentially.
4. Run `action=destroy` with `confirm_destroy=destroy-sre-demo-lab` after evidence review. Destroy
   applies an exact destroy plan from the same job.

## Test from the operator PC

Set `enable_vpn_operator_access=true` on the plan and apply runs to add direct peering, gateway
transit, private DNS links, and minimum operator roles. Public access for AKS, MySQL, and Azure
OpenAI remains disabled.

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

The workstation can then prepare the same environment and run one approved scenario or the full
reference sweep:

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
  reference. The approval reference is recorded in every run result.
- Terraform generates the MySQL password inside encrypted private state. The sensitive composite
  output is read only on the private runner and writes the value directly to a mode-0600 temporary
  file; it is never a workflow input, command-line argument, repository-safe artifact, or committed
  value. No persistent secret store is created solely for the fault sweep.
- The default lab VNet uses `10.73.0.0/20`; change it only after checking every peered and local
  address space for overlap.
- The expiry tag supports cost review but does not delete resources automatically. Explicit
  destroy remains required so cleanup is reviewable and state-consistent.
- Raw plan, apply, destroy, and enforce reports remain runner-local and are shredded. The workflow
  retains only a repository-safe summary of scenario outcomes and rollback status.
- No live Azure plan, apply, fault injection, or destroy is evidence for this source change until
  it runs against an exact committed revision and its receipts are retained.
