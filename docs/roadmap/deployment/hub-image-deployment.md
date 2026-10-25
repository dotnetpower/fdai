---
title: Deploy with Release Hub images
---
# Deploy with Release Hub images

Use a cloned checkout to install FDAI with prebuilt images selected from
`https://hub.msfdai.com`. The local deployment coordinator still owns Azure sign-in, Terraform
plans, application setup and independent health checks. Release Hub distributes signed metadata
and records deployment requests; it never receives Azure credentials or applies a deployment.

> **Scope:** This is connected image bootstrap, not completion of the
> [Hub-managed lifecycle](hub-managed-lifecycle.md). Enrollment, customer configuration approval,
> installation-local policy and Agent execution retain their own contracts.
> [Source deployment](source-deployment.md) and the signed offline package remain available
> explicitly, without a Hub dependency.

## Design at a glance

| Concern | Decision |
|---------|----------|
| Ordinary clone deployment | Select Release Hub images rather than build service images |
| Distribution endpoint | `https://hub.msfdai.com`, with an explicit HTTPS override for another approved Release Hub |
| Trust | An independently approved Ed25519 Release public key; never trust a key merely because it came with the catalog |
| Release selection | An eligible version in the selected channel, with signed, digest-pinned image locations |
| Local source | A clean checkout matching the signed Release source commit, so migrations and Console cannot silently differ |
| Image delivery | Import images into the installation's own registry and read back the exact digests before applying workloads |
| Failure | Stop on missing trust, invalid signatures, expiry, rollback, recall, source drift or failed image observation; never fall back to source builds |
| Request visibility | Release Hub operators can list reported subscription requests; the catalog and public callers cannot read that list |
| Licensing | Existing installation-bound Trial and entitlement rules; a catalog signature grants no entitlement or execution authority |

## Design, critique and revised boundary

**Initial design:** Replace every source build with a registry pull and display the Azure
subscription in Release Hub.

**Critique:** A mutable image tag or a digest returned beside an untrusted download does not
establish trust. Signed images can still disagree with checkout migrations. A submitted
subscription ID does not prove ownership, and a recorded request does not prove deployment
success. Changing source-mode behavior implicitly would also remove its keyless, Hub-independent
installation contract.

**Revised boundary:** Keep explicit source and offline modes unchanged. The ordinary clone
entry point selects a separate Hub-image option. Verify the signed catalog and exact manifest,
channel membership, expiry, recall, retained revision and source compatibility before Azure
effects. Carry the exact selection to the managed host and distinguish signed image provenance
from checkout-supplied infrastructure, migrations and Console. Import by digest, not by a mutable
tag. Request intake stores self-reported metadata only and cannot authorize any operation.

## Deploy from a clone

### Publisher inputs

Publish a compatible `fdai.application-release.v2` manifest through the existing Release Hub
publication and channel workflow. Each `components.<name>.image_ref` identifies a registry
image by immutable digest, for example
`registry.example.com/fdai/core-control-plane@sha256:<64-lowercase-hex>`.
The reference digest must match the signed component image digest.

The bootstrap requires exactly these seven components: `core-control-plane`, `operator-service`,
`document-ingestion-api`, `document-processing-worker`, `isolated-executor`, `clamav` and
`pgvector`. The Release source commit must match the checkout. Old manifests without signed
image locations remain valid for their existing consumers but are not eligible for this bootstrap.
Publishing metadata does not build images, prove registry availability or grant pull access.

### Installation inputs

First obtain the Release public key through your approved independent trust channel. Keep the
public PEM outside the checkout. This is a verification key, not a signing key or an Azure
credential. Do not download an unverified replacement to make a signature failure disappear.

```bash
az login
az account show --query '{subscription:id,name:name}' --output table
git clone https://github.com/dotnetpower/fdai.git
fdai/scripts/deployment/azure/fdai-up.sh \
  --hub-public-key /trusted/release-hub-public.pem \
  --region <azure-region>
```

The selected channel needs a published, compatible Release and reachable images. If the checkout
does not match the signed source commit, stop and select that reviewed commit before running the
command again. Do not mix current checkout migrations with older images or silently switch to a
development channel.

With an installed CLI, select this mode with `fdaictl provision azure --hub <checkout>`.
Use `--hub-public-key <public.pem>` or the `FDAI_HUB_PUBLIC_KEY` public-key file path,
`--hub-channel <channel>` (default `RELEASE`), `--hub-release <version>` for an exact version,
and `--hub-url <approved-https-origin>` to override the distribution endpoint.

The workstation and managed host still need the connected deployment prerequisites, including
package and Terraform provider access. Only runtime image building changes; this is not an
air-gapped installer or a promise that all artifacts are downloaded from the Hub hostname.
Release Hub supplies signed image locations, while the corresponding registry supplies image
layers. Registry pull authorization remains installation-local.

### Select a different path explicitly

For a Hub-independent source build, use the existing explicit source option:

```bash
fdai/scripts/deployment/azure/fdai-up.sh --source . --region <azure-region>
```

The wrapper resolves its own checkout before interpreting `--source .`. With an installed CLI,
use `fdaictl provision azure --source <checkout>` instead. Source mode does not download a
catalog or register a deployment request. Offline installation remains:

```bash
fdaictl provision azure --offline-kit /private/fdai-deployment-kit.tar.gz
```

Neither path acquires a new Release Hub prerequisite. Switching modes or target inputs is not a
recovery technique; preserve the old private work directory and use the original sealed inputs
or a separate new run.

## See subscription deployment requests

The connected Hub-image command reports a minimal request after verifying its Release selection
and reading the selected Azure account, before the first Azure deployment effect.

| Field | Meaning |
|-------|---------|
| `request_id` | Stable request digest used for exact retry detection |
| `subscription_id` | The subscription reported by the deployment client |
| `release_id`, `channel` | The selected published Release and channel |
| `region` | Requested Azure location |
| `source_commit`, `catalog_digest` | Exact checkout and catalog input identities |
| `recorded_at` | Server-recorded receipt time |
| `status`, `trust` | `requested` and `self-reported`, never deployment success or verified ownership |

`POST /v1/deployment-requests` accepts this bounded metadata. The explicit public-catalog profile
can expose this intake to clone users without making vendor management APIs public.
`GET /v1/deployment-requests` remains operator-only. The **Deployment requests** view provides
subscription filtering and pagination. Request records are separate from catalog publication:
they do not advance catalog revisions, renew expiry, enter catalog exports or grant access to
customer resources.

This is an explicit exception to the catalog-only vendor metadata boundary for request
visibility. It does not permit tenant IDs, identities, credentials, configuration contents,
resource names, callback addresses or operational data. Subscription IDs stay in the Hub's
private runtime database and never enter this repository.

An exact repeated request retains its original record. A reused ID with different fields is a
conflict. If submission has an uncertain outcome, preserve its ID and inspect the retained
record; never manufacture a new request or automatically retry a timed-out mutation.
The request list is an intake ledger, not an installation inventory or effect-verification feed.

## Current bootstrap limits

A rerun preserves its exact catalog selection and target binding. Changing catalog bytes,
Release or trust inputs requires a separately reviewed run and private work directory; this
bootstrap does not implement in-place channel upgrades. A new directory does not authorize
adoption of an existing installation. Do not use it to evade retained state or an uncertain apply.

Hub-mode teardown is not implemented. Do not switch to source mode to tear down a Hub run or
bypass its sealed input binding. The existing explicit source teardown contract applies only
to source installations.

## Validation and delivery limits

Focused local tests can establish catalog verification, import/readback, request persistence,
authentication separation and UI behavior. They cannot establish the availability of the live
Hub, publication of a compatible Release, registry access in another subscription, or an
accepted Azure installation. Publication and rollout of the new Hub/CLI builds remain separate
authorized operations.

## Related docs

| To learn about | Read |
|----------------|------|
| Clone deployment prerequisites | [Deploy quickstart](../../user-guide/deploy-quickstart.md) |
| Explicit source build and licensing | [Source deployment](source-deployment.md) |
| Signed catalog and channel contracts | [Lifecycle releases and channels](lifecycle-releases-and-channels.md) |
| Installation-agent execution | [Hub lifecycle operator guide](../../runbooks/hub-lifecycle-operator-guide.md) |
| Delivery evidence and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/hub-image-deployment.md) |
