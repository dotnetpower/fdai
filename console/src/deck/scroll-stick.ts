/**
 * Scroll follow rules for the command deck transcript.
 *
 * Pure and DOM-free so it is unit-tested directly. A live turn follows new content without lifting
 * the question being answered above the top edge, so the text someone is reading holds still. When
 * the turn settles, the view moves just far enough to show the verification row. Any scroll the
 * follower did not make itself stops the follow, unless it lands on the bottom, which follows the
 * newest content instead.
 */

/** Pixels from the bottom within which the transcript counts as being at the newest content. */
export const FOLLOW_BOTTOM_PX = 32;
/** Room kept above a pinned question. */
export const FOLLOW_PIN_GAP_PX = 12;
/** Room kept below a revealed verification row. */
export const FOLLOW_REVEAL_GAP_PX = 16;
/** Content further than this below the visible edge offers Jump to latest. */
export const JUMP_CONTENT_PX = 8;

/** `pin` holds the question being answered at the top edge; `bottom` follows the newest content. */
export type FollowMode = "pin" | "bottom";

export interface FollowState {
  readonly following: boolean;
  readonly mode: FollowMode;
  /** The last position the follower set or observed, in scroll pixels. */
  readonly expected: number;
}

export interface FollowGeometry {
  readonly maxScrollTop: number;
  readonly clientHeight: number;
  /** Top of the pinned question in scroll-content pixels, or null when nothing is pinned. */
  readonly pinTop: number | null;
  /** Bottom of the settled turn's verification row in scroll-content pixels, or null. */
  readonly revealBottom: number | null;
}

/**
 * True when the scroll position is within `threshold` pixels of the bottom. Guards against
 * sub-pixel rounding so a fully scrolled container always counts as at the bottom.
 */
export function isNearBottom(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  threshold: number = FOLLOW_BOTTOM_PX,
): boolean {
  return scrollHeight - clientHeight - scrollTop <= threshold;
}

/** Where a following transcript rests. */
export function followTargetScrollTop(mode: FollowMode, geometry: FollowGeometry): number {
  const max = Math.max(0, geometry.maxScrollTop);
  if (mode === "bottom" || geometry.pinTop === null) return max;
  let target = Math.min(max, geometry.pinTop - FOLLOW_PIN_GAP_PX);
  if (geometry.revealBottom !== null) {
    const reveal = geometry.revealBottom + FOLLOW_REVEAL_GAP_PX - geometry.clientHeight;
    target = Math.max(target, Math.min(max, reveal));
  }
  return Math.max(0, target);
}

/**
 * The next scroll position for a follower: it only moves toward newer content, never back over
 * text the operator may be reading. Returns null when no move is needed.
 */
export function followStepScrollTop(
  state: FollowState,
  scrollTop: number,
  target: number,
): number | null {
  if (!state.following || target <= scrollTop + 0.5) return null;
  return target;
}

/**
 * Classify a scroll event. The follower's own move, or a clamp between its last position and its
 * target after content shrinks, keeps the follow. Anything else is the reader moving the view: the
 * follow stops unless the reader lands on the bottom, which follows the newest content.
 */
export function followAfterScroll(
  state: FollowState,
  scrollTop: number,
  target: number,
  atBottom: boolean,
): FollowState {
  if (Math.abs(scrollTop - state.expected) <= 1) return state;
  const onCourse = state.following &&
    scrollTop >= Math.min(state.expected, target) - 2 &&
    scrollTop <= target + 2;
  if (onCourse) return { ...state, expected: scrollTop };
  return { following: atBottom, mode: atBottom ? "bottom" : state.mode, expected: scrollTop };
}

/** Jump to latest appears only when real content sits below the visible edge. */
export function jumpToLatestVisible(distanceToBottom: number, contentBelowPx: number): boolean {
  return distanceToBottom > FOLLOW_BOTTOM_PX && contentBelowPx > JUMP_CONTENT_PX;
}

export interface CompletedWorkRevealTarget {
  readonly turnId: string;
  readonly childSelector: string;
}

/** A settled turn reveals its verification row; incident choices sit above it in the same reply. */
export function completedWorkRevealTarget(deckTurnId: string): CompletedWorkRevealTarget {
  return { turnId: deckTurnId, childSelector: ".deck-gr-actions" };
}
