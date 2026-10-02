---
title: Deployment Resource Conventions
---
# Deployment Resource Conventions

This document defines the resource naming and tagging conventions for infrastructure that FDAI
provisions. Use it to keep Terraform plans deterministic, resource ownership queryable, and
deployment-specific values outside the upstream distribution.

> This contract applies to provisioned infrastructure. Runtime code consumes resource identifiers
> through configuration and does not compute names or ownership tags.

The Teams A1 approval bot is provisioned by the reusable `infra/modules/teams-a1-approval-bot`
module, which creates a dedicated non-executor user-assigned identity, the Azure Bot, and the Teams
channel registration, and returns the `teams_approval_destination` contract values. The
group-connected team id, channel id, and Operator activity endpoint stay human-supplied inputs
because the azurerm provider cannot create them.

## Foundation and application plan boundary

New-subscription bootstrap derives the ops resource group, application resource group, and state
storage account names before the first private runner exists. `fdaictl provision
bootstrap-reconcile` binds those names to the reviewed profile and source commit, pins every Azure
management-plane read to the verified subscription, and writes only a private expiring plan. It
does not register providers, create resources, write Terraform state, or dispatch a workflow.

The separately approved foundation phase owns creation of the private `tfstate` and
`deployment-plans` containers and the remote-state handoff. Application plan-only execution treats
both containers as prerequisites and stops when either is absent. It never creates foundation
resources as an incidental planning side effect.

Foundation resources also declare the settings a tenant policy may attach at creation, so the
post-apply plan can be zero-change. The operations public IPs accept policy-owned `ip_tags`, and the
runner virtual machine declares its guest patch mode and platform-safety-check bypass. Each is an
exact observed input rather than a default: an empty selection preserves provider behavior, and an
unsupported value stops the run instead of being adopted. Without these declarations a subscription
that tags every public IP, or a tenant that enforces platform-managed patching, could never converge
a fresh installation.

The bootstrap host's ephemeral OS disk uses `ReadOnly` caching, as required by AzureRM for
`diff_disk_settings`. Scoped role-definition identifiers are reduced to their GUID component before
ABAC `GuidEquals` comparison; the observation delegate retains only Cost Management Reader,
Monitoring Reader and Reader for `ServicePrincipal` subjects on both write and delete. A failed
partial apply retains its state and claims; use the bounded recovery contract in
[Installable Deployment CLI](installable-deployment-cli.md), never repeat the claimed apply.

Application feature inputs describe the desired platform state during a full plan. Monitoring uses
the bounded `module.monitoring` target only when it is the sole selected feature; when combined with
application features, it remains enabled and participates in the complete non-destructive plan.
The operational-history-only plan includes the application resource group's historical moved
address so Terraform can reconcile that no-op state transition before evaluating only the history
storage, private endpoint, lifecycle Job, and exact internal ownership-marker targets. During deployer identity migration, the
module preserves the previous data-owner assignment and adds the stable runner assignment at a
separate address. Replacing either assignment remains a destructive plan and is blocked.
The dev operations gateway target set includes that same moved resource-group address before its
gateway, runtime, identity, and role targets, so a protected image update can reconcile the state
move without widening to an untargeted destructive plan.
The compute target closure also includes its existing out-of-band and rule-watcher Jobs before
Terraform evaluates the selected measurement runners.
The protected Console release workflow binds an exact CI-verified Core image, updates the existing
catalog materialization Job with rollback, runs schema migration, and verifies the selected
revision's immutable Rule and Ontology projections through PostgreSQL readback before publishing the
matching Console artifact. One shared request workflow validates an allowlisted operation and the
exact revision, then dispatches either Console publication or catalog refresh with the repository
automation identity. The same request boundary can dispatch only the exact protected RCA reader
apply or verification-resume coordinates, or one unexpired Core model-binding service plan, after
verifying the Environment policy. The Core path fixes the service and transition mode before
dispatch and validates the exact run, attempt, digests, image, and artifact metadata. `fdaictl`
routes the exclusive RCA apply through that request boundary. A still-valid plan remains eligible when
unrelated commits advance `main` only if its revision remains an ancestor and the protected request
controls remain identical. The human maintainer can then approve that bot-owned deployment without
enabling self-review or administrator bypass.

The alert-noise qualification prerequisite is a separate dev-only target, not part of broad
monitoring. It creates exactly `ag-<workload>-noise-pilot-<env>-<region>` and
`alert-<workload>-noise-pilot-<env>-<region>` against the existing
`ca-<workload>-<env>-<region>-core` Container App `Replicas` metric. The target is derived
internally instead of accepted as an arbitrary resource ID. The recipient remains in owner-only
deployment configuration. The pilot doesn't change the Core app or read application data,
credentials, connection strings, or Key Vault content. Baseline, treatment, recovery, and cleanup
plans are independently scope-checked before any local apply. The operator confirms each local
deployment plan. That confirmation and the Terraform records are not Var approval, FDAI runtime
authority, effect evidence, or promotion evidence. Shared or production alert changes retain their
normal runtime quorum.

The A3-E evidence target is a separate development-only Terraform root. It references an existing
protected holding resource group and owns only its private network, single VM, two identities, and
target-scoped roles in a separate state. Names use the `fdai-a3e-<env>-<region>` suffix while the
subscription, holding group, actor, region, SKU, exact image version, expiry, address space, and SSH
public key remain protected deployment inputs. The executor role permits only VM read, start, and
deallocate; the observer receives Reader on the same VM. The subnet and VM NIC both bind the
egress-deny NSG, and VM extension operations remain disabled. A value-blind gate accepts only the
exact create set. Apply, initial deallocation, campaign effects, rollback, and cleanup remain
separately approved stages.
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

### Region token design and critique

**Initial design:** Derive unknown Azure region tokens by truncating the region name to five
characters.

**Critique:** Truncation is not a naming contract. It maps distinct public regions to the same
token, such as `westus` and `westus3` both becoming `westu`, and can direct two installations in
one subscription to the same resource groups. It also makes a new Azure region look supported
without a reviewed token.

**Revised contract:** New installations use only the reviewed Azure public-region token table in
`azure_naming.py`. A region missing from that table fails before any Azure effect. Existing
installations keep the token recorded in retained Foundation variables and profiles; a
same-work-directory continuation never recomputes it from the new table. When a run starts without
retained state, the coordinator performs read-only resource-group discovery for the same
subscription, environment, workload, and Azure location before planning. It reuses the single
matching token from FDAI-owned tags and names, or from the explicit `fdai:region-token` tag when
future installations record it. Discovery fails closed when more than one candidate token exists.
No automatic rename or migration is performed.

The Operator API uses `operator-api` as its physical component. Its workload identity is named
`id-<workload>[-<env>][-<region>]-operator-api`, and its Container App is named
`ca-<workload>[-<env>][-<region>]-operator-api`. The legacy `readapi` token is valid only in
historical Terraform `moved` addresses and retained evidence. An existing deployment replaces the
physical resources through a reviewed protected plan; it does not rename them in place.

The disposable A3-E target uses `fdai-a3e-<env>-<region>` after each CAF prefix. Its executor and
observer identities append `-executor` and `-observer`. The root references its holding resource
group instead of naming or owning a new group, and deployment values remain outside source control.

The default **resource group** is `rg-fdai` (fixed by user directive). Everything the
system provisions lives under that RG unless a resource type requires a subscription-scope
placement (none today).

### Event Bus product topic namespace

An Event Bus topic that uses the FDAI product namespace starts with `fdai.` and follows
`fdai.<domain>.<purpose>`. Current examples include `fdai.change.events`,
`fdai.pantheon.objects`, and `fdai.pipeline.stages`. A dead-letter entity appends `.dlq` to the
complete topic name, such as `fdai.change.events.dlq`.

Terraform owns provisioned topic names and passes them to each runtime through configuration.
Application defaults support local startup and must match the Terraform-selected names; they do
not create a second naming authority. The undocumented `aw.` product prefix is legacy and is not
accepted in an active topic default or new infrastructure declaration. Historical evidence keeps
the exact `aw.*` name that was observed so a later rename cannot rewrite a prior validation claim.

This product-prefix rule does not rename contract-specific `runtime.*`, `object.*`, `operator.*`,
or `core.*` topics, nor does it apply to SSE channels, OpenTelemetry keys, Entra groups, or chat
commands. Changing a provisioned Event Hub entity name is a replacement, not an in-place rename.
A deployment therefore uses a protected plan and exact apply, verifies every role scope and
producer/consumer binding, drains or expires retained records on the old entity, and records
post-apply transport evidence before deleting the old path.
An explicitly approved, non-authoritative development backlog may instead be discarded when the
exact apply deletes the legacy entities.
The one-time migration controls are retired after the validated cutover. Current platform and
service plans accept only canonical `fdai.*` bindings. The three historical Terraform `moved`
blocks only resolve older state addresses; they neither provision legacy topics nor plan recurring
replacement work after state reaches the canonical keys.

### CAF prefixes for the day-zero inventory

| Resource | CAF prefix | Char rules | Example name |
|----------|------------|------------|--------------|
| Resource Group | `rg-` | 1-90; alphanumerics + hyphens/underscores | `rg-fdai` |
| User-assigned Managed Identity | `id-` | 3-128 | `id-fdai-executor` |
| Container Apps environment | `cae-` | 2-32; alphanumerics + hyphens | `cae-fdai` |
| Container App (core) | `ca-` | 2-32 | `ca-fdai-core` |
| Container Apps Job (out-of-band) | `caj-` | 2-32 | `caj-fdai-oob`, `caj-fdai-browser-gc` |
| Virtual Network | `vnet-` | 2-64 | `vnet-fdai-a3e-dev-wus2` |
| Subnet | `snet-` | 1-80 | `snet-fdai-a3e-dev-wus2` |
| Network Security Group | `nsg-` | 1-80 | `nsg-fdai-a3e-dev-wus2` |
| Virtual Machine | `vm-` | 1-64 | `vm-fdai-a3e-dev-wus2` |
| Virtual Machine Scale Set | `vmss-` | 1-64 | `vmss-fdai-ohl-dev-krc` |
| Event Hubs namespace | `evhns-` | 6-50 | `evhns-fdai` |
| PostgreSQL Flexible Server | `psql-` | 3-63; lowercase | `psql-fdai` |
| Key Vault | `kv-` | 3-24; alphanumerics + hyphens | `kv-fdai` |
| **Container Registry (ACR)** | `cr` | 5-50; **alphanumeric only, no hyphens** | `crfdai` |
| Log Analytics workspace | `log-` | 4-63 | `log-fdai` |
| Azure Monitor alert / action group | `alert-` / `ag-` | 1-260 / 1-260 | `alert-fdai-event-bus-consumer-lag`, `ag-fdai` |
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
- **Fresh public contributor deployments** set `resource_name_suffix` to a stable six-character
  lowercase hash of the verified subscription. Terraform appends it only to globally scoped
  registry, vault, event-bus, database, communication, and AI account names. The empty default
  preserves every existing deployment name and avoids an in-place rename.
- **Static Web Apps use their hosting region suffix.** The design-mocks resource includes the
  `design-mocks` component and the Static Web Apps region, for example
  `stapp-fdai-design-mocks-dev-ea`. This region can differ from the control-plane region because
  Static Web Apps is not available in every Azure region.
- If a legal name exceeds the character limit after adding env/region/instance, use the
  documented short-name `aip` in place of `fdai` - and only for that resource kind.
  Do not sprinkle `aip` where the full name still fits.
- **Key Vault preserves every legal existing name.** When the complete candidate exceeds 24
  characters, Terraform uses `kv-aip-<8hex>`, where `<8hex>` is the stable SHA-256 prefix of the
  complete candidate including workload, environment, region and global suffix.
- The browser-evidence cleanup Job uses the short component `browser-gc`, so the longest allowed
  `caj-fdai-staging-<region>-browser-gc` form remains at or below 32 characters.

### What this rule prevents

- **Random suffixes**: A short deterministic hash is allowed where globally unique names
  require it, such as Storage or a fresh public contributor deployment. A suffix that changes on
  every plan blocks review.
- **Customer names or environment values in the identifier**: These values belong in
  `*.tfvars` and the tag map, not in the resource name.
- **Inline naming logic in Python**: The app reads identifiers from environment variables;
  `infra/` decides names at plan time.

## Terraform State Root Convention

Reusable modules declare their own compatibility floor instead of inheriting an accidental
provider choice from the caller. Azure resource modules require Terraform `>= 1.9` and AzureRM
`~> 4.14`; provider-free rendering modules declare the Terraform floor only. A provider major
upgrade therefore requires an explicit module contract change and independent validation.

Every production Terraform root has one stable root id, one environment-scoped backend key, and
one scheduled drift plan. The deployment contract currently contains seven roots:

| Root class | Count | Backend key pattern |
|------------|-------|---------------------|
| Legacy platform | 1 | `fdai-<environment>.tfstate` |
| Independent service | 5 | `services/<service>/<environment>.tfstate` |
| Ops bootstrap | 1 | `ops/bootstrap/<environment>.tfstate` |

The first bootstrap apply may use local state only while it creates the private backend. After
migration, the remote bootstrap key is authoritative. Adding a production root without a unique
backend key and drift-plan coordinate is not supported. Drift checks fail when evidence is missing
or unreadable; they never omit a registered root and report success.

The Core and Operator service roots receive the semantic-turn request and projection topic names
as environment-scoped Terraform inputs. Terraform passes the reviewed names through
`FDAI_SEMANTIC_TURN_REQUEST_TOPIC` and `FDAI_SEMANTIC_TURN_PROJECTION_TOPIC`; application code does
not derive, rename, or substitute these cross-service channels. Each Container App receives each
name once, so a legacy literal cannot shadow the Terraform-selected topic.
The root variable and its child service module declare the same optional `semantic_requests` and
`semantic_projections` fields. They also declare `semantic_physical`, the provisioned Event Hub
that carries both logical topics. The default physical topic is `fdai.pantheon.objects`, whose
existing logical-topic envelope and `.dlq` sibling preserve schema isolation, stable partition
keys, per-logical-topic hashed consumer groups, and dead-letter routing without consuming another
Event Hubs entity. The logical request and projection names remain distinct contract and
configuration values; neither becomes a standalone Azure Event Hub. Both independent roots must
pass `terraform validate` before state migration or a protected plan; a root-only field that the
child module drops is a deployment contract failure, not an optional runtime degradation.
Local runtime preparation carries the same bootstrap, logical names, and physical-topic marker into
the independent Operator environment; a partial triplet stops before either service starts.
Operator and document-ingestion migration Jobs each accept a separate digest-pinned migration
image. Empty values preserve the corresponding service image for compatibility; protected deploys
bind reviewed migration digests so schema advancement does not depend on runtime image cadence.
Core service input materialization removes empty optional platform endpoint outputs before
validating that every active model binding has an exact provider endpoint.

The Operator App image and its one-off schema migration image are independently digest-pinned.
The migration image must contain the database's current Alembic revision set; an unset migration
image falls back to the App image only for backward compatibility, not as a promotion shortcut.

The Operator module also declares `caj-<workload>-catalog` as a separate manual Container Apps Job.
It uses the digest-pinned Core image that owns the reviewed Rule and Ontology catalogs. The deploy
workflow binds an explicitly selected Core source revision independently of the isolated Executor,
then starts the catalog Job only after `caj-<workload>-migrate` succeeds. Both Jobs use the Operator
managed identity and PostgreSQL secret reference, but catalog materialization creates reference
projections only; it does not create detected runtime issues, readiness, or execution authority.

After Core state ownership moves to `services/core-control-plane/<environment>.tfstate`, the
legacy platform root retains the shared Container Apps environment and scheduled Jobs but no
longer declares the Core Container App resource. Its deterministic Core name remains available for
health and effect checks, and monitoring constructs the live ARM id from that name. The historical
source address remains only in the state-migration manifest and the legacy-plan guard. A platform
plan that proposes any create, update, replacement, or delete at that address is blocked.

The legacy platform root may retain the isolated Executor wrapper only as a rollback-compatible
deployment surface. That wrapper binds both `service_distribution` and `service_entrypoint` to
`fdai-isolated-executor-service`; empty or co-located Core values fail the module precondition before
a plan can be approved. After all five runtime state moves, every legacy Container App resource is
inactive while the Operator and ingestion migration Jobs remain legacy-state owned. Deployment
verification reads the independent Apps' live FQDNs from Azure by deterministic name; it never
reintroduces their resources into the platform state.

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
| `fdai:region-token` | reviewed short token such as `wus3`, or a retained legacy token such as `westu` | Foundation variables / Terraform input | Explicit naming token for future discovery. Older installations may lack this tag; discovery then parses FDAI-owned resource group names and fails closed on ambiguity. |
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
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/deployment-resource-conventions.md) |
| The concrete resource inventory and bootstrap sequence | [Deploy and Onboard](deploy-and-onboard.md) |
| The deployment lifecycle and environment model | [Deployment](deployment.md) |
| Customer-agnostic deployment configuration | [Customer-Agnostic Scope](../../../.github/instructions/generic-scope.instructions.md) |
