# `console/`

Thin, read-only operator SPA - KPI dashboard, incident roster, audit log
viewer, per-agent activity timeline, and Approvals view. This is the layer-3 surface described in
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
  [`docs/roadmap/interfaces/user-rbac-and-identity.md` § 10.1](../docs/roadmap/interfaces/user-rbac-and-identity.md).

## Read-only surface

The SPA starts with six always-on GET routes on the read API
(`src/fdai/delivery/read_api/main.py`):

| Route | Purpose |
|-------|---------|
| `GET /audit` | Paginated audit log rows (newest first), optionally filtered by `correlation_id`. |
| `GET /kpi` | Dashboard KPIs (event count, shadow/enforce share, approvals pending, per-kind, per-outcome). |
| `GET /hil-queue` | Pending approval count for Readers; safety detail for Approvers and Owners (decisions still happen through ChatOps). |
| `GET /incidents` | Paginated incident roster with active/resolved/all filters. |
| `GET /audit/{correlation_id}/trace` | Ordered end-to-end trace for one incident. |
| `GET /healthz` | Read-API health status. |

Managed-resource views use GET-only read routes. The console has narrow POST
carve-outs for narrator turns, typed action **proposals**, and pure workflow
validation; none executes a managed-resource mutation directly. Core read
routes enforce `405` on mutating verbs
(`tests/delivery/read_api/test_main.py::TestReadOnlyInvariant`).

The **Evidence > Documents** panel is a separate content-ingestion surface, not
a managed-resource mutation path. Its dedicated client talks only to the
ingestion gateway, uploads source bytes directly to the gateway-provided object
target, and requires the operator to acknowledge the effective shared audience.
The GET-only `ReadApiClient` remains unchanged and never gains upload helpers.

The panel registry in [`src/panels.tsx`](src/panels.tsx) groups the complete
operator surface into five stable navigation domains: Overview, Operations,
Agents, Governance, and Evidence. An icon-only Activity Bar selects a domain,
opens the adjacent Explorer, and navigates to that domain's first visible panel.
Settings is pinned to the bottom of the Activity Bar and uses the same Explorer
pattern. Page titles render a compact domain / panel hierarchy when the labels
differ (for example, `Overview / Dashboard` and `Overview / LLM usage`). A root
whose panel title repeats its domain label keeps a single title. In local dev
mode, a `Labs` group appears immediately above Settings and links to
development-only design tools such as the Logo lab.

The production shell keeps this Activity Bar + Explorer hierarchy even though
the static prototypes under [`mocks/ui/`](../mocks/ui/) use a single sidebar.
The prototypes remain the visual reference for content: Calm Slate palette,
hairline borders, compact section hierarchy, semantic tier/risk colors, KPI
accents, evidence tables, and approval safety cards. Shared `--cs-*` tokens in
[`src/styles.css`](src/styles.css) apply that language across every route while
preserving the documented navigation and clean History API URLs.

The **Operations > Incidents** panel is the incident-centric entry point. It groups
the append-only audit stream by `correlation_id`, shows lifecycle status and
the latest fix disposition, and loads one incident's audit history on
selection. Active, Resolved, and All filters use server-side keyset
pagination. Links open the existing Audit and Trace panels with the same
correlation filter. The roster does not create a second incident source of
truth and exposes no action or approval control.
Optional read projections, including workflow Processes, reports, ontology,
inventory, pantheon, promotion gates, and LLM cost, render an explicit
unavailable state when the composition root does not register their GET route.
The Processes panel consumes `GET /views/process` and
`GET /views/process/{process_id}`. It renders server-selected, bounded
ViewSpecs instead of computing workflow or ontology decisions in the browser.

The Overview health axis fails closed: known guard failures show **Needs
attention**, and missing promotion or autonomy evidence shows **Evidence
unavailable** rather than healthy. The Approvals view joins its bounded latest-item
projection with the authoritative `/kpi.hil_pending` total so a queue larger
than the display cap is labeled as truncated instead of silently undercounted.

The Approvals route also enforces the visibility split in
[`operator-console.md` section 3.2](../docs/roadmap/interfaces/operator-console.md#32-week-1-additions-write--approve--runbook).
A Reader receives `detail_level=count_only`, an empty item array, and the
authoritative queue total. A principal with the `approve-runtime-hil`
capability receives `detail_level=full` plus the action's recorded target,
mode, stop-condition, rollback reference, impact scope, citing rules, reasons,
and TTL. The server performs the redaction; the browser never decides whether
sensitive approval intent is visible. Older park records remain readable and
show `Not recorded` for safety fields that predate the enriched projection.

Human-facing console copy uses **Approvals**, **Approval required**, and
**Pending approval** instead of exposing the `HIL` acronym by default. The
machine contract stays unchanged: the `hil` decision, `/hil-queue` route,
TypeScript types, events, and audit values retain their canonical identifiers.
The technical glossary still explains human approval when an operator asks explicitly or
inspects a raw decision.

The Overview presents evidence in operating-owner order: current posture and
evidence metadata, five measured outcome metrics, routing and control
distributions, required attention, and vertical results. Synthetic measurements
are labeled as simulated instead of proven. Agent organization remains on its
owned Agents routes. Audit-level counts and living-rule evidence stay in a
collapsed section instead of competing with the executive summary.

Every data-bearing Overview item is a drill-down link, including evidence
metadata, unavailable states, distribution segments and legends, attention
facts, vertical statistics, and collapsed operational counts. Four analytical
hubs explain the aggregate rather than repeating it:
`/operating-outcomes/<metric>`, `/control-assurance`,
`/verticals/<vertical>`, and `/trust-routing/<tier>`.
Existing evidence routes remain the terminal detail surfaces: `/approvals`,
`/agents`, `/agent-activity`, `/rules`, `/promotion-gates`, `/audit`, and
`/trace`. Query filters are shareable, for example `/audit?mode=shadow` and
`/promotion-gates?status=blocked`.

Drill-down routes remain contextual destinations from the data under
investigation and are also available in the Overview Explorer. Selecting the
Overview Activity Bar group opens Dashboard as its first visible panel; local
panel order and visibility preferences determine the first destination for
every group.

The SPA uses clean History API URLs. User-facing paths are lowercase
`kebab-case` with no spaces or underscores; internal API routes and serialized
values remain unchanged. The emitted `staticwebapp.config.json` rewrites
non-asset application paths to `index.html` so direct links and browser refresh
work on Azure Static Web Apps. Legacy `#/...` bookmarks migrate once to their
clean equivalent.

The Provisioning panel consumes `GET /provision/stream` with fetch-based SSE.
It acquires the same MSAL bearer header as other read calls, aborts the stream
when the route unmounts or the tab is hidden, and reconnects transient failures
with capped exponential backoff when visible. Permanent `401` / `403` responses
stop reconnecting. The token stays in the Authorization header and never enters
the URL.

Core and high-risk optional payloads are decoded before routes enter their
ready state. Version-skewed or malformed `200` responses become a uniform
contract error instead of a render crash. Rule detail deep links also preserve
their explicit `active` or `collected` origin; a missing rule in that origin
returns `404` instead of falling back across catalog tiers.

The Overview group's Dashboard landing panel is eager; every other panel is loaded as a separate
route chunk behind a Suspense boundary. Heavy visualization libraries remain
on-demand. Command Deck requests are bound to one transcript session and are
retired on close, clear, session switch, route navigation, or unmount, so a
late answer cannot enter a different screen or agent conversation.

The standalone Settings panel changes presentation plus opt-in chat verification behavior.
Theme, locale, reduced-motion, and experimental semantic-verification preferences are
validated and stored in browser
`localStorage`, with an in-memory fallback for the current tab when persistent
storage is blocked. The runtime section exposes the configured read-API
endpoint for diagnostics. Settings never call the read API, mutate managed
resources, or hold an execution identity.

The **Agents > Pantheon** panel combines two read-only sources without
conflating them. `GET /pantheon/graph` and `GET /pantheon/workflows` provide
the fork-locked organization, ownership, reporting lines, flags, and workflow
registrations. `GET /agents/stream` adds each agent's current runtime state,
task detail, correlation id, and engaged count. The page follows the Calm
Slate prototype with governance, pipeline, and domain card groups plus a
registry-derived reporting tree. Interactive local development does not create
an agent stream; the runtime layer stays unavailable until the Azure FDAI
runtime relay is configured. Neither source grants the console execution
authority.

The **History > Agent activity** panel
([`src/routes/agent-activity.tsx`](src/routes/agent-activity.tsx)) reuses the
same `GET /audit` route - no new backend route. It reconstructs a per-agent
view (which pantheon agent did what, when, and how) by grouping audit rows on
their `actor`, and offers two toggled layouts: a mock-aligned **Activity** view
(per-agent groups, semantic verb rows, time/layer/verb/search filters) and a
**Waterfall** master-detail. The waterfall's left column is a
compact, collapsible incident tree (grouped by `correlation_id`); selecting a
step opens a large detail pane on the right that renders the append-only entry
verbatim - a lifecycle stepper (event sent -> received -> work started ->
finished, with per-hop latency), the narrative of what the agent did, any
agent-to-agent conversation (the conversational-port turns exchanged while
doing the work, shown as `from -> to` bubbles), its structured inputs /
outputs, and the full record (tier, mode, outcome, decision, hashes). A small
speech-bubble badge on a left row marks the steps that carry a conversation.
Agent chips (coloured by cognitive layer) filter both layouts, and every entry
deep-links to its full pipeline trace via `/trace?correlation=<id>`.

The panel also subscribes to `GET /agents/stream`. A bounded stream signal
updates the current connection/engaged indicators and triggers a background
refresh of the authoritative audit projection at most once per 1.5 seconds.
The stream message itself is never rendered as an audit row. This preserves
the append-only ledger as the source of truth while allowing a visible tab to
update without polling. The hook closes the SSE connection while the tab is
hidden and reconnects when it becomes visible. The dev
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

The local agent stream rotates through nine bounded, customer-agnostic Azure
operations narratives across low, medium, and high severity. This avoids a
misleading roster made from the same three incident titles while preserving the
same `agent.state`, `incident.ticket`, and `conversation.turn` wire contracts.

So in live the panel still renders and stays segmented by real producer -
`agentOf()` attributes a row to its `producer_principal` when set, else
humanizes the service `actor` (`fdai.core.rca` -> `core.rca`) rather than
collapsing every core row into `System`. The lifecycle stepper shows the one
`Finished` node it can derive from `recorded_at`, and the conversation /
inputs / outputs / narrative sections are omitted until the pipeline emits
them. Enriching those optional sections still requires producers to stamp
`producer_principal`, lifecycle spans, and conversational turns; the console
does not infer missing evidence.
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
(ontology graph, pantheon, impact scope, promotion gates, rule-fire trace, and
the inventory graph, and the rule catalog below). Each is reader-role gated and collision-checked; none
ships enabled upstream unless its `ReadApiConfig` input is set.

### Governance presentation

The Governance routes share the Calm Slate information hierarchy from
[`mocks/ui/`](../mocks/ui/) while keeping their existing read contracts.
Architecture is intentionally unchanged because it has no matching governance
mock and already owns a specialized inventory canvas.

- **Ontology** presents the structured `GET /ontology/graph` response as three
  URL-addressable views. Objects uses a deterministic 2D one-hop neighborhood,
  Links shows endpoint and cardinality contracts, and Actions provides a
  filterable ActionType safety-contract catalog. The Mermaid source remains an
  ObjectType fallback and evidence view.
- **Rules** preserves server-side facets, paging, detected issues, and the detail
  drawer. Facets render as count-bearing chips, while list rows expose only
  recorded provenance, category, source, affected count, and version. The UI
  does not invent shadow accuracy or override counts missing from the API.
- **Workflow builder** keeps conversational authoring and pure validation. A
  selected published workflow now renders as a read-only Palette / Canvas /
  Inspector workspace backed by `GET /workflows/action-types` and
  `GET /workflows/catalog`; drag, direct publication, and execution remain
  unavailable.
- **Impact scope** renders the actual simulation response as concentric depth
  rings and an impact tree by default. The existing Architecture map and raw
  table remain alternate views. No resource, personnel, or connection cap is
  shown unless the response records it.
- **Promotion gates** filters measured ActionTypes by ready/blocked state and
  search text, and renders accuracy, reviewed/agreed progress, policy escapes,
  and recorded gaps. Promotion remains a separate reviewed catalog PR.
- **Scope** uses the same summary/evidence panels for monitoring scope, action
  scope, and the hard executor boundary. Its builder still emits a policy-as-
  code preview for a PR and never changes scope from the browser.

### Architecture panel (Knowledge)

The **Knowledge > Architecture** panel renders the deployed inventory instance graph from
`GET /inventory/graph`. It shows subscription and resource-group containment, VNet and
subnet boundaries, resource status, and `attached_to` / `depends_on` links in one read-only
canvas. Pan, zoom, filtering, selection, and deep links are local view operations only.
The console cannot add, move, resize, or delete resources.

Production responses merge the immutable reconciliation snapshot with the
ordered real-time resource/link overlay. The toolbar shows pending real-time
change count alongside snapshot freshness so an operator can distinguish a
recent Huginn projection from the last six-hour full reconciliation.

The default selector shows only FDAI's own tagged control-plane resources and the parent
boundaries needed to render their containment. The service identity `fdai` is reserved for this
default view rather than exposed as a duplicate service. Named service views use the explicit
`fdai:service`, `service`, `application`, `app`, `workload`, or `azd-service-name` inventory
tags. Missing or conflicting service values fall back to a resource-group view instead of being
guessed into an application. Every view uses the same boundary-normalization pass before
rendering, so a resource cannot appear outside its declared parent scope. The right-side Map
controls provide Iso / Top / Front camera presets, layer and display toggles, and the canvas
includes Zoom in / out / Fit controls.

The canvas renders floor reflections first, then opaque resource bodies, connection paths,
and finally resource abbreviations and labels. This keeps dependency lines visible above the
blocks without obscuring their text, while each lifted resource retains a color-matched mirrored
reflection on the floor plane.

The map limits its visual grammar to four geometric primitives. Semantic variants change the
proportions or stacking of those primitives without introducing a new silhouette for every
Azure resource type:

| Semantic role | Example resource types | Shape |
|---------------|------------------------|-------|
| Database | PostgreSQL, SQL Database | Solid-top cylinder |
| Application runtime | App Service, Container Apps, Functions, AKS | Rectangular block |
| Gateway and L4 | Front Door, Application Gateway, Load Balancer | Low, wide block |
| Storage | Storage Account, object storage | Two-level slab |
| Queue and event bus | Event Hubs, Service Bus, queues, Kafka | Hexagonal prism |
| Secret and security | Key Vault, Firewall, NSG | Chamfered compact block |

Resource color and layer filtering are separate contracts:

- **Resource color**: every supported Azure resource type and alias maps to an explicit solid
  token. The palette is derived from the dominant fills in the current
  [Azure Architecture Icons](https://learn.microsoft.com/azure/architecture/icons/) and adjusted
  only when a darker solid is required for Canvas contrast. It is described as Azure-aligned,
  not as a replacement for or modification of the official SVG icons.
- **Layer filter**: `Scope`, `Network`, `Security`, `Runtime`, `Data`, `Messaging`, and
  `Observability` filter the operational role of resources. Filter controls use neutral selection
  marks and counts so they do not imply a second color taxonomy. Empty layers stay visible but
  disabled, preserving a stable control order across architecture views.
- **Visual redundancy**: color is paired with a shape and abbreviation. On wider canvases it is
  also paired with a service label, while pointer selection exposes inspector metadata. The map
  does not rely on color alone to distinguish resource types.

The right-side `Resource colors` legend lists only the service tokens present in the selected
architecture view. Event Hubs, databases, and Storage therefore retain distinct green, blue,
and teal identities even though all three participate in data movement.

The local FDAI view includes an Event Hubs node in the `web-api -> event-hub -> event-worker`
flow so every primitive is visible during development. Resource lift stays deliberately small
so each mirrored floor reflection remains visually attached to its node. Bodies use line-free
surfaces with face shading for depth; an outline appears only on the selected resource as an
interaction cue. On narrow canvases, the map keeps resource abbreviations but suppresses long
labels to prevent overlap; selecting a resource still exposes its full name in the inspector.

The same canvas is reused by **Safety > Impact scope** in a context mode that highlights
the target and reached resources while dimming the rest. Live activity scopes and rule
detected issues deep-link into the full Architecture panel when they carry a resource reference.

### Rule catalog panel (Knowledge)

The **Knowledge > Rules** panel ([`src/routes/rule-catalog.tsx`](src/routes/rule-catalog.tsx))
answers "what does this rule enforce, why does it matter, and which resources
violate it" over three GET routes
([`src/fdai/delivery/read_api/rule_catalog.py`](../src/fdai/delivery/read_api/routes/rule_catalog.py)):

| Route | Purpose |
|-------|---------|
| `GET /rules` | Paginated, faceted list over the active catalog + collected corpus, tagged `origin=active\|collected`. Server-side filter (`origin`/`category`/`severity`/`source`/`q`) + `limit`/`offset`. |
| `GET /rules/{id}` | Full detail: sandboxed Rego + fix template bodies, plus an `explanation` (why it matters / risk) parsed from the Rego `# METADATA` block or the `azure_policy` / `kube_bench` params - grounded, never fabricated. |
| `GET /rules/{id}/findings` | Affected resources (resource + the attribute at fault) behind a `findings_provider` seam. Upstream ships none -> honest `evaluated=false`; a fork wires an inventory-evaluation source. |

The seams are `ReadApiConfig.rule_catalog_rules`, `_collected_rules`,
`_policies_root`, `_remediation_root`, and `_findings_provider`. Interactive
local development leaves detected issues unavailable until an Azure-backed inventory
evaluation source is configured; it never evaluates a synthetic inventory. A selected rule is deep-linked into
the URL hash (`#/rules?rule=<id>&origin=<origin>`), so a rule detail is
shareable and the browser back button closes the drawer.

## Command deck (conversational surface)

The deck (`src/deck/`) is a screen-aware conversational surface: the narrator
(Bragi) is a **translator, not a judge**, matching the
narrator-is-a-translator contract in
[`.github/instructions/architecture.instructions.md`](../.github/instructions/architecture.instructions.md).
It answers screen questions from the published `ViewSnapshot`, direct KPI /
approval / audit / incident questions from server-owned read-model tools, and
domain questions from the owning pantheon agent. Explicit multi-agent requests
call a bounded set of contributors and aggregate their evidence. Every request
uses the signed-in operator's bearer token and a stable, server-namespaced
conversation session. The question path never issues a privileged call.

### Submitting an action or incident

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
[operator-console.md § 13.6](../docs/roadmap/interfaces/operator-console.md#136-action-submit---post-chataction-propose-never-execute).

Incident creation uses the same endpoint but a different built-in workflow.
The deck recognizes English and Korean incident-open requests, displays the
server's severity/target summary, and sends `confirm` or `확인` back with the
same conversation id. Only then does `IncidentRegistry` create the audited
control-plane record. This path never invokes Thor or a cloud executor.
The local development composition runs the same proposal through a persistent
in-memory pantheon bus, so a submitted restart reaches Forseti and finishes as
a Thor shadow action instead of stopping at HTTP acceptance. Production binds
the same contracts to the configured event bus.

### Cross-screen open (Now > Agents incident thread)

Any read-only surface can raise the deck without holding a reference to it, via
the decoupled `fdai:deck:open` window event
([`src/deck/open-deck.ts`](src/deck/open-deck.ts) `openDeckWithContext`). The
Now > Agents route ([`src/routes/agents.tsx`](src/routes/agents.tsx)) uses it:
the **Ask the deck about this incident** button opens an isolated conversation
with a typed incident id, correlation id, and optional selected-agent binding.
The server treats that binding as an untrusted hint, verifies both identifiers
against its read model, and bypasses fuzzy ranking only for an exact match.
Bragi remains the narrator; the selected agent is screen context, not reply
authorship. The seam seeds a draft the operator still sends and never executes
an action.

Playwright covers this operator flow in
[`tests/e2e/agents-incident-deck.spec.ts`](tests/e2e/agents-incident-deck.spec.ts)
for desktop and mobile Chromium. The browser test clicks accessible controls,
checks the outbound binding, Bragi identity, RCA-unavailable wording, bounded
agent activity, trust status, and absence of redundant disambiguation. It uses
explicit synthetic route fixtures only inside the test runner. A Starlette
integration test separately sends the same contract through the real chat route
and `OperationalEvidenceResolver`. Browser E2E is an explicit local validation,
not a required CI gate. From `console/`, install the browser once with
`npx playwright install chromium`, then run `npm run test:e2e`. Use
`npm run test:e2e:headed` when inspecting the interaction visually.

### Agent collaboration lines + hover cards (Now > Agents)

The constellation draws an SVG overlay
([`ConstellationLinks`](src/routes/agents.tsx)) that ties together the agents
currently co-engaged on the same incident, so the operator can see *which ticket
each agent is working on and with whom* at a glance. Grouping is a pure model
helper (`engagedGroups` in [`src/routes/agents.model.ts`](src/routes/agents.model.ts)):
non-idle agents sharing a `correlation_id` become one link mesh, coloured per
incident and labelled with its ticket id. The selected incident (or a hovered
agent's links) is emphasised while the rest fade back. Line coordinates are
measured from the real rendered node centres via a `ResizeObserver`, so the
overlay tracks reflow without a hard-coded layout; it is `pointer-events: none`
and `aria-hidden` because the same facts are text in the incident list.

Hovering an agent reveals a card ([`AgentHoverCard`](src/routes/agents.tsx))
that answers "what is this agent doing right now?" - the coarse state, a
plain-language task description (`STATE_TASK`), the streamed `detail` when the
producer supplies one, and the incident (ticket + title) it is engaged on. The
dev/demo emitter enriches each `agent.state` frame with a task `detail`
([`agent_activity_emitter.py`](../src/fdai/delivery/read_api/streaming/agent_activity_emitter.py));
the field stays optional so the real relay is free to omit it. A hovered node
returns to full opacity even while dimmed, so its card stays readable (a parent
`opacity` otherwise caps the child tooltip).

The incident side list is newest-first and shows the most recent
`INCIDENT_PREVIEW` (10) by default; an **All (N)** toggle beside the heading
expands to the full retained history and back to **Recent**. The list is an
accordion: selecting a row pins it and expands its workflow card (steps,
agent-to-agent conversation, RCA) inline directly beneath that row; clicking
the open row again collapses it.

The interactive local read API does not start a local ControlLoop or Pantheon
runtime. Live and Agents remain unavailable until a deployed Azure FDAI runtime
relay supplies authoritative frames. Authentication mode is not treated as
evidence provenance.

### Org-chart layout + agent focus (Now > Agents)

A **Constellation | Org chart** toggle in the header switches the stage between
the free grid and a hierarchical org chart built from the fork-locked pantheon
structure (`AGENT_ROLE` + `ORG_CHART` in
[`src/routes/agents.model.ts`](src/routes/agents.model.ts), mirroring
[agent-pantheon.md § 2](../docs/roadmap/agents/agent-pantheon.md)): Odin at the
root, Thor (operations) and Forseti (judgment) reporting to it, recovery /
narration / approval under Thor, sensing / domain specialists under Forseti, and
the four governance staff on a dotted line to Odin. **Org chart is the default
view**; both layouts share the same live nodes ([`renderNode`](src/routes/agents.tsx)),
each carrying the agent's line icon (from `public/agent-icons/<name>.svg`, painted
via a CSS mask so the monochrome glyph tints to the agent's accent colour) inside
its live status ring. The org mode adds a faint reporting-line overlay
([`OrgReportingLines`](src/routes/agents.tsx)) and shows each agent's role title
in place of the state label (the live ring still pulses).

Clicking any agent (in either layout) opens the
[`AgentFocus`](src/routes/agents.tsx) side panel: the role title + one-line duty,
its reporting line, the live state and task, and every incident the agent
participates in (newest first, each row selects that incident). Clicking the same
agent again, or the panel's close button, dismisses it. This answers "who is this
agent and what events is it working?" without leaving the live view.

A **Chat with {agent}** button in the focus panel starts a conversation primed
with that agent's recent work. It calls `openDeckWithContext`
([`src/deck/open-deck.ts`](src/deck/open-deck.ts)) with a evidence check note built by
`agentChatContext` ([`src/routes/agents.model.ts`](src/routes/agents.model.ts)) -
the agent's role, live state, and recent incidents (with RCAs). The deck injects
that note as an opening turn that **speaks as the agent** - its line icon + name
in the header (not the generic "deck" label) - and **types in** like a live reply
instead of appearing all at once, so the entrance reads as the agent introducing
itself. It joins the narrator's history and seeds a starter question, so the
operator gets an immediate, grounded answer about what the agent has been doing.
Still read-only: it opens a primed question box, never auto-submits or executes.

Each agent chat is its own **session**: the deck keys transcripts by session
(`agent:{name}` vs the general `screen` deck, see `transcriptKeyFor` in
[`src/deck/transcript-store.ts`](src/deck/transcript-store.ts)) so an agent
conversation never appends to - or leaks into - another. The deck header shows
the active agent as a chip with a **General** button back to the screen deck;
each session persists independently in tab-scoped storage and **Clear** only
clears the active one.

The Agents route also publishes a `selected_agent` record with the focused
agent's current state, task, and incident correlation. This live row takes
precedence over the opening context turn, so a newly arrived incident cannot
leave the conversation answering from an older idle snapshot.

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

Interactive screens publish more than headline counters. Their `records`
include the visible `sections`, available `controls`, and operational
`constraints` or safety boundaries, plus the current values and enabled state.
Facts keep stable machine `key` values for deterministic verification and can
add a human-facing `label`. Controls publish `label`, `detail`, and a grounded
`disabled_reason` when unavailable, so the narrator never has to infer a reason
or read an internal token aloud.
Pure sibling builders such as `document-ingestion.view.ts` keep this screen
model testable without rendering the route. The route-contract gate accepts a
builder only when that builder owns `purpose`, `glossary`, and the shared
glossary import.

For a screen-explanation turn, Bragi walks the model in a stable order:
purpose, visible sections, current status, available controls, then constraints
and safety boundaries. It explains why a control is disabled from the published
reason instead of merely listing JSON facts.
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

The chat backend (`src/fdai/delivery/read_api/routes/chat.py`) keeps each turn's
system prompt lean for cost and latency: compact base instructions, the FDAI
glossary appended only for concept questions (EN + KO), and every `records`
array capped to a representative sample (with a `_records_truncated` hint) so
the snapshot JSON does not dominate the token budget - the operator narrows to
off-sample rows via the page's own search/filter. Its latency router retries
another configured candidate in the same turn when a backend fails before the
first token. After a token is visible it never mixes models; an interrupted
reply stays partial and is labelled as such.

While a turn is pending, the deck renders a **retrieval trace**
(`src/deck/retrieval-trace.tsx`) in place of a bare typing indicator. It streams
the read-only sources the deck is evidence check on in a slot-machine window. The
first SSE status frame previews the current `ViewSnapshot`; after evidence
resolution, the server replaces that preview with a bounded list of the actual
tool, operational, agent, or glossary sources it selected. The trace remains
visible through every pre-token progress event and for at least 420 ms, then
changes into the answer bubble when text is ready. The preparing and answer
surfaces share the same width and alignment; short entry motion and staggered
source rows avoid an abrupt layout jump. Tokens that arrive during the minimum
interval enter an adaptive visual queue: each display frame drains one to three
already-paced deltas, depending on backlog, rather than dumping the whole
buffer at once. It fabricates nothing: every row comes from the live snapshot,
backend health descriptor, or server-owned evidence selection.

Rich replies render ATX headings, emphasis, strong text, strikethrough,
unordered and ordered lists, read-only task lists, blockquotes, thematic
breaks, safe links, tables, fenced code, and chart blocks. An open code fence
stays a stable plain preview while streaming and receives syntax highlighting
only after the closing fence arrives. Unsafe link schemes remain plain text.

The completed reply distinguishes evidence references from sources. A screen
or server-owned provider is a source; the individual manifest entries checked
inside that source are shown as `evidence references`. A bounded correction
that removes unsupported sentences and passes re-verification is presented as
verified, not as a warning.

Opening the deck uses a **floating panel** by default so the operator can keep
the underlying console visible. Dragging the header title moves the panel and
the bottom-right corner resizes it. The left and top edges retain a 12 px guard;
the right and bottom edges may move beyond the viewport when the operator wants
the panel partly out of the way. The header can switch the same live
conversation to a **right sidebar** or to the existing **full workspace**. The
sidebar starts at 440 px and its left
separator resizes it from 340 to 720 px with pointer or arrow-key input. Its
width is saved in `sessionStorage`, and the shell body always shrinks by the
same current width so the panel never covers navigation or page content. The
selected mode is also tab-scoped; compact mobile viewports render the panel as
a full-screen surface.

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
- **Follow the answer** - the transcript moves to the newest content when the
  answer first appears and again when its terminal revision is rendered. This
  final move is intentional even when the operator scrolled upward during
  preparation.
- **Transport resilience** - the browser accepts LF or CRLF SSE framing,
  preserves split UTF-8 code points, and labels interrupted output as partial.
  Genuine incremental model deltas render immediately. Only a large frame or a
  same-tick burst receives a short, paint-sized cadence, so bursty reasoning
  models still look progressive without replaying every token through the
  slower deterministic fallback typewriter. Cosmetic pacing is disabled while
  the tab or window is unfocused, so a background turn is complete when the
  operator returns and leaves no polling timer behind.
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

The upstream console ships a deliberately read-focused panel registry. A fork
adds vertical-specific dashboards (a FinOps cost board, a drift board, a
DR-drill history) **without editing `app.tsx` or `shell.tsx`**, through two
matching seams:

1. **API side** - implement the `ReadPanel` Protocol
   (`src/fdai/delivery/read_api/panels.py`) and register it at the
   composition root via `ReadApiConfig.extra_panels`. The app factory wraps
   each panel as a **GET-only** route, authorizes it with the same reader-role
   gate as the core routes, and fails fast on a malformed / colliding path -
   so the read-only invariant holds for extensions exactly as for core routes.
2. **Console side** - add a `ConsolePanel` entry to `EXTRA_PANELS` in
  [`src/panels.tsx`](src/panels.tsx). The Activity Bar, Explorer, and router
  iterate the registry, so a new panel appears with no other change. Panels
  use their navigation domain by default; global utilities can opt into the
  standalone bottom position with `placement: "bottom"`. Panels fetch their
  data through the GET-only `client.panel<T>(path)` helper.

Both halves ship a copy-paste reference that is **not** registered upstream
(so the default UI stays minimal): `ExampleFinOpsPanel` in `panels.py` and
[`src/routes/example-finops.tsx`](src/routes/example-finops.tsx). A fork opts
in by registering both.

Panels are read-only like the rest of the console: no action / approval button.
Cost / change actions still flow through fix PRs and ChatOps approvals.

## Tooltip contract

Use [`src/components/tooltip.tsx`](src/components/tooltip.tsx) for short,
non-interactive explanations. Keep the trigger's `aria-label` concise; the
shared component adds `aria-describedby` while the explanation is open. It
opens after 100 ms for a pointer, opens immediately on keyboard focus, closes
after 50 ms, dismisses on Escape or click, ignores touch hover, stays inside
the viewport, and disables animation when reduced motion is requested.

Avoid native DOM `title` attributes. A `title` prop on a component such as
`PageHeader`, `EmptyState`, or `DetailSection` is still a visible-heading API,
not a tooltip. [`src/components/title-inventory.test.ts`](src/components/title-inventory.test.ts)
classifies those component props and blocks new native title bubbles.

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
    ├── auth.ts         - MSAL.js wrapper + anonymous / Azure CLI dev modes
    ├── api.ts          - read-only ReadApiClient (core GET methods + panel())
    ├── preferences.ts  - validated browser-local display preferences
    ├── types.ts        - TS mirrors of read_model.py shapes
    ├── panels.tsx      - panel registry (core panels + fork extension point)
    ├── router.ts       - clean path mapping + History API navigation
    ├── styles.css      - minimal, no design-system dep
    ├── components/
    │   ├── left-rail.tsx - grouped flyouts + bottom global utilities
    │   ├── rail-icons.tsx - group and standalone navigation glyphs
    │   ├── tooltip.tsx  - shared accessible portal tooltip
    │   └── shell.tsx   - top bar + left rail shell
    └── routes/
      ├── dashboard.tsx             - Overview data loading + composition
      ├── dashboard.executive.tsx   - posture, evidence metadata, and outcomes
      ├── dashboard.distributions.tsx - routing/control + attention summaries
      ├── dashboard.signals.tsx     - vertical and living-rule signals
      ├── analytics-data.ts         - shared read-only analytics loader
      ├── analytics-hubs.tsx        - four Overview drill-down hubs
        ├── audit.tsx
        ├── hil-queue.tsx
        ├── processes.tsx        - Now > Processes dynamic ViewSpec renderer
        ├── rule-catalog.tsx     - Knowledge > Rules panel (explanation + affected resources)
        ├── settings.tsx         - standalone local presentation controls
        ├── example-finops.tsx  - reference fork panel (opt-in, not registered)
        └── login.tsx
```

## Local development

The canonical local topology is the VS Code compound
`Console Web: Full Stack` in [`.vscode/launch.json`](../.vscode/launch.json):
console SPA `5273`, read API `8010`, and ingestion gateway `8011`. Start that
compound from Run and Debug, or run the equivalent commands below.

```sh
cd console
npm install
# Terminal 1: load local MSAL values and verify browser Entra tokens.
set -a; . console/.env.local; set +a
FDAI_READ_API_LOCAL_ENTRA=1 \
  uv run uvicorn 'fdai.delivery.read_api.dev.local:app' \
  --factory --port 8010

# Terminal 2: run the SPA with browser Entra sign-in.
VITE_DEV_MODE=0 \
  VITE_READ_API_BASE_URL=http://127.0.0.1:8010 npm run dev
```

The browser access token is the authorization principal. The API verifies its
signature, issuer, audience, lifetime, and App Roles. Separately, the server
uses the current Azure CLI session to obtain short-lived tokens when an Azure
adapter needs Microsoft Graph, Azure Resource Graph, or Azure OpenAI. The CLI
identity never replaces the browser principal. Local seed data, static users,
and scenario replay are pytest-only and aren't supported by the interactive
profile.

The Documents route uses a dedicated ingestion gateway rather than the read
API. The in-memory gateway is test-only and isn't part of `Console Web: Full
Stack`. Documents render unavailable until an Azure-backed ingestion adapter is
configured. Automated gateway tests may start the isolated factory on port
`8011`:

```bash
FDAI_INGESTION_GATEWAY_DEV_MODE=1 \
  uv run uvicorn fdai.delivery.ingestion_gateway.dev:app \
  --factory --host 127.0.0.1 --port 8011
```

Set `VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011` for the console. The
factory supports local direct upload only and refuses to boot unless the dev
mode environment variable is explicit. Accepted text and OOXML documents are
split by structural unit, embedded with the deterministic local model, and
stored in a searchable in-memory index. The index is cleared when the gateway
restarts. The factory allows the standard local console ports `4173`, `5273`,
`5180`, and `5190` on both `127.0.0.1` and `localhost`. For another port, pass
one or more exact origins to the gateway process:

```bash
FDAI_INGESTION_GATEWAY_DEV_MODE=1 \
FDAI_INGESTION_GATEWAY_CORS_ALLOW_ORIGINS=http://127.0.0.1:5178 \
  uv run uvicorn fdai.delivery.ingestion_gateway.dev:app \
  --factory --host 127.0.0.1 --port 8011
```

The local read API allows both Vite's development origin on port `5273`
and the production-preview origin on port `4173`. To smoke-test the built
artifact, run `npm run build && npm run preview` against the same API.

When Vite uses another port, add that exact origin to the read API process.
Wildcards aren't accepted.

```sh
FDAI_READ_API_LOCAL_ENTRA=1 \
  FDAI_READ_API_CORS_ALLOW_ORIGINS=http://127.0.0.1:5178 \
  uv run uvicorn 'fdai.delivery.read_api.dev.local:app' \
    --factory --port 8010
```

The interactive API requires either `FDAI_READ_API_LOCAL_ENTRA=1` (canonical)
or the explicit CLI-principal alternative. It rejects anonymous dev mode,
scenario replay, and synthetic inventory outside pytest fixtures.

Settings > Models uses the local Azure CLI session to combine the target
region's GPT catalog, subscription quota, and deployments on the Azure OpenAI
account named by `resolved-models.json`. Results are cached for five minutes;
**Refresh catalog** bypasses that cache. Set `FDAI_MODEL_CATALOG_LIVE=0` when
working offline. Discovery is read-only and returns only model family, version,
SKU, quota, and deployment names. It never returns resource ids, endpoints, or
credentials.

A deployed model such as GPT-5.4 can be selected as the T2 primary immediately
in the governance draft builder. A catalog model with quota but no deployment
is labeled **Auto-provision ready**. Selecting it prepares a registry fragment;
the reviewed resolver and Terraform pipeline create the deployment later. The
console never calls Azure deployment create/update APIs directly.

### Auto-open the narrator endpoint (local dev)

When the Command Deck shows a `deterministic` badge even though a keyless
narrator is wired, the usual cause is that the Azure OpenAI account behind the
narrator has `publicNetworkAccess: Disabled` (a tenant policy can flip it), so
every call from the laptop returns `403 "Public access is disabled"` and the
`/chat/health` mode reads `azure-ad-routed-unavailable`.

The **local** read API reconciles this at startup **by default**: it finds the
account behind the narrator endpoint and, only when the endpoint is
unreachable, adds this machine's current public IP to the account firewall and
enables restricted public access (`defaultAction: Deny` plus the single IP). An
already-reachable account is left untouched. Disable the hook with
`FDAI_NARRATOR_AUTO_OPEN_AOAI=0` (also accepts `false` / `no` / `off`).

```sh
# Auto-open runs by default; set the flag to 0 to opt out.
FDAI_READ_API_LOCAL_AZURE_CLI=1 \
  uv run uvicorn 'fdai.delivery.read_api.dev.local:app' \
    --factory --host 127.0.0.1 --port 8010
```

The hook is **local-dev only and fail-safe**: it shells out to `az`
against the developer's own signed-in subscription, and any failure (no `az`
CLI, not logged in, RBAC denied, dynamic IP changed) is logged and swallowed so
the API still boots and the console keeps working via the deterministic
fallback. It is never wired into a production build.

## Local Azure CLI sign-in

Use this mode when you want the local console to reuse the interactive account
already selected by `az login`, without opening the MSAL sign-in page. Confirm
the active account first, especially when you use more than one Azure CLI
profile:

```sh
az login --use-device-code
az account show --query '{subscription:name,user:user.name,tenant:tenantId}' --output table
```

The read API inherits `AZURE_CONFIG_DIR` from its process. If you use a named
Azure CLI profile, set the same `AZURE_CONFIG_DIR` when starting the API. The
API checks `az account show`, obtains a short-lived ARM token, and keeps that
token inside the API process. It exposes only the stable object id, username,
display name, and local role projection to the SPA.

```sh
# Terminal 1: Azure-backed API projected as the current Azure CLI user.
FDAI_READ_API_LOCAL_AZURE_CLI=1 \
  uv run uvicorn 'fdai.delivery.read_api.dev.local:app' \
  --factory --host 127.0.0.1 --port 8010

# Terminal 2: SPA with MSAL bypassed in favor of the local CLI profile.
cd console
VITE_LOCAL_AZURE_CLI_AUTH=1 \
  VITE_READ_API_BASE_URL=http://127.0.0.1:8010 \
    npm run dev
```

The local principal has a fixed `Contributor` development ceiling. It doesn't import production App Roles or
grant Azure resource permissions to the browser. The API refuses this mode
when `RUNTIME_ENV` is `staging` or `prod`, and it can't be combined with
`FDAI_READ_API_DEV_MODE=1` or `FDAI_READ_API_LOCAL_ENTRA=1`.

## Test-only authentication fixtures

Automated tests can invoke `app(test_fixtures=True)` to exercise anonymous and
real-Entra verification over isolated data. The builder checks for pytest and
fails in an interactive process. This fixture path is not a local Console data
profile and must never be presented as Azure observation.

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
| `VITE_INGESTION_API_BASE_URL` | Origin of the Azure-backed document-ingestion gateway. Port `8011` is reserved for isolated automated gateway tests. |
| `VITE_MSAL_CLIENT_ID` | Entra App Registration client id (SPA). |
| `VITE_MSAL_TENANT_ID` | Entra tenant id (single-tenant per fork). |
| `VITE_MSAL_API_SCOPE` | API audience scope (e.g. `api://<api-guid>/access`). |
| `VITE_DEV_MODE` | Test-only authorization bypass paired with read-API fixtures. The interactive full-stack profile never sets it. |
| `VITE_LOCAL_LOGIN_PROMPT` | Test-only chooser toggle used with `VITE_DEV_MODE`; not an interactive Azure data mode. |
| `VITE_LOCAL_AZURE_CLI_AUTH` | `1` to project the current local `az login` user through the local read API. Explicit alternative to browser Entra sign-in; never set in production or together with `VITE_DEV_MODE`. |
| `VITE_CONSOLE_BASE_PATH` | Optional subpath if not served at origin root. |
| `VITE_WORKFLOW_CATALOG_REPO` | Optional `owner/repo` of the catalog repo. When set, a validated workflow draft shows a one-click "Open a PR on GitHub" (new-file link); the console still never commits. |
| `VITE_WORKFLOW_CATALOG_BRANCH` | Branch the new-file PR link targets (default `main`). |
