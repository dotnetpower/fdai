import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable } from "../api";
import type { OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  ExternalLink,
  StatusPill,
  type AsyncState,
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
    readonly kind: "source" | "sink";
    readonly path: string;
    readonly line: number | null;
  }[];
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
    ScorecardKey | "potential_critical" | "potential_high" | "potential_medium" | "potential_low",
    number
  >>;
  readonly gaps: readonly (typeof GAPS)[number][];
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
        : panelArray(row.flow_steps, `${label}.flow_steps`).map((step, stepIndex) => {
          const value = panelRecord(step, `${label}.flow_steps ${stepIndex}`);
          const line = value.line;
          if (
            line !== null
            && (typeof line !== "number" || !Number.isInteger(line) || line <= 0)
          ) {
            throw panelContractError(`${label}.flow_steps line must be positive or null`);
          }
          return {
            kind: oneOf(value.kind, ["source", "sink"] as const, `${label}.flow_steps.kind`),
            path: panelNonEmptyString(value, "path", `${label}.flow_steps`),
            line,
          };
        });
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
      };
    }),
    artifacts,
    scorecard: (() => {
      const scorecard = panelRecord(root.scorecard, "code-security issues.scorecard");
      return Object.fromEntries(
        [...SCORECARD_KEYS, "potential_critical", "potential_high", "potential_medium", "potential_low"]
          .map((key) => [key, panelNonNegativeInteger(scorecard, key, "code-security issues.scorecard")]),
      ) as CodeSecurityIssuesResponse["scorecard"];
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

export function ReviewIssuesPanel({
  client,
  repositoryAlias,
  repositoryLocation,
  revision,
  onClose,
}: {
  readonly client: Pick<OperatorApiClient, "panel">;
  readonly repositoryAlias: string;
  readonly repositoryLocation: string | null;
  readonly revision: string;
  readonly onClose: () => void;
}) {
  const [state, setState] = useState<AsyncState<CodeSecurityIssuesResponse>>({ status: "loading" });
  const [selectedIssue, setSelectedIssue] = useState<CodeSecurityIssueSummary | null>(null);
  const [reportView, setReportView] = useState<"html" | "sarif" | null>(null);
  const [scorecardFilter, setScorecardFilter] = useState<ScorecardKey | "all">("all");
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
  const visibleIssues = state.status === "ready"
    ? state.data.issues.filter((issue) => scorecardMatches(issue, scorecardFilter))
    : [];
  useEffect(() => {
    if (
      state.status === "ready"
      && (
        selectedIssue === null
        || !visibleIssues.some((issue) => issue.issue_id === selectedIssue.issue_id)
      )
    ) {
      setSelectedIssue(visibleIssues[0] ?? null);
    }
  }, [scorecardFilter, selectedIssue, state, visibleIssues]);
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
            <div class="code-security-scorecard" role="group" aria-label={t("codeSecurity.issues.scorecard")}>
              {SCORECARD_KEYS.map((key) => (
                <button
                  key={key}
                  type="button"
                  class={scorecardFilter === key ? "active" : ""}
                  aria-pressed={scorecardFilter === key}
                  onClick={() => setScorecardFilter(scorecardFilter === key ? "all" : key)}
                >
                  <span>{t(`codeSecurity.issues.score.${key}`)}</span>
                  <strong>{data.scorecard[key]}</strong>
                  {key === "needs_review" && data.scorecard.potential_critical > 0
                    ? (
                      <small>
                        {t("codeSecurity.issues.potentialCritical", {
                          count: data.scorecard.potential_critical,
                        })}
                      </small>
                    )
                    : null}
                </button>
              ))}
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
                    {visibleIssues.map((issue) => (
                      <button
                        key={issue.issue_id}
                        type="button"
                        aria-current={selectedIssue?.issue_id === issue.issue_id ? "true" : undefined}
                        onClick={() => setSelectedIssue(issue)}
                      >
                        <span>
                          <strong>{issue.title ?? issue.weakness_class.replaceAll("_", " ")}</strong>
                          <StatusPill kind={severityKind(issue.severity)} label={severityLabel(issue)} />
                        </span>
                        <span class="mono">{issueLocation(issue)}</span>
                        <small>{`${issue.priority} · ${issue.confidence} · ${issue.issue_id}`}</small>
                      </button>
                    ))}
                  </nav>
                  {selectedIssue === null
                    ? null
                    : (
                      <article class="code-security-finding-detail" aria-label={t("codeSecurity.issues.detailTitle")}>
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
                        {selectedIssue.severity_rationale === null
                          ? null
                          : (
                            <div class="code-security-severity-reason">
                              <strong>{t("codeSecurity.issues.severityReason")}</strong>
                              <p>{selectedIssue.severity_rationale}</p>
                              {selectedIssue.deciding_facts.length === 0
                                ? null
                                : (
                                  <p>
                                    {`${t("codeSecurity.issues.decidingFacts")}: ${
                                      selectedIssue.deciding_facts.join(", ")
                                    }`}
                                  </p>
                                )}
                            </div>
                          )}
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
                                    <code>
                                      {step.line === null
                                        ? step.path
                                        : `${step.path}:${step.line}`}
                                    </code>
                                  </li>
                                ))}
                              </ol>
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
