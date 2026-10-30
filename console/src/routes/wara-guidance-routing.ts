export interface RouteBox { readonly x: number; readonly y: number; readonly width: number; readonly height: number }
export interface EdgeRoute {
  readonly path: string;
  readonly labelX: number;
  readonly labelY: number;
  // "top" and "bottom" pass over or under the nodes in between; "left" bulges around a column; null is direct.
  readonly detour: "top" | "bottom" | "left" | null;
}
export interface RouteOptions {
  // Fractions of the node edge (0..1) where this edge leaves and enters, so edges on one side stay apart.
  readonly startPort?: number;
  readonly endPort?: number;
  readonly topRank?: number;
  readonly bottomRank?: number;
  readonly leftRank?: number;
  // Lower edge of the drawing area; a detour below the nodes is used only when it still fits.
  readonly canvasBottom?: number;
  // Every other node; a direct curve is used only when it stays clear of all of them.
  readonly obstacles?: readonly RouteBox[];
}

type Point = readonly [number, number];
type Curve = readonly [Point, Point, Point, Point];

const ARROW_GAP = 3;
const CLEARANCE = 3;
const SAMPLES = 32;
const LANE_STEP = 8;
const SHOULDER = 36;

const point = (curve: Curve, t: number): Point => {
  const u = 1 - t;
  const weight = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t] as const;
  return [
    weight[0] * curve[0][0] + weight[1] * curve[1][0] + weight[2] * curve[2][0] + weight[3] * curve[3][0],
    weight[0] * curve[0][1] + weight[1] * curve[1][1] + weight[2] * curve[2][1] + weight[3] * curve[3][1],
  ];
};

function clear(curve: Curve, obstacles: readonly RouteBox[]): boolean {
  for (let step = 2; step < SAMPLES - 1; step += 1) {
    const [x, y] = point(curve, step / SAMPLES);
    if (obstacles.some((box) => x > box.x - CLEARANCE && x < box.x + box.width + CLEARANCE && y > box.y - CLEARANCE && y < box.y + box.height + CLEARANCE)) return false;
  }
  return true;
}

const cubic = (curve: Curve): string => `M ${curve[0][0]} ${curve[0][1]} C ${curve[1][0]} ${curve[1][1]}, ${curve[2][0]} ${curve[2][1]}, ${curve[3][0]} ${curve[3][1]}`;

/**
 * Routes one connector as the shortest smooth curve that stays clear of every other node.
 * Side-by-side nodes connect right-to-left, stacked nodes bottom-to-top. A blocked connection
 * detours over the top of the diagram (skipped or returning columns) or around the left edge
 * (stacked nodes with another node between them).
 */
export function guidanceEdgeRoute(from: RouteBox, to: RouteBox, options: RouteOptions = {}): EdgeRoute {
  const { startPort = .5, endPort = .5, topRank = 0, bottomRank = 0, leftRank = 0, canvasBottom = Number.POSITIVE_INFINITY, obstacles = [] } = options;
  const stacked = from.x < to.x + to.width && to.x < from.x + from.width;
  if (stacked) {
    const down = to.y > from.y;
    // Stacked nodes share a vertical stretch, so the connector stays straight up and down.
    const shared = Math.max(from.x, to.x);
    const sx = shared + (Math.min(from.x + from.width, to.x + to.width) - shared) * startPort;
    const ex = sx;
    const sy = down ? from.y + from.height : from.y;
    const ey = down ? to.y - ARROW_GAP : to.y + to.height + ARROW_GAP;
    const reach = (Math.abs(ey - sy) / 2) * (down ? 1 : -1);
    const direct: Curve = [[sx, sy], [sx, sy + reach], [ex, ey - reach], [ex, ey]];
    if (clear(direct, obstacles)) return { path: cubic(direct), labelX: sx + 10, labelY: down ? sy + 15 : sy - 6, detour: null };
    const startY = from.y + from.height * startPort;
    const endY = to.y + to.height * endPort;
    const bulge = 24 + leftRank * LANE_STEP;
    const edgeX = Math.min(from.x, to.x - ARROW_GAP);
    const around: Curve = [[from.x, startY], [edgeX - bulge, startY], [edgeX - bulge, endY], [to.x - ARROW_GAP, endY]];
    return { path: cubic(around), labelX: from.x - 8, labelY: startY - 5, detour: "left" };
  }
  const forward = to.x >= from.x + from.width;
  const dir = forward ? 1 : -1;
  const sx = forward ? from.x + from.width : from.x;
  const ex = forward ? to.x - ARROW_GAP : to.x + to.width + ARROW_GAP;
  const sy = from.y + from.height * startPort;
  const ey = to.y + to.height * endPort;
  const reach = Math.max(24, Math.abs(ex - sx) / 2) * dir;
  const direct: Curve = [[sx, sy], [sx + reach, sy], [ex - reach, ey], [ex, ey]];
  const label = { labelX: sx + dir * 8, labelY: sy - 5 };
  if (clear(direct, obstacles)) return { path: cubic(direct), ...label, detour: null };
  const shoulder = Math.min(SHOULDER, Math.abs(ex - sx) / 3);
  const rise = sx + dir * shoulder;
  const fall = ex - dir * shoulder;
  const half = dir * shoulder / 2;
  const detour = (lane: number): { readonly path: string; readonly pieces: readonly Curve[] } => ({
    path: `M ${sx} ${sy} C ${sx + half} ${sy}, ${rise - half} ${lane}, ${rise} ${lane} H ${fall} C ${fall + half} ${lane}, ${ex - half} ${ey}, ${ex} ${ey}`,
    pieces: [
      [[sx, sy], [sx + half, sy], [rise - half, lane], [rise, lane]],
      [[rise, lane], [rise + (fall - rise) / 3, lane], [rise + 2 * (fall - rise) / 3, lane], [fall, lane]],
      [[fall, lane], [fall + half, lane], [ex - half, ey], [ex, ey]],
    ],
  });
  const low = Math.min(sx, ex);
  const high = Math.max(sx, ex);
  const between = obstacles.filter((box) => box.x + box.width > low && box.x < high);
  const candidates: { readonly lane: number; readonly detour: "top" | "bottom" }[] = [];
  if (between.length > 0) {
    candidates.push({ lane: Math.min(...between.map((box) => box.y)) - 14 - topRank * LANE_STEP, detour: "top" });
    const under = Math.max(...between.map((box) => box.y + box.height)) + 14 + bottomRank * LANE_STEP;
    if (under < canvasBottom - 6) candidates.push({ lane: under, detour: "bottom" });
    candidates.sort((a, b) => Math.abs(a.lane - (sy + ey) / 2) - Math.abs(b.lane - (sy + ey) / 2));
  }
  // The topmost lane clears every node, so a route always exists.
  candidates.push({ lane: Math.min(from.y, to.y, ...obstacles.map((box) => box.y)) - 12 - topRank * LANE_STEP, detour: "top" });
  const chosen = candidates.find((candidate) => detour(candidate.lane).pieces.every((piece) => clear(piece, obstacles))) ?? candidates[candidates.length - 1]!;
  return { path: detour(chosen.lane).path, ...label, detour: chosen.detour };
}
