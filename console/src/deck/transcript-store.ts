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
    .filter((t) => t.streaming !== true && t.text.trim().length > 0)
    .slice(-maxTurns)
    .map((t) => {
      const base: PersistedTurn = { id: t.id, role: t.role, text: t.text, at: t.at };
      return {
        ...base,
        ...(t.source ? { source: t.source } : {}),
        ...(t.agent ? { agent: t.agent } : {}),
        ...(t.citations ? { citations: t.citations } : {}),
        ...(t.followUps ? { followUps: t.followUps } : {}),
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
    const turn: PersistedTurn = {
      id: rec.id,
      role: rec.role,
      text: rec.text,
      at: rec.at,
      ...(typeof rec.source === "string" ? { source: rec.source } : {}),
      ...(typeof rec.agent === "string" ? { agent: rec.agent } : {}),
      ...(validCitations(rec.citations) ? { citations: rec.citations } : {}),
      ...(validStringArray(rec.followUps) ? { followUps: rec.followUps } : {}),
    };
    out.push(turn);
  }
  return out;
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
