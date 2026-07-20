import { loadConfig } from "../config";
import {
  consumeLiveSse,
  type LiveStageEvent,
  type LiveStageName,
} from "../hooks/use-live-stream";
import { chatRequestHeaders } from "./auth";

const STAGE_ORDER: readonly LiveStageName[] = [
  "ingest",
  "route",
  "verify",
  "gate",
  "execute",
  "audit",
];
const STAGE_AGENT: Readonly<Record<LiveStageName, string>> = {
  ingest: "Huginn",
  route: "Forseti",
  verify: "Forseti",
  gate: "Forseti",
  execute: "Thor",
  audit: "Saga",
};

export interface ActionProgressSnapshot {
  readonly text: string;
  readonly terminal: boolean;
}

export function formatActionProgress(
  correlationId: string,
  events: ReadonlyMap<LiveStageName, LiveStageEvent>,
): ActionProgressSnapshot {
  const lines = [`Tracking ${correlationId}`];
  let terminal = false;
  for (const stage of STAGE_ORDER) {
    const event = events.get(stage);
    if (!event) continue;
    const state = event.phase === "done"
      ? "complete"
      : event.phase === "failed"
        ? `failed${event.error ? `: ${event.error}` : ""}`
        : event.phase;
    const detail = progressDetail(event.detail);
    lines.push(`- ${STAGE_AGENT[stage]} · ${stage}: ${state}${detail ? ` · ${detail}` : ""}`);
    if (stage === "audit" && (event.phase === "done" || event.phase === "failed")) {
      terminal = true;
    }
  }
  return { text: lines.join("\n"), terminal };
}

export async function watchActionProgress(
  correlationId: string,
  onSnapshot: (snapshot: ActionProgressSnapshot) => void,
  timeoutMs: number = 120_000,
): Promise<void> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const events = new Map<LiveStageName, LiveStageEvent>();
  const config = loadConfig();
  const base = config.readApiBaseUrl || window.location.origin;
  try {
    const headers = await chatRequestHeaders();
    const response = await fetch(`${base.replace(/\/$/, "")}/live/stream`, {
      method: "GET",
      headers: { ...headers, accept: "text/event-stream" },
      credentials: "omit",
      signal: controller.signal,
    });
    await consumeLiveSse(response, (event) => {
      if (event.correlation_id !== correlationId) return;
      events.set(event.stage, event);
      const snapshot = formatActionProgress(correlationId, events);
      onSnapshot(snapshot);
      if (snapshot.terminal) controller.abort();
    });
  } catch (error) {
    if (!controller.signal.aborted) throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function progressDetail(detail: Record<string, unknown> | undefined): string {
  if (!detail) return "";
  for (const key of ["outcome", "gate_decision", "decision", "routed_to", "mode"]) {
    const value = detail[key];
    if (typeof value === "string" && value) return `${key}=${value}`;
  }
  return "";
}
