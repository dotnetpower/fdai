import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { t } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleTimestamp, isRfc3339Timestamp } from "../time-format";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
} from "./panel-decode";

export interface BrowserEvidenceRow {
  readonly artifact_id: string;
  readonly policy_ref: string;
  readonly source_host: string;
  readonly final_host: string;
  readonly captured_at: string;
  readonly expires_at: string;
  readonly selector_count: number;
  readonly redaction_count: number;
  readonly prompt_injection_finding_count: number;
  readonly hash_count: number;
  readonly browser_version: string;
  readonly custody_ref: string;
  readonly isolation_verified: boolean;
  readonly untrusted: boolean;
  readonly legal_hold: boolean;
  readonly legal_hold_ref: string | null;
  readonly legal_hold_at: string | null;
}

export interface BrowserEvidenceResponse {
  readonly surface: "browser-evidence";
  readonly count: number;
  readonly items: readonly BrowserEvidenceRow[];
}

const ROOT_KEYS = new Set(["surface", "items", "count"]);
const ITEM_KEYS = new Set([
  "artifact_id",
  "policy_id",
  "policy_version",
  "source_url",
  "final_url",
  "captured_at",
  "expires_at",
  "selector_count",
  "screenshot_hash",
  "text_hash",
  "snapshot_hash",
  "redaction_count",
  "browser_version",
  "custody_audit_ref",
  "prompt_injection_finding_count",
  "isolation_verified",
  "untrusted",
  "legal_hold",
  "legal_hold_ref",
  "legal_hold_at",
]);

export function BrowserEvidenceRoute({ client }: { readonly client: OperatorApiClient }) {
  const [state, setState] = useState<AsyncState<BrowserEvidenceResponse>>({
    status: "loading",
  });
  useEffect(() => {
    let cancelled = false;
    void loadBrowserEvidenceState(client).then((next) => {
      if (!cancelled) setState(next);
    });
    return () => { cancelled = true; };
  }, [client]);

  return (
    <div class="stack evidence-route">
      <PageHeader
        title={t("route.browserEvidence")}
        subtitle={t("browserEvidence.subtitle")}
      />
      <AsyncBoundary state={state} resourceLabel={t("browserEvidence.resourceLabel")}>
        {(data) => <BrowserEvidenceBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export async function loadBrowserEvidenceState(
  client: Pick<OperatorApiClient, "panel">,
): Promise<AsyncState<BrowserEvidenceResponse>> {
  try {
    return {
      status: "ready",
      data: decodeBrowserEvidence(await client.panel<unknown>("/browser-evidence")),
    };
  } catch (error) {
    if (isOptionalOperatorApiUnavailable(error)) {
      return { status: "unavailable", message: t("browserEvidence.unavailable") };
    }
    return {
      status: "error",
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

export function decodeBrowserEvidence(value: unknown): BrowserEvidenceResponse {
  const root = panelRecord(value, "browser evidence");
  requireExactKeys(root, ROOT_KEYS, "browser evidence");
  if (panelNonEmptyString(root, "surface", "browser evidence") !== "browser-evidence") {
    throw new OperatorApiError(502, "invalid Operator API response: browser evidence surface is invalid");
  }
  const rawItems = panelArray(root["items"], "browser evidence.items");
  if (rawItems.length > 500) {
    throw new OperatorApiError(502, "invalid Operator API response: browser evidence items exceed 500");
  }
  const items = rawItems.map((item, index) => decodeItem(item, index));
  const count = panelNonNegativeInteger(root, "count", "browser evidence");
  if (count !== items.length) {
    throw new OperatorApiError(502, "invalid Operator API response: browser evidence count MUST match rows");
  }
  return { surface: "browser-evidence", count, items };
}

function decodeItem(value: unknown, index: number): BrowserEvidenceRow {
  const row = panelRecord(value, `browser evidence[${index}]`);
  requireExactKeys(row, ITEM_KEYS, `browser evidence[${index}]`);
  const artifactId = panelNonEmptyString(row, "artifact_id", "browser evidence");
  if (!/^sha256:[0-9a-f]{64}$/.test(artifactId)) {
    throw new OperatorApiError(502, "invalid Operator API response: browser evidence artifact id is invalid");
  }
  const policyVersion = positiveInteger(row, "policy_version");
  const sourceHost = httpsHost(panelNonEmptyString(row, "source_url", "browser evidence"));
  const finalHost = httpsHost(panelNonEmptyString(row, "final_url", "browser evidence"));
  const capturedAt = timestamp(row, "captured_at");
  const expiresAt = timestamp(row, "expires_at");
  if (Date.parse(capturedAt) >= Date.parse(expiresAt)) {
    throw new OperatorApiError(502, "invalid Operator API response: browser evidence retention window is invalid");
  }
  if (!panelBoolean(row, "untrusted", "browser evidence")) {
    throw new OperatorApiError(502, "invalid Operator API response: browser evidence MUST be untrusted");
  }
  if (!panelBoolean(row, "isolation_verified", "browser evidence")) {
    throw new OperatorApiError(502, "invalid Operator API response: browser evidence isolation MUST be verified");
  }
  const legalHold = panelBoolean(row, "legal_hold", "browser evidence");
  const legalHoldRef = optionalNonEmptyString(row, "legal_hold_ref");
  const legalHoldAt = optionalTimestamp(row, "legal_hold_at");
  if (
    (legalHold && (legalHoldRef === null || legalHoldAt === null))
    || (!legalHold && (legalHoldRef !== null || legalHoldAt !== null))
  ) {
    throw new OperatorApiError(502, "invalid Operator API response: browser evidence legal hold is inconsistent");
  }
  const hashes = ["screenshot_hash", "text_hash", "snapshot_hash"]
    .map((key) => optionalHash(row, key));
  return {
    artifact_id: artifactId,
    policy_ref: `${panelNonEmptyString(row, "policy_id", "browser evidence")}@${policyVersion}`,
    source_host: sourceHost,
    final_host: finalHost,
    captured_at: capturedAt,
    expires_at: expiresAt,
    selector_count: panelNonNegativeInteger(row, "selector_count", "browser evidence"),
    redaction_count: panelNonNegativeInteger(row, "redaction_count", "browser evidence"),
    prompt_injection_finding_count: panelNonNegativeInteger(row, "prompt_injection_finding_count", "browser evidence"),
    hash_count: hashes.filter((hash) => hash !== null).length,
    browser_version: panelNonEmptyString(row, "browser_version", "browser evidence"),
    custody_ref: panelNonEmptyString(row, "custody_audit_ref", "browser evidence"),
    isolation_verified: true,
    untrusted: true,
    legal_hold: legalHold,
    legal_hold_ref: legalHoldRef,
    legal_hold_at: legalHoldAt,
  };
}

function requireExactKeys(
  value: Readonly<Record<string, unknown>>,
  allowed: ReadonlySet<string>,
  label: string,
): void {
  const unsupported = Object.keys(value).find((key) => !allowed.has(key));
  if (unsupported) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label}.${unsupported} is not allowed`);
  }
}

function positiveInteger(row: Readonly<Record<string, unknown>>, key: string): number {
  const value = panelNonNegativeInteger(row, key, "browser evidence");
  if (value < 1) {
    throw new OperatorApiError(502, `invalid Operator API response: browser evidence.${key} MUST be positive`);
  }
  return value;
}

function httpsHost(value: string): string {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.hash) {
      throw new Error("invalid HTTPS metadata URL");
    }
    return parsed.host;
  } catch {
    throw new OperatorApiError(502, "invalid Operator API response: browser evidence URL MUST be canonical HTTPS");
  }
}

function timestamp(row: Readonly<Record<string, unknown>>, key: string): string {
  const value = panelNonEmptyString(row, key, "browser evidence");
  if (!isRfc3339Timestamp(value)) {
    throw new OperatorApiError(502, `invalid Operator API response: browser evidence.${key} MUST be RFC 3339`);
  }
  return value;
}

function optionalTimestamp(row: Readonly<Record<string, unknown>>, key: string): string | null {
  const value = panelNullableString(row, key, "browser evidence");
  if (value !== null && !isRfc3339Timestamp(value)) {
    throw new OperatorApiError(502, `invalid Operator API response: browser evidence.${key} MUST be RFC 3339 or null`);
  }
  return value;
}

function optionalNonEmptyString(
  row: Readonly<Record<string, unknown>>,
  key: string,
): string | null {
  const value = panelNullableString(row, key, "browser evidence");
  if (value !== null && value.trim().length === 0) {
    throw new OperatorApiError(502, `invalid Operator API response: browser evidence.${key} MUST NOT be empty`);
  }
  return value;
}

function optionalHash(row: Readonly<Record<string, unknown>>, key: string): string | null {
  const value = panelNullableString(row, key, "browser evidence");
  if (value !== null && !/^[0-9a-f]{64}$/.test(value)) {
    throw new OperatorApiError(502, `invalid Operator API response: browser evidence.${key} is invalid`);
  }
  return value;
}

function BrowserEvidenceBody({ data }: { readonly data: BrowserEvidenceResponse }) {
  const artifactsHref = `${routeHref("browser-evidence")}#browser-evidence-artifacts`;
  const columns: readonly Column<BrowserEvidenceRow>[] = [
    { key: "source", header: t("browserEvidence.column.source"), render: (row) => row.source_host === row.final_host ? row.source_host : `${row.source_host} -> ${row.final_host}` },
    { key: "policy", header: t("browserEvidence.column.policy"), render: (row) => row.policy_ref, cellClass: "mono" },
    { key: "captured", header: t("browserEvidence.column.captured"), render: (row) => formatConsoleTimestamp(row.captured_at) },
    { key: "expires", header: t("browserEvidence.column.expires"), render: (row) => formatConsoleTimestamp(row.expires_at) },
    { key: "sanitization", header: t("browserEvidence.column.sanitization"), render: (row) => t("browserEvidence.sanitization", { selectors: row.selector_count, redactions: row.redaction_count, findings: row.prompt_injection_finding_count }) },
    { key: "integrity", header: t("browserEvidence.column.integrity"), render: (row) => <span class="mono">{t("browserEvidence.integrity", { hashes: row.hash_count, custody: row.custody_ref })}</span> },
    { key: "isolation", header: t("browserEvidence.column.isolation"), render: () => <StatusPill kind="success" label={t("browserEvidence.verified")} /> },
    { key: "retention", header: t("browserEvidence.column.retention"), render: (row) => row.legal_hold ? <StatusPill kind="warning" label={t("browserEvidence.held")} /> : <StatusPill kind="neutral" label={t("browserEvidence.scheduled")} /> },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("browserEvidence.readOnlyTitle")}</strong>
        <span>{t("browserEvidence.readOnlyBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={artifactsHref} label={t("browserEvidence.artifacts")} value={data.count} />
        <KpiCard href={artifactsHref} label={t("browserEvidence.mode")} value={t("browserEvidence.metadataOnly")} />
        <KpiCard href={artifactsHref} label={t("browserEvidence.legalHolds")} value={data.items.filter((row) => row.legal_hold).length} />
      </KpiGrid>
      <div id="browser-evidence-artifacts">
        <DataTable
          columns={columns}
          rows={data.items}
          keyOf={(row) => row.artifact_id}
          empty={t("browserEvidence.empty")}
        />
      </div>
    </div>
  );
}
