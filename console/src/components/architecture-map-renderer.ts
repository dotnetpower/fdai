import {
  LIFT,
  cameraWorldSize,
  circlePoints,
  clamp,
  convexHull,
  footprintPoints,
  project,
  rectangle,
  slabTiers,
  type Camera,
  type Point,
} from "./architecture-map.geometry";
import { architectureResourceAbbreviation } from "./architecture-resource-abbreviations";
import { isArchitectureNetworkPlane } from "./architecture-network-layout";
import { architectureNetworkPathRank } from "./architecture-network-path";
import {
  drawArchitectureAttachmentRoute,
  drawArchitectureNetworkMemberships,
  drawArchitectureNetworkPathSpines,
  drawArchitectureNetworkPlanes,
} from "./architecture-network-renderer";
import {
  geometryOf,
  isRegion,
  RESOURCE_COLOR_TOKENS,
  resourceColorOf,
  resourceColorTokenOf,
  resourceTypeLabelOf,
  shapeOf,
  DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS,
  type ArchitectureDisplayOptions,
  type ArchitectureNodeGeometry,
  type ArchitectureResourceColorToken,
  type InventoryGraphResponse,
  type InventoryLink,
  type InventoryResource,
} from "./architecture-map.model";

type CanvasPaint = string | CanvasGradient | CanvasPattern;

interface LabelBounds {
  readonly left: number;
  readonly right: number;
  readonly top: number;
  readonly bottom: number;
}

export interface ArchitectureMapPalette {
  readonly background: string;
  readonly surface: string;
  readonly surfaceBorder: string;
  readonly labelBackground: string;
  readonly selectedLabelBackground: string;
  readonly labelText: string;
  readonly selectedLabelText: string;
}

export const DEFAULT_ARCHITECTURE_MAP_PALETTE: ArchitectureMapPalette = {
  background: "#eef2f4",
  surface: "#fbfcfd",
  surfaceBorder: "#aeb9c3",
  labelBackground: "rgba(255,255,255,.94)",
  selectedLabelBackground: "rgba(239,249,248,.97)",
  labelText: "#263543",
  selectedLabelText: "#102f36",
};

export function architectureLabelFontSize(cameraScale: number, selected = false): number {
  const minimum = selected ? 15 : 13;
  const growth = selected ? .16 : .14;
  return clamp(minimum + Math.max(0, cameraScale - 22) * growth, minimum, selected ? 22 : 20);
}

export function architectureGlyphFontSize(cameraScale: number, abbreviation: string): number {
  const base = clamp(10 + Math.max(0, cameraScale - 22) * .12, 10, 16);
  return Math.max(7, base * Math.min(1, 3.4 / abbreviation.length));
}

export function architectureFloorLegendFontSize(cameraScale: number): number {
  return clamp(13 + Math.max(0, cameraScale - 18) * .22, 13, 22);
}

export function architectureFloorLegendEntries(
  resources: readonly InventoryResource[],
): readonly ArchitectureResourceColorToken[] {
  return [...new Set(resources.map(resourceColorTokenOf))]
    .sort((first, second) =>
      RESOURCE_COLOR_TOKENS[first].label.localeCompare(RESOURCE_COLOR_TOKENS[second].label));
}

export function fitArchitectureLabel(
  text: string,
  maximumWidth: number,
  measure: (value: string) => number,
): string {
  if (measure(text) <= maximumWidth) return text;
  const suffix = "...";
  let low = 0;
  let high = text.length;
  while (low < high) {
    const middle = Math.ceil((low + high) / 2);
    if (measure(`${text.slice(0, middle)}${suffix}`) <= maximumWidth) low = middle;
    else high = middle - 1;
  }
  return `${text.slice(0, low)}${suffix}`;
}

export function renderMap(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  graph: InventoryGraphResponse,
  selectedId: string | null,
  highlightedIds?: ReadonlySet<string>,
  options: ArchitectureDisplayOptions = DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS,
  palette: ArchitectureMapPalette = DEFAULT_ARCHITECTURE_MAP_PALETTE,
): void {
  const showLabels = options.showLabels;
  context.clearRect(0, 0, width, height);
  context.fillStyle = palette.background;
  context.fillRect(0, 0, width, height);
  const world = cameraWorldSize(camera);
  const plate = rectangle(camera, width, height, 0, 0, world.width, world.height, 0);
  fillPolygon(context, plate, palette.surface, palette.surfaceBorder);
  if (options.showGrid) drawGrid(context, width, height, camera);

  const regions = graph.resources.filter(isRegion).sort((first, second) =>
    (second.w ?? 0) * (second.h ?? 0) - (first.w ?? 0) * (first.h ?? 0));
  for (const region of regions.filter((resource) => !isArchitectureNetworkPlane(resource))) {
    const color = resourceColorOf(region);
    const points = rectangle(camera, width, height, region.x ?? 0, region.y ?? 0, region.w ?? 0, region.h ?? 0, .01);
    context.save();
    context.globalAlpha = region.type === "subscription" ? .12 : .2;
    fillPolygon(context, points, color, selectedId === region.id ? "#0f6670" : color, selectedId === region.id ? 2.5 : 1.1);
    context.restore();
  }
  drawArchitectureNetworkPlanes(
    context,
    width,
    height,
    camera,
    regions.filter(isArchitectureNetworkPlane),
    selectedId,
    palette,
  );
  drawArchitectureNetworkMemberships(context, width, height, camera, graph, highlightedIds);
  drawArchitectureNetworkPathSpines(context, width, height, camera, graph, highlightedIds);

  const nodes = graph.resources.filter((resource) => !isRegion(resource));
  if (options.showReflections) drawReflections(context, width, height, camera, nodes, highlightedIds);
  const ordered = [...nodes].sort((first, second) =>
    project(camera, width, height, second.x ?? 0, second.y ?? 0).depth -
    project(camera, width, height, first.x ?? 0, first.y ?? 0).depth);
  if (options.showConnections) {
    drawLinks(context, width, height, camera, graph, highlightedIds, "containment");
    drawLinks(context, width, height, camera, graph, highlightedIds, "attachment");
  }
  for (const node of ordered) drawNodeBody(context, width, height, camera, node, selectedId, highlightedIds);
  if (options.showConnections) {
    drawLinks(context, width, height, camera, graph, highlightedIds, "dependency");
  }
  const labelBounds = ordered.map((node) => nodeLabelObstacle(camera, width, height, node));
  const overlayOrder = architectureOverlayOrder(ordered, selectedId);
  for (const node of overlayOrder) {
    drawNodeOverlay(
      context,
      width,
      height,
      camera,
      node,
      node.id === selectedId,
      highlightedIds,
      showLabels,
      labelBounds,
      palette,
    );
  }
  if (showLabels) {
    for (const region of regions.filter((resource) => !isArchitectureNetworkPlane(resource))) {
      drawLabel(
        context,
        project(camera, width, height, (region.x ?? 0) + .2, (region.y ?? 0) + .2, .02),
        region.name,
        resourceColorOf(region),
        architectureLabelFontSize(camera.scale) * .88,
        labelBounds,
        false,
        palette,
        architectureResourceAbbreviation(region.type),
      );
    }
  }
  drawFloorLegend(context, width, height, camera, graph.resources, palette);
}

export function architectureOverlayOrder(
  nodes: readonly InventoryResource[],
  selectedId: string | null,
): InventoryResource[] {
  return [...nodes].sort((first, second) =>
    Number(first.id === selectedId) - Number(second.id === selectedId));
}

function drawGrid(context: CanvasRenderingContext2D, width: number, height: number, camera: Camera): void {
  const world = cameraWorldSize(camera);
  context.save();
  context.fillStyle = "rgba(68,86,101,.18)";
  for (let x = 1; x < world.width; x += 1) {
    for (let y = 1; y < world.height; y += 1) {
      const point = project(camera, width, height, x, y, .003);
      context.beginPath();
      context.arc(point.x, point.y, .7, 0, Math.PI * 2);
      context.fill();
    }
  }
  context.restore();
}

function drawFloorLegend(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  resources: readonly InventoryResource[],
  palette: ArchitectureMapPalette,
): void {
  const entries = architectureFloorLegendEntries(resources);
  if (entries.length === 0) return;
  const world = cameraWorldSize(camera);
  const plate = rectangle(camera, width, height, 0, 0, world.width, world.height, 0);
  const rightCorner = plate.reduce((rightmost, point) => point.x > rightmost.x ? point : rightmost);
  const fontSize = width >= 700
    ? architectureFloorLegendFontSize(camera.scale)
    : Math.min(10, architectureFloorLegendFontSize(camera.scale));
  const rowHeight = fontSize * 1.45;
  const availableWidth = Math.max(80, width - rightCorner.x - fontSize * 2.4);
  const columns = width >= 700 && availableWidth >= 280 ? 2 : 1;
  const rows = Math.ceil(entries.length / columns);
  const columnWidth = availableWidth / columns;
  const originX = rightCorner.x + fontSize * 1.6;
  const originY = rightCorner.y + fontSize * 1.8;

  context.save();
  context.textAlign = "left";
  context.textBaseline = "middle";
  context.font = `650 ${fontSize}px Aptos, Segoe UI, sans-serif`;
  for (const [index, token] of entries.entries()) {
    const column = Math.floor(index / rows);
    const row = index % rows;
    const x = originX + column * columnWidth;
    const y = originY + row * rowHeight;
    const label = fitArchitectureLabel(
      RESOURCE_COLOR_TOKENS[token].label,
      columnWidth - fontSize,
      (value) => context.measureText(value).width,
    );
    context.fillStyle = darken(RESOURCE_COLOR_TOKENS[token].color, .72);
    context.fillText(label, x, y);
  }
  context.restore();
}

function drawReflections(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  nodes: readonly InventoryResource[],
  highlightedIds?: ReadonlySet<string>,
): void {
  for (const node of nodes) {
    const nodeX = node.x ?? 0;
    const nodeY = node.y ?? 0;
    const color = resourceColorOf(node);
    const shape = shapeOf(node);
    const geometry = geometryOf(node);
    if (shape === "lane") continue;
    if (shape === "cylinder") {
      drawCylinderReflection(
        context,
        width,
        height,
        camera,
        nodeX,
        nodeY,
        color,
        highlightAlpha(node.id, highlightedIds),
        geometry,
      );
      continue;
    }
    if (shape === "slab") {
      drawSlabReflection(
        context, width, height, camera, nodeX, nodeY, color,
        highlightAlpha(node.id, highlightedIds), geometry,
      );
      drawContactGlow(
        context, width, height, camera, nodeX, nodeY, color,
        highlightAlpha(node.id, highlightedIds), geometry,
      );
      continue;
    }
    const mirrorBase = footprintPoints(camera, width, height, nodeX, nodeY, shape, geometry, -LIFT);
    const mirrorTop = footprintPoints(
      camera, width, height, nodeX, nodeY, shape, geometry, -(LIFT + geometry.height),
    );
    const alpha = highlightAlpha(node.id, highlightedIds);
    context.save();
    context.globalAlpha = alpha;
    context.filter = "blur(.8px)";
    for (let index = 0; index < mirrorBase.length; index += 1) {
      const next = (index + 1) % mirrorBase.length;
      const face = [mirrorBase[index]!, mirrorBase[next]!, mirrorTop[next]!, mirrorTop[index]!];
      const fade = context.createLinearGradient(
        mirrorBase[index]!.x,
        mirrorBase[index]!.y,
        mirrorTop[index]!.x,
        mirrorTop[index]!.y,
      );
      fade.addColorStop(0, rgba(color, .28));
      fade.addColorStop(.5, rgba(color, .12));
      fade.addColorStop(1, rgba(color, 0));
      fillPolygon(context, face, fade, rgba(color, 0), 0);
    }
    fillPolygon(context, mirrorTop, rgba(color, .035), rgba(color, 0), 0);
    context.restore();

    drawContactGlow(context, width, height, camera, nodeX, nodeY, color, alpha, geometry);
  }
}

function drawContactGlow(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  x: number,
  y: number,
  color: string,
  alpha: number,
  geometry: ArchitectureNodeGeometry,
): void {
  const point = project(camera, width, height, x, y, .004);
  const radius = camera.scale * Math.max(geometry.width, geometry.depth) * .43;
  context.save();
  context.globalAlpha = alpha * .24;
  context.translate(point.x, point.y + 2);
  context.scale(1, .35);
  const glow = context.createRadialGradient(0, 0, 0, 0, 0, radius);
  glow.addColorStop(0, color);
  glow.addColorStop(1, rgba(color, 0));
  context.fillStyle = glow;
  context.beginPath();
  context.arc(0, 0, radius, 0, Math.PI * 2);
  context.fill();
  context.restore();
}

function drawLinks(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  graph: InventoryGraphResponse,
  highlightedIds?: ReadonlySet<string>,
  pass: "containment" | "attachment" | "dependency" = "dependency",
): void {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  for (const link of graph.links) {
    const source = byId.get(link.source);
    const target = byId.get(link.target);
    if (!source || !target || !architectureLinkIsDrawable(source, target, link)) continue;
    if (
      (pass === "containment" && link.type !== "contains")
      || (pass === "attachment" && link.type !== "attached_to")
      || (pass === "dependency" && link.type !== "depends_on")
    ) continue;
    if (link.type === "contains") {
      const start = project(
        camera, width, height,
        (source.x ?? 0) + (source.w ?? 0) / 2,
        (source.y ?? 0) + (source.h ?? 0) / 2,
        .025,
      );
      const end = project(
        camera, width, height,
        (target.x ?? 0) + (target.w ?? 0) / 2,
        (target.y ?? 0) + (target.h ?? 0) / 2,
        .025,
      );
      const edgeActive = !highlightedIds || (
        highlightedIds.has(source.id) && highlightedIds.has(target.id)
      );
      context.save();
      context.globalAlpha = edgeActive ? .3 : .06;
      context.strokeStyle = "#6f7f89";
      context.lineWidth = 1.1;
      context.setLineDash([3, 4]);
      context.beginPath();
      context.moveTo(start.x, start.y);
      context.lineTo(end.x, end.y);
      context.stroke();
      context.restore();
      continue;
    }
    const edgeActive = !highlightedIds || (
      highlightedIds.has(source.id) && highlightedIds.has(target.id)
    );
    if (link.type === "attached_to") {
      drawArchitectureAttachmentRoute(
        context,
        width,
        height,
        camera,
        source,
        target,
        edgeActive,
      );
      continue;
    }
    const start = project(
      camera, width, height, source.x ?? 0, source.y ?? 0,
      architectureLinkElevation(source),
    );
    const end = project(
      camera, width, height, target.x ?? 0, target.y ?? 0,
      architectureLinkElevation(target),
    );
    context.save();
    context.globalAlpha = edgeActive ? .72 : .1;
    context.strokeStyle = "#426f87";
    context.lineWidth = 1.7;
    context.setLineDash([]);
    const bend = Math.min(28, Math.abs(end.x - start.x) * .12 + 8);
    context.beginPath();
    context.moveTo(start.x, start.y);
    context.bezierCurveTo(start.x, start.y - bend, end.x, end.y - bend, end.x, end.y);
    context.strokeStyle = "rgba(255,255,255,.88)";
    context.lineWidth = 4.2;
    context.stroke();
    context.beginPath();
    context.moveTo(start.x, start.y);
    context.bezierCurveTo(start.x, start.y - bend, end.x, end.y - bend, end.x, end.y);
    context.strokeStyle = "#426f87";
    context.lineWidth = 1.7;
    context.stroke();
    drawArrowHead(context, start, end, "#426f87");
    context.restore();
  }
}

export function architectureLinkElevation(resource: InventoryResource): number {
  return LIFT + geometryOf(resource).height + .16;
}

export function architectureLinkIsDrawable(
  source: InventoryResource,
  target: InventoryResource,
  link: InventoryLink,
): boolean {
  if (link.type === "contains") {
    return !(isArchitectureNetworkPlane(source) && isArchitectureNetworkPlane(target));
  }
  if (link.type === "attached_to") {
    if (
      source.network_plane_id
      && source.network_plane_id === target.network_plane_id
    ) return false;
    if (
      source.network_plane_id === target.id
      || target.network_plane_id === source.id
    ) return false;
    return (!isRegion(source) || isArchitectureNetworkPlane(source))
      && (!isRegion(target) || isArchitectureNetworkPlane(target));
  }
  return !isRegion(source) && !isRegion(target);
}

function drawArrowHead(
  context: CanvasRenderingContext2D,
  start: Pick<Point, "x" | "y">,
  end: Pick<Point, "x" | "y">,
  color: string,
): void {
  const angle = Math.atan2(end.y - start.y, end.x - start.x);
  const size = 7;
  context.beginPath();
  context.moveTo(end.x, end.y);
  context.lineTo(
    end.x - Math.cos(angle - Math.PI / 6) * size,
    end.y - Math.sin(angle - Math.PI / 6) * size,
  );
  context.lineTo(
    end.x - Math.cos(angle + Math.PI / 6) * size,
    end.y - Math.sin(angle + Math.PI / 6) * size,
  );
  context.closePath();
  context.fillStyle = color;
  context.fill();
}

function drawNodeBody(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  node: InventoryResource,
  selectedId: string | null,
  highlightedIds?: ReadonlySet<string>,
): void {
  const nodeX = node.x ?? 0;
  const nodeY = node.y ?? 0;
  const color = resourceColorOf(node);
  const shape = shapeOf(node);
  const geometry = geometryOf(node);
  if (shape === "cylinder") {
    drawCylinderBody(
      context,
      width,
      height,
      camera,
      nodeX,
      nodeY,
      color,
      selectedId === node.id,
      highlightAlpha(node.id, highlightedIds),
      geometry,
    );
    return;
  }
  if (shape === "slab") {
    drawSlabBody(
      context, width, height, camera, nodeX, nodeY, color,
      selectedId === node.id, highlightAlpha(node.id, highlightedIds), geometry,
    );
    return;
  }
  const top = footprintPoints(
    camera, width, height, nodeX, nodeY, shape, geometry, LIFT + geometry.height,
  );
  const base = footprintPoints(camera, width, height, nodeX, nodeY, shape, geometry, LIFT);
  drawPrismBody(
    context, top, base, color, selectedId === node.id,
    highlightAlpha(node.id, highlightedIds),
  );
}

function drawPrismBody(
  context: CanvasRenderingContext2D,
  top: readonly Point[],
  base: readonly Point[],
  color: string,
  selected: boolean,
  alpha: number,
): void {
  context.save();
  context.globalAlpha = alpha;
  const faces = top.map((point, index) => {
    const next = (index + 1) % top.length;
    const points = [point, top[next]!, base[next]!, base[index]!];
    return {
      points,
      depth: points.reduce((total, current) => total + current.depth, 0) / points.length,
      index,
    };
  }).sort((first, second) => second.depth - first.depth);
  for (const face of faces) {
    fillPolygon(
      context,
      face.points,
      darken(color, face.index % 2 ? .72 : .57),
      "transparent",
      0,
    );
  }
  fillPolygon(
    context,
    top,
    color,
    selected ? "#102f36" : "transparent",
    selected ? 2.4 : 0,
  );
  context.restore();
}

function drawSlabReflection(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  x: number,
  y: number,
  color: string,
  alpha: number,
  geometry: ArchitectureNodeGeometry,
): void {
  drawPrismReflection(
    context,
    footprintPoints(camera, width, height, x, y, "slab", geometry, -LIFT),
    footprintPoints(camera, width, height, x, y, "slab", geometry, -(LIFT + geometry.height)),
    color,
    alpha,
  );
}

function drawPrismReflection(
  context: CanvasRenderingContext2D,
  mirrorBase: readonly Point[],
  mirrorTop: readonly Point[],
  color: string,
  alpha: number,
): void {
  context.save();
  context.globalAlpha = alpha;
  context.filter = "blur(.8px)";
  for (let index = 0; index < mirrorBase.length; index += 1) {
    const next = (index + 1) % mirrorBase.length;
    const face = [mirrorBase[index]!, mirrorBase[next]!, mirrorTop[next]!, mirrorTop[index]!];
    const fade = context.createLinearGradient(
      mirrorBase[index]!.x,
      mirrorBase[index]!.y,
      mirrorTop[index]!.x,
      mirrorTop[index]!.y,
    );
    fade.addColorStop(0, rgba(color, .28));
    fade.addColorStop(.5, rgba(color, .12));
    fade.addColorStop(1, rgba(color, 0));
    fillPolygon(context, face, fade, rgba(color, 0), 0);
  }
  fillPolygon(context, mirrorTop, rgba(color, .035), rgba(color, 0), 0);
  context.restore();
}

function drawSlabBody(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  x: number,
  y: number,
  color: string,
  selected: boolean,
  alpha: number,
  geometry: ArchitectureNodeGeometry,
): void {
  const { lowerHeight, lowerGeometry, upperGeometry } = slabTiers(geometry);
  drawPrismBody(
    context,
    footprintPoints(camera, width, height, x, y, "slab", lowerGeometry, LIFT + lowerHeight),
    footprintPoints(camera, width, height, x, y, "slab", lowerGeometry, LIFT),
    darken(color, .86),
    false,
    alpha,
  );
  drawPrismBody(
    context,
    footprintPoints(camera, width, height, x, y, "slab", upperGeometry, LIFT + geometry.height),
    footprintPoints(camera, width, height, x, y, "slab", upperGeometry, LIFT + lowerHeight),
    color,
    selected,
    alpha,
  );
}

function drawCylinderBody(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  x: number,
  y: number,
  color: string,
  selected: boolean,
  alpha: number,
  geometry: ArchitectureNodeGeometry,
): void {
  const top = circlePoints(
    camera, width, height, x, y, geometry.width / 2, LIFT + geometry.height,
  );
  const base = circlePoints(camera, width, height, x, y, geometry.width / 2, LIFT);
  const bounds = [...top, ...base].reduce(
    (current, point) => ({
      minX: Math.min(current.minX, point.x),
      maxX: Math.max(current.maxX, point.x),
    }),
    { minX: Number.POSITIVE_INFINITY, maxX: Number.NEGATIVE_INFINITY },
  );
  const sideFill = context.createLinearGradient(bounds.minX, 0, bounds.maxX, 0);
  sideFill.addColorStop(0, darken(color, .52));
  sideFill.addColorStop(.48, darken(color, .76));
  sideFill.addColorStop(1, darken(color, .58));
  context.save();
  context.globalAlpha = alpha;
  fillPolygon(context, convexHull([...top, ...base]), sideFill, "transparent", 0);
  fillPolygon(context, top, color, selected ? "#102f36" : "transparent", selected ? 2.4 : 0);
  context.restore();
}

function drawCylinderReflection(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  x: number,
  y: number,
  color: string,
  alpha: number,
  geometry: ArchitectureNodeGeometry,
): void {
  const mirrorBase = circlePoints(camera, width, height, x, y, geometry.width / 2, -LIFT);
  const mirrorTop = circlePoints(
    camera, width, height, x, y, geometry.width / 2, -(LIFT + geometry.height),
  );
  context.save();
  context.globalAlpha = alpha;
  context.filter = "blur(.8px)";
  for (let index = 0; index < mirrorBase.length; index += 1) {
    const next = (index + 1) % mirrorBase.length;
    const face = [mirrorBase[index]!, mirrorBase[next]!, mirrorTop[next]!, mirrorTop[index]!];
    const fade = context.createLinearGradient(
      mirrorBase[index]!.x,
      mirrorBase[index]!.y,
      mirrorTop[index]!.x,
      mirrorTop[index]!.y,
    );
    fade.addColorStop(0, rgba(color, .3));
    fade.addColorStop(.5, rgba(color, .13));
    fade.addColorStop(1, rgba(color, 0));
    fillPolygon(context, face, fade, rgba(color, 0), 0);
  }
  fillPolygon(context, mirrorTop, rgba(color, .04), rgba(color, 0), 0);
  context.restore();
}

function drawNodeOverlay(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  node: InventoryResource,
  selected: boolean,
  highlightedIds?: ReadonlySet<string>,
  showLabels = true,
  occupiedLabels: LabelBounds[] = [],
  palette: ArchitectureMapPalette = DEFAULT_ARCHITECTURE_MAP_PALETTE,
): void {
  const nodeX = node.x ?? 0;
  const nodeY = node.y ?? 0;
  const geometry = geometryOf(node);
  context.save();
  context.globalAlpha = highlightAlpha(node.id, highlightedIds);
  const center = project(camera, width, height, nodeX, nodeY, LIFT + geometry.height + .02);
  context.fillStyle = "#fff";
  const glyph = architectureResourceAbbreviation(node.type);
  const glyphSize = architectureGlyphFontSize(camera.scale, glyph);
  context.font = `800 ${glyphSize}px Aptos, Segoe UI, sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.strokeStyle = "rgba(28,39,51,.38)";
  context.lineWidth = 2.4;
  context.strokeText(glyph, center.x, center.y);
  context.fillText(glyph, center.x, center.y);
  if ((node.collapsed_count ?? 0) > 0) {
    const badge = project(
      camera,
      width,
      height,
      nodeX + geometry.width / 2,
      nodeY - geometry.depth / 2,
      LIFT + geometry.height + .06,
    );
    const label = `+${node.collapsed_count}`;
    context.font = "700 10px Aptos, Segoe UI, sans-serif";
    const badgeWidth = Math.max(22, context.measureText(label).width + 10);
    context.fillStyle = "rgba(25,45,58,.92)";
    context.beginPath();
    context.roundRect(badge.x - badgeWidth / 2, badge.y - 9, badgeWidth, 18, 9);
    context.fill();
    context.fillStyle = "#fff";
    context.fillText(label, badge.x, badge.y + .5);
  }
  if (showLabels && architectureNodeLabelIsVisible(node, selected, camera.scale)) {
    const fontSize = architectureLabelFontSize(camera.scale, selected);
    const labelPoint = project(camera, width, height, nodeX, nodeY, 0);
    drawLabel(
      context,
      {
        ...labelPoint,
        y: labelPoint.y + camera.scale * geometry.depth / 2 + fontSize / 2 + 14,
      },
      node.name,
      selected ? palette.selectedLabelText : palette.labelText,
      fontSize,
      occupiedLabels,
      selected,
      palette,
      selected ? resourceTypeLabelOf(node) : undefined,
    );
  }
  context.restore();
}

export function architectureNodeLabelIsVisible(
  node: InventoryResource,
  selected: boolean,
  cameraScale: number,
): boolean {
  if (selected) return true;
  if (cameraScale < 12) return false;
  return !node.network_plane_id || architectureNetworkPathRank(node) === 3;
}

function nodeLabelObstacle(
  camera: Camera,
  width: number,
  height: number,
  node: InventoryResource,
): LabelBounds {
  const geometry = geometryOf(node);
  const center = project(
    camera,
    width,
    height,
    node.x ?? 0,
    node.y ?? 0,
    LIFT + geometry.height / 2,
  );
  const halfWidth = camera.scale * geometry.width / 2 + 5;
  const halfHeight = camera.scale * geometry.depth / 2 + 5;
  return {
    left: center.x - halfWidth,
    right: center.x + halfWidth,
    top: center.y - halfHeight,
    bottom: center.y + halfHeight,
  };
}

function fillPolygon(
  context: CanvasRenderingContext2D,
  points: readonly Point[],
  fill: CanvasPaint,
  stroke: CanvasPaint = fill,
  lineWidth = 1,
): void {
  const first = points[0];
  if (!first) return;
  context.beginPath();
  context.moveTo(first.x, first.y);
  for (const point of points.slice(1)) context.lineTo(point.x, point.y);
  context.closePath();
  context.fillStyle = fill;
  context.fill();
  if (lineWidth > 0) {
    context.strokeStyle = stroke;
    context.lineWidth = lineWidth;
    context.stroke();
  }
}

function drawLabel(
  context: CanvasRenderingContext2D,
  point: Pick<Point, "x" | "y">,
  text: string,
  color: string,
  size: number,
  occupiedLabels?: LabelBounds[],
  force = false,
  palette: ArchitectureMapPalette = DEFAULT_ARCHITECTURE_MAP_PALETTE,
  subtitle?: string,
): void {
  const subtitleSize = Math.max(10, size * .72);
  context.font = `600 ${size}px Aptos, Segoe UI, sans-serif`;
  const maximumTextWidth = Math.max(72, Math.min(320, context.canvas.clientWidth - 36));
  const fittedText = fitArchitectureLabel(
    text,
    maximumTextWidth,
    (value) => context.measureText(value).width,
  );
  const textWidth = context.measureText(fittedText).width;
  context.font = `600 ${subtitleSize}px Aptos, Segoe UI, sans-serif`;
  const subtitleWidth = subtitle ? context.measureText(subtitle).width : 0;
  const labelWidth = Math.max(textWidth, subtitleWidth) + 12;
  const labelHeight = size + (subtitle ? subtitleSize + 3 : 0) + 8;
  const labelX = clamp(
    point.x,
    labelWidth / 2 + 8,
    context.canvas.clientWidth - labelWidth / 2 - 8,
  );
  const labelY = force
    ? clamp(point.y, labelHeight / 2 + 8, context.canvas.clientHeight - labelHeight / 2 - 8)
    : point.y;
  const bounds = {
    left: labelX - labelWidth / 2,
    right: labelX + labelWidth / 2,
    top: labelY - labelHeight / 2,
    bottom: labelY + labelHeight / 2,
  };
  if (!force && (bounds.top < 8 || bounds.bottom > context.canvas.clientHeight - 8)) return;
  if (!force && occupiedLabels?.some((current) => labelsOverlap(current, bounds))) return;
  occupiedLabels?.push(bounds);
  context.fillStyle = force ? palette.selectedLabelBackground : palette.labelBackground;
  context.fillRect(bounds.left, bounds.top, labelWidth, labelHeight);
  if (force) {
    context.strokeStyle = "#2f7774";
    context.lineWidth = 1;
    context.strokeRect(bounds.left, bounds.top, labelWidth, labelHeight);
  }
  context.fillStyle = color;
  context.textAlign = "center";
  context.textBaseline = "middle";
  const nameY = subtitle ? labelY - subtitleSize / 2 - 1 : labelY;
  context.font = `600 ${size}px Aptos, Segoe UI, sans-serif`;
  context.fillText(fittedText, labelX, nameY);
  if (subtitle) {
    context.font = `600 ${subtitleSize}px Aptos, Segoe UI, sans-serif`;
    context.fillStyle = rgba(color, .72);
    context.fillText(subtitle, labelX, labelY + size / 2 + 1);
  }
}

function labelsOverlap(first: LabelBounds, second: LabelBounds): boolean {
  const gap = 4;
  return first.left < second.right + gap
    && first.right + gap > second.left
    && first.top < second.bottom + gap
    && first.bottom + gap > second.top;
}

function highlightAlpha(id: string, highlightedIds?: ReadonlySet<string>): number {
  if (!highlightedIds || highlightedIds.size === 0) return 1;
  return highlightedIds.has(id) ? 1 : .14;
}

function darken(color: string, factor: number): string {
  const value = Number.parseInt(color.slice(1), 16);
  const red = Math.round(((value >> 16) & 255) * factor);
  const green = Math.round(((value >> 8) & 255) * factor);
  const blue = Math.round((value & 255) * factor);
  return `#${((red << 16) | (green << 8) | blue).toString(16).padStart(6, "0")}`;
}

function rgba(color: string, alpha: number): string {
  const value = Number.parseInt(color.slice(1), 16);
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
}
