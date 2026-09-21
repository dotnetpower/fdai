---
title: FDAI Console Conversations
---
# FDAI Console Conversations
How a human operator talks *back to* FDAI through CLI, Teams, Slack, and web chat. This FDAI Console capability owns the **conversational surface**, not a separate product: layered architecture, tool catalog, LLM tiers, session persistence, per-tool RBAC, safety invariants, and rollout status. FDAI Console is a governed operator surface, not a read-only product. It can submit server-authorized typed requests, while managed-resource execution remains outside the browser and high-risk actions still require human approval. Module splits preserve public Operator and assurance facades, generated CQAS inventory, and canonical visual mappings without changing request or execution authority.
Push-direction notifications (system → human) live in [channels-and-notifications.md](channels-and-notifications.md); operational views and requests are defined in [console-operations.md](console-operations.md), and the SPA lives under [project-structure.md § console/](../architecture/project-structure.md#module-boundaries); evidence provenance, stream recovery, localization, and Architecture-map resilience are owned by [console-evidence-and-resilience.md](console-evidence-and-resilience.md). Login bootstrap derives assigned-principal access from verified App Roles without requiring the optional access-request projection; unassigned access remains closed when that projection is unavailable. In local development, an independent service adapter may use Azure CLI only for model narration; it has no provider-read or execution authority. Ontology presents a reviewed Semantic model and Catalog topology from one exact-release registry projection. Runtime instances appear only in a separate, purpose-scoped Context snapshot backed by a secured receipt. The instance surface keeps source candidate accounting, bounded response counts, focus-graph items, Inspector-only relationships, and IAM-only relationships separate so layout omission never reads as missing provider evidence. Fleet source rows use `(source, scope_digest)` identity, display each opaque scope digest, and do not collapse several cluster states into one row. While visible, it consumes an authenticated inventory-invalidation SSE stream and immediately revalidates the selected instance after a committed watermark. Cross-origin replay explicitly admits the bounded `Last-Event-ID` request header. When SSE is unavailable, a monotonic countdown shows the next 15-second fallback poll; browser resume also triggers immediate revalidation. Refresh failure preserves the last verified response, provider states remain text-bearing semantic badges, and neither SSE nor polling substitutes for inventory observation or raises relationship completeness. Incident attention never submits during mount; each explicit click opens a fresh incident-bound conversation, and a receipt-bound planner outage renders a localized model-connectivity or semantic-runtime recovery step. Once server verification exists, its evidence references exclusively own citations, including an explicit zero-reference result; screen context is cited only when no verification result exists.
Settings > Integrations previews the reviewed Calm Slate incident-open email with synthetic placeholders. Operator Service loads the same packaged HTML used by the design specimen, while the Console keeps it in a sandboxed frame, centers it on a 760 CSS pixel canvas with a 640 pixel desktop email sheet, and reflows it without horizontal clipping at constrained and mobile widths. An Owner can also save one public-cloud Teams Workflows URL and send a fixed synthetic Adaptive Card through a bounded diagnostic. A deployment uses a dedicated Key Vault secret and a managed identity that can write only that versioned secret. The local profile encrypts the value with a domain-separated key derived from its private service DSN and stores only ciphertext in the loopback Operator database. FDAI reads the exact saved version back and verifies its digest before testing. Contributor, Approver, and Owner roles receive the current URL through a no-store response after refresh; Reader and BreakGlass roles receive only `visible: false`. Every successful reveal writes an audit record containing the actor, digest, binding version, and timestamp without the URL. Saving or revealing the secret does not grant approval or execution authority, and a deployment still controls when its notification runtime references the binding. The Teams A1 guide separates protected FDAI preparation from the tenant consent, Teams app installation, and final deployment approval that remain provider-hosted human actions, and it never accepts a client secret. Its Owner-only action persists one revisioned, no-authority proposal for a protected plan and reports the durable request state without claiming provider or deployment success.
Settings > Models starts a bounded projection prefetch on pointer or keyboard focus and coalesces a successful result for 60 seconds only inside the authenticated API client. Explicit catalog refresh, conflict recovery, and post-mutation reads remain fresh; browser storage and shared HTTP caches remain unused. Settings > Runtime policies renders every entry in the shared runtime-setting allowlist with localized labels and hints; local read-only materialization projects the same complete key set instead of a group-specific subset. Owners can manage settings only through the revisioned, audited Operator API, while the materialized projection remains non-manageable. The section exposes aggressive T2 answer recovery to Owners. Every environment defaults the control off until promotion evidence justifies an audited override. Saving the audited revision applies to later interactive read turns without restarting Core. The control cannot enable T2 for Golden campaigns, action drafts, scope or authorization denials, or execution paths, and it does not relax ontology or evidence verification. For optional Console projections, typed `404`, `501`, and explicitly classified source-gate `503` responses render as unavailable. An unclassified `503` remains an operational error instead of being presented as an absent projection. Authentication failures, unexpected transport or `500` responses, and decoder failures also remain visible errors. Cost Governance uses the complete versioned `CostReadinessReason` vocabulary for both runtime decoding and localized labels, so partial evidence and bounded truncation remain readable while an unknown reason still fails visibly. Settings > Integrations > Document OCR lets an Owner choose process-isolated local Korean and English OCR or request Azure Document Intelligence. Saving creates a revision- and digest-bound policy plus a protected plan request without apply authority. The panel reports the provider that deployment readback confirms, supports retrying a plan request, and separates switching to local OCR from explicit Azure resource removal. Tag canaries remain outside the Console mutation surface: it may present mode, approval, dispatch, rollback, and independently verified effect records, but cannot select a target or value, promote the ActionType, or call the dev gateway.
The Controls view separates catalog presence and semantic mapping from scope-bound evaluation, applicability, and satisfaction. The WAF checklist shows all 59 pinned definitions with immutable workload evidence, while the CAF sibling view shows all 15 methodology and landing-zone areas with owner, cadence, approved exception, and evidence limitations. Neither view calculates compliance in the browser or writes evidence. The Rules route follows the approved catalog-workbench hierarchy: authoritative summary metrics and filters lead into a 220 CSS pixel Catalog views rail and a bounded detail table. The rail uses only server-owned total, active, collected, and Controls destinations; it never copies the mock's synthetic overrides or shadow-accuracy values. A selected rule opens a URL-backed dialog without remounting the catalog, and Escape or browser Back restores focus to the native rule detail button. When no per-rule findings provider is connected, a known catalog rule returns `evaluated: false` with an empty findings list instead of an operational `503`; an unknown rule remains `404`.
Knowledge > Documents restores a bounded collection-scoped document list after refresh. Exact same-name records share one file row, and authorized immutable versions load only when the operator opens history; uploader identity and access memberships stay outside that projection. An unchanged governed upload reuses the ready version; changed content creates a successor. Preview, download, and delete target the selected version, and deletion never reactivates an older version implicitly. Changing the collection clears prior rows before the next authorized read, and loading, unavailable, error, and empty states remain distinct without granting document or collection authority. An unavailable document action remains keyboard focusable so its explanation is discoverable, but it has no activation handler and cannot invoke the operation. Authenticated projection readers keep driver placeholders and expression grouping explicit so stored data is not hidden by SQL parsing errors. Live health summaries and document identity rows reflow inside the primary content at 1440, 993, and 390 pixel widths. A required Report variable remains an initial prompt rather than an error until the operator enters part of the variable set. Reports follows the approved evidence-workbench hierarchy: a dynamic catalog, source, and renderer summary; declared variable controls; template selection; the rendered widget canvas; and inspectable provenance. Counts and states come only from the server catalog, registry, and render envelope. The Console does not copy mock values or turn a missing render into zero. Awaiting render, a rendered zero-widget report, partial or unavailable evidence, and synthetic evidence remain distinct. At constrained widths the catalog moves above the canvas, and mobile form, navigation, and disclosure targets remain at least 44 CSS pixels without horizontal overflow.
The dashboard preserves bounded service-health answers across loading, partial, and unavailable states. It displays exact resource identity, evidence timing, and provider limitations from the semantic projection rather than substituting generic inventory data. Inventory invalidation epoch changes require a successful authenticated snapshot reread before acknowledging a new stream cursor; failed, timed-out or identity-cancelled reads cannot resume it. This read-only reset never changes incident, approval, attachment or assessment replay authority.
Overview recognizes both existing authoritative-projection `503` messages, `authoritative Operator projection is unavailable` and `authoritative projection is unavailable`, as explicit optional-source unavailability. A refused autonomy measurement preserves the available KPI backbone and displays evidence unavailable rather than replacing the whole page with an error. Measurement completeness limits remain authoritative; this presentation never turns truncated evidence into measured values or makes a generic service `503` optional.
Vertical and Operating Outcomes keep domain rows visible when attribution is missing, preserve the canonical observed-event denominator, and separate unavailable from measured zero through the schema-versioned wire contract. Each outcome detail uses its selected metric's sample count, retains the event denominator separately, and renders server-authored missing, incomplete, mixed-source, or unattributed evidence reasons without deriving a reason in the browser. They present zero savings in both primary and comparison views only when at least one cost event was observed in the measurement window. Live Resilience and Cost Governance drill-downs retain canonical filters; Promotion Gates has no vertical field, so Change Safety opens that owning view without a misleading filter. Sample links omit operational filters, and switching data modes returns the visible request to loading before the next source resolves. Sample KPI and autonomy fixtures pass the same decoder invariants as live responses. The native comparison table preserves keyboard navigation and bounded horizontal scrolling through 320 CSS pixels.
A schema read that identifies one canonical declaration type and a count facet converges adjacent manifest, declaration, and relationship intents on the server-owned principal-manifest count plan.
This path does not make a second model request or grant execution authority. Readable declaration-list judgments likewise preserve one canonical kind when plural-type facets carry `available`, `queryable`, or `readable` separately or as a combined machine field. Core uses the current principal manifest, not utterance keyword routing; additional negative, historical, or property requirements cannot be discarded by this compact path.
The packaged Core development diagnostics module serves only an explicitly enabled local owner-only Unix socket; it adds no Console, Operator HTTP, or authority-bearing route, and its regression remains owned by the Operator service suite.
The resulting semantic operation remains `aggregate`; the presentation compiler preserves its canonical operation and value fields so an independent oracle can verify the displayed count.
Catalog topology preserves its deterministic exact-release coordinates while using one bounded 900 ms spring-settle on initial entry. Interaction ends the effect and reduced-motion preference skips it. Workflow Builder uses the reviewed published-definition hierarchy: authoritative source and revision, four selected-workflow facts, review controls, a 220 CSS pixel catalog rail, an ordered contract path, and a 310 CSS pixel inspector. Optional principal definitions and Python-task capability reads degrade independently without hiding an available built-in catalog; the required catalog and ActionType palette still fail visibly. Principal-scoped durable Process history remains workflow-state-only, and structural validation is never presented as a substrate mutation preview.
Agent Activity links a correlation to Trace only when the row is backed by durable audit evidence. Inventory scan, ontology projection, and current-state read correlations remain visible identifiers without an audit-trace link. A manual lookup with no matching audit steps renders a neutral unavailable state instead of an operational failure.
Huginn discovery health keeps `not_bound` projection and `not_observed` cursor, backpressure, or source-health signals distinct from healthy evidence. Console projections may render those canonical limitations but never infer a passing source check from them.
Trace presents recent discovery, correlation lookup, ordered stages, selected evidence, action attempts, and the complete audit timeline as read-only views of `operator-audit-log`. The response correlation must match the request, sequence and optional fields must decode strictly, and joined steps preserve actor, source event and correlation, entry hashes, and canonical action values. Approval requires explicit approval records; delivery and notification never imply approval. Completeness is true only when the server proves the trace fits within its 500-record bound, and sampled discovery is always labeled recent rather than complete. Decision, action-attempt, RCA, and independent effect summaries must reconcile with ordered steps or the projection is unavailable. The correlation lookup toolbar remains in normal document flow and scrolls away with the route, so it never covers timeline or evidence content. Localization and responsive presentation may change labels and layout only; canonical values, timestamps, provenance, authority, and the distinction between latest and terminal state remain.
Agent Activity owns chronological work and handoff evidence. Its route-backed Roles and ownership dialog contains only the fixed reporting tree, owned object types, authority boundaries, and selected-agent summary; it preserves Activity filters, closes with Back or Escape, and links a selected role to a filtered Waterfall. `/pantheon` remains the shareable role-only fallback. Neither organization surface renders an Incident timeline, workflow, or conversation transcript. Live activity, durable audit parents, and expanded audit conversations retain independent bounds, so conversation expansion cannot evict the 500 explicitly fetched operational activities. The browser hydrates durable activity and bounds each log source with one batch ordering pass instead of repeatedly sorting every growing prefix; the full bounded result and filtering semantics stay unchanged. A newly appended non-replay row receives a neutral whole-row tint that fades over three seconds. Initial rows, retained replay, filtering, and unchanged rerenders do not trigger the cue; reduced-motion mode keeps the tint static for the same bounded interval. The log uses shared panel-title, compact, label, and caption roles, with no text below the 11 CSS pixel caption floor. Explicit keyboard refresh returns focus to its trigger after the bounded read. In Waterfall, disclosure, correlation identity, and cross-route navigation remain separate affordances: the chevron only expands or collapses, the complete identifier is selectable non-interactive text, and a labeled Trace action alone navigates while browser Back restores the prior filters and selection. Live presents at most 15 current control-loop and source-read cards in one newest-first selectable page flow while retaining their distinct decision, evidence, and execution semantics; an explicitly selected deep link remains visible within that bound. The central SSE owns current activity; Agent Activity remains the explicit bounded retained-history read. Live coverage cards remain links in loading and unavailable states, decode ARG totals only from the authority-free inventory envelope, and show a missing optional `rule.findings-summary` projection as not evaluated; the shared workflow adapter does not route that summary through document attachments or any evidence writer.
The Live route keeps Authority coverage immediately after the source and attention status rail,
followed by a compact KPI row and Current activity. Events per second remains a 60-second SSE
measurement. Gate and tier mix use the bounded current control-loop cards so reconnecting does not
hide retained decisions already visible on the same screen. Source reads never create a gate or
tier. This presentation order and aggregation change no stream, evidence, or authority.
The authenticated `/provisioning` route is a read-only projection of one durable subscription genesis run. It replays completed stages, resource discovery, and final verification without starting, retrying, approving, or changing deployment.
Database, semantic, model, runtime, inventory, and system readiness remain separate, and resource and page totals stay estimates until independent inventory closure.
Only a consistent terminal readiness snapshot reaches 100 percent; invalid frames still advance the cursor, a new run resets its sequence, and cancelled or failed runs remain explicit.
Before connecting, the Console verifies that the Operator manifest owns `/provision/stream`; the Operator declares that durable source only when its PostgreSQL replay store is configured and otherwise reports one unavailable reason.
Source verification, unavailable, reconnecting, and unobserved states remain distinct, while changing between Sample and Live resets run-local state so synthetic evidence cannot remain on a Live screen.
The production layout uses visible headings for source notices, follows the provisioning mock's run summary, and separates Stages, Readiness, and Resources into keyboard-accessible views without copying mock-only lifecycle data. Console catalog or navigation changes refresh the source-bound question bank before semantic-intent coverage and CQAS provenance so all generated artifacts retain the same authoritative source digest. The latest base integration followed that order and preserved all 400 question identities. A digest-only refresh changes no runtime authority.
During initial inventory, `/provision/stream` replays the Core-owned count-only ledger through the Operator role's `SELECT`-only PostgreSQL grant; its allowlisted payload contains no subscription, resource, or provider identifiers. Console tracks inventory run and sequence separately from the overall Genesis run, so a new scan cannot reset stage readiness or overall progress. Detailed resource, page, provider-type, relationship, unmapped-object, and coverage-gap counts remain non-authoritative; only the independently closed terminal record represents inventory readiness.
The Console shell keeps a compact FDAI brand lockup in its header and uses a square browser icon whose transparent exterior and white interior preserve the mark on light and dark browser chrome. Content containers use the calm-slate hierarchy with 1 px hairline borders; decorative colored top or left edge accents are prohibited. Static design-mock checks follow the current navigation taxonomy and distinguish semantic line swatches from prohibited container-edge accents. By default, navigation reserves only the 56 px activity rail in the content layout. A non-Settings group button or page-title breadcrumb opens its child Explorer as an overlay, selecting a child closes the overlay, and an explicit pin restores the persistent 300 px dock. Settings opens as a modal workspace over the current route, keeps its section changes out of browser history, and restores the unchanged route and screen when closed. Operators can use the activity rail context menu or its accessible `...` control to show or hide optional groups; Overview, Settings, and the current visible group remain protected. The Overview Explorer lists one canonical Dashboard entry. The stable `/resource-dashboard` Resource dashboard route remains available for deep links but stays out of the Explorer; the former `/dashboard-v2` path canonicalizes to it while preserving the query string. An icon-led 44 CSS pixel page-header switch opens it from Overview, and its reciprocal header link returns to Overview. The Resource dashboard defaults its honeycomb to a representative recorded-state lens with visible axis markers. Green and red distinguish qualified positive and negative values. Amber marks transitional values and every `?` state that requires evidence review, while neutral and patterned treatments retain other recorded, not-provided, and inapplicable values without converting provisioning success into health. The complete Needs review count links to its filtered list; review does not itself mean failure or grant action authority. Explicit operational, serving, availability, provisioning, and observation lenses remain available.
Qualified Provisioning Succeeded uses the green completion treatment with a visible `P` axis
marker. That treatment reports provisioning completion only and does not establish operational
health or availability; generic recorded values and evidence-absence states remain neutral or
patterned.
A managed identity with the exact reviewed no-state combination uses green `Observed` only when
the complete generation-fenced inventory page records its presence. It has no axis marker and does
not claim identity usability, role assignment, token issuance, operational health, or availability.
Each Resource dashboard state filter keeps its symbol, localized state label, and count inside one
wrapping chip. The chip stays within the Resource panel at desktop and mobile widths instead of
leaving the count outside the semantic surface or clipping a long label.
The representative lens chooses recorded values before absence reasons. A no-traffic serving reason
cannot hide a qualified provisioning value, and an explicit provider `Unknown` remains a neutral
axis-qualified recorded value. Only unresolved classification or evidence gaps retain `?` Needs
review; failure remains a separate red state.
The header places a localized Guides command immediately before the account identity. It opens a modal right drawer populated from a strictly validated `catalog.json` at the production Console's same-origin `/manuals` path; legacy or external Manual Studio builds may override it through `VITE_MANUAL_STUDIO_URL`. The installer binds same-origin share metadata, and the protected Static Web Apps publisher verifies the bundled catalog, library, and representative share page. The drawer presents every available manual in one continuous scroll, ordered from stage `01` through `05`. Stage headings and quiet separators preserve the FDAI Value-to-Scale Journey without adding a second page or filter control. Each card centers a 4:5 book cover and places only the manual description below it as a full-width short recommendation. The cover remains the single source for deck type, `L100` through `L400` depth, stage, title, duration, and slide count; a missing depth defaults to `L100`. The independent library can use its wider presentation while preserving the same information model. Cover assets must remain within that configured base path, and selecting a manual opens its HTML slide presentation in a new tab. A separately hosted Manual Studio permits catalog reads only from `MANUAL_STUDIO_ALLOWED_ORIGINS`; the bundled path remains same-origin. An unavailable or invalid catalog remains explicit and grants no runtime authority.
The authenticated active-incident stream can open an idle Command Deck with an incident selector. That selector is a presentation hint only; the server re-resolves the durable incident and its evidence before answering. Concurrent stream subscribers on one Operator replica share one authoritative incident snapshot read for each two-second polling interval, while authentication and replay cursors remain connection-specific.
When the tab and Deck are idle, the first browser observation of an incident submits one localized read-only investigation turn. A browser-local incident ledger suppresses replay after reload; the incident badge remains an explicit way to investigate again. When an incident question matches several records equally, the terminal answer includes bounded candidate buttons rather than relying on a plain-text instruction. A button opens the candidate's exact incident conversation and immediately submits the localized read-only investigation turn. The click is the operator's explicit request; an automatic active-incident stream open never submits a managed-resource action.
This doc covers the **pull direction** - the operator asks, simulates, approves - across every channel the notification doc already ships adapters for. Push and pull share the same channel credentials and the same audit contract, but they are distinct integration surfaces. For local preparation, the private `console/.env.local` may carry browser bindings plus only the server-owned `FDAI_LOCAL_NO_AZURE_DEPLOYMENT` and `FDAI_LOCAL_RESOURCE_GROUP` selectors; explicit process values take precedence, duplicate keys fail closed, and neither selector grants execution authority. Reusing the local-state preparation cache also requires the live legacy and all five service migration heads, so recreating the database inside the same Docker volume reruns schema preparation.
> Customer-agnostic: every channel id, LLM deployment name, resource id, and group name below is a placeholder. A fork supplies concrete values via config ([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).
## 1. Framing - what this is (and what it is not)
Instance-candidate enrollment uses the authenticated principal, role, and group scope without changing human-report-line, assignment, approval, or action authority. The default Core index lifecycle remains agent-owned and read-only; exact-ID results do not qualify semantic ranking or imply a complete collection. The bilingual identity-only terminal explicitly reports partial, non-exhaustive candidates and no execution authority. It neither projects arbitrary properties nor substitutes for attachment authorization, exact document citations, or document evidence completeness.

The FDAI Console conversation surface does **not** carry judgment authority. FDAI's judgment stays where it already is - the deterministic
engine (T0), the quality gate (T2 verifier), the risk gate, and the shipped Rego policies. The console is the **conversational surface**
through which an operator inspects that judgment, simulates change, and approves what the system has already queued.

Three properties follow directly:

- **LLM is a translator, not a judge.** Natural language becomes tool calls and tool results become natural language; execution eligibility comes only from the verifier
  ([architecture.instructions.md § Design Principles](../../../.github/instructions/architecture.instructions.md#design-principles)).
- **Tools expose pipeline stages, not primitive data sources.** The console exposes
  `describe_event()`, `explain_verdict()`, and `simulate_change()` instead of primitive log, metric,
  and config queries. The system has already reasoned; the operator asks about the result.
- **Growth is catalog growth, not model memory growth.** Recurring investigation patterns become
  new rule candidates through the discovery loop
  ([architecture.instructions.md § Rule Catalog](../../../.github/instructions/architecture.instructions.md#rule-catalog)) -
  not opaque session memory. Persistent conversation state stays in auditable, exportable,
  CSP-neutral `audit_log` and `operator_memory` records.

Completed answers also enter the off-path [Conversation Assurance](../decisioning/conversation-assurance.md) loop. A one-question improvement turn uses the same authenticated `/chat/stream` request and exposes its six-phase Run Record, content-free dynamic prompt manifest, Pantheon participant and evaluator prompt profiles, and Preparing answer transition as separate presentation gates. The expanded Run Record shows only profile ids, versions, hashes, situations, and budgets, never SYSTEM text. JSON and SSE adapters share the typed conversation-turn service and extracted request setup, evidence, progress, verification, and terminal-delivery helpers while preserving their existing wire contracts. Browser assurance parser and evidence-gate regressions register with the Console Vitest suite so repository-wide Console collection exercises the same runner contract as focused checks.
Terminal intake preserves the exact verification reason and evidence-manifest completeness. Outcome summaries, context selection, Azure investigations, durable delivery, and attachment evidence remain owned by their typed providers; adapter modules only coordinate presentation and persistence.
Core separates semantic request binding, bounded Incident evidence projection, and localized Incident answer rendering into dedicated modules. The semantic turn processor coordinates those modules; this internal split changes no wire field, evidence limit, citation, locale, or authority.
Operator likewise separates immutable PostgreSQL family records, bounded row projection, and strict inventory evidence decoding from query and outbox orchestration. The facade preserves existing imports, principal scope, proposal idempotency, wire values, replay ordering, and no-authority behavior.
Operator IAM also separates access and assignment proposal decoding, runtime and model configuration persistence, configuration projection, and human-approval persistence from the shared PostgreSQL adapter facade. Malformed nested assignment duties and goal references fail closed instead of being omitted, while public ports, revision fencing, proposal idempotency, approval identity, and `execution_authority: false` remain unchanged.
Operator semantic presentation also separates Pantheon assurance terminals, localized Incident blocks, and content-redacted technical trajectories from terminal event orchestration. These renderers remain read-only and preserve wire fields, evidence bounds, locale selection, query redaction, and `execution_authority: false`.
Operator semantic transport also delegates verified query activity projection and document-answer materialization away from its event iterator. The split preserves event ordering, replay cursors, progress monotonicity, deadline holds, principal scope, content redaction, and no-execution authority.
An explicit fixed-census diagnostic request uses a bounded `conversation-assurance:<case-id>` purpose. Core validates the case, question, and locale against its server-owned census before Bragi answers. The resulting `done` event carries the answer, content-free diagnostics, trace latency, and schema-v2 queue/assurance timing; ordinary `operations-review` requests retain the existing semantic result contract.
The version 1.2 semantic projection preserves this boundary across the service split: `answered` requires exact release, principal manifest, plan, execution receipt, and evidence references; unavailable dependencies return a typed limitation. Recorded-state reads likewise return fail-closed HTTP 409 when the Operator and inventory ontology releases differ, and recover only after a complete atomic reprojection under the current release.
Version 1.6 can also carry bounded authenticated group claims and governed-document evidence.
The Console accepts only Core-projected version 2 intent evidence, displays exact revision citations and incomplete-coverage limits, and never treats document text as instructions or current operational state. The committed semantic-intent coverage artifact is regenerated from authoritative sources, binds the exact federated question-bank digest, and grants no runtime authority; format-only owner reflow may refresh its catalog citation pin without changing Console behavior. The same source-only refresh neither creates nor changes a human report line. Registering an isolated AKS execution route changes neither Console approval authority nor the requirement for independent live effect evidence. Assigning its tests to the isolated Executor service suite changes test collection metadata only.
Missing optional document evidence permits a partial answer only after independent operational evidence completes; required or explicit document evidence stays held. Unknown evidence authority values and unsupported intent-evidence versions are discarded, never downgraded or displayed.
The [structured cloud-document extension](cloud-resource-knowledge-structured-rag.md) is under development: v3 format selection and accepted retrieval terms grant no authority and do not establish live readiness.
The Process journal also projects an adaptive Investigation Room. Operator rechecks the Process revision and nested content digests; Console validates the same identity before showing bounded rounds, competing hypotheses, evidence gaps, and terminal status. Truncated hypothesis labels expose the exact identifier through the shared keyboard-accessible Tooltip rather than a browser-native title bubble. The room grants no mutation, approval, promotion, planning-selection, or execution control.
The Process workspace shows loaded-run counts and nine snapshot facts before collapsed control, investigation, planning, journal, and workflow-evidence sections. Provenance preserves selection; event links open the containing journal and record.
Explicit Sample mode provides one focused, read-only VM-start review journey plus two supporting held and denied cases. It also presents a generated 100-event tier cohort with `T0` 94 percent, `T1` 5 percent, and `T2` 1 percent; the Sample generator produces that exact distribution, labels it presentation-only, and never changes Live routing or creates operational evidence. The focused synthetic correlation connects the operator question, grounded evidence, separate human approval, provider acceptance, independent observation, reconciliation, and recovery readiness without replacing an empty Live source, exposing a permitted transition, or claiming an operational effect. Incident history keeps the completed correlation while the pending Approval card uses a distinct correlation so current states do not conflict. The pending card keeps Incident, Trace, Audit, and RCA drill-downs in Sample mode and binds them to one synthetic correlation. Each drill-down renders matching synthetic evidence or an explicit recorded-evidence absence without querying Live data. Live Approval cards expose Incident navigation only when the server confirms a canonical Incident for the correlation; Audit, Trace, and RCA remain available for operational correlations without an Incident. Synthetic action, target, and rule identifiers without a matching Sample detail projection remain text instead of broken links. Runtime browser notifications carry an explicit Live selection so a tab's Sample preference cannot reinterpret operational alert evidence. Equal-content-width comparison, keyboard interaction, light/dark status contrast, and 320-1440px reflow checks cover this presentation. Catalog validation follows the imported `t` binding rather than unrelated formatting helpers.
Operator-owned Kafka adapters publish semantic proposals, consume semantic projections, and relay validated Core stage and Pantheon runtime-state frames into separate bounded `/live/stream` and `/agents/stream` SSE hubs. The Live route uses `/live/stream` for control-loop decisions and a separate read-only `/agents/stream` subscription for current source-read activity, so inventory, health, metrics, logs, cost, and recovery observations remain visibly active without being presented as decisions or execution. Authenticated `GET /agents/activity` projects bounded inventory scan, ontology projection, and current-state read history from durable sources before the Console applies newer stream frames; current-state replay and live frames share the same hashed-correlation activity id. These observation routes use the same bearer gate as snapshot reads, stay connected with keepalives when Kafka is absent, and report `Awaiting source` until an authoritative frame arrives; `GET /chat/health` reads the semantic bridge's process-owned worker readiness directly instead of requiring a durable conversation projection row. Console publication consumes the selected profile's HTTPS browser gateway base when present and otherwise retains the Container Apps FQDN; both expose the same root Operator API paths without a browser rewrite.
Terraform pins the request and projection topics, while Core renders verified query tables and Operator maps durable results to the existing `done` event.
Injected providers take precedence and the local narrator is exclusive. Full-stack preparation fingerprints the path and bytes of an explicit absolute `FDAI_LOCAL_RESOLVED_MODELS_PATH` in both legacy and staged caches. Changes regenerate bindings. The same contract includes an explicitly enabled owner-only Kubernetes fleet file without changing service boundaries. Without an explicit selection, a missing default model artifact is generated from existing scope-bound deployments before cache reuse, following [runtime parity](../deployment/dev-and-deploy-parity.md); failed or ambiguous discovery stops preparation without provisioning or granting authority.
The managed full-stack task defers authoritative inventory refresh to its continuous reconciliation process so the Console, Core, and Operator processes can start while collection runs. Complete readiness still requires active-scope inventory coverage and a clean analyzer tick. The local analyzer receives its service-owned StateStore binding explicitly so target admission can verify recorded state evidence without raising autonomy. Standalone preparation retains synchronous inventory refresh.
Local preparation fingerprints its stale-consumer cleanup helper and isolates readiness messages in `fdai.startup.probes`, with one-hour or 1 MiB-per-partition delete retention and ten-minute segment rolling. Cleanup rechecks empty PID-specific introspection groups and removes only those whose process has exited; operational messages, dead letters, active groups, and database records remain untouched. Broker retention is asynchronous, and existing runtimes adopt the probe topic after managed preparation and restart.
The Operator API never marks a review ready, creates a catalog proposal, or grants authority. Reporting an incorrect answer adds evidence for autonomous re-evaluation, and every governed transition still requires exact replay evidence plus the existing catalog lifecycle.
### 1.1 Vocabulary added to the shared glossary

The following tokens are added to the shared vocabulary in
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) and are used consistently by every referring doc:

- **operator-console** - the legacy contract token for the conversation capability documented here; the product display name remains FDAI Console.
- **narrator** - the LLM tier of the operator console (translator role;
  never a judge). Distinct from the T2 quality-gate role, which is a
  domain reasoner over a proposed action.
- **operator-conversation** - one bounded exchange between an operator and
  the console (multi-turn, RBAC-scoped, audited).
- **console-tool** - one exposed pipeline stage or catalog view the narrator
  may call.

Explanatory questions about T2 execution-eligibility checks or insufficient-evidence handling use the canonical glossary before
action-context or intent-graph tools. This precedence applies only to concept explanations. A question with an exact action, approval,
correlation, or idempotency selector continues to require server-owned action lifecycle evidence.

## 2. Three-layer architecture

![2. Three-layer architecture. The main stages are CLI REPL, Teams (pull), Slack (pull), Web chat (Console SPA), Narrator (LLM)\nT1 translation default\nT2 translation escalation, Intent classify\n(read | simulate | approve | breakglass), RBAC gate\n(per-tool role floor), Verifier re-check\n(no auto-execute), Session state\n(audit-log-backed), ControlLoop, RuleIndex / T0Engine, QualityGate.](../../diagrams/generated/fdai-operator-console-01.en.svg)

- **Layer 3 (Channel)** is thin. Every adapter converts one turn between its wire format and a
  `ConversationTurn`; no judgment lives here. A streamed read sends SSE comment heartbeats while the provider task is idle, without progress or evidence. Stream close cancels and awaits that task.
  Web, Slack, and Teams render the same ordered agent-activity contract: Bragi shows the handoff, and the accountable observer shows canonical command/result evidence. An agent selected by an
  agent conversation target or incident binding, or addressed with `Ask <agent>` or `@<agent>`,
  remains the response owner.
  An agent-card Ask opens with a compact projected-state line list; its longer fixed context stays non-rendered for backend history, and the visible report streams in bounded two-word bursts.
  Web Investigation animates only received branch frames with elapsed time, typed badges, and staggered status rows. A terminal investigation keeps its session header and observed steps visible beside the final answer; only redacted command output and timestamps remain in disclosures. A source branch linked to an observed execution step is represented once on that step rather than repeated as a separate row. Full workspace reserves one 760 px reading measure for the desktop answer and structured evidence, keeps long-table headers visible while rows scroll, and uses the full mobile viewport with labeled-row reflow and no horizontal overflow. Phase markers, a 15 px conversation scale, and one dark command/code surface keep the production hierarchy aligned with the execution mock. The browser never replays work or invents progress.
  Observed activity uses `input_kind` to separate process commands from canonical server queries.
  Query rows show verified typed input, authority, snapshot provenance, and bounded results without
  inventing CLI arguments, exit codes, endpoints, or provider errors. Execution provenance keeps
  inter-service `transport` separate from interface, service, component, operation, and
  provider-neutral source, so ObjectSet reads remain internal typed queries. Lifecycle-only events
  show recorded explanation, owner, outcome, authority, and observation time; older records remain
  `Not recorded`. Web, Slack, Teams, and durable replay preserve the query/command distinction.
  A narrator milestone settles the preceding activity group before the next group begins. Web shows
  the milestone as a compact progress note, opens only the current group, and restores completed
  groups in causal order. Slack and Teams edit the same cumulative redacted activity projection.
  When a request carries both a plain agent target and an incident binding, the two structured
  agent values must match; conflict is rejected before evidence retrieval. For model-backed answers, global read-only safety stays first and the selected immutable charter follows only on an exact `conversation_policy` match. A dedicated target session assigns that verified agent's voice across follow-up turns and renders self-role questions deterministically from content-addressed capability facts; ordinary screen delegation keeps Bragi as narrator.
  A policy mismatch or explicit handoff returns narration to Bragi, and the charter never becomes evidence, authority, or tool permission. The injected charter is composed for the turn: the immutable baseline plus the operator-locale layer when the answer locale is not English. Agent evidence also carries the layer manifest and digest of the prompt that governed the agent's own turn, so a spent escalation budget or evidence gap is stated as a constraint rather than left invisible.
  Bragi becomes the response owner only after that agent abstains and hands the turn back. Vendor adapters change presentation only. Slack uses plain-text activity
  blocks for query, command, and output bodies so markup characters cannot change the observed input,
  and preserves those blocks across posts, stream updates, and edits.
  Teams keeps the Adaptive Card under 24,000 bytes, counts omitted activities, and always retains
  the final accountable-agent answer. Renderers distinguish producer-side partial evidence with
  `[UPSTREAM OUTPUT TRUNCATED]` from vendor-limit clipping with `[CHANNEL OUTPUT TRUNCATED]`.
  Full-workspace presentation, composer placement, history restore, header controls, and internal
  screen grounding are owned by [progressive conversations](operator-console-progressive-conversations.md#command-deck-workspace-lifecycle). Sent images render inside the operator turn, and validated image attachments bypass prompt-only semantic tool planning and omitted-subject
  LLM-usage refinement so the current image reaches vision narration. Terminal verification preserves the interpretation as unverified with a current `conversation-image` ref instead of treating it as screen-verified. Explicit measured LLM usage remains a deterministic tool request. Browser transcript caches retain only image descriptors, while authenticated history reads load
  bytes from the principal-scoped conversation image repository. A restored transcript shows its last recorded
  time and a new-conversation action. Tables render every bounded row without internal scrolling or expansion controls; cell-level `<br>` variants become safe line breaks while other raw HTML remains text.
  On narrow screens, cells reflow while preserving native table semantics.
- **Layer 2 (Coordinator)** owns intent classification, RBAC gating, tool
  dispatch, verifier re-check, and session bookkeeping. Core translation uses the `Narrator`
  Protocol. A narrator that also implements `GroundedAnswerNarrator` receives a completed
  successful `ToolResult` in a second presentation-only pass. The coordinator retains the
  original tool-result turn, accepts no new tool call, and falls back to the deterministic preview
  when rendering fails, exceeds the response bound, or omits an `evidence_ref`. Its system prompt is
  assembled deterministically from `AnswerPlan`, tool side-effect class, evidence-reference count,
  and the presence of prior conversation context. The current inbound/tool/result transaction is
  excluded from that prior context. Web generation uses the Operator API backend seam, so deployments
  can bind providers.
  `AnswerPlan.format` keeps `table`, `chart`, and `mixed` as presentation preferences. An explicit
  request format or saved response preference wins only when the verified result can support that
  shape without changing meaning. After eligible read evidence resolves, a bounded structured
  model call may arrange a `PresentationPlan` from server-declared slots. The model receives only
  shape metadata, allowed slot-component pairs, coverage classes, and the operator request. It
  never receives row values and cannot emit titles, facts, units, thresholds, status, severity,
  colors, links, or evidence references. The plan can choose slot order, one allowlisted component,
  emphasis, and whether supporting detail starts collapsed. It cannot repeat or omit a required
  slot. `AnswerPlan.format` continues to own the canonical Markdown text fallback, while
  `PresentationPlan` owns only the Console artifact layout. Presentation planning never rewrites
  the canonical text format. An explicit format or saved preference skips the artifact and keeps
  the established table, chart, list, or prose renderer.

  The server compiles immutable evidence into a bounded `presentation_artifact`; versioned layouts,
  integrity, and fallback rules are owned by [Operator Console Progressive Conversations](operator-console-progressive-conversations.md). The compiler enforces compatible units and threshold directions for
  charts, keeps partial or truncated coverage visible, and binds every block reference to the
  terminal verification receipt. A partial source never removes completed slots: the answer renders
  every available verified fact and marks only the missing portion as unknown or unavailable.
  A streamed evidence-fast-path turn starts with the complete deterministic plan and streams the
  canonical answer immediately while the optional mini-model planner runs concurrently. After the
  answer is visible, the terminal event waits at most five seconds for a valid alternative layout;
  timeout, cancellation, invalid output, or provider failure keeps the deterministic plan. The
  non-stream JSON route uses the deterministic plan directly and never delays an evidence answer
  for presentation planning.
  Presentation planning can return no artifact only when no relevant verified slot exists. Model,
  schema, timeout, or compiler failure uses the deterministic answer and default layout, so the
  operator still receives the maximum evidence-supported answer. Existing Markdown table, fenced
  chart, bullet, and prose output remains the compatibility contract for other channels and older
  clients.
  The semantic turn planner projects only the bounded capabilities for that request into a strict
  structured-output schema. Every object rejects additional properties and marks its declared
  fields required. A tool's optional arguments are represented as nullable fields, and the
  coordinator removes null placeholders before deterministic selection validation and dispatch.
  After rendering, a core validator rejects numeric values, percentages, RFC3339 timestamps, and
  canonical rule, event, incident, correlation, or ActionType identifiers that do not occur in the
  immutable `ToolResult`. Freshness words such as `current`, `live`, or `latest` require an exact
  timestamp from that result. Markdown list ordinals, ordinary resource aliases, and numbers
  embedded in identifiers are excluded from this conservative check to avoid treating formatting
  as a claim.
  When intent translation remains ambiguous, an optional `ClarificationNarrator` sees only the
  installed tool schemas visible to the principal and may return one bounded question. This path
  invokes no tool, guesses no argument, and falls back to the deterministic abstain response when
  the provider fails or the response is not one question.
  An optional `ContextualNarrator` can translate a single-tool follow-up from bounded prior turns.
  Prior text is escaped as untrusted data, and every parsed scalar argument must occur in the
  current utterance or those prior turns after Unicode and separator normalization. Missing or
  invented arguments discard the translation before tool lookup and execution. Adapters that do
  not implement this protocol retain the original context-free `Narrator.translate` behavior.
  For a compound request that misses direct T0 matching, an optional `ReadPlanNarrator` may propose
  two or three canonical commands. The coordinator reparses every command with its own grammar and
  validates the complete plan for installed-tool membership, RBAC, distinct commands, and
  `side_effect_class=read` before the first call. Invalid plans execute nothing. Valid reads run
  serially, retain one tool-call/result pair per step, aggregate evidence references, and use the
  same grounded presentation pass. A failed or unavailable read stops the remaining plan, skips synthesis, and returns a deterministic unverified hold instead of empty-screen or narrator output.
  Before synthesis, the aggregator compares high-signal `state`, `status`, `verdict`, `mode`,
  `health`, and `outcome` fields only when two tools name the same `resource_id`, `scope_ref`, or
  `id`. Different values produce a structured conflict, preserve both evidence sets, change the
  aggregate to `abstain`, and skip model rendering. Different identities are not compared. Local and deployed interactive reads use one core-owned mode policy, so the same latency profile selects the same direct, streamed, or detached mode.
- **Layer 1 (Core)** is exactly the deterministic core that already ships.
  The console adds no new judgment path, no new persistence store, and no
  new execution vector. A console tool call resolves to a call the
  existing pipeline already knows how to make.
### 2.1 Module map

The source inventory and boundaries are owned by [Operator Console Module Map and Boundaries](operator-console-module-map.md).

## 3. Tool catalog

The complete governed tool inventory is in [Operator Console Tool Catalog](operator-console-tool-catalog.md).

## 4-6. Runtime model (Narrator, DI seams, session model)

Moved to a focused owner document: [operator-console-runtime-model.md](operator-console-runtime-model.md). It covers the Narrator LLM tier model (section 4), DI seams (section 5), and the session model and memory (section 6).

### 6. Session model + memory

See [operator-console-runtime-model.md#6-session-model--memory](operator-console-runtime-model.md#6-session-model--memory).
## 7. Safety invariants (chat does not weaken them)

The seven autonomous-action safeguards from [coding-conventions.instructions.md §
Safety](../../../.github/instructions/coding-conventions.instructions.md#safety) apply unchanged. Chat adds three of its own on top.

### 7.1 The seven existing safeguards

Every write-class tool call (`simulate_change` in enforce mode - disallowed today - `approve_hil`, `run_runbook --live`) MUST carry:

1. **Stop-condition** - inherited from the ActionType without console alteration.
2. **Rollback path** - inherited from the ActionType's `rollback_contract`.
3. **Blast-radius limit** - inherited from `blast_radius`; language cannot widen it.
4. **Dry-run receipt** - required before a write-class tool reaches live dispatch.
5. **Per-resource lock** - held by the execution path, never by the browser.
6. **Idempotency** - binds retries to the same action and suppresses duplicate mutation.
7. **Audit entry** - persisted before dispatch and closed with the terminal outcome.

### 7.2 Three chat-specific invariants

8. **Verifier re-check on every write-class tool call.** After the
   narrator emits a `tool_calls` frame that targets a write-class tool,
   the coordinator re-runs the T0Engine + policy-as-code check against
   the tool arguments. On abstain / deny, the tool call is dropped and
   the turn falls through to HIL (see §7.4). This is the mechanical
   guarantee behind "the LLM never grants execution eligibility".
9. **No self-approval, chat-scoped.** `approve_hil` refuses when the
   caller's Entra `oid` matches the requester recorded on the queued
   item, even if the caller holds Owner. This is the same invariant as
   the PR gate ([security-and-identity.md](../architecture/security-and-identity.md));
   chat adds the invariant name to the audit reason on refusal.
10. **A BreakGlass request must be time-boxed and explicit.** `activate_break_glass`
   requires `(reason, expiry <= 4h)` and pages every configured Owner via
   the push-direction Slack/Teams adapter
   ([channels-and-notifications.md](channels-and-notifications.md)). No
  silent elevation. **The request is fail-closed on notification:** if the
   primary pager channel is down, the coordinator tries the configured
  fallback channel; if *no* channel confirms delivery, the request is
   **refused** (a break-glass with no audit witness is more dangerous than
   a delayed emergency), and the refusal is itself audited so an Owner can
  see the attempt. The shipped tool returns pager and audit receipts only; it does not change
  `ConversationSession`, `Principal`, or the RiskGate role axis, so it raises no approval
  eligibility. Until a session-scoped grant store and dispatch integration exist, no elevation
  occurs. A future grant must never return `auto` or permit self-approval (safeguard 9). The exact
   eligibility semantics are defined in
   [user-rbac-and-identity.md § 2](user-rbac-and-identity.md#2-role-model-4-tiers--break-glass)
   and mirrored by the RiskGate role axis
   ([execution-model.md § 2.5](../decisioning/execution-model.md#25-axis-f---role-rbac)).

### 7.3 BreakGlass request receipt

The current `ActivateBreakGlassTool` result contains `activated_at`, `expires_at`, a redacted reason, `pager_receipt`, and `audit_id`. Its
`max_ttl_seconds` default and ceiling are `14400`; a larger adapter setting is rejected. This result is not an authorization grant record,
and no persistent store currently enforces session-end or expiry revocation. No downstream path may use the receipt as elevation evidence.

### 7.4 Human approval fall-through when the LLM proposes a write

The narrator MAY, when the operator says "just fix it", emit a `tool_call` for `run_runbook(dry_run=false)` or `approve_hil`. On the
verifier re-check (safeguard 8):

- If verifier passes AND RBAC is satisfied → the tool call proceeds.
- If verifier abstains or RBAC is under the floor → the coordinator
  internally files a review item in the existing HIL queue and returns
  "I filed a HIL item, id X" to the operator.
- Under no circumstance does the write happen without an audit entry before dispatch. For an ActionType explicitly configured to use a reviewed [human report line](human-report-lines-and-approval-routing.md), the queue first shows the requester a separate contact-consent card.
  `Send approval request` authorizes only notification of the exact pinned route, not the action. The route, graph, RBAC, and ActionType policy are rechecked before delivery and when an approval arrives. Reporting-line review can briefly show `activation_pending` after the Owner decision while Core atomically converges the graph. Native detail controls expose stable approval and consent identifiers for audit drill-down. An actionless shadow Human-review Verdict whose exact reason is `no_rule_match` or `anomaly_action_unavailable` is audit evidence, not approval work: the Console may expose it in Verdict and audit views, but because Thor creates no `ActionRun` or resource claim, the Console does not synthesize a HIL queue item or consent/approval card. Only a newly judged actionable proposal can enter this fall-through.
## 8. Channel integration (push vs pull)

The channel abstraction ([channels-and-notifications.md](channels-and-notifications.md)) already handles push (system → human). Pull uses
**separate adapters and configuration contracts**. A deployment can reuse a secret provider or workload identity, but it does not derive
inbound conversation enablement from the outbound notification matrix. This separation preserves the different trust posture and blast
radius of send-only and receive-plus-send surfaces.

The shared pull-direction contract, gateway, Slack signed ingress, Teams authenticated activity normalizer, bounded Starlette routes, Slack
Web API publisher, and Teams Bot Framework publisher are implemented. The Slack route verifies timestamped signatures. The Teams route calls
an injected bearer authenticator before parsing activity JSON. Reply publishers use only configured HTTPS endpoints, injected app/workload
credentials, and server-owned conversation resolution. The delivery-layer channel runtime binds the concrete Bot Framework JWT verifier, Teams
principal resolver, Slack secrets/app credentials, fixed-endpoint publishers, and background gateway lifecycle. Missing required credentials
or identity bindings fail startup before traffic. Those bindings stay in `delivery/`; they do not change the coordinator.

`ChannelAccessService` is the sender-access foundation for those principal resolvers. Each channel selects `disabled`, `allowlist`, or
`pairing`. Unknown senders resolve to no principal and never reach the coordinator. Pairing mode issues a bounded, expiring challenge,
stores only its SHA-256 digest, caps pending requests per channel, requires a separately authorized approver, verifies the code in constant
time, and maps the approved sender to an existing FDAI principal. Disabled and allowlist modes never self-enroll a sender. The PostgreSQL
store now enforces the pending cap and approval transition atomically across replicas. Native challenge delivery replies in the originating
thread and conditionally removes the pending digest when delivery fails. The code is never stored or placed in response metadata.

`CrossChannelIdentityLinkService` records an explicit relationship only after both channel senders are independently paired to the same
principal. It rejects same-channel links, self-approval, unapproved endpoints, and any attempt to relate two distinct principals. The
durable link is idempotent and does not merge principal records, roles, sessions, or audit histories.

| Channel | Push (existing) | Pull (this doc) | Shared config |
|---------|-----------------|-----------------|---------------|
| Teams | A1 HIL and outbound notification adapters | `TeamsIngressVerifier` + authenticated bounded activity route + workload-identity reply publisher + principal binding | Deployments can reuse selected identity/secret providers. |
| Slack | `SlackWebhookChannel` and A1 adapter | `SlackIngressVerifier` + signed Events API route + fixed-endpoint Web API reply publisher | Deployments can reuse selected secret providers. |
| Email | send-only | (not planned; asynchronous, ill-suited to interactive) | n/a |
| Webhook | send-only | (not planned; caller must own an interactive protocol themselves) | n/a |
| Pager (PagerDuty) | send-only | (not planned) | n/a |
| SMS | send-only | (not planned) | n/a |
| Web chat | n/a | Authenticated `POST /chat` and `POST /chat/stream` SSE | Console SPA/Operator API config |
| CLI | n/a | stdin/stdout UI calling the shared Operator API `/chat`; explicit loopback Azure CLI profile with memory-only session bearer, never caller-supplied tokens | [CLI authentication](../../../cli/README.md#authentication); missing bootstrap permits only an ordinary read; `401`/`403` stays closed; Browser Entra is unchanged |

### 8.1 Separate channel configuration

[`config/notifications-matrix.yaml`](../../../config/notifications-matrix.yaml) owns outbound
notification routing only. Conversation channels use separate enablement, secret references,
Teams identity/principal bindings, and queue-capacity settings. Sharing a credential backend does
not merge configuration ownership.
## 9. Growth model (catalog + operator memory)

The console gets better over time via three deterministic mechanisms; model-side learning is **not** one of them. Operator Memory review applies the selected scope kind and reference to both entries and compaction candidates before the bounded read limit. Candidate rows expose their exact scope, and leaving either filter unset preserves the corresponding all-scope read without granting approval or memory-write authority.
After a joined Console catalog source changes, including Agent Activity or Trace presentation text, regenerate the complete question bank and then semantic intent coverage in the same delivery change; artifact equality rejects stale source digests, and a provenance-only refresh cannot change question identity, readiness, or authority. Run both artifact-equality checks after the second generator so the semantic inventory is verified against the newly materialized question bank. Recheck the final merged tree after a base update: a pass on the earlier topic head does not validate newly merged catalog bytes. Conversation Delivery likewise displays only recorded breaker-mode counts; regenerating its System Knowledge source commitment does not give the browser pause, resume, retry, approval, or escalation authority.

### 9.1 Day 1

The Day-1 console can answer:

- "What rules apply to `network.nsg` in `example-rg`?"
  → `query_inventory` + `explore_catalog`.
- "Why did event `<id>` route to HIL?" → `explain_verdict`.
- "Show me every audit entry for `object-storage.public-access.deny` in
  the last 24h." → `query_audit`.
- "If I create a storage account with public access enabled, what would
  the loop do?" → `describe_event`.

No writes, no runbooks, no approvals - just orientation.

### 9.2 Week 1

Adds `simulate_change`, `approve_hil`, `run_runbook --dry-run`, and the
Teams / Slack pull adapters. The console can now:

- Preview a change end-to-end in shadow.
- Resolve queued HIL items with the same identity gate the PR flow uses.
- Trigger the shipped runbooks
  ([docs/runbooks/](../../runbooks)) from any channel.

### 9.3 Month 1

Adds the observation-depth tools (§3.3) and the discovery-loop hook:

- The coordinator publishes a `console.recurrent_query` signal to the
  discovery-loop input stream when the same tool-argument shape appears
  N times across distinct principals in a rolling window (N configured;
  default 5 / week).
- The rule-candidate generator
  ([rule-governance.md](../rules-and-detection/rule-governance.md)) receives that signal like
  any other; the resulting rule ships shadow-first through the same
  promotion pipeline.

The result is that a common investigation pattern in chat becomes a
first-class rule in the catalog - **the console grows the catalog, not
itself**.
## 10. Rollout reconciliation

The original Day/Week/Month sequence is historical implementation context, not the current
availability source.

| Slice | Current status |
|-------|----------------|
| Core/CLI translator | `Narrator`, grounded answer rendering in the delivery-layer Azure OpenAI narrator adapter, coordinator, read tools, Python headless harness, and shared-API TypeScript CLI ship. Intent translation and answer rendering use separate prompts; both retain the deterministic tool and RBAC boundary. |
| Write/approval tools | Simulation, HIL, runbook, and proposal routes ship. Break-glass stops at the pager/audit request receipt in §7.3 and grants no elevation. |
| Teams/Slack conversation | The delivery-layer channel runtime, authenticated ingress, principal resolution, publishers, and optional durable replies ship; environment-owned enablement and credentials remain required. |
| Web chat and memory | JSON/SSE chat, principal-scoped history/preferences/memory, AnswerPlan, and progressive verification ship. The bounded timing parser accepts existing v1 envelopes and Core's v2 durable queue phase instead of discarding the complete timing envelope. |
| Observation/discovery | `POST /read-investigations` selects direct, streamed, or detached execution from durable latency evidence before Azure I/O. Direct Command Deck and HTTP reads share an owner-scoped result-replay ledger; closing a streamed response cancels its in-flight read. The surface is registered only with a dedicated reader binding; catalog presence alone proves neither provider health nor promotion. |
| Forecast and Dynamic learning | `GET /forecast-learning` projects forecast closure and publication health; `GET /dynamic-assurance` projects durable scalar/graph model summaries and trajectory closure counts. Both routes are Reader-only and expose no detector/model mutation, promotion, approval, or execution control. |
| Subscription provisioning | `/provisioning` replays durable stage evidence, follows estimated inventory progress, and renders verified readiness, failure, or cancellation without deployment authority. |
| System Knowledge role catalog | Regeneration can refresh cited Pantheon bus ownership, subscription, producer, and event-time facts while graph lifecycle ownership remains separate. Loki's score-producer citation changes no Console data source, timestamp authority, AKS scenario behavior, human reporting line, approval route, or execution authority. |

Live Azure completion evidence and capability promotion remain governed by deployment verification
and the authoritative registry, never inferred from phase names in this document.
## 11. Testability

- **Coordinator** - property tests: "verifier re-check runs on every
  write-class tool call", "RBAC floor is enforced before the narrator
  sees the tool schema", "audit entry precedes every tool dispatch",
  "escalation records tier and trigger".
- **Narrator adapter** - contract tests using `httpx.MockTransport` for the strict Azure OpenAI
  intent translator, injection-isolated grounded answer prompt, exact evidence-reference
  preservation, and resolved deployment binding.
- **Tools** - each tool has a shadow-mode test showing it never mutates
  when its `side_effect_class == read | simulate`; a `write` /
  `approve` test showing the verifier re-check gate.
- **Channels and service ownership** - CLI REPL golden transcript, Teams Bot Framework activity/JWT, Slack signed HTTP Events API, and publisher receipts. Every Operator service test is registered under exactly one group in `tests/integration/service-suites.json`; an unowned test fails the repository coverage gate before a service-specific runner can execute.
- **RBAC matrix** - table-driven test over every (Role × Tool) cell to
  prove the floor from §3.1-§3.3 is applied.
- **Break-glass** - tests prove `activate_break_glass` refuses `expiry > 4h`, requires Owner
  notification and audit receipts, and does not mutate the session principal. Persistent grants
  and session-end revocation are not shipped contracts.
- **Determinism** - two runs of the same CLI transcript through a fake
  `Narrator` produce byte-identical audit trails (given fixed
  timestamps and idempotency keys).
- **Session recovery** - principal-scoped `ConversationHistoryStore` reloads prior turns by session
  id, while stable request idempotency prevents duplicate appends. Audit/ontology retain hashes and
  references rather than raw transcripts.
## 12. Failure modes

- **Narrator unavailable** - fall through to Chat T0 direct-hit; if the
  turn does not match a T0 pattern, respond with a canned "reasoning
  layer is temporarily unavailable; here is the direct query surface"
  and expose the tools list.
- **Grounded answer rendering unavailable or invalid** - return the completed deterministic tool
  preview. The coordinator also uses this fallback when the model returns an empty or oversized
  answer or drops any required evidence reference. Rendering failure never changes tool data,
  status, authorization, or execution state.
- **Verifier abstain on write-class tool** - internally file a HIL
  review item (see §7.4), return the HIL id, audit reason
  `verifier_abstained`.
- **Channel adapter disconnects** - when durable delivery is configured, the complete response and
  terminal/ambiguous state remain in the ledger. The direct path still resumes durable conversation
  history by session id but does not claim exactly-once provider send.
- **Break-glass request receipt** - the coordinator does not interpret the receipt as elevated
  capability. A future grant integration must recheck TTL before every privileged tool call.
- **Tool implementation raises** - the tool's typed error surface (§3.4)
  is wrapped as a `ToolResult(status=error)`; the narrator sees a
  structured error, not an exception traceback.
## 13. Data + wire contracts

FDAI Console compiles the generated TypeScript view at `console/src/generated/service-contracts.ts`.
The checksum-pinned repository generator derives it from the same N/N-1 JSON Schemas used by the five backend services; the generated interface improves compile-time alignment only. For deployed AKS, the deployment coordinator registers the exact Static Web Apps redirect and publishes runtime API bindings after convergence. Browser route and Sample-mode restoration preserve an MSAL response hash until `handleRedirectPromise` consumes it.
The Operator service still validates wire payloads against the canonical schema, and Console receives no deployment, approval, mutation, or execution authority.
The Audit workspace requests the additive `summary=true` envelope. A current Operator returns retained-query counts, record context, and integrity observations, while an older Operator keeps the page-only envelope that Console treats as unavailable summary evidence.
Incident, Agent Activity, and Trace reads omit the flag and retain their bounded page cost.

Split into focused owner documents:

- [operator-console-wire-contracts.md](operator-console-wire-contracts.md) - audit entry, CLI REPL, approval callback (13.1-13.3), semantic Incident creation, managed-action submission status, Python VM workbench, grounded code, and ontology projection (13.6-13.9).
- [operator-console-view-snapshot.md](operator-console-view-snapshot.md) - the self-describing screen contract (13.4).
- [operator-console-incident-roster.md](operator-console-incident-roster.md) - incident roster, fix history, catalog-reused queued/applied status, bounded HTTP `202` revalidation, and the no-authority Huginn-to-Saga guidance audit path (13.5).
## 14. MCP delivery and managed catalog

FDAI's only shipped MCP integration is a single fixed-transport, read-only Azure MCP client
(`services/core-control-plane/src/fdai/delivery/azure/mcp_read_investigation.py`) for optional read
investigations, with typed provider fallback when unavailable. It is not an outbound catalog: there
is no per-server install/enable lifecycle, `tools/list` discovery, health monitor, or admin audit
record for externally hosted MCP servers today. A managed outbound catalog under
`services/core-control-plane/src/fdai/delivery/mcp/` - disabled-by-default install, non-invoking
discovery, allowlist verification, a durable revision-CAS snapshot, health monitoring, and endpoint
validation - remains a design target, not shipped behavior. Like publishing FDAI as an MCP server,
this is also unshipped: no inbound MCP server process, `list_tools`/`call_tool` wire endpoint, or
external MCP principal mapping exists today. A fork MUST NOT infer either surface here.

A future inbound MCP proposal can additively reuse the coordinator and RBAC, reject anonymous
callers, map mTLS or audience-scoped Entra identities to service `Principal` records, and audit the
resolved role. That remains future scope requiring its own threat model, protocol tests, and
deployment gates.
## 15. Decision status

- **OD-C1 resolved** - the strict core narrator prompt lives in the delivery-layer Azure OpenAI narrator adapter; the
  broader prompt catalog uses `rule-catalog/prompts/base`, `packs`, `scenarios`, and `tools`.
- **OD-C2 resolved** - principal-scoped user memory/preferences and separate governed operator
  memory now have schemas, provenance, consent, and retention paths.
- **OD-C3 residual** - persistent BreakGlass grant/elevation is not implemented. A future design
  must retain no-self-approval and separately approve any distinct-approver requirement.
- **OD-C4 current behavior** - CLI history is bounded process-memory navigation only. A persistent
  history file and retention/redaction contract are neither shipped nor blockers for the current CLI.
## 16. Further reading

- [architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) -
  trust routing, verifier authority.
- [action-ontology.md](../decisioning/action-ontology.md) - ActionType schema with the
  `trigger_kind` axis (`operator_request`) that the console emits, plus
  the `argument_schema` the coordinator validates against.
- [execution-model.md](../decisioning/execution-model.md) - the unified RiskGate the
  chat verifier re-check (§7.2) invokes, and the 5-axis authority
  matrix that decides auto / HIL / deny for every write-class tool call.
- [channels-and-notifications.md](channels-and-notifications.md) - the
  push-direction channel matrix this doc's pull side extends.
- [user-rbac-and-identity.md](user-rbac-and-identity.md) - the RBAC role
  set the tool matrix (§3) references.
- [security-and-identity.md](../architecture/security-and-identity.md) - no-self-approval,
  execution identity, safety invariants.
- [prompt-composition.md](../decisioning/prompt-composition.md) - narrator prompt
  layering, tool-schema exposure, debate orchestrator (Wave 4.5) that
  Month 1 may consume.
- [rule-governance.md](../rules-and-detection/rule-governance.md) - the discovery loop the
  Month-1 console feeds.
- [project-structure.md § console/](../architecture/project-structure.md#module-boundaries) -
  the FDAI Console SPA the Month-1 web-chat channel extends.

## Related docs

| To learn about | Read |
|----------------|------|
| Delivery status and Live design | [Implementation ledger](../../roadmap-implementation/interfaces/operator-console.md), [Live metrics](live-cockpit-metrics.md), [Live and Audit presentation](live-audit-presentation.md) |
