# `infra/`

Infrastructure as Code - Terraform (HCL).

Renders the four CSP-neutrality contracts (event bus / runtime / secret / workload
identity) into Azure resources. Entry command: `terraform apply` per
[docs/roadmap/deployment/deploy-and-onboard.md](../docs/roadmap/deployment/deploy-and-onboard.md).

## Turnkey path (`azd`)

For a one-command experience, [`azure.yaml`](../azure.yaml) drives this Terraform
through the Azure Developer CLI. `scripts/deployment/azure/azd-up.sh` (or `make azd-up`) runs a
non-mutating `azd provision --preview` by default; set `FDAI_AZD_CONFIRM=1` to
run a real `azd up`. The two-gate design keeps an accidental apply impossible.

`azure.yaml` also declares a `services.core` block so `azd deploy` / `azd up`
builds the app image from the [`Dockerfile`](../Dockerfile) and deploys it to the
Container App tagged `azd-service-name: core` (set in
[`modules/compute/container-apps/main.tf`](modules/compute/container-apps/main.tf)).
A `services` block only drives `azd deploy`; `azd provision --preview` is
unaffected.

Direct Terraform plans require `core_image` to reference an FDAI image built
from the repository Dockerfile. The variable rejects the former
`mcr.microsoft.com/azure-cli` bootstrap placeholder. The core Container App
keeps one replica, exposes internal `/live` and `/ready` probes, and starts a
dedicated five-minute canary Job. The canary UAMI has only ACR pull and Event
Hubs send. When the read API is enabled, a read UAMI owns ACR, Key Vault, and
Reader access while a separate command UAMI owns Event Hubs send/receive.

Production plans also require PostgreSQL `ZoneRedundant` high availability,
35-day geo-redundant backup, and signed human approval delivery. Supply the human approval URL and
32+ character HMAC secret through CI secrets; Terraform stores them in Key
Vault and never writes populated values to this repository.

Environment values (subscription id, tenant id, resource group, etc.) are supplied
at apply time via env vars / tfvars files that are **never committed** - the repo
stays customer-agnostic per
[generic-scope.instructions.md](../.github/instructions/generic-scope.instructions.md).

## Module Layout

Every provisioned concern lives in **one module per seam** under `modules/`, following
the same DI pattern the Python code uses:

```
infra/
├── main.tf                 # composition root - picks a sub-module per seam
├── variables.tf            # workload="fdai", env, region, kind selectors
├── outputs.tf              # cross-module contract outputs
├── modules/
│   ├── resource-group/         # rg-fdai
│   ├── identity/               # id-fdai-executor
│   ├── compute/
│   │   └── container-apps/     # default runtime
│   ├── state-store/
│   │   └── postgres-flex/      # default (audit + pgvector)
│   ├── event-bus/
│   │   └── event-hubs-kafka/   # default (Kafka wire on :9093)
│   ├── secret-store/
│   │   └── key-vault/          # default (Container Apps native secret + KV reference)
│   ├── storage/
│   │   └── adls-gen2/           # opt-in governed document source + artifacts (HNS)
│   ├── ingestion-gateway/
│   │   └── container-app/       # opt-in upload gateway + ClamAV sidecar + migration job
│   ├── vm-task-host/            # opt-in custom Linux/GPU VM cloud-init profile
│   ├── vm-task-rbac/            # target-VM-scoped Managed Run Command RBAC
│   └── observability/
│       └── log-analytics/      # default (App Insights binds to this workspace)
└── envs/                       # per-env tfvars (git-ignored)
    ├── dev/
    ├── staging/
    └── prod/
```

Approved Azure-internal alternates for each seam (AKS, Cosmos, ESO, ...) are catalogued in
[docs/roadmap/architecture/csp-neutrality.md § Approved Alternative Azure Implementations](../docs/roadmap/architecture/csp-neutrality.md#approved-alternative-azure-implementations).
Alternates land as **sibling sub-modules** (e.g. `modules/compute/aks/`) when a real need
arises; each MUST honor the standard output contract below so callers stay swap-blind.

### Governed Python task host

[`modules/vm-task-host/`](modules/vm-task-host/) and
[`modules/vm-task-rbac/`](modules/vm-task-rbac/) are opt-in helpers for a custom
Linux or GPU VM. They do not create or start the VM. A downstream composition
passes the host module's `cloud_init_base64` to
`azurerm_linux_virtual_machine.custom_data`, then passes the created VM id and
executor principal id to the separate RBAC module. The split avoids a Terraform
dependency cycle between VM creation and target-scoped role assignment.

The cloud-init profile creates a locked, non-root `fdai-task` account, private
content-addressed task directories, and a root-owned systemd launcher. The
launcher keeps source read-only, confines output to one run directory, blocks
privilege escalation and host credential paths, and maps declared network,
process, filesystem-write, and GPU capabilities into systemd sandbox
properties. It verifies the configured Python executable but installs no
package, driver, CUDA runtime, or Python module.
Those dependencies belong in the approved VM image. The custom role allows VM
read and `virtualMachines/runCommands` read/write/delete only. It doesn't grant
VM lifecycle, network, disk, role-management, or subscription permissions.

```hcl
module "vm_task_host" {
  source = "./modules/vm-task-host"
}

resource "azurerm_linux_virtual_machine" "gpu" {
  # VM image, size, network, identity, and naming stay caller-owned.
  custom_data = module.vm_task_host.cloud_init_base64
  tags        = merge(local.tags, module.vm_task_host.inventory_tags)
}

module "vm_task_rbac" {
  source = "./modules/vm-task-rbac"

  virtual_machine_id    = azurerm_linux_virtual_machine.gpu.id
  executor_principal_id = module.identity.principal_id
}
```

## Standard Output Contract (per module)

Every module exposes a **canonical output shape** so `main.tf` can compose modules without
branching on which alternate was picked. Each module returns as few of these fields as its
concern requires; missing fields are unset, not defaulted, so a downstream consumer either
uses them or does not.

| Output | Shape | Example |
|--------|-------|---------|
| `endpoint` | string | `evhns-fdai.servicebus.windows.net:9093` |
| `identity_resource_id` | string | Azure resource id of a managed identity |
| `identity_principal_id` | string | OID of the same identity (for role assignments) |
| `secret_ref_envelope` | object | `{ vault_name, secret_name, key_vault_reference }` |
| `topics` | list(string) | day-zero: `["aw.change.events", "aw.dr.events", "aw.finops.events"]` |
| `connection_string_ref` | string | pointer to a Key Vault secret; **never the raw value** |
| `log_workspace_id` | string | Log Analytics workspace resource id |
| `log_workspace_customer_id` | string | Log Analytics workspace customer GUID (auto-wired into the core app for metric KQL and the read API for bounded Command Deck KQL as `FDAI_MONITOR_WORKSPACE_ID`) |
| `admin_group_object_id_ref` | string | env-var name that carries the Entra group OID |

Values are always **references**, never raw secrets: any `*_ref` field points at a Key Vault
secret or an env-var name whose value the app resolves at runtime via the injected
`SecretProvider` - see
[csp-neutrality.md § Secret Contract](../docs/roadmap/architecture/csp-neutrality.md#3-secret-contract--environment--k8s-secret).

## Opt-in variables (metric analyzer tick + Prometheus)

The reference threshold analyzers ([src/fdai/core/investigation/analyzers.py](../src/fdai/core/investigation/analyzers.py))
never fire on their own - a periodic tick has to invoke them. The tick is an
opt-in Container Apps Job (mirroring the scheduler tick pattern) driven by
these root-level variables; the whole thing stays dormant until the fork
supplies a cron expression. Full latency analysis:
[docs/roadmap/rules-and-detection/observability-and-detection.md](../docs/roadmap/rules-and-detection/observability-and-detection.md).

| Variable | Type | Purpose |
|----------|------|---------|
| `analyzer_tick_cron_expression` | string | Cron for the tick job. Empty (default) leaves it unprovisioned. Recommended: `"* * * * *"` (every minute). |
| `analyzer_targets_json` | string | JSON array of `{"resource_id", "kind"}` pairs. `kind` MUST be one of `aks_cluster` / `mysql_flexible_server` / `azure_openai` / `application_gateway` / `api_management`. Empty -> the CLI logs `no targets` and exits 0, so a mis-provisioned cron stays quiet. |
| `analyzer_window_seconds` | string | Look-back window per analyzer per tick. Empty -> CLI default (300 s). |
| `analyzer_budget_seconds` | string | Coordinator time budget; over this the outcome is `BUDGET_EXCEEDED`. Empty -> CLI default (60 s). |
| `prometheus_endpoint` | string | Base URL of a Prometheus-compatible query API (AKS Managed Prometheus data-collection endpoint, self-hosted Prom, Thanos, Cortex, Mimir). When set alongside a Log Analytics workspace, `wire_azure_container` builds a **RoutedMetricProvider**: Prom serves its declared metrics (AKS-scoped: `node_cpu_percent`, ...) and AML fills the rest of the 14-metric analyzer catalog. Prom-only or AML-only cases keep the single-backend binding. |
| `prometheus_audience` | string | OIDC audience for the Prometheus bearer token. AKS Managed Prometheus with AAD requires `https://prometheus.monitor.azure.com`. Empty -> unauthenticated Prom. |

**Latency envelope with these enabled:**

- AKS-scoped metrics (`node_cpu_percent`, ...) with `prometheus_endpoint` wired:
  ~15-60 s (Prom scrape + tick cadence).
- Non-AKS resources (App Gateway, MySQL, Azure OpenAI, APIM): ~2-5 min
  (Azure Monitor Logs KQL ingestion floor - not a tunable).
- Event-based paths (`KubeEvents`, Activity Log, forwarded diagnostics via
  the Kafka bus): unchanged, sub-second (already event-driven).

Azure resource writes and deletes use a dedicated `aw.inventory.raw` Event Hub.
A subscription-scoped Event Grid subscription delivers with the inventory
user-assigned managed identity, while Event Hubs local authentication remains
disabled. The core normalizes that raw stream into the canonical change topic
for Huginn. The Inventory Container Apps Job still performs the complete
ARG/ARM reconciliation every six hours by default.
Terraform exposes primary and auxiliary Event Hub names separately through
`event_bus_topics` and `event_bus_auxiliary_topics`; local runtime preparation
uses the auxiliary output to bind `FDAI_INVENTORY_RAW_TOPIC` only after that
topic is present in the applied state.

See [envs/dev.tfvars.example](envs/dev.tfvars.example) for the full commented example.

## Naming

Every resource name follows the CAF convention in
[deploy-and-onboard.md § Resource Naming Convention](../docs/roadmap/deployment/deploy-and-onboard.md#resource-naming-convention).
The workload token is the fixed literal `fdai`; the default resource group is
`rg-fdai`. Modules MUST NOT compute names from a random string or a subscription
hash - a rename is a Terraform diff, not a mystery.

## Implemented layout

The `modules/` directory contains the Azure day-zero resource seams, and `envs/` contains
parameter examples for development, staging, and production. The ops/hub bootstrap for
private-everything tenants lives under `bootstrap/`. Keep this README and the deployment
roadmap synchronized whenever a module, environment parameter, or bootstrap stage changes
([coding-conventions.instructions.md § Documentation Workflow](../.github/instructions/coding-conventions.instructions.md#documentation-workflow)).

## Security scan baseline

`infra-lint.yml` runs Trivy and Checkov as blocking checks. `infra/.checkov.baseline` records
the reviewed day-zero detected issues that depend on a production-only setting, an external Azure
control, or an intentionally retained development path. The baseline is technical debt, not
proof that a detected issue is fixed: each production-relevant item remains covered by the ARB
blockers and `production-gates.tf`. A new detected issue fails CI. Removing or hardening a resource
also removes its baseline entry; do not regenerate the whole file to absorb a new failure.

The only Trivy inline exception is the Key Vault module's public development path. The
production Terraform gate requires private networking, disables public access, and sets the
vault network default to deny, so the exception cannot authorize a production plan.
