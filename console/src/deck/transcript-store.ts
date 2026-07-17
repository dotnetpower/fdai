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
} from "./backend";

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
      return {
        ...base,
        ...(t.source ? { source: t.source } : {}),
        ...(t.agent ? { agent: t.agent } : {}),
        ...(t.citations ? { citations: t.citations } : {}),
        ...(t.followUps ? { followUps: t.followUps } : {}),
        ...(t.terminal !== undefined ? { terminal: t.terminal } : {}),
        ...(typeof t.revision === "number" ? { revision: t.revision } : {}),
        ...(validVerification(t.verification) ? { verification: t.verification } : {}),
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
    const turn: PersistedTurn = {
      id: rec.id,
      role: rec.role,
      text: rec.text,
      at: rec.at,
      ...(typeof rec.source === "string" ? { source: rec.source } : {}),
      ...(typeof rec.agent === "string" ? { agent: rec.agent } : {}),
      ...(validCitations(rec.citations) ? { citations: rec.citations } : {}),
      ...(validStringArray(rec.followUps) ? { followUps: rec.followUps } : {}),
      ...(typeof rec.terminal === "boolean" ? { terminal: rec.terminal } : {}),
      ...(typeof rec.revision === "number" && Number.isInteger(rec.revision)
        ? { revision: rec.revision }
        : {}),
      ...(validVerification(rec.verification) ? { verification: rec.verification } : {}),
      ...(answerPlan ? { answerPlan } : {}),
      ...(answerPlanning ? { answerPlanning } : {}),
      ...(codeArtifacts.length > 0 ? { codeArtifacts } : {}),
    };
    out.push(turn);
  }
  return out;
}

function validVerification(value: unknown): value is NonNullable<PersistedTurn["verification"]> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  const status = record.status;
  const baseValid = (
    (status === "verified" ||
      status === "consistent" ||
      status === "corrected" ||
      status === "unverified") &&
    typeof record.authority === "string" &&
    typeof record.checks_completed === "number" &&
    typeof record.checks_total === "number" &&
    Array.isArray(record.evidence_refs) &&
    record.evidence_refs.every((item) => typeof item === "string") &&
    (record.reason_code === null || typeof record.reason_code === "string")
  );
  if (!baseValid) return false;
  if (record.claims !== undefined && !validClaims(record.claims)) return false;
  if (
    record.failed_claim_ids !== undefined &&
    !validStringArray(record.failed_claim_ids)
  ) return false;
  if (
    record.evidence_manifest !== undefined &&
    !validEvidenceManifest(record.evidence_manifest)
  ) return false;
  return true;
}

function validClaims(value: unknown): boolean {
  if (!Array.isArray(value)) return false;
  return value.every((item) => {
    if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
    const claim = item as Record<string, unknown>;
    const span = claim.span;
    const spanRecord =
      typeof span === "object" && span !== null
        ? (span as Record<string, unknown>)
        : null;
    return (
      typeof claim.claim_id === "string" &&
      typeof claim.kind === "string" &&
      typeof claim.text === "string" &&
      typeof spanRecord?.start === "number" &&
      typeof spanRecord?.end === "number" &&
      typeof claim.raw_value === "string" &&
      typeof claim.normalized_value === "string" &&
      (claim.unit === null || typeof claim.unit === "string") &&
      validStringArray(claim.anchors) &&
      (claim.status === "supported" ||
        claim.status === "unsupported" ||
        claim.status === "ambiguous") &&
      validStringArray(claim.evidence_refs) &&
      (claim.reason_code === null || typeof claim.reason_code === "string")
    );
  });
}

function validEvidenceManifest(value: unknown): boolean {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const manifest = value as Record<string, unknown>;
  if (!Array.isArray(manifest.entries)) return false;
  return (
    typeof manifest.schema_version === "number" &&
    typeof manifest.manifest_id === "string" &&
    typeof manifest.authority === "string" &&
    (manifest.route_id === null || typeof manifest.route_id === "string") &&
    (manifest.captured_at === null || typeof manifest.captured_at === "string") &&
    typeof manifest.complete === "boolean" &&
    typeof manifest.source_entry_count === "number" &&
    manifest.entries.every((item) => {
      if (typeof item !== "object" || item === null || Array.isArray(item)) return false;
      const entry = item as Record<string, unknown>;
      return (
        typeof entry.ref === "string" &&
        typeof entry.path === "string" &&
        typeof entry.field === "string" &&
        typeof entry.kind === "string" &&
        typeof entry.raw_value === "string" &&
        typeof entry.normalized_value === "string" &&
        validStringArray(entry.anchors)
      );
    })
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
