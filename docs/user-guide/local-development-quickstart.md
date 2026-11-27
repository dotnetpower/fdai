---
title: Local Development Quickstart
description: Learn how to run FDAI Console Web, Release Hub, the 9-service Pure-Rust local stack, and the optional Docker data stack after cloning the repository.
---

# Local Development Quickstart

After cloning FDAI, you can launch the Pure-Rust **Console Web** (`fdai-console-v4` on port
`5290`), **Release Hub** (`fdai-release-hub` on port `8022`), or the complete 9-service Pure-Rust
stack with only the Rust stable toolchain and `make`. Docker is optional for live PostgreSQL,
Redpanda, and ClamAV bindings, and Node.js is only required when editing SPA source files.

## Choose a local path

| Path | Command | Browser / health URL | External prerequisites |
|------|---------|----------------------|------------------------|
| Console Web standalone | `make console-v4-up` | `http://127.0.0.1:5290` | Rust stable (`cargo`), `make` |
| Release Hub standalone | `make release-hub-up` | `http://127.0.0.1:8022` | Rust stable (`cargo`), `make` |
| Lifecycle Hub standalone | `make lifecycle-hub-up` | `http://127.0.0.1:8021` | Rust stable (`cargo`), `make` |
| Complete Pure-Rust stack (9 services) | `make rust-fullstack-up` | Console `5290`, Release Hub `8022`, Lifecycle Hub `8021`, Operator API `8010` | Rust stable (`cargo`), `make` |
| Docker data stack | `make dev-up` | PostgreSQL `5432` / `5433`, Redpanda `19092`, ClamAV `3310` | Docker Engine + Compose v2 |
| Optional SPA UI live-reload dev | `npm --prefix console run dev` or `npm --prefix lifecycle_rs/release-hub/ui run dev` | Console SPA `5273`, Release Hub UI `5291` | Node.js 22+ and `npm` |

Console Web (`fdai-console-v4`) and Release Hub (`fdai-release-hub`) start cleanly on loopback
without Azure sign-in, Entra app registrations, or Python. When PostgreSQL or upstream Azure
sources are unconfigured, Console Web shows honest `not-measured` or offline states instead of
fabricating runtime data.

## Install the prerequisites

### Required for Console Web and Release Hub

1. **Git and Make**: `git`, `bash`, `make`, and `curl`.
2. **Rust stable toolchain**: install via [rustup](https://rustup.rs/) if `cargo` is not on your
   `PATH`:

   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain stable
   source "$HOME/.cargo/env"
   rustc --version
   cargo --version
   ```

3. **Optional tracked Git hooks** (recommended if you plan to commit changes):

   ```bash
   make hooks-install
   ```

Fresh clones use `cargo ... --locked` by default so Cargo fetches the exact crate versions pinned
in `Cargo.lock` once and reuses the local cache on later runs. In an air-gapped environment with a
populated Cargo cache, pass `CARGO_FLAGS="--locked --offline"` to `make` or set
`FDAI_CARGO_OFFLINE=1` before running `make rust-fullstack-up`.

### Optional: Docker data stack

Install Docker Engine or Docker Desktop with Docker Compose v2 when you want live loopback
PostgreSQL backing Console Web, Redpanda event transport, or ClamAV document scanning. On WSL,
enable Docker Desktop [WSL integration](https://docs.docker.com/desktop/features/wsl/) and verify
that your shell can run Docker without `sudo`:

```bash
docker version
docker compose version
docker info
```

### Optional: Node.js 22+ for SPA source editing

Pre-built Release Hub UI assets (`lifecycle_rs/release-hub/ui/dist`) and Lifecycle Hub UI assets
(`lifecycle_rs/hub/ui/dist`) are tracked in the repository, and Console v4 (`console_rs/`) serves
its templates and assets directly from the Rust binary. Install Node.js 22 or later only when you
modify TypeScript or Preact UI sources under `console/`, `lifecycle_rs/release-hub/ui/`, or
`lifecycle_rs/hub/ui/`.

## Run Console Web (`http://127.0.0.1:5290`)

From the repository root, start the standalone Pure-Rust Console v4 server:

```bash
make console-v4-up
```

Equivalent direct Cargo command:

```bash
cargo run --locked -p fdai-console-v4 -- --host 127.0.0.1 --port 5290
```

Open `http://127.0.0.1:5290` in your browser, or verify readiness from another terminal:

```bash
cargo run --locked -p fdai-console-v4 -- --check
curl -sS http://127.0.0.1:5290/api/v4/meta
```

### Console Web options and live PostgreSQL binding

- **Custom host or port**: pass `--host` / `--port` or set `FDAI_CONSOLE_V4_HOST` and
  `FDAI_CONSOLE_V4_PORT`.
- **Live local PostgreSQL binding**: start Docker with `make dev-up` and export
  `FDAI_DATABASE_URL` (or let `fdai-console-v4` automatically read a loopback `FDAI_DATABASE_URL`
  from `.fdai/local-runtime.env`). Set `FDAI_CONSOLE_V4_ALLOW_DB_WRITES=1` only when you
  explicitly want local loopback write endpoints enabled.
- **Operator API upstream proxy**: `fdai-console-v4` proxies operator routes to
  `FDAI_OPERATOR_URL` (default `http://127.0.0.1:8010`).

## Run Release Hub (`http://127.0.0.1:8022`)

From the repository root, start the Pure-Rust Release Hub server with its pre-built UI:

```bash
make release-hub-up
```

Equivalent direct Cargo command:

```bash
cargo run --locked -p fdai-release-hub -- \
  --host 127.0.0.1 \
  --port 8022 \
  --static-dir lifecycle_rs/release-hub/ui/dist
```

Open `http://127.0.0.1:8022` in your browser, or verify readiness from another terminal:

```bash
cargo run --locked -p fdai-release-hub -- --check
curl -sS http://127.0.0.1:8022/healthz
curl -sS http://127.0.0.1:8022/auth/config
```

### Release Hub options and UI development

- **Local profile and state**: when Entra environment variables are unset, Release Hub starts in
  loopback `local-development` mode (`{"profile":"local-development"}`) and persists state to
  `.fdai/release-hub-state.json` by default. Override the file path with
  `FDAI_RELEASE_HUB_STATE_PATH` and the port with `FDAI_RELEASE_HUB_PORT` or `--port`.
- **Rebuilding the Release Hub UI after frontend edits**:

  ```bash
  npm --prefix lifecycle_rs/release-hub/ui ci
  npm --prefix lifecycle_rs/release-hub/ui run build
  ```

- **Live-reload UI dev server**: Vite in `lifecycle_rs/release-hub/ui/vite.config.ts` serves on
  `http://127.0.0.1:5291` and proxies `/v1`, `/healthz`, and `/auth` to `http://127.0.0.1:8091`.
  To use Vite HMR, run Release Hub on port `8091` in one terminal and Vite in another:

  ```bash
  cargo run --locked -p fdai-release-hub -- --host 127.0.0.1 --port 8091
  npm --prefix lifecycle_rs/release-hub/ui run dev
  ```

- **Lifecycle Hub**: run `make lifecycle-hub-up` to launch `fdai-hub` on `http://127.0.0.1:8021`.
  See [lifecycle_rs/release-hub/README.md](../../lifecycle_rs/release-hub/README.md) and
  [Hub lifecycle operator guide](../runbooks/hub-lifecycle-operator-guide.md) for catalog trust
  and operator boundaries.

## Run all 9 Pure-Rust services together

To start Console Web, Release Hub, Lifecycle Hub, and all six core Pure-Rust Axum services with
one command, run:

```bash
make rust-fullstack-up
```

This runs [`deploy_rs/start-fullstack-rust.sh`](../../deploy_rs/start-fullstack-rust.sh), builds
all nine binaries, starts them in the background, verifies every health endpoint, and writes logs
to `.fdai/logs/<service>.log` and PIDs to `.fdai/rust-fullstack.pids`. Stop the stack with:

```bash
make rust-fullstack-down
```

| Service | Default address | Health / metadata endpoint |
|---------|-----------------|----------------------------|
| Console Web (`fdai-console-v4`) | `http://127.0.0.1:5290` | `http://127.0.0.1:5290/api/v4/meta` |
| Release Hub (`fdai-release-hub`) | `http://127.0.0.1:8022` | `http://127.0.0.1:8022/healthz` |
| Lifecycle Hub (`fdai-hub`) | `http://127.0.0.1:8021` | `http://127.0.0.1:8021/healthz` |
| Operator API (`fdai-operator-service`) | `http://127.0.0.1:8010` | `http://127.0.0.1:8010/healthz` |
| Document Ingestion API | `http://127.0.0.1:8011` | `http://127.0.0.1:8011/healthz` |
| Document Processing Worker | `http://127.0.0.1:8012` | `http://127.0.0.1:8012/healthz` |
| Isolated Executor | `http://127.0.0.1:8013` | `http://127.0.0.1:8013/healthz` |
| Core Control Plane | `http://127.0.0.1:8014` | `http://127.0.0.1:8014/healthz` |
| System Knowledge Service | `http://127.0.0.1:8016` | `http://127.0.0.1:8016/healthz` |

In VS Code, you can also open **Tasks: Run Task** and choose `console-v4: serve (5290)`,
`release-hub: serve (8022)`, `lifecycle-hub: serve (8021)`, `fullstack: start Pure-Rust stack`,
or `fullstack: stop Pure-Rust stack`.

## Start and inspect the optional Docker data stack

Start PostgreSQL, Redpanda, and ClamAV when you want live local database tables or integration
tests:

```bash
make dev-up
docker compose -f infra/local/docker-compose.yml ps
```

The first `make dev-up` copies `infra/local/.env.example` to the git-ignored `infra/local/.env`
(using the local-only `devonly` password) and waits for every container health check.

| Container | Image | Loopback port | Persistent volume |
|-----------|-------|---------------|-------------------|
| Runtime PostgreSQL | `pgvector/pgvector:pg16` | `5432` | `fdai-pgdata` |
| Validation PostgreSQL | `pgvector/pgvector:pg16` | `5433` | `fdai-validation-pgdata` |
| Redpanda | `redpandadata/redpanda:v26.2.2` (digest pinned) | Kafka `19092`, admin `9644` | `fdai-redpandadata` |
| ClamAV | `clamav/clamav:stable` | `3310` | `fdai-clamavdata` |

All published container ports bind to `127.0.0.1`. Host Kafka clients use `127.0.0.1:19092`, while
containers on the `fdai-local` Docker network use `redpanda:29092`.

### Stop or reset Docker data

| Command | Effect |
|---------|--------|
| `make dev-down` | Stops the Docker containers and preserves all four named volumes. |
| `make dev-up` | Restarts the containers with their existing data. |
| `make dev-nuke` | Stops the containers and permanently removes all four Docker volumes. |

## Optional: Azure, Entra, and legacy SPA setup

When you want authenticated Browser Entra sign-in or Azure-backed readers against a real Azure
subscription, configure `az login --use-device-code` and create the git-ignored `console/.env.local`
with values from the [Entra app registration runbook](../runbooks/entra-app-registration.md):

```dotenv
VITE_MSAL_CLIENT_ID=<spa-app-client-id>
VITE_MSAL_TENANT_ID=<tenant-id>
VITE_MSAL_API_SCOPE=api://<operator-api-app-client-id>/access
VITE_OPERATOR_API_BASE_URL=http://127.0.0.1:8010
VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011
```

If `deploy_rs/start-fullstack-rust.sh` finds `.fdai/local-operator-service.env` or
`console/.env.local`, it automatically loads the matching Entra tenant and audience settings for
the local Operator API. To develop the legacy Preact SPA (`console/`, port `5273`), install
dependencies with `npm --prefix console ci --no-audit --no-fund` and run
`npm --prefix console run dev`.

## Troubleshoot startup

### `cargo` not found or offline cache error

- Install the Rust stable toolchain via `rustup` and add `$HOME/.cargo/bin` to your `PATH`.
- On a fresh clone, use the default `--locked` build (`make console-v4-up`, `make release-hub-up`,
  or `make rust-fullstack-up`). Avoid passing `--offline` until Cargo has downloaded the workspace
  crates once.

### A required port is already in use

- Default Pure-Rust service ports are `5290` (Console Web), `8022` (Release Hub), `8021`
  (Lifecycle Hub), and `8010`-`8016` (Core and Operator services).
- Stop a previous full-stack run with `make rust-fullstack-down`, or override ports with
  `FDAI_CONSOLE_PORT`, `FDAI_RELEASE_HUB_PORT`, `FDAI_LIFECYCLE_HUB_PORT`, or `--port`.
- Docker ports are fixed at `5432`, `5433`, `19092`, `9644`, and `3310`. Stop the conflicting
  process rather than changing the Compose ports.

### Docker is missing or a container is unhealthy

- Run `docker version`, `docker compose version`, and `docker info` from the same shell without
  `sudo`. After adding your user to the `docker` group, reopen your WSL window or restart VS Code.
- Inspect container logs without deleting data:

  ```bash
  docker compose -f infra/local/docker-compose.yml ps
  docker compose -f infra/local/docker-compose.yml logs --tail=100 \
    postgres postgres-validation redpanda clamav
  ```

## Keep local and deployed state separate

Local services use loopback PostgreSQL (`127.0.0.1:5432`) and local state files under `.fdai/`
even when Azure readers are enabled. Never copy an Azure PostgreSQL DSN into a local environment
file, copy a local DSN into deployment configuration, or present local records as deployed
evidence.

## Next steps

| To learn about | Read |
|----------------|------|
| Detailed local checklist and verification commands | [Local development setup](../../DEVELOPING.md) |
| Release Hub local startup, routes, and UI | [Release Hub README](../../lifecycle_rs/release-hub/README.md) |
| Console SPA architecture and local auth behavior | [Console README](../../console/README.md) |
| Entra registrations and App Roles | [Entra app registration](../runbooks/entra-app-registration.md) |
| Optional private-endpoint VPN access | [Isolated development access](../../tools/dev-access/README.md) |
| Azure subscription deployment | [Deploy quickstart](deploy-quickstart.md) |
| Contribution and verification workflow | [Contributing](../../CONTRIBUTING.md) |
