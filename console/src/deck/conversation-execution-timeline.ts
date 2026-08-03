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
  readonly details: ExecutionTimelineDetails;
}

interface RawTimelineItem extends Omit<ExecutionTimelineItem, "leftPct" | "widthPct"> {}

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
  const tailMs = actualSpanMs > 0 ? actualSpanMs * 0.05 : SINGLETON_SPAN_MS;
  const denominator = actualSpanMs + tailMs;
  return items.map((item) => {
    const itemStart = Date.parse(item.startedAt);
    const leftPct = ((itemStart - startMs) / denominator) * 100;
    const rawWidth = (item.durationMs / denominator) * 100;
    return {
      ...item,
      leftPct,
      widthPct: Math.min(Math.max(rawWidth, MIN_BAR_PCT), Math.max(MIN_BAR_PCT, 100 - leftPct)),
    };
  });
}

function rawItems(
  trajectory: ConversationTrajectory,
  includeModelCalls: boolean,
): RawTimelineItem[] {
  const items: RawTimelineItem[] = [];
  if (trajectory.startedAt) {
    items.push(pointItem("turn-input", "input", "operator", trajectory.startedAt, {
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
  for (const branch of trajectory.branches) {
    if (!branch.completedAt) continue;
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
    items.push(pointItem("turn-answer", "answer", "terminal", trajectory.completedAt, {
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
