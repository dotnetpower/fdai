/** Return how many already-paced deltas the UI may paint in one frame. */
export function streamPaintBatchSize(backlog: number): number {
  if (backlog > 24) return 3;
  if (backlog > 8) return 2;
  return 1;
}

/** Drain one visual frame while preserving byte-for-byte answer order. */
export function drainStreamPaint(queue: string[]): string {
  return queue.splice(0, streamPaintBatchSize(queue.length)).join("");
}

/** Return whether terminal completion must not wait for display frames. */
export function shouldFlushStreamPaintSynchronously(
  visibilityState: string,
  focused: boolean,
): boolean {
  return visibilityState === "hidden" || !focused;
}

/** Drain every paced delta when no visible frame can be relied on. */
export function flushStreamPaint(queue: string[]): string {
  return queue.splice(0).join("");
}

/** Split a terminal-only canonical answer into bounded visual deltas. This is
 * presentation pacing only: joining the chunks reproduces the received answer
 * byte-for-byte. */
export function terminalRevealChunks(text: string): string[] {
  return text.match(/\S+\s*/g) ?? (text.length > 0 ? [text] : []);
}
