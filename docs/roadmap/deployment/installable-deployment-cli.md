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
| Connected artifact source | Versioned signed release kit over bounded HTTPS |
| Disconnected artifact source | Complete signed kit embedded in a digest-pinned deployment appliance |
| Approval | Current human approval bound to each exact plan digest |
| Execution identity | Managed host user-assigned Managed Identity |
| GitHub dependency | None for tenant deployment |

GitHub Actions may validate source, build images, and publish signed releases. It cannot plan,
apply, resume, or tear down a tenant deployment.

## Operator experience

From a source checkout, run:

```bash
az login
scripts/deployment/azure/fdai-up.sh --region <azure-region>
```

The wrapper creates the locked local environment when needed and invokes:

```bash
fdaictl provision azure --online --region <azure-region>
```

For artifact-offline deployment, use the same coordinator with a local complete kit:

```bash
fdaictl provision azure \
  --offline-kit /media/fdai/fdai-deployment-kit.tar.gz \
  --region <azure-region>
```

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
error. An incomplete runner image calls for retained-state review and a separately approved recovery
plan; a retained apply claim permits verification only, not another apply. Diagnostics never grant
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
9. Import and read back every runtime image digest.
10. Run database migrations and materialize the authoritative catalogs.
11. Deploy the services and verify runtime health.
12. Require a second zero-change Terraform plan before reporting deployment readiness.

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

A disconnected release packages the same complete signed kit inside one OCI deployment appliance.
The release command is:

```bash
bash scripts/deployment/release/build-deployment-appliance.sh \
  --kit /private/fdai-deployment-kit.tar.gz \
  --base-image <approved-deployer-base>@sha256:<digest> \
  --output /private/fdai-deployment-appliance.oci.tar
```

The approved base contains Python 3 with pip, Azure CLI, OpenSSH, and `tar`. The builder verifies the kit
before constructing the image, installs the CLI only from the kit wheelhouse, runs the image build
without network access, and emits an OCI archive with SBOM and provenance.

`build-standalone-deployment-kit.sh --appliance-base-image <image>@sha256:<digest>` composes kit and
appliance creation in one clean-checkout release run. The separate builder remains available when
an already verified kit needs an appliance wrapper.

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
