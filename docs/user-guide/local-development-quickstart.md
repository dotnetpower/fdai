---
title: Local Development Quickstart
description: Configure Docker, local state, authentication, and the complete FDAI Console stack on a Linux or WSL workstation.
---

# Local Development Quickstart

FDAI local development uses Docker for PostgreSQL, Redpanda, and ClamAV while the Python and
Node.js services run on the host. Use this guide to choose the Docker-only data stack or prepare
the complete Console stack with its Azure and Microsoft Entra bindings.

## Choose a local path

| Path | Use it for | Azure requirement |
|------|------------|-------------------|
| Docker data stack | Persistence tests, migrations, Kafka-compatible event development, and document scanning | None |
| Complete Console stack | Console, all five backend services, inventory and observation loops, document processing, and Manual Studio | An active Azure CLI session, matching Entra app registrations, and either applied `infra/` state or an explicitly selected existing read-scope resource group |

The complete stack is not an offline demo. Its databases and event transport are local, but its
Azure readers and environment metadata are grounded in the selected deployment. If you don't yet
have readable deployment state, start with the Docker data stack and deterministic tests.

> The public contributor deployment keeps isolated Terraform state under
> `.fdai/deploy/public-dev-<suffix>/`. Complete local-stack preparation currently reads the
> initialized `infra/` backend and doesn't automatically adopt that isolated state. Don't copy or
> move a state file to bypass this boundary.

## Install the prerequisites

### One-command workstation setup

On x86_64 Ubuntu or WSL, run the repository installer from the repository root:

```bash
bash scripts/automation/setup-local-development.sh
```

The script installs the system packages and repository-pinned command-line tools, configures
Docker access, installs the locked Python and Console dependencies, downloads Playwright Chromium,
enables the tracked Git hooks, and applies the shared VS Code settings and extensions. It also
starts and waits for the Docker data stack: runtime and validation PostgreSQL with pgvector,
Redpanda, and ClamAV. It prompts for `sudo` in the terminal when required. It doesn't sign in to
Azure or GitHub and doesn't create tenant-specific configuration.

The installer can start the data stack during its first run by using the newly assigned Docker
group. Reopen the WSL window before running Docker commands directly so existing terminals receive
that group membership. Import `.vscode/fdai.code-profile` with `Profiles: Import Profile` because
profile import remains a user-visible VS Code action. You can verify the toolchain and healthy data
stack without changing them:

```bash
bash scripts/automation/setup-local-development.sh --check
```

Use the following sections when you need to install a prerequisite manually or diagnose a failed
check.

### Docker data stack

Install Docker Engine or Docker Desktop and Docker Compose v2. On WSL, enable the Docker Desktop
[WSL integration](https://docs.docker.com/desktop/features/wsl/) or expose another Docker Engine to
the same WSL distribution. The user that runs VS Code and FDAI should be able to run Docker without
`sudo`. The first start also needs access to the container registry for the images listed below.

Verify the exact capabilities used by the startup script:

```bash
docker version
docker compose version
docker info
```

If any command fails, follow the Docker
[installation guide](https://docs.docker.com/engine/install/) before continuing. FDAI requires the
Docker CLI, the `docker compose` v2 plugin, and a reachable daemon.

### Complete Console stack

Install these additional tools:

- Python 3.13 and `uv` for the workspace environment.
- Node.js 22 or later with `npm` for Console and Manual Studio.
- Terraform 1.9 or later and Azure CLI for deployed environment metadata.
- OPA matching `OPA_VERSION` in the [Core image](../../services/core-control-plane/docker/Dockerfile).
  Run `opa version` and `opa check policies` from the repository root. OPA must be on the VS Code
  task's `PATH`; the workspace includes `~/.local/bin` for user-installed tools.
- ShellCheck for validating repository shell scripts before commit and push.
- `git`, `bash`, `make`, `curl`, and standard Linux command-line tools.
- Tesseract with English and Korean language data. The Document Processing Worker runs on the host,
  while ClamAV runs in Docker.

On Ubuntu or WSL, install ShellCheck and Tesseract with:

```bash
sudo apt-get update
sudo apt-get install -y shellcheck tesseract-ocr tesseract-ocr-eng tesseract-ocr-kor
shellcheck --version
tesseract --list-langs
```

If you don't use the one-command installer, install the repository dependencies and hooks:

```bash
uv sync --extra dev
make hooks-install
npm --prefix console ci --no-audit --no-fund
```

The [VS Code profile setup](../../DEVELOPING.md#1-vs-code-profile-recommended) is recommended but
doesn't install Docker, Python, Node.js, OPA, Terraform, or Azure CLI.

### Verify processing readiness

Use the managed `console: start full stack` task. A frontend HTTP `200`, API liveness response,
or `pantheon_ready` log entry alone does not prove that Core consumers are running. Missing OPA
blocks Core processing; the preparation script checks for it before starting dependencies.
Check the current readiness report and a fresh Pantheon heartbeat, then verify a conversation
through the Console at `http://localhost:5273`.

Generating `resolved-models.json` does not prove that its selected deployments exist or are
reachable. Before treating model setup as complete, verify deployment names, endpoint bindings,
identity access, and capacity for the full request including system prompts and output tokens.
Do not hand-edit generated model records or remove required capabilities to bypass startup checks.
A `429`, timeout, or unavailable planner is a failed conversation check, not a successful setup.
Stop live retries and resolve the reported prerequisite; preserve network restrictions and RBAC.

## Configure authentication and local files

### Select the Azure and Terraform context

Sign in and verify the default Azure CLI profile used by the committed full-stack launchers:

```bash
az login --use-device-code
env -u AZURE_CONFIG_DIR az account show \
  --query '{subscription:name,subscriptionId:id,tenant:tenantId,user:user.name}' \
  --output table
terraform -chdir=infra output -raw resource_group_name
```

The Terraform command should return the resource group for that same subscription. A missing
output, unreadable backend, or subscription mismatch blocks complete-stack preparation. The
Docker-only path does not need this check. If the selected deployment exposes only private
endpoints, configure the optional [development VPN](../../tools/dev-access/README.md) before using
those Azure-backed readers.

#### No applied Azure deployment yet

A contributor or customer subscription with no applied FDAI Terraform state can prepare the local
Console stack with `FDAI_LOCAL_NO_AZURE_DEPLOYMENT=1` and
`FDAI_LOCAL_RESOURCE_GROUP=<existing-read-scope>` on the preparation task or script. The script
verifies that group in the active subscription and reads its region. Missing or invalid scope
stops preparation; it never invents a resource group or silently selects the entire subscription.

To reuse the same explicit scope from VS Code tasks, add both settings to the gitignored
`console/.env.local` file described below:

```dotenv
FDAI_LOCAL_NO_AZURE_DEPLOYMENT=1
FDAI_LOCAL_RESOURCE_GROUP=<existing-read-scope>
```

An explicitly exported process environment takes precedence over values in the file. Keep the
selected resource group local to the workstation and never commit it.

PostgreSQL, Redpanda, and ClamAV remain local. This option skips Terraform deployment discovery,
not authentication or authoritative-source checks, and creates no Azure resources. Existing
readers use the selected scope; unconfigured sources remain unavailable. Without an execution
gateway, managed-resource execution stays unavailable and no fake executor is selected by this
option. Sign-in still uses an existing Entra registration or the explicit Azure CLI principal mode.

### Create the Console environment

Create the gitignored `console/.env.local` with values from your Entra app registrations:

```dotenv
VITE_MSAL_CLIENT_ID=<spa-app-client-id>
VITE_MSAL_TENANT_ID=<tenant-id>
VITE_MSAL_API_SCOPE=api://<operator-api-app-client-id>/access
VITE_OPERATOR_API_BASE_URL=http://127.0.0.1:8010
VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011
```

The tenant must match the default Azure CLI profile. Follow the
[Entra app registration runbook](../runbooks/entra-app-registration.md) when the API audience,
SPA registration, delegated scope, App Roles, or local redirect URIs do not exist yet. Never commit
the populated file. Complete-stack preparation safely adds the two loopback SPA redirect URIs and
stops before service startup if the signed-in identity cannot update that app registration.

The preparation task creates `.fdai/local-runtime.env` and the service-specific
`.fdai/local-*.env` files. Treat these as generated private files and don't edit or copy them into
a deployment.

### Understand the Docker environment

The first `make dev-up` copies `infra/local/.env.example` to the gitignored `infra/local/.env`.
The canonical stack uses the committed local-only `devonly` PostgreSQL password because its local
DSNs use the same value. Don't reuse this value outside the loopback development stack.

A root `resolved-models.json` is optional. Without it, startup reports that local LLM calls and
metering are unavailable while deterministic paths continue to run. A
`resolved-models-local.json` file is not selected automatically by the full-stack task.

## Start and inspect Docker

You can start the dependencies first to verify Docker independently:

```bash
make dev-up
docker compose -f infra/local/docker-compose.yml ps
```

The complete-stack preparation task also runs `make dev-up`, so this separate step is optional.
Startup waits for every container health check and reconciles the Redpanda community configuration
and two-partition local topic default.

| Container | Image | Loopback port | Persistent volume |
|-----------|-------|---------------|-------------------|
| Runtime PostgreSQL | `pgvector/pgvector:pg16` | `5432` | `fdai-pgdata` |
| Validation PostgreSQL | `pgvector/pgvector:pg16` | `5433` | `fdai-validation-pgdata` |
| Redpanda | `redpandadata/redpanda:latest` | Kafka `19092`, admin `9644` | `fdai-redpandadata` |
| ClamAV | `clamav/clamav:stable` | `3310` | `fdai-clamavdata` |

All published container ports bind to `127.0.0.1`. The Compose project also creates the named
`fdai-local` network; containers in another Compose project must explicitly join that network.
Host Kafka clients use `127.0.0.1:19092`, while containers on `fdai-local` use
`redpanda:29092`.

## Start the complete stack

For normal development, run `Tasks: Run Task` -> `console: start full stack` in VS Code. The task
prepares dependencies, starts or reuses Docker, migrates both databases, creates service-owned
roles, materializes local projections and catalogs, generates private service environments, and
starts every service. It runs only from the primary Git checkout.

Use `Run and Debug` -> `Console Web: Full Stack` when the service processes should be owned by the
debugger. Both paths use the same preparation script. The first run can take longer because it
pulls images and installs dependencies; later runs reuse stages whose inputs and outputs have not
changed.

If preparation succeeds but the service supervisor doesn't start, run `Tasks: Run Task` ->
`console: start local services`. This visible background task reuses the prepared environments and
starts the complete service set without repeating preparation. Then run
`console: wait full stack ready`; a complete start reports `ready: 10/10` and `unavailable: none`.

| Surface | Address or readiness signal |
|---------|-----------------------------|
| Console | `http://localhost:5273` |
| Manual Studio | `http://127.0.0.1:5474` |
| Operator API | `http://127.0.0.1:8010/healthz` |
| Document Ingestion API | `http://127.0.0.1:8011` |
| Document Processing Worker | Health listener on `127.0.0.1:8012` |
| Isolated Executor | Health listener on `127.0.0.1:8013` |
| Core Runtime | Ready after a fresh Pantheon heartbeat |

Preparation registers both `http://localhost:5273` and `http://127.0.0.1:5273` as local SPA
redirects. Use `http://localhost:5273` as the standard browser origin so authentication and
session state do not split across hostnames.

In a remote WSL workspace, the VS Code integrated browser can rewrite `localhost` to
`127.0.0.1` while forwarding the remote port. This is browser forwarding behavior, not a change
to the Console server or Entra configuration. Open `http://localhost:5273` in a regular host
Chrome or Edge window when you need the canonical authentication and session origin.

Use the `console: wait full stack ready` task only as a bounded diagnostic after a successful
start. Service logs are under `.fdai/logs/`.

## Stop or reset local data

Stop the VS Code task or debug compound before stopping its Docker dependencies.

| Command | Effect |
|---------|--------|
| `make dev-down` | Stops Docker containers and preserves all four named volumes. |
| `make dev-up` | Restarts the containers with their existing data. |
| `make dev-nuke` | Stops the containers and permanently removes all four Docker volumes. |

After `make dev-nuke`, the next complete-stack preparation recreates the databases and reruns
migrations. The command does not delete `.fdai/document-store`, generated environments, or service
logs.

## Troubleshoot Docker and startup

### Docker is missing or unavailable

Run the three verification commands from the same Linux or WSL shell that runs VS Code tasks. If
`docker info` reports permission denied or cannot reach the daemon, fix daemon access for that user
instead of running the FDAI stack with `sudo`. After adding the user to the `docker` group, reopen
the WSL window or restart VS Code before running tasks so the extension host receives the new group
membership.

### A container is unhealthy

Inspect status and bounded logs without deleting data:

```bash
docker compose -f infra/local/docker-compose.yml ps
docker compose -f infra/local/docker-compose.yml logs --tail=100 \
  postgres postgres-validation redpanda clamav
```

ClamAV may need extra time on its first start while its signatures initialize. Use
`make dev-nuke` only when discarding all local database, event, and scanner state is intentional.

### A required port is already in use

The Docker ports are `5432`, `5433`, `19092`, `9644`, and `3310`. Stop the process or Compose
project that owns the conflicting loopback port; don't change FDAI ports independently because the
generated local service environments use these fixed values.

### Console preparation stops before service startup

- **Missing `console/.env.local`**: create the file from the Entra values above.
- **Entra tenant mismatch**: compare `VITE_MSAL_TENANT_ID` with
  `env -u AZURE_CONFIG_DIR az account show --query tenantId -o tsv`.
- **Terraform output failure**: initialize the intended `infra/` backend and verify its deployment
  state. Don't substitute an Azure PostgreSQL DSN or copy a state file.
- **Linked-worktree rejection**: use the primary checkout or stop the primary stack first.
- **Tesseract language failure**: confirm both `eng` and `kor` appear in `tesseract --list-langs`.

An unavailable Azure-backed panel is not automatically a Docker failure. Check the local service
health first, then verify that the selected Azure source and capability are actually deployed and
readable.

## Keep local and deployed state separate

The local services use loopback PostgreSQL and Redpanda even when Azure readers are enabled. Never
copy an Azure PostgreSQL DSN into a generated local environment, copy a local DSN into deployment
configuration, or present local records as deployed evidence. The local isolated Executor remains
a shadow consumer without a managed-resource identity.

## Next steps

| To learn about | Read |
|----------------|------|
| Detailed local checklist | [Local development setup](../../DEVELOPING.md) |
| Console authentication and service behavior | [Console local development](../../console/README.md#local-development) |
| Entra registrations and App Roles | [Entra app registration](../runbooks/entra-app-registration.md) |
| Optional private-endpoint access | [Isolated development access](../../tools/dev-access/README.md) |
| Azure subscription deployment | [Deploy quickstart](deploy-quickstart.md) |
| Contribution and verification workflow | [Contributing](../../CONTRIBUTING.md) |
