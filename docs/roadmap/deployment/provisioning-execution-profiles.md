---
title: Provisioning Execution Profiles
---
# Provisioning Execution Profiles

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

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| AKS basic deployment followed by detailed private-network provisioning | not-started | Two-stage contract below; no new runtime acceptance evidence | An ordinary PC can initiate the AKS baseline without prebuilt internal infrastructure. API Server VNet Integration, stage selection, baseline acceptance, Console network requests and resumable protected execution still need implementation and end-to-end validation. |
| Read-only inspection and profile initialization commands | implemented | `packages/deployment-cli`; focused profile, target, tool, and productization tests | The dedicated distribution registers `fdaictl`, writes private target-bound profiles, and returns review until execution-host evidence exists. |
| Managed VM, private backend, and manual deployment host | implemented | `infra/bootstrap/`, standalone deployment modules, and focused bootstrap tests | The durable VNet host, workload identity, private state, exact plans, and application apply run without GitHub Actions. |
| Audited Run Command private relay | implemented | `execution_bundle.py`, `run_command_receiver.py`, `run_command_private_relay.py`, fixed bootstrap/orchestration modules, and 25 focused passing tests | One eligible Linux deployment host can stage a digest-bound bundle to one peered WSL host without cloud artifact storage. Live Azure transfer evidence and automatic access-profile routing remain open. |
| Fresh-subscription local coordinator | implemented | `fdaictl provision azure`; `fdai-up.sh`; signed-kit, Foundation, Bastion, managed-host, approval, license, migration, and convergence modules; routed lifecycle tests | One `dev` process derives the target from the active Azure CLI user and keeps stateful transitions serial. Tenant deployment has no GitHub transport. A governed Azure receipt and complete subscription-assurance evidence remain open. |
| Prebuilt OCI deployment appliance consumption | in-progress | `run-deployment-appliance.sh`; focused script and CLI tests | Tenant provisioning can start the manual standalone coordinator from a release-published, digest-pinned appliance with no public artifact fallback. A governed artifact-offline Azure receipt remains open; tenant deployment does not construct the image. |
| Offline-kit construction and verification | validated | `fdai_deployment_cli.offline_kit`; locked release scripts; successful network-isolated air-gap drill | Signature-first verification, exact files, SBOM coverage, ABI/libc binding, private snapshots, and shipped-wheel installation pass. |
| Stable Network API Foundation discovery | validated | PR #926; `deployment-v0.1.0-r4`; [issue #803 evidence](https://github.com/dotnetpower/fdai/issues/803#issuecomment-5653340906) | The published signed bundle passed all Foundation input reads in West US 2; no plan, apply, recovery, or deployment-readiness claim was produced. |
| Temporary public-access cleanup | not-started | The access preference contract in this document | No composed command proves bounded creation, automatic cleanup, incomplete-on-cleanup-failure behavior, and audit closure. |
| Pinned TUF root and rotation | not-started | `docs/runbooks/offline-trust-ceremony.md` | The first root ceremony, package resource, client bootstrap, and rotation evidence remain open. |
| Post-provision verification | in-progress | Managed-host exact-plan apply receipts, ACR digest readback, migrations, health readback, and second zero-change plan; routed lifecycle tests | The implementation exists, but local-coordinator and appliance-entry-point receipts from one exact local signed kit remain open. Public release publication is not required. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-09-21 | implemented | Separated source and offline-kit Foundation planning plus private Terraform/filesystem helpers from the deployment CLI command facade. | `current change`; 12-lens critique; 184 focused plan and help-hardening tests; Ruff and strict mypy passed. | No parser handler, output contract, target binding, approval, or mutation authority changed. |
| 2026-09-21 | implemented | Split the retained internal GitHub protected-workflow client into immutable values, bounded subprocess transport, dispatch, private artifact I/O, plan metadata, apply receipts, and provider-schema evidence modules while preserving the public facade. | `current change`; 12-lens critique; 42 focused GitHub Actions tests; Ruff, strict mypy, LOC, design-route, and documentation gates. | Public tenant provisioning remains manual and GitHub-free. No command, credential, Azure role, or apply authority changed. |
| 2026-09-19 | implemented | Added a claim-first, source-address-bound, certificate-pinned private TLS relay for the explicit audited Action Run Command access path. It creates no cloud staging artifact, allows one verification-only recovery, and grants no apply authority. | `current change`; execution bundle and receiver modules, fixed relay/bootstrap/orchestration modules, 25 focused tests, Ruff. | Retain one exact live peered-host transfer receipt, then connect the explicit adapter to reviewed `fdaictl` access-profile routing without changing VM lifecycle or application approval. |
| 2026-09-17 | in-progress | Removed public release publication and online Azure convergence as operational-validation prerequisites. One exact locally built signed kit now supplies both the local coordinator and appliance entry points; online acquisition remains a supported optional distribution path. | `current change`; owner documents and Azure deployment skill; no runtime, signature, approval, or Azure behavior changed. | Build and independently verify one local complete kit, then retain separately approved local-coordinator and appliance-entry-point convergence receipts from those same bytes. |
| 2026-09-16 | not-started | Made AKS the explicit basic-deployment target and moved selected peering, private endpoints, private DNS, private-cluster mode and public-access removal into a Console-originated detailed provisioning plan. Tenant provisioning consumes prebuilt signed images and never builds or captures them. | `current change`; documentation and deployment-skill contracts only; no CLI, Console, Terraform or Azure effect claimed. | Implement the API-server subnet and public baseline, remove tenant image builders, add Console network request states and protected execution, and retain both baseline and private-transition receipts. |
| 2026-09-15 | not-started | Defined ordinary-PC initiation and separated baseline service deployment from later detailed provisioning. Advanced unselected configuration cannot block baseline success; policy-mandated security and state protection remain prerequisites for the effects that need them. | Current design and deployment-skill update only; no new CLI commands, schema fields, platform support or deployed behavior claimed. | Implement both stages and prove an outside-PC start reaches authenticated baseline health, then add a selected capability without reinstalling or resetting persistent state. |
| 2026-09-15 | in-progress | Clarified existing-host-first deployment: the current internal VM may own coordinator and execution roles; another VM, Bastion or state relocation is not automatically required. Separated actual endpoint/identity failures from installer wiring gaps. | Current documentation change in this profile and the deployment skill; no execution-path implementation or Azure acceptance is claimed. | Make the public coordinator honor an eligible current-host selection, preserve existing backend ownership and completed effects, and demonstrate exact-plan execution and independent readback without a redundant host transfer. |
| 2026-09-13 | validated | Published `deployment-v0.1.0-r4` with the stable Network API correction, verified actual draft/public downloads and installed bytes, and passed signed-bundle Foundation discovery in West US 2 without Azure mutation. | PR #926; source `c137aa104682a59b979f5f3554a06bf87c555b8e`, tree-identical protected merge `d312225c795ce9bb90022f37ebb7fd6f83a4d343`; successful CI `34755232779` and `34755464071`; archive SHA-256 `c7e8b3e99fd77534ad7e2b2321d2e677fb3fe316a946e4c58ef797d5682bbab5`; 11 isolated artifact checks, 304 signed files, 59 matching installed files, and 12 read-only calls yielding seven layout prefixes; [issue #803 evidence](https://github.com/dotnetpower/fdai/issues/803#issuecomment-5653340906). | Existing r1/r3 state and claims remain unchanged. Explicit r4 source selection and a distinct prepared context are required; exact-plan approval, partial-image recovery, and online/offline deployment convergence remain open. |
| 2026-09-13 | implemented | Corrected Foundation discovery after Azure CLI selected a Network API unavailable in an existing resource's region. Route-table and local-gateway detail reads now pin `2024-05-01` without changing inventory scope, failure handling, or approval. | `current change`; `test_genesis_network_api.py`, `test_genesis_network_layout.py`, and `test_genesis_prepare.py`: 32 passed; Ruff, format, strict typing, and a bounded read-only provider check passed. | Publish and verify a replacement signed kit; r3 retains its original bytes. No apply or recovery was performed, and deployment convergence remains open. |
| 2026-09-13 | validated | Published and installed `deployment-v0.1.0-r3`, including all 14 additional rounds (nine production corrections and five rejected hypotheses with regressions). Both protected PRs merged and exact-source main CI completed successfully. | PR #918 and #920; source `3b4c088ea20d1d77770912394141847bf9940886`; CI `34746227767`; archive SHA-256 `7b454ff37833d7f5c665fddb1f7954c99f8ebeda363c3a3d807f9707e4c6f82b`; 11 no-network acceptance checks for 304 files, 59 installed payload files, six images, seven support packages, and 11 Terraform roots; actual public download and network-denied online/offline retry checks. | The bounded reviewed slice has no confirmed Medium-or-higher defect; retained-copy accumulation is Low. Azure SKU eligibility and separately approved partial-image recovery/convergence remain blocked. The prerelease requires explicit artifact selection. |
| 2026-09-13 | implemented | H14 closes the buffered-read gap in the prior download deadline: use available-data reads so a slow stream cannot fill a large buffer through many socket reads before the next total-budget check. | `current change`; real `BufferedReader`/synthetic raw-stream failure reproduced; the focused acquisition suite passes after using `read1` where supported. | The total deadline can overshoot by at most one bounded socket read; release and Azure receipts remain separate. |
| 2026-09-13 | implemented | Completed 13 new critique rounds: eight production corrections and five experimentally rejected hypotheses with regressions. The bounded final review leaves no confirmed Medium-or-higher defect in acquisition, deadline/transport, approval input, and error presentation. | Commits `d8c4fa3a2` through `7e1f7a3f2`; 379 focused owning regressions passed; changed-source Ruff and strict typing; two read-only reviews plus the H13 counterexample. | Retained-copy disk accumulation is Low. Publish the hardened revision; Azure image recovery and convergence remain blocked and are not completed Low findings. |
| 2026-09-13 | validated | Built and published development kit `deployment-v0.1.0-r2` from integrated `74743842facfd3c986d3e069e2ae8e6714147bae`; cold-installed and verified the same artifact through actual public download and both offline source forms. | Required CI `34741317737`; issue #803 evidence; archive SHA-256 `4be041e244dfbcd3b69ea117f2c8a995ef14f2ae1188f55ad6ca00849c09e223`; 11 isolated acceptance checks: 300 files, 48 installed payload files, six images, seven support packages, and 11 Terraform roots. | This accepted artifact predates the subsequent 13-round CLI hardening. No Azure apply or subscription-readiness receipt was produced. |
| 2026-09-13 | implemented | Proved transfer exceptions stop the application immediately, preserve tunnel cleanup, and cannot reach a later command or ready receipt, even after expiry. | `current change`; integrated pre/post-expiry transfer-failure regressions passed without production changes. | The original failure is preserved rather than masked by a secondary expiry exception. |
| 2026-09-13 | implemented | Bound release downloads by one 15-minute monotonic transfer budget in addition to the 30-second socket limit; progress cannot renew it. | `current change`; previously passing slow-trickle stream now rejects and removes only its new partial download; acquisition regressions. | Retained prior archives and deployment state remain untouched; no network retry is added. |
| 2026-09-13 | implemented | Bound both application confirmations and actor lookup to the same at-most-ten-minute window, plan expiry, and remaining invocation budget; require a real terminal. | `current change`; reproduced unbounded read, timeout/noninteractive controls, shared-budget and existing exact/destructive approval tests. | An expired or closed input grants no approval and triggers no automatic retry. |
| 2026-09-13 | implemented | Proved expired image reviews still permit verification of an existing claim, without reselection, reapproval, or repeated apply. | `current change`; manual and automatic-selection claim/resume regressions preserve exact claim bytes and one original apply. | This verifies completed effects only and cannot repair a partial image build. |
| 2026-09-13 | implemented | Normalize Azure identity and managed-host I/O exceptions before rendering; raw OS or child-process fallback errors no longer print command arguments or private paths. | `current change`; five reproduced synthetic-marker disclosures and focused CLI/transport regressions. | Stable failure categories do not infer whether a claimed remote effect completed. |
| 2026-09-13 | implemented | Clamp every application SSH/SCP operation to one current deadline without changing command, stdin, identity, or tunnel cleanup. | `current change`; two reproduced transfer-to-substrate budget failures and direct transport regressions. | Expired or failed effects remain verification-only; no retry or approval is added. |
| 2026-09-13 | implemented | Start the coordinator budget before preparation, cap Foundation approval by current remaining time, and recompute the application handoff after Foundation and identity work. | `current change`; three previously failing fake-clock regressions and existing coordinator tests. | Bound each application transport operation by that remaining budget. |
| 2026-09-13 | implemented | Enforce the release HTTPS host/port allowlist before every redirect request, not only after the final response. | `current change`; three reproduced disallowed-target contacts; real urllib redirect-chain tests with synthetic HTTP transport and an allowed CDN control. | Publish the corrected CLI; no allowlist expansion or live retry is implied. |
| 2026-09-13 | implemented | Proved an existing offline cache cannot silently adopt an explicit online source without a bound source record. | `current change`; directory and archive cross-mode regressions stop before network I/O and preserve prior bytes. | Default-version legacy adoption still requires complete signature and snapshot verification. |
| 2026-09-13 | implemented | Proved local-directory acquisition executes the authenticated private snapshot, not later changes to the original bundle; a later retry rejects that changed source. | `current change`; deterministic source-replacement regression passed without production changes. | Preserve signature and complete snapshot checks in both modes. |
| 2026-09-13 | implemented | Proved that replacing an archive pathname cannot redirect the extractor's held original descriptor; no production change was needed. | `current change`; deterministic open-inode replacement regression passed. | In-place content changes remain subject to signature and snapshot checks. |
| 2026-09-13 | implemented | Reverify local archive and directory retries against the retained exact snapshot while creating a fresh execution copy and preserving previous evidence. | `current change`; two reproduced retry failures and four offline retry/tamper checks; owning acquisition suite. | Deliver the new CLI; retained partial applies still need separately approved recovery. |
| 2026-09-13 | implemented | Reject non-Linux POSIX hosts before either artifact acquisition mode, rather than treating x64 macOS or FreeBSD as Linux. | `current change`; five focused host-boundary regressions, including the four previously failing cases. | Publish the corrected CLI; Azure convergence remains separate. |
| 2026-09-12 | implemented | Restricted tenant provisioning to manual transport, removed workflow dispatch from the public CLI, allowed token-free observation-only installation, and added an OCI deployment appliance entry point. | `current change`; deployment CLI contracts, standalone modules, appliance scripts, and focused tests | Build one clean appliance and retain connected and artifact-offline Azure deployment receipts. |
| 2026-08-14 | in-progress | Adopted the implementation ledger; earlier provenance was not reconstructed. Corrected inspection, profile persistence, and offline verification from implemented to their evidence-backed current states. | current change; package metadata, bootstrap source, release scripts, and focused workflow checks listed in the scope table | Create the CLI package, restore offline verification, complete trust bootstrap, and validate the full lifecycle. |
| 2026-08-29 | validated | Added target-bound inspection and private profiles, restored signed offline verification, and completed the shipped-wheel network-isolated drill. | Campaign commits from `dd28b64d9`; focused tests and successful `airgap-drill.sh` | Complete managed-host Azure execution and retain protected post-provision receipts. |
| 2026-09-05 | implemented | Routed exclusive RCA reader identity apply and verification resume through an allowlisted bot-owned request. The downstream apply remains bound to a protected GitHub Environment and validates its reviewer policy from protected `main` before mutation. | `current change`; focused deployment CLI, workflow, and Environment policy tests | Retain one independently approved exact apply and effect receipt. |
| 2026-09-05 | implemented | Extracted the read-only inventory change accelerators from the scheduled inventory entry point while preserving the venue-selected workload identity, private runner transport, per-scope locks, durable cursor fencing, and complete-reconciliation authority. | `current change`; inventory accelerator and job tests, strict mypy, and enforced file-size gate. | Retain the integrated change-feed timing receipt tracked by the operating-instance owner. |
| 2026-09-06 | implemented | Added an installed inventory wrapper that accepts only positional `once` or `loop` modes for exact-image Container Apps rehearsals. It translates to the existing CLI without changing collection, projection, identity, or execution authority. | `current change`; focused inventory CLI tests, strict mypy, package build, and entrypoint discovery. | Retain one exact-image inventory projection refresh receipt before operational-history certification. |
| 2026-09-06 | implemented | Added a deadline-bounded active-generation projection release migration to the protected OI-16 execution profile. It performs no provider read, preserves the prior manifest and journal fences, and refuses incomplete or changed content before writing. | `current change`; focused replay CLI, projection, persistence, workflow, and package checks. | Retain one successful exact-release migration receipt from the protected dev campaign. |
| 2026-09-11 | implemented | Added bounded parallel execution for independent local artifact lanes, Foundation input discovery, provider inspection and registration requests, policy-probe resource operations, and tenant-directory reads. Stateful applies, approvals, cleanup, handoffs, repository writes, and protected application transitions remain serial. | `current change`; focused Genesis, provider-mirror, preparation, Entra, and productization tests | Retain timing evidence from the next exact-main supervised deployment without treating elapsed time as readiness. |
| 2026-09-11 | implemented | Added online and artifact-offline installed-package deployment from the active `az login` target without requiring GitHub Actions. Complete signed kits, a no-GitHub managed host, exact application approvals, operator-issued or Trial licensing, image readback, pre-activation migrations, and convergence checks share one path. | `current change`; deployment CLI and Genesis source; strict mypy; package build and cold install; routed deployment and Genesis tests | Build the complete signed release kit from a clean snapshot and retain online and artifact-offline Azure convergence receipts. |
| 2026-09-12 | implemented | Completed 16 standalone deployment critique and hardening rounds. Transport reuse now binds the exact signed kit, trust roots require Ed25519, destructive plans require a second exact confirmation, ambiguous applies resume by verification only, retained Foundation and Entra context is exact, provider fallback remains blocked, and license, migration, image, revision-health, and zero-change effects require independent readback. | `current change`; deployment CLI, release builder, ShellCheck, strict mypy, focused package and Genesis tests, and independent post-fix critiques | Build and reverify the clean signed kit, then retain online and artifact-offline Azure convergence receipts before raising validation state. |
| 2026-09-12 | implemented | Corrected complete-kit runtime metadata to read the digest from the verified OCI manifest descriptor after the first clean build reached that API boundary. | `current change`; `build-standalone-deployment-kit.sh`; clean local OCI and Console build | Rebuild and reverify the complete signed kit before deployment. |
| 2026-09-12 | implemented | Added GitHub's exact official release asset CDN hostname to the HTTPS allowlist after the first live online acquisition rejected the valid redirect before Azure mutation. Subdomains, credentials, non-default ports, and all other redirect hosts remain blocked. | `current change`; focused downloader regression; published `deployment-v0.1.0` asset | Re-run online acquisition and retain the target-bound Azure convergence receipt. |

### Remaining work

- [x] Implement `provision inspect` and `provision init` in the dedicated CLI package and pass no-mutation, mode-`0600`/`0700`, overwrite, symlink, and stable-JSON tests.
- [x] Restore offline-kit verification behind an injected release root and pass signature-before-parse, exact-file-set, no-follow digest, compatibility, and bounds tests.
- [ ] Implement temporary public-access creation and cleanup so cleanup failure leaves an incomplete audited operation, then pass CIDR, duration, authentication, rollback, and idempotency tests.
- [ ] Complete the TUF root ceremony and package bootstrap, with signed root and rotation evidence accepted by the offline trust ceremony.
- [x] Build and reverify one complete signed kit from a clean snapshot, then cold-install its CLI and acquire the same kit through both online and local artifact paths. Evidence: `deployment-v0.1.0-r2` and the 2026-09-13 artifact checkpoint above.
- [x] Publish a replacement complete kit containing the subsequent CLI hardening and repeat exact installed-artifact acceptance. Evidence: `deployment-v0.1.0-r3` includes H01-H14, all 59 default-installed payload files match its signed wheel, and the prior installation was backed up.
- [x] Publish and verify a replacement signed kit containing the stable Network API correction, then confirm Foundation discovery from that exact artifact without treating discovery as deployment readiness. Evidence: `deployment-v0.1.0-r4` and the linked issue #803 read-only checkpoint; the existing installed CLI already matches all 59 signed wheel files and was not replaced.
- [ ] Retain target-bound Foundation and application convergence receipts from the local coordinator and appliance entry point using the same exact locally supplied signed kit, without requiring public release publication or claiming whole-subscription readiness.
- [ ] Demonstrate current-VM `existing-host` execution without creating a redundant host or relocating an already correct protected backend, retaining identity, exact-plan, no-repeat and readback checks.
- [ ] Retain one exact live private-relay Run Command staging receipt over the reviewed peered route,
  then connect the explicit adapter to `fdaictl` access-profile selection without broadening VM,
  network, plan, or application authority.
- [ ] Demonstrate ordinary-PC basic deployment without preconfigured private access, with later detailed provisioning that preserves installation identity, existing state and Trial start time; keep optional missing capabilities separate from baseline health.
- [ ] Create the AKS basic profile with API Server VNet Integration and dedicated workload and API-server subnets, then prove authenticated restricted public management access from the initiating coordinator.
- [ ] Implement `/provisioning` network intent, assessment, exact-plan request, approval, apply, rollback and independent readback for peering, private endpoints, DNS and private-cluster mode.
- [ ] Remove tenant-run Docker, Buildx, ACR Tasks and VM image-capture paths; require a prebuilt signed image manifest and deployed-digest readback instead.
- [ ] Build one deployment appliance from an approved digest-pinned base, verify its SBOM and provenance, and retain an artifact-offline Azure deployment receipt from the image entry point.

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
The invocation budget begins before preparation. Approval waits and application handoff use
current remaining time; an expired budget starts no next stage and cannot produce readiness.
Application confirmation requires a real terminal and one at-most-ten-minute window shared by
both prompts and actor lookup, shortened by plan expiry and the remaining invocation budget.
`DeadlineTransport` clamps each existing Bastion command and file transfer to that same current
budget and checks expiry after I/O. The underlying tunnel retains its own bounded cleanup.
Identity and transport failures use fixed diagnostics; raw OS and subprocess exceptions never
render command arguments or paths. Unknown effect outcomes still require retained-state review.

The command discovers an operator-held mode-`0600` license issuer key from an explicit option or the
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
4. Azure Run Command as an audited emergency path.

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
verified complete signed kit can supply both the local coordinator and the deployment appliance.

The target release workflow builds the wheel and source distribution once in a read-only job, checks that
the Python and bundle versions match, and publishes that exact artifact through PyPI Trusted
Publishing only after the matching signed bundle is published. Only the publish job receives the
GitHub OIDC permission; no long-lived PyPI token is stored.

The public PyPI release line starts at `0.1.0`. Existing repository tags `v0.1.1` through
`v0.1.12` are pre-PyPI engineering milestones and are not rewritten. The first public release tags
the exact publication commit as `v0.1.0`. An installation with an active pre-PyPI bundle state
above `0.1.0` uses a fresh public release state or an explicit migration; it is not treated as a
semantic-version upgrade to `0.1.0`.

Disconnected delivery uses the same `fdai` wheel and command contracts in a platform-specific
offline kit. The kit contains:

- the FDAI wheel and all transitive Python wheels;
- the signed deployment bundle;
- a pinned Terraform binary and provider mirror;
- OPA and required helper binaries;
- an SBOM, SHA-256 manifest, signatures, and the release trust metadata.

Complete staging builds the signed deployment bundle first, then assembles runtime v2 from a
private digest-bound descriptor against those exact bundle bytes before signing the outer kit.
An independently prebuilt runtime remains supported only when it already binds that exact bundle.

Offline mode blocks fallback to PyPI, GitHub, and the public Terraform registry. The artifact
source may be an approved internal mirror or removable media. The installer and `fdaictl` verify
the same pinned release root in both cases.

The target `verify_offline_kit` implementation checks an Ed25519 signature before parsing the manifest, binds exact CLI and
platform versions, rejects symlinks and extra files, streams every file digest, and requires the
wheel, signed deployment bundle, Terraform binary and provider mirror, OPA, and SBOM. The release
root is injectable for tests, release construction, and pinned inspection composition only.
Artifact hashing uses a no-follow descriptor open so a path swap cannot redirect it. `fdaictl`
does not expose a
`--release-root` override; inspection remains `review` until a public root is pinned in the wheel.

Executing kit content demands stronger evidence than reporting on it. `provision plan` runs the
kit's Terraform binary, so it verifies the kit against a release root the operator supplies and
refuses to plan when that verification fails. Both paths resolve every artifact from the signed
manifest rather than from a directory convention. When the pinned root ships, `--release-root`
becomes a planning override that inspection still does not accept.

`build_offline_kit_manifest` is the intended release-side inverse of that verifier. It reads the staged kit
with the same scan, so it refuses to describe a symlink, a non-regular entry, or an out-of-bound
tree, and it derives the file list from the stage rather than from an operator-supplied list. A
declared artifact role that is absent from the stage fails before anything is signed, and two
builds of identical content produce one identical signable byte string.
`scripts/deployment/release/build-offline-kit.py` is intended to add signing after the verifier
module is restored: it loads an operator-held Ed25519
private key, removes any stale signature before writing the new manifest so an interrupted run
leaves an unverifiable kit rather than a plausible one, and re-verifies the written kit against
the public release root before reporting. The private key never enters the kit, the repository,
or any log line.

### Trust root and rotation

The final offline authority uses The Update Framework (TUF) 1.0 through Python-TUF 7. The wheel
ships the initial signed `root.json` through an out-of-band trust bootstrap. Root private keys stay
offline. CI may use delegated online keys for targets, snapshot, and timestamp metadata, but it
never receives a root private key.

Clients update root metadata one version at a time and require each new root to satisfy both the
old and new root thresholds. TUF metadata expiry and monotonic versions provide freeze, rollback,
and mix-and-match protection. The metadata threshold and key ceremony are release-security policy;
they are independent from the one-person approval required for a provisioning apply.

The current exact-content verifier remains defense in depth after TUF authenticates the target.
Python-TUF integration and the first root ceremony remain blocked until the offline root is created
and backed up outside CI. No generated private key is committed or transferred through `fdaictl`.

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
| Install and command contracts | [Installable Deployment CLI](installable-deployment-cli.md) |
| Azure inventory and bootstrap resources | [Deploy and Onboard](deploy-and-onboard.md) |
| Plan, release, and rollback lifecycle | [Deployment](deployment.md) |
| Executor and human identity separation | [Security and Identity](../architecture/security-and-identity.md) |
