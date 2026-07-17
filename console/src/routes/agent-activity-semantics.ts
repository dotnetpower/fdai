import type { PillKind } from "../components/ui";
import type { AuditItem } from "../types";

const AGENT_LAYER: Readonly<Record<string, string>> = {
  Odin: "planning",
  Thor: "execution",
  Forseti: "judgment",
  Huginn: "sensing",
  Heimdall: "sensing",
  Var: "approval",
  Vidar: "recovery",
  Bragi: "conversational",
  Saga: "audit",
  Mimir: "governance",
  Norns: "governance",
  Muninn: "governance",
  Njord: "domain",
  Freyr: "domain",
  Loki: "domain",
};

export function agentOf(item: AuditItem): string {
  const principal = item.entry["producer_principal"];
  if (typeof principal === "string" && principal.trim()) {
    return principal in AGENT_LAYER ? principal : principal.trim();
  }
  if (item.actor in AGENT_LAYER) return item.actor;
  const semanticOwner = semanticAgentOwner(item);
  if (semanticOwner !== null) return semanticOwner;
  if (item.actor && item.actor.trim()) return humanizeActor(item.actor);
  return "System";
}

function semanticAgentOwner(item: AuditItem): string | null {
  if (!item.actor.startsWith("fdai.")) return null;
  const actionKind = item.action_kind.toLowerCase();
  const stage = typeof item.entry["stage"] === "string"
    ? item.entry["stage"].toLowerCase()
    : "";
  if (actionKind.startsWith("hil.") || item.actor === "fdai.core.hil_resume") return "Var";
  if (actionKind.startsWith("risk_gate.")) return "Forseti";
  if (actionKind.startsWith("rca.") || item.actor === "fdai.core.rca") return "Forseti";
  if (actionKind.startsWith("governance.")) return "Mimir";
  if (actionKind.startsWith("measurement.pattern_growth")) return "Norns";
  if (actionKind.startsWith("control_loop.")) {
    return stage === "trust_router" ? "Heimdall" : "Forseti";
  }
  return null;
}

function humanizeActor(actor: string): string {
  const parts = actor.split(".");
  if (parts.length >= 2 && parts[0] === "fdai") return parts.slice(1).join(".");
  return actor;
}

export function isAgentActivitySelectionValid(
  selected: string | null,
  observedAgents: readonly string[],
): boolean {
  return selected === null || selected in AGENT_LAYER || observedAgents.includes(selected);
}

export function agentActivityRank(label: string): number {
  return label === "System" ? 2 : label in AGENT_LAYER ? 0 : 1;
}

export function layerOf(agent: string): string {
  return AGENT_LAYER[agent] ?? "system";
}

export function outcomeOf(item: AuditItem): string | null {
  const outcome = item.entry["outcome"];
  return typeof outcome === "string" ? outcome : null;
}

export function summaryOf(item: AuditItem): string | null {
  const summary = item.entry["summary"];
  return typeof summary === "string" ? summary : null;
}

export function tierOf(item: AuditItem): string | null {
  const tier = item.entry["tier"];
  return typeof tier === "string" ? tier.toUpperCase() : null;
}

export function outcomePill(outcome: string): PillKind {
  if (outcome.includes("hil") || outcome.includes("await")) return "hil";
  if (outcome.includes("escalat")) return "warning";
  if (outcome === "auto") return "auto";
  if (outcome.includes("pr_opened") || outcome.includes("recorded")) return "success";
  if (outcome.includes("matched") || outcome.includes("normalized")) return "info";
  return "neutral";
}

export function modePill(mode: string): PillKind {
  if (mode === "enforce") return "enforce";
  if (mode === "shadow") return "shadow";
  return "neutral";
}

export function milliseconds(iso: string): number {
  const value = new Date(iso).getTime();
  return Number.isNaN(value) ? 0 : value;
}

export function entryStr(item: AuditItem, key: string): string | null {
  const value = item.entry[key];
  return typeof value === "string" ? value : null;
}

export function entryNum(item: AuditItem, key: string): number | null {
  const value = item.entry[key];
  return typeof value === "number" ? value : null;
}

export function entryMap(
  item: AuditItem,
  key: string,
): ReadonlyArray<readonly [string, string]> | null {
  const value = item.entry[key];
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const pairs = Object.entries(value as Record<string, unknown>)
    .filter((entry): entry is [string, string] => typeof entry[1] === "string");
  return pairs.length > 0 ? pairs : null;
}

export interface AgentTurn {
  readonly from: string;
  readonly to: string;
  readonly text: string;
}

export function entryConversation(item: AuditItem): readonly AgentTurn[] | null {
  const value = item.entry["conversation"];
  if (!Array.isArray(value)) return null;
  const turns = value.filter(
    (turn): turn is AgentTurn =>
      turn !== null &&
      typeof turn === "object" &&
      typeof (turn as AgentTurn).from === "string" &&
      typeof (turn as AgentTurn).to === "string" &&
      typeof (turn as AgentTurn).text === "string",
  );
  return turns.length > 0 ? turns : null;
}

const SHOWN_ENTRY_KEYS: ReadonlySet<string> = new Set([
  "event_ts", "received_at", "started_at", "finished_at", "duration_ms", "queue_ms",
  "detail", "summary", "inputs", "outputs", "conversation",
  "tier", "outcome", "decision", "pipeline_stage", "reason",
  "producer_principal", "action_kind", "correlation_id", "recorded_at", "event_id",
  "actor", "mode",
]);

function fmtScalar(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function fmtEntryValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(fmtScalar).join(", ");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => `${key}: ${fmtScalar(nested)}`)
      .join(" · ");
  }
  return String(value);
}

export function otherEntryFields(item: AuditItem): ReadonlyArray<readonly [string, string]> {
  return Object.entries(item.entry)
    .filter(([key, value]) =>
      !SHOWN_ENTRY_KEYS.has(key) && value !== null && value !== undefined && value !== "")
    .map(([key, value]) => [key, fmtEntryValue(value)] as const)
    .filter(([, value]) => value !== "");
}

export function clockMs(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const value = String(date.getMilliseconds()).padStart(3, "0");
  return `${clock(iso)}.${value}`;
}

function clock(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");
  return `${hours}:${minutes}:${seconds}`;
}

export function startClockOf(item: AuditItem): string {
  return clock(entryStr(item, "started_at") ?? item.recorded_at);
}

export function fmtDur(millis: number): string {
  if (millis <= 0) return "0s";
  if (millis < 1000) return `${Math.round(millis)}ms`;
  const totalSeconds = Math.round(millis / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  if (seconds === 0) return `${minutes}m`;
  return `${minutes}m ${seconds}s`;
}

export interface LifecyclePhase {
  readonly key: string;
  readonly label: string;
  readonly iso: string | null;
  readonly gapLabel: string | null;
}

export function lifecycleOf(item: AuditItem): readonly LifecyclePhase[] {
  const raw: readonly (readonly [string, string, string | null])[] = [
    ["sent", "Event sent", entryStr(item, "event_ts")],
    ["received", "Received", entryStr(item, "received_at")],
    ["started", "Work started", entryStr(item, "started_at")],
    ["finished", "Finished", entryStr(item, "finished_at") ?? item.recorded_at],
  ];
  const present = raw.filter((row) => row[2] !== null) as (readonly [string, string, string])[];
  return present.map(([key, label, iso], index) => {
    const previous = index > 0 ? present[index - 1]![2] : null;
    const gap = previous !== null ? milliseconds(iso) - milliseconds(previous) : null;
    return {
      key,
      label,
      iso,
      gapLabel: gap === null ? null : gap <= 0 ? "0s" : `+${fmtDur(gap)}`,
    };
  });
}
