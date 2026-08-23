export interface ArchitectureNetworkRoutePoint {
  readonly x: number;
  readonly y: number;
}

export interface ArchitectureNetworkRouteBox {
  readonly id: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

function center(box: ArchitectureNetworkRouteBox): ArchitectureNetworkRoutePoint {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

function boundaryPoint(
  box: ArchitectureNetworkRouteBox,
  toward: ArchitectureNetworkRoutePoint,
): ArchitectureNetworkRoutePoint {
  const origin = center(box);
  const deltaX = toward.x - origin.x;
  const deltaY = toward.y - origin.y;
  const factor = Math.min(
    deltaX ? box.width / 2 / Math.abs(deltaX) : Number.POSITIVE_INFINITY,
    deltaY ? box.height / 2 / Math.abs(deltaY) : Number.POSITIVE_INFINITY,
  );
  return Number.isFinite(factor)
    ? { x: origin.x + deltaX * factor, y: origin.y + deltaY * factor }
    : origin;
}

function segmentCrossesBox(
  start: ArchitectureNetworkRoutePoint,
  end: ArchitectureNetworkRoutePoint,
  box: ArchitectureNetworkRouteBox,
  padding: number,
): boolean {
  const left = box.x - padding;
  const right = box.x + box.width + padding;
  const top = box.y - padding;
  const bottom = box.y + box.height + padding;
  if (start.x === end.x) {
    return start.x > left && start.x < right &&
      Math.max(Math.min(start.y, end.y), top) < Math.min(Math.max(start.y, end.y), bottom);
  }
  if (start.y === end.y) {
    return start.y > top && start.y < bottom &&
      Math.max(Math.min(start.x, end.x), left) < Math.min(Math.max(start.x, end.x), right);
  }
  return true;
}

function compactPoints(
  points: readonly ArchitectureNetworkRoutePoint[],
): ArchitectureNetworkRoutePoint[] {
  return points.filter((point, index) => {
    const previous = points[index - 1];
    return !previous || previous.x !== point.x || previous.y !== point.y;
  });
}

/** Routes one relationship around unrelated node boxes and terminates on endpoint boundaries. */
export function architectureNetworkOrthogonalRoute(
  source: ArchitectureNetworkRouteBox,
  target: ArchitectureNetworkRouteBox,
  obstacles: readonly ArchitectureNetworkRouteBox[],
): readonly ArchitectureNetworkRoutePoint[] {
  const sourceCenter = center(source);
  const targetCenter = center(target);
  const unrelated = obstacles.filter((box) => box.id !== source.id && box.id !== target.id);
  const clearance = Math.max(0.35, Math.min(source.width, source.height, target.width, target.height) * .18);
  const minimumCenterX = Math.min(sourceCenter.x, targetCenter.x);
  const maximumCenterX = Math.max(sourceCenter.x, targetCenter.x);
  const corridorObstacles = unrelated.filter((box) => {
    const boxCenterX = box.x + box.width / 2;
    return boxCenterX > minimumCenterX && boxCenterX < maximumCenterX;
  });
  const topLane = Math.min(source.y, target.y, ...corridorObstacles.map((box) => box.y)) - clearance;
  const bottomLane = Math.max(
    source.y + source.height,
    target.y + target.height,
    ...corridorObstacles.map((box) => box.y + box.height),
  ) + clearance;
  const middleX = (sourceCenter.x + targetCenter.x) / 2;
  const middleY = (sourceCenter.y + targetCenter.y) / 2;
  const candidates = [
    [sourceCenter, { x: middleX, y: sourceCenter.y }, { x: middleX, y: targetCenter.y }, targetCenter],
    [sourceCenter, { x: sourceCenter.x, y: middleY }, { x: targetCenter.x, y: middleY }, targetCenter],
    [sourceCenter, { x: sourceCenter.x, y: bottomLane }, { x: targetCenter.x, y: bottomLane }, targetCenter],
    [sourceCenter, { x: sourceCenter.x, y: topLane }, { x: targetCenter.x, y: topLane }, targetCenter],
  ].map(compactPoints);
  const clear = candidates.find((points) =>
    points.slice(1).every((end, index) =>
      unrelated.every((box) => !segmentCrossesBox(points[index]!, end, box, clearance / 3)),
    ),
  ) ?? candidates[0]!;
  const routed = [...clear];
  routed[0] = boundaryPoint(source, routed[1] ?? targetCenter);
  routed[routed.length - 1] = boundaryPoint(target, routed[routed.length - 2] ?? sourceCenter);
  return compactPoints(routed);
}

/** Connects peer network boundaries through their header corridor without routing around child nodes. */
export function architectureNetworkPeeringRoute(
  source: ArchitectureNetworkRouteBox,
  target: ArchitectureNetworkRouteBox,
): readonly ArchitectureNetworkRoutePoint[] {
  const sourceIsLeft = source.x + source.width <= target.x;
  const targetIsLeft = target.x + target.width <= source.x;
  if (!sourceIsLeft && !targetIsLeft) {
    return architectureNetworkOrthogonalRoute(source, target, []);
  }
  const inset = Math.min(32, Math.min(source.height, target.height) * .12);
  const sourceY = source.y + inset;
  const targetY = target.y + inset;
  const start = {
    x: sourceIsLeft ? source.x + source.width : source.x,
    y: sourceY,
  };
  const end = {
    x: sourceIsLeft ? target.x : target.x + target.width,
    y: targetY,
  };
  if (sourceY === targetY) return [start, end];
  const middleX = (start.x + end.x) / 2;
  return [start, { x: middleX, y: sourceY }, { x: middleX, y: targetY }, end];
}

export function architectureNetworkRoutePath(
  points: readonly ArchitectureNetworkRoutePoint[],
): string {
  return points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x} ${point.y}`).join(" ");
}
