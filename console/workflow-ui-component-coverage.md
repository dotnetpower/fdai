# Workflow UI Component Coverage

이 문서는 생성된 WorkflowApp이 사용할 수 있는 generic report widget과 HTML
component coverage를 기록합니다. 2026-07-18 기준 backend registry, report schema,
console renderer 및 `mocks/ui/*.html` 시안을 교차 검토했습니다.

## Design at a glance

Upstream은 36개 `WidgetBuilder`와 engine-special container인 `group`, `tabs`를 합쳐
38개 widget type을 제공합니다. Console은 37개 type을 semantic HTML, bounded SVG
또는 CSS primitive로 렌더링합니다. `iframe`은 remote executable 또는 independently
navigable content를 가져올 수 있으므로 generated workflow surface에서 의도적으로
차단합니다.

단일 machine-readable source는
[`widget-capabilities.json`](../rule-catalog/reports/widget-capabilities.json)입니다.
Frontend coverage test와 backend registry parity test가 이 catalog를 검증합니다.

## Coverage matrix

| Pattern | Widget types | HTML or visual primitive | Status |
|---------|--------------|--------------------------|--------|
| KPI and scalar | `query_value`, `change` | KPI card, definition list | Covered |
| Progress and target | `gauge`, `progress_bar` | `role=meter`, native `progress` | Covered |
| Workflow sequence | `process_steps` | Ordered stepper, status pill, native `progress` | Covered |
| Before and after | `comparison` | Responsive comparison table | Covered |
| Category and distribution | `bar_chart`, `pie_chart`, `distribution` | Bars, segmented distribution, legend | Covered |
| Time and XY data | `timeseries`, `sparkline`, `scatter_plot`, `heatmap` | SVG plus accessible data table or matrix | Covered |
| Ranked and tabular data | `top_list`, `table` | Captioned table with scoped headers | Covered |
| Events and evidence | `list_stream`, `event_stream` | Ordered timeline and bounded details | Covered |
| Health and reliability | `check_status`, `alert_status`, `slo_summary`, `service_summary` | KPI grid, status pills, lists | Covered |
| Cost | `cost_summary`, `budget_summary` | Currency summary, bars, progress | Covered |
| Flow and hierarchy | `funnel`, `sankey`, `treemap`, `retention`, `flame_graph`, `split_graph` | Funnel, edge list, tiles, matrix, bounded frames, small multiples | Covered |
| Architecture and geography | `hostmap`, `topology_map`, `geomap` | Tiles, nodes and semantic edges, coordinate/region tables | Covered |
| Narrative and callout | `free_text`, `note` | Plain rich-text surface and tinted callout | Covered |
| Governed media | `image` | Lazy raster image with URL revalidation | Covered |
| Layout | `group`, `tabs` | 12-column grid and keyboard tabs | Covered |
| Remote embedded page | `iframe` | Explicit blocked state | Blocked |

## Prototype gaps resolved

The mock review identified two patterns that had no backend contract:

- `mocks/ui/workflow-builder.html` uses an ordered node chain. The new
  `process_steps` builder normalizes status, progress, duration, message and truncation
  evidence for the generic stepper.
- `mocks/ui/report.html` uses an AS-IS / TO-BE comparison. The new `comparison`
  builder emits field-level before/after values and a factual `changed` flag. It does
  not infer whether the change is beneficial.

Existing components were also hardened:

- Timeseries includes a point table for non-visual inspection.
- Tables use captions and scoped headers; top lists expose rank.
- Stream rows retain additional fields in bounded `details` blocks.
- Topology edges use a semantic list.
- Composite rendering stops after depth 8.
- Flame graphs stop after depth 8 or 200 frames.
- Images reject SVG, credentials and unsafe schemes in both backend and frontend.

## Deliberate fallbacks

Some data shapes do not justify a large browser SDK in the generic surface:

- `geomap` displays coordinates and region codes in tables. A product-specific map can
  use a reviewed build-time panel when geographic interaction is a measured need.
- `sankey` displays weighted directed edges. This preserves exact evidence without a
  force-layout dependency.
- `free_text` displays content as text with preserved line breaks. It never injects
  report-authored HTML.

These fallbacks preserve information and accessibility while keeping the WorkflowApp
surface read-only and CSP-neutral.

## Not prebuilt in the generic surface

The following components are deliberately outside the generated WorkflowApp renderer:

- Mutation forms, approval buttons, retry controls and execution commands. These must
  re-enter the typed control pipeline through the governed command surfaces.
- Arbitrary JavaScript, remote components and iframes.
- Code editors, terminals and file-upload controls.
- Interactive geographic SDKs, force-directed graph canvases and 3D scenes.
- Domain-specific planners such as Gantt editors or Kanban mutation boards.

When one of these interactions is required, use a reviewed build-time `EXTRA_PANELS`
component with an injected read-only `ReadPanel`, or a separately governed command
surface. Do not expand the manifest into an executable UI language.

## Adding a widget type

A new upstream widget type should land with all of the following in one change:

1. A pure `WidgetBuilder` and data-shape tests.
2. Registration in `default_widget_builders()`.
3. An entry in `widget-capabilities.json` with `render` or a justified `blocked` status.
4. A semantic frontend renderer or explicit blocked component.
5. Responsive and accessibility checks.
6. English and Korean reporting-subsystem documentation updates.

The exact registry parity test fails when steps 2 and 3 diverge. The frontend coverage
test fails when a `render` entry has no supported renderer.
