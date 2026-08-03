import type { ConversationTrajectory } from "./conversation-trajectory";
import type { TrajectoryPhaseState } from "./conversation-trajectory-presentation";

const MIN_BAR_PCT = 1.5;
const SINGLETON_SPAN_MS = 1000;

export type ExecutionTimelineKind = "turn" | "phase" | "evidence" | "model";

export type ExecutionTimelineFactKey =
  | "agent"
  | "authority"
  | "checks"
  | "contributors"
  | "evidence"
  | "evidenceRequirement"
  | "format"
  | "intent"
  | "model"
  | "modelCalls"
  | "reason"
  | "redactions"
  | "requestMessages"
  | "response"
  | "source"
  | "tool"
  | "usage";

export interface ExecutionTimelineFact {
  readonly key: ExecutionTimelineFactKey;
  readonly value: string;
}

export interface ExecutionTimelineDetails {
  readonly summary?: string;
  readonly facts: readonly ExecutionTimelineFact[];
  readonly evidenceRefs: readonly string[];
}

export interface ExecutionTimelineItem {
  readonly id: string;
  readonly kind: ExecutionTimelineKind;
  readonly label: string;
  readonly detail: string;
  readonly state: TrajectoryPhaseState;
  readonly startedAt: string;
  readonly completedAt: string;
  readonly durationMs: number;
  readonly leftPct: number;
  readonly widthPct: number;
  readonly gapLeftPct: number;
  readonly gapWidthPct: number;
  readonly displayLabel?: string;
  readonly details: ExecutionTimelineDetails;
}

export interface ExecutionTimelineWindow {
  readonly startedAt: string;
  readonly completedAt: string;
  readonly durationMs: number;
}

interface RawTimelineItem extends Omit<
  ExecutionTimelineItem,
  "leftPct" | "widthPct" | "gapLeftPct" | "gapWidthPct"
> {}

export function buildExecutionTimeline(
  trajectory: ConversationTrajectory,
  options: { readonly includeModelCalls?: boolean } = {},
): readonly ExecutionTimelineItem[] {
  const items = rawItems(trajectory, options.includeModelCalls !== false)
    .filter((item) => validInterval(item.startedAt, item.completedAt))
    .sort((left, right) => Date.parse(left.startedAt) - Date.parse(right.startedAt));
  if (items.length === 0) return [];
  const startMs = Math.min(...items.map((item) => Date.parse(item.startedAt)));
  const endMs = Math.max(...items.map((item) => Date.parse(item.completedAt)));
  const actualSpanMs = Math.max(0, endMs - startMs);
  const denominator = actualSpanMs > 0 ? actualSpanMs : SINGLETON_SPAN_MS;
  let coveredUntilMs = startMs;
  return items.map((item) => {
    const itemStart = Date.parse(item.startedAt);
    const itemEnd = Date.parse(item.completedAt);
    const rawLeft = ((itemStart - startMs) / denominator) * 100;
    const leftPct = Math.min(rawLeft, 100 - MIN_BAR_PCT);
    const rawWidth = (item.durationMs / denominator) * 100;
    const gapStartMs = coveredUntilMs;
    const gapDurationMs = Math.max(0, itemStart - gapStartMs);
    const gapLeftPct = ((gapStartMs - startMs) / denominator) * 100;
    const gapWidthPct = (gapDurationMs / denominator) * 100;
    coveredUntilMs = Math.max(coveredUntilMs, itemEnd);
    return {
      ...item,
      leftPct,
      widthPct: Math.min(Math.max(rawWidth, MIN_BAR_PCT), 100 - leftPct),
      gapLeftPct,
      gapWidthPct,
    };
  });
}

export function executionTimelineWindow(
  items: readonly ExecutionTimelineItem[],
): ExecutionTimelineWindow | undefined {
  if (items.length === 0) return undefined;
  const startedAt = items.reduce((earliest, item) =>
    Date.parse(item.startedAt) < Date.parse(earliest) ? item.startedAt : earliest,
  items[0]!.startedAt);
  const completedAt = items.reduce((latest, item) =>
    Date.parse(item.completedAt) > Date.parse(latest) ? item.completedAt : latest,
  items[0]!.completedAt);
  return {
    startedAt,
    completedAt,
    durationMs: Math.max(0, Date.parse(completedAt) - Date.parse(startedAt)),
  };
}

function rawItems(
  trajectory: ConversationTrajectory,
  includeModelCalls: boolean,
): RawTimelineItem[] {
  const items: RawTimelineItem[] = [];
  const inputAt = earliestTimestamp([
    trajectory.startedAt,
    trajectory.answer.turnTiming?.started_at,
    ...(trajectory.answer.turnTiming?.phases.map((phase) => phase.started_at) ?? []),
    ...trajectory.activities.map((activity) => activity.execution?.startedAt),
    ...trajectory.branches.map((branch) => branch.startedAt),
    ...(trajectory.answer.modelTrace?.calls.map((call) => call.started_at) ?? []),
  ]);
  if (inputAt) {
    items.push(pointItem("turn-input", "input", "operator", inputAt, {
      summary: trajectory.question.text,
      facts: [{ key: "source", value: "operator" }],
      evidenceRefs: [],
    }));
  }
  for (const phase of trajectory.answer.turnTiming?.phases ?? []) {
    items.push({
      id: `phase-${phase.phase}`,
      kind: "phase",
      label: phase.phase,
      detail: phase.status,
      state: phase.status,
      startedAt: phase.started_at,
      completedAt: phase.completed_at,
      durationMs: phase.duration_ms,
      details: phaseDetails(trajectory, phase.phase, includeModelCalls),
    });
  }
  const representedBranchIds = new Set<string>();
  for (const activity of trajectory.activities) {
    const execution = activity.execution;
    if (!execution?.startedAt || !execution.completedAt) continue;
    if (activity.branchId) representedBranchIds.add(activity.branchId);
    items.push({
      id: `activity-${activity.activityId}`,
      kind: "evidence",
      label: execution.inputKind === "query" ? "query" : "tool",
      displayLabel: activity.label,
      detail: activity.status,
      state: branchState(activity.status),
      startedAt: execution.startedAt,
      completedAt: execution.completedAt,
      durationMs: execution.durationMs ?? Math.max(
        0,
        Date.parse(execution.completedAt) - Date.parse(execution.startedAt),
      ),
      details: {
        ...(activity.detail ? { summary: activity.detail } : {}),
        facts: [
          { key: "tool", value: execution.tool },
          ...(activity.authority
            ? [{ key: "authority" as const, value: activity.authority }]
            : []),
          ...(activity.agent ? [{ key: "agent" as const, value: activity.agent }] : []),
        ],
        evidenceRefs: [],
      },
    });
  }
  for (const branch of trajectory.branches) {
    if (!branch.completedAt || representedBranchIds.has(branch.branchId)) continue;
    items.push({
      id: `evidence-${branch.branchId}`,
      kind: "evidence",
      label: branch.kind,
      detail: branch.status,
      state: branchState(branch.status),
      startedAt: branch.startedAt,
      completedAt: branch.completedAt,
      durationMs: branch.durationMs ?? Math.max(0, Date.parse(branch.completedAt) - Date.parse(branch.startedAt)),
      details: {
        summary: branch.summary,
        facts: [],
        evidenceRefs: branch.evidenceRefs,
      },
    });
  }
  if (includeModelCalls) {
    for (const call of trajectory.answer.modelTrace?.calls ?? []) {
      if (!call.completed_at || call.duration_ms === null) continue;
      items.push({
        id: `model-${call.call_id}`,
        kind: "model",
        label: call.kind,
        detail: call.model,
        state: call.status === "completed" ? "completed" : "degraded",
        startedAt: call.started_at,
        completedAt: call.completed_at,
        durationMs: call.duration_ms,
        details: {
          facts: [
            { key: "model", value: call.model },
            { key: "requestMessages", value: String(call.request.messages.length) },
            { key: "response", value: call.response ? "recorded" : "notRecorded" },
            ...(call.usage ? [{ key: "usage" as const, value: formatUsage(call.usage) }] : []),
            {
              key: "redactions",
              value: String(call.redactions.reduce(
                (total, redaction) => total + redaction.replacements,
                0,
              )),
            },
          ],
          evidenceRefs: [],
        },
      });
    }
  }
  if (trajectory.completedAt) {
    const source = trajectory.answer.source ?? trajectory.answer.agent ?? "recorded";
    const answerAt = latestTimestamp([
      trajectory.completedAt,
      trajectory.answer.turnTiming?.completed_at,
      ...(trajectory.answer.turnTiming?.phases.map((phase) => phase.completed_at) ?? []),
    ]) ?? trajectory.completedAt;
    items.push(pointItem("turn-answer", "answer", "terminal", answerAt, {
      facts: [
        { key: "source", value: source },
        ...(trajectory.answer.agent
          ? [{ key: "agent" as const, value: trajectory.answer.agent }]
          : []),
      ],
      evidenceRefs: trajectory.answer.verification?.evidence_refs ?? [],
    }));
  }
  return items;
}

function latestTimestamp(values: readonly (string | undefined)[]): string | undefined {
  return values.reduce<string | undefined>((latest, value) => {
    if (!value || !Number.isFinite(Date.parse(value))) return latest;
    if (!latest || Date.parse(value) > Date.parse(latest)) return value;
    return latest;
  }, undefined);
}

function earliestTimestamp(values: readonly (string | undefined)[]): string | undefined {
  return values.reduce<string | undefined>((earliest, value) => {
    if (!value || !Number.isFinite(Date.parse(value))) return earliest;
    if (!earliest || Date.parse(value) < Date.parse(earliest)) return value;
    return earliest;
  }, undefined);
}

function pointItem(
  id: string,
  label: string,
  detail: string,
  at: string,
  details: ExecutionTimelineDetails,
): RawTimelineItem {
  return {
    id,
    kind: "turn",
    label,
    detail,
    state: "completed",
    startedAt: at,
    completedAt: at,
    durationMs: 0,
    details,
  };
}

function phaseDetails(
  trajectory: ConversationTrajectory,
  phase: string,
  includeModelCalls: boolean,
): ExecutionTimelineDetails {
  const { answer, branches } = trajectory;
  const evidenceRefs = uniqueStrings([
    ...branches.flatMap((branch) => branch.evidenceRefs),
    ...(answer.verification?.evidence_refs ?? []),
  ]);
  if (phase === "semantic_plan") {
    return {
      facts: [
        ...(answer.answerPlan
          ? [
              { key: "intent" as const, value: answer.answerPlan.intent },
              { key: "format" as const, value: answer.answerPlan.format },
              {
                key: "evidenceRequirement" as const,
                value: answer.answerPlan.evidence_requirement,
              },
            ]
          : []),
        ...(answer.answerPlanning?.primary_agent
          ? [{ key: "agent" as const, value: answer.answerPlanning.primary_agent }]
          : []),
        ...(answer.answerPlanning?.consulted_agents.length
          ? [{
              key: "contributors" as const,
              value: answer.answerPlanning.consulted_agents.join(", "),
            }]
          : []),
      ],
      evidenceRefs: answer.answerPlanning?.contributions.flatMap(
        (contribution) => contribution.evidence_refs,
      ) ?? [],
    };
  }
  if (phase === "evidence") {
    const completed = branches.filter((branch) => branch.status === "completed").length;
    const summary = branches.map((branch) => branch.summary).filter(Boolean).join(" · ");
    return {
      ...(summary ? { summary } : {}),
      facts: [{ key: "evidence", value: `${completed}/${branches.length}` }],
      evidenceRefs,
    };
  }
  if (phase === "generation") {
    return {
      facts: [
        {
          key: "source",
          value: answer.source ?? answer.agent ?? "recorded",
        },
        {
          key: "modelCalls",
          value: includeModelCalls && answer.modelTrace
            ? String(answer.modelTrace.calls.length)
            : "notRecorded",
        },
      ],
      evidenceRefs: [],
    };
  }
  if (phase === "quality_review" || phase === "verification") {
    const verification = answer.verification;
    return {
      facts: verification
        ? [
            { key: "authority", value: verification.authority },
            {
              key: "checks",
              value: `${verification.checks_completed}/${verification.checks_total}`,
            },
            ...(verification.reason_code
              ? [{ key: "reason" as const, value: verification.reason_code }]
              : []),
          ]
        : [],
      evidenceRefs: verification?.evidence_refs ?? [],
    };
  }
  return { facts: [], evidenceRefs: [] };
}

function formatUsage(usage: Readonly<Record<string, number>>): string {
  return Object.entries(usage)
    .map(([key, value]) => `${key}: ${value}`)
    .join(" / ");
}

function uniqueStrings(values: readonly string[]): string[] {
  return [...new Set(values)];
}

function branchState(status: string): TrajectoryPhaseState {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "pending" || status === "running") return "running";
  return "degraded";
}

function validInterval(startedAt: string, completedAt: string): boolean {
  const start = Date.parse(startedAt);
  const end = Date.parse(completedAt);
  return Number.isFinite(start) && Number.isFinite(end) && end >= start;
}
