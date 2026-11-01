/**
 * Agent trajectories projected from retained durable audit records.
 *
 * One trajectory groups the audit steps that share a correlation id, in recorded order. Step
 * categories, phases, and tones derive only from recorded fields; a phase without records stays
 * unrecorded rather than inferred as skipped, and no terminal completion is asserted beyond the
 * recorded outcome. This is a read-only presentation projection, not a governed trajectory export.
 */

import { getLocale } from "../i18n";
import type { AuditItem } from "../types";
import type { LiveAgentActivityEvent } from "./agents.model";
import {
  ACTION_TYPE_LABELS,
  auditProvenanceOf,
  entryConversation,
  entryMap,
  entryNum,
  entryStr,
  isSagaAuditMirror,
  OBSERVATION_DOMAIN_LABELS,
  otherEntryFields,
  OUTCOME_LABELS,
  REASON_LABELS,
  RESOURCE_TYPE_LABELS,
  RULE_LABELS,
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
  readonly hasExplicitSummary?: boolean;
  readonly ruleId?: string | null;
  readonly actionType?: string | null;
  readonly resourceType?: string | null;
  readonly domain?: string | null;
  readonly eventType?: string | null;
  readonly aggregateType?: string | null;
  readonly aggregateCount?: number | null;
  readonly repeatCount?: number;
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
    const rawSteps = bucket
      .map((item) => stepOf(item, agentOf))
      .filter((step): step is TrajectoryStep => step !== null)
      .sort((left, right) => left.endMs - right.endMs || left.seq - right.seq);
    const steps = collapseRepeatedTrajectorySteps(rawSteps);
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

function stepSignature(step: TrajectoryStep): string {
  return [
    step.agent,
    step.actionKind,
    step.ruleId ?? "",
    step.actionType ?? "",
    step.resource ?? "",
    step.domain ?? "",
    step.outcome ?? "",
    step.decision ?? "",
    step.reason ?? "",
    step.summary,
  ].join("|");
}

/**
 * Collapses repeated identical periodic steps (such as recurring analyzer ticks or repeated
 * identical source-transition probes on the same correlation id) while preserving distinct rules,
 * inputs, outputs, and conversations.
 */
export function collapseRepeatedTrajectorySteps(
  steps: readonly TrajectoryStep[],
): readonly TrajectoryStep[] {
  if (steps.length <= 1) return steps;
  const result: TrajectoryStep[] = [];
  const indexBySignature = new Map<string, number>();
  for (const step of steps) {
    const hasUniqueContext = Boolean(
      (step.inputs && step.inputs.length > 0) ||
      (step.outputs && step.outputs.length > 0) ||
      (step.conversation && step.conversation.length > 0),
    );
    const sig = stepSignature(step);
    const existingIndex = !hasUniqueContext ? indexBySignature.get(sig) : undefined;
    if (existingIndex !== undefined) {
      const prev = result[existingIndex]!;
      result[existingIndex] = {
        ...prev,
        endMs: Math.max(prev.endMs, step.endMs),
        recordedAt: step.endMs >= prev.endMs ? step.recordedAt : prev.recordedAt,
        durationMs: step.durationMs ?? prev.durationMs,
        repeatCount: (prev.repeatCount ?? 1) + (step.repeatCount ?? 1),
      };
      continue;
    }
    indexBySignature.set(sig, result.length);
    result.push(step);
  }
  return result;
}

/**
 * Merges live correlated SSE stream events into the durable audit item list so Trajectories
 * update smoothly in real time as agents process new events.
 */
export function mergeLiveEventsIntoAuditItems(
  items: readonly AuditItem[],
  liveEvents: readonly LiveAgentActivityEvent[],
): readonly AuditItem[] {
  if (liveEvents.length === 0) return items;
  const knownKeys = new Set<string>();
  for (const item of items) {
    if (item.event_id) knownKeys.add(`id:${item.event_id}`);
    if (item.correlation_id) {
      knownKeys.add(`sig:${item.correlation_id}|${item.actor}|${item.action_kind}|${item.recorded_at}`);
    }
  }
  const appended: AuditItem[] = [];
  for (const event of liveEvents) {
    if (event.source === "replay" || !event.correlationId || !event.correlationId.trim()) continue;
    if (event.kind === "agent.state" && event.activityPhase === "started") continue;
    if (
      event.kind === "agent.state" &&
      !event.activityPhase &&
      (event.state === "idle" || event.state === "watching")
    ) {
      continue;
    }
    const eventId = event.eventId ?? event.activityId ?? `live-${event.sequence}`;
    const actionKind = event.operationalKind
      ?? event.eventType
      ?? (event.kind === "conversation.turn" ? "conversation.turn" : event.kind);
    const sigKey = `sig:${event.correlationId}|${event.agent}|${actionKind}|${event.ts}`;
    if (knownKeys.has(`id:${eventId}`) || knownKeys.has(sigKey)) continue;
    knownKeys.add(`id:${eventId}`);
    knownKeys.add(sigKey);
    const entry: Record<string, unknown> = {
      producer_principal: event.agent,
      summary: event.detail || event.summary,
    };
    if (event.resourceRef) entry["resource_ref"] = event.resourceRef;
    if (event.resourceType) entry["resource_type"] = event.resourceType;
    if (event.eventType) entry["event_type"] = event.eventType;
    if (event.observationDomain) entry["domain"] = event.observationDomain;
    if (event.startedAt) entry["started_at"] = event.startedAt;
    if (event.completedAt) entry["finished_at"] = event.completedAt;
    if (typeof event.durationMs === "number") entry["duration_ms"] = event.durationMs;
    if (event.activityPhase) entry["outcome"] = event.activityPhase;
    if (event.kind === "conversation.turn" && event.agents.length >= 2) {
      entry["conversation"] = [{
        from: event.agents[0]!,
        to: event.agents[1]!,
        text: event.detail ?? event.summary,
      }];
    }
    appended.push({
      seq: 1_000_000_000 + event.sequence,
      event_id: eventId,
      correlation_id: event.correlationId,
      actor: event.agent,
      action_kind: actionKind,
      mode: "shadow",
      entry,
      entry_hash: `live-${event.sequence}`,
      previous_hash: `live-${Math.max(event.sequence - 1, 0)}`,
      recorded_at: event.ts,
    });
  }
  return appended.length > 0 ? [...appended, ...items] : items;
}

export interface TrajectoryDisplayGroup {
  readonly key: string;
  readonly primary: AgentTrajectory;
  readonly members: readonly AgentTrajectory[];
}

export interface PinnedTrajectoryDetail {
  readonly correlationId: string;
  readonly filterKey: string;
  readonly trajectory: AgentTrajectory;
  readonly groupMembers: readonly AgentTrajectory[];
}

export interface StabilizedTrajectorySelection {
  readonly shown: readonly AgentTrajectory[];
  readonly grouped: readonly TrajectoryDisplayGroup[];
  readonly current: AgentTrajectory | null;
  readonly currentGroupMembers: readonly AgentTrajectory[];
  readonly pinned: PinnedTrajectoryDetail | null;
}

export function groupTrajectoriesForDisplay(
  trajectories: readonly AgentTrajectory[],
  selectedCorrelationId: string | null,
  locale: "en" | "ko" = getLocale(),
): readonly TrajectoryDisplayGroup[] {
  const groups = new Map<string, AgentTrajectory[]>();
  for (const trajectory of trajectories) {
    const key = [
      presentTrajectoryTitle(trajectory, locale),
      trajectory.latestOutcome ?? "",
    ].join("||");
    const bucket = groups.get(key) ?? [];
    bucket.push(trajectory);
    groups.set(key, bucket);
  }
  const result: TrajectoryDisplayGroup[] = [];
  for (const [key, members] of groups) {
    const primary = (selectedCorrelationId !== null
      ? members.find((item) => item.correlationId === selectedCorrelationId)
      : undefined) ?? members[0]!;
    result.push({ key, primary, members });
  }
  return result;
}

/**
 * Keeps the currently viewed trajectory detail body stable while new activities stream in or
 * older records age out of the bounded window. Selection changes only when no trajectory is pinned
 * yet, when the operator explicitly selects a trajectory, or when a filter change excludes the
 * previously pinned correlation id.
 */
export function stabilizeTrajectorySelection(
  liveShown: readonly AgentTrajectory[],
  selectedCorrelationId: string | null,
  filterKey: string,
  previousPinned: PinnedTrajectoryDetail | null,
  locale: "en" | "ko" = getLocale(),
): StabilizedTrajectorySelection {
  const canPreservePinned =
    previousPinned !== null &&
    (selectedCorrelationId === null || selectedCorrelationId === previousPinned.correlationId) &&
    (
      previousPinned.filterKey === filterKey ||
      liveShown.some((item) => item.correlationId === previousPinned.correlationId)
    );

  if (canPreservePinned) {
    const hasPinnedInLive = liveShown.some(
      (item) => item.correlationId === previousPinned.correlationId,
    );
    const shown = hasPinnedInLive
      ? liveShown.map((item) =>
          item.correlationId === previousPinned.correlationId ? previousPinned.trajectory : item)
      : [...liveShown, previousPinned.trajectory];
    const grouped = groupTrajectoriesForDisplay(shown, previousPinned.correlationId, locale);
    const pinned = previousPinned.filterKey === filterKey
      ? previousPinned
      : { ...previousPinned, filterKey };
    return {
      shown,
      grouped,
      current: previousPinned.trajectory,
      currentGroupMembers: previousPinned.groupMembers,
      pinned,
    };
  }

  if (liveShown.length === 0) {
    return {
      shown: [],
      grouped: [],
      current: null,
      currentGroupMembers: [],
      pinned: null,
    };
  }

  const grouped = groupTrajectoriesForDisplay(liveShown, selectedCorrelationId, locale);
  const activeGroup = (selectedCorrelationId !== null
    ? grouped.find((group) =>
        group.members.some((member) => member.correlationId === selectedCorrelationId))
    : undefined) ?? grouped[0] ?? null;
  const current = activeGroup?.primary ?? null;
  const currentGroupMembers = activeGroup?.members ?? (current ? [current] : []);
  const pinned: PinnedTrajectoryDetail | null = current
    ? {
        correlationId: current.correlationId,
        filterKey,
        trajectory: current,
        groupMembers: currentGroupMembers,
      }
    : null;
  return {
    shown: liveShown,
    grouped,
    current,
    currentGroupMembers,
    pinned,
  };
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
  const authority = nestedRecord(item.entry["authority"]);
  const hasExplicitSummary = Boolean(
    entryStr(item, "summary") ||
    entryStr(item, "detail") ||
    recordStr(payload, "summary") ||
    recordStr(payload, "detail"),
  );
  const embedded = extractEmbeddedAuditContext(item);
  const ruleId = entryStr(item, "rule_id")
    ?? firstStringElement(item.entry["candidate_rule_ids"])
    ?? firstCitationRef(item.entry["rca_citations"])
    ?? recordStr(authority, "matched_rule_id")
    ?? embedded.ruleId;
  const actionType = entryStr(item, "action_type")
    ?? entryStr(item, "action_type_id")
    ?? entryStr(item, "rca_remediation_ref")
    ?? recordStr(authority, "action_type_id");
  const domain = entryStr(item, "domain")
    ?? entryStr(item, "source_id")
    ?? recordStr(payload, "source_id");
  const eventType = entryStr(item, "event_type") ?? recordStr(payload, "event_type");
  const aggregateType = recordStr(payload, "aggregate_type");
  const aggregateCount = typeof payload?.["count"] === "number" ? payload["count"] : null;
  const rawResource = entryStr(item, "resource_ref")
    || entryStr(item, "target_resource_ref")
    || entryStr(item, "resource_id")
    || entryStr(item, "target_ref")
    || recordStr(payload, "resource_id")
    || recordStr(payload, "resource_ref")
    || embedded.resourceRef
    || entryStr(item, "repository_alias");
  const resourceType = entryStr(item, "resource_type")
    || recordStr(payload, "resource_type")
    || inferResourceType(ruleId, rawResource);
  const resource = rawResource || resourceType;
  const outcome = entryStr(item, "outcome")
    ?? entryStr(item, "terminal_outcome")
    ?? entryStr(item, "t1_outcome")
    ?? entryStr(item, "t2_outcome")
    ?? entryStr(item, "rca_outcome")
    ?? entryStr(item, "status")
    ?? recordStr(payload, "outcome")
    ?? recordStr(payload, "terminal_outcome")
    ?? recordStr(payload, "judgment_state")
    ?? (item.action_kind.endsWith(".timeout") || entryStr(item, "reason") === "approval_expired"
      ? "timed_out"
      : null)
    ?? (item.action_kind === "hil.requested" ? "hil_pending" : null)
    ?? (item.action_kind === "hil.request.dispatch_unavailable" ? "shadow_queued" : null)
    ?? (item.action_kind.endsWith(".abstain") ? "abstain" : null)
    ?? (item.action_kind.endsWith(".compliant") ? "compliant" : null)
    ?? (aggregateType ? "aggregated" : null);
  const decision = entryStr(item, "decision")
    ?? entryStr(item, "gate_route")
    ?? entryStr(item, "gate_outcome")
    ?? recordStr(payload, "decision");
  const reason = entryStr(item, "reason")
    ?? entryStr(item, "t1_reason")
    ?? entryStr(item, "t2_reason")
    ?? entryStr(item, "rca_reason")
    ?? firstStringElement(item.entry["gate_reasons"])
    ?? recordStr(payload, "reason");
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
    hasExplicitSummary,
    ruleId,
    actionType,
    resourceType,
    domain,
    eventType,
    aggregateType,
    aggregateCount,
  };
}

function firstStringElement(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  const found = value.find((entry): entry is string => typeof entry === "string" && entry.trim().length > 0);
  return found ? found.trim() : null;
}

function firstCitationRef(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  for (const item of value) {
    const rec = nestedRecord(item);
    const ref = recordStr(rec, "ref");
    if (ref) return ref;
  }
  return null;
}

function extractEmbeddedAuditContext(item: AuditItem): {
  readonly ruleId: string | null;
  readonly resourceRef: string | null;
} {
  let ruleId: string | null = null;
  let resourceRef: string | null = null;
  const impacts = item.entry["rca_impact"];
  if (Array.isArray(impacts)) {
    for (const impact of impacts) {
      const rec = nestedRecord(impact);
      const evidenceRef = recordStr(rec, "evidence_ref");
      if (evidenceRef && evidenceRef.startsWith("finding:")) {
        const parts = evidenceRef.slice("finding:".length).split("::");
        if (parts[0]?.trim()) ruleId = ruleId ?? parts[0].trim();
        if (parts[2]?.trim()) resourceRef = resourceRef ?? parts[2].trim();
      }
    }
  }
  const idempotencyKey = entryStr(item, "idempotency_key");
  if (idempotencyKey && idempotencyKey.includes("::")) {
    const parts = idempotencyKey.split("::");
    if (parts.length >= 3) {
      if (parts[1]?.trim()) ruleId = ruleId ?? parts[1].trim();
      const rawTarget = parts[2]?.trim() ?? "";
      const cleanTarget = rawTarget.replace(/:(hil_request|hil_timeout|rca)$/i, "");
      if (cleanTarget) resourceRef = resourceRef ?? cleanTarget;
    }
  }
  if (!resourceRef && item.correlation_id?.startsWith("inventory:scope-")) {
    resourceRef = item.correlation_id.slice("inventory:".length);
  }
  return { ruleId, resourceRef };
}

const ARM_PROVIDER_RESOURCE_TYPE: Readonly<Record<string, string>> = {
  "microsoft.compute/virtualmachinescalesets": "compute.vm-scale-set",
  "microsoft.compute/virtualmachines": "compute.vm",
  "microsoft.compute/disks": "disk",
  "microsoft.compute/galleries": "compute.image-gallery",
  "microsoft.compute/images": "compute.image",
  "microsoft.network/networksecuritygroups": "network.nsg",
  "microsoft.network/virtualnetworks": "network.vnet",
  "microsoft.network/networkinterfaces": "network.interface",
  "microsoft.network/publicipaddresses": "network.public-ip",
  "microsoft.network/loadbalancers": "network.load-balancer",
  "microsoft.network/natgateways": "network.nat-gateway",
  "microsoft.network/privateendpoints": "network.private-endpoint",
  "microsoft.network/privatednszones": "network.private-dns-zone",
  "microsoft.network/dnszones": "network.dns-zone",
  "microsoft.network/bastionhosts": "network.bastion-host",
  "microsoft.network/azurefirewalls": "network.firewall",
  "microsoft.network/firewallpolicies": "network.firewall-policy",
  "microsoft.network/routetables": "network.route-table",
  "microsoft.network/networkwatchers": "observability.network-monitor",
  "microsoft.storage/storageaccounts": "object-storage",
  "microsoft.keyvault/vaults": "secret-store",
  "microsoft.dbforpostgresql/flexibleservers": "postgresql-server",
  "microsoft.containerservice/managedclusters": "kubernetes-cluster",
  "microsoft.containerregistry/registries": "container-registry",
  "microsoft.app/containerapps": "compute.container-app",
  "microsoft.app/jobs": "compute.container-app-job",
  "microsoft.app/managedenvironments": "compute.container-app-environment",
  "microsoft.cognitiveservices/accounts": "llm-endpoint",
  "microsoft.eventhub/namespaces": "event-hub",
  "microsoft.operationalinsights/workspaces": "log-workspace",
  "microsoft.insights/components": "application-insights",
  "microsoft.managedidentity/userassignedidentities": "managed-identity",
  "microsoft.authorization/roleassignments": "authorization.role-assignment",
};

function inferResourceType(ruleId: string | null, resourceRef: string | null): string | null {
  if (ruleId) {
    for (const candidate of Object.keys(RESOURCE_TYPE_LABELS)) {
      if (ruleId === candidate || ruleId.startsWith(`${candidate}.`)) return candidate;
    }
  }
  if (resourceRef) {
    if (RESOURCE_TYPE_LABELS[resourceRef]) return resourceRef;
    const lowered = resourceRef.toLowerCase();
    if (lowered.includes("/deployments/")) return "llm-model-deployment";
    const providerMatch = /\/providers\/([^/]+\/[^/]+)/.exec(lowered);
    if (providerMatch?.[1] && ARM_PROVIDER_RESOURCE_TYPE[providerMatch[1]]) {
      return ARM_PROVIDER_RESOURCE_TYPE[providerMatch[1]]!;
    }
    if (/\/resource-group\/[^/]+$/.test(lowered) || /\/resourcegroups\/[^/]+$/.test(lowered)) {
      return "resource-group";
    }
  }
  return null;
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

export function trajectorySubtitle(trajectory: AgentTrajectory, locale: "en" | "ko" = getLocale()): string {
  const first = trajectory.steps[0];
  if (!first) return "";
  const rules = unique(trajectory.steps.map((step) => step.ruleId ?? null));
  const actions = unique(trajectory.steps.map((step) => step.actionType ?? null));
  const resType = trajectory.steps.find((step) => step.resourceType)?.resourceType ?? null;
  if (!resType && rules.length === 0 && actions.length === 0) return "";
  const parts: string[] = [];
  if (resType) {
    parts.push(presentResourceTypeLabel(resType, locale));
  }
  if (rules.length > 0) {
    parts.push(locale === "ko" ? `규칙: ${rules[0]}${rules.length > 1 ? ` 외 ${rules.length - 1}건` : ""}` : `Rule: ${rules[0]}${rules.length > 1 ? ` +${rules.length - 1}` : ""}`);
  } else {
    parts.push(presentActionKindLabel(first.actionKind, locale));
  }
  if (actions.length > 0) {
    const actionLabel = ACTION_TYPE_LABELS[actions[0]!]?.[locale] ?? actions[0]!;
    parts.push(locale === "ko" ? `권고 조치: ${actionLabel}` : `Action: ${actionLabel}`);
  }
  if (trajectory.modes.length > 0) {
    parts.push(locale === "ko" ? `${trajectory.modes.join(" / ")} 모드` : `${trajectory.modes.join(" / ")} mode`);
  }
  return parts.join(" \u00b7 ");
}

export interface ParsedStructuredFieldValue {
  readonly kind: "plain" | "structured" | "object";
  readonly scalars: ReadonlyArray<readonly [string, string]>;
  readonly longScalars: ReadonlyArray<readonly [string, string]>;
  readonly nestedEntries: ReadonlyArray<readonly [string, Record<string, unknown>]>;
  readonly directObject: Record<string, unknown> | null;
}

export function parseStructuredFieldValue(value: string): ParsedStructuredFieldValue {
  if (value.includes(" \u00b7 ") && value.includes(":")) {
    const entries = value.split(" \u00b7 ").map((part) => part.trim()).filter(Boolean);
    if (entries.length > 1) {
      const scalars: Array<readonly [string, string]> = [];
      const longScalars: Array<readonly [string, string]> = [];
      const nestedEntries: Array<readonly [string, Record<string, unknown>]> = [];
      for (const entry of entries) {
        if (entry.endsWith(":")) continue;
        const colon = entry.indexOf(": ");
        if (colon <= 0) {
          scalars.push(["", entry]);
          continue;
        }
        const key = entry.slice(0, colon).trim();
        const rawVal = entry.slice(colon + 2).trim();
        if (!rawVal || rawVal === "[]" || rawVal === "{}" || rawVal === "null") continue;
        const parsedObj = parseJsonObject(rawVal);
        if (parsedObj) {
          nestedEntries.push([key, parsedObj]);
        } else if (key.length + rawVal.length > 28 || /^\d{4}-\d{2}-\d{2}T/.test(rawVal)) {
          longScalars.push([key, rawVal]);
        } else {
          scalars.push([key, rawVal]);
        }
      }
      return {
        kind: "structured",
        scalars,
        longScalars,
        nestedEntries,
        directObject: null,
      };
    }
  }
  const directObj = parseJsonObject(value.trim());
  if (directObj) {
    return {
      kind: "object",
      scalars: [],
      longScalars: [],
      nestedEntries: [],
      directObject: directObj,
    };
  }
  return {
    kind: "plain",
    scalars: [],
    longScalars: [],
    nestedEntries: [],
    directObject: null,
  };
}

function parseJsonObject(raw: string): Record<string, unknown> | null {
  if (!raw.startsWith("{") || !raw.endsWith("}")) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export function formatOutcomeWithCode(
  outcome: string,
  locale: "en" | "ko" = getLocale(),
): string {
  const label = formatOutcomeLabel(outcome, locale);
  return label.toLowerCase() === outcome.toLowerCase() ? outcome : `${label} (${outcome})`;
}

export function formatOutcomeLabel(outcome: string, locale: "en" | "ko" = getLocale()): string {
  const key = outcome.trim().toLowerCase().replace(/[\s-]+/g, "_");
  const entry = OUTCOME_LABELS[key];
  if (entry) return entry[locale];
  const normalized = outcome.trim().replace(/[-_]+/g, " ");
  if (!normalized) return outcome;
  if (/^hil\b/i.test(normalized)) {
    return `HIL${normalized.slice(3)}`;
  }
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function presentResourceTypeLabel(resourceType: string, locale: "en" | "ko" = getLocale()): string {
  return RESOURCE_TYPE_LABELS[resourceType]?.[locale] ?? humanizeMachineToken(resourceType);
}

export function presentReasonLabel(reason: string, locale: "en" | "ko" = getLocale()): string {
  const key = reason.trim();
  const entry = REASON_LABELS[key];
  if (entry) return entry[locale];
  if (key.startsWith("control_loop_unhandled_error:")) {
    const errType = key.slice("control_loop_unhandled_error:".length);
    return locale === "ko"
      ? `컨트롤 루프 처리 중 예외 발생 (${errType})`
      : `Unhandled control-loop error (${errType})`;
  }
  return /\s/.test(key) ? key : humanizeMachineToken(key);
}

export function presentActionKindLabel(actionKind: string, locale: "en" | "ko" = getLocale()): string {
  const map: Readonly<Record<string, { readonly en: string; readonly ko: string }>> = {
    "control_loop.compliant": { en: "Policy compliance evaluation", ko: "정책 준수 평가" },
    "control_loop.abstain": { en: "Trust router rule check", ko: "신뢰 라우터 규칙 매칭 점검" },
    "control_loop.t1_evaluate": { en: "T1 similarity case evaluation", ko: "T1 유사 과거 사례 비교 평가" },
    "control_loop.t2_evaluate": { en: "T2 deliberative reasoning evaluation", ko: "T2 심층 추론 및 검증 평가" },
    "control_loop.unhandled_failure": { en: "Control-loop exception handling", ko: "컨트롤 루프 예외 처리" },
    "measurement.control_loop.v1": { en: "Control-loop outcome measurement", ko: "컨트롤 루프 처리 결과 계측" },
    "rca.hypothesis": { en: "Root-cause & policy violation analysis", ko: "규칙 위반 원인 및 영향 분석(RCA)" },
    "risk_gate.unified": { en: "Risk gate & autonomy ceiling check", ko: "위험 등급 및 자율 실행 한도 평가" },
    "risk_gate.evaluated": { en: "Risk gate evaluation", ko: "위험 게이트 평가" },
    "hil.requested": { en: "Human-in-the-loop approval request", ko: "운영자 승인(HIL) 요청 발행" },
    "hil.request.dispatch_unavailable": { en: "Approval queue retention (shadow)", ko: "승인 요청 콘솔 대기열 유지(Shadow)" },
    "hil.timeout": { en: "Human approval timeout expiration", ko: "운영자 승인 대기 기한 만료 처리" },
    "observation-campaign.source-transition": { en: "Scheduled observation campaign probe", ko: "정기 관측 캠페인 소스 점검" },
    "notification.route": { en: "Operational alert notification routing", ko: "운영 알림 채널 라우팅 및 전송" },
    "audit.record": { en: "Immutable audit ledger retention", ko: "불변 감사 원장 보존 기록" },
    "event.normalized": { en: "Operational event intake & normalization", ko: "운영 이벤트 수집 및 정규화" },
    "inventory.current_state.read": { en: "Current resource state verification", ko: "현재 리소스 상태 조회" },
    "baseline_evaluation.started": { en: "Inventory baseline evaluation started", ko: "인벤토리 기준선 정책 평가 시작" },
    "baseline_evaluation.coverage": { en: "Inventory baseline coverage summary", ko: "인벤토리 기준선 평가 범위 집계" },
    "mimir.rule-source.observed": { en: "Rule catalog source observation", ko: "규칙 카탈로그 소스 변경 감지" },
    "runtime.operational-state-recorded": { en: "Runtime health & posture snapshot", ko: "런타임 상태 스냅샷 기록" },
    "observer.deployment.proposed": { en: "Cluster observer deployment proposal", ko: "클러스터 관측기 배포 제안" },
    "observer.deployment.refreshed": { en: "Cluster observer posture refresh", ko: "클러스터 관측기 상태 갱신" },
  };
  return map[actionKind]?.[locale] ?? humanizeMachineToken(actionKind);
}

export function presentTrajectoryTitle(
  trajectory: AgentTrajectory,
  locale: "en" | "ko" = getLocale(),
): string {
  const explicitStep = trajectory.steps.find((step) => step.hasExplicitSummary);
  if (explicitStep) return explicitStep.summary;

  const rules = unique(trajectory.steps.map((step) => step.ruleId ?? null));
  const actionType = trajectory.steps.find((step) => step.actionType)?.actionType ?? null;
  const resType = trajectory.steps.find((step) => step.resourceType)?.resourceType ?? null;
  const rawResource = trajectory.steps.find((step) =>
    step.resource && step.resource !== step.resourceType)?.resource ?? null;
  const shortRes = rawResource && rawResource !== resType ? shortResourceLabel(rawResource) : null;
  const resTypeLabel = resType ? presentResourceTypeLabel(resType, locale) : null;
  const targetSuffix = shortRes && (!resTypeLabel || !resTypeLabel.toLowerCase().includes(shortRes.toLowerCase()))
    ? ` (${shortRes})`
    : "";

  // 1. Policy Rule-driven trajectories (RCA, HIL, Risk Gate, or T0 Compliance)
  if (rules.length > 0) {
    const primaryRule = RULE_LABELS[rules[0]!]?.[locale] ?? humanizeMachineToken(rules[0]!);
    const extraRules = rules.length > 1
      ? (locale === "ko" ? ` 외 ${rules.length - 1}건` : ` (+${rules.length - 1} more)`)
      : "";
    if (trajectory.latestOutcome === "timed_out") {
      return locale === "ko"
        ? `${primaryRule}${extraRules}${targetSuffix} - 승인 기한 만료`
        : `${primaryRule}${extraRules}${targetSuffix} - approval expired`;
    }
    if (trajectory.latestOutcome === "hil" || trajectory.latestOutcome === "hil_pending" || trajectory.latestOutcome === "shadow_queued") {
      const actionLabel = actionType ? (ACTION_TYPE_LABELS[actionType]?.[locale] ?? actionType) : null;
      return locale === "ko"
        ? `${primaryRule}${extraRules}${targetSuffix} - ${actionLabel ? `${actionLabel} 승인 대기` : "운영자 승인 대기"}`
        : `${primaryRule}${extraRules}${targetSuffix} - ${actionLabel ? `awaiting approval (${actionLabel})` : "awaiting approval"}`;
    }
    if (trajectory.latestOutcome === "compliant") {
      return locale === "ko"
        ? `${primaryRule}${extraRules}${targetSuffix} - 정책 준수 확인`
        : `${primaryRule}${extraRules}${targetSuffix} - compliant`;
    }
    return `${primaryRule}${extraRules}${targetSuffix}`;
  }

  // 2. Observation campaign transitions
  const campaignStep = trajectory.steps.find((step) => step.actionKind === "observation-campaign.source-transition");
  if (campaignStep) {
    const domKey = campaignStep.domain ?? "metrics";
    const domLabel = OBSERVATION_DOMAIN_LABELS[domKey]?.[locale] ?? domKey;
    if (trajectory.latestOutcome === "degraded") {
      return locale === "ko"
        ? `${domLabel} 정기 관측 캠페인 점검 - 수집 지연 감지`
        : `${domLabel} observation campaign check - source degraded`;
    }
    return locale === "ko"
      ? `${domLabel} 정기 관측 캠페인 점검`
      : `${domLabel} scheduled observation campaign check`;
  }

  // 3. Notification routing
  const notifStep = trajectory.steps.find((step) => step.actionKind === "notification.route");
  if (notifStep) {
    return locale === "ko"
      ? "운영 알림 채널 라우팅 및 콘솔 수신함 전송"
      : "Operational alert notification routed and delivered";
  }

  // 4. Observer deployment proposals/refreshes
  const observerStep = trajectory.steps.find((step) => step.actionKind.startsWith("observer.deployment."));
  if (observerStep) {
    return locale === "ko"
      ? "클러스터 관측기(Observer) 배포 준비 상태 점검 - 추가 확인 필요"
      : "Cluster observer deployment readiness check - needs evidence";
  }

  // 5. Rule activation requests
  const ruleActStep = trajectory.steps.find((step) => step.actionKind.startsWith("rule_activation."));
  if (ruleActStep) {
    return locale === "ko"
      ? "정책 규칙 카탈로그 활성화 세대 전환 및 검증"
      : "Policy rule catalog activation generation update";
  }

  // 6. Control-loop reason-based trajectories (e.g. inventory_baseline_no_rule_match, no_rule_matches_resource_and_signal_type, event_payload_missing_resource_type)
  const primaryReason = trajectory.steps.find((step) => step.reason)?.reason ?? null;
  const hasT1NoNeighbour = trajectory.steps.some((step) => step.reason === "no_neighbour_found");
  const subjectLabel = resTypeLabel
    ? `${resTypeLabel}${targetSuffix}`
    : (shortRes ?? (locale === "ko" ? "클라우드 리소스" : "Cloud resource"));

  if (primaryReason === "inventory_baseline_no_rule_match") {
    return locale === "ko"
      ? `${subjectLabel} 인벤토리 기준선 검토 - 적용 대상 규칙 없음`
      : `${subjectLabel} inventory baseline review - no applicable rule`;
  }
  if (primaryReason === "no_rule_matches_resource_and_signal_type") {
    return locale === "ko"
      ? `${subjectLabel} 변경 이벤트 검토 - ${hasT1NoNeighbour ? "일치 규칙 및 유사 사례 없음" : "일치하는 규칙 없음"}`
      : `${subjectLabel} change event review - ${hasT1NoNeighbour ? "no matching rule or similar case" : "no matching rule"}`;
  }
  if (primaryReason === "no_rule_denied") {
    const eventType = trajectory.steps.find((step) => step.eventType)?.eventType;
    if (eventType === "analyzer.host_cpu.observed") {
      return locale === "ko"
        ? `${subjectLabel} 호스트 CPU 메트릭 점검 - 이상 및 규칙 위반 없음`
        : `${subjectLabel} host CPU metric check - compliant`;
    }
    return locale === "ko"
      ? `${subjectLabel} 정책 준수 점검 - 위반 사항 없음`
      : `${subjectLabel} policy compliance check - no violations`;
  }
  if (primaryReason === "event_payload_missing_resource_type") {
    return locale === "ko"
      ? `${subjectLabel} 변경 이벤트 수신 - 리소스 유형 누락으로 라우팅 보류`
      : `${subjectLabel} change event - routing abstained (missing resource type)`;
  }
  if (primaryReason === "approval_expired") {
    return locale === "ko"
      ? `${subjectLabel} 조치 승인 요청 - 승인 대기 기한 만료`
      : `${subjectLabel} remediation approval request - expired`;
  }

  // 7. Saga single-step audit mirrors
  const mirrorStep = trajectory.steps[0];
  if (mirrorStep && mirrorStep.actionKind === "audit.record") {
    if (mirrorStep.aggregateType === "forseti.no_rule_match") {
      const cnt = mirrorStep.aggregateCount ?? 1;
      return locale === "ko"
        ? `규칙 미일치 리소스 이벤트 감사 집계 기록 (${cnt}건)`
        : `Unmatched-rule resource event audit aggregate (${cnt})`;
    }
    if (mirrorStep.eventType === "inventory.resource_observed") {
      return locale === "ko"
        ? `${subjectLabel} 인벤토리 관측 상태 감사 보존`
        : `${subjectLabel} inventory observation retained in audit`;
    }
    if (mirrorStep.eventType === "inventory.resource_changed") {
      return locale === "ko"
        ? `${subjectLabel} 인벤토리 변경 감지 감사 보존`
        : `${subjectLabel} inventory change retained in audit`;
    }
  }

  return trajectory.title;
}

export function presentAuditItemSummary(
  item: AuditItem,
  locale: "en" | "ko" = getLocale(),
): string {
  const direct = entryStr(item, "summary") || entryStr(item, "detail");
  if (direct) return direct;
  const step = stepOf(item, () => item.actor);
  if (!step) return entryStr(item, "reason") || item.action_kind;
  if (
    !step.ruleId &&
    !step.actionType &&
    !step.resourceType &&
    !step.domain &&
    !step.eventType &&
    !step.aggregateType &&
    !step.reason &&
    !step.outcome
  ) {
    return item.action_kind;
  }
  return presentStepSummary(step, locale);
}

export function presentStepSummary(
  step: TrajectoryStep,
  locale: "en" | "ko" = getLocale(),
): string {
  if (step.hasExplicitSummary) return step.summary;
  const resLabel = step.resourceType
    ? presentResourceTypeLabel(step.resourceType, locale)
    : shortResourceLabel(step.resource);
  const shortRes = step.resource && step.resource !== step.resourceType
    ? shortResourceLabel(step.resource)
    : null;
  const targetSuffix = shortRes && resLabel && !resLabel.toLowerCase().includes(shortRes.toLowerCase())
    ? ` (${shortRes})`
    : "";
  const subject = resLabel ? `${resLabel}${targetSuffix}` : (shortRes ?? "");

  if (step.actionKind === "rca.hypothesis") {
    const ruleText = step.ruleId ? (RULE_LABELS[step.ruleId]?.[locale] ?? step.ruleId) : "";
    const actionText = step.actionType ? (ACTION_TYPE_LABELS[step.actionType]?.[locale] ?? step.actionType) : "";
    if (locale === "ko") {
      return `${ruleText || subject}${targetSuffix} 위반 확인${actionText ? ` -> ${actionText} 조치 권고` : ""}`;
    }
    return `Confirmed ${ruleText || subject}${targetSuffix} violation${actionText ? ` -> recommended ${actionText}` : ""}`;
  }
  if (step.actionKind === "risk_gate.unified" || step.actionKind === "risk_gate.evaluated") {
    const ruleText = step.ruleId ? (RULE_LABELS[step.ruleId]?.[locale] ?? step.ruleId) : "";
    const actionText = step.actionType ? (ACTION_TYPE_LABELS[step.actionType]?.[locale] ?? step.actionType) : "";
    return locale === "ko"
      ? `위험 게이트 평가${ruleText ? ` (${ruleText})` : ""}: ${actionText ? `${actionText} 조치에 대해 ` : ""}운영자 승인(HIL) 필요 판정`
      : `Risk gate evaluation${ruleText ? ` (${ruleText})` : ""}: human approval (HIL) required${actionText ? ` for ${actionText}` : ""}`;
  }
  if (step.actionKind === "hil.requested") {
    const ruleText = step.ruleId ? (RULE_LABELS[step.ruleId]?.[locale] ?? step.ruleId) : subject;
    return locale === "ko"
      ? `${ruleText}${targetSuffix} 조치를 위한 운영자 승인(HIL) 요청 생성`
      : `Created human approval (HIL) request for ${ruleText}${targetSuffix}`;
  }
  if (step.actionKind === "hil.request.dispatch_unavailable") {
    const ruleText = step.ruleId ? (RULE_LABELS[step.ruleId]?.[locale] ?? step.ruleId) : "";
    return locale === "ko"
      ? `${ruleText ? `${ruleText} - ` : ""}외부 알림 채널 전송 생략 (Shadow 모드로 콘솔 승인 대기열 보관)`
      : `${ruleText ? `${ruleText} - ` : ""}external approval dispatch skipped (retained in shadow queue)`;
  }
  if (step.actionKind === "hil.timeout") {
    const ruleText = step.ruleId ? (RULE_LABELS[step.ruleId]?.[locale] ?? step.ruleId) : "";
    const targetLabel = ruleText ? `${ruleText}${targetSuffix}` : subject;
    return locale === "ko"
      ? `${targetLabel ? `${targetLabel} - ` : ""}운영자 승인 대기 시간 만료(미실행 종료)`
      : `${targetLabel ? `${targetLabel} - ` : ""}human approval window expired (closed without execution)`;
  }
  if (step.actionKind === "control_loop.t1_evaluate") {
    const reasonText = step.reason ? presentReasonLabel(step.reason, locale) : "";
    return locale === "ko"
      ? `${subject ? `${subject} ` : ""}T1 유사 사례 비교 평가 - ${reasonText || "보류"}`
      : `${subject ? `${subject} ` : ""}T1 similarity evaluation - ${reasonText || "abstained"}`;
  }
  if (step.actionKind === "control_loop.abstain") {
    const reasonText = step.reason ? presentReasonLabel(step.reason, locale) : "";
    return locale === "ko"
      ? `${subject ? `${subject} ` : ""}규칙 매칭 점검 - ${reasonText || "자동 조치 보류"}`
      : `${subject ? `${subject} ` : ""}rule matching check - ${reasonText || "abstained"}`;
  }
  if (step.actionKind === "control_loop.compliant") {
    const ruleText = step.ruleId ? (RULE_LABELS[step.ruleId]?.[locale] ?? step.ruleId) : subject;
    return locale === "ko"
      ? `${ruleText} 평가 완료 - 모든 정책 기준 충족(위반 없음)`
      : `${ruleText} evaluated - all policy criteria satisfied`;
  }
  if (step.actionKind === "measurement.control_loop.v1") {
    const outcomeText = step.outcome ? formatOutcomeLabel(step.outcome, locale) : "";
    return locale === "ko"
      ? `${subject ? `${subject} ` : ""}컨트롤 루프 처리 결과 계측 기록${outcomeText ? ` (${outcomeText})` : ""}`
      : `Recorded ${subject ? `${subject} ` : ""}control-loop outcome measurement${outcomeText ? ` (${outcomeText})` : ""}`;
  }
  if (step.actionKind === "observation-campaign.source-transition") {
    const domKey = step.domain ?? "metrics";
    const domLabel = OBSERVATION_DOMAIN_LABELS[domKey]?.[locale] ?? domKey;
    const outcomeText = step.outcome ? formatOutcomeLabel(step.outcome, locale) : "";
    return locale === "ko"
      ? `${domLabel} 관측 캠페인 소스 상태 기록${outcomeText ? ` - ${outcomeText}` : ""}`
      : `Recorded ${domLabel} campaign source status${outcomeText ? ` - ${outcomeText}` : ""}`;
  }
  if (step.actionKind === "audit.record") {
    if (step.aggregateType === "forseti.no_rule_match") {
      const cnt = step.aggregateCount ?? 1;
      return locale === "ko"
        ? `규칙 미일치 이벤트 ${cnt}건을 감사 원장에 집계 기록`
        : `Recorded aggregate of ${cnt} unmatched-rule event(s) in audit ledger`;
    }
    if (step.eventType === "inventory.resource_observed") {
      return locale === "ko"
        ? `${subject || "리소스"} 인벤토리 관측 이벤트를 감사 원장에 보존`
        : `Retained ${subject || "resource"} inventory observation event in audit ledger`;
    }
    if (step.eventType === "inventory.resource_changed") {
      return locale === "ko"
        ? `${subject || "리소스"} 인벤토리 변경 감지 이벤트를 감사 원장에 보존`
        : `Retained ${subject || "resource"} inventory change event in audit ledger`;
    }
  }
  return step.summary === step.actionKind
    ? presentActionKindLabel(step.actionKind, locale)
    : step.summary;
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
