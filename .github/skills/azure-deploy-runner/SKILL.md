---
name: azure-deploy-runner
description: |
  FDAI installation to Azure through exactly two paths: a key holder's contributor deployment from
  a local checkout, or a signed offline package on an Azure VM without internet. Load before
  running `fdaictl provision azure`, `fdai-up.sh`, building an offline package, Terraform apply
  for FDAI resources, or onboarding a new Azure target.
version: 3.0.0
scope: repository
---

# Azure Deployment

The [constitution](../../../docs/roadmap/architecture/fdai-constitution.md#article-1-purpose-and-scope)
defines FDAI installation. There are two paths, and each needs only what is listed.

## Contributor source deployment

A contributor with a clone, an active `az login`, and the development signing private key deploys
every FDAI resource to their own subscription:

```bash
az login
scripts/deployment/azure/fdai-up.sh --source . --signing-key /private/signing-key.pem \
  --region <azure-region>
```

- Build whatever is needed from the checkout, including service images.
- Do not require a protected branch, CI result, published artifact, prebuilt package, appliance,
  attestation, provenance, SBOM, or maintainer involvement.

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
