import type { ElkPoint } from "elkjs/lib/elk-api.js";

export interface CubicCurve {
  start: ElkPoint;
  control1: ElkPoint;
  control2: ElkPoint;
  end: ElkPoint;
}

export function cubicCurve(start: ElkPoint, end: ElkPoint): CubicCurve {
  const deltaX = end.x - start.x;
  const deltaY = end.y - start.y;
  if (Math.abs(deltaX) > Math.abs(deltaY) * 2) {
    return {
      start,
      control1: { x: start.x + deltaX * 0.42, y: start.y },
      control2: { x: end.x - deltaX * 0.42, y: end.y },
      end,
    };
  }
  return {
    start,
    control1: { x: start.x, y: start.y + deltaY * 0.42 },
    control2: { x: end.x, y: end.y - deltaY * 0.42 },
    end,
  };
}

export function pointOnCubic(curve: CubicCurve, progress: number): ElkPoint {
  const inverse = 1 - progress;
  return {
    x:
      inverse ** 3 * curve.start.x +
      3 * inverse ** 2 * progress * curve.control1.x +
      3 * inverse * progress ** 2 * curve.control2.x +
      progress ** 3 * curve.end.x,
    y:
      inverse ** 3 * curve.start.y +
      3 * inverse ** 2 * progress * curve.control1.y +
      3 * inverse * progress ** 2 * curve.control2.y +
      progress ** 3 * curve.end.y,
  };
}

export function sampleCubic(
  start: ElkPoint,
  end: ElkPoint,
  segments = 24,
): ElkPoint[] {
  const curve = cubicCurve(start, end);
  return Array.from({ length: segments + 1 }, (_, index) =>
    pointOnCubic(curve, index / segments),
  );
}
