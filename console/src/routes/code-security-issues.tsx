import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable } from "../api";
import type { OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  CopyButton,
  ExternalLink,
  StatusPill,
  type AsyncState,
  type PillKind,
} from "../components/ui";
import { routeHref } from "../router";
import { t } from "./i18n/code-security";
import { formatConsoleTimestamp } from "../time-format";
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
const DETERMINED_SEVERITIES = ["critical", "high", "medium", "low"] as const;
const CONFIDENCES = ["hypothesis", "reported", "corroborated", "verified", "proven"] as const;
const GAPS = [
  "code_security_issue_malformed",
  "code_security_issues_unavailable",
  "code_security_issues_truncated",
  "code_security_artifacts_unavailable",
  "code_security_artifacts_malformed",
] as const;
const SCORECARD_KEYS = [
  "critical",
  "high",
  "medium",
  "low",
  "informational",
  "needs_review",
] as const;
type ScorecardKey = (typeof SCORECARD_KEYS)[number];
const PRIORITY_ORDER = new Map(PRIORITIES.map((priority, index) => [priority, index]));
const SEVERITY_ORDER = new Map(
  ["critical", "high", "medium", "low", "undetermined"].map((severity, index) => [severity, index]),
);
const PAGE_SIZE = 25;
const FLOW_KINDS = ["source", "flow", "call", "return", "sanitizer", "sink"] as const;
const ANALYSIS_ID = /^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$/;
const SHA256 = /^sha256:[0-9a-f]{64}$/;
const SEMVER = /^\d+\.\d+\.\d+$/;

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
  readonly title: string | null;
  readonly severity_floor: Exclude<(typeof SEVERITIES)[number], "undetermined"> | null;
  readonly severity_ceiling: Exclude<(typeof SEVERITIES)[number], "undetermined"> | null;
  readonly severity_rationale: string | null;
  readonly deciding_facts: readonly string[];
  readonly location: {
    readonly path: string;
    readonly start_line: number | null;
  } | null;
  readonly code_context: {
    readonly highlight_start: number;
    readonly highlight_end: number;
    readonly redacted: boolean;
    readonly lines: readonly {
      readonly number: number;
      readonly text: string;
    }[];
  } | null;
  readonly flow_steps: readonly {
    readonly kind: (typeof FLOW_KINDS)[number];
    readonly path: string;
    readonly line: number | null;
    readonly end_line: number | null;
    readonly node_id: string | null;
    readonly call_context: readonly string[];
  }[];
  readonly analysis_evidence: {
    readonly path_id: string;
    readonly path_digest: string;
    readonly graph_digest: string;
    readonly graph_schema_version: string;
    readonly path_schema_version: string;
    readonly rule_version: string;
    readonly frontend_versions: Readonly<Record<string, string>>;
    readonly coverage_limits: readonly string[];
  } | null;
}

export interface CodeSecurityIssuesResponse {
  readonly available: boolean;
  readonly issues: readonly CodeSecurityIssueSummary[];
  readonly artifacts: {
    readonly mode: "full" | "summary";
    readonly html: string;
    readonly sarif: string;
  } | null;
  readonly scorecard: Readonly<Record<
    | ScorecardKey
    | "total"
    | "determined"
    | "potential_critical"
    | "potential_high"
    | "potential_medium"
    | "potential_low",
    number
  >>;
  readonly coverage: {
    readonly complete: boolean;
    readonly limits: readonly string[];
    readonly details_available: boolean;
  };
  readonly review_summary: {
    readonly recorded_total: number;
    readonly recorded_determined: number;
    readonly recorded_needs_review: number;
    readonly shown_total: number;
    readonly truncated: boolean;
    readonly recorded_by_severity: Readonly<Record<
      (typeof SEVERITIES)[number],
      number
    >>;
  };
  readonly gaps: readonly (typeof GAPS)[number][];
}

export function findingResultCount(
  data: CodeSecurityIssuesResponse,
  _visible: number,
): { readonly available: number; readonly recorded: number; readonly bounded: boolean } {
  return {
    available: data.review_summary.shown_total,
    recorded: data.review_summary.recorded_total,
    bounded: data.review_summary.truncated,
  };
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    throw panelContractError(`${label} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function formatSarif(value: unknown): string {
  const text = panelNonEmptyString({ value }, "value", "code-security issues.artifacts.sarif");
  try {
    const document = JSON.parse(text) as unknown;
    const root = panelRecord(document, "code-security issues.artifacts.sarif");
    if (root.version !== "2.1.0") {
      throw panelContractError("code-security issues.artifacts.sarif must be SARIF 2.1.0");
    }
    return JSON.stringify(document, null, 2);
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw panelContractError("code-security issues.artifacts.sarif must be valid JSON");
    }
    throw error;
  }
}

export function decodeCodeSecurityIssues(payload: unknown): CodeSecurityIssuesResponse {
  const root = panelRecord(payload, "code-security issues");
  const artifacts = root.artifacts === null || root.artifacts === undefined
    ? null
    : (() => {
      const record = panelRecord(root.artifacts, "code-security issues.artifacts");
      return {
        mode: oneOf(
          record.mode,
          ["full", "summary"] as const,
          "code-security issues.artifacts.mode",
        ),
        html: panelNonEmptyString(record, "html", "code-security issues.artifacts"),
        sarif: formatSarif(record.sarif),
      };
    })();
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
      const location = row.location === null || row.location === undefined
        ? null
        : (() => {
          const value = panelRecord(row.location, `${label}.location`);
          const line = value.start_line;
          if (
            line !== null
            && (typeof line !== "number" || !Number.isInteger(line) || line <= 0)
          ) {
            throw panelContractError(`${label}.location.start_line must be positive or null`);
          }
          return {
            path: panelNonEmptyString(value, "path", `${label}.location`),
            start_line: line,
          };
        })();
      const codeContext = row.code_context === null || row.code_context === undefined
        ? null
        : (() => {
          const value = panelRecord(row.code_context, `${label}.code_context`);
          return {
            highlight_start: panelNonNegativeInteger(value, "highlight_start", `${label}.code_context`),
            highlight_end: panelNonNegativeInteger(value, "highlight_end", `${label}.code_context`),
            redacted: panelBoolean(value, "redacted", `${label}.code_context`),
            lines: panelArray(value.lines, `${label}.code_context.lines`).map((line, lineIndex) => {
              const record = panelRecord(line, `${label}.code_context.lines ${lineIndex}`);
              return {
                number: panelNonNegativeInteger(record, "number", `${label}.code_context.lines`),
                text: typeof record.text === "string"
                  ? record.text
                  : (() => { throw panelContractError(`${label}.code_context line text must be a string`); })(),
              };
            }),
          };
        })();
      const flowSteps = row.flow_steps === undefined
        ? []
        : panelArray(row.flow_steps, `${label}.flow_steps`).map((step, stepIndex, steps) => {
          if (steps.length > 64) {
            throw panelContractError(`${label}.flow_steps exceeds 64 steps`);
          }
          const value = panelRecord(step, `${label}.flow_steps ${stepIndex}`);
          const line = value.line;
          if (
            line !== null
            && (typeof line !== "number" || !Number.isInteger(line) || line <= 0)
          ) {
            throw panelContractError(`${label}.flow_steps line must be positive or null`);
          }
          const endLine = value.end_line ?? null;
          if (
            endLine !== null
            && (
              typeof endLine !== "number"
              || !Number.isInteger(endLine)
              || endLine <= 0
              || (typeof line === "number" && endLine < line)
            )
          ) {
            throw panelContractError(`${label}.flow_steps end_line must follow line`);
          }
          const nodeId = value.node_id ?? null;
          if (nodeId !== null && (typeof nodeId !== "string" || !ANALYSIS_ID.test(nodeId))) {
            throw panelContractError(`${label}.flow_steps node_id is invalid`);
          }
          const callContext = value.call_context === undefined
            ? []
            : panelStringArray(value.call_context, `${label}.flow_steps.call_context`);
          if (callContext.length > 16 || callContext.some(item => !ANALYSIS_ID.test(item))) {
            throw panelContractError(`${label}.flow_steps call_context is invalid`);
          }
          return {
            kind: oneOf(value.kind, FLOW_KINDS, `${label}.flow_steps.kind`),
            path: panelNonEmptyString(value, "path", `${label}.flow_steps`),
            line,
            end_line: endLine,
            node_id: nodeId,
            call_context: callContext,
          };
        });
      const analysisEvidence = row.analysis_evidence === null || row.analysis_evidence === undefined
        ? null
        : (() => {
          const value = panelRecord(row.analysis_evidence, `${label}.analysis_evidence`);
          const required = (key: string, pattern: RegExp): string => {
            const raw = panelNonEmptyString(value, key, `${label}.analysis_evidence`);
            if (!pattern.test(raw)) {
              throw panelContractError(`${label}.analysis_evidence ${key} is invalid`);
            }
            return raw;
          };
          const rawFrontends = panelRecord(
            value.frontend_versions,
            `${label}.analysis_evidence.frontend_versions`,
          );
          const frontendVersions = Object.fromEntries(
            Object.entries(rawFrontends).map(([key, version]) => {
              if (!ANALYSIS_ID.test(key) || typeof version !== "string" || !SEMVER.test(version)) {
                throw panelContractError(`${label}.analysis_evidence frontend version is invalid`);
              }
              return [key, version];
            }),
          );
          const coverageLimits = panelStringArray(
            value.coverage_limits,
            `${label}.analysis_evidence.coverage_limits`,
          );
          if (
            Object.keys(frontendVersions).length === 0
            || Object.keys(frontendVersions).length > 16
            || coverageLimits.length > 64
            || coverageLimits.some(item => !ANALYSIS_ID.test(item))
          ) {
            throw panelContractError(`${label}.analysis_evidence is outside bounds`);
          }
          return {
            path_id: required("path_id", ANALYSIS_ID),
            path_digest: required("path_digest", SHA256),
            graph_digest: required("graph_digest", SHA256),
            graph_schema_version: required("graph_schema_version", SEMVER),
            path_schema_version: required("path_schema_version", SEMVER),
            rule_version: required("rule_version", SEMVER),
            frontend_versions: frontendVersions,
            coverage_limits: coverageLimits,
          };
        })();
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
        title: row.title === null || row.title === undefined
          ? null
          : panelNonEmptyString(row, "title", label),
        severity_floor: row.severity_floor === null || row.severity_floor === undefined
          ? null
          : oneOf(row.severity_floor, DETERMINED_SEVERITIES, `${label}.severity_floor`),
        severity_ceiling: row.severity_ceiling === null || row.severity_ceiling === undefined
          ? null
          : oneOf(row.severity_ceiling, DETERMINED_SEVERITIES, `${label}.severity_ceiling`),
        severity_rationale: row.severity_rationale === null || row.severity_rationale === undefined
          ? null
          : panelNonEmptyString(row, "severity_rationale", label),
        deciding_facts: row.deciding_facts === undefined
          ? []
          : panelStringArray(row.deciding_facts, `${label}.deciding_facts`),
        location,
        code_context: codeContext,
        flow_steps: flowSteps,
        analysis_evidence: analysisEvidence,
      };
    }),
    artifacts,
    scorecard: (() => {
      const scorecard = panelRecord(root.scorecard, "code-security issues.scorecard");
      return Object.fromEntries(
        [
          ...SCORECARD_KEYS,
          "total",
          "determined",
          "potential_critical",
          "potential_high",
          "potential_medium",
          "potential_low",
        ]
          .map((key) => [key, panelNonNegativeInteger(scorecard, key, "code-security issues.scorecard")]),
      ) as CodeSecurityIssuesResponse["scorecard"];
    })(),
    coverage: (() => {
      const coverage = panelRecord(root.coverage, "code-security issues.coverage");
      return {
        complete: panelBoolean(coverage, "complete", "code-security issues.coverage"),
        limits: panelStringArray(coverage.limits, "code-security issues.coverage.limits"),
        details_available: panelBoolean(
          coverage,
          "details_available",
          "code-security issues.coverage",
        ),
      };
    })(),
    review_summary: (() => {
      const summary = panelRecord(root.review_summary, "code-security issues.review_summary");
      return {
        recorded_total: panelNonNegativeInteger(
          summary,
          "recorded_total",
          "code-security issues.review_summary",
        ),
        recorded_determined: panelNonNegativeInteger(
          summary,
          "recorded_determined",
          "code-security issues.review_summary",
        ),
        recorded_needs_review: panelNonNegativeInteger(
          summary,
          "recorded_needs_review",
          "code-security issues.review_summary",
        ),
        shown_total: panelNonNegativeInteger(
          summary,
          "shown_total",
          "code-security issues.review_summary",
        ),
        truncated: panelBoolean(summary, "truncated", "code-security issues.review_summary"),
        recorded_by_severity: Object.fromEntries(
          SEVERITIES.map((severity) => [
            severity,
            panelNonNegativeInteger(
              panelRecord(
                summary.recorded_by_severity,
                "code-security issues.review_summary.recorded_by_severity",
              ),
              severity,
              "code-security issues.review_summary.recorded_by_severity",
            ),
          ]),
        ) as CodeSecurityIssuesResponse["review_summary"]["recorded_by_severity"],
      };
    })(),
    gaps: panelArray(root.gaps, "code-security issues.gaps").map((gap, index) =>
      oneOf(panelRecord(gap, `issue gap ${index}`).reason_code, GAPS, `issue gap ${index}`)),
  };
}

function severityKind(severity: CodeSecurityIssueSummary["severity"]): PillKind {
  if (severity === "critical") return "danger";
  if (severity === "high" || severity === "medium") return "warning";
  return "neutral";
}

function severityLabel(issue: CodeSecurityIssueSummary): string {
  if (
    issue.severity === "undetermined"
    && issue.severity_floor !== null
    && issue.severity_ceiling !== null
  ) {
    return `${issue.severity_floor} - ${issue.severity_ceiling}`;
  }
  return issue.severity;
}

function issueLocation(issue: CodeSecurityIssueSummary): string {
  if (issue.location === null) return t("codeSecurity.issues.locationUnavailable");
  return issue.location.start_line === null
    ? issue.location.path
    : `${issue.location.path}:${issue.location.start_line}`;
}

function scorecardMatches(issue: CodeSecurityIssueSummary, key: ScorecardKey | "all"): boolean {
  if (key === "all") return true;
  if (key === "needs_review") return issue.severity === "undetermined";
  if (key === "informational") return issue.severity === "low" && issue.priority === "P4";
  if (key === "low") return issue.severity === "low" && issue.priority !== "P4";
  return issue.severity === key;
}

function findingSearchText(issue: CodeSecurityIssueSummary): string {
  return [
    issue.title,
    issue.issue_id,
    issue.weakness_class,
    issue.location?.path,
    issue.package,
    ...issue.producers,
    ...issue.advisory_ids,
    ...issue.cwe_ids.map((cwe) => `CWE-${cwe}`),
  ].filter((value): value is string => typeof value === "string").join(" ").toLocaleLowerCase();
}

function compareIssues(
  left: CodeSecurityIssueSummary,
  right: CodeSecurityIssueSummary,
  sort: "priority" | "severity" | "path",
): number {
  if (sort === "path") return issueLocation(left).localeCompare(issueLocation(right));
  if (sort === "severity") {
    const leftSeverity = left.severity_ceiling ?? left.severity;
    const rightSeverity = right.severity_ceiling ?? right.severity;
    return (SEVERITY_ORDER.get(leftSeverity) ?? 99) - (SEVERITY_ORDER.get(rightSeverity) ?? 99)
      || (PRIORITY_ORDER.get(left.priority) ?? 99) - (PRIORITY_ORDER.get(right.priority) ?? 99)
      || issueLocation(left).localeCompare(issueLocation(right));
  }
  return (PRIORITY_ORDER.get(left.priority) ?? 99) - (PRIORITY_ORDER.get(right.priority) ?? 99)
    || (SEVERITY_ORDER.get(left.severity_ceiling ?? left.severity) ?? 99)
      - (SEVERITY_ORDER.get(right.severity_ceiling ?? right.severity) ?? 99)
    || issueLocation(left).localeCompare(issueLocation(right));
}

function coverageLimitLabel(limit: string): string {
  const exited = /^scanner ([A-Za-z0-9._-]+) exited (-?[0-9]+)$/.exec(limit);
  if (exited !== null) {
    return t("codeSecurity.issues.coverageScannerExit", {
      scanner: exited[1]!,
      code: exited[2]!,
    });
  }
  return limit;
}

function decidingFactLabel(fact: string): string {
  const key = `codeSecurity.issues.fact.${fact}`;
  const translated = t(key);
  return translated === key ? fact.replaceAll("_", " ") : translated;
}

function downloadArtifact(name: string, content: string, type: string): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function githubFileUrl(
  repositoryLocation: string | null,
  revision: string,
  issue: CodeSecurityIssueSummary,
): string | null {
  if (repositoryLocation === null || issue.location === null) return null;
  const repository = repositoryLocation.split("/").map(encodeURIComponent).join("/");
  const path = issue.location.path.split("/").map(encodeURIComponent).join("/");
  const line = issue.location.start_line === null ? "" : `#L${issue.location.start_line}`;
  return `https://github.com/${repository}/blob/${revision}/${path}${line}`;
}

/** CWE ids for code issues; advisory ids and the package for dependency issues. */
export function issueReference(issue: CodeSecurityIssueSummary): string {
  if (issue.cwe_ids.length > 0) return issue.cwe_ids.map((cwe) => `CWE-${cwe}`).join(", ");
  const advisories = issue.advisory_ids.join(", ");
  return issue.package === null ? advisories || "-" : `${issue.package} ${advisories}`.trim();
}

export function formatCodeSecurityReviewMarkdownBrief(
  repositoryAlias: string,
  revision: string,
  reviewDigest: string,
  data: CodeSecurityIssuesResponse,
): string {
  const topIssues = data.issues.slice(0, 10).map(
    (issue) =>
      `- **[${issue.priority} / ${severityLabel(issue)}]** \`${issue.issue_id}\` (${issue.weakness_class}) -- ${issueReference(issue)} @ \`${issueLocation(issue)}\` (confidence: ${issue.confidence}, KEV: ${issue.known_exploited})`,
  );
  return [
    `# Code Security Review: ${repositoryAlias} (${revision.slice(0, 12)})`,
    `- **Review Digest:** \`${reviewDigest}\``,
    `- **Coverage:** ${data.coverage.complete ? "complete" : "incomplete"}`,
    `- **Findings:** ${data.review_summary.recorded_total} total (${data.review_summary.recorded_determined} determined, ${data.review_summary.recorded_needs_review} needs review)`,
    `- **Scorecard:** critical=${data.scorecard.critical}, high=${data.scorecard.high}, medium=${data.scorecard.medium}, low=${data.scorecard.low}`,
    `- **Execution Authority:** \`false\` (read-only projection)`,
    ...(topIssues.length > 0 ? ["", "## Top Findings", ...topIssues] : []),
  ].join("\n");
}

export function ReviewIssuesPanel({
  client,
  repositoryAlias,
  repositoryLocation,
  revision,
  reviewDigest,
  recordedAt,
  reviewSource,
  producers: reviewProducers,
  onClose,
}: {
  readonly client: Pick<OperatorApiClient, "panel">;
  readonly repositoryAlias: string;
  readonly repositoryLocation: string | null;
  readonly revision: string;
  readonly reviewDigest: string;
  readonly recordedAt: string;
  readonly reviewSource: string;
  readonly producers: readonly string[];
  readonly onClose: () => void;
}) {
  const [state, setState] = useState<AsyncState<CodeSecurityIssuesResponse>>({ status: "loading" });
  const [selectedIssue, setSelectedIssue] = useState<CodeSecurityIssueSummary | null>(null);
  const detailRef = useRef<HTMLElement>(null);
  const [reportView, setReportView] = useState<"html" | "sarif" | null>(null);
  const [scorecardFilter, setScorecardFilter] = useState<ScorecardKey | "all">("all");
  const [query, setQuery] = useState("");
  const [producer, setProducer] = useState("all");
  const [weakness, setWeakness] = useState("all");
  const [sort, setSort] = useState<"priority" | "severity" | "path">("priority");
  const [page, setPage] = useState(1);
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
  const producers = useMemo(
    () => state.status === "ready"
      ? [...new Set(state.data.issues.flatMap((issue) => issue.producers))].sort()
      : [],
    [state],
  );
  const weaknesses = useMemo(
    () => state.status === "ready"
      ? [...new Set(state.data.issues.map((issue) => issue.weakness_class))].sort()
      : [],
    [state],
  );
  const visibleIssues = useMemo(() => {
    if (state.status !== "ready") return [];
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return state.data.issues
      .filter((issue) => scorecardMatches(issue, scorecardFilter))
      .filter((issue) => producer === "all" || issue.producers.includes(producer))
      .filter((issue) => weakness === "all" || issue.weakness_class === weakness)
      .filter((issue) => normalizedQuery === "" || findingSearchText(issue).includes(normalizedQuery))
      .sort((left, right) => compareIssues(left, right, sort));
  }, [producer, query, scorecardFilter, sort, state, weakness]);
  const pageCount = Math.max(1, Math.ceil(visibleIssues.length / PAGE_SIZE));
  const pageIssues = visibleIssues.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  useEffect(() => setPage(1), [producer, query, scorecardFilter, sort, weakness]);
  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);
  useEffect(() => {
    if (
      state.status === "ready"
      && (
        selectedIssue === null
        || !pageIssues.some((issue) => issue.issue_id === selectedIssue.issue_id)
      )
    ) {
      setSelectedIssue(pageIssues[0] ?? null);
    }
  }, [pageIssues, selectedIssue, state]);
  return (
    <section class="stack code-security-issues" aria-labelledby="code-security-issues-title">
      <div class="code-security-issues-header">
        <h3 id="code-security-issues-title">
          {`${t("codeSecurity.issues.title")}: ${repositoryAlias} ${revision.slice(0, 12)}`}
        </h3>
        <div class="row" style="gap: 8px;">
          {state.status === "ready" ? (
            <CopyButton
              text={formatCodeSecurityReviewMarkdownBrief(
                repositoryAlias,
                revision,
                reviewDigest,
                state.data,
              )}
              label={t("codeSecurity.issues.copyBrief")}
            />
          ) : null}
          <button type="button" class="btn subtle" onClick={onClose}>{t("codeSecurity.issues.close")}</button>
        </div>
      </div>
      <p class="muted">{t("codeSecurity.issues.body")}</p>
      <dl class="code-security-review-provenance" aria-label={t("codeSecurity.issues.provenance")}>
        <div>
          <dt>{t("codeSecurity.issues.reviewDigest")}</dt>
          <dd class="mono">{reviewDigest}</dd>
        </div>
        <div>
          <dt>{t("codeSecurity.issues.recordedAt")}</dt>
          <dd>{formatConsoleTimestamp(recordedAt)}</dd>
        </div>
        <div>
          <dt>{t("codeSecurity.issues.reviewSource")}</dt>
          <dd>{reviewSource}</dd>
        </div>
        <div>
          <dt>{t("codeSecurity.issues.reviewProducers")}</dt>
          <dd>{reviewProducers.join(", ") || t("codeSecurity.issues.notRecorded")}</dd>
        </div>
      </dl>
      <AsyncBoundary state={state} resourceLabel={t("codeSecurity.issues.title")}>
        {(data) => (
          <>
            {data.coverage.complete
              ? (
                <div class="code-security-coverage-status complete" role="status">
                  <strong>{t("codeSecurity.issues.coverageComplete")}</strong>
                  <span>{t("codeSecurity.issues.coverageCompleteBody")}</span>
                </div>
              )
              : (
                <div class="code-security-coverage-status incomplete" role="alert">
                  <div>
                    <strong>{t("codeSecurity.issues.coverageIncomplete")}</strong>
                    <span>{t("codeSecurity.issues.coverageIncompleteBody")}</span>
                  </div>
                  {data.coverage.limits.length === 0
                    ? (
                      <span class="muted">
                        {data.coverage.details_available
                          ? t("codeSecurity.issues.coverageLimitsUnknown")
                          : t("codeSecurity.issues.coverageDetailsUnavailable")}
                      </span>
                    )
                    : (
                      <ul>
                        {data.coverage.limits.map((limit) => (
                          <li key={limit}>{coverageLimitLabel(limit)}</li>
                        ))}
                      </ul>
                    )}
                </div>
              )}
            <section class="code-security-review-summary" aria-label={t("codeSecurity.issues.scorecard")}>
              <div class="code-security-review-primary">
                <span>{t("codeSecurity.issues.reviewRequired")}</span>
                <strong>{data.review_summary.recorded_needs_review}</strong>
                <p>
                  {t("codeSecurity.issues.reviewRequiredBody", {
                    total: data.review_summary.recorded_total,
                    determined: data.review_summary.recorded_determined,
                  })}
                </p>
                {data.review_summary.truncated
                  ? (
                    <small>
                      {t("codeSecurity.issues.boundedSummary", {
                        shown: data.review_summary.shown_total,
                        total: data.review_summary.recorded_total,
                      })}
                    </small>
                  )
                  : null}
              </div>
              <dl>
                <div>
                  <dt>{t("codeSecurity.issues.totalFindings")}</dt>
                  <dd>{data.review_summary.recorded_total}</dd>
                </div>
                <div>
                  <dt>{t("codeSecurity.issues.determinedFindings")}</dt>
                  <dd>{data.review_summary.recorded_determined}</dd>
                </div>
                <div>
                  <dt>{t("codeSecurity.issues.potentialCriticalLabel")}</dt>
                  <dd>{data.scorecard.potential_critical}</dd>
                </div>
                <div>
                  <dt>{t("codeSecurity.issues.coverage")}</dt>
                  <dd>
                    {data.coverage.complete
                      ? t("codeSecurity.issues.complete")
                      : t("codeSecurity.issues.incomplete")}
                  </dd>
                </div>
              </dl>
              <div class="code-security-recorded-severity">
                <span>{t("codeSecurity.issues.recordedSeverity")}</span>
                {(["critical", "high", "medium", "low", "undetermined"] as const).map(
                  (severity) => (
                    <span key={severity}>
                      {`${t(`codeSecurity.issues.score.${
                        severity === "undetermined" ? "needs_review" : severity
                      }`)} ${data.review_summary.recorded_by_severity[severity]}`}
                    </span>
                  ),
                )}
              </div>
            </section>
            <div
              class="code-security-severity-filters"
              role="group"
              aria-label={t("codeSecurity.issues.severityFilters")}
            >
              <button
                type="button"
                class={scorecardFilter === "all" ? "active" : ""}
                aria-pressed={scorecardFilter === "all"}
                onClick={() => setScorecardFilter("all")}
              >
                {`${t("codeSecurity.issues.score.all")} ${data.scorecard.total}`}
              </button>
              {SCORECARD_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  class={scorecardFilter === key ? "active" : ""}
                  aria-pressed={scorecardFilter === key}
                  onClick={() => setScorecardFilter(key)}
                >
                  {`${t(`codeSecurity.issues.score.${key}`)} ${data.scorecard[key]}`}
                </button>
              ))}
            </div>
            <div class="code-security-finding-tools">
              <label class="cs-control-field code-security-finding-search">
                <span class="cs-control-label">{t("codeSecurity.issues.search")}</span>
                <input
                  class="cs-control-input"
                  type="search"
                  value={query}
                  placeholder={t("codeSecurity.issues.searchPlaceholder")}
                  onInput={(event) => setQuery(event.currentTarget.value)}
                />
              </label>
              <label class="cs-control-field">
                <span class="cs-control-label">{t("codeSecurity.issues.producer")}</span>
                <select
                  class="cs-control-select"
                  value={producer}
                  onChange={(event) => setProducer(event.currentTarget.value)}
                >
                  <option value="all">{t("codeSecurity.issues.allProducers")}</option>
                  {producers.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <label class="cs-control-field">
                <span class="cs-control-label">{t("codeSecurity.issues.weakness")}</span>
                <select
                  class="cs-control-select"
                  value={weakness}
                  onChange={(event) => setWeakness(event.currentTarget.value)}
                >
                  <option value="all">{t("codeSecurity.issues.allWeaknesses")}</option>
                  {weaknesses.map((item) => (
                    <option key={item} value={item}>{item.replaceAll("_", " ")}</option>
                  ))}
                </select>
              </label>
              <label class="cs-control-field">
                <span class="cs-control-label">{t("codeSecurity.issues.sort")}</span>
                <select
                  class="cs-control-select"
                  value={sort}
                  onChange={(event) =>
                    setSort(event.currentTarget.value as "priority" | "severity" | "path")}
                >
                  <option value="priority">{t("codeSecurity.issues.sortPriority")}</option>
                  <option value="severity">{t("codeSecurity.issues.sortSeverity")}</option>
                  <option value="path">{t("codeSecurity.issues.sortPath")}</option>
                </select>
              </label>
            </div>
            {visibleIssues.length === 0
              ? (
                <p class="muted" role="status">
                  {data.issues.length > 0
                    ? t("codeSecurity.issues.noFilterResults")
                    : data.available
                    ? t("codeSecurity.issues.empty")
                    : t("codeSecurity.issues.notRecorded")}
                </p>
              )
              : (
                <div class="code-security-review-workspace">
                  <nav class="code-security-finding-list" aria-label={t("codeSecurity.issues.findingsList")}>
                    {pageIssues.map((issue) => (
                      <button
                        key={issue.issue_id}
                        type="button"
                        aria-controls="code-security-finding-detail"
                        aria-current={selectedIssue?.issue_id === issue.issue_id ? "true" : undefined}
                        onClick={() => {
                          setSelectedIssue(issue);
                          window.requestAnimationFrame(() => detailRef.current?.focus());
                        }}
                      >
                        <span>
                          <strong>{issue.title ?? issue.weakness_class.replaceAll("_", " ")}</strong>
                          <StatusPill kind={severityKind(issue.severity)} label={severityLabel(issue)} />
                        </span>
                        <span class="mono">{issueLocation(issue)}</span>
                        <small>{`${issue.priority} · ${issue.confidence} · ${issue.issue_id}`}</small>
                      </button>
                    ))}
                    <footer class="code-security-finding-pagination">
                      <span>
                        {(() => {
                          const count = findingResultCount(data, visibleIssues.length);
                          return t(
                            count.bounded
                              ? "codeSecurity.issues.resultCountBounded"
                              : "codeSecurity.issues.resultCount",
                            {
                              visible: visibleIssues.length,
                              available: count.available,
                              recorded: count.recorded,
                            },
                          );
                        })()}
                      </span>
                      <div>
                        <button
                          type="button"
                          class="btn subtle"
                          disabled={page <= 1}
                          onClick={() => setPage((current) => Math.max(1, current - 1))}
                        >
                          {t("codeSecurity.issues.previousPage")}
                        </button>
                        <span>
                          {t("codeSecurity.issues.pageStatus", { page, pages: pageCount })}
                        </span>
                        <button
                          type="button"
                          class="btn subtle"
                          disabled={page >= pageCount}
                          onClick={() => setPage((current) => Math.min(pageCount, current + 1))}
                        >
                          {t("codeSecurity.issues.nextPage")}
                        </button>
                      </div>
                    </footer>
                  </nav>
                  {selectedIssue === null
                    ? null
                    : (
                      <article
                        id="code-security-finding-detail"
                        ref={detailRef}
                        class="code-security-finding-detail"
                        aria-label={t("codeSecurity.issues.detailTitle")}
                        tabIndex={-1}
                      >
                        <header>
                          <div>
                            <StatusPill
                              kind={severityKind(selectedIssue.severity)}
                              label={severityLabel(selectedIssue)}
                            />
                            <StatusPill kind="neutral" label={selectedIssue.priority} />
                          </div>
                          <h4>
                            {selectedIssue.title
                              ?? selectedIssue.weakness_class.replaceAll("_", " ")}
                          </h4>
                          <p class="mono">{issueLocation(selectedIssue)}</p>
                          {githubFileUrl(repositoryLocation, revision, selectedIssue) === null
                            ? null
                            : (
                              <ExternalLink
                                href={githubFileUrl(repositoryLocation, revision, selectedIssue)!}
                              >
                                {t("codeSecurity.issues.openGithub")}
                              </ExternalLink>
                            )}
                        </header>
                        <section class="code-security-severity-reason">
                          <strong>
                            {selectedIssue.severity === "undetermined"
                              ? t("codeSecurity.issues.severityUndetermined")
                              : t("codeSecurity.issues.severityDetermined")}
                          </strong>
                          <p>
                            {selectedIssue.severity === "undetermined"
                              && selectedIssue.severity_floor !== null
                              && selectedIssue.severity_ceiling !== null
                              ? t("codeSecurity.issues.severityRangeBody", {
                                floor: selectedIssue.severity_floor,
                                ceiling: selectedIssue.severity_ceiling,
                              })
                              : t("codeSecurity.issues.severityDeterminedBody", {
                                severity: selectedIssue.severity,
                              })}
                          </p>
                          {selectedIssue.deciding_facts.length === 0
                            ? null
                            : (
                              <>
                                <span>{t("codeSecurity.issues.decidingFacts")}</span>
                                <ul>
                                  {selectedIssue.deciding_facts.map((fact) => (
                                    <li key={fact}>{decidingFactLabel(fact)}</li>
                                  ))}
                                </ul>
                              </>
                            )}
                          {selectedIssue.severity_rationale === null
                            ? null
                            : (
                              <details>
                                <summary>{t("codeSecurity.issues.technicalRationale")}</summary>
                                <p>{selectedIssue.severity_rationale}</p>
                              </details>
                            )}
                        </section>
                        {selectedIssue.code_context === null
                          ? (
                            <div class="code-security-code-unavailable">
                              {t("codeSecurity.issues.codeUnavailable")}
                            </div>
                          )
                          : (
                            <section
                              class="code-security-code-context"
                              aria-label={t("codeSecurity.issues.codeContext")}
                            >
                              <header>
                                <strong>{t("codeSecurity.issues.codeContext")}</strong>
                                {selectedIssue.code_context.redacted
                                  ? <span>{t("codeSecurity.issues.secretRedacted")}</span>
                                  : null}
                              </header>
                              <pre>
                                {selectedIssue.code_context.lines.map((line) => (
                                  <span
                                    key={line.number}
                                    class={
                                      line.number >= selectedIssue.code_context!.highlight_start
                                      && line.number <= selectedIssue.code_context!.highlight_end
                                        ? "highlight"
                                        : ""
                                    }
                                  >
                                    <b>{line.number}</b>
                                    <code>{line.text || " "}</code>
                                  </span>
                                ))}
                              </pre>
                            </section>
                          )}
                        {selectedIssue.flow_steps.length > 1
                          ? (
                            <section
                              class="code-security-flow"
                              aria-label={t("codeSecurity.issues.flowTitle")}
                            >
                              <strong>{t("codeSecurity.issues.flowTitle")}</strong>
                              <ol>
                                {selectedIssue.flow_steps.map((step, index) => (
                                  <li key={`${step.kind}:${step.path}:${step.line ?? 0}:${index}`}>
                                    <span>{t(`codeSecurity.issues.flow.${step.kind}`)}</span>
                                    <div class="code-security-flow-target">
                                      <code>
                                        {step.line === null
                                          ? step.path
                                          : step.end_line !== null && step.end_line !== step.line
                                          ? `${step.path}:${step.line}-${step.end_line}`
                                          : `${step.path}:${step.line}`}
                                      </code>
                                      {step.call_context.length === 0
                                        ? null
                                        : (
                                          <small>
                                            {t("codeSecurity.issues.callContext", {
                                              context: step.call_context.join(" / "),
                                            })}
                                          </small>
                                        )}
                                    </div>
                                  </li>
                                ))}
                              </ol>
                              {selectedIssue.analysis_evidence === null
                                ? null
                                : (
                                  <details class="code-security-analysis-evidence">
                                    <summary>{t("codeSecurity.issues.analysisEvidence")}</summary>
                                    <dl>
                                      <div><dt>{t("codeSecurity.issues.pathId")}</dt><dd class="mono">{selectedIssue.analysis_evidence.path_id}</dd></div>
                                      <div><dt>{t("codeSecurity.issues.graphDigest")}</dt><dd class="mono">{selectedIssue.analysis_evidence.graph_digest}</dd></div>
                                      <div><dt>{t("codeSecurity.issues.schemas")}</dt><dd>{selectedIssue.analysis_evidence.graph_schema_version} / {selectedIssue.analysis_evidence.path_schema_version}</dd></div>
                                      <div><dt>{t("codeSecurity.issues.ruleVersion")}</dt><dd>{selectedIssue.analysis_evidence.rule_version}</dd></div>
                                      <div><dt>{t("codeSecurity.issues.frontends")}</dt><dd>{Object.entries(selectedIssue.analysis_evidence.frontend_versions).map(([name, version]) => `${name} ${version}`).join(", ")}</dd></div>
                                      <div><dt>{t("codeSecurity.issues.coverageGaps")}</dt><dd>{selectedIssue.analysis_evidence.coverage_limits.length === 0 ? t("codeSecurity.issues.noCoverageGaps") : selectedIssue.analysis_evidence.coverage_limits.join(", ")}</dd></div>
                                    </dl>
                                  </details>
                                )}
                            </section>
                          )
                          : null}
                        <dl>
                          <div><dt>{t("codeSecurity.issues.column.issue")}</dt><dd class="mono">{selectedIssue.issue_id}</dd></div>
                          <div><dt>{t("codeSecurity.issues.column.confidence")}</dt><dd>{selectedIssue.confidence}</dd></div>
                          <div><dt>{t("codeSecurity.issues.column.weaknessClass")}</dt><dd>{selectedIssue.weakness_class}</dd></div>
                          <div><dt>{t("codeSecurity.issues.column.reference")}</dt><dd class="mono">{issueReference(selectedIssue)}</dd></div>
                          <div><dt>{t("codeSecurity.issues.column.producers")}</dt><dd>{selectedIssue.producers.join(", ")}</dd></div>
                          <div><dt>{t("codeSecurity.issues.due")}</dt><dd>{t("codeSecurity.issues.dueDays", { count: selectedIssue.due_days })}</dd></div>
                        </dl>
                        <div class="row" style="gap: 8px; flex-wrap: wrap; margin-top: 8px;">
                          <a class="btn subtle" href={`${routeHref("rules")}?view=controls&framework=msrc-csaf`}>
                            {t("codeSecurity.issues.viewInMsrcCsaf")}
                          </a>
                          <a class="btn subtle" href={`${routeHref("rules")}?view=controls&framework=azure-mcsb`}>
                            {t("codeSecurity.issues.viewInMcsb")}
                          </a>
                        </div>
                      </article>
                    )}
                </div>
              )}
            {data.artifacts === null
              ? null
              : (
                <section class="code-security-report-viewer" aria-label={t("codeSecurity.issues.reportTitle")}>
                  {data.artifacts.mode === "summary"
                    ? <p class="muted">{t("codeSecurity.issues.summaryArtifact")}</p>
                    : null}
                  <div class="code-security-report-actions">
                    <button type="button" class="btn subtle" onClick={() => setReportView("html")}>
                      {t("codeSecurity.issues.viewHtml")}
                    </button>
                    <button type="button" class="btn subtle" onClick={() => setReportView("sarif")}>
                      {t("codeSecurity.issues.viewSarif")}
                    </button>
                    <button
                      type="button"
                      class="btn subtle"
                      onClick={() =>
                        downloadArtifact(
                          `${repositoryAlias}-${revision.slice(0, 12)}.html`,
                          data.artifacts!.html,
                          "text/html;charset=utf-8",
                        )}
                    >
                      {t("codeSecurity.issues.downloadHtml")}
                    </button>
                    <button
                      type="button"
                      class="btn subtle"
                      onClick={() =>
                        downloadArtifact(
                          `${repositoryAlias}-${revision.slice(0, 12)}.sarif`,
                          data.artifacts!.sarif,
                          "application/sarif+json;charset=utf-8",
                        )}
                    >
                      {t("codeSecurity.issues.downloadSarif")}
                    </button>
                    {reportView === null
                      ? null
                      : (
                        <button type="button" class="btn subtle" onClick={() => setReportView(null)}>
                          {t("codeSecurity.issues.hideReport")}
                        </button>
                      )}
                  </div>
                  {reportView === "html"
                    ? (
                      <iframe
                        class="code-security-report-frame"
                        title={t("codeSecurity.issues.htmlTitle")}
                        sandbox=""
                        srcDoc={data.artifacts.html}
                      />
                    )
                    : reportView === "sarif"
                      ? (
                        <pre class="code-security-sarif" aria-label={t("codeSecurity.issues.sarifTitle")}>
                          {data.artifacts.sarif}
                        </pre>
                      )
                      : null}
                </section>
              )}
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
