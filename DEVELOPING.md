# Local development setup

A short, task-oriented checklist for getting a working local FDAI
environment: Azure sign-in, the optional private-network VPN, environment
variables, and how to start the local stack. For the contribution rules
(hooks, `make check`, docs-first) see
[CONTRIBUTING.md](CONTRIBUTING.md); the substantive engineering contract lives
under [.github/instructions/](.github/instructions/). For a Docker-first walkthrough with a
component and port inventory, persistence behavior, and troubleshooting, see the bilingual
[Local Development Quickstart](docs/user-guide/local-development-quickstart.md).

## 1. VS Code Profile (recommended)

FDAI ships a portable Settings and Extensions profile at
[`.vscode/fdai.code-profile`](.vscode/fdai.code-profile). Import it with
`Profiles: Import Profile`, create or replace `FDAI`, and switch to it with
`Profiles: Switch Profile`. The profile excludes personal keybindings, themes,
snippets, MCP servers, UI state, and language models.

VS Code does not synchronize extensions or machine settings into WSL, SSH, or
dev-container windows. In a WSL FDAI terminal, apply and verify the shared
remote settings:

```bash
python3 scripts/automation/configure-vscode-profile.py \
  --apply-machine-settings --check-machine-settings
```

The command validates the profile and extension lists before writing, preserves
unrelated JSON settings, and is safe to repeat. It stops without writing when an
existing settings file contains JSONC comments. You can also ask GitHub Copilot
to run `/setup-vscode-profile` or say "set up the FDAI VS Code Profile".

New integrated terminals disable interactive command pagers through the workspace settings. This
keeps Git, GitHub CLI, PostgreSQL, and systemd output in the terminal instead of leaving a hidden
`less` session that can interpret later shell commands as save-file names.

## 2. One-time install

On x86_64 Ubuntu or WSL, run the repository installer from the repository root:

```bash
bash scripts/automation/setup-local-development.sh
```

The script installs the system packages and pinned user tools, configures Docker access, installs
the locked Python and Console dependencies, downloads Playwright Chromium, enables the tracked Git
hooks, and applies the shared VS Code machine settings and extensions. It prompts for `sudo` in the
terminal when needed. It never signs in to Azure or GitHub and never creates tenant-specific files.

Reopen the WSL window after the first run so existing terminals receive Docker group membership.
In VS Code, import `.vscode/fdai.code-profile` with `Profiles: Import Profile`; profile import remains
a user-visible editor action. Verify the complete workstation setup at any time:

```bash
bash scripts/automation/setup-local-development.sh --check
```

The commands below are the manual equivalent and remain useful for troubleshooting.

FDAI development commands use ripgrep (`rg`) for fast repository searches. The one-time installer
installs it automatically. For a manual Ubuntu or WSL setup, install and verify it with:

```bash
sudo apt-get update
sudo apt-get install -y ripgrep
rg --version
```

The local full stack runs the Document Processing Worker on the host. On Ubuntu
or WSL, install Tesseract OCR and its English and Korean language data:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng tesseract-ocr-kor
tesseract --list-langs
```

`pytesseract`, installed by `uv sync`, is only the Python wrapper. The
Document Processing Worker container image installs the equivalent Alpine
packages separately, so you can skip the host packages when you run the worker
only as a container.

The complete local stack also requires the Docker CLI, a reachable Docker daemon, and Docker
Compose v2. The VS Code profile does not install them. Confirm that the same user and Linux or WSL
shell that runs VS Code tasks can execute these commands without `sudo`:

```bash
docker version
docker compose version
docker info
```

See the [Docker setup and troubleshooting steps](docs/user-guide/local-development-quickstart.md#install-the-prerequisites)
if any check fails.

Install OPA using the version pinned by the Core image and confirm `opa check policies` succeeds.
OPA must be on the VS Code task's `PATH`, not just an interactive shell's path. The workspace
includes `~/.local/bin` for user-installed tools. Without OPA, Core readiness blocks consumers
even when the HTTP APIs are listening. See the [startup verification guidance](docs/user-guide/local-development-quickstart.md#verify-processing-readiness).

```bash
uv sync --extra dev      # runtime + dev dependencies (Python 3.13)
make hooks-install       # tracked git hooks (core.hooksPath=.githooks)
npm --prefix console ci --no-audit --no-fund
```

## 3. Azure sign-in (`az login`)

The local Operator API and Azure adapters reuse your interactive Azure CLI
session. Sign in and confirm the active account before anything else, because
a wrong subscription or tenant is the most common source of confusing errors.

```bash
az login --use-device-code
az account show \
  --query '{subscription:name,user:user.name,tenant:tenantId}' \
  --output table
```

For a manual Operator API start, you can isolate a named Azure CLI profile with
`AZURE_CONFIG_DIR` and export the same value when you start that process:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-fdai"
az login --use-device-code
```

`AZURE_CONFIG_DIR=` (empty) is not the same as unset. To force the default
profile for a single command, use `env -u AZURE_CONFIG_DIR <cmd>`.
The committed full-stack preparation and service launchers intentionally use that default profile,
so confirm `env -u AZURE_CONFIG_DIR az account show` before using the standard VS Code task.

## 4. VPN for private endpoints (optional)

Only needed when you must reach FDAI private services (Key Vault, PostgreSQL,
Storage, Azure OpenAI) that have public network access disabled. Unit tests
and the deterministic console path do not require it.

- Full setup, WSL DNS, and the P2S profile: [tools/dev-access/README.md](tools/dev-access/README.md).
- When VS Code opens this workspace, the `dev-access: configure VPN on folder open`
  task runs automatically. Without local `tools/dev-access/infra/terraform.tfstate`
  it is a quiet no-op, so other contributors are unaffected.
- After connecting Azure VPN Client, if WSL DNS is not applied automatically:

  ```bash
  tools/dev-access/scripts/wsl-dns.sh apply     # revert before disconnecting
  ```

- Verify reachability (pass real hostnames at runtime; never commit them):

  ```bash
  tools/dev-access/scripts/doctor.sh <private-vault-host> <private-postgres-host>:5432
  ```

## 5. Environment variables

Local runtime values are read from `console/.env.local` (git-ignored: it holds
your MSAL client and tenant ids and API base URLs). It is never committed; the
upstream repo does not generate this file. Create it from the values produced by the
[Entra app registration runbook](docs/runbooks/entra-app-registration.md#4-map-ids-to-configuration).
The full key reference is in [console/README.md](console/README.md#fork-configuration). The common
keys are:

| Variable | Purpose |
|----------|---------|
| `VITE_MSAL_CLIENT_ID` / `VITE_MSAL_TENANT_ID` | Entra SPA app registration for browser sign-in. |
| `VITE_MSAL_API_SCOPE` | Delegated Operator API scope in `api://<audience>/<scope>` form. |
| `VITE_OPERATOR_API_BASE_URL` | Operator API origin (local default `http://127.0.0.1:8010`). |
| `VITE_LOCAL_AZURE_CLI_AUTH` / `VITE_LOCAL_AZURE_CLI_AUTH_CONFIRM` | Launcher-owned CLI-debug pair. Don't persist either value in `console/.env.local`; use the explicit CLI-debug task or `--auth-mode azure-cli`. |
| `FDAI_DATABASE_URL` | Postgres DSN; gates the `services/core-control-plane/tests/persistence/` tests and the local core runtime. |
| `AZURE_CONFIG_DIR` | Named Azure CLI profile (see section 2). Export the same value for the API. |

The full-stack task reads root `resolved-models.json` when present. Without it, local LLM calls and
metering remain unavailable while deterministic paths continue to work. A
`resolved-models-local.json` file is not selected automatically; direct preparation can select an
absolute path with `FDAI_LOCAL_RESOLVED_MODELS_PATH`. If an artifact references an account you do
not own, provision your own with the `azure-selfprovision` skill.

To restore an explicitly selected existing direct account, use
`scripts/deployment/local/bind-existing-model.py --artifact resolved-models.json --evidence <readback.json> --family <primary-family> --restore-account <account-name>`.
The readback contains `observed_at`, `account`, and `deployments` from Azure management queries
and must be less than five minutes old. The tool checks the subscription, account, deployment
identities, model versions, and capacities; preserves capability membership and review holds;
and backs up the prior ignored artifact. Reviewed endpoint policies require their owning workflow
instead. Regenerate local service environments after binding to refresh their model digests.
This verifies configuration, not network reachability or model inference. Keep
`FDAI_NARRATOR_AUTO_OPEN_AOAI=0` in the private Console environment when reusing a restricted account.

## 6. Start the local stack

The canonical topology is the console SPA (`5273`) plus all five independent backend services:
Core Control Plane, Operator API (`8010`), Document Ingestion API (`8011`), Document Processing
Worker (`8012` health), and isolated Executor (`8013` health).

The complete stack combines local Docker state with Azure-backed readers. Before starting it,
select the intended Azure read scope with `FDAI_LOCAL_RESOURCE_GROUP=<existing-read-scope>` and
make sure the default `az` profile uses that group's subscription and the tenant recorded in
`console/.env.local`. Local Console preparation never initializes or reads Terraform state. The
Docker-only path below has no Azure dependency. See
[Choose a local path](docs/user-guide/local-development-quickstart.md#choose-a-local-path) for the
boundary, including the isolated state retained by the public contributor deployment.

The preparation task reads that setting from the process environment or the gitignored
`console/.env.local`; after one successful run it may reuse the prior private local-runtime scope.
The selected group is verified in the active subscription, and no placeholder scope or default
region is invented. PostgreSQL and Redpanda remain local. A unique development operations gateway
may be discovered through Azure CLI, and its audience is derived from the validated private
`VITE_MSAL_API_SCOPE`. The local Console receives no executor identity and
cannot promote an ActionType. Actual Azure changes still require the deployed Executor, durable
promotion evidence, applicable human approval, dry-run, rollback, audit, and independent effect
verification. See [Select the Azure read scope](docs/user-guide/local-development-quickstart.md#select-the-azure-read-scope).

- VS Code (recommended): trust the workspace, then run the `console: start full stack` task for
  managed service reuse or the `Console Web: Full Stack` compound when you need debugger-owned
  processes. Both paths restore Docker PostgreSQL, Redpanda, and ClamAV, run only invalidated
  dependency, migration, environment, projection, inventory, and Entra preparation stages, and
  start every service plus the SPA. The start task returns only after the supervisor reports
  `ready` or `failed`; every preparation command and readiness check has a bounded deadline. Use
  `console: wait full stack ready` only for a ten-second diagnostic after a successful start. Use
  `bash scripts/deployment/local/prepare-console-full-stack.sh --force` to refresh every stage.
  These standard paths always use Browser Entra. For a bounded authentication diagnostic only,
  run `console: start full stack (Azure CLI debug, Contributor)`. That mode cannot open approval
  details that require `Approver` or `Owner`.
- Terminal launchers: run each long-lived server in its own terminal. The Console command prepares
  and starts the same complete stack as the VS Code task. The design command starts the independent
  static mock server on `http://127.0.0.1:5373`.

  ```bash
  ./scripts/deployment/local/start-console-web.sh
  ./scripts/deployment/local/start-console-web.sh --auth-mode azure-cli  # CLI debug only
  ./scripts/deployment/local/start-design-mocks.sh
  ```

  Pass `--force` to `start-console-web.sh` only when every preparation stage must be refreshed.
  Omitting `--auth-mode` always selects Browser Entra. The Azure CLI alternative has a fixed
  `Contributor` ceiling and is not a way to test approval authority.
  If a standard port is owned outside the managed launcher, the Console script exits before
  preparation and leaves that process untouched. Stop the matching VS Code debug configuration
  or other owning process, then retry.
- Optional Docker data stack for persistence tests and Docker verification. It starts runtime and
  validation PostgreSQL, Redpanda, and ClamAV:

  ```bash
  make dev-up
  export FDAI_DATABASE_URL=postgresql://fdai:fdai@localhost:5432/fdai
  make dev-down            # stop (volumes preserved)
  ```

  `make dev-nuke` stops those containers and permanently deletes all four named Docker volumes.
  It does not delete `.fdai/document-store` or service logs. The full
  [Docker component and lifecycle reference](docs/user-guide/local-development-quickstart.md#start-and-inspect-docker)
  lists the fixed loopback ports and recovery checks.

  Local startup also retires empty introspection consumer groups whose owning process no longer
  exists. It rechecks group membership and process liveness before each deletion and preserves
  active groups, startup probes, messages, dead letters, and database records. To preview this
  bounded cleanup separately, run `python3 scripts/deployment/local/cleanup-local-broker.py`;
  add `--apply` to retire the verified groups. Remote Docker endpoints are rejected. Unavailable
  cleanup leaves retained groups alone and does not prevent startup.
  Readiness round trips use `fdai.startup.probes`, never the operational dead-letter topic.
  Preparation reconciles this disposable topic to delete retention of one hour or 1 MiB per
  partition, with ten-minute segment rolling. These are broker retention targets, not a
  synchronous size limit. Existing runtimes adopt the new topic on their next managed restart.

Manual equivalents for each service are documented in
[console/README.md](console/README.md#local-development).

## 7. Verify before you push

```bash
make check               # lint + gates + test + operator (CI parity)
```

See [CONTRIBUTING.md](CONTRIBUTING.md#everyday-workflow) for the per-target
breakdown.
