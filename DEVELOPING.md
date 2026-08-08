# Local development setup

A short, task-oriented checklist for getting a working local FDAI
environment: Azure sign-in, the optional private-network VPN, environment
variables, and how to start the local stack. For the contribution rules
(hooks, `make check`, docs-first) see
[CONTRIBUTING.md](CONTRIBUTING.md); the substantive engineering contract lives
under [.github/instructions/](.github/instructions/).

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

## 2. One-time install

```bash
uv sync --extra dev      # runtime + dev dependencies (Python 3.13)
make hooks-install       # tracked git hooks (core.hooksPath=.githooks)
npm --prefix console install
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

If you keep more than one Azure CLI profile, isolate them with
`AZURE_CONFIG_DIR` and export the same value when you start the API:

```bash
export AZURE_CONFIG_DIR="$HOME/.azure-fdai"
az login --use-device-code
```

`AZURE_CONFIG_DIR=` (empty) is not the same as unset. To force the default
profile for a single command, use `env -u AZURE_CONFIG_DIR <cmd>`.

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
upstream repo ships schema and empty defaults only. The full key reference is
in [console/README.md](console/README.md#fork-configuration). The common keys:

| Variable | Purpose |
|----------|---------|
| `VITE_MSAL_CLIENT_ID` / `VITE_MSAL_TENANT_ID` | Entra SPA app registration for browser sign-in. |
| `VITE_OPERATOR_API_BASE_URL` | Operator API origin (local default `http://127.0.0.1:8010`). |
| `VITE_LOCAL_AZURE_CLI_AUTH` | `1` projects your `az login` user through the API instead of browser Entra. Never set in production. |
| `FDAI_DATABASE_URL` | Postgres DSN; gates the `services/core-control-plane/tests/persistence/` tests and the local core runtime. |
| `AZURE_CONFIG_DIR` | Named Azure CLI profile (see section 2). Export the same value for the API. |

`resolved-models-local.json` points the local LLM and narrator path at an Azure
OpenAI endpoint. If it references an account you do not own, provision your own
with the `azure-selfprovision` skill.

## 6. Start the local stack

The canonical topology is the console SPA (`5273`), Operator API (`8010`), and
ingestion gateway (`8011`).

- VS Code (recommended): trust the workspace. Automatic workspace tasks are
  enabled in `.vscode/settings.json`, so `console: Operator API (Local Entra)`
  prepares and starts the Operator API without prompting whenever the folder opens.
  Start `console: core runtime` and
  `console: frontend (Browser Entra)` separately, or use the
  `Console Web: Full Stack` compound from Run and Debug.
- Optional dev data stack (Postgres + Redpanda) for persistence tests:

  ```bash
  make dev-up
  export FDAI_DATABASE_URL=postgresql://fdai:fdai@localhost:5432/fdai
  make dev-down            # stop (volumes preserved)
  ```

Manual equivalents for each service are documented in
[console/README.md](console/README.md#local-development).

## 7. Verify before you push

```bash
make check               # lint + gates + test + operator (CI parity)
```

See [CONTRIBUTING.md](CONTRIBUTING.md#everyday-workflow) for the per-target
breakdown.
