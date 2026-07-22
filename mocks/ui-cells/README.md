# UI Cells - WebGL2 living-organism mock

Exploratory mock for a hierarchical, zoomable view of the FDAI control-plane state.
Renders as one "organism" of weighted Voronoi cells inside a hexagon; users zoom from the
whole tenant view down to individual rules/resources.

Not the production console. The production operator console stays a thin read-only DOM SPA
(see [../../.github/instructions/app-shape.instructions.md](../../.github/instructions/app-shape.instructions.md));
this is an exploratory ambient/visual layer.

## What it demonstrates

- **Two grouping axes over the same tree**:
  - **WAF Pillars** (initial): `pillar → category → rule` - Well-Architected Framework
    (Reliability, Security, Cost, Operational Excellence, Performance, Sustainability).
  - **Topology**: `subscription → resource-group → resource → sub-part`.
  - **Severity**: `severity → pillar → rule`.
  - Toggle in the HUD swaps the grouper function; layout is recomputed only when the
    topology of the tree actually changes.
- **Discovery / init state**: on cold start the tree is present but empty - cells are laid
  out as translucent isometric building outlines. A simulated auth → permission →
  discovery → evaluation stream fills each building from the base upward as its data
  arrives. Buildings fade out and cells transition to their steady-state color on ready.
- **Palette system**: five swappable palettes (Azure Semantic, Aurora Orb, Azure Brand,
  WAF Pillar categorical, Colorblind-safe). Palette choice persists in `localStorage`.
- **Risk-oriented color**: `g ∈ [0,1]` where **higher = more risk** (`g_direction: "risk"`).
  Palette direction is chosen to match - hotter/redder colors indicate more risk.
- **WebGL2 rendering**: cell fills and rims each render in one draw call. Zoom/pan updates
  uniforms only; mesh is rebuilt on topology change (view toggle, lazy expand).

## Not implemented (intentional, mock scope)

- Real Azure Resource Graph / MSAL - the discovery stream is a synthetic SSE replay.
- Full 10k-leaf performance work (single draw call is set up, but not stress-tested).
- Deep-linking via `location.hash`, cache warming with `requestIdleCallback`, full
  callgraph arcs - these are prompt "nice-to-have" items, deferred.
- Offline vendoring of d3 modules - currently loaded from CDN. Vendoring is a follow-up
  (see [Vendoring](#vendoring)).

## Run

```bash
cd mocks/ui-cells
python3 server.py
# open http://localhost:8081/
```

`server.py` is stdlib-only. It serves static files and streams `/events` as SSE, replaying
[data/discovery-stream.jsonl](data/discovery-stream.jsonl) event-by-event with a small
delay so you can watch the buildings fill.

You can also open `index.html` over `file://` - the client falls back to fetching
`data/discovery-stream.jsonl` and replaying via `setInterval`. This works offline once the
d3 CDN scripts are cached, and lets you demo without the server.

Replay: click **Replay** in the top-right HUD to restart the discovery sequence.

## Interactions

| Input | Effect |
|-------|--------|
| Wheel | zoom around cursor |
| Drag | pan |
| Click a cell | reframe to that cell; drills into pillar/category/rule |
| View toggle | swap grouping (Pillar / Topology / Severity) |
| Palette selector | swap color palette |
| Replay | restart the discovery stream |

## Data

- [data/skeleton.json](data/skeleton.json) - compact spec of pillars, categories, rules,
  and a synthetic topology (subscriptions, resource groups, resources). Expanded to a
  d3.hierarchy at runtime.
- [data/palettes.json](data/palettes.json) - palette definitions.
- [data/discovery-stream.jsonl](data/discovery-stream.jsonl) - synthetic SSE stream.
  One JSON event per line: `{"type": "...", "at": <ms_offset>, "payload": {...}}`.

Event types:

| type | meaning |
|------|---------|
| `phase` | state-machine transition (`auth`, `permission`, `discovery`, `evaluation`, `ready`, `error`) |
| `permit` | permission-check result for a subscription |
| `resource` | a discovered resource attaches to a resource-group cell |
| `finding` | an evaluated rule produces a detected issue of a given severity |
| `progress` | ambient fill-level tick for a group of cells |
| `done` | terminal marker |

All values are synthetic and customer-agnostic - GUIDs are all-zero placeholders and names
use `example-*` prefixes, per
[../../.github/instructions/generic-scope.instructions.md](../../.github/instructions/generic-scope.instructions.md).

## Files

- [index.html](index.html) - shell (canvas + overlay + HUD).
- [app.js](app.js) - state machine, layout, WebGL2 renderer, 2D overlay, interactions.
- [server.py](server.py) - stdlib-only HTTP + SSE simulator.
- [data/](data/) - skeleton, palettes, discovery stream.

## Vendoring

The d3 modules currently load from `cdn.jsdelivr.net`. To make this offline-only, drop the
corresponding UMD builds into `vendor/` and swap the `<script>` src references in
[index.html](index.html). No other change is needed - the app touches only the global
`d3` namespace.
