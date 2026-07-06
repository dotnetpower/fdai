# `console/`

Thin, read-only operator SPA - KPI dashboard, audit log viewer, HIL queue view.
This is the layer-3 surface described in
[`.github/instructions/app-shape.instructions.md`](../.github/instructions/app-shape.instructions.md)
§ Operator console. The read-only invariant is a hard rule: the SPA MUST issue
no privileged calls, MUST NOT expose an action / approval button, and MUST NOT
share the executor identity.

## Framework choice

**Vite + Preact** (10.24) with the MSAL.js browser client.

- **Preact over React** - same JSX/hook API, ~10 kB runtime instead of ~45 kB.
  The console is a low-traffic surface for operators; a smaller bundle wins.
- **Vite over Astro** - the `site/` docs site uses Astro Starlight for
  content-plus-islands; the console is a fully authenticated SPA behind Entra
  ID with no static content pre-render benefit. Vite gives the fastest DX and
  the smallest transitive dep tree for that shape.
- **MSAL.js** - the standard Entra ID library. Handles OIDC + PKCE per
  [`docs/roadmap/user-rbac-and-identity.md` § 10.1](../docs/roadmap/user-rbac-and-identity.md).

## Read-only surface

The SPA talks to exactly three GET routes on the read API
(`src/aiopspilot/delivery/read_api/main.py`):

| Route | Purpose |
|-------|---------|
| `GET /audit` | Paginated audit log rows (newest first). |
| `GET /kpi` | Dashboard KPIs (event count, shadow/enforce share, HIL pending, per-kind, per-outcome). |
| `GET /hil-queue` | Pending HIL items (approvals happen through ChatOps, not here). |

No mutating verb (`POST` / `PUT` / `DELETE` / `PATCH`) is called anywhere in
`src/**`. The pytest suite for the API enforces `405` on mutating verbs
(`tests/delivery/read_api/test_main.py::TestReadOnlyInvariant`).

## Extending the console (fork panels)

The upstream console ships a deliberately minimal UI - the three core panels
above. A fork adds vertical-specific dashboards (a FinOps cost board, a drift
board, a DR-drill history) **without editing `app.tsx` or `shell.tsx`**, through
two matching seams:

1. **API side** - implement the `ReadPanel` Protocol
   (`src/aiopspilot/delivery/read_api/panels.py`) and register it at the
   composition root via `ReadApiConfig.extra_panels`. The app factory wraps
   each panel as a **GET-only** route, authorizes it with the same reader-role
   gate as the core routes, and fails fast on a malformed / colliding path -
   so the read-only invariant holds for extensions exactly as for core routes.
2. **Console side** - add a `ConsolePanel` entry to `EXTRA_PANELS` in
   [`src/panels.tsx`](src/panels.tsx). The nav bar and router iterate the
   registry, so a new panel appears with no other change. Panels fetch their
   data through the GET-only `client.panel<T>(path)` helper.

Both halves ship a copy-paste reference that is **not** registered upstream
(so the default UI stays minimal): `ExampleFinOpsPanel` in `panels.py` and
[`src/routes/example-finops.tsx`](src/routes/example-finops.tsx). A fork opts
in by registering both.

Panels are read-only like the rest of the console: no action / approval button.
Cost / change actions still flow through remediation PRs and ChatOps HIL.

## Layout

```text
console/
├── index.html          - Vite entrypoint (single-page shell)
├── package.json        - deps: preact, @azure/msal-browser
├── tsconfig.json       - strict TS, jsx=preact
├── vite.config.ts      - build → console/dist/ (git-ignored)
└── src/
    ├── main.tsx        - Preact render root
    ├── app.tsx         - top-level router + init
    ├── config.ts       - env-var-driven runtime config
    ├── auth.ts         - MSAL.js wrapper + dev-mode bypass
    ├── api.ts          - read-only ReadApiClient (three GET methods + panel())
    ├── types.ts        - TS mirrors of read_model.py shapes
    ├── panels.tsx      - panel registry (core panels + fork extension point)
    ├── styles.css      - minimal, no design-system dep
    ├── components/
    │   └── shell.tsx   - top bar + nav (iterates the panel registry)
    └── routes/
        ├── dashboard.tsx
        ├── audit.tsx
        ├── hil-queue.tsx
        ├── example-finops.tsx  - reference fork panel (opt-in, not registered)
        └── login.tsx
```

## Local development

```sh
cd console
npm install
# Terminal 1: run the read API in dev mode (anonymous auth).
AIOPSPILOT_READ_API_DEV_MODE=1 \
    uv run uvicorn 'aiopspilot.delivery.read_api._local:app' \
        --factory --port 8000

# Terminal 2: run the SPA against the dev-mode API.
VITE_DEV_MODE=1 VITE_READ_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

The dev-mode env var is a **boot-time tripwire** - the API refuses to build a
`dev_mode=True` app unless `AIOPSPILOT_READ_API_DEV_MODE=1` is set. A fork's
production build pipeline never sets that env var.

## Production build

```sh
npm run build
# → console/dist/ (git-ignored)
```

The `dist/` output is uploaded by `infra/modules/console/` to Azure Static
Web Apps. Custom domain, CSP headers, and MSAL app-registration values are
supplied by the fork; the upstream repo ships schema and empty defaults only.

## Fork configuration

Set these at build time (Static Web App app settings, `.env.production`, or
CI env):

| Env var | Meaning |
|---------|---------|
| `VITE_READ_API_BASE_URL` | Origin of the read API (e.g. `https://api.<fork>`). |
| `VITE_MSAL_CLIENT_ID` | Entra App Registration client id (SPA). |
| `VITE_MSAL_TENANT_ID` | Entra tenant id (single-tenant per fork). |
| `VITE_MSAL_API_SCOPE` | API audience scope (e.g. `api://<api-guid>/access`). |
| `VITE_DEV_MODE` | `1` to bypass MSAL. Never set in production. |
| `VITE_CONSOLE_BASE_PATH` | Optional subpath if not served at origin root. |
