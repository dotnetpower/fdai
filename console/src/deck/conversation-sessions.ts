import type { IncidentConversationBinding } from "./open-deck";
import { PANTHEON } from "../routes/agents.model";

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
const PANTHEON_AGENT_NAMES = new Set(PANTHEON.map((agent) => agent.name));

/** Produce a stable, non-identifying browser scope for one signed-in user. */
export function conversationUserScope(identity: string | null, devMode: boolean): string {
  const normalized = (identity?.trim().toLowerCase() || (devMode ? "dev" : "anonymous"));
  let hash = 0x811c9dc5;
  for (let index = 0; index < normalized.length; index += 1) {
    hash ^= normalized.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

/** Normalize a route pathname for conversation ownership; query is excluded. */
export function conversationPath(pathname: string): string {
  const pathOnly = pathname.split(/[?#]/, 1)[0] ?? "";
  const withLeadingSlash = pathOnly.startsWith("/") ? pathOnly : `/${pathOnly}`;
  const normalized = withLeadingSlash.replace(/\/+/g, "/").replace(/\/$/, "");
  return normalized === "" ? "/" : normalized.toLowerCase();
}

/** One default Command Deck conversation per user and canonical menu URL. */
export function screenConversationKey(userScope: string, pathname: string): string {
  return `screen:${userScope}:${conversationPath(pathname)}`;
}

export function isScreenConversationKey(key: string): boolean {
  return key === GENERAL_CONVERSATION_KEY || key.startsWith("screen:");
}

/** Scope explicit agent or manually-created conversation keys to one user. */
export function userConversationKey(userScope: string, key: string): string {
  const prefix = `user:${userScope}:`;
  return key.startsWith(prefix) ? key : `${prefix}${key}`;
}

/** Keep the browser conversation index isolated when accounts change in one tab. */
export function conversationIndexKeyFor(userScope: string): string {
  return `${CONVERSATION_INDEX_KEY}::${userScope}`;
}

export interface ConversationSummary {
  readonly key: string;
  readonly label: string;
  readonly kind: "screen-default" | "screen-thread" | "agent";
  readonly agent?: string;
  readonly originPath: string;
  readonly originLabel: string;
  readonly createdAt: string;
  readonly updatedAt: string;
  readonly binding?: IncidentConversationBinding;
}

export interface ConversationGroups {
  readonly current: readonly ConversationSummary[];
  readonly other: readonly ConversationSummary[];
  readonly agents: readonly ConversationSummary[];
}

export function screenConversationSummary(
  key: string,
  pathname: string,
  routeLabel: string,
  now: string,
  previous?: ConversationSummary,
): ConversationSummary {
  return {
    key,
    label: routeLabel,
    kind: "screen-default",
    originPath: conversationPath(pathname),
    originLabel: routeLabel,
    createdAt: previous?.createdAt ?? now,
    updatedAt: previous?.updatedAt ?? now,
  };
}

export function manualConversationSummary(
  key: string,
  pathname: string,
  routeLabel: string,
  now: string,
  label: string,
): ConversationSummary {
  return {
    key,
    label,
    kind: "screen-thread",
    originPath: conversationPath(pathname),
    originLabel: routeLabel,
    createdAt: now,
    updatedAt: now,
  };
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
    if (
      record.kind !== "general" &&
      record.kind !== "screen-default" &&
      record.kind !== "screen-thread" &&
      record.kind !== "agent"
    ) continue;
    if (typeof record.updatedAt !== "string" || Number.isNaN(Date.parse(record.updatedAt))) {
      continue;
    }
    const kind = record.kind === "general"
      ? (isScreenConversationKey(record.key) ? "screen-default" : "screen-thread")
      : record.kind;
    const originPath = typeof record.originPath === "string"
      ? conversationPath(record.originPath)
      : legacyOriginPath(record.key, record.label);
    const originLabel = typeof record.originLabel === "string" && record.originLabel.length > 0
      ? record.originLabel
      : originPath;
    const createdAt = typeof record.createdAt === "string" && !Number.isNaN(Date.parse(record.createdAt))
      ? record.createdAt
      : record.updatedAt;
    out.push({
      key: record.key,
      label: record.label,
      kind,
      originPath,
      originLabel,
      createdAt,
      updatedAt: record.updatedAt,
      ...(typeof record.agent === "string" && record.agent.length > 0
        ? { agent: record.agent }
        : {}),
      ...(parseIncidentBinding(record.binding) ?? {}),
    });
  }
  return out;
}

export function normalizeIncidentBinding(value: unknown): IncidentConversationBinding | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const incidentId = typeof record.incidentId === "string" ? record.incidentId.trim() : "";
  const correlationId = typeof record.correlationId === "string"
    ? record.correlationId.trim()
    : "";
  if (
    record.kind !== "incident" ||
    incidentId.length === 0 ||
    incidentId.length > 256 ||
    correlationId.length === 0 ||
    correlationId.length > 256
  ) return null;
  const selectedAgent = typeof record.selectedAgent === "string"
    ? record.selectedAgent.trim()
    : "";
  return {
    kind: "incident",
    incidentId,
    correlationId,
    ...(PANTHEON_AGENT_NAMES.has(selectedAgent) ? { selectedAgent } : {}),
  };
}

function parseIncidentBinding(value: unknown): { readonly binding: IncidentConversationBinding } | null {
  const binding = normalizeIncidentBinding(value);
  return binding === null ? null : { binding };
}

/** Split the flat cache index into the three operator-facing sections. */
export function conversationGroups(
  conversations: readonly ConversationSummary[],
  pathname: string,
): ConversationGroups {
  const currentPath = conversationPath(pathname);
  const newestFirst = (items: readonly ConversationSummary[]) =>
    [...items].sort((left, right) => Date.parse(right.updatedAt) - Date.parse(left.updatedAt));
  return {
    current: newestFirst(
      conversations.filter(
        (item) => item.kind !== "agent" && item.originPath === currentPath,
      ),
    ),
    other: newestFirst(
      conversations.filter(
        (item) => item.kind !== "agent" && item.originPath !== currentPath,
      ),
    ),
    agents: newestFirst(conversations.filter((item) => item.kind === "agent")),
  };
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
  const screen = ordered.find((item) => isScreenConversationKey(item.key));
  if (screen && !retained.some((item) => item.key === screen.key)) {
    retained[Math.max(0, retained.length - 1)] = screen;
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

export function conversationLabelForPrompt(
  summary: ConversationSummary,
  prompt: string,
  hasOperatorTurn: boolean,
): string {
  if (summary.agent) return summary.agent;
  if (summary.kind === "screen-thread" && !hasOperatorTurn) {
    return conversationTitle(prompt);
  }
  return summary.label;
}

function legacyOriginPath(key: string, label: string): string {
  if (key.startsWith("screen:")) {
    const scopeSeparator = key.indexOf(":", "screen:".length);
    if (scopeSeparator >= 0) return conversationPath(key.slice(scopeSeparator + 1));
  }
  return label.startsWith("/") ? conversationPath(label) : "/";
}
