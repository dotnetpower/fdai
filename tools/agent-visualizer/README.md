# FDAI Neural View

Use Neural View to explore FDAI's 15 agents, real Python function definitions, and declared
event-bus relationships in 3D. This standalone tool lives outside the operating Console and
control loop. Activity view uses source-derived call topology with simulated activity and Azure
traffic. Ontology view uses the complete stored FDAI ontology map and actual instances collected
in the local PostgreSQL database.
It does not call models, approve actions, or change resources.

## Running locally

Use Node.js 22 or later and the repository's Python environment. From the repository root:

```bash
npm --prefix tools/agent-visualizer ci
npm --prefix tools/agent-visualizer run dev
```

Open `http://127.0.0.1:5573`. The server binds to loopback and fails if that port is occupied.
It doesn't start or replace the Console or any backend. `dev` and `build` first regenerate the
source call graph without executing application modules. The build does not read a database.
For a production bundle:

```bash
npm --prefix tools/agent-visualizer run build
npm --prefix tools/agent-visualizer run preview
```

The production output has relative asset URLs and bundles its dependencies and FDAI brand
assets locally. It doesn't load fonts, scripts, analytics, or scenario data from a CDN.

## Publishing as a static experience

Build the public GitHub Pages variant from the repository root:

```bash
npm --prefix tools/agent-visualizer run build:public
```

The public build keeps the source-derived Activity view and removes the local Ontology entry
point. The Ontology view depends on the loopback-only PostgreSQL snapshot middleware and isn't a
public evidence source. The Pages workflow publishes the resulting static files under
`/neural-view/`; add `?lang=ko` to start the experience in Korean.

## Controls

| Control | Result |
|---------|--------|
| Scenario selector | Switch among safe change, recovery, and knowledge stories |
| Activity / Ontology | Switch between simulated Python activity and the full ontology map |
| Refresh from local DB | Read a new private, read-only local database snapshot |
| All objects / Catalog / Instances | Show all map nodes, only catalog nodes, or DB instances with their type anchors |
| ObjectType / relationship filters | Narrow presentation without omitting source data from the export |
| Play, pause, timeline, speed, loop | Reproduce the same scene or inspect an exact point |
| Independent activity lanes | Inspect each agent's own repeating task and open its source function |
| Agent button or node label | Select an agent and inspect its role and reachable Python functions |
| Small node or function search result | Highlight a real function and its static callers/callees |
| Python function details | Inspect source file/line and unresolved or external call receivers |
| Event bus or broadcast disclosure | Inspect overlapping topics and each declared subscriber fan-out |
| Pub/sub declarations | Browse every relevant canonical topic and available Python handlers |
| Azure Resource Graph node | Focus the source-backed query entry point |
| Orbit | Slowly move around the full neural field |
| Follow | Default Activity camera; follow the latest story activity, or pin a selected agent |
| Tour | Automatically frame the overview, event bus, a Python function, and Azure |
| Manual, drag, scroll, zoom buttons | Take over the camera without changing scenario state |
| Reset view | Clear selection and restore the overview camera |
| Glow, node labels | Adjust presentation density |
| Stars | Show or hide the decorative, slowly twinkling background |
| Reduce motion | Pause playback and suppress automatic moving signals; play remains opt-in |
| Cinema | Hide side panels while retaining the view-specific source watermark |
| Fullscreen | Request browser fullscreen; failure leaves Cinema available |
| EN / KO | Switch between English and Korean |

Space toggles playback when focus is outside a control. Native button and range keyboard
behavior is preserved. C toggles Cinema outside controls, and Escape exits Cinema.
The bottom dock keeps camera controls close to the lower edge. Hovering the dock or entering it
with keyboard-visible focus reveals playback above that fixed camera row; leaving collapses the
unused space. Camera buttons do not move under the pointer, and opening playback overlays the
graph rather than resizing its canvas. The graph uses the space reclaimed from hidden playback.
Touch/narrow layouts keep both rows open. Cinema retains its hover/focus playback and a visible
exit button without obscuring the source watermark.
Use your screen recorder to capture the view; this tool does not record video or audio.
Activity starts with **Follow** and **1x**, with the camera controls and speed selector matching
the runtime state. Returning from Ontology restores Follow; an explicit Reset view still opens
the Orbit overview. User-selected playback speeds remain available.

The Cinema button has a slow border-only glow. Reduce motion removes that animation, and forced
colors retains the standard button boundary. Mouse-wheel zoom works over node/function/edge labels
as well as the canvas, without disabling label selection or intercepting sidebar scrolling.

### Automatic filming tour

Select **Tour**, then **Cinema** for automatic camera choreography. Each scenario contains two
complete tours: overview, event-bus fan-out, a source-backed Python function, and Azure.
The function shot uses the selected function when available, otherwise Huginn's source-backed
ingestion entry point (or the Azure Resource Graph query entry if that definition is absent). The same scenario
time reproduces the same pose after the brief mode-entry transition.
The tour returns continuously to the overview at the scenario loop boundary.

Pause freezes the tour; seeking chooses the corresponding shot. Dragging takes manual control,
and selecting an agent or function switches to focused viewing. Reduce motion disables Tour
and stops an active tour without starting playback.

Node names use deterministic screen-space placement to avoid overlaps. Neutral dotted leader
lines connect displaced labels to their nodes; they are not Python call edges. Focused labels
take priority, and all agent/function details remain reachable through the text controls.
Every subordinate node has its real Python function name, rendered as a lightweight code annotation
rather than a boxed badge. The overview hides these annotations. As the camera approaches,
names gradually fade in; moving away fades them out. Nearby labels that cannot fit without overlap
remain suppressed. Faint or hidden labels don't intercept pointer input or enter the tab order.
Focused labels stay readable, and the selected function's explicit annotation remains available.
Reduce motion removes the temporal fade but preserves distance-based visibility.

Function search always includes every indexed definition. Hover shows the qualified symbol
and source file/line; click or keyboard activation opens the caller/callee view.

## Reading the visualization

- **Agent hubs:** The 15 named nodes correspond to the fixed FDAI pantheon.
- **Small nodes:** Every subordinate point is a Python function definition with a source
  file and line. There are no decorative function nodes. Agent-to-definition lines represent
  file membership; definition-to-definition lines represent static call references.
- **Background stars:** Small, unconnected, unlabelled decorative specks. They are not graph
  nodes and cannot be selected. A seeded 360-star field uses one GPU draw call, with slow
  individual brightness changes and a quieter center so it doesn't compete with the graph.
  Stars pause with playback and remain static under Reduce motion. A depth-only node silhouette
  keeps the screen-space backdrop behind graph nodes while the camera moves.
- **Shared functions:** A shared function appears once, placed near one reachable agent.
  Reachability and visual grouping don't transfer ownership or execution authority.
- **Capability labels:** The side panel retains readable role descriptions; these aren't
  extra graph nodes or measured functions.
- **Moving light:** The publisher sends to the event bus, which fans out to declared subscribers.
  Publishers have separate periods and offsets, so several topics can be in flight at once.
  They do not take turns through a global topic queue.
- **Independent activity:** All 15 agents have separate synthetic task periods, durations,
  and offsets. A lane shows its purpose, working/waiting state, and local progress. Each activity
  lights its specific source function and local path, rather than lighting all functions equally.
  These activities are read/observation illustrations, not automatic approval or execution.
  The ordered narrative remains a separate explanation, not the scheduler for those lanes.
- **Source selection:** Selecting a function highlights its actual source references. A
  `declared-receiver` edge uses an explicit receiver type annotation, not observed dynamic dispatch.
- **Activity and afterglow:** Derived from the scenario clock. No random background firing
  represents work, and seeking backward removes future activity.
- **Approval and outcome:** Scripted examples grant no authority. Dispatch is distinct
  from independent effect verification, including in the safe-change story.
- **Colors:** Identify presentation families, not health or success. Text identifies the
  activity and selected agent independently of color. Loki has a red identity override across
  its graph, detail and activity surfaces; red does not change its role or imply failure.

The `SYNTHETIC DEMO` watermark remains visible in Cinema and fullscreen. Playback time is
scenario-relative, not an operational timestamp. Source topology and simulated timing never merge
into a claim of observed execution. Frame rate is a local rendering sample.

## Full ontology map and actual instances

Select **Ontology** to read the complete map directly. This is not the small resource specimen
and is not restricted to Resource objects. It uses:

- `state_kv["operator-projection:operations:ontology.graph"].catalog_topology`, the same stored
  catalog map consumed by FDAI Console;
- every current `ontology_resource` row, across all populated ObjectTypes;
- every `ontology_link` row whose endpoints are present;
- retained `operational_state_transition` records and coverage summaries.

All ObjectTypes remain in the map, including types with zero collected instances. Catalog nodes
include object, interface, function, action, resource and signal types, rules, properties, workflows
and agent references as supplied by the source map. Catalog references and database instances
remain distinct nodes, not records merged by similar names.

The initial validated local capture contained 89 ObjectTypes, 383 catalog nodes, 6,371 database
instances and 8,326 stored instance relationships. The full view therefore contained 6,754 nodes
and 15,461 edges: catalog edges, stored instance edges, and explicit type-classification edges.
These counts are not constants or fixtures; the header reports each new database capture.

**All objects** renders the full selected data on the GPU. **Catalog** and **Instances** are
presentation layers. Type and relationship filters preserve visible/total accounting. Only
labels and detail lists have display limits: search is paged in batches of 100, the inspector
shows up to 80 relationships and 40 history rows, and nearby instance labels are bounded to keep
the graph legible. The underlying export and default graph do not silently sample data.
Self-typed links render as loops, and selected relations show direction arrows and predicates.

### Local read and privacy boundary

The local PostgreSQL database and `.fdai/local-runtime.env` must already exist. The reader uses
the service-owned `FDAI_STATE_STORE_DSN` internally, admits only loopback port 5432, rejects
ambient routing overrides, and starts a repeatable-read, read-only transaction before reading
application tables. It doesn't start services, alter roles, query Azure, or import the Core runtime.

The viewer's fixed `GET /__neural/ontology` route runs only this reader with a 45-second process
deadline; SQL statements have a 15-second deadline. Concurrent refreshes share one export.
The optional explicit command is:

```bash
npm --prefix tools/agent-visualizer run snapshot:db
```

The export is stored at ignored `.fdai/neural-view/ontology.json` with mode `0600`, inside a
`0700` directory. It is never bundled into the static build or committed. Source identifiers are
pseudonymized consistently within the local service credential context. Original instance names,
conversation bodies, arbitrary properties and credentials are not exported. Only public catalog
metadata, type memberships, source counts, safe stored-state values and bounded transition
metadata enter the viewer. All relationships preserve the same pseudonymous endpoint mapping.

The reader refuses exports beyond 25,000 instances, 100,000 stored links or 50,000 history rows
instead of silently returning a subset. Missing source tables, missing ObjectTypes, invalid
endpoints, count mismatches or an unavailable DB produce an explicit error. No mock fallback or
Console popup is used. A complete database read does not imply complete provider observation.

### Stored state and history

Selecting an ObjectType shows its exact collected instance count, its declarations and the
matching stored history. **Explore this type's instances** opens its actual rows. Instances
show their pseudonymous identity, revision, exported state lane and available timestamps.
Missing or unexportable values remain unknown, not healthy.

**Replay stored transitions** uses the real retained time window, compressed into the display
timeline. Operational and availability transitions have separate selectors. Only non-synthetic,
conflict-free `observed` transitions with a retained target value recolor the replay; the stored
current value remains separately visible. The current topology stays fixed, so replay doesn't
claim a reconstructed historical graph or complete intermediate-state coverage. Before a
retained state is available for a node, its replay state remains unknown.

Names and contents of sensitive instance types such as Conversation, Turn and Principal stay
pseudonymized or omitted, while their actual counts and recorded relationships are included.

## Azure Resource Graph rate

The Azure Resource Graph transport declares a default sustained shared budget of **3 requests per second**
and a burst allowance of **15** in
[`arg_transport.py`](../../services/core-control-plane/src/fdai/delivery/azure/arg_transport.py).
This is a rate limiter shared by concurrent queries, not a scheduler that detects changes
three times per second.

The visualizer reads that default from source and animates three synthetic request starts per
**active display second**, independent of the scenario's playback speed. At the default 1x,
story and transport clocks advance together. Selecting 2x accelerates the story and agent tasks
while the combined Azure Resource Graph lane still starts three requests per real second, not six.

The requests alternate between two source-backed workflows sharing that visual budget:

- **Resource scan:** `AzureResourceGraphInventory.full_snapshot()` and
  `AzureArgQueryFactory._fetch_all_pages()`.
- **Change detection:** `run_resource_change_feed()` and `AzureResourceChangeFeed.poll()`.

Huginn is the accountable collection agent; the actual reads belong to the independent inventory
worker and provider adapters. Returned changes enter the event ingress for Huginn normalization
and Heimdall observation. The dotted agent/worker line shows that responsibility and data flow,
not a direct Python call from Huginn or a claim that an Azure Resource Graph query is executing.

The Azure marker stays static, without rotation or flashing request-slot indicators. Small,
subdued request and response trails follow the worker/query path. Response travel time is
illustrative, not measured latency. No response is claimed to prove an actual resource change.

Pausing freezes both clocks. Restart and scenario selection reset both; seeking places the
transport clock at the chosen scenario time for reproducible 1x-default shots. Changing
playback speed does not accelerate or reset Azure Resource Graph traffic; story loops do not reset its ongoing
transport clock. Hidden tabs do not accumulate missed traffic.

The tool does not call Azure, change the limiter, consume quota, or assert a live polling interval.
The pane keeps the synthetic source and rate distinction visible, including in Cinema mode.

## Source coverage and limitations

The AST generator indexes Python under `services/*/src/` and `packages/*/src/`. It includes
all definitions in canonical agent-owned files, conservatively resolved transitive callees,
declared subscriber handlers, and inventory, Azure Resource Graph query/transport, resource-change feed, and
change-acceleration definitions with their reachable callees.
The displayed function and edge counts describe this scope, not the whole repository.

It resolves lexical calls, imports/re-exports, unambiguous inherited methods, captured `self`
in nested query closures, and explicitly declared receiver types. It doesn't guess unknown
receivers, multiple possible inherited implementations, external SDK implementations, or
runtime-injected bindings. Unresolved calls remain inspectable rather than acquiring invented
edges. A static graph cannot prove the complete runtime call graph.

Canonical topic ownership comes from `AgentSpec.owns` and `OWNED_OBJECT_TOPICS`; subscribers
come from `AgentSpec.subscribes`. Optional worker command subscriptions and non-agent consumer
groups remain explicitly outside this view. No application module is imported or executed.

Regenerate the snapshot after changing Python sources:

```bash
npm --prefix tools/agent-visualizer run graph
```

Do not hand-edit `src/generated/code-graph.json`. It contains relative source locations, call
symbols, declarations, and an input digest, not code bodies, query payloads, tenant values,
credentials, or endpoints.

## Design boundaries

The source extractor, scene, camera, timeline, and synthetic activity adapter are separate
modules. Three.js uses GPU geometry, additive light, and bloom, with a seeded layout and
bounded signal buffers. Dim static edges preserve context; selected call paths and active
broadcasts receive emphasis. The user-requested cinematic surface intentionally differs
from the calm Console palette without changing Console tokens.

The design deliberately avoids global Python function tracing, unbounded physics simulation,
backend changes, and direct provider connectors. No approval or execution controls are present.
The scenario types are private presentation types, not public runtime contracts.

Ontology uses the explicitly authorized local database reader described above. Activity scenarios
remain synthetic and separate from database records. The ontology surface remains read-only and
cannot authorize or execute managed-resource changes.

## Layout

| Path | Responsibility |
|------|----------------|
| `scenarios/` | Explicitly synthetic, bilingual narrative events |
| `scripts/` | No-import AST indexing, topic/rate extraction, and source snapshot generation |
| `src/generated/` | Generated Python call topology; private DB data is never placed here |
| `src/agents.ts` | Curated agent positions and semantic role labels |
| `src/playback/` | Pure time projection, concurrent fan-out, and synthetic Azure Resource Graph slots |
| `src/scene/` | Real function nodes, event bus, Azure trails, selection, and GPU cleanup |
| `src/camera/` | Overview, follow, focus, and manual camera control |
| `src/recorded/` | Full-map accounting, catalog/instance layers, private snapshot decoder and history inspector |
| `private-snapshot-plugin.ts` | Fixed local read-only snapshot route for Vite dev and preview |
| `src/ui/` | Accessible controls, text alternatives, and EN/KO catalogs |
| `tests/` | Model and browser regression tests |

## Testing

```bash
npm --prefix tools/agent-visualizer test
uv run pytest -q --no-cov tools/agent-visualizer/tests/test_source_graph.py
uv run pytest -q --no-cov tools/agent-visualizer/tests/test_local_ontology_db.py
npm --prefix tools/agent-visualizer run build
npm --prefix tools/agent-visualizer run test:e2e
```

The browser tests use the repository's Playwright tooling and loopback port 5573.
Ontology browser tests use an explicit structural fixture at the private route and prove full
accounting, zero-instance types, layers, drilldowns and retained-history semantics. Actual local
database verification is recorded separately using the real read-only export and its counts;
neither check is a claim of live provider or authenticated Console parity.
An existing server should be this tool from the current checkout, not an unrelated listener.
If Chromium isn't installed, use the normal Playwright browser setup before running E2E.
Software WebGL support in the test browser validates mechanics, not native-GPU performance.
The wheel/hover interaction regression file uses DOM measurements and screenshots without trace
screencasting: a controlled local Chromium comparison lost the WebGL context with trace capture,
while the identical interaction passed without it. Other browser tests retain their existing
trace settings.

The WebGL-unavailable state keeps the scenario and text inspector accessible. A graphics-context
loss pauses playback and presents an explicit reload action. Reduced-motion preference starts
paused. Background tabs suspend rendering and do not accumulate missed playback time.

## Related docs

| To learn about | Read |
|----------------|------|
| Agent identities and authority | [Agent pantheon](../../docs/roadmap/agents/agent-pantheon.md) |
| Evidence and execution boundaries | [FDAI Constitution](../../docs/roadmap/architecture/fdai-constitution.md) |
| Existing operational UI | [Console](../../console/README.md) |
