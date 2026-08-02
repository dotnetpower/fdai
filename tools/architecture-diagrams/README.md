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

## Authoring contract

Each `.diagram.yaml` file contains:

- Document metadata and `en` / `ko` title, description, and detailed alt text.
- Nested groups that represent system, cloud, network, subnet, cluster, or
  logical layer boundaries.
- Nodes with stable ASCII ids and localized labels.
- Agent nodes use their named glyph from the canonical
  `console/public/agent-icons/manifest.json` pantheon set. Non-agent nodes
  without an explicit product icon render as text-only cards rather than
  profile initials.
- A non-agent node that represents the complete fixed runtime can set
  `icon: agent-pantheon`. This collective mark doesn't create a sixteenth agent.
- Single-direction edges with an explicit semantic kind.
- A legend whenever line styles carry meaning.

SVG is the mandatory canonical format. Diagrams default to SVG and PNG for
backward compatibility, and can set `formats: [svg]` when no raster consumer
exists.

Deployment diagrams can opt into `canvas.profile: azure-reference` for a compact,
icon-forward Azure reference style. In that profile, use semantic presentation
values instead of pixel-level styling:

- Set groups to `presentation: boundary`, `band`, or `panel` to distinguish
  network boundaries, subnet bands, and surrounding surfaces.
- Set a group to `layout: row` or `layout: column` when its direct child nodes
  or groups need a stable presentation independent of cross-group edges.
- Set `gap` on an explicit row or column when routing corridors need more room
  than the compact profile's default spacing.
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
stable region composition. Add `alignWith: <group-id>` when that band should
share the horizontal center of a nested reference group.
Individual cross-layer edges can opt into an explicit route; compilation rejects
a route when it crosses an unrelated node. All other edges retain ELK routing
and bounded corner rounding.

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
