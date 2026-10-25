---
name: azure-deploy-runner
description: |
  FDAI Azure installation from a clone using signed images from hub.msfdai.com by default,
  explicit Hub-independent source builds, or a signed offline package. Load before running
  fdaictl provision azure, fdai-up.sh, building an offline package, Terraform apply for FDAI
  resources, or onboarding a new Azure target. Includes Release Hub subscription request
  visibility without confusing requests with deployment success.
version: 4.2.1
scope: repository
---

# Azure Deployment

The [constitution](../../../docs/roadmap/architecture/fdai-constitution.md#article-1-purpose-and-scope)
defines FDAI installation. Ordinary clone deployment selects
[Hub-image bootstrap](../../../docs/roadmap/deployment/hub-image-deployment.md).
Explicit source builds and offline packages retain their existing contracts. Connected image
bootstrap is not completion of the full
[Hub-managed lifecycle](../../../docs/roadmap/deployment/hub-managed-lifecycle.md).

## Default clone deployment: Release Hub images

When another operator clones FDAI and requests deployment, use `https://hub.msfdai.com` to
select signed prebuilt image locations. Do not build service images locally or in ACR by default.

```bash
az login
az account show --query '{subscription:id,name:name}' --output table
git clone https://github.com/dotnetpower/fdai.git
fdai/scripts/deployment/azure/fdai-up.sh \
  --hub-public-key /trusted/release-hub-public.pem --region <azure-region>
```

- Obtain the Release public PEM through an independently approved trust channel. It is public,
  not a signing key; downloading a replacement beside the catalog never establishes trust.
- Verify catalog and manifest signatures, channel, expiry, recall, retained revision and exact
  checkout compatibility. Mirror immutable image digests into the installation's own registry and
  verify readback before workload apply.
- Missing trust, unavailable images or a Hub failure stops this path. Never silently fall back to
  source builds, weaken verification, switch channels or manufacture a release.
- Report the selected subscription's minimal deployment request to Release Hub. Its
  **Deployment requests** view is operator-only; records are `requested` / `self-reported`,
  never proof of subscription ownership, approval, enrollment or operational success.
- Keep Azure credentials, tenant IDs, identities, customer configuration and workload data out of
  the Hub request. No callback is registered and Release Hub never deploys into the subscription.
- Existing Trial/full-entitlement selection, exact-plan approval, managed-host execution,
  health/inventory checks and second zero-change plan remain authoritative. Local implementation
  is not live Hub publication or accepted Azure deployment evidence.
- Reruns bind the exact catalog and target. A changed catalog needs a separately reviewed run
  and private work directory, not an in-place channel upgrade or adoption of existing resources.
  Hub teardown is unsupported; never switch modes to bypass that boundary.

## Source deployment

Anyone with a clone and an active `az login` deploys every FDAI resource to their own subscription
with one command line. The [source deployment owner](../../../docs/roadmap/deployment/source-deployment.md)
defines the contract:

```bash
az login
git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --source . --region <azure-region>
```

- Select this path only when source deployment is explicitly requested; it has no Hub network or
  request-registration prerequisite. Build service images from the checkout into the deployment's own registry. Do not build, sign,
  or require a kit, bundle, control package, appliance, SBOM, provenance, attestation, published
  release, protected branch, CI result, or maintainer involvement.
- No `secrets/integrity-signing-key.pem` means one durable 30-day Trial. A usable upstream
  integrity signing key there, matching `security/integrity/upstream-signing-key.pub`, means a
  full installation entitlement. A present but unusable key stops the run before any Azure effect.
  No other key under `secrets/` selects full mode.
- After the Trial ends, every Console view shows a persistent expiry watermark. Never add a
  setting, flag, or data path that hides it; only a full entitlement does.
- Never copy, print, or pass a private key value. Only the signed entitlement reaches Key Vault.

Current status: the source path continues through application convergence. It builds the five
service images and imports the two dependency images into the deployment registry, runs service
migrations and catalogs, initializes the Trial or installation entitlement, executes initial
inventory, verifies browser access, and requires a second zero-change plan. The
[source deployment ledger](../../../docs/roadmap-implementation/deployment/source-deployment.md)
retains one keyless new-subscription completion and unchanged rerun receipt. A current-revision
keyless acceptance run, a key-holder new installation, and a Trial-to-full rerun remain operational
evidence work. Do not treat those open receipts as an implementation gate, and do not report a
specific installation as accepted until its own terminal receipt is verified.

## Offline package

A key holder builds one signed offline package that contains every artifact for all FDAI
resources: the deployment CLI and its wheels, the Terraform configuration, Terraform and its
provider mirror, kubectl and kubelogin, service and sidecar images, the Console, and migration
support.

```bash
scripts/deployment/release/build-standalone-deployment-kit.sh \
  --out /private/fdai-offline --signing-key /private/signing-key.pem
fdaictl provision azure --offline-kit /private/fdai-offline/fdai-deployment-kit-*.tar.gz
```

- On an Azure VM without internet access, the package alone suffices. Do not download, pull from a
  public registry, use a package index, or build.
- Azure management and data-plane endpoints must stay reachable through Azure network paths.
- The only package guarantee is one detached Ed25519 signature over the checksum list.
- The package signing key authenticates artifacts, not usage rights. An offline installation runs
  the 30-day Trial unless a separately issued entitlement is supplied.

## Rules that remain

- The operator's invocation approves the plan it shows. Deleting or replacing an existing
  resource needs one explicit extra confirmation.
- Confirm `az account show` names the intended subscription before the first effect.
- Secrets and signing keys never enter the repository, logs, command-line values, or chat. Pass
  key files by path only.
- Do not use GitHub Actions as the tenant deployment transport.
- Operator default: do not create, deploy, or bind a GitHub App for an installation. Omit
  `--catalog-review-profile` and use the Console-governed approval path. Select an App-backed
  integration only on a new explicit operator request. This is a selection default, not an
  installation gate, and it never blocks a run.
- Operator default for the development installation `rg-fdai-dev-wus3` / `aks-fdai-dev-wus3`: the
  operator deploys workloads only through the Hub (signed release, approved catalog, Plan, lifecycle
  agent apply). Do not start a new source-AKS installation or edit that cluster's workloads with
  kubectl. Azure resources the lifecycle agent cannot create stay a separate, named change.
  Read-only inspection and deleting a pod so its Deployment recreates it remain allowed. This is a
  selection default, not an installation gate.
- Do not repeat an apply whose outcome is ambiguous. Read back state and plan again instead.
- Articles 7 and 8 govern FDAI's own runtime actions on managed resources. They are not
  installation gates.

Do not add any other installation gate. A gate that is not listed here is a defect.
