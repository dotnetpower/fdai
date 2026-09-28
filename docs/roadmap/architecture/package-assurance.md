---
title: Package Assurance
---

# Package assurance

This document defines the minimal distribution contract for an FDAI Python package. An offline
package should install like an ordinary local pip wheelhouse, with one detached private-key
signature added before installation.

> **Scope:** This contract covers Python package distribution only. Azure identity, Terraform
> approval, runtime images, database migration, service health, and deployment recovery belong to
> their deployment owners.
>
> **Implementation ledger:** Current delivery evidence is tracked in the
> [Package Assurance implementation ledger](../../roadmap-implementation/architecture/package-assurance.md).

## Design at a glance

The offline package contains only these files:

```text
package/
  INSTALL.txt
  requirements.txt
  SHA256SUMS
  SHA256SUMS.sig
  wheels/
    fdai_deployment_cli-<version>-py3-none-any.whl
    <dependency wheels>
```

The signer signs `SHA256SUMS` once with an operator-held Ed25519 private key. The trusted public key
is supplied independently. The package does not carry a trust ceremony, artifact profile, nested
signature, SBOM requirement, provenance document, compatibility matrix, runtime authorization, or
deployment receipt.

## Build

Use the focused builder:

```bash
scripts/deployment/release/build-signed-python-package.sh \
  --out /private/fdai-python-package \
  --signing-key /private/deployment-signing-key.pem
```

The builder creates the deployment CLI wheel, downloads its locked runtime dependencies into
`wheels/`, writes one sorted checksum list, signs that list, and creates a tar archive. It does not
build service images or assemble an Azure deployment payload.

Every shipped file except the signature pair is listed in `SHA256SUMS`; the builder fails when
`wheels/` contains anything other than wheel files. Locked workspace path dependencies, such as
the service contracts, are built as wheels because they have no index hash.

## Verify and install

Verify the signature and checksums before invoking pip:

```bash
cd package
openssl pkeyutl -verify -pubin \
  -inkey /private/trusted-package-signer.pub \
  -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig
sha256sum -c SHA256SUMS
python -m pip install --no-index --find-links wheels -r requirements.txt
```

Pip owns Python version, ABI, platform-wheel, dependency, and installation checks. A package that
does not match the target interpreter fails through normal pip behavior.

## The single package constraint

The only FDAI package-assurance requirement is a valid detached Ed25519 signature over the checksum
list. File hashes are the signed content map, not a separate approval system.

The private key stays outside the repository and package. Installing the package does not grant
Azure access, execution authority, feature activation, or approval.

## Constraints removed

The package layer no longer defines or requires:

- assurance levels or boundary classifications;
- connected, offline, or appliance artifact profiles;
- signed-root or TUF ceremonies;
- separate release and bundle signatures;
- SBOM or provenance documents;
- compatibility manifests or N-1 policy;
- exact transport-archive identity;
- package freshness or operational evidence;
- dependency mirrors outside the wheelhouse;
- runtime promotion, approval, identity, or effect verification.

Owners may still produce any of those artifacts for deployment or release purposes. They are not
package installation prerequisites and are not checked by the global package gate.

## Package inventory

[`config/package-assurance.json`](../../../config/package-assurance.json) lists only Python
distributions that currently publish this signed wheelhouse. It is not an exhaustive workspace
inventory. Internal packages need no entry.

The checker validates the Ed25519 signature format selection and confirms that each listed
distribution path matches its `pyproject.toml` name. Pip and the package manager own everything
else.

## Related docs

| To learn about | Read |
|----------------|------|
| Deployment behavior after installation | [Installable Deployment CLI](../deployment/installable-deployment-cli.md) |
| Runtime and Azure artifact delivery | [Disconnected Deployment](../deployment/disconnected-deployment.md) |
| Package implementation evidence | [Package Assurance implementation ledger](../../roadmap-implementation/architecture/package-assurance.md) |
