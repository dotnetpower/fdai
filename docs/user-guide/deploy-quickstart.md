---
title: Deploy Quickstart
description: Deploy FDAI to your own Azure subscription from a clone with one command line, or install it from a signed offline package.
derives_from: [{ source: docs/roadmap/deployment/deploy-and-onboard.md, sha: 344fddd38ae6b21dedd298a5b75746673a505745 }, { source: docs/roadmap/deployment/source-deployment.md, sha: fa493c7a1f499e59649708839904b9e7e4921dd5 }]
---

# Deploy Quickstart

> **Deployment distribution:** The [constitution](../roadmap/architecture/fdai-constitution.md#article-1-purpose-and-scope) defines only two installation paths, the one-command source deployment and the signed offline package. Any installation gate in this document that the constitution does not list is superseded and no longer applies.

You can deploy FDAI to your own Azure subscription from a clone of the repository with one command
line after one interactive Azure sign-in. You don't need a key, a signed kit, a published release,
or any GitHub setup. Without the upstream integrity signing key, the installation runs a 30-day
Trial and shows an expiry watermark after it ends. With that key at
`secrets/integrity-signing-key.pem` in your clone, it receives a full entitlement.

Terraform remains the infrastructure source of truth. The deployment command builds the service
images from your clone in your own registry, shows each plan it applies, moves private data-plane
work into the virtual network, and verifies the resulting application before it reports deployment
readiness.

By default, the plan gives the dedicated inventory Managed Identity subscription-scoped AKS
Cluster User and RBAC Reader roles. The inventory Job can then discover current and future AKS
clusters and read their Kubernetes objects without giving Core, Operator, or Thor those roles.
Review this read scope in the plan.

## Choose a deployment path

| Environment | Start with | What you need |
|-------------|------------|---------------|
| Any Azure subscription you can sign in to | Run `az login`, then one line: `git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --region <region>` | Nothing else. No key, kit, or release |
| An Azure VM without internet access | Run `fdaictl provision azure --offline-kit <package>` on that VM | One signed offline package from a key holder |

GitHub Actions tests the repository. It is not part of either deployment path.

> **Current status:** The one-command source deployment is still being completed, as its
> [implementation ledger](../roadmap-implementation/deployment/source-deployment.md) records:
>
> - A keyless run creates the Foundation and then stops with
>   `prebuilt_runtime_artifacts_required` before the application stage.
> - No deployment step starts the Trial yet, so an installation without a token stays
>   observation-only.
> - Core verifies licenses with the upstream integrity key, but with
>   `secrets/integrity-signing-key.pem` the deployment still issues a 30-day token instead of the
>   installation entitlement, and the expiry watermark doesn't exist yet.
> - Until those items close, a holder of the offline-package signing key reaches the application
>   stage only by building the signed offline package and passing `--offline-kit`.

## Deploy from a clone

### Prerequisites

Before you start, confirm the following requirements:

- A Linux x86-64 workstation with Bash, `git`, Azure CLI, and `uv`. Windows users can use WSL2
  with these tools installed inside Linux.
- Python 3.13, or permission for `uv` to download it. Initial installation needs access to the
  configured Python package index and, if needed, the Python distribution host. This procedure is
  for connected environments; use the signed offline package on an Azure VM without internet access.
- Node.js and npm, only when you select the Console add-on.
- An Azure identity that can create the Foundation resources and assign the documented deployment
  roles in the selected subscription.
- Capacity in the selected Azure region for the required resource types.
- An interactive Azure session for the intended subscription.

### Install the command once

This step is optional. The `fdai-up.sh` wrapper runs from your clone without installing anything;
install `fdaictl` only when you want to run the same coordinator from any directory.

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
your checkout, not a same-named package on PyPI. Installation needs no Azure login, FDAI maintainer key,
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

Sign in, then run one line that clones the repository and starts the deployment in your chosen
Azure region:

```bash
az login
git clone https://github.com/dotnetpower/fdai.git && fdai/scripts/deployment/azure/fdai-up.sh --region koreacentral
```

If you already have a clone, run `scripts/deployment/azure/fdai-up.sh --region koreacentral` from
its root instead. The wrapper prepares your clone's locked environment and runs
`fdaictl provision azure --source .` with your options. With an installed CLI, you can run that
command directly from the clone. The activity stream appears automatically in an interactive
terminal; add `--progress plain` for line-oriented logs. The private work directory must be outside
your clone.

The coordinator performs the following operations in one resumable process:

1. Reads the active tenant and subscription from Azure CLI without accepting either value as a
   command-line secret.
2. Pins one clean committed snapshot of your clone.
3. Selects the Trial or full entitlement mode from your clone's `secrets/` directory.
4. Runs read-only policy, quota, provider, and target checks.
5. Shows and applies the Foundation plan: the private state boundary, virtual network, Bastion
   access, deployment identity, and managed deployment host.
6. Builds the service images from the snapshot in your registry and reads back their digests.
7. Applies migrations and catalogs, starts the Trial or stores the full entitlement, configures
   Entra when selected, and deploys the application by digest.
8. Verifies image digests, migration and catalog state, service health, and a second zero-change
   plan.

Your invocation approves each plan the command shows. Deleting or replacing an existing resource
requires one extra typed confirmation. The command never interprets silence as approval. If an
apply result is ambiguous, rerunning the same command performs verification-only recovery rather
than repeating the apply. Rerunning the command later upgrades the same installation from your
current clone.

To check feasibility first, add `--prepare-only` to pin the snapshot without Azure access, or
`--preflight-only` to read AKS SKU and quota feasibility without changing resources. A successful
preparation or preflight is not a deployed application.

A new interactive run shows the installation settings once at startup. Supply a setup estimate
ceiling with `--setup-cost-ceiling <USD>` or enter it during that review. Select optional surfaces
with `--add-on` and optional observation sources with `--observation-source`; the default is the
headless observation-first profile. These settings do not deploy resources by themselves.

Before the Foundation plan, Genesis reads the regional VM catalog and chooses a compatible managed
host size within the quota budget. The choice is sealed before approval and never changed during
apply. If no compatible size is available, review the reported restrictions, hardware
requirements, and quota; existing claims still resume verification only.

Foundation plans first use a private local backend. Only the exact migration archive activates the
signed remote-backend example for the attested host; migration approval and readback remain mandatory.
If a retained migration claim predates the complete archive and lacks all sibling support files,
resume from the corrected exact source with a fresh `foundation-state` approval. The coordinator
preserves the original claim and backend effect, restores only exact files from the reviewed
recovery configuration, and verifies a current-source overlay outside Terraform's input tree before
running verification only. A partial file set or a different existing file stops recovery.
After cleanup, a later exact-source run transfers its verified observer through the private Bastion
path, reads its digest back, and runs it with the managed identity. The observer downloads the
protected state blob directly with Azure CLI, matches it to the retained authority digest, and
removes its temporary files without rebuilding the deleted Terraform work tree or provider mirror.

### Recover a verified public development deployment

This recovery path adopts state from the `azd-up.sh` public development bootstrap and still runs
through the legacy release-kit acquisition, which is scheduled for removal.

Use application-state adoption only when the contributor deployment has already produced a verified
`fdai.contributor-recovery.v1` receipt after a failed apply. Run the command from the exact signed kit
revision that contains the adoption support:

```bash
fdaictl provision azure \
  --online \
  --region <azure-region> \
  --adopt-runner-image-receipt <verified-runner-image-receipt> \
  --adopt-application-state <private-terraform-state> \
  --adopt-application-recovery <private-recovery-receipt> \
  --adopt-resolved-models <private-resolved-models>
```

Supply the runner receipt and all three application mode-0600 files together. The coordinator
verifies their digests, target, resource
count, resource suffix, and model-capability contract. It creates a private staged copy that removes
only the application resource group's two ownership records. The original local state remains
unchanged.

The runner receipt reuses an independently verified managed image without another image apply. A
new Foundation run keeps its current signed source and records the image's original source, signed
verifier source, image run, and exact receipt digest as separate provenance.

The managed host accepts the staged state only when the Foundation-owned remote application backend
doesn't contain a state blob. It writes an immutable claim before the single non-forced state push,
then reads the state back and verifies its lineage, serial, content, and managed-resource count. If
the process stops after the claim, run the same command with the same work directory and inputs. The
host verifies the existing remote state and doesn't repeat the push. A different input, target,
Foundation binding, nonempty backend, or changed lineage stops recovery for operator review.
The recovered-state path also stops before approval if either subsequent plan contains a delete or
replacement action.

Don't delete the existing Azure resources or the original local state to resolve an adoption error.
Keep the work directory and use the retained claim or receipt to determine the failed boundary.

### Trial and full entitlement

The command selects the entitlement once, on your workstation, before it changes anything in Azure:

| Your clone | Your installation | After 30 days |
|------------|-------------------|---------------|
| No `secrets/integrity-signing-key.pem` | Starts one 30-day Trial at first activation | New acting work is blocked and an expiry watermark appears; observation, diagnosis, audit, and export continue |
| The upstream integrity signing key at `secrets/integrity-signing-key.pem` | Receives a full entitlement bound to this installation | No change |
| A key file that is not usable | Nothing; the command stops before any Azure change | Not applicable |

The command checks the key before it changes anything. The key file must be owner-only
(`chmod 600`) and match the committed `security/integrity/upstream-signing-key.pub`; the
offline-package signing key never selects full entitlement. The key never leaves your workstation;
only the signed entitlement is stored in your Key Vault. Rerunning the command never renews a
Trial, even if its record was deleted, and a later run with the key upgrades a Trial installation
in place.

Entitlement only makes capabilities available. Runtime promotion, risk checks, and human approval
remain independent controls.

### When the Trial ends

After 30 days, FDAI keeps observing, diagnosing, auditing, and exporting, but new acting work is
blocked. Every Console page then shows a watermark in the lower-right corner stating that the
evaluation period has expired, similar to an operating system that isn't activated. You can't
dismiss the watermark, and no setting, data change, or redeployment turns it off. Only a full
entitlement removes it, which requires rerunning the deployment with the upstream integrity
signing key present.

## Deploy from a signed offline package

Use the offline package when the target Azure VM can't reach GitHub, PyPI, the public Terraform
registry, or a public container registry. A key holder builds one signed package that contains the
deployment CLI and its wheels, the Terraform configuration, Terraform and its provider mirror,
`kubectl` and `kubelogin`, every service and dependency image, the Console, and migration support:

```bash
scripts/deployment/release/build-standalone-deployment-kit.sh \
  --out <private-output-directory> --signing-key <package-signing-key>
```

Copy the package to the Azure VM, install `fdaictl` from its signed wheelhouse as described in
[Disconnected Deployment](../roadmap/deployment/disconnected-deployment.md), and run:

```bash
fdaictl provision azure --offline-kit <fdai-deployment-kit.tar.gz> --region <azure-region>
```

The command verifies the package's detached Ed25519 signature and every checksum before it uses
any file. The package alone is sufficient: no download, public registry, package index, or build
is needed. Azure management and data-plane endpoints must stay reachable through Azure network
paths. The package signing key authenticates artifacts, not usage rights, so an offline
installation runs the 30-day Trial unless a separately issued entitlement is supplied.

> A network with no Azure management-plane route cannot deploy Azure resources. In that profile,
> the package can be verified and prepared, but the command cannot report deployment readiness.

## Understand the result

A successful command reports `deployment_ready=true` after the application converges and its
second Terraform plan is zero-change. `subscription_ready=false` can remain while broader assurance
campaigns, such as complete model-capacity and inventory certification, are still open. This does
not mean that the selected application failed to deploy.

If you configure analyzer targets directly, use `resource_id` for the logical FDAI Resource and
`provider_resource_id` for the exact Azure resource ID used by metric queries. When inventory is
available, FDAI can reconcile a legacy Azure ID to its logical Resource. Without inventory, provide
both fields for metric-backed targets so detected issues and Incidents never expose the provider identity
as their target. Non-metric targets, such as Pod lifecycle evidence, use only their logical ID.

The private work directory can contain SSH keys, target-specific inputs, plans, and recovery state.
Do not upload or share its contents; use sanitized CLI diagnostics instead. Keep the directory until
verification and any required recovery are complete.

## Internal and advanced paths

The following tools are not public tenant deployment entry points:

- `genesis-up.sh` is a low-level Foundation diagnostic and recovery tool.
- `azd-up.sh` is a Core-only public development bootstrap on Container Apps. It is not the
  one-command source deployment.
- `fdaictl provision azure --online` acquires a published release kit. It is not one of the two
  installation paths and is scheduled for removal.
- `fdai-up.sh` refuses the retired `--signing-key` option and never builds a kit. Build the signed
  offline package separately and pass `--offline-kit` instead.
- Deployment workflows under `.github/workflows/` are repository CI, release, and historical
  automation. They are not supported tenant installers.
- Direct Terraform execution is an expert integration boundary and must preserve the same plan,
  approval, identity, rollback, and verification contracts.

## Next steps

| To learn about | Read |
|----------------|------|
| One-command source deployment and entitlement | [One-Command Source Deployment](../roadmap/deployment/source-deployment.md) |
| Complete deployment topology | [Deploy and Onboard](../roadmap/deployment/deploy-and-onboard.md) |
| Connected and disconnected execution profiles | [Provisioning Execution Profiles](../roadmap/deployment/provisioning-execution-profiles.md) |
| Signed offline package and trust boundaries | [Disconnected Deployment](../roadmap/deployment/disconnected-deployment.md) |
| Recovery after an incomplete run | [Deployment Recovery](../runbooks/deployment-recovery.md) |
