import type { RouterCandidate, RouterSnapshot } from "./backend-types";

/** Preserves legacy router identity while admitting only valid optional measurement metadata. */
export function parseRouter(raw: unknown): RouterSnapshot | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  const chose = typeof record.chose === "string" ? record.chose : null;
  if (chose === null) return undefined;
  const reason = typeof record.reason === "string" ? record.reason : "";
  const candidates = parseRouterCandidates(record.candidates);
  const visionRecord = typeof record.vision === "object" && record.vision !== null
    ? record.vision as Record<string, unknown>
    : null;
  const visionChose = typeof visionRecord?.chose === "string" ? visionRecord.chose : null;
  const vision = visionRecord
    ? {
        available: visionRecord.available === true,
        chose: visionChose,
        candidates: parseRouterCandidates(visionRecord.candidates),
      }
    : undefined;
  const updatedAt = parseRouterTimestamp(record.updated_at);
  const expiresAt = parseRouterTimestamp(record.expires_at);
  const interval = record.interval_seconds;
  return {
    chose, reason, candidates,
    ...(updatedAt ? { updated_at: updatedAt } : {}),
    ...(expiresAt ? { expires_at: expiresAt } : {}),
    ...(typeof interval === "number" && Number.isFinite(interval) && interval > 0
      ? { interval_seconds: interval } : {}),
    ...(vision ? { vision } : {}),
  };
}

function parseRouterTimestamp(raw: unknown): string | undefined {
  return typeof raw === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(raw) &&
    Number.isFinite(Date.parse(raw)) ? raw : undefined;
}

function latency(raw: unknown): number | null {
  return typeof raw === "number" && Number.isFinite(raw) && raw >= 0 ? raw : null;
}

function parseRouterCandidates(raw: unknown): RouterCandidate[] {
  const rawCandidates = Array.isArray(raw) ? raw : [];
  const candidates: RouterCandidate[] = [];
  for (const candidate of rawCandidates) {
    if (typeof candidate !== "object" || candidate === null) continue;
    const record = candidate as Record<string, unknown>;
    const deployment = typeof record.deployment === "string" ? record.deployment : null;
    if (deployment === null) continue;
    const p50 = latency(record.p50_ms);
    const p95 = latency(record.p95_ms);
    const samples = typeof record.samples === "number" &&
      Number.isSafeInteger(record.samples) && record.samples >= 0 ? record.samples : 0;
    const historyRaw = Array.isArray(record.history_ms) ? record.history_ms : [];
    const history = historyRaw.filter((item): item is number => latency(item) !== null);
    const measuredAt = parseRouterTimestamp(record.measured_at);
    const rawStatus = record.status;
    const status = rawStatus === "measured" || rawStatus === "unmeasured" ||
      rawStatus === "failed" || rawStatus === "stale" ? rawStatus : undefined;
    candidates.push({
      deployment, p50_ms: p50, p95_ms: p95, samples, history_ms: history,
      ...(status ? { status } : rawStatus !== undefined ? { status: "unmeasured" as const } : {}),
      ...(measuredAt ? { measured_at: measuredAt } : {}),
      ...(record.measured_at !== undefined && !measuredAt && status !== "failed" && status !== "stale"
        ? { status: "unmeasured" as const } : {}),
    });
  }
  return candidates;
}
