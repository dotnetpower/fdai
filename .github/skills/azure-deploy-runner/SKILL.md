---
name: azure-deploy-runner
description: |
  FDAI installation to Azure through exactly two paths: a one-line source deployment from any
  local checkout (30-day Trial and expiry watermark without the integrity signing key, full
  entitlement with it), or a signed offline package on an Azure VM without internet. Load before
  running `fdaictl provision azure`, `fdai-up.sh`, building an offline package, Terraform apply for
  FDAI resources, or onboarding a new Azure target.
version: 4.1.0
scope: repository
---

# Azure Deployment

The [constitution](../../../docs/roadmap/architecture/fdai-constitution.md#article-1-purpose-and-scope)
defines FDAI installation. There are two paths, and each needs only what is listed.

## Source deployment

Anyone with a clone and an active `az login` deploys every FDAI resource to their own subscription
with one command line. The [source deployment owner](../../../docs/roadmap/deployment/source-deployment.md)
defines the contract:

```bash
az login
git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --region <azure-region>
```

- Build service images from the checkout into the deployment's own registry. Do not build, sign,
  or require a kit, bundle, control package, appliance, SBOM, provenance, attestation, published
  release, protected branch, CI result, or maintainer involvement.
- No `secrets/integrity-signing-key.pem` means one durable 30-day Trial. A usable upstream
  integrity signing key there, matching `security/integrity/upstream-signing-key.pub`, means a
  full installation entitlement. A present but unusable key stops the run before any Azure effect.
  No other key under `secrets/` selects full mode.
- After the Trial ends, every Console view shows a persistent expiry watermark. Never add a
  setting, flag, or data path that hides it; only a full entitlement does.
- Never copy, print, or pass a private key value. Only the signed entitlement reaches Key Vault.

Current status: the keyless source run stops after Foundation handoff with
`prebuilt_runtime_artifacts_required` until the
[source deployment ledger](../../../docs/roadmap-implementation/deployment/source-deployment.md)
closes its application work packages. The code still verifies licenses with the separate license
key pair and has no watermark yet. Until then, a holder of the offline-package signing key can
reach the application stage only through the interim
`fdai-up.sh --source . --signing-key <path>` route, which still builds a signed kit and is
scheduled for removal. Report that limitation instead of presenting the interim route as the
source path.

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
- Do not repeat an apply whose outcome is ambiguous. Read back state and plan again instead.
- Articles 7 and 8 govern FDAI's own runtime actions on managed resources. They are not
  installation gates.

Do not add any other installation gate. A gate that is not listed here is a defect.
