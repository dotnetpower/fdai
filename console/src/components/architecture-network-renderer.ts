import {
  clamp,
  project,
  rectangle,
  type Camera,
  type Point,
} from "./architecture-map.geometry";
import {
  isRegion,
  resourceColorOf,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";
import { isArchitectureNetworkPlane } from "./architecture-network-layout";

interface NetworkLabelPalette {
  readonly labelText: string;
}

export function drawArchitectureNetworkPlanes(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  planes: readonly InventoryResource[],
  selectedId: string | null,
  palette: NetworkLabelPalette,
): void {
  for (const plane of planes) {
    const points = rectangle(
      camera,
      width,
      height,
      plane.x ?? 0,
      plane.y ?? 0,
      plane.w ?? 0,
      plane.h ?? 0,
      plane.type === "network.subnet" || plane.type === "subnet" ? .022 : .016,
    );
    const color = resourceColorOf(plane);
    const subnet = plane.type === "network.subnet" || plane.type === "subnet";
    context.save();
    context.globalAlpha = subnet ? .2 : .11;
    fillPolygon(
      context,
      points,
      color,
      selectedId === plane.id ? palette.labelText : color,
      selectedId === plane.id ? 2.4 : subnet ? 1.4 : 1,
    );
    context.restore();
    drawWorldLabel(context, width, height, camera, plane, color);
  }
}

export function drawArchitectureNetworkMemberships(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  graph: Pick<InventoryGraphResponse, "resources" | "links">,
  highlightedIds?: ReadonlySet<string>,
): void {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const directlyAttachedIds = new Set(
    graph.links
      .filter((link) => link.type === "attached_to")
      .flatMap((link) => [link.source, link.target]),
  );
  for (const node of graph.resources.filter((resource) => !isRegion(resource))) {
    if (directlyAttachedIds.has(node.id)) continue;
    const plane = node.network_plane_id ? byId.get(node.network_plane_id) : undefined;
    if (!plane || !isArchitectureNetworkPlane(plane)) continue;
    const railX = (plane.x ?? 0) + .28;
    const railTop = (plane.y ?? 0) + .62;
    const points = [
      project(camera, width, height, node.x ?? 0, node.y ?? 0, .045),
      project(camera, width, height, railX, node.y ?? 0, .045),
      project(camera, width, height, railX, railTop, .045),
    ];
    const active = !highlightedIds || highlightedIds.has(node.id);
    strokeRoute(context, points, active ? .48 : .08, "#1490df", 1.35, [4, 4]);
  }
}

export function drawArchitectureAttachmentRoute(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  source: InventoryResource,
  target: InventoryResource,
  active: boolean,
): void {
  const sourceCenter = resourceCenter(source);
  const targetCenter = resourceCenter(target);
  const middleX = (sourceCenter.x + targetCenter.x) / 2;
  const points = [
    project(camera, width, height, sourceCenter.x, sourceCenter.y, .065),
    project(camera, width, height, middleX, sourceCenter.y, .065),
    project(camera, width, height, middleX, targetCenter.y, .065),
    project(camera, width, height, targetCenter.x, targetCenter.y, .065),
  ];
  strokeRoute(context, points, active ? .72 : .08, "#ffffff", 4.4, []);
  strokeRoute(context, points, active ? .88 : .12, "#397a5d", 2.1, []);
}

function drawWorldLabel(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  plane: InventoryResource,
  color: string,
): void {
  const origin = project(
    camera,
    width,
    height,
    (plane.x ?? 0) + .34,
    (plane.y ?? 0) + .42,
    .035,
  );
  const axis = project(
    camera,
    width,
    height,
    (plane.x ?? 0) + 1.34,
    (plane.y ?? 0) + .42,
    .035,
  );
  const subnet = plane.type === "network.subnet" || plane.type === "subnet";
  const fontSize = clamp(camera.scale * (subnet ? .24 : .28), subnet ? 11 : 12, subnet ? 17 : 20);
  const maximumWidth = Math.max(72, camera.scale * Math.max(1, (plane.w ?? 1) - .68));
  context.save();
  context.translate(origin.x, origin.y);
  context.rotate(Math.atan2(axis.y - origin.y, axis.x - origin.x));
  context.font = `700 ${fontSize}px Aptos, Segoe UI, sans-serif`;
  context.textAlign = "left";
  context.textBaseline = "middle";
  context.fillStyle = color;
  context.globalAlpha = subnet ? .9 : .76;
  context.fillText(fitText(plane.name, maximumWidth, (value) => context.measureText(value).width), 0, 0);
  context.restore();
}

function strokeRoute(
  context: CanvasRenderingContext2D,
  points: readonly Point[],
  alpha: number,
  color: string,
  lineWidth: number,
  dash: readonly number[],
): void {
  const first = points[0];
  if (!first) return;
  context.save();
  context.globalAlpha = alpha;
  context.strokeStyle = color;
  context.lineWidth = lineWidth;
  context.setLineDash([...dash]);
  context.beginPath();
  context.moveTo(first.x, first.y);
  points.slice(1).forEach((point) => context.lineTo(point.x, point.y));
  context.stroke();
  context.restore();
}

function resourceCenter(resource: InventoryResource): { readonly x: number; readonly y: number } {
  return {
    x: (resource.x ?? 0) + (resource.w ?? 0) / 2,
    y: (resource.y ?? 0) + (resource.h ?? 0) / 2,
  };
}

function fillPolygon(
  context: CanvasRenderingContext2D,
  points: readonly Point[],
  fill: string,
  stroke: string,
  lineWidth: number,
): void {
  const first = points[0];
  if (!first) return;
  context.beginPath();
  context.moveTo(first.x, first.y);
  points.slice(1).forEach((point) => context.lineTo(point.x, point.y));
  context.closePath();
  context.fillStyle = fill;
  context.fill();
  context.strokeStyle = stroke;
  context.lineWidth = lineWidth;
  context.stroke();
}

function fitText(text: string, maximumWidth: number, measure: (value: string) => number): string {
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
