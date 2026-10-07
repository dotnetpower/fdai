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
import { usePublishViewContext, type ViewSnapshot } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { t } from "./i18n/assurance-twin";
import { currentRoute, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

const SEVERITIES = ["low", "medium", "high", "critical"] as const;
type Severity = (typeof SEVERITIES)[number];
const VERDICTS = ["clear", "needs_review", "blocked"] as const;
type Verdict = (typeof VERDICTS)[number];
const MODES = ["shadow", "enforce"] as const;
type TwinMode = (typeof MODES)[number];
const FRESHNESS_STATES = ["fresh", "stale", "unavailable", "unknown"] as const;
type Freshness = (typeof FRESHNESS_STATES)[number];

export interface AssuranceTwinProvenance {
  readonly activity_id: string | null;
  readonly correlation_id: string | null;
  readonly evidence_digest: string | null;
  readonly evidence_source_revision: string | null;
}

export interface AssuranceTwinEvidenceGap {
  readonly identity: string | null;
  readonly freshness: Freshness | null;
  readonly reason_code: string;
  readonly reason_codes: readonly string[];
}

export interface AssuranceTwinFinding {
  readonly rule_id: string;
  readonly resource_type: string;
  readonly resource_ref: string;
  readonly severity: Severity;
  readonly reason: string;
  readonly evidence_refs: readonly string[];
}

export interface AssuranceTwinPostureReport extends AssuranceTwinProvenance {
  readonly scope: string;
  readonly generated_at: string;
  readonly mode: TwinMode;
  readonly verdict: Verdict;
  readonly blocks_action: boolean;
  readonly resource_count: number;
  readonly rule_count: number;
  readonly highest_severity: Severity | null;
  readonly severity_counts: Readonly<Record<Severity, number>>;
  readonly finding_count: number;
  readonly findings: readonly AssuranceTwinFinding[];
  readonly freshness: Freshness;
  readonly reason_codes: readonly string[];
}

export interface AssuranceTwinReviewSummary extends AssuranceTwinProvenance {
  readonly review_key: string;
  readonly pr_ref: string;
  readonly generated_at: string;
  readonly mode: TwinMode;
  readonly verdict: Verdict;
  readonly finding_count: number;
  readonly freshness: Freshness;
  readonly reason_codes: readonly string[];
}

export interface AssuranceTwinReviewDetail extends AssuranceTwinReviewSummary {
  readonly findings: readonly AssuranceTwinFinding[];
}

export interface AssuranceTwinReviewDetailState {
  readonly available: boolean;
  readonly review: AssuranceTwinReviewDetail | null;
  readonly gap: AssuranceTwinEvidenceGap | null;
}

export interface AssuranceTwinResponse {
  readonly posture: {
    readonly available: boolean;
    readonly complete: boolean;
    readonly reports: readonly AssuranceTwinPostureReport[];
    readonly gaps: readonly AssuranceTwinEvidenceGap[];
  };
  readonly reviews: {
    readonly available: boolean;
    readonly complete: boolean;
    readonly reviews: readonly AssuranceTwinReviewSummary[];
    readonly gaps: readonly AssuranceTwinEvidenceGap[];
  };
}

/** Build a drill-down href that preserves the review key byte for byte.

Review keys are opaque twin identity: mixed case, underscores, and a `/`
(as in `owner/repo#12`) are all meaningful. They therefore travel as an
exact query value rather than a path segment, so neither the slugifying
`routeHref` segment builder nor a path router can split or canonicalise
them. */
export function assuranceTwinReviewHref(reviewKey: string): string {
  return routeHref("assurance-twin", { params: { review: reviewKey } });
}

/** Read the exact review identity carried by the current route, if any. */
export function assuranceTwinReviewIdFromSearch(search: URLSearchParams): string | null {
  const value = search.get("review");
  return value === null || value === "" ? null : value;
}

export function buildAssuranceTwinViewSnapshot(data: AssuranceTwinResponse): ViewSnapshot {
  const verdictCounts = {
    clear: data.posture.reports.filter((report) => report.verdict === "clear").length,
    needs_review: data.posture.reports.filter((report) => report.verdict === "needs_review").length,
    blocked: data.posture.reports.filter((report) => report.verdict === "blocked").length,
  };
  return {
    routeId: "assurance-twin",
    routeLabel: t("route.assuranceTwin"),
    purpose: t("assuranceTwin.readOnlyBody"),
    glossary: composeGlossary([], [
      {
        term: t("route.assuranceTwin"),
        plain: t("assuranceTwin.subtitle"),
        tech: "PostureAssessmentReport",
      },
    ]),
    headline: data.posture.reports.length > 0
      ? `${t("assuranceTwin.postureReports")}: ${data.posture.reports.length}; `
        + `${t("assuranceTwin.reviews")}: ${data.reviews.reviews.length}`
      : t("assuranceTwin.unavailable"),
    capturedAt: new Date().toISOString(),
    facts: data.posture.reports.length > 0
      ? [
        { key: "posture_report_count", label: t("assuranceTwin.postureReports"), value: data.posture.reports.length },
        { key: "blocked_count", label: t("assuranceTwin.verdictValue.blocked"), value: verdictCounts.blocked },
        { key: "needs_review_count", label: t("assuranceTwin.verdictValue.needs_review"), value: verdictCounts.needs_review },
        { key: "clear_count", label: t("assuranceTwin.verdictValue.clear"), value: verdictCounts.clear },
      ]
      : [],
    records: {
      reviews: data.reviews.reviews.map((row) => ({
        review_key: row.review_key,
        pr_ref: row.pr_ref,
        verdict: row.verdict,
        finding_count: row.finding_count,
        generated_at: row.generated_at,
      })),
    },
  };
}

const PROVENANCE_KEYS = ["activity_id", "correlation_id", "evidence_digest", "evidence_source_revision"] as const;
const POSTURE_ROOT_KEYS = new Set(["surface", "available", "complete", "source", "reports", "gaps"]);
const REPORT_KEYS = new Set([
  "scope",
  "generated_at",
  "mode",
  "verdict",
  "blocks_action",
  "resource_count",
  "rule_count",
  "highest_severity",
  "severity_counts",
  "finding_count",
  "findings",
  "freshness",
  "reason_codes",
  ...PROVENANCE_KEYS,
]);
const REVIEWS_ROOT_KEYS = new Set(["surface", "available", "complete", "source", "reviews", "gaps"]);
const DETAIL_ROOT_KEYS = new Set(["surface", "source", "available", "review", "gap"]);
const GAP_KEYS = new Set(["identity", "freshness", "reason_code", "reason_codes"]);
const REVIEW_SUMMARY_KEYS = new Set([
  "review_key",
  "pr_ref",
  "generated_at",
  "mode",
  "verdict",
  "finding_count",
  "freshness",
  "reason_codes",
  ...PROVENANCE_KEYS,
]);
const FINDING_KEYS = new Set([
  "rule_id",
  "resource_type",
  "resource_ref",
  "severity",
  "reason",
  "evidence_refs",
]);

export function AssuranceTwinRoute({ client }: { readonly client: OperatorApiClient }) {
  const reviewId = assuranceTwinReviewIdFromSearch(currentRoute().search);
  const [state, setState] = useState<AsyncState<AssuranceTwinResponse>>({ status: "loading" });
  const [detailState, setDetailState] = useState<AsyncState<AssuranceTwinReviewDetailState> | null>(null);

  useEffect(() => {
    let cancelled = false;
    void loadAssuranceTwinState(client).then((next) => {
      if (!cancelled) setState(next);
    });
    return () => { cancelled = true; };
  }, [client]);

  useEffect(() => {
    if (reviewId === null) {
      setDetailState(null);
      return;
    }
    let cancelled = false;
    setDetailState({ status: "loading" });
    void loadAssuranceTwinReviewDetail(client, reviewId).then((next) => {
      if (!cancelled) setDetailState(next);
    });
    return () => { cancelled = true; };
  }, [client, reviewId]);

  return (
    <div class="stack evidence-route">
      <PageHeader title={t("route.assuranceTwin")} subtitle={t("assuranceTwin.subtitle")} />
      {reviewId === null
        ? (
          <AsyncBoundary state={state} resourceLabel={t("assuranceTwin.resourceLabel")}>
            {(data) => <AssuranceTwinBody data={data} />}
          </AsyncBoundary>
        )
        : (
          <AsyncBoundary
            state={detailState ?? { status: "loading" }}
            resourceLabel={t("assuranceTwin.reviewDetailResourceLabel")}
          >
            {(detail) => <AssuranceTwinReviewDetailBody state={detail} />}
          </AsyncBoundary>
        )}
    </div>
  );
}

export async function loadAssuranceTwinState(
  client: Pick<OperatorApiClient, "panel">,
): Promise<AsyncState<AssuranceTwinResponse>> {
  try {
    const [posture, reviews] = await Promise.all([
      client.panel<unknown>("/assurance-twin/posture"),
      client.panel<unknown>("/assurance-twin/reviews"),
    ]);
    return {
      status: "ready",
      data: {
        posture: decodeAssuranceTwinPosture(posture),
        reviews: decodeAssuranceTwinReviews(reviews),
      },
    };
  } catch (error) {
    if (isOptionalOperatorApiUnavailable(error)) {
      return { status: "unavailable", message: t("assuranceTwin.unavailable") };
    }
    return { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

export async function loadAssuranceTwinReviewDetail(
  client: Pick<OperatorApiClient, "panel">,
  reviewId: string,
): Promise<AsyncState<AssuranceTwinReviewDetailState>> {
  try {
    const payload = await client.panel<unknown>(
      "/assurance-twin/review",
      { review_key: reviewId },
    );
    return { status: "ready", data: decodeAssuranceTwinReviewDetail(payload) };
  } catch (error) {
    if (isOptionalOperatorApiUnavailable(error)) {
      return { status: "unavailable", message: t("assuranceTwin.unavailable") };
    }
    return { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

function decodeAssuranceTwinPosture(value: unknown): AssuranceTwinResponse["posture"] {
  const root = panelRecord(value, "assurance twin posture");
  requireExactKeys(root, POSTURE_ROOT_KEYS, "assurance twin posture");
  const available = panelBoolean(root, "available", "assurance twin posture");
  const complete = panelBoolean(root, "complete", "assurance twin posture");
  const rawReports = panelArray(root["reports"], "assurance twin posture.reports");
  const reports = rawReports.map((item, index) => decodeReport(item, index));
  const gaps = decodeGaps(root["gaps"], "assurance twin posture.gaps");
  if (available !== reports.length > 0 || complete !== (gaps.length === 0)) {
    throw new OperatorApiError(502, "invalid Operator API response: assurance twin posture availability is inconsistent");
  }
  return { available, complete, reports, gaps };
}

function decodeAssuranceTwinReviews(value: unknown): AssuranceTwinResponse["reviews"] {
  const root = panelRecord(value, "assurance twin reviews");
  requireExactKeys(root, REVIEWS_ROOT_KEYS, "assurance twin reviews");
  const available = panelBoolean(root, "available", "assurance twin reviews");
  const complete = panelBoolean(root, "complete", "assurance twin reviews");
  const rawReviews = panelArray(root["reviews"], "assurance twin reviews.reviews");
  const reviews = rawReviews.map((item, index) => decodeReviewSummary(item, index));
  const gaps = decodeGaps(root["gaps"], "assurance twin reviews.gaps");
  if (available !== reviews.length > 0 || complete !== (gaps.length === 0)) {
    throw new OperatorApiError(502, "invalid Operator API response: assurance twin review availability is inconsistent");
  }
  return { available, complete, reviews, gaps };
}

function decodeAssuranceTwinReviewDetail(value: unknown): AssuranceTwinReviewDetailState {
  const root = panelRecord(value, "assurance twin review detail");
  requireExactKeys(root, DETAIL_ROOT_KEYS, "assurance twin review detail");
  const available = panelBoolean(root, "available", "assurance twin review detail");
  const rawReview = root["review"];
  const rawGap = root["gap"];
  if (!available) {
    if (rawReview !== null) {
      throw new OperatorApiError(502, "invalid Operator API response: unavailable assurance twin detail MUST NOT carry a review");
    }
    return { available, review: null, gap: decodeGap(rawGap, "assurance twin review detail.gap") };
  }
  if (rawGap !== null) {
    throw new OperatorApiError(502, "invalid Operator API response: available assurance twin detail MUST NOT carry a gap");
  }
  const row = panelRecord(rawReview, "assurance twin review detail.review");
  const { findings: rawFindingsValue, ...summaryRow } = row;
  const summary = decodeReviewSummary(summaryRow, 0);
  const rawFindings = panelArray(rawFindingsValue, "assurance twin review detail.findings");
  const findings = rawFindings.map((item, index) => decodeFinding(item, index));
  if (summary.finding_count !== findings.length) {
    throw new OperatorApiError(502, "invalid Operator API response: assurance twin finding_count MUST match findings");
  }
  return { available, review: { ...summary, findings }, gap: null };
}

function decodeGaps(value: unknown, label: string): readonly AssuranceTwinEvidenceGap[] {
  return panelArray(value, label).map((item) => decodeGap(item, label));
}

function decodeGap(value: unknown, label: string): AssuranceTwinEvidenceGap {
  const row = panelRecord(value, label);
  requireExactKeys(row, GAP_KEYS, label);
  return {
    identity: panelNullableString(row, "identity", label),
    freshness: nullableEnum(row, "freshness", FRESHNESS_STATES, label),
    reason_code: panelNonEmptyString(row, "reason_code", label),
    reason_codes: panelStringArray(row["reason_codes"], `${label}.reason_codes`),
  };
}

function decodeProvenance(
  row: Readonly<Record<string, unknown>>,
  label: string,
): AssuranceTwinProvenance {
  return {
    activity_id: panelNullableString(row, "activity_id", label),
    correlation_id: panelNullableString(row, "correlation_id", label),
    evidence_digest: panelNullableString(row, "evidence_digest", label),
    evidence_source_revision: panelNullableString(row, "evidence_source_revision", label),
  };
}

function decodeReport(value: unknown, index: number): AssuranceTwinPostureReport {
  const row = panelRecord(value, `assurance twin posture.reports[${index}]`);
  requireExactKeys(row, REPORT_KEYS, `assurance twin posture.reports[${index}]`);
  const rawFindings = panelArray(row["findings"], "assurance twin posture report.findings");
  const findings = rawFindings.map((item, i) => decodeFinding(item, i));
  const findingCount = panelNonNegativeInteger(row, "finding_count", "assurance twin posture report");
  if (findingCount !== findings.length) {
    throw new OperatorApiError(502, "invalid Operator API response: assurance twin finding_count MUST match findings");
  }
  return {
    ...decodeProvenance(row, "assurance twin posture report"),
    scope: panelNonEmptyString(row, "scope", "assurance twin posture report"),
    generated_at: panelNonEmptyString(row, "generated_at", "assurance twin posture report"),
    mode: enumValue(row, "mode", MODES, "assurance twin posture report"),
    verdict: enumValue(row, "verdict", VERDICTS, "assurance twin posture report"),
    blocks_action: panelBoolean(row, "blocks_action", "assurance twin posture report"),
    resource_count: panelNonNegativeInteger(row, "resource_count", "assurance twin posture report"),
    rule_count: panelNonNegativeInteger(row, "rule_count", "assurance twin posture report"),
    highest_severity: nullableEnum(row, "highest_severity", SEVERITIES, "assurance twin posture report"),
    severity_counts: severityCounts(row["severity_counts"]),
    finding_count: findingCount,
    findings,
    freshness: enumValue(row, "freshness", FRESHNESS_STATES, "assurance twin posture report"),
    reason_codes: panelStringArray(row["reason_codes"], "assurance twin posture report.reason_codes"),
  };
}

function decodeReviewSummary(value: unknown, index: number): AssuranceTwinReviewSummary {
  const row = panelRecord(value, `assurance twin reviews[${index}]`);
  requireExactKeys(row, REVIEW_SUMMARY_KEYS, `assurance twin reviews[${index}]`);
  return {
    ...decodeProvenance(row, "assurance twin review"),
    review_key: panelNonEmptyString(row, "review_key", "assurance twin review"),
    pr_ref: panelNonEmptyString(row, "pr_ref", "assurance twin review"),
    generated_at: panelNonEmptyString(row, "generated_at", "assurance twin review"),
    mode: enumValue(row, "mode", MODES, "assurance twin review"),
    verdict: enumValue(row, "verdict", VERDICTS, "assurance twin review"),
    finding_count: panelNonNegativeInteger(row, "finding_count", "assurance twin review"),
    freshness: enumValue(row, "freshness", FRESHNESS_STATES, "assurance twin review"),
    reason_codes: panelStringArray(row["reason_codes"], "assurance twin review.reason_codes"),
  };
}

function decodeFinding(value: unknown, index: number): AssuranceTwinFinding {
  const row = panelRecord(value, `assurance twin finding[${index}]`);
  requireExactKeys(row, FINDING_KEYS, `assurance twin finding[${index}]`);
  return {
    rule_id: panelNonEmptyString(row, "rule_id", "assurance twin finding"),
    resource_type: panelNonEmptyString(row, "resource_type", "assurance twin finding"),
    resource_ref: panelNonEmptyString(row, "resource_ref", "assurance twin finding"),
    severity: enumValue(row, "severity", SEVERITIES, "assurance twin finding"),
    reason: panelNonEmptyString(row, "reason", "assurance twin finding"),
    evidence_refs: panelStringArray(row["evidence_refs"], "assurance twin finding.evidence_refs"),
  };
}

function severityCounts(value: unknown): Readonly<Record<Severity, number>> {
  const row = panelRecord(value, "assurance twin severity_counts");
  const counts = {} as Record<Severity, number>;
  for (const severity of SEVERITIES) {
    counts[severity] = panelNonNegativeInteger(row, severity, "assurance twin severity_counts");
  }
  return counts;
}

function enumValue<T extends string>(
  row: Readonly<Record<string, unknown>>,
  key: string,
  allowed: readonly T[],
  label: string,
): T {
  const raw = panelNonEmptyString(row, key, label);
  if (!(allowed as readonly string[]).includes(raw)) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label}.${key} is invalid`);
  }
  return raw as T;
}

function nullableEnum<T extends string>(
  row: Readonly<Record<string, unknown>>,
  key: string,
  allowed: readonly T[],
  label: string,
): T | null {
  const raw = panelNullableString(row, key, label);
  if (raw === null) return null;
  if (!(allowed as readonly string[]).includes(raw)) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label}.${key} is invalid`);
  }
  return raw as T;
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

function verdictTone(verdict: Verdict): "positive" | "warning" | "danger" {
  if (verdict === "clear") return "positive";
  if (verdict === "needs_review") return "warning";
  return "danger";
}

function verdictStatusKind(verdict: Verdict): "success" | "warning" | "danger" {
  if (verdict === "clear") return "success";
  if (verdict === "needs_review") return "warning";
  return "danger";
}

function freshnessStatusKind(freshness: Freshness): "success" | "warning" | "danger" | "neutral" {
  if (freshness === "fresh") return "success";
  if (freshness === "stale") return "warning";
  if (freshness === "unavailable") return "danger";
  return "neutral";
}

function EvidenceGaps({ reasonCodes }: { readonly reasonCodes: readonly string[] }) {
  if (reasonCodes.length === 0) return null;
  return (
    <div class="assurance-twin-gaps">
      <strong>{t("assuranceTwin.evidenceGaps")}</strong>
      <ul>
        {reasonCodes.map((code) => (
          <li key={code}><span class="mono">{code}</span></li>
        ))}
      </ul>
    </div>
  );
}

function WithheldEvidence(
  { gaps, heading }: {
    readonly gaps: readonly AssuranceTwinEvidenceGap[];
    readonly heading: string;
  },
) {
  if (gaps.length === 0) return null;
  return (
    <div class="assurance-twin-gaps" role="status">
      <strong>{heading}</strong>
      <ul>
        {gaps.map((gap, index) => (
          <li key={`${gap.identity ?? "unknown"}:${gap.reason_code}:${index}`}>
            <span class="mono">{gap.identity ?? t("assuranceTwin.gap.unknownIdentity")}</span>
            {" - "}
            <span>{t(`assuranceTwin.gap.${gap.reason_code}`)}</span>
            {gap.freshness === null ? null : (
              <>
                {" "}
                <StatusPill
                  kind={freshnessStatusKind(gap.freshness)}
                  label={t(`assuranceTwin.freshnessValue.${gap.freshness}`)}
                />
              </>
            )}
            {gap.reason_codes.length === 0 ? null : (
              <span class="mono">{` (${gap.reason_codes.join(", ")})`}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function EvidenceProvenance({ record }: { readonly record: AssuranceTwinProvenance }) {
  if (record.evidence_digest === null && record.activity_id === null) return null;
  return (
    <dl class="assurance-twin-provenance">
      <dt>{t("assuranceTwin.provenance.activity")}</dt>
      <dd class="mono">{record.activity_id ?? t("assuranceTwin.gap.unknownIdentity")}</dd>
      <dt>{t("assuranceTwin.provenance.correlation")}</dt>
      <dd class="mono">{record.correlation_id ?? t("assuranceTwin.gap.unknownIdentity")}</dd>
      <dt>{t("assuranceTwin.provenance.evidenceDigest")}</dt>
      <dd class="mono">{record.evidence_digest ?? t("assuranceTwin.gap.unknownIdentity")}</dd>
      <dt>{t("assuranceTwin.provenance.sourceRevision")}</dt>
      <dd class="mono">{record.evidence_source_revision ?? t("assuranceTwin.gap.unknownIdentity")}</dd>
    </dl>
  );
}

function AssuranceTwinBody({ data }: { readonly data: AssuranceTwinResponse }) {
  usePublishViewContext(() => buildAssuranceTwinViewSnapshot(data), [data]);
  const reviewsHref = `${routeHref("assurance-twin")}#assurance-twin-reviews`;
  const columns: readonly Column<AssuranceTwinReviewSummary>[] = [
    {
      key: "pr_ref",
      header: t("assuranceTwin.column.change"),
      render: (row) => (
        <a class="mono assurance-twin-review-link" href={assuranceTwinReviewHref(row.review_key)}>
          {row.pr_ref}
        </a>
      ),
    },
    {
      key: "verdict",
      header: t("assuranceTwin.column.verdict"),
      render: (row) => (
        <StatusPill
          kind={verdictStatusKind(row.verdict)}
          label={t(`assuranceTwin.verdictValue.${row.verdict}`)}
        />
      ),
    },
    {
      key: "mode",
      header: t("assuranceTwin.column.mode"),
      render: (row) => <StatusPill kind={row.mode === "enforce" ? "enforce" : "shadow"} label={t(`assuranceTwin.mode.${row.mode}`)} />,
    },
    {
      key: "findings",
      header: t("assuranceTwin.column.findings"),
      render: (row) => row.finding_count,
    },
    {
      key: "freshness",
      header: t("assuranceTwin.column.freshness"),
      render: (row) => (
        <StatusPill
          kind={freshnessStatusKind(row.freshness)}
          label={t(`assuranceTwin.freshnessValue.${row.freshness}`)}
        />
      ),
    },
    {
      key: "generated_at",
      header: t("assuranceTwin.column.generatedAt"),
      render: (row) => formatConsoleTimestamp(row.generated_at),
    },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("assuranceTwin.readOnlyTitle")}</strong>
        <span>{t("assuranceTwin.readOnlyBody")}</span>
      </div>
      {data.posture.reports.length > 0
        ? data.posture.reports.map((report) => (
          <section class="stack" key={report.scope}>
            <h2>
              {t("assuranceTwin.scope")}: <span class="mono">{report.scope}</span>
            </h2>
            <KpiGrid>
              <KpiCard
                href={reviewsHref}
                label={t("assuranceTwin.verdict")}
                value={t(`assuranceTwin.verdictValue.${report.verdict}`)}
                tone={verdictTone(report.verdict)}
              />
              <KpiCard href={reviewsHref} label={t("assuranceTwin.resourceCount")} value={report.resource_count} />
              <KpiCard href={reviewsHref} label={t("assuranceTwin.ruleCount")} value={report.rule_count} />
              <KpiCard
                href={reviewsHref}
                label={t("assuranceTwin.highestSeverity")}
                value={report.highest_severity ? t(`assuranceTwin.severityValue.${report.highest_severity}`) : t("assuranceTwin.noFindings")}
                tone={report.highest_severity === "critical" || report.highest_severity === "high" ? "danger" : "default"}
              />
              <KpiCard
                href={reviewsHref}
                label={t("assuranceTwin.freshness")}
                value={t(`assuranceTwin.freshnessValue.${report.freshness}`)}
                evidenceState={report.freshness === "unavailable" ? "not-connected" : "measured"}
                tone={report.freshness === "unavailable" ? "danger" : "default"}
              />
            </KpiGrid>
            <EvidenceGaps reasonCodes={report.reason_codes} />
            <EvidenceProvenance record={report} />
          </section>
        ))
        : (
          <div class="muted">
            {t(data.posture.gaps.length > 0
              ? "assuranceTwin.unavailable"
              : "assuranceTwin.noPostureReport")}
          </div>
        )}
      <WithheldEvidence gaps={data.posture.gaps} heading={t("assuranceTwin.postureWithheld")} />
      <div id="assurance-twin-reviews">
        <h2>{t("assuranceTwin.reviews")}</h2>
        <DataTable
          columns={columns}
          rows={data.reviews.reviews}
          keyOf={(row) => row.review_key}
          empty={t(data.reviews.gaps.length > 0
            ? "assuranceTwin.reviewsUnavailable"
            : "assuranceTwin.reviewsEmpty")}
        />
        <WithheldEvidence gaps={data.reviews.gaps} heading={t("assuranceTwin.reviewsWithheld")} />
      </div>
    </div>
  );
}

function AssuranceTwinReviewDetailBody(
  { state }: { readonly state: AssuranceTwinReviewDetailState },
) {
  const detail = state.review;
  const columns: readonly Column<AssuranceTwinFinding>[] = [
    { key: "rule", header: t("assuranceTwin.column.rule"), render: (row) => <span class="mono">{row.rule_id}</span> },
    { key: "resource", header: t("assuranceTwin.column.resource"), render: (row) => `${row.resource_type} / ${row.resource_ref}` },
    {
      key: "severity",
      header: t("assuranceTwin.column.severity"),
      render: (row) => <StatusPill kind={row.severity === "critical" || row.severity === "high" ? "danger" : "warning"} label={t(`assuranceTwin.severityValue.${row.severity}`)} />,
    },
    { key: "reason", header: t("assuranceTwin.column.reason"), render: (row) => row.reason },
  ];
  if (detail === null) {
    return (
      <div class="stack">
        <a class="assurance-twin-back-link" href={routeHref("assurance-twin")}>
          {t("assuranceTwin.backToReviews")}
        </a>
        <WithheldEvidence
          gaps={state.gap === null ? [] : [state.gap]}
          heading={t("assuranceTwin.reviewDetailWithheld")}
        />
        <div class="muted">{t("assuranceTwin.reviewDetailUnavailable")}</div>
      </div>
    );
  }
  return (
    <div class="stack">
      <a class="assurance-twin-back-link" href={routeHref("assurance-twin")}>
        {t("assuranceTwin.backToReviews")}
      </a>
      <KpiGrid>
        <KpiCard
          href={assuranceTwinReviewHref(detail.review_key)}
          label={t("assuranceTwin.verdict")}
          value={t(`assuranceTwin.verdictValue.${detail.verdict}`)}
          tone={verdictTone(detail.verdict)}
        />
        <KpiCard
          href={assuranceTwinReviewHref(detail.review_key)}
          label={t("assuranceTwin.column.findings")}
          value={detail.finding_count}
        />
      </KpiGrid>
      <EvidenceGaps reasonCodes={detail.reason_codes} />
      <EvidenceProvenance record={detail} />
      <DataTable
        columns={columns}
        rows={detail.findings}
        keyOf={(row, index) => `${row.rule_id}:${row.resource_ref}:${index}`}
        empty={t("assuranceTwin.reviewsEmpty")}
      />
    </div>
  );
}
