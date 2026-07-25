/**
 * grounded-sources - shape a deck reply's grounding metadata into the clean,
 * source-streaming presentation the design mock (mocks/ui/deck-sources.html)
 * shows: typed source cards with a coloured badge, a pill breakdown, a
 * reconstructed retrieval trace, and the numbered inline citation marks.
 *
 * Honest-data only: every field here is derived from data the reply already
 * carries - the evidence manifest (field / value / path / kind), the plain
 * citations, the reply ``source`` descriptor (``llm:<model> · <ms> · <tokens>`` or
 * ``deterministic``), the verification check counts, and the shadow
 * answer-planning consulted-agent list. Nothing is fetched or fabricated.
 *
 * Pure and dependency-free so it is unit-testable; grounded-reply.tsx and
 * rich-content.tsx consume these builders.
 */

import type { AnswerVerification } from "./backend";
import type { Citation } from "./citations";

const MAX_MODEL_DESCRIPTOR_CHARS = 128;
const MAX_SOURCE_DETAIL_CHARS = 160;
const MODEL_DESCRIPTOR = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const LATENCY_DESCRIPTOR = /^\d+(?:\.\d+)?ms$/;
const TOKEN_DESCRIPTOR = /^\d+(?:\.\d+)?k? tok$/;

/** Fixed badge palette. Each tone maps to a `.deck-src-badge.is-<tone>` class
 *  in styles.css. Codes are category tokens (like the mock's WAF / CIS / OPA
 *  badges), not localized prose. */
export type SourceTone =
  | "screen"
  | "records"
  | "incident"
  | "audit"
  | "cause"
  | "policy"
  | "metric"
  | "identifier"
  | "time"
  | "evidence";

/** One grounding source, numbered so an inline `[n]` chip and its expanded
 *  card agree. `value` is the literal string an inline chip anchors to (null
 *  when the source is structural, e.g. the whole screen). */
export interface GroundedSource {
  readonly n: number;
  readonly badge: string;
  readonly tone: SourceTone;
  readonly title: string;
  readonly meta: string;
  readonly path: string | null;
  readonly value: string | null;
}

/** One inline citation anchor: place a `[n]` chip after the first occurrence
 *  of `value` in the answer text. */
export interface CiteMark {
  readonly n: number;
  readonly value: string;
  readonly title: string;
}

/** One stat span in the grounded pill (e.g. `7 sources`, `2/2 checks`). */
export interface PillStat {
  readonly value: string;
  readonly label: string;
}

/** One reconstructed retrieval-trace stage. `side` mirrors the mock's
 *  side_effect_class tag (read / route / ground / verify). */
export interface TraceStage {
  readonly action: "retrieve" | "infer" | "deterministic" | "consult" | "handoff" | "ground" | "verify";
  readonly label: string;
  readonly detail: string;
  readonly side: "read" | "route" | "ground" | "verify";
  readonly status: "complete" | "attention";
  readonly model?: string;
  readonly from?: string;
  readonly to?: string;
}

/** Parsed reply source descriptor. */
export type ReplySource =
  | { readonly kind: "deterministic"; readonly reason: string | null }
  | { readonly kind: "llm"; readonly model: string; readonly timing: string | null }
  | { readonly kind: "other"; readonly raw: string };

/** Parse the reply ``source`` descriptor (``llm:<model> · <ms> · <tokens>`` or
 *  ``deterministic``) into its display parts. */
export function parseReplySource(source: string | undefined): ReplySource | null {
  if (source === undefined) return null;
  const trimmed = source.trim();
  if (trimmed.length === 0) return null;
  if (trimmed === "deterministic") return { kind: "deterministic", reason: null };
  const deterministic = /^deterministic \(([^()]*)\)$/.exec(trimmed);
  if (deterministic) {
    const reason = deterministic[1]?.trim() ?? "";
    if (!validSourceDetail(reason)) return { kind: "other", raw: trimmed };
    return { kind: "deterministic", reason: reason.length > 0 ? reason : null };
  }
  if (trimmed.startsWith("llm:")) {
    const rest = trimmed.slice(4).trim();
    const canonicalParts = rest.split(" · ").map((part) => part.trim());
    if (canonicalParts.length > 1) {
      const [model, ...metrics] = canonicalParts;
      if (!validModelDescriptor(model ?? "") || !validMetrics(metrics)) {
        return { kind: "other", raw: trimmed };
      }
      return {
        kind: "llm",
        model: model ?? "",
        timing: metrics.join(" · "),
      };
    }
    const sep = rest.indexOf(" - ");
    if (sep >= 0) {
      const model = rest.slice(0, sep).trim();
      const timing = rest.slice(sep + 3).trim();
      if (!validModelDescriptor(model) || !LATENCY_DESCRIPTOR.test(timing)) {
        return { kind: "other", raw: trimmed };
      }
      return { kind: "llm", model, timing: timing.length > 0 ? timing : null };
    }
    if (!validModelDescriptor(rest)) return { kind: "other", raw: trimmed };
    return { kind: "llm", model: rest, timing: null };
  }
  return { kind: "other", raw: trimmed };
}

function validModelDescriptor(model: string): boolean {
  return model.length <= MAX_MODEL_DESCRIPTOR_CHARS && MODEL_DESCRIPTOR.test(model);
}

function validMetrics(metrics: readonly string[]): boolean {
  if (metrics.length === 0 || metrics.length > 2) return false;
  let sawLatency = false;
  let sawTokens = false;
  for (const metric of metrics) {
    if (!validSourceDetail(metric)) return false;
    if (LATENCY_DESCRIPTOR.test(metric)) {
      if (sawLatency) return false;
      sawLatency = true;
      continue;
    }
    if (TOKEN_DESCRIPTOR.test(metric)) {
      if (sawTokens) return false;
      sawTokens = true;
      continue;
    }
    return false;
  }
  return true;
}

function validSourceDetail(value: string): boolean {
  return value.length <= MAX_SOURCE_DETAIL_CHARS && !/[\u0000-\u001f\u007f]/.test(value);
}

/** Categorise a source into a badge code + tone from whatever hints it carries
 *  (evidence kind, path, field, or citation label). */
function categorize(
  kind: string,
  path: string,
  field: string,
  label: string,
): { readonly badge: string; readonly tone: SourceTone } {
  const hint = `${kind} ${path} ${field} ${label}`.toLowerCase();
  if (label === "screen" || /(^|[^a-z])screen/.test(hint)) {
    return { badge: "SCREEN", tone: "screen" };
  }
  if (label.startsWith("records.") || /\brecord/.test(hint)) {
    return { badge: "RECORDS", tone: "records" };
  }
  // Value-kind badges win next: at the field/card level the entry's own kind is
  // its most specific descriptor and gives the list the mock's visual variety.
  if (kind === "causal") return { badge: "CAUSE", tone: "cause" };
  if (/rego|polic/.test(hint)) return { badge: "POLICY", tone: "policy" };
  if (kind === "id") return { badge: "ID", tone: "identifier" };
  if (kind === "percentage") return { badge: "PCT", tone: "metric" };
  if (kind === "number") return { badge: "NUM", tone: "metric" };
  if (kind === "timestamp") return { badge: "TIME", tone: "time" };
  if (kind === "scope") return { badge: "SCOPE", tone: "records" };
  // Source-provenance hints only when the entry carries no distinguishing kind
  // (typically plain citations that have a label but no evidence kind).
  if (/incident/.test(hint)) return { badge: "INCIDENT", tone: "incident" };
  if (/audit|\bevent|\bevt/.test(hint)) return { badge: "AUDIT", tone: "audit" };
  if (/\brca\b|cause|reason/.test(hint)) return { badge: "CAUSE", tone: "cause" };
  if (label.startsWith("evidence.")) return { badge: "EVIDENCE", tone: "evidence" };
  return { badge: "SOURCE", tone: "evidence" };
}

/** Build the ordered, numbered grounding-source list. Prefers the richer
 *  evidence manifest (field / value / path / kind); falls back to the plain
 *  citation labels when no manifest is attached. */
export function buildSources(
  verification: AnswerVerification | undefined,
  cites: readonly Citation[],
): GroundedSource[] {
  const entries = verification?.evidence_manifest?.entries ?? [];
  if (entries.length > 0) {
    return entries.map((e, i) => {
      const { badge, tone } = categorize(e.kind, e.path, e.field, "");
      const value = e.raw_value.trim();
      return {
        n: i + 1,
        badge,
        tone,
        title: e.field || e.kind,
        meta: e.raw_value,
        path: e.path.length > 0 ? e.path : null,
        value: value.length > 0 ? value : null,
      };
    });
  }
  return cites.map((c, i) => {
    const { badge, tone } = categorize("", "", "", c.label);
    const value = c.value?.trim() ?? "";
    return {
      n: i + 1,
      badge,
      tone,
      title: c.label,
      meta: c.value ?? "",
      path: null,
      value: value.length >= 2 ? value : null,
    };
  });
}

/** Reduce the ordered sources to the inline citation anchors worth placing:
 *  those with a literal value at least two characters long. Deduplicates on
 *  value so a repeated fact does not fight for two different numbers. */
export function citationMarks(sources: readonly GroundedSource[]): CiteMark[] {
  const seen = new Set<string>();
  const marks: CiteMark[] = [];
  for (const source of sources) {
    const value = source.value;
    if (value === null || value.length < 2) continue;
    if (seen.has(value)) continue;
    seen.add(value);
    marks.push({
      n: source.n,
      value,
      title: source.meta ? `${source.title} - ${source.meta}` : source.title,
    });
  }
  return marks;
}

/** Build the grounded-pill stat spans from data the reply already holds. Only
 *  stats with real values are emitted (no zero-filled placeholders). */
export function pillStats(input: {
  readonly sourceCount: number;
  readonly checksCompleted: number;
  readonly checksTotal: number;
  readonly agentCount: number;
}): PillStat[] {
  const stats: PillStat[] = [];
  if (input.sourceCount > 0) {
    stats.push({
      value: String(input.sourceCount),
      label: input.sourceCount === 1 ? "source" : "sources",
    });
  }
  if (input.checksTotal > 0) {
    stats.push({
      value: `${input.checksCompleted}/${input.checksTotal}`,
      label: "checks",
    });
  }
  if (input.agentCount > 0) {
    stats.push({
      value: String(input.agentCount),
      label: input.agentCount === 1 ? "agent" : "agents",
    });
  }
  return stats;
}

/** Reconstruct the retrieval-trace stages from the reply's own metadata, so an
 *  operator can re-open "how this was grounded" after the answer settles. */
export function groundingStages(input: {
  readonly sources: readonly GroundedSource[];
  readonly source: string | undefined;
  readonly verification: AnswerVerification | undefined;
  readonly agents: readonly string[];
  readonly handoff?: {
    readonly from: string;
    readonly to: string;
    readonly reason?: string;
  };
}): TraceStage[] {
  const stages: TraceStage[] = [];
  if (input.sources.length > 0) {
    stages.push({
      action: "retrieve",
      label: "Retrieved grounding sources",
      detail: `${input.sources.length} read-only`,
      side: "read",
      status: "complete",
    });
  }
  const parsed = parseReplySource(input.source);
  if (parsed?.kind === "llm") {
    stages.push({
      action: "infer",
      label: `Reasoned with ${parsed.model}`,
      detail: parsed.timing ?? "narrator",
      side: "route",
      status: "complete",
      model: parsed.model,
    });
  } else if (parsed?.kind === "deterministic") {
    stages.push({
      action: "deterministic",
      label: "Used deterministic answerer",
      detail: parsed.reason ?? "no model",
      side: "route",
      status: "complete",
    });
  }
  if (input.agents.length > 0) {
    stages.push({
      action: "consult",
      label: "Consulted specialist agents",
      detail: input.agents.join(", "),
      side: "read",
      status: "complete",
    });
  }
  if (input.handoff) {
    stages.push({
      action: "handoff",
      label: `Agent handoff: ${input.handoff.from} to ${input.handoff.to}`,
      detail: input.handoff.reason ?? "specialist abstained",
      side: "route",
      status: "complete",
      from: input.handoff.from,
      to: input.handoff.to,
    });
  }
  const verification = input.verification;
  if (verification) {
    const refs = verification.evidence_refs.length;
    const manifest = verification.evidence_manifest;
    const incompleteManifest = manifest?.complete === false;
    if (refs > 0 || incompleteManifest) {
      stages.push({
        action: "ground",
        label: "Bound answer to evidence",
        detail: incompleteManifest
          ? `${manifest.entries.length}/${manifest.source_entry_count} manifest sources available`
          : `${refs} reference${refs === 1 ? "" : "s"}`,
        side: "ground",
        status: incompleteManifest ? "attention" : "complete",
      });
    }
    if (verification.checks_total > 0) {
      stages.push({
        action: "verify",
        label: "Checked answer",
        detail: `${verification.checks_completed}/${verification.checks_total} checks`,
        side: "verify",
        status: verification.status === "unverified" ? "attention" : "complete",
      });
    }
  }
  return stages;
}
