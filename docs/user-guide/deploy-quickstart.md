---
title: Deploy Quickstart
description: Deploy FDAI with signed Release Hub images, an explicit source build, or a signed offline package.
derives_from: [{ source: docs/roadmap/deployment/deploy-and-onboard.md, sha: 5ed506756c13326d19e4ccc4031a628b07eef774 }, { source: docs/roadmap/deployment/source-deployment.md, sha: a3f745efb0afc86b156d80500aafea28d49bf679 }, { source: docs/roadmap/deployment/hub-image-deployment.md, sha: 073c3c7c2aa71caf864a9e7a8e5d42969f6504c3 }]
---

# Deploy Quickstart

> **Deployment distribution:** Ordinary clone deployment selects
> [Release Hub images](../roadmap/deployment/hub-image-deployment.md). Explicit source builds and
> signed offline packages retain their [constitutional contracts](../roadmap/architecture/fdai-constitution.md#article-1-purpose-and-scope).
> Connected image bootstrap does not complete the full
> [Hub-managed lifecycle](../roadmap/deployment/hub-managed-lifecycle.md).

You can deploy FDAI to your own Azure subscription from a clone of the repository after one
interactive Azure sign-in. By default, the command selects prebuilt images through
`https://hub.msfdai.com`, using an independently trusted Release public key and a compatible
published Release. You don't need a private signing key, a signed kit or GitHub setup.
Explicit source mode needs neither a Hub nor a published Release.
Without the upstream integrity signing key, the installation runs a 30-day
Trial and shows an expiry watermark after it ends. With that key at
`secrets/integrity-signing-key.pem` in your clone, it receives a full entitlement.

Terraform remains the infrastructure source of truth. The deployment command imports signed,
digest-pinned service images into your own registry, shows each plan it applies, moves private data-plane
work into the virtual network, and verifies the resulting application before it reports deployment
readiness.

By default, the plan gives the dedicated inventory Managed Identity subscription-scoped AKS
Cluster User and RBAC Reader roles. The inventory Job can then discover current and future AKS
clusters and read their Kubernetes objects without giving Core, Operator, or Thor those roles.
Review this read scope in the plan.

## Choose a deployment path

| Environment | Start with | What you need |
|-------------|------------|---------------|
| Connected clone deployment | Run `az login`, then `scripts/deployment/azure/fdai-up.sh --hub-public-key <trusted-public.pem> --region <region>` from your clone | Independently trusted Release public key, compatible published Release and registry pull access |
| Explicit source build in your own subscription | Run `az login`, then `scripts/deployment/azure/fdai-up.sh --source . --region <region>` | No Hub, verification key, kit or published Release |
| An Azure VM without internet access | Run `fdaictl provision azure --offline-kit <package>` on that VM | One signed offline package from a key holder |

GitHub Actions tests the repository. It is not the tenant deployment transport.

> **Hub development validation:** The separate
> [Release Hub](../../infra/release-hub/README.md) and
> [Lifecycle Hub](../../infra/lifecycle-hub/README.md) guides deploy each product's own UI/API/DB
> independently. Login and peer catalog bindings aren't startup prerequisites; management APIs
> remain unavailable without authentication. The
> [legacy paired guide](../../infra/hubs-development/README.md) retains its existing authenticated
> fixture. Neither is a complete Hub-managed FDAI installation or a replacement for either
> source/offline path. Hub-image bootstrap is documented separately and does not imply a completed
> managed lifecycle. Local evidence isn't Azure or production trust-root acceptance; cloud execution
> requires separate approval.

> **Current status:** The one-command source deployment is implemented through application
> convergence. Its
> [implementation ledger](../roadmap-implementation/deployment/source-deployment.md) records:
>
> - A source run continues past the Foundation into the application stage: it builds the service
>   images in your registry, applies the AKS runtime and workloads, runs migrations, and starts the
>   30-day Trial. One keyless new-subscription run and unchanged rerun reached terminal readiness.
>   A current-revision acceptance run is still required for each new installation.
> - With `secrets/integrity-signing-key.pem`, the application stage installs the installation
>   entitlement instead of the Trial. A live key-holder new installation and Trial-to-full rerun
>   have not yet been recorded.
> - A run stops for review if it outlives its confirmed installation scope; start a fresh run in
>   a new work directory after a guarded teardown.

## Deploy from a clone

### Prerequisites

Before you start, confirm the following requirements:

- A Linux x86-64 workstation with Bash, `git`, Azure CLI, and `uv`. Windows users can use WSL2
  with these tools installed inside Linux.
- Python 3.13, or permission for `uv` to download it. Initial installation needs access to the
  configured Python package index and, if needed, the Python distribution host. This procedure is
  for connected environments; use the signed offline package on an Azure VM without internet access.
- Node.js and npm, only when you select the Console add-on.
- No local Terraform installation. The command uses `terraform` on `PATH` only when it is the
  pinned release; otherwise it downloads that release once and verifies its committed digests.
- An Azure identity that can create the Foundation resources and assign the documented deployment
  roles in the selected subscription.
- If you select the Console or enterprise identity add-on, the shared tenant-local FDAI API,
  approval-bot, and role-group display names must be unique. The installer derives a separate
  Console SPA from the exact target binding, so another FDAI installation doesn't own its
  redirects. Duplicate exact shared or derived names stop the run before Azure resources are
  created.
- If you select the Console or enterprise identity add-on, an active Microsoft Entra
  `Privileged Role Administrator` or `Global Administrator` role on the signed-in account. The
  installer grants the deployment identity the Microsoft Graph `Application.ReadWrite.OwnedBy`
  application permission, which no lesser role can assign. Activate the role first when it is
  eligible through Privileged Identity Management. Without it the Foundation completes and the
  Application identity stage stops with a directory-role denial; rerunning the same command
  resumes after the role is active.
- Capacity in the selected Azure region for the required resource types.
- An interactive Azure session for the intended subscription.
- For the default image path, an independently approved Release Hub public PEM and a clean checkout
  matching the signed Release source commit. The key is public; never supply a private key.
  The selected channel and signed image locations must be reachable. A failed check stops deployment
  instead of building replacement images. See [Release Hub image deployment](../roadmap/deployment/hub-image-deployment.md).

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

Obtain the Release public key through your approved trust channel, sign in and check the selected
subscription, then deploy in your chosen Azure region:

```bash
az login
az account show --query '{subscription:id,name:name}' --output table
git clone https://github.com/dotnetpower/fdai.git
fdai/scripts/deployment/azure/fdai-up.sh \
  --hub-public-key /trusted/release-hub-public.pem --region koreacentral
```

If you already have a clone, run the wrapper from it with the same public-key and region options.
The wrapper prepares your clone's locked environment and selects Hub images by default.
For the unchanged Hub-independent build path, explicitly run
`scripts/deployment/azure/fdai-up.sh --source . --region koreacentral`, or
`fdaictl provision azure --source <checkout>` with an installed CLI.
The activity stream appears automatically in an interactive
terminal as append-only installer events; add `--progress plain` to remove terminal styling while
keeping the same scrolling records. Quiet preparation and preflight work writes a `still working`
record every 10 seconds, followed by an explicit completion or failure record. The private work
directory must be outside your clone.

For a disposable source-AKS development installation, you can add
`--development-authority-profile <private-reviewed-profile.json>`. FDAI validates and transfers the
profile only for the application plan and derives the separate executor principal from it. Omitting
the option preserves a retained profile. Use `--clear-development-profile` to remove it
through a later exact plan.

The coordinator performs the following operations in one resumable process:

1. Reads the active tenant and subscription from Azure CLI without accepting either value as a
   command-line secret.
2. Pins one clean committed snapshot of your clone.
   In Hub mode, verifies the signed catalog and Release, requires matching source, and records
   the selected subscription's minimal deployment request before Azure deployment effects.
3. Selects the Trial or full entitlement mode from your clone's `secrets/` directory.
4. Runs read-only policy, quota, provider, and target checks.
5. Shows and applies the Foundation plan: the private state boundary, virtual network, Bastion
   access, deployment identity, and managed deployment host.
6. Imports the signed image digests into your registry and reads them back. Explicit source mode
   builds the service images from the snapshot instead.
7. Applies migrations and catalogs, starts the Trial or stores the full entitlement, configures
   Entra when selected, and deploys the application by digest.
8. Verifies image digests, migration and catalog state, service health, and a second zero-change
   plan.

Your invocation approves each plan the command shows. Deleting or replacing an existing resource
requires one extra typed confirmation. The command never interprets silence as approval. If an
apply result is ambiguous, rerunning the same command performs verification-only recovery rather
than repeating the apply. Hub-image reruns retain the exact selected catalog; in-place channel
upgrades and Hub teardown are not implemented. A catalog change needs a separately reviewed run,
not mode switching or adoption of existing resources. Explicit source mode retains its own
resume/update contract. A request row is not deployment success:
Release Hub operators see `requested` / `self-reported` records in **Deployment requests**.
The request includes the subscription, region, Release/channel and input digests, never Azure
credentials or customer configuration. It does not prove subscription ownership.

An exact Foundation recovery may use a newer clean checkout for recovery logic. After verified
state handoff, application deployment still uses the original retained source snapshot and the
original runtime profile. Recovery does not silently upgrade application bytes or select a signed
kit.

For explicit source mode, add `--prepare-only` to pin the snapshot without Azure access, or
`--preflight-only` to read AKS SKU and quota feasibility without changing resources. A successful
preparation or preflight is not a deployed application.

A new interactive run shows the installation settings once at startup. Supply a setup estimate
ceiling with `--setup-cost-ceiling <USD>` or enter it during that review. Select optional surfaces
with `--add-on` and optional observation sources with `--observation-source`; the default is the
headless observation-first profile. The partial AKS compute cost review uses a 1500 USD monthly
ceiling unless you pass `--monthly-cost-ceiling <USD>`. These settings do not deploy resources by
themselves.
The `notifications` add-on also needs `--notification-recipients <path>`: a private JSON file
`{"recipients": ["name@domain"]}` that stays out of the runtime profile and receipts.

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

`azd-up.sh` remains a Core-only development diagnostic. It isn't an FDAI installation path, and
`fdaictl provision azure` no longer adopts its state through connected release-kit acquisition.
Keep its work directory and receipts for diagnosis. Create a supported installation with the
one-command source path or a signed offline package instead.

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

To upgrade an existing offline installation, rerun the same command with the newer package and the
installation's original `--work-dir`. The command verifies the newer package, keeps the previous
package snapshot for review, and continues the existing Foundation under the revision that created
it. It then deploys the application from the newer package. It never approves a new Foundation
plan under the older revision.

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

Role assignment checks need tenant permissions that the deployment doesn't grant. A tenant
administrator grants the inventory identity Microsoft Graph `User.Read.All` and
`GroupMember.Read.All` application permissions to judge subscription assignments, and `Reader` at
the tenant root management group to judge managed identity assignments. Until then, those checks
report `unknown` instead of passing. For details, see
[Deploy and onboard](../roadmap/deployment/deploy-and-onboard.md).

The private work directory can contain SSH keys, target-specific inputs, plans, and recovery state.
Do not upload or share its contents; use sanitized CLI diagnostics instead. Keep the directory until
verification and any required recovery are complete.

## Internal and advanced paths

The following tools are not public tenant deployment entry points:

- `genesis-up.sh` is a low-level Foundation diagnostic and recovery tool.
- `azd-up.sh` is a Core-only public development bootstrap on Container Apps. It is not the
  one-command source deployment and its state isn't adopted by the public installer.
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
