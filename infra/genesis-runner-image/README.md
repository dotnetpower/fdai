# Genesis runner image

This Terraform root builds the exact managed image used by a fresh-subscription Foundation runner.
It runs before `infra/genesis-foundation` and contains no GitHub registration token, Azure
credential, deployment state, or customer-specific value.

## Contract

The local Genesis coordinator snapshots this root, resolves one numeric Canonical Marketplace
image version, and creates a saved Terraform plan. The plan can run only after a current approval
file binds its review and plan digests.

Terraform creates a private builder VM behind an FQDN-allowlisted Firewall Basic, runs one exact Custom Script
extension, deallocates and generalizes that VM, captures a managed image, then boots a second
private verifier VM from the captured image. The verifier repeats the toolchain and credential
absence checks before it is deallocated. No Azure VM Image Builder template or staging Storage
account is used, so a tenant policy that disables Storage Shared Key cannot break the build.

The image customization installs the versions and SHA-256 values declared in `toolchain.json`:

- Azure CLI and its Microsoft package-signing key
- Terraform
- Open Policy Agent (OPA)
- GitHub Actions runner
- the enrollment, attestation, and Foundation state-handoff helpers

Terraform's official ZIP and the executable extracted from it have separate SHA-256 fields. Local
planning authenticates the executable, while image customization authenticates both artifacts.

The image remains unregistered. `genesis-runner-enrollment.sh` later sends a short-lived GitHub
registration token only through SSH standard input over an exact Azure Bastion tunnel.

## Supported toolchain

`toolchain.json` currently pins Terraform 1.9.8 and Azure CLI 2.88.0. These versions support the
Foundation, enrollment, state handoff, and the private-runner application path over Azure Bastion.
They're older than the Terraform 1.16.1 and Azure CLI 2.90.0 that the protected
`[self-hosted, fdai-deploy, fdai-deploy-candidate]` workflows are validated on. The azurerm backend in
Terraform 1.9.8 rejects the managed-identity Azure CLI session those workflows use.

Enrollment still applies the `fdai-deploy` labels, because the Genesis GitHub transport dispatches
`deploy-dev.yml` to the enrolled runner. To stop a Genesis-image runner from failing later inside a
protected job, `scripts/deployment/azure/login-deploy-identity.sh` first runs
`check-runner-terraform.sh`. That check refuses any Terraform older than 1.16.1 before the first
Azure call. Raise the pinned toolchain before you rely on a Genesis runner for protected workflows.

## Files

| File | Purpose |
|------|---------|
| `main.tf` | Creates the temporary builder and captures the generalized managed image. |
| `customize-runner-image.sh.tftpl` | Installs and verifies the pinned toolchain without credentials. |
| `enroll-runner.sh` | Reads one registration token from standard input and configures an exact slot. |
| `attest-runner.sh` | Verifies tool versions, managed identity, services, labels, and source binding. |
| `migrate-foundation-state.py` | Migrates and verifies Foundation state from inside the private network. |
| `toolchain.json` | Machine-readable version and checksum authority for the image. |

## Safety boundaries

- Plans require the exact direct-builder resource and action set and accept create and read actions
  only. Update, replacement, delete, Storage, and VM Image Builder actions are blocked.
- Tenant policy may append only the bounded `FirstPartyUsage=/Unprivileged` IP tag to both
  Firewall public IPs. Terraform ignores that externally owned field, while post-apply ARM
  readback rejects asymmetric, unknown, or changed policy tags.
- The local Terraform executable must match the pinned Terraform SHA-256.
- Apply writes an immutable claim before Terraform. A retry after that claim can verify only.
- Independent Azure Resource Manager readback must match the source and toolchain tags, successful
  builder and verifier extensions, bounded public-IP policy effects, deallocated VM states, and a
  refreshed zero-change Terraform plan before a receipt is written.
- Managed-image IDs and local state paths remain in private receipts and are omitted from portable
  Genesis status.

## Testing

Run the focused Terraform and Python checks from the repository root:

```bash
terraform -chdir=infra/genesis-runner-image test
uv run pytest -q --no-cov tests/integration/scripts/test_genesis_runner_image.py
```
