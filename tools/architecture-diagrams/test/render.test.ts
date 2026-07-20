import assert from "node:assert/strict";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { parseDiagram } from "../src/model/validate.js";
import {
  renderSvg,
  roundedEdgePath,
  smoothCurvePath,
} from "../src/render/svg.js";

const source = `
id: render-sample
version: 1
kind: container
locales:
  en: { title: Render sample, description: Layout check, alt: A source sends an event to a processor. }
  ko: { title: Render sample, description: Layout check, alt: Source가 processor로 event를 보냅니다. }
canvas: { width: 800, height: 480, direction: RIGHT }
groups:
  - id: core
    kind: system
    label: { en: Core, ko: Core }
nodes:
  - id: source
    kind: external
    label: { en: Source, ko: Source }
  - id: processor
    parent: core
    kind: process
    label: { en: Processor, ko: Processor }
  - id: sink
    parent: core
    kind: store
    label: { en: Sink, ko: Sink }
edges:
  - id: event-flow
    from: source
    to: processor
    kind: event
    label: { en: normalized event, ko: normalized event }
  - id: internal-flow
    from: processor
    to: sink
    kind: write
legend:
  - kind: event
    label: { en: Asynchronous event, ko: Asynchronous event }
`;

test("lays out nested groups and renders accessible SVG", async () => {
  const spec = parseDiagram(source);
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");

  assert.ok(layout.groups.get("core")?.width);
  assert.ok(layout.nodes.get("processor")?.x);
  assert.equal(
    layout.edges.find((edge) => edge.id === "internal-flow")?.container,
    "core",
  );
  assert.match(svg, /<svg[^>]+role="img"/);
  assert.match(svg, /svg\[data-diagram-id\]\s*\{/);
  assert.doesNotMatch(svg, /<style>\s*svg\s*\{/);
  assert.match(svg, /var\(--fdai-diagram-canvas, #faf9f8\)/);
  assert.match(svg, /var\(--fdai-diagram-azure, #0078d4\)/);
  assert.match(svg, /var\(--fdai-diagram-text, #323130\)/);
  assert.match(svg, /<title id="diagram-title">Render sample<\/title>/);
  assert.match(svg, /data-node-id="processor"/);
  assert.match(svg, /marker-end="url\(#arrow-event\)"/);
  const internalStart = svg.match(
    /data-edge-id="internal-flow"[\s\S]*?<path d="M([\d.]+) ([\d.]+)/,
  );
  const core = layout.groups.get("core");
  assert.ok(internalStart && core);
  assert.ok(Number(internalStart[1]) >= core.x + 48);
});

test("rounds orthogonal corners without changing endpoints", () => {
  const path = roundedEdgePath(
    [
      { x: 0, y: 0 },
      { x: 40, y: 0 },
      { x: 40, y: 60 },
    ],
    10,
    20,
    12,
  );
  assert.equal(path, "M10 20 L38 20 Q50 20 50 32 L50 80");
});

test("renders long cross-band connections as a bounded cubic curve", () => {
  assert.equal(
    smoothCurvePath({ x: 0, y: 0 }, { x: 100, y: 200 }, 10, 20),
    "M10 20 C10 104 110 136 110 220",
  );
});
