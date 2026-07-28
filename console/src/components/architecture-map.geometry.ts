import {
  architectureViewIsFocused,
  geometryOf,
  isRegion,
  shapeOf,
  type ArchitectureCameraView,
  type ArchitectureNodeGeometry,
  type ArchitectureNodeShape,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";

export interface Camera {
  yaw: number;
  pitch: number;
  perspective?: number;
  scale: number;
  panX: number;
  panY: number;
  worldWidth?: number;
  worldHeight?: number;
}

export interface Point {
  x: number;
  y: number;
  depth: number;
}

export type Quad = readonly [Point, Point, Point, Point];

export const WORLD = { width: 18, height: 12 };
const FOCUSED_WORLD = { width: 8, height: 6 };
export const LIFT = .10;
export const DEFAULT_ISOMETRIC_CAMERA = {
  yaw: .28,
  pitch: .44,
  perspective: .34,
} as const;
const ZOOM_STEP = 1.2;
const MIN_ZOOM = 6;
const MAX_ZOOM = 512;
const ORBIT_RADIANS_PER_PIXEL = .005;
const FIT_HORIZONTAL_PADDING = 112;
const FIT_VERTICAL_PADDING = 120;

export function architectureZoomScale(
  scale: number,
  direction: "in" | "out",
): number {
  return clamp(scale * (direction === "in" ? ZOOM_STEP : 1 / ZOOM_STEP), MIN_ZOOM, MAX_ZOOM);
}

export function zoomCameraAtPoint(
  camera: Camera,
  direction: "in" | "out",
  screenX: number,
  screenY: number,
  width: number,
  height: number,
): void {
  const previousScale = camera.scale;
  const nextScale = architectureZoomScale(previousScale, direction);
  const ratio = nextScale / previousScale;
  const relativeX = screenX - (width / 2 + camera.panX);
  const relativeY = screenY - (height / 2 + camera.panY);
  camera.scale = nextScale;
  camera.panX = screenX - width / 2 - relativeX * ratio;
  camera.panY = screenY - height / 2 - relativeY * ratio;
}

export function orbitArchitectureCamera(camera: Camera, deltaX: number): void {
  const fullTurn = Math.PI * 2;
  camera.yaw = ((camera.yaw + deltaX * ORBIT_RADIANS_PER_PIXEL + Math.PI) % fullTurn
    + fullTurn) % fullTurn - Math.PI;
}

export function architectureResourceFromValue(
  resources: readonly InventoryResource[],
  value: string,
): InventoryResource | null {
  return resources.find((resource) => resource.id === value) ?? null;
}

export function applyCameraView(camera: Camera, view: ArchitectureCameraView): void {
  if (view === "top") { camera.yaw = 0; camera.pitch = 1.5; camera.perspective = 0; }
  else if (view === "front") { camera.yaw = 0; camera.pitch = .23; camera.perspective = .12; }
  else Object.assign(camera, DEFAULT_ISOMETRIC_CAMERA);
}

export function architectureWorldSize(
  graph: Pick<InventoryGraphResponse, "resources" | "active_view" | "views">,
): { width: number; height: number } {
  const minimum = architectureViewIsFocused(graph) ? FOCUSED_WORLD : WORLD;
  return graph.resources.filter(isRegion).reduce(
    (world, resource) => ({
      width: Math.max(world.width, (resource.x ?? 0) + (resource.w ?? 0)),
      height: Math.max(world.height, (resource.y ?? 0) + (resource.h ?? 0)),
    }),
    { ...minimum },
  );
}

export function architectureCanvasHeight(
  graph: Pick<InventoryGraphResponse, "resources" | "active_view" | "views">,
): number {
  const minimumHeight = architectureViewIsFocused(graph) ? 680 : 780;
  return Math.max(minimumHeight, Math.round(architectureWorldSize(graph).height * 36));
}

export function cameraWorldSize(camera: Camera): { width: number; height: number } {
  return {
    width: camera.worldWidth ?? WORLD.width,
    height: camera.worldHeight ?? WORLD.height,
  };
}

export function architectureLegendReserveWidth(canvasWidth: number): number {
  if (canvasWidth >= 700) return clamp(canvasWidth * .24, 220, 340);
  return clamp(canvasWidth * .34, 96, 180);
}

export function fitCamera(
  camera: Camera,
  width: number,
  height: number,
  graph?: Pick<InventoryGraphResponse, "resources">,
): void {
  const world = graph ? architectureWorldSize(graph) : cameraWorldSize(camera);
  camera.worldWidth = world.width;
  camera.worldHeight = world.height;
  const previousScale = camera.scale;
  const previousPanX = camera.panX;
  const previousPanY = camera.panY;
  camera.scale = 1;
  camera.panX = 0;
  camera.panY = 0;
  const corners = [0, 1.2].flatMap((z) => [
    project(camera, width, height, 0, 0, z),
    project(camera, width, height, world.width, 0, z),
    project(camera, width, height, world.width, world.height, z),
    project(camera, width, height, 0, world.height, z),
  ]);
  const minimumX = Math.min(...corners.map((point) => point.x));
  const maximumX = Math.max(...corners.map((point) => point.x));
  const minimumY = Math.min(...corners.map((point) => point.y));
  const maximumY = Math.max(...corners.map((point) => point.y));
  const horizontalSpan = maximumX - minimumX;
  const verticalSpan = maximumY - minimumY;
  const horizontalCenterOffset = (minimumX + maximumX) / 2 - width / 2;
  const verticalCenterOffset = (minimumY + maximumY) / 2 - height / 2;
  const legendReserve = architectureLegendReserveWidth(width);
  camera.scale = clamp(Math.min(
    Math.max(1, width - FIT_HORIZONTAL_PADDING - legendReserve) / Math.max(1, horizontalSpan),
    Math.max(1, height - FIT_VERTICAL_PADDING) / Math.max(1, verticalSpan),
  ), MIN_ZOOM, 96);
  camera.panX = -legendReserve / 2 - horizontalCenterOffset * camera.scale;
  const projectedVerticalSpan = verticalSpan * camera.scale;
  const anchorTallWorldAtTop = height - projectedVerticalSpan > FIT_VERTICAL_PADDING * 2;
  camera.panY = anchorTallWorldAtTop
    ? FIT_VERTICAL_PADDING - height / 2 - (minimumY - height / 2) * camera.scale
    : height * .04 - verticalCenterOffset * camera.scale;
  if (!Number.isFinite(camera.scale)) {
    camera.scale = previousScale;
    camera.panX = previousPanX;
    camera.panY = previousPanY;
  }
}

export function project(
  camera: Camera,
  width: number,
  height: number,
  x: number,
  y: number,
  z = 0,
): Point {
  const world = cameraWorldSize(camera);
  const offsetX = x - world.width / 2;
  const offsetY = y - world.height / 2;
  const rotatedX = offsetX * Math.cos(camera.yaw) - offsetY * Math.sin(camera.yaw);
  const rotatedY = offsetX * Math.sin(camera.yaw) + offsetY * Math.cos(camera.yaw);
  const depthRatio = rotatedY / Math.max(1, world.height / 2);
  const perspectiveScale = clamp(
    1 - depthRatio * (camera.perspective ?? DEFAULT_ISOMETRIC_CAMERA.perspective),
    .68,
    1.32,
  );
  return {
    x: width / 2 + camera.panX + rotatedX * camera.scale * perspectiveScale,
    y: height / 2 + camera.panY -
      (rotatedY * Math.sin(camera.pitch) + z * Math.cos(camera.pitch)) *
      camera.scale * perspectiveScale,
    depth: rotatedY * Math.cos(camera.pitch) - z * Math.sin(camera.pitch),
  };
}

export function pickResource(
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
    const point = project(
      camera, width, height, resource.x ?? 0, resource.y ?? 0,
      LIFT + geometryOf(resource).height / 2,
    );
    const distance = Math.hypot(screenX - point.x, screenY - point.y);
    const geometry = geometryOf(resource);
    const hitRadius = Math.max(22, camera.scale * Math.max(geometry.width, geometry.depth) / 2);
    if (!pointInPolygon(screenX, screenY, silhouette) && distance > hitRadius) continue;
    if (!best || distance < best.distance) best = { resource, distance };
  }
  if (best) return best.resource;
  return graph.resources
    .filter(isRegion)
    .filter((resource) => pointInPolygon(
      screenX,
      screenY,
      rectangle(
        camera,
        width,
        height,
        resource.x ?? 0,
        resource.y ?? 0,
        resource.w ?? 0,
        resource.h ?? 0,
        .01,
      ),
    ))
    .sort((first, second) =>
      (first.w ?? 0) * (first.h ?? 0) - (second.w ?? 0) * (second.h ?? 0))[0] ?? null;
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

export function slabTiers(geometry: ArchitectureNodeGeometry): {
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

export function rectangle(
  camera: Camera,
  width: number,
  height: number,
  x: number,
  y: number,
  rectWidth: number,
  rectHeight: number,
  z: number,
): Quad {
  return [
    project(camera, width, height, x, y, z),
    project(camera, width, height, x + rectWidth, y, z),
    project(camera, width, height, x + rectWidth, y + rectHeight, z),
    project(camera, width, height, x, y + rectHeight, z),
  ];
}

export function footprintPoints(
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

export function circlePoints(
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

export function convexHull(points: readonly Point[]): Point[] {
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

export function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}
