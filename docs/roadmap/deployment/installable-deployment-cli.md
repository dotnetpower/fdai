---
title: Installable Deployment CLI
---
# Installable Deployment CLI

This document defines the target installation and deployment experience for FDAI. Operators
install an isolated Python command-line tool, run a read-only deployment preflight, and submit
an approved Terraform plan to the deployment runner without moving secrets through the local
machine.

> **Status:** This is a target design. The `fdaictl` entry point, release bundle, and commands
> described here are not shipped yet.
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

For a one-time run or a CI job, use an ephemeral environment:

```bash
uvx --from fdai==<version> fdaictl deploy preflight --environment dev
```

`pipx` is the recommended fallback when `uv` is unavailable. A direct `pip install` remains
supported inside a virtual environment, but installing into the system Python is not recommended.
The installer does not silently install or upgrade Azure CLI, Terraform, GitHub CLI, or other
system tools. `fdaictl doctor` reports missing and incompatible tools with corrective guidance.

> These commands are the target interface. Do not use them until the package and console entry
> point are published by a release.

## Command model

Commands are grouped around diagnosis, onboarding, deployment, and status. Every command that can
lead to a mutation makes the remote execution boundary visible.

| Command | Purpose | Azure mutation |
|---------|---------|----------------|
| `fdaictl version` | Show CLI, bundle, schema, and compatibility versions | No |
| `fdaictl doctor` | Check Python, Azure CLI, Terraform, GitHub CLI, authentication, and local config | No |
| `fdaictl onboard init` | Create a schema-validated, untracked environment configuration | No |
| `fdaictl deploy preflight` | Collect static and live read-only deployment blockers | No |
| `fdaictl deploy plan` | Produce and analyze a Terraform plan on the approved runner | No |
| `fdaictl deploy apply --plan-id <id>` | Submit the exact approved plan for remote apply | Yes, on the runner |
| `fdaictl deploy status` | Read workflow, runner, plan, and deployment status | No |
| `fdaictl deploy teardown` | Submit the guarded environment teardown workflow | Yes, on the runner |

The initial implementation should not expose arbitrary Terraform arguments. Supported environment
and feature settings come from the validated configuration schema. An explicit escape hatch, if
one is added later, should be audited and should never accept secret values on the command line.

## Preflight contract

`fdaictl deploy preflight` is a read-only composition root for the existing
`PreflightAnalyzer`. It should reuse the shared report and probe contracts rather than implement a
second set of readiness rules inside the CLI.

### Stages

The command runs these stages in order:

1. **Toolchain and artifact checks:** Verify supported versions, lock files, CLI-to-bundle
   compatibility, checksums, signatures, and the selected environment.
2. **Identity and target checks:** Confirm the active Azure subscription, deployer role
   assignments, provider registrations, target region, and runner identity.
3. **Static infrastructure checks:** Run Terraform formatting, initialization, validation, and
   plan generation. Convert the plan to JSON for policy and dependency analysis.
4. **Bounded live checks:** Query Azure Policy, Resource Graph, quota, network configuration, and
   required secret existence through read-only adapters.
5. **Readiness decision:** Assemble one grounded report, record whether each finding is enforced
   or still in shadow mode, and print the next safe action.

A failed or skipped probe never produces a `clear` result. The report marks the run incomplete and
provides the failed probe name without exposing customer values or credentials.

### Finding categories

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

## Read-only preflight and bootstrap discovery

The default preflight never creates an Azure resource. Some tenant policy discovery requires a
throwaway resource to observe the policy result. Keep that operation behind a separate, explicit
command:

```bash
fdaictl bootstrap probe-policy --allow-probe-resources
```

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

## Plan and apply integrity

`fdaictl deploy plan` submits a plan-only workflow and returns an opaque plan ID, plan digest,
expiry time, and workflow URL. The local CLI does not download or print the binary Terraform plan
because plan files can contain sensitive state-derived values.

`fdaictl deploy apply --plan-id <id>` applies the exact saved plan only when all of these checks
pass:

- the plan was produced for the same subscription, environment, bundle digest, and commit;
- the plan has not expired or already been applied;
- the preflight report has no enforce-mode blocker;
- the caller requested apply explicitly and satisfies the workflow approval policy;
- the runner identity and backend configuration match the recorded plan context.

The protected workflow store keeps the plan for a short, configured retention period. Logs expose
only the plan summary and digest. They do not expose the plan file, state, credentials, or secret
values.

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

| Increment | Scope | Exit criteria |
|-----------|-------|---------------|
| C1: Package and doctor | Console entry point, version output, toolchain and auth diagnostics | Installs in an isolated environment and produces deterministic text and JSON |
| C2: Read-only preflight | Existing analyzer, Terraform plan JSON, Azure read adapters | Network-free tests pass and live probes cannot mutate Azure |
| C3: Plan workflow | Bundle resolution, signature check, remote plan submission, status | Plan-only is the default and returns a verifiable digest |
| C4: Apply workflow | Exact-plan apply, approval, expiry, audit, post-checks | A stale, mismatched, or blocked plan cannot apply |
| C5: Release hardening | Signed wheel and bundle, SBOM, internal mirror and disconnected bundle support | Reproducible install and rollback are demonstrated |

## Acceptance criteria

The design is ready to promote from roadmap to implementation when these criteria are testable:

- A clean host can install a pinned CLI version with one isolated-tool command.
- `doctor` identifies a wrong Azure subscription before any workflow is submitted.
- `deploy preflight` is read-only and produces byte-stable JSON for identical inputs.
- A probe failure cannot be reported as `clear`.
- A private-everything tenant always routes plan and apply to the VNet runner.
- Apply uses the recorded plan digest and rejects stale or mismatched plans.
- No secret, state file, or binary plan reaches terminal output or the local machine.
- The CLI and deployment bundle can roll back together to a previously signed version.

## Open questions

- Which approved package index and release store publish the first wheel and deployment bundle?
- What signature and attestation format should the release pipeline standardize on?
- What is the maximum saved-plan retention period for each environment?
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
