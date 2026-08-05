const CONVERSATION_WIDTH_KEY = "fdai.deck.conversation-width.v1";

export const CONVERSATION_WIDTH_MIN = 180;
export const CONVERSATION_WIDTH_MAX = 360;
export const CONVERSATION_WIDTH_DEFAULT = 240;

export function clampConversationWidth(value: number): number {
  return Math.min(CONVERSATION_WIDTH_MAX, Math.max(CONVERSATION_WIDTH_MIN, value));
}

export function initialConversationWidth(): number {
  if (typeof window === "undefined") return CONVERSATION_WIDTH_DEFAULT;
  try {
    const stored = Number.parseInt(window.localStorage.getItem(CONVERSATION_WIDTH_KEY) ?? "", 10);
    return clampConversationWidth(
      Number.isFinite(stored) ? stored : CONVERSATION_WIDTH_DEFAULT,
    );
  } catch {
    return CONVERSATION_WIDTH_DEFAULT;
  }
}

export function saveConversationWidth(value: number): void {
  try {
    window.localStorage.setItem(CONVERSATION_WIDTH_KEY, String(value));
  } catch {
    /* best-effort preference */
  }
}
