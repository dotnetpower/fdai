/**
 * Transcript persistence for the command deck.
 *
 * The deck keeps a short conversation in memory. To survive an accidental
 * reload (but nothing more), completed turns are mirrored into
 * ``sessionStorage`` - tab-scoped and cleared when the tab closes. This module
 * is the pure serialise/parse core so it is unit-tested without a DOM; the
 * component supplies the storage object.
 *
 * Only completed turns are persisted (a mid-stream turn is skipped), the buffer
 * is capped, and parsing is defensive: any malformed payload yields an empty
 * transcript rather than throwing into the render path.
 */

import {
  parseAnswerPlan,
  parseAnswerPlanning,
  parseGroundedCodeArtifacts,
  type AnswerPlanMetadata,
  type AnswerPlanningMetadata,
  type AnswerVerification,
  type GroundedCodeArtifact,
  type InvestigationActivity,
} from "./backend";
import { parseAnswerVerification } from "./backend-normalizers";

export const TRANSCRIPT_KEY = "fdai.deck.transcript.v1";

/**
 * Per-session storage key. The deck keeps distinct conversations - the general
 * screen deck vs a chat scoped to one agent - in separate transcripts so their
 * turns never bleed into each other. The general session uses {@link
 * TRANSCRIPT_KEY} unchanged (back-compat with the single-session format).
 */
export function transcriptKeyFor(sessionKey: string): string {
  return sessionKey === "screen" ? TRANSCRIPT_KEY : `${TRANSCRIPT_KEY}::${sessionKey}`;
}

const DEFAULT_MAX_TURNS = 40;

/** The persisted shape - a lean subset of the in-memory turn. */
export interface PersistedTurn {
  readonly id: string;
  readonly role: "operator" | "deck";
  readonly text: string;
  readonly kind?: "message" | "activity";
  readonly activities?: readonly InvestigationActivity[];
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
  readonly codeArtifacts?: readonly GroundedCodeArtifact[];
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
  maxTurns: number = DEFAULT_MAX_TURNS,
): string {
  const persisted: PersistedTurn[] = turns
    .filter(
      (t) =>
        t.streaming !== true &&
        t.text.trim().length > 0 &&
        (t.role === "operator" || t.terminal !== false),
    )
    .slice(-maxTurns)
    .map((t) => {
      const base: PersistedTurn = { id: t.id, role: t.role, text: t.text, at: t.at };
      const verification = parseAnswerVerification(t.verification);
      return {
        ...base,
        ...(t.source ? { source: t.source } : {}),
        ...(t.kind ? { kind: t.kind } : {}),
        ...(validActivities(t.activities) ? { activities: t.activities } : {}),
        ...(t.agent ? { agent: t.agent } : {}),
        ...(t.citations ? { citations: t.citations } : {}),
        ...(t.followUps ? { followUps: t.followUps } : {}),
        ...(t.terminal !== undefined ? { terminal: t.terminal } : {}),
        ...(typeof t.revision === "number" ? { revision: t.revision } : {}),
        ...(verification ? { verification } : {}),
        ...(t.answerPlan ? { answerPlan: t.answerPlan } : {}),
        ...(t.answerPlanning ? { answerPlanning: t.answerPlanning } : {}),
        ...(t.codeArtifacts && t.codeArtifacts.length > 0
          ? { codeArtifacts: t.codeArtifacts }
          : {}),
      };
    });
  return JSON.stringify(persisted);
}

/** Parse a persisted transcript defensively. Any malformed input yields ``[]``. */
export function parseTurns(raw: string | null): PersistedTurn[] {
  if (!raw) return [];
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  const out: PersistedTurn[] = [];
  for (const item of parsed) {
    if (typeof item !== "object" || item === null) continue;
    const rec = item as Record<string, unknown>;
    if (typeof rec.id !== "string") continue;
    if (rec.role !== "operator" && rec.role !== "deck") continue;
    if (typeof rec.text !== "string") continue;
    if (typeof rec.at !== "string") continue;
    const answerPlan = parseAnswerPlan(rec.answerPlan);
    const answerPlanning = parseAnswerPlanning(rec.answerPlanning);
    const codeArtifacts = parseGroundedCodeArtifacts(rec.codeArtifacts);
    const verification = parseAnswerVerification(rec.verification);
    const turn: PersistedTurn = {
      id: rec.id,
      role: rec.role,
      text: rec.text,
      at: rec.at,
      ...(typeof rec.source === "string" ? { source: rec.source } : {}),
      ...(rec.kind === "message" || rec.kind === "activity" ? { kind: rec.kind } : {}),
      ...(validActivities(rec.activities) ? { activities: rec.activities } : {}),
      ...(typeof rec.agent === "string" ? { agent: rec.agent } : {}),
      ...(validCitations(rec.citations) ? { citations: rec.citations } : {}),
      ...(validStringArray(rec.followUps) ? { followUps: rec.followUps } : {}),
      ...(typeof rec.terminal === "boolean" ? { terminal: rec.terminal } : {}),
      ...(typeof rec.revision === "number" && Number.isInteger(rec.revision)
        ? { revision: rec.revision }
        : {}),
      ...(verification ? { verification } : {}),
      ...(answerPlan ? { answerPlan } : {}),
      ...(answerPlanning ? { answerPlanning } : {}),
      ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
    };
    out.push(turn);
  }
  return out;
}

function validActivities(value: unknown): value is readonly InvestigationActivity[] {
  if (!Array.isArray(value)) return false;
  return value.length <= 64 && value.every((item) => {
    if (typeof item !== "object" || item === null) return false;
    const record = item as Record<string, unknown>;
    return (
      typeof record.activityId === "string" &&
      typeof record.kind === "string" &&
      ["pending", "running", "completed", "unavailable", "failed"].includes(
        String(record.status),
      ) &&
      typeof record.label === "string" &&
      (record.agent === undefined || typeof record.agent === "string") &&
      (record.detail === undefined || typeof record.detail === "string") &&
      (record.completed === null || typeof record.completed === "number") &&
      (record.total === null || typeof record.total === "number") &&
      (record.authority === undefined || typeof record.authority === "string") &&
      (record.observedAt === undefined || typeof record.observedAt === "string") &&
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
    record.redacted === true &&
    (record.output === undefined ||
      (typeof record.output === "string" && record.output.length <= 64 * 1024)) &&
    (record.outputTruncated === undefined || typeof record.outputTruncated === "boolean") &&
    (record.exitCode === undefined ||
      (typeof record.exitCode === "number" && Number.isSafeInteger(record.exitCode))) &&
    (record.startedAt === undefined || typeof record.startedAt === "string") &&
    (record.completedAt === undefined || typeof record.completedAt === "string") &&
    (record.durationMs === undefined ||
      (typeof record.durationMs === "number" &&
        Number.isSafeInteger(record.durationMs) &&
        record.durationMs >= 0))
  );
}

function validStringArray(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function validCitations(
  value: unknown,
): value is readonly { readonly label: string; readonly value?: string }[] {
  return Array.isArray(value) && value.every((item) => {
    if (item === null || typeof item !== "object" || Array.isArray(item)) return false;
    const record = item as Record<string, unknown>;
    return typeof record.label === "string" &&
      (record.value === undefined || typeof record.value === "string");
  });
}
