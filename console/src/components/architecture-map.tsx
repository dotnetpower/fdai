import { forwardRef } from "preact/compat";
import { useEffect, useImperativeHandle, useRef } from "preact/hooks";
import {
  constrainGraph,
  geometryOf,
  isRegion,
  resourceColorOf,
  shapeOf,
  type ArchitectureCameraView,
  type ArchitectureDisplayOptions,
  type ArchitectureNodeGeometry,
  type ArchitectureNodeShape,
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
  const showLabels = options.showLabels && width >= 420;
  context.clearRect(0, 0, width, height);
  context.fillStyle = "#eef2f4";
  context.fillRect(0, 0, width, height);
  const plate = rectangle(camera, width, height, 0, 0, WORLD.width, WORLD.height, 0);
  fillPolygon(context, plate, "#fbfcfd", "#aeb9c3");
  if (options.showGrid) drawGrid(context, width, height, camera);

  const regions = graph.resources.filter(isRegion).sort((first, second) =>
    (second.w ?? 0) * (second.h ?? 0) - (first.w ?? 0) * (first.h ?? 0));
  for (const region of regions) {
    const color = resourceColorOf(region);
    const points = rectangle(camera, width, height, region.x ?? 0, region.y ?? 0, region.w ?? 0, region.h ?? 0, .01);
    context.save();
    context.globalAlpha = region.type === "subscription" ? .12 : .2;
    fillPolygon(context, points, color, selectedId === region.id ? "#0f6670" : color, selectedId === region.id ? 2.5 : 1.1);
    context.restore();
    if (showLabels) {
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
  for (const node of ordered) drawNodeOverlay(context, width, height, camera, node, highlightedIds, showLabels);
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
    const color = resourceColorOf(node);
    const shape = shapeOf(node);
    const geometry = geometryOf(node);
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
): void {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  for (const link of graph.links.filter((item) => item.type !== "contains")) {
    const source = byId.get(link.source);
    const target = byId.get(link.target);
    if (!source || !target || isRegion(source) || isRegion(target)) continue;
    const start = project(
      camera, width, height, source.x ?? 0, source.y ?? 0,
      LIFT + geometryOf(source).height * .7,
    );
    const end = project(
      camera, width, height, target.x ?? 0, target.y ?? 0,
      LIFT + geometryOf(target).height * .7,
    );
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
  highlightedIds?: ReadonlySet<string>,
  showLabels = true,
): void {
  const nodeX = node.x ?? 0;
  const nodeY = node.y ?? 0;
  const geometry = geometryOf(node);
  context.save();
  context.globalAlpha = highlightAlpha(node.id, highlightedIds);
  const center = project(camera, width, height, nodeX, nodeY, LIFT + geometry.height + .02);
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
    const silhouette = nodeSilhouette(camera, width, height, resource);
    if (!pointInPolygon(screenX, screenY, silhouette)) continue;
    const point = project(
      camera, width, height, resource.x ?? 0, resource.y ?? 0,
      LIFT + geometryOf(resource).height / 2,
    );
    const distance = Math.hypot(screenX - point.x, screenY - point.y);
    if (!best || distance < best.distance) best = { resource, distance };
  }
  return best?.resource ?? null;
}

function nodeSilhouette(
  camera: Camera,
  width: number,
  height: number,
  resource: InventoryResource,
): Point[] {
  const x = resource.x ?? 0;
  const y = resource.y ?? 0;
  const shape = shapeOf(resource);
  const geometry = geometryOf(resource);
  if (shape === "cylinder") {
    return convexHull([
      ...circlePoints(camera, width, height, x, y, geometry.width / 2, LIFT),
      ...circlePoints(camera, width, height, x, y, geometry.width / 2, LIFT + geometry.height),
    ]);
  }
  if (shape === "slab") {
    const { upperGeometry } = slabTiers(geometry);
    return convexHull([
      ...footprintPoints(camera, width, height, x, y, shape, geometry, LIFT),
      ...footprintPoints(
        camera, width, height, x, y, shape, upperGeometry, LIFT + geometry.height,
      ),
    ]);
  }
  return convexHull([
    ...footprintPoints(camera, width, height, x, y, shape, geometry, LIFT),
    ...footprintPoints(camera, width, height, x, y, shape, geometry, LIFT + geometry.height),
  ]);
}

function slabTiers(geometry: ArchitectureNodeGeometry): {
  lowerHeight: number;
  lowerGeometry: ArchitectureNodeGeometry;
  upperGeometry: ArchitectureNodeGeometry;
} {
  const lowerHeight = geometry.height * .48;
  const inset = Math.min(geometry.width, geometry.depth) * .17;
  return {
    lowerHeight,
    lowerGeometry: { ...geometry, height: lowerHeight },
    upperGeometry: {
      width: geometry.width - inset,
      depth: geometry.depth - inset,
      height: geometry.height - lowerHeight,
    },
  };
}

function pointInPolygon(x: number, y: number, points: readonly Point[]): boolean {
  let inside = false;
  for (let index = 0, previous = points.length - 1; index < points.length; previous = index++) {
    const currentPoint = points[index]!;
    const previousPoint = points[previous]!;
    if (
      (currentPoint.y > y) !== (previousPoint.y > y) &&
      x < ((previousPoint.x - currentPoint.x) * (y - currentPoint.y)) /
        (previousPoint.y - currentPoint.y) + currentPoint.x
    ) inside = !inside;
  }
  return inside;
}

function rectangle(camera: Camera, width: number, height: number, x: number, y: number, rectWidth: number, rectHeight: number, z: number): Quad {
  return [
    project(camera, width, height, x, y, z),
    project(camera, width, height, x + rectWidth, y, z),
    project(camera, width, height, x + rectWidth, y + rectHeight, z),
    project(camera, width, height, x, y + rectHeight, z),
  ];
}

function footprintPoints(
  camera: Camera,
  width: number,
  height: number,
  centerX: number,
  centerY: number,
  shape: ArchitectureNodeShape,
  geometry: ArchitectureNodeGeometry,
  z: number,
): Point[] {
  if (shape === "hexagon") {
    return regularPolygonPoints(
      camera, width, height, centerX, centerY, geometry.width, geometry.depth, z, 6, Math.PI / 6,
    );
  }
  if (shape === "compact") {
    const halfWidth = geometry.width / 2;
    const halfDepth = geometry.depth / 2;
    const cut = Math.min(geometry.width, geometry.depth) * .18;
    return worldPoints(camera, width, height, z, [
      [centerX - halfWidth + cut, centerY - halfDepth],
      [centerX + halfWidth - cut, centerY - halfDepth],
      [centerX + halfWidth, centerY - halfDepth + cut],
      [centerX + halfWidth, centerY + halfDepth - cut],
      [centerX + halfWidth - cut, centerY + halfDepth],
      [centerX - halfWidth + cut, centerY + halfDepth],
      [centerX - halfWidth, centerY + halfDepth - cut],
      [centerX - halfWidth, centerY - halfDepth + cut],
    ]);
  }
  return [...rectangle(
    camera, width, height,
    centerX - geometry.width / 2, centerY - geometry.depth / 2,
    geometry.width, geometry.depth, z,
  )];
}

function regularPolygonPoints(
  camera: Camera,
  width: number,
  height: number,
  centerX: number,
  centerY: number,
  polygonWidth: number,
  polygonDepth: number,
  z: number,
  sides: number,
  rotation: number,
): Point[] {
  return worldPoints(
    camera,
    width,
    height,
    z,
    Array.from({ length: sides }, (_, index) => {
      const angle = rotation + (index / sides) * Math.PI * 2;
      return [
        centerX + Math.cos(angle) * polygonWidth / 2,
        centerY + Math.sin(angle) * polygonDepth / 2,
      ] as const;
    }),
  );
}

function worldPoints(
  camera: Camera,
  width: number,
  height: number,
  z: number,
  points: readonly (readonly [number, number])[],
): Point[] {
  return points.map(([x, y]) => project(camera, width, height, x, y, z));
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

function convexHull(points: readonly Point[]): Point[] {
  const ordered = [...points].sort((first, second) => first.x - second.x || first.y - second.y);
  const cross = (origin: Point, first: Point, second: Point) =>
    (first.x - origin.x) * (second.y - origin.y) -
    (first.y - origin.y) * (second.x - origin.x);
  const buildHalf = (candidates: readonly Point[]) => {
    const half: Point[] = [];
    for (const point of candidates) {
      while (half.length >= 2 && cross(half.at(-2)!, half.at(-1)!, point) <= 0) half.pop();
      half.push(point);
    }
    return half;
  };
  const lower = buildHalf(ordered);
  const upper = buildHalf([...ordered].reverse());
  lower.pop();
  upper.pop();
  return [...lower, ...upper];
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
  const red = Math.round(((value >> 16) & 255) * factor);
  const green = Math.round(((value >> 8) & 255) * factor);
  const blue = Math.round((value & 255) * factor);
  return `#${((red << 16) | (green << 8) | blue).toString(16).padStart(6, "0")}`;
}

function rgba(color: string, alpha: number): string {
  const value = Number.parseInt(color.slice(1), 16);
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}