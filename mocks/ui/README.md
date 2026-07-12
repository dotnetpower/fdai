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
| [dashboard.html](dashboard.html) | Overview - success/guard KPIs, trust-tier + risk-gate distribution, mode mix, top HIL items, recent audit |
| [hil.html](hil.html) | HIL queue - plain-first approval cards with safety facts, filters by risk / category / vertical |
| [promotion.html](promotion.html) | Shadow to enforce candidates and the four gate checks (accuracy, escapes, guard budget, safety invariants) |
| [rules.html](rules.html) | Rule catalog: accepted rules, discovery-loop candidates, scoped overrides |
| [actions.html](actions.html) | ActionType ontology - trigger, execution path, rollback contract, six-axis risk ceiling |
| [audit.html](audit.html) | Append-only stream - execute, reject, timeout, abstain, deny, override change, rollback |

Fleet / Safety surfaces (mirror console panels under `Now` and `Safety`):

| File | Purpose |
|------|---------|
| [agents.html](agents.html) | Fleet roster - lifecycle state of all 15 pantheon agents (running / idle / recovering / shadow) with per-agent throughput and chat entry |
| [pantheon.html](pantheon.html) | Pantheon directory - 15 agents grouped by governance / pipeline / domain layer, with the reporting tree |
| [agent-activity.html](agent-activity.html) | Per-agent timeline projected from the audit log - who did what, when, and how; verbs = execute / approve / reject / rollback / abstain / audit |
| [blast-radius.html](blast-radius.html) | Per-action impact view - concentric target / direct / indirect rings plus cap bars enforced by the risk gate |
| [provision.html](provision.html) | In-flight re-provision - Terraform stream projected as status + resource list + live event log; console URL surfaces on `provision.done` |
| [llm-cost.html](llm-cost.html) | LLM spend - per-tier daily budget bars, event mix, 7-day trend, per-model attribution table |

Knowledge surfaces (ontology + trace):

| File | Purpose |
|------|---------|
| [ontology.html](ontology.html) | ObjectType + LinkType registry - sidebar list, one-hop neighborhood SVG, per-type detail card |
| [rule-trace.html](rule-trace.html) | Per-correlation timeline - the full pipeline path (ingest &rarr; router &rarr; quality gate &rarr; risk gate &rarr; dispatch &rarr; audit) for one event id |
| [workflow-builder.html](workflow-builder.html) | Read-only visual view of a `when &rarr; do` workflow - ActionType palette, node/edge canvas, per-step inspector with safety facts |

Report and kit:

| File | Purpose |
|------|---------|
| [report.html](report.html) | Weekly review layout: numbered sections, KPI grid, AS-IS / TO-BE compare, critique table |
| [components.html](components.html) | Component gallery: KPI cards, tables, tags, severity, alerts, forms, tabs, tier chips, meters |
| [index.html](index.html) | Kit landing: palette, page index, design principles |

## Assets

- [assets/calm-slate.css](assets/calm-slate.css) - the whole theme: CSS variables (palette),
  layout container (max-width 1160px), section number badges, cards, KPI grid, AS-IS/TO-BE
  comparison, critique table, pill tags, severity badges, trust-tier chips, buttons, forms,
  alerts, tabs, meters, and the Live cockpit (activity swarm, sparkline strip, audit ticker).
  All classes are prefixed `cs-`.
- [assets/calm-slate.js](assets/calm-slate.js) - minimal tab switching only; no privileged calls.
- [assets/live.js](assets/live.js) - Live cockpit only. Generates synthetic control-plane events,
  routes them through T0 / T1 / T2 with the roadmap's distribution, and renders the swarm,
  sparkline, and audit ticker. Pure client-side, no backend.

## Usage

Open any page directly in a browser (no build step):

```
ui/index.html
```

Reuse the kit by linking the stylesheet and applying `cs-` classes:

```html
<link rel="stylesheet" href="assets/calm-slate.css" />
<div class="cs-card cs-kpi">
  <div class="cs-kpi-accent"></div>
  <span class="cs-kpi-label">Auto-resolution rate</span>
  <span class="cs-kpi-value">87.4%</span>
</div>
```

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
  privileged calls (approvals flow through ChatOps or a remediation PR).
