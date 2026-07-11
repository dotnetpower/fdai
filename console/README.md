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
view (which pantheon agent did what, when, and how) by grouping audit rows on
their `actor`, and offers two toggled layouts: a **Timeline** (vertical, newest
first) and a **Waterfall** master-detail. The waterfall's left column is a
compact, collapsible incident tree (grouped by `correlation_id`); selecting a
step opens a large detail pane on the right that renders the append-only entry
verbatim - a lifecycle stepper (event sent -> received -> work started ->
finished, with per-hop latency), the narrative of what the agent did, any
agent-to-agent conversation (the conversational-port turns exchanged while
doing the work, shown as `from -> to` bubbles), its structured inputs /
outputs, and the full record (tier, mode, outcome, decision, hashes). A small
speech-bubble badge on a left row marks the steps that carry a conversation.
Agent chips (coloured by cognitive layer) filter both layouts, and every entry
deep-links to its full pipeline trace via `#/trace?correlation=<id>`. The dev
read-API seed
([`src/fdai/delivery/read_api/_local.py`](../src/fdai/delivery/read_api/dev/local.py))
attributes each row to its producing agent and carries the lifecycle
timestamps + inputs / outputs + conversation so the pane renders a realistic
sample.

**Dev seed vs live.** The panel is data-driven and degrades gracefully - it
reuses the always-on `GET /audit` route in every environment, and each detail
section renders only when its field is present. The audit shapes differ:

| Field | Dev seed (`_local.py`) | Live control loop |
|-------|------------------------|-------------------|
| `actor` | pantheon agent (`Odin`, ...) | dotted service (`fdai.core.control_loop`) |
| `producer_principal` | agent name | absent today (stamped once the pantheon drives the hot path) |
| `tier`, `mode`, `action_kind`, `correlation_id` | present | present |
| `event_ts` / `received_at` / `started_at` / `finished_at`, `inputs` / `outputs`, `conversation`, `summary` / `detail` | present | not emitted yet |

So in live the panel still renders and stays segmented by real producer -
`agentOf()` attributes a row to its `producer_principal` when set, else
humanizes the service `actor` (`fdai.core.rca` -> `core.rca`) rather than
collapsing every core row into `System`. The lifecycle stepper shows the one
`Finished` node it can derive from `recorded_at`, and the conversation /
inputs / outputs / narrative sections are omitted until the pipeline emits
them. Making those live is core + pantheon work (agents stamping
`producer_principal` and lifecycle spans; the conversational port emitting
turns), tracked in the agent-pantheon roadmap - not a console change.
`src/routes/agent-activity.test.ts` pins this tolerance to both shapes.

**Faithful full view (nothing stored is hidden).** The `audit_log.entry`
column is JSONB and the read model passes it through verbatim, so any field a
producer persists is renderable. The detail pane curates the fields it knows
how to format nicely (lifecycle, conversation, inputs / outputs, record) and
then renders **every remaining `entry` key** in an "Other recorded fields"
section via a generic key/value viewer. This means the genuinely-stored live
fields that have no dedicated section - the executor's `rollback_kind`,
`blast_radius`, `resource_ref`, `operation`, `rule_id`, `pr_ref`,
`citing_rule_ids`, `stop_condition` (see
[`src/fdai/core/executor/executor.py`](../src/fdai/core/executor/executor.py)
`_write_audit`) - are shown, not dropped by a hardcoded allow-list, and new
producer fields appear automatically. The invariant is two-way: everything
shown comes from the stored `entry` (read-only passthrough), and everything
stored is shown.

Beyond the three always-on routes above, the app factory registers several
**opt-in** GET routes when their inputs are wired at the composition root
(ontology graph, pantheon, blast-radius, promotion gates, rule-fire trace, and
the rule catalog below). Each is reader-role gated and collision-checked; none
ships enabled upstream unless its `ReadApiConfig` input is set.

### Rule catalog panel (Knowledge)

The **Knowledge > Rules** panel ([`src/routes/rule-catalog.tsx`](src/routes/rule-catalog.tsx))
answers "what does this rule enforce, why does it matter, and which resources
violate it" over three GET routes
([`src/fdai/delivery/read_api/rule_catalog.py`](../src/fdai/delivery/read_api/routes/rule_catalog.py)):

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

### Submitting an action (propose, never execute)

For an explicit operator command (`restart vm-1`), the deck does not ask the
narrator - it POSTs to `/chat/action`
([`src/deck/backend.ts`](src/deck/backend.ts) `submitAction`), detected by
[`src/deck/action-intent.ts`](src/deck/action-intent.ts) (a leading imperative
verb, mirroring the server's `is_action_intent`). That endpoint publishes an
`ActionProposal` into the typed pantheon pipeline; **nothing runs until Forseti
judges it and, for a high-risk action, an approver signs off** (execution is
shadow-first, and RBAC is enforced server-side - a Reader gets `403`). The deck
renders the outcome (submitted with a correlation id / refused by role /
unmapped) and never holds any execution authority. See
[operator-console.md § 13.5](../docs/roadmap/operator-console.md).

### Self-describing screens

Each route publishes a `ViewSnapshot` (`src/deck/context.tsx`) that is a screen
*model*, not just a value digest. Besides `facts`/`records`, a route declares:

- **`purpose`** - one or two lines on what the screen is for, so "what is this
  screen / why am I here" is grounded without a per-route answerer.
- **`glossary`** - the terms/labels this screen renders (e.g. `correlation id`,
  `waterfall`, a `corr-*` chip), each with a `plain` meaning, optional `tech`
  token, `seeAlso` route, and `match` records-column. Routes compose these from
  the shared catalog in [`src/deck/glossary.ts`](src/deck/glossary.ts) so a term
  means the same thing on every screen.
- **causal fields kept in `records`** - `detail`/`summary`/`reason`/`tier`/
  `outcome` are NOT projected away, so "why did this start" is answered by
  quoting the recorded narrative instead of shrugging.

The deterministic answerer ([`src/deck/answerer.ts`](src/deck/answerer.ts)) is
**screen-agnostic**: a resolver chain (causal -> glossary/value-chip -> route
enhancer -> generic record search) answers "what is X" and "why did this start"
on *any* route - including screens with no bespoke enhancer - from the declared
`purpose`/`glossary`/records. A new screen becomes explainable by declaring its
vocabulary, not by adding code. The server narrator receives the same `purpose`
and `glossary` in the snapshot JSON and is instructed to ground term and causal
answers in them.

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

### Conversation UX affordances

The deck input and transcript behave like a familiar chat/terminal surface, all
read-only and grounded:

- **History recall** - Arrow-Up / Arrow-Down walk previously submitted prompts
  (shell-style), stashing the live draft. Pure reducer in
  [`src/deck/draft-history.ts`](src/deck/draft-history.ts).
- **Auto-growing input** - the textarea grows to fit a multi-line draft up to a
  capped height, then scrolls.
- **Stop** - an in-flight streaming reply can be cancelled; whatever streamed so
  far is kept and labelled `stopped` (the backend threads an `AbortSignal`
  through `askBackendStream`).
- **Copy / Regenerate** - each completed reply exposes a Copy button and a
  Regenerate button that re-asks the operator question that produced it.
- **Smart autoscroll** - the transcript follows streaming tokens only while the
  operator is reading the latest turn; scrolling up to re-read an earlier answer
  suppresses the follow and surfaces a `Jump to latest` control. Geometry lives
  in [`src/deck/scroll-stick.ts`](src/deck/scroll-stick.ts).
- **Accessibility** - the overlay is an `aria-modal` dialog with a Tab focus
  trap and focus restoration on close; the transcript is an `aria-live` log and
  a visually-hidden `role="status"` region announces retrieving / answering /
  ready transitions.
- **Reload survival** - completed turns are mirrored into tab-scoped
  `sessionStorage` (defensive parse, capped) so an accidental refresh does not
  lose the conversation. Serialisation core in
  [`src/deck/transcript-store.ts`](src/deck/transcript-store.ts).

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

## Local sign-in test (real Entra)

To exercise the **actual** MSAL sign-in + JWT verification + App-Role gate
locally - not the anonymous bypass - run the same seed harness with
`FDAI_READ_API_LOCAL_ENTRA=1` instead of `FDAI_READ_API_DEV_MODE`. The API then
verifies genuine Entra access tokens against the tenant JWKS
([`entra_verifier.py`](../src/fdai/delivery/read_api/entra_verifier.py)) while
still serving the in-memory seed, so no live audit store is needed.

Prerequisite - two Entra app registrations in your tenant (see
[user-rbac-and-identity.md § 10](../docs/roadmap/user-rbac-and-identity.md#10-sign-in-flow-reference)):

1. **SPA app** (`fdai-console-spa`): platform *Single-page application*, redirect
   URI `http://localhost:5173`. Note its client id.
2. **API app** (`fdai-api`): Application ID URI `api://<api-guid>`, one exposed
   scope `access`, and App Roles `Reader` / `Contributor` / `Approver` / `Owner`.
   Assign your user the `Reader` (or higher) App Role in *Enterprise
   applications*.

```sh
# Terminal 1: read API with REAL Entra verification (seed data).
FDAI_READ_API_LOCAL_ENTRA=1 \
    FDAI_ENTRA_TENANT_ID=<tenant-guid> \
    FDAI_API_AUDIENCE=api://<api-guid> \
    uv run uvicorn 'fdai.delivery.read_api._local:app' \
        --factory --port 8000

# Terminal 2: SPA in NON-dev mode - MSAL actually signs you in.
VITE_DEV_MODE=0 \
    VITE_READ_API_BASE_URL=http://127.0.0.1:8000 \
    VITE_MSAL_CLIENT_ID=<spa-client-id> \
    VITE_MSAL_TENANT_ID=<tenant-guid> \
    VITE_MSAL_API_SCOPE=api://<api-guid>/access \
    npm run dev
```

Open `http://localhost:5173`, click **Sign in with Entra ID**, complete the
Entra prompt, and the console loads the seed behind your real token. An
unauthenticated call returns `401`; a signed-in user with no App Role gets `403`
(assign a role to fix). This proves the production auth path end-to-end without
deploying anything.

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
| `VITE_WORKFLOW_CATALOG_REPO` | Optional `owner/repo` of the catalog repo. When set, a validated workflow draft shows a one-click "Open a PR on GitHub" (new-file link); the console still never commits. |
| `VITE_WORKFLOW_CATALOG_BRANCH` | Branch the new-file PR link targets (default `main`). |
