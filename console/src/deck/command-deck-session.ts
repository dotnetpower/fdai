import type { ConversationTurnPayload } from "../user-context-client";
import type {
  AnswerPlanMetadata,
  AnswerPlanningMetadata,
  AnswerVerification,
  DelegationMetadata,
  EvidenceFreshnessContext,
  GroundedCodeArtifact,
  ModelTrace,
  TurnTiming,
  TrajectoryDetail,
  ProgressiveAnswer,
  ResourceContext,
  RouterSnapshot,
} from "./backend";
import {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseGroundedCodeArtifacts,
  parseModelTrace,
  parseTurnTiming,
} from "./backend-parsers";
import {
  parseAnswerVerification,
  parseDelegation,
  parseEvidenceFreshnessContext,
  parseResourceContext,
  parseRouter,
} from "./backend-normalizers";
import { parseTrajectoryDetail } from "./trajectory-detail";

const MAX_SESSION_ID_CHARS = 200;
const MAX_REPLAY_PAYLOAD_CHARS = 512 * 1024;

export interface RestoredTurn {
  readonly id: string;
  readonly role: "operator" | "deck";
  readonly text: string;
  readonly source?: string;
  readonly terminal: boolean;
  readonly agent?: string;
  readonly at: string;
  readonly recordedAt: string;
  readonly router?: RouterSnapshot;
  readonly verification?: AnswerVerification;
  readonly delegation?: DelegationMetadata;
  readonly answerPlan?: AnswerPlanMetadata;
  readonly answerPlanning?: AnswerPlanningMetadata;
  readonly codeArtifacts?: readonly GroundedCodeArtifact[];
  readonly modelTrace?: ModelTrace;
  readonly turnTiming?: TurnTiming;
  readonly trajectoryDetail?: TrajectoryDetail;
  readonly resourceContext?: ResourceContext;
  readonly evidenceFreshnessContext?: EvidenceFreshnessContext;
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
  const replay = parseReplayPayload(turn);
  const router = parseRouter(replay?.router);
  const verification = parseAnswerVerification(replay?.verification);
  const delegation = parseDelegation(replay?.delegation);
  const answerPlan = parseAnswerPlan(replay?.answer_plan);
  const answerPlanning = parseAnswerPlanning(replay?.answer_planning);
  const codeArtifacts = parseGroundedCodeArtifacts(replay?.code_artifacts);
  const modelTrace = parseModelTrace(replay?.model_trace);
  const turnTiming = parseTurnTiming(replay?.turn_timing);
  const trajectoryDetail = parseTrajectoryDetail(replay?.trajectory_detail);
  const resourceContext = parseResourceContext(replay?.resource_context);
  const evidenceFreshnessContext = parseEvidenceFreshnessContext(
    replay?.evidence_freshness_context,
  );
  const source = turn.metadata.source ?? replaySource(replay) ??
    (turn.role === "assistant" ? "history" : undefined);
  const agent = turn.metadata.agent ?? delegation?.primary_agent;
  return {
    id: turn.turn_id,
    role: turn.role === "operator" ? "operator" : "deck",
    text: turn.content,
    at: time,
    recordedAt: turn.recorded_at,
    terminal: true,
    ...(source ? { source } : {}),
    ...(agent ? { agent } : {}),
    ...(router ? { router } : {}),
    ...(verification ? { verification } : {}),
    ...(delegation ? { delegation } : {}),
    ...(answerPlan ? { answerPlan } : {}),
    ...(answerPlanning ? { answerPlanning } : {}),
    ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
    ...(modelTrace ? { modelTrace } : {}),
    ...(turnTiming ? { turnTiming } : {}),
    ...(trajectoryDetail ? { trajectoryDetail } : {}),
    ...(resourceContext ? { resourceContext } : {}),
    ...(evidenceFreshnessContext ? { evidenceFreshnessContext } : {}),
  };
}

function parseReplayPayload(turn: ConversationTurnPayload): Record<string, unknown> | undefined {
  const raw = turn.metadata.replay_payload;
  if (typeof raw !== "string" || raw.length === 0 || raw.length > MAX_REPLAY_PAYLOAD_CHARS) {
    return undefined;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return undefined;
    const payload = parsed as Record<string, unknown>;
    return payload.answer === turn.content ? payload : undefined;
  } catch {
    return undefined;
  }
}

function replaySource(payload: Record<string, unknown> | undefined): string | undefined {
  if (!payload) return undefined;
  if (typeof payload.source === "string" && payload.source.length > 0 && payload.source.length <= 1024) {
    return payload.source;
  }
  if (typeof payload.model !== "string" || payload.model.length === 0 || payload.model.length > 128) {
    return undefined;
  }
  const latency = typeof payload.latency_ms === "number" && Number.isFinite(payload.latency_ms) && payload.latency_ms >= 0
    ? ` / ${Math.round(payload.latency_ms)}ms`
    : "";
  return `llm:${payload.model}${latency}`;
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
