---
title: Deployment Resource Conventions
---
# Deployment Resource Conventions

This document defines the resource naming and tagging conventions for infrastructure that FDAI
provisions. Use it to keep Terraform plans deterministic, resource ownership queryable, and
deployment-specific values outside the upstream distribution.

> This contract applies to provisioned infrastructure. Runtime code consumes resource identifiers
> through configuration and does not compute names or ownership tags.

## Resource Naming Convention

Every Azure resource this repo provisions follows the **Microsoft Cloud Adoption Framework
(CAF)** abbreviation convention. Names are deterministic, deployment-agnostic, and safe to
grep for - a rename is a Terraform diff, never a hand-edit.

Pattern:

```
<caf-prefix>-<workload>[-<component>][-<env>][-<region>][-<instance>]
```

- **workload** is the fixed literal `fdai` (product name, not a customer identifier -
  allowed under [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
- **component** is added only when one resource kind is provisioned more than once
  (e.g. `ca-fdai-core` vs a future `ca-fdai-worker`).
- **env** (`dev`/`staging`/`prod`) and **region** (`krc`/`weu`/`eus`) suffixes are added only
  when the resource is deployed side-by-side; the day-zero deployment keeps names
  suffix-free.
- **instance** (`01`, `02`, ...) is added only when multiple copies exist in one env.

The default **resource group** is `rg-fdai` (fixed by user directive). Everything the
system provisions lives under that RG unless a resource type requires a subscription-scope
placement (none today).

### CAF prefixes for the day-zero inventory

| Resource | CAF prefix | Char rules | Example name |
|----------|------------|------------|--------------|
| Resource Group | `rg-` | 1-90; alphanumerics + hyphens/underscores | `rg-fdai` |
| User-assigned Managed Identity | `id-` | 3-128 | `id-fdai-executor` |
| Container Apps environment | `cae-` | 2-32; alphanumerics + hyphens | `cae-fdai` |
| Container App (core) | `ca-` | 2-32 | `ca-fdai-core` |
| Container Apps Job (out-of-band) | `caj-` | 2-32 | `caj-fdai-oob` |
| Event Hubs namespace | `evhns-` | 6-50 | `evhns-fdai` |
| PostgreSQL Flexible Server | `psql-` | 3-63; lowercase | `psql-fdai` |
| Key Vault | `kv-` | 3-24; alphanumerics + hyphens | `kv-fdai` |
| **Container Registry (ACR)** | `cr` | 5-50; **alphanumeric only, no hyphens** | `crfdai` |
| Log Analytics workspace | `log-` | 4-63 | `log-fdai` |
| Foundry account (`AIServices`) | `aif-` | 2-64; alphanumerics + hyphens | `aif-fdai-search` |
| Foundry account project | `proj-` | 2-64; alphanumerics + hyphens | `proj-fdai-search` |
| Azure Bot (HIL Adaptive Cards) | `bot-` | 2-64 | `bot-fdai` |
| Static Web App | `stapp-` | 2-40 | `stapp-fdai`, `stapp-fdai-design-mocks-dev-ea` |

### Length-safety rules

- **ACR names never contain hyphens**; the prefix `cr` is fused with the workload token
  (`crfdai`). When env/region suffixes join, do not reintroduce hyphens - use one
  continuous lowercase alphanumeric string (e.g. `crfdaidevkrc01`).
- **Storage accounts** use at most 24 lowercase alphanumeric characters. Document storage
  adds a stable six-character hash derived from subscription + environment for global uniqueness.
- **Static Web Apps use their hosting region suffix.** The design-mocks resource includes the
  `design-mocks` component and the Static Web Apps region, for example
  `stapp-fdai-design-mocks-dev-ea`. This region can differ from the control-plane region because
  Static Web Apps is not available in every Azure region.
- If a legal name exceeds the character limit after adding env/region/instance, use the
  documented short-name `aip` in place of `fdai` - and only for that resource kind.
  Do not sprinkle `aip` where the full name still fits.

### What this rule prevents

- **Random suffixes**: A short deterministic hash is allowed where globally unique names
  require it, such as Storage. A suffix that changes on every plan blocks review.
- **Customer names or environment values in the identifier**: These values belong in
  `*.tfvars` and the tag map, not in the resource name.
- **Inline naming logic in Python**: The app reads identifiers from environment variables;
  `infra/` decides names at plan time.

## Resource Tagging Convention

Naming makes a resource readable; tagging makes a fleet queryable. Every resource this
repo provisions carries a small, machine-parseable tag set. All FDAI-owned keys are
namespaced under the `fdai:` prefix so the whole set is grep-able and FDAI-provisioned
resources are unambiguous even in a **shared subscription** where other teams' resources
sit side by side. The tag map is decided in Terraform (`infra/main.tf` `base_tags`), never
computed in Python.

### Base tag set

| Tag key | Value | Source | Purpose |
|---------|-------|--------|---------|
| `fdai:managed` | `true` | constant | **Ownership marker.** The single authoritative "FDAI provisioned this" flag. `az resource list --tag fdai:managed=true` enumerates exactly what FDAI owns - the basis for blast-radius scoping, cleanup/audit cross-checks, and cost attribution. |
| `fdai:workload` | `fdai` | `var.workload` | Product/workload token; mirrors the CAF name token. |
| `fdai:env` | `day-zero` / `dev` / `staging` / `prod` | `var.env` | Environment. `day-zero` is the unqualified deployment. |
| `fdai:layer` | `control-plane` / `ops-bootstrap` | per-config | Architectural layer - the app spoke (`infra/main.tf`) vs the ops/hub bootstrap (`infra/bootstrap`). |
| `fdai:managed-by` | `terraform` | constant | Provisioning tool. |
| `fdai:vertical` | `shared` / `resilience` / `change-safety` / `cost-governance` | `var.cost_vertical` (default `shared`) | AIOps vertical the resource's cost is attributed to. Cross-vertical control-plane infra stays `shared`; per-vertical resources (e.g. the three executor MIs) override this key. |

### Why `fdai:managed` matters

The executor may run inside a subscription that also hosts resources FDAI does not own.
The ownership marker lets the control plane draw that boundary. It is the query key these
capabilities rely on, not behavior hardcoded by one script:

- **Impact scoping**: The safety invariant that an autonomous action must bound its target
  set is expressed against `fdai:managed=true`, so a fix can be constrained to resources
  FDAI created and never reach one it did not.
- **Cleanup and audit**: `terraform destroy` already removes the provisioned fleet by state.
  The marker is the out-of-band cross-check that lets a sweep or audit confirm a resource
  belongs to FDAI before it is ever considered for deletion.
- **Cost attribution**: Cost Management and Resource Graph can group spend by `fdai:vertical`
  and isolate the total FDAI footprint as the `fdai:managed=true` slice.

### Deployment-supplied tags (`additional_tags`)

Customer- and environment-specific keys are never hardcoded in `base_tags`. A deployment
supplies them through the `additional_tags` map in its uncommitted `*.tfvars`, keeping the
`fdai:` namespace:

```hcl
additional_tags = {
  "fdai:cost-center"         = "cc-1234"
  "fdai:owner"               = "team-platform"
  "fdai:criticality"         = "high"
  "fdai:data-classification" = "internal"
}
```

`additional_tags` is merged on top of `base_tags`, so a deployment can also override a base value
(e.g. pin `fdai:vertical`) without editing core.

### Per-resource overrides

A module invocation may narrow a single key with a local `merge` - e.g. the per-vertical
executor MIs set `merge(local.tags, { "fdai:vertical" = "resilience" })`. Use the same
`fdai:` namespace so a resource never carries two competing keys for one concept. Reserve
`fdai:component` for the CAF component token when one resource kind is provisioned more than
once (e.g. `core` vs `worker`), mirroring the naming convention above.

### Rules

- **Use the `fdai:` namespace for all FDAI keys**: A bare `env` or `vertical` key collides
  with other teams and defeats the grep-ability guarantee.
- **Keep customer and secret values out of `base_tags`**: These values belong in
  `additional_tags` from uncommitted `*.tfvars`, exactly like deployment-specific names.
- **Keep query values stable and lowercase**: Cost Management and Resource Graph group on
  literal values such as `true`, `dev`, and `resilience`; drift breaks aggregation.

## Related docs

| To learn about | Read |
|----------------|------|
| The concrete resource inventory and bootstrap sequence | [Deploy and Onboard](deploy-and-onboard.md) |
| The deployment lifecycle and environment model | [Deployment](deployment.md) |
| Customer-agnostic deployment configuration | [Customer-Agnostic Scope](../../../.github/instructions/generic-scope.instructions.md) |
