---
name: azure-deploy-runner
description: |
  FDAI deployment workflow for connected and artifact-offline Azure environments. Tenant
  deployment runs from `az login` through the local standalone coordinator and a VNet-integrated
  manual managed host, never GitHub Actions. Load before planning or running `fdaictl provision
  azure`, `fdai-up.sh`, Terraform apply, deployment appliance work, private endpoint recovery, or
  onboarding a new Azure target.
version: 2.0.0
scope: repository
---

# Azure Deployment on a Private Tenant

FDAI supports one tenant-deployment engine with two artifact sources:

- Connected: clone the repository, run `az login`, then run `fdai-up.sh`.
- Artifact-offline: load a digest-pinned deployment appliance or provide the same complete signed kit
  through `--offline-kit`.

Both paths use `fdaictl provision azure` and the same exact-plan, approval, Managed Identity,
recovery, and verification contracts. GitHub Actions may test source and publish release artifacts.
It MUST NOT plan, apply, resume, or tear down a tenant deployment.

## Private-Endpoint Constraint

A tenant policy can disable public access and key authentication for Key Vault and Storage. An
operator workstation outside the virtual network then cannot:

- write Key Vault secrets;
- reach the private Terraform state backend;
- complete private storage data-plane operations;
- import images into a private registry.

The local workstation remains the human control surface. Private data-plane work runs on a
Bastion-reachable managed host inside the target VNet under a dedicated user-assigned Managed
Identity. This internal execution location is an implementation detail of the one-command flow, not
an extra operator procedure.

## Required Public Experience

### Connected deployment

```bash
az login
scripts/deployment/azure/fdai-up.sh --region <azure-region>
```

The command:

1. Reads the active Azure tenant and subscription from the signed-in human.
2. Downloads and verifies one versioned complete deployment kit.
3. Runs bounded read-only target, policy, provider, quota, and region checks.
4. Shows each exact Terraform plan and waits for explicit terminal approval.
5. Creates the Foundation, including private state, hub VNet, Bastion, deploy identity, and managed
   host.
6. Transfers the verified kit through Bastion.
7. Runs substrate and application Terraform under the managed identity.
8. Imports and reads back the exact runtime image digests.
9. Runs migrations, catalog materialization, Entra configuration, and service activation.
10. Requires service health and a second zero-change plan before reporting
    `deployment_ready=true`.

### Artifact-offline deployment

The release owner provides one digest-pinned OCI deployment appliance that embeds a signed kit:

- the deployment CLI wheel and locked dependencies;
- the signed Terraform bundle;
- Terraform, OPA, and the provider mirror;
- every required service and dependency OCI archive;
- Console and migration support;
- manifests, SBOMs, provenance, and signatures.

The appliance entry point signs in interactively or uses an explicitly selected user-assigned
Managed Identity, then invokes `fdaictl provision azure --offline-kit /opt/fdai/kit.tar.gz`. The
Managed Identity path requires the exact client ID. It MUST NOT fall back to GitHub, PyPI, the
public Terraform registry, or a public container registry.

A network with no Azure management-plane route can verify and prepare artifacts but cannot deploy
Azure resources or report deployment readiness.

## Identity and Approval

- The signed-in Azure human selects the target and approves exact plans.
- The managed-host UAMI executes Terraform and private data-plane operations.
- Human and executor identities remain distinct.
- Approval is bound to the exact binary-plan digest and expiry.
- A changed plan requires new approval.
- Destructive plans require a second exact confirmation.
- Silence never grants authority.
- Environment names do not grant authority.

The deploy identity uses the minimum roles needed for the selected plan. Typical Foundation roles
include Contributor and User Access Administrator on the application resource group, Network
Contributor on the operations group, Storage Blob Data Contributor on private state, and only the
reviewed subscription-scoped reader or service roles.

## Recovery

Every mutation writes an immutable pre-effect claim. If Terraform or the transport ends with an
ambiguous result, the next invocation performs authoritative readback and a zero-change plan. It
MUST NOT repeat the apply from the retained claim.

A changed target, signed kit, Foundation state, network handoff, Entra binding, provider context,
or plan digest requires a new prepared context. Cleanup failure leaves the run incomplete and
preserves its audit evidence.

## Capability Mode

A maintainer signing key is not an adopter prerequisite. If no verified deployment-bound token is
available, the installation completes in observation-only mode and creates no license secret. The
Core can observe and report but cannot execute managed-resource actions.

A valid token does not bypass runtime promotion, risk policy, human approval, executor identity,
rollback, or effect verification.

## Release and Appliance Construction

A release is built only from a clean exact revision after focused checks. The complete release
builder may emit both the signed kit and appliance:

```bash
bash scripts/deployment/release/build-standalone-deployment-kit.sh \
  --out /private/fdai-release \
  --appliance-base-image <approved-base>@sha256:<digest>
```

The appliance base MUST be Linux x86-64, digest-pinned, independently approved, and already contain
Python 3 with pip, Azure CLI, OpenSSH, and `tar`. Appliance construction verifies the complete kit,
installs only from its wheelhouse, disables build network and base pulls, and emits OCI SBOM and
provenance records.

Never place signing keys, tenant identifiers, credentials, endpoints, or customer values in the
image, repository, documentation, or logs.

## Validation Gates

Before reporting implementation completion, run the focused package, integration, shell, roadmap,
and translation checks. Before reporting operational validation, retain both of these receipts:

1. A connected active-login deployment from the exact signed release.
2. An appliance-entry-point deployment with no public artifact access.

Each receipt must prove target binding, exact plans and approvals, Foundation handoff, managed-host
identity, image digest import and readback, migrations, service health, cleanup, and second-plan
zero change. Broader model-capacity and inventory certification may keep
`subscription_ready=false`; that state is independent from application deployment readiness.

## Guardrails

- Do not run Azure mutation or build a release artifact before the exact revision passes focused
  checks and release preflight.
- Confirm `az account show` identifies the intended subscription before mutation.
- Do not use GitHub workflow dispatch as a tenant deployment transport.
- Do not run private data-plane operations from an external workstation.
- Do not use a system-assigned identity implicitly when a user-assigned deployment identity is
  required.
- Do not retry an ambiguous apply.
- Do not weaken signature, exact-plan, approval, rollback, or readback controls to simplify the
  one-command experience.

## Related

- `docs/user-guide/deploy-quickstart.md`
- `docs/roadmap/deployment/installable-deployment-cli.md`
- `docs/roadmap/deployment/provisioning-execution-profiles.md`
- `docs/roadmap/deployment/disconnected-deployment.md`
- `docs/roadmap/deployment/deploy-and-onboard.md`
