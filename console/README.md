# `console/`

Thin, read-only operator SPA - KPI dashboard, audit log viewer, per-agent
activity timeline, HIL queue view. This is the layer-3 surface described in
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
(`src/fdai/delivery/read_api/main.py`):

| Route | Purpose |
|-------|---------|
| `GET /audit` | Paginated audit log rows (newest first). |
| `GET /kpi` | Dashboard KPIs (event count, shadow/enforce share, HIL pending, per-kind, per-outcome). |
| `GET /hil-queue` | Pending HIL items (approvals happen through ChatOps, not here). |

No mutating verb (`POST` / `PUT` / `DELETE` / `PATCH`) is called anywhere in
`src/**`. The pytest suite for the API enforces `405` on mutating verbs
(`tests/delivery/read_api/test_main.py::TestReadOnlyInvariant`).

The **History > Agent activity** panel
([`src/routes/agent-activity.tsx`](src/routes/agent-activity.tsx)) reuses the
same `GET /audit` route - no new backend route. It reconstructs a per-agent
timeline (which pantheon agent did what, when, and how) by grouping audit rows
on their `actor`, colours each agent chip by its cognitive layer, and
deep-links every entry to its full pipeline trace via
`#/trace?correlation=<id>`.

Beyond the three always-on routes above, the app factory registers several
**opt-in** GET routes when their inputs are wired at the composition root
(ontology graph, pantheon, blast-radius, promotion gates, rule-fire trace, and
the rule catalog below). Each is reader-role gated and collision-checked; none
ships enabled upstream unless its `ReadApiConfig` input is set.

### Rule catalog panel (Knowledge)

The **Knowledge > Rules** panel ([`src/routes/rule-catalog.tsx`](src/routes/rule-catalog.tsx))
answers "what does this rule enforce, why does it matter, and which resources
violate it" over three GET routes
([`src/fdai/delivery/read_api/rule_catalog.py`](../src/fdai/delivery/read_api/rule_catalog.py)):

| Route | Purpose |
|-------|---------|
| `GET /rules` | Paginated, faceted list over the active catalog + collected corpus, tagged `origin=active\|collected`. Server-side filter (`origin`/`category`/`severity`/`source`/`q`) + `limit`/`offset`. |
| `GET /rules/{id}` | Full detail: sandboxed Rego + remediation template bodies, plus an `explanation` (why it matters / risk) parsed from the Rego `# METADATA` block or the `azure_policy` / `kube_bench` params - grounded, never fabricated. |
| `GET /rules/{id}/findings` | Affected resources (resource + the attribute at fault) behind a `findings_provider` seam. Upstream ships none -> honest `evaluated=false`; a fork wires an inventory-evaluation source. |

The seams are `ReadApiConfig.rule_catalog_rules`, `_collected_rules`,
`_policies_root`, `_remediation_root`, and `_findings_provider`. The dev harness
(`src/fdai/delivery/read_api/_local.py`) wires a demo findings provider
(`demo_findings.py`) that evaluates the shipped Rego against a small synthetic,
customer-agnostic inventory via real OPA - each finding's `problem` is the
policy's own `deny_reason`, not invented. A selected rule is deep-linked into
the URL hash (`#/rules?rule=<id>&origin=<origin>`), so a rule detail is
shareable and the browser back button closes the drawer.

## Command deck (conversational surface)

The deck (`src/deck/`) is a screen-aware, read-only conversational surface: the
narrator (Bragi) is a **translator, not a judge**, matching the
narrator-is-a-translator contract in
[`.github/instructions/architecture.instructions.md`](../.github/instructions/architecture.instructions.md).
It answers questions grounded in only what is on screen (the published
`ViewSnapshot`) and never issues a privileged call.

The chat backend (`src/fdai/delivery/read_api/chat.py`) keeps each turn's
system prompt lean for cost and latency: compact base instructions, the FDAI
glossary appended only for concept questions (EN + KO), and every `records`
array capped to a representative sample (with a `_records_truncated` hint) so
the snapshot JSON does not dominate the token budget - the operator narrows to
off-sample rows via the page's own search/filter.

While a turn is pending, the deck renders a **retrieval trace**
(`src/deck/retrieval-trace.tsx`) in place of a bare typing indicator. It streams
the read-only sources the deck is grounding on - the current screen snapshot
facts - in a slot-machine window, alongside the stages it can honestly report
from data it already holds (`Read this screen` from the snapshot, `Route` /
`Consult backend` from the backend health descriptor). It fabricates nothing:
every row comes from the live `ViewSnapshot` or `BackendHealth`. When the chat
backend later streams real per-stage retrieval events (SSE), `retrieval-trace.tsx`
is the seam that renders them.

## Extending the console (fork panels)

The upstream console ships a deliberately minimal UI - the three core panels
above. A fork adds vertical-specific dashboards (a FinOps cost board, a drift
board, a DR-drill history) **without editing `app.tsx` or `shell.tsx`**, through
two matching seams:

1. **API side** - implement the `ReadPanel` Protocol
   (`src/fdai/delivery/read_api/panels.py`) and register it at the
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
        ├── rule-catalog.tsx     - Knowledge > Rules panel (explanation + affected resources)
        ├── example-finops.tsx  - reference fork panel (opt-in, not registered)
        └── login.tsx
```

## Local development

```sh
cd console
npm install
# Terminal 1: run the read API in dev mode (anonymous auth).
FDAI_READ_API_DEV_MODE=1 \
    uv run uvicorn 'fdai.delivery.read_api._local:app' \
        --factory --port 8000

# Terminal 2: run the SPA against the dev-mode API.
VITE_DEV_MODE=1 VITE_READ_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

The dev-mode env var is a **boot-time tripwire** - the API refuses to build a
`dev_mode=True` app unless `FDAI_READ_API_DEV_MODE=1` is set. A fork's
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
