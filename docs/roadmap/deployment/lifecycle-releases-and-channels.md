---
title: Lifecycle Releases and Channels
---
# Lifecycle Releases and Channels

This document defines what an FDAI Release contains and how Releases move through release
channels. It also defines how connected and offline installations receive Releases, and how
recalls and database schema compatibility keep upgrades safe. It owns the Release manifest, the
channel model, upgrade bundles, and recall.

> **Status:** Design only. Today FDAI has signed deployment bundles and offline kits, and their
> signed manifests use the channel names `development`, `beta`, and `stable`. The deployment CLI
> trusts only `development`. The
> [implementation ledger](../../roadmap-implementation/deployment/lifecycle-releases-and-channels.md)
> tracks the rest.
>
> **Scope:** This document serves the [Hub-managed lifecycle](hub-managed-lifecycle.md). The
> [source deployment](source-deployment.md) and the first-installation offline package keep their
> current contracts.

## Design at a glance

| Concern | Decision |
|---------|----------|
| Release | A signed manifest of prebuilt image digests, schema range, dependencies, configuration schema, and capability maximums |
| Build once | The vendor builds each image once, and every installation runs the same digests |
| Channels | `DEV`, `RELEASE_CANDIDATE`, `RELEASE`, and custom channels |
| Subscription | Each installation subscribes to one channel, optionally with a version range |
| Upgrade | Automatic: the newest eligible Release inside a maintenance window |
| Connected delivery | Images are mirrored into a registry inside the customer boundary |
| Offline delivery | A signed upgrade bundle that an operator imports into a Target Hub |
| Recall | A Release recall triggers roll-off. A capability recall returns an ActionType or Workflow to shadow mode everywhere. |
| Catalog integrity | Signed root, snapshot, and timestamp records with increasing versions and recall sequence numbers |
| Schema | Expand/contract and forward-only. Each Release declares the schema revisions it tolerates. |

## Release contents

| Field | Content |
|-------|---------|
| `product`, `version`, `source_commit` | Product identity, semantic version, and exact source revision |
| `images` | OCI digests for Core, Operator API, Document Ingestion API, Document Processing Worker, isolated Executor, the ClamAV sidecar, the Console bundle, and both installation agents |
| `sbom`, `provenance` | Digests of the supply-chain evidence for each image |
| `schema` | `target`, the revision its migrations produce, and `tolerates`, the range of revisions its code accepts |
| `dependencies` | Supported version ranges for the Hub and both installation agents |
| `configuration_schema` | Keys, defaults, and the `x-fdai-axis` and `x-fdai-owner` annotations described in [Lifecycle Configuration](lifecycle-configuration.md) |
| `capabilities` | The maximum mode for each ActionType and Workflow, and any capability recall |
| `downtime` | Which Entities need a downtime window for this upgrade |
| `workloads` | The workload template and the schema-expand migration Job template that the lifecycle agent renders, as [Workload rendering migration](hub-managed-lifecycle.md#workload-rendering-migration) defines |
| Signature | Detached signature by the vendor release key over the canonical manifest |

An image built from a source checkout has no vendor signature and is labeled
`unverified-source-build`. Such an installation can enroll with a Hub. The Hub treats every Entity
that runs an unverified image as drifted, and the first Plan replaces those images with a signed
Release from the subscribed channel.

## Versions

- Versions are ordered semantic versions. A release candidate such as `1.5.0-rc1` orders before
  `1.5.0`, as in [Apollo versions](https://www.palantir.com/docs/apollo/core/products-releases-versions).
- A new major version is deployable only after the customer adds an Entity override block that
  covers it.
- An installation never moves to an older version unless a vendor-signed recall allows it and the
  older Release tolerates the current schema revision.

## Release channels

| Channel | Receives | Typical subscriber |
|---------|----------|--------------------|
| `DEV` | Every published build | Vendor test installations |
| `RELEASE_CANDIDATE` | Release candidates and releases | Early adopters, such as Customer B |
| `RELEASE` | Releases that passed the promotion pipeline | Production installations |
| Custom | Releases that a channel contributor adds manually or a pipeline promotes | A customer that curates eligible Releases, or a pilot group |

A promotion pipeline defines the channel order and the criteria for each stage: required labels,
such as a completed security review, soak time with healthy canary installations, product
maintenance windows, and bounded timeouts. A channel contributor can also add a Release manually,
for example to ship an incident fix, as in
[Apollo channel promotion](https://www.palantir.com/docs/apollo/core/release-channels).

A regulated customer that reviews each Release before it becomes eligible can create a custom
channel in its Target Hub and add Releases from `RELEASE` by hand. Channel membership is
eligibility curation, not installation approval. Installations that subscribe to that channel still
apply each eligible Release automatically inside their windows.

Channel names migrate one way. `development` maps to `DEV`, `beta` maps to `RELEASE_CANDIDATE`, and
`stable` maps to `RELEASE`. Artifacts signed before the migration keep their legacy names, and the
deployment CLI maps those names only to verify them.

## Subscriptions and automatic upgrades

- Installation settings name one channel and an optional version range. Every Entity follows the
  installation's channel, because FDAI services release together.
- Inside each maintenance window, the Hub plans the newest Release on the channel that passes every
  constraint. Entities that the Release marks as needing downtime wait for a downtime window.
- A version pin is a version range, such as `>=1.4.0 <1.5.0`, or `=1.4.3` for an exact version.
- When a recall leaves a pinned range without an eligible Release, the Hub reports that no Release
  is eligible and alerts the operator. It doesn't move the installation outside its range.

| Situation | Recommended subscription |
|-----------|--------------------------|
| Standard production | `RELEASE` |
| A change board reviews each version before it becomes eligible | A custom channel with manual additions |
| Early access to new capabilities | `RELEASE_CANDIDATE` |
| A certified version or an integration requires one release line | A version range pin, widened through a reviewed merge |
| Vendor or customer test installation | `DEV` |

## Recall

- **Release recall:** A vendor-signed recall notice stops the Hub from proposing the Release and
  cancels pending Plans that target it. Installations that run it receive a roll-off Plan to the
  newest eligible Release that isn't recalled. Roll-off takes priority over other Plans. A manual
  suppression window still blocks it, and the Hub raises an alert.
- **Capability recall:** A Release or signed recall notice can name ActionTypes and Workflows that
  must return to shadow mode. The installation demotes them immediately, outside maintenance
  windows, because lowering authority is always allowed. It blocks a new promotion of the same
  capability until a later Release lifts the recall, and this precedence also covers an operator
  override promotion.
- Offline installations apply recalls when an operator imports the bundle that carries them.

## Catalog integrity

A signature proves who published a record, but not that the record is current. The vendor
therefore signs catalog metadata in separate roles, following
[The Update Framework (TUF)](https://theupdateframework.io/):

- A root record names the keys that may sign every other record. It changes only through a
  threshold of offline keys.
- A snapshot record lists the current version of every channel membership and recall record.
- A timestamp record names the current snapshot and expires after a short published interval.
- Every record carries a version that only increases. Installations and Target Hubs reject a
  lower version, and each upgrade bundle names the bundle it extends.
- Recall notices carry a sequence number per product, so a withheld recall shows up as a gap.

When the timestamp record expires, the installation accepts only recall roll-off Plans and raises
an alert. It also returns operator-override promotions to shadow mode until fresh metadata arrives,
because those promotions rely on recall as their safety net. An offline Target Hub sets the expiry
interval to match its bundle cadence.

## Schema compatibility

Database migrations stay expand/contract and forward-only. [Deployment](deployment.md) already
serializes them with a database-scoped lock, bounds their deadlines, and runs them before a new
revision takes traffic.

| Phase | Change | Runs as | Roll-back target |
|-------|--------|---------|------------------|
| Expand | Additive schema only | The Release's migration job, before any workload switches | The previous Release, which tolerates the expanded schema |
| Switch | Workloads move to the new Release | The lifecycle agent's workload phase | The previous Release |
| Contract | Removes the old shape in a later Release | A migration job after a point-in-time restore checkpoint | None for that shape. Only a forward fix. |

- An upgrade is eligible only when the target Release tolerates the current schema revision and
  its migrations move forward from it.
- A roll-back is eligible only when the older Release tolerates the current schema revision.
  Otherwise the installation holds for the operator and a forward fix.
- A contract Release is scheduled only when every Release that the installation might roll back to
  inside the supported window tolerates the contracted shape, and only after the restore checkpoint
  is recorded.
- A migration that stops partway suppresses the installation. The next Plan resumes the same
  forward migration under the same lock and never runs a Release against a shape it doesn't
  tolerate.

## Artifact delivery

### Connected installations

The installation imports each Release's images into its own container registry inside the
boundary. The artifacts-missing constraint blocks a Plan until every required digest is present,
as in [Apollo constraints](https://www.palantir.com/docs/apollo/core/plans-and-constraints).

### Offline installations

An upgrade bundle carries Releases, channel membership, recall notices, and the minimal image
layers that the Target Hub doesn't already have. The vendor release key signs the bundle's
checksum list. The customer may add its own signed configuration packages to the transfer media,
and the Target Hub verifies each package signature separately.

1. An operator imports the bundle into the Target Hub.
2. The Target Hub verifies the signature and every checksum, publishes images into the registry
   inside the boundary, and updates its catalog.
3. Plans proceed under the normal constraints.

The first-installation offline package keeps its current contract. For a Hub-managed offline site,
it also contains the Target Hub.

## Release data model

| Table | Key | Purpose | Time fields | Mutability |
|-------|-----|---------|-------------|------------|
| `release` | `release_id` | Product, version, manifest digest, signature, schema range, dependencies | `published_at`, `recorded_at` | Immutable |
| `release_artifact` | `release_id`, `artifact` | Image digest, SBOM digest, provenance digest | `recorded_at` | Immutable |
| `release_channel` | `channel_id` | Name, default or custom, owning Hub | `effective_from` | Revisioned |
| `channel_membership` | `channel_id`, `release_id` | Pipeline or manual addition, and the actor | `added_at` | Append-only. Removal is a new row. |
| `promotion_pipeline` | `product`, `revision` | Stage order and criteria | `effective_from` | Revisioned |
| `promotion_run` | `run_id` | Stage results and soak observations | `started_at`, `finished_at` | Append-only |
| `recall` | `recall_id` | Release or capability scope, reason, sequence number, signed notice digest | `issued_at`, `recorded_at` | Append-only. Lifting is a new row. |
| `catalog_record` | `role`, `version` | Root, snapshot, or timestamp record and its signature | `signed_at`, `expires_at`, `recorded_at` | Append-only |
| `bundle_import` | `bundle_id` | Checksum digest and import result in a Target Hub | `imported_at` | Append-only |

## Honest limits

- Nothing beyond signed deployment bundles, offline kits, and legacy channel names is implemented.
- The production trust-root ceremony hasn't run. A vendor release key must exist before any Hub
  path can verify Releases.
- Reproducible double-build verification of the signed bundle remains open.
- Releases don't yet declare schema ranges, capability maximums, or downtime needs.

## Related docs

| To learn about | Read |
|----------------|------|
| Lifecycle architecture and Plans | [Hub-Managed Lifecycle](hub-managed-lifecycle.md) |
| Configuration layers and packages | [Lifecycle Configuration](lifecycle-configuration.md) |
| Signed bundles and the deployment CLI | [Installable Deployment CLI](installable-deployment-cli.md) |
| Offline delivery today | [Disconnected Deployment](disconnected-deployment.md) |
| Channel history in the productization plan | [Productization and Extensibility](../fork-and-sequencing/productization-and-extensibility.md) |
| Decision record | [ADR-0003](../architecture/decisions/0003-hub-managed-lifecycle-and-operator-governance.md) |
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/lifecycle-releases-and-channels.md) |
