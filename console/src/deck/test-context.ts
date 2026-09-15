/** Strict candidate-only test-context data shared by chat and the review form. */
export interface TestContextDraft {
  readonly target_ref: string;
  readonly signal_code: string;
  readonly source_ref: string;
  readonly semantic_receipt: string;
  readonly window: {
    readonly expected_min: number;
    readonly expected_max: number;
    readonly effective_from: string;
    readonly effective_to: string;
  };
  readonly authority: "candidate_only";
  readonly execution_authority: false;
}

function object(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= 512;
}

function timestamp(value: unknown): value is string {
  if (typeof value !== "string" || value.startsWith("0000-") || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value) ||
      !Number.isFinite(Date.parse(value))) return false;
  const calendar = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isFinite(calendar.getTime()) && calendar.toISOString().slice(0, 10) === value.slice(0, 10);
}

function before(start: string, end: string): boolean {
  const startMs = Date.parse(start);
  const endMs = Date.parse(end);
  const remainder = (value: string) => (value.match(/\.(\d{1,6})/)?.[1] ?? "").padEnd(6, "0").slice(3);
  return startMs < endMs || (startMs === endMs && remainder(start) < remainder(end));
}

/** Reject malformed or authority-bearing drafts; never infer fields from answer prose. */
export function parseTestContextDraft(value: unknown): TestContextDraft | undefined {
  const draft = object(value);
  const window = object(draft?.window);
  if (!draft || !window || Object.keys(draft).sort().join() !==
      "authority,execution_authority,semantic_receipt,signal_code,source_ref,target_ref,window" ||
      Object.keys(window).sort().join() !== "effective_from,effective_to,expected_max,expected_min" ||
      draft.authority !== "candidate_only" || draft.execution_authority !== false ||
      !text(draft.target_ref) || !text(draft.signal_code) || !text(draft.source_ref) ||
      typeof draft.semantic_receipt !== "string" || !/^sha256:[a-f0-9]{64}$/.test(draft.semantic_receipt) ||
      typeof window.expected_min !== "number" || !Number.isFinite(window.expected_min) ||
      typeof window.expected_max !== "number" || !Number.isFinite(window.expected_max) ||
      window.expected_min > window.expected_max || !timestamp(window.effective_from) ||
      !timestamp(window.effective_to) ||
      !before(window.effective_from, window.effective_to)) return undefined;
  return {
    target_ref: draft.target_ref, signal_code: draft.signal_code, source_ref: draft.source_ref,
    semantic_receipt: draft.semantic_receipt, authority: "candidate_only", execution_authority: false,
    window: { expected_min: window.expected_min, expected_max: window.expected_max,
      effective_from: window.effective_from, effective_to: window.effective_to },
  };
}