# FDAI Release Hub (`lifecycle_rs/release-hub`)

Pure-Rust Axum server for the FDAI Release Hub (`fdai-release-hub`). It manages release manifests,
Ed25519 signatures, TUF metadata, channel curation (`DEV`, `RELEASE_CANDIDATE`, `RELEASE`),
capability recalls, Stencil definitions, and OCI v2 manifest endpoints, and serves the pre-built
Release Hub UI from `lifecycle_rs/release-hub/ui/dist`.

## Running locally

From the repository root, only the Rust stable toolchain (`cargo`) and `make` are required:

```bash
# Recommended Make target -> http://127.0.0.1:8022
make release-hub-up

# Or run directly with Cargo
cargo run --locked -p fdai-release-hub -- \
  --host 127.0.0.1 \
  --port 8022 \
  --static-dir lifecycle_rs/release-hub/ui/dist
```

Verify readiness from another terminal:

```bash
cargo run --locked -p fdai-release-hub -- --check
curl -sS http://127.0.0.1:8022/healthz
curl -sS http://127.0.0.1:8022/auth/config
```

In VS Code, run **Tasks: Run Task** -> `release-hub: serve (8022)`, or launch the full 9-service
Pure-Rust stack with `make rust-fullstack-up`.

## Configuration

| Flag or environment variable | Default | Purpose |
|------------------------------|---------|---------|
| `--host` / `FDAI_RELEASE_HUB_HOST` | `127.0.0.1` | Bind address (loopback by default). |
| `--port` / `FDAI_RELEASE_HUB_PORT` | `8022` | HTTP listening port. |
| `--static-dir` / `FDAI_RELEASE_HUB_STATIC_DIR` | auto-detected `lifecycle_rs/release-hub/ui/dist` | Static UI bundle directory. |
| `FDAI_RELEASE_HUB_STATE_PATH` | `.fdai/release-hub-state.json` | Local JSON state store path. |
| `FDAI_ENTRA_TENANT_ID` / `FDAI_RELEASE_HUB_REMOTE_ORIGIN` | unset (`local-development`) | Enables remote-development Entra authentication when configured. |

When Entra variables are unset, Release Hub binds to loopback and responds with
`{"profile":"local-development"}` on `/auth/config`. No Azure login is required for local use.

## Developing the Release Hub UI

Pre-built static assets live in `lifecycle_rs/release-hub/ui/dist`, so you don't need Node.js just
to run the server. If you modify TypeScript or Preact files under `lifecycle_rs/release-hub/ui/`:

```bash
npm --prefix lifecycle_rs/release-hub/ui ci
npm --prefix lifecycle_rs/release-hub/ui run build
```

For Vite hot-reload on `http://127.0.0.1:5291` (which proxies `/v1`, `/healthz`, and `/auth` to
`http://127.0.0.1:8091`), start Release Hub on port `8091` and run Vite in a second terminal:

```bash
cargo run --locked -p fdai-release-hub -- --host 127.0.0.1 --port 8091
npm --prefix lifecycle_rs/release-hub/ui run dev
```

## Testing

```bash
cargo test --locked -p fdai-release-hub
npm --prefix lifecycle_rs/release-hub/ui test
```

## Related docs

- [Local Development Quickstart](../../docs/user-guide/local-development-quickstart.md)
- [Hub lifecycle operator guide](../../docs/runbooks/hub-lifecycle-operator-guide.md)
- [Legacy design notes and protocol boundaries](../../lifecycle/release-hub/README.md)
