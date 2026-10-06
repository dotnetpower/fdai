---
title: Installable Deployment CLI
---

# Installable Deployment CLI

> **Deployment distribution:** The [constitution](../architecture/fdai-constitution.md#article-1-purpose-and-scope) defines three installation paths: the one-command source deployment, the signed offline package, and the [Hub-managed lifecycle](hub-managed-lifecycle.md), which is designed but not yet implemented. Any installation gate in this document that the constitution does not list is superseded and no longer applies. [One-Command Source Deployment](source-deployment.md) owns the source path's artifacts and entitlement selection.

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
| Infrastructure engine | Terraform from the selected signed profile closure |
| Target selection | Active interactive Azure CLI user |
| Apply location | Managed deployment host inside the target VNet |
| Connected artifact source | One clean checkout; service images are built from it into the deployment's own registry, as [source deployment](source-deployment.md) defines |
| Disconnected artifact source | Complete offline profile in one signed kit; no appliance image is produced |
| Approval | Current human approval bound to each exact plan digest |
| Runtime identity | Scoped read-only observation identity by default; privileged executor only for the explicit governed-execution add-on |
| GitHub dependency | None for tenant deployment |

GitHub Actions may validate source, build images, and optionally publish signed releases; publication is not a deployment-validation prerequisite. GitHub Actions cannot plan, apply, resume, or tear down a tenant deployment. The read-only [observer artifact preflight](../architecture/aks-outbound-connector.md#artifact-preflight) reuses the same pinned-root offline kit and OCI verifier for an exact Core image; its bounded process result creates no new release trust, approval or installation authority. The kit may also bind one optional default Rule activation profile by path, id, source timestamp, file digest, and complete-kit manifest digest. Preparation emits deterministic Core environment bindings only; it neither applies a generation nor deploys a tenant workload.

## Connected source deployment

Current source-mode support covers private preparation, read-only AKS capacity preflight,
exact-approved Foundation execution through private state handoff, and verified source transfer
to the enrolled host, plus source-runtime OCI image preparation. Connected deployment does not
build a dedicated managed-host image.
The public source command resumes these checkpoints using the shared private coordinator;
new interactive source installations confirm settings at startup only; later stages and JSON
execution never prompt. Under constitution Article 1 the invocation approves each checkpoint it
reaches: without `--approval-file`, the command runs
`scripts/deployment/azure/genesis_approval_prompt.py` itself, which reads the exact checkpoint the
run reached and records the operator's invocation as approval of the evidence it prints, and then
continues to the next checkpoint. Foundation and runner-image plan contracts refuse every update,
replacement, or deletion, so no Foundation checkpoint needs the typed confirmation that deleting or
replacing an existing resource requires. `--approval-file <path>` remains an advanced input that
supplies an existing exact record instead; retained ambient approvals are otherwise ignored. The
record binds the authenticated operator and expires 30 minutes after issuance, so reissue it if a
resume starts later.
Resuming a run repeats its sealed intent. Cost and profile arguments belong to that intent, so a
resume that omits or changes one is refused and names the differing fields rather than failing
opaquely.
`--foundation-workload <token>` selects the naming token for a new source installation and defaults
to `fdai`. Use a distinct token when canonical application or operations groups already exist.
The token is sealed into source preparation, retained variables, the run binding, and every exact
Foundation plan. Repeat it unchanged on approval resume. It grants no ownership of existing
resources and never authorizes deletion or adoption.
The region suffix is selected by the same naming owner as the offline package path: retained
Foundation variables keep their original token, a fresh work directory discovers one matching
FDAI-owned installation token before planning, and only reviewed public-region tokens are used for
new installs. An unknown or ambiguous token stops before Azure effects.
Initial confirmation is separate from that approval. The coordinator advances within exact
approval and returns review state when another checkpoint needs authority; it does not create
approval, read stdin or report success. After the verified Foundation handoff, source mode
continues into the shared managed-host application sequence without a signed kit. A plan returns
exit code `2` for review, not deployment success; a capacity blocker returns `3`.
`--prepare-only` makes no Azure call. `--preflight-only` reads the current human target, SKU
restrictions, x64 architecture, host encryption, required zones and shared-family/total quota at
autoscaler maximum plus simultaneous 33-percent surge. A `postgres-flex` profile also requires the
regional PostgreSQL Flexible Server catalog to offer PostgreSQL 16. It neither reserves capacity nor accounts
for the Foundation graph. The distinct source work directory never adopts a kit run.

After initial confirmation, a bounded public-price read adds an explicit partial AKS compute
cost review before Foundation planning. A compute-only overrun blocks; an under-ceiling result
still leaves full installation and setup costs unverified. Without `--monthly-cost-ceiling`, a new
run uses 1500 USD, which the default AKS profile fits; a retained run keeps the ceiling recorded in
its source intent or profile. The [runtime profile owner](runtime-deployment-profiles.md#state-ownership)
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

Source and kit Foundation inputs use distinct types and saved-plan schemas. A retained source plan must match the current snapshot and source-input digests.
Source execution copies verified infrastructure into a private state-preserving directory, uses `terraform` on `PATH` only when it matches the pinned binary digest or otherwise downloads the pinned release and verifies both committed digests, and acquires only lockfile-selected providers for a local mirror.
Before each source effect, the Foundation, runner-enrollment, and state-handoff steps check only that the clean checkout is the exact deployed commit. They never query a CI result or require the GitHub CLI, Azure Developer CLI, or a workstation Terraform. Runner enrollment reads that mode from the saved review that the Foundation apply receipt binds.
Source application continuation transfers one hashed requirements file exported from the committed `uv.lock` beside the snapshot. The managed host verifies its digest, builds the runtime support environment from it and the snapshot's workspace packages, and downloads the kit's pinned `kubectl` and `kubelogin` with digest checks. Because each resume re-extracts the snapshot, every Terraform initialization recreates the generated backend file.
The immutable snapshot does not receive Terraform state or generated data. Existing exact-plan approval, pre-effect claim, verification-only recovery, and independent readback remain authoritative.
Private state transfer includes the Foundation root, sibling bootstrap/shared modules, and the exact five `genesis-runner-image` support files referenced by Terraform.
For a retained claim created before that archive closure, recovery preserves the original claim and backend migration while restoring the exact support bytes from the reviewed recovery configuration.
It requires a fresh exact `foundation-state` approval before writing a current-source repair claim, installs only missing files without replacement, and places the current verifier outside Terraform's sibling input tree under a separate remote repair manifest; fixed remote inspection arguments use shell-neutral field separators.
That verifier then runs in `verify` mode. A later verified controller can reuse the completed repair only after revalidating the repair source and proving the verifier digest is unchanged. State comparison preserves exact lineage, resource identities, and non-transient content while allowing only one backend-migration serial increment and order-only `check_results` normalization. Refresh-only drift is accepted only when it keeps the same resource ID and its observed `after` value exactly matches the same address's no-op desired value; deferred or unclosed drift is blocked. After cleanup, reobservation transfers the current verified observer through the owner-only Bastion path, reads its digest back, and runs it under the managed identity. New authority records seal both normalized Terraform output and exact backend blob bytes; the observer downloads the protected blob through Azure CLI data-plane authorization, verifies its authority-bound digest and backend protection, then removes every transient file without restoring the old Terraform work tree or provider mirror. A completed legacy receipt that predates the blob digest remains valid through its original independent zero-change evidence, but no digest is invented and repeated blob reobservation begins only with the extended authority record. A partial base set, a different existing file, or changed readback blocks recovery.
These adapters do not prove a completed deployment.

`fdaictl provision azure --source <checkout> --teardown` is a source-only cleanup path. It derives
one review from retained source intent, source preparation, Genesis marker, and verified Foundation
handoff receipts. It can name only the application and operations resource groups proven by that
evidence, binds them to the target binding and source run binding, requires one exact
`--teardown-confirmation` value, and then reads back absence after deletion. Because Azure deletes
resource groups asynchronously, readback waits up to 30 minutes before it reports a partial
failure, and a rerun skips groups that already read back absent. If any ownership proof is missing
or names an unproven resource, the command stops before any delete call.

The source coordinator uses the private managed-host route and reads Foundation provider
registrations and inherited policy without changing either. Policy visibility is not a compliance
or deployment-success claim. An exclusive run lock covers checkpoints; exact approval remains
separate, and output format or TTY presence grants no authority. Source, snapshot, human target,
and retained run must match before effects. After verified Foundation handoff, the source path
transfers the pinned source snapshot to the managed host, installs the deployment CLI from it, and
builds images with Azure Container Registry Tasks rather than Docker or Buildx. The bounded
single-service `dev` update remains separate.
**Initial design:** build every runtime image during source provisioning. **Critique:** that makes the tenant an unsigned release builder. **Revised contract:** a complete signed kit uses `--adopt-foundation-directory` plus `--adopt-foundation-recovery` only after recovery, enrollment, state-authority, target, profile, host-key, cleanup, and zero-change verification.
**Superseded for new source installations:** Constitution Article 1 makes the tenant-side build the source path itself, with `operator-selected-source` provenance rather than release trust, as [source deployment](source-deployment.md) defines. The signed-kit adoption below remains for recovered Foundations that continue with an offline package.
Adoption stages exact handoff and access evidence and emits a no-effect receipt. The local coordinator retains the complete chain, and the managed host independently verifies the historical handoff digest plus the distinct current kit and runtime digests before preparation; neither repeats Foundation apply, enrollment, migration, or state ownership. Repository admission persists digest-pinned references for all five baseline services before application planning. Application plans, approvals, and the optional catalog review checkpoint remain separate.
The terminal Foundation receipt in that evidence is either a verified recovery receipt or the `applied` receipt of an ordinary Foundation apply, so a Foundation that applied normally continues without a recovery detour. Any other schema and state pair, including an in-progress apply, stops adoption.

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
open. Local and mocked transport evidence do not establish a successful Azure deployment. An eligible existing Windows host whose WSL environment is reachable only through audited Azure Run Command can receive a separate execution bundle from the exact Linux deployment host over an already connected peered private route. The coordinator runs on that Linux host and requires an exact `run_command` provision profile plus current human approval bound to the complete target descriptor, operation id, bundle receipt digest, and fixed receiver digest. Before any claim or relay effect, it derives the tenant/subscription binding from the active Azure account, verifies the current human actor, and reads back the exact VM resource id, private address, and deployment UAMI. It then records an immutable transfer claim before opening a one-shot TLS relay or invoking the target. The relay holds the exact bundle and fixed dependency-free receiver through verified descriptors, accepts only the target host's private source address, and keeps its ephemeral certificate and key in memory-backed descriptors. The fixed Run Command accepts only exact VM, relay, operation, size, count, mode, and digest coordinates. WSL checks the downloaded certificate against the independently supplied digest before using it as the CA, verifies both payloads, and runs the fixed receiver. SAS values, account keys, bearer tokens, arbitrary script text, and raw evidence never enter parameters or logs, and no cloud staging artifact is created. A retained ambiguous invocation permits at most one separately claimed `--verify-existing` call; it removes only stale download transients and never repeats extraction or fresh transfer. Success requires typed host evidence, the fixed host-cleanup marker, source-bound relay completion, and relay shutdown. The extracted execution tree is retained while downloaded transient files are removed. The receipt binds the current staging approval but grants no apply authority and replaces neither a later exact plan nor its approval. The adapter is explicit; automatic `fdaictl` access-profile routing and live Azure acceptance remain separate.

### Source runtime artifact admission

Source deployment follows the constitution's deployment distribution and is owned by
[One-Command Source Deployment](source-deployment.md): anyone with a clone runs one command, the
command builds service images from the checkout into the deployment's own registry, and no key,
signed kit, protected branch, CI result, published artifact, attestation, provenance, or SBOM is
required or created. `fdai-up.sh` builds and signs no kit: without a mode argument it deploys its
own checkout, and it refuses the retired `--signing-key` option. The offline package keeps one
signed package for
an Azure VM without internet access.

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

An installation whose workload state predates the standalone application receipt can use a bounded adoption step by supplying all five `--adopt-historical-*` inputs: a private binding, retained Terraform state, workload variables, live Deployment snapshot, and the historical exact plan. The binding can reference execution assets only below its evidence directory and pins the Terraform binary digest, source revision, Managed Identity, and runtime profile. The coordinator accepts the historical plan only when it contains one in-place Deployment update and no unrelated mutation, or when it is a complete zero-change plan. It then uses the Managed Identity to compare remote state and current Deployments and creates a fresh full Terraform plan. If that plan contains only the allowlisted legacy AKS normalization, the same coordinator returns a digest-bound reconciliation review instead of treating the drift as apply authority. It attempts verification-only recovery first. Without an existing claim, it requires current exact-plan approval, revalidates the saved plan with the strict historical contract, writes an immutable claim, and applies once through the Managed Identity. Success requires healthy workload readback, refreshed state and typed Deployment evidence, and a complete full-scope zero-change plan. Only that receipt-bound post-state can re-enter adoption. Partial inputs, changed peers, unrecognized effects, state drift, a changed plan, or a tampered claim or receipt stop the update. Adoption itself writes local evidence only and grants no apply authority.
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

Source alone is the complete runtime deployment input. The application stage builds the service
images from the pinned snapshot into the deployment's own registry, reads back their digests, and
validates configuration as [source deployment](source-deployment.md#what-the-command-builds)
defines; it never requires a prebuilt signed runtime artifact manifest. Foundation, private
data-plane execution, exact-plan approvals, immutable claims, bounded commands, independent effect
checks, and recovery remain required. A failed kit verification in `--offline-kit` mode never falls
back to source mode or an installation-time build.

Trial and entitlement selection belong to
[source deployment](source-deployment.md#entitlement-selection) and
[Capability Licensing](../fork-and-sequencing/capability-licensing.md). Trial availability does not
change promotion, risk, RBAC, human approval, or executor identity, and a release signature alone
is never an entitlement.

These are target contracts. The implementation ledger records separately the source entrypoint,
Foundation execution, workload activation, Trial enforcement, and live acceptance. Deployment
readiness remains false until all selected services, identities, migrations, transport, jobs,
Console authentication, cleanup, and second zero-change plans have been independently verified.

### Source image stage

**Initial design:** Build the runtime images on the managed host from the transferred snapshot with
a local container engine, then import them like kit archives.

**Critique:** The source path promises no container engine. A host-side build duplicates the
registry's own build service, and an imported archive digest proves only that bytes moved, not
which registry run produced them.

**Revised design:** `source_image_stage.run_source_image_stage` drives the deployment registry's
build service with only Azure CLI and one verified snapshot of one commit:

- A malformed commit, snapshot digest, subscription, or registry name, or a missing service
  Dockerfile, stops before any call. The registry must exist in the exact subscription in the
  `Succeeded` state. A missing registry, or a subscription where Azure Container Registry Tasks is
  not allowed, stops with `source_image_builder_unavailable` before any effect and never falls back
  to another image source.
- Before the first effect, an immutable claim binds the commit, snapshot digest, subscription,
  registry, service list, and dependency pins. A claim or receipt for different inputs stops with
  `source_image_stage_inputs_changed`.
- The five baseline services build in canonical order with `az acr build`, tagged `sha-<commit>`.
  Each digest comes from the run record's output image for exactly that repository, tag, and
  registry. ClamAV and pgvector are imported with `az acr import` by the digests that the offline
  kit builder also pins.
- Every image is read back by digest and by its commit tag, and any mismatch stops with
  `source_image_build_failed`. Only then does the private receipt bind the seven digests, with
  `operator-selected-source` provenance, `release_signature_verified=false`, and
  `deployment_ready=false`.
- A completed receipt whose own digest verifies permits verification only; an edited receipt stops
  with `source_image_stage_inputs_changed`. An interrupted stage keeps its claim and repeats
  its builds on the next run. That rewrites only the stage's own commit tags, and deployment always
  uses read-back digests.
- The stage writes only its claim and receipt: no kit, signature, SBOM, provenance statement, or
  attestation. Command output never reaches its error text.

The stage needs only Azure CLI and the snapshot, so the application continuation can run it on the
workstation against the clean checkout or on the managed host against the transferred snapshot. It
runs after the platform apply creates the registry and before any service apply. Source deployment
now invokes it inside the shared application sequence and continues with the read-back digests.

## Operator experience

Install the signed offline Python package with standard tools:

```bash
cd package
openssl pkeyutl -verify -pubin \
  -inkey /private/trusted-package-signer.pub \
  -rawin -in SHA256SUMS -sigfile SHA256SUMS.sig
sha256sum -c SHA256SUMS
python -m pip install --no-index --find-links wheels -r requirements.txt
```

The 6.9 MB wheelhouse installs `fdaictl` without a source checkout or network call. Every shipped
file except the signature pair is listed in `SHA256SUMS`, and workspace path dependencies ship as
built wheels. The control-package builder runs only under CPython 3.12 so binary wheels match the
managed-host interpreter that installs the package. Runtime images,
Terraform inputs, and other deployment payloads are selected later by the deployment command and
are not Python package-installation requirements. No appliance image is produced,
not a second package-certification path.

The command derives tenant and subscription only from the active Azure CLI user. It does not
require a GitHub account, Git remote, repository variable, repository secret, workflow dispatch,
or registered GitHub runner.

### Discover commands safely

Running `fdaictl` without arguments displays the same overview as `fdaictl --help` and exits with
code `0`. A command group by itself, such as `fdaictl provision`, displays that group's help.
Help and the top-level `--version` alias do not sign in, inspect Azure, download artifacts, or
create deployment state. The existing `version --output json` contract stays unchanged; its source-entrypoint regression uses a test-owned `UV_PROJECT_ENVIRONMENT` instead of the central validator's no-sync environment, which isolates parallel validation without changing the packaged entrypoint.

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
| `fdaictl provision plan` | Plan the selected Terraform root | No |
| `fdaictl provision entra --target-profile <private-json> --control-profile <private-json>` | Inspect profile-bound tenant controls, or apply the exact app/role-binding plan over five existing groups. One process-wide serialized boundary captures human identity and `aw-approvers` membership in the original CLI context, then target-profile v2 selects a private mode-0700 executor Azure context and validates its exact active tenant/subscription before every control and app/group plan read | Read-only unless `--apply` is supplied, an `aw-approvers` human grants current approval, and a distinct exact managed-identity token matches the active `dev` target |
| `fdaictl provision console-update build` | Build one source-bound Console artifact from protected Git source | No |
| `fdaictl provision console-update plan` | Seal an existing-development target plus candidate and rollback artifacts | No |
| `fdaictl provision console-update apply` | Publish one exact Console plan and verify remote content and access | Yes, after exact terminal approval |
| `fdaictl provision azure --online` | Acquire a signed kit and deploy the headless observation-first profile; repeated `--add-on` and `--observation-source` selections opt into independent surfaces and derive each source's minimum read role | Infrastructure only after exact plan approval; no managed-resource execution authority by default |
| `fdaictl provision azure --offline-kit <path>` | Run the same profile contract without public artifact acquisition | Same exact profile and approvals |
| `fdaictl onboard guided --simulate` | Rehearse the finite stage graph | No |
| `fdaictl onboard status` | Read a local hash-chained rehearsal journal | No |
| `fdaictl bundle verify` | Inspect an optional deployment bundle | No |
| `fdaictl offline prepare` | Prepare a local deployment payload; not required for Python package installation | No |
| `fdaictl offline install-support` | Install optional migration support from local wheels | No |
| `fdaictl license inspect` | Verify a capability token, or an installation entitlement against both exact bindings, without a network call | No |

`fdaictl provision azure --evidence-verifier-input <path>` is an AKS-only, default-off extension
to the `--online`, `--offline-kit`, and connected source application deployment paths. The file is
a private reviewed JSON input. It enables only the independent operational evidence verifier
identity and workload binding, rejects placeholders and secret material, and grants no execution,
promotion, or approval authority.

### Entra display-name ambiguity preflight

**Decision and critique:** Installations that select `read-only-console` or
`enterprise-identity-governance` use one tenant-local shared set of Entra registrations and groups,
resolved only by unique exact display name. Earlier alternatives would have guessed among duplicate
registrations, generated installation-scoped names, or introduced an explicit binding file. Guessing
can break a running Console, installation-scoped names would fork the shared tenant contract, and a
binding file needs a separate owner-review flow. The revised contract therefore performs a read-only
preflight before the first Azure effect: duplicate `fdai-api`, `fdai-console-spa`,
`fdai-approval-bot`, or `aw-*` display names stop the run with a fixed ambiguity reason. The
operator resolves the tenant by renaming or removing the extra registration, then reruns the same
installation. Each installation then adds only its exact Static Web Apps origin to the shared SPA registration and keeps every other redirect. Microsoft Graph neither preserves redirect order nor guarantees read-after-write consistency, so the effect check requires the exact submitted redirect set, in any order, within six reads taken five seconds apart.

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

The source-checkout wrapper selects Python from the verified repository-root `.venv` for an isolated `uv` environment, and the installed CLI passes that interpreter to fixed packaged Genesis launchers,
plan generation, and reverification. The outer Foundation timeout reserves process-group cleanup;
nested Genesis termination grace decreases at each of at most eight levels. Optional caller-owned
stdout and stderr descriptors preserve progress and machine-output separation without changing
stdin or cancellation. Status, approval, and safe environment filtering remain independent gates.

Reusable Console artifacts use the environment-isolated offline build and require installation-time
bindings, never host deployment defaults. CLI build tooling uses a stage-private environment rather
than the caller's selected virtual environment. Complete builds use one private detached checkout
of a pinned commit, excluding caller-local ignored inputs and signing keys. Raw tracked bytes,
modes, and a stable metadata fingerprint are checked throughout assembly and immediately before
signing; unchanged lockfiles or Git status flags alone do not prove source identity. The CLI
wheels include locked workspace path dependencies, such as the service contracts, built as wheels.

The complete release wrapper requires a fresh private output root and preserves earlier archives.
Caller-relative signing-key paths resolve before changing directories, and current-UID, mode-0600,
regular-file checks remain required. Because a wrong key and a wrong path fail the same way, a
separate checker identifies a candidate key before a build consumes it: it reports the packaged
roots' fingerprints, the roles a candidate satisfies, and the unmet custody requirements, and it
emits no key material so it stays safe to run wherever the key might be. Both build refusals name
it. The development profile pins one signer for the complete-kit and bundle roles, so one file
satisfies `--signing-key`; licensing uses the separate upstream integrity key, which the checker
reports as the `integrity` role. The build shares a three-hour
total budget with per-stage and
no-progress deadlines. Nested supervisors forward
cancellation with shorter cleanup grace than their parent. Success requires a valid archive checksum
and completion of every requested artifact stage; interruption cannot continue to later signing.

Source hardening covers packaged entry points, stateful verification-only resume, and nested
cancellation. Focused source tests do not replace signature verification, exact-file and SBOM
checks, or fresh and resumed complete artifact acceptance in the network-isolated air-gap drill.
See [Disconnected Deployment](disconnected-deployment.md) for the complete artifact trust boundary.

The CLI also carries pure validators for [Lifecycle Configuration](lifecycle-configuration.md)
packages. They reject configuration keys without an allowed non-authority axis and an owner, resolve
Release defaults, environment configuration, and the most specific matching override block, and
reject a package that holds a literal secret value instead of a Key Vault reference before signing.
No packager calls them yet, and they grant no deployment or apply authority.

## Standalone deployment sequence

The coordinator performs these stages in order:

1. Read and validate the active Azure human target.
2. Acquire the selected artifact source and verify every executable input.
3. Inspect policy, provider, quota, region, and Foundation state.
4. Create an exact Foundation plan and obtain current terminal approval.
5. Create the private state account, hub network, Bastion, deployment identity, and managed host.
6. Verify state handoff and the managed-host image.
7. Make the same verified artifact closure available on the selected host; transfer it only for a remote host.
8. Run the substrate and application plans under the managed identity.
   Targeted stages also include each `moved` source and destination whose source is in state.
9. Read the Terraform-selected registry and Core application names for substrate readback and
  capability identity without recomputing Azure resource names in Python.
10. Import and read back every runtime image digest.
11. Run database migrations and materialize the authoritative catalogs. A lineage adopted by an
   earlier run advances to head without new adoption evidence.
12. Deploy the services and verify runtime health.
13. Require a second zero-change Terraform plan before reporting deployment readiness.

Independent preparation and read-only probes can run concurrently. Approval, apply, cleanup,
state transition, handoff, migration, and application activation remain serial.

## Approval and recovery

The invocation approves each exact plan it shows; the approval record still binds the plan digest,
actor, and expiry. A deletion or replacement of an existing resource needs one exact typed
confirmation, and closed input grants nothing.

Before an effect, the coordinator writes an immutable claim. If the outcome becomes ambiguous, a
later invocation performs authoritative readback and a zero-change plan. It does not repeat the
apply from the retained claim. Target, kit, Foundation, Entra, or provider-context changes require
a new prepared context.

### Retained kit acquisition

An online retry keeps the work directory and treats its retained kit as untrusted input. It checks
the package-pinned release signature, compatibility, exact file set, all digests, runtime images,
and bundle binding again before advancing. An existing materialized payload is reused only when it
matches those verified files exactly; only the pinned `bin/` tools and Terraform are owner-executable. A new execution copy of the signed bundle avoids reusing
Python bytecode, Terraform scratch files, or other residue from a previous execution copy. The workstation coordinator removes its own execution copies when its process exits, after success or failure; no retained record references them, and the next retry makes a fresh copy. The managed host keeps its execution copy for every step of one run. After an application run converges, the coordinator prunes the transfer directories that earlier kits left on the managed host. A directory whose claims all have receipts is removed. A directory that still holds a claim without a receipt keeps its claims, receipts, reviews, plans, and migration evidence, and only its re-derivable kit, environments, provider data, and credential caches are removed. A pruning failure is reported and never fails the converged run.

The cache records a digest of the requested artifact URL to reject an implicit source switch.
This local record is not signature or remote-origin evidence. A legacy cache without this record
can be considered only for the default versioned source, after complete verification. It does not
prove that the published release is current. An override with an unbound cache is blocked.
Acquisition is serialized per work directory; it does not replace the deployment target lock.

HTTP status, connection failure, local destination conflicts, permissions, and storage exhaustion
have distinct value-safe errors. Corrupt or partial retained content is preserved and blocked,
not silently replaced or accepted. Retry never deletes run state, SSH keys, plans, or approvals,
never changes a signed source file, and never repeats an Azure effect from kit-cache evidence.

#### Offline kit upgrade design and critique

**Initial design:** Require operators to move `kit-work/verified`, `kit-work/kit`, and
`run/standalone-kit.tar.gz` out of the work directory before rerunning with a newer signed kit.
Then treat the newer kit as a fresh installation input.

**Critique:** Manual moves are not a safe installation contract. They can strand the runner SSH
key, run binding, profile, and host-key evidence that identify the existing Foundation, and a new
work directory can cause Terraform to plan a replacement installation beside the old one. Reusing
the retained snapshot silently is also unsafe because a verified older kit must not mask the
operator's newly supplied kit, and tampering in the retained snapshot must remain visible.

**Revised contract:** A same-work-directory offline upgrade verifies the newly supplied kit first.
If the retained kit snapshot and materialized payload verify against their original manifest, the
coordinator moves them to `kit-work/retained-kit-review/` and materializes the new kit in their
place. If the retained snapshot is unsafe, incomplete, or tampered, the run stops and preserves it
for review. The managed-host transfer archive follows the same rule: a valid previous
`run/standalone-kit.tar.gz` and sidecar move to `run/standalone-kit-review/` before the new archive
is written, while an invalid archive remains blocked.

Foundation continuity stays separate from application source selection. Existing offline
Foundation variables keep their creating `source_commit`, runner SSH key, run binding, profile,
and host keys. The current kit source becomes the application source and is recorded beside the
Foundation lineage in `run/foundation-source-lineage.json`. The Foundation orchestration then runs
under that retained lineage: its status, approvals, plan reviews, and receipts stay bound to the
creating revision. The signed source evidence carries both the kit's `source_commit` and the
retained `foundation_source_commit`, so source verification accepts exactly those two revisions.
The continuation re-verifies completed Foundation checkpoints under the revision that created them,
including the retained runner-image receipt, and already satisfied effects are recovered through
their retained claims and independent readback instead of being repeated. The
coordinator then rebuilds a no-effect Foundation adoption receipt from that retained, verified
chain and binds it to the newer kit, so the managed host accepts the kit only through that
evidence. It does not approve a plan computed from the newer kit while that plan carries the
retained revision as provenance.

**Transition design:** The coordinator first compares precise Foundation inputs before it decides
whether a transition exists. The trigger set is the Terraform root content used by Foundation, the
provider lock, the bootstrap support files, the runner-image toolchain, the Terraform binary, and
the retained runner-image observation digest. The whole deployment-bundle digest and the whole
offline-kit manifest digest are excluded because those values change for every kit and don't prove
Foundation configuration drift. When those inputs are unchanged, the continuation remains the
verified #1811 path: no transition receipt is written and no new plan is computed.

**Transition critique:** A retained `foundation-plan-attempt-*` review can be a legacy review that
has no action `summary` and can be expired long before an upgrade. Such a review is enough to
identify the retained input context for the pure continuation path, but it is not enough to approve
or summarize a new transition. Similarly, setting `zero_change_verified: true` without running a
plan from the newer kit would make the receipt look verified while proving nothing about the new
Foundation configuration.

**Transition revision:** When any trigger input differs, the coordinator computes the newer kit's
Foundation plan against the authoritative remote Foundation state after state handoff. It reuses
the Bastion-bound state-handoff machinery, the retained SSH key, run binding, profile, and host
keys, but records the transition under the newer revision's provenance. A zero-change plan advances
the lineage with a no-effect transition receipt. A non-destructive plan is approved by the
invocation, claimed before effect, applied once, independently read back, and followed by a second
zero-change plan. A delete, replacement, or runner-image/toolchain change that implies runner
replacement keeps the existing exact typed confirmation requirement; without an interactive TTY it
is refused. Interrupted transitions after a claim resume by verification only. Only after
verification does the coordinator bind the retained apply, enrollment, state-handoff, authority,
and transition receipts to the application lineage and advance `run/foundation-source-lineage.json`.
Application plans keep the existing rule: the invocation approves the non-destructive exact plan it
shows, and deleting or replacing an existing resource still needs the explicit extra confirmation.

**Transport revision:** The transition helper is shipped per run and digest-bound in the transition
evidence. It is not part of the runner image, so adding the helper does not imply a runner-image
replacement for existing installations. The local coordinator packages the newer kit's Foundation
root, provider mirror, modules, bootstrap support, runner-image support files, and retained
variables into a private archive. The retained variables are the Foundation input whose normalized
digest the retained plan reviewed, such as the runner-image materialization; when no candidate
matches, the transition stops with `foundation_transition_variables_unverifiable`. The archive
activates the AzureRM backend from the Foundation root's verified backend example, the same
contract the state handoff uses, and refuses a root that still carries a local state. The
coordinator then copies that archive and the helper under the Bastion transfer prefix over the
installation's Bastion tunnel, and runs the helper under the retained runner Managed Identity
against the existing AzureRM backend recorded by the state authority. The helper refuses an empty
or unmanaged remote state, because planning without the migrated state would propose recreating the
whole Foundation. Before each plan, it binds the policy-assigned values that the exact input cannot
predict, the `FirstPartyUsage` public IP tags and the runner guest patch selection, from a read-only
refresh. It applies the same supported-value rules as the Foundation apply, so drift that a tenant
policy introduced after the apply does not turn into a replacement. The helper can plan, apply one
already reviewed plan, verify by readback plus a zero-change plan, and clean up its transient work.
It cannot approve, choose a target, repeat an ambiguous apply, change the runner image, or advance
lineage; those remain local coordinator decisions after bounded evidence returns.

Each transition attempt owns a distinct remote work directory. The helper publishes its bounded
evidence below the Bastion evidence boundary, removes the transferred archive after a verified
extraction, and, before a new plan, prunes the work, transfers, and evidence of superseded attempts.
The coordinator resumes only the newest claimed or completed attempt, and only when that attempt's
review records the current Foundation inputs. A completed attempt for other inputs is superseded by
a new plan; an interrupted apply for other inputs stops with
`foundation_transition_interrupted_for_other_inputs`. A failed remote step reports a bounded reason
without identifiers.

A control-only repair can reuse a verified kit through a [signed deployment-control package](disconnected-deployment.md#deployment-control-package).

## Capability token behavior

No signing key is an installation prerequisite. The command selects the entitlement mode on the
workstation before any Azure effect, as [source deployment](source-deployment.md#entitlement-selection)
defines: no integrity signing key means the durable Trial, and a usable
`secrets/integrity-signing-key.pem` means a full installation entitlement. That fixed path in the
working checkout is the only issuer key the CLI reads; no option, environment variable, or home
directory path selects another one. A pre-issued token file
remains an advanced `--trial-token` input. Until the Trial is initialized by deployment, an
installation without a token starts observation-only without creating a license secret. Omitting a
token on a resumed installation does not revoke one previously installed. Without action
authority, the Core can observe and report but cannot execute managed-resource actions.

A token never grants deployment or runtime authority by itself. Promotion state, risk policy,
human approval, executor identity, and effect verification remain separate controls.

## Deployment appliance

Removed. Constitution Article 1 defines exactly three installation paths: the one-command source
deployment, a signed offline package, and the [Hub-managed lifecycle](hub-managed-lifecycle.md),
which is designed but not implemented. It also states that installation tooling adds no other
gate. An appliance image was another packaging of the same kit rather than one of those paths, so
its builder and runner are gone and no release step produces one.

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

Managed-host checkpoint failures return one bounded structured failure record to the workstation.
The record carries a fixed reason code, a redacted provider excerpt, and any Azure provider error
codes such as `OverconstrainedZonalAllocationRequest`, `AllocationFailed`, or
`ParameterOutOfRange`. The excerpt is length-limited and redacts resource IDs, GUIDs, hostnames,
tokens, and secret-like assignments before the local coordinator renders it.

## Related docs

| To learn about | Read |
|----------------|------|
| Implementation status and remaining evidence | [Implementation ledger](../../roadmap-implementation/deployment/installable-deployment-cli.md) |
| One-command source deployment and entitlement | [One-Command Source Deployment](source-deployment.md) |
| Execution-host and connectivity choices | [Provisioning Execution Profiles](provisioning-execution-profiles.md) |
| Disconnected trust and artifact delivery | [Disconnected Deployment](disconnected-deployment.md) |
| Azure resource inventory and bootstrap | [Deploy and Onboard](deploy-and-onboard.md) |
| Identity and approval separation | [Security and Identity](../architecture/security-and-identity.md) |
