const RESUME_THRESHOLD_MS = 5_000;

export function resumedConversationAt(
  turns: readonly { readonly recordedAt?: string }[],
  openedAtMs: number,
): string | null {
  for (let index = turns.length - 1; index >= 0; index -= 1) {
    const recordedAt = turns[index]?.recordedAt;
    if (!recordedAt) continue;
    const recordedMs = Date.parse(recordedAt);
    if (!Number.isFinite(recordedMs)) continue;
    return recordedMs <= openedAtMs - RESUME_THRESHOLD_MS ? recordedAt : null;
  }
  return null;
}
