import { useEffect, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, ReadApiError } from "../api";
import type { ReadApiClient } from "../api";
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
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

export interface BrowserEvidenceRow {
  readonly artifact_id: string;
  readonly policy_ref: string;
  readonly source_host: string;
  readonly captured_at: string;
  readonly expires_at: string;
  readonly redaction_count: number;
  readonly prompt_injection_findings: readonly string[];
  readonly content_digest: string;
  readonly custody_ref: string;
  readonly isolation_verified: boolean;
}

export interface BrowserEvidenceResponse {
  readonly read_only: boolean;
  readonly shadow_only: boolean;
  readonly count: number;
  readonly artifacts: readonly BrowserEvidenceRow[];
}

export function BrowserEvidenceRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<BrowserEvidenceResponse>>({
    status: "loading",
  });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = decodeBrowserEvidence(await client.panel<unknown>("/browser-evidence"));
        if (!cancelled) setState({ status: "ready", data });
      } catch (error) {
        if (cancelled) return;
        if (isOptionalReadApiUnavailable(error)) {
          setState({ status: "unavailable", message: "Browser evidence is not wired." });
        } else {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client]);

  return (
    <div class="stack evidence-route">
      <PageHeader
        title={t("route.browserEvidence")}
        subtitle={t("browserEvidence.subtitle")}
      />
      <AsyncBoundary state={state} resourceLabel="browser evidence">
        {(data) => <BrowserEvidenceBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeBrowserEvidence(value: unknown): BrowserEvidenceResponse {
  const root = panelRecord(value, "browser evidence");
  const readOnly = panelBoolean(root, "read_only", "browser evidence");
  const shadowOnly = panelBoolean(root, "shadow_only", "browser evidence");
  const captureControls = panelBoolean(root, "capture_controls", "browser evidence");
  const promotionControls = panelBoolean(root, "promotion_controls", "browser evidence");
  const mutationControls = panelBoolean(root, "mutation_controls", "browser evidence");
  if (!readOnly || !shadowOnly || captureControls || promotionControls || mutationControls) {
    throw new ReadApiError(502, "invalid read API response: browser evidence MUST be read-only and shadow-only");
  }
  const artifacts = panelArray(root["artifacts"], "browser evidence.artifacts")
    .map((item, index) => decodeArtifact(item, index));
  const count = panelNonNegativeInteger(root, "count", "browser evidence");
  if (count !== artifacts.length) {
    throw new ReadApiError(502, "invalid read API response: browser evidence count MUST match rows");
  }
  return { read_only: readOnly, shadow_only: shadowOnly, count, artifacts };
}

function decodeArtifact(value: unknown, index: number): BrowserEvidenceRow {
  const row = panelRecord(value, `browser evidence[${index}]`);
  const sourceUrl = panelNonEmptyString(row, "canonical_source_url", "browser evidence");
  let sourceHost: string;
  try {
    const parsed = new URL(sourceUrl);
    if (parsed.protocol !== "https:") throw new Error("HTTPS required");
    sourceHost = parsed.host;
  } catch {
    throw new ReadApiError(502, "invalid read API response: browser evidence source URL MUST be HTTPS");
  }
  if (panelBoolean(row, "can_authorize_action", "browser evidence")) {
    throw new ReadApiError(502, "invalid read API response: browser evidence cannot authorize action");
  }
  if (!panelBoolean(row, "untrusted", "browser evidence")) {
    throw new ReadApiError(502, "invalid read API response: browser evidence MUST be untrusted");
  }
  return {
    artifact_id: panelNonEmptyString(row, "artifact_id", "browser evidence"),
    policy_ref: `${panelNonEmptyString(row, "policy_id", "browser evidence")}@${panelNonNegativeInteger(row, "policy_version", "browser evidence")}`,
    source_host: sourceHost,
    captured_at: panelNonEmptyString(row, "captured_at", "browser evidence"),
    expires_at: panelNonEmptyString(row, "expires_at", "browser evidence"),
    redaction_count: panelNonNegativeInteger(row, "redaction_count", "browser evidence"),
    prompt_injection_findings: panelStringArray(row["prompt_injection_findings"], "browser evidence.prompt injection findings"),
    content_digest: panelNonEmptyString(row, "content_digest", "browser evidence"),
    custody_ref: panelNonEmptyString(row, "chain_of_custody_audit_ref", "browser evidence"),
    isolation_verified: panelBoolean(row, "isolation_verified", "browser evidence"),
  };
}

function BrowserEvidenceBody({ data }: { readonly data: BrowserEvidenceResponse }) {
  const artifactsHref = `${routeHref("browser-evidence")}#browser-evidence-artifacts`;
  const columns: readonly Column<BrowserEvidenceRow>[] = [
    { key: "source", header: "Source", render: (row) => row.source_host },
    { key: "policy", header: "Policy", render: (row) => row.policy_ref, cellClass: "mono" },
    { key: "captured", header: "Captured", render: (row) => new Date(row.captured_at).toLocaleString() },
    { key: "redactions", header: "Redactions", render: (row) => row.redaction_count, cellClass: "num" },
    { key: "injection", header: "Untrusted content", render: (row) => row.prompt_injection_findings.length ? <StatusPill kind="warning" label={`${row.prompt_injection_findings.length} finding(s)`} /> : <StatusPill kind="success" label="scan clear" /> },
    { key: "isolation", header: "Isolation", render: (row) => <StatusPill kind={row.isolation_verified ? "success" : "danger"} label={row.isolation_verified ? "verified" : "unverified"} /> },
    { key: "digest", header: "Content digest", render: (row) => row.content_digest.slice(0, 16), cellClass: "mono" },
    { key: "custody", header: "Custody", render: (row) => row.custody_ref, cellClass: "mono" },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("browserEvidence.readOnlyTitle")}</strong>
        <span>{t("browserEvidence.readOnlyBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={artifactsHref} label={t("browserEvidence.artifacts")} value={data.count} />
        <KpiCard href={artifactsHref} label={t("browserEvidence.mode")} value={t("browserEvidence.shadow")} />
      </KpiGrid>
      <div id="browser-evidence-artifacts">
        <DataTable
          columns={columns}
          rows={data.artifacts}
          keyOf={(row) => row.artifact_id}
          empty={t("browserEvidence.empty")}
        />
      </div>
    </div>
  );
}
