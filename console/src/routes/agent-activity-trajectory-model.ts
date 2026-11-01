/**
 * Agent trajectories projected from retained durable audit records.
 *
 * One trajectory groups the audit steps that share a correlation id, in recorded order. Step
 * categories, phases, and tones derive only from recorded fields; a phase without records stays
 * unrecorded rather than inferred as skipped, and no terminal completion is asserted beyond the
 * recorded outcome. This is a read-only presentation projection, not a governed trajectory export.
 */

import type { AuditItem } from "../types";
import {
  auditProvenanceOf,
  entryConversation,
  entryMap,
  entryNum,
  entryStr,
  isSagaAuditMirror,
  otherEntryFields,
  tierOf,
  type AgentTurn,
} from "./agent-activity-semantics";

export type TrajectoryStepCategory =
  | "intake"
  | "evidence"
  | "decision"
  | "risk"
  | "approval"
  | "action"
  | "recovery"
  | "verification"
  | "record"
  | "activity";

export type TrajectoryTone = "neutral" | "good" | "attention" | "bad";

export type TrajectoryPhaseId =
  | "intake"
  | "evidence"
  | "judgment"
  | "authorization"
  | "execution"
  | "outcome";

export type TrajectoryPhaseState = "recorded" | "attention" | "failed" | "unrecorded";

export interface TrajectoryStep {
  readonly seq: number;
  readonly eventId: string;
  readonly agent: string;
  readonly category: TrajectoryStepCategory;
  readonly actionKind: string;
  readonly summary: string;
  readonly recordedAt: string;
  readonly startMs: number;
  readonly endMs: number;
  readonly durationMs: number | null;
  readonly mode: string;
  readonly tier: string | null;
  readonly outcome: string | null;
  readonly decision: string | null;
  readonly reason: string | null;
  readonly resource: string | null;
  readonly inputs: ReadonlyArray<readonly [string, string]> | null;
  readonly outputs: ReadonlyArray<readonly [string, string]> | null;
  readonly conversation: readonly AgentTurn[] | null;
  readonly fields: ReadonlyArray<readonly [string, string]>;
  readonly tone: TrajectoryTone;
  readonly entryHash: string;
  readonly previousHash: string;
  readonly sample: boolean;
}

export interface AgentTrajectory {
  readonly correlationId: string;
  readonly title: string;
  readonly steps: readonly TrajectoryStep[];
  readonly agents: readonly string[];
  readonly startMs: number;
  readonly endMs: number;
  readonly latestOutcome: string | null;
  readonly tone: TrajectoryTone;
  readonly tiers: readonly string[];
  readonly modes: readonly string[];
  readonly handoffs: number;
  readonly flaggedSteps: number;
  readonly sampleSteps: number;
}

export interface TrajectoryPhase {
  readonly id: TrajectoryPhaseId;
  readonly state: TrajectoryPhaseState;
  readonly steps: number;
}

export interface TrajectoryScale {
  readonly x: (ms: number) => number;
  readonly breaks: readonly { readonly left: number; readonly realMs: number }[];
}

const PHASE_CATEGORIES: ReadonlyArray<readonly [TrajectoryPhaseId, readonly TrajectoryStepCategory[]]> = [
  ["intake", ["intake"]],
  ["evidence", ["evidence"]],
  ["judgment", ["decision", "risk"]],
  ["authorization", ["approval"]],
  ["execution", ["action", "recovery"]],
  ["outcome", ["verification", "record"]],
];

const BAD_OUTCOME = /\b(fail|failed|failure|error|errored|reject|rejected|deny|denied|timeout|timed_out)\b/;
const ATTENTION_OUTCOME = /\b(hil|await|awaiting|pending|escalat\w*|abstain\w*|partial|hold|held|blocked|degraded)\b/;
const GOOD_OUTCOME = /\b(completed|succeeded|success|verified|approved|passed|resolved|compliant)\b/;

/** Groups durable audit records into correlation trajectories, newest activity first. */
export function buildAgentTrajectories(
  items: readonly AuditItem[],
  agentOf: (item: AuditItem) => string,
): readonly AgentTrajectory[] {
  const groups = new Map<string, AuditItem[]>();
  for (const item of items) {
    const resolvedCorrelation =
      (item.correlation_id !== null && item.correlation_id.trim()
        ? item.correlation_id.trim()
        : null) ??
      entryStr(item, "correlation_id") ??
      entryStr(item, "incident_id");
    if (resolvedCorrelation === null || !resolvedCorrelation.trim()) continue;
    if (item.action_kind === "startup_readiness.audit_probe") continue;
    const bucket = groups.get(resolvedCorrelation) ?? [];
    bucket.push(item);
    groups.set(resolvedCorrelation, bucket);
  }
  const trajectories: AgentTrajectory[] = [];
  for (const [correlationId, bucket] of groups) {
    const steps = bucket
      .map((item) => stepOf(item, agentOf))
      .filter((step): step is TrajectoryStep => step !== null)
      .sort((left, right) => left.endMs - right.endMs || left.seq - right.seq);
    if (steps.length === 0) continue;
    trajectories.push(trajectoryOf(correlationId, steps));
  }
  return trajectories.sort((left, right) => {
    const leftBucket = trajectorySortBucket(left);
    const rightBucket = trajectorySortBucket(right);
    return leftBucket - rightBucket ||
      right.endMs - left.endMs ||
      left.correlationId.localeCompare(right.correlationId);
  });
}

function trajectorySortBucket(trajectory: AgentTrajectory): number {
  if (trajectory.steps.length > 1) return 0;
  if (trajectory.steps[0]?.actionKind !== "audit.record") return 1;
  return 2;
}

/** Count of retained audit records that cannot join a trajectory because they lack a correlation. */
export function uncorrelatedAuditCount(items: readonly AuditItem[]): number {
  return items.filter((item) => {
    const resolved =
      (item.correlation_id !== null && item.correlation_id.trim()
        ? item.correlation_id.trim()
        : null) ??
      entryStr(item, "correlation_id") ??
      entryStr(item, "incident_id");
    return resolved === null || !resolved.trim();
  }).length;
}

export function filterAgentTrajectories(
  trajectories: readonly AgentTrajectory[],
  agent: string | null,
  query: string,
): readonly AgentTrajectory[] {
  const needle = normalize(query);
  return trajectories.filter((trajectory) => {
    if (agent !== null && !trajectory.steps.some((step) =>
      step.agent === agent ||
      (step.conversation ?? []).some((turn) => turn.from === agent || turn.to === agent))) {
      return false;
    }
    if (!needle) return true;
    return normalize([
      trajectory.correlationId,
      ...trajectory.steps.flatMap((step) => [
        step.agent,
        step.actionKind,
        step.summary,
        step.outcome,
        step.decision,
        step.reason,
        step.resource,
        step.eventId,
        ...(step.conversation ?? []).flatMap((turn) => [turn.from, turn.to, turn.text]),
      ]),
    ].filter(Boolean).join(" ")).includes(needle);
  });
}

export function trajectoryPhases(trajectory: AgentTrajectory): readonly TrajectoryPhase[] {
  return PHASE_CATEGORIES.map(([id, categories]) => {
    const steps = trajectory.steps.filter((step) => categories.includes(step.category));
    const state: TrajectoryPhaseState = steps.length === 0
      ? "unrecorded"
      : steps.some((step) => step.tone === "bad")
        ? "failed"
        : steps.some((step) => step.tone === "attention")
          ? "attention"
          : "recorded";
    return { id, state, steps: steps.length };
  });
}

/**
 * Piecewise time scale: recorded work time stays linear while long idle gaps compress to a short
 * labeled break, so one long wait cannot hide every other step.
 */
export function trajectoryScale(trajectory: AgentTrajectory): TrajectoryScale {
  const intervals = trajectory.steps.map((step) => [step.startMs, step.endMs] as const);
  const marks = [...new Set(intervals.flat())].sort((left, right) => left - right);
  const segments: { a: number; b: number; covered: boolean; from: number; weight: number }[] = [];
  for (let index = 1; index < marks.length; index += 1) {
    const a = marks[index - 1]!;
    const b = marks[index]!;
    segments.push({ a, b, covered: intervals.some(([start, end]) => start < b && end > a), from: 0, weight: 0 });
  }
  const active = segments.filter((segment) => segment.covered)
    .reduce((total, segment) => total + segment.b - segment.a, 0);
  const cap = Math.max(active * 0.08, 40);
  const breaks: { at: number; realMs: number }[] = [];
  let cursor = 0;
  for (const segment of segments) {
    const real = segment.b - segment.a;
    segment.from = cursor;
    segment.weight = !segment.covered && real > cap * 3 && real > 1000 ? cap : real;
    cursor += segment.weight;
    if (segment.weight !== real) breaks.push({ at: segment.from + segment.weight / 2, realMs: real });
  }
  const total = Math.max(cursor, 1);
  const x = (ms: number): number => {
    if (marks.length === 0 || ms <= marks[0]!) return 0;
    const segment = segments.find((entry) => ms >= entry.a && ms <= entry.b);
    if (!segment) return 100;
    const ratio = segment.b === segment.a ? 0 : (ms - segment.a) / (segment.b - segment.a);
    return (segment.from + ratio * segment.weight) / total * 100;
  };
  return { x, breaks: breaks.map((entry) => ({ left: entry.at / total * 100, realMs: entry.realMs })) };
}

export function stepCategory(item: AuditItem): TrajectoryStepCategory {
  const text = [
    item.action_kind,
    entryStr(item, "stage"),
    entryStr(item, "pipeline_stage"),
    entryStr(item, "decision"),
  ].filter(Boolean).join(" ").toLowerCase();
  if (isSagaAuditMirror(item) || /^(audit|outcome)\./.test(item.action_kind)) return "record";
  if (/rollback|revert|recovery/.test(text)) return "recovery";
  if (/^hil\.|approv/.test(text)) return "approval";
  if (/risk_gate|risk/.test(text)) return "risk";
  if (/verif|effect/.test(text)) return "verification";
  if (/execut|dispatch|^action\.|pr_opened|remediat/.test(text)) return "action";
  if (/trust_router|rout|rule|verdict|judg|rca|decision|control_loop/.test(text)) return "decision";
  if (/ingest|normaliz|^event\.|intake|received/.test(text)) return "intake";
  if (/read|query|inventory|observ|collect|scan|measurement|evidence/.test(text)) return "evidence";
  return "activity";
}

export function outcomeTone(...values: readonly (string | null)[]): TrajectoryTone {
  const text = values.filter(Boolean).join(" ").toLowerCase().replace(/[-.]/g, "_").replace(/_/g, " ");
  if (BAD_OUTCOME.test(text) || /\btimed out\b/.test(text)) return "bad";
  if (ATTENTION_OUTCOME.test(text)) return "attention";
  if (GOOD_OUTCOME.test(text)) return "good";
  return "neutral";
}

function stepOf(item: AuditItem, agentOf: (item: AuditItem) => string): TrajectoryStep | null {
  const endMs = timestamp(entryStr(item, "finished_at") ?? item.recorded_at);
  if (endMs === null) return null;
  const durationMs = boundedDuration(entryNum(item, "duration_ms"));
  const explicitStart = timestamp(entryStr(item, "started_at") ?? entryStr(item, "received_at"));
  const startMs = durationMs !== null
    ? endMs - durationMs
    : explicitStart !== null && explicitStart <= endMs ? explicitStart : endMs;
  const payload = nestedRecord(item.entry["payload"]);
  const outcome = entryStr(item, "outcome")
    ?? entryStr(item, "terminal_outcome")
    ?? entryStr(item, "t1_outcome")
    ?? entryStr(item, "t2_outcome")
    ?? entryStr(item, "status")
    ?? recordStr(payload, "outcome")
    ?? recordStr(payload, "terminal_outcome")
    ?? recordStr(payload, "judgment_state")
    ?? (item.action_kind.endsWith(".timeout") || entryStr(item, "reason") === "approval_expired"
      ? "timed_out"
      : null)
    ?? (recordStr(payload, "aggregate_type") ? "aggregated" : null);
  const decision = entryStr(item, "decision")
    ?? entryStr(item, "gate_route")
    ?? recordStr(payload, "decision");
  const reason = entryStr(item, "reason")
    ?? entryStr(item, "t1_reason")
    ?? entryStr(item, "t2_reason")
    ?? recordStr(payload, "reason");
  const resource = entryStr(item, "resource_ref")
    || entryStr(item, "target_resource_ref")
    || entryStr(item, "resource_id")
    || entryStr(item, "target_ref")
    || entryStr(item, "resource_type")
    || recordStr(payload, "resource_id")
    || recordStr(payload, "resource_ref")
    || recordStr(payload, "resource_type");
  return {
    seq: item.seq,
    eventId: item.event_id,
    agent: agentOf(item),
    category: stepCategory(item),
    actionKind: item.action_kind,
    summary: deriveStepSummary(item, payload),
    recordedAt: item.recorded_at,
    startMs,
    endMs,
    durationMs: durationMs ?? (endMs > startMs ? endMs - startMs : null),
    mode: item.mode,
    tier: tierOf(item),
    outcome,
    decision,
    reason,
    resource,
    inputs: entryMap(item, "inputs"),
    outputs: entryMap(item, "outputs"),
    conversation: entryConversation(item),
    fields: otherEntryFields(item).filter(([key]) =>
      key !== "resource_ref" && key !== "target_resource_ref" && key !== "stage"),
    tone: outcomeTone(outcome, decision),
    entryHash: item.entry_hash,
    previousHash: item.previous_hash,
    sample: auditProvenanceOf(item) === "sample",
  };
}

function nestedRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function recordStr(record: Record<string, unknown> | null, key: string): string | null {
  if (!record) return null;
  const value = record[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function shortResourceLabel(value: string | null): string | null {
  if (!value) return null;
  const parts = value.split("/").filter(Boolean);
  return parts.length > 1 ? parts[parts.length - 1]! : value;
}

function humanizeMachineToken(token: string): string {
  const readable = token
    .split(".")
    .map((part) => part.replace(/[-_]+/g, " ").trim())
    .filter(Boolean)
    .join(" \u00b7 ");
  return readable ? readable.charAt(0).toUpperCase() + readable.slice(1) : token;
}

function deriveStepSummary(
  item: AuditItem,
  payload: Record<string, unknown> | null,
): string {
  const direct = entryStr(item, "summary") || entryStr(item, "detail");
  if (direct) return direct;
  if (payload) {
    const payloadSummary = recordStr(payload, "summary") || recordStr(payload, "detail");
    if (payloadSummary) return payloadSummary;
    const eventType = recordStr(payload, "event_type");
    const shortRes = shortResourceLabel(
      recordStr(payload, "resource_id") ?? recordStr(payload, "resource_ref"),
    );
    if (eventType) {
      return shortRes
        ? `${humanizeMachineToken(eventType)} \u00b7 ${shortRes}`
        : humanizeMachineToken(eventType);
    }
    const aggregateType = recordStr(payload, "aggregate_type");
    if (aggregateType) {
      const count = payload["count"];
      return typeof count === "number"
        ? `${humanizeMachineToken(aggregateType)} (${count})`
        : humanizeMachineToken(aggregateType);
    }
    const kind = recordStr(payload, "kind");
    if (kind) {
      return shortRes
        ? `${humanizeMachineToken(kind)} \u00b7 ${shortRes}`
        : humanizeMachineToken(kind);
    }
  }
  const eventType = entryStr(item, "event_type");
  const resourceType = entryStr(item, "resource_type");
  if (eventType) {
    return resourceType
      ? `${humanizeMachineToken(eventType)} \u00b7 ${resourceType}`
      : humanizeMachineToken(eventType);
  }
  if (item.action_kind === "observation-campaign.source-transition") {
    const sourceId = entryStr(item, "source_id") ?? entryStr(item, "domain");
    if (sourceId) {
      return `Observation campaign \u00b7 ${sourceId}`;
    }
  }
  const reason = entryStr(item, "reason")
    ?? entryStr(item, "t1_reason")
    ?? entryStr(item, "t2_reason");
  if (reason) {
    const readableReason = /\s/.test(reason.trim()) ? reason : humanizeMachineToken(reason);
    return resourceType
      ? `${readableReason} \u00b7 ${resourceType}`
      : readableReason;
  }
  return item.action_kind;
}

function trajectoryOf(correlationId: string, steps: readonly TrajectoryStep[]): AgentTrajectory {
  const agents: string[] = [];
  let handoffs = 0;
  steps.forEach((step, index) => {
    if (!agents.includes(step.agent)) agents.push(step.agent);
    if (index > 0 && steps[index - 1]!.agent !== step.agent) handoffs += 1;
  });
  const nonMirrorSteps = steps.filter((step) => step.actionKind !== "audit.record");
  const outcomePool = nonMirrorSteps.some((step) => step.outcome !== null || step.decision !== null)
    ? nonMirrorSteps
    : steps;
  const latestWithOutcome = [...outcomePool].reverse().find((step) => step.outcome !== null || step.decision !== null);
  const latestOutcome = latestWithOutcome?.outcome ?? latestWithOutcome?.decision ?? null;
  return {
    correlationId,
    title: trajectoryTitle(steps),
    steps,
    agents,
    startMs: Math.min(...steps.map((step) => step.startMs)),
    endMs: Math.max(...steps.map((step) => step.endMs)),
    latestOutcome,
    tone: latestWithOutcome?.tone ?? "neutral",
    tiers: unique(steps.map((step) => step.tier)),
    modes: unique(steps.map((step) => step.mode)),
    handoffs,
    flaggedSteps: steps.filter((step) => step.tone === "attention" || step.tone === "bad").length,
    sampleSteps: steps.filter((step) => step.sample).length,
  };
}

/** First prose summary, else a readable form of the first machine value; raw values stay on each step. */
export function trajectoryTitle(steps: readonly TrajectoryStep[]): string {
  const prose = steps.find((step) => step.summary !== step.actionKind && /\s/.test(step.summary.trim()));
  if (prose) return prose.summary;
  const machine = steps[0]!.summary;
  const readable = machine.split(".").map((part) => part.replace(/[-_]+/g, " ").trim()).filter(Boolean).join(" \u00b7 ");
  return readable ? readable.charAt(0).toUpperCase() + readable.slice(1) : machine;
}

export function trajectorySubtitle(trajectory: AgentTrajectory): string {
  const first = trajectory.steps[0];
  if (!first) return "";
  const parts: string[] = [humanizeMachineToken(first.actionKind)];
  const shortRes = shortResourceLabel(first.resource);
  if (shortRes && !trajectory.title.includes(shortRes)) {
    parts.push(shortRes);
  }
  if (trajectory.modes.length > 0) {
    parts.push(trajectory.modes.join(" / "));
  }
  return parts.join(" \u00b7 ");
}

export function formatOutcomeLabel(outcome: string): string {
  const normalized = outcome.trim().replace(/[-_]+/g, " ");
  if (!normalized) return outcome;
  if (/^hil\b/i.test(normalized)) {
    return `HIL${normalized.slice(3)}`;
  }
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

function unique(values: readonly (string | null)[]): readonly string[] {
  return [...new Set(values.filter((value): value is string => value !== null && value !== ""))];
}

function boundedDuration(value: number | null): number | null {
  return value !== null && Number.isFinite(value) && value >= 0 && value <= 86_400_000 ? value : null;
}

function timestamp(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function normalize(value: string): string {
  return value.trim().toLowerCase().replace(/[\s_-]+/g, " ");
}
