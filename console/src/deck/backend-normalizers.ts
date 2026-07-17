import { readConsolePreferences } from "../preferences";
import type {
  AnswerEvidenceManifest,
  AnswerVerification,
  AnswerVerificationStatus,
  AtomicAnswerClaim,
  AtomicClaimStatus,
  DelegationMetadata,
  EvidenceManifestEntry,
  RetrievalSourcePreview,
  RouterCandidate,
  RouterSnapshot,
} from "./backend-types";

export function parseRetrievalSourcePreviews(
  raw: unknown,
): readonly RetrievalSourcePreview[] {
  if (!Array.isArray(raw)) return [];
  const sources: RetrievalSourcePreview[] = [];
  for (const item of raw.slice(0, 8)) {
    if (typeof item !== "object" || item === null) continue;
    const record = item as Record<string, unknown>;
    const side = record.side_effect_class;
    if (
      typeof record.kind !== "string" ||
      typeof record.label !== "string" ||
      typeof record.detail !== "string" ||
      (side !== "read" && side !== "route" && side !== "simulate" && side !== "ground")
    ) continue;
    sources.push({
      kind: record.kind,
      label: record.label,
      detail: record.detail,
      side_effect_class: side,
    });
  }
  return sources;
}

export function parseDelegation(raw: unknown): DelegationMetadata | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;
  if (typeof record.primary_agent !== "string" || record.primary_agent.length === 0) {
    return undefined;
  }
  const contributors = Array.isArray(record.contributors)
    ? record.contributors.filter((item): item is string => typeof item === "string").slice(0, 8)
    : [];
  return {
    primary_agent: record.primary_agent,
    contributors,
    ...(typeof record.trace_ref === "string" && record.trace_ref.length > 0
      ? { trace_ref: record.trace_ref }
      : {}),
  };
}

export function newRequestId(): string {
  const cryptoLike = globalThis.crypto as { randomUUID?: () => string } | undefined;
  return cryptoLike?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function parseVerificationStatus(raw: unknown): AnswerVerificationStatus | null {
  return raw === "verified" ||
      raw === "consistent" ||
      raw === "corrected" ||
      raw === "unverified"
    ? raw
    : null;
}

export function parseAnswerVerification(raw: unknown): AnswerVerification | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;
  const status = parseVerificationStatus(record.status);
  if (status === null || typeof record.authority !== "string") return undefined;
  const refs = Array.isArray(record.evidence_refs)
    ? record.evidence_refs.filter((item): item is string => typeof item === "string")
    : [];
  const failedClaimIds = Array.isArray(record.failed_claim_ids)
    ? record.failed_claim_ids.filter((item): item is string => typeof item === "string")
    : [];
  const claims = parseAtomicClaims(record.claims);
  const manifest = parseEvidenceManifest(record.evidence_manifest);
  const artifactPresent = record.claims !== undefined || record.evidence_manifest !== undefined;
  const malformedArtifact = artifactPresent && (claims === null || manifest === null);
  return {
    status: malformedArtifact ? "unverified" : status,
    authority: record.authority,
    checks_completed:
      typeof record.checks_completed === "number" ? record.checks_completed : 0,
    checks_total: typeof record.checks_total === "number" ? record.checks_total : 0,
    evidence_refs: refs,
    reason_code: malformedArtifact
      ? "malformed_verification_artifact"
      : (typeof record.reason_code === "string" ? record.reason_code : null),
    claims: claims ?? [],
    ...(manifest ? { evidence_manifest: manifest } : {}),
    failed_claim_ids: failedClaimIds,
  };
}

function parseAtomicClaims(raw: unknown): AtomicAnswerClaim[] | null {
  if (raw === undefined) return [];
  if (!Array.isArray(raw)) return null;
  const claims: AtomicAnswerClaim[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) return null;
    const claim = item as Record<string, unknown>;
    const kind = claim.kind;
    const status = claim.status;
    const span = claim.span;
    const spanRecord =
      typeof span === "object" && span !== null
        ? (span as Record<string, unknown>)
        : null;
    const start = spanRecord?.start;
    const end = spanRecord?.end;
    if (
      typeof claim.claim_id !== "string" ||
      !["id", "number", "percentage", "timestamp", "causal", "scope"].includes(
        String(kind),
      ) ||
      typeof claim.text !== "string" ||
      typeof start !== "number" ||
      typeof end !== "number" ||
      typeof claim.raw_value !== "string" ||
      typeof claim.normalized_value !== "string" ||
      (claim.unit !== null && typeof claim.unit !== "string") ||
      !validStringArray(claim.anchors) ||
      !["supported", "unsupported", "ambiguous"].includes(String(status)) ||
      !validStringArray(claim.evidence_refs) ||
      (claim.reason_code !== null && typeof claim.reason_code !== "string")
    ) return null;
    claims.push({
      claim_id: claim.claim_id,
      kind: kind as AtomicAnswerClaim["kind"],
      text: claim.text,
      span: { start, end },
      raw_value: claim.raw_value,
      normalized_value: claim.normalized_value,
      unit: claim.unit as string | null,
      anchors: claim.anchors as string[],
      status: status as AtomicClaimStatus,
      evidence_refs: claim.evidence_refs as string[],
      reason_code: claim.reason_code as string | null,
    });
  }
  return claims;
}

function parseEvidenceManifest(raw: unknown): AnswerEvidenceManifest | null | undefined {
  if (raw === undefined) return undefined;
  if (typeof raw !== "object" || raw === null) return null;
  const manifest = raw as Record<string, unknown>;
  if (!Array.isArray(manifest.entries)) return null;
  const entries: EvidenceManifestEntry[] = [];
  for (const item of manifest.entries) {
    if (typeof item !== "object" || item === null) return null;
    const entry = item as Record<string, unknown>;
    if (
      typeof entry.ref !== "string" ||
      typeof entry.path !== "string" ||
      typeof entry.field !== "string" ||
      typeof entry.kind !== "string" ||
      typeof entry.raw_value !== "string" ||
      typeof entry.normalized_value !== "string" ||
      !validStringArray(entry.anchors)
    ) return null;
    entries.push({
      ref: entry.ref,
      path: entry.path,
      field: entry.field,
      kind: entry.kind,
      raw_value: entry.raw_value,
      normalized_value: entry.normalized_value,
      anchors: entry.anchors,
    });
  }
  if (
    typeof manifest.schema_version !== "number" ||
    typeof manifest.manifest_id !== "string" ||
    typeof manifest.authority !== "string" ||
    (manifest.route_id !== null && typeof manifest.route_id !== "string") ||
    (manifest.captured_at !== null && typeof manifest.captured_at !== "string") ||
    typeof manifest.complete !== "boolean" ||
    typeof manifest.source_entry_count !== "number"
  ) return null;
  return {
    schema_version: manifest.schema_version,
    manifest_id: manifest.manifest_id,
    authority: manifest.authority,
    route_id: manifest.route_id as string | null,
    captured_at: manifest.captured_at as string | null,
    complete: manifest.complete,
    source_entry_count: manifest.source_entry_count,
    entries,
  };
}

function validStringArray(raw: unknown): raw is string[] {
  return Array.isArray(raw) && raw.every((item) => typeof item === "string");
}

export function extractString(payload: unknown, key: string): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === "string" ? value : null;
}

export function extractNumber(payload: unknown, key: string): number | null {
  if (typeof payload !== "object" || payload === null) return null;
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function totalTokensOf(raw: unknown): number | null {
  if (typeof raw !== "object" || raw === null) return null;
  const usage = raw as Record<string, unknown>;
  const total = usage.total_tokens;
  if (typeof total === "number" && Number.isFinite(total) && total >= 0) {
    return Math.round(total);
  }
  const prompt = usage.prompt_tokens;
  const completion = usage.completion_tokens;
  if (
    typeof prompt === "number" &&
    Number.isFinite(prompt) &&
    typeof completion === "number" &&
    Number.isFinite(completion)
  ) {
    return Math.round(prompt + completion);
  }
  return null;
}

export function tokenSuffix(usage: unknown): string {
  if (!readConsolePreferences().showTokenUsage) return "";
  const total = totalTokensOf(usage);
  if (total === null) return "";
  const label =
    total >= 1000 ? `${(total / 1000).toFixed(total >= 10000 ? 0 : 1)}k` : `${total}`;
  return ` · ${label} tok`;
}

export function parseRouter(raw: unknown): RouterSnapshot | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;
  const chose = typeof record.chose === "string" ? record.chose : null;
  if (chose === null) return undefined;
  const reason = typeof record.reason === "string" ? record.reason : "";
  const rawCandidates = Array.isArray(record.candidates) ? record.candidates : [];
  const candidates: RouterCandidate[] = [];
  for (const candidate of rawCandidates) {
    if (typeof candidate !== "object" || candidate === null) continue;
    const candidateRecord = candidate as Record<string, unknown>;
    const deployment =
      typeof candidateRecord.deployment === "string" ? candidateRecord.deployment : null;
    if (deployment === null) continue;
    const p50 =
      typeof candidateRecord.p50_ms === "number" && Number.isFinite(candidateRecord.p50_ms)
        ? candidateRecord.p50_ms
        : null;
    const p95 =
      typeof candidateRecord.p95_ms === "number" && Number.isFinite(candidateRecord.p95_ms)
        ? candidateRecord.p95_ms
        : null;
    const samples =
      typeof candidateRecord.samples === "number" && Number.isFinite(candidateRecord.samples)
        ? candidateRecord.samples
        : 0;
    const historyRaw = Array.isArray(candidateRecord.history_ms)
      ? candidateRecord.history_ms
      : [];
    const history: number[] = [];
    for (const item of historyRaw) {
      if (typeof item === "number" && Number.isFinite(item) && item >= 0) history.push(item);
    }
    candidates.push({ deployment, p50_ms: p50, p95_ms: p95, samples, history_ms: history });
  }
  return { chose, reason, candidates };
}
