import { useCallback, useEffect, useState } from "preact/hooks";
import "./code-security.css";
import { ReviewIssuesPanel } from "./code-security-issues";
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
import { t as appT } from "../i18n";
import { t } from "./i18n/code-security";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import {
  RepositoryScanSection,
  decodeCodeSecurityRepositories,
  decodeCodeSecurityScanRequests,
  decodeCodeSecurityWorkerStatus,
  type CodeSecurityRepositoriesResponse,
  type CodeSecurityScanRequestsResponse,
  type CodeSecurityWorkerStatusResponse,
} from "./code-security-requests";
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
const SOURCE_KINDS = ["local_path", "git_repository", "external_sarif"] as const;
const REVISION_KINDS = ["commit", "snapshot"] as const;
const TRIGGERS = ["cli", "console", "schedule"] as const;
export const SOURCE_FILTERS = ["all", ...SOURCE_KINDS, "legacy"] as const;
export type SourceFilter = (typeof SOURCE_FILTERS)[number];

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
  readonly source: ReviewSource | null;
  readonly producers: readonly string[];
}

export interface ReviewSource {
  readonly kind: (typeof SOURCE_KINDS)[number];
  readonly provider: string;
  readonly revision_kind: (typeof REVISION_KINDS)[number];
  readonly trigger: (typeof TRIGGERS)[number];
  readonly request_id: string | null;
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
  /** ``null`` when the registration or request projection is unavailable. */
  readonly repositories?: CodeSecurityRepositoriesResponse | null;
  readonly requests?: CodeSecurityScanRequestsResponse | null;
  readonly worker?: CodeSecurityWorkerStatusResponse | null;
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
    source: decodeSource(row.source, `${label}.source`),
    producers: row.producers === undefined ? [] : panelStringArray(row.producers, `${label}.producers`),
  };
}

function decodeSource(value: unknown, label: string): ReviewSource | null {
  if (value === null || value === undefined) return null;
  const record = panelRecord(value, label);
  const requestId = record.request_id;
  if (requestId !== null && (typeof requestId !== "string" || requestId.length === 0)) {
    throw panelContractError(`${label}.request_id must be a string or null`);
  }
  return {
    kind: oneOf(record.kind, SOURCE_KINDS, `${label}.kind`),
    provider: panelNonEmptyString(record, "provider", label),
    revision_kind: oneOf(record.revision_kind, REVISION_KINDS, `${label}.revision_kind`),
    trigger: oneOf(record.trigger, TRIGGERS, `${label}.trigger`),
    request_id: requestId,
  };
}

/** The filter bucket a review belongs to; unlabeled ``1.0.0`` reviews stay visible as legacy. */
export function sourceCategory(review: CodeSecurityReview): Exclude<SourceFilter, "all"> {
  return review.source?.kind ?? "legacy";
}

export function filterBySource(
  reviews: readonly CodeSecurityReview[],
  filter: SourceFilter,
): readonly CodeSecurityReview[] {
  return filter === "all" ? reviews : reviews.filter((review) => sourceCategory(review) === filter);
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
    routeLabel: appT("nav.panel.codeSecurity"),
    purpose: t("codeSecurity.readOnlyBody"),
    glossary: composeGlossary([], [
      { term: appT("nav.panel.codeSecurity"), plain: t("codeSecurity.subtitle"), tech: "code-security-review" },
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
        source: sourceCategory(review),
        provider: review.source?.provider ?? null,
        trigger: review.source?.trigger ?? null,
      })),
      scan_requests: (state.requests?.requests ?? []).map((request) => ({
        request_id: request.request_id,
        repository_alias: request.repository_alias,
        status: request.status,
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

function sourceLabel(review: CodeSecurityReview): string {
  if (review.source === null) return t("codeSecurity.source.legacy");
  return `${t(`codeSecurity.source.${review.source.kind}`)} (${review.source.provider})`;
}

function SourceFilterControl({
  value,
  counts,
  onChange,
}: {
  readonly value: SourceFilter;
  readonly counts: Readonly<Record<SourceFilter, number>>;
  readonly onChange: (next: SourceFilter) => void;
}) {
  return (
    <div class="segmented-control code-security-source-filter" role="group" aria-label={t("codeSecurity.filterLabel")}>
      {SOURCE_FILTERS.map((filter) => (
        <button
          key={filter}
          type="button"
          class={filter === value ? "active" : ""}
          aria-pressed={filter === value}
          onClick={() => onChange(filter)}
        >
          {`${t(`codeSecurity.source.${filter}`)} ${counts[filter]}`}
        </button>
      ))}
    </div>
  );
}

function CodeSecurityBody({
  state,
  client,
  onQueued,
}: {
  readonly state: CodeSecurityState;
  readonly client: Pick<OperatorApiClient, "requestCodeSecurityScan" | "changeCodeSecurityRepository" | "panel">;
  readonly onQueued: () => void;
}) {
  usePublishViewContext(() => buildCodeSecurityViewSnapshot(state), [state]);
  const [filter, setFilter] = useState<SourceFilter>("all");
  const [selected, setSelected] = useState<{ readonly alias: string; readonly revision: string } | null>(null);
  const data = state.reviews;
  const href = routeHref("code-security");
  const visible = filterBySource(data.reviews, filter);
  const latest = latestPerRepository(visible);
  const counts = Object.fromEntries(
    SOURCE_FILTERS.map((item) => [item, filterBySource(data.reviews, item).length]),
  ) as Record<SourceFilter, number>;
  const columns: readonly Column<CodeSecurityReview>[] = [
    {
      key: "repository",
      header: t("codeSecurity.column.repository"),
      render: (row) => <span class="mono">{row.repository_alias}</span>,
    },
    {
      key: "source",
      header: t("codeSecurity.column.source"),
      render: (row) => (
        <Tooltip content={row.producers.join(", ") || sourceLabel(row)}>
          <span>{sourceLabel(row)}</span>
        </Tooltip>
      ),
    },
    {
      key: "revision",
      header: t("codeSecurity.column.revision"),
      render: (row) => (
        <Tooltip content={row.revision}>
          <span class="mono">
            {row.source?.revision_kind === "snapshot"
              ? `${t("codeSecurity.snapshot")} ${row.revision.slice(0, 8)}`
              : row.revision.slice(0, 12)}
          </span>
        </Tooltip>
      ),
    },
    {
      key: "trigger",
      header: t("codeSecurity.column.trigger"),
      render: (row) => (row.source === null ? "-" : t(`codeSecurity.trigger.${row.source.trigger}`)),
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
    {
      key: "detail",
      header: t("codeSecurity.column.detail"),
      render: (row) => (
        <button
          type="button"
          class="btn subtle"
          aria-pressed={selected?.alias === row.repository_alias && selected.revision === row.revision}
          aria-label={`${t("codeSecurity.issues.open")} ${row.repository_alias} ${row.revision.slice(0, 12)}`}
          onClick={() => setSelected({ alias: row.repository_alias, revision: row.revision })}
        >
          {t("codeSecurity.issues.open")}
        </button>
      ),
    },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("codeSecurity.readOnlyTitle")}</strong>
        <span>{t("codeSecurity.readOnlyBody")}</span>
      </div>
      <SourceFilterControl value={filter} counts={counts} onChange={setFilter} />
      <KpiGrid>
        <KpiCard href={href} label={t("codeSecurity.kpi.reviews")} value={visible.length} />
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
        rows={visible}
        keyOf={(row) => `${row.repository_alias}:${row.revision}`}
        empty={t("codeSecurity.empty")}
        caption={appT("nav.panel.codeSecurity")}
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
      {selected === null
        ? null
        : (
          <ReviewIssuesPanel
            client={client}
            repositoryAlias={selected.alias}
            repositoryLocation={
              state.repositories?.repositories.find(
                (repository) => repository.repository_alias === selected.alias,
              )?.location ?? null
            }
            revision={selected.revision}
            onClose={() => setSelected(null)}
          />
        )}
      <RepositoryScanSection
        client={client}
        repositories={state.repositories ?? null}
        requests={state.requests ?? null}
        worker={state.worker ?? null}
        onQueued={onQueued}
      />
      <PacksSection data={state.packs} />
    </div>
  );
}

async function optionalPanel<T>(load: () => Promise<unknown>, decode: (payload: unknown) => T): Promise<T | null> {
  try {
    return decode(await load());
  } catch (error) {
    if (isOptionalOperatorApiUnavailable(error)) return null;
    throw error;
  }
}

export async function loadCodeSecurityState(
  client: Pick<OperatorApiClient, "panel">,
): Promise<AsyncState<CodeSecurityState>> {
  try {
    const [reviews, packs, repositories, requests, worker] = await Promise.all([
      client.panel<unknown>("/code-security/reviews"),
      client.panel<unknown>("/code-security/packs"),
      optionalPanel(() => client.panel<unknown>("/code-security/repositories"), decodeCodeSecurityRepositories),
      optionalPanel(() => client.panel<unknown>("/code-security/scan-requests"), decodeCodeSecurityScanRequests),
      optionalPanel(() => client.panel<unknown>("/code-security/worker-status"), decodeCodeSecurityWorkerStatus),
    ]);
    return {
      status: "ready",
      data: {
        reviews: decodeCodeSecurityReviews(reviews),
        packs: decodeCodeSecurityPacks(packs),
        repositories,
        requests,
        worker,
      },
    };
  } catch (error) {
    if (isOptionalOperatorApiUnavailable(error)) {
      return { status: "unavailable", message: t("codeSecurity.unavailable") };
    }
    return { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

export function codeSecurityRefreshDelay(state: AsyncState<CodeSecurityState>): number | null {
  if (state.status === "error" || state.status === "unavailable") return 15_000;
  if (state.status !== "ready") return null;
  return (state.data.requests?.requests ?? []).some(
    (request) => request.status === "queued" || request.status === "running",
  )
    ? 5_000
    : 30_000;
}

export function CodeSecurityRoute({ client }: { readonly client: OperatorApiClient }) {
  const [state, setState] = useState<AsyncState<CodeSecurityState>>({ status: "loading" });
  const [generation, setGeneration] = useState(0);
  const reload = useCallback(() => setGeneration((value) => value + 1), []);
  useEffect(() => {
    let cancelled = false;
    void loadCodeSecurityState(client).then((next) => {
      if (!cancelled) setState(next);
    });
    return () => { cancelled = true; };
  }, [client, generation]);
  useEffect(() => {
    const delay = codeSecurityRefreshDelay(state);
    if (delay === null) return;
    const refresh = () => {
      if (document.visibilityState === "visible") reload();
    };
    const timer = window.setTimeout(refresh, delay);
    const visibility = () => {
      if (document.visibilityState === "visible") reload();
    };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [reload, state]);
  return (
    <div class="stack evidence-route">
      <PageHeader title={appT("nav.panel.codeSecurity")} subtitle={t("codeSecurity.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("codeSecurity.resourceLabel")}>
        {(data) => <CodeSecurityBody state={data} client={client} onQueued={reload} />}
      </AsyncBoundary>
      {state.status === "error" || state.status === "unavailable"
        ? (
          <button type="button" class="btn subtle code-security-route-refresh" onClick={reload}>
            {t("codeSecurity.worker.refresh")}
          </button>
        )
        : null}
    </div>
  );
}
