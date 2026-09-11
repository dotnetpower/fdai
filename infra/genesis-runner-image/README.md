# Genesis runner image

This Terraform root builds the exact managed image used by a fresh-subscription Foundation runner.
It runs before `infra/genesis-foundation` and contains no GitHub registration token, Azure
credential, deployment state, or customer-specific value.

## Contract

The local Genesis coordinator snapshots this root, resolves one numeric Canonical Marketplace
image version, and creates a saved Terraform plan. The plan can run only after a current approval
file binds its review and plan digests.

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

- Plans accept create and read actions only. Update, replacement, and delete actions are blocked.
- The local Terraform executable must match the pinned Terraform SHA-256.
- Apply writes an immutable claim before Terraform. A retry after that claim can verify only.
- Independent Azure Resource Manager readback must match the source and toolchain tags before a
  receipt is written.
- Managed-image IDs and local state paths remain in private receipts and are omitted from portable
  Genesis status.

## Testing

Run the focused Terraform and Python checks from the repository root:

```bash
terraform -chdir=infra/genesis-runner-image test
uv run pytest -q --no-cov tests/integration/scripts/test_genesis_runner_image.py
```
