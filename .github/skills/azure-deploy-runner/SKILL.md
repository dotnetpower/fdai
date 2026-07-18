---
name: azure-deploy-runner
description: |
  FDAI deploy workflow on the private-everything Azure tenant profile
  (Key Vault + Storage with public network access disabled, key-auth
  off). Deploys run from a VNet-integrated self-hosted runner, not
  the laptop, because a laptop cannot complete the Terraform storage
  data-plane readiness poll from outside the VNet. Load this skill
  before a deploy, when planning `azd up` or `terraform apply`, when
  troubleshooting a KV secret 403 from a laptop, when adding a new
  data service that a policy might force private, or when onboarding
  a new deploy target.
version: 1.0.0
scope: repository
---

# Azure Deploy on the Private-Everything Tenant

The runnable target is the maintainer's private tenant, where policy
forces every data service private and turns key-auth off. This skill
captures the shape that actually deploys under those constraints. It
is generic: no tenant / subscription / resource names are recorded here
(those belong in the maintainer's `/memories/` per the
[customer-agnostic scope rule](../../instructions/generic-scope.instructions.md)).

## Tenant Constraints

Under a private-everything policy the laptop CANNOT:

- (a) write Key Vault secrets: KV `publicNetworkAccess=Disabled` and
  it reverts back to Disabled if you flip it via `az`.
- (b) reach a Terraform remote-state backend when the state Storage
  account is private.
- (c) complete Terraform's storage data-plane readiness poll when
  `allowSharedKeyAccess=false`.

Consequence: **all deploy data-plane work runs from inside the VNet**,
on a self-hosted runner attached to the workspace.

## Canonical Solution Shape

Two Terraform layers plus a runner VM.

### `infra/bootstrap/` (ops layer, local state)

- ops resource group + VNet with `snet-runner` + `snet-pe` subnets
- state Storage account (private) + blob private endpoint +
  `privatelink.blob.core.windows.net` private DNS zone
- runner VM (Ubuntu, `Standard_B1s` or `B2s`, system managed
  identity, **no public IP**), cloud-init installs Terraform + Azure
  CLI + GitHub Actions runner
- Runner MI role assignments:
  - **Contributor** + **User Access Administrator** on the app RG
    (UAA is required to create role assignments during the app
    apply; Contributor alone lacks `Microsoft.Authorization/*`).
  - **Network Contributor** on the ops RG (VNet peering + DNS zone
    links).
  - **Storage Blob Data Contributor** on the state storage account.
- The state Storage account is created **out of band** by
  `az storage account create ...` (a private + key-auth-off account
  cannot finish Terraform's blob poll from a laptop). Terraform
  data-sources it instead of managing it. The state container is
  created from the runner.

### `infra/` (app layer, remote state on the state Storage account)

- Postgres + Key Vault + Event Hubs namespace + ACR + Log Analytics
  + Container Apps env + Container App (VNet-integrated) +
  Container Apps Jobs (out-of-band watchers).
- App config carries `enable_private_networking=true` plus the ops
  VNet identifiers so the app spoke peers with the ops hub and the
  KV private DNS zone gets an `extra_vnet_links` entry to the ops
  VNet. Key Vault secrets `depends_on` the peering to avoid the
  private-link / DNS race.

### GitHub Actions workflow

- `.github/workflows/deploy-dev.yml` on `[self-hosted, fdai-deploy]`.
- **Plan-only by default**; an `apply=true` input is required to run
  `terraform apply`.
- Non-secret Azure identifiers (subscription id / region / ops
  VNet id / state SA name) live in repo **Variables**.
- Console deploys also set `ENTRA_CONSOLE_SPA_CLIENT_ID`. The runner MI is an
  owner of that tenant's SPA app registration and has the Microsoft Graph
  `Application.ReadWrite.OwnedBy` application permission with admin consent.
- Postgres admin credentials live in repo **Secrets**.
- The runner's identity does `az login --identity` at job start;
  no service principal secret is stored anywhere.

## Runner Lifecycle

- Runner VM stays running only while a deploy is active. To save
  cost, deallocate when idle:
  ```
  az vm deallocate -g <ops-rg> -n <runner-vm-name>
  ```
- Start it before a CI run:
  ```
  az vm start -g <ops-rg> -n <runner-vm-name>
  ```
- The runner is registered as a systemd service labeled
  `self-hosted,fdai-deploy` so the workflow's `runs-on` matches.

## Standard Deploy Flow

1. **Preflight (from the laptop)**: run `scripts/deployment/local/dev-status.sh` and
   confirm the correct `az account show` subscription. When two
   profiles are present (default + a customer profile under
   `$HOME/.azure-customer`), check the customer one with
   `AZURE_CONFIG_DIR=$HOME/.azure-customer az account show`.
2. **Start the runner** if deallocated.
3. **Plan-only run**:
   ```
   gh workflow run deploy-dev.yml
   ```
   Watch the summary; a plan of `0 add / N change / 0 destroy` where
   `N` matches a known no-op set (e.g. rotating the KV-hosted DB
   password to the GH-secret value) is safe to promote to apply.
4. **Apply run** (still from the workflow, still on the runner):
   ```
   gh workflow run deploy-dev.yml -f apply=true
   ```
5. **Console identity sync**: when `deploy_console=true`, the workflow reads
  the Terraform Static Web App hostname, verifies the active tenant, preserves
  existing SPA redirect URIs, and adds the deployed HTTPS origin. A missing
  variable, tenant mismatch, or Graph authorization failure blocks the run.
6. **Post-apply audit**: read the runner's audit log (via
   `az vm run-command` + `journalctl`); confirm no secrets landed
   in logs; deallocate the runner.

## Secret Hygiene

- Passwords are born **on the runner** each apply (`openssl rand`)
  and are never transmitted from the laptop or committed. The live
  password lives only in KV and the remote state file.
- Runner apply logs are shredded at end of run. The local Terraform
  state file (if any) is removed from the runner.
- Never `az keyvault secret set` from a laptop against a private KV.
  The RBAC role assignment might exist, but the data-plane call still
  fails with a 403 because public access is Disabled.

## Common Failure Modes

- **KV secret 403 from the laptop**: expected. Run from the runner.
- **Storage stuck `provisioningState=Creating`** after a killed
  `terraform apply`: delete + recreate the SA via `az` (`az` waits
  for `Succeeded`), then re-run.
- **Terraform state carries stale renamed resource IDs** (typical
  after a project rename): `terraform state rm` the stale ids and
  let apply recreate under the new names.
- **Postgres in `Stopped` state**: `az postgres flexible-server start
  --resource-group <rg> --name <server>` before `terraform apply`.
- **Runner Contributor cannot manage role assignments**: add User
  Access Administrator on the app RG.
- **Transient 403 on the Nth KV secret** during apply: private-link /
  DNS race. Re-apply resolves it.

## Guardrails (do NOT deploy)

- **FDAI dev deploy on the maintainer's private tenant requires
  explicit maintainer approval per session.** The `moonchoi` cost
  policy has been lifted, but the "no `terraform apply` before P1
  completion" rule is still in force unless the maintainer overrides
  it in the current session.
- Never run a destructive `terraform apply` against another tenant
  from a session that is authenticated to a wrong profile. Confirm
  the `az account show` output first (see `scripts/deployment/local/dev-status.sh`).
- Do not add customer / tenant / subscription / resource identifiers
  to this skill, to the repo, or to any docs. They live only in the
  maintainer's `/memories/`. See
  [.github/instructions/generic-scope.instructions.md](../../instructions/generic-scope.instructions.md).

## Related

- Deploy topology:
  [docs/roadmap/deployment/deploy-and-onboard.md](../../../docs/roadmap/deployment/deploy-and-onboard.md).
- CSP-neutrality and provider seams:
  [docs/roadmap/architecture/csp-neutrality.md](../../../docs/roadmap/architecture/csp-neutrality.md).
- App shape:
  [.github/instructions/app-shape.instructions.md](../../instructions/app-shape.instructions.md).
- Session snapshot:
  [scripts/deployment/local/dev-status.sh](../../../scripts/deployment/local/dev-status.sh).
