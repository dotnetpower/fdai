# `infra/`

Infrastructure as Code - Terraform (HCL).

Renders the four CSP-neutrality contracts (event bus / runtime / secret / workload
identity) into Azure resources. Entry command: `terraform apply` per
[docs/roadmap/deployment/deploy-and-onboard.md](../docs/roadmap/deployment/deploy-and-onboard.md).

## Turnkey path (`azd`)

For a one-command experience, [`azure.yaml`](../azure.yaml) drives this Terraform
through the Azure Developer CLI. `scripts/azd-up.sh` (or `make azd-up`) runs a
non-mutating `azd provision --preview` by default; set `FDAI_AZD_CONFIRM=1` to
run a real `azd up`. The two-gate design keeps an accidental apply impossible.

`azure.yaml` also declares a `services.core` block so `azd deploy` / `azd up`
builds the app image from the [`Dockerfile`](../Dockerfile) and deploys it to the
Container App tagged `azd-service-name: core` (set in
[`modules/compute/container-apps/main.tf`](modules/compute/container-apps/main.tf)).
A `services` block only drives `azd deploy`; `azd provision --preview` is
unaffected.

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
| `log_workspace_customer_id` | string | Log Analytics workspace customer GUID (auto-wired into the core app as `FDAI_MONITOR_WORKSPACE_ID` so the metric adapter binds) |
| `admin_group_object_id_ref` | string | env-var name that carries the Entra group OID |

Values are always **references**, never raw secrets: any `*_ref` field points at a Key Vault
secret or an env-var name whose value the app resolves at runtime via the injected
`SecretProvider` - see
[csp-neutrality.md § Secret Contract](../docs/roadmap/architecture/csp-neutrality.md#3-secret-contract--environment--k8s-secret).

## Naming

Every resource name follows the CAF convention in
[deploy-and-onboard.md § Resource Naming Convention](../docs/roadmap/deployment/deploy-and-onboard.md#resource-naming-convention).
The workload token is the fixed literal `fdai`; the default resource group is
`rg-fdai`. Modules MUST NOT compute names from a random string or a subscription
hash - a rename is a Terraform diff, not a mystery.

## What is NOT here yet

The `modules/` and `envs/` directories are **planned**, not created. Scaffolding lands with
Phase 0 W4.1 (Terraform bootstrap modules). Adding files under `infra/` before W4.1 requires
docs to move in the same PR - that is the docs-first / docs-after rule
([coding-conventions.instructions.md § Documentation Workflow](../.github/instructions/coding-conventions.instructions.md#documentation-workflow)).
