import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import type {
  ElkEdgeSection,
  ElkLabel,
  ElkPoint,
} from "elkjs/lib/elk-api.js";

import type { DiagramLayout, PositionedShape } from "../layout/elk.js";
import { cubicCurve } from "../layout/curve.js";
import type {
  DiagramEdge,
  DiagramNode,
  DiagramSpec,
  EdgeKind,
  Locale,
} from "../model/types.js";
import {
  EDGE_FONT_SIZE,
  EDGE_LINE_HEIGHT,
  NODE_FONT_SIZE,
  NODE_LINE_HEIGHT,
  edgeLabelGeometry,
  estimatedTextWidth,
  nodeGeometry,
  wrapText,
} from "../model/text.js";

const edgeStyles: Record<EdgeKind, { color: string; dash: string; width: number }> = {
  request: { color: "#0078d4", dash: "none", width: 2.4 },
  event: { color: "#35b4e3", dash: "7 4", width: 2.4 },
  approval: { color: "#8764b8", dash: "3 4", width: 2.6 },
  mutation: { color: "#d83b01", dash: "none", width: 3 },
  audit: { color: "#107c10", dash: "2 4", width: 2.4 },
  rollback: { color: "#a4262c", dash: "9 4 2 4", width: 2.6 },
  read: { color: "#008272", dash: "5 4", width: 2.2 },
  write: { color: "#5c2d91", dash: "none", width: 2.6 },
};

const edgeKindLabels: Record<EdgeKind, Record<Locale, string>> = {
  request: { en: "Decision request", ko: "결정 요청" },
  event: { en: "Asynchronous event", ko: "비동기 이벤트" },
  approval: { en: "Human approval", ko: "사람 승인" },
  mutation: { en: "Governed change", ko: "통제된 변경" },
  audit: { en: "Audit record", ko: "감사 기록" },
  rollback: { en: "Rollback path", ko: "롤백 경로" },
  read: { en: "Read projection", ko: "읽기 projection" },
  write: { en: "Write", ko: "쓰기" },
};

interface IconLock {
  icons: Record<string, { file: string; productName: string; sha256: string }>;
}

const iconDirectory = fileURLToPath(
  new URL("../../assets/azure/", import.meta.url),
);
const iconLock = JSON.parse(
  await readFile(new URL("../../assets/azure/icons.lock.json", import.meta.url), "utf8"),
) as IconLock;

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function textLines(
  lines: string[],
  x: number,
  startY: number,
  className: string,
  lineHeight = NODE_LINE_HEIGHT,
  anchor: "start" | "middle" = "middle",
): string {
  return `<text class="${className}" x="${x}" y="${startY}" text-anchor="${anchor}">${lines
    .map(
      (line, index) =>
        `<tspan x="${x}" dy="${index === 0 ? 0 : lineHeight}">${escapeXml(line)}</tspan>`,
    )
    .join("")}</text>`;
}

async function iconDataUri(icon: string | undefined): Promise<string | undefined> {
  if (!icon) return undefined;
  const entry = iconLock.icons[icon];
  if (!entry) throw new Error(`Unknown diagram icon '${icon}'`);
  const source = await readFile(`${iconDirectory}/${entry.file}`);
  const payload = source.at(-1) === 0x0a ? source.subarray(0, -1) : source;
  const digest = createHash("sha256").update(payload).digest("hex");
  if (digest !== entry.sha256) {
    throw new Error(`Diagram icon '${icon}' does not match icons.lock.json`);
  }
  return `data:image/svg+xml;base64,${source.toString("base64")}`;
}

function genericIcon(
  node: DiagramNode,
  shape: PositionedShape,
  size: number,
  top: number,
): string {
  const x = shape.x + shape.width / 2;
  const y = shape.y + top + size / 2;
  const radius = size / 2;
  const abbreviation = node.label.en
    .split(/\s+/u)
    .map((word) => word[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  if (node.kind === "store") {
    const rx = radius * 0.82;
    return `<g class="generic-icon" aria-hidden="true"><ellipse cx="${x}" cy="${y - radius * 0.35}" rx="${rx}" ry="${radius * 0.3}"/><path d="M${x - rx} ${y - radius * 0.35}v${radius * 0.95}c0 ${radius * 0.2} ${radius * 0.4} ${radius * 0.34} ${rx} ${radius * 0.34}s${rx} ${-radius * 0.14} ${rx} ${-radius * 0.34}v${-radius * 0.95}"/><path d="M${x - rx} ${y + radius * 0.05}c0 ${radius * 0.2} ${radius * 0.4} ${radius * 0.34} ${rx} ${radius * 0.34}s${rx} ${-radius * 0.14} ${rx} ${-radius * 0.34}"/></g>`;
  }
  if (node.kind === "decision") {
    return `<g class="generic-icon" aria-hidden="true"><path d="M${x} ${y - radius}l${radius} ${radius}-${radius} ${radius}-${radius}-${radius}z"/><text x="${x}" y="${y + 4}" text-anchor="middle">${escapeXml(abbreviation)}</text></g>`;
  }
  return `<g class="generic-icon" aria-hidden="true"><circle cx="${x}" cy="${y}" r="${radius}"/><text x="${x}" y="${y + 4}" text-anchor="middle">${escapeXml(abbreviation)}</text></g>`;
}

async function renderNode(
  node: DiagramNode,
  shape: PositionedShape,
  locale: Locale,
): Promise<string> {
  const geometry = nodeGeometry(node);
  const icon = await iconDataUri(node.icon);
  const x = shape.x + shape.width / 2;
  const labelLines = wrapText(node.label[locale], geometry.maxLabelUnits);
  const labelStart = shape.y + geometry.labelTop + NODE_FONT_SIZE;
  const iconMarkup = icon
    ? `<image href="${icon}" x="${x - geometry.iconSize / 2}" y="${shape.y + geometry.iconTop}" width="${geometry.iconSize}" height="${geometry.iconSize}" preserveAspectRatio="xMidYMid meet" aria-hidden="true"/>`
    : genericIcon(node, shape, geometry.iconSize, geometry.iconTop);
  const description = node.description?.[locale] ?? node.label[locale];
  return `<g class="diagram-node node-${node.kind}" data-node-id="${node.id}" role="button" tabindex="0" aria-label="${escapeXml(`${node.label[locale]}. ${description}`)}"><rect x="${shape.x}" y="${shape.y}" width="${shape.width}" height="${shape.height}" rx="8"/>${iconMarkup}${textLines(labelLines, x, labelStart, "node-label")}</g>`;
}

function distance(left: ElkPoint, right: ElkPoint): number {
  return Math.hypot(right.x - left.x, right.y - left.y);
}

function pointToward(
  from: ElkPoint,
  to: ElkPoint,
  amount: number,
): ElkPoint {
  const length = distance(from, to);
  if (!length) return from;
  const ratio = amount / length;
  return {
    x: from.x + (to.x - from.x) * ratio,
    y: from.y + (to.y - from.y) * ratio,
  };
}

export function roundedEdgePath(
  points: ElkPoint[],
  offsetX: number,
  offsetY: number,
  cornerRadius = 14,
): string {
  const translated = points.map((point) => ({
    x: point.x + offsetX,
    y: point.y + offsetY,
  }));
  const first = translated[0];
  if (!first) return "";
  if (translated.length === 1) return `M${first.x} ${first.y}`;

  const commands = [`M${first.x} ${first.y}`];
  for (let index = 1; index < translated.length - 1; index += 1) {
    const previous = translated[index - 1]!;
    const corner = translated[index]!;
    const next = translated[index + 1]!;
    const radius = Math.min(
      cornerRadius,
      distance(previous, corner) / 2,
      distance(corner, next) / 2,
    );
    const before = pointToward(corner, previous, radius);
    const after = pointToward(corner, next, radius);
    commands.push(
      `L${before.x} ${before.y}`,
      `Q${corner.x} ${corner.y} ${after.x} ${after.y}`,
    );
  }
  const last = translated.at(-1)!;
  commands.push(`L${last.x} ${last.y}`);
  return commands.join(" ");
}

export function smoothCurvePath(
  start: ElkPoint,
  end: ElkPoint,
  offsetX: number,
  offsetY: number,
): string {
  const curve = cubicCurve(
    { x: start.x + offsetX, y: start.y + offsetY },
    { x: end.x + offsetX, y: end.y + offsetY },
  );
  return `M${curve.start.x} ${curve.start.y} C${curve.control1.x} ${curve.control1.y} ${curve.control2.x} ${curve.control2.y} ${curve.end.x} ${curve.end.y}`;
}

function sectionPoints(section: ElkEdgeSection): ElkPoint[] {
  return [section.startPoint, ...(section.bendPoints ?? []), section.endPoint];
}

function edgeLabelPosition(section: ElkEdgeSection): ElkPoint {
  const points = sectionPoints(section);
  const middle = Math.max(0, Math.floor((points.length - 1) / 2));
  const first = points[middle] ?? section.startPoint;
  const second = points[middle + 1] ?? section.endPoint;
  return { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
}

function renderEdge(
  edge: DiagramEdge,
  section: ElkEdgeSection,
  locale: Locale,
  offsetX: number,
  offsetY: number,
  layoutLabel?: ElkLabel,
): string {
  const style = edgeStyles[edge.kind];
  const label = edge.label?.[locale];
  const labelGeometry = edgeLabelGeometry(edge);
  const fallbackPosition = edgeLabelPosition(section);
  const labelX = layoutLabel?.x !== undefined && labelGeometry
    ? layoutLabel.x + labelGeometry.width / 2
    : fallbackPosition.x;
  const labelY = layoutLabel?.y !== undefined && labelGeometry
    ? layoutLabel.y + labelGeometry.height / 2
    : fallbackPosition.y - 9;
  const labelLines = label && labelGeometry
    ? wrapText(label, labelGeometry.maxLabelUnits)
    : [];
  const labelStart = labelGeometry
    ? -((labelLines.length - 1) * EDGE_LINE_HEIGHT) / 2 + EDGE_FONT_SIZE * 0.35
    : 0;
  const labelMarkup = label && labelGeometry
    ? `<g class="edge-label" transform="translate(${labelX + offsetX} ${labelY + offsetY})"><rect x="${-labelGeometry.width / 2}" y="${-labelGeometry.height / 2}" width="${labelGeometry.width}" height="${labelGeometry.height}" rx="4"/>${textLines(labelLines, 0, labelStart, "edge-label-text", EDGE_LINE_HEIGHT)}</g>`
    : "";
  const accessibleLabel = label ?? edgeKindLabels[edge.kind][locale];
  const path =
    edge.route === "curve"
      ? smoothCurvePath(section.startPoint, section.endPoint, offsetX, offsetY)
      : roundedEdgePath(sectionPoints(section), offsetX, offsetY);
  return `<g class="diagram-edge edge-${edge.kind}" data-edge-id="${edge.id}" data-edge-from="${edge.from.split(":", 1)[0]}" data-edge-to="${edge.to.split(":", 1)[0]}"><title>${escapeXml(accessibleLabel)}</title><path d="${path}" fill="none" stroke="${style.color}" stroke-width="${style.width}" stroke-dasharray="${style.dash}" stroke-linecap="round" stroke-linejoin="round" marker-end="url(#arrow-${edge.kind})"/>${labelMarkup}</g>`;
}

function renderLegend(spec: DiagramSpec, locale: Locale, y: number): string {
  if (!spec.legend?.length) return "";
  let x = 48;
  const items = spec.legend.map((item) => {
    const style = edgeStyles[item.kind];
    const label = item.label[locale];
    const width = Math.max(120, estimatedTextWidth(label, 12) + 58);
    const markup = `<g class="legend-item" transform="translate(${x} ${y})"><line x1="0" y1="0" x2="34" y2="0" stroke="${style.color}" stroke-width="${style.width}" stroke-dasharray="${style.dash}" marker-end="url(#arrow-${item.kind})"/><text x="45" y="5">${escapeXml(label)}</text></g>`;
    x += width;
    return markup;
  });
  return `<g class="diagram-legend" role="group" aria-label="${locale === "ko" ? "범례" : "Legend"}">${items.join("")}</g>`;
}

export async function renderSvg(
  spec: DiagramSpec,
  layout: DiagramLayout,
  locale: Locale,
): Promise<string> {
  const offsetX = 48;
  const offsetY = 112;
  const legendHeight = spec.legend?.length ? 58 : 20;
  const width = Math.max(spec.canvas.width, Math.ceil(layout.width + offsetX * 2));
  const height = Math.max(
    spec.canvas.height,
    Math.ceil(layout.height + offsetY + legendHeight),
  );
  const groupById = new Map(spec.groups.map((group) => [group.id, group]));
  const nodeById = new Map(spec.nodes.map((node) => [node.id, node]));
  const edgeById = new Map(spec.edges.map((edge) => [edge.id, edge]));
  const markers = Object.entries(edgeStyles)
    .map(
      ([kind, style]) =>
        `<marker id="arrow-${kind}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${style.color}"/></marker>`,
    )
    .join("");
  const groups = [...layout.groups.values()]
    .sort((left, right) => left.depth - right.depth)
    .map((shape) => {
      const group = groupById.get(shape.id);
      if (!group) return "";
      const groupLines = wrapText(group.label[locale], (shape.width - 36) / 14);
      return `<g class="diagram-group group-${group.kind}" data-group-id="${group.id}" role="group" aria-label="${escapeXml(group.label[locale])}"><rect class="group-surface" x="${shape.x + offsetX}" y="${shape.y + offsetY}" width="${shape.width}" height="${shape.height}" rx="8"/><rect class="group-header" x="${shape.x + offsetX + 1}" y="${shape.y + offsetY + 1}" width="${Math.max(0, shape.width - 2)}" height="38" rx="7"/>${textLines(groupLines, shape.x + offsetX + 18, shape.y + offsetY + 27, "group-label", 16, "start")}</g>`;
    })
    .join("");
  const edges = layout.edges
    .flatMap((layoutEdge) => {
      const edge = edgeById.get(layoutEdge.id);
      if (!edge) return [];
      const container = layoutEdge.container
        ? layout.groups.get(layoutEdge.container)
        : undefined;
      return (layoutEdge.sections ?? []).map((section, index) =>
        renderEdge(
          edge,
          section,
          locale,
          offsetX + (container?.x ?? 0),
          offsetY + (container?.y ?? 0),
          index === 0 ? layoutEdge.labels?.[0] : undefined,
        ),
      );
    })
    .join("");
  const nodes = (
    await Promise.all(
      [...layout.nodes.values()].map(async (shape) => {
        const node = nodeById.get(shape.id);
        if (!node) return "";
        const translatedShape = {
          ...shape,
          x: shape.x + offsetX,
          y: shape.y + offsetY,
        };
        return renderNode(node, translatedShape, locale);
      }),
    )
  ).join("");

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="diagram-title diagram-description" data-diagram-id="${spec.id}" data-locale="${locale}">
  <title id="diagram-title">${escapeXml(spec.locales[locale].title)}</title>
  <desc id="diagram-description">${escapeXml(spec.locales[locale].alt)}</desc>
  <metadata>${escapeXml(JSON.stringify({ id: spec.id, version: spec.version, updated: spec.updated }))}</metadata>
  <defs>${markers}<filter id="node-shadow" x="-20%" y="-20%" width="140%" height="150%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="#172b4d" flood-opacity="0.14"/></filter></defs>
  <style>
    svg[data-diagram-id] { color: var(--fdai-diagram-text, #323130); font-family: "Noto Sans KR", "Noto Sans", "Segoe UI", sans-serif; }
    .diagram-title { font-size: 26px; font-weight: 700; fill: var(--fdai-diagram-text, #323130); }
    .diagram-subtitle { font-size: 14px; fill: var(--fdai-diagram-muted, #605e5c); }
    .diagram-group .group-surface { fill: var(--fdai-diagram-surface, #ffffff); stroke: var(--fdai-diagram-border, #a19f9d); stroke-width: 1.5; stroke-dasharray: 5 4; }
    .diagram-group .group-header { fill: var(--fdai-diagram-neutral-header, #edebe9); stroke: none; }
    .diagram-group.group-system .group-surface { fill: var(--fdai-diagram-control-surface, #eff6fc); stroke: var(--fdai-diagram-azure, #0078d4); }
    .diagram-group.group-system .group-header { fill: var(--fdai-diagram-control-header, #deecf9); }
    .diagram-group[data-group-id="control-flow"] .group-header { fill: var(--fdai-diagram-control-header, #deecf9); }
    .diagram-group[data-group-id="operational-signals"] .group-surface { fill: var(--fdai-diagram-surface, #ffffff); stroke: var(--fdai-diagram-border, #a19f9d); }
    .diagram-group[data-group-id="operational-signals"] .group-header { fill: var(--fdai-diagram-neutral-header, #edebe9); }
    .diagram-group[data-group-id="delivery-surfaces"] .group-surface { fill: var(--fdai-diagram-delivery-surface, #f0fbfd); stroke: var(--fdai-diagram-cyan-dark, #35b4e3); }
    .diagram-group[data-group-id="delivery-surfaces"] .group-header { fill: var(--fdai-diagram-delivery-header, #d9f8ff); }
    .diagram-group[data-group-id="rule-catalog-layer"] .group-surface { fill: var(--fdai-diagram-surface, #ffffff); stroke: var(--fdai-diagram-border-strong, #605e5c); }
    .diagram-group[data-group-id="rule-catalog-layer"] .group-header { fill: var(--fdai-diagram-neutral-header, #edebe9); }
    .diagram-group[data-group-id="human-channel"] .group-surface { fill: var(--fdai-diagram-delivery-surface, #f0fbfd); stroke: var(--fdai-diagram-cyan-dark, #35b4e3); }
    .diagram-group[data-group-id="human-channel"] .group-header { fill: var(--fdai-diagram-delivery-header, #d9f8ff); }
    .diagram-group[data-group-id="action-delivery"] .group-surface { fill: var(--fdai-diagram-control-surface, #eff6fc); stroke: var(--fdai-diagram-azure, #0078d4); }
    .diagram-group[data-group-id="action-delivery"] .group-header { fill: var(--fdai-diagram-control-header, #deecf9); }
    .diagram-group[data-group-id="operator-console-layer"] .group-surface { fill: var(--fdai-diagram-delivery-surface, #f0fbfd); stroke: var(--fdai-diagram-cyan-dark, #35b4e3); }
    .diagram-group[data-group-id="operator-console-layer"] .group-header { fill: var(--fdai-diagram-delivery-header, #d9f8ff); }
    .diagram-group.group-network .group-surface, .diagram-group.group-subnet .group-surface { fill: var(--fdai-diagram-delivery-surface, #f0fbfd); stroke: #008272; }
    .group-label { font-size: 14px; font-weight: 650; fill: var(--fdai-diagram-muted, #605e5c); }
    .diagram-node rect { fill: var(--fdai-diagram-node, #ffffff); stroke: var(--fdai-diagram-border, #a19f9d); stroke-width: 1.25; filter: url(#node-shadow); }
    .diagram-node:hover rect, .diagram-node:focus rect, .diagram-node.is-active rect { stroke: var(--fdai-diagram-azure-dark, #005a9e); stroke-width: 3; }
    .diagram-node:focus { outline: none; }
    .node-label { font-size: 13px; font-weight: 650; fill: var(--fdai-diagram-text, #323130); letter-spacing: 0; }
    .generic-icon circle, .generic-icon path { fill: var(--fdai-diagram-azure-soft, #deecf9); stroke: var(--fdai-diagram-azure, #0078d4); stroke-width: 1.8; }
    .generic-icon text { font-size: 12px; font-weight: 700; fill: var(--fdai-diagram-azure-dark, #005a9e); }
    .edge-label rect { fill: var(--fdai-diagram-label-surface, #ffffff); stroke: var(--fdai-diagram-border, #a19f9d); }
    .edge-label-text, .legend-item text { font-size: 12px; font-weight: 600; fill: var(--fdai-diagram-muted, #605e5c); }
    .diagram-edge.is-muted { opacity: 0.12; }
    .diagram-edge.is-active path { stroke-width: 4; }
  </style>
  <rect class="diagram-background" width="${width}" height="${height}" fill="var(--fdai-diagram-canvas, #faf9f8)"/>
  <text class="diagram-title" x="48" y="45">${escapeXml(spec.locales[locale].title)}</text>
  <text class="diagram-subtitle" x="48" y="72">${escapeXml(spec.locales[locale].description)}</text>
  <g data-diagram-viewport="">${groups}${edges}${nodes}${renderLegend(spec, locale, height - 30)}</g>
</svg>`;
}
