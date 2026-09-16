---
name: azure-deploy-runner
description: |
  FDAI deployment workflow for connected and artifact-offline Azure environments. Tenant
  deployment starts on an ordinary PC through the local standalone coordinator; use an eligible
  internal host only for operations that require it, never GitHub Actions. Load before planning or running `fdaictl provision
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

## Basic Deployment Before Detailed Provisioning

Follow the [two-stage contract](../../../docs/roadmap/deployment/provisioning-execution-profiles.md#basic-deployment-and-detailed-provisioning).
An ordinary PC with a supported CLI environment can start basic deployment. Internal-VM location,
VPN, IMDS, a PC-attached Managed Identity and a precreated deployment host are not universal startup
prerequisites. Where private operations require another venue, the installer includes the minimum
host/access/identity work in the reviewed basic plan; the user does not assemble a Foundation first.

Basic deployment creates the AKS Standard baseline with API Server VNet Integration, the reserved
API-server and workload subnet shape, the five baseline services, persistent state, required
migrations, authenticated Console access and independent health evidence. Public AKS management
access is the initial default so an ordinary external coordinator can complete the baseline; bind it
to the reviewed access policy and never treat public access as anonymous or unrestricted access.

Model setup, managed-resource scope, optional connectors, organization-specific policy, private
endpoints, VNet peering, private DNS links, private-cluster mode and additional capacity belong to
later detailed provisioning. Do not block basic success on those unselected capabilities or treat
basic health as whole-subscription readiness. Required tenant security policy, identity separation,
exact approval, budget and state protection still apply. A policy that requires private access from
the first effect cannot be deferred; use an eligible existing internal host or include the minimum
access path in the exact basic plan. Missing optional capability configuration stays explicitly
unavailable and never grants runtime authority. This is the target experience, not proof that the
current CLI fully implements stage separation or supports every desktop operating system natively.

## Detailed Private-Network Provisioning

After baseline Console health is proven, `/provisioning` may collect a private-network intent and
submit a governed provisioning request for:

- hub or existing-VNet peering;
- private endpoints for selected Azure services;
- private DNS zones, links, forwarding and resolution checks;
- AKS private-cluster mode and removal of public API access;
- approved egress routing, firewall and network-isolation changes.

The browser and Operator API never receive the deployment identity, Terraform state, provider
payloads or private data-plane credentials. They create a content-addressed draft and exact-plan
request. The protected deployment executor produces the plan, a distinct human approves it, and the
executor applies it. Console reports read-only plan, approval, progress and independent effect
evidence. It does not mutate Azure directly.

Network hardening is ordered to preserve access: prove target CIDRs and non-overlap, establish
peering and routes, establish DNS, verify the execution host and AKS API path, create and verify
private endpoints, then disable the corresponding public access. A failed verification leaves the
public path unchanged or executes the approved rollback. Do not strand the cluster by disabling the
last verified management path.

The coordinator can run on an ordinary PC outside Azure. Coordinator and execution host are roles,
not necessarily separate machines. Follow
[Existing host](../../../docs/roadmap/deployment/provisioning-execution-profiles.md#existing-host):
prefer the operator's current eligible internal VM before provisioning another host. Do not infer
external location from the words PC, workstation, local terminal, Windows, or WSL. Private endpoint
reachability, the actual execution toolchain, deployment identity and state ownership determine
eligibility. A suitable existing host can execute Terraform directly; Bastion and file transfer are
needed only for a separately selected remote host. This does not permit fallback to an ineligible host.

## Keep Deployment Moving

- Reuse the operator's selected target, runtime, budget and approved unchanged scope. Do not ask the
  same setup questions again; obtain new approval only where changed effects or the exact-plan
  contract requires it. Initial preferences are not approval of unknown future plans.
- Reuse verified infrastructure, suitable scoped deployment identities and completed artifacts.
  Do not require a new Foundation VM or identity merely because the installer normally creates one.
  Keep human and executor identities distinct and never select a system identity implicitly.
- Treat Foundation handoff as context and authoritative-state continuity, not a mandatory transfer
  to another machine. Preserve an already correct protected backend; do not create a second state
  owner, move application data or repeat an apply to satisfy a missing installer record.
- Report the exact failed requirement and its smallest repair. Distinguish DNS, routing, TLS,
  authorization, tool compatibility and installer wiring. An internal VM is not automatically
  eligible, but an installer gap is not evidence that Azure or Terraform cannot deploy there.
- Keep repository delivery separate from tenant deployment. Honor a request to stop GitHub activity;
  do not poll, push or open PRs as a substitute for local work. Preserve mandatory source eligibility
  checks, and state explicitly if satisfying one conflicts with the requested no-network scope.

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
5. Reuses an eligible existing host and verified Foundation resources, or plans only the missing
  infrastructure. A new managed host and its access path are conditional, not universal prerequisites.
6. Makes verified artifacts available on the selected host, transferring them only for remote execution.
7. Runs AKS substrate and application Terraform on that host under the approved deployment identity.
8. Verifies the prebuilt signed runtime image set and reads back the exact deployed digests. Tenant
  deployment never builds a service or managed-host image.
9. Runs baseline migrations, required catalog/bootstrap data, minimum Entra configuration and service
  activation; defers optional detailed provisioning until after basic deployment.
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
public Terraform registry, a public container registry or an installation-time image build.

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

## Artifact Boundary

Release construction is a separate upstream supply-chain responsibility. Tenant provisioning only
accepts a complete prebuilt, signed and digest-pinned artifact set with manifests, SBOMs,
provenance and signatures. It never invokes Docker, Buildx, ACR Tasks, a remote builder or a VM
image capture operation. Connected mode downloads the verified set; artifact-offline mode reads the
same set from the approved kit. Neither mode changes artifact bytes.

Never place signing keys, tenant identifiers, credentials, endpoints or customer values in an
image, repository, documentation or logs.

## Validation Gates

Before reporting implementation completion, run the focused package, integration, shell, roadmap,
and translation checks. Before reporting operational validation, retain both of these receipts:

1. A connected active-login deployment from the exact signed release.
2. An appliance-entry-point deployment with no public artifact access.

Each receipt must prove target binding, exact plans and approvals, Foundation handoff, managed-host
identity, prebuilt image verification and deployed-digest readback, migrations, service health,
cleanup, and second-plan zero change. Broader model-capacity and inventory certification may keep
`subscription_ready=false`; that state is independent from application deployment readiness.

## Guardrails

- Do not run Azure mutation or build a release artifact before the exact revision passes focused
  checks and release preflight.
- Do not build or capture any image during tenant provisioning.
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
