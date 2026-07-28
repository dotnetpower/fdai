import type { ComponentChildren } from "preact";
import type { AutonomyPayload, VerticalSummary } from "../types";
import { StatusPill } from "../components/ui";
import { routeHref } from "../router";
import { t } from "./i18n/analytics";
import { formatUsd } from "./dashboard.model";

export type VerticalDisplayState = "measured" | "review" | "simulated" | "unavailable";
export type VerticalSlug = "resilience" | "change-safety" | "cost-governance";
export type VerticalPrimaryMetric = "auto-resolution" | "change-failure-rate" | "monthly-savings";

export function formatMeasuredSavings(value: number): string {
  return formatUsd(value);
}

export function verticalResolutionRate(vertical: VerticalSummary): number | null {
  return vertical.events > 0 ? vertical.auto_resolved / vertical.events : null;
}

export function verticalDisplayState(
  vertical: VerticalSummary,
  synthetic: boolean,
): VerticalDisplayState {
  if (synthetic) return "simulated";
  if (vertical.events === 0) return "unavailable";
  return vertical.open_risks > 0 ? "review" : "measured";
}

export function verticalPayloadKey(slug: string): string {
  if (slug === "change-safety") return "change_safety";
  if (slug === "cost-governance") return "cost";
  return slug;
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

interface Props {
  readonly autonomy: AutonomyPayload;
  readonly context: Readonly<Record<string, string>>;
  readonly evidence: ComponentChildren;
}

export function VerticalOutcomesBody({ autonomy, context, evidence }: Props) {
  return (
    <div class="vertical-outcomes stack">
      {autonomy.synthetic ? (
        <section class="vertical-boundary-banner">
          <strong>{t("analytics.verticals.simulatedTitle")}</strong>
          <span>{t("analytics.simulatedEvidenceBoundary")}</span>
        </section>
      ) : null}
      <CostReferenceNotice />
      {evidence}
      <section class="vertical-portfolio-section">
        <header class="vertical-section-head">
          <div>
            <h3>{t("analytics.verticals.signalsTitle")}</h3>
            <p>{t("analytics.verticals.signalsSubtitle")}</p>
          </div>
        </header>
        <VerticalSignalGrid autonomy={autonomy} context={context} />
      </section>
      <CrossVerticalComparison autonomy={autonomy} context={context} />
      <EvidenceContracts autonomy={autonomy} context={context} />
    </div>
  );
}

function VerticalSignalGrid({ autonomy, context }: { readonly autonomy: AutonomyPayload; readonly context: Readonly<Record<string, string>> }) {
  return (
    <section class="vertical-summary-grid" aria-label={t("analytics.verticals.summaryLabel")}>
      {autonomy.verticals.filter(isAttributedVertical).map((vertical) => (
        <VerticalSignalCard autonomy={autonomy} context={context} key={vertical.key} vertical={vertical} />
      ))}
    </section>
  );
}

function VerticalSignalCard({ autonomy, context, vertical }: { readonly autonomy: AutonomyPayload; readonly context: Readonly<Record<string, string>>; readonly vertical: VerticalSummary }) {
  const slug = verticalRouteSlug(vertical.key) as VerticalSlug;
  const primaryMetric = verticalPrimaryMetric(slug);
  const destination = verticalDestination(slug, vertical, autonomy.synthetic, context);
  return (
    <article class="vertical-summary">
      <span class="vertical-summary-head">
        <strong>{t(`analytics.vertical.${slug}`)}</strong>
        <VerticalStatePill state={verticalDisplayState(vertical, autonomy.synthetic)} />
      </span>
      <PrimarySignal metric={primaryMetric} vertical={vertical} />
      <p class="vertical-summary-purpose">{t(`analytics.verticals.card.${slug}.purpose`)}</p>
      <dl><DomainFacts slug={slug} vertical={vertical} /></dl>
      <a class="vertical-summary-link" href={destination}>
        {t(`analytics.verticals.card.${slug}.link`)}<span aria-hidden="true">&rarr;</span>
      </a>
    </article>
  );
}

function PrimarySignal({ metric, vertical }: { readonly metric: VerticalPrimaryMetric; readonly vertical: VerticalSummary }) {
  if (metric === "monthly-savings") {
    return <span class="vertical-primary-signal"><b>{formatMeasuredSavings(vertical.monthly_savings)}</b><small>{t("analytics.verticals.primary.monthlySavings")}</small></span>;
  }
  if (metric === "change-failure-rate") {
    return <span class="vertical-primary-signal is-unavailable" data-evidence-state="not-connected"><b>{t("analytics.unavailable")}</b><small>{t("analytics.verticals.primary.changeFailureRate")}</small></span>;
  }
  const rate = verticalResolutionRate(vertical);
  return <span class={`vertical-primary-signal${rate === null ? " is-unavailable" : ""}`} data-evidence-state={rate === null ? "insufficient-sample" : "measured"}><b>{rate === null ? t("analytics.unavailable") : formatRate(rate)}</b><small>{t("analytics.verticals.primary.autoResolution")}</small></span>;
}

function DomainFacts({ slug, vertical }: { readonly slug: VerticalSlug; readonly vertical: VerticalSummary }) {
  if (slug === "resilience") {
    return <><VerticalFact label={t("analytics.verticals.fact.recoveryDrills")} /><VerticalFact label={t("analytics.verticals.fact.medianMttr")} /><VerticalFact label={t("analytics.verticals.fact.rollbackPaths")} /></>;
  }
  if (slug === "change-safety") {
    return <><VerticalFact label={t("analytics.verticals.fact.rollbackSuccess")} /><VerticalFact label={t("analytics.verticals.fact.medianLeadTime")} /><VerticalFact label={t("analytics.verticals.fact.promotionGuards")} /></>;
  }
  return <><VerticalFact label={t("analytics.verticals.fact.observedCostEvents")} value={vertical.events} /><VerticalFact label={t("analytics.openRisks")} value={vertical.open_risks} /><VerticalFact label={t("analytics.verticals.fact.budgetVariance")} /></>;
}

function CrossVerticalComparison({ autonomy, context }: { readonly autonomy: AutonomyPayload; readonly context: Readonly<Record<string, string>> }) {
  return (
    <section class="vertical-comparison">
      <header class="vertical-comparison-head"><div><h3>{t("analytics.verticals.comparison")}</h3><p>{t("analytics.verticals.comparisonSubtitle")}</p></div></header>
      <div class="vertical-comparison-table" role="table" aria-label={t("analytics.verticals.comparison")}>
        <div class="vertical-comparison-row is-header" role="row">
          <span role="columnheader">{t("analytics.verticalLabel")}</span><span role="columnheader">{t("analytics.events")}</span><span role="columnheader">{t("analytics.autoResolved")}</span><span role="columnheader">{t("analytics.resolutionRate")}</span><span role="columnheader">{t("analytics.openRisks")}</span><span role="columnheader">{t("analytics.monthlySavings")}</span>
        </div>
        {autonomy.verticals.filter(isAttributedVertical).map((vertical) => {
          const slug = verticalRouteSlug(vertical.key) as VerticalSlug;
          const rate = verticalResolutionRate(vertical);
          return (
            <a class="vertical-comparison-row" href={verticalDestination(slug, vertical, autonomy.synthetic, context)} role="row" key={vertical.key}>
              <strong role="cell">{t(`analytics.vertical.${slug}`)}</strong><span role="cell">{vertical.events}</span><span role="cell">{vertical.auto_resolved}</span><span role="cell" class={rate === null ? "is-unavailable" : undefined}>{rate === null ? t("analytics.unavailable") : formatRate(rate)}</span><span role="cell">{vertical.open_risks}</span><span role="cell">{formatMeasuredSavings(vertical.monthly_savings)}</span>
            </a>
          );
        })}
      </div>
    </section>
  );
}

function EvidenceContracts({ autonomy, context }: { readonly autonomy: AutonomyPayload; readonly context: Readonly<Record<string, string>> }) {
  return (
    <section class="vertical-contracts">
      <header class="vertical-section-head"><div><h3>{t("analytics.verticals.contractsTitle")}</h3><p>{t("analytics.verticals.contractsSubtitle")}</p></div></header>
      <div class="vertical-contract-list">
        {autonomy.verticals.filter(isAttributedVertical).map((vertical) => {
          const slug = verticalRouteSlug(vertical.key) as VerticalSlug;
          return (
            <a href={verticalDestination(slug, vertical, autonomy.synthetic, context)} key={vertical.key}>
              <strong>{t(`analytics.vertical.${slug}`)}</strong><span>{t(`analytics.verticals.contract.${slug}.source`, { source: autonomy.source.name })}</span><span>{t(`analytics.verticals.contract.${slug}.measures`)}</span><small>{autonomy.source.as_of ? t("overview.evidence.asOf", { time: autonomy.source.as_of }) : t("analytics.unavailable")}</small>
            </a>
          );
        })}
      </div>
      <nav class="analytics-links" aria-label={t("analytics.relatedEvidence")}><a href={routeHref("incidents")}>{t("analytics.viewIncidents")}</a><a href={routeHref("audit", { params: { window: `${autonomy.window_days}d` } })}>{t("analytics.viewAudit")}</a></nav>
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

function VerticalFact({ label, value }: { readonly label: string; readonly value?: string | number }) {
  return <div><dt>{label}</dt><dd class={value === undefined ? "is-unavailable" : undefined}>{value ?? t("analytics.unavailable")}</dd></div>;
}

function verticalDestination(slug: VerticalSlug, vertical: VerticalSummary, synthetic: boolean, context: Readonly<Record<string, string>>): string {
  const verticalKey = synthetic ? null : vertical.key;
  if (slug === "resilience") return routeHref("incidents", { params: { ...context, vertical: verticalKey } });
  if (slug === "change-safety") return routeHref("promotion-gates", { params: { ...context, vertical: verticalKey } });
  return routeHref("audit", { params: { ...context, vertical: verticalKey } });
}

function formatRate(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

function isAttributedVertical(vertical: VerticalSummary): boolean {
  return vertical.key !== "unattributed";
}
