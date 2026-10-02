---
title: Provisioning Execution Profiles
---
# Provisioning Execution Profiles

> **Deployment distribution:** The [constitution](../architecture/fdai-constitution.md#article-1-purpose-and-scope) defines three installation paths: the one-command source deployment, the signed offline package, and the [Hub-managed lifecycle](hub-managed-lifecycle.md), which is designed but not yet implemented. Any installation gate in this document that the constitution does not list is superseded and no longer applies.

This document defines how the planned `fdaictl` distribution selects a provisioning host, connectivity mode, command
transport, and access path. It also defines the human approval and workload-identity boundary
that applies before Terraform changes infrastructure or role assignments.

> **Scope:** Azure is the implemented target. The profiles do not change the Terraform source of
> truth or allow local fallback around a private endpoint.

The package retains an internal development and staging client for already protected repository
workflows. That library dispatches context-bound plan or apply requests and validates bounded
status artifacts; it is not a public tenant-provisioning transport. Its facade delegates immutable
request values, subprocess transport, dispatch, plan metadata, apply receipts, and provider-schema
evidence to focused modules. This split adds no command, credential, Azure role, or apply authority.
The command facade also delegates source and offline-kit Foundation planning, private filesystem
handling, target checks, provider-lock validation, and bounded Terraform execution to one focused
plan module. Parser handlers, output contracts, exact approval requirements, and mutation authority
remain unchanged.
## Design at a glance

Provisioning treats four choices as independent axes. The command evaluates evidence first and
does not infer authority from environment names such as `dev` or from the machine on which the
operator installed the wheel.

| Axis | Supported values | Selection rule |
|------|------------------|----------------|
| Connectivity | `online`, `offline` | Use online sources only after bounded TLS checks pass; otherwise require a signed offline kit |
| Execution host | `existing-host`, `managed-vm` | Reuse a suitable private-network host; create a managed VM when no suitable host is available |
| Transport | `manual` | Tenant deployment always uses the local coordinator and the managed deployment host. GitHub Actions may build and publish releases but cannot plan or apply a tenant. |
| Ownership | `fdai-managed` | Terraform manages declared resources and role assignments after approval |

### Standalone active-login deployment

The default product experience is basic deployment from an ordinary PC, followed by detailed
provisioning on the same installation. The current `provision azure` name does not require all
advanced configuration to finish before basic service availability. Stage separation is a target
contract below; this documentation adds no implemented CLI flag or command.

The installed package supports one default subscription deployment boundary after `az login`:

```bash
fdaictl provision azure --offline-kit /media/fdai/fdai-kit.tar
# Source-checkout convenience wrapper using the same local kit.
scripts/deployment/azure/fdai-up.sh --offline-kit /media/fdai/fdai-kit.tar
# Optional bounded HTTPS distribution path.
fdaictl provision azure --online
```

Both commands derive the tenant and subscription only from the active Azure CLI user context. They
do not require a source checkout, Git remote, GitHub account, GitHub repository, required CI check,
repository variable, repository secret, workflow dispatch, or GitHub runner registration. Offline
mode reads the complete kit from a local path and blocks every public artifact fallback. Online
mode remains optional and downloads the same format over bounded HTTPS, validating each redirect
before contact. Offline means artifact-offline,
not disconnected from the selected Azure control plane or Bastion endpoint.
Offline retries reread the supplied source, reverify the retained snapshot, and use a fresh
execution copy without replacing earlier state. Changed or incomplete bytes stop the retry.
Online transfer progress cannot renew the 15-minute total download budget. Socket reads retain
their 30-second bound; available-data reads return between underlying reads, and expiry removes
only the newly created partial download without retrying. One in-flight socket read can outlast the total boundary by at most its own bound.

The package pins the release and bundle verification roots independently from the kit. A complete
kit contains the deployment bundle, Terraform and OPA, the provider mirror, runtime OCI archives,
Console content, migration support, and their software bills of materials. Signature, exact-file,
platform, source-revision, and runtime-content verification completes before Azure mutation.
The current managed-host image and complete-kit builder support Linux x86_64. Other host
operating systems or architectures fail before either acquisition mode; POSIX alone is not Linux.

Foundation network discovery reads existing route tables and local network gateways across the
selected subscription using the stable Network API `2024-05-01`. It does not let Azure CLI select
a newer version that may be unavailable in an existing resource's region. A failed read still
blocks discovery; it never drops a reservation, registers a provider, or retries another version.

Basic deployment verifies the prebuilt signed image set, creates the AKS substrate with API Server
VNet Integration, deploys the five baseline services, installs the deployment-bound license, runs
migrations before application activation, and requires health checks plus second zero-change plans.
Tenant provisioning never builds or captures an image. The basic path keeps authenticated,
restricted public management access unless tenant policy requires private access from the first
effect.

The complete baseline image set is an installation input, not the release unit for every later
change. After baseline health is established, an operator can build and publish one selected service
candidate upstream, then deploy only that digest-pinned service without rebuilding, resigning, or
redeploying unchanged services. The update plans only the selected service-owned state, preserves
peer service state, and reads back the selected image and health. Select multiple services only when
a changed wire contract, schema or migration, sidecar, or shared runtime dependency requires a
coordinated compatibility update.

Selected private application backends, private registry paths and private service endpoints are a
later detailed provisioning plan. An eligible current VM can serve as `existing-host`, with
coordinator and execution on the same machine. When policy requires private access during basic
deployment, that host or the minimum `managed-vm` path must have verified line-of-sight before the
effect; private work never falls back to an ineligible host.

Every mutating checkpoint retains exact-plan approval, an immutable pre-effect claim, a bounded
stop and cleanup path, target locking, stable idempotency, and independent effect readback. The
default standalone `dev` path accepts one current local human approval per exact plan. Staging and
production continue to require the configured independent quorum and approved execution host.
If an apply outcome is ambiguous, the next invocation runs a zero-change plan and authoritative
readback only. It never repeats the apply from the retained claim. A changed Foundation run,
network/state handoff, Entra binding, provider configuration, or signed kit requires a distinct
prepared context.
When that verification plan proves residual changes rather than zero change, the original claim
remains immutable. The coordinator may expose one separately named residual plan only after binding
it to the original claim and refreshed state. A new exact residual approval and pre-effect residual
claim are required; no residual effect is automatic, and an ambiguous residual effect permits
verification only rather than another apply. Independent readback and residual zero change are
required before the stage is complete.
For an AKS baseline recovery, a current existing Key Vault or document storage account that
authoritative management-plane readback reports as public-disabled may select its focused
private-access repair. The repair binds the verified managed-host VNet, creates shared two-way
application peering plus only the selected Key Vault or Blob/DFS private endpoints and DNS links,
and records each selection in retained context. It does not silently promote the whole installation
to the detailed private-network profile. Each repair remains part of the separately reviewed
residual plan. A focused repair runs through a distinct exact `access` plan and approval before the
ordinary substrate plan. Completion requires read-only data-plane probes from the managed host, so
secret and filesystem creation cannot race endpoint, DNS or peering propagation. When Foundation
already owns the runner VNet's Blob-zone link, focused recovery keeps that link singular and writes
the document endpoint A record into the existing operations zone; the DFS zone retains its separate
runner link.
The invocation budget begins before preparation. Approval waits and application handoff use
current remaining time; an expired budget starts no next stage and cannot produce readiness.
Application confirmation requires a real terminal and one at-most-ten-minute window shared by
both prompts and actor lookup, shortened by plan expiry and the remaining invocation budget.
`DeadlineTransport` clamps each existing Bastion command and file transfer to that same current
budget and checks expiry after I/O. The underlying tunnel retains its own bounded cleanup.
Identity and transport failures use fixed diagnostics; raw OS and subprocess exceptions never
render command arguments or paths. Unknown effect outcomes still require retained-state review.

The target selects the entitlement mode from `secrets/integrity-signing-key.pem`, as
[source deployment](source-deployment.md#entitlement-selection) defines. Until that lands, the
command discovers an operator-held mode-`0600` license issuer key from an explicit option or the
documented user configuration path. When the key exists, it issues a deployment- and image-bound
token without copying the key. A supplied pre-issued Trial token follows the same verification and
transfer path. When neither is present, deployment completes in observation-only mode without
creating a license secret. A token crosses Bastion through standard input and is written to Key
Vault by the managed identity; it never appears in arguments, Terraform state, portable status, or
logs.

## Read-only inspection

The target command runs inspection before creating a bootstrap plan:

```bash
fdaictl provision inspect --output json
```

Inspection checks the local Azure CLI, Terraform, bounded online artifact access,
an offline-kit candidate, and the Azure workload identity endpoint. It returns a stable JSON
contract with `mutation_performed=false`, the required approval policy and quorum, and the selected profile.
It never installs a tool, writes configuration, creates a resource, registers a runner, or applies
Terraform.

The result uses these states:

| State | Meaning |
|-------|---------|
| `ready` | An existing host has its toolchain, workload identity, and online access or a verified offline kit |
| `review` | A managed VM or offline kit without a pinned verifier requires operator review |
| `incomplete` | The explicitly requested profile is missing a required dependency or access path |

File presence alone never establishes trust. With a composition-injected pinned verifier,
inspection checks signature, compatibility, exact files, digests, and bounds, then returns only
non-secret manifest metadata. Rejected content is `incomplete`; verified content can make a
complete existing-host profile `ready`. Until the public root ceremony packages that verifier,
the target CLI must keep offline directories at `candidate` / `review`.

## Profile initialization

The target initialization command saves a reviewed profile with explicit, resolved values:

```bash
fdaictl provision init \
	--target-binding <sha256> \
	--connectivity online \
	--host existing-host \
	--transport manual \
	--access-method internal_ssh
```

The target binding is a deployment-local digest of the intended tenant and subscription pair, not
either raw identifier. The command rejects every `auto` value and writes `.fdai/provisioning/profile.json` with file mode
`0600` in a mode-`0700` directory. Offline profiles require `--artifact-source`. Temporary public
SSH requires a canonical source CIDR narrower than the entire address space and an access window
of 5-60 minutes. Tenant deployment profiles accept only `manual` transport.

An existing destination blocks initialization unless `--force` is explicit. Force never follows
a symbolic link or replaces a non-file destination. Profile initialization changes no Azure
resource and reports `mutation_performed=false` in JSON output.

## Execution hosts

### Basic deployment and detailed provisioning

**Design and critique:** Requiring complete private infrastructure and every operational integration
before starting turns setup into a prerequisite for itself. Deferring authentication, data protection
or tenant-mandated policy would instead create an unsafe baseline. Split the work by what is needed
to run the product safely, not by whether the operator's PC happens to be inside Azure.

An ordinary PC with a supported CLI runtime and access to Azure management/identity endpoints can
initiate deployment. Internal-VM location, VPN, IMDS, an attached Managed Identity or a precreated
Foundation are not universal PC prerequisites. Native OS support remains subject to the implemented
toolchain; using a supported Linux environment does not require the physical PC to be an Azure VM.

| Stage | Required outcome | Not a prerequisite for this stage |
|-------|------------------|----------------------------------|
| Basic deployment | AKS Standard with API Server VNet Integration, dedicated workload and API-server subnets, the five baseline services and required dependencies, durable state and migrations, minimum workload identity/RBAC, authenticated Console URL, restricted public management access, independent baseline health and restart persistence. | Private endpoints, VNet peering, private DNS, private-cluster mode, full resource discovery, model-capacity certification, optional connectors/ChatOps, organization-specific policies, production scale tuning or autonomous-action promotion. |
| Detailed provisioning | Add selected private networking, operating scope, models, integrations, policies and capacity to the existing installation, with capability-specific exact plans, readiness and approvals. | Reinstalling the baseline, recreating verified resources or resetting persistent data and Trial start time. |

For basic deployment, collect only target, region, runtime/database choices and necessary cost/access
decisions. Reuse unchanged selections. Minimum dependencies and mandatory subscription policy cannot
be deferred; optional setup stays unavailable rather than represented by fake health or evidence.
Following the [Trial contract](installable-deployment-cli.md#source-provenance-and-trial), basic
installation requires no publisher signing key, and later provisioning does not renew the Trial.

The coordinator executes eligible management-plane steps from the PC. Basic deployment reserves
the network structure needed for later hardening, but it does not require peering the PC, attaching
a VM identity to it, creating private endpoints or manually building Foundation before starting.
Private data-plane steps required by policy use an eligible existing host or the minimum
installer-managed execution path included in the approved plan. Do not expose a policy-required
private service publicly or switch an existing backend merely to avoid the internal execution path.
Host preparation is installer work, not an extra product stage.

After baseline Console health passes, `/provisioning` may collect the intended peer VNet, address
ranges, private services, DNS and egress posture. The browser submits a content-addressed request;
it never receives the deployment identity or runs Terraform. The protected executor validates
non-overlap, produces an exact plan, waits for distinct human approval, applies it and independently
verifies peering, route, DNS, TLS, identity and endpoint reachability before public access is
removed. An ambiguous effect resumes verification only.

Report basic deployment success only after authoritative service and access checks pass. Detailed
provisioning may remain incomplete while the baseline is healthy; `subscription_ready=false` alone
does not mean basic deployment failed. Conversely, a cluster or Console shell alone is not baseline
success. Preserve existing result-field semantics and define any new stage-specific contracts before
implementation; do not relabel legacy whole-run receipts as basic success without their evidence.

Example: start from a laptop, review the baseline plan, and open the authenticated Console after
service checks pass. Then configure a model and managed-resource scope during detailed provisioning
without redeploying the working baseline or granting autonomous action authority implicitly.

### Existing host

Prefer `existing-host` for an eligible current internal VM, jumpbox or deployment host. Calling a
machine a PC or using a local terminal does not make it external. Verify the actual execution
environment, including Linux tooling under WSL where applicable, rather than inferring eligibility
from the desktop operating system. The selected host needs:

- network and private DNS reachability to every required private endpoint;
- Azure CLI and Terraform;
- a distinct workload identity with the approved deployment roles;
- durable access to the protected Terraform backend and plan store.

Manual execution means that the operator starts `fdaictl` on this host. It does not mean that
Terraform uses the operator's interactive Azure identity. An execution host without the required
workload identity is incomplete; this does not reject an ordinary PC acting only as coordinator.
On the execution host, Azure CLI validates the exact selected user-assigned identity for CLI
operations. Terraform backend and provider processes use native Managed Identity authentication
with that exact client ID, not the Azure CLI service-principal session, and inherited alternative
authentication selectors are removed before execution.
Reuse an existing appropriately scoped deployment identity where permitted;
do not require the identity or host to have been created by the current Foundation run. Identity
attachment, role changes and network changes still need their own reviewed scope and exact approval.

**Design and critique:** A separate managed VM is one implementation, not proof that a current VM
is unsuitable. Conversely, being inside Azure does not prove access to a particular private endpoint.
Check target, DNS, routes, TLS, backend authorization and executor identity separately. A missing
direct VNet peering alone does not prove that no approved routed path exists. Report the failed
check and the smallest repair, not a blanket requirement to provision another host.

When coordinator and execution share an eligible host, no SSH/Bastion hop or source transfer to a
second machine is required. Foundation handoff preserves verified resource context and authoritative
Terraform state; it does not inherently move resources or application data. Reuse a correct protected
backend. When migration is actually required, retain its exact approval and single-owner checks.
Never repeat a completed apply or fabricate a receipt to repair a missing installer completion record.

Existing-host selection does not by itself prove that every public coordinator path implements it.
Report an unsupported entrypoint or recovery-receipt path as an installer gap, separately from host
eligibility. Do not claim this documentation change completes that implementation or deployment.

### Managed VM

Use `managed-vm` when no suitable existing host is available or policy requires a dedicated deployment
host. External coordinator location alone does not justify replacing an eligible host.
The VM remains durable but is normally
deallocated. Protected state, plans, approvals, and audit records remain in private storage so VM
start, stop, or rebuild does not change deployment authority.

Inspection evaluates existing-host suitability first and creates no VM. Bootstrap planning
shows the VM, network, identity, role, access, cost, stop, and cleanup effects before approval.

## Access preference

The managed-host access order is fixed:

1. Approved internal SSH.
2. Temporary public-IP SSH when Azure Policy and the deployment profile allow it.
3. Azure Bastion.
4. Azure Run Command as an audited emergency path, or the registered
   [scoped Terraform operation](#scoped-run-command-terraform).

Fresh-subscription Genesis doesn't fall through this list. A profile with `access_method=bastion`
selects the exact Standard Bastion native tunnel created by Foundation. Enrollment material then
travels only through SSH standard input, and state handoff uses the same pinned host-key boundary.

`access_method=run_command` is explicit and never an automatic Bastion fallback. It can stage a
digest-bound execution bundle only from an eligible Linux deployment host over an already connected
peered private route to the selected WSL host. An exact profile and current human approval bind the
complete target descriptor, operation id, bundle receipt digest, and receiver digest. The active human account must match the derived tenant/subscription
binding, and live Azure readback must match the VM resource id, private address, and deployment UAMI.
Only then does the coordinator record an immutable claim before a
one-shot TLS relay listens or Action Run Command starts. The relay accepts only the selected host's
private source address; WSL pins the ephemeral certificate digest, verifies the fixed receiver and
bundle, and returns typed evidence over the same relay. No SAS, account key, bearer token, arbitrary
remote script, or cloud staging artifact belongs to this transport. An ambiguous invocation permits
one separately claimed verification-only call and never repeats extraction or fresh transfer. VM
lifecycle approval remains separate, and the staging receipt grants no Terraform apply authority.
The implementation uses Action Run Command (`az vm run-command invoke`), not a managed command
resource. It requires a healthy VM agent, an existing private route from WSL to the relay address,
one-command concurrency, a completion marker within the 4 KiB response bound, and completion inside
the 90-minute service ceiling. The Linux host must bind the reviewed private address and port and
provide Python and OpenSSL. These limits do not weaken the coordinator's shorter deadline.
The explicit adapter is `dev`-only with approval quorum one. Staging and production remain blocked
until this transport supports and verifies their protected approval quorum.

Targeted substrate plans include every role assignment the AKS workloads need at start, such as
the isolated-executor Event Hubs roles and the ingestion sender role. Subscription-scoped roles
that the deploy identity cannot delegate stay outside those targets.

### Scoped Run Command Terraform

**Design and critique:** The Terraform backend is private, and subscription policy can deny any public
exception, so a workstation can't initialize a root that uses it. Copying state to the PC or opening
the account would create a second state owner or weaken policy. An interactive VPN, Bastion, or SSH
session for every small change turns private networking into a development bottleneck. A hand-written
Run Command script avoids the network path but loses exact source, plan binding, and recovery
evidence.

`scripts/deployment/azure/scoped_terraform.py` lets an ordinary PC that reaches only Azure Resource
Manager run one registered Terraform scope on the existing managed deployment host:

- A private operator profile names the exact tenant, subscription, VM, executor client ID, and backend
  account, container, state key, and resource group. It accepts only the `dev-single-operator`
  approval profile. Staging and production stay blocked until this path supports a protected quorum.
- Source comes from `git archive` of the scope root at a commit that `origin/main` contains after a
  fresh fetch. The fixed receiver, `scoped_terraform_receiver.py`, comes from the same commit. The
  source, receiver, and variable digests, the backend, the executor, and the VM bind a
  content-addressed operation ID that the receiver recomputes.
- The variable file must be private, name only declared root variables, and contain no secret-like
  material. Backend input accepts only the account, container, key, and resource group. No SAS,
  account key, bearer token, or client secret crosses the transport.
- Action Run Command carries one fixed bootstrap that verifies the embedded receiver and payload
  digests. The coordinator passes the script as a private file rather than a command-line argument
  and bounds it to 192 KiB. The receiver returns one result line within 3 KiB, and Terraform output
  stays in root-only host files.
- The receiver requests an IMDS token for the exact executor client ID and tenant, clears inherited
  credentials, and selects Managed Identity for both the backend and the provider. It generates a
  `backend "azurerm" {}` block, rejects a backend block in source, and verifies the initialized
  backend binding.
- `plan` targets only the registered addresses and rejects any other address, delete, or
  replacement. Destroy mode accepts only deletes of the registered addresses. The PC shows the
  review, and the signed-in human types `<mode> <first 12 plan-digest characters>`. The approval
  records the human object ID, operation ID, plan digest, and a one-hour expiry.
- `apply` verifies the approved digest, writes a create-only pre-effect claim, applies the saved plan
  once, writes a receipt, and runs a targeted zero-change plan. A claim without a receipt blocks new
  plans and applies for the same state target from any source revision, and `verify` never applies.
  `apply` and `verify` reuse the source commit retained at plan time, so a later `main` merge can't
  split one operation. The PC then reads the resulting resources through Azure Resource
  Manager and compares their scope-specific authoritative properties. A transport timeout, lost connection, or missing result line records a private ambiguity marker for the state target; plan and apply stay blocked, and only `verify` for the same operation runs once the Azure Activity Log shows a terminal status for every Run Command since that invocation started. Azure's `Conflict` for an already running command is reported as busy, not as ambiguity.

The first scope, `aks-container-insights`, targets the AKS Container Insights data collection rule and
its cluster association. `aks-inventory-observation-roles` targets the substrate inventory Reader, Monitoring Reader, Log Analytics Reader, and pipeline-stage Event Hubs sender assignments; the coordinator sends only the root's local module closure, and declared legacy state moves may only change addresses. A rejected plan returns up to 12 out-of-scope addresses. Adding a scope is a reviewed source change with focused tests. The Run
Command permission already grants root on the VM, so this path adds no VM authority; it replaces
unrecorded manual commands with bound, recoverable operations.

This path has the following limitations:

- The host needs Terraform, Python 3, and provider download egress that the committed lock file
  verifies.
- Action Run Command allows one command per VM, a 4 KiB response, and a 90-minute ceiling.
- Plan, claim, and receipt records currently live only on the host.

Temporary public access is never a silent fallback. Its plan requires an allowlisted source CIDR,
key- or certificate-only SSH, a bounded access window, and automatic removal of the public IP and
temporary network-security rule. `0.0.0.0/0`, password authentication, and a persistent public IP
are not accepted. Cleanup is part of the operation's success criteria. Failed cleanup leaves the
operation incomplete and writes an audit record.

## Online and offline delivery

Online delivery is an optional distribution path. It uses the public `fdai-deployment-cli` package and a version-matched complete signed
deployment kit. The managed host consumes only the kit's authenticated binaries, providers,
runtime images, and migration wheels.

Operational validation does not require this publication path. A locally built, independently
verified complete signed kit supplies the local coordinator; no appliance image is produced.

The target release workflow builds the wheel and source distribution once in a read-only job, checks that
the Python and bundle versions match, and publishes that exact artifact through PyPI Trusted
Publishing only after the matching signed bundle is published. Only the publish job receives the
GitHub OIDC permission; no long-lived PyPI token is stored.

The public PyPI release line starts at `0.1.0`. Existing repository tags `v0.1.1` through
`v0.1.12` are pre-PyPI engineering milestones and are not rewritten. The first public release tags
the exact publication commit as `v0.1.0`. An installation with an active pre-PyPI bundle state
above `0.1.0` uses a fresh public release state or an explicit migration; it is not treated as a
semantic-version upgrade to `0.1.0`.

Disconnected Python installation uses the signed wheelhouse described in
[Package Assurance](../architecture/package-assurance.md). It contains the deployment CLI wheel,
its local dependency wheels, `requirements.txt`, `SHA256SUMS`, and one detached Ed25519 signature.
Standard OpenSSL, `sha256sum`, and pip commands verify and install it without a network call.

The private signing key stays outside the repository and package. The trusted public key is
provided independently. Pip owns interpreter, ABI, platform, dependency, and installation checks.

Terraform binaries, providers, runtime images, Console files, and migration assets are deployment
payloads rather than Python package contents. Deployment owners may validate those inputs when a
deployment selects them, but package completion does not require a complete kit, signed root, TUF
ceremony, nested bundle signature, SBOM, provenance document, appliance, or Azure receipt.

## Approval and apply

Every operator-initiated infrastructure or role-assignment apply requires one authenticated human
approval bound to the exact binary-plan digest. The executor is a distinct workload identity. A
changed or expired plan invalidates approval, and apply accepts neither `-auto-approve` nor
caller-supplied Terraform arguments.

Delete, replacement, role change, state-backend change, temporary-access creation, and
temporary-access cleanup are highlighted separately in human and JSON output. They use the same
one-approver provisioning policy. This deployment policy does not reduce the existing quorum rule
for high-impact autonomous runtime actions.

The target lifecycle is:

```text
inspect -> profile init -> bootstrap plan -> human approval -> exact apply
	-> access cleanup -> post-provision verification
```

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/provisioning-execution-profiles.md) |
| Install and command contracts | [Installable Deployment CLI](installable-deployment-cli.md) |
| Azure inventory and bootstrap resources | [Deploy and Onboard](deploy-and-onboard.md) |
| Plan, release, and rollback lifecycle | [Deployment](deployment.md) |
| Executor and human identity separation | [Security and Identity](../architecture/security-and-identity.md) |
