---
title: Operator Console - Incident Roster and Fix History
---

# Operator Console - Incident Roster and Fix History

> Focused owner document extracted from [operator-console.md](operator-console.md) section 13.5.

### 13.5 Incident roster and fix history

The read-only SPA exposes a first-class **Now > Incidents** panel. It is the
roster-first entry point for incident response: an operator can find active or
resolved incidents before knowing a correlation id, select one, and inspect
its remediation history. The existing Audit and Trace panels remain the
record-level and end-to-end drill-down surfaces.

The API contract is:

| Route | Purpose |
|-------|---------|
| `GET /incidents?status=active|resolved|all&limit=<n>&cursor=<opaque>` | Return incident summaries newest activity first. |
| `GET /audit?correlation_id=<id>&limit=<n>&cursor=<opaque>` | Return the selected incident's append-only history. |
| `GET /audit/{correlation_id}/trace` | Reconstruct ordered correlated audit activity and any recorded pipeline stages. |
| `POST /chat/stream` | Produce a typed incident draft from natural language without creating a record. |
| `POST /chat/action/confirm` | Confirm the typed draft and create the audited Incident. |

The incident roster stays read-only. Incident creation uses semantic draft plus
typed confirmation routes and never adds a mutation button to the panel.
For a recognized incident-open request, the route behaves as follows:

1. It requires Contributor capability, severity, and a target correlation key.
2. It returns `incident_confirmation_required` with a human-readable summary
  and a 10-minute expiry. No incident exists at this point.
3. A `confirm` or `확인` message from the same principal and `session_id`
  creates the audited incident and returns its id and initial `open` state.

The pending proposal is bounded by a 200-character `session_id`. Oversized
session or idempotency keys are rejected rather than truncated, preventing two
distinct identifiers from collapsing to the same confirmation. Production
stores the proposal in Postgres and consumes it atomically, so confirmation can
land on another replica. The persisted record contains a SHA-256 of the source
prompt, not the raw operator text.

Missing values return `incident_details_required`; cancellation returns
`incident_creation_cancelled`. An unrelated action command continues through
the existing Bragi-to-Huginn typed proposal path. An allowlisted agent uses the
same built-in workflow with member-event evidence and a reason, but does not
impersonate an operator or bypass the incident registry.

The same authenticated route accepts only exact lifecycle command grammar;
it does not guess from free-form status prose:

- `transition incident <uuid> to <state>` or
  `incident <uuid> 상태 <state>으로 변경`
- `assign incident <uuid> to <oid>` or
  `incident <uuid> 담당자 <oid> 지정`

Both require a nonblank conversation `session_id`, Contributor capability, and
the registry's persisted expected-state check. Illegal edges, unknown ids, and
cross-replica conflicts return `incident_lifecycle_rejected` without changing
the canonical incident.

`correlation_id` is the investigation key used to join evidence; it does not by
itself prove that an Incident lifecycle record exists. The projection can attach a row without
a top-level correlation only when its `event_id` equals an already-known
correlation, or when an explicit incident lifecycle link resolves to exactly
one correlation. Ambiguous rows stay unattached; the read model never invents
an association from a resource name. For a pending HIL item, the projection
may read its server-owned park record to recover rule severity and category;
it does not rewrite the append-only audit row. Lifecycle state is authoritative
when present. Otherwise the projection derives `open`, `in_progress`, or
`resolved` from audit stages. A denied, abstained, or failed remediation does
not by itself claim that the underlying incident is resolved.
Local Operator API audit fixtures carry explicit sample provenance and stay visible
in Audit, Trace, and Agent activity. They are excluded from the operational
Incident roster, so a normal or within-threshold monitoring sample cannot look
like an opened Incident.

Each incident summary includes `involved_agents`, derived server-side from the
recorded `producer_principal`, canonical action owner, and stage ownership. The
Agents surface hydrates this durable incident snapshot first, then applies
newer `/agents/stream` stage deltas. This keeps a newly opened tab consistent
with Incidents while preserving live stage transitions.

The summary title also remains server-owned. The projection uses an explicit recorded `title`,
`summary`, or rule id first. When those fields are absent, it builds a bounded subject from the
recorded `signal:` and `resource:` correlation keys. An Azure resource id contributes only its
resource type and final resource name, so the roster can show a subject such as
`Resource inventory change - Storage account storage-example` without exposing the complete path.
Only an incident with no recorded subject evidence falls back to its event id; the browser does not
invent a replacement title.

#### Selective Azure SRE Agent adoption

FDAI adopts the operator-facing strengths documented for Azure SRE Agent without adopting its execution model:

| Observed practice | FDAI adaptation | Preserved boundary |
|-------------------|-----------------|--------------------|
| [Rich incident cards](https://learn.microsoft.com/azure/sre-agent/incident-platforms#rich-incident-cards) | Show an operator-readable title, description, source platform and id, severity, source status and time, response-plan reference, and source-detail link only after a server-owned trust marker. Add `title_source`; mark identifier fallback as `Title unavailable` instead of presenting a GUID as the subject. | Canonical lifecycle state stays separate from source-platform status, and every displayed field remains recorded evidence. |
| [Investigation threads and session insights](https://learn.microsoft.com/azure/sre-agent/review-agent-insights) | Project bounded `initial`, `progress`, `issue`, `success`, and `resolved` milestones with evidence references, explicit gaps, evaluation, and an inert learning candidate. | A conversation transcript is not evidence; independent effect verification, not self-evaluation, closes recovery or promotes learning. |
| [Response plans](https://learn.microsoft.com/azure/sre-agent/response-plan) | Preview historical matches before activation, pin the plan revision, expose enabled state, and merge repeated alerts under an explicit cooldown and deduplication key. | A plan routes investigation only; typed `ActionType`, risk, approval, executor, rollback, and audit gates still decide every state change. |
| [Incident value tracking](https://learn.microsoft.com/azure/sre-agent/track-incident-value) | Measure agent-mitigated, agent-assisted, human-mitigated, pending, and time-to-mitigate cohorts with exact windows, denominators, and incident drill-down. | No aggregate claims success without authoritative terminal state and independently verified outcome evidence. |

> FDAI does not adopt arbitrary Azure CLI writes, default autonomous response plans, or permission-as-authority behavior from Azure SRE Agent run modes. The seven safeguards and separated judge, approver, executor, observer, and auditor roles remain authoritative.

Missing correlations remain missing. The projection treats empty values and historical `None` or
`null` string sentinels as absent, so unrelated audit-only rows cannot form a synthetic Incident.

The roster returns summaries only. It does not embed every audit row, and the
cursor bounds each server-side page. Selection performs a separate filtered
GET for history. Every route is Reader-gated and returns `405` for mutating
verbs. The panel provides links to Audit and Trace but no execute, approve, or
rollback button; those operations remain in remediation PRs and ChatOps.

Incident creation, each legal state change, and requested roster summaries are
eligible for A2 operational notification. Replayed opens and same-state
transitions do not notify twice. Lifecycle messages contain the incident id,
severity, and normalized state, but omit free-form reason text and resource
correlation keys. A roster notification is bounded to 20 ids and links back to
the complete `/incidents` view. Event-specific `audit_id` values keep channel
idempotency from suppressing later transitions. Durable sent checkpoints and
startup replay retry any notice missed by a crash. Before delivery, replicas
compete for an atomic claim token with a bounded lease; only one sends, and
only that token can mark the notice sent or release it after failure.
Unresolved channels fall back to the HIL escalation sink.

Incident alert subscription follows the channel-as-audience contract in
[channels-and-notifications.md](channels-and-notifications.md): membership in
the configured A2 operations channel determines who continuously receives
open, transition, roster, and SLA-breach notices. The console does not create
per-user direct-message subscriptions. Assignment and external ticket linkage
remain authenticated write-direction chat/tool operations and appear as audit
history; the read-only roster surfaces the linked `ticket_id`.

The roster accepts an optional canonical `vertical` filter, and the audit
route applies `mode`, `tier`, `action`, `outcome`, `vertical`, and bounded
`window=<n>d` filters on the server before cursor pagination. An analytical
deep link therefore searches the complete filtered result set rather than
filtering only the first browser page. The cursor is bound to the incident
status and vertical, so changing either filter invalidates a stale cursor.

Overview audit KPIs aggregate the newest 500 audit rows in both the in-memory
and Postgres read models. `GET /kpi` returns that immutable sample as
`audit_sample` with inclusive `from_seq` and `through_seq` bounds, `row_count`,
and `limit`. Every Overview link to Audit carries those bounds, and `GET
/audit` applies `from_seq` and `through_seq` before dimension filters and
cursor pagination. Operators can therefore enumerate the same append-only
sample that produced the displayed count or ratio even after newer rows
arrive. `hil_pending` remains a separate current queue projection and is not
part of the audit sample. Tier keys and tier filtering use lowercase canonical
values (`t0`, `t1`, `t2`).

The SPA renders the incident roster as a semantic list of selection buttons.
The selected button exposes `aria-pressed`, and every button points to the
incident detail region with `aria-controls`. Unknown top-level URLs are replaced with canonical
`/overview`, so one visible screen cannot create multiple conversation caches
under typo paths.

Explicit child-view and entity identifiers fail closed. When a URL names an
unknown workflow, ObjectType, LinkType, ActionType, agent, audit entry,
architecture view or resource, incident correlation, promotion reason, IAM
tab, or live event, the console preserves the requested value and renders an
unavailable or waiting state with valid recovery links. It never substitutes
the first row, default workflow, default view, or another entity's evidence.
Only a URL with no explicit identifier can select the documented default.
ActionType directory filters are canonical URL state (`q`, `category`,
`trigger`, and `execution`) and remain intact when an operator selects an
action, so refresh, back navigation, and shared links reproduce the same list.
Blast-radius query drafts write `target`, `depth`, and `links` to the URL
without running the simulation; `links=none` preserves an explicitly empty
selection until the operator chooses a valid traversal set.
Opaque entity identifiers also remain byte-for-byte stable across canonical
URL replacement and nested drilldowns. In particular, Process ids are encoded
but never lowercased or slugified, and a workflow step link preserves its
catalog ownership group. Manual RCA and Trace lookups first write the submitted
correlation id to the canonical URL; editing the input invalidates any earlier
response so evidence cannot appear under a different identifier.

Write-direction forms keep one idempotency key for one unchanged operator
intent. A transport failure or lost response therefore retries the same key;
changing the target, parameters, or justification rotates it, and a confirmed
success retires it. Daily briefing subscription creation derives a stable
principal-scoped subscription identity from that key and returns the existing
record for an identical retry. Access requests, IAM role requests, and governed
Python runs use the same rule. Batch document upload locks collection, purpose,
storage mode, consent, and selected files until completion, and stops issuing
new requests after the route unmounts.

Canonical source mutations and derivative ontology projections have separate
success boundaries. A committed workflow definition or binding returns the
source-store result even when its immediate ontology projection fails. The
PostgreSQL source transaction enqueues the corresponding projection recovery
record, so a retry never misreports a committed create as a conflict or a
committed delete as not found.

Agent runtime state also requires observed evidence. Before an agent state frame or durable incident
projection attributes work, Agents, Agent Activity, and Pantheon render it `unobserved`, not `idle`
or ready. The fixed runtime-binding map doesn't prove consumer health. A headless Pantheon publishes
health-derived `agent.runtime-state` heartbeats, and the Operator API marks only live, non-error agents
`idle` or `watching`. Deployment schedule status stays unavailable until a scheduler supplies it.

The Capabilities route is an inert catalog projection with `source=static-catalog` and
`execution_eligibility=false`; entries describe side-effect classes, roles, and default modes.
Catalog presence doesn't prove provider binding, runtime health, or execution permission. The
Skills route projects installed skill and governed bundle metadata, ordered members, compatibility,
eligibility, references, and bounded diagnostics from `GET /skills`, with no lifecycle or mutation control.
Bragi uses the same Reader-gated disclosure; content reads recheck trust and budgets, while execution decisions stay with composition, RBAC, verification, and the risk gate.
Approved source evidence is available through GET routes under `/api/v1/skill-sources`, but the
current SPA Skills route reads `/skills` and does not yet consume those routes. A future read-only
source view can browse, search, inspect quarantine, and check disabled update candidates. Candidate
approval and source revocation remain separate authenticated POST routes for Approver and Owner
automation. The Skills panel provides no lifecycle control. See
[skill-source-management.md](skill-source-management.md).

Operational read surfaces render provenance from their payload instead of
static claims. Scheduler Runs shows its ledger `source` and `durable` flag; LLM
Cost shows `latest_occurred_at`; Settings Models shows the generated snapshot
filename and `as_of`. Missing fields render unavailable or fail contract
decoding. The browser doesn't infer durability, freshness, or provider health
from a route name, environment mode, or configured default.

Exact entity lookups filter on the server before page limits. Incident
correlation links, Audit entry links, and Approval searches therefore resolve
beyond the first roster page instead of reporting a false absence. Approval
search remains unavailable to count-only roles so filtered totals cannot leak
hidden queue content. Independent sources are isolated: an optional principal
workflow projection cannot hide the built-in workflow catalog, and an unused
analytics source cannot replace another hub with an error screen. Report render
and PDF failures stay local to the selected operation and do not remove the
catalog or variable editor; late downloads are discarded after route changes.

Diagnostics distinguishes process liveness from an authenticated KPI read
path. A successful `/healthz` response never claims that operational data is
healthy. Likewise, last-observed agent frames remain visible as history, but
Engaged, Watching, and Idle are current counts only while the agent stream is
open. Canvas visualizations provide an equivalent keyboard and screen-reader
resource selector, and composite tab widgets move DOM focus together with
roving selection.

Time-bound and aggregate evidence remains conservative while a route stays
open. Approval and Operator Memory rows cross their recorded TTL boundary
without requiring a reload; Architecture continuously advances snapshot age
while retaining the server's snapshot freshness verdict. A missing tier
measurement is unavailable, not measured zero. Scope eligibility counts only
`included` entries. A multi-datasource report has a known aggregate evidence
time only when every source supplies one, and then uses the oldest source time.
Mixed-currency LLM cost groups are labelled non-additive and never displayed as
a single-currency total.
Scope groups explicit monitoring and action entries under each recorded
subscription; it doesn't derive inherited authority, and every level links to Architecture.

The Process list follows the same rule with `source`, nullable `synthetic`, and
nullable `durable`. The local seeded runtime reports
`synthetic-dev/true/false`; production reports `postgres/false/true`. Process
status, journals, and dynamic views remain server-owned, but a current render
doesn't erase how the underlying snapshot was produced or stored.

The selected incident detail keeps the summary and evidence layers separate. It shows alert
lifecycle, agent work state, pending user input, server-owned incident and ticket ids, disposition,
verdict, vertical, mode, timestamps, and history count before the remediation timeline. One compact
response-routing section orders recorded severity, involved agents, the governed human-ownership
mapping, and autonomy mode. Missing values render unavailable; the browser doesn't infer impact,
people, ownership, or recovery. The detail links to the correlation-scoped **Incident RCA Dossier**
in History > Reports.

The remediation history presents each audit row as a plain-language event. It uses recorded
`summary`, `detail`, or `reason` text first, then a deterministic template for known lifecycle,
notification, human approval, and audit event kinds. The responsible agent comes from a recorded
`producer_principal`, Pantheon actor, or the canonical stage-owner mapping. A non-agent runtime is
labelled as a responsible service instead of being attributed to an agent. Each row retains the
exact machine `action_kind` as secondary text and shows at most five recorded facts. Raw entry JSON
is omitted from Incidents; the correlation-scoped Audit link remains the complete record surface.

Overview keeps every required analytical section visible when autonomy
measurement is absent or malformed. It renders an explicit unavailable state
instead of removing the section or inferring zero. When evidence is present,
the success surface includes cost per resolved event, mixed-model
disagreement, verifier failure, shadow divergence, the measurement window,
sample size, confidence, and the named source. **History > Reports** renders
the declarative reporting catalog and its server-owned widget evidence.
Synthetic measurement can illustrate the analytical shape, but it cannot
decide operational health, increase the attention count, or create failed-guard
drilldowns. Overview and Control Assurance treat synthetic guards as unknown
for operational posture while continuing to label their source, window, sample
size, confidence, and source timestamp. A zero-event vertical renders its
resolution rate as unavailable instead of inferring 0%. Overview loads the
required audit KPI and independent optional cost, promotion, and autonomy
projections concurrently; only the documented unavailable statuses degrade an
optional projection. Analytical tab and comparison links preserve the current
query. Failed guards and T2 leading indicators add canonical `guard` and
`indicator` filters, and an unknown filter value renders unavailable instead of
selecting another row.

Contract rules (enforced by `console/src/routes/view-contract.test.ts`):

- **Every publishing route MUST declare `purpose` and `glossary`**, composed
  from the shared catalog `console/src/deck/glossary.ts` so a term means the
  same thing on every screen. A route that publishes a snapshot without them
  fails the build - an under-described screen can never land silently.
- **Causal fields stay in `records`.** `detail`, `summary`, `reason`, `tier`,
  and `outcome` are NOT projected away, so "why did this start" is answered by
  quoting the recorded audit narrative (and the ordered hand-off chain) instead
  of shrugging.
- The narrator resolves questions with a **screen-agnostic** chain (causal ->
  glossary / value-chip -> route enhancer -> generic record search); a new
  screen becomes explainable by declaring its vocabulary, not by adding code.
  The offline deterministic answerer (`console/src/deck/answerer.ts`) and the
  server narrator (`chat.py`) both ground term and cause answers in the same
  `purpose`/`glossary`.
- The CLI REPL and live cockpit send the same self-describing snapshot to the
  server narrator through `POST /chat`. The CLI contains no model client,
  intent router, cloud credential flow, or console-tool implementation.

#### 13.5.1 RCA view (root-cause analysis)

The read-only SPA exposes a first-class **History > RCA** panel. Given an
incident `correlation_id` (typically deep-linked from the Incidents roster,
`#/rca?correlation=<id>`), it renders the tiered, grounded root-cause
hypotheses the control loop already appends to the audit ledger, plus the
linked response plan. It is the "why did this happen, and what was the plan"
surface that pairs with the Incidents roster (13.5).

The API contract is one GET route:

| Route | Purpose |
|-------|---------|
| `GET /rca?correlation=<id>` | Return the per-incident RCA view for one correlation id. |

The route returns `404` when the correlation has no audit rows. It never turns
an unknown correlation into a normal empty RCA dossier, because that would
present missing evidence as a completed analysis.

The projection composes existing audit data; it introduces no new source of
truth. The control loop writes each hypothesis as a shadow `rca.hypothesis`
audit entry (see
[observability-and-detection.md](../rules-and-detection/observability-and-detection.md)
section 4). The panel reads the correlated audit rows and projects:

- **Root-cause hypotheses**, newest first, each with its `RcaTier`
  (`t0` direct / `t1` correlation / `t2` reasoning), confidence, cause text,
  reason, shadow-vs-enforce mode, and grounded `citations`
  (`rule` / `event` / `telemetry` / `incident` / `change` / `scenario` /
  `knowledge`).
- **Grounding state.** An ungrounded / abstained hypothesis
  (`outcome == "abstained"`, `grounded == false`) is surfaced explicitly as
  "insufficient grounding -> HIL", never as a confident cause.
- **Response plan** composed from the same correlated audit stream: the
  verdict (`auto` / `hil` / `deny` / `abstain`), the delivered action kind,
  its mode, and the rollback reference.
- **Structured T1 causal chain.** A T1 hypothesis can carry
  `causal_chain` with root/failure event ids, ambiguity, and ordered hops.
  Each hop preserves cause/effect event and resource refs, lead seconds,
  relationship, and confidence. Malformed or absent chain data renders
  unavailable instead of being partially reconstructed in the browser.

The reporting catalog includes `incident-rca-dossier`. Its required
`correlation_id` variable scopes hypothesis, citation, causal-hop, response,
and chronology widgets to one incident. PDF delivery remains a target optional format. No upstream
`pdf-report` encoder or authenticated Download PDF control is currently implemented. A future
renderer must arrange only the server-owned report envelope, keep unrecorded sections unavailable,
and perform no new RCA.

An RCA hypothesis answers "why", never "execute": execution eligibility stays
with the risk gate + verifier. The route is Reader-gated, returns `405` for
mutating verbs, and provides links into Audit and Trace but no execute /
approve / rollback button. The projection is a pure function
(`services/operator-service/src/fdai_operator_service/`) covered by
`services/operator-service/tests/`.

## Implementation status

### Implementation scope

| Area | State | Evidence | Notes |
|------|-------|----------|-------|
| Incident lifecycle, roster projection, and Console views | implemented | `services/core-control-plane/src/fdai/core/incident/`; `services/core-control-plane/tests/core/incident/`; `console/src/routes/incidents.tsx`; focused Console incident tests | Incident state, correlation, lifecycle, roster, attention, and bounded presentation have focused coverage. |
| Operator-readable identity and phased investigation | implemented | `incident_projection.py`; `projection_logic.py`; `postgres.py`; `incidents.tsx`; `incidents.detail-sections.tsx`; `incidents.milestones.ts`; focused Operator tests (`31 passed`), Console tests (`66 passed`), typecheck, strict mypy, Ruff, Pylance, and catalog parity | Title provenance, trusted source context, plan preview, bounded evidence milestones, and independently verified outcome cohorts are implemented without execution authority. |
| RCA contracts, projection, and read-only route | implemented | `services/core-control-plane/src/fdai/core/rca/`; `services/core-control-plane/tests/core/rca/`; `services/operator-service/src/fdai_operator_service/rca_projection.py`; `services/operator-service/tests/test_operator_service_composition.py`; `console/src/routes/rca.test.ts` | The route distinguishes unknown correlations, projects recorded hypotheses and response evidence, and exposes no action authority. |
| RCA report catalog and datasource | implemented | `rule-catalog/reports/incident-rca-dossier.yaml`; `services/core-control-plane/src/fdai/core/reporting/datasources/audit_rca.py`; reporting tests | The declarative dossier and bounded audit projection exist. |
| RCA PDF format and download control | not-started | [RCA view](#1351-rca-view-root-cause-analysis) | No upstream PDF encoder, optional delivery module, or authenticated download control is present. |
| Governed authenticated runtime evidence | in-progress | Console incident and RCA views; Operator read routes | Focused checks prove implementation, but no current governed Browser Entra roster-to-RCA receipt is retained by this owner document. |

### Implementation history

| Date | State | Change | Evidence | Remaining |
|------|-------|--------|----------|-----------|
| 2026-08-14 | in-progress | Adopted the implementation ledger and corrected the RCA PDF claim to target status; earlier provenance was not reconstructed. | `current change`; current incident, RCA, reporting, Operator, and Console evidence listed in the scope table. | Implement optional PDF delivery and retain governed roster-to-RCA runtime evidence. |
| 2026-08-14 | in-progress | Compared current Microsoft Learn guidance for Azure SRE Agent and accepted only its rich incident identity, phased investigation, response-plan preview, and evidence-backed outcome analytics patterns. | `current change`; [selective adoption contract](#selective-azure-sre-agent-adoption) and current Operator/Console paths in the scope table. | Implement and validate the four bounded operator-facing gaps without widening FDAI execution authority. |
| 2026-08-14 | implemented | Added server-owned title provenance, trusted source and pinned-plan context, bounded audit milestones, and same-snapshot outcome cohorts with exact drill-down while preserving FDAI authority boundaries. | `current change`; `incident_projection.py`, `incidents.detail-sections.tsx`, and task-owned Operator, service-contract, Console, catalog, and focused test paths; Operator `31 passed`, Console `66 passed`, typecheck, strict mypy, Ruff, Pylance, and catalog parity passed; 15 critique rounds left only Low findings. | Retain governed runtime evidence separately. |

### Remaining work

- [x] Add a bounded `title_source` contract and focused projection, decoder, and render tests that prefer recorded title, summary, rule, signal, and sanitized resource subjects, while labeling identifier fallback as unavailable.
- [x] Project source-platform identity, description, status, timestamp, source link, pinned response-plan revision, historical-match preview, and cooldown/deduplication evidence without replacing canonical lifecycle state.
- [x] Render ordered investigation milestones with exact evidence references, unavailable gaps, evaluation receipts, and inert learning candidates; prove transcript text cannot create evidence, close recovery, or promote learning.
- [x] Publish agent-mitigated, assisted, human-mitigated, pending, and time-to-mitigate cohorts with exact source, window, denominator, terminal-state rules, independent outcome verification, and incident drill-down.
- [ ] Retain one authenticated roster-to-RCA receipt that binds the incident, correlation, hypothesis, citations, response plan, audit rows, and unavailable behavior to one source revision.
- [ ] Implement and focused-test an optional PDF `FormatEncoder` and GET-only download path that render only the existing report envelope and remain absent when the extra is unavailable.
- [ ] Add PDF pagination, escaping, source-digest, unavailable-section, and no-new-analysis regression checks before documenting a reference page count.
