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
import {
  CALM_SLATE_LIGHT,
  calmSlateFoundationCss,
  standaloneThemeCss,
} from "./theme.js";
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
  REFERENCE_EDGE_FONT_SIZE,
  REFERENCE_EDGE_LINE_HEIGHT,
  REFERENCE_GROUP_FONT_SIZE,
  REFERENCE_NODE_BODY_FONT_SIZE,
  REFERENCE_NODE_BODY_LINE_HEIGHT,
  REFERENCE_NODE_FONT_SIZE,
  REFERENCE_NODE_LINE_HEIGHT,
  edgeLabelGeometry,
  estimatedTextWidth,
  nodeBodyLines,
  nodeGeometry,
  wrapText,
} from "../model/text.js";

function themeColor(name: keyof typeof CALM_SLATE_LIGHT): string {
  return `var(${name}, ${CALM_SLATE_LIGHT[name]})`;
}

const edgeStyles: Record<EdgeKind, { color: string; dash: string; width: number }> = {
  request: { color: themeColor("--fdai-diagram-edge-request"), dash: "none", width: 2.4 },
  event: { color: themeColor("--fdai-diagram-edge-event"), dash: "7 4", width: 2.4 },
  approval: { color: themeColor("--fdai-diagram-edge-approval"), dash: "3 4", width: 2.6 },
  mutation: { color: themeColor("--fdai-diagram-edge-mutation"), dash: "none", width: 3 },
  audit: { color: themeColor("--fdai-diagram-edge-audit"), dash: "2 4", width: 2.4 },
  rollback: { color: themeColor("--fdai-diagram-edge-rollback"), dash: "9 4 2 4", width: 2.6 },
  read: { color: themeColor("--fdai-diagram-edge-read"), dash: "5 4", width: 2.2 },
  write: { color: themeColor("--fdai-diagram-edge-write"), dash: "none", width: 2.6 },
  feedback: { color: themeColor("--fdai-diagram-edge-feedback"), dash: "8 4", width: 2.6 },
  sequence: { color: themeColor("--fdai-diagram-edge-sequence"), dash: "none", width: 2.4 },
  transition: { color: themeColor("--fdai-diagram-edge-transition"), dash: "none", width: 2.4 },
  association: { color: themeColor("--fdai-diagram-edge-association"), dash: "none", width: 2.2 },
  dependency: { color: themeColor("--fdai-diagram-edge-dependency"), dash: "5 4", width: 2.2 },
  timeline: { color: themeColor("--fdai-diagram-edge-timeline"), dash: "none", width: 3 },
};

const toneStyles = {
  input: { fill: themeColor("--fdai-diagram-tone-input-fill"), stroke: themeColor("--fdai-diagram-tone-input-stroke") },
  interpretation: { fill: themeColor("--fdai-diagram-tone-interpretation-fill"), stroke: themeColor("--fdai-diagram-tone-interpretation-stroke") },
  model: { fill: themeColor("--fdai-diagram-tone-model-fill"), stroke: themeColor("--fdai-diagram-tone-model-stroke") },
  policy: { fill: themeColor("--fdai-diagram-tone-policy-fill"), stroke: themeColor("--fdai-diagram-tone-policy-stroke") },
  decision: { fill: themeColor("--fdai-diagram-tone-decision-fill"), stroke: themeColor("--fdai-diagram-tone-decision-stroke") },
  execution: { fill: themeColor("--fdai-diagram-tone-execution-fill"), stroke: themeColor("--fdai-diagram-tone-execution-stroke") },
  feedback: { fill: themeColor("--fdai-diagram-tone-feedback-fill"), stroke: themeColor("--fdai-diagram-tone-feedback-stroke") },
  store: { fill: themeColor("--fdai-diagram-tone-store-fill"), stroke: themeColor("--fdai-diagram-tone-store-stroke") },
  neutral: { fill: themeColor("--fdai-diagram-tone-neutral-fill"), stroke: themeColor("--fdai-diagram-tone-neutral-stroke") },
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
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#315f82" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
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
  offsetX = 0,
  offsetY = 0,
  compact = false,
): Promise<string> {
  const geometry = nodeGeometry(node, compact);
  const nodeFontSize = compact ? REFERENCE_NODE_FONT_SIZE : NODE_FONT_SIZE;
  const nodeLineHeight = compact ? REFERENCE_NODE_LINE_HEIGHT : NODE_LINE_HEIGHT;
  const bodyFontSize = compact ? REFERENCE_NODE_BODY_FONT_SIZE : NODE_BODY_FONT_SIZE;
  const bodyLineHeight = compact
    ? REFERENCE_NODE_BODY_LINE_HEIGHT
    : NODE_BODY_LINE_HEIGHT;
  const icon = node.kind === "agent"
    ? await pantheonAgentIconDataUri(node)
    : node.icon === "agent-pantheon"
      ? await pantheonIconDataUri(pantheonIconManifest.collective, node.icon)
      : await iconDataUri(node.icon);
  const barShape = node.shape === "bar";
  const pieSlice = node.shape === "pie-slice";
  const centeredChartNode = ["circle", "pie-slice"].includes(node.shape ?? "");
  const externalBarLabel = barShape && shape.labelX !== undefined;
  const x = externalBarLabel ? shape.labelX! : shape.x + shape.width / 2;
  const labelLines = wrapText(
    node.label[locale],
    externalBarLabel
      ? Math.max(4, shape.labelWidth! / nodeFontSize)
      : barShape || centeredChartNode
      ? Math.max(4, (shape.width - 16) / nodeFontSize)
      : geometry.maxLabelUnits,
  );
  const labelStart = externalBarLabel
    ? shape.labelY! + nodeFontSize * 0.35
    : barShape || centeredChartNode
    ? shape.y + shape.height / 2 -
      ((labelLines.length - 1) * nodeLineHeight) / 2 + nodeFontSize * 0.35
    : shape.y + geometry.labelTop + nodeFontSize;
  const bodyLines = nodeBodyLines(node, locale, geometry.maxBodyUnits);
  const bodyMarkup = bodyLines.length
    ? textLines(
        bodyLines,
        shape.x + 14,
        shape.y + geometry.bodyTop + bodyFontSize,
        "node-body",
        bodyLineHeight,
        "start",
      )
    : "";
  const presentation = node.presentation ?? "card";
  const nodeShape = node.shape ?? "card";
  const premiumCard = !compact &&
    (nodeShape === "card" || nodeShape === "terminator") &&
    presentation !== "icon";
  const iconBackplateMarkup = icon && premiumCard
    ? `<circle class="node-icon-backplate" cx="${x}" cy="${shape.y + geometry.iconTop + geometry.iconSize / 2}" r="${geometry.iconSize / 2 + 7}" aria-hidden="true"/>`
    : "";
  const iconMarkup = icon
    ? `<image${node.kind === "agent" ? ' class="agent-icon"' : ""} href="${icon}" x="${x - geometry.iconSize / 2}" y="${shape.y + geometry.iconTop}" width="${geometry.iconSize}" height="${geometry.iconSize}" preserveAspectRatio="xMidYMid meet" aria-hidden="true"/>`
    : "";
  const description = node.description?.[locale] ?? node.label[locale];
  const surface = barShape && node.status === "milestone"
    ? milestoneShapeMarkup(shape)
    : nodeShapeMarkup(nodeShape, shape, presentation);
  const insetMarkup = premiumCard
    ? `<rect class="node-inset" x="${shape.x + 2}" y="${shape.y + 2}" width="${Math.max(0, shape.width - 4)}" height="${Math.max(0, shape.height - 4)}" rx="${nodeShape === "terminator" ? Math.max(0, shape.height / 2 - 2) : 6}" aria-hidden="true"/>`
    : "";
  const dividerMarkup = premiumCard && bodyLines.length
    ? `<line class="node-divider" x1="${shape.x + 14}" y1="${shape.y + geometry.bodyTop - 4}" x2="${shape.x + shape.width - 14}" y2="${shape.y + geometry.bodyTop - 4}" aria-hidden="true"/>`
    : "";
  const progressMarkup = barShape && node.status !== "milestone" && node.progress !== undefined
    ? `<rect class="node-progress" x="${shape.x}" y="${shape.y}" width="${shape.width * node.progress / 100}" height="${shape.height}" rx="4" aria-hidden="true"/>`
    : "";
  const badgeMarkup = node.badge
    ? `<g class="node-badge" transform="translate(${shape.x + 14} ${shape.y + 14})" aria-hidden="true"><circle r="12"/><text y="4">${node.badge}</text></g>`
    : "";
  const leaderMarkup = shape.leader
    ? `<path class="chart-leader" d="${shape.leader}" aria-hidden="true"/>`
    : "";
  return `<g class="diagram-node node-${node.kind}" data-node-id="${node.id}" data-presentation="${presentation}" data-shape="${nodeShape}" data-tone="${node.tone ?? "neutral"}"${shape.paletteIndex !== undefined ? ` data-palette-index="${shape.paletteIndex % 8}"` : ""}${node.status ? ` data-status="${node.status}"` : ""} transform="translate(${offsetX} ${offsetY})" role="button" tabindex="0" aria-label="${escapeXml(`${node.label[locale]}. ${description}`)}">${leaderMarkup}${surface}${insetMarkup}${progressMarkup}${iconBackplateMarkup}${iconMarkup}${textLines(labelLines, x, labelStart, "node-label", nodeLineHeight, externalBarLabel ? "start" : "middle")}${dividerMarkup}${bodyMarkup}${badgeMarkup}</g>`;
}

function milestoneShapeMarkup(shape: PositionedShape): string {
  const centerX = shape.x + shape.width / 2;
  const centerY = shape.y + shape.height / 2;
  const radius = Math.min(11, shape.height / 2 - 2);
  return `<polygon class="node-surface" points="${centerX},${centerY - radius} ${centerX + radius},${centerY} ${centerX},${centerY + radius} ${centerX - radius},${centerY}"/>`;
}

function nodeShapeMarkup(
  shapeKind: NonNullable<DiagramNode["shape"]>,
  shape: PositionedShape,
  presentation: NonNullable<DiagramNode["presentation"]> | "card",
): string {
  const { x, y, width, height } = shape;
  if (shapeKind === "pie-slice" && shape.path) {
    return `<path class="node-surface" d="${shape.path}"/>`;
  }
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
    : shapeKind === "bar"
      ? 4
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
  diagramKind: DiagramSpec["kind"],
  profile: DiagramSpec["canvas"]["profile"],
  layoutLabel?: ElkLabel,
): string {
  const style = edgeStyles[edge.kind];
  const compact = profile === "azure-reference";
  const edgeFontSize = compact ? REFERENCE_EDGE_FONT_SIZE : EDGE_FONT_SIZE;
  const edgeLineHeight = compact ? REFERENCE_EDGE_LINE_HEIGHT : EDGE_LINE_HEIGHT;
  const strokeWidth = Math.min(14, style.width * (edge.weight ?? 1));
  const label = edge.label?.[locale];
  const labelGeometry = edgeLabelGeometry(edge, compact);
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
    ? -((labelLines.length - 1) * edgeLineHeight) / 2 + edgeFontSize * 0.35
    : 0;
  const labelMarkup = label && labelGeometry
    ? `<g class="edge-label" transform="translate(${labelX + offsetX} ${labelY + offsetY})"><rect x="${-labelGeometry.width / 2}" y="${-labelGeometry.height / 2}" width="${labelGeometry.width}" height="${labelGeometry.height}" rx="8"/>${textLines(labelLines, 0, labelStart, "edge-label-text", edgeLineHeight)}</g>`
    : "";
  const stepPosition = edgeStepPosition(section, labelX, labelY, labelGeometry);
  const stepMarkup = edge.step
    ? `<g class="edge-step" transform="translate(${stepPosition.x + offsetX} ${stepPosition.y + offsetY})" aria-hidden="true"><circle r="13"/><text y="4">${edge.step}</text></g>`
    : "";
  const accessibleLabel = `${edge.step ? `Step ${edge.step}. ` : ""}${label ?? edgeKindLabels[edge.kind][locale]}`;
  const sankey = diagramKind === "sankey";
  const path =
    edge.route === "curve" || sankey
      ? smoothCurvePath(section.startPoint, section.endPoint, offsetX, offsetY)
      : roundedEdgePath(
          sectionPoints(section),
          offsetX,
          offsetY,
          profile === "azure-reference" ? 4 : 14,
        );
  const marker = sankey ? "" : ` marker-end="url(#arrow-${edge.kind})"`;
  return `<g class="diagram-edge edge-${edge.kind}" data-edge-id="${edge.id}" data-edge-from="${edge.from.split(":", 1)[0]}" data-edge-to="${edge.to.split(":", 1)[0]}" data-edge-route="${edge.route ?? "auto"}"${edge.weight ? ` data-edge-weight="${edge.weight}"` : ""}${edge.step ? ` data-edge-step="${edge.step}"` : ""}><title>${escapeXml(accessibleLabel)}</title><path class="edge-hit" d="${path}"/><path class="edge-path" d="${path}" fill="none" stroke="${style.color}" stroke-width="${strokeWidth}" stroke-dasharray="${style.dash}" stroke-linecap="butt" stroke-linejoin="round"${marker}/>${labelMarkup}${stepMarkup}</g>`;
}

function renderLegend(spec: DiagramSpec, locale: Locale, y: number): string {
  if (!spec.legend?.length) return "";
  let x = 48;
  const items = spec.legend.map((item) => {
    const label = item.label[locale];
    const width = Math.max(120, estimatedTextWidth(label, 12) + 58);
    const symbol = item.kind
      ? `<line x1="0" y1="0" x2="34" y2="0" stroke="${edgeStyles[item.kind].color}" stroke-width="${edgeStyles[item.kind].width}" stroke-dasharray="${edgeStyles[item.kind].dash}" marker-end="url(#arrow-${item.kind})"/>`
      : `<rect class="legend-swatch" x="0" y="-8" width="24" height="14" rx="7" fill="${toneStyles[item.tone].fill}" stroke="${toneStyles[item.tone].stroke}"/>`;
    const markup = `<g class="legend-item" transform="translate(${x} ${y})">${symbol}<text x="45" y="5">${escapeXml(label)}</text></g>`;
    x += width;
    return markup;
  });
  return `<g class="diagram-legend" role="group" aria-label="${locale === "ko" ? "범례" : "Legend"}">${items.join("")}</g>`;
}

function renderChartBackdrop(
  spec: DiagramSpec,
  layout: DiagramLayout,
  locale: Locale,
  offsetX: number,
  offsetY: number,
): string {
  if (spec.kind === "gantt" && layout.axis) {
    const groups = [...layout.groups.values()];
    const top = offsetY + Math.min(...groups.map((group) => group.y));
    const bottom = offsetY + Math.max(...groups.map((group) => group.y + group.height));
    const ticks = Array.from({ length: 6 }, (_, index) => {
      const ratio = index / 5;
      const value = layout.axis!.minimum +
        (layout.axis!.maximum - layout.axis!.minimum) * ratio;
      const x = offsetX + layout.axis!.x + layout.axis!.width * ratio;
      const label = layout.axis!.kind === "date"
        ? new Date(value * 86_400_000).toISOString().slice(0, 10)
        : Number.isInteger(value) ? String(value) : value.toFixed(1);
      return `<line class="chart-guide" x1="${x}" y1="${top + 38}" x2="${x}" y2="${bottom}"/><text class="chart-tick-label" x="${x}" y="${top + 29}" text-anchor="middle">${label}</text>`;
    }).join("");
    return `<g class="chart-backdrop gantt-grid" aria-hidden="true">${ticks}</g>`;
  }
  if (spec.kind === "pie") {
    const centerX = offsetX + layout.width / 2;
    const centerY = offsetY + layout.height / 2;
    const total = spec.nodes.reduce((sum, node) => sum + (node.value ?? 0), 0);
    return `<g class="chart-backdrop donut-center" aria-hidden="true"><circle class="donut-center-ring" cx="${centerX}" cy="${centerY}" r="54"/><text class="donut-total" x="${centerX}" y="${centerY - 3}" text-anchor="middle">${total}</text><text class="donut-caption" x="${centerX}" y="${centerY + 19}" text-anchor="middle">TOTAL</text></g>`;
  }
  if (["quadrant", "xy-chart", "wardley"].includes(spec.kind)) {
    const padding = spec.canvas.padding ?? 56;
    const x = offsetX + padding;
    const y = offsetY + padding;
    const width = layout.width - padding * 2;
    const height = layout.height - padding * 2;
    const xAxis = spec.canvas.xAxis?.[locale] ?? "";
    const yAxis = spec.canvas.yAxis?.[locale] ?? "";
    const regions = spec.kind === "quadrant"
      ? `<rect class="quadrant-region region-one" x="${x}" y="${y}" width="${width / 2}" height="${height / 2}"/><rect class="quadrant-region region-two" x="${x + width / 2}" y="${y}" width="${width / 2}" height="${height / 2}"/><rect class="quadrant-region region-three" x="${x}" y="${y + height / 2}" width="${width / 2}" height="${height / 2}"/><rect class="quadrant-region region-four" x="${x + width / 2}" y="${y + height / 2}" width="${width / 2}" height="${height / 2}"/>`
      : "";
    return `<g class="chart-backdrop" aria-hidden="true"><rect class="chart-frame" x="${x}" y="${y}" width="${width}" height="${height}" rx="8"/>${regions}<line class="chart-guide" x1="${x + width / 2}" y1="${y}" x2="${x + width / 2}" y2="${y + height}"/><line class="chart-guide" x1="${x}" y1="${y + height / 2}" x2="${x + width}" y2="${y + height / 2}"/>${xAxis ? `<text class="chart-axis-label" x="${x + width / 2}" y="${y + height + 28}" text-anchor="middle">${escapeXml(xAxis)}</text>` : ""}${yAxis ? `<text class="chart-axis-label" x="${x - 18}" y="${y + height / 2}" text-anchor="middle" transform="rotate(-90 ${x - 18} ${y + height / 2})">${escapeXml(yAxis)}</text>` : ""}</g>`;
  }
  if (spec.kind === "radar") {
    const centerX = offsetX + layout.width / 2;
    const centerY = offsetY + layout.height / 2;
    const radius = Math.min(layout.width, layout.height) * 0.34;
    const points = [...layout.nodes.values()].map(
      (node) => `${offsetX + node.x + node.width / 2},${offsetY + node.y + node.height / 2}`,
    );
    const spokes = points.map((point) => {
      const [x, y] = point.split(",");
      return `<line class="radar-spoke" x1="${centerX}" y1="${centerY}" x2="${x}" y2="${y}"/>`;
    }).join("");
    return `<g class="chart-backdrop" aria-hidden="true">${[0.25, 0.5, 0.75, 1].map((scale) => `<circle class="chart-guide-ring" cx="${centerX}" cy="${centerY}" r="${radius * scale}"/>`).join("")}${spokes}<polygon class="radar-area" points="${points.join(" ")}"/></g>`;
  }
  return "";
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
        `<marker id="arrow-${kind}" viewBox="0 0 10 10" refX="9" refY="5" markerUnits="userSpaceOnUse" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 1L9 5L0 9z" fill="${style.color}"/></marker>`,
    )
    .join("");
  const groups = [...layout.groups.values()]
    .sort((left, right) => left.depth - right.depth)
    .map((shape) => {
      const group = groupById.get(shape.id);
      if (!group) return "";
      const compact = spec.canvas.profile === "azure-reference";
      const groupFontSize = compact ? REFERENCE_GROUP_FONT_SIZE : GROUP_FONT_SIZE;
      const groupLines = wrapText(
        group.label[locale],
        (shape.width - 36) / groupFontSize,
      );
      const presentation = group.presentation ?? "default";
      const radius = spec.canvas.profile === "azure-reference" ? 2 : 8;
      const accent = compact
        ? ""
        : `<line class="group-accent" x1="${shape.x + offsetX + 18}" y1="${shape.y + offsetY + 39}" x2="${shape.x + offsetX + 66}" y2="${shape.y + offsetY + 39}" aria-hidden="true"/>`;
      const itemCount = spec.nodes.filter((node) => node.parent === group.id).length;
      const kanbanChrome = spec.kind === "kanban"
        ? `<line class="kanban-header-divider" x1="${shape.x + offsetX + 14}" y1="${shape.y + offsetY + 42}" x2="${shape.x + offsetX + shape.width - 14}" y2="${shape.y + offsetY + 42}" aria-hidden="true"/><g class="kanban-count" transform="translate(${shape.x + offsetX + shape.width - 22} ${shape.y + offsetY + 20})" aria-hidden="true"><circle r="10"/><text y="4">${itemCount}</text></g>`
        : "";
      return `<g class="diagram-group group-${group.kind}" data-group-id="${group.id}" data-depth="${shape.depth}" data-presentation="${presentation}" role="group" aria-label="${escapeXml(group.label[locale])}"><rect class="group-surface" x="${shape.x + offsetX}" y="${shape.y + offsetY}" width="${shape.width}" height="${shape.height}" rx="${radius}"/><rect class="group-header" x="${shape.x + offsetX + 1}" y="${shape.y + offsetY + 1}" width="${Math.max(0, shape.width - 2)}" height="38" rx="${radius}"/>${accent}${kanbanChrome}${textLines(groupLines, shape.x + offsetX + 18, shape.y + offsetY + 27, "group-label", compact ? 16 : 21, "start")}</g>`;
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
          spec.kind,
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
        return renderNode(
          node,
          shape,
          locale,
          offsetX,
          offsetY,
          spec.canvas.profile === "azure-reference",
        );
      }),
    )
  ).join("");
  const standaloneDarkThemeSelector =
    spec.canvas.profile === "azure-reference"
      ? 'svg[data-diagram-id]:not([data-embedded]):not([data-profile="azure-reference"])'
      : "svg[data-diagram-id]:not([data-embedded])";

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="diagram-title diagram-description" data-diagram-id="${spec.id}" data-kind="${spec.kind}" data-locale="${locale}" data-profile="${spec.canvas.profile ?? "default"}">
  <title id="diagram-title">${escapeXml(spec.locales[locale].title)}</title>
  <desc id="diagram-description">${escapeXml(spec.locales[locale].alt)}</desc>
  <metadata>${escapeXml(JSON.stringify({ id: spec.id, version: spec.version, updated: spec.updated }))}</metadata>
  <defs>${markers}<filter id="node-shadow" x="-25%" y="-30%" width="150%" height="170%"><feDropShadow dx="0" dy="1" stdDeviation="1.5" flood-color="var(--fdai-diagram-shadow, #17212b)" flood-opacity="0.10"/><feDropShadow dx="0" dy="7" stdDeviation="10" flood-color="var(--fdai-diagram-shadow, #17212b)" flood-opacity="0.07"/></filter><filter id="group-shadow" x="-10%" y="-15%" width="120%" height="135%"><feDropShadow dx="0" dy="5" stdDeviation="12" flood-color="var(--fdai-diagram-shadow, #17212b)" flood-opacity="0.045"/></filter><filter id="label-shadow" x="-20%" y="-40%" width="140%" height="180%"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-color="var(--fdai-diagram-shadow, #17212b)" flood-opacity="0.08"/></filter></defs>
  <style>
    svg[data-diagram-id] { color: var(--fdai-diagram-text, #323130); font-family: "Noto Sans KR", "Noto Sans", "Segoe UI", sans-serif; }
    @media (prefers-color-scheme: dark) {
      ${standaloneDarkThemeSelector} {
        --fdai-diagram-canvas: #111315; --fdai-diagram-surface: #1b1f23; --fdai-diagram-node: #20252a; --fdai-diagram-label-surface: #1b1f23; --fdai-diagram-text: #f3f5f7; --fdai-diagram-muted: #c5cbd2; --fdai-diagram-border: #69737d; --fdai-diagram-border-strong: #aab2bb; --fdai-diagram-neutral-header: #30363d; --fdai-diagram-control-surface: #10283d; --fdai-diagram-control-header: #153d5c; --fdai-diagram-delivery-surface: #102d32; --fdai-diagram-delivery-header: #134148; --fdai-diagram-azure: #63d9ff; --fdai-diagram-azure-dark: #8bc8ff; --fdai-diagram-cyan-dark: #63d9ff;
        --fdai-diagram-tone-input-fill: #10243a; --fdai-diagram-tone-input-stroke: #6cb8ff; --fdai-diagram-tone-interpretation-fill: #102a3a; --fdai-diagram-tone-interpretation-stroke: #50c8ff; --fdai-diagram-tone-model-fill: #0e2d28; --fdai-diagram-tone-model-stroke: #5ee0bd; --fdai-diagram-tone-policy-fill: #17331d; --fdai-diagram-tone-policy-stroke: #73d17c; --fdai-diagram-tone-decision-fill: #3a2a0b; --fdai-diagram-tone-decision-stroke: #f3c969; --fdai-diagram-tone-execution-fill: #2b2040; --fdai-diagram-tone-execution-stroke: #c7a0ff; --fdai-diagram-tone-feedback-fill: #261f42; --fdai-diagram-tone-feedback-stroke: #b9a1ff; --fdai-diagram-tone-store-fill: #25292e; --fdai-diagram-tone-store-stroke: #b8c2cc; --fdai-diagram-tone-neutral-fill: #20252a; --fdai-diagram-tone-neutral-stroke: #b8c2cc;
        --fdai-diagram-edge-request: #6cb8ff; --fdai-diagram-edge-event: #50c8ff; --fdai-diagram-edge-approval: #c7a0ff; --fdai-diagram-edge-mutation: #ff9d72; --fdai-diagram-edge-audit: #73d17c; --fdai-diagram-edge-rollback: #ff8b91; --fdai-diagram-edge-read: #5ee0bd; --fdai-diagram-edge-write: #d6a8ff; --fdai-diagram-edge-feedback: #b9a1ff; --fdai-diagram-edge-sequence: #6cb8ff; --fdai-diagram-edge-transition: #c7a0ff; --fdai-diagram-edge-association: #c5cbd2; --fdai-diagram-edge-dependency: #aab2bb; --fdai-diagram-edge-timeline: #f3c969;
        --fdai-diagram-group-lane-fill: #1b1f23; --fdai-diagram-group-lane-stroke: #7890a8; --fdai-diagram-group-sidebar-fill: #25203a; --fdai-diagram-group-sidebar-stroke: #b9a1ff; --fdai-diagram-group-feedback-fill: #211d35; --fdai-diagram-group-feedback-stroke: #b9a1ff; --fdai-diagram-group-datastore-fill: #20252a; --fdai-diagram-group-datastore-stroke: #aab2bb; --fdai-diagram-badge-fill: #6cb8ff; --fdai-diagram-badge-text: #07131f; --fdai-diagram-gantt-planned: #313840; --fdai-diagram-gantt-planned-stroke: #aab2bb; --fdai-diagram-gantt-planned-text: #f3f5f7; --fdai-diagram-gantt-active: #237bc2; --fdai-diagram-gantt-active-stroke: #8bc8ff; --fdai-diagram-gantt-done: #267a35; --fdai-diagram-gantt-done-stroke: #73d17c; --fdai-diagram-gantt-critical: #b94a2f; --fdai-diagram-gantt-critical-stroke: #ff9d72; --fdai-diagram-gantt-milestone: #7655bd; --fdai-diagram-gantt-milestone-stroke: #c7a0ff; --fdai-diagram-gantt-progress: #ffffff; --fdai-diagram-gantt-text: #ffffff; --fdai-diagram-chart-surface: #1b1f23; --fdai-diagram-chart-1: #6cb8ff; --fdai-diagram-chart-2: #5ee0bd; --fdai-diagram-chart-3: #c7a0ff; --fdai-diagram-chart-4: #ff9d72; --fdai-diagram-chart-5: #f3c969; --fdai-diagram-chart-6: #ff8b91; --fdai-diagram-chart-7: #50c8ff; --fdai-diagram-chart-8: #d6a8ff; --fdai-diagram-pie-text: #07131f;
      }
    }
    .diagram-title { font-size: 26px; font-weight: 700; fill: var(--fdai-diagram-text, #323130); }
    .diagram-subtitle { font-size: 15px; fill: var(--fdai-diagram-muted, #605e5c); }
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
    .node-progress { fill: var(--fdai-diagram-gantt-progress, #ffffff); fill-opacity: 0.2; pointer-events: none; }
    .node-badge { filter: url(#label-shadow); }
    .node-badge circle { fill: var(--fdai-diagram-badge-fill, #173b6c); stroke: var(--fdai-diagram-badge-ring, #ffffff); stroke-width: 2.5; }
    .node-badge text { fill: var(--fdai-diagram-badge-text, #ffffff); font-size: 12px; font-weight: 700; text-anchor: middle; }
    ${Object.entries(toneStyles).map(([tone, style]) => `.diagram-node[data-tone="${tone}"] > .node-surface { fill: ${style.fill}; stroke: ${style.stroke}; }`).join("\n    ")}
    .node-inset { fill: none; stroke: var(--fdai-diagram-surface, #ffffff); stroke-opacity: 0.72; stroke-width: 1; pointer-events: none; }
    .node-divider { stroke: var(--fdai-diagram-border, #d7dbde); stroke-width: 1; stroke-opacity: 0.72; }
    .node-icon-backplate { fill: var(--fdai-diagram-surface, #ffffff); stroke-width: 1.25; stroke-opacity: 0.34; }
    ${Object.entries(toneStyles).map(([tone, style]) => `.diagram-node[data-tone="${tone}"] > .node-icon-backplate { stroke: ${style.stroke}; }`).join("\n    ")}
    .diagram-node[data-shape="bar"] > .node-surface { fill: var(--fdai-diagram-gantt-planned, #e8edf2); stroke: var(--fdai-diagram-gantt-planned-stroke, #667085); filter: none; }
    .diagram-node[data-shape="bar"] .node-label { fill: var(--fdai-diagram-gantt-planned-text, #323130); font-size: 14px; }
    .diagram-node[data-shape="bar"][data-status="active"] > .node-surface { fill: var(--fdai-diagram-gantt-active, #0f6cbd); stroke: var(--fdai-diagram-gantt-active-stroke, #005a9e); }
    .diagram-node[data-shape="bar"][data-status="done"] > .node-surface { fill: var(--fdai-diagram-gantt-done, #107c10); stroke: var(--fdai-diagram-gantt-done-stroke, #0b5c0b); }
    .diagram-node[data-shape="bar"][data-status="critical"] > .node-surface { fill: var(--fdai-diagram-gantt-critical, #c43501); stroke: var(--fdai-diagram-gantt-critical-stroke, #8f2600); }
    .diagram-node[data-shape="bar"][data-status="milestone"] > .node-surface { fill: var(--fdai-diagram-gantt-milestone, #6b46c1); stroke: var(--fdai-diagram-gantt-milestone-stroke, #51349a); }
    .diagram-node[data-shape="bar"][data-status="active"] .node-label,
    .diagram-node[data-shape="bar"][data-status="done"] .node-label,
    .diagram-node[data-shape="bar"][data-status="critical"] .node-label,
    .diagram-node[data-shape="bar"][data-status="milestone"] .node-label { fill: var(--fdai-diagram-gantt-text, #ffffff); }
    .diagram-node[data-shape="pie-slice"] > .node-surface { filter: none; stroke: var(--fdai-diagram-surface, #ffffff); stroke-width: 2; }
    .diagram-node[data-shape="pie-slice"] .node-label { fill: var(--fdai-diagram-pie-text, #ffffff); font-size: 14px; }
    .diagram-node[data-shape="pie-slice"][data-palette-index="0"] > .node-surface { fill: var(--fdai-diagram-chart-1, #0f6cbd); }
    .diagram-node[data-shape="pie-slice"][data-palette-index="1"] > .node-surface { fill: var(--fdai-diagram-chart-2, #008272); }
    .diagram-node[data-shape="pie-slice"][data-palette-index="2"] > .node-surface { fill: var(--fdai-diagram-chart-3, #6b46c1); }
    .diagram-node[data-shape="pie-slice"][data-palette-index="3"] > .node-surface { fill: var(--fdai-diagram-chart-4, #c43501); }
    .diagram-node[data-shape="pie-slice"][data-palette-index="4"] > .node-surface { fill: var(--fdai-diagram-chart-5, #9a6500); }
    .diagram-node[data-shape="pie-slice"][data-palette-index="5"] > .node-surface { fill: var(--fdai-diagram-chart-6, #a4262c); }
    .diagram-node[data-shape="pie-slice"][data-palette-index="6"] > .node-surface { fill: var(--fdai-diagram-chart-7, #187ea8); }
    .diagram-node[data-shape="pie-slice"][data-palette-index="7"] > .node-surface { fill: var(--fdai-diagram-chart-8, #5c2d91); }
    svg[data-kind="venn"] .diagram-node > .node-surface { fill-opacity: 0.34; }
    svg[data-kind="venn"] .diagram-node[data-palette-index="0"] > .node-surface { fill: var(--fdai-diagram-chart-1, #0f6cbd); stroke: var(--fdai-diagram-chart-1, #0f6cbd); }
    svg[data-kind="venn"] .diagram-node[data-palette-index="1"] > .node-surface { fill: var(--fdai-diagram-chart-2, #008272); stroke: var(--fdai-diagram-chart-2, #008272); }
    svg[data-kind="venn"] .diagram-node[data-palette-index="2"] > .node-surface { fill: var(--fdai-diagram-chart-3, #6b46c1); stroke: var(--fdai-diagram-chart-3, #6b46c1); }
    .chart-frame { fill: var(--fdai-diagram-chart-surface, #ffffff); stroke: var(--fdai-diagram-border-strong, #605e5c); stroke-width: 1; }
    .chart-guide { stroke: var(--fdai-diagram-border, #a19f9d); stroke-width: 1; stroke-dasharray: 5 5; opacity: 0.72; }
    .chart-guide-ring { fill: none; stroke: var(--fdai-diagram-border, #a19f9d); stroke-width: 1; stroke-dasharray: 4 6; opacity: 0.76; }
    .chart-axis-label { fill: var(--fdai-diagram-muted, #605e5c); font-size: 14px; font-weight: 600; }
    .edge-hit { fill: none; stroke: transparent; stroke-width: 14; pointer-events: stroke; cursor: pointer; }
    .edge-path { pointer-events: stroke; transition: stroke-width 140ms ease, opacity 140ms ease; }
    .diagram-edge[data-edge-route="orthogonal-above"][data-edge-step] > .edge-path { opacity: 0.52; stroke-width: 2; }
    .edge-label { cursor: pointer; }
    .edge-label rect { fill: var(--fdai-diagram-label-surface, #ffffff); stroke: var(--fdai-diagram-border, #a19f9d); transition: fill 140ms ease, stroke 140ms ease, stroke-width 140ms ease; }
    .edge-label-text, .legend-item text { font-size: ${EDGE_FONT_SIZE}px; font-weight: 600; fill: var(--fdai-diagram-muted, #605e5c); }
    .edge-label-text { transition: fill 140ms ease; }
    .diagram-edge.is-muted { opacity: 0.12; }
    .diagram-edge.is-muted:hover { opacity: 1; }
    svg:not([data-kind="sankey"]) .diagram-edge.is-active > .edge-path,
    svg:not([data-kind="sankey"]) .diagram-edge:hover > .edge-path { stroke-width: 4; opacity: 1; }
    .diagram-edge:hover .edge-label rect { fill: var(--fdai-diagram-control-header, #deecf9); stroke: var(--fdai-diagram-azure-dark, #005a9e); stroke-width: 2; }
    .diagram-edge:hover .edge-label-text { fill: var(--fdai-diagram-text, #323130); font-weight: 700; }
    .edge-step circle { fill: #107c10; stroke: #ffffff; stroke-width: 2; }
    .edge-step text { fill: #ffffff; font-size: 12px; font-weight: 700; text-anchor: middle; }
    svg[data-profile="conceptual"] .diagram-group .group-surface { stroke-dasharray: none; }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="lane"] .group-surface { fill: var(--fdai-diagram-group-lane-fill, #ffffff); stroke: var(--fdai-diagram-group-lane-stroke, #9fb3c8); }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="sidebar"] .group-surface { fill: var(--fdai-diagram-group-sidebar-fill, #f7f5ff); stroke: var(--fdai-diagram-group-sidebar-stroke, #7c5ce7); }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="feedback"] .group-surface { fill: var(--fdai-diagram-group-feedback-fill, #faf8ff); stroke: var(--fdai-diagram-group-feedback-stroke, #6045df); }
    svg[data-profile="conceptual"] .diagram-group[data-presentation="datastore"] .group-surface { fill: var(--fdai-diagram-group-datastore-fill, #f7f8fa); stroke: var(--fdai-diagram-group-datastore-stroke, #6b7280); }
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
    svg[data-profile="azure-reference"] .group-label { fill: #3b3a39; font-size: ${REFERENCE_GROUP_FONT_SIZE}px; font-weight: 650; }
    svg[data-profile="azure-reference"] .node-label { font-size: 13px; font-weight: 650; fill: #323130; }
    svg[data-profile="azure-reference"] .node-body { font-size: ${REFERENCE_NODE_BODY_FONT_SIZE}px; }
    svg[data-profile="azure-reference"] .edge-label-text,
    svg[data-profile="azure-reference"] .legend-item text { fill: #484644; font-size: ${REFERENCE_EDGE_FONT_SIZE}px; font-weight: 650; }
    ${standaloneThemeCss(spec.canvas.profile === "azure-reference")}
    ${calmSlateFoundationCss()}
  </style>
  <rect class="diagram-background" width="${width}" height="${height}" fill="${spec.canvas.profile === "azure-reference" ? "#ffffff" : "var(--fdai-diagram-canvas, #faf9f8)"}"/>
  <text class="diagram-title" x="48" y="45">${escapeXml(spec.locales[locale].title)}</text>
  <text class="diagram-subtitle" x="48" y="72">${escapeXml(spec.locales[locale].description)}</text>
  <g data-diagram-viewport="">${renderChartBackdrop(spec, layout, locale, offsetX, offsetY)}${groups}${edges}${nodes}${renderLegend(spec, locale, height - 30)}</g>
</svg>`;
}
