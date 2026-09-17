# `console/`

Thin, non-privileged operator SPA - KPI dashboard, incident roster, audit log
viewer, per-agent activity timeline, and Approvals view. This is the layer-3 surface described in
[`.github/instructions/app-shape.instructions.md`](../.github/instructions/app-shape.instructions.md)
§ Operator console. The authority boundary is a hard rule: the SPA never issues privileged
managed-resource calls or shares the executor identity. Bounded request controls submit typed
records to the Operator API, where server-owned authorization and lifecycle checks run again.

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

The SPA starts with six always-on GET routes on the Operator API
(`services/operator-service/src/fdai_operator_service/`):

| Route | Purpose |
|-------|---------|
| `GET /audit` | Paginated audit log rows (newest first), optionally filtered by `correlation_id`. |
| `GET /kpi` | Dashboard KPIs (event count, shadow/enforce share, approvals pending, per-kind, per-outcome). |
| `GET /hil-queue` | Pending approval count for Readers; safety detail and server-owned decision availability for Approvers and Owners. |
| `POST /hil/{approval_id}/operator-decision` | Record an eligible human approval or rejection and durably queue it for the Var-owned lifecycle without executing the action. |
| `GET /incidents` | Paginated incident roster with active/resolved/all filters. |
| `GET /audit/{correlation_id}/trace` | Ordered end-to-end trace for one incident. |
| `GET /healthz` | Operator API health status. |

Managed-resource views use GET-only read routes. The console has narrow POST
carve-outs for narrator turns, typed action **proposals**, and pure workflow
validation; none executes a managed-resource mutation directly. Core read
routes enforce `405` on mutating verbs
(`services/operator-service/tests/`).

The **Evidence > Documents** panel is a separate content-ingestion surface, not
a managed-resource mutation path. Its dedicated client talks only to the
ingestion gateway, uploads source bytes directly to the gateway-provided object
target, and requires the operator to acknowledge the effective shared audience.
The GET-only `OperatorApiClient` remains unchanged and never gains upload helpers.

The panel registry in [`src/panels.tsx`](src/panels.tsx) groups the complete
operator surface into six stable navigation domains: Overview, Operations,
Agents, Governance, Knowledge, and Evidence. An icon-only Activity Bar selects a domain,
opens the adjacent Explorer, and navigates to that domain's first visible panel.
Selecting the open domain again collapses the Explorer without changing the
current route; selecting the same domain while collapsed restores its Explorer.
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
accents, evidence tables, and approval safety cards. Shared foundation tokens in
[`../ui/calm-slate-tokens.css`](../ui/calm-slate-tokens.css) apply that language to both the
Console and static prototypes. Shared presentation behavior such as the semantic top-edge shimmer
lives in [`../ui/calm-slate-primitives.css`](../ui/calm-slate-primitives.css).
[`src/styles.css`](src/styles.css) owns route and shell styling while preserving the documented
navigation and clean History API URLs.

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
The Processes panel consumes `GET /views/process`,
`GET /views/process/{process_id}/events`, and the optional
`GET /views/process/{process_id}`. It renders server-selected, bounded
ViewSpecs instead of computing workflow or ontology decisions in the browser.
The workspace presents loaded-run counts, a selectable run list, and nine
snapshot facts before expandable control, investigation, planning, journal,
and workflow-evidence sections. An event deep link opens its journal and event.
Use **Provenance** to inspect the source without clearing the selected run.
Explicit **Sample** mode provides three generic runs with read-only evidence
and no permitted transitions; an empty Live source never activates Sample.
The focused `processes-mock-parity.spec.ts` check compares the master mock and
Console at equal content width with pinned navigation, not just overflow.

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

The Overview presents pending decisions first, then current posture alongside
routing and control, followed by four operating outcome metrics. The
auto-resolution ring shows the measured rate and its baseline marker; missing
measurements remain unavailable rather than becoming a zero-valued chart.
Expand **Operational evidence** for source and time-window metadata, the full
control summary, vertical results, audit counts, and living-rule evidence.
The audit sample count and sequence links retain the exact audit boundary.
Synthetic measurements are labeled as simulated instead of proven. The
route-local composition in [`dashboard.css`](src/routes/dashboard.css) follows
the essential design mock without changing the shared shell or analytical
routes. Agent organization remains on its owned Agents routes.
Essential attention cards use a short count summary instead of repeating their
instructions. English and Korean share the same spacing and visual hierarchy;
unavailable values stay explicit but quieter than measured values. Reading space
takes priority over fitting secondary evidence into the first viewport.
Layout follows evidence availability, not the Sample/Live switch. Missing routing
distributions become short linked status rows. When the auto-resolution measurement
is absent, the other posture facts take its space and the missing metric retains a
detail link. Four unavailable outcome metrics become a compact list; any measured
value, including zero, retains the metric-card presentation. An empty audit sample
or explicitly recorded zero counts are distinct from unavailable classifications.
Optional reads show skeletons while pending, and a failed dashboard read offers an
explicit retry and Diagnostics link without inventing a source failure reason.

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

The Settings > Environment and deployment surface opens on onboarding
readiness and keeps read-only deployment-run evidence on a separate tab.
`/onboarding` and `/provisioning` remain stable compatibility routes, but they
are no longer duplicate primary-navigation entries. The deployment tab consumes
`GET /provision/stream` with fetch-based SSE. It acquires the same MSAL bearer
header as other read calls, aborts the stream when the route unmounts or the tab
is hidden, and reconnects transient failures with capped exponential backoff
when visible. Permanent `401` / `403` responses stop reconnecting. The token
stays in the Authorization header and never enters the URL.

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
storage is blocked. The runtime section exposes the configured Operator API
endpoint for diagnostics. Settings never call the Operator API, mutate managed
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
view (which pantheon agent did what, when, and how) and offers two toggled
layouts. **Activity** is a bounded chronological log that combines durable
audit rows with browser-session runtime frames while labeling each source.
It expands recorded and live agent-to-agent turns into detailed `from -> to`
rows, supports agent and keyword filters, configurable columns, fullscreen,
and live tailing that starts enabled. The rendered log is capped at 200 rows;
the runtime reducer separately caps retained stream frames at 100. **Waterfall**
remains the durable audit master-detail view. Its left column is a
compact, collapsible incident tree (grouped by `correlation_id`); selecting a
step opens a large detail pane on the right that renders the append-only entry
verbatim - a lifecycle stepper (event sent -> received -> work started ->
finished, with per-hop latency), the narrative of what the agent did, any
agent-to-agent conversation (the conversational-port turns exchanged while
doing the work, shown as `from -> to` bubbles), its structured inputs /
outputs, and the full record (tier, mode, outcome, decision, hashes). A small
speech-bubble badge on a left row marks the steps that carry a conversation.
Agent chips filter Waterfall, while the Activity log uses its compact agent
selector. Every correlated entry deep-links to its full pipeline trace via
`/trace?correlation=<id>`.

The panel also subscribes to `GET /agents/stream`. A bounded stream signal
updates the current connection/engaged indicators and triggers a background
refresh of the authoritative audit projection at most once per 1.5 seconds.
The stream message appears only as a source-labeled runtime row; it is never
reclassified as durable audit evidence. This preserves the append-only ledger
as the source of truth while allowing a visible tab to update without polling.
The hook closes the SSE connection while the tab is
hidden and reconnects when it becomes visible. The dev
Operator API seed
([`services/operator-service/src/fdai_operator_service/`](../services/operator-service/src/fdai_operator_service/))
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
[`services/core-control-plane/src/fdai/core/executor/executor.py`](../services/core-control-plane/src/fdai/core/executor/executor.py)
`_write_audit`) - are shown, not dropped by a hardcoded allow-list, and new
producer fields appear automatically. The invariant is two-way: everything
shown comes from the stored `entry` (read-only passthrough), and everything
stored is shown.

Beyond the three always-on routes above, the app factory registers several
**opt-in** GET routes when their inputs are wired at the composition root
(ontology graph, pantheon, impact scope, promotion gates, rule-fire trace, and
the inventory graph, and the rule catalog below). Each is reader-role gated and collision-checked; none
ships enabled upstream unless its `OperatorApiConfig` input is set.

### Governance presentation

The Governance routes share the Calm Slate information hierarchy from
[`mocks/ui/`](../mocks/ui/) while keeping their existing read contracts.
Architecture uses the same quiet hierarchy through a graph-first orthographic SVG workbench with
adjacent inspection.

- **Ontology** presents the structured catalog and operational instance projections as
  URL-addressable views. Objects uses a deterministic 2D one-hop neighborhood,
  Links shows endpoint and cardinality contracts, and Actions provides a
  filterable ActionType safety-contract catalog. Instances resolves an exact Resource
  autocomplete selection through the existing read-only URL state and uses FDAI tooltips for
  Resource and relationship details. The Mermaid source remains an ObjectType fallback and
  evidence view.
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

### Architecture panel (Governance)

The **Governance > Architecture** panel renders the deployed inventory instance graph from
`GET /inventory/graph`. It shows subscription and resource-group containment, VNet and
subnet boundaries, resource status, and `attached_to` / `depends_on` links in one read-only
SVG workbench. Pan, zoom, filtering, selection, and deep links are local view operations only.
The console cannot add, move, resize, or delete resources.
The bounded Landscape is visible before selection. It derives containment without requiring API
coordinates, keeps Subscription as a neutral boundary, and shows at most 8 Resource Group summary
cards ranked by returned descendants. Selecting a Resource opens a type-diverse, 36-record focus
that reserves direct relationship endpoints first and opens the nonmodal Inspector in the same
frame.
The Network lens keeps at most 2 VNet boundaries, 4 related Subnet boundaries, and 4 related
network-role records while Resource remains at **Scope overview**. Path calculation still uses the
complete returned evidence graph, and selecting a Resource narrows only the presentation focus.

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
rendering, so a Resource cannot appear outside its declared parent scope.

The top toolbar owns registered scope, bounded Resource search, the `Topology | Network` lens,
and compact read-only source state. A coverage strip keeps displayed and returned Resource and
relationship counts distinct. The collapsible right Inspector provides Overview, Links, Network
Path, and Sources views; it moves below the graph at constrained widths without losing state.

The Topology and Network lenses share one accessible orthographic SVG primitive with pan, wheel
zoom, Fit, full screen, roving keyboard focus, and 44 px mobile targets. Subscription, Resource
Group, VNet, and Subnet records render as nested neutral boundaries. Known resource types use the
same reviewed official Azure icons as the static compiler; unmapped types keep stable abbreviation
fallbacks. Typed paths terminate at node and region boundaries and preserve endpoint and direction
semantics without converting layout into evidence. Card, containment, placement, and hit-target
geometry use the same dimensions, so dense revealed Resources cannot overlap or intercept an
adjacent card's pointer target.
Any visible record without finite generated geometry produces an explicit unavailable
presentation instead of falling back to coordinate zero.

The Network Path Inspector view traces the shortest reported `attached_to`, `depends_on`, or
`peered_with` path. A fresh, complete graph can report `No observed path`; stale, partial,
truncated, or relationship-incomplete evidence reports `Path unknown`. Filters remain
presentation-only. SVG and PNG export use one sanitized, identifier-free SVG source that retains
snapshot time, freshness, completeness, resource-type labels, and
`Read-only observed topology`.

The same SVG primitive is reused by **Safety > Impact scope** in a context mode that highlights
the target and reached resources while dimming the rest. Live activity scopes and rule
detected issues deep-link into the full Architecture panel when they carry a resource reference.

### Rule catalog panel (Knowledge)

The **Knowledge > Rules** panel ([`src/routes/rule-catalog.tsx`](src/routes/rule-catalog.tsx))
answers "what does this rule enforce, why does it matter, and which resources
violate it" and shows versioned control-framework coverage over five GET routes
([`services/operator-service/src/fdai_operator_service/`](../services/operator-service/src/fdai_operator_service/)):

| Route | Purpose |
|-------|---------|
| `GET /rules` | Paginated, faceted list over the active catalog + collected corpus, tagged `origin=active\|collected`. Server-side filter (`origin`/`category`/`severity`/`source`/`q`) + `limit`/`offset`. |
| `GET /rules/{id}` | Full detail: sandboxed Rego + fix template bodies, plus an `explanation` (why it matters / risk) parsed from the Rego `# METADATA` block or the `azure_policy` / `kube_bench` params - grounded, never fabricated. |
| `GET /rules/{id}/findings` | Affected resources (resource + the attribute at fault) behind a `findings_provider` seam. Upstream ships none -> honest `evaluated=false`; a fork wires an inventory-evaluation source. |
| `GET /mcsb-controls` | Versioned MCSB definitions, domain and implementation-coverage facets, exact policy-profile counts, and paging. Coverage is a catalog crosswalk, not a workload compliance result. |
| `GET /mcsb-controls/{version}/{control_id}` | Reviewed rule, runtime-observation, manual-evidence, and pinned-source references for one MCSB control. |

The bounded origin, category, and severity facets use compact chips. Source is an open-ended facet,
so it uses a count-bearing select that stays within the filter toolbar at narrow viewport widths.
The Controls view switches between Azure WAF, MCSB v1, and MCSB v2 preview. MCSB v1 renders the
complete 86-control import and its implementation crosswalk. MCSB v2 renders all 81 pinned preview
definitions as Unmapped until its independent crosswalk is reviewed.

The seams are `OperatorApiConfig.rule_catalog_rules`, `_collected_rules`,
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

For resource-history continuity, the deck returns only a server-selected bounded resource context.
Resource Health history can add a complete anomalous-event anchor consisting of resource group,
timestamp, and status. The browser preserves these fields without interpreting them; the Operator API
rejects partial anchors and uses its configured Azure reader scope for any pre-incident Activity
Log correlation. Provider failures and truncated reads remain visible instead of falling through
to an ungrounded narrator answer.

### Submitting an action or incident

Every natural-language turn, including an explicit operator command
(`restart vm-1`), uses `/chat/stream`. The configured mini narrator selects a
strict typed plan from the server-owned capability manifest. A write selection
returns an ephemeral action draft with Confirm and Cancel controls; it does not
publish anything. Confirm posts only the typed draft to `/chat/action/confirm`,
which rechecks the allowlist, arguments, identity, and RBAC before publishing an
`ActionProposal` into the typed pantheon pipeline. **Nothing runs until Forseti
judges it and, for a high-risk action, an approver signs off** (execution is
shadow-first, and RBAC is enforced server-side - a Reader gets `403`). The deck
renders the outcome (submitted with a correlation id / refused by role /
unmapped) and never holds any execution authority. See
[the semantic action draft contract](../docs/roadmap/interfaces/operator-console-wire-contracts.md#136-semantic-action-draft-and-typed-confirmation).

Incident creation uses a dedicated semantic draft and typed confirmation flow.
The Operator API reloads the principal-owned draft before returning HTTP `202`,
then publishes a versioned request on the Incident creation topic. Core opens or
reuses the audited record through `IncidentRegistry`; the `/incidents`
projection, rather than HTTP acceptance, proves completion. This path never
invokes Thor, a cloud executor, or an ActionType promotion mode.
The local development composition runs the same proposal through a persistent
in-memory pantheon bus, so a submitted restart reaches Forseti and finishes as
a Thor shadow action instead of stopping at HTTP acceptance. Production binds
the same contracts to the configured event bus.

### Agent Activity and role ownership

The Agents workspace separates three operator questions:

- **Fleet** shows the current observed state of the fixed 15-agent runtime.
- **Agent Activity** owns chronological audit and handoff evidence, including the Waterfall.
- **Roles and ownership** opens as a route-backed dialog over Agent Activity and shows only fixed
  reporting lines, owned object types, authority boundaries, and supporting runtime state.

The role workspace is implemented once in
[`src/routes/agent-organization.tsx`](src/routes/agent-organization.tsx). Agent Activity opens it
with `roles=1`, preserves the current filters and selected agent, closes with Browser Back or
Escape, traps keyboard focus, and restores focus to the opener. `/pantheon` remains a shareable
direct-page fallback that renders the same component.

### Fixed role tree and selected ownership

The organization tree is built from the fork-locked `AGENT_ROLE`, `AGENT_CONTRACT`, and `ORG_CHART`
records in [`src/routes/agents.model.ts`](src/routes/agents.model.ts): Odin at the root, Thor and
Forseti on the two operating lines, their direct reports below, and four governance staff on dotted
lines. Selecting a node opens a role-only detail with responsibility, manager, layer, runtime
binding, owned object types, observed state, and a link to that agent's filtered Waterfall.

Incident timelines, Detect -> Ticket -> RCA -> Resolve progress, and agent conversation transcripts
are intentionally absent from the organization surface. Their owning routes are Agent Activity,
Incidents, Trace, and RCA. The dialog is read-only and does not grant judgment, approval,
execution, or recovery authority.

The interactive local Operator API does not start a local ControlLoop or Pantheon runtime. Fleet
and role-state evidence remain unavailable until a deployed Azure FDAI runtime relay supplies
authoritative frames. Authentication mode is not treated as evidence provenance.

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

The chat backend (`services/operator-service/src/fdai_operator_service/`) keeps each turn's
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
surfaces share the same width and alignment. The observed trace expands from
the compact pending row instead of replacing it at full height, and staggered
source rows avoid an abrupt layout jump. Tokens that arrive during the minimum
interval enter an adaptive visual queue: each display frame drains one to three
already-paced deltas, depending on backlog, rather than dumping the whole
buffer at once. A terminal-only canonical answer uses up to 60 one-chunk display
frames when the tab is visible; hidden or unfocused tabs finish synchronously.
It fabricates nothing: every row comes from the live snapshot, backend health
descriptor, or server-owned evidence selection.

Rich replies render ATX headings, emphasis, strong text, strikethrough,
unordered and ordered lists, read-only task lists, blockquotes, thematic
breaks, safe links, tables, fenced code, and chart blocks. An open code fence
stays a stable plain preview while streaming and receives syntax highlighting
only after the closing fence arrives. Unsafe link schemes remain plain text.

The completed reply distinguishes evidence references from sources. A screen
or server-owned provider is a source; the individual manifest entries checked
inside that source are shown as `evidence references`. Expanded screen-record
sources show the row count plus at most four scalar fields from the first
browser-visible record. Nulls, nested values, and off-snapshot data are omitted,
and every preview is length-bounded. A bounded correction that removes
unsupported sentences and passes re-verification is presented as verified, not
as a warning. An unverified terminal keeps its canonical result and reason in
the turn record but presents a typed clarification question in the transcript,
so the operator can name the target, time range, condition, or evidence source
for the next read.

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
   (`services/operator-service/src/fdai_operator_service/`) and register it at the
   composition root via `OperatorApiConfig.extra_panels`. The app factory wraps
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

Extension panels are read-only. The owned Approvals route is the narrow exception: eligible human
approvers can submit a server-revalidated decision, while execution remains with Thor.

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
    ├── api.ts          - OperatorApiClient (authoritative reads + typed bounded requests)
    ├── preferences.ts  - validated browser-local display preferences
    ├── types.ts        - TS mirrors of read_model.py shapes
    ├── panels.tsx      - panel registry (core panels + fork extension point)
    ├── router.ts       - clean path mapping + History API navigation
    ├── styles.css      - route and shell styles over shared Calm Slate tokens
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
console SPA `5273`, Operator API `8010`, Document Ingestion API `8011`, Document Processing
Worker health `8012`, and isolated Executor health `8013`. Start that compound from Run and Debug.
It uses Docker PostgreSQL, Redpanda, and ClamAV locally and starts all five independently packaged
backend services.

```sh
# Run and Debug -> Console Web: Full Stack
```

The browser access token is the authorization principal. The API verifies its
signature, issuer, audience, lifetime, and App Roles. Separately, the server
uses the current Azure CLI session to obtain short-lived tokens when an Azure
adapter needs Microsoft Graph, Azure Resource Graph, or Azure OpenAI. The CLI
identity never replaces the browser principal. Local seed data, static users,
and scenario replay are pytest-only and aren't supported by the interactive
profile.

The Documents route uses the independent Document Ingestion API rather than the Operator API.
Local uploads persist source bytes under `.fdai/document-store`, metadata and vectors in Docker
PostgreSQL, lifecycle events in Docker Redpanda, and scans through Docker ClamAV. Azure deployments
use their service-owned Azure Database for PostgreSQL DSNs and managed Azure adapters instead.

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

The local Operator API allows both Vite's development origin on port `5273`
and the production-preview origin on port `4173`. To smoke-test the built
artifact, run `npm run build && npm run preview` against the same API.

When Vite uses another port, add that exact origin to the Operator API process.
Wildcards aren't accepted.

```sh
FDAI_OPERATOR_API_LOCAL_ENTRA=1 \
  FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS=http://127.0.0.1:5178 \
  uv run uvicorn 'fdai.delivery.operator_api.dev.local:app' \
    --factory --port 8010
```

The interactive API requires either `FDAI_OPERATOR_API_LOCAL_ENTRA=1` (canonical)
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

The **local** Operator API reconciles this at startup **by default**: it finds the
account behind the narrator endpoint and, only when the endpoint is
unreachable, adds this machine's current public IP to the account firewall and
enables restricted public access (`defaultAction: Deny` plus the single IP). An
already-reachable account is left untouched. Disable the hook with
`FDAI_NARRATOR_AUTO_OPEN_AOAI=0` (also accepts `false` / `no` / `off`).

```sh
# Auto-open runs by default; set the flag to 0 to opt out.
./scripts/deployment/local/start-console-web.sh --auth-mode azure-cli
```

The hook is **local-dev only and fail-safe**: it shells out to `az`
against the developer's own signed-in subscription, and any failure (no `az`
CLI, not logged in, RBAC denied, dynamic IP changed) is logged and swallowed so
the API still boots and the console keeps working via the deterministic
fallback. It is never wired into a production build.

## Local Browser Entra session resilience

The standard loopback Console uses MSAL Browser v4 encrypted `localStorage` so
the signed-in account cache can survive a tab or VS Code webview recreation.
Deployed origins continue to use `sessionStorage`. The Console requests a token
at startup, every 30 minutes, and after focus, visibility, or network recovery;
overlapping requests are coalesced.

The encryption key remains browser-session-bound. Closing the browser can still
require sign-in unless Entra Keep Me Signed In applies. The cache and refresh
loop don't bypass the 24-hour SPA refresh-token window, Conditional Access,
MFA, revocation, or an administrator-required sign-in. Never inspect, copy, or
commit the MSAL cache values.

## Local Azure CLI sign-in

Use this mode only for a bounded authentication diagnostic when you want the
local console to reuse the interactive account already selected by `az login`.
The standard full-stack task always uses Browser Entra. Confirm the active
account before starting the explicit debug mode:

```sh
az login --use-device-code
az account show --query '{subscription:name,user:user.name,tenant:tenantId}' --output table
```

The managed launcher checks `az account show`, obtains a short-lived ARM token,
and keeps that token inside the API process. It exposes only the stable object
id, username, display name, and local role projection to the SPA.

```sh
./scripts/deployment/local/start-console-web.sh --auth-mode azure-cli
```

The local principal has a fixed `Contributor` development ceiling. It cannot
open approval details that require `Approver` or `Owner`, import production App
Roles, or grant Azure resource permissions to the browser. Don't persist the
underlying Vite or API flags in `console/.env.local`; the launcher sets paired
enablement and confirmation values for this invocation. The API refuses this
mode when `RUNTIME_ENV` is `staging` or `prod`, and it can't be combined with
`FDAI_OPERATOR_API_DEV_MODE=1` or `FDAI_OPERATOR_API_LOCAL_ENTRA=1`.

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

The protected Azure publisher uploads the `dist/` output to Azure Static Web
Apps and adds the allowlisted Manual Studio files under `/manuals`. It builds
the Console with `VITE_MANUAL_STUDIO_URL` bound to that same-origin path, then
verifies the deployed Console entry asset, manual catalog, and manual library
against the local files. Custom domain, CSP headers, and MSAL app-registration
values are supplied by the fork; the upstream repo ships schema and empty
defaults only.

## Fork configuration

Set these at build time (Static Web App app settings, `.env.production`, or
CI env):

| Env var | Meaning |
|---------|---------|
| `VITE_OPERATOR_API_BASE_URL` | Origin of the Operator API (e.g. `https://api.<fork>`). |
| `VITE_INGESTION_API_BASE_URL` | Origin of the Azure-backed document-ingestion gateway. Port `8011` is reserved for isolated automated gateway tests. |
| `VITE_MSAL_CLIENT_ID` | Entra App Registration client id (SPA). |
| `VITE_MSAL_TENANT_ID` | Entra tenant id (single-tenant per fork). |
| `VITE_MSAL_API_SCOPE` | API audience scope (e.g. `api://<api-guid>/access`). |
| `VITE_DEV_MODE` | Test-only authorization bypass paired with Operator API fixtures. The interactive full-stack profile never sets it. |
| `VITE_LOCAL_LOGIN_PROMPT` | Test-only chooser toggle used with `VITE_DEV_MODE`; not an interactive Azure data mode. |
| `VITE_LOCAL_AZURE_CLI_AUTH` | Launcher-owned CLI-debug enablement. Don't persist it in `.env.local`; use `--auth-mode azure-cli`. |
| `VITE_LOCAL_AZURE_CLI_AUTH_CONFIRM` | Launcher-owned confirmation paired exactly with `VITE_LOCAL_AZURE_CLI_AUTH`. A mismatch stops Console startup. |
| `VITE_CONSOLE_BASE_PATH` | Optional subpath if not served at origin root. |
| `VITE_MANUAL_STUDIO_URL` | Optional HTTPS origin or path for the published manual catalog. Local development defaults to `http://127.0.0.1:5474`; the protected Azure publisher uses the Console's same-origin `/manuals` path. |
| `VITE_WORKFLOW_CATALOG_REPO` | Optional `owner/repo` of the catalog repo. When set, a validated workflow draft shows a one-click "Open a PR on GitHub" (new-file link); the console still never commits. |
| `VITE_WORKFLOW_CATALOG_BRANCH` | Branch the new-file PR link targets (default `main`). |
