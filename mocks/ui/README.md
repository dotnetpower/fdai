# Calm Slate - FDAI UI Kit

A static, dependency-free component library and page templates for the FDAI
**read-only operator console** and generated reports. The theme is toned-down and
report-oriented: a desaturated palette, hairline borders, soft shadows, numbered section
badges - calm and professional, with no primary/neon colors and no top/bottom color bands.

> This is a static demo (plain HTML/CSS/JS). It is English-only and customer-agnostic; all
> values shown are synthetic placeholders. It follows the app-shape rule that the console is
> **read-only** - the pages render state but execute no actions. See
> [../../.github/instructions/app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md).

## Pages

Operator console (read-only). Overview / Now / History surfaces:

| File | Purpose |
|------|---------|
| [live.html](live.html) | Live cockpit - activity swarm of tiles for control-plane events flowing through T0 / T1 / T2, KPI strip with sparkline, audit ticker |
| [dashboard.html](dashboard.html) | Dashboard - operating posture, evidence-qualified summaries, aggregated attention, and links into focused Overview analysis |
| [operating-outcomes.html](operating-outcomes.html) | Operating outcomes - measured results, baselines, trends, and cross-vertical breakdowns |
| [control-assurance.html](control-assurance.html) | Control assurance - safety posture, policy escapes, promotion guards, and required attention |
| [verticals.html](verticals.html) | Vertical outcomes - comparable results for Resilience, Change Safety, and Cost Governance |
| [trust-routing.html](trust-routing.html) | Trust routing - T0, T1, and T2 distribution, governed T2 flow, and leading indicators |
| [llm-cost.html](llm-cost.html) | LLM cost - per-tier daily budget bars, event mix, 7-day trend, and per-model attribution |
| [incidents.html](incidents.html) | Incident-centric roster with active/resolved filtering, current disposition, and per-incident fix history |
| [hil.html](hil.html) | Human approval queue - plain-first approval cards with safety facts, filters by risk / category / vertical |
| [detection-readiness.html](detection-readiness.html) | Detection-readiness evidence with target decisions, coverage gaps, and authority ceilings |
| [configuration-baselines.html](configuration-baselines.html) | Baseline integrity, drift, Knowledge evidence, history, review readiness, and measured latency |
| [processes.html](processes.html) | Runtime process list, filters, selected process detail, and immutable workflow facts |
| [workflow-apps.html](workflow-apps.html) | Published workflow-specific read surfaces and recent run history |
| [scheduler-runs.html](scheduler-runs.html) | Scheduler dispatch filters, evidence metrics, and bounded attempt history |
| [background-tasks.html](background-tasks.html) | Owner-scoped read-only investigations with selected task detail and progress timeline |
| [automation-blueprints.html](automation-blueprints.html) | Recurring-work suggestions, review state, confidence, cost, and isolation profile |
| [scheduled-continuations.html](scheduled-continuations.html) | Scoped conversation anchors with exact result, origin, evidence, digest, and expiry |
| [conversation-delivery.html](conversation-delivery.html) | Delivery reliability, latency, duplicate risk, state distribution, and adapter breakers |
| [promotion.html](promotion.html) | Shadow to enforce candidates and the four gate checks (accuracy, escapes, guard budget, safety invariants) |
| [rules.html](rules.html) | Rule catalog: accepted rules, discovery-loop candidates, scoped overrides |
| [actions.html](actions.html) | ActionType ontology - trigger, execution path, rollback contract, six-axis risk ceiling |
| [audit.html](audit.html) | Append-only stream - execute, reject, timeout, hold for review, deny, override change, rollback |
| [rca.html](rca.html) | Root-cause hypothesis with tier, confidence, grounded citations, causal chain, response plan, and explicit held for review state |
| [rca-report.html](rca-report.html) | Browser-scale detailed RCA report using the same Calm Slate shell, spacing, cards, tables, and evidence hierarchy as the console mocks |

Fleet / Safety surfaces (mirror console panels under `Now` and `Safety`):

| File | Purpose |
|------|---------|
| [agents.html](agents.html) | Fleet - live state, current work, fixed ownership, role boundaries, throughput, and chat entry for all 15 agents |
| [agents-constellation.html](agents-constellation.html) | Org - reporting lines with incident focus rings and the per-incident agent conversation panel |
| [agent-activity.html](agent-activity.html) | Per-agent timeline projected from the audit log - who did what, when, and how; verbs = execute / approve / reject / rollback / hold for review / audit |
| [impact scope.html](blast-radius.html) | Per-action impact view - responsive query controls, concentric target / direct / indirect rings, and cap bars enforced by the safety check |
| [provision.html](provision.html) | In-flight re-provision - Terraform stream projected as status + resource list + live event log; console URL surfaces on `provision.done` |

Visualization surfaces:

| File | Purpose |
|------|---------|
| [service-map.html](service-map.html) | Directional service topology preview with 2.5D resources, merged bidirectional roads, glow traffic, port and TLS details, hover-revealed zoom controls, fullscreen, shared tooltips, four analysis modes, and a selected-resource inspector. All topology and telemetry values are synthetic. |

Knowledge surfaces (ontology + trace):

| File | Purpose |
|------|---------|
| [ontology.html](ontology.html) | ObjectType + LinkType registry - sidebar list, one-hop neighborhood SVG, per-type detail card |
| [ontology-map.html](ontology-map.html) | Actual 33 ObjectType / 46 LinkType / 44 ActionType declaration graph with searchable registry modes and inspectors |
| [ontology-knowledge-graph.html](ontology-knowledge-graph.html) | Complete generated catalog graph with type colors, weighted topology communities, fullscreen canvas, and current catalog relationships |
| [rule-trace.html](rule-trace.html) | Per-correlation timeline - the full pipeline path (ingest &rarr; router &rarr; quality gate &rarr; safety check &rarr; dispatch &rarr; audit) for one event id |
| [workflow-builder.html](workflow-builder.html) | Read-only visual view of a `when &rarr; do` workflow - ActionType palette, node/edge canvas, per-step inspector with safety facts |
| [architecture.html](architecture.html) | Production Architecture route structure with summary metrics, observed path, selected relationship, and stored-topology boundary |
| [agent oversight mock](handover.html) | Agent oversight workspace with ownership coverage, operational ownership (`stewardship`) facts, and identity health |
| [capabilities.html](capabilities.html) | Capability declarations with side-effect class, default mode, eligibility, and required role |
| [skills.html](skills.html) | Runtime skill packages, dependencies, agent eligibility, bundles, and load diagnostics |
| [context-selection-comparisons.html](context-selection-comparisons.html) | Baseline and candidate context-policy evaluation with token, overlap, pinned-evidence, latency, and failure facts |
| [scope.html](scope.html) | Effective monitoring and action scope with independent IAM and executor boundaries |

Evidence and governed-source surfaces:

| File | Purpose |
|------|---------|
| [browser-evidence.html](browser-evidence.html) | Redacted browser-evidence metadata, custody, isolation, expiry, and legal-hold state |
| [forecast-learning.html](forecast-learning.html) | Prediction closure, outcome distribution, publication debt, and retention debt |
| [conversation-search.html](conversation-search.html) | Authorized conversation search filters, result summaries, and selected context posture |
| [conversation-assurance.html](conversation-assurance.html) | Answer review, model agreement, cost, dispute state, and selected assessment detail |
| [reports.html](reports.html) | Declarative report selection, bounded variables, source readiness, and rendered widgets |
| [documents.html](documents.html) | Governed document-ingestion form, scan/protection state, and recent ingestion results |

Console utility surfaces:

| File | Purpose |
|------|---------|
| [labs.html](labs.html) | Development-only index for static experiments and shared design studies |
| [settings-runtime.html](settings-runtime.html) | Audited runtime-policy values, revisioned overrides, restart requirements, and unavailable state |
| [settings-iam.html](settings-iam.html) | Identity and access tabs for personal access, users, roles, and governed requests |

Chat surfaces:

| File | Purpose |
|------|---------|
| [deck.html](deck.html) | Command deck (chat) - transcript-first workspace with optional conversation history and current-screen context panels, visible Bragi-to-agent handoffs, grounded citations, observed read-command evidence, and evidence attachments |
| [deck-sources.html](deck-sources.html) | Same conversation surface zoomed into how Bragi streams retrieval + citations into an in-progress reply |
| [deck-sources-v2.html](deck-sources-v2.html) | Adaptive response lifecycle with an in-transcript selector for investigation, clarification, evidence posture, governed proposal, effect verification, cancellation, memory retention, structured brief, and rendered Markdown document examples |
| [conversation-response-patterns.html](conversation-response-patterns.html) | Operational response patterns and deterministic selection order for bounded investigation disclosure, target clarification, evidence limits, governed recovery proposals, graded effect verification, cancellation receipts, consent-based durable learning, structured operational briefs, and rendered Markdown documents |

Presentation wireframes (offline, not part of the console shell):

| File | Purpose |
|------|---------|
| [roadmap-slide-wireframe.html](roadmap-slide-wireframe.html) | 16:9 PPT roadmap draft: a concise operating-model slide that connects SRE to Resilience (Chaos/DR), Change Safety (ARB + Change Management), and Cost Governance (FinOps), followed by a three-horizon capability roadmap. Timelines and maturity states are proposals, not completion claims. |

Report and kit:

| File | Purpose |
|------|---------|
| [report.html](report.html) | Weekly review layout: numbered sections, KPI grid, AS-IS / TO-BE compare, critique table |
| [typography.html](typography.html) | Shared semantic type scale, composed content hierarchy, English/Korean copy, and long-identifier reading bounds |
| [components.html](components.html) | Searchable 23-section component gallery with exact-section links, light and dark previews, keyboard interaction states, shared typography, metrics, tables, forms, navigation, feedback, charts, code, lists, menus, drawers, data states, notifications, and calendars |
| [index.html](index.html) | Kit landing: palette, page index, design principles |

## Assets

- [../../ui/calm-slate-tokens.css](../../ui/calm-slate-tokens.css) - shared palette, typography,
  shape, and elevation tokens consumed by both the Console and static prototypes.
- [../../ui/calm-slate-primitives.css](../../ui/calm-slate-primitives.css) - shared presentation
  primitives such as the semantic top-edge content-update shimmer.
- [assets/calm-slate.css](assets/calm-slate.css) - mock layout and component styles over the shared tokens:
  layout container (max-width 1160px), section number badges, cards, KPI grid, AS-IS/TO-BE
  comparison, critique table, pill tags, severity badges, trust-tier chips, buttons, forms,
  selection controls, native date and time inputs, range controls, alerts, tabs, pagination,
  loading and empty states, tooltips, dialogs, syntax-highlighted code, grid and stacked lists,
  feeds, rich selects, comboboxes, dropdowns, drawers, responsive data states, notifications,
  calendars, meters, reusable charts, and the Live cockpit (activity swarm, sparkline strip, audit ticker). All
  classes are prefixed `cs-`.
- [assets/calm-slate.js](assets/calm-slate.js) - shared left navigation, tab switching, local
  select and menu behavior, code copy feedback, drawers, notifications, calendar selection, and
  chart detail modals; no privileged calls. Direct page loads render the full navigation.
  Pages embedded by the kit landing suppress their local shell so the navigation is not nested.
- [assets/live.js](assets/live.js) - Live cockpit only. Generates synthetic control-plane events,
  routes them through T0 / T1 / T2 with the roadmap's distribution, stops non-executable paths
  before execution and effect observation, and reports omitted synthetic attempts when the preview
  pool is saturated. Its 12-item work pool renders as a four-column desktop swarm and responsive
  tablet or mobile flow with a 12px operational text floor and 11px technical annotations. It
  explains tier, autonomy, and mode badges on hover or focus. Queue preserves the same work facts
  as Flow while adding risk, SLA, and control state. The page renders the swarm, sparkline, and
  audit ticker entirely client-side with no backend.

## Usage

Open any page directly in a browser (no build step):

```
ui/index.html
```

The kit landing keeps the page index and preview in one frame. Opening a page directly uses the
same left navigation and highlights the current page. On narrow screens, use the menu button to
open the navigation without reducing the content width.

Reuse the kit by linking the stylesheet and applying `cs-` classes:

```html
<link rel="stylesheet" href="assets/calm-slate.css" />
<div class="cs-card cs-kpi">
  <span class="cs-kpi-label">Auto-resolution rate</span>
  <span class="cs-kpi-value">87.4%</span>
</div>
```

Content containers never use colored top or left edge accents. This includes KPI stamps,
severity rails, inset selection rails, and pseudo-element strips. Put status in text, icons,
pills, a complete neutral or softly tinted border, or a subtle whole-surface tint. Position-based
mechanics such as navigation selection, chart edges, progress, and focus outlines remain valid.

## Palette

| Role | Hex |
|------|-----|
| Background | `#FBFAF9` |
| Card | `#FFFFFF` |
| Text / soft | `#2C333A` / `#6B7178` |
| Hairline | `#E3E1DE` |
| Steel blue (primary) | `#44688E` |
| Slate navy | `#3E4C59` |
| Sage / Terracotta / Dusty red / Teal / Plum | `#5E8259` / `#BC7449` / `#AC5A5A` / `#4F847E` / `#7B6C9C` |

Font stack: `"Segoe UI", "Malgun Gothic", sans-serif`.

## Conventions

- English-only content and identifiers; no customer names, ids, endpoints, or secrets.
- Muted accents carry meaning (severity, trust tier, trend) - never decoration for its own sake.
- The console demo shows buttons/forms as style samples only; the production console issues no
  privileged calls (approvals flow through ChatOps or a fix PR).
