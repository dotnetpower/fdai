---
title: Installable Deployment CLI
---
# Installable Deployment CLI

This document defines the target installation and deployment experience for FDAI. Operators
install an isolated Python command-line tool, run a read-only deployment preflight, and submit
an approved Terraform plan to the deployment runner without moving secrets through the local
machine.

> **Status:** Increment C1 and the static part of C2 are implemented in the source distribution.
> The `fdaictl` entry point, deterministic `version` and `doctor` output, secure `onboard init`,
> active Azure target guard, network-free `deploy preflight`, Terraform plan JSON analysis, and
> local `security audit` are available. The remote deployment contract, plan-only GitHub workflow
> dispatch, and exact-plan apply guard are also implemented. Bounded live Azure Policy, Compute
> quota, Resource Graph identity, value-blind Key Vault secret probes, and runner TLS egress
> evidence are available. Signed bundle build/verify/release and production exact-plan apply
> wiring are implemented. Signed wheel/mirror/disconnected delivery and teardown remain.
>
> **Execution boundary:** Terraform remains the infrastructure execution engine and source of
> truth. `fdaictl` is a thin orchestration layer over validation, plan analysis, workflow
> submission, and post-deployment checks.
>
> **Implementation focus:** Azure is the only implemented deployment target. Non-Azure provider
> support is deferred.

## Design at a glance

Use `uv` to install `fdaictl` as an isolated tool. The CLI resolves a version-matched deployment
bundle, checks the local toolchain and Azure environment, converts the Terraform plan to JSON,
and passes it through the existing deployment preflight analyzer. A real apply runs only on the
approved deployment runner, including for commands submitted from a laptop.

| Concern | Decision |
|---------|----------|
| Operator command | `fdaictl` |
| Preferred installation | `uv tool install fdai` |
| One-time and CI execution | `uvx --from fdai fdaictl ...` |
| Infrastructure engine | Terraform under `infra/` |
| Default action | Read-only preflight or plan |
| Apply location | VNet-integrated self-hosted runner |
| Package contents | Python CLI in a wheel plus a signed deployment bundle |
| Machine output | Stable JSON schema and documented exit codes |
| Product language | English source catalog with locale fallback |

## Why use a separate command

The repository already has two distinct command surfaces:

- `python -m fdai` starts the headless control-plane process.
- The `cli/` package is the read-only operator console.

Deployment is a third responsibility. `fdaictl` keeps deployment administration separate from
both the runtime process and the conversational console. This boundary also prevents a future
operator-console feature from acquiring deployment credentials or becoming an execution surface.

## Target operator experience

The planned persistent installation is:

```bash
uv tool install fdai==<version>
fdaictl version
fdaictl doctor
```

From a source checkout, run the implemented C1 commands with `uv run fdaictl`. A published wheel
can use the persistent installation form above once release hardening is complete.

For a one-time run or a CI job, use an ephemeral environment:

```bash
uvx --from fdai==<version> fdaictl deploy preflight --environment dev
```

`pipx` is the recommended fallback when `uv` is unavailable. A direct `pip install` remains
supported inside a virtual environment, but installing into the system Python is not recommended.
The installer does not silently install or upgrade Azure CLI, Terraform, GitHub CLI, or other
system tools. `fdaictl doctor` reports missing and incompatible tools with corrective guidance.

> `version`, `doctor`, `onboard init`, guarded `onboard guided`, portable `backup create` and
> `backup restore`, `deploy preflight`, and plan-only `deploy plan` dispatch are implemented.
> Sanitized plan metadata status is available through `deploy status`, and guarded exact-plan
> submission is available through `deploy apply`. `release upgrade|rollback`,
> `extension validate`, and `trajectory validate` are implemented; teardown remains unavailable.

## Command model

Commands are grouped around diagnosis, onboarding, deployment, and status. Every command that can
lead to a mutation makes the remote execution boundary visible.

| Command | Purpose | Azure mutation |
|---------|---------|----------------|
| `fdaictl version` | Show CLI, bundle, schema, and compatibility versions | No |
| `fdaictl doctor` | Check Python, Azure CLI, Terraform, GitHub CLI, authentication, and local config | No |
| `fdaictl onboard init` | Create a schema-validated, untracked environment configuration | No |
| `fdaictl onboard guided` | Run doctor, private config creation, live preflight, plan-only runner submission, and a sanitized status post-check in order | No |
| `fdaictl security audit` | Check runtime flag combinations, local config hygiene, and requested sandbox availability | No, unless `--fix-permissions` is explicit |
| `fdaictl bundle verify` | Verify bundle signature, compatibility, file set, digests, SBOM, and size | No |
| `fdaictl backup create` | Create a private portable archive from validated configuration, references, audit metadata, and user context | No |
| `fdaictl backup restore` | Verify and atomically restore a portable archive into a new local directory | No |
| `fdaictl deploy preflight` | Collect static and live read-only deployment blockers | No |
| `fdaictl deploy plan` | Submit a plan-only workflow to the approved runner | No |
| `fdaictl deploy apply --plan-id <id>` | Submit the exact approved plan for remote apply | Yes, on the runner |
| `fdaictl deploy status` | Read sanitized plan digest, expiry, status, and workflow URL | No |
| `fdaictl deploy teardown` | Submit the guarded environment teardown workflow | Yes, on the runner |
| `fdaictl release upgrade` / `rollback` | Verify and atomically switch the signed-bundle active pointer | No |
| `fdaictl extension validate` | Check extension manifest/archive compatibility and security offline | No |
| `fdaictl trajectory validate` | Check governed dataset checksums, schema, order, and source mapping | No |

The C1 commands use stable JSON schemas for automation. `onboard init` captures only the active
subscription and tenant identifiers, environment, region, remote-runner boundary, and shadow-mode
default in a gitignored mode-`0600` file. Human output never prints the account identifiers.

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
- **User context:** Locale, verbosity, timezone, learner-sharing preference, and explicitly
  consented memory records. Conversation transcripts and generated briefing bodies are not part of
  this archive format.

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

Use `fdaictl onboard guided` to run the existing safe deployment stages as one fail-closed
sequence. The command is a plan-only wizard; it doesn't expose an apply option and it never invokes
Terraform locally.

The sequence is fixed:

1. **Toolchain doctor:** Verify Python, Azure CLI, Terraform, GitHub CLI, and interactive Azure
  authentication before writing configuration.
2. **Private configuration:** Create the schema-validated mode-`0600` environment file. An existing
  file blocks the run unless `--force-config` is explicit.
3. **Target doctor:** Re-run doctor with the new file and block an active tenant or subscription
  mismatch before any runner call.
4. **Live preflight:** Run static and configured read-only Azure probes. An optional
  `--terraform-plan` file is parsed for resource types; the wizard doesn't run `terraform plan`.
5. **Plan-only submission:** Dispatch the approved runner workflow with `apply=false` through the
  existing opaque context contract.
6. **Post-check:** Poll only for temporarily missing plan metadata for up to 60 seconds. Continue
  only when sanitized status is `planning` or `ready`; every other state fails closed.

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

The implemented static path accepts a versioned JSON input containing the deployment's neutral
scope, resource types, required egress hosts, and grounded policy facts. It runs only the
deterministic local probes, performs no network call, and preserves the analyzer's stable ordering
and shadow-versus-enforce semantics. Pass machine-readable `terraform show -json` output with
`--terraform-plan`. The input's explicit `terraform_resource_type_map` converts only managed
resources with a `create` action, including replacements, to CSP-neutral types. Data sources,
no-op, read, update-only, and delete-only changes are ignored. An unmapped created type makes the
run incomplete, and resource addresses or planned values never enter the report.

Pass `--environment-config` to add bounded live Azure checks. The CLI reads the validated
onboarding target, obtains a short-lived ARM token through the local Azure CLI identity, and runs
Azure Policy, configured Compute quota, and executor RBAC probes through bounded read-only ARM
and Resource Graph transports. ARM GET requests are limited to 20 seconds and eight pages; the
role query is a 20-second read-only ARG POST. Neutral resource types are translated to ARM types
inside the Azure adapter. An unmapped type or failed probe makes the run incomplete, and the CLI
error doesn't expose the subscription, resource group, principal, role definition, or Azure
path. An optional `key_vault` block checks required secret references by opening a streamed GET
and inspecting only the status code; it never reads the response body or secret value. Missing
references use a SHA-256-derived id, so vault hosts and secret names don't enter the report.
The report includes a stable `checks` array even when no finding exists. Each entry records only
the probe category, `clear` or `finding` status, and finding count, so automation can distinguish a
successful check from a check that was never configured. A live profile can declare
`required_categories`; missing quota, identity, or secret configuration then fails before any
network call. Bounded runner TLS reachability supplies the live egress evidence. Static Firewall,
NSG, and UDR topology analysis remains a separate future adapter.

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

The current Python wheel contains the `src/fdai` package, while deployment also depends on
Terraform modules, policies, schemas, and selected rule-catalog data. Packaging all mutable
infrastructure files as importable Python resources would make version alignment and inspection
harder. Use two version-matched artifacts instead.

### Python wheel

The wheel contains:

- the `fdaictl` entry point and command parser;
- configuration and output schemas;
- preflight orchestration and report rendering;
- artifact download and signature verification;
- workflow submission and status clients.

Deployment-only integrations should remain outside the control-plane runtime import path. The
first implementation can ship in the existing distribution. A separate lightweight CLI
distribution can be considered later if installation size or dependency isolation becomes a
measured problem.

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

`fdaictl bundle verify --bundle <dir> --public-key <pem>` implements the verification side. It
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

The approval-gated `release-deployment-bundle` workflow reads
`FDAI_BUNDLE_SIGNING_KEY_PEM` from the `release` GitHub Environment, builds twice from the same
commit and `SOURCE_DATE_EPOCH`, compares both directories, archives, and public keys byte-for-byte,
runs `fdaictl bundle verify`, and publishes the archive, public key, manifest, signature, and
checksums as a 30-day Actions artifact. `publish_release=true` is the separate explicit gate that
creates a GitHub Release. The temporary private key is mode-restricted and removed through a shell
trap.

Before the `release` Environment can expose that signing key, two independent jobs must pass from
the exact clean checkout. The verification job installs the locked Python and console dependencies,
starts a disposable pgvector PostgreSQL service, upgrades it to the single Alembic head, runs
`scripts/verify.sh --full` with live integration tests, and then runs the productization, console,
wheel-build, and isolated-CLI checks. A final `git diff --exit-code` blocks generators that rewrite
tracked source. The dependency-audit job runs the pinned Python vulnerability scanner. The bundle
job declares both jobs in `needs`, uses a pinned Ubuntu runner image, and alone receives
`contents: write`; verification and audit jobs remain read-only.

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

`fdaictl deploy plan` submits a plan-only workflow and currently returns the workflow run id and
URL. It requires the same environment config to pass `doctor`, reads the GitHub credential only
from `FDAI_GITHUB_TOKEN`, and sends `apply=false`, the environment, exact commit, and a SHA-256
deployment-context fingerprint. Tenant, subscription, backend, and runner identifiers aren't sent
in the dispatch body. The workflow validates the bounded request id, context digest, and exact
checked-out commit before planning.

```bash
FDAI_GITHUB_TOKEN=<installation-token> fdaictl deploy plan \
  --config .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --bundle-digest <sha256> \
  --commit-sha <git-sha> \
  --output json
```

The local CLI doesn't download or print the binary Terraform plan because plan files can contain
sensitive state-derived values. The runner stores CLI-requested plans and sanitized metadata in a
private `deployment-plans` Blob container beside the remote-state container. Uploads use the
runner managed identity, public access is off, and `overwrite=false` makes each run path immutable.
Metadata records the plan digest, context digest, exact commit, workflow run, and a one-hour logical
expiry without tenant, subscription, backend, runner, or secret values. `deploy plan` returns the
derived plan id, and `deploy status --plan-id <id>` reads the bounded metadata-only artifact. Each
new plan run scans at most 1001 private blobs and deletes at most 1000 allowlisted plan paths older
than 24 hours; reaching either bound fails closed without deleting unknown paths.

`fdaictl deploy apply --plan-id <id>` applies the exact saved plan only when all of these checks
pass:

- the plan was produced for the same subscription, environment, bundle digest, and commit;
- the plan has not expired or already been applied;
- the preflight report has no enforce-mode blocker;
- the caller requested apply explicitly and satisfies the workflow approval policy;
- the runner identity and backend configuration match the recorded plan context.

The CLI reruns `doctor`, retrieves bounded metadata, verifies the context digest and logical
expiry, and dispatches the stored plan digest only. The apply workflow uses the target GitHub
Environment for external approval and audit history. It skips `terraform plan`, restores the exact
binary and metadata from private Blob storage, verifies all digests, ids, status, timestamps, and
commit, and then creates an immutable `apply-claim.json` before `terraform apply`. A duplicate or
failed prior claim blocks automatic retry. A successful run writes an immutable
`apply-receipt.json`; `deploy status` projects `applying` from the claim and `applied` from the
receipt.

```bash
FDAI_GITHUB_TOKEN=<installation-token> fdaictl deploy apply \
  --config .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --plan-id <plan-id> \
  --bundle-digest <sha256> \
  --commit-sha <git-sha> \
  --output json
```

The protected workflow store marks each plan expired after one hour. Logs expose only the plan id,
digest, and expiry. They don't expose the plan file, state, credentials, or secret values. Apply
must reject logical expiry even if physical cleanup hasn't removed the blob yet.

The transport-neutral foundation is implemented in `fdai.deployment_cli.remote`. `PlanRecord`
contains only opaque metadata, and `RemoteDeploymentService` reloads it before apply. The local
guard requires `ready` status, unexpired retention, exact tenant/subscription/environment/bundle/
commit/backend/runner context, clear enforced preflight, and an available approved runner. It then
submits the workflow-owned stored digest, never a caller-supplied replacement. A concrete GitHub
plan-only transport returns current dispatch run details, the runner writes the protected binary
plan plus metadata, and the CLI retrieves sanitized status through a bounded run-scoped zip. The
exact-plan apply transport, GitHub Environment approval boundary, immutable claim, and audit receipt
are implemented. Runner egress preflight evidence is bound into immutable plan metadata, and
post-apply checks require Terraform convergence, migration success, and enabled endpoint health
before the receipt is written. Runner-side Policy, quota, identity, secret, and egress evidence
are required inputs to the C4 exact-plan gate.

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

## Delivery sequence

Deliver the CLI in small increments so the read-only boundary can be verified before remote apply
is exposed.

| Increment | Status | Scope | Exit criteria |
|-----------|--------|-------|---------------|
| C1: Package, doctor, and local security | Implemented | Console entry point, version output, toolchain and auth diagnostics, local onboarding config, local security audit | Source install produces deterministic text and JSON; target mismatch and critical local posture fail closed without exposing identifiers or values |
| C2: Read-only preflight | Implemented | Static and Terraform-plan analysis, live Policy/quota/identity/secret probes, and bounded runner TLS egress with hash-only evidence | Mock transport proves no mutation or secret-value read; every failed or incomplete probe blocks a clear result |
| C3: Plan workflow | Implemented | Opaque context digest, doctor/target guard, current GitHub dispatch API, exact-commit guard, private immutable plan upload, metadata-only status artifact, logical expiry, and bounded physical cleanup | Plan-only is the default; target identifiers are absent from dispatch and metadata, and apply stays unavailable |
| C4: Apply workflow | Implemented | Exact restore/verifier, complete runner Policy/quota/identity/secret and egress evidence, dual evidence digests, guards, approval, at-most-once claim, audit/status, Terraform convergence, migrations, and health checks | Stale, mismatched, evidence-tampered, claimed, applied, expired, non-converged, or unhealthy plans cannot produce an applied receipt |
| C5: Release hardening | Partial | Ed25519 verification, signed stable/beta/development channels, atomic config-preserving upgrade/rollback state, deterministic tracked-file build, CycloneDX SBOM, double-build comparison, and approval-gated artifact/optional GitHub Release publication implemented; signed wheel, mirror, and disconnected delivery remain | Reproducible bundle publication passes before broader distribution channels are enabled |
| C6: Guided onboarding | Implemented | Ordered doctor, private config, target guard, live preflight, plan-only runner dispatch, and bounded sanitized status post-check | Stage-spy tests prove fail-stop ordering and no guided path imports or calls local apply |

## Acceptance criteria

The design is ready to promote from roadmap to implementation when these criteria are testable:

- A clean host can install a pinned CLI version with one isolated-tool command.
- `doctor` identifies a wrong Azure subscription before any workflow is submitted.
- `deploy preflight` is read-only and produces byte-stable JSON for identical inputs.
- `onboard guided` stops at the first failed stage and never exposes a local apply path.
- A probe failure cannot be reported as `clear`.
- A private-everything tenant always routes plan and apply to the VNet runner.
- Apply uses the recorded plan digest and rejects stale or mismatched plans.
- No secret, state file, or binary plan reaches terminal output or the local machine.
- The CLI and deployment bundle can roll back together to a previously signed version.

## Open questions and decisions

- Which approved package index and release store publish the first wheel and deployment bundle?
- [x] Signature/attestation - detached Ed25519 manifest signature, deterministic CycloneDX file
  SBOM, and GitHub build-provenance/SBOM attestations.
- [x] Saved-plan retention - one-hour logical expiry and bounded physical cleanup eligibility
  after 24 hours.
- Should `fdaictl deploy teardown` ship with the first apply release or remain a separate guarded
  script until teardown drills are measured?

## Related docs

| To learn about | Read |
|----------------|------|
| Concrete Azure inventory and onboarding | [deploy-and-onboard.md](deploy-and-onboard.md) |
| Deployment lifecycle and rollback | [deployment.md](deployment.md) |
| Readiness findings and probe contracts | [deployment-preflight.md](deployment-preflight.md) |
| Turning blockers into Terraform toggles | [preflight-active-reassembly.md](preflight-active-reassembly.md) |
| Private runner bootstrap | [../../../infra/bootstrap/README.md](../../../infra/bootstrap/README.md) |
| Product localization rules | [../../../.github/instructions/language.instructions.md](../../../.github/instructions/language.instructions.md) |
