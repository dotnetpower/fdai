import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import type {
  ElkEdgeSection,
  ElkLabel,
  ElkPoint,
} from "elkjs/lib/elk-api.js";
import {
  BadgeCheck,
  BookOpen,
  Cable,
  CirclePause,
  FileCheck,
  GitBranch,
  Inbox,
  Play,
  RefreshCcw,
  Route,
  SearchCheck,
  ShieldCheck,
  Terminal,
  Wrench,
  type IconNode,
} from "lucide";

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
  GROUP_FONT_SIZE,
  NODE_BODY_FONT_SIZE,
  NODE_BODY_LINE_HEIGHT,
  NODE_FONT_SIZE,
  NODE_LINE_HEIGHT,
  edgeLabelGeometry,
  estimatedTextWidth,
  nodeBodyLines,
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
  feedback: { color: "#6b4eff", dash: "8 4", width: 2.6 },
  sequence: { color: "#0f6cbd", dash: "none", width: 2.4 },
  transition: { color: "#6b46c1", dash: "none", width: 2.4 },
  association: { color: "#44546a", dash: "none", width: 2.2 },
  dependency: { color: "#7a8699", dash: "5 4", width: 2.2 },
  timeline: { color: "#b77900", dash: "none", width: 3 },
};

const toneStyles = {
  input: { fill: "#f4f8ff", stroke: "#2563eb" },
  interpretation: { fill: "#eef6ff", stroke: "#0f6cbd" },
  model: { fill: "#eefbf7", stroke: "#008272" },
  policy: { fill: "#f1faef", stroke: "#2e7d32" },
  decision: { fill: "#fff8e6", stroke: "#b77900" },
  execution: { fill: "#f7f2ff", stroke: "#6b46c1" },
  feedback: { fill: "#f5f2ff", stroke: "#6b4eff" },
  store: { fill: "#f6f7f8", stroke: "#5f6b7a" },
  neutral: { fill: "#ffffff", stroke: "#7a8699" },
} as const;

const edgeKindLabels: Record<EdgeKind, Record<Locale, string>> = {
  request: { en: "Decision request", ko: "결정 요청" },
  event: { en: "Asynchronous event", ko: "비동기 이벤트" },
  approval: { en: "Human approval", ko: "사람 승인" },
  mutation: { en: "Governed change", ko: "통제된 변경" },
  audit: { en: "Audit record", ko: "감사 기록" },
  rollback: { en: "Rollback path", ko: "롤백 경로" },
  read: { en: "Read projection", ko: "읽기 projection" },
  write: { en: "Write", ko: "쓰기" },
  feedback: { en: "Feedback loop", ko: "피드백 루프" },
  sequence: { en: "Interaction", ko: "상호작용" },
  transition: { en: "State transition", ko: "상태 전이" },
  association: { en: "Association", ko: "연관 관계" },
  dependency: { en: "Dependency", ko: "의존 관계" },
  timeline: { en: "Timeline", ko: "타임라인" },
};

interface IconEntry {
  file: string;
  mediaType?: "image/png" | "image/svg+xml";
  productName: string;
  sha256: string;
}

interface IconLock {
  icons: Record<string, IconEntry>;
}

interface PantheonIconEntry {
  name: string;
  role: string;
  accent: string;
  file: string;
}

interface PantheonIconManifest {
  collective: PantheonIconEntry;
  agents: PantheonIconEntry[];
}

const iconCatalogs = await Promise.all([
  loadIconCatalog("azure"),
  loadIconCatalog("brands"),
]);
const pantheonIconDirectory = fileURLToPath(
  new URL("../../../../console/public/agent-icons/", import.meta.url),
);
const pantheonIconManifest = JSON.parse(
  await readFile(`${pantheonIconDirectory}/manifest.json`, "utf8"),
) as PantheonIconManifest;
const pantheonIconById = new Map(
  pantheonIconManifest.agents.map((agent) => [agent.name.toLowerCase(), agent]),
);
const lucideIconById = new Map<string, IconNode>([
  ["lucide-badge-check", BadgeCheck],
  ["lucide-book-open", BookOpen],
  ["lucide-cable", Cable],
  ["lucide-circle-pause", CirclePause],
  ["lucide-file-check", FileCheck],
  ["lucide-git-branch", GitBranch],
  ["lucide-inbox", Inbox],
  ["lucide-play", Play],
  ["lucide-refresh-ccw", RefreshCcw],
  ["lucide-route", Route],
  ["lucide-search-check", SearchCheck],
  ["lucide-shield-check", ShieldCheck],
  ["lucide-terminal", Terminal],
  ["lucide-wrench", Wrench],
]);

async function loadIconCatalog(name: string): Promise<{
  directory: string;
  lock: IconLock;
}> {
  const assetUrl = new URL(`../../assets/${name}/`, import.meta.url);
  return {
    directory: fileURLToPath(assetUrl),
    lock: JSON.parse(
      await readFile(new URL("icons.lock.json", assetUrl), "utf8"),
    ) as IconLock,
  };
}

function escapeXml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function lucideIconDataUri(icon: string): string | undefined {
  if (!icon.startsWith("lucide-")) return undefined;
  const iconNode = lucideIconById.get(icon);
  if (!iconNode) throw new Error(`Unknown diagram icon '${icon}'`);
  const body = iconNode
    .map(([tag, attributes]) => {
      const serialized = Object.entries(attributes)
        .filter(([name]) => name !== "key")
        .map(([name, value]) => ` ${name}="${escapeXml(String(value))}"`)
        .join("");
      return `<${tag}${serialized}/>`;
    })
    .join("");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#44688e" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
  return `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
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
  const lucideIcon = lucideIconDataUri(icon);
  if (lucideIcon) return lucideIcon;
  const catalog = iconCatalogs.find(({ lock }) => lock.icons[icon]);
  if (!catalog) throw new Error(`Unknown diagram icon '${icon}'`);
  const entry = catalog.lock.icons[icon];
  if (!entry) throw new Error(`Unknown diagram icon '${icon}'`);
  const source = await readFile(`${catalog.directory}/${entry.file}`);
  const payload = source.at(-1) === 0x0a ? source.subarray(0, -1) : source;
  const digest = createHash("sha256").update(payload).digest("hex");
  if (digest !== entry.sha256) {
    throw new Error(`Diagram icon '${icon}' does not match icons.lock.json`);
  }
  return `data:${entry.mediaType ?? "image/svg+xml"};base64,${source.toString("base64")}`;
}

async function pantheonIconDataUri(entry: PantheonIconEntry, iconId: string): Promise<string> {
  const source = await readFile(`${pantheonIconDirectory}/${entry.file}`, "utf8");
  if (
    !source.startsWith("<svg ") ||
    /<(?:script|foreignObject)\b|\b(?:href|src)\s*=/iu.test(source)
  ) {
    throw new Error(`Pantheon icon '${iconId}' contains unsupported SVG content`);
  }
  return `data:image/svg+xml;base64,${Buffer.from(
    source.replaceAll("currentColor", entry.accent),
  ).toString("base64")}`;
}

async function pantheonAgentIconDataUri(node: DiagramNode): Promise<string> {
  const entry = pantheonIconById.get(node.id);
  if (!entry) {
    throw new Error(`Unknown pantheon agent icon '${node.id}'`);
  }
  return pantheonIconDataUri(entry, node.id);
}

async function renderNode(
  node: DiagramNode,
  shape: PositionedShape,
  locale: Locale,
): Promise<string> {
  const geometry = nodeGeometry(node);
  const icon = node.kind === "agent"
    ? await pantheonAgentIconDataUri(node)
    : node.icon === "agent-pantheon"
      ? await pantheonIconDataUri(pantheonIconManifest.collective, node.icon)
      : await iconDataUri(node.icon);
  const x = shape.x + shape.width / 2;
  const labelLines = wrapText(node.label[locale], geometry.maxLabelUnits);
  const labelStart = shape.y + geometry.labelTop + NODE_FONT_SIZE;
  const bodyLines = nodeBodyLines(node, locale, geometry.maxBodyUnits);
  const bodyMarkup = bodyLines.length
    ? textLines(
        bodyLines,
        shape.x + 14,
        shape.y + geometry.bodyTop + NODE_BODY_FONT_SIZE,
        "node-body",
        NODE_BODY_LINE_HEIGHT,
        "start",
      )
    : "";
  const iconMarkup = icon
    ? `<image${node.kind === "agent" ? ' class="agent-icon"' : ""} href="${icon}" x="${x - geometry.iconSize / 2}" y="${shape.y + geometry.iconTop}" width="${geometry.iconSize}" height="${geometry.iconSize}" preserveAspectRatio="xMidYMid meet" aria-hidden="true"/>`
    : "";
  const description = node.description?.[locale] ?? node.label[locale];
  const presentation = node.presentation ?? "card";
  const nodeShape = node.shape ?? "card";
  const surface = nodeShapeMarkup(nodeShape, shape, presentation);
  const badgeMarkup = node.badge
    ? `<g class="node-badge" transform="translate(${shape.x + 14} ${shape.y + 14})" aria-hidden="true"><circle r="12"/><text y="4">${node.badge}</text></g>`
    : "";
  return `<g class="diagram-node node-${node.kind}" data-node-id="${node.id}" data-presentation="${presentation}" data-shape="${nodeShape}" data-tone="${node.tone ?? "neutral"}" role="button" tabindex="0" aria-label="${escapeXml(`${node.label[locale]}. ${description}`)}">${surface}${iconMarkup}${textLines(labelLines, x, labelStart, "node-label")}${bodyMarkup}${badgeMarkup}</g>`;
}

function nodeShapeMarkup(
  shapeKind: NonNullable<DiagramNode["shape"]>,
  shape: PositionedShape,
  presentation: NonNullable<DiagramNode["presentation"]> | "card",
): string {
  const { x, y, width, height } = shape;
  if (shapeKind === "diamond") {
    return `<polygon class="node-surface" points="${x + width / 2},${y} ${x + width},${y + height / 2} ${x + width / 2},${y + height} ${x},${y + height / 2}"/>`;
  }
  if (shapeKind === "circle") {
    return `<ellipse class="node-surface" cx="${x + width / 2}" cy="${y + height / 2}" rx="${width / 2}" ry="${height / 2}"/>`;
  }
  if (shapeKind === "database") {
    const curve = Math.min(14, height / 5);
    return `<path class="node-surface" d="M${x} ${y + curve} C${x} ${y} ${x + width} ${y} ${x + width} ${y + curve} L${x + width} ${y + height - curve} C${x + width} ${y + height} ${x} ${y + height} ${x} ${y + height - curve} Z"/><path class="node-detail" d="M${x} ${y + curve} C${x} ${y + curve * 2} ${x + width} ${y + curve * 2} ${x + width} ${y + curve}"/>`;
  }
  if (shapeKind === "document") {
    const fold = Math.min(18, width / 5, height / 4);
    return `<path class="node-surface" d="M${x} ${y} H${x + width - fold} L${x + width} ${y + fold} V${y + height} H${x} Z"/><path class="node-detail" d="M${x + width - fold} ${y} V${y + fold} H${x + width}"/>`;
  }
  const radius = shapeKind === "terminator"
    ? height / 2
    : presentation === "icon"
      ? 4
      : 8;
  return `<rect class="node-surface" x="${x}" y="${y}" width="${width}" height="${height}" rx="${radius}"/>`;
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

function edgeStepPosition(
  section: ElkEdgeSection,
  labelX: number,
  labelY: number,
  labelGeometry: ReturnType<typeof edgeLabelGeometry>,
): ElkPoint {
  if (labelGeometry) {
    return {
      x: labelX - labelGeometry.width / 2 - 19,
      y: labelY,
    };
  }
  const fallback = edgeLabelPosition(section);
  return { x: fallback.x, y: fallback.y - 18 };
}

function renderEdge(
  edge: DiagramEdge,
  section: ElkEdgeSection,
  locale: Locale,
  offsetX: number,
  offsetY: number,
  profile: DiagramSpec["canvas"]["profile"],
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
  const stepPosition = edgeStepPosition(section, labelX, labelY, labelGeometry);
  const stepMarkup = edge.step
    ? `<g class="edge-step" transform="translate(${stepPosition.x + offsetX} ${stepPosition.y + offsetY})" aria-hidden="true"><circle r="13"/><text y="4">${edge.step}</text></g>`
    : "";
  const accessibleLabel = `${edge.step ? `Step ${edge.step}. ` : ""}${label ?? edgeKindLabels[edge.kind][locale]}`;
  const path =
    edge.route === "curve"
      ? smoothCurvePath(section.startPoint, section.endPoint, offsetX, offsetY)
      : roundedEdgePath(
          sectionPoints(section),
          offsetX,
          offsetY,
          profile === "azure-reference" ? 4 : 14,
        );
  return `<g class="diagram-edge edge-${edge.kind}" data-edge-id="${edge.id}" data-edge-from="${edge.from.split(":", 1)[0]}" data-edge-to="${edge.to.split(":", 1)[0]}" data-edge-route="${edge.route ?? "auto"}"${edge.step ? ` data-edge-step="${edge.step}"` : ""}><title>${escapeXml(accessibleLabel)}</title><path class="edge-hit" d="${path}"/><path class="edge-path" d="${path}" fill="none" stroke="${style.color}" stroke-width="${style.width}" stroke-dasharray="${style.dash}" stroke-linecap="round" stroke-linejoin="round" marker-end="url(#arrow-${edge.kind})"/>${labelMarkup}${stepMarkup}</g>`;
}

function renderLegend(spec: DiagramSpec, locale: Locale, y: number): string {
  if (!spec.legend?.length) return "";
  let x = 48;
  const items = spec.legend.map((item) => {
    const label = item.label[locale];
    const width = Math.max(120, estimatedTextWidth(label, 12) + 58);
    const symbol = item.kind
      ? `<line x1="0" y1="0" x2="34" y2="0" stroke="${edgeStyles[item.kind].color}" stroke-width="${edgeStyles[item.kind].width}" stroke-dasharray="${edgeStyles[item.kind].dash}" marker-end="url(#arrow-${item.kind})"/>`
      : `<rect class="legend-swatch" x="0" y="-10" width="28" height="18" rx="3" fill="${toneStyles[item.tone].fill}" stroke="${toneStyles[item.tone].stroke}"/>`;
    const markup = `<g class="legend-item" transform="translate(${x} ${y})">${symbol}<text x="45" y="5">${escapeXml(label)}</text></g>`;
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
        `<marker id="arrow-${kind}" viewBox="0 0 10 10" refX="9.5" refY="5" markerUnits="userSpaceOnUse" markerWidth="9" markerHeight="9" orient="auto"><path d="M0 0L10 5L0 10z" fill="${style.color}"/></marker>`,
    )
    .join("");
  const groups = [...layout.groups.values()]
    .sort((left, right) => left.depth - right.depth)
    .map((shape) => {
      const group = groupById.get(shape.id);
      if (!group) return "";
      const groupLines = wrapText(
        group.label[locale],
        (shape.width - 36) / GROUP_FONT_SIZE,
      );
      const presentation = group.presentation ?? "default";
      const radius = spec.canvas.profile === "azure-reference" ? 2 : 8;
      return `<g class="diagram-group group-${group.kind}" data-group-id="${group.id}" data-presentation="${presentation}" role="group" aria-label="${escapeXml(group.label[locale])}"><rect class="group-surface" x="${shape.x + offsetX}" y="${shape.y + offsetY}" width="${shape.width}" height="${shape.height}" rx="${radius}"/><rect class="group-header" x="${shape.x + offsetX + 1}" y="${shape.y + offsetY + 1}" width="${Math.max(0, shape.width - 2)}" height="38" rx="${radius}"/>${textLines(groupLines, shape.x + offsetX + 18, shape.y + offsetY + 27, "group-label", 16, "start")}</g>`;
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
          spec.canvas.profile,
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

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="diagram-title diagram-description" data-diagram-id="${spec.id}" data-locale="${locale}" data-profile="${spec.canvas.profile ?? "default"}">
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
    .group-label { font-size: ${GROUP_FONT_SIZE}px; font-weight: 650; fill: var(--fdai-diagram-muted, #605e5c); }
    .diagram-node > rect, .diagram-node > .node-surface { fill: var(--fdai-diagram-node, #ffffff); stroke: var(--fdai-diagram-border, #a19f9d); stroke-width: 1.25; filter: url(#node-shadow); }
    .diagram-node:hover > rect, .diagram-node:focus > rect, .diagram-node.is-active > rect,
    .diagram-node:hover > .node-surface, .diagram-node:focus > .node-surface, .diagram-node.is-active > .node-surface { stroke: var(--fdai-diagram-azure-dark, #005a9e); stroke-width: 3; }
    .diagram-node:focus { outline: none; }
    .node-label { font-size: ${NODE_FONT_SIZE}px; font-weight: 650; fill: var(--fdai-diagram-text, #323130); letter-spacing: 0; }
    .node-body { font-size: ${NODE_BODY_FONT_SIZE}px; font-weight: 450; fill: var(--fdai-diagram-muted, #605e5c); letter-spacing: 0; }
    .node-detail { fill: none; stroke: var(--fdai-diagram-border, #a19f9d); stroke-width: 1.25; }
    .node-badge circle { fill: #173b6c; stroke: #ffffff; stroke-width: 2; }
    .node-badge text { fill: #ffffff; font-size: 11px; font-weight: 700; text-anchor: middle; }
    ${Object.entries(toneStyles).map(([tone, style]) => `.diagram-node[data-tone="${tone}"] > .node-surface { fill: ${style.fill}; stroke: ${style.stroke}; }`).join("\n    ")}
    .edge-hit { fill: none; stroke: transparent; stroke-width: 14; pointer-events: stroke; cursor: pointer; }
    .edge-path { pointer-events: stroke; transition: stroke-width 140ms ease, opacity 140ms ease; }
    .diagram-edge[data-edge-route="orthogonal-above"][data-edge-step] > .edge-path { opacity: 0.52; stroke-width: 2; }
    .edge-label { cursor: pointer; }
    .edge-label rect { fill: var(--fdai-diagram-label-surface, #ffffff); stroke: var(--fdai-diagram-border, #a19f9d); transition: fill 140ms ease, stroke 140ms ease, stroke-width 140ms ease; }
    .edge-label-text, .legend-item text { font-size: 12px; font-weight: 600; fill: var(--fdai-diagram-muted, #605e5c); }
    .edge-label-text { transition: fill 140ms ease; }
    .diagram-edge.is-muted { opacity: 0.12; }
    .diagram-edge.is-muted:hover { opacity: 1; }
    .diagram-edge.is-active > .edge-path, .diagram-edge:hover > .edge-path { stroke-width: 4; opacity: 1; }
    .diagram-edge:hover .edge-label rect { fill: var(--fdai-diagram-control-header, #deecf9); stroke: var(--fdai-diagram-azure-dark, #005a9e); stroke-width: 2; }
    .diagram-edge:hover .edge-label-text { fill: var(--fdai-diagram-text, #323130); font-weight: 700; }
    .edge-step circle { fill: #107c10; stroke: #ffffff; stroke-width: 2; }
    .edge-step text { fill: #ffffff; font-size: 12px; font-weight: 700; text-anchor: middle; }
    svg[data-profile="conceptual"] .diagram-group .group-surface { stroke-dasharray: none; }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="lane"] .group-surface { fill: #ffffff; stroke: #9fb3c8; }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="sidebar"] .group-surface { fill: #f7f5ff; stroke: #7c5ce7; }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="feedback"] .group-surface { fill: #faf8ff; stroke: #6b4eff; }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="datastore"] .group-surface { fill: #f7f8fa; stroke: #6b7280; }
    svg[data-profile="azure-reference"] .diagram-title { font-size: 24px; }
    svg[data-profile="azure-reference"] .diagram-group .group-surface { stroke-dasharray: none; }
    svg[data-profile="azure-reference"] .diagram-group .group-header { fill: transparent; }
    svg[data-profile="azure-reference"] .diagram-group[data-presentation="boundary"] .group-surface { fill: #ffffff; stroke: var(--fdai-diagram-azure, #0078d4); stroke-width: 1.75; }
    svg[data-profile="azure-reference"] .diagram-group[data-presentation="band"] .group-surface { fill: #f3f2f1; stroke: #d2d0ce; stroke-width: 1; }
    svg[data-profile="azure-reference"] .diagram-group[data-presentation="band"] .group-header { fill: #e9e9e9; }
    svg[data-profile="azure-reference"] .diagram-group[data-presentation="panel"] .group-surface { fill: #ffffff; stroke: #d2d0ce; stroke-width: 1; }
    svg[data-profile="azure-reference"] .diagram-group[data-group-id="azure-region"] > .group-surface { fill: #f8fbfe; stroke: #b8c7d9; }
    svg[data-profile="azure-reference"] .diagram-group[data-group-id="azure-region"] > .group-header { fill: #eef4fa; }
    svg[data-profile="azure-reference"] .diagram-group[data-group-id="fdai-vnet"] > .group-surface { fill: #ffffff; }
    svg[data-profile="azure-reference"] .diagram-group[data-group-id="platform-services"] > .group-surface { fill: #f5f9fc; stroke: #b8c7d9; }
    svg[data-profile="azure-reference"] .diagram-group[data-group-id="platform-services"] > .group-header { fill: #e7f0f7; }
    svg[data-profile="azure-reference"] .diagram-group[data-group-id="governed-delivery"] > .group-surface { fill: #f8fafc; stroke: #b8c7d9; }
    svg[data-profile="azure-reference"] .diagram-group[data-group-id="governed-delivery"] > .group-header { fill: #eaf0f5; }
    svg[data-profile="azure-reference"] .diagram-group[data-group-id="private-service-backends"] > .group-surface { fill: #fbfcfd; stroke: #c8d0d8; }
    svg[data-profile="azure-reference"] .diagram-group[data-group-id="private-service-backends"] > .group-header { fill: #f1f4f6; }
    svg[data-profile="azure-reference"] .diagram-node > rect { filter: none; }
    svg[data-profile="azure-reference"] .diagram-node[data-presentation="icon"] > rect { fill: transparent; stroke: transparent; }
    svg[data-profile="azure-reference"] .diagram-node[data-presentation="icon"]:hover > rect,
    svg[data-profile="azure-reference"] .diagram-node[data-presentation="icon"]:focus > rect,
    svg[data-profile="azure-reference"] .diagram-node[data-presentation="icon"].is-active > rect { fill: #ffffff; stroke: var(--fdai-diagram-azure, #0078d4); stroke-width: 1.5; }
    svg[data-profile="azure-reference"] .group-label { fill: #3b3a39; font-weight: 650; }
    svg[data-profile="azure-reference"] .node-label { font-size: 13px; font-weight: 650; fill: #323130; }
    svg[data-profile="azure-reference"] .edge-label-text,
    svg[data-profile="azure-reference"] .legend-item text { fill: #484644; font-weight: 650; }
  </style>
  <rect class="diagram-background" width="${width}" height="${height}" fill="${spec.canvas.profile === "azure-reference" || spec.canvas.profile === "conceptual" ? "#ffffff" : "var(--fdai-diagram-canvas, #faf9f8)"}"/>
  <text class="diagram-title" x="48" y="45">${escapeXml(spec.locales[locale].title)}</text>
  <text class="diagram-subtitle" x="48" y="72">${escapeXml(spec.locales[locale].description)}</text>
  <g data-diagram-viewport="">${groups}${edges}${nodes}${renderLegend(spec, locale, height - 30)}</g>
</svg>`;
}
