import { useState } from "preact/hooks";
import { OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import { DataTable, StatusPill, type Column, type PillKind } from "../components/ui";
import { Tooltip } from "../components/tooltip";
import { t } from "./i18n/code-security";
import { formatConsoleTimestamp } from "../time-format";
import {
  FeedbackLine,
  RepositoryRegistrationForm,
  submitRepositoryChange,
  type RegistrationFeedback,
} from "./code-security-registration";
import {
  panelArray,
  panelBoolean,
  panelContractError,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelRecord,
} from "./panel-decode";

const EXPOSURES = ["exposed", "internal", "not_deployed", "unknown"] as const;
const STATUSES = ["queued", "running", "completed", "rejected"] as const;
const DECISIONS = ["urgent", "open", "clear", "coverage_incomplete"] as const;
const REJECTIONS = [
  "request_malformed",
  "requester_role_insufficient",
  "repository_not_registered",
  "repository_disabled",
  "repository_conflict",
  "source_unavailable",
  "scan_failed",
  "review_conflict",
  "attempts_exhausted",
] as const;
const GAPS = [
  "code_security_repository_malformed",
  "code_security_scan_request_malformed",
  "code_security_review_truncated",
] as const;
const REF = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$/;
const KINDS = ["scan", "repository_change"] as const;
const ACTIONS = ["register", "enable", "disable", "connect", "disconnect"] as const;

type RequestStatus = (typeof STATUSES)[number];
type Gap = (typeof GAPS)[number];

export interface CodeSecurityRepository {
  readonly repository_alias: string;
  readonly provider: "github";
  readonly location: string;
  readonly default_ref: string;
  readonly exposure: (typeof EXPOSURES)[number];
  readonly enabled: boolean;
  readonly registered_at: string;
}

export interface CodeSecurityRepositoriesResponse {
  readonly repositories: readonly CodeSecurityRepository[];
  readonly gaps: readonly Gap[];
}

export interface ScanResult {
  readonly revision: string;
  readonly decision: (typeof DECISIONS)[number];
  readonly issue_count: number;
  readonly coverage_complete: boolean;
}

export interface CodeSecurityScanRequest {
  readonly request_id: string;
  readonly kind: (typeof KINDS)[number];
  readonly action: (typeof ACTIONS)[number] | null;
  readonly location: string | null;
  readonly repository_alias: string;
  readonly ref: string | null;
  readonly status: RequestStatus;
  readonly accepted_at: string;
  readonly closed_at: string | null;
  readonly rejection_reason: (typeof REJECTIONS)[number] | null;
  readonly result: ScanResult | { readonly enabled: boolean } | null;
}

export interface CodeSecurityScanRequestsResponse {
  readonly requests: readonly CodeSecurityScanRequest[];
  readonly gaps: readonly Gap[];
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    throw panelContractError(`${label} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function decodeGaps(value: unknown, label: string): readonly Gap[] {
  return panelArray(value, `${label}.gaps`).map((gap, index) =>
    oneOf(panelRecord(gap, `${label} gap ${index}`).reason_code, GAPS, `${label} gap ${index}`));
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0) throw panelContractError(`${label} must be a string or null`);
  return value;
}

export function decodeCodeSecurityRepositories(payload: unknown): CodeSecurityRepositoriesResponse {
  const root = panelRecord(payload, "code-security repositories");
  return {
    repositories: panelArray(root.repositories, "code-security repositories.repositories").map((item, index) => {
      const label = `code-security repository ${index}`;
      const row = panelRecord(item, label);
      return {
        repository_alias: panelNonEmptyString(row, "repository_alias", label),
        provider: oneOf(row.provider, ["github"] as const, `${label}.provider`),
        location: panelNonEmptyString(row, "location", label),
        default_ref: panelNonEmptyString(row, "default_ref", label),
        exposure: oneOf(row.exposure, EXPOSURES, `${label}.exposure`),
        enabled: panelBoolean(row, "enabled", label),
        registered_at: panelNonEmptyString(row, "registered_at", label),
      };
    }),
    gaps: decodeGaps(root.gaps, "code-security repositories"),
  };
}

export function decodeCodeSecurityScanRequests(payload: unknown): CodeSecurityScanRequestsResponse {
  const root = panelRecord(payload, "code-security scan requests");
  return {
    requests: panelArray(root.requests, "code-security scan requests.requests").map((item, index) => {
      const label = `code-security scan request ${index}`;
      const row = panelRecord(item, label);
      const status = oneOf(row.status, STATUSES, `${label}.status`);
      const kind = oneOf(row.kind, KINDS, `${label}.kind`);
      let result: CodeSecurityScanRequest["result"] = null;
      if (row.result !== null) {
        const record = panelRecord(row.result, `${label}.result`);
        result = kind === "repository_change"
          ? { enabled: panelBoolean(record, "enabled", label) }
          : {
            revision: panelNonEmptyString(record, "revision", label),
            decision: oneOf(record.decision, DECISIONS, `${label}.result.decision`),
            issue_count: panelNonNegativeInteger(record, "issue_count", label),
            coverage_complete: panelBoolean(record, "coverage_complete", label),
          };
      }
      if ((status === "completed") !== (result !== null)) {
        throw panelContractError(`${label} result must match its status`);
      }
      return {
        request_id: panelNonEmptyString(row, "request_id", label),
        kind,
        action: row.action === null ? null : oneOf(row.action, ACTIONS, `${label}.action`),
        location: nullableString(row.location, `${label}.location`),
        repository_alias: panelNonEmptyString(row, "repository_alias", label),
        ref: nullableString(row.ref, `${label}.ref`),
        status,
        accepted_at: panelNonEmptyString(row, "accepted_at", label),
        closed_at: nullableString(row.closed_at, `${label}.closed_at`),
        rejection_reason: row.rejection_reason === null
          ? null
          : oneOf(row.rejection_reason, REJECTIONS, `${label}.rejection_reason`),
        result,
      };
    }),
    gaps: decodeGaps(root.gaps, "code-security scan requests"),
  };
}

function statusKind(status: RequestStatus): PillKind {
  if (status === "completed") return "success";
  if (status === "rejected") return "danger";
  return "info";
}

/** A fresh key per deliberate submission; retries of one submission reuse it. */
export function scanRequestIdempotencyKey(alias: string, ref: string, nonce: string): string {
  return `code-security-scan:${alias}:${ref || "default"}:${nonce}`;
}

type Feedback = { readonly kind: "queued" | "forbidden" | "failed"; readonly detail?: string } | null;

function ScanRequestForm({
  client,
  repositories,
  onQueued,
}: {
  readonly client: Pick<OperatorApiClient, "requestCodeSecurityScan">;
  readonly repositories: readonly CodeSecurityRepository[];
  readonly onQueued: () => void;
}) {
  const enabled = repositories.filter((repository) => repository.enabled);
  const [alias, setAlias] = useState(enabled[0]?.repository_alias ?? "");
  const [ref, setRef] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const selected = enabled.find((repository) => repository.repository_alias === alias);
  const trimmed = ref.trim();
  const refValid = trimmed === "" || (REF.test(trimmed) && !trimmed.includes(".."));
  const submit = async (event: Event) => {
    event.preventDefault();
    if (selected === undefined || !refValid || submitting) return;
    setSubmitting(true);
    setFeedback(null);
    try {
      await client.requestCodeSecurityScan(
        trimmed ? { repository_alias: selected.repository_alias, ref: trimmed } : { repository_alias: selected.repository_alias },
        scanRequestIdempotencyKey(selected.repository_alias, trimmed, crypto.randomUUID()),
      );
      setFeedback({ kind: "queued" });
      onQueued();
    } catch (error) {
      if (error instanceof OperatorApiError && error.status === 403) {
        setFeedback({ kind: "forbidden" });
      } else {
        setFeedback({ kind: "failed", detail: error instanceof Error ? error.message : String(error) });
      }
    } finally {
      setSubmitting(false);
    }
  };
  if (enabled.length === 0) {
    return <p class="muted">{t("codeSecurity.scan.noRepositories")}</p>;
  }
  return (
    <form class="code-security-scan-form" onSubmit={submit}>
      <label>
        <span>{t("codeSecurity.scan.repository")}</span>
        <select
          aria-label={t("codeSecurity.scan.repository")}
          value={alias}
          disabled={submitting}
          onChange={(event) => setAlias(event.currentTarget.value)}
        >
          {enabled.map((repository) => (
            <option key={repository.repository_alias} value={repository.repository_alias}>
              {`${repository.repository_alias} (${repository.location})`}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>{t("codeSecurity.scan.ref")}</span>
        <input
          value={ref}
          disabled={submitting}
          placeholder={selected ? `${t("codeSecurity.scan.refPlaceholder")}: ${selected.default_ref}` : ""}
          aria-invalid={!refValid}
          onInput={(event) => setRef((event.currentTarget as HTMLInputElement).value)}
        />
      </label>
      <button type="submit" class="btn primary" disabled={submitting || selected === undefined || !refValid}>
        {submitting ? t("codeSecurity.scan.submitting") : t("codeSecurity.scan.submit")}
      </button>
      {feedback === null
        ? null
        : (
          <p class={feedback.kind === "queued" ? "muted code-security-scan-feedback" : "alert error code-security-scan-feedback"} role="status">
            {t(`codeSecurity.scan.${feedback.kind}`)}
            {feedback.detail ? ` ${feedback.detail}` : ""}
          </p>
        )}
    </form>
  );
}

function isScanResult(result: CodeSecurityScanRequest["result"]): result is ScanResult {
  return result !== null && "revision" in result;
}

function resultText(request: CodeSecurityScanRequest): string {
  if (isScanResult(request.result)) {
    return `${t(`codeSecurity.decision.${request.result.decision}`)} - ${request.result.issue_count}`;
  }
  if (request.result !== null) {
    return t(`codeSecurity.repoState.${request.result.enabled ? "enabled" : "disabled"}`);
  }
  if (request.rejection_reason !== null) return t(`codeSecurity.rejection.${request.rejection_reason}`);
  return "-";
}

function RepositoryToggle({
  client,
  repository,
  onQueued,
}: {
  readonly client: Pick<OperatorApiClient, "changeCodeSecurityRepository">;
  readonly repository: CodeSecurityRepository;
  readonly onQueued: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<RegistrationFeedback>(null);
  const action = repository.enabled ? "disable" : "enable";
  const toggle = async () => {
    setBusy(true);
    const result = await submitRepositoryChange(client, { action, repository_alias: repository.repository_alias });
    setFeedback(result);
    setBusy(false);
    if (result?.kind === "queued") onQueued();
  };
  return (
    <span class="code-security-toggle">
      <button type="button" class="btn subtle" disabled={busy} onClick={() => void toggle()}>
        {t(`codeSecurity.register.${action}`)}
      </button>
      <FeedbackLine feedback={feedback} />
    </span>
  );
}

export function RepositoryScanSection({
  client,
  repositories,
  requests,
  onQueued,
}: {
  readonly client: Pick<OperatorApiClient, "requestCodeSecurityScan" | "changeCodeSecurityRepository">;
  readonly repositories: CodeSecurityRepositoriesResponse | null;
  readonly requests: CodeSecurityScanRequestsResponse | null;
  readonly onQueued: () => void;
}) {
  if (repositories === null || requests === null) {
    return (
      <section class="stack" aria-labelledby="code-security-scans">
        <h2 id="code-security-scans">{t("codeSecurity.scan.title")}</h2>
        <p class="muted" role="status">{t("codeSecurity.scan.unavailable")}</p>
      </section>
    );
  }
  const repositoryColumns: readonly Column<CodeSecurityRepository>[] = [
    { key: "repository", header: t("codeSecurity.repoColumn.repository"), render: (row) => <span class="mono">{row.repository_alias}</span> },
    { key: "location", header: t("codeSecurity.repoColumn.location"), render: (row) => <span class="mono">{row.location}</span> },
    { key: "ref", header: t("codeSecurity.repoColumn.defaultRef"), render: (row) => <span class="mono">{row.default_ref}</span> },
    { key: "exposure", header: t("codeSecurity.repoColumn.exposure"), render: (row) => t(`codeSecurity.exposure.${row.exposure}`) },
    {
      key: "state",
      header: t("codeSecurity.repoColumn.state"),
      render: (row) => (
        <StatusPill
          kind={row.enabled ? "info" : "neutral"}
          label={t(`codeSecurity.repoState.${row.enabled ? "enabled" : "disabled"}`)}
        />
      ),
    },
    {
      key: "change",
      header: t("codeSecurity.repoColumn.change"),
      render: (row) => <RepositoryToggle client={client} repository={row} onQueued={onQueued} />,
    },
  ];
  const requestColumns: readonly Column<CodeSecurityScanRequest>[] = [
    { key: "requested", header: t("codeSecurity.requestColumn.requestedAt"), render: (row) => formatConsoleTimestamp(row.accepted_at) },
    { key: "repository", header: t("codeSecurity.requestColumn.repository"), render: (row) => <span class="mono">{row.repository_alias}</span> },
    {
      key: "kind",
      header: t("codeSecurity.requestColumn.kind"),
      render: (row) => (row.action === null ? t("codeSecurity.requestKind.scan") : t(`codeSecurity.requestKind.${row.action}`)),
    },
    {
      key: "ref",
      header: t("codeSecurity.requestColumn.ref"),
      render: (row) => !isScanResult(row.result)
        ? <span class="mono">{row.ref ?? row.location ?? "-"}</span>
        : (
          <Tooltip content={row.result.revision}>
            <span class="mono">{`${row.ref ?? ""} ${row.result.revision.slice(0, 12)}`.trim()}</span>
          </Tooltip>
        ),
    },
    {
      key: "status",
      header: t("codeSecurity.requestColumn.status"),
      render: (row) => <StatusPill kind={statusKind(row.status)} label={t(`codeSecurity.requestStatus.${row.status}`)} />,
    },
    { key: "result", header: t("codeSecurity.requestColumn.result"), render: resultText },
  ];
  const gaps = [...repositories.gaps, ...requests.gaps];
  return (
    <section class="stack" aria-labelledby="code-security-scans">
      <h2 id="code-security-scans">{t("codeSecurity.scan.title")}</h2>
      <p class="muted">{t("codeSecurity.scan.body")}</p>
      <ScanRequestForm client={client} repositories={repositories.repositories} onQueued={onQueued} />
      <RepositoryRegistrationForm client={client} onQueued={onQueued} />
      <DataTable
        columns={repositoryColumns}
        rows={repositories.repositories}
        keyOf={(row) => row.repository_alias}
        empty={t("codeSecurity.scan.noRepositories")}
        caption={t("codeSecurity.scan.repositoriesTitle")}
      />
      <DataTable
        columns={requestColumns}
        rows={requests.requests}
        keyOf={(row) => row.request_id}
        empty={t("codeSecurity.scan.requestsEmpty")}
        caption={t("codeSecurity.scan.requestsTitle")}
      />
      {gaps.length > 0
        ? (
          <div class="assurance-twin-gaps" role="status">
            <strong>{t("codeSecurity.scan.withheld")}</strong>
            <ul>
              {gaps.map((gap, index) => <li key={`${gap}:${index}`}>{t(`codeSecurity.gap.${gap}`)}</li>)}
            </ul>
          </div>
        )
        : null}
    </section>
  );
}
