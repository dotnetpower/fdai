---
title: Subscription Genesis Assurance
---
# Subscription Genesis Assurance

This document defines the safety, completeness, recovery, and operator-experience controls that
make a subscription genesis run trustworthy. It complements the lifecycle in
[Subscription Genesis Provisioning](subscription-genesis-provisioning.md) and turns its broad
stages into falsifiable gates.

> **Scope:** These controls apply to empty and partially configured Azure subscriptions. They do
> not authorize a live deployment, model call, quota request, or resource mutation.
>
> **Implementation ledger:** Delivery evidence is tracked in the
> [Subscription Genesis Assurance implementation ledger](../../roadmap-implementation/deployment/subscription-genesis-assurance.md).

## Design at a glance

Every run compiles a finite manifest, acquires one subscription-and-environment lock, executes only
sealed stage plans, and records independent postcondition evidence. A run that cannot prove one
required entry ends as `blocked`, `failed`, `cancelled`, or `incomplete`, never `ready`.

## Foundation and external control planes

The first Azure execution host does not exist in an empty subscription. Foundation bootstrap
therefore uses a narrowly bounded local control-plane exception:

- **Local boundary:** The signed-in operator can create resource groups, the private state account,
  network, deployment identity, and execution host. The phase cannot write Key Vault, PostgreSQL,
  model, or application data planes.
- **State cache:** Local state uses `umask 077`, a mode-`0700` directory, a mode-`0600` regular file,
  no symlinks, no secret inputs, and a bounded lifetime. The run records its digest but never
  uploads the file as evidence.
- **Stable names:** A run derives globally unique names once, stores only their digests in portable
  status, and reuses the same names on resume. It never generates a new state account after a
  partial foundation attempt.
- **Remote authority:** The runner uses Terraform state migration, not inferred reconstruction, and
  compares lineage, serial, address set, resource ids, and managed count. A zero-change remote plan
  and state-versioning readback are required before deleting the local cache.
- **Data protection:** Blob versioning, soft delete, TLS, key-auth disablement, public-access
  disablement, private endpoint, private DNS, and the state lease path are required postconditions.
  Best-effort enablement cannot close the foundation stage.

External control planes are first-class dependencies:

| Dependency | Required assurance |
|------------|--------------------|
| Azure | Exact cloud, tenant, subscription, provider registrations, policy assignments, locks, quotas, terms, and effective RBAC are captured at plan time and rechecked before each mutation. |
| Source host | Repository, immutable commit, signed bundle, dependency lock, and image attestations match the run manifest. |
| Workflow host | Repository authorization, protected environments, approvers, runner labels, concurrency group, and retention policy are verified without granting FDAI runtime authority. |
| Identity directory | App registrations, App Roles, groups, redirect origins, owners, admin consent, and tenant match are planned and read back. |
| Artifact sources | Online allowlists or the verified offline kit cover every wheel, binary, provider, image, signature, and software bill of materials entry. |

Runner enrollment never places a registration token, remove token, database password, or GitHub
token in Terraform variables, state, process arguments, Azure Run Command payloads, logs, or chat.
The target implementation uses provider-hosted authorization and a protected input channel. If the
selected transport cannot meet that condition, the run pauses for an approved existing host rather
than weakening secret handling.

Repository settings are compiled from the manifest and applied idempotently. The operation reports
the names of missing variables and secret references but never their values. Database credentials
are generated on the private execution host, stored in the approved secret provider, and consumed
by reference; rerunning onboarding does not rotate them implicitly.

## Planning, authority, and concurrency

- **Finite dependency graph:** Every manifest entry declares prerequisites, owner, executor,
  approval class, idempotency key, timeout, no-progress timeout, rollback, postcondition observer,
  and evidence schema version. Cycles and unknown dependencies block planning.
- **Single active run:** A lease keyed by cloud, tenant, subscription, environment, and Terraform
  root prevents concurrent genesis or teardown. Lease loss stops new work and requires operator
  review before resume.
- **Time authority:** Plan expiry, approvals, leases, and evidence age use an authenticated UTC
  source with a declared skew bound. Clock uncertainty blocks mutation.
- **Approval policy:** Each mutating checkpoint requires at least one current accountable human.
  High-impact foundation, identity, network, production, or teardown plans use the configured
  quorum. Approvers and execution identities remain distinct.
- **Dry run and rollback:** A successful plan and rollback rehearsal are required before apply.
  Destructive migration or adoption needs a verified backup/restore point and a separately approved
  rollback plan.
- **Cancellation:** Cancellation stops scheduling new entries, lets an in-flight provider call
  reach its bounded terminal receipt, releases leases, runs only preapproved cleanup, and ends
  `cancelled` or `incomplete`.
- **Apply ambiguity:** An absent claim can replan. A claim without a receipt can resume verification
  only. A failed or ambiguous claim cannot retry automatically.

Existing resources are adopted only from an explicit address allowlist and exact immutable
property match. Management locks, deny assignments, policy remediations, or foreign ownership make
the entry a conflict. The run never removes a lock or policy assignment unless that exact mutation
is independently designed and approved.

Before approval, the plan reports the projected monthly cost, one-time model validation budget,
quota consumption, public IP count, egress profile, backup retention, and resources that do not
scale to zero. A profile cost ceiling blocks plans above the approved amount.

## Network and execution-host assurance

Planning checks address overlap across the ops VNet, application VNet, VPN, peered VNets, hub
routes, Private DNS Resolver ranges, and selected private endpoint subnets. It validates both
runner-to-service paths and operator-through-VPN paths without treating VPN access as deployment
authority.

The selected execution profile must prove:

- DNS, TCP, TLS, identity, management-plane, GitHub or manual transport, artifact, state, Key Vault,
  PostgreSQL, Event Hubs, registry, model, and monitoring paths from the actual host;
- effective routes, firewalls, network security groups, service tags, proxy trust, and private DNS
  answers for the target Azure cloud;
- checksum-pinned tools and images, with no unverified `latest` download during a protected run;
- bounded egress or a complete signed offline kit; and
- a healthy runner heartbeat after reboot or deallocation behavior appropriate to its disk model.

Sovereign clouds use their own endpoint suffixes, audiences, service tags, and supported services.
Unsupported parity is a plan blocker, not a public-cloud fallback.

## Database and semantic assurance

The database bootstrap manifest separates infrastructure, schema, data, and runtime authority:

| Gate | Required evidence |
|------|-------------------|
| Server | Version, region, zone posture, storage, backup, retention, encryption, private DNS, TLS, parameters, locale, and time zone match the profile. |
| Recovery | A fresh backup or restore point exists before destructive work; restore is rehearsed for the selected production class and bound to an RPO/RTO. |
| Migration | Legacy and service-owned heads, dependency order, transaction behavior, locks, statement deadlines, adoption records, and rollback references are exact. |
| Roles | Migration, owner, runtime, read, Job, and executor principals have only declared grants; runtime identities cannot run DDL or assume migration authority. |
| Extensions | Every required extension and version is present before dependent schema or catalog work starts. |
| Semantic release | The signed bundle enumerates the deployable ontology, rule, workflow, ResourceType, prompt, and product-default set with exact versions and digests. |
| Projection | Immutable read projections match the release digest and preserve deployment-owned settings through compare-and-set rules. |

"Every repository catalog entry" does not mean every collected reference is enabled. The manifest
classifies entries as `runtime-required`, `reference-only`, `optional-disabled`, or
`deployment-overlay`. Only reviewed runtime-required entries become active defaults, and all action
modes remain shadow-only.

Service activation waits for one atomic readiness marker binding every migration head, semantic
release digest, default-set digest, role manifest, and timestamp. Runtime-principal readback must
match that marker. A migration principal cannot certify its own runtime access.

## Model assurance

Model planning accounts for capability reuse and aggregate quota. Multiple capabilities can share a
deployment only when the registry explicitly permits the same publisher, family, version, SKU,
content-filter policy, data zone, and workload isolation class. Otherwise they receive separate
capacity.

The capacity plan includes input and output tokens, cached-token treatment, requests per minute,
concurrency, provider SKU units, per-model quota, regional quota, current deployments, reserve,
retry behavior, and expected burst. Quota is reserved with a compare-before-apply check immediately
before creation; drift forces replan.

The plan also verifies:

- account ownership and private endpoint/DNS closure;
- publisher terms, subscription eligibility, content filtering, responsible-AI policy, data
  residency, and preview restrictions;
- deployer, runtime, and Operator roles without local keys;
- exact endpoint-to-deployment bindings and no borrowed account;
- quantitative success, throttling, throughput, latency, and cost thresholds; and
- an explicit live-model approval because probes incur cost and send test content.

A quota increase is an external human-reviewed prerequisite. `fdaictl` can produce the required
capacity evidence and status, but it does not assume approval, poll forever, or create a smaller
deployment silently. Partial model creation is cleaned up only by a sealed cleanup plan.

## Inventory completeness and progress assurance

Genesis scans one exact subscription root. It accounts for top-level resources, mapped types,
unmapped provider types, extension resources, and separately bounded child-resource sources such as
ARM and Kubernetes. A source limit does not turn into successful truncation: the run emits a
stable blocker with the observed limit and required next action.

The count phase and collection phase are not transactionally consistent because Azure resources can
change. Progress therefore presents the denominator as an estimate and completeness from the final
provider coverage receipt. Deletes or creates during collection either reconcile in the same
complete generation or leave a newer-change overlay that blocks genesis closure.

Large subscriptions spill staged batches to PostgreSQL and never require the optional in-memory
observer to retain the complete graph. Object, relationship, byte, page, request, concurrency,
attempt, and no-progress limits come from the signed collection policy. If the full subscription
cannot fit those approved bounds, planning requires a reviewed partition strategy before scanning.

The inventory identity receives only read roles on the declared subscription and write access to
its private staging and event surfaces. RBAC propagation is explicitly observed before collection.
Private AKS or another child source is included only after endpoint, certificate, audience,
workload identity, and provider authorization checks pass; otherwise its declared scope remains
incomplete.

Progress separates completion from time:

- exact stage and checkpoint counts report completed work;
- resource and page denominators remain labeled estimates;
- fixed weights provide only completion fraction, never elapsed-time prediction;
- estimated completion time appears only with a minimum sample window and stable rate, and
  disappears on retry, throttling, approval wait, or denominator change;
- every event has schema version, run id, attempt id, monotonic sequence, previous-event digest,
  current counters, sanitized reason, and resume cursor reference; and
- the CLI, workflow summary, Operator API, and Console localize labels, support screen readers, and
  bound retained events and rendered text.

The postcondition observer is distinct from the inventory writer identity. It reads the active
generation, coverage manifest, freshness, and graph counts after promotion. Only that readback can
close the initial scan.

## Operational closure and test matrix

Readiness additionally requires event-bus round-trip, DLQ reachability, canary audit no-op, runtime
health, guarded-processing readiness, model binding, database read, catalog digest, inventory
freshness, monitoring, budget alert, and operator notification checks.

The run publishes bounded notifications on approval wait, no-progress warning, failure,
cancellation, cleanup failure, and readiness. Notifications contain run and stage references only.
Logs and evidence have byte, item, and retention limits and exclude secrets, target identifiers,
provider payloads, prompts, and model output.

The end-to-end matrix includes:

- empty, manually bootstrapped, older FDAI, and foreign-resource subscriptions;
- public Azure, private Azure with VPN, existing host, managed VM, and signed offline kit;
- developer and production profiles, including quorum and backup requirements;
- policy deny, management lock, address overlap, DNS failure, route failure, RBAC delay, quota race,
  provider throttling, model-term failure, migration failure, catalog mismatch, inventory
  truncation, process crash, lease loss, cancellation, cleanup failure, and clock skew;
- interruption before and after every external effect, claim write, receipt write, and state
  migration boundary; and
- second-run no-change, upgrade from a supported older manifest, rollback, restore, teardown, and
  environment cleanup.

Live validation uses a dedicated approved subscription, exact pushed revision, green required CI,
cost ceiling, expiry, and teardown plan. It never reuses a customer environment as a test fixture.

## Pre-login hardening evidence

| Round | Finding and resolution | Focused evidence |
|-------|------------------------|------------------|
| H01 | Terraform failure output could disclose state-derived values. The CLI now maps it to bounded stable reason codes. | `test_terraform_failure_is_redacted_to_stable_reason` |
| H02 | Journal reads checked a path before reopening it and could follow a replacement link. Reads now use one no-follow descriptor and validate that descriptor. | `test_journal_reader_never_follows_symlink` |
| H03 | Profile reads had the same check-then-open race. They now read through one no-follow descriptor with mode and size validation. | `test_profile_reader_never_follows_symlink` |
| H04 | Resume input could claim both a terminal receipt and failure. The reducer now rejects that contradictory state instead of selecting a recovery action. | `test_resume_rejects_failed_state_after_terminal_receipt` |
| H05 | A journal did not bind its manifest, so a changed source revision could resume old progress. Every event now binds one immutable context digest. | `test_simulation_refuses_resume_under_changed_manifest` |
| H06 | Stage idempotency keys bound the profile but not the source revision. They now include both, preventing cross-revision effect reuse. | `test_idempotency_keys_change_with_source_revision` |
| H07 | Model capacity accepted booleans and non-finite ratios, which could bypass validation or fail during arithmetic. Boundary validation now rejects them. | `test_capacity_rejects_non_numeric_and_non_finite_inputs` |
| H08 | License parsing accepted permissive base64 forms and duplicate capabilities. It now requires canonical base64url and a unique sorted capability set. | `test_license_rejects_noncanonical_base64_and_duplicate_capabilities` |
| H09 | Offline kit hashing trusted path metadata collected before opening the file. It now verifies descriptor identity and detects mutation during hashing. | `test_offline_hash_rejects_replaced_file_identity` |
| H10 | Bundle hashing had the same replacement race and no aggregate size bounds. It now checks descriptor identity during hashing and enforces file, count, and total ceilings. | `test_bundle_hash_rejects_replaced_file_identity` |
| H11 | Local inspection treated installed tools as readiness even when Azure had no active account. It now performs a read-only, identifier-free authentication check and fails closed. | `test_azure_authentication_fails_closed_without_login` |
| H12 | The offline kit staged only the `fdaictl` wheel and omitted its transitive runtime wheels. Release staging now exports hashed production dependencies and downloads binary wheels into the signed kit. | `test_release_scripts_use_the_installable_distribution` |
| H13 | Bundle verification authenticated content but ignored its declared CLI compatibility window. It now blocks versions outside the signed minimum and maximum. | `test_bundle_rejects_incompatible_cli_version` |
| H14 | Profiles did not bind the intended tenant and subscription, allowing reuse against another active login. They now require a deployment-local target digest. | `test_profile_init_requires_digest_bound_target` |
| H15 | Rehearsal marked completed stages as `verifying`, making interruption status dishonest. The journal now has an explicit `completed` state and resumes only those stages. | `test_simulation_interrupts_and_resumes_without_duplicate_stage` |
| H16 | The journal accepted `ready` as a first event and allowed work after terminal failure. Transition checks now require completed readiness evidence and close terminal runs. | `test_journal_rejects_ready_without_readiness_evidence` |
| H17 | Offline planning reopened and reparsed the manifest after verification, allowing a replacement race. It now consumes only paths returned by the verified result. | `test_offline_kit_verifies_signature_exact_files_and_compatibility` |
| H18 | The compiled manifest sealed broad stages but not the concrete minimum platform and service inventory. It now enumerates provider registration, foundation, data, model, five-service, Job, Console, and monitoring entries. | `test_compiler_emits_finite_ordered_manifest` |
| H19 | A ready rehearsal returned before validating the requested run and manifest. Ready journals now pass the same context checks as interrupted journals. | `test_ready_simulation_still_validates_run_and_manifest` |
| H20 | Bundle verification could block while opening a FIFO before type validation. It now rejects every non-regular payload before opening it. | `test_bundle_hash_rejects_fifo_before_open` |
| H21 | Profile inspection recorded a target digest but did not compare it with the active Azure context. It now derives the active binding without disclosure and requires an exact match. | `test_active_target_binding_is_stable_and_identifier_free` |
| H22 | Offline planning let callers choose the CLI version and platform used for compatibility checks. It now binds the installed version and runtime-derived platform. | `test_runtime_platform_is_not_caller_controlled` |
| H23 | Bundle verification trusted an arbitrary `sbom_path` and did not prove component coverage. It now requires a declared CycloneDX 1.5 SBOM whose SHA-256 entries exactly cover the payload. | `test_bundle_rejects_incomplete_sbom` |
| H24 | Offline planning accepted an arbitrary infrastructure directory unrelated to the signed kit. It now safely extracts and verifies the kit-declared deployment bundle and plans only its `infra` root. | `test_bundle_archive_rejects_path_traversal` |
| H25 | Verified Terraform, provider, and bundle paths could be replaced before execution. Planning now copies them to a private tree while rechecking signed digests, then executes only that snapshot. | `test_materialization_rejects_artifact_replaced_after_verification` |
| H26 | Release staging could label host binaries and wheels as another target platform. It now rejects cross-platform staging until target-specific artifact resolution exists. | `test_release_scripts_use_the_installable_distribution` |
| H27 | Idempotency keys used only a 12-character revision prefix, allowing rare cross-revision collisions. They now bind the complete source commit. | `test_idempotency_keys_change_with_source_revision` |
| H28 | Planning followed an existing work-directory link and could truncate a linked CLI configuration. It now requires a new private directory and creates configuration with no-follow exclusivity. | `test_plan_work_directory_and_config_reject_existing_links` |
| H29 | A kit could declare one bundle version while carrying another valid signed bundle. Planning now requires both signed version claims to match. | `test_plan_rejects_bundle_version_mismatch` |
| H30 | ARM64 hosts inherited x86 staging defaults and failed despite being supported. Staging and the drill now derive defaults from the host while still rejecting explicit cross-platform requests. | `test_release_scripts_use_the_installable_distribution` |
| H31 | Local inspection could report `ready` without execution-host, transport, workload-identity, or offline-kit evidence. It now returns `review` until that external evidence is verified. | `test_local_inspection_cannot_claim_execution_host_readiness` |
| H32 | License inspection could report signed but runtime-invalid identifiers or unverified image and tenant bindings as active. It now enforces canonical identity and caller-bound digest checks. | `test_license_rejects_invalid_identifiers_and_unverified_bindings` |
| H33 | The air-gap drill executed checkout source instead of the wheel it shipped. It now installs only from signed kit wheels with `--no-index` inside the isolated network namespace and runs that `fdaictl`. | `test_release_scripts_use_the_installable_distribution` |
| H34 | Dependency download used the `uvx` interpreter ABI instead of the CLI build interpreter. It now pins wheel resolution to the exact Python used to build and verify the kit. | `test_release_scripts_use_the_installable_distribution` |
| H35 | Journal replay verified hashes but skipped legal transition checks, allowing a crafted first `ready`. Replay now applies the same transition reducer as append. | `test_journal_replay_rejects_ready_without_readiness_evidence` |
| H36 | A blocked run was nonterminal and could continue without a new reviewed run. `blocked` now closes the journal like other fail-closed terminal states. | `test_journal_rejects_event_after_blocked_state` |
| H37 | Boolean utilization and reserve ratios still passed finite-number checks. Capacity validation now rejects booleans for both ratio fields explicitly. | `test_capacity_rejects_non_numeric_and_non_finite_inputs` |
| H38 | The root productization pytest process could not import the independent CLI project. Productization now runs CLI tests in that project's environment before the root suite. | `test_productization_builds_the_installable_deployment_cli` |
| H39 | A two-event journal could mark only `system-readiness` complete and then become ready. Ready now requires every compiled manifest entry completed in exact order. | `test_journal_rejects_ready_with_only_readiness_stage` |
| H40 | Terraform inherited ambient control variables such as `TF_CLI_ARGS_plan=-destroy`. Planning now rejects Terraform controls and constructs a minimal allowlisted environment with a private data directory. | `test_terraform_environment_rejects_ambient_plan_controls` |
| H41 | Relative work paths were reinterpreted beneath Terraform's later working directory. Planning now converts them to absolute paths without resolving a hostile link. | `test_relative_plan_work_directory_becomes_absolute` |
| H42 | Offline-kit verification accepted an arbitrary signed SBOM payload. It now requires CycloneDX 1.5 with unique SHA-256 components that exactly cover every other kit file. | `test_offline_kit_rejects_incomplete_sbom` |
| H43 | Inspection required GitHub CLI even for manual transport profiles. Tool prerequisites now follow the selected transport. | `test_manual_profile_does_not_require_github_cli` |
| H44 | Non-force profile initialization used a replacing rename after its existence check, so concurrent creation could be overwritten. Publication now uses atomic no-replace linking. | `test_profile_publish_never_replaces_concurrent_destination` |
| H45 | The air-gap drill installed and executed the kit before authenticating it. A trusted external verifier now checks the signed manifest and wheel digests before installation. | `test_release_scripts_use_the_installable_distribution` |
| H46 | Kit compatibility recorded architecture but not Python ABI or libc. The signed manifest now binds the runtime implementation, minor version, and libc identity. | `test_offline_kit_verifies_signature_exact_files_and_compatibility` |
| H47 | Malformed bundle archives escaped the CLI's stable error boundary as `TarError`. Extraction now maps archive parser failures to a bounded bundle verification error. | `test_bundle_archive_maps_malformed_input_to_stable_error` |
| H48 | A truncated gzip raised `EOFError` outside the normalized archive error path. It now produces the same bounded verification failure. | `test_bundle_archive_maps_truncated_gzip_to_stable_error` |
| H49 | The drill installed wheels from mutable kit storage after verification. The external verifier now materializes every wheel into a private digest-checked snapshot used by `pip`. | `test_materialization_snapshots_every_python_wheel` |
| H50 | The drill extracted the bundle before authenticating the kit, exposing unbounded archive parsing. It now materializes, safely extracts, and verifies the signed bundle only after external kit verification. | `test_release_scripts_use_the_installable_distribution` |
| H51 | Manual drill steps still executed Terraform and providers from mutable kit paths. Every Terraform path now points to the authenticated private snapshot. | `test_release_scripts_use_the_installable_distribution` |
| H52 | Release staging resolved open-ended build and download tooling from the network. Hatchling and pip are now exact pins, and build, export, and download require the committed CLI lock. | `test_release_tooling_is_exactly_pinned` |
| H53 | `provision plan` had no path for Terraform's five required inputs. It now snapshots a private JSON input, rejects real or extra secrets, injects an explicit plan-only password, and removes the snapshot after planning. | `test_plan_input_is_private_canonical_and_non_secret` |
| H54 | Key-name secret detection missed sensitive webhook variables. Plan input now accepts exactly five Terraform values plus one target digest and no optional values. | `test_plan_input_rejects_real_password_and_extra_secret` |
| H55 | Offline plans were not bound to the inspected tenant and subscription intent. Planning now requires the reviewed profile, matches its target digest to plan input, and rechecks an active Azure account when available. | `test_plan_input_must_match_profile_target_binding` |
| H56 | Optional model demand was included in blocking required TPM, causing valid required capacity to fail. Required and optional demand now have separate sufficiency outcomes. | `test_optional_shortfall_does_not_block_required_capacity` |
| H57 | A caller-supplied target digest did not constrain effective tenant, subscription, or region input. Planning now recomputes the digest, matches the profile region, and injects the verified subscription into Terraform. | `test_plan_input_region_must_match_profile` |
| H58 | Optional capability reserve ratios still reduced quota used for required sufficiency. Required and combined reserve are now calculated independently. | `test_optional_reserve_does_not_block_required_capacity` |
| H59 | The synthetic air-gap profile inherited a signed-in host's Azure CLI context and failed target binding. The drill now uses a private empty Azure configuration directory. | `test_release_scripts_use_the_installable_distribution` |

## Related docs

| To learn about | Read |
|----------------|------|
| Zero-to-ready stage order | [Subscription Genesis Provisioning](subscription-genesis-provisioning.md) |
| Host and transport profiles | [Provisioning Execution Profiles](provisioning-execution-profiles.md) |
| Required network paths | [Network Connectivity Matrix](network-connectivity-matrix.md) |
| Recovery requirements | [Control-Plane Disaster Recovery](control-plane-disaster-recovery.md) |
| Security authority | [Security and Identity](../architecture/security-and-identity.md) |
