---
title: Installable Deployment CLI
---

# Installable Deployment CLI

This document defines the public FDAI deployment command. Operators run one local coordinator
after Azure sign-in, while Terraform apply and private data-plane work run on the managed host
inside the target virtual network.

> **Execution boundary:** Terraform remains the infrastructure source of truth. `fdaictl` owns
> validation, artifact verification, exact-plan approval, managed-host coordination, recovery, and
> post-deployment checks. Tenant deployment does not use GitHub Actions.
>
> **Implementation focus:** Azure is the only implemented target. Non-Azure providers are deferred.

## Design at a glance

| Concern | Decision |
|---------|----------|
| Operator command | `fdaictl provision azure` |
| Source-checkout command | `scripts/deployment/azure/fdai-up.sh` |
| Infrastructure engine | Terraform from the signed complete kit |
| Target selection | Active interactive Azure CLI user |
| Apply location | Managed deployment host inside the target VNet |
| Connected artifact source | Local complete signed kit for validation; versioned bounded HTTPS distribution is optional |
| Disconnected artifact source | Complete signed kit embedded in a digest-pinned deployment appliance |
| Approval | Current human approval bound to each exact plan digest |
| Execution identity | Managed host user-assigned Managed Identity |
| GitHub dependency | None for tenant deployment |

GitHub Actions may validate source, build images, and optionally publish signed releases; publication
is not a deployment-validation prerequisite. GitHub Actions cannot plan, apply, resume, or tear down a tenant deployment.

## Connected source deployment

Current source-mode support covers private preparation, read-only AKS capacity preflight,
exact-approved Foundation execution through private state handoff, and verified source transfer
to the enrolled host, plus source-runtime OCI image preparation. Connected deployment does not
build a dedicated managed-host image.
The public source command resumes these checkpoints using the shared private coordinator;
new interactive source installations confirm settings at startup only; later stages and JSON
execution never prompt. `--approval-file <path>` explicitly supplies an existing
private human approval to the shared verifier. Without it, retained ambient approvals are ignored.
`--foundation-workload <token>` selects the naming token for a new source installation and defaults
to `fdai`. Use a distinct token when canonical application or operations groups already exist.
The token is sealed into source preparation, retained variables, the run binding, and every exact
Foundation plan. Repeat it unchanged on approval resume. It grants no ownership of existing
resources and never authorizes deletion or adoption.
Initial confirmation is separate from that approval. The coordinator advances within exact approval and returns review state when another
checkpoint needs authority; it does not create approval, read stdin or report success. Managed-host application
execution and durable Trial activation are not yet connected. A plan
returns exit code `2` for review, not deployment success; a capacity blocker returns `3`.
`--prepare-only` makes no Azure call. `--preflight-only` reads the current human target, SKU
restrictions, x64 architecture, host encryption, required zones and shared-family/total quota at
autoscaler maximum plus simultaneous 33-percent surge. It neither reserves capacity nor accounts
for the Foundation graph. The distinct source work directory never adopts a kit run.

After initial confirmation, a bounded public-price read adds an explicit partial AKS compute
cost review before Foundation planning. A compute-only overrun blocks; an under-ceiling result
still leaves full installation and setup costs unverified. The [runtime profile owner](runtime-deployment-profiles.md#state-ownership)
defines price selection and exclusions. Runner-image reviews retain their legacy numeric estimate
for artifact-offline compatibility only. Connected deployment has no runner-image review.

Connected Foundation preparation resolves one exact Canonical Ubuntu 24.04 Marketplace version,
selects quota for only the managed host, and seals the existing checksum-pinned bootstrap script
into the Foundation plan. The script installs and verifies the exact Azure CLI, Terraform, OPA,
ORAS, attestation, and state-migration tools on that host. No builder VM, verifier VM, image capture,
or runner-image approval is part of this path.

Artifact-offline deployment can still select a separately verified prebuilt host image when the
managed host cannot download bootstrap artifacts. That optional path retains its image-specific
review and recovery tools, but those tools do not block or define connected deployment.

The interactive checkpoint prompt resolves that same trusted CLI before reading the current
human approver. A missing trusted executable or a service-principal account cannot create approval.
The existing human-only terminal confirmation remains mandatory; selecting a checkpoint does not
grant approval or apply any resources.

Source and kit Foundation inputs use distinct types and saved-plan schemas. A retained source
plan must match the current snapshot and source-input digests. Source execution copies the
verified infrastructure into a private state-preserving directory, verifies the pinned Terraform
binary, and acquires only lockfile-selected providers for a local mirror. The immutable snapshot
does not receive Terraform state or generated data. Existing exact-plan approval, pre-effect claim,
verification-only recovery, and independent readback remain authoritative. Private state transfer
includes the Foundation root, its sibling bootstrap module and shared modules, so relative module
references remain valid on the managed host. These adapters do not prove a completed deployment.

The source coordinator uses the private managed-host route explicitly. It reads Foundation
provider registrations and inherited policy assignments without registering providers or creating
policy-probe resources. Policy visibility is not a compliance or deployment-success claim.
An exclusive run lock covers the shared checkpoint coordinator. Exact approval is collected
separately before unattended execution; output format and TTY presence never grant authority. The same
source, snapshot, human target and retained run must match on every resumption. No approval from
one checkpoint grants another checkpoint, and published exact-source CI remains mandatory before
resource effects. A verified Foundation handoff still leaves application deployment incomplete.

### Application group collision recovery

**Initial design:** Change the shared workload token when an existing application group blocks a
new installation. **Critique:** That also renames operations resources after a partial apply and
can replace already created infrastructure. **Revised contract:** Optional `application_workload`
selects only the application's CAF group-name token; null preserves the legacy name. Operations,
state-account and image names keep their original inputs. The selected group remains Terraform-owned
and flows through the existing group reference and private handoff, without adopting an existing group.

An existing group is not an empty deployment slot, even when its tags resemble FDAI. This input is
not a recovery command or authority: a changed name requires a new exact plan and current approval.
Partial recovery must retain the original authoritative state and claim, prove every completed
resource remains no-op, and reject import, replacement, deletion or expanded roles. Completed
resources are compared with their recorded state and stable IDs, not unrealized initial plan defaults;
only equivalent empty representations and originally computed fields can differ. AzAPI dynamic
state values are decoded through their structured type/value representation before comparison. The ordinary
claimed apply remains verification-only; this naming input alone cannot resume the partial deployment.

`operations_public_ip_tags` is empty by default and accepts only the exact policy-owned
`FirstPartyUsage=/Unprivileged` value as an alternative. It is passed explicitly to the existing
Bastion and NAT IPs, not ignored through lifecycle rules. Recovery requires the same allowed value
on both retained IPs and pins that value in the new plan; unknown or differing tags stop preparation.
This prevents a policy-added tag from forcing replacement of the IPs and their dependent connections.

`genesis_foundation_recovery_plan.py` uses a fresh private directory under the original lock,
validates original review/claim/snapshot/configuration, and passes the original state path directly
to Terraform. It binds current source, provider and plan bytes, retains bounded private diagnostics,
checks group ownership and rejects concurrent state changes. Its expiring review grants no authority.
When the original plan already contains the supported application-name and public-IP policy inputs,
the recovery planner accepts byte-identical current configuration instead of requiring the legacy
source migration again. Any other source difference remains blocked.
Recovery reads the image-augmented Foundation variables when an artifact-offline image was used,
or the base Foundation variables for an image-free connected run. It never fabricates an image
receipt or changes bootstrap mode while selecting the retained input.
When the application group already exists in the original state, policy-only recovery preserves
its exact state ID and requires a no-op. It never renames or adopts that group. A missing
application group still follows the distinct-name and verified-absence contract.
If policy input reconciliation makes every retained resource no-op, Terraform reports the saved
plan as non-applyable. Recovery accepts that only when every resource action is `no-op` or `read`;
any pending effect still requires an applyable plan.

`genesis_foundation_recovery_apply.py` requires fresh `foundation-apply` approval bound to the recovery
review and code; the official prompt accepts `--foundation-recovery-review`. Before its immutable claim,
it verifies current human identity, exact-source CI, original claim/snapshot/lineage, group ownership,
current VM SKU/quota, configuration/provider/plan/tool/state hashes and expiry. It applies once against
the original state; claims permit only `--verify-only`. Group readback uses explicit name/subscription
and checks the exact ID. Independent readback and zero change gate the receipt; host/state/app checks remain separate.

One successor may select `--predecessor-directory` after the initial recovery is claimed but incomplete.
The predecessor's review, claim, plan, variables, configuration and provider hashes remain immutable.
All recorded resources, including the newly created application group, must stay no-op with matching IDs
and known settings. Exactly two absent creates are permitted: the host's ephemeral OS disk changes from
`ReadWrite` to required `ReadOnly` caching; the observation delegate's scoped role-definition operands
become bare GUIDs. The three observation roles, `ServicePrincipal` restriction and write/delete clauses
are unchanged. Only those two exact bootstrap source edits are allowed. The group is independently
read by ID, not assumed absent. New review, source CI and approval are required; predecessor approval
cannot authorize the successor. Further successor chains, imports, replacements and extra effects are rejected.
Successor regressions retain collected helpers even when runtime tests replace Python module names.

### Recovered host enrollment

The enrollment adapter checks the unaltered recovery receipt, both claims, review, original snapshot,
state hash/lineage and private handoff under the original lock. Shared correlation fields exist only
in memory, never as a fabricated ordinary receipt. Current approval, source CI and independent host
attestation remain separate requirements; this boundary does not migrate state or activate services.

The runner enrollment command accepts `--foundation-recovery-directory` together with the original
plan directory and `--original-source-snapshot`. A new enrollment requires `--recovery-approval-file`;
the official prompt produces it from `--recovered-foundation-receipt`. Approval binds that receipt's
digest and the enrollment source, not the earlier recovery plan. Recovery and enrollment source CI
must both pass. Claims, known hosts and enrollment receipts stay in the recovery directory, retain
the recovery receipt, enrollment source and approved actor. Verification-only resume never reenrolls
or changes that source. Ordinary enrollment remains unchanged.

### Recovered state migration

Only a transient archive combines verified recovery configuration and original state; both inputs stay
unchanged. Duplicate state owners or changed receipt-bound hashes/bytes block publication in the existing host format.

The state-handoff command accepts `--foundation-recovery-directory` and `--recovery-approval-file`
alongside its original source inputs. The official prompt takes both `--recovered-foundation-receipt`
and `--recovered-enrollment-receipt` to issue a separate `foundation-state` approval bound to both
receipts and current migration source. The adapter verifies both retained claims, original state or
exact backend authority, host-key evidence, recovery configuration, providers and variables, and CI
for recovery, enrollment and migration sources. It holds the original writer lock through the shared
claim-before-transfer, managed-host reattestation, backend migration, independent state comparison
and cleanup flow. No ordinary Foundation receipt is fabricated.

Migration records retain recovery schema, current source and verified approver. A retained claim
permits verification only, never another transfer or migration. After backend authority permits local
state deletion, resume validates that authority and the final receipt, then independently observes
the backend. Missing local state alone grants no authority. Live recovery acceptance remains open.

### Explicit source recovery
Resume with `--source <current-checkout> --work-dir <original-run> --foundation-recovery-directory <recovery>`.
Original snapshot, profile, region and budget remain immutable; execution source is separate. Missing
success returns review. Separate exact approvals advance enrollment/migration; claims allow verification
only, never repeated apply or scope changes. Completed migration observes the backend without reenrollment.
The original lock protects source transfer; immutable progress preserves old status and false readiness.
Existing claims build/reverify five original-source images; wrong revisions, inventories or readiness
are rejected. Missing tools return review; registry import and activation remain unconnected.

**Design and critique:** A kit-shaped source object implies release trust. Instead, `standalone_host
verify-source-runtime` binds the snapshot's canonical `source_commit`, pinned digests and six OCI images, then
rechecks bytes. Opaque hashes prove neither executable contents nor signatures; no login, installation,
publication or authority follows. Support installation takes an admitted root, without kit fallback.

### Source transfer boundary

After the current private Foundation reaches its application boundary, the source coordinator
loads the original state-handoff receipt through its bounded plan reference. It checks the retained
digest, source, target, host attestation, remote-backend authority, zero-change plan and transient
cleanup. Portable status is a projection, not the original receipt to rehash.

The coordinator then prepares `source-transfer.tar` and an immutable local transfer receipt.
The uncompressed archive contains the canonical source manifest plus numbered regular blobs,
not archive-selected destination paths or links. The receiver reconstructs only manifest-owned
files and internal links into a fresh private snapshot, checking independently supplied archive
and snapshot digests before source execution. It rejects duplicate, missing, extra, absolute,
traversal, hardlink and conflicting file/directory records. Limits are 65536 files, 64 MiB per file,
2 GiB total source bytes and 16 MiB of manifest; archive overhead is separately bounded.
Existing output, partial state or changed receipts are preserved rather than repaired or replaced.
At most four file writes run concurrently, each retaining its private descriptor checks and
`fsync`. Final snapshot verification waits for every write; a failed write cannot produce success.

The installed `python -m fdai_deployment_cli.source_transport` receiver accepts the archive,
fresh destination and both independent digests, returns sanitized verification evidence, and never
executes the received application code. `--verify-existing` checks the same archive and snapshot
without writing, adopting partial state, or repairing files. Local preparation verifies a complete
receiver round trip before reuse; its receipt leaves remote transfer and deployment readiness false.

Installing that receiver from a signed kit would reintroduce the source-mode prerequisite this path
removes. Instead, a deterministic zipapp contains seven receiver modules from the exact snapshot
plus a fixed launcher. Each module's read bytes must match its manifest hash; the private bootstrap
is bounded to 4 MiB and runs on the host's Python 3.12 or later without installing dependencies.
It remains operator-selected source, not a signed release or entitlement.

The source coordinator transfers under its existing Foundation execution lock after source CI,
target and state authority checks. It validates the original Foundation and enrollment receipt chain,
pins the enrolled SSH key and host-key digest, and repeats the managed-host identity/tool attestation.
Only then does it record an immutable transfer claim, create a fresh private host directory and copy
the receiver and source archive through Bastion. The receiver hash is checked before execution;
archive and snapshot digests arrive independently over the authenticated connection. Returned
evidence must match the local receiver result. All remote operations share the remaining deadline.

A retained claim allows verification only, never another copy or overwrite. Failed or partial
transfers preserve the claim and fail the source stage. Verified host transfer produces its own
private receipt with `remote_transfer_verified=true`, but no apply authority or deployment readiness.
The public command checks that receipt against current local source and handoff evidence, then reports
`source_application_execution_not_connected`. Registry import and application execution remain
open. Local and mocked transport evidence do not establish a successful Azure deployment.

### Source runtime artifact admission

Source mode does not create service, dependency, deployment-host or appliance images. Tenant
provisioning never invokes Docker, Buildx, ACR Tasks, a remote builder or VM image capture. A source
checkout can prepare and verify Foundation inputs, but it cannot enter the application stage until
the operator supplies a trusted prebuilt runtime artifact manifest whose source revision matches the
immutable checkout.

The manifest identifies all five baseline service images, dependency images, Console content and
migration support by digest. The coordinator verifies signatures, provenance, SBOM coverage,
platform, source revision and exact file bounds before registry credentials are acquired. A cache
hit is accepted only after the same verification. Missing, partial, mutable-tagged or mismatched
artifacts stop with `runtime_artifacts_required`; the installer never repairs them by building.

Private registry mirror or import remains execution-host work when selected. It changes only the
artifact location, independently reads back the same digest and cannot alter image bytes. An
ambiguous publication claim resumes verification only and never rebuilds or republishes the image.

An existing `dev` AKS installation can update one service directly from a clean local checkout on
its eligible deployment host. This path is separate from new installation and release assembly:

```bash
fdaictl provision source-service-update \
  --source <clean-checkout> \
  --service operator-service \
  --application-work-dir <retained-application-work-dir>
```

The command snapshots tracked source, builds one Linux OCI archive with the exact Git revision,
validates its archive and manifest digests, and requests current human approval before registry
import. The retained deployment Managed Identity performs the import and reads back the digest.
The coordinator then produces a Terraform plan limited to the selected Deployment, requests the
normal exact-plan approval, applies it, verifies healthy replicas and unchanged peer rollout
identity, and requires a targeted zero-change plan. A retained import or apply claim permits only
verification recovery. This path accepts no dirty checkout, mutable tag, direct developer registry
push, direct `kubectl` mutation, staging or production target, new installation, dependency image,
database migration, or runtime-profile change. It creates operator-selected source evidence, not a
release signature or deployment readiness for the whole installation.

An installation whose workload state predates the standalone application receipt can use a bounded adoption step by supplying all five `--adopt-historical-*` inputs: a private binding, retained Terraform state, workload variables, live Deployment snapshot, and the historical exact plan. The binding can reference execution assets only below its evidence directory and pins the Terraform binary digest, source revision, Managed Identity, and runtime profile. The coordinator accepts the historical plan only when it contains one in-place Deployment update and no unrelated mutation, or when it is a complete zero-change plan. It then uses the Managed Identity to compare remote state and current Deployments, creates a fresh full Terraform plan, and writes a distinct adoption receipt only when that plan is complete and zero-change. Partial inputs, changed peers, state drift, a tampered receipt, or a plan with changes stop the update. Adoption writes local evidence only; it does not change Azure resources or grant apply authority.
The development source path is selected explicitly with `fdaictl provision azure --source <path>`.
It is mutually exclusive with `--online` and `--offline-kit`. Initial support targets a new
`dev` installation using AKS and PostgreSQL Flexible Server. It does not migrate an existing
Container Apps installation and does not claim disconnected or production readiness.

### Initial confirmation and bounded unattended execution

**Initial design:** Ask for installation scope before the first execution stage, then use that
scope throughout a finite unattended run. Scope includes the exact source and target, runtime
profile, region, monthly estimate ceiling, separate setup estimate ceiling, Console access,
service retention, and temporary-resource cleanup.

`--setup-cost-ceiling` supplies a whole-USD setup estimate ceiling; a fresh interactive run asks
for it at startup if omitted. `--console-access` chooses `public-https-entra` (default) or
`private-https-entra`. `--allow-dedicated-identities` and `--cleanup-temporary-resources` are
explicit opt-ins, and services/data stay retained. These source-install-only settings cannot
silently apply to kit, preparation, preflight, or legacy exact-approval invocations. They are
preferences pending execution-side scope validation, not deployed settings or a billing cap.

**Critique:** A startup yes/no answer cannot authenticate later resource ownership, prices, RBAC
scope, or rollback safety. Existing plan reviews do not contain enough evidence for those checks.
Treating a saved scope as an exact checkpoint approval would erase an authority boundary.

**Revised contract:** Initial confirmation records installation preferences, not apply authority.
A fresh interactive source installation shows the complete scope and collects one bounded answer.
JSON and non-TTY runs return `initial_confirmation_required` instead of reading input. Preparation
and preflight-only calls do not ask. An exact retained confirmation resumes without asking; a
changed source, target, budget or option, expired confirmation, or an already-started run lacking
that record stops without prompting or silently renewing consent. Legacy exact-approved resumes
remain supported without treating an approval file as blanket scope consent.

The confirmation has an immutable private record, an exact preparation/run binding and a finite
validity window. Its digest detects drift, not human identity or authorization. It cannot mint
`fdai.genesis-approval.v1` records, and it never enables runtime action authority or Trial.

Full start-once execution additionally requires an independently reviewed bounded authorization
adapter for every effect. Before each claim it must verify exact plan bytes, current source/target,
complete fresh price evidence against both ceilings, exact new-resource ownership, allowlisted
role/scope/principal tuples, no existing-resource destruction, current authorization/revocation,
and all existing lock, idempotency, rollback and audit requirements. Cleanup covers only declared
temporary resources created by that run and must independently prove absence. Retained services
and data are not cleanup targets. Missing evidence ends the run with a persisted review/blocked
result, never another prompt, guessed cost, automatic consent, or repeated ambiguous apply.
The scope collector can ship independently; until those effect adapters are verified, it cannot
claim that one initial confirmation completes deployment authorization. The initial collection
window is at most ten minutes, within the invocation deadline; the record lasts no longer than
the original invocation budget or 24 hours. Restart cannot extend it. Signed-kit startup and its
later approval prompts remain a separate integration requirement, not implemented by this change.

### Source provenance and Trial

Automatically prompting on a text terminal interrupts unattended runs. Automatically approving
every later plan would erase the exact-plan boundary. The revised source interface separates
approval collection from execution: one explicitly supplied, current, source-bound checkpoint
approval permits its existing scope only. Missing or expired authority produces retained review
evidence and exit code `2`, without waiting for stdin. Signed-kit interaction is unchanged.

Skipping signature checks on a deployment kit would erase its trust boundary. Instead, a source
deployment pins a clean Git commit, records exact source and dependency digests, and transfers
only the required inputs through the authenticated managed-host connection. Source provenance
is explicitly `operator-selected-source`, never `signed-release`. A changed checkout, missing
input, altered snapshot, or conflicting retained run stops before any new effect.
Reading an internal tracked document link may update its access time without changing source.
Verification ignores that access-time-only change, while checking the target bytes, file identity,
mode, size, modification time, and change time; links outside the tracked snapshot stay blocked.

Source alone is not a complete runtime deployment input. It avoids local release assembly and
publisher keys, but the application stage still requires the prebuilt signed runtime artifact
manifest described above, digest readback and configuration validation. Foundation, private
data-plane execution, exact-plan approvals, immutable claims, bounded commands, independent effect
checks, and recovery remain required. A failed kit or runtime-artifact verification never falls
back to source mode or an installation-time build.

No license starts a durable 30-day Trial at first activation, not on each process start or image
upgrade. Trial availability does not change promotion, risk, RBAC, human approval, or executor
identity. Expiry blocks new acting work while preserving observation, diagnosis, export, audit,
and safe completion or recovery of in-flight work. Missing or inconsistent retained Trial state
cannot silently create another Trial. A later trusted entitlement can replace Trial without an
infrastructure reinstall; a release signature alone is not an entitlement.

These are target contracts. The implementation ledger records separately the source entrypoint,
Foundation execution, workload activation, Trial enforcement, and live acceptance. Deployment
readiness remains false until all selected services, identities, migrations, transport, jobs,
Console authentication, cleanup, and second zero-change plans have been independently verified.

## Operator experience

Use one exact local signed kit for both required operational-validation entry points:

```bash
az login
scripts/deployment/azure/fdai-up.sh \
  --offline-kit /private/fdai-deployment-kit.tar.gz \
  --region <azure-region>
```

The wrapper creates the locked environment and invokes `fdaictl provision azure --offline-kit`.
Embed those same verified bytes in the deployment appliance for its separate receipt.

**Design revision:** The initial online-plus-appliance evidence rule coupled tenant validation to
external release publication. Local signature, exact-file, source, image, SBOM, and provenance
checks already bind the archive. Therefore the local coordinator and appliance receipts use the
same locally built kit; public publication and `--online` Azure convergence are optional
distribution evidence. Exact-plan approval, managed identity, verification-only recovery, and
second-plan zero change remain mandatory.

The command derives tenant and subscription only from the active Azure CLI user. It does not
require a GitHub account, Git remote, repository variable, repository secret, workflow dispatch,
or registered GitHub runner.

### Discover commands safely

Running `fdaictl` without arguments displays the same overview as `fdaictl --help` and exits with
code `0`. A command group by itself, such as `fdaictl provision`, displays that group's help.
Help and the top-level `--version` alias do not sign in, inspect Azure, download artifacts, or
create deployment state. The existing `version --output json` contract stays unchanged.

The overview describes each command and gives a short sign-in, doctor, and deployment example.
Leaf help explains the required artifact-source choice, defaults, units, output modes, and
advanced optional inputs. `onboard guided` is explicitly a simulation, not live deployment.
Help is static, plain text on stdout; it does not start a dashboard or read stdin.
The parser does not resolve the default home directory until an Azure deployment actually starts.

Without an explicit help or version request, unknown commands and options, incomplete leaf arguments,
and conflicting artifact sources remain usage errors on stderr with exit code `2` and a next-help
hint. No error is converted into a default deployment or an automatic retry. Long options require
their full names rather than accepting abbreviations.

### Terminal progress

Interactive text output uses an unboxed, scrolling activity stream on stderr. Colored status labels
distinguish running work, completed phases, approval waits, and failures without relying on color
alone. Phase transitions and bounded details remain in terminal history. A small transient view
updates only the current phase, elapsed time, observed download bytes, and Foundation checkpoint;
it never reserves a fixed panel or lists work that has not started. Completed coordinator phases
and reported child checkpoints remain separate counts, not time estimates or subscription readiness.

`--progress auto` is the default. Redirected output, `TERM=dumb`, or `NO_COLOR` selects plain
phase messages without terminal control sequences. Use `--progress plain` for readable logs or
`--progress off` to hide progress. `--output json` disables progress and preserves one
final result on stdout. Intermediate Foundation JSON is not repeated on stdout.

Interactive `auto` output appends each distinct Foundation checkpoint transition once and updates
the last observed activity without appending heartbeat-only lines. A bounded adapter recognizes only
the complete known Genesis introduction and exact progress format. It replaces duplicate banners
and ASCII bars; those observations never advance coordinator state or readiness. The current view
stays compact in short terminals, and final failure context remains in the scrolling output.

Unrecognized or malformed output remains native diagnostics, including warnings or prompts without
a trailing newline. Live redraw pauses for those details and for the separate exact approval path.
Original review and confirmation remain visible and unchanged. Plain, off, and JSON modes keep
their existing child-output behavior. Failure or interruption leaves the current phase incomplete,
restores the terminal, and never claims rollback or safe retry. Only the existing verified
deployment result can produce the ready summary.

The coordinator checks the orchestration exit code before accepting retained status for handoff.
A failed or signal-terminated child cannot advance identity or application setup from an older record.
Accepted status must match the exact next attempt, signed source, prepared run, and apply mode;
only a private-runner handoff can advance application setup. Missing, stale, or malformed status
remains blocked rather than being treated as progress.

After a failed child exit, a separate diagnostic reader may describe a recognized blocker from that
exact failed attempt. It uses bounded private input, rejects duplicate JSON keys and mismatched
context, and emits only fixed value-safe guidance. Missing or unrecognized evidence keeps the generic
error. A retained apply claim permits verification only, not another apply. Diagnostics never grant
handoff, cleanup, approval, or permission to delete state or switch work directories.

Before displaying an application approval, the coordinator validates the review schema, stage,
digests, action counts, and expiry. It rechecks expiry after confirmation; closed input grants no
approval. Live rendering starts with a fresh cursor footprint after each prompt so review text is
not erased. Initial or resumed startup interruption restores the cursor, and a secondary output
failure cannot replace the original deployment error.

Rendering belongs to the installed local CLI. It does not modify signed bundle code, parse raw
provider logs as progress evidence, write deployment status, or grant approval. Rich supplies the
terminal renderer; its locked dependencies are included by the existing offline wheelhouse export.
Do not replace the installed coordinator during an active deployment. A display update takes effect
only after installing the reviewed CLI while idle; it does not change an already running process.

## Public command model

| Command | Purpose | Azure mutation |
|---------|---------|----------------|
| `fdaictl version` | Show the installed CLI version | No |
| `fdaictl doctor` | Check Azure CLI and active authentication | No |
| `fdaictl provision inspect` | Inspect a manual execution profile and local prerequisites | No |
| `fdaictl provision init` | Create a private manual execution profile | No |
| `fdaictl provision bootstrap-reconcile` | Read target and Foundation state into an expiring plan | No |
| `fdaictl provision plan` | Plan a verified offline-kit Terraform root | No |
| `fdaictl provision console-update build` | Build one source-bound Console artifact from protected Git source | No |
| `fdaictl provision console-update plan` | Seal an existing-development target plus candidate and rollback artifacts | No |
| `fdaictl provision console-update apply` | Publish one exact Console plan and verify remote content and access | Yes, after exact terminal approval |
| `fdaictl provision azure --online` | Acquire a signed kit and run the standalone Azure deployment | Yes, after exact approvals |
| `fdaictl provision azure --offline-kit <path>` | Run the same deployment without public artifact acquisition | Yes, after exact approvals |
| `fdaictl onboard guided --simulate` | Rehearse the finite stage graph | No |
| `fdaictl onboard status` | Read a local hash-chained rehearsal journal | No |
| `fdaictl bundle verify` | Verify bundle signature, compatibility, files, SBOM, and digests | No |
| `fdaictl offline prepare` | Materialize a verified private offline snapshot | No |
| `fdaictl offline install-support` | Install migration support only from signed wheels | No |
| `fdaictl license inspect` | Verify a capability token without a network call | No |

The public CLI does not register `deploy plan`, `deploy apply`, or `deploy status`. Those commands
previously dispatched GitHub workflows and are not part of the standalone deployment contract.
Live onboarding uses `provision azure`; `onboard guided` is simulation-only.

### Existing development Console update

Use `provision console-update` only to update the static Console on an existing `dev` Container
Apps installation. It does not plan or change Terraform resources, service images, database state,
runtime authority, or a production installation. This compatibility path uses the local
coordinator and does not dispatch a GitHub workflow.

The `build` command accepts protected `origin/main` or one of its ancestors. It creates a clean Git
archive, runs the environment-isolated offline Console build, packages the allowlisted Manual Studio
content under `/manuals`, and writes a deterministic archive plus a mode-`0600` source manifest.
Ignored files such as `console/.env.local` cannot enter that snapshot. Build the candidate from
current protected `origin/main` and the rollback from a distinct known-good ancestor.

The `plan` command reads a mode-`0600` target manifest supplied outside source control. The manifest
contains the existing Static Web App resource ID and hostname, API origins, and public Entra
SPA client and separately registered API scope bindings. Planning requires the active Azure tenant and subscription to match, reads the Static Web
App hostname from Azure, verifies both artifact manifests, and creates a private plan that expires
within 20 minutes. Planning does not request a deployment token or publish content.
Invoking `apply` is explicit coding-session authorization for this bounded non-destructive dev update; it does not request another confirmation or machine-digest transcription. The command rechecks protected
`origin/main`, the Azure target, both artifacts, and plan expiry, then writes approval and claim
records that bind the validated plan digest internally before publication. A retained claim permits candidate readback only and never repeats the candidate publication, including after plan expiry. Recovery reuses tightened private attempt directories, uses the current reviewed publisher, verifies rollback content before any restore, and publishes rollback only when neither artifact is present. Remote hashes cover served `index.html`, runtime config, the hashed entry asset, and bundled Manual Studio files when present; `staticwebapp.config.json` is validated locally because the host consumes rather than serves it. The installer replaces only the reserved Manual Studio share-page origin with the exact same-origin `/manuals` URL. Rollback closure verifies this static effect independently from Operator and Ingestion health so an unrelated service outage cannot trigger repeat publication; the failure receipt records those service checks as unverified. A failed publication or claimed-content mismatch writes a terminal failure receipt. Success requires exact remote hashes, SPA
fallback, both API health checks, exact-origin CORS, unauthenticated denial, and the Entra redirect.
The resulting Console receipt does not set whole-application or subscription readiness.

## Signed artifact and execution safety

The installed CLI passes its own Python interpreter to fixed packaged Genesis launchers, plan
generation, and reverification. The outer Foundation timeout reserves process-group cleanup;
nested Genesis termination grace decreases at each of at most eight levels. Optional caller-owned
stdout and stderr descriptors preserve progress and machine-output separation without changing
stdin or cancellation. Status, approval, and safe environment filtering remain independent gates.

Reusable Console artifacts use the environment-isolated offline build and require installation-time
bindings, never host deployment defaults. CLI build tooling uses a stage-private environment rather
than the caller's selected virtual environment. Complete builds use one private detached checkout
of a pinned commit, excluding caller-local ignored inputs and signing keys. Raw tracked bytes,
modes, and a stable metadata fingerprint are checked throughout assembly and immediately before
signing; unchanged lockfiles or Git status flags alone do not prove source identity.

The complete release wrapper requires a fresh private output root and preserves earlier archives.
Caller-relative signing-key paths resolve before changing directories, and current-UID, mode-0600,
regular-file checks remain required. The build shares a three-hour total budget with per-stage and
no-progress deadlines, including an optional deployment appliance. Nested supervisors forward
cancellation with shorter cleanup grace than their parent. Success requires a valid archive checksum
and completion of every requested artifact stage; interruption cannot continue to later signing.

Source hardening covers packaged entry points, stateful verification-only resume, and nested
cancellation. Focused source tests do not replace signature verification, exact-file and SBOM
checks, or fresh and resumed complete artifact acceptance in the network-isolated air-gap drill.
See [Disconnected Deployment](disconnected-deployment.md) for the complete artifact trust boundary.

## Standalone deployment sequence

The coordinator performs these stages in order:

1. Read and validate the active Azure human target.
2. Acquire one online or local complete signed kit and verify every executable input.
3. Inspect policy, provider, quota, region, and Foundation state.
4. Create an exact Foundation plan and obtain current terminal approval.
5. Create the private state account, hub network, Bastion, deployment identity, and managed host.
6. Verify state handoff and the managed-host image.
7. Transfer the same verified kit through Bastion.
8. Run the substrate and application plans under the managed identity.
9. Read the Terraform-selected Core application name and derive the deployment-bound capability
  identity without recomputing an Azure resource name in Python.
10. Import and read back every runtime image digest.
11. Run database migrations and materialize the authoritative catalogs.
12. Deploy the services and verify runtime health.
13. Require a second zero-change Terraform plan before reporting deployment readiness.

Independent preparation and read-only probes can run concurrently. Approval, apply, cleanup,
state transition, handoff, migration, and application activation remain serial.

## Approval and recovery

Every mutating checkpoint binds approval to one exact binary plan and expiry. A changed plan needs
new approval. Destructive plans require a second exact confirmation. Silence never grants
authority.

Before an effect, the coordinator writes an immutable claim. If the outcome becomes ambiguous, a
later invocation performs authoritative readback and a zero-change plan. It does not repeat the
apply from the retained claim. Target, kit, Foundation, Entra, or provider-context changes require
a new prepared context.

### Retained kit acquisition

An online retry keeps the work directory and treats its retained kit as untrusted input. It checks
the package-pinned release signature, compatibility, exact file set, all digests, runtime images,
and bundle binding again before advancing. An existing materialized payload is reused only when it
matches those verified files exactly. A new execution copy of the signed bundle avoids reusing
Python bytecode, Terraform scratch files, or other residue from a previous execution copy.

The cache records a digest of the requested artifact URL to reject an implicit source switch.
This local record is not signature or remote-origin evidence. A legacy cache without this record
can be considered only for the default versioned source, after complete verification. It does not
prove that the published release is current. An override with an unbound cache is blocked.
Acquisition is serialized per work directory; it does not replace the deployment target lock.

HTTP status, connection failure, local destination conflicts, permissions, and storage exhaustion
have distinct value-safe errors. Corrupt or partial retained content is preserved and blocked,
not silently replaced or accepted. Retry never deletes run state, SSH keys, plans, or approvals,
never changes a signed source file, and never repeats an Azure effect from kit-cache evidence.

## Capability token behavior

A maintainer signing key is not an adopter prerequisite. The command uses a matching operator-held
issuer key when one is explicitly available, or verifies a supplied pre-issued Trial token. When
neither is present, a new installation can start in observation-only mode without creating a license
secret. Omitting a token on a resumed installation does not revoke one previously installed.
Without action authority, the Core can observe and report but cannot execute managed-resource actions.

A token never grants deployment or runtime authority by itself. Promotion state, risk policy,
human approval, executor identity, and effect verification remain separate controls.

## Deployment appliance

A disconnected release may publish the same complete signed kit inside a prebuilt OCI deployment
appliance. Appliance construction is an upstream release responsibility and is not a tenant
provisioning command. The tenant accepts only a digest-pinned appliance with verified provenance,
SBOM and embedded-kit signatures; otherwise it uses the kit directly. Tenant deployment never
constructs or modifies the appliance image.

The image entry point accepts either interactive Azure authentication or a specifically selected
user-assigned managed identity. It invokes
`fdaictl provision azure --offline-kit /opt/fdai/kit.tar.gz` and blocks all public artifact
fallback. `FDAI_DEPLOYMENT_APPLIANCE_KIT` can select another private regular archive, and
`FDAI_DEPLOYMENT_APPLIANCE_WORK_DIR` can select another absolute private work directory. Managed
Identity mode requires both `FDAI_DEPLOYMENT_APPLIANCE_USE_MANAGED_IDENTITY=1` and the exact
`FDAI_DEPLOYMENT_APPLIANCE_MI_CLIENT_ID`. The embedded kit carries Terraform, OPA, provider
mirrors, runtime images, Console, migration support, signatures, and software bills of materials.

## Result contract

`deployment_ready=true` means the selected application converged, service health passed, and the
second Terraform plan was zero-change. `subscription_ready=false` may remain while broader
subscription assurance, model-capacity certification, or complete inventory evidence is open.
These states are separate so a deployed application is not misreported as a fully certified
subscription.

The retained GitHub transport is compatibility code only, not a registered public deployment
command. Its post-apply receipt still requires Terraform convergence, migration success, and
enabled endpoint health; keeping those checks does not restore a workflow-based tenant installer.

All machine output uses stable English keys and excludes credentials, raw state, tenant values,
and secret content. Private local and managed-host directories use mode `0700`; sensitive files
use mode `0600`.

## Related docs

| To learn about | Read |
|----------------|------|
| Implementation status and remaining evidence | [Implementation ledger](../../roadmap-implementation/deployment/installable-deployment-cli.md) |
| Execution-host and connectivity choices | [Provisioning Execution Profiles](provisioning-execution-profiles.md) |
| Disconnected trust and artifact delivery | [Disconnected Deployment](disconnected-deployment.md) |
| Azure resource inventory and bootstrap | [Deploy and Onboard](deploy-and-onboard.md) |
| Identity and approval separation | [Security and Identity](../architecture/security-and-identity.md) |
