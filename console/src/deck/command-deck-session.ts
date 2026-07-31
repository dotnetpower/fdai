import type { ProgressiveAnswer } from "./backend";
import type { ConversationTurnPayload } from "../user-context-client";

const MAX_SESSION_ID_CHARS = 200;

export interface RestoredTurn {
  readonly id: string;
  readonly role: "operator" | "deck";
  readonly text: string;
  readonly source?: string;
  readonly terminal: boolean;
  readonly agent?: string;
  readonly at: string;
}

export type DeckLayoutMode = "floating" | "dock" | "workspace";

export function parseDeckLayoutMode(value: string | null): DeckLayoutMode {
  return value === "dock" || value === "workspace" || value === "floating"
    ? value
    : "dock";
}

export function clampDockWidth(value: number, viewportWidth: number): number {
  const maximum = Math.max(340, Math.min(720, viewportWidth - 320));
  return Math.round(Math.max(340, Math.min(maximum, value)));
}

export function restoredTurn(turn: ConversationTurnPayload): RestoredTurn {
  const at = new Date(turn.recorded_at);
  const time = Number.isNaN(at.getTime())
    ? turn.recorded_at
    : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const source = turn.metadata.source ?? (turn.role === "assistant" ? "history" : undefined);
  return {
    id: turn.turn_id,
    role: turn.role === "operator" ? "operator" : "deck",
    text: turn.content,
    at: time,
    terminal: true,
    ...(source ? { source } : {}),
    ...(turn.metadata.agent ? { agent: turn.metadata.agent } : {}),
  };
}

export function sessionIdFor(
  sessions: Map<string, string>,
  sessionKey: string,
  create: () => string = () => boundedSessionId(sessionKey),
): string {
  const existing = sessions.get(sessionKey);
  if (existing) return existing;
  const created = create();
  sessions.set(sessionKey, created);
  return created;
}

function boundedSessionId(sessionKey: string): string {
  if (sessionKey.length <= MAX_SESSION_ID_CHARS) return sessionKey;
  let hash = 0x811c9dc5;
  for (let index = 0; index < sessionKey.length; index += 1) {
    hash ^= sessionKey.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  const suffix = (hash >>> 0).toString(16).padStart(8, "0");
  return `${sessionKey.slice(0, MAX_SESSION_ID_CHARS - suffix.length - 1)}:${suffix}`;
}

export function clearScheduledTimeouts(
  timers: Set<number>,
  clear: (timer: number) => void = (timer) => window.clearTimeout(timer),
): void {
  for (const timer of timers) clear(timer);
  timers.clear();
}

export function matchingTurnIndexes(
  turns: readonly { readonly text: string }[],
  rawQuery: string,
): number[] {
  const query = rawQuery.trim().toLowerCase();
  if (!query) return [];
  return turns.flatMap((turn, index) =>
    turn.text.toLowerCase().includes(query) ? [index] : [],
  );
}

export function replyAgent(
  reply: Pick<ProgressiveAnswer, "delegation" | "verification">,
): string {
  return reply.delegation?.primary_agent ?? "Bragi";
}

export function provisionalReplyAgent(targetAgent: string | undefined): string {
  return targetAgent ?? "Bragi";
}

export function replyAgentLabel(
  agent: string,
  delegation: ProgressiveAnswer["delegation"],
): string {
  const handoffFrom = delegation?.handoff_from;
  return handoffFrom && handoffFrom !== agent
    ? `${handoffFrom} -> ${agent}`
    : agent;
}
