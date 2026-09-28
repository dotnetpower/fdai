import type {
  ContextReceipt,
  ContextReceiptFreshness,
  TurnBudgetExhaustion,
  TurnBudgetMeasure,
  TurnBudgetTelemetry,
  WorkProgressDensity,
  WorkProgressShape,
} from "./backend-types";

// Optional work progress contracts from the persisted trajectory detail. Each parser fails
// closed: a malformed value is dropped on its own, so valid evidence beside it survives.

const DENSITIES = new Set<WorkProgressDensity>(["compact", "procedural"]);
const EXHAUSTION_REASONS = new Set<TurnBudgetExhaustion>([
  "deadline",
  "model_calls",
  "tokens",
  "rate_limited",
  "cancelled",
]);
const FRESHNESS = new Set<ContextReceiptFreshness>(["fresh", "stale", "superseded"]);
const MAX_WAVES = 8;
const MAX_PLANNED_READS = 64;
const MAX_CONTEXT_RECEIPTS = 4;
const MAX_RECEIPT_ID_CHARS = 128;
const MAX_RECEIPT_LABEL_CHARS = 80;
const MAX_TIMESTAMP_CHARS = 64;
const MAX_MEASURE = 10_000_000;
const DIGEST = /^[0-9a-f]{64}$/;

export function parseWorkProgressShape(raw: unknown): WorkProgressShape | undefined {
  const record = objectRecord(raw);
  if (!record || record.schema_version !== 1) return undefined;
  const density = record.density;
  if (typeof density !== "string" || !DENSITIES.has(density as WorkProgressDensity)) return undefined;
  if (!boundedInteger(record.waves, 1, MAX_WAVES) ||
      !boundedInteger(record.planned_reads, 0, MAX_PLANNED_READS)) return undefined;
  // A compact shape describes one wave with at most one read.
  if (density === "compact" && (record.waves !== 1 || record.planned_reads > 1)) return undefined;
  return {
    schema_version: 1,
    density: density as WorkProgressDensity,
    waves: record.waves,
    planned_reads: record.planned_reads,
  };
}

export function parseTurnBudget(raw: unknown): TurnBudgetTelemetry | undefined {
  const record = objectRecord(raw);
  if (!record || record.schema_version !== 1 || typeof record.complete !== "boolean" ||
      !validTimestamp(record.as_of)) return undefined;
  const reason = record.exhaustion_reason;
  if (reason !== undefined &&
      (typeof reason !== "string" || !EXHAUSTION_REASONS.has(reason as TurnBudgetExhaustion))) {
    return undefined;
  }
  // A measure may end above its maximum only when it is the reason the turn ended: observed token
  // usage replaces its reservation before the check, and a deadline is noticed after it passes.
  // Model calls are reserved before each call, so they never overshoot.
  const modelCalls = parseMeasure(record.model_calls, { reservable: true, overshoot: false });
  const tokens = parseMeasure(record.tokens, { reservable: true, overshoot: reason === "tokens" });
  const elapsed = parseMeasure(record.elapsed_ms, { reservable: false, overshoot: reason === "deadline" });
  if (!modelCalls || !tokens || !elapsed) return undefined;
  return {
    schema_version: 1,
    model_calls: modelCalls,
    tokens,
    elapsed_ms: elapsed,
    as_of: record.as_of,
    complete: record.complete,
    ...(reason !== undefined ? { exhaustion_reason: reason as TurnBudgetExhaustion } : {}),
  };
}

export function parseContextReceipts(raw: unknown): readonly ContextReceipt[] | undefined {
  if (!Array.isArray(raw) || raw.length > MAX_CONTEXT_RECEIPTS) return undefined;
  const receipts: ContextReceipt[] = [];
  for (const item of raw) {
    const receipt = parseContextReceipt(item);
    if (!receipt) return undefined;
    receipts.push(receipt);
  }
  if (new Set(receipts.map((receipt) => receipt.receipt_id)).size !== receipts.length) return undefined;
  return receipts;
}

function parseContextReceipt(raw: unknown): ContextReceipt | undefined {
  const record = objectRecord(raw);
  if (!record || record.kind !== "operator_preference") return undefined;
  const freshness = record.freshness;
  if (!boundedText(record.receipt_id, MAX_RECEIPT_ID_CHARS) ||
      typeof record.digest !== "string" || !DIGEST.test(record.digest) ||
      !validTimestamp(record.observed_at) ||
      typeof freshness !== "string" || !FRESHNESS.has(freshness as ContextReceiptFreshness) ||
      !boundedText(record.label, MAX_RECEIPT_LABEL_CHARS)) return undefined;
  return {
    receipt_id: record.receipt_id,
    kind: "operator_preference",
    digest: record.digest,
    observed_at: record.observed_at,
    freshness: freshness as ContextReceiptFreshness,
    label: record.label,
  };
}

function parseMeasure(
  raw: unknown,
  rules: { readonly reservable: boolean; readonly overshoot: boolean },
): TurnBudgetMeasure | undefined {
  const record = objectRecord(raw);
  if (!record ||
      !boundedInteger(record.used, 0, MAX_MEASURE) ||
      !boundedInteger(record.reserved, 0, MAX_MEASURE) ||
      !boundedInteger(record.maximum, 1, MAX_MEASURE)) return undefined;
  if (!rules.reservable && record.reserved !== 0) return undefined;
  if (!rules.overshoot && record.used + record.reserved > record.maximum) return undefined;
  return { used: record.used, reserved: record.reserved, maximum: record.maximum };
}

function objectRecord(raw: unknown): Record<string, unknown> | undefined {
  return typeof raw === "object" && raw !== null && !Array.isArray(raw)
    ? raw as Record<string, unknown>
    : undefined;
}

function boundedInteger(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= minimum && value <= maximum;
}

function boundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maximum;
}

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_TIMESTAMP_CHARS && Number.isFinite(Date.parse(value));
}
