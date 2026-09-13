---
title: Deploy Quickstart
description: Deploy FDAI to Azure from one local command or a digest-pinned disconnected deployment appliance.
derives_from: [{ source: docs/roadmap/deployment/deploy-and-onboard.md, sha: 167f34b237d6f693ed155e7e4003f6d124909a24 }]
---

# Deploy Quickstart

You can deploy FDAI to an Azure subscription after one interactive Azure sign-in. Tenant
deployment runs from the local `fdaictl` coordinator and a managed host inside the target virtual
network. It does not use GitHub Actions, repository variables, repository secrets, or a GitHub
runner.

Terraform remains the infrastructure source of truth. The deployment command verifies a signed
release, shows each exact plan for approval, moves private data-plane work into the virtual network,
and verifies the resulting application before it reports deployment readiness.

## Choose a deployment path

| Environment | Start with | Artifact source |
|-------------|------------|-----------------|
| Connected Azure environment | Clone the repository, install `fdaictl`, run `az login`, then run `fdaictl provision azure --online` | Versioned signed release kit |
| No public artifact egress | Load a digest-pinned FDAI deployment appliance and run its entry point | Complete signed kit embedded in the appliance image |

GitHub Actions can build, test, sign, and publish a release. It is not part of either tenant
deployment path.

## Deploy from a clone

### Prerequisites

Before you start, confirm the following requirements:

- A Linux x86-64 workstation with Bash, `git`, Azure CLI, and `uv`. Windows users can use WSL2
  with these tools installed inside Linux.
- Python 3.13, or permission for `uv` to download it. Initial installation needs access to the
  configured Python package index and, if needed, the Python distribution host. This installation
  procedure is for connected environments; use the appliance path for artifact-offline deployment.
- An Azure identity that can create the Foundation resources and assign the documented deployment
  roles in the selected subscription.
- Capacity in the selected Azure region for the required resource types.
- An interactive Azure session for the intended subscription.

### Install the command once

Cloning the repository does not automatically register shell commands. From the cloned repository
root, install the local deployment CLI into a user-owned, isolated `uv` tool environment:
If you already cloned FDAI, skip the first two commands and start in the repository root.

```bash
git clone https://github.com/dotnetpower/fdai.git
cd fdai
set -o pipefail
uv export --project packages/deployment-cli --locked --no-dev --no-emit-project \
  --format requirements-txt --no-hashes | \
  uv tool install --python 3.13 --constraints - ./packages/deployment-cli
uv tool update-shell
```

The export constrains runtime dependency versions to the repository lock. The package comes from
your checkout, not a same-named package on PyPI. Installation needs no Azure login, maintainer key,
`sudo`, full application environment, or virtual-environment activation, and it does not deploy
Azure resources. Stop if installation fails; do not continue with an older executable.

`uv tool update-shell` adds the user command directory to your shell configuration when needed.
Open a new terminal, or update the current Bash session and verify the command:

```bash
export PATH="$(uv tool dir --bin):$PATH"
command -v fdaictl
fdaictl
fdaictl version
fdaictl provision azure --help
```

`command -v` should resolve `fdaictl` inside the directory printed by `uv tool dir --bin`, usually
`~/.local/bin` on Linux. The command then works outside the cloned directory too. Bare `fdaictl`,
`version`, and `--help` do not sign in or deploy.

| If you see | Check or action |
|------------|-----------------|
| `uv: command not found` | Install `uv` using the [official installation guide](https://docs.astral.sh/uv/getting-started/installation/), then reopen the terminal. |
| `fdaictl: command not found` | Confirm installation with `uv tool list`, run `uv tool update-shell`, then reopen the terminal or use the PATH command above. |
| A different `fdaictl` is selected | Inspect `type -a fdaictl` and `uv tool list`. Resolve the conflicting executable instead of blindly overwriting it with `--force`. |
| Changes in the clone do not appear | The normal installation is a snapshot. From the updated repository root, repeat the locked installation pipeline with `--reinstall` added to `uv tool install`. |
| Bare `fdaictl` still reports a required command | The selected installation predates the discovery help. Verify `command -v fdaictl`, then reinstall from the updated clone using the same locked pipeline. |

For local CLI development, add `--editable` to the same installation command. Package source edits
then take effect immediately, so keep the checkout at that location; dependency changes still
require reinstallation. Normal adopters should use the snapshot installation above.

### Explore commands safely

| Command | What you see |
|---------|--------------|
| `fdaictl` or `fdaictl --help` | Command descriptions and a short getting-started example |
| `fdaictl provision` | Deployment and preparation commands |
| `fdaictl provision azure --help` | Required artifact-source choice, defaults, units, output modes, and advanced inputs |
| `fdaictl --version` | Installed version; `fdaictl version --output json` remains available for scripts |

These discovery commands print static text and exit successfully without Azure access, downloads,
deployment-state changes, or input prompts. To execute a leaf command, supply its required options.
Invalid commands, incomplete arguments, and conflicting artifact sources still return usage error
`2` with a next-help hint; they do not start a deployment. Use full long-option names, not abbreviations.

### Run the deployment

After installation, run this from any directory and choose the Azure region:

```bash
az login
fdaictl provision azure --online --region koreacentral
```

The activity stream appears automatically in an interactive terminal. Add `--progress plain` for
line-oriented logs. Select exactly one artifact source: `--online` or `--offline-kit <path>`.
If you prefer not to install a persistent command, the original checkout wrapper remains available:

```bash
bash scripts/deployment/azure/fdai-up.sh --region koreacentral
```

Both commands use the same coordinator. Installing or updating the CLI does not update the signed
deployment kit: its Genesis scripts come from the verified release, not your clone. A kit-owned fix
needs a corrected signed kit; never edit extracted kit files or disable verification. Successful
command registration is not evidence of successful deployment.

The coordinator performs the following operations in one resumable process:

1. Reads the active tenant and subscription from Azure CLI without accepting either value as a
   command-line secret.
2. Downloads and verifies one versioned complete deployment kit, or revalidates the retained kit.
3. Runs read-only policy, quota, provider, and target checks.
4. Displays the exact Foundation plan and waits for explicit approval.
5. Creates the private state boundary, virtual network, Bastion access, deployment identity, and
   managed deployment host.
6. Transfers the verified kit to that host and runs private Terraform operations with its managed
   identity.
7. Imports the signed service images, applies migrations, configures Entra, and deploys the
   application.
8. Verifies image digests, migration and catalog state, service health, and a second zero-change
   plan.

The command never interprets silence as approval. If an apply result is ambiguous, rerunning the
same command performs verification-only recovery rather than repeating the apply.

Before a new image plan, Genesis selects compatible private builder and verifier VM sizes in the
requested region, checks their combined quota, and displays the sealed choices before approval.
Apply never changes those sizes. This requires a signed kit containing the selection support;
Foundation VM selection and recovery of an earlier partial attempt remain separate reviews.

### If kit acquisition fails

An online retry revalidates retained kit files instead of replacing them. Every signature, exact
file set, digest, runtime image, and bundle binding is checked again. A cached download is not a
trusted or current release merely because the file exists. Existing execution copies, run state,
SSH keys, plans, and approvals are preserved.

| Error category | Check or action |
|----------------|-----------------|
| `HTTP 404` | Confirm that the selected CLI version and platform have a published complete kit. Azure login does not publish or authenticate a GitHub release. |
| `HTTP 401` or `HTTP 403` | Review release access and network policy. Do not put a token in the URL or command line. |
| `HTTP 429`, `HTTP 503`, connection failure, or timeout | Stop this attempt. Review release-host DNS, HTTPS, proxy, and TLS trust before another explicit attempt; never disable certificate verification. |
| Local destination conflict, permission denial, or full storage | Preserve the deployment work directory. Update an older CLI using the locked installation procedure, or correct the specific local access/storage problem without deleting run evidence. |
| Retained source differs, signature fails, or content is incomplete | Stop and review the selected source and retained inputs. The CLI does not overwrite or repair signed files, silently switch sources, or skip validation. |

The default versioned source can revalidate a legacy cache without a source-request record.
A different `--online-url` cannot borrow that cache. Once recorded, the requested source stays
fixed for that work directory. Revalidation does not fetch a newer release or alter scripts inside
the signed kit; a kit-owned fix still needs a corrected signed release.

### Capability mode

An installation without a deployment-bound capability token starts in observation-only mode. This
is a complete deployment with no managed-resource action authority. Supplying a verified token can
enable only its declared capabilities; runtime promotion, risk checks, and human approval remain
independent controls.

## Deploy from an appliance image

Use the deployment appliance when the target network cannot reach GitHub, PyPI, the public
Terraform registry, or a public container registry. The release owner supplies one signed OCI
archive containing:

- `fdaictl` and its locked Python dependencies;
- the signed Terraform deployment bundle;
- Terraform, OPA, and the complete provider mirror;
- every required FDAI service and dependency OCI image;
- Console, migration, and deployment-support artifacts;
- SBOM, provenance, manifest, and signature records.

Load the image with an OCI-compatible container tool on an approved host. The image entry point
uses interactive Azure sign-in or its managed identity and invokes the same standalone coordinator
with the embedded kit. Public artifact fallback is not supported.

For a new private subscription, a minimal Foundation bootstrap can create the Bastion-reachable
host first. The complete application plan and apply still run from the deployment appliance inside
the target network.

> A network with no Azure management-plane route cannot deploy Azure resources. In that profile,
> the appliance can verify and prepare its artifacts but cannot report deployment readiness.

## Understand the result

A successful command reports `deployment_ready=true` after the application converges and its
second Terraform plan is zero-change. `subscription_ready=false` can remain while broader assurance
campaigns, such as complete model-capacity and inventory certification, are still open. This does
not mean that the selected application failed to deploy.

The private work directory can contain SSH keys, target-specific inputs, plans, and recovery state.
Do not upload or share its contents; use sanitized CLI diagnostics instead. Keep the directory until
verification and any required recovery are complete.

## Internal and advanced paths

The following tools are not public tenant deployment entry points:

- `genesis-up.sh` is a low-level Foundation diagnostic and recovery tool.
- `azd-up.sh` is a contributor-only public development bootstrap.
- Deployment workflows under `.github/workflows/` are repository CI, release, and historical
  automation. They are not supported tenant installers.
- Direct Terraform execution is an expert integration boundary and must preserve the same plan,
  approval, identity, rollback, and verification contracts.

## Next steps

| To learn about | Read |
|----------------|------|
| Complete deployment topology | [Deploy and Onboard](../roadmap/deployment/deploy-and-onboard.md) |
| Connected and disconnected execution profiles | [Provisioning Execution Profiles](../roadmap/deployment/provisioning-execution-profiles.md) |
| Appliance and offline trust boundaries | [Disconnected Deployment](../roadmap/deployment/disconnected-deployment.md) |
| Recovery after an incomplete run | [Deployment Recovery](../runbooks/deployment-recovery.md) |
