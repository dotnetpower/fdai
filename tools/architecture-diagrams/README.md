# Architecture Diagram Compiler

This package compiles bilingual FDAI architecture specifications into static
SVG and PNG assets plus a progressively enhanced site viewer. It keeps diagram
topology under `docs/diagrams/` and leaves `site/` as a presentation layer.

## Layout

| Path | Purpose |
|------|---------|
| `schema/diagram.schema.json` | JSON Schema for groups, nodes, ports, edges, legends, and localized text. |
| `src/layout/` | ELK compound-graph layout with orthogonal edge routing. |
| `src/render/` | Accessible SVG renderer and verified icon embedding. |
| `src/viewer/` | Dependency-light Web Component with pan, zoom, node focus, fullscreen, and download. |
| `assets/azure/` | Allowlisted official Azure icons and provenance lock. |
| `assets/fonts/` | Noto Sans KR subset used for deterministic bilingual PNG output. |
| `test/` | Schema, reference-integrity, layout, and SVG regression tests. |

The source and output ownership is:

| Path | Ownership |
|------|-----------|
| `docs/diagrams/*.diagram.yaml` | Canonical, hand-authored diagram topology and localized copy. |
| `docs/diagrams/generated/` | Generated static assets for GitHub-rendered documentation. |
| `site/public/diagrams/architecture-diagram.js` | Generated interactive viewer for the docs site. |
| `site/public/diagrams/generated/` | Generated static assets and manifest for the docs site. |

Don't hand-edit generated files. Change the YAML source or compiler and run the
renderer.

## Commands

Run commands from the repository root:

```bash
npm --prefix tools/architecture-diagrams ci --no-audit --no-fund
npm --prefix tools/architecture-diagrams test
npm --prefix tools/architecture-diagrams run typecheck
npm --prefix tools/architecture-diagrams run validate
npm --prefix tools/architecture-diagrams run render
npm --prefix tools/architecture-diagrams run check
```

`render` writes both generated output trees. `check` compiles in memory and
fails when a committed artifact is missing or stale.

## Diagram kinds

Use `kind` to select a validated layout strategy rather than treating it as a
descriptive tag. Existing Azure topology kinds remain supported, while logical
and behavioral diagrams use the same bilingual compiler and viewer.

| Family | Kinds | Strategy or required primitive |
|--------|-------|--------------------------------|
| Architecture | `context`, `container`, `component`, `deployment`, `network`, `architecture`, `c4-context`, `c4-container`, `c4-component`, `c4-deployment` | Layered compound graph with optional deployment hierarchy |
| Flow | `data-flow`, `flowchart`, `graph`, `conceptual-flow` | Layered semantic flow with optional conceptual profile |
| Interaction | `sequence`, `railroad` | Ordered interaction path |
| Process | `swimlane`, `user-journey`, `kanban`, `block`, `cynefin` | Lane or grid layout |
| State and decisions | `state`, `decision-tree`, `requirement` | Transition, tree, or dependency layout |
| Semantic models | `domain`, `entity-relationship`, `class-diagram`, `mindmap`, `ishikawa`, `tree-view` | Association or tree layout |
| Time | `timeline`, `gantt`, `git-graph`, `event-modeling` | Timeline or scaled task bars |
| Coordinates | `quadrant`, `xy-chart`, `wardley`, `venn` | `xValue`, `yValue`, and optional `size` |
| Radial charts | `pie`, `radar` | Positive `value` fields and radial geometry |
| Weighted and partitioned | `sankey`, `packet` | Edge `weight` or node `value` |

Kind-specific requirements fail during validation. This prevents a nominal
sequence diagram with no interactions or a swimlane diagram with no lanes from
silently rendering as an unrelated generic graph.

Chart-oriented kinds use data fields in addition to the common node contract:

- Gantt tasks use `start` or `after` plus `end` or `duration`. Optional
  `status` and `progress` drive bar presentation and viewer details.
- Pie and radar nodes use `value`. Pie nodes use `shape: pie-slice`.
- Quadrant, XY, Wardley, and Venn nodes use `xValue` and `yValue` on a
  normalized 0-100 axis. `size` controls the rendered marker.
- Block, packet, Kanban, and Cynefin layouts may set `row` and `column`.
- Sankey connectors set `weight`; the renderer scales stroke width without
  changing the edge's semantic kind.

## Authoring contract

Each `.diagram.yaml` file contains:

- Document metadata and `en` / `ko` title, description, and detailed alt text.
- Nested groups that represent system, cloud, network, subnet, cluster, or
  logical layer boundaries.
- Nodes with stable ASCII ids and localized labels.
- Agent nodes use their named glyph from the canonical
  `console/public/agent-icons/manifest.json` pantheon set. Actual Azure and
  third-party products use only the verified product catalogs. FDAI-owned
  concepts may use a statically allowlisted `lucide-*` line glyph; unsupported
  names fail compilation. Nodes without an icon remain text-only cards rather
  than profile initials.
- A non-agent node that represents the complete fixed runtime can set
  `icon: agent-pantheon`. This collective mark doesn't create a sixteenth agent.
- Single-direction edges with an explicit semantic kind.
- A legend whenever line styles carry meaning.

SVG is the mandatory canonical format. Diagrams default to SVG and PNG for
backward compatibility, and can set `formats: [svg]` when no raster consumer
exists.

### Conceptual architecture

Set `canvas.profile: conceptual` for architecture flows such as
`docs/diagrams/fdai-conceptual-control-loop.diagram.yaml`. Keep domain meaning
in `kind`, and use presentation fields only for visual communication:

- Use `shape` for `card`, `diamond`, `terminator`, `database`, `document`, or
  `circle` geometry.
- Use `tone` for semantic color roles such as `input`, `model`, `policy`,
  `decision`, `execution`, `feedback`, or `store`.
- Use `content` for localized bullet text inside a node and `badge` for a
  numbered stage.
- Use `presentation: lane`, `sidebar`, `feedback`, or `datastore` for logical
  group surfaces.
- Use a tone legend for colored stages and an edge legend for connector
  semantics.

```yaml
kind: conceptual-flow
canvas:
  width: 1600
  height: 900
  direction: RIGHT
  rootLayout: column
  profile: conceptual
groups:
  - id: governed-flow
    kind: layer
    presentation: lane
    layout: row
    label: { en: Governed flow, ko: 통제된 흐름 }
nodes:
  - id: policy
    parent: governed-flow
    kind: decision
    shape: diamond
    tone: policy
    badge: 1
    label: { en: Policy decision, ko: 정책 결정 }
    content:
      - { en: "Allow, deny, or hold", ko: "허용, 거부 또는 보류" }
edges: []
legend:
  - tone: policy
    label: { en: Policy judgment, ko: 정책 판단 }
```

Deployment diagrams can opt into `canvas.profile: azure-reference` for a compact,
icon-forward Azure reference style. In that profile, use semantic presentation
values instead of pixel-level styling:

- Set groups to `presentation: boundary`, `band`, or `panel` to distinguish
  network boundaries, subnet bands, and surrounding surfaces.
- Set a group to `layout: row` or `layout: column` when its direct child nodes
  or groups need a stable presentation independent of cross-group edges.
- Set `gap` on an explicit row or column when routing corridors need more room
  than the compact profile's default spacing.
- Set `justify: center` or `justify: start` when a fixed-width row shouldn't
  spread a small child set across all available space.
- Set icon-bearing nodes to `presentation: icon` when the official product icon
  should carry the visual hierarchy. FDAI-owned runtime components remain cards.
- Set `step` on an edge to render a numbered flow badge separately from its
  localized label.

High-level overviews keep architecture responsibilities in separate labeled
groups instead of merging every human and delivery surface into one box. The
renderer preserves ELK's collision-aware orthogonal route, then rounds each
bend with a bounded quadratic curve. Direct hops stay straight, so curved
connectors improve flow without turning the diagram into an ambiguous free-form
graph.

Supporting groups can opt into `placement: top`, `below`, or `right` to form a
stable region composition. Set `placementGap` to control the gap to the aligned
surface. Add `alignWith: <group-id>` when that band should share the horizontal
center of a nested reference group.
Individual cross-layer edges can opt into an explicit route; compilation rejects
a route when it crosses an unrelated node. All other edges retain ELK routing
and bounded corner rounding. Use `orthogonal-shortest` for an obstacle-aware
one-bend connection that falls back to the standard orthogonal route when both
L-shaped candidates are blocked. Use `orthogonal-outer` when a connection must
leave its source band before following a right-side corridor across stacked
bands.

The validator rejects unknown keys, duplicate ids, missing locales, unknown
parents, edges that reference missing elements, and port references that don't
exist on the selected node. Edges can target a group boundary when the diagram
needs to show a relationship at that abstraction level. Display text is escaped
before it reaches SVG. The viewer accepts only generated SVG without scripts,
`foreignObject`, or external image references.

Layout and rendering share one bilingual text-geometry module. It estimates
Latin and CJK width separately, wraps long tokens without truncation, sizes each
node for the longer locale, reserves separate icon and label zones, and gives
ELK the widest localized edge-label box before routing. Compilation fails when
nodes overlap, a node escapes its parent, or an edge label overlaps a node. This
makes collision checks part of the generated-asset contract rather than a
manual screenshot convention.

ELK still computes orthogonal collision-safe routes, but the SVG renderer rounds
each bend with a bounded quadratic curve. Straight control-loop hops stay
straight, while longer cross-region paths gain Mermaid-like visual flow without
cutting through nodes. Region boundaries use distinct header bands for
operational signals, the FDAI control plane, and human or delivery surfaces.

## Azure icons and fonts

Only use an official Azure icon for an actual Azure service. Keep the product
name adjacent to the icon. Don't crop, rotate, recolor, distort, or use an Azure
icon to represent an FDAI component.

FDAI-owned concepts may use the statically imported Lucide glyphs allowlisted in
the renderer. The package pins Lucide through `package-lock.json`; Lucide is
distributed under the ISC license, with Feather-derived portions under MIT. See
the installed package `LICENSE` and <https://lucide.dev/license>.

The compiler verifies every vendored icon against `assets/azure/icons.lock.json`.
Builds don't download assets from the network. When updating the official icon
pack, review the current Microsoft terms, replace only the allowlisted subset,
and update the archive and file checksums together.

PNG output uses the checked-in Noto Sans KR subset with system fonts disabled.
If a new diagram introduces a missing glyph, regenerate the subset from the
Google Fonts source recorded in `assets/fonts/font.lock.json`, update its
checksum, and inspect both locale PNG files before merging.

## Site integration

The docs page keeps an ordinary localized `<img>` inside
`<fdai-architecture-diagram>`. Without JavaScript, the SVG remains readable.
With JavaScript, the generated Web Component loads the same SVG and adds a
compact floating toolbar plus a component-detail panel. The toolbar appears at
the upper right when the diagram is hovered or receives keyboard focus; touch
devices keep it visible. Desktop starts with the full diagram at its native
aspect ratio. Narrow screens start with a readable crop that leaves room to pan
on both axes and provide a separate overview control. Arrow keys pan,
`+` and `-` zoom, `0` resets the view, and `Escape` clears a selected component.
Hovering a connector or its label emphasizes both, so a label remains traceable
through dense crossings.
The mouse wheel always keeps its normal page-scrolling behavior. Use the toolbar
or keyboard controls to zoom the diagram.
Relative URLs keep localhost, GitHub Pages, and downstream project base paths
aligned.

The visual palette follows the FDAI option-B prototype: Azure blue `#0078d4`,
cyan `#50e6ff`, Fluent ink surfaces, and the existing semantic action colors.
Static SVG and PNG use the light palette. The interactive viewer supplies dark
ink surfaces and cyan/azure accents through inherited CSS variables when the
site switches theme.

## Verification

Before submitting a change:

1. Run the package tests, typecheck, `render`, and `check` commands.
2. Run `npm --prefix site test` and `npm --prefix site run build`.
3. Inspect English and Korean output at desktop and mobile widths.
4. Select a node with pointer and keyboard input and confirm that related flows
   and localized detail text appear.
