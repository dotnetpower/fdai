import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable } from "../api";
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
  type PillKind,
} from "../components/ui";
import { Tooltip } from "../components/tooltip";
import { usePublishViewContext, type ViewSnapshot } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
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
const CONFIDENCES = ["hypothesis", "reported", "corroborated", "verified", "proven"] as const;
const EXPOSURES = ["exposed", "internal", "not_deployed", "unknown"] as const;
const DECISIONS = ["urgent", "open", "clear", "coverage_incomplete"] as const;
const GAPS = [
  "code_security_review_malformed",
  "code_security_review_truncated",
  "code_security_pack_malformed",
] as const;
const VERDICTS = ["fixed_verified", "still_present", "inconclusive", "not_applicable"] as const;
const ADJUDICATION_DECISIONS = ["accepted", "rejected"] as const;
const DISPOSITIONS = ["false_positive", "open"] as const;

type Exposure = (typeof EXPOSURES)[number];
type Decision = (typeof DECISIONS)[number];
type Gap = (typeof GAPS)[number];
type Counts<K extends string> = Readonly<Record<K, number>>;

export interface CodeSecurityReview {
  readonly repository_alias: string;
  readonly revision: string;
  readonly review_digest: string;
  readonly recorded_at: string;
  readonly issue_count: number;
  readonly by_priority: Counts<(typeof PRIORITIES)[number]>;
  readonly by_severity: Counts<(typeof SEVERITIES)[number]>;
  readonly by_confidence: Counts<(typeof CONFIDENCES)[number]>;
  readonly known_exploited_count: number;
  readonly exposure: Exposure;
  readonly coverage_complete: boolean;
  readonly top_issue_ids: readonly string[];
  readonly decision: Decision;
}

export interface CodeSecurityReviewsResponse {
  readonly available: boolean;
  readonly complete: boolean;
  readonly reviews: readonly CodeSecurityReview[];
  readonly gaps: readonly Gap[];
}

export interface CodeSecurityPackAdjudication {
  readonly issue_id: string;
  readonly decision: (typeof ADJUDICATION_DECISIONS)[number];
  readonly issue_disposition: (typeof DISPOSITIONS)[number];
  readonly adjudicator: string;
  readonly decided_at: string;
}

export interface CodeSecurityPack {
  readonly pack_id: string;
  readonly base_commit: string;
  readonly issue_count: number;
  readonly recorded_at: string;
  readonly expires_at: string;
  readonly revoked: boolean;
  readonly latest_verification: {
    readonly rescan_revision: string;
    readonly recorded_at: string;
    readonly verdicts: Counts<(typeof VERDICTS)[number]>;
  } | null;
  readonly adjudications: readonly CodeSecurityPackAdjudication[];
}

export interface CodeSecurityPacksResponse {
  readonly available: boolean;
  readonly complete: boolean;
  readonly packs: readonly CodeSecurityPack[];
  readonly gaps: readonly Gap[];
}

export interface CodeSecurityState {
  readonly reviews: CodeSecurityReviewsResponse;
  readonly packs: CodeSecurityPacksResponse;
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== "string" || !(allowed as readonly string[]).includes(value)) {
    throw panelContractError(`${label} must be one of ${allowed.join(", ")}`);
  }
  return value as T;
}

function counts<K extends string>(value: unknown, keys: readonly K[], label: string): Counts<K> {
  const record = panelRecord(value, label);
  const result = {} as Record<K, number>;
  for (const key of keys) {
    result[key] = panelNonNegativeInteger(record, key, `${label}.${key}`);
  }
  return result;
}

function decodeReview(value: unknown, index: number): CodeSecurityReview {
  const label = `code-security review ${index}`;
  const row = panelRecord(value, label);
  return {
    repository_alias: panelNonEmptyString(row, "repository_alias", label),
    revision: panelNonEmptyString(row, "revision", label),
    review_digest: panelNonEmptyString(row, "review_digest", label),
    recorded_at: panelNonEmptyString(row, "recorded_at", label),
    issue_count: panelNonNegativeInteger(row, "issue_count", label),
    by_priority: counts(row.by_priority, PRIORITIES, `${label}.by_priority`),
    by_severity: counts(row.by_severity, SEVERITIES, `${label}.by_severity`),
    by_confidence: counts(row.by_confidence, CONFIDENCES, `${label}.by_confidence`),
    known_exploited_count: panelNonNegativeInteger(row, "known_exploited_count", label),
    exposure: oneOf(row.exposure, EXPOSURES, `${label}.exposure`),
    coverage_complete: panelBoolean(row, "coverage_complete", label),
    top_issue_ids: panelStringArray(row.top_issue_ids, `${label}.top_issue_ids`),
    decision: oneOf(row.decision, DECISIONS, `${label}.decision`),
  };
}

export function decodeCodeSecurityReviews(payload: unknown): CodeSecurityReviewsResponse {
  const root = panelRecord(payload, "code-security reviews");
  return {
    available: panelBoolean(root, "available", "code-security reviews"),
    complete: panelBoolean(root, "complete", "code-security reviews"),
    reviews: panelArray(root.reviews, "code-security reviews.reviews").map(decodeReview),
    gaps: decodeGaps(root.gaps, "code-security reviews"),
  };
}

function decodePack(value: unknown, index: number): CodeSecurityPack {
  const label = `code-security pack ${index}`;
  const row = panelRecord(value, label);
  const verification = row.latest_verification;
  let latest: CodeSecurityPack["latest_verification"] = null;
  if (verification !== null) {
    const record = panelRecord(verification, `${label}.latest_verification`);
    latest = {
      rescan_revision: panelNonEmptyString(record, "rescan_revision", label),
      recorded_at: panelNonEmptyString(record, "recorded_at", label),
      verdicts: counts(record.verdicts, VERDICTS, `${label}.verdicts`),
    };
  }
  return {
    pack_id: panelNonEmptyString(row, "pack_id", label),
    base_commit: panelNonEmptyString(row, "base_commit", label),
    issue_count: panelNonNegativeInteger(row, "issue_count", label),
    recorded_at: panelNonEmptyString(row, "recorded_at", label),
    expires_at: panelNonEmptyString(row, "expires_at", label),
    revoked: panelBoolean(row, "revoked", label),
    latest_verification: latest,
    adjudications: panelArray(row.adjudications, `${label}.adjudications`).map((item, position) => {
      const entry = panelRecord(item, `${label}.adjudications.${position}`);
      return {
        issue_id: panelNonEmptyString(entry, "issue_id", label),
        decision: oneOf(entry.decision, ADJUDICATION_DECISIONS, `${label}.decision`),
        issue_disposition: oneOf(entry.issue_disposition, DISPOSITIONS, `${label}.issue_disposition`),
        adjudicator: panelNonEmptyString(entry, "adjudicator", label),
        decided_at: panelNonEmptyString(entry, "decided_at", label),
      };
    }),
  };
}

function decodeGaps(value: unknown, label: string): readonly Gap[] {
  return panelArray(value, `${label}.gaps`).map((gap, index) =>
    oneOf(panelRecord(gap, `${label} gap ${index}`).reason_code, GAPS, `${label} gap ${index}.reason_code`));
}

export function decodeCodeSecurityPacks(payload: unknown): CodeSecurityPacksResponse {
  const root = panelRecord(payload, "code-security packs");
  return {
    available: panelBoolean(root, "available", "code-security packs"),
    complete: panelBoolean(root, "complete", "code-security packs"),
    packs: panelArray(root.packs, "code-security packs.packs").map(decodePack),
    gaps: decodeGaps(root.gaps, "code-security packs"),
  };
}

export function packState(pack: CodeSecurityPack, now: Date): "active" | "revoked" | "expired" {
  if (pack.revoked) return "revoked";
  return new Date(pack.expires_at).getTime() < now.getTime() ? "expired" : "active";
}

/** The newest review per repository; rows arrive newest first. */
export function latestPerRepository(
  reviews: readonly CodeSecurityReview[],
): readonly CodeSecurityReview[] {
  const seen = new Set<string>();
  return reviews.filter((review) => {
    if (seen.has(review.repository_alias)) return false;
    seen.add(review.repository_alias);
    return true;
  });
}

function decisionKind(decision: Decision): PillKind {
  if (decision === "urgent") return "danger";
  if (decision === "open" || decision === "coverage_incomplete") return "warning";
  return "success";
}

export function buildCodeSecurityViewSnapshot(state: CodeSecurityState): ViewSnapshot {
  const data = state.reviews;
  const latest = latestPerRepository(data.reviews);
  return {
    routeId: "code-security",
    routeLabel: t("route.codeSecurity"),
    purpose: t("codeSecurity.readOnlyBody"),
    glossary: composeGlossary([], [
      { term: t("route.codeSecurity"), plain: t("codeSecurity.subtitle"), tech: "code-security-review" },
    ]),
    headline: data.available
      ? `${t("codeSecurity.kpi.reviews")}: ${data.reviews.length}`
      : t("codeSecurity.unavailable"),
    capturedAt: new Date().toISOString(),
    facts: [
      { key: "review_count", label: t("codeSecurity.kpi.reviews"), value: data.reviews.length },
      { key: "pack_count", label: t("codeSecurity.packsTitle"), value: state.packs.packs.length },
      {
        key: "urgent_count",
        label: t("codeSecurity.kpi.urgent"),
        value: latest.filter((review) => review.decision === "urgent").length,
      },
    ],
    records: {
      reviews: data.reviews.map((review) => ({
        repository_alias: review.repository_alias,
        revision: review.revision,
        decision: review.decision,
        issue_count: review.issue_count,
        recorded_at: review.recorded_at,
      })),
      packs: state.packs.packs.map((pack) => ({
        pack_id: pack.pack_id,
        revoked: pack.revoked,
        issue_count: pack.issue_count,
        fixed_verified: pack.latest_verification?.verdicts.fixed_verified ?? null,
      })),
    },
  };
}

function verdictCount(pack: CodeSecurityPack, verdict: (typeof VERDICTS)[number]) {
  return pack.latest_verification === null ? "-" : pack.latest_verification.verdicts[verdict];
}

function PacksSection({ data }: { readonly data: CodeSecurityPacksResponse }) {
  const now = new Date();
  const columns: readonly Column<CodeSecurityPack>[] = [
    { key: "pack", header: t("codeSecurity.packColumn.pack"), render: (row) => <span class="mono">{row.pack_id}</span> },
    {
      key: "base",
      header: t("codeSecurity.packColumn.base"),
      render: (row) => (
        <Tooltip content={row.base_commit}>
          <span class="mono">{row.base_commit.slice(0, 12)}</span>
        </Tooltip>
      ),
    },
    { key: "issues", header: t("codeSecurity.packColumn.issues"), render: (row) => row.issue_count, cellClass: "num" },
    {
      key: "state",
      header: t("codeSecurity.packColumn.state"),
      render: (row) => {
        const state = packState(row, now);
        return (
          <StatusPill
            kind={state === "active" ? "info" : "neutral"}
            label={t(`codeSecurity.packState.${state}`)}
          />
        );
      },
    },
    {
      key: "fixed",
      header: t("codeSecurity.packColumn.fixedVerified"),
      render: (row) => verdictCount(row, "fixed_verified"),
      cellClass: "num",
    },
    {
      key: "present",
      header: t("codeSecurity.packColumn.stillPresent"),
      render: (row) => verdictCount(row, "still_present"),
      cellClass: "num",
    },
    {
      key: "inconclusive",
      header: t("codeSecurity.packColumn.inconclusive"),
      render: (row) => verdictCount(row, "inconclusive"),
      cellClass: "num",
    },
    {
      key: "false-positives",
      header: t("codeSecurity.packColumn.falsePositives"),
      render: (row) => row.adjudications.filter((item) => item.issue_disposition === "false_positive").length,
      cellClass: "num",
    },
  ];
  return (
    <section class="stack" aria-labelledby="code-security-packs">
      <h2 id="code-security-packs">{t("codeSecurity.packsTitle")}</h2>
      <DataTable
        columns={columns}
        rows={data.packs}
        keyOf={(row) => row.pack_id}
        empty={t("codeSecurity.packsEmpty")}
      />
      {data.gaps.length > 0
        ? (
          <div class="assurance-twin-gaps" role="status">
            <strong>{t("codeSecurity.packsWithheld")}</strong>
            <ul>
              {data.gaps.map((gap, index) => <li key={`${gap}:${index}`}>{t(`codeSecurity.gap.${gap}`)}</li>)}
            </ul>
          </div>
        )
        : null}
    </section>
  );
}

function CodeSecurityBody({ state }: { readonly state: CodeSecurityState }) {
  usePublishViewContext(() => buildCodeSecurityViewSnapshot(state), [state]);
  const data = state.reviews;
  const href = routeHref("code-security");
  const latest = latestPerRepository(data.reviews);
  const columns: readonly Column<CodeSecurityReview>[] = [
    {
      key: "repository",
      header: t("codeSecurity.column.repository"),
      render: (row) => <span class="mono">{row.repository_alias}</span>,
    },
    {
      key: "revision",
      header: t("codeSecurity.column.revision"),
      render: (row) => (
        <Tooltip content={row.revision}>
          <span class="mono">{row.revision.slice(0, 12)}</span>
        </Tooltip>
      ),
    },
    {
      key: "decision",
      header: t("codeSecurity.column.decision"),
      render: (row) => (
        <StatusPill kind={decisionKind(row.decision)} label={t(`codeSecurity.decision.${row.decision}`)} />
      ),
    },
    { key: "issues", header: t("codeSecurity.column.issues"), render: (row) => row.issue_count, cellClass: "num" },
    {
      key: "priority",
      header: t("codeSecurity.column.priority"),
      render: (row) => `${row.by_priority.P0} / ${row.by_priority.P1} / ${row.by_priority.P2}`,
      cellClass: "num",
    },
    {
      key: "confidence",
      header: t("codeSecurity.column.confidence"),
      render: (row) => row.by_confidence.verified + row.by_confidence.proven,
      cellClass: "num",
    },
    {
      key: "exposure",
      header: t("codeSecurity.column.exposure"),
      render: (row) => t(`codeSecurity.exposure.${row.exposure}`),
    },
    {
      key: "recorded_at",
      header: t("codeSecurity.column.recordedAt"),
      render: (row) => formatConsoleTimestamp(row.recorded_at),
    },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("codeSecurity.readOnlyTitle")}</strong>
        <span>{t("codeSecurity.readOnlyBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={href} label={t("codeSecurity.kpi.reviews")} value={data.reviews.length} />
        <KpiCard
          href={href}
          label={t("codeSecurity.kpi.openIssues")}
          value={latest.reduce((total, review) => total + review.issue_count, 0)}
        />
        <KpiCard
          href={href}
          label={t("codeSecurity.kpi.urgent")}
          value={latest.filter((review) => review.decision === "urgent").length}
          tone={latest.some((review) => review.decision === "urgent") ? "danger" : "default"}
        />
        <KpiCard
          href={href}
          label={t("codeSecurity.kpi.incomplete")}
          value={latest.filter((review) => !review.coverage_complete).length}
          tone={latest.some((review) => !review.coverage_complete) ? "warning" : "default"}
        />
      </KpiGrid>
      <DataTable
        columns={columns}
        rows={data.reviews}
        keyOf={(row) => `${row.repository_alias}:${row.revision}`}
        empty={t("codeSecurity.empty")}
        caption={t("route.codeSecurity")}
      />
      {data.gaps.length > 0
        ? (
          <div class="assurance-twin-gaps" role="status">
            <strong>{t("codeSecurity.withheld")}</strong>
            <ul>
              {data.gaps.map((gap, index) => <li key={`${gap}:${index}`}>{t(`codeSecurity.gap.${gap}`)}</li>)}
            </ul>
          </div>
        )
        : null}
      <PacksSection data={state.packs} />
    </div>
  );
}

export async function loadCodeSecurityState(
  client: Pick<OperatorApiClient, "panel">,
): Promise<AsyncState<CodeSecurityState>> {
  try {
    const [reviews, packs] = await Promise.all([
      client.panel<unknown>("/code-security/reviews"),
      client.panel<unknown>("/code-security/packs"),
    ]);
    return {
      status: "ready",
      data: { reviews: decodeCodeSecurityReviews(reviews), packs: decodeCodeSecurityPacks(packs) },
    };
  } catch (error) {
    if (isOptionalOperatorApiUnavailable(error)) {
      return { status: "unavailable", message: t("codeSecurity.unavailable") };
    }
    return { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

export function CodeSecurityRoute({ client }: { readonly client: OperatorApiClient }) {
  const [state, setState] = useState<AsyncState<CodeSecurityState>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    void loadCodeSecurityState(client).then((next) => {
      if (!cancelled) setState(next);
    });
    return () => { cancelled = true; };
  }, [client]);
  return (
    <div class="stack evidence-route">
      <PageHeader title={t("route.codeSecurity")} subtitle={t("codeSecurity.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("codeSecurity.resourceLabel")}>
        {(data) => <CodeSecurityBody state={data} />}
      </AsyncBoundary>
    </div>
  );
}
