/**
 * Transcript persistence for the command deck.
 *
 * The deck keeps a short conversation in memory. To survive an accidental
 * reload or browser restart, completed turns are mirrored into browser-local
 * storage under a principal-scoped conversation key. PostgreSQL remains the
 * memory of record. This module is the pure serialise/parse core so it is
 * unit-tested without a DOM; the component supplies the storage object.
 *
 * Only completed turns are persisted (a mid-stream turn is skipped), the buffer
 * is capped, and parsing is defensive: any malformed payload yields an empty
 * transcript rather than throwing into the render path.
 */

import {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseGroundedCodeArtifacts,
  parseIncidentCandidates,
  parseModelTrace,
  parseTurnTiming,
  type AnswerPlanMetadata,
  type AnswerPlanningMetadata,
  type AnswerVerification,
  type DelegationMetadata,
  type EvidenceBranch,
  type GroundedCodeArtifact,
  type InvestigationActivity,
  type IncidentCandidate,
  type ModelTrace,
  type TurnTiming,
  type TrajectoryDetail,
  type ResourceContext,
} from "./backend";
import {
  parseAnswerVerification,
  parseDelegation,
  parseResourceContext,
} from "./backend-normalizers";
import { parseTrajectoryDetail } from "./trajectory-detail";
import { parseIntentGraph, parseIntentGraphEvidence } from "./intent-graph";

export const TRANSCRIPT_KEY = "fdai.deck.transcript.v1";
export const MAX_TRANSCRIPT_JSON_CHARS = 4 * 1024 * 1024;
export const MAX_TRANSCRIPT_TURNS = 40;

const MAX_TURN_TEXT_CHARS = 256 * 1024;
const MAX_TURN_ID_CHARS = 256;
const MAX_TURN_SOURCE_CHARS = 1024;
const MAX_TURN_TIME_CHARS = 64;
const MAX_TURN_RECORDED_AT_CHARS = 64;
const MAX_AGENT_NAME_CHARS = 64;
const MAX_CITATIONS = 512;
const MAX_CITATION_LABEL_CHARS = 1024;
const MAX_CITATION_VALUE_CHARS = 16 * 1024;
const MAX_FOLLOW_UPS = 8;
const MAX_FOLLOW_UP_CHARS = 512;
const MAX_ACTIVITIES = 64;
const MAX_BRANCHES = 4;
const MAX_ACTIVITY_ID_CHARS = 128;
const MAX_ACTIVITY_KIND_CHARS = 128;
const MAX_ACTIVITY_LABEL_CHARS = 512;
const MAX_ACTIVITY_DETAIL_CHARS = 16 * 1024;
const MAX_ACTIVITY_AUTHORITY_CHARS = 1024;
const MAX_ACTIVITY_TIMESTAMP_CHARS = 64;

/**
 * Per-session storage key. The deck keeps distinct conversations - the general
 * screen deck vs a chat scoped to one agent - in separate transcripts so their
 * turns never bleed into each other. The general session uses {@link
 * TRANSCRIPT_KEY} unchanged (back-compat with the single-session format).
 */
export function transcriptKeyFor(sessionKey: string): string {
  return sessionKey === "screen" ? TRANSCRIPT_KEY : `${TRANSCRIPT_KEY}::${sessionKey}`;
}

/** The persisted shape - a lean subset of the in-memory turn. */
export interface PersistedTurn {
  readonly id: string;
  readonly role: "operator" | "deck";
  readonly text: string;
  readonly recordedAt?: string;
  readonly groundingText?: string;
  readonly kind?: "message" | "activity";
  readonly activities?: readonly InvestigationActivity[];
  readonly branches?: readonly EvidenceBranch[];
  readonly at: string;
  readonly source?: string;
  /** Agent name when this turn speaks as a specific agent (icon + name header). */
  readonly agent?: string;
  readonly citations?: readonly { readonly label: string; readonly value?: string }[];
  readonly followUps?: readonly string[];
  readonly terminal?: boolean;
  readonly revision?: number;
  readonly verification?: AnswerVerification;
  readonly answerPlan?: AnswerPlanMetadata;
  readonly answerPlanning?: AnswerPlanningMetadata;
  readonly delegation?: DelegationMetadata;
  readonly codeArtifacts?: readonly GroundedCodeArtifact[];
  readonly incidentCandidates?: readonly IncidentCandidate[];
  readonly modelTrace?: ModelTrace;
  readonly turnTiming?: TurnTiming;
  readonly trajectoryDetail?: TrajectoryDetail;
  readonly resourceContext?: ResourceContext;
  readonly intentGraph?: import("./backend-types").IntentGraphMetadata;
  readonly intentGraphEvidence?: import("./backend-types").IntentGraphEvidence;
  readonly evidenceMode?: import("./backend-types").IntentEvidenceMode;
}

interface MaybeStreamingTurn extends PersistedTurn {
  readonly streaming?: boolean;
}

/**
 * Serialise turns to a JSON string. Drops any still-streaming turn, keeps only
 * the persisted fields, and caps to the most recent ``maxTurns``.
 */
export function serializeTurns(
  turns: readonly MaybeStreamingTurn[],
  maxTurns: number = MAX_TRANSCRIPT_TURNS,
): string {
  const turnLimit = Number.isSafeInteger(maxTurns) && maxTurns >= 0
    ? Math.min(maxTurns, MAX_TRANSCRIPT_TURNS)
    : MAX_TRANSCRIPT_TURNS;
  if (turnLimit === 0) return "[]";
  const persisted: PersistedTurn[] = turns
    .filter(
      (t) =>
        t.streaming !== true &&
        boundedString(t.id, MAX_TURN_ID_CHARS) &&
        boundedString(t.text, MAX_TURN_TEXT_CHARS) &&
        t.text.trim().length > 0 &&
        boundedString(t.at, MAX_TURN_TIME_CHARS) &&
        (t.role === "operator" || t.terminal !== false),
    )
    .slice(-turnLimit)
    .map((t) => {
      const base: PersistedTurn = { id: t.id, role: t.role, text: t.text, at: t.at };
      const verification = parseAnswerVerification(t.verification);
      const answerPlan = parseAnswerPlan(t.answerPlan);
      const answerPlanning = parseAnswerPlanning(t.answerPlanning);
      const delegation = parseDelegation(t.delegation);
      const codeArtifacts = parseGroundedCodeArtifacts(t.codeArtifacts);
      const incidentCandidates = parseIncidentCandidates({
        schema_version: 1,
        locale: t.incidentCandidates?.[0]?.locale ?? "en",
        candidates: t.incidentCandidates?.map((candidate) => ({
          incident_id: candidate.incidentId,
          correlation_id: candidate.correlationId,
          title: candidate.title,
          severity: candidate.severity,
          status: candidate.status,
          last_updated_at: candidate.lastUpdatedAt,
        })) ?? [],
      });
      const modelTrace = parseModelTrace(t.modelTrace);
      const turnTiming = parseTurnTiming(t.turnTiming);
      const trajectoryDetail = parseTrajectoryDetail(t.trajectoryDetail);
      const resourceContext = parseResourceContext(t.resourceContext);
      const intentGraph = parseIntentGraph(t.intentGraph);
      const intentGraphEvidence = parseIntentGraphEvidence(t.intentGraphEvidence);
      return {
        ...base,
        ...(boundedString(t.groundingText, MAX_TURN_TEXT_CHARS)
          ? { groundingText: t.groundingText }
          : {}),
        ...(boundedTimestamp(t.recordedAt) ? { recordedAt: t.recordedAt } : {}),
        ...(boundedString(t.source, MAX_TURN_SOURCE_CHARS) ? { source: t.source } : {}),
        ...(t.kind ? { kind: t.kind } : {}),
        ...(validActivities(t.activities) ? { activities: t.activities } : {}),
        ...(validBranches(t.branches) ? { branches: t.branches } : {}),
        ...(boundedString(t.agent, MAX_AGENT_NAME_CHARS) ? { agent: t.agent } : {}),
        ...(validCitations(t.citations) ? { citations: t.citations } : {}),
        ...(validFollowUps(t.followUps) ? { followUps: t.followUps } : {}),
        ...(t.terminal !== undefined ? { terminal: t.terminal } : {}),
        ...(nonnegativeSafeInteger(t.revision) ? { revision: t.revision } : {}),
        ...(verification ? { verification } : {}),
        ...(answerPlan ? { answerPlan } : {}),
        ...(answerPlanning ? { answerPlanning } : {}),
        ...(delegation ? { delegation } : {}),
        ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
        ...(incidentCandidates.length > 0 ? { incidentCandidates } : {}),
        ...(modelTrace ? { modelTrace } : {}),
        ...(turnTiming ? { turnTiming } : {}),
        ...(trajectoryDetail ? { trajectoryDetail } : {}),
        ...(resourceContext ? { resourceContext } : {}),
        ...(intentGraph ? { intentGraph } : {}),
        ...(intentGraphEvidence ? {
          intentGraphEvidence,
          evidenceMode: intentGraphEvidence.evidence_mode,
        } : {}),
      };
    });
  let serialized = JSON.stringify(persisted);
  while (serialized.length > MAX_TRANSCRIPT_JSON_CHARS && persisted.length > 0) {
    persisted.shift();
    serialized = JSON.stringify(persisted);
  }
  return serialized;
}

/** Parse a persisted transcript defensively. Any malformed input yields ``[]``. */
export function parseTurns(raw: string | null): PersistedTurn[] {
  if (!raw || raw.length > MAX_TRANSCRIPT_JSON_CHARS) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: PersistedTurn[] = [];
  for (const item of parsed.slice(-MAX_TRANSCRIPT_TURNS)) {
    if (typeof item !== "object" || item === null) continue;
    const rec = item as Record<string, unknown>;
    if (!boundedString(rec.id, MAX_TURN_ID_CHARS)) continue;
    if (rec.role !== "operator" && rec.role !== "deck") continue;
    if (!boundedString(rec.text, MAX_TURN_TEXT_CHARS) || rec.text.trim().length === 0) continue;
    if (!boundedString(rec.at, MAX_TURN_TIME_CHARS)) continue;
    const answerPlan = parseAnswerPlan(rec.answerPlan);
    const answerPlanning = parseAnswerPlanning(rec.answerPlanning);
    const delegation = parseDelegation(rec.delegation);
    const codeArtifacts = parseGroundedCodeArtifacts(rec.codeArtifacts);
    const incidentCandidates = parseIncidentCandidates({
      schema_version: 1,
      locale: Array.isArray(rec.incidentCandidates) &&
          typeof rec.incidentCandidates[0] === "object" && rec.incidentCandidates[0] !== null
        ? (rec.incidentCandidates[0] as Record<string, unknown>).locale
        : "en",
      candidates: Array.isArray(rec.incidentCandidates)
        ? rec.incidentCandidates.map((candidate) => {
            if (typeof candidate !== "object" || candidate === null) return candidate;
            const item = candidate as Record<string, unknown>;
            return {
              incident_id: item.incidentId,
              correlation_id: item.correlationId,
              title: item.title,
              severity: item.severity,
              status: item.status,
              last_updated_at: item.lastUpdatedAt,
            };
          })
        : [],
    });
    const modelTrace = parseModelTrace(rec.modelTrace);
    const turnTiming = parseTurnTiming(rec.turnTiming);
    const trajectoryDetail = parseTrajectoryDetail(rec.trajectoryDetail);
    const verification = parseAnswerVerification(rec.verification);
    const resourceContext = parseResourceContext(rec.resourceContext);
    const intentGraph = parseIntentGraph(rec.intentGraph);
    const intentGraphEvidence = parseIntentGraphEvidence(rec.intentGraphEvidence);
    const turn: PersistedTurn = {
      id: rec.id,
      role: rec.role,
      text: rec.text,
      at: rec.at,
      ...(boundedTimestamp(rec.recordedAt) ? { recordedAt: rec.recordedAt } : {}),
      ...(boundedString(rec.groundingText, MAX_TURN_TEXT_CHARS)
        ? { groundingText: rec.groundingText }
        : {}),
      ...(boundedString(rec.source, MAX_TURN_SOURCE_CHARS) ? { source: rec.source } : {}),
      ...(rec.kind === "message" || rec.kind === "activity" ? { kind: rec.kind } : {}),
      ...(validActivities(rec.activities) ? { activities: rec.activities } : {}),
      ...(validBranches(rec.branches) ? { branches: rec.branches } : {}),
      ...(boundedString(rec.agent, MAX_AGENT_NAME_CHARS) ? { agent: rec.agent } : {}),
      ...(validCitations(rec.citations) ? { citations: rec.citations } : {}),
      ...(validFollowUps(rec.followUps) ? { followUps: rec.followUps } : {}),
      ...(typeof rec.terminal === "boolean" ? { terminal: rec.terminal } : {}),
      ...(nonnegativeSafeInteger(rec.revision)
        ? { revision: rec.revision }
        : {}),
      ...(verification ? { verification } : {}),
      ...(answerPlan ? { answerPlan } : {}),
      ...(answerPlanning ? { answerPlanning } : {}),
      ...(delegation ? { delegation } : {}),
      ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
      ...(incidentCandidates.length > 0 ? { incidentCandidates } : {}),
      ...(modelTrace ? { modelTrace } : {}),
      ...(turnTiming ? { turnTiming } : {}),
      ...(trajectoryDetail ? { trajectoryDetail } : {}),
      ...(resourceContext ? { resourceContext } : {}),
      ...(intentGraph ? { intentGraph } : {}),
      ...(intentGraphEvidence ? {
        intentGraphEvidence,
        evidenceMode: intentGraphEvidence.evidence_mode,
      } : {}),
    };
    out.push(turn);
  }
  return out;
}

function validBranches(value: unknown): value is readonly EvidenceBranch[] {
  if (!Array.isArray(value)) return false;
  const terminalStatuses = ["completed", "unavailable", "failed", "timed_out", "cancelled"];
  return value.length <= MAX_BRANCHES && value.every((item) => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
    const record = item as Record<string, unknown>;
    return (
      boundedString(record.branchId, 256) &&
      ["tool", "operational", "agent", "public_web"].includes(String(record.kind)) &&
      (record.parentBranchId === null || boundedString(record.parentBranchId, 256)) &&
      terminalStatuses.includes(String(record.status)) &&
      boundedString(record.summary, 512) &&
      boundedTimestamp(record.startedAt) &&
      (record.completedAt === undefined || boundedTimestamp(record.completedAt)) &&
      (record.durationMs === undefined || nonnegativeSafeInteger(record.durationMs)) &&
      Array.isArray(record.evidenceRefs) &&
      record.evidenceRefs.length <= 64 &&
      record.evidenceRefs.every((ref) => boundedString(ref, 1024))
    );
  });
}

function boundedTimestamp(value: unknown): value is string {
  return boundedString(value, MAX_TURN_RECORDED_AT_CHARS) && Number.isFinite(Date.parse(value));
}

function validActivities(value: unknown): value is readonly InvestigationActivity[] {
  if (!Array.isArray(value)) return false;
  return value.length <= MAX_ACTIVITIES && value.every((item) => {
    if (typeof item !== "object" || item === null) return false;
    const record = item as Record<string, unknown>;
    const completed = nullableNonnegativeSafeInteger(record.completed);
    const total = nullableNonnegativeSafeInteger(record.total);
    return (
      boundedString(record.activityId, MAX_ACTIVITY_ID_CHARS) &&
      boundedString(record.kind, MAX_ACTIVITY_KIND_CHARS) &&
      ["pending", "running", "completed", "unavailable", "failed"].includes(
        String(record.status),
      ) &&
      boundedString(record.label, MAX_ACTIVITY_LABEL_CHARS) &&
      (record.agent === undefined || boundedString(record.agent, MAX_AGENT_NAME_CHARS)) &&
      (record.detail === undefined || boundedString(record.detail, MAX_ACTIVITY_DETAIL_CHARS)) &&
      completed !== undefined &&
      total !== undefined &&
      !(completed !== null && total !== null && completed > total) &&
      (record.authority === undefined ||
        boundedString(record.authority, MAX_ACTIVITY_AUTHORITY_CHARS)) &&
      (record.observedAt === undefined ||
        boundedString(record.observedAt, MAX_ACTIVITY_TIMESTAMP_CHARS)) &&
      (record.execution === undefined || validExecution(record.execution))
    );
  });
}

function validExecution(value: unknown): boolean {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.tool === "string" &&
    record.tool.length > 0 &&
    record.tool.length <= 64 &&
    typeof record.command === "string" &&
    record.command.length > 0 &&
    record.command.length <= 16 * 1024 &&
    (record.inputKind === undefined || ["command", "query"].includes(String(record.inputKind))) &&
    record.redacted === true &&
    (record.output === undefined ||
      (typeof record.output === "string" && record.output.length <= 64 * 1024)) &&
    (record.outputTruncated === undefined || typeof record.outputTruncated === "boolean") &&
    (record.exitCode === undefined ||
      (typeof record.exitCode === "number" && Number.isSafeInteger(record.exitCode))) &&
    !(record.inputKind === "query" && record.exitCode !== undefined) &&
    (record.startedAt === undefined || boundedString(record.startedAt, 64)) &&
    (record.completedAt === undefined || boundedString(record.completedAt, 64)) &&
    (record.durationMs === undefined ||
      (typeof record.durationMs === "number" &&
        Number.isSafeInteger(record.durationMs) &&
        record.durationMs >= 0))
  );
}

function validFollowUps(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.length <= MAX_FOLLOW_UPS &&
    value.every((item) => boundedString(item, MAX_FOLLOW_UP_CHARS));
}

function validCitations(
  value: unknown,
): value is readonly { readonly label: string; readonly value?: string }[] {
  return Array.isArray(value) && value.length <= MAX_CITATIONS && value.every((item) => {
    if (item === null || typeof item !== "object" || Array.isArray(item)) return false;
    const record = item as Record<string, unknown>;
    return boundedString(record.label, MAX_CITATION_LABEL_CHARS) &&
      (record.value === undefined || boundedString(record.value, MAX_CITATION_VALUE_CHARS));
  });
}

function boundedString(value: unknown, maxChars: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maxChars;
}

function nonnegativeSafeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function nullableNonnegativeSafeInteger(value: unknown): number | null | undefined {
  if (value === null) return null;
  return nonnegativeSafeInteger(value) ? value : undefined;
}
