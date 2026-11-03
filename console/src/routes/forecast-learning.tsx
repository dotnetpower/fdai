import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import { EvidenceRefresh } from "../components/evidence-refresh";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  kpiEvidenceLabel,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext, type ViewSnapshot } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { getLocale } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/evidence";
import { panelArray, panelRecord } from "./panel-decode";
import { ForecastActivity } from "./forecast-activity";

interface EpisodeSummary {
  readonly total: number;
  readonly closed: number;
  readonly open: number;
  readonly overdue: number;
  readonly abstained: number;
  readonly closure_completeness: number | null;
}

interface OutcomeRow {
  readonly label: string;
  readonly miss_origin: string | null;
  readonly count: number;
}

interface DebtSummary {
  readonly pending: number;
  readonly oldest_pending_at?: string | null;
  readonly dead_lettered?: number;
  readonly overdue?: number;
}

export interface ForecastLearningResponse {
  readonly source: string;
  readonly durable: boolean;
  readonly episodes: EpisodeSummary;
  readonly outcomes: readonly OutcomeRow[];
  readonly publication: DebtSummary;
  readonly retention: DebtSummary;
}

export function buildForecastLearningViewSnapshot(
  data: ForecastLearningResponse,
): ViewSnapshot {
  return {
    routeId: "forecast-learning",
    routeLabel: t("evidence.forecastLearning.title"),
    purpose: t("evidence.forecastLearning.bannerBody"),
    glossary: composeGlossary([TERMS.outcome]),
    headline: t("evidence.forecastLearning.viewHeadline", {
      total: data.episodes.total,
      open: data.episodes.open,
      overdue: data.episodes.overdue,
    }),
    capturedAt: new Date().toISOString(),
    facts: [
      {
        key: "closure_completeness",
        label: t("evidence.forecastLearning.completeness"),
        value: data.episodes.closure_completeness,
        group: "episodes",
        unit: "ratio",
      },
      {
        key: "overdue_episodes",
        label: t("evidence.forecastLearning.overdue"),
        value: data.episodes.overdue,
        group: "episodes",
      },
      {
        key: "publication_debt",
        label: t("evidence.forecastLearning.outboxDebt"),
        value: data.publication.pending,
        group: "delivery",
      },
      {
        key: "dead_letters",
        label: t("evidence.forecastLearning.deadLetters"),
        value: data.publication.dead_lettered ?? 0,
        group: "delivery",
      },
      {
        key: "retention_debt",
        label: t("evidence.forecastLearning.retentionDebt"),
        value: data.retention.overdue ?? 0,
        group: "retention",
      },
      { key: "source", value: data.source, group: "provenance" },
      { key: "durable", value: data.durable, group: "provenance" },
    ],
    records: {
      outcomes: data.outcomes.map((outcome) => ({ ...outcome })),
    },
  };
}

export function ForecastLearningRoute({ client }: { readonly client: OperatorApiClient }) {
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [state, setState] = useState<AsyncState<ForecastLearningResponse>>({
    status: "loading",
  });
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const data = decodeForecastLearning(
          await client.panel<unknown>("/forecast-learning"),
        );
        if (!cancelled) setState({ status: "ready", data });
      } catch (error) {
        if (cancelled) return;
        if (isOptionalOperatorApiUnavailable(error)) {
          setState({
            status: "unavailable",
            message: t("evidence.forecastLearning.unavailable"),
          });
        } else {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, refreshRevision]);
  return (
    <div class="stack governance-route cs-workspace-route">
      <PageHeader
        title={t("evidence.forecastLearning.title")}
        subtitle={t("evidence.forecastLearning.subtitle")}
        actions={<EvidenceRefresh loading={state.status === "loading"} onRefresh={() => {
          setState({ status: "loading" });
          setRefreshRevision((revision) => revision + 1);
        }} />}
      />
      <AsyncBoundary
        state={state}
        resourceLabel={t("evidence.forecastLearning.resource")}
      >
        {(data) => <ForecastLearningBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeForecastLearning(value: unknown): ForecastLearningResponse {
  const root = panelRecord(value, "forecast learning");
  const episodes = panelRecord(root["episodes"], "forecast learning episodes");
  const publication = panelRecord(root["publication"], "forecast publication debt");
  const retention = panelRecord(root["retention"], "forecast retention debt");
  const decodedEpisodes: EpisodeSummary = {
    total: integer(episodes["total"], "episodes.total"),
    closed: integer(episodes["closed"], "episodes.closed"),
    open: integer(episodes["open"], "episodes.open"),
    overdue: integer(episodes["overdue"], "episodes.overdue"),
    abstained: integer(episodes["abstained"], "episodes.abstained"),
    closure_completeness: nullableRatio(episodes["closure_completeness"]),
  };
  if (
    decodedEpisodes.closed + decodedEpisodes.open !== decodedEpisodes.total ||
    decodedEpisodes.overdue > decodedEpisodes.open ||
    decodedEpisodes.abstained > decodedEpisodes.total
  ) {
    throw new OperatorApiError(
      502,
      "invalid Operator API response: forecast episode totals do not reconcile",
    );
  }
  const outcomes = panelArray(root["outcomes"], "forecast outcomes").map((item, index) => {
    const row = panelRecord(item, `forecast outcomes[${index}]`);
    return {
      label: text(row["label"], "outcome label"),
      miss_origin:
        row["miss_origin"] === null ? null : text(row["miss_origin"], "miss origin"),
      count: integer(row["count"], "outcome count"),
    };
  });
  const outcomeKeys = new Set<string>();
  for (const row of outcomes) {
    const key = `${row.label}:${row.miss_origin ?? "none"}`;
    if (outcomeKeys.has(key)) {
      throw new OperatorApiError(
        502,
        "invalid Operator API response: forecast outcome keys MUST be unique",
      );
    }
    outcomeKeys.add(key);
  }
  const decodedRetention = {
    pending: integer(retention["pending"], "retention.pending"),
    overdue: integer(retention["overdue"], "retention.overdue"),
  };
  if (decodedRetention.overdue > decodedRetention.pending) {
    throw new OperatorApiError(
      502,
      "invalid Operator API response: forecast retention overdue MUST NOT exceed pending",
    );
  }
  return {
    source: text(root["source"], "source"),
    durable: root["durable"] === true,
    episodes: decodedEpisodes,
    outcomes,
    publication: {
      pending: integer(publication["pending"], "publication.pending"),
      dead_lettered: integer(publication["dead_lettered"], "publication.dead_lettered"),
      oldest_pending_at:
        publication["oldest_pending_at"] === null
          ? null
          : text(publication["oldest_pending_at"], "oldest pending"),
    },
    retention: decodedRetention,
  };
}

function ForecastLearningBody({ data }: { readonly data: ForecastLearningResponse }) {
  usePublishViewContext(
    () => buildForecastLearningViewSnapshot(data),
    [data],
  );
  const anchor = `${routeHref("forecast-learning")}#forecast-outcomes`;
  const totalOutcomeCount = data.outcomes.reduce((sum, row) => sum + row.count, 0);
  const columns: readonly Column<OutcomeRow>[] = [
    {
      key: "label",
      header: t("evidence.forecastLearning.column.label"),
      render: (row) => <strong>{row.label}</strong>,
    },
    {
      key: "origin",
      header: t("evidence.forecastLearning.column.origin"),
      render: (row) => row.miss_origin ?? "-",
    },
    {
      key: "count",
      header: t("evidence.forecastLearning.column.count"),
      render: (row) => row.count,
      cellClass: "num",
    },
    {
      key: "share",
      header: "%",
      render: (row) => totalOutcomeCount > 0 ? `${Math.round((row.count / totalOutcomeCount) * 100)}%` : "0%",
      cellClass: "num",
    },
  ];
  const completeness = data.episodes.closure_completeness;
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("evidence.forecastLearning.bannerTitle")}</strong>
        <span>{t("evidence.forecastLearning.bannerBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard
          href={anchor}
          label={t("evidence.forecastLearning.completeness")}
          evidenceState={completeness === null ? "not-measured" : "measured"}
          value={completeness === null ? kpiEvidenceLabel("not-measured") : `${(completeness * 100).toFixed(1)}%`}
        />
        <KpiCard
          href={anchor}
          label={t("evidence.forecastLearning.overdue")}
          value={data.episodes.overdue}
          tone={data.episodes.overdue ? "warning" : "positive"}
        />
        <KpiCard
          href={anchor}
          label={t("evidence.forecastLearning.outboxDebt")}
          value={data.publication.pending}
          tone={data.publication.pending ? "warning" : "positive"}
        />
        <KpiCard
          href={anchor}
          label={t("evidence.forecastLearning.deadLetters")}
          value={data.publication.dead_lettered ?? 0}
          tone={data.publication.dead_lettered ? "warning" : "positive"}
        />
        <KpiCard
          href={anchor}
          label={t("evidence.forecastLearning.retentionDebt")}
          value={data.retention.overdue ?? 0}
          tone={data.retention.overdue ? "warning" : "positive"}
        />
      </KpiGrid>
      <div class="evidence-source-line">
        <StatusPill kind={data.durable ? "success" : "warning"} label={data.source} />
      </div>
      <div id="forecast-outcomes" class="cs-workspace-split has-selection">
        <div class="cs-workspace-main">
          <ForecastActivity data={data} />
          {data.outcomes.length > 0 ? (
            <div class="cs-ratio-bars">
              {data.outcomes.map((row) => {
                const pct = totalOutcomeCount > 0 ? Math.round((row.count / totalOutcomeCount) * 100) : 0;
                return (
                  <div class="cs-ratio-row" key={`${row.label}:${row.miss_origin ?? "none"}`}>
                    <span>{row.label}{row.miss_origin ? ` (${row.miss_origin})` : ""}</span>
                    <div class="cs-ratio-track" aria-hidden="true">
                      <span class={row.miss_origin ? "is-warning" : "is-success"} style={`width:${pct}%`} />
                    </div>
                    <strong>{row.count} ({pct}%)</strong>
                  </div>
                );
              })}
            </div>
          ) : null}
          <DataTable
            columns={columns}
            rows={data.outcomes}
            keyOf={(row) => `${row.label}:${row.miss_origin ?? "none"}`}
            scrollRegionLabel={t("evidence.forecastLearning.title")}
            empty={t("evidence.forecastLearning.empty")}
          />
        </div>
        <aside class="cs-inspector-pane" aria-label={t("evidence.forecastLearning.title")}>
          <header class="cs-inspector-head">
            <div>
              <span class="cs-inspector-kicker">{data.source}</span>
              <h3>{t("evidence.forecastLearning.title")}</h3>
              <p>{t("evidence.forecastLearning.viewHeadline", {
                total: data.episodes.total,
                open: data.episodes.open,
                overdue: data.episodes.overdue,
              })}</p>
            </div>
            <StatusPill kind={data.durable ? "success" : "warning"} label={data.source} />
          </header>
          <dl class="cs-facts-grid">
            <div><dt>{t("evidence.forecastLearning.completeness")}</dt><dd>{completeness === null ? kpiEvidenceLabel("not-measured") : `${(completeness * 100).toFixed(1)}%`} ({data.episodes.closed} / {data.episodes.total})</dd></div>
            <div><dt>{t("evidence.forecastLearning.overdue")}</dt><dd>{data.episodes.overdue} ({getLocale() === "ko" ? `진행 중 ${data.episodes.open}, 보류 ${data.episodes.abstained}` : `${data.episodes.open} open, ${data.episodes.abstained} abstained`})</dd></div>
            <div><dt>{t("evidence.forecastLearning.outboxDebt")}</dt><dd>{data.publication.pending} / {t("evidence.forecastLearning.deadLetters")}: {data.publication.dead_lettered ?? 0}</dd></div>
            <div><dt>{getLocale() === "ko" ? "가장 오래된 대기 시각" : "Oldest pending"}</dt><dd>{data.publication.oldest_pending_at ? formatConsoleTimestamp(data.publication.oldest_pending_at) : t("evidence.common.none")}</dd></div>
            <div><dt>{t("evidence.forecastLearning.retentionDebt")}</dt><dd>{data.retention.overdue ?? 0} / {data.retention.pending}</dd></div>
          </dl>
        </aside>
      </div>
    </div>
  );
}

function integer(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new OperatorApiError(
      502,
      `invalid Operator API response: ${label} MUST be a non-negative integer`,
    );
  }
  return value;
}

function nullableRatio(value: unknown): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new OperatorApiError(
      502,
      "invalid Operator API response: closure completeness MUST be a ratio or null",
    );
  }
  return value;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new OperatorApiError(
      502,
      `invalid Operator API response: ${label} MUST be a non-empty string`,
    );
  }
  return value;
}
