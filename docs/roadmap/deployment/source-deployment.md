---
title: One-Command Source Deployment
---

# One-Command Source Deployment

Anyone who clones the FDAI repository can deploy every FDAI resource to their own Azure
subscription with one command after `az login`. This document defines that command, the artifacts
it may and may not create, and how it selects a 30-day Trial or a full entitlement. It owns the
first installation path in [Constitution Article 1](../architecture/fdai-constitution.md#article-1-purpose-and-scope).

> **Status:** This is the target contract. Today a keyless source run stops after the verified
> Foundation handoff with `prebuilt_runtime_artifacts_required`, and no deployment step initializes
> the durable Trial. The [implementation ledger](../../roadmap-implementation/deployment/source-deployment.md)
> records the current state and the ordered remaining work.
>
> **Scope:** Runtime and provisioning topology, Trial and token semantics, and the signed offline
> package stay with the owners listed in [Related docs](#related-docs).

## Design at a glance

| Concern | Decision |
|---------|----------|
| Who can deploy | Anyone with a clone, an interactive `az login`, and rights to create resources and role assignments in the target subscription |
| Entry points | `scripts/deployment/azure/fdai-up.sh --region <region>` or `fdaictl provision azure --source <checkout> --region <region>`; both run one coordinator |
| Artifact source | One clean committed checkout; service images are built from it into the deployment's own registry |
| Release artifacts created | None: no signed kit, bundle, control package, wheelhouse, appliance, host image, SBOM, provenance, attestation, or published release |
| Keys required | None. A signing key is never an installation input |
| No license key | One durable 30-day Trial from first activation |
| License key in `secrets/` | A full-catalog installation entitlement without expiry, bound to that installation |
| Approval | The invocation approves each plan it shows; deleting or replacing an existing resource needs one typed confirmation |
| Success | `deployment_ready=true` only after service health and a second zero-change plan |

## Design and critique

**Initial design:** Treat any private key under `secrets/` as proof of full entitlement, deploy
observation-only otherwise, and keep building a signed kit from the checkout before deployment.

**Critique:**

- A filename or an arbitrary key is not proof. The integrity key and the offline-package signing
  key protect other compromise domains, and an empty or mismatched file passes a presence check.
- The deployed runtime must never read a private key.
- Observation-only is not a Trial. A new user could never evaluate the acting capabilities.
- A 30-day token on the key holder's own installation degrades it unless the key holder redeploys,
  which is a Trial in everything but name.
- Building and signing a kit to deploy from source creates artifacts that nobody else verifies and
  requires a signing key that a new user does not have.

**Revised contract:** Only the dedicated license issuer key selects full mode, and the workstation
turns it into a signed installation entitlement. Without that key, the deployment initializes one
durable Trial. The source path builds images directly into the deployment and creates no signed
release artifact. A present but unusable license key stops the run before the first Azure effect
instead of silently selecting Trial.

## Run the command

```bash
git clone https://github.com/dotnetpower/fdai.git
cd fdai
az login
scripts/deployment/azure/fdai-up.sh --region koreacentral
```

`fdai-up.sh` prepares the checkout's locked environment and invokes
`fdaictl provision azure --source <checkout>` with the remaining options. Both entry points run the
same coordinator and produce the same result. Running the command again resumes or upgrades the
same installation.

The workstation needs Bash, `git`, Azure CLI, and `uv`. Selecting the Console add-on also needs
Node.js and npm to build the Console from the committed lockfile. No container engine, GitHub
account, repository secret, workflow, or registered runner is required.

## Entitlement selection

The coordinator selects the entitlement mode once, on the workstation, before any Azure effect:

| Workstation state | Deployment receives | After 30 days |
|-------------------|---------------------|---------------|
| No `secrets/license-signing-key.pem` | One Trial record initialized at first activation | New acting work is blocked; observation, diagnosis, audit, and export continue |
| Usable dedicated license key | A full-catalog installation entitlement | No change; the entitlement has no expiry |
| License key present but unusable | Nothing; the run stops before any Azure effect | Not applicable |

A usable key is the fixed `secrets/license-signing-key.pem` file in the checkout's ignored
`secrets/` directory, or the file named by the explicit `--license-signing-key <path>` option. It
must be a current-UID, mode-`0600` regular file whose Ed25519 public key matches the packaged
license public key. `scripts/deployment/release/check-signing-key.py --scan secrets` reports the
role each key satisfies without printing key material. The integrity key and the offline-package
signing key never select full mode.

- **Key custody:** The private key never leaves the workstation. It never enters an image,
  Terraform input or state, a command-line value, a log, or Key Vault. Only the signed entitlement
  moves, through a Key Vault file input under a digest-derived secret name.
- **Binding:** The entitlement and the Trial record bind the installation and deployment digests,
  not the source revision or image digest. Upgrades and restarts neither invalidate a full
  entitlement nor renew a Trial.
- **Mode change:** A later run with a usable key replaces Trial with the full entitlement without
  reinstalling. A later run without a key keeps an installed entitlement; omission never revokes it.
- **Authority:** Entitlement moves only the capability `available` axis. Promotion, RBAC, risk,
  human approval, executor identity, and effect verification stay independent, as
  [Capability Licensing](../fork-and-sequencing/capability-licensing.md#the-rule-that-makes-this-safe)
  requires.

## What the command builds

| Input | Source path behavior |
|-------|----------------------|
| Service images | Built from a `git archive` of the exact commit by the registry build service of the deployment's own registry, tagged `sha-<commit>`, and deployed by digest |
| Dependency images | Imported by pinned digest into the deployment's registry |
| Console | Built from the checkout and published only when the Console add-on is selected |
| Terraform providers | Resolved from the public Terraform registry under the committed lock files |
| Database | Migrations and authoritative catalogs from the checkout, followed by Trial initialization |
| Provenance | Recorded in the private run receipt as `operator-selected-source`, never as a signed release |

The source path never creates a signed kit, deployment bundle, bundle signature,
deployment-control package, signed wheelhouse, runtime release manifest, appliance, runner or host
image, SBOM, provenance or attestation statement, TUF metadata, or published release or image. It
never requires a protected branch, CI result, public GHCR package, or maintainer. The signed
offline package in [Disconnected Deployment](disconnected-deployment.md) is the only installation
artifact that FDAI signs.

## Stage order

1. Read the human target from the active `az login` session and confirm the subscription.
2. Admit one clean committed checkout and pin its snapshot.
3. Select the entitlement mode on the workstation.
4. Run the read-only provider, policy, quota, and SKU preflight.
5. Plan and apply the platform under the selected runtime and provisioning profiles.
6. Build the service images, import the dependency images, and read back every digest.
7. Run migrations and catalogs, and initialize the Trial record once when none exists.
8. In full mode, issue the installation entitlement and store it through Key Vault.
9. Plan and apply the services by digest, and publish the Console when it is selected.
10. Verify health, run the initial inventory, and require a second zero-change plan.
11. Report `deployment_ready`, the entitlement mode, and the Trial end date without secret values.

Independent reads and builds may run concurrently. Approval, apply, migration, entitlement writes,
and activation stay serial. Every apply keeps the claim-before-effect, verification-only recovery,
and no-repeated-ambiguous-apply rules in
[Installable Deployment CLI](installable-deployment-cli.md#approval-and-recovery).

## Honest limits

- **Not tamper-proof:** Anyone who controls the source and its persistent state can remove the
  Trial check. The Trial is an evaluation boundary, not copy protection.
- **No reinstall detection:** Tearing down an installation and deploying a new one starts a new
  Trial. FDAI runs no global activation service.
- **Builder availability:** Remote image builds need the registry build service in the target
  subscription. When it is unavailable, the run stops with fixed guidance before any service apply
  rather than falling back to another image source.
- **Operator-selected source:** A source installation proves which commit the operator selected,
  not that a publisher released it.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/source-deployment.md) |
| Installation paths and their limits | [FDAI Constitution Article 1](../architecture/fdai-constitution.md#article-1-purpose-and-scope) |
| Trial, tokens, and the installation entitlement | [Capability Licensing](../fork-and-sequencing/capability-licensing.md) |
| `fdaictl` commands, approval, and recovery | [Installable Deployment CLI](installable-deployment-cli.md) |
| AKS or Container Apps and database placement | [Runtime Deployment Profiles](runtime-deployment-profiles.md) |
| Where Terraform runs and how it is reached | [Provisioning Execution Profiles](provisioning-execution-profiles.md) |
| The signed offline package | [Disconnected Deployment](disconnected-deployment.md) |
| Step-by-step user instructions | [Deploy Quickstart](../../user-guide/deploy-quickstart.md) |
