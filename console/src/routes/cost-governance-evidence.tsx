import { useState } from "preact/hooks";
import type {
  CostDisclosurePolicy,
  CostEvidenceState,
  CostGovernanceProjection,
  CostReadinessReason,
  CostReadinessSurface,
  CostSurfaceReadiness,
} from "../api-cost-governance";
import { costLocale, formatCurrency } from "./cost-governance-format";
import {
  costReadiness,
  type CostGovernanceSummary,
} from "./cost-governance.view-model";
import { t } from "./i18n/cost-governance";

const READINESS_SURFACES: readonly CostReadinessSurface[] = [
  "observations",
  "analytics",
  "resource-candidates",
  "decision-cases",
  "settlements",
];

export function CostEvidenceSummary({
  projection,
  summary,
}: {
  readonly projection: CostGovernanceProjection;
  readonly summary: CostGovernanceSummary;
}) {
  const [expanded, setExpanded] = useState(false);
  const evidence = projection.evidence ?? null;
  const disclosure = evidence?.disclosure ?? projection.disclosure ?? null;
  const disclosureCurrency = singleProjectionCurrency(projection, summary.currency);
  const detailsId = "cost-evidence-details";
  return (
    <section class="cost-evidence-summary" aria-labelledby="cost-evidence-title">
      <div class="cost-evidence-toolbar">
        <div>
          <span id="cost-evidence-title">{t("costGovernance.evidence.source")}</span>
          <strong>{projection.source_authority}</strong>
          <small>{sourceCount(evidence?.sources.length ?? 0)}</small>
        </div>
        <div>
          <span>{t("costGovernance.evidence.period")}</span>
          <strong>{formatEvidenceWindow(
            evidence?.window_start_at ?? projection.analytics?.window_start_at ?? null,
            evidence?.window_end_at ?? projection.analytics?.window_end_at ?? null,
          )}</strong>
          <small>{t("costGovernance.evidence.generatedAt", {
            value: formatTimestamp(projection.generated_at ?? null),
          })}</small>
        </div>
        <div>
          <span>{t("costGovernance.evidence.freshness")}</span>
          <strong class={`cost-evidence-value is-${evidence?.freshness ?? "unknown"}`}>
            {freshnessLabel(evidence?.freshness ?? "unknown")}
          </strong>
          <small>{t("costGovernance.evidence.latestSource", {
            value: formatTimestamp(
              evidence?.latest_source_at ?? projection.analytics?.observed_at ?? null,
            ),
          })}</small>
        </div>
        <div class="cost-evidence-state">
          <span>{t("costGovernance.evidence.completeness")}</span>
          <strong>{evidence
            ? t("costGovernance.evidence.completePartial", {
              complete: evidence.complete_count,
              partial: evidence.partial_count,
            })
            : projection.complete
            ? t("costGovernance.summary.complete")
            : t("costGovernance.summary.incomplete")}</strong>
          <i class={projection.complete ? "complete" : "partial"} aria-hidden="true" />
          <small>{t("costGovernance.evidence.records", {
            count: evidence
              ? evidence.complete_count + evidence.partial_count
              : summary.sourceRecordCount,
          })}</small>
        </div>
        <button
          type="button"
          class="cost-evidence-toggle"
          aria-expanded={expanded}
          aria-controls={detailsId}
          onClick={() => setExpanded((value) => !value)}
        >
          {t(expanded
            ? "costGovernance.evidence.hideDetails"
            : "costGovernance.evidence.showDetails")}
        </button>
      </div>
      {expanded ? (
        <div class="cost-evidence-details" id={detailsId}>
          <DisclosureSummary disclosure={disclosure} currency={disclosureCurrency} />
          <ReadinessSummary projection={projection} />
          <SourceSummary projection={projection} />
        </div>
      ) : null}
    </section>
  );
}

export function readinessUnavailableText(
  projection: CostGovernanceProjection,
  surface: CostReadinessSurface,
): string {
  const readiness = costReadiness(projection, surface);
  if (readiness?.reason) return readinessReasonLabel(readiness.reason);
  if (readiness?.state === "partial") return t("costGovernance.evidence.partialNoReason");
  if (readiness?.state === "unavailable") {
    return t("costGovernance.evidence.unavailableNoReason");
  }
  if (!readiness) return t("costGovernance.evidence.readinessNotReported");
  return t("costGovernance.evidence.readyNoRecords");
}

function DisclosureSummary({
  disclosure,
  currency,
}: {
  readonly disclosure: CostDisclosurePolicy | null;
  readonly currency: string;
}) {
  return (
    <section>
      <h2>{t("costGovernance.evidence.disclosureTitle")}</h2>
      {disclosure ? (
        <dl class="cost-evidence-facts">
          <div>
            <dt>{t("costGovernance.evidence.granularityLabel")}</dt>
            <dd>{enumLabel("granularity", disclosure.granularity)}</dd>
          </div>
          <div>
            <dt>{t("costGovernance.evidence.identityVisibilityLabel")}</dt>
            <dd>{enumLabel("identity", disclosure.identity_visibility)}</dd>
          </div>
          <div>
            <dt>{t("costGovernance.evidence.amountPrecisionLabel")}</dt>
            <dd>{enumLabel("precision", disclosure.amount_precision)}</dd>
          </div>
          <div>
            <dt>{t("costGovernance.evidence.roundingIncrement")}</dt>
            <dd>{currency
              ? formatCurrency(disclosure.rounding_increment, currency)
              : t("costGovernance.evidence.currencyIndependentIncrement", {
                amount: disclosure.rounding_increment.toLocaleString(costLocale()),
              })}</dd>
          </div>
          <div>
            <dt>{t("costGovernance.evidence.smallCellMinimum")}</dt>
            <dd>{disclosure.small_cell_minimum.toLocaleString(costLocale())}</dd>
          </div>
        </dl>
      ) : <p>{t("costGovernance.evidence.disclosureNotReported")}</p>}
    </section>
  );
}

function ReadinessSummary({
  projection,
}: {
  readonly projection: CostGovernanceProjection;
}) {
  return (
    <section>
      <h2>{t("costGovernance.evidence.readinessTitle")}</h2>
      <ul class="cost-readiness-list">
        {READINESS_SURFACES.map((surface) => (
          <ReadinessRow
            key={surface}
            surface={surface}
            readiness={costReadiness(projection, surface)}
          />
        ))}
      </ul>
    </section>
  );
}

function ReadinessRow({
  surface,
  readiness,
}: {
  readonly surface: CostReadinessSurface;
  readonly readiness: CostSurfaceReadiness | null;
}) {
  const state = readiness?.state ?? "unavailable";
  return (
    <li>
      <span>{t(`costGovernance.evidence.facets.${surface}`)}</span>
      <strong class={`cost-evidence-value is-${state}`}>{stateLabel(state)}</strong>
      <small>
        {readiness
          ? t("costGovernance.evidence.readinessCount", { count: readiness.record_count })
          : t("costGovernance.evidence.readinessNotReported")}
        {readiness?.reason ? (
          <>
            {" "}
            {readinessReasonLabel(readiness.reason)}
            {" "}
            <code>{readiness.reason}</code>
          </>
        ) : null}
      </small>
    </li>
  );
}

function SourceSummary({
  projection,
}: {
  readonly projection: CostGovernanceProjection;
}) {
  const sources = projection.evidence?.sources ?? [];
  const analyticsRun = projection.evidence?.latest_analytics_run ?? null;
  return (
    <section>
      <h2>{t("costGovernance.evidence.sourcesTitle")}</h2>
      {sources.length > 0 ? (
        <ul class="cost-source-list">
          {sources.map((source) => (
            <li key={source.source_authority}>
              <strong>{source.source_authority}</strong>
              <span class={`cost-evidence-value is-${source.state}`}>
                {stateLabel(source.state)}
              </span>
              <small>{formatEvidenceWindow(source.window_start_at, source.window_end_at)}</small>
              <small>{t("costGovernance.evidence.completePartial", {
                complete: source.complete_count,
                partial: source.partial_count,
              })}</small>
              {source.reason ? <code>{source.reason}</code> : null}
            </li>
          ))}
        </ul>
      ) : <p>{t("costGovernance.evidence.sourcesNotReported")}</p>}
      {analyticsRun ? (
        <details class="cost-analytics-run">
          <summary>{t("costGovernance.evidence.latestRun", {
            status: t(`costGovernance.evidence.runStates.${analyticsRun.status}`),
            time: formatTimestamp(analyticsRun.finished_at),
          })}</summary>
          <dl>
            <RunFact
              label={t("costGovernance.evidence.runVenue")}
              value={t(`costGovernance.evidence.venues.${analyticsRun.venue}`)}
            />
            <RunFact
              label={t("costGovernance.evidence.runWindow")}
              value={formatEvidenceWindow(
                analyticsRun.window_start_at,
                analyticsRun.window_end_at,
              )}
            />
            <RunFact
              label={t("costGovernance.evidence.runDuration")}
              value={`${formatTimestamp(analyticsRun.started_at)} - ${
                formatTimestamp(analyticsRun.finished_at)
              }`}
            />
            <RunFact
              label={t("costGovernance.evidence.runCounts")}
              value={t("costGovernance.evidence.runCountValues", {
                observations: analyticsRun.observation_count,
                trend: analyticsRun.trend_point_count,
                budgets: analyticsRun.budget_count,
                recommendations: analyticsRun.recommendation_count,
                utilization: analyticsRun.utilization_count,
              })}
            />
            <RunFact
              label={t("costGovernance.evidence.runIdentity")}
              value={analyticsRun.run_id}
            />
          </dl>
          {analyticsRun.limitations.length ? (
            <p>{t("costGovernance.evidence.runLimitations", {
              limitations: analyticsRun.limitations.join(", "),
            })}</p>
          ) : null}
          {analyticsRun.failure_reason ? (
            <p>{t("costGovernance.evidence.runFailure", {
              reason: analyticsRun.failure_reason,
            })}</p>
          ) : null}
        </details>
      ) : null}
    </section>
  );
}

function RunFact({ label, value }: { readonly label: string; readonly value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function freshnessLabel(value: "fresh" | "stale" | "unknown"): string {
  return t(`costGovernance.evidence.freshnessStates.${value}`);
}

function stateLabel(value: CostEvidenceState): string {
  return t(`costGovernance.evidence.states.${value}`);
}

function enumLabel(group: "granularity" | "identity" | "precision", value: string): string {
  return t(`costGovernance.evidence.${group}.${value}`);
}

function readinessReasonLabel(reason: CostReadinessReason): string {
  const key = `costGovernance.evidence.reasons.${reason}`;
  const localized = t(key);
  return localized === key
    ? t("costGovernance.evidence.reasonFallback")
    : localized;
}

function sourceCount(count: number): string {
  return count === 1
    ? t("costGovernance.evidence.sourceCountOne")
    : count > 1
    ? t("costGovernance.evidence.sourceCount", { count })
    : t("costGovernance.evidence.sourceCountNotReported");
}

function formatEvidenceWindow(start: string | null, end: string | null): string {
  if (!start || !end) return t("costGovernance.evidence.windowNotReported");
  return `${formatTimestamp(start)} - ${formatTimestamp(end)}`;
}

function formatTimestamp(value: string | null): string {
  if (!value) return t("costGovernance.evidence.notReported");
  const instant = new Date(value);
  if (Number.isNaN(instant.valueOf())) return t("costGovernance.evidence.notReported");
  return new Intl.DateTimeFormat(costLocale(), {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(instant);
}

function singleProjectionCurrency(
  projection: CostGovernanceProjection,
  summaryCurrency: string,
): string {
  if (summaryCurrency) return summaryCurrency;
  const currencies = new Set<string>();
  for (const item of projection.items) {
    if (typeof item["currency"] === "string" && item["currency"]) {
      currencies.add(item["currency"]);
    }
  }
  for (const recommendation of projection.analytics?.recommendations ?? []) {
    if (recommendation.currency) currencies.add(recommendation.currency);
  }
  return currencies.size === 1 ? [...currencies][0]! : "";
}
