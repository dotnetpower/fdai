import { forwardRef } from "preact/compat";
import { useEffect, useImperativeHandle, useRef } from "preact/hooks";
import {
  constrainGraph,
  isRegion,
  layerOf,
  shapeOf,
  type ArchitectureCameraView,
  type ArchitectureDisplayOptions,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly selectedId?: string | null;
  readonly highlightedIds?: ReadonlySet<string>;
  readonly onSelect?: (resource: InventoryResource | null) => void;
  readonly className?: string;
  readonly options?: ArchitectureDisplayOptions;
  readonly onZoomChange?: (percent: number) => void;
}

export interface ArchitectureMapHandle {
  readonly setView: (view: ArchitectureCameraView) => void;
  readonly zoomIn: () => void;
  readonly zoomOut: () => void;
  readonly fit: () => void;
}

interface Camera {
  yaw: number;
  pitch: number;
  scale: number;
  panX: number;
  panY: number;
}

interface Point { x: number; y: number; depth: number }
type Quad = readonly [Point, Point, Point, Point];
type CanvasPaint = string | CanvasGradient | CanvasPattern;

const WORLD = { width: 18, height: 12 };
const LIFT = .10;
const HEIGHT = .34;
const NODE_WIDTH = 1.04;
const NODE_DEPTH = .76;
const COLORS = {
  scope: "#697586",
  network: "#27989b",
  security: "#d99a3e",
  compute: "#397fba",
  data: "#8a62b7",
} as const;

const DEFAULT_OPTIONS: ArchitectureDisplayOptions = {
  showConnections: true,
  showReflections: true,
  showLabels: true,
  showGrid: true,
};

export const ArchitectureMap = forwardRef<ArchitectureMapHandle, Props>(function ArchitectureMap({
  graph,
  selectedId = null,
  highlightedIds,
  onSelect,
  className = "",
  options = DEFAULT_OPTIONS,
  onZoomChange,
}, forwardedRef) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cameraRef = useRef<Camera>({ yaw: Math.PI / 4, pitch: .58, scale: 42, panX: 0, panY: 0 });
  const fitScaleRef = useRef(42);
  const dragRef = useRef<{ startX: number; startY: number; lastX: number; lastY: number } | null>(null);
  const stateRef = useRef({
    graph: constrainGraph(graph),
    selectedId,
    highlightedIds,
    onSelect,
    options,
  });
  const drawRef = useRef<(() => void) | null>(null);
  stateRef.current = { graph: constrainGraph(graph), selectedId, highlightedIds, onSelect, options };

  const notifyZoom = () => onZoomChange?.(
    Math.round((cameraRef.current.scale / fitScaleRef.current) * 100),
  );

  useImperativeHandle(forwardedRef, () => ({
    setView(view) {
      applyCameraView(cameraRef.current, view);
      fitCamera(cameraRef.current, canvasRef.current?.clientWidth ?? 1, canvasRef.current?.clientHeight ?? 1);
      fitScaleRef.current = cameraRef.current.scale;
      drawRef.current?.();
      notifyZoom();
    },
    zoomIn() {
      cameraRef.current.scale = clamp(cameraRef.current.scale * 1.14, 18, 132);
      drawRef.current?.();
      notifyZoom();
    },
    zoomOut() {
      cameraRef.current.scale = clamp(cameraRef.current.scale * .88, 18, 132);
      drawRef.current?.();
      notifyZoom();
    },
    fit() {
      fitCamera(cameraRef.current, canvasRef.current?.clientWidth ?? 1, canvasRef.current?.clientHeight ?? 1);
      fitScaleRef.current = cameraRef.current.scale;
      drawRef.current?.();
      notifyZoom();
    },
  }), [onZoomChange]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const resize = () => {
      const ratio = window.devicePixelRatio || 1;
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      fitCamera(cameraRef.current, width, height);
      fitScaleRef.current = cameraRef.current.scale;
      draw();
      notifyZoom();
    };
    const draw = () => {
      const state = stateRef.current;
      renderMap(
        context,
        canvas.clientWidth,
        canvas.clientHeight,
        cameraRef.current,
        state.graph,
        state.selectedId,
        state.highlightedIds,
        state.options,
      );
    };
    drawRef.current = draw;
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);

    const localPoint = (event: PointerEvent | WheelEvent) => {
      const rect = canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const pointerDown = (event: PointerEvent) => {
      canvas.setPointerCapture(event.pointerId);
      const point = localPoint(event);
      dragRef.current = { startX: point.x, startY: point.y, lastX: point.x, lastY: point.y };
    };
    const pointerMove = (event: PointerEvent) => {
      const previous = dragRef.current;
      if (!previous) return;
      const current = localPoint(event);
      cameraRef.current.panX += current.x - previous.lastX;
      cameraRef.current.panY += current.y - previous.lastY;
      dragRef.current = { ...previous, lastX: current.x, lastY: current.y };
      draw();
    };
    const pointerUp = (event: PointerEvent) => {
      const previous = dragRef.current;
      dragRef.current = null;
      const point = localPoint(event);
      if (!previous || Math.hypot(point.x - previous.startX, point.y - previous.startY) > 6) return;
      const state = stateRef.current;
      state.onSelect?.(pickResource(state.graph, cameraRef.current, canvas.clientWidth, canvas.clientHeight, point.x, point.y));
    };
    const wheel = (event: WheelEvent) => {
      event.preventDefault();
      cameraRef.current.scale = clamp(cameraRef.current.scale * (event.deltaY < 0 ? 1.1 : .91), 18, 132);
      draw();
      notifyZoom();
    };
    canvas.addEventListener("pointerdown", pointerDown);
    canvas.addEventListener("pointermove", pointerMove);
    canvas.addEventListener("pointerup", pointerUp);
    canvas.addEventListener("pointercancel", () => { dragRef.current = null; });
    canvas.addEventListener("wheel", wheel, { passive: false });
    resize();
    return () => {
      observer.disconnect();
      canvas.removeEventListener("pointerdown", pointerDown);
      canvas.removeEventListener("pointermove", pointerMove);
      canvas.removeEventListener("pointerup", pointerUp);
      canvas.removeEventListener("wheel", wheel);
      drawRef.current = null;
    };
  }, []);

  useEffect(() => { drawRef.current?.(); }, [selectedId, highlightedIds, options]);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !drawRef.current) return;
    fitCamera(cameraRef.current, canvas.clientWidth, canvas.clientHeight);
    fitScaleRef.current = cameraRef.current.scale;
    drawRef.current();
    notifyZoom();
  }, [graph]);

  return <canvas ref={canvasRef} class={`architecture-map ${className}`} aria-label="Resource architecture map" />;
});

function applyCameraView(camera: Camera, view: ArchitectureCameraView): void {
  if (view === "top") { camera.yaw = 0; camera.pitch = 1.5; }
  else if (view === "front") { camera.yaw = 0; camera.pitch = .23; }
  else { camera.yaw = Math.PI / 4; camera.pitch = .58; }
}

function fitCamera(camera: Camera, width: number, height: number): void {
  camera.scale = clamp(Math.min(width / 20, height / 13), 22, 64);
  camera.panX = 0;
  camera.panY = 6;
}

function project(camera: Camera, width: number, height: number, x: number, y: number, z = 0): Point {
  const offsetX = x - WORLD.width / 2;
  const offsetY = y - WORLD.height / 2;
  const rotatedX = offsetX * Math.cos(camera.yaw) - offsetY * Math.sin(camera.yaw);
  const rotatedY = offsetX * Math.sin(camera.yaw) + offsetY * Math.cos(camera.yaw);
  return {
    x: width / 2 + camera.panX + rotatedX * camera.scale,
    y: height / 2 + camera.panY - (rotatedY * Math.sin(camera.pitch) + z * Math.cos(camera.pitch)) * camera.scale,
    depth: rotatedY * Math.cos(camera.pitch) - z * Math.sin(camera.pitch),
  };
}

function renderMap(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  graph: InventoryGraphResponse,
  selectedId: string | null,
  highlightedIds?: ReadonlySet<string>,
  options: ArchitectureDisplayOptions = DEFAULT_OPTIONS,
): void {
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#eef2f4";
  context.fillRect(0, 0, width, height);
  const plate = rectangle(camera, width, height, 0, 0, WORLD.width, WORLD.height, 0);
  fillPolygon(context, plate, "#fbfcfd", "#aeb9c3");
  if (options.showGrid) drawGrid(context, width, height, camera);

  const regions = graph.resources.filter(isRegion).sort((first, second) =>
    (second.w ?? 0) * (second.h ?? 0) - (first.w ?? 0) * (first.h ?? 0));
  for (const region of regions) {
    const color = COLORS[layerOf(region)];
    const points = rectangle(camera, width, height, region.x ?? 0, region.y ?? 0, region.w ?? 0, region.h ?? 0, .01);
    context.save();
    context.globalAlpha = region.type === "subscription" ? .12 : .2;
    fillPolygon(context, points, color, selectedId === region.id ? "#0f6670" : color, selectedId === region.id ? 2.5 : 1.1);
    context.restore();
    if (options.showLabels) {
      drawLabel(context, project(camera, width, height, (region.x ?? 0) + .2, (region.y ?? 0) + .2, .02), region.name, color, 9);
    }
  }

  const nodes = graph.resources.filter((resource) => !isRegion(resource));
  if (options.showReflections) drawReflections(context, width, height, camera, nodes, highlightedIds);
  const ordered = [...nodes].sort((first, second) =>
    project(camera, width, height, second.x ?? 0, second.y ?? 0).depth -
    project(camera, width, height, first.x ?? 0, first.y ?? 0).depth);
  for (const node of ordered) drawNodeBody(context, width, height, camera, node, selectedId, highlightedIds);
  if (options.showConnections) drawLinks(context, width, height, camera, graph, highlightedIds);
  for (const node of ordered) drawNodeOverlay(context, width, height, camera, node, highlightedIds, options.showLabels);
}

function drawGrid(context: CanvasRenderingContext2D, width: number, height: number, camera: Camera): void {
  context.save();
  context.fillStyle = "rgba(68,86,101,.18)";
  for (let x = 1; x < WORLD.width; x += 1) {
    for (let y = 1; y < WORLD.height; y += 1) {
      const point = project(camera, width, height, x, y, .003);
      context.beginPath();
      context.arc(point.x, point.y, .7, 0, Math.PI * 2);
      context.fill();
    }
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
    const color = COLORS[layerOf(node)];
    const isDatabase = shapeOf(node) === "cylinder";
    if (isDatabase) {
      drawCylinderReflection(
        context,
        width,
        height,
        camera,
        nodeX,
        nodeY,
        color,
        highlightAlpha(node.id, highlightedIds),
      );
      continue;
    }
    const x = nodeX - NODE_WIDTH / 2;
    const y = nodeY - NODE_DEPTH / 2;
    const mirrorBase = rectangle(camera, width, height, x, y, NODE_WIDTH, NODE_DEPTH, -LIFT);
    const mirrorTop = rectangle(
      camera,
      width,
      height,
      x,
      y,
      NODE_WIDTH,
      NODE_DEPTH,
      -(LIFT + HEIGHT),
    );
    const alpha = highlightAlpha(node.id, highlightedIds);
    context.save();
    context.globalAlpha = alpha;
    context.filter = "blur(.8px)";
    for (let index = 0; index < 4; index += 1) {
      const next = (index + 1) % 4;
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

    const point = project(camera, width, height, nodeX, nodeY, .004);
    context.save();
    context.globalAlpha = alpha * .24;
    context.translate(point.x, point.y + 2);
    context.scale(1, .35);
    const glow = context.createRadialGradient(0, 0, 0, 0, 0, camera.scale * .45);
    glow.addColorStop(0, color);
    glow.addColorStop(1, rgba(color, 0));
    context.fillStyle = glow;
    context.beginPath();
    context.arc(0, 0, camera.scale * .45, 0, Math.PI * 2);
    context.fill();
    context.restore();
  }
}

function drawLinks(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
  camera: Camera,
  graph: InventoryGraphResponse,
  highlightedIds?: ReadonlySet<string>,
): void {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  for (const link of graph.links.filter((item) => item.type !== "contains")) {
    const source = byId.get(link.source);
    const target = byId.get(link.target);
    if (!source || !target || isRegion(source) || isRegion(target)) continue;
    const start = project(camera, width, height, source.x ?? 0, source.y ?? 0, LIFT + HEIGHT * .7);
    const end = project(camera, width, height, target.x ?? 0, target.y ?? 0, LIFT + HEIGHT * .7);
    const edgeActive = !highlightedIds || (highlightedIds.has(source.id) && highlightedIds.has(target.id));
    context.save();
    context.globalAlpha = edgeActive ? .72 : .1;
    context.strokeStyle = link.type === "attached_to" ? "#397a5d" : "#426f87";
    context.lineWidth = 1.7;
    context.setLineDash(link.type === "attached_to" ? [5, 4] : []);
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
    context.strokeStyle = link.type === "attached_to" ? "#397a5d" : "#426f87";
    context.lineWidth = 1.7;
    context.stroke();
    context.restore();
  }
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
  const color = COLORS[layerOf(node)];
  if (shapeOf(node) === "cylinder") {
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
    );
    return;
  }
  const top = rectangle(
    camera,
    width,
    height,
    nodeX - NODE_WIDTH / 2,
    nodeY - NODE_DEPTH / 2,
    NODE_WIDTH,
    NODE_DEPTH,
    LIFT + HEIGHT,
  );
  const base = rectangle(
    camera,
    width,
    height,
    nodeX - NODE_WIDTH / 2,
    nodeY - NODE_DEPTH / 2,
    NODE_WIDTH,
    NODE_DEPTH,
    LIFT,
  );
  context.save();
  context.globalAlpha = highlightAlpha(node.id, highlightedIds);
  for (let index = 0; index < 4; index += 1) {
    const next = (index + 1) % 4;
    fillPolygon(
      context,
      [top[index]!, top[next]!, base[next]!, base[index]!],
      darken(color, index % 2 ? .72 : .56),
      "transparent",
      0,
    );
  }
  fillPolygon(
    context,
    top,
    color,
    selectedId === node.id ? "#102f36" : "transparent",
    selectedId === node.id ? 2.4 : 0,
  );
  context.restore();
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
): void {
  const top = circlePoints(camera, width, height, x, y, .46, LIFT + HEIGHT);
  const base = circlePoints(camera, width, height, x, y, .46, LIFT);
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
  for (let index = 0; index < top.length; index += 1) {
    const next = (index + 1) % top.length;
    fillPolygon(
      context,
      [top[index]!, top[next]!, base[next]!, base[index]!],
      sideFill,
      "transparent",
      0,
    );
  }
  fillPolygon(context, top, color, selected ? "#102f36" : "transparent", selected ? 2.4 : 0);
  const inner = circlePoints(camera, width, height, x, y, .37, LIFT + HEIGHT + .006);
  fillPolygon(context, inner, rgba("#ffffff", .09), "transparent", 0);
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
): void {
  const mirrorBase = circlePoints(camera, width, height, x, y, .46, -LIFT);
  const mirrorTop = circlePoints(camera, width, height, x, y, .46, -(LIFT + HEIGHT));
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
  highlightedIds?: ReadonlySet<string>,
  showLabels = true,
): void {
  const nodeX = node.x ?? 0;
  const nodeY = node.y ?? 0;
  context.save();
  context.globalAlpha = highlightAlpha(node.id, highlightedIds);
  const center = project(camera, width, height, nodeX, nodeY, LIFT + HEIGHT + .02);
  context.fillStyle = "#fff";
  context.font = "800 9px Aptos, Segoe UI, sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.strokeStyle = "rgba(28,39,51,.38)";
  context.lineWidth = 2.4;
  context.strokeText(abbreviation(node.type), center.x, center.y);
  context.fillText(abbreviation(node.type), center.x, center.y);
  if (showLabels) {
    const labelPoint = project(camera, width, height, nodeX, nodeY, 0);
    drawLabel(context, { ...labelPoint, y: labelPoint.y + 13 }, node.name, "#354252", 9);
  }
  context.restore();
}

function pickResource(
  graph: InventoryGraphResponse,
  camera: Camera,
  width: number,
  height: number,
  screenX: number,
  screenY: number,
): InventoryResource | null {
  let best: { resource: InventoryResource; distance: number } | null = null;
  for (const resource of graph.resources.filter((item) => !isRegion(item))) {
    const point = project(camera, width, height, resource.x ?? 0, resource.y ?? 0, LIFT + HEIGHT / 2);
    const distance = Math.hypot(screenX - point.x, screenY - point.y);
    if (distance < 28 && (!best || distance < best.distance)) best = { resource, distance };
  }
  return best?.resource ?? null;
}

function rectangle(camera: Camera, width: number, height: number, x: number, y: number, rectWidth: number, rectHeight: number, z: number): Quad {
  return [
    project(camera, width, height, x, y, z),
    project(camera, width, height, x + rectWidth, y, z),
    project(camera, width, height, x + rectWidth, y + rectHeight, z),
    project(camera, width, height, x, y + rectHeight, z),
  ];
}

function circlePoints(
  camera: Camera,
  width: number,
  height: number,
  centerX: number,
  centerY: number,
  radius: number,
  z: number,
  segments = 24,
): Point[] {
  return Array.from({ length: segments }, (_, index) => {
    const angle = (index / segments) * Math.PI * 2;
    return project(
      camera,
      width,
      height,
      centerX + Math.cos(angle) * radius,
      centerY + Math.sin(angle) * radius,
      z,
    );
  });
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

function drawLabel(context: CanvasRenderingContext2D, point: Pick<Point, "x" | "y">, text: string, color: string, size: number): void {
  context.font = `600 ${size}px Aptos, Segoe UI, sans-serif`;
  const labelWidth = context.measureText(text).width + 8;
  context.fillStyle = "rgba(255,255,255,.9)";
  context.fillRect(point.x - labelWidth / 2, point.y - 7, labelWidth, 14);
  context.fillStyle = color;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, point.x, point.y);
}

function highlightAlpha(id: string, highlightedIds?: ReadonlySet<string>): number {
  if (!highlightedIds || highlightedIds.size === 0) return 1;
  return highlightedIds.has(id) ? 1 : .14;
}

function abbreviation(type: string): string {
  if (type === "postgresql") return "DB";
  if (type === "redis") return "RD";
  if (type === "storage-account") return "ST";
  return type.split("-").map((part) => part[0]).join("").slice(0, 3).toUpperCase();
}

function darken(color: string, factor: number): string {
  const value = Number.parseInt(color.slice(1), 16);
  return `rgb(${Math.round(((value >> 16) & 255) * factor)},${Math.round(((value >> 8) & 255) * factor)},${Math.round((value & 255) * factor)})`;
}

function rgba(color: string, alpha: number): string {
  const value = Number.parseInt(color.slice(1), 16);
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}