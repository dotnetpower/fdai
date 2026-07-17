import {
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
  scale: number;
  panX: number;
  panY: number;
}

export interface Point {
  x: number;
  y: number;
  depth: number;
}

export type Quad = readonly [Point, Point, Point, Point];

export const WORLD = { width: 18, height: 12 };
export const LIFT = .10;

export function architectureResourceFromValue(
  resources: readonly InventoryResource[],
  value: string,
): InventoryResource | null {
  return resources.find((resource) => resource.id === value) ?? null;
}

export function applyCameraView(camera: Camera, view: ArchitectureCameraView): void {
  if (view === "top") { camera.yaw = 0; camera.pitch = 1.5; }
  else if (view === "front") { camera.yaw = 0; camera.pitch = .23; }
  else { camera.yaw = Math.PI / 4; camera.pitch = .58; }
}

export function fitCamera(camera: Camera, width: number, height: number): void {
  camera.scale = clamp(Math.min(width / 20, height / 13), 22, 64);
  camera.panX = 0;
  camera.panY = 6;
}

export function project(
  camera: Camera,
  width: number,
  height: number,
  x: number,
  y: number,
  z = 0,
): Point {
  const offsetX = x - WORLD.width / 2;
  const offsetY = y - WORLD.height / 2;
  const rotatedX = offsetX * Math.cos(camera.yaw) - offsetY * Math.sin(camera.yaw);
  const rotatedY = offsetX * Math.sin(camera.yaw) + offsetY * Math.cos(camera.yaw);
  return {
    x: width / 2 + camera.panX + rotatedX * camera.scale,
    y: height / 2 + camera.panY -
      (rotatedY * Math.sin(camera.pitch) + z * Math.cos(camera.pitch)) * camera.scale,
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
