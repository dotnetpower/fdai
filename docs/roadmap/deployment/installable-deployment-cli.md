---
title: Installable Deployment CLI
---
# Installable Deployment CLI

This document defines the target installation and deployment experience for FDAI. Operators
install an isolated Python command-line tool, run a read-only deployment preflight, and submit
an approved Terraform plan to the deployment runner without moving secrets through the local
machine.

> **Execution boundary:** Terraform remains the infrastructure execution engine and source of
> truth. The planned `fdaictl` distribution is a thin orchestration layer over validation, plan
> analysis, workflow submission, and post-deployment checks.
>
> **Implementation focus:** Azure is the only implemented deployment target. Non-Azure provider
> support is deferred.
## Design at a glance

Install `fdaictl` as an isolated `uv` tool. It verifies a version-matched bundle and the target
environment before an approved execution host applies the exact Terraform plan.

| Concern | Decision |
|---------|----------|
| Operator command | `fdaictl` |
| Preferred installation | `uv tool install fdai-deployment-cli` |
| One-time and CI execution | `uvx --from fdai-deployment-cli fdaictl ...` |
| Infrastructure engine | Terraform under `infra/` |
| Default action | Read-only preflight or plan |
| Apply location | VNet-integrated self-hosted runner |
| Package contents | Python CLI in a wheel plus a signed deployment bundle |
| Machine output | Stable JSON schema and documented exit codes |
| Product language | English source catalog with locale fallback |
| Command boundary | `fdaictl` remains separate from the control-plane process and read-only operator console |

## Target operator experience

The planned persistent installation is:

```bash
uv tool install fdai-deployment-cli==<version>
fdaictl version
fdaictl doctor
```

From a source checkout, use `uv run --project packages/deployment-cli fdaictl`. Published wheels
use the pinned installation above.

For a one-time run or a CI job, use an ephemeral environment:

```bash
uvx --from fdai-deployment-cli==<version> fdaictl deploy preflight --environment dev
```

Use `pipx` when `uv` is unavailable, or install with `pip` inside a virtual environment. The
installer never changes system tools; `fdaictl doctor` reports missing or incompatible tools.

> The source tree registers the local `fdaictl` entrypoint. Protected Azure dispatch, publication,
> and governed runtime evidence remain tracked in the
> [implementation ledger](../../roadmap-implementation/deployment/installable-deployment-cli.md).

## Command model

Commands are grouped around diagnosis, onboarding, deployment, and status. Every command that can
lead to a mutation makes the remote execution boundary visible.

| Command | Purpose | Azure mutation |
|---------|---------|----------------|
| `fdaictl version` | Show CLI, bundle, schema, and compatibility versions | No |
| `fdaictl doctor` | Check Python, Azure CLI, Terraform, GitHub CLI, authentication, and local config | No |
| `fdaictl provision inspect` | Inspect online/offline, signed-kit trust, existing/managed host, transport, access, and workload-identity readiness | No |
| `fdaictl provision bootstrap-reconcile` | Read the exact Azure target, provider registrations, foundation resource groups, and private state-account posture into an expiring mode-`0600` plan with separate intent and observation digests | No |
| `fdaictl provision plan` | Bind a reviewed profile to private non-secret plan input, verify the kit and bundle, then plan its `infra` root | No |
| `fdaictl provision init` | Create a schema-validated, untracked environment configuration | No |
| `fdaictl onboard guided` / `status` / `resume-verification` | Orchestrate one durable subscription-genesis run over the low-level exact-plan commands | Only after an explicit protected approval |
| `fdaictl security audit` | Check runtime flag combinations, local config hygiene, and requested sandbox availability | No, unless `--fix-permissions` is explicit |
| `fdaictl bundle verify` | Verify bundle signature, compatibility, file set, digests, SBOM, and size | No |
| `fdaictl backup create` | Create a private portable archive from validated configuration, references, audit metadata, and user context | No |
| `fdaictl backup restore` | Verify and atomically restore a portable archive into a new local directory | No |
| `fdaictl deploy preflight` | Collect static and live read-only deployment blockers | No |
| `fdaictl deploy plan` | Submit a plan-only workflow to the approved runner | No |
| `fdaictl deploy apply --plan-id <id>` | Submit the exact approved plan for remote apply; requires `--plan-expires-at` from `deploy status` plan metadata | Yes, on the runner |
| `fdaictl deploy status` | Read sanitized plan digest, expiry, status, and workflow URL | No |
| `fdaictl deploy teardown` | Submit the guarded environment teardown workflow | Yes, on the runner |
| `fdaictl release upgrade` / `rollback` | Verify and atomically switch the signed-bundle active pointer | No |
| `fdaictl extension validate` | Check extension manifest/archive compatibility and security offline | No |
| `fdaictl trajectory validate` | Check governed dataset checksums, schema, order, and source mapping | No |
| `fdaictl license inspect` | Verify a capability license token against the packaged public key and report entitlement status | No |

For the exclusive RCA reader identity target, `deploy apply` and verification resume submit through
the allowlisted protected-operation workflow. The repository automation identity then requests the
exact downstream apply so a solo maintainer can review it without self-approval. The downstream job
still binds the selected GitHub Environment and revalidates its no-bypass reviewer policy before
mutation.

Disconnected installation authenticates the signed kit with a trusted verifier outside that kit,
copies its wheels into a private digest-checked snapshot, and installs only from that snapshot. The
same verifier safely extracts and verifies the signed bundle before Terraform reads it. The installed
`fdaictl` then repeats verification, and every Terraform binary and provider path uses the private
snapshot rather than the original kit. Artifact metadata and content descriptors open in
nonblocking, no-follow mode and verify file identity after opening, so a check/open replacement
cannot stall verification.
Connected staging also requires the committed deployment CLI lock and exact Hatchling and pip
versions before it can sign an offline kit. Terraform and OPA are downloaded at pinned versions
and accepted only after their platform-specific official SHA-256 values match. The output root must
be a safe absolute path. A descriptor-based guard verifies current-UID ownership, mode 0700, and a
mode-0600 regular staging sentinel before cleanup. Restaging removes every generated directory and
single-file output while preserving the ownership sentinel. Sentinel verification opens the final
component in nonblocking mode before descriptor checks, so a special file cannot stall resume.
Generated child files use a held-parent, exclusive, no-follow writer. A resumed replacement unlinks
only the final entry through that descriptor and then recreates it with `O_EXCL`, so an existing
symlink, FIFO, or hard link cannot redirect or truncate another file. Signed offline-kit metadata
and streamed bundle archive publication use the same boundary.
Before creating or resuming a release workdir, the guard also requires every ancestor to be owned by
root or the current UID. A group- or world-writable ancestor must have the sticky bit, which prevents
another UID from swapping the validated workdir before cleanup.
The `provision plan` workdir applies the same ancestor policy, requires an existing safe parent, and
sets mode `0700` through the newly opened directory descriptor before materializing verified
artifacts.
Offline planning recomputes the profile target digest from concrete tenant and subscription input,
matches the profile region, and supplies the verified subscription to Terraform.
The synthetic air-gap drill isolates Azure CLI configuration so a host login cannot alter its
target evidence, requires Azure CLI as a local prerequisite, and expects its distinct redacted
provider-authentication marker. Repeated `--skip-stage` drills recreate their isolated Azure
configuration only inside a sentinel-owned work directory. Fresh drills require a nonexistent safe
absolute path, and both fresh and resumed drills use the descriptor-based UID and mode guard. The
drill needs no ambient Terraform because it uses the authenticated kit snapshot.
It also clears Python import overrides before invoking the installed distribution, so checkout
source cannot shadow a shipped wheel. Manifest, trust-key, and SBOM reads use bounded nonblocking
regular-file readers in both source and installed-wheel verification.
The shipped-wheel install disables the `uv` cache, so a previously cached wheel with the same
version and filename cannot replace the authenticated kit artifact during a hardening drill.
A pre-login hardening campaign closes only after the complete focused gate stack, fresh and resumed
air-gap drills, and a final severity audit leave no finding above Low.
The connected stage issues its synthetic license through the current Core and service-contract
package roots rather than the retired monolithic source path, and verifies the issued Ed25519
signature without a removed delivery adapter. License output is a new private file; issuance never
truncates or replaces an existing path. Release utilities read signing keys through one nonblocking,
no-follow, 65536-byte regular-file boundary. Private keys must be owned by the current UID with mode
`0600`.
Connected plans expose only a validated Azure CLI path or target-bound Managed Identity variables
to Terraform; unrelated environment values remain excluded.

The C1 commands use stable JSON schemas for automation. `provision init` captures only the active subscription and tenant identifiers,
environment, region, remote-runner boundary, and shadow-mode default in a gitignored mode-`0600` file. Human output never prints the account
identifiers. Profile, plan-input, and journal readers open paths in nonblocking mode before checking for a mode-`0600` regular file, so
named pipes cannot stall read-only commands. Journal appends also use a nonblocking exclusive lock with a five-second monotonic deadline and
repeat descriptor validation after acquisition, so contention stops the append instead of hanging onboarding. Journal directory traversal
opens every component relative to a held parent descriptor and rejects symlinked ancestors. Provision-event v2 records the manifest version
used for READY validation, while the v1 decoder preserves replay of journals created before that field existed. Resource and page counters
can appear after discovery starts and can grow, but cannot disappear, decrease, or reduce their expected totals in a later progress
snapshot.

`license inspect` is offline in the same sense as bundle and kit verification: the public key ships with the distribution, so no network
call, revocation lookup, or certificate chain is involved. It reports status and non-secret metadata only and never echoes the token,
document, or signature. The token input is accepted only as a mode-`0600` regular file no larger than 8192 bytes. The reader does not follow
symlinks and opens the path in nonblocking mode before checking its type, so named pipes and device files are blocked without waiting. It
preserves the token bytes exactly and rejects leading or trailing whitespace; release issuance writes the token without a trailing newline.
Trust-key inputs use the same no-follow, nonblocking regular-file boundary with a 65536-byte limit. The entitlement contract itself lives in
[capability-licensing.md](../fork-and-sequencing/capability-licensing.md).

## Local security audit

`fdaictl security audit` checks high-risk local and runtime combinations before a process starts.
It reports stable check ids without echoing environment values or configuration contents. Current
checks cover:

- development authentication bypasses enabled in staging or production;
- missing Entra verifier configuration outside development;
- VM-task or chaos enforcement without its required governed runtime context;
- a requested bubblewrap command sandbox whose binary is unavailable;
- a deployment configuration that is a symbolic link, has group or world permissions, cannot be
  parsed, or contains secret-like field names.

Use `--output json` for automation. A critical unfixed finding exits `3`; no critical finding exits
`0`. `--fix-permissions` is deliberately narrow: for a regular local config file, it can set the
file to mode `0600` and its directory to `0700`. It never follows a symlink, edits configuration
content, disables a feature, rotates a credential, or changes a cloud resource.

This audit does not replace deployment preflight, OPA policy evaluation, secret scanning, Entra
access review, or the risk gate. It catches local configuration drift early, then those
authoritative controls make the deployment and runtime decisions.

## Portable backup and restore

Use `fdaictl backup create` to move the operator-owned deployment metadata that is needed after a
workstation or installation change. The command reads four validated JSON inputs and creates a
deterministic mode-`0600` archive:

- **Configuration:** The schema-validated environment, remote-runner boundary, and shadow-mode
  default.
- **References:** Opaque secret, document, policy, workflow, channel, and bundle references. A
  secret reference names a provider entry; it never contains the secret value.
- **Audit metadata:** The source schema, record count, last sequence, and audit hash-chain head.
  Audit entry bodies are not exported.
- **User context:** Locale, verbosity, answer detail and format preferences including `chart`,
  timezone, learner-sharing preference, and explicitly consented memory records. Conversation
  transcripts and generated briefing bodies are not part of this archive format.

Example:

```bash
fdaictl backup create \
  --config .fdai/environments/dev.json \
  --references .fdai/portable/references.json \
  --audit-metadata .fdai/portable/audit-metadata.json \
  --user-context .fdai/portable/user-context.json \
  --archive fdai-dev.fdai-backup

fdaictl backup restore \
  --archive fdai-dev.fdai-backup \
  --destination .fdai/restored/dev
```

The archive contains an exact four-file allowlist plus a SHA-256 manifest. Creation blocks unknown
schema fields, credential-shaped values, private-key material, Terraform state markers, symbolic
links, oversized inputs, and accidental overwrite unless `--force` is explicit. It does not read a
secret provider or Terraform state file.

Restore accepts only the same fixed member set and stored ZIP format, validates every schema and
digest before publishing files, and rejects an existing destination. The destination appears by
one atomic rename with directory mode `0700` and file mode `0600`, so a failed validation leaves no
partial restored state. Both commands are local-only and make no Azure or Terraform calls.

## Guided deployment onboarding

Use `fdaictl onboard guided` to run the safe subscription-genesis stages as one durable, fail-closed sequence. It pauses at protected approval checkpoints and composes the low-level `deploy plan`, `deploy apply`, and `deploy status` contracts.
Only the sealed foundation phase can run Terraform locally because the Azure execution host does not exist yet; it performs no private data-plane write. [Subscription Genesis Provisioning](subscription-genesis-provisioning.md) defines the full lifecycle.
The [Subscription Genesis Assurance](subscription-genesis-assurance.md) contract defines safety, cancellation, secret transfer, concurrency, cost, and final readiness.

The sequence is fixed:

1. **Toolchain doctor:** Verify Python, Azure CLI, Terraform, GitHub CLI, and interactive Azure
  authentication before writing configuration.
2. **Private configuration:** Create the schema-validated mode-`0600` environment file. An existing
  file blocks the run unless `--force-config` is explicit.
3. **Target doctor:** Re-run doctor with the new file and block an active tenant or subscription
  mismatch before any runner call.
4. **Live preflight:** Run static and configured read-only Azure probes. An optional
  `--terraform-plan` file is parsed for resource types; the wizard doesn't run `terraform plan`.
5. **Durable orchestration:** Create the run manifest, submit exact plans, and pause at each
  protected approval without transferring state or secrets to the local machine.
6. **Post-check:** Follow sanitized run progress through database, semantic, model, runtime,
  inventory, and readiness closure. Apply-claim recovery follows the existing no-retry rule.

Example:

```bash
fdaictl onboard guided \
  --environment dev \
  --region koreacentral \
  --config .fdai/environments/dev.json \
  --preflight-input .fdai/preflight/dev.json \
  --repository <owner>/<repository> \
  --bundle-digest <sha256> \
  --commit-sha <git-sha> \
  --output json
```

The GitHub installation token stays in `FDAI_GITHUB_TOKEN`; it is not a command argument. Machine
output reports the completed step ids, plan id, status, and workflow URL without target identifiers
or credential values. A failure reports only the failed step and a sanitized reason. Later stages
are never called after an earlier failure, so a doctor or preflight blocker cannot reach runner
submission.

The initial implementation should not expose arbitrary Terraform arguments. Supported environment
and feature settings come from the validated configuration schema. An explicit escape hatch, if
one is added later, should be audited and should never accept secret values on the command line.

## Preflight contract

`fdaictl deploy preflight` is a read-only composition root for the existing
`PreflightAnalyzer`. It should reuse the shared report and probe contracts rather than implement a
second set of readiness rules inside the CLI.

The implemented analyzer primitives accept the data represented by a versioned JSON input. The target CLI path will expose that input
containing the deployment's neutral scope, resource types, required egress hosts, and grounded policy facts. It runs only the deterministic
local probes, performs no network call, and preserves the analyzer's stable ordering and shadow-versus-enforce semantics. Pass
machine-readable `terraform show -json` output with `--terraform-plan`. The input's explicit `terraform_resource_type_map` converts only
managed resources with a `create` action, including replacements, to CSP-neutral types. Data sources, no-op, read, update-only, delete-only,
and Terraform built-in metadata such as `terraform_data` are ignored. An unmapped created provider resource makes the run incomplete, and
resource addresses or planned values never enter the report.

Pass `--environment-config` to add bounded live Azure checks. The CLI reads the validated onboarding target, obtains a short-lived ARM token
through the local Azure CLI identity, and runs Azure Policy, configured Compute quota, and executor RBAC probes through bounded read-only
ARM and Resource Graph transports. ARM GET requests are limited to 20 seconds and eight pages; the role query is a 20-second read-only ARG
POST. Neutral resource types are translated to ARM types inside the Azure adapter. An unmapped type or failed probe makes the run
incomplete, and the CLI error doesn't expose the subscription, resource group, principal, role definition, or Azure path. An optional
`key_vault` block checks required secret references by opening a streamed GET and inspecting only the status code; it never reads the
response body or secret value. Missing references use a SHA-256-derived id, so vault hosts and secret names don't enter the report. The
report includes a stable `checks` array even when no finding exists. Each entry records only the probe category, `clear` or `finding`
status, and finding count, so automation can distinguish a successful check from a check that was never configured. A live profile can
declare `required_categories`; missing quota, identity, or secret configuration then fails before any network call. Bounded runner TLS
reachability supplies the live egress evidence. Static Firewall, NSG, and UDR topology analysis remains a separate future adapter.

```bash
terraform -chdir=infra show -json dev.plan > dev.plan.json
fdaictl deploy preflight \
  --input preflight-input.json \
  --terraform-plan dev.plan.json \
  --environment-config .fdai/environments/dev.json \
  --output json
```

### Stages

The command runs these stages in order:

1. **Toolchain and artifact checks:** Verify supported versions, lock files, CLI-to-bundle
   compatibility, checksums, signatures, and the selected environment.
2. **Identity and target checks:** Confirm the active Azure subscription, deployer role
   assignments, provider registrations, target region, and runner identity.
3. **Static infrastructure checks:** Validate supplied `terraform show -json` plan data. The
  approved runner's `deploy plan` workflow owns fmt/init/validate and plan generation.
4. **Bounded live checks:** Query Azure Policy, Resource Graph, quota, network configuration, and
   required secret existence through read-only adapters.
5. **Readiness decision:** Assemble one grounded report, record whether each finding is enforced
   or still in shadow mode, and print the next safe action.

A failed or skipped probe never produces a `clear` result. The report marks the run incomplete and
provides the failed probe name without exposing customer values or credentials.

### Detected issue categories

The CLI presents the categories already defined by deployment preflight:

- **Policy guardrails:** Denied resource types, required network controls, and public-access
  restrictions.
- **Supply-chain egress:** Package, image, and operating-system repositories that require an
  approved mirror.
- **Identity and RBAC:** Missing deployer or runner permissions at the intended scope.
- **Quota and capacity:** Region, SKU, and service quota blockers.
- **Dependency ordering:** Resources that need a prerequisite deployment stage.
- **Secret configuration:** Missing references or unreachable secret providers, without reading
  or printing secret values.

### Output and exit codes

Human output is a concise table. Automation uses `--output json`, whose schema is versioned
independently from display text. Localized display strings never change field names, verdicts,
evidence identifiers, or exit codes.

| Exit code | Meaning |
|-----------|---------|
| `0` | The run completed and no review or enforced blocker remains |
| `2` | Review is needed, including a blocker reported by a shadow-mode probe |
| `3` | An enforce-mode blocker prevents plan or apply |
| `4` | The run is incomplete because a required probe or dependency failed |
| `64` | Command usage or environment configuration is invalid |

The report's truthful verdict remains separate from whether a finding currently blocks a deploy.
For example, a shadow-mode probe can report `blocked` while the process exits with `2` for review
instead of `3` for enforcement.

For protected remote plans, the private runner requires the non-secret GitHub Variable
`DEPLOY_PREFLIGHT_INPUT_JSON`. Its `azure_live.required_categories` must contain
`policy_guardrail`, `quota_capacity`, `identity_rbac`, and `secret_config`, with the corresponding
resource-type maps, quota checks, principal/role references, and Key Vault metadata references.
The workflow overwrites the mode to `enforce`, sets the current timestamp, and replaces the report
scope with a neutral value. It installs the locked CLI, converts the exact binary plan to JSON,
runs all four read-only live categories, and accepts only a `clear` report with complete check
coverage. Plan JSON, environment identifiers, and the input profile are removed at step exit.

When `deploy_operator_api` is enabled, configure non-secret `STEWARDSHIP_MAINTAINERS` and
`STEWARDSHIP_AGENT_BINDINGS_JSON` repository Variables. The latter maps every non-autonomous
Pantheon agent to one or more `user:<oid>` or `group:<oid>` tokens; Loki may retain its explicit
autonomous acceptance. The workflow binds the Entra directory provider and these values into
Terraform. Resource preconditions reject an empty maintainer or any missing agent binding before a
broken Operator API revision can be created.

Only the sanitized report is stored beside the protected plan. Metadata binds separate SHA-256
digests for runner-egress evidence and Azure live evidence. Exact apply downloads both original
files and recomputes their digests before claim or Terraform execution; changing either evidence
file blocks apply even when the binary plan digest still matches.

## Read-only preflight and bootstrap discovery

The default preflight never creates an Azure resource. Some tenant policy discovery requires a
throwaway resource to observe the policy result. Keep that operation behind a separate, explicit
command:

```bash
fdaictl bootstrap probe-policy --allow-probe-resources
```

This bootstrap mutation command is **planned** and is not registered in the current CLI parser.
For now, invoke `infra/bootstrap/preflight-policy-check.sh` explicitly.

This command should show the resource scope, cleanup behavior, stop condition, and expected cost
before it runs. It is not part of `fdaictl deploy preflight`, and preflight must not invoke it
implicitly.

## Deployment artifact model

The runtime now ships as five service wheels plus the versioned service-contract SDK. Those
runtime distributions do not include the planned `fdaictl` deployment commands. Deployment also
depends on Terraform modules, policies, schemas, and selected rule-catalog data. Packaging all
mutable infrastructure files as importable Python resources would make version alignment and
inspection harder. Use a dedicated CLI wheel and a version-matched deployment bundle instead.

### Planned deployment CLI wheel

The dedicated wheel will contain:

- the `fdaictl` entry point and command parser;
- configuration and output schemas;
- preflight orchestration and report rendering;
- artifact download and signature verification;
- workflow submission and status clients.

Deployment-only integrations remain outside every service runtime import path. Do not restore the
retired top-level `fdai.deployment_cli` package to a runtime wheel. Ship the command surface only
through the dedicated lightweight CLI distribution when this planned interface is implemented.

### Signed deployment bundle

The deployment bundle contains:

- the Terraform root and modules from `infra/`;
- OPA policies used to verify the plan;
- required rule-catalog schemas and deployment profiles;
- a manifest that records versions and SHA-256 digests;
- a software bill of materials and release signature.

CLI version `<version>` resolves bundle `<version>` by default. The CLI verifies the signature and
manifest before running Terraform. An operator can provide `--bundle <path>` for a disconnected
environment, but the same verification still applies. A version mismatch fails before plan
generation unless an explicitly documented compatibility range allows it.

`fdaictl bundle verify --bundle <dir> --public-key <pem>` defines the target verification side. It
accepts Ed25519 public keys only, verifies the detached manifest signature, checks the current CLI
against the manifest compatibility range, rejects traversal and symlinks, requires the exact
listed file set and a listed JSON SBOM, streams every SHA-256 check, and enforces a total-size cap.
It never contains signing-key or bundle-building code.

`scripts/deployment/release/build-deployment-bundle.py` implements the release-only build side. It discovers only
tracked files under `infra/`, `policies/`, `rule-catalog/schema/`, `rule-catalog/profiles/`, and
`rule-catalog/risk-classification.yaml`; plan, tfvars, tfstate, PEM/key, symlink, untracked, and
outside-root paths are rejected. It normalizes file mode, mtime, tar owner/group, gzip timestamp,
and ordering, generates a deterministic CycloneDX file SBOM, writes the canonical manifest, and
signs it with an external Ed25519 private key. The private key never enters the bundle.

Every manifest also signs one release channel: `stable`, `beta`, or `development`. The release
workflow requires the channel as an explicit choice and passes it into both reproducibility builds,
so changing a channel after signing invalidates the signature. Bundle verification returns the
signed channel together with version and manifest digest.

The approval-gated `release-deployment-bundle` workflow is designed to read
`FDAI_BUNDLE_SIGNING_KEY_PEM` from the `release` GitHub Environment, builds twice from the same
commit and `SOURCE_DATE_EPOCH`, compares both directories, archives, and public keys byte-for-byte,
runs `fdaictl bundle verify`, and publishes the archive, public key, manifest, signature, and
checksums as a 30-day Actions artifact. `publish_release=true` is the separate explicit gate that
creates a GitHub Release. The temporary private key is mode-restricted and removed through a shell
trap.

Before the `release` Environment can expose that signing key, two independent jobs must pass from
the exact clean checkout. The verification job installs the locked Python and console dependencies,
starts a disposable pgvector PostgreSQL service, upgrades it to the single Alembic head, runs
`scripts/verify.sh --all` with live integration tests, and then runs the productization and console
checks. Productization validates the deployment CLI in its independent project environment, then
validates the service-contract SDK and five service-owned roots before building all seven wheels. A final `git diff --exit-code`
blocks generators that rewrite tracked source. The dependency-audit job runs the pinned Python
vulnerability scanner. The bundle job declares both jobs in `needs`, uses a pinned Ubuntu runner
image, and alone receives `contents: write`; verification and audit jobs remain read-only.

## Release channels, upgrade, and rollback

Use `fdaictl release upgrade` to activate a newer signed bundle revision. Supply the local
environment config, release-state path, bundle directory, trusted public key, and expected channel.
The command verifies the signature, file digests, CLI compatibility range, and signed channel before
writing any state. Upgrade accepts only a newer semantic version; use rollback for an older version.

```bash
fdaictl release upgrade \
  --state .fdai/release-state.json \
  --config .fdai/environments/dev.json \
  --bundle <verified-bundle-directory> \
  --public-key <trusted-public-key.pem> \
  --channel stable \
  --output json
```

Release state is an atomic mode-`0600` JSON pointer containing the active version, signed channel,
manifest digest, a bounded 20-entry history, and only the SHA-256 digest of the current config. It
doesn't store config content, secret values, Terraform state, binary plans, or host paths. The CLI
writes a temporary state file, rechecks the config digest, and only then replaces the active pointer.
The config itself is never rewritten.

Use `fdaictl release rollback` with the exact prior signed bundle. The candidate must match the
newest history entry in version, channel, and manifest digest after full bundle verification. A
different, tampered, incompatible, or merely older bundle is blocked before state changes.

```bash
fdaictl release rollback \
  --state .fdai/release-state.json \
  --config .fdai/environments/dev.json \
  --bundle <prior-verified-bundle-directory> \
  --public-key <trusted-public-key.pem> \
  --output json
```

## Plan and apply integrity

The protected workflow implements the runner side of this contract. The source distribution
registers `deploy plan`, `deploy apply`, and `deploy status`, and `onboard guided` composes the same
transport after bootstrap reconciliation.

`fdaictl deploy plan` checks the active Azure target against the mode-`0600` profile, requires the
Azure and GitHub CLIs, and submits a plan-only workflow. It returns a bounded request id and context
digest. `deploy status --request-id <id>` recomputes the context, finds one request-bound workflow,
and downloads only sanitized plan metadata after success. Status strips only the reviewed
request-mode prefix before checking the embedded target/context binding. The GitHub CLI uses
provider-hosted authentication, and no credential is copied into a command argument.

The dispatch sends `apply=false`, the environment, exact commit, and a SHA-256 deployment-context fingerprint.
Console, Operator API, document-ingestion, isolated-Executor, monitoring, and the exclusive RCA-reader
bootstrap selection are sealed identically into plan and apply. The RCA selection uses a `plan-rca-*` or
`apply-rca-*` request and permits only the dedicated identity and Monitoring Reader role. An optional runtime
source revision is also sealed into the fingerprint; planning promotes and verifies that Core image, while
apply restores the digest-pinned plan. Any changed input invalidates the plan before Terraform runs.

Apply dispatch carries no GitHub Environment approval gate. The client does not inspect required
reviewers, self-review, or administrator bypass, and the protected workflows bind no deployment
environment, so an authorized dispatch applies immediately. A profile `approval_quorum` value is
still required to be positive but no longer selects an external approver on this transport.

The current client supports `dev` and `staging`. It rejects `prod` because the production image,
alert destination, and budget inputs are not yet part of the client context digest. Production
continues to use the separately reviewed workflow interface until those fields are bound.

`--deploy-design-mocks` is a dev-only, exclusive target. It cannot be combined with another
deployment feature flag. The runner targets only `module.design_mocks` and rejects a plan that
contains any resource change outside the design-mocks Static Web App.

```bash
fdaictl deploy plan \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --commit-sha <git-sha> \
  --run-id <run-id> \
  --output json

fdaictl deploy status \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --request-id <request-id> \
  --commit-sha <git-sha> \
  --output json
```

The local CLI doesn't download or print the binary Terraform plan because plan files can contain sensitive state-derived values. The runner
stores CLI-requested plans and sanitized metadata in a private `deployment-plans` Blob container beside the remote-state container. Uploads
use the runner managed identity, public access is off, and `overwrite=false` makes each run path immutable. Metadata records the plan
digest, context digest, exact commit, workflow run, and a one-hour logical expiry without tenant, subscription, backend, runner, or secret
values. A plan with a selected runtime revision also records the verified source revision and OCI digest without a registry endpoint or mutable
tag. A successful `deploy status` returns the derived plan id and digest from the bounded metadata-only artifact. Each new plan run scans at
most 1001 private blobs and deletes at most 1000 allowlisted plan paths older than 24 hours; reaching either bound fails closed without
deleting unknown paths.

`fdaictl deploy apply --plan-id <id>` applies the exact saved plan only when all of these checks
pass:

- the plan was produced for the same subscription, environment, bundle digest, and commit;
- the plan has not expired or already been applied;
- `--plan-expires-at` (from sanitized `deploy status` plan metadata) passes deterministic UTC
  client-side expiry enforcement before dispatch;
- the preflight report has no enforce-mode blocker;
- the caller requested apply explicitly;
- the runner identity and backend configuration match the recorded plan context.

The CLI repeats its tool, authentication, and target checks and dispatches the reviewed plan id and
digest with the same computed context. The apply workflow independently reloads the workflow-owned
metadata and verifies context and logical expiry. It skips `terraform plan`, restores the exact
binary and metadata from private Blob storage, verifies all digests, ids, status, timestamps, and
commit, and then creates an immutable `apply-claim.json` before `terraform apply`. A duplicate or
failed prior claim blocks automatic retry. A successful run writes an immutable
`apply-receipt.json`; `deploy status` projects `applying` from the claim and `applied` from the
receipt.

If Terraform apply succeeds but a later identity, migration, health, or canary check fails, run
the same command with `--resume-verification`. Resume requires the exact plan to project
`applying`, verifies the existing claim and absence of a receipt, skips Terraform apply, proves
convergence, and reruns the post-apply checks before writing the receipt. A changed context,
missing claim, or existing receipt blocks resume. Targeted plans may leave the console hostname
output empty; Entra sync then resolves the exact Static Web App id from Terraform state and reads
its hostname through the Azure management plane.

Post-apply migration permits immutable built-in workflow definitions for the same workflow document
to coexist when they pin different action-catalog digests. The unique database identity includes
workflow name, workflow version, definition hash, and action-catalog digest. This keeps startup
idempotent across catalog releases without overwriting older definitions.

```bash
fdaictl deploy apply \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --plan-id <plan-id> \
  --plan-digest <plan-digest> \
  --plan-expires-at <expires-at> \
  --commit-sha <git-sha> \
  --run-id <run-id> \
  --output json
```

The protected workflow store marks each plan expired after one hour. Logs expose only the plan id,
digest, and expiry. They don't expose the plan file, state, credentials, or secret values. Apply
must reject logical expiry even if physical cleanup hasn't removed the blob yet.

The transport keeps only opaque metadata locally. The GitHub plan path returns a request-bound
dispatch receipt, the runner stores the protected binary plan in private Blob storage, and
`deploy status` retrieves a bounded sanitized artifact through the workflow host. Exact apply and
verification-only resume send the same feature selection and context digest. The GitHub Environment
approval boundary, immutable claim, and audit receipt remain authoritative. Runner egress preflight
evidence is bound into immutable plan metadata, and post-apply checks require Terraform convergence,
migration success, and enabled endpoint health before the receipt is written. Runner-side policy,
quota, identity, secret, and egress evidence are required inputs to the C4 exact-plan gate.

## Private-everything tenants

A local command does not move the apply boundary back to the laptop. When a tenant makes Key Vault,
state storage, or other data services private, both plan and apply run on the VNet-integrated
self-hosted runner. The local CLI uses management-plane reads to determine that the runner path is
required, starts or locates the approved workflow, and reports its status.

The runner continues to use managed identity. `fdaictl` does not copy a service-principal secret,
Terraform state, generated database password, or Key Vault value to the local machine. If the
runner is unavailable, the CLI reports a blocker rather than falling back to a local apply.

## Configuration and secret handling

Environment configuration is schema-validated and stored outside the package. Generated config is
untracked by default and contains references, not secret values.

- **Allowed:** Environment name, region, feature flags, backend references, repository name, and
  approved artifact source.
- **Not allowed:** Passwords, access tokens, connection strings, Terraform state, binary plans, or
  populated customer config in the upstream repository.
- **Command history:** Secret values are never accepted as command-line arguments.
- **Logs:** Structured logs carry a correlation ID and redact configured sensitive fields.
- **Machine output:** JSON uses stable English field names and never includes secret material.

User-visible CLI text is an L2 product surface. English source messages live in a message catalog,
Korean translations live in the matching locale catalog, and missing translations fall back to
English. Logs, JSON fields, verdicts, and evidence remain English-only machine surfaces.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and remaining work | [Implementation ledger](../../roadmap-implementation/deployment/installable-deployment-cli.md) |
| Provisioning host, connectivity, transport, and access selection | [Provisioning execution profiles](provisioning-execution-profiles.md) |
| Concrete Azure inventory and onboarding | [deploy-and-onboard.md](deploy-and-onboard.md) |
| Deployment lifecycle and rollback | [deployment.md](deployment.md) |
| Readiness findings and probe contracts | [deployment-preflight.md](deployment-preflight.md) |
| Turning blockers into Terraform toggles | [preflight-active-reassembly.md](preflight-active-reassembly.md) |
| Private runner bootstrap | [../../../infra/bootstrap/README.md](../../../infra/bootstrap/README.md) |
| Product localization rules | [../../../.github/instructions/language.instructions.md](../../../.github/instructions/language.instructions.md) |
