/**
 * Scroll-stick helper for the command deck transcript.
 *
 * Pure and DOM-free so it is unit-tested directly. The transcript should
 * follow new content only when the operator is already reading the latest
 * turn; if they have scrolled up to re-read an earlier answer, an arriving
 * reply must NOT yank them back down. `isNearBottom` decides that from raw
 * scroll geometry.
 */

/** Pixels from the bottom within which the transcript is considered "stuck". */
export const STICK_THRESHOLD_PX = 80;

/**
 * True when the scroll position is within `threshold` pixels of the bottom.
 * Guards against sub-pixel rounding so a fully scrolled container always
 * counts as near-bottom.
 */
export function isNearBottom(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  threshold: number = STICK_THRESHOLD_PX,
): boolean {
  const distanceFromBottom = scrollHeight - clientHeight - scrollTop;
  return distanceFromBottom <= threshold;
}
