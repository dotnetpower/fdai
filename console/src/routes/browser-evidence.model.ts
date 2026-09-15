import { OperatorApiError } from "../api";
import { isRfc3339Timestamp } from "../time-format";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
} from "./panel-decode";

export type BrowserEvidenceRetention =
  | "held"
  | "expired_pending_purge"
  | "expiring"
  | "retained";
export type BrowserEvidenceAuditLinkState =
  | "exact"
  | "missing"
  | "malformed"
  | "ambiguous"
  | "unsupported_sequence";
export type BrowserEvidenceSort = "attention" | "newest";
export type BrowserEvidenceHostScope = "requested" | "final" | "either";
export type BrowserEvidenceFindingFilter = "present" | "clear";

export interface BrowserEvidenceItem {
  readonly artifact_id: string;
  readonly policy_id: string;
  readonly policy_version: number;
  readonly source_host: string;
  readonly final_host: string;
  readonly redirected: boolean;
  readonly captured_at: string;
  readonly expires_at: string;
  readonly selector_count: number;
  readonly redaction_count: number;
  readonly prompt_injection_finding_count: number;
  readonly digest_presence: {
    readonly screenshot: boolean;
    readonly text: boolean;
    readonly accessibility_snapshot: boolean;
  };
  readonly browser_version: string;
  readonly custody_audit_ref: string;
  readonly retention_state: BrowserEvidenceRetention;
  readonly legal_hold: boolean;
  readonly legal_hold_ref: string | null;
  readonly legal_hold_at: string | null;
  readonly audit: {
    readonly state: BrowserEvidenceAuditLinkState;
    readonly sequence: string | null;
    readonly correlation_id: string | null;
  };
  readonly isolation_verified: true;
  readonly untrusted: true;
  readonly can_authorize_action: false;
}

export interface BrowserEvidenceWorkspaceResponse {
  readonly schema_version: "2.0.0";
  readonly surface: "browser-evidence-workspace";
  readonly consistency: "drift_aware";
  readonly summary_scope: "filtered_and_snapshot";
  readonly observed_at: string;
  readonly source_observed_at: string | null;
  readonly loaded_count: number;
  readonly matching_admitted_count: number;
  readonly snapshot_total_count: number;
  readonly snapshot_admitted_count: number;
  readonly snapshot_withheld_count: number;
  readonly withheld_reasons: {
    readonly invalid_metadata: number;
    readonly trust_invalid: number;
    readonly isolation_unverified: number;
  };
  readonly summary: {
    readonly security_finding_count: number;
    readonly legal_hold_count: number;
    readonly expiring_count: number;
    readonly expired_pending_purge_count: number;
    readonly retained_count: number;
  };
  readonly has_more: boolean;
  readonly next_cursor: string | null;
  readonly page_complete: boolean;
  readonly items: readonly BrowserEvidenceItem[];
}

export interface BrowserEvidenceData {
  readonly page: BrowserEvidenceWorkspaceResponse;
  readonly items: readonly BrowserEvidenceItem[];
}

export interface BrowserEvidenceRequest {
  readonly params: Readonly<Record<string, string>>;
  readonly sort: BrowserEvidenceSort;
  readonly invalid: readonly string[];
  readonly hasFilters: boolean;
}

const ROOT_KEYS = new Set([
  "schema_version",
  "surface",
  "consistency",
  "summary_scope",
  "observed_at",
  "source_observed_at",
  "loaded_count",
  "matching_admitted_count",
  "snapshot_total_count",
  "snapshot_admitted_count",
  "snapshot_withheld_count",
  "withheld_reasons",
  "summary",
  "has_more",
  "next_cursor",
  "page_complete",
  "items",
]);
const ITEM_KEYS = new Set([
  "artifact_id",
  "policy_id",
  "policy_version",
  "source_host",
  "final_host",
  "redirected",
  "captured_at",
  "expires_at",
  "selector_count",
  "redaction_count",
  "prompt_injection_finding_count",
  "digest_presence",
  "browser_version",
  "custody_audit_ref",
  "retention_state",
  "legal_hold",
  "legal_hold_ref",
  "legal_hold_at",
  "audit",
  "isolation_verified",
  "untrusted",
  "can_authorize_action",
]);
const DIGEST_KEYS = new Set(["screenshot", "text", "accessibility_snapshot"]);
const AUDIT_KEYS = new Set(["state", "sequence", "correlation_id"]);
const WITHHELD_KEYS = new Set([
  "invalid_metadata",
  "trust_invalid",
  "isolation_unverified",
]);
const SUMMARY_KEYS = new Set([
  "security_finding_count",
  "legal_hold_count",
  "expiring_count",
  "expired_pending_purge_count",
  "retained_count",
]);
const RETENTION_STATES = new Set<BrowserEvidenceRetention>([
  "held",
  "expired_pending_purge",
  "expiring",
  "retained",
]);
const AUDIT_STATES = new Set<BrowserEvidenceAuditLinkState>([
  "exact",
  "missing",
  "malformed",
  "ambiguous",
  "unsupported_sequence",
]);
const FILTER_KEYS = [
  "artifact",
  "host",
  "host_scope",
  "policy",
  "policy_version",
  "from",
  "before",
  "retention",
  "finding",
  "custody",
  "sort",
] as const;
const ROUTE_KEYS = new Set<string>([...FILTER_KEYS, "locale"]);
const PAGE_SIZE = 25;

export function decodeBrowserEvidenceWorkspace(
  value: unknown,
  sort: BrowserEvidenceSort = "attention",
): BrowserEvidenceWorkspaceResponse {
  const root = panelRecord(value, "browser evidence workspace");
  requireExactKeys(root, ROOT_KEYS, "browser evidence workspace");
  exact(root, "schema_version", "2.0.0");
  exact(root, "surface", "browser-evidence-workspace");
  exact(root, "consistency", "drift_aware");
  exact(root, "summary_scope", "filtered_and_snapshot");
  const observedAt = timestamp(root, "observed_at", "browser evidence workspace");
  const sourceObservedAt = optionalTimestamp(
    root,
    "source_observed_at",
    "browser evidence workspace",
  );
  if (sourceObservedAt !== null && Date.parse(sourceObservedAt) > Date.parse(observedAt)) {
    throw contractError("source observation MUST NOT be later than observation");
  }
  const withheldRaw = panelRecord(
    root["withheld_reasons"],
    "browser evidence workspace.withheld_reasons",
  );
  requireExactKeys(
    withheldRaw,
    WITHHELD_KEYS,
    "browser evidence workspace.withheld_reasons",
  );
  const withheld = {
    invalid_metadata: panelNonNegativeInteger(
      withheldRaw,
      "invalid_metadata",
      "browser evidence workspace.withheld_reasons",
    ),
    trust_invalid: panelNonNegativeInteger(
      withheldRaw,
      "trust_invalid",
      "browser evidence workspace.withheld_reasons",
    ),
    isolation_unverified: panelNonNegativeInteger(
      withheldRaw,
      "isolation_unverified",
      "browser evidence workspace.withheld_reasons",
    ),
  };
  const summaryRaw = panelRecord(root["summary"], "browser evidence workspace.summary");
  requireExactKeys(summaryRaw, SUMMARY_KEYS, "browser evidence workspace.summary");
  const summary = {
    security_finding_count: panelNonNegativeInteger(
      summaryRaw,
      "security_finding_count",
      "browser evidence workspace.summary",
    ),
    legal_hold_count: panelNonNegativeInteger(
      summaryRaw,
      "legal_hold_count",
      "browser evidence workspace.summary",
    ),
    expiring_count: panelNonNegativeInteger(
      summaryRaw,
      "expiring_count",
      "browser evidence workspace.summary",
    ),
    expired_pending_purge_count: panelNonNegativeInteger(
      summaryRaw,
      "expired_pending_purge_count",
      "browser evidence workspace.summary",
    ),
    retained_count: panelNonNegativeInteger(
      summaryRaw,
      "retained_count",
      "browser evidence workspace.summary",
    ),
  };
  const items = panelArray(root["items"], "browser evidence workspace.items")
    .map((item, index) => decodeItem(item, index, observedAt));
  if (items.length > 500 || new Set(items.map((item) => item.artifact_id)).size !== items.length) {
    throw contractError("items MUST contain at most 500 unique artifacts");
  }
  const loadedCount = panelNonNegativeInteger(
    root,
    "loaded_count",
    "browser evidence workspace",
  );
  const matchingCount = panelNonNegativeInteger(
    root,
    "matching_admitted_count",
    "browser evidence workspace",
  );
  const snapshotTotal = panelNonNegativeInteger(
    root,
    "snapshot_total_count",
    "browser evidence workspace",
  );
  const snapshotAdmitted = panelNonNegativeInteger(
    root,
    "snapshot_admitted_count",
    "browser evidence workspace",
  );
  const snapshotWithheld = panelNonNegativeInteger(
    root,
    "snapshot_withheld_count",
    "browser evidence workspace",
  );
  if (
    loadedCount !== items.length
    || loadedCount > matchingCount
    || matchingCount > snapshotAdmitted
    || snapshotTotal !== snapshotAdmitted + snapshotWithheld
    || snapshotWithheld !== (
      withheld.invalid_metadata + withheld.trust_invalid + withheld.isolation_unverified
    )
    || matchingCount !== (
      summary.legal_hold_count
      + summary.expiring_count
      + summary.expired_pending_purge_count
      + summary.retained_count
    )
  ) {
    throw contractError("counts do not reconcile");
  }
  const hasMore = panelBoolean(root, "has_more", "browser evidence workspace");
  const pageComplete = panelBoolean(root, "page_complete", "browser evidence workspace");
  const nextCursor = boundedNullable(
    root,
    "next_cursor",
    "browser evidence workspace",
    4096,
  );
  if (hasMore === pageComplete || hasMore !== (nextCursor !== null)) {
    throw contractError("page continuation is inconsistent");
  }
  if (hasMore && loadedCount >= matchingCount) {
    throw contractError("page continuation exceeds matching records");
  }
  assertOrder(items, sort);
  return {
    schema_version: "2.0.0",
    surface: "browser-evidence-workspace",
    consistency: "drift_aware",
    summary_scope: "filtered_and_snapshot",
    observed_at: observedAt,
    source_observed_at: sourceObservedAt,
    loaded_count: loadedCount,
    matching_admitted_count: matchingCount,
    snapshot_total_count: snapshotTotal,
    snapshot_admitted_count: snapshotAdmitted,
    snapshot_withheld_count: snapshotWithheld,
    withheld_reasons: withheld,
    summary,
    has_more: hasMore,
    next_cursor: nextCursor,
    page_complete: pageComplete,
    items,
  };
}

export function browserEvidenceRequest(search: URLSearchParams): BrowserEvidenceRequest {
  const params: Record<string, string> = { limit: String(PAGE_SIZE) };
  const invalid: string[] = [];
  for (const key of search.keys()) {
    if (!ROUTE_KEYS.has(key)) invalid.push(key);
  }
  for (const key of FILTER_KEYS) {
    const values = search.getAll(key);
    if (values.length > 1) {
      invalid.push(key);
      continue;
    }
    const value = values[0]?.trim();
    if (value) params[key] = value;
  }
  const sort = params["sort"] ?? "attention";
  if (sort !== "attention" && sort !== "newest") invalid.push("sort");
  const hostScope = params["host_scope"] ?? "either";
  if (!["requested", "final", "either"].includes(hostScope)) invalid.push("host_scope");
  if (params["artifact"] && !/^sha256:[0-9a-f]{64}$/.test(params["artifact"])) {
    invalid.push("artifact");
  }
  if (params["host"] && !isCanonicalHost(params["host"])) invalid.push("host");
  if (
    params["policy_version"]
    && (
      !params["policy"]
      || !/^[1-9][0-9]*$/.test(params["policy_version"])
      || Number(params["policy_version"]) > 2_147_483_647
    )
  ) {
    invalid.push("policy_version");
  }
  if (
    params["retention"]
    && !RETENTION_STATES.has(params["retention"] as BrowserEvidenceRetention)
  ) {
    invalid.push("retention");
  }
  if (params["finding"] && !["present", "clear"].includes(params["finding"])) {
    invalid.push("finding");
  }
  if (
    params["policy"]
    && (!isBoundedText(params["policy"], 256))
  ) {
    invalid.push("policy");
  }
  if (
    params["custody"]
    && (!isBoundedText(params["custody"], 512))
  ) {
    invalid.push("custody");
  }
  for (const key of ["from", "before"] as const) {
    if (params[key] && !isRfc3339Timestamp(params[key])) invalid.push(key);
  }
  if (
    params["from"]
    && params["before"]
    && Date.parse(params["from"]) >= Date.parse(params["before"])
  ) {
    invalid.push("capture_window");
  }
  return {
    params,
    sort: sort === "newest" ? "newest" : "attention",
    invalid: [...new Set(invalid)],
    hasFilters: FILTER_KEYS.some((key) => key !== "sort" && Boolean(params[key])),
  };
}

export function appendBrowserEvidencePage(
  current: BrowserEvidenceData,
  requestedCursor: string,
  page: BrowserEvidenceWorkspaceResponse,
): BrowserEvidenceData {
  if (current.page.next_cursor !== requestedCursor) {
    throw new Error("Browser evidence cursor changed before the page was applied");
  }
  if (Date.parse(page.observed_at) < Date.parse(current.page.observed_at)) {
    throw new Error("Browser evidence observation moved backwards while loading");
  }
  const items = [...current.items];
  const positions = new Map(items.map((item, index) => [item.artifact_id, index]));
  for (const item of page.items) {
    const index = positions.get(item.artifact_id);
    if (index === undefined) {
      positions.set(item.artifact_id, items.length);
      items.push(item);
    } else if (JSON.stringify(items[index]) !== JSON.stringify(item)) {
      throw new Error("Browser evidence changed while loading a drift-aware page");
    }
  }
  if (items.length > page.matching_admitted_count) {
    throw new Error(
      "Browser evidence changed while loading; refresh the drift-aware workspace",
    );
  }
  return { page, items };
}

export function browserEvidenceAttentionRank(item: BrowserEvidenceItem): number {
  if (item.prompt_injection_finding_count > 0) return 0;
  if (item.retention_state === "expired_pending_purge") return 1;
  if (item.retention_state === "expiring") return 2;
  if (item.retention_state === "held") return 3;
  return 4;
}

function decodeItem(value: unknown, index: number, observedAt: string): BrowserEvidenceItem {
  const label = `browser evidence workspace.items[${index}]`;
  const row = panelRecord(value, label);
  requireExactKeys(row, ITEM_KEYS, label);
  const artifactId = bounded(row, "artifact_id", label, 71);
  if (!/^sha256:[0-9a-f]{64}$/.test(artifactId)) {
    throw contractError(`${label}.artifact_id is invalid`);
  }
  const sourceHost = host(row, "source_host", label);
  const finalHost = host(row, "final_host", label);
  const redirected = panelBoolean(row, "redirected", label);
  if (redirected !== (sourceHost !== finalHost)) {
    throw contractError(`${label}.redirected is inconsistent`);
  }
  const capturedAt = timestamp(row, "captured_at", label);
  const expiresAt = timestamp(row, "expires_at", label);
  if (Date.parse(capturedAt) >= Date.parse(expiresAt)) {
    throw contractError(`${label}.retention window is invalid`);
  }
  const legalHold = panelBoolean(row, "legal_hold", label);
  const legalHoldRef = boundedNullable(row, "legal_hold_ref", label, 512);
  const legalHoldAt = optionalTimestamp(row, "legal_hold_at", label);
  if (legalHold !== (legalHoldRef !== null && legalHoldAt !== null)) {
    throw contractError(`${label}.legal hold is inconsistent`);
  }
  const retention = bounded(row, "retention_state", label, 32);
  if (!RETENTION_STATES.has(retention as BrowserEvidenceRetention)) {
    throw contractError(`${label}.retention state is invalid`);
  }
  if (retention !== retentionAt(legalHold, expiresAt, observedAt)) {
    throw contractError(`${label}.retention state does not match observation`);
  }
  const digestRaw = panelRecord(row["digest_presence"], `${label}.digest_presence`);
  requireExactKeys(digestRaw, DIGEST_KEYS, `${label}.digest_presence`);
  const auditRaw = panelRecord(row["audit"], `${label}.audit`);
  requireExactKeys(auditRaw, AUDIT_KEYS, `${label}.audit`);
  const auditState = bounded(auditRaw, "state", `${label}.audit`, 32);
  if (!AUDIT_STATES.has(auditState as BrowserEvidenceAuditLinkState)) {
    throw contractError(`${label}.audit state is invalid`);
  }
  const auditSequence = boundedNullable(auditRaw, "sequence", `${label}.audit`, 19);
  const auditCorrelation = boundedNullable(
    auditRaw,
    "correlation_id",
    `${label}.audit`,
    256,
  );
  if (auditState === "exact") {
    if (
      auditSequence === null
      || !/^[1-9][0-9]{0,18}$/.test(auditSequence)
      || !Number.isSafeInteger(Number(auditSequence))
    ) {
      throw contractError(`${label}.exact audit sequence is invalid`);
    }
  } else if (auditSequence !== null || auditCorrelation !== null) {
    throw contractError(`${label}.non-exact audit link exposes identity`);
  }
  if (
    !panelBoolean(row, "isolation_verified", label)
    || !panelBoolean(row, "untrusted", label)
    || panelBoolean(row, "can_authorize_action", label)
  ) {
    throw contractError(`${label}.authority boundary is invalid`);
  }
  return {
    artifact_id: artifactId,
    policy_id: bounded(row, "policy_id", label, 256),
    policy_version: positiveInteger(row, "policy_version", label),
    source_host: sourceHost,
    final_host: finalHost,
    redirected,
    captured_at: capturedAt,
    expires_at: expiresAt,
    selector_count: panelNonNegativeInteger(row, "selector_count", label),
    redaction_count: panelNonNegativeInteger(row, "redaction_count", label),
    prompt_injection_finding_count: panelNonNegativeInteger(
      row,
      "prompt_injection_finding_count",
      label,
    ),
    digest_presence: {
      screenshot: panelBoolean(digestRaw, "screenshot", `${label}.digest_presence`),
      text: panelBoolean(digestRaw, "text", `${label}.digest_presence`),
      accessibility_snapshot: panelBoolean(
        digestRaw,
        "accessibility_snapshot",
        `${label}.digest_presence`,
      ),
    },
    browser_version: bounded(row, "browser_version", label, 256),
    custody_audit_ref: bounded(row, "custody_audit_ref", label, 512),
    retention_state: retention as BrowserEvidenceRetention,
    legal_hold: legalHold,
    legal_hold_ref: legalHoldRef,
    legal_hold_at: legalHoldAt,
    audit: {
      state: auditState as BrowserEvidenceAuditLinkState,
      sequence: auditSequence,
      correlation_id: auditCorrelation,
    },
    isolation_verified: true,
    untrusted: true,
    can_authorize_action: false,
  };
}

function assertOrder(
  items: readonly BrowserEvidenceItem[],
  sort: BrowserEvidenceSort,
): void {
  for (let index = 1; index < items.length; index += 1) {
    const previous = items[index - 1]!;
    const current = items[index]!;
    const previousRank = sort === "attention" ? browserEvidenceAttentionRank(previous) : 0;
    const currentRank = sort === "attention" ? browserEvidenceAttentionRank(current) : 0;
    const invalidRank = previousRank > currentRank;
    const previousTime = Date.parse(previous.captured_at);
    const currentTime = Date.parse(current.captured_at);
    const invalidTime = previousRank === currentRank && previousTime < currentTime;
    const invalidId = previousRank === currentRank
      && previousTime === currentTime
      && previous.artifact_id < current.artifact_id;
    if (invalidRank || invalidTime || invalidId) {
      throw contractError(`items are not ordered by ${sort}`);
    }
  }
}

function retentionAt(
  legalHold: boolean,
  expiresAt: string,
  observedAt: string,
): BrowserEvidenceRetention {
  if (legalHold) return "held";
  const expiry = Date.parse(expiresAt);
  const observed = Date.parse(observedAt);
  if (expiry <= observed) return "expired_pending_purge";
  if (expiry <= observed + 7 * 24 * 60 * 60 * 1000) return "expiring";
  return "retained";
}

function exact(
  row: Readonly<Record<string, unknown>>,
  key: string,
  expected: string,
): void {
  if (panelNonEmptyString(row, key, "browser evidence workspace") !== expected) {
    throw contractError(`${key} MUST be ${expected}`);
  }
}

function bounded(
  row: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
  maximum: number,
): string {
  const value = panelNonEmptyString(row, key, label);
  if (
    value !== value.trim()
    || value.length > maximum
    || [...value].some((character) => character.charCodeAt(0) < 32)
  ) {
    throw contractError(`${label}.${key} MUST be bounded text`);
  }
  return value;
}

function boundedNullable(
  row: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
  maximum: number,
): string | null {
  const value = panelNullableString(row, key, label);
  if (value === null) return null;
  if (
    value.length === 0
    || value !== value.trim()
    || value.length > maximum
    || [...value].some((character) => character.charCodeAt(0) < 32)
  ) {
    throw contractError(`${label}.${key} MUST be bounded text or null`);
  }
  return value;
}

function host(
  row: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string {
  const value = bounded(row, key, label, 253);
  if (!isCanonicalHost(value)) throw contractError(`${label}.${key} is not canonical`);
  return value;
}

function isCanonicalHost(value: string): boolean {
  if (
    value !== value.toLowerCase()
    || /[\s/?#@]/.test(value)
    || !isAscii(value)
  ) {
    return false;
  }
  const labels = (value.endsWith(".") ? value.slice(0, -1) : value).split(".");
  return labels.every((label) => label.length >= 1 && label.length <= 63);
}

function isBoundedText(value: string, maximum: number): boolean {
  return value.length <= maximum
    && value === value.trim()
    && ![...value].some((character) => character.charCodeAt(0) < 32);
}

function isAscii(value: string): boolean {
  return [...value].every((character) => {
    const code = character.charCodeAt(0);
    return code >= 32 && code <= 126;
  });
}

function timestamp(
  row: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string {
  const value = panelNonEmptyString(row, key, label);
  if (!isRfc3339Timestamp(value)) {
    throw contractError(`${label}.${key} MUST be RFC 3339`);
  }
  return value;
}

function optionalTimestamp(
  row: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string | null {
  const value = panelNullableString(row, key, label);
  if (value !== null && !isRfc3339Timestamp(value)) {
    throw contractError(`${label}.${key} MUST be RFC 3339 or null`);
  }
  return value;
}

function positiveInteger(
  row: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  const value = panelNonNegativeInteger(row, key, label);
  if (value < 1) throw contractError(`${label}.${key} MUST be positive`);
  return value;
}

function requireExactKeys(
  value: Readonly<Record<string, unknown>>,
  expected: ReadonlySet<string>,
  label: string,
): void {
  const unknown = Object.keys(value).filter((key) => !expected.has(key));
  const missing = [...expected].filter((key) => !(key in value));
  if (unknown.length > 0 || missing.length > 0) {
    throw contractError(`${label} fields are invalid`);
  }
}

function contractError(message: string): OperatorApiError {
  return new OperatorApiError(
    502,
    `invalid Operator API response: browser evidence workspace ${message}`,
  );
}
