import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable } from "../api";
import type { OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  StatusPill,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { t } from "./i18n/code-security";
import {
  panelArray,
  panelBoolean,
  panelContractError,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

const PRIORITIES = ["P0", "P1", "P2", "P3", "P4"] as const;
const SEVERITIES = ["critical", "high", "medium", "low", "undetermined"] as const;
const CONFIDENCES = ["hypothesis", "reported", "corroborated", "verified", "proven"] as const;
const GAPS = [
  "code_security_issue_malformed",
  "code_security_issues_unavailable",
  "code_security_issues_truncated",
] as const;

export interface CodeSecurityIssueSummary {
  readonly issue_id: string;
  readonly priority: (typeof PRIORITIES)[number];
  readonly due_days: number;
  readonly severity: (typeof SEVERITIES)[number];
  readonly confidence: (typeof CONFIDENCES)[number];
  readonly weakness_class: string;
  readonly cwe_ids: readonly number[];
  readonly advisory_ids: readonly string[];
  readonly package: string | null;
  readonly producers: readonly string[];
  readonly known_exploited: boolean;
}

export interface CodeSecurityIssuesResponse {
  readonly available: boolean;
  readonly issues: readonly CodeSecurityIssueSummary[];
  readonly gaps: readonly (typeof GAPS)[number][];
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    throw panelContractError(`${label} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

export function decodeCodeSecurityIssues(payload: unknown): CodeSecurityIssuesResponse {
  const root = panelRecord(payload, "code-security issues");
  return {
    available: panelBoolean(root, "available", "code-security issues"),
    issues: panelArray(root.issues, "code-security issues.issues").map((item, index) => {
      const label = `code-security issue ${index}`;
      const row = panelRecord(item, label);
      const cwe = panelArray(row.cwe_ids, `${label}.cwe_ids`).map((value) => {
        if (typeof value !== "number" || !Number.isInteger(value) || value <= 0) {
          throw panelContractError(`${label}.cwe_ids must hold CWE numbers`);
        }
        return value;
      });
      const pkg = row.package;
      if (pkg !== null && (typeof pkg !== "string" || pkg.length === 0)) {
        throw panelContractError(`${label}.package must be a string or null`);
      }
      return {
        issue_id: panelNonEmptyString(row, "issue_id", label),
        priority: oneOf(row.priority, PRIORITIES, `${label}.priority`),
        due_days: panelNonNegativeInteger(row, "due_days", label),
        severity: oneOf(row.severity, SEVERITIES, `${label}.severity`),
        confidence: oneOf(row.confidence, CONFIDENCES, `${label}.confidence`),
        weakness_class: panelNonEmptyString(row, "weakness_class", label),
        cwe_ids: cwe,
        advisory_ids: panelStringArray(row.advisory_ids, `${label}.advisory_ids`),
        package: pkg,
        producers: panelStringArray(row.producers, `${label}.producers`),
        known_exploited: panelBoolean(row, "known_exploited", label),
      };
    }),
    gaps: panelArray(root.gaps, "code-security issues.gaps").map((gap, index) =>
      oneOf(panelRecord(gap, `issue gap ${index}`).reason_code, GAPS, `issue gap ${index}`)),
  };
}

function severityKind(severity: CodeSecurityIssueSummary["severity"]): PillKind {
  if (severity === "critical") return "danger";
  if (severity === "high" || severity === "medium") return "warning";
  return "neutral";
}

/** CWE ids for code issues; advisory ids and the package for dependency issues. */
export function issueReference(issue: CodeSecurityIssueSummary): string {
  if (issue.cwe_ids.length > 0) return issue.cwe_ids.map((cwe) => `CWE-${cwe}`).join(", ");
  const advisories = issue.advisory_ids.join(", ");
  return issue.package === null ? advisories || "-" : `${issue.package} ${advisories}`.trim();
}

export function ReviewIssuesPanel({
  client,
  repositoryAlias,
  revision,
  onClose,
}: {
  readonly client: Pick<OperatorApiClient, "panel">;
  readonly repositoryAlias: string;
  readonly revision: string;
  readonly onClose: () => void;
}) {
  const [state, setState] = useState<AsyncState<CodeSecurityIssuesResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    client
      .panel<unknown>("/code-security/issues", { repository_alias: repositoryAlias, revision })
      .then((payload) => {
        if (!cancelled) setState({ status: "ready", data: decodeCodeSecurityIssues(payload) });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setState(
          isOptionalOperatorApiUnavailable(error)
            ? { status: "unavailable", message: t("codeSecurity.issues.unavailable") }
            : { status: "error", message: error instanceof Error ? error.message : String(error) },
        );
      });
    return () => { cancelled = true; };
  }, [client, repositoryAlias, revision]);
  const columns: readonly Column<CodeSecurityIssueSummary>[] = [
    { key: "id", header: t("codeSecurity.issues.column.issue"), render: (row) => <span class="mono">{row.issue_id}</span> },
    { key: "priority", header: t("codeSecurity.issues.column.priority"), render: (row) => row.priority },
    {
      key: "severity",
      header: t("codeSecurity.issues.column.severity"),
      render: (row) => <StatusPill kind={severityKind(row.severity)} label={row.severity} />,
    },
    { key: "confidence", header: t("codeSecurity.issues.column.confidence"), render: (row) => row.confidence },
    { key: "class", header: t("codeSecurity.issues.column.weaknessClass"), render: (row) => row.weakness_class },
    { key: "reference", header: t("codeSecurity.issues.column.reference"), render: (row) => <span class="mono">{issueReference(row)}</span> },
    { key: "producers", header: t("codeSecurity.issues.column.producers"), render: (row) => row.producers.join(", ") },
    {
      key: "kev",
      header: t("codeSecurity.issues.column.knownExploited"),
      render: (row) => (row.known_exploited ? t("codeSecurity.issues.yes") : "-"),
    },
  ];
  return (
    <section class="stack code-security-issues" aria-labelledby="code-security-issues-title">
      <div class="code-security-issues-header">
        <h3 id="code-security-issues-title">
          {`${t("codeSecurity.issues.title")}: ${repositoryAlias} ${revision.slice(0, 12)}`}
        </h3>
        <button type="button" class="btn subtle" onClick={onClose}>{t("codeSecurity.issues.close")}</button>
      </div>
      <p class="muted">{t("codeSecurity.issues.body")}</p>
      <AsyncBoundary state={state} resourceLabel={t("codeSecurity.issues.title")}>
        {(data) => (
          <>
            <DataTable
              columns={columns}
              rows={data.issues}
              keyOf={(row) => row.issue_id}
              empty={data.available ? t("codeSecurity.issues.empty") : t("codeSecurity.issues.notRecorded")}
              caption={t("codeSecurity.issues.title")}
            />
            {data.gaps.length > 0
              ? (
                <ul class="assurance-twin-gaps" role="status">
                  {data.gaps.map((gap, index) => <li key={`${gap}:${index}`}>{t(`codeSecurity.gap.${gap}`)}</li>)}
                </ul>
              )
              : null}
          </>
        )}
      </AsyncBoundary>
    </section>
  );
}
