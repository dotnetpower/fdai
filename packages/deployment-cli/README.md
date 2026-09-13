# FDAI Deployment CLI

This package provides the installable `fdaictl` deployment surface. It validates local
configuration, verifies signed deployment artifacts, and runs resumable Azure provisioning from
an active Azure CLI user or a managed deployment host. Tenant deployment never dispatches a
GitHub workflow or depends on repository variables, repository secrets, or a GitHub runner.

## Install from a clone

Cloning does not register `fdaictl` on PATH. Follow the
[clone-to-command installation guide](../../docs/user-guide/deploy-quickstart.md#install-the-command-once)
or its [Korean translation](../../docs/user-guide/deploy-quickstart-ko.md#명령을-한-번-설치)
for locked `uv tool install`, shell PATH setup, verification, updates, and optional editable mode.
No maintainer-specific paths, signing keys, or full application environment are required.

## Commands

Run `fdaictl` or `fdaictl --help` for command descriptions and a short getting-started example.
A bare group such as `fdaictl provision` shows its own help. Add `--help` to a leaf command for
required inputs, defaults, units, and examples. These discovery paths exit `0` without Azure
access, downloads, deployment-state changes, or prompts. Invalid executable invocations still
fail with usage error `2` and a next-help hint; long options must use their full names.
`--version` is a shortcut for `version`; `version --output json` keeps its stable schema.
An older snapshot installation needs the locked reinstall described in the guide above.

After `az login`, use `fdaictl provision azure --online` for the connected path. Use
`fdaictl provision azure --offline-kit <path>` for an artifact-offline path. Both modes run the
same local coordinator, move private data-plane work to the Bastion-reachable managed host, and
pause for exact-plan approval without using GitHub Actions.

Interactive text mode shows a live phase dashboard with elapsed time and observed download bytes.
Use `--progress plain` for line-oriented logs or `--progress off` to hide the dashboard. Redirected
output, `NO_COLOR`, and `TERM=dumb` use plain messages automatically. `--output json` disables the
dashboard and keeps intermediate Foundation results and approval prompts off stdout.
Phase counts are not time estimates or readiness evidence; exact approvals and verified results
remain authoritative. Redraw pauses while existing detailed output or approval input owns the terminal.
Small terminals use a compact current-phase view. Resuming the live view preserves the approval
text, EOF denies new approval, and failed or stale Foundation status never advances the run.

Use `fdaictl onboard guided --simulate` only to rehearse the finite stage graph without Azure
authentication or mutation. Live onboarding uses `fdaictl provision azure`; the rehearsal does
not expose a workflow dispatch path.

Use `fdaictl provision bootstrap-reconcile` before the first foundation approval. It performs only
target-pinned Azure management-plane reads and writes a private expiring plan whose intent and
observations have separate digests. It never creates a resource, registers a provider, writes
Terraform state, or dispatches a workflow.

The standalone coordinator prepares the foundation plan, obtains explicit terminal approval,
creates the private deployment host, transfers the verified kit through Azure Bastion, and runs
the application plan and exact apply under the host's managed identity. Verification-only resume
never repeats an ambiguous Terraform apply.

Online kit acquisition can resume in the same work directory. It rechecks package-pinned signatures,
exact payloads, runtime images, and bundle binding, and extracts a fresh execution copy without
deleting earlier state. The local source-request digest prevents an implicit URL change; it is not
trust evidence. Corrupt or partial retained content blocks reuse. HTTP, network, destination,
permission, and storage errors are distinct. See the
[kit-acquisition troubleshooting guide](../../docs/user-guide/deploy-quickstart.md#if-kit-acquisition-fails).
Keep the private work directory, which can contain SSH keys and sensitive recovery inputs.

New installations without a deployment-bound capability token can start observation-only.
Omitting a token on a resumed installation does not revoke one previously installed. A new adopter
does not need a maintainer signing key. A verified token can enable only the capabilities it declares
and does not bypass runtime promotion or approval policy.

## Deployment appliance

For a network that cannot download public artifacts, the release owner can wrap one complete
signed kit in an OCI deployment appliance:

```bash
bash scripts/deployment/release/build-deployment-appliance.sh \
  --kit /private/fdai-deployment-kit.tar.gz \
  --base-image <approved-deployer-base>@sha256:<digest> \
  --output /private/fdai-deployment-appliance.oci.tar
```

The base image must already contain Python 3 with pip, Azure CLI, OpenSSH, and `tar`. The build runs with no
network access, installs `fdaictl` only from the verified kit wheelhouse, and embeds the complete
Terraform, provider, runtime-image, Console, migration, SBOM, and provenance payload. The image
entry point authenticates with an interactive Azure user or its managed identity and invokes
`fdaictl provision azure --offline-kit` directly. It never contacts GitHub, PyPI, the public
Terraform registry, or a public container registry while deploying.

The complete release builder accepts the same base as `--appliance-base-image` and emits the kit
and appliance in one clean-checkout release run.

## Offline release preparation

On the connected release host, describe the prebuilt artifacts for one closed runtime v2 tree.
The descriptor is a mode-`0600` JSON file under a mode-`0700` directory. It names relative
files below `--source-root` and pins the SHA-256 of every OCI archive, SBOM, provenance record,
Console archive, and deployment-support archive. It also pins each OCI manifest digest, the exact
source commit, and `linux-x86_64` or `linux-aarch64`.

```bash
uv run --project packages/deployment-cli python \
  scripts/deployment/release/build-runtime-release.py \
  --source-root /private/release-inputs \
  --descriptor /private/runtime-release-build.json \
  --deployment-bundle /private/fdai-deployment-bundle-0.1.0.tar.gz \
  --output /private/runtime-release
```

For a standalone review, the command above binds an existing deployment bundle. For kit staging,
pass the descriptor and source root directly to `stage-offline-kit.sh`; it builds the signed
deployment bundle first, then assembles runtime v2 against those exact bytes before outer signing.
The builder validates all five FDAI service OCI archives and the revision-neutral ClamAV archive
before publishing `runtime/release.json`. It does not download, build, sign, attest, or publish an
image. It reports `production_release_eligibility=unverified`; the protected supply-chain gate must
have produced and approved the descriptor inputs. An interruption at the final publication boundary
leaves `runtime/.fdai-incomplete`; every runtime loader rejects that tree. Review and remove the
entire marked output, then rebuild into a new path rather than deleting only the marker.

The connected packaging host can collect all six runtime distributions and their required
workspace support libraries with locked binary dependencies:

```bash
python3 scripts/deployment/release/stage-runtime-wheelhouse.py \
  --out-dir /private/runtime-wheelhouse
```

The output separates build wheels, per-package dependency wheels, and hash-pinned requirements.
Only `build/`, `wheels/`, `requirements/`, and `inventory.json` are deliverables; exclude `.work/`.
`stage-offline-kit.sh --with-runtime-wheels` includes these at `support/python/` before signing,
separate from the CLI's own dependency versions.

Use `fdaictl offline prepare` with an independently trusted verifier, verification keys, a signed
kit, an offline target-bound profile, a positive cost ceiling, an exact source revision, and a new
private work directory. It snapshots the CLI toolchain, signed deployment bundle, and a complete
local runtime inventory without network calls or artifact execution.

Complete preparation requires runtime inventory v2: local archives for all five services,
the ClamAV sidecar, Console, and deployment support, with hashes, SBOMs, image provenance, and a
binding to the exact deployment bundle bytes. V2 staging and preparation inspect all six OCI
images for blob/manifest digests and the selected CPU platform. Service images must carry the FDAI
revision; ClamAV is a digest-bound dependency, not an FDAI-source image. OPA is already embedded in
Core and shipped as a kit tool. No layers are extracted or executed, and provenance semantics
remain a separate release gate.

Registry references without local payloads do not qualify. Release staging accepts these prebuilt
inputs through `stage-offline-kit.sh --runtime-release <directory>`. Legacy v1 inventories remain
readable and stageable, but `offline prepare` rejects them instead of silently omitting ClamAV.

Use the complete drill after staging inputs are available. `--require-runtime` prevents the older
toolchain-only rehearsal from being mistaken for complete release preparation. The connected stage
builds and signs the kit; the verification phase installs its CLI, runs `offline prepare`, and
installs every hash-pinned deployment-support distribution in a network namespace with no route or
DNS.

```bash
bash scripts/deployment/release/airgap-drill.sh \
  --runtime-descriptor /private/runtime-release-build.json \
  --runtime-source-root /private/release-inputs \
  --require-runtime
```

`prepared/preparation.json` uses `fdai.offline-preparation.v2`, binds the checked image digests,
and reports `state=prepared`, `subscription_ready=false`, and the remaining
approval and independent-readback checkpoints. This is not an Azure installer, production trust
bootstrap, or a ready receipt. Existing public-artifact GitHub deployment commands reject offline
profiles before authentication or dispatch.
See [Disconnected Deployment](../../docs/roadmap/deployment/disconnected-deployment.md).

The low-level ACR adapter supports service publication with an exact FDAI revision and dependency
publication without that revision claim. Both validate local content before acquiring credentials,
upload only to the selected registry/repository under deadlines, and require manifest GET readback.
Dependency receipts carry `source_commit=None`; neither receipt grants provenance or readiness.
These are protected-executor building blocks, not public mutating CLI commands. Approval,
target/identity binding, lease, audit, recovery, and full-runtime orchestration remain required.

### Plan the private foundation

`fdaictl provision plan --stage foundation` selects the signed bundle's
`infra/genesis-foundation` root. Without `--stage`, the existing platform plan remains the default.
Foundation planning requires an offline `managed-vm` profile with a positive cost ceiling and an
authenticated Azure CLI target matching that profile. Only the kit's locked providers are used.
Azure management-plane connectivity is still required; offline refers to artifact delivery.

Use the existing `--offline-kit`, `--release-root`, `--bundle-public-key`, `--work-dir`,
`--profile`, and `--variables-file` options. The work directory must be new. Supply a mode-`0600`
JSON input with these fields:

- `tenant_id`, `subscription_id`, `target_binding`, and `region`, matching the reviewed profile;
- `workload`, `region_short`, and `state_storage_account_name`;
- `ops_address_space`, `runner_subnet_prefix`, and `pe_subnet_prefix` as canonical IPv4 CIDRs;
- `runner_ssh_public_key` as an RSA or Ed25519 public key without a comment;
- `runner_source_image_id` as an exact managed-image or numeric gallery-version ARM id;
- `source_commit`, `run_digest`, and `foundation_context_digest` as reviewed provenance references.

Optional fields are `state_retention_days`, `runner_vm_size`, and `enable_public_egress`.
The profile supplies `env`. Credentials, registration tokens, arbitrary Terraform variables, mutable
image versions, overlapping subnets, and subnets outside the hub are not accepted. Cross-network
overlap, cost estimates, image attestations, and source eligibility still need protected preflight.

The command performs a dry run only. It returns `state=review`, `apply_authorized=false`, and
`subscription_ready=false`; it does not create resources, enroll a runner, migrate state, or grant
approval. Its declared source revision is not proof of release eligibility.

Add `--save-plan` to retain the exact foundation plan as `foundation.tfplan`, with a
`foundation-plan.json` review receipt in the new work directory. This option is not supported for
the platform dry run, which uses a placeholder database credential. Saved-plan creation checks
Terraform's complete plan projection and normalized variables, then binds the binary plan to the
verified kit, bundle, Terraform binary, provider lock, profile, target, and input digests.
Transient variables and JSON projection are removed on success or failure.

Keep both files private. The binary plan can contain sensitive provider values and is not a
portable evidence attachment. Save the returned `saved_plan.review_digest` separately, then verify
local integrity before handing the plan to a protected approval flow:

```bash
fdaictl provision verify-foundation-plan \
  --directory /private/foundation-review \
  --profile /private/profile.json \
  --expected-review-digest <review-digest> --output json
```

Verification reads only private mode-`0600` files beneath a current-user mode-`0700` directory.
It rejects changed plan bytes, mismatched profiles or receipts, and reviews outside their one-hour
local-clock window. This window is not authenticated time authority. Neither command attests the
plan's origin, proves source eligibility, or authorizes apply. A protected executor still needs
independent provenance, current approval, authenticated time, lease, rollback, and effect checks.
After expiry or a failed attempt, use a new work directory and obtain a new review digest.

### Compare state after a protected handoff

On the approved private host, `fdaictl provision verify-state-handoff` compares already-captured
local and remote raw Terraform state against the JSON output of a complete no-change plan:

```bash
fdaictl provision verify-state-handoff \
  --local-state /private/handoff/local.json \
  --remote-state /private/handoff/remote.json \
  --plan-json /private/handoff/plan.json \
  --output-receipt /private/handoff/comparison.json --output json
```

Each input must be a mode-`0600` regular JSON file no larger than 1 MiB. The output must be new,
with an absolute path under a private mode-`0700` directory. No input is modified or deleted.
The comparison checks lineage, serial, managed instance addresses and ids, full state content,
and the plan's prior managed identities. Changes, imports, moves, drift, deferred work, failed
checks, tainted/deposed instances, and incomplete plans are blocked.

Output contains only digests, counts, and comparison status, never raw state values or resource
identifiers. A match remains `state=review`: it does not prove that the supplied files came from
the approved backend or observer. Independent storage protection, lease, identity, approval, and
effect checks remain required. In particular, `local_state_deletion_authorized=false` means you
must retain the recovery cache. This command neither migrates state nor makes a subscription ready.

### Install the deployment support interpreter

```bash
fdaictl offline install-support \
  --offline-kit /media/fdai-kit --release-root /trusted/release-root.pub \
  --work-dir /private/fdai-support --output json
```

The work directory must not exist. The command authenticates and snapshots the support payload,
then uses a trusted preinstalled `uv` to create `support-env/` without indexes, caches, downloads,
or source builds. It checks dependency consistency and independently reads back the installed
distribution versions before writing `support-installation.json`.

The support interpreter can host the packaged migration and deployment tools. It does not start
the runtime services or grant the support process an Executor identity. A failed attempt retains
its private workspace without a success receipt; use a fresh work directory after diagnosis.

### Generate the first database credential

For a fresh platform deployment, the approved private-host Terraform input can set
`generate_initial_postgres_password = true` and `postgres_admin_password = null`.
Terraform generates a sensitive 32-character credential and retains it in private state without
time-based rotation triggers. No cleartext password input or new password output is required.
The existing supplied-password mode remains the default. Enabling generation on an existing server
changes its credential and requires separate review; it is not an automatic migration.

### Configure prebuilt Console files

The packaging host uses `npm --prefix console run build:offline` to build tenant-neutral files
without loading local env files or exposing process `VITE_*` values. Copy `console/dist/offline/`
into a private mode-`0700` installation directory. No Node.js rebuild runs on the installer host.

Create a mode-`0600` JSON file in a private directory with your actual public bindings:

```json
{
  "schema_version": "fdai.console-runtime.v1",
  "operator_api_base_url": "https://operator.example.com",
  "ingestion_api_base_url": "https://ingestion.example.com",
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "spa_client_id": "00000000-0000-0000-0000-000000000001",
  "api_scope": "api://00000000-0000-0000-0000-000000000002/access"
}
```

```bash
fdaictl offline configure-console --directory /private/console \
  --settings /private/console-settings.json --output json
```

The command replaces only the shipped placeholder and refuses a silent tenant change.
Runtime bindings always require Entra authentication; no bypass flag is accepted. Preserve the
generated hosting configuration so `fdai-config.js` is not cached. Entra registration, matching
API verifier/CORS settings, site publication, and authenticated readback remain separate steps.

Terminal journal events use schema v3 and bind completed stages to receipt digests. The aggregate
genesis readiness receipt requires every foundation, application, migration, semantic, model,
inventory, rollback, second-run no-change, and system-verification evidence family. Database and
semantic readback additionally requires all five service migration heads, the required PostgreSQL
extensions, passing runtime-role checks, exact ontology/catalog/default/role-manifest digests,
shadow-only defaults, and an independent observer.
Legacy v1 and v2 journals remain readable for audit but are replay-only; a new run is required
before additional stages can be recorded.

## Testing

```bash
uv run --project packages/deployment-cli python -m pytest \
  -c packages/deployment-cli/pyproject.toml -q packages/deployment-cli/tests
```
