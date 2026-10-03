import type { ElkPoint } from "elkjs/lib/elk-api.js";

export const LANE_OVERLAP_TOLERANCE = 6;

export function collinearOverlapLength(
  firstStart: ElkPoint,
  firstEnd: ElkPoint,
  secondStart: ElkPoint,
  secondEnd: ElkPoint,
  tolerance = LANE_OVERLAP_TOLERANCE,
): number {
  if (
    firstStart.y === firstEnd.y &&
    secondStart.y === secondEnd.y &&
    Math.abs(firstStart.y - secondStart.y) <= tolerance
  ) {
    const left = Math.max(
      Math.min(firstStart.x, firstEnd.x),
      Math.min(secondStart.x, secondEnd.x),
    );
    const right = Math.min(
      Math.max(firstStart.x, firstEnd.x),
      Math.max(secondStart.x, secondEnd.x),
    );
    return Math.max(0, right - left);
  }
  if (
    firstStart.x === firstEnd.x &&
    secondStart.x === secondEnd.x &&
    Math.abs(firstStart.x - secondStart.x) <= tolerance
  ) {
    const top = Math.max(
      Math.min(firstStart.y, firstEnd.y),
      Math.min(secondStart.y, secondEnd.y),
    );
    const bottom = Math.min(
      Math.max(firstStart.y, firstEnd.y),
      Math.max(secondStart.y, secondEnd.y),
    );
    return Math.max(0, bottom - top);
  }
  return 0;
}
