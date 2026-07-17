import type { ProgressiveAnswer } from "./backend";
import type { ConversationTurnPayload } from "../user-context-client";

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
    : "floating";
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

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function sessionIdFor(
  sessions: Map<string, string>,
  sessionKey: string,
  create: () => string = newId,
): string {
  const existing = sessions.get(sessionKey);
  if (existing) return existing;
  const created = create();
  sessions.set(sessionKey, created);
  return created;
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
  if (
    reply.verification?.status === "corrected" ||
    reply.verification?.status === "unverified"
  ) {
    return "Bragi";
  }
  return reply.delegation?.primary_agent ?? "Bragi";
}
