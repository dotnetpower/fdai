/**
 * Browser-side conversation index for the command deck.
 *
 * The audit log remains the conversation source of truth. This small index is
 * only a tab-scoped navigation aid: it remembers which cached transcripts are
 * available so the deck can render the same history + new-conversation shell
 * as the design mock.
 */

export const CONVERSATION_INDEX_KEY = "fdai.deck.conversations.v1";
export const GENERAL_CONVERSATION_KEY = "screen";
const DEFAULT_MAX_CONVERSATIONS = 24;

export interface ConversationSummary {
  readonly key: string;
  readonly label: string;
  readonly kind: "general" | "agent";
  readonly agent?: string;
  readonly updatedAt: string;
}

/** Parse the tab-scoped index defensively. */
export function parseConversationIndex(raw: string | null): ConversationSummary[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: ConversationSummary[] = [];
  for (const item of parsed) {
    if (item === null || typeof item !== "object" || Array.isArray(item)) continue;
    const record = item as Record<string, unknown>;
    if (typeof record.key !== "string" || record.key.length === 0) continue;
    if (typeof record.label !== "string" || record.label.length === 0) continue;
    if (record.kind !== "general" && record.kind !== "agent") continue;
    if (typeof record.updatedAt !== "string" || Number.isNaN(Date.parse(record.updatedAt))) {
      continue;
    }
    out.push({
      key: record.key,
      label: record.label,
      kind: record.kind,
      updatedAt: record.updatedAt,
      ...(typeof record.agent === "string" && record.agent.length > 0
        ? { agent: record.agent }
        : {}),
    });
  }
  return out;
}

/** Deduplicate, sort newest-first, and cap the tab-scoped index. */
export function upsertConversation(
  conversations: readonly ConversationSummary[],
  summary: ConversationSummary,
  maxConversations: number = DEFAULT_MAX_CONVERSATIONS,
): ConversationSummary[] {
  if (maxConversations <= 0) return [];
  const ordered = [summary, ...conversations.filter((item) => item.key !== summary.key)]
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt));
  const retained = ordered.slice(0, maxConversations);
  const general = ordered.find((item) => item.key === GENERAL_CONVERSATION_KEY);
  if (general && !retained.some((item) => item.key === GENERAL_CONVERSATION_KEY)) {
    retained[Math.max(0, retained.length - 1)] = general;
  }
  return retained;
}

export function serializeConversationIndex(
  conversations: readonly ConversationSummary[],
): string {
  return JSON.stringify(conversations);
}

/** Build a concise title from the first operator turn. */
export function conversationTitle(prompt: string, maxLength: number = 44): string {
  const normalized = prompt.trim().replace(/\s+/g, " ");
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, Math.max(1, maxLength - 3)).trimEnd()}...`;
}
