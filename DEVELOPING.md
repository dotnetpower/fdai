# Local development setup

A short, task-oriented checklist for running FDAI locally right after cloning: Pure-Rust Console
Web (`fdai-console-v4` on `5290`), Release Hub (`fdai-release-hub` on `8022`), Lifecycle Hub
(`fdai-hub` on `8021`), the 9-service Pure-Rust stack, optional Docker data services, and optional
Azure sign-in. For contribution rules (hooks, `make check`, docs-first), see
[CONTRIBUTING.md](CONTRIBUTING.md); the substantive engineering contract lives under
[.github/instructions/](.github/instructions/). For a step-by-step walkthrough with port tables
and troubleshooting, see the bilingual
[Local Development Quickstart](docs/user-guide/local-development-quickstart.md).

## 1. Quick start after cloning (Console Web & Release Hub)

Only the Rust stable toolchain (`rustup` / `cargo`), `git`, `bash`, `make`, and `curl` are
required to launch Console Web and Release Hub locally. Python, Node.js, and Azure sign-in are
not required for standalone loopback runs.

```bash
# 1. Install Rust stable if cargo is not yet installed
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
source "$HOME/.cargo/env"

# 2. Run Console Web (Pure-Rust Console v4) -> http://127.0.0.1:5290
make console-v4-up

# 3. Run Release Hub (Pure-Rust server + prebuilt UI) -> http://127.0.0.1:8022
make release-hub-up

# 4. Run Lifecycle Hub (Pure-Rust server + prebuilt UI) -> http://127.0.0.1:8021
make lifecycle-hub-up

# 5. Or build and start all 9 Pure-Rust services together in one command
make rust-fullstack-up
make rust-fullstack-down
```

Verify readiness from another terminal:

```bash
cargo run --locked -p fdai-console-v4 -- --check
curl -sS http://127.0.0.1:5290/api/v4/meta

cargo run --locked -p fdai-release-hub -- --check
curl -sS http://127.0.0.1:8022/healthz
curl -sS http://127.0.0.1:8022/auth/config
```

Fresh clones use `CARGO_FLAGS ?= --locked` so Cargo downloads exact `Cargo.lock` crate versions on
first run. For offline/air-gapped workstations with a warm Cargo cache, run
`CARGO_FLAGS="--locked --offline" make <target>` or set `FDAI_CARGO_OFFLINE=1` for
`make rust-fullstack-up`.

## 2. VS Code Profile and tasks (recommended)

FDAI ships a portable Settings and Extensions profile at
[`.vscode/fdai.code-profile`](.vscode/fdai.code-profile). Import it with
`Profiles: Import Profile`, create or replace `FDAI`, and switch to it with
`Profiles: Switch Profile`. The profile excludes personal keybindings, themes,
snippets, MCP servers, UI state, and language models.

In VS Code, run **Tasks: Run Task** to launch Pure-Rust services without remembering flags:

- `console-v4: serve (5290)` - Pure-Rust Console Web on `http://127.0.0.1:5290`
- `release-hub: serve (8022)` - Pure-Rust Release Hub + UI on `http://127.0.0.1:8022`
- `lifecycle-hub: serve (8021)` - Pure-Rust Lifecycle Hub + UI on `http://127.0.0.1:8021`
- `fullstack: start Pure-Rust stack` / `fullstack: stop Pure-Rust stack` - all 9 Axum services

Enable the tracked Git hooks once per clone (VS Code also runs `hooks: install` on folder open):

```bash
make hooks-install
```

## 3. Optional local services (Docker DB, SPA UI editing)

### Docker data stack (PostgreSQL + Redpanda + ClamAV)

Start Docker dependencies when you want live local PostgreSQL backing `fdai-console-v4` or want to
run persistence tests. Verify Docker Engine and Compose v2 run without `sudo`:

```bash
docker version
docker compose version
docker info
make dev-up
```

`make dev-up` starts runtime PostgreSQL (`127.0.0.1:5432`), validation PostgreSQL
(`127.0.0.1:5433`), Redpanda (`127.0.0.1:19092`, admin `9644`), and ClamAV (`127.0.0.1:3310`).
Use `make dev-down` to stop containers while preserving volumes, or `make dev-nuke` to drop all
four local volumes.

### Optional Node.js 22+ for SPA source editing

Pre-built static UI bundles are tracked at `lifecycle_rs/release-hub/ui/dist` and
`lifecycle_rs/hub/ui/dist`, and `console_rs/` embeds its own HTML templates and assets. Install
Node.js 22+ only when editing UI source files:

```bash
# Rebuild Release Hub UI bundle served by fdai-release-hub (:8022)
npm --prefix lifecycle_rs/release-hub/ui ci
npm --prefix lifecycle_rs/release-hub/ui run build

# Optional Release Hub Vite HMR (5291 -> proxies to Release Hub on 8091)
cargo run --locked -p fdai-release-hub -- --host 127.0.0.1 --port 8091
npm --prefix lifecycle_rs/release-hub/ui run dev

# Optional legacy Console SPA (console/, port 5273)
npm --prefix console ci --no-audit --no-fund
npm --prefix console run dev
```

## 4. Optional Azure sign-in (`az login`) and VPN

Azure sign-in is only needed for Azure-backed readers, Entra authentication, or cloud deployment.
Confirm the active account and tenant before enabling Azure bindings:

```bash
az login --use-device-code
az account show \
  --query '{subscription:name,user:user.name,tenant:tenantId}' \
  --output table
```

For private-endpoint access (Key Vault, Azure PostgreSQL, Storage, Azure OpenAI with public access
disabled), configure the optional VPN documented in [tools/dev-access/README.md](tools/dev-access/README.md).
Unit tests and standalone loopback Console Web / Release Hub runs do not require VPN access.

## 5. Environment variables

Common local environment variables for Console Web, Release Hub, and the full stack:

| Variable | Default | Purpose |
|----------|---------|---------|
| `FDAI_CONSOLE_V4_HOST` / `FDAI_CONSOLE_V4_PORT` | `127.0.0.1` / `5290` | Bind address and port for `fdai-console-v4` (`FDAI_CONSOLE_PORT` in `start-fullstack-rust.sh`). |
| `FDAI_OPERATOR_URL` | `http://127.0.0.1:8010` | Upstream Operator API URL proxied by `fdai-console-v4`. |
| `FDAI_DATABASE_URL` | unset (or loopback `.fdai/local-runtime.env`) | Loopback PostgreSQL DSN for live Console v4 DB queries. Never point local services at Azure PostgreSQL. |
| `FDAI_CONSOLE_V4_ALLOW_DB_WRITES` | `0` | Opt-in flag (`1`) for local loopback write endpoints in Console v4. |
| `FDAI_RELEASE_HUB_PORT` | `8022` | Listening port for `fdai-release-hub`. |
| `FDAI_RELEASE_HUB_STATE_PATH` | `.fdai/release-hub-state.json` | Local JSON state store for Release Hub. |
| `FDAI_LIFECYCLE_HUB_PORT` | `8021` | Listening port for `fdai-hub`. |
| `FDAI_CARGO_OFFLINE` | `0` | Set `1` to pass `--offline` in `deploy_rs/start-fullstack-rust.sh`. |

For optional Browser Entra sign-in against Operator API (`8010`), create the git-ignored
`console/.env.local` using values from the
[Entra app registration runbook](docs/runbooks/entra-app-registration.md#4-map-ids-to-configuration)
(`VITE_MSAL_CLIENT_ID`, `VITE_MSAL_TENANT_ID`, `VITE_MSAL_API_SCOPE`,
`VITE_OPERATOR_API_BASE_URL`, `VITE_INGESTION_API_BASE_URL`). When present,
`deploy_rs/start-fullstack-rust.sh` loads the tenant and audience automatically.

## 6. Verify before you push

```bash
make lint                # cargo check --workspace --locked
make gates               # fdai-xtask verify + check-migrations + check-hygiene
make test                # cargo test --workspace --locked
make check               # lint + gates + test
```

See [CONTRIBUTING.md](CONTRIBUTING.md#everyday-workflow) for the full target reference and
[docs/user-guide/local-development-quickstart.md](docs/user-guide/local-development-quickstart.md)
for troubleshooting. Legacy Python tooling has been archived under `_archive/python/`.
