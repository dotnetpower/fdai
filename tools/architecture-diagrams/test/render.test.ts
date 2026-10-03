import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import type { ElkPoint } from "elkjs/lib/elk-api.js";

import { layoutDiagram } from "../src/layout/elk.js";
import { parseDiagram } from "../src/model/validate.js";
import {
  renderSvg,
  roundedEdgePath,
  smoothCurvePath,
} from "../src/render/svg.js";

function segmentIntersectsBox(
  start: ElkPoint,
  end: ElkPoint,
  box: { x: number; y: number; width: number; height: number },
  padding = 3,
): boolean {
  const left = box.x - padding;
  const right = box.x + box.width + padding;
  const top = box.y - padding;
  const bottom = box.y + box.height + padding;
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  let minimum = 0;
  let maximum = 1;
  for (const [origin, delta, low, high] of [
    [start.x, deltaX, left, right],
    [start.y, deltaY, top, bottom],
  ] as const) {
    if (delta === 0) {
      if (origin < low || origin > high) return false;
      continue;
    }
    const first = (low - origin) / delta;
    const second = (high - origin) / delta;
    minimum = Math.max(minimum, Math.min(first, second));
    maximum = Math.min(maximum, Math.max(first, second));
    if (minimum > maximum) return false;
  }
  return true;
}

function sectionPoints(section: {
  startPoint: ElkPoint;
  bendPoints?: ElkPoint[];
  endPoint: ElkPoint;
}): ElkPoint[] {
  return [
    section.startPoint,
    ...(section.bendPoints ?? []),
    section.endPoint,
  ];
}

function firstSegmentIsPerpendicular(
  points: ElkPoint[],
  side: "NORTH" | "EAST" | "SOUTH" | "WEST",
): boolean {
  const start = points[0]!;
  const end = points[1]!;
  if (side === "EAST") return end.x > start.x && end.y === start.y;
  if (side === "WEST") return end.x < start.x && end.y === start.y;
  if (side === "SOUTH") return end.y > start.y && end.x === start.x;
  return end.y < start.y && end.x === start.x;
}

function lastSegmentIsPerpendicular(
  points: ElkPoint[],
  side: "NORTH" | "EAST" | "SOUTH" | "WEST",
): boolean {
  const start = points[points.length - 2]!;
  const end = points[points.length - 1]!;
  if (side === "EAST") return start.x > end.x && start.y === end.y;
  if (side === "WEST") return start.x < end.x && start.y === end.y;
  if (side === "SOUTH") return start.y > end.y && start.x === end.x;
  return start.y < end.y && start.x === end.x;
}

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
    icon: lucide-inbox
    label: { en: Processor, ko: Processor }
  - id: thor
    parent: core
    kind: agent
    label: { en: Thor agent, ko: Thor agent }
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
  assert.match(svg, /@media \(prefers-color-scheme: dark\)/);
  assert.match(svg, /var\(--fdai-diagram-edge-event, #3f7773\)/);
  assert.match(svg, /\.diagram-node > rect/);
  assert.doesNotMatch(svg, /\.diagram-node rect \{/);
  assert.match(svg, /<title id="diagram-title">Render sample<\/title>/);
  assert.match(svg, /data-node-id="processor"/);
  const nodeMarkup = (id: string): string => {
    const start = svg.indexOf(`data-node-id="${id}"`);
    const next = svg.indexOf('<g class="diagram-node', start + 1);
    assert.ok(start >= 0);
    return svg.slice(start, next >= 0 ? next : undefined);
  };
  assert.match(nodeMarkup("thor"), /<image class="agent-icon"/);
  const thorIcon = nodeMarkup("thor").match(/href="data:image\/svg\+xml;base64,([^"]+)"/);
  assert.ok(thorIcon);
  const thorSvg = Buffer.from(thorIcon[1]!, "base64").toString("utf8");
  assert.match(thorSvg, /aria-label="Thor \(Responder\)"/);
  assert.match(thorSvg, /#f5a623/);
  assert.doesNotMatch(thorSvg, /currentColor/);
  const processorIcon = nodeMarkup("processor").match(
    /href="data:image\/svg\+xml;base64,([^"]+)"/,
  );
  assert.ok(processorIcon);
  const processorSvg = Buffer.from(processorIcon[1]!, "base64").toString("utf8");
  assert.match(processorSvg, /stroke="#315f82"/);
  assert.match(processorSvg, /<path [^>]*\/>/);
  assert.doesNotMatch(processorSvg, /\bkey=/);
  for (const id of ["source", "sink"]) {
    assert.doesNotMatch(nodeMarkup(id), /class="(?:agent|generic)-icon"|<image /);
  }
  assert.match(svg, /marker-end="url\(#arrow-event\)"/);
  assert.match(svg, /<marker id="arrow-event"[^>]*refX="0"/);
  assert.doesNotMatch(svg, /<marker id="arrow-event"[^>]*refX="(?:9|9\.5)"/);
  assert.match(svg, /<path class="edge-hit"/);
  assert.match(svg, /<path class="edge-path"[^>]*stroke-linecap="butt"/);
  assert.match(svg, /\.edge-hit \{[^}]*cursor: pointer/);
  assert.match(svg, /\.diagram-edge:hover > \.edge-path/);
  assert.match(svg, /\.diagram-edge:hover \.edge-label rect/);
  assert.match(svg, /\.diagram-edge:hover \.edge-label-text/);
  const internalStart = svg.match(
    /data-edge-id="internal-flow"[\s\S]*?<path class="edge-path" d="M([\d.]+) ([\d.]+)/,
  );
  const core = layout.groups.get("core");
  assert.ok(internalStart && core);
  assert.ok(Number(internalStart[1]) >= core.x + 48);
});

test("routes flowchart edges that cross group boundaries", async () => {
  const spec = parseDiagram(`
id: cross-group-flow
version: 1
kind: flowchart
locales:
  en: { title: Cross group, description: Cross group, alt: Source sends an event to target. }
  ko: { title: Cross group, description: Cross group, alt: Source가 target으로 event를 보냅니다. }
canvas: { width: 800, height: 480, direction: RIGHT }
groups:
  - id: left
    kind: system
    label: { en: Left, ko: Left }
  - id: right
    kind: system
    label: { en: Right, ko: Right }
nodes:
  - id: source
    parent: left
    kind: process
    label: { en: Source, ko: Source }
  - id: target
    parent: right
    kind: process
    label: { en: Target, ko: Target }
edges:
  - id: cross-boundary
    from: source
    to: target
    kind: event
`);
  const layout = await layoutDiagram(spec);
  const edge = layout.edges.find((candidate) => candidate.id === "cross-boundary");
  assert.ok(edge?.sections?.length);
  const svg = await renderSvg(spec, layout, "en");
  assert.match(svg, /data-edge-id="cross-boundary"/);
});

test("routes fallback cross-group edges around unrelated nodes", async () => {
  const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
  const source = await readFile(
    path.join(
      repositoryRoot,
      "docs/diagrams/fdai-escalation-and-standing-authority-01.diagram.yaml",
    ),
    "utf8",
  );
  const spec = parseDiagram(source);
  const layout = await layoutDiagram(spec);
  const edge = layout.edges.find((candidate) => candidate.id === "flow-03");
  assert.ok(edge?.sections?.length);
  assert.ok(
    edge.sections.some((section) => section.id.endsWith("-missing-edge-route")),
  );
  const obstacle = layout.nodes.get("r1");
  assert.ok(obstacle);
  const crossingSegments = edge.sections.flatMap((section) => {
    const points = [
      section.startPoint,
      ...(section.bendPoints ?? []),
      section.endPoint,
    ];
    return points
      .slice(1)
      .filter((end, index) =>
        segmentIntersectsBox(points[index]!, end, obstacle),
      );
  });
  assert.deepEqual(crossingSegments, []);
});

test("keeps aligned fallback endpoints straight and perpendicular", async () => {
  const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
  const source = await readFile(
    path.join(
      repositoryRoot,
      "docs/diagrams/fdai-conceptual-control-loop.diagram.yaml",
    ),
    "utf8",
  );
  const spec = parseDiagram(source);
  const layout = await layoutDiagram(spec);
  const edge = layout.edges.find(
    (candidate) => candidate.id === "context-to-ontology",
  );
  assert.ok(edge?.sections?.length);
  assert.ok(
    edge.sections.some((section) => section.id.endsWith("-missing-edge-route")),
  );
  const points = sectionPoints(edge.sections[0]!);
  assert.deepEqual(points, [
    { x: 336, y: 562 },
    { x: 416, y: 562 },
  ]);
});

test("fallback endpoint stubs leave and enter perpendicular to the node side", async () => {
  const repositoryRoot = path.resolve(import.meta.dirname, "../../..");
  const source = await readFile(
    path.join(
      repositoryRoot,
      "docs/diagrams/fdai-escalation-and-standing-authority-01.diagram.yaml",
    ),
    "utf8",
  );
  const spec = parseDiagram(source);
  const layout = await layoutDiagram(spec);
  const edge = layout.edges.find((candidate) => candidate.id === "flow-03");
  assert.ok(edge?.sections?.length);
  assert.ok(
    edge.sections.some((section) => section.id.endsWith("-missing-edge-route")),
  );
  const points = sectionPoints(edge.sections[0]!);
  assert.ok(firstSegmentIsPerpendicular(points, "WEST"));
  assert.ok(lastSegmentIsPerpendicular(points, "EAST"));
});

test("rejects an agent node outside the fixed pantheon", async () => {
  const spec = parseDiagram(source.replaceAll("id: thor", "id: worker"));
  const layout = await layoutDiagram(spec);
  await assert.rejects(
    renderSvg(spec, layout, "en"),
    /Unknown pantheon agent icon 'worker'/,
  );
});

test("rejects a generic icon outside the static Lucide allowlist", async () => {
  const spec = parseDiagram(source.replace("icon: lucide-inbox", "icon: lucide-not-allowed"));
  const layout = await layoutDiagram(spec);
  await assert.rejects(renderSvg(spec, layout, "en"), /Unknown diagram icon 'lucide-not-allowed'/);
});

test("renders the collective pantheon mark without creating a sixteenth agent", async () => {
  const spec = parseDiagram(source.replace(
    "    icon: lucide-inbox",
    "    icon: agent-pantheon",
  ));
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");
  const start = svg.indexOf('data-node-id="processor"');
  const next = svg.indexOf('<g class="diagram-node', start + 1);
  const processorMarkup = svg.slice(start, next >= 0 ? next : undefined);
  const icon = processorMarkup.match(/href="data:image\/svg\+xml;base64,([^"]+)"/);

  assert.ok(icon);
  const iconSvg = Buffer.from(icon[1]!, "base64").toString("utf8");
  assert.match(iconSvg, /FDAI Agent Pantheon \(15-agent collective\)/);
  assert.match(iconSvg, /#44688e/);
  assert.doesNotMatch(iconSvg, /currentColor/);
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

test("renders the Azure reference profile with semantic presentations and a step badge", async () => {
  const spec = parseDiagram(source);
  spec.canvas.profile = "azure-reference";
  spec.groups[0]!.presentation = "band";
  spec.nodes[2]!.presentation = "icon";
  spec.edges[1]!.step = 1;
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");

  assert.match(svg, /data-profile="azure-reference"/);
  assert.match(svg, /data-presentation="band"/);
  assert.match(svg, /data-node-id="thor" data-presentation="icon"/);
  assert.match(svg, /<g class="edge-step"[^>]*><circle r="13"\/><text y="4">1<\/text><\/g>/);
  assert.match(svg, /<title>Step 1\. Write<\/title>/);
});
