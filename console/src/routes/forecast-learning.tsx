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
import { routeHref } from "../router";
import { t } from "./i18n/evidence";
import { panelArray, panelRecord } from "./panel-decode";

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

interface ForecastLearningResponse {
  readonly source: string;
  readonly durable: boolean;
  readonly episodes: EpisodeSummary;
  readonly outcomes: readonly OutcomeRow[];
  readonly publication: DebtSummary;
  readonly retention: DebtSummary;
}

export function ForecastLearningRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<ForecastLearningResponse>>({
    status: "loading",
  });
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = decodeForecastLearning(
          await client.panel<unknown>("/forecast-learning"),
        );
        if (!cancelled) setState({ status: "ready", data });
      } catch (error) {
        if (cancelled) return;
        if (isOptionalReadApiUnavailable(error)) {
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
  }, [client]);
  return (
    <div class="stack governance-route">
      <PageHeader
        title={t("evidence.forecastLearning.title")}
        subtitle={t("evidence.forecastLearning.subtitle")}
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
  if (decodedEpisodes.closed + decodedEpisodes.open !== decodedEpisodes.total) {
    throw new ReadApiError(
      502,
      "invalid read API response: forecast episode totals do not reconcile",
    );
  }
  return {
    source: text(root["source"], "source"),
    durable: root["durable"] === true,
    episodes: decodedEpisodes,
    outcomes: panelArray(root["outcomes"], "forecast outcomes").map((item, index) => {
      const row = panelRecord(item, `forecast outcomes[${index}]`);
      return {
        label: text(row["label"], "outcome label"),
        miss_origin:
          row["miss_origin"] === null ? null : text(row["miss_origin"], "miss origin"),
        count: integer(row["count"], "outcome count"),
      };
    }),
    publication: {
      pending: integer(publication["pending"], "publication.pending"),
      dead_lettered: integer(publication["dead_lettered"], "publication.dead_lettered"),
      oldest_pending_at:
        publication["oldest_pending_at"] === null
          ? null
          : text(publication["oldest_pending_at"], "oldest pending"),
    },
    retention: {
      pending: integer(retention["pending"], "retention.pending"),
      overdue: integer(retention["overdue"], "retention.overdue"),
    },
  };
}

function ForecastLearningBody({ data }: { readonly data: ForecastLearningResponse }) {
  const anchor = `${routeHref("forecast-learning")}#forecast-outcomes`;
  const columns: readonly Column<OutcomeRow>[] = [
    {
      key: "label",
      header: t("evidence.forecastLearning.column.label"),
      render: (row) => row.label,
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
          value={completeness === null ? null : `${(completeness * 100).toFixed(1)}%`}
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
      <div id="forecast-outcomes">
        <DataTable
          columns={columns}
          rows={data.outcomes}
          keyOf={(row) => `${row.label}:${row.miss_origin ?? "none"}`}
          empty={t("evidence.forecastLearning.empty")}
        />
      </div>
    </div>
  );
}

function integer(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new ReadApiError(
      502,
      `invalid read API response: ${label} MUST be a non-negative integer`,
    );
  }
  return value;
}

function nullableRatio(value: unknown): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new ReadApiError(
      502,
      "invalid read API response: closure completeness MUST be a ratio or null",
    );
  }
  return value;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new ReadApiError(
      502,
      `invalid read API response: ${label} MUST be a non-empty string`,
    );
  }
  return value;
}
