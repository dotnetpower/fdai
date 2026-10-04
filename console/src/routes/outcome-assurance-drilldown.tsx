import type {
  OutcomeAssuranceMetric,
  OutcomeAssuranceProjection,
  OutcomeAssuranceReadState,
} from "../api-outcome-assurance";
import {
  DataTable,
  StatusPill,
  UnavailableState,
  type Column,
  type PillKind,
} from "../components/ui";
import { t } from "./i18n/analytics";

export function outcomeAssuranceUnavailableMessage(
  projection: OutcomeAssuranceProjection | null,
): string {
  if (projection === null) return t("analytics.outcomeAssurance.notConnected");
  if (projection.state === "stale") return t("analytics.outcomeAssurance.stale");
  if (projection.state === "unavailable") {
    return t("analytics.outcomeAssurance.unavailable", {
      reason: projection.reason ?? "unknown",
    });
  }
  return "";
}

export function OutcomeAssuranceDrilldown({
  projection,
}: {
  readonly projection: OutcomeAssuranceProjection | null;
}) {
  if (projection === null) {
    return (
      <section class="assurance-section" aria-label={t("analytics.outcomeAssurance.title")}>
        <UnavailableState
          evidenceState="not-connected"
          message={outcomeAssuranceUnavailableMessage(null)}
        />
      </section>
    );
  }
  const unavailable = outcomeAssuranceUnavailableMessage(projection);
  return (
    <section class="assurance-section" aria-label={t("analytics.outcomeAssurance.title")}>
      <header class="assurance-section-head">
        <div>
          <h3>{t("analytics.outcomeAssurance.title")}</h3>
          <p>{t("analytics.outcomeAssurance.subtitle")}</p>
        </div>
        <StatusPill
          kind={toneForState(projection.state)}
          label={t(`analytics.outcomeAssurance.state.${projection.state}`)}
        />
      </header>
      {unavailable ? (
        <UnavailableState
          evidenceState={projection.state === "stale" ? "not-measured" : "not-connected"}
          message={unavailable}
        />
      ) : null}
      <div class="analytics-evidence">
        <strong>{t("overview.evidence.source", { source: projection.sources[0]?.name ?? "unknown" })}</strong>
        <span>{t("overview.evidence.asOf", { time: projection.provenance.as_of })}</span>
        <span>{t("analytics.outcomeAssurance.scope", { scope: projection.scope.scope_ref })}</span>
        <span>{t("analytics.outcomeAssurance.window", {
          start: projection.window.start,
          end: projection.window.end,
        })}</span>
      </div>
      <DataTable
        columns={OUTCOME_COLUMNS}
        empty={t("analytics.outcomeAssurance.noOutcomes")}
        keyOf={(row) => `${row.objective_ref}:${row.metric}`}
        rows={projection.outcomes.map((metric) => ({
          ...metric,
          display_value: displayOutcomeValue(metric),
          display_sample: metric.sample_size === null ? t("analytics.unavailable") : metric.sample_size,
        }))}
      />
      <dl class="analytics-evidence">
        <div>
          <dt>{t("analytics.outcomeAssurance.attribution")}</dt>
          <dd>{projection.alignment.coverage === null
            ? t("analytics.unavailable")
            : `${Math.round(projection.alignment.coverage * 100)}%`}</dd>
        </div>
        <div>
          <dt>{t("analytics.outcomeAssurance.guards")}</dt>
          <dd>{t(`analytics.outcomeAssurance.guardState.${projection.guards.state}`)}</dd>
        </div>
      </dl>
    </section>
  );
}

function displayOutcomeValue(metric: OutcomeAssuranceMetric): string {
  if (metric.current_value === null) return t("analytics.unavailable");
  if (metric.unit === "ratio") return `${Math.round(metric.current_value * 100)}%`;
  return String(metric.current_value);
}

function toneForState(state: OutcomeAssuranceReadState): PillKind {
  if (state === "complete") return "success";
  if (state === "stale") return "warning";
  return "neutral";
}

const OUTCOME_COLUMNS: readonly Column<OutcomeAssuranceMetric & {
  readonly display_value: string;
  readonly display_sample: string | number;
}>[] = [
  {
    key: "objective_ref",
    header: t("analytics.outcomeAssurance.objective"),
    render: (row) => row.objective_ref,
  },
  {
    key: "metric",
    header: t("analytics.outcomeAssurance.metric"),
    render: (row) => row.metric,
  },
  {
    key: "state",
    header: t("analytics.status"),
    render: (row) => t(`analytics.outcomeAssurance.metricState.${row.state}`),
  },
  {
    key: "current_value",
    header: t("analytics.current"),
    render: (row) => row.display_value,
  },
  {
    key: "sample_size",
    header: t("analytics.sampleSize"),
    render: (row) => row.display_sample,
  },
];
