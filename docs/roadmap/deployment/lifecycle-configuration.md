---
title: Lifecycle Configuration
---
# Lifecycle Configuration

This document defines how an installation's desired lifecycle configuration is authored, layered,
packaged, and delivered to a Lifecycle Hub. It also keeps that configuration separate from
customer identifiers, secrets, policy, and authority. It owns the value classes, the configuration
layers, and the signed configuration package.

> **Status:** Design only. No configuration package, sealed value, or configuration schema
> annotation exists yet. The
> [implementation ledger](../../roadmap-implementation/deployment/lifecycle-configuration.md)
> tracks delivery.
>
> **Scope:** [Hub-Managed Lifecycle](hub-managed-lifecycle.md) owns how the Hub uses this
> configuration. [Operator Governance Profiles](../decisioning/operator-governance-profiles.md)
> owns approval and admission policy, which are never configuration.

## Design at a glance

| Concern | Decision |
|---------|----------|
| Source of truth | A customer-owned Git repository. A reviewed merge is the change request. |
| Delivery | One signed configuration package per merged revision. It carries the full revision and names its predecessor. |
| Layers | Release defaults, then Environment Config, then Entity override blocks per Release version range |
| Missing override | A Release without a matching override block isn't deployed |
| Customer identifiers | Sealed to the installation key. The Hub stores only ciphertext and digests. |
| Secrets | Key Vault references only. Managed identities replace credentials wherever Azure allows it. |
| Authority | Never configuration. Policy revisions and the promotion registry own it. |

## Value classes

Every value an installation needs belongs to exactly one class. The class decides who owns it,
where it lives, how it changes, and what the Hub can see.

| Class | Examples | Owner | Stored in | Changed through | Hub sees |
|-------|----------|-------|-----------|-----------------|----------|
| Lifecycle configuration | Region, channel, windows, sizing, replicas, model capacity type, integration kinds | Customer | Customer Git, then the configuration package | Reviewed merge | Value |
| Sealed identifier | Tenant ID, subscription ID, resource names, endpoint URLs, client IDs | Customer | Sealed section of the package | Reviewed merge | Ciphertext and digest |
| Secret reference | Name of a Key Vault secret for an API key or integration token | Customer | Package for the name, Key Vault for the value | Merge for the name, Key Vault for the value | Name only |
| Policy revision | Approval policy, admission (OPA/Rego) policy | Installation operators | Installation PostgreSQL | Console policy administration | Digest only |
| Authority state | Promotion state, standing authorizations, kill switch, approval profile | Installation governance | Installation stores | Governed authority paths | Digests and counts |
| Runtime state | Reported state, receipts, operational data | Installation | Installation | Not configurable | Lifecycle metadata only |

Each configuration key in a Release's configuration schema declares its
[ADR-0002](../architecture/decisions/0002-independent-runtime-axes.md) axis and owner through
`x-fdai-axis` and `x-fdai-owner` annotations. The packager rejects a key without both annotations.
It also rejects any key on an authority axis, such as action lifecycle, approval profile,
authorization policy, or standing authority.

## Where common items belong

| Item | Class | Where it lives | Notes |
|------|-------|----------------|-------|
| Azure region | Configuration | Environment Config | Feeds the data-residency constraint |
| Subscription ID | Sealed | Environment Config, sealed section | The installation also proves it from its own binding |
| Resource group | Sealed | Environment Config, sealed section | Names follow [resource conventions](deployment-resource-conventions.md) |
| Model endpoint | Sealed | `endpoint_ref` in the model binding, resolved inside the installation | The Hub never sees the URL |
| Model and deployment name | Configuration | Model binding | Not a secret |
| PTU | Configuration | Model binding with capacity kind `ptu` and a unit count | The Settings model inventory confirms it |
| Tenant ID | Sealed | Environment Config, sealed section | An identifier, not a secret |
| Client ID | Sealed | Entity override block | Prefer a managed identity with no client secret |
| Client secret | Secret | Avoid it. If an integration requires one, store it in Key Vault and reference it by name. | The customer rotates it |
| API key | Secret | Key Vault secret referenced by name | Runtime T1 and T2 model bindings use Microsoft Entra ID, not keys |
| Database connection | Derived | Built inside the installation from a managed identity and a private endpoint | Service-owned DSNs keep no password |
| ITSM endpoint | Sealed | Integration binding | Its credential is a separate secret reference |
| OPA policy | Policy revision | Installation policy store through FDAI Console | The Release ships the baseline |
| Approval policy | Policy revision | Installation policy store through FDAI Console | The approval profile inside it is authority state |

## Configuration layers

The installation resolves its effective configuration in this order:

1. **Release defaults:** The configuration schema and default values that ship inside the signed
   Release.
2. **Environment Config:** Values that apply to the whole installation, such as region,
   residency, network profile, and model bindings. Installation settings, such as the channel,
   version range, maintenance windows, and Entity list, travel in the same package.
3. **Entity override blocks:** Values for one Entity and one Release version range. The most
   specific range that contains the target Release wins, as in
   [Apollo config overrides](https://www.palantir.com/docs/apollo/managing-entities/set-config-overrides).
   An Entity override can reference an Environment Config key.

A later layer replaces a key from an earlier layer. The packager validates the result against
the target Release's configuration schema and rejects unknown keys, authority keys, and sealed keys
outside the sealed section. When no override block covers a Release's major version, that Release
isn't deployable for the Entity. This rule lets a customer decide in advance which major versions
it accepts.

The initially proposed five layers map onto this model as follows:

| Proposed layer | Where it goes |
|----------------|---------------|
| Product defaults | Release defaults |
| Environment configuration | Environment Config and installation settings |
| Customer policy | Policy revisions, never configuration |
| Entity configuration | Entity override blocks |
| Runtime override | Commands with an expiry, not a configuration layer |

## Customer Git and configuration packages

The customer keeps one directory per installation in its own Git repository:

```text
installations/<installation-id>/
  installation.yaml   # channel, version range, maintenance windows, Entities
  environment.yaml    # Environment Config values that the Hub may read
  sealed.yaml         # identifiers and endpoints, sealed during packaging
  entities/
    core.yaml         # Entity override blocks by Release version range
```

The repository stays inside the customer's control, so `sealed.yaml` can hold readable values
there. Sealing protects those values from the Hub, not from the customer.

1. A reviewed merge to the protected branch starts packaging in the customer's pipeline or
   through `fdaictl`.
2. The packager validates every layer, encrypts the sealed section to the installation's public
   key from enrollment, and records the revision ID, Git commit, predecessor digest, and content
   digests.
3. The customer configuration key signs the package.
4. The package is uploaded to the Hub, or carried inside an upgrade bundle for an offline Target
   Hub.
5. The Hub verifies the signature and the predecessor digest. A missing or forked revision blocks
   the import until the gap is resolved.
6. The Hub recomputes Plans. Installation agents verify the signature again and decrypt sealed
   values only inside the installation.

A configuration rollback is a revert commit that produces a new revision. An older package is
never imported again as the current revision. A break-glass change is reconciled to the approved
revision when it expires, unless a merged change adopted it.

## Secrets

- Secret values never enter Git, configuration packages, the Hub, Plans, logs, or command lines.
- Managed identities and workload identity federation replace client secrets for Azure access.
- An unavoidable third-party secret lives in the installation's Key Vault. Workloads read it
  through the Key Vault CSI driver with workload identity, as the existing runtime does.
- The customer rotates secrets in Key Vault. Rotation doesn't create a configuration revision, and
  reported state shows only whether each reference resolves.
- Apollo creates Kubernetes secrets through Plans
  ([Apollo secrets](https://www.palantir.com/docs/apollo/managing-secrets/add-edit-delete-secrets)).
  FDAI deliberately doesn't, so the Hub never carries a secret value.

## Policy and authority aren't configuration

- Approval policy and admission policy revisions are authored in FDAI Console under
  [Operator Governance Profiles](../decisioning/operator-governance-profiles.md) and stay inside the
  installation.
- Promotion state, standing authorizations, the kill switch, and the approval profile change only
  through their governed authority paths.
- The Hub sees only digests of policy and authority state in reported state. A Release may declare
  a maximum mode for an ActionType, and no policy revision can exceed it.

## Examples

These examples use placeholders. Customer A runs an online Target Hub in Korea Central with PTU
capacity and in-country processing:

```yaml
# installations/<customer-a-installation>/installation.yaml
hub: target-hub-online
channel: RELEASE
version_range: ">=1.5.0 <2.0.0"
maintenance_windows:
  downtime: "Sun 02:00-04:00 Asia/Seoul"
  no_downtime: "daily 01:00-05:00 Asia/Seoul"
entities: [core, operator-api, document-ingestion-api, document-processing-worker,
           isolated-executor, console]
```

```yaml
# installations/<customer-a-installation>/environment.yaml
region: koreacentral
data_residency:
  processing_scope: geography       # geography | data-zone | global
network:
  profile: private-endpoints-only
model_bindings:
  diversity_policy: same-publisher-distinct-models
  primary:
    provider: azure-openai
    deployment_type: ProvisionedManaged
    capacity: { kind: ptu, units: 100 }
    endpoint_ref: model-primary
  secondary:
    provider: azure-openai
    deployment_type: ProvisionedManaged
    capacity: { kind: ptu, units: 50 }
    endpoint_ref: model-secondary
integrations:
  itsm:
    endpoint_ref: itsm-primary
    credential_ref: itsm-token      # Key Vault secret name
```

```yaml
# installations/<customer-a-installation>/sealed.yaml
tenant_id: 00000000-0000-0000-0000-000000000000
subscription_id: 00000000-0000-0000-0000-000000000000
resource_group: <customer-a-application-rg>
endpoints:
  model-primary: https://model-primary.example.com
  model-secondary: https://model-secondary.example.com
  itsm-primary: https://itsm.example.com
```

```yaml
# installations/<customer-a-installation>/entities/core.yaml
overrides:
  - versions: ">=1.5.0 <2.0.0"
    values:
      replicas: 2
      resources: { cpu: "2", memory: 4Gi }
```

Customer B uses a central Hub cell in East US, subscribes to `RELEASE_CANDIDATE`, sets
`processing_scope: global` with Standard pay-as-you-go capacity, and keeps the default
`mixed-publisher` diversity policy. Customer C pins `version_range: ">=1.4.0 <1.5.0"` and binds a
`self-hosted` provider through an `apim-gateway` route with capacity kind `gpu`.

## Configuration data model

| Table | Key | Purpose | Time fields | Mutability |
|-------|-----|---------|-------------|------------|
| `configuration_revision` | `installation_id`, `revision_id` | Git commit, predecessor digest, package digest, signer key | `committed_at`, `imported_at`, `recorded_at` | Append-only |
| `installation_settings` | `revision_id` | Channel, version range, windows, Entity list | Inherits the revision | Immutable per revision |
| `environment_config_value` | `revision_id`, `key` | Value, axis, and owner annotation | Inherits the revision | Immutable per revision |
| `sealed_value` | `revision_id`, `key` | Ciphertext reference and digest | Inherits the revision | Immutable per revision |
| `entity_override_block` | `revision_id`, `entity_id`, `version_range` | Override values and digest | Inherits the revision | Immutable per revision |
| `package_import` | `import_id` | Source, such as upload or bundle, and the verification result | `imported_at` | Append-only |

## Honest limits

- Nothing in this document is implemented yet.
- Releases don't carry configuration schemas with axis and owner annotations yet.
- No packaging command exists. Onboarding for the customer configuration key needs its own
  runbook.
- A customer who loses the configuration key can't publish new revisions until a key rotation
  is registered with the Hub.

## Related docs

| To learn about | Read |
|----------------|------|
| Lifecycle architecture and Plans | [Hub-Managed Lifecycle](hub-managed-lifecycle.md) |
| Releases, channels, and bundles | [Lifecycle Releases and Channels](lifecycle-releases-and-channels.md) |
| Approval and admission policy | [Operator Governance Profiles](../decisioning/operator-governance-profiles.md) |
| Model bindings, capacity, and diversity | [Model Capability Lifecycle](../architecture/model-capability-lifecycle.md) |
| Decision record | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/lifecycle-configuration.md) |
