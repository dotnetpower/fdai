import type { ComponentChildren } from "preact";
import type { AutonomyPayload, VerticalSummary } from "../types";
import { StatusPill, UnavailableState } from "../components/ui";
import { routeHref } from "../router";
import { t } from "./i18n/analytics";
import { formatUsd } from "./dashboard.model";
import type { ChaosResultSummary } from "./chaos-results-summary";

export type VerticalDisplayState = "measured" | "review" | "simulated" | "unavailable";
export type VerticalSlug = "resilience" | "change-safety" | "cost-governance";
export type VerticalPrimaryMetric = "auto-resolution" | "change-failure-rate" | "monthly-savings";

const VERTICAL_SLUGS: readonly VerticalSlug[] = [
  "resilience",
  "change-safety",
  "cost-governance",
];

interface VerticalOutcomeView {
  readonly slug: VerticalSlug;
  readonly vertical: VerticalSummary | null;
}

export function formatMeasuredSavings(value: number): string {
  return formatUsd(value);
}

export function verticalResolutionRate(vertical: VerticalSummary): number | null {
  return vertical.events > 0 ? vertical.auto_resolved / vertical.events : null;
}

/** Preserve zero savings only when at least one cost event was observed. */
export function verticalMonthlySavings(vertical: VerticalSummary): number | null {
  return vertical.events > 0 ? vertical.monthly_savings : null;
}

export function verticalDisplayState(
  vertical: VerticalSummary | null,
  synthetic: boolean,
): VerticalDisplayState {
  if (vertical === null) return "unavailable";
  if (synthetic) return "simulated";
  if (vertical.events === 0) return "unavailable";
  return vertical.open_risks > 0 ? "review" : "measured";
}

export function verticalPayloadKey(slug: string): string {
  if (slug === "change-safety") return "change_safety";
  if (slug === "cost-governance") return "cost";
  return slug;
}

export function verticalEvidenceKey(slug: VerticalSlug): string {
  return slug.replaceAll("-", "_");
}

export function verticalRouteSlug(payloadKey: string): string {
  if (payloadKey === "change_safety") return "change-safety";
  if (payloadKey === "cost") return "cost-governance";
  return payloadKey;
}

export function verticalPrimaryMetric(slug: VerticalSlug): VerticalPrimaryMetric {
  if (slug === "change-safety") return "change-failure-rate";
  if (slug === "cost-governance") return "monthly-savings";
  return "auto-resolution";
}

/** Keep every canonical domain visible without fabricating missing measurements. */
export function verticalOutcomeViews(
  verticals: readonly VerticalSummary[],
): readonly VerticalOutcomeView[] {
  const attributed = new Map(
    verticals
      .filter(isAttributedVertical)
      .map((vertical) => [verticalRouteSlug(vertical.key), vertical]),
  );
  return VERTICAL_SLUGS.map((slug) => ({
    slug,
    vertical: attributed.get(slug) ?? null,
  }));
}

interface Props {
  readonly autonomy: AutonomyPayload | null;
  readonly chaosResults: ChaosResultSummary | null;
  readonly context: Readonly<Record<string, string>>;
  readonly evidence: ComponentChildren;
}

export function VerticalOutcomesBody({ autonomy, chaosResults, context, evidence }: Props) {
  const views = verticalOutcomeViews(autonomy?.verticals ?? []);
  const hasMissingVerticals = views.some(({ vertical }) => vertical === null);
  const hasUnattributedEvents = autonomy !== null
    && !autonomy.synthetic
    && autonomy.attribution.unattributed_events > 0;
  return (
    <div class="vertical-outcomes stack">
      {autonomy?.synthetic ? (
        <section class="vertical-boundary-banner">
          <strong>{t("analytics.verticals.simulatedTitle")}</strong>
          <span>{t("analytics.simulatedEvidenceBoundary")}</span>
        </section>
      ) : null}
      {autonomy ? <CostReferenceNotice /> : null}
      {evidence}
      {autonomy === null ? (
        <UnavailableState
          evidenceState="not-connected"
          message={t("analytics.autonomyUnavailable")}
        />
      ) : hasUnattributedEvents ? (
        <UnavailableState
          evidenceState="not-connected"
          message={t("analytics.verticals.attributionIncomplete", {
            count: autonomy.attribution.unattributed_events,
          })}
        />
      ) : hasMissingVerticals ? (
        <UnavailableState
          evidenceState="not-connected"
          message={t("analytics.verticals.attributionUnavailable")}
        />
      ) : null}
      <section class="vertical-portfolio-section">
        <header class="vertical-section-head">
          <div>
            <h3>{t("analytics.verticals.signalsTitle")}</h3>
            <p>{t("analytics.verticals.signalsSubtitle")}</p>
          </div>
        </header>
        <VerticalSignalGrid
          chaosResults={chaosResults}
          context={context}
          synthetic={autonomy?.synthetic ?? false}
          views={views}
        />
      </section>
      <CrossVerticalComparison autonomy={autonomy} context={context} views={views} />
      <EvidenceContracts autonomy={autonomy} chaosResults={chaosResults} context={context} views={views} />
    </div>
  );
}

function VerticalSignalGrid({
  chaosResults,
  context,
  synthetic,
  views,
}: {
  readonly chaosResults: ChaosResultSummary | null;
  readonly context: Readonly<Record<string, string>>;
  readonly synthetic: boolean;
  readonly views: readonly VerticalOutcomeView[];
}) {
  return (
    <section class="vertical-summary-grid" aria-label={t("analytics.verticals.summaryLabel")}>
      {views.map(({ slug, vertical }) => (
        <VerticalSignalCard
          chaosResults={chaosResults}
          context={context}
          key={slug}
          slug={slug}
          synthetic={synthetic}
          vertical={vertical}
        />
      ))}
    </section>
  );
}

function VerticalSignalCard({
  chaosResults,
  context,
  slug,
  synthetic,
  vertical,
}: {
  readonly chaosResults: ChaosResultSummary | null;
  readonly context: Readonly<Record<string, string>>;
  readonly slug: VerticalSlug;
  readonly synthetic: boolean;
  readonly vertical: VerticalSummary | null;
}) {
  const primaryMetric = verticalPrimaryMetric(slug);
  const destination = verticalDestination(slug, synthetic, context);
  return (
    <article class="vertical-summary">
      <span class="vertical-summary-head">
        <strong>{t(`analytics.vertical.${slug}`)}</strong>
        <VerticalStatePill state={verticalDisplayState(vertical, synthetic)} />
      </span>
      <PrimarySignal metric={primaryMetric} vertical={vertical} />
      <p class="vertical-summary-purpose">{t(`analytics.verticals.card.${slug}.purpose`)}</p>
      <dl><DomainFacts chaosResults={chaosResults} slug={slug} vertical={vertical} /></dl>
      <a class="vertical-summary-link" href={destination}>
        {t(`analytics.verticals.card.${slug}.link`)}<span aria-hidden="true">&rarr;</span>
      </a>
    </article>
  );
}

function PrimarySignal({
  metric,
  vertical,
}: {
  readonly metric: VerticalPrimaryMetric;
  readonly vertical: VerticalSummary | null;
}) {
  if (vertical === null) {
    return (
      <span class="vertical-primary-signal is-unavailable" data-evidence-state="not-connected">
        <b>{t("analytics.unavailable")}</b>
        <small>{t(`analytics.verticals.primary.${primaryMetricKey(metric)}`)}</small>
      </span>
    );
  }
  if (metric === "monthly-savings") {
    const savings = verticalMonthlySavings(vertical);
    return (
      <span
        class={`vertical-primary-signal${savings === null ? " is-unavailable" : ""}`}
        data-evidence-state={savings === null ? "insufficient-sample" : "measured"}
      >
        <b>{savings === null ? t("analytics.unavailable") : formatMeasuredSavings(savings)}</b>
        <small>{t("analytics.verticals.primary.monthlySavings")}</small>
      </span>
    );
  }
  if (metric === "change-failure-rate") {
    return <span class="vertical-primary-signal is-unavailable" data-evidence-state="not-connected"><b>{t("analytics.unavailable")}</b><small>{t("analytics.verticals.primary.changeFailureRate")}</small></span>;
  }
  const rate = verticalResolutionRate(vertical);
  return <span class={`vertical-primary-signal${rate === null ? " is-unavailable" : ""}`} data-evidence-state={rate === null ? "insufficient-sample" : "measured"}><b>{rate === null ? t("analytics.unavailable") : formatRate(rate)}</b><small>{t("analytics.verticals.primary.autoResolution")}</small></span>;
}

function DomainFacts({
  chaosResults,
  slug,
  vertical,
}: {
  readonly chaosResults: ChaosResultSummary | null;
  readonly slug: VerticalSlug;
  readonly vertical: VerticalSummary | null;
}) {
  if (slug === "resilience") {
    const reportHref = routeHref("reports", { segments: ["chaos-enforce-results"] });
    return <><VerticalFact href={chaosResults ? reportHref : undefined} label={t("analytics.verticals.fact.validatedExperiments")} value={chaosResults?.validated} /><VerticalFact label={t("analytics.verticals.fact.medianMttr")} /><VerticalFact href={chaosResults ? reportHref : undefined} label={t("analytics.verticals.fact.rollbackPaths")} value={chaosResults?.reverted} /></>;
  }
  if (slug === "change-safety") {
    return <><VerticalFact label={t("analytics.verticals.fact.rollbackSuccess")} /><VerticalFact label={t("analytics.verticals.fact.medianLeadTime")} /><VerticalFact label={t("analytics.verticals.fact.promotionGuards")} /></>;
  }
  return <><VerticalFact label={t("analytics.verticals.fact.observedCostEvents")} value={vertical?.events} /><VerticalFact label={t("analytics.openRisks")} value={vertical?.open_risks} /><VerticalFact label={t("analytics.verticals.fact.budgetVariance")} /></>;
}

function CrossVerticalComparison({
  autonomy,
  context,
  views,
}: {
  readonly autonomy: AutonomyPayload | null;
  readonly context: Readonly<Record<string, string>>;
  readonly views: readonly VerticalOutcomeView[];
}) {
  return (
    <section class="vertical-comparison">
      <header class="vertical-comparison-head"><div><h3>{t("analytics.verticals.comparison")}</h3><p>{t("analytics.verticals.comparisonSubtitle")}</p></div></header>
      <div class="vertical-comparison-scroll">
        <table class="vertical-comparison-table">
          <caption class="sr-only">{t("analytics.verticals.comparison")}</caption>
          <thead>
            <tr class="vertical-comparison-row is-header">
              <th scope="col">{t("analytics.verticalLabel")}</th><th scope="col">{t("analytics.events")}</th><th scope="col">{t("analytics.autoResolved")}</th><th scope="col">{t("analytics.resolutionRate")}</th><th scope="col">{t("analytics.openRisks")}</th><th scope="col">{t("analytics.monthlySavings")}</th>
            </tr>
          </thead>
          <tbody>
            {views.map(({ slug, vertical }) => {
              const rate = vertical === null ? null : verticalResolutionRate(vertical);
              const savings = vertical === null ? null : verticalMonthlySavings(vertical);
              const unavailable = t("analytics.unavailable");
              return (
                <tr class="vertical-comparison-row" key={slug}>
                  <th scope="row">
                    <a href={verticalDestination(slug, autonomy?.synthetic ?? false, context)}>
                      {t(`analytics.vertical.${slug}`)}
                    </a>
                  </th>
                  <td class={vertical === null ? "is-unavailable" : undefined}>{vertical?.events ?? unavailable}</td>
                  <td class={vertical === null ? "is-unavailable" : undefined}>{vertical?.auto_resolved ?? unavailable}</td>
                  <td class={rate === null ? "is-unavailable" : undefined}>{rate === null ? unavailable : formatRate(rate)}</td>
                  <td class={vertical === null ? "is-unavailable" : undefined}>{vertical?.open_risks ?? unavailable}</td>
                  <td class={savings === null ? "is-unavailable" : undefined}>{savings === null ? unavailable : formatMeasuredSavings(savings)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function EvidenceContracts({
  autonomy,
  chaosResults,
  context,
  views,
}: {
  readonly autonomy: AutonomyPayload | null;
  readonly chaosResults: ChaosResultSummary | null;
  readonly context: Readonly<Record<string, string>>;
  readonly views: readonly VerticalOutcomeView[];
}) {
  return (
    <section class="vertical-contracts">
      <header class="vertical-section-head"><div><h3>{t("analytics.verticals.contractsTitle")}</h3><p>{t("analytics.verticals.contractsSubtitle")}</p></div></header>
      <div class="vertical-contract-list">
        {views.map(({ slug, vertical }) => (
          <a href={slug === "resilience" && chaosResults
            ? routeHref("reports", { segments: ["chaos-enforce-results"] })
            : verticalDestination(slug, autonomy?.synthetic ?? false, context)} key={slug}>
            <strong>{t(`analytics.vertical.${slug}`)}</strong>
            <span>{slug === "resilience" && chaosResults
              ? t("analytics.verticals.contract.resilience.chaosSource", { source: chaosResults.source })
              : vertical === null || autonomy === null
              ? t("analytics.verticals.contractUnavailable")
              : t(`analytics.verticals.contract.${slug}.source`, { source: autonomy.source.name })}</span>
            <span>{slug === "resilience" && chaosResults
              ? t("analytics.verticals.contract.resilience.chaosMeasures")
              : t(`analytics.verticals.contract.${slug}.measures`)}</span>
            <small>{slug === "resilience" && chaosResults?.asOf
              ? t("overview.evidence.asOf", { time: chaosResults.asOf })
              : vertical !== null && autonomy?.source.as_of
              ? t("overview.evidence.asOf", { time: autonomy.source.as_of })
              : t("analytics.unavailable")}</small>
          </a>
        ))}
      </div>
      <nav class="analytics-links" aria-label={t("analytics.relatedEvidence")}><a href={routeHref("incidents")}>{t("analytics.viewIncidents")}</a><a href={routeHref("audit", { params: { window: autonomy ? `${autonomy.window_days}d` : null } })}>{t("analytics.viewAudit")}</a></nav>
    </section>
  );
}

function CostReferenceNotice() {
  return <aside class="analytics-reference-note" role="note" aria-label={t("analytics.outcomes.costNoticeLabel")}><span class="analytics-reference-icon" aria-hidden="true">i</span><div><strong>{t("analytics.outcomes.costNoticeTitle")}</strong><p>{t("analytics.outcomes.costNoticeBody")}</p></div></aside>;
}

function VerticalStatePill({ state }: { readonly state: VerticalDisplayState }) {
  const kind = state === "review" ? "warning" : state === "measured" ? "success" : "neutral";
  return <StatusPill kind={kind} label={t(`analytics.verticals.state.${state}`)} />;
}

function VerticalFact({ href, label, value }: { readonly href?: string | undefined; readonly label: string; readonly value?: string | number | undefined }) {
  return <div><dt>{label}</dt><dd class={value === undefined ? "is-unavailable" : undefined}>{href && value !== undefined ? <a href={href}>{value}</a> : value ?? t("analytics.unavailable")}</dd></div>;
}

function verticalDestination(slug: VerticalSlug, synthetic: boolean, context: Readonly<Record<string, string>>): string {
  const verticalKey = synthetic ? null : verticalEvidenceKey(slug);
  if (slug === "resilience") return routeHref("incidents", { params: { ...context, vertical: verticalKey } });
  if (slug === "change-safety") {
    return routeHref("promotion-gates", { params: { ...context, vertical: null } });
  }
  return routeHref("audit", { params: { ...context, vertical: verticalKey } });
}

function primaryMetricKey(metric: VerticalPrimaryMetric): string {
  if (metric === "change-failure-rate") return "changeFailureRate";
  if (metric === "monthly-savings") return "monthlySavings";
  return "autoResolution";
}

function formatRate(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

function isAttributedVertical(vertical: VerticalSummary): boolean {
  return vertical.key !== "unattributed";
}
