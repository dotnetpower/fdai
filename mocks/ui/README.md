# Calm Slate — AIOpsPilot UI Kit

A static, dependency-free component library and page templates for the AIOpsPilot
**read-only operator console** and generated reports. The theme is toned-down and
report-oriented: a desaturated palette, hairline borders, soft shadows, numbered section
badges — calm and professional, with no primary/neon colors and no top/bottom color bands.

> This is a static demo (plain HTML/CSS/JS). It is English-only and customer-agnostic; all
> values shown are synthetic placeholders. It follows the app-shape rule that the console is
> **read-only** — the pages render state but execute no actions. See
> [../.github/instructions/app-shape.instructions.md](../.github/instructions/app-shape.instructions.md).

## Pages

| File | Purpose |
|------|---------|
| [index.html](index.html) | theme overview: palette, page index, design principles |
| [components.html](components.html) | component gallery: KPI cards, tables, tags, severity, alerts, forms, tabs, tiers, meters |
| [report.html](report.html) | report layout: numbered sections, KPI grid, AS-IS/TO-BE compare, critique table |
| [dashboard.html](dashboard.html) | read-only operator console: KPIs, HIL queue, shadow results, audit log |

## Assets

- [assets/calm-slate.css](assets/calm-slate.css) — the whole theme: CSS variables (palette),
  layout container (max-width 1160px), section number badges, cards, KPI grid, AS-IS/TO-BE
  comparison, critique table, pill tags, severity badges, trust-tier chips, buttons, forms,
  alerts, tabs, and meters. All classes are prefixed `cs-`.
- [assets/calm-slate.js](assets/calm-slate.js) — minimal tab switching only; no privileged calls.

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
- Muted accents carry meaning (severity, trust tier, trend) — never decoration for its own sake.
- The console demo shows buttons/forms as style samples only; the production console issues no
  privileged calls (approvals flow through ChatOps or a remediation PR).
