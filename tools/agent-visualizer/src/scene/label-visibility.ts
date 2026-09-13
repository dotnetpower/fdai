const REVEAL_DISTANCE = 44;
const FULL_DISTANCE = 22;
export const LABEL_INTERACTION_OPACITY = 0.5;

/** Angular scale, not activity, reveals optional source annotations as the camera approaches. */
export function functionLabelOpacity(distance: number, zoom = 1): number {
  const progress = Math.max(0, Math.min(1, (REVEAL_DISTANCE - distance / zoom) / (REVEAL_DISTANCE - FULL_DISTANCE)));
  return progress * progress * (3 - 2 * progress);
}

/** Smooth manual zoom steps as well as camera travel; reduced motion uses the static target. */
export function approachLabelOpacity(current: number, target: number, delta: number, reduced: boolean): number {
  if (reduced) return target;
  const next = current + (target - current) * (1 - Math.exp(-Math.max(0, delta) * 10));
  return Math.abs(next - target) < 0.002 ? target : next;
}
