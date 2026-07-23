import type { AutonomyPayload, MetricVsBaseline, VerticalSummary } from "../types";
import {
  DataTable,
  KpiCard,
  KpiGrid,
  StatusPill,
  UnavailableState,
  kpiEvidenceLabel,
  type Column,
} from "../components/ui";
import { getLocale } from "../i18n";
import { t } from "./i18n/analytics";
import { currentRoute, routeHref } from "../router";
import type { AnalyticsData } from "./analytics-data";

export const OUTCOME_KEYS = [
  "auto-resolution",
  "human-touchpoints",
  "mttr",
  "change-lead-time",
  "cost-per-resolved-event",
] as const;
export type OutcomeKey = (typeof OUTCOME_KEYS)[number];

interface OutcomeViewContract {
  readonly titleKey: string;
  readonly descriptionKey: string;
  readonly currentLabelKey: string;
  readonly analysisTitleKey: string;
  readonly analysisUnavailableKey: string;
  readonly breakdownTitleKey: string;
  readonly breakdownUnavailableKey: string;
  readonly measuredBreakdown: boolean;
}

export function outcomeViewContract(key: OutcomeKey): OutcomeViewContract {
  return {
    titleKey: `analytics.outcomes.views.${key}.title`,
    descriptionKey: `analytics.outcomes.views.${key}.description`,
    currentLabelKey: `analytics.outcomes.views.${key}.currentLabel`,
    analysisTitleKey: `analytics.outcomes.views.${key}.analysisTitle`,
    analysisUnavailableKey: `analytics.outcomes.views.${key}.analysisUnavailable`,
    breakdownTitleKey: `analytics.outcomes.views.${key}.breakdownTitle`,
    breakdownUnavailableKey: `analytics.outcomes.views.${key}.breakdownUnavailable`,
    measuredBreakdown: key === "auto-resolution",
  };
}

export function outcomeMetric(data: AutonomyPayload, key: OutcomeKey): MetricVsBaseline {
  if (key === "auto-resolution") return data.success.auto_resolution_rate;
  if (key === "human-touchpoints") return data.success.human_touchpoints_per_100;
  if (key === "mttr") return data.success.mttr_seconds;
  if (key === "cost-per-resolved-event") return data.success.cost_per_resolved_event_usd;
  return data.success.change_lead_time_seconds;
}

function duration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export function formatOutcomeMetric(value: number | null, key: OutcomeKey): string {
  if (value === null) return t("analytics.unavailable");
  if (key === "auto-resolution") return `${Math.round(value * 100)}%`;
  if (key === "human-touchpoints") return value.toFixed(1);
  if (key === "cost-per-resolved-event") return `$${value.toFixed(2)}`;
  return duration(value);
}

export function autoResolutionCounts(verticals: readonly VerticalSummary[]): {
  readonly observed: number;
  readonly resolved: number;
} {
  return verticals.reduce(
    (total, vertical) => ({
      observed: total.observed + vertical.events,
      resolved: total.resolved + vertical.auto_resolved,
    }),
    { observed: 0, resolved: 0 },
  );
}

export function OperatingOutcomeBody({
  data,
  active,
}: {
  readonly data: AnalyticsData;
  readonly active: OutcomeKey;
}) {
  const autonomy = data.autonomy!;
  const metric = outcomeMetric(autonomy, active);
  const contract = outcomeViewContract(active);
  const metricLabel = t(`analytics.metric.${active}`);
  const trend = autonomy.trend[active.replaceAll("-", "_")] ??
    (active === "auto-resolution" ? autonomy.trend.auto_resolution_rate : undefined);

  return (
    <div class="stack outcome-view">
      <header class="outcome-intro">
        <div>
          <h2>{t(contract.titleKey)}</h2>
          <p>{t(contract.descriptionKey)}</p>
        </div>
        <span>{t(`analytics.${metric.direction}Better`)}</span>
      </header>
      {active === "cost-per-resolved-event" ? <CostReferenceNotice /> : null}
      <EvidenceStrip autonomy={autonomy} />
      <OutcomeKpis autonomy={autonomy} metric={metric} active={active} contract={contract} />
      <div class="outcome-analysis-grid">
        <TrendChart values={trend ?? []} active={active} label={t("analytics.outcomes.trend", { metric: metricLabel })} />
        {active === "auto-resolution" ? (
          <GuardBoundary autonomy={autonomy} />
        ) : (
          <ProjectionGap heading={t(contract.analysisTitleKey)} message={t(contract.analysisUnavailableKey)} />
        )}
      </div>
      {contract.measuredBreakdown ? (
        <AutoResolutionBreakdown verticals={autonomy.verticals} />
      ) : (
        <ProjectionGap heading={t(contract.breakdownTitleKey)} message={t(contract.breakdownUnavailableKey)} />
      )}
      <OutcomeEvidenceLinks active={active} windowDays={autonomy.window_days} />
    </div>
  );
}

function EvidenceStrip({ autonomy }: { readonly autonomy: AutonomyPayload }) {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  return (
    <div class="analytics-evidence">
      <strong>{autonomy.synthetic ? t("analytics.simulated") : t("analytics.measured")}</strong>
      <span>{t("analytics.window", { days: autonomy.window_days })}</span>
      <span>{t("analytics.samples", { count: autonomy.sample_size.toLocaleString(locale) })}</span>
      <span>
        {autonomy.confidence === null
          ? t("analytics.confidenceUnavailable")
          : t("analytics.confidence", { value: Math.round(autonomy.confidence * 100) })}
      </span>
      <span>{t("overview.evidence.source", { source: autonomy.source.name })}</span>
      {autonomy.source.as_of ? <span>{t("overview.evidence.asOf", { time: autonomy.source.as_of })}</span> : null}
    </div>
  );
}

function OutcomeKpis({
  autonomy,
  metric,
  active,
  contract,
}: {
  readonly autonomy: AutonomyPayload;
  readonly metric: MetricVsBaseline;
  readonly active: OutcomeKey;
  readonly contract: OutcomeViewContract;
}) {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  const auditHref = (outcome?: string) => routeHref("audit", {
    params: { window: `${autonomy.window_days}d`, outcome },
  });
  if (active === "auto-resolution") {
    const counts = autoResolutionCounts(autonomy.verticals);
    return (
      <KpiGrid>
        <KpiCard
          evidenceState={metric.value === null ? "not-measured" : "measured"}
          href={auditHref("auto")}
          label={t(contract.currentLabelKey)}
          value={metric.value === null ? kpiEvidenceLabel("not-measured") : formatOutcomeMetric(metric.value, active)}
          hint={metric.value === null ? t("analytics.notMeasuredHint") : undefined}
        />
        <KpiCard
          evidenceState={metric.baseline === null ? "not-measured" : "measured"}
          href={auditHref("auto")}
          label={t("analytics.baseline")}
          value={metric.baseline === null ? t("analytics.outcomes.noBaseline") : formatOutcomeMetric(metric.baseline, active)}
          hint={metric.baseline === null ? t("analytics.outcomes.noBaselineHint") : undefined}
        />
        <KpiCard href={auditHref("auto")} label={t("analytics.outcomes.autoResolvedCount")} value={counts.resolved.toLocaleString(locale)} />
        <KpiCard href={auditHref()} label={t("analytics.outcomes.observedEventCount")} value={counts.observed.toLocaleString(locale)} />
      </KpiGrid>
    );
  }
  const hrefs: Readonly<Record<Exclude<OutcomeKey, "auto-resolution">, readonly [string, string, string, string]>> = {
    "human-touchpoints": [
      routeHref("hil-queue"),
      auditHref("hil"),
      routeHref("hil-queue"),
      auditHref("hil"),
    ],
    mttr: [
      routeHref("incidents", { params: { status: "resolved" } }),
      routeHref("reports"),
      routeHref("incidents", { params: { status: "resolved" } }),
      routeHref("reports"),
    ],
    "change-lead-time": [
      auditHref(),
      auditHref(),
      routeHref("promotion-gates"),
      auditHref(),
    ],
    "cost-per-resolved-event": [
      routeHref("llm-cost"),
      auditHref(),
      routeHref("llm-cost"),
      auditHref(),
    ],
  };
  const [currentHref, baselineHref, directionHref, sampleHref] = hrefs[active];
  return (
    <KpiGrid>
      <KpiCard
        evidenceState={metric.value === null ? "not-measured" : "measured"}
        href={currentHref}
        label={t(contract.currentLabelKey)}
        value={metric.value === null ? kpiEvidenceLabel("not-measured") : formatOutcomeMetric(metric.value, active)}
        hint={metric.value === null ? t("analytics.notMeasuredHint") : undefined}
      />
      <KpiCard
        evidenceState={metric.baseline === null ? "not-measured" : "measured"}
        href={baselineHref}
        label={t("analytics.baseline")}
        value={metric.baseline === null ? t("analytics.outcomes.noBaseline") : formatOutcomeMetric(metric.baseline, active)}
        hint={metric.baseline === null ? t("analytics.outcomes.noBaselineHint") : undefined}
      />
      <KpiCard href={directionHref} label={t("analytics.direction")} value={t(`analytics.${metric.direction}Better`)} />
      <KpiCard href={sampleHref} label={t("analytics.sampleSize")} value={autonomy.sample_size.toLocaleString(locale)} />
    </KpiGrid>
  );
}

function TrendChart({
  values,
  active,
  label,
}: {
  readonly values: readonly number[];
  readonly active: OutcomeKey;
  readonly label: string;
}) {
  if (values.length < 2) return <ProjectionGap heading={label} message={t("analytics.trendUnavailable")} />;
  const maximum = Math.max(...values);
  const minimum = Math.min(...values);
  const range = maximum - minimum || 1;
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * 100;
    const y = 36 - ((value - minimum) / range) * 32;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <figure class="analytics-trend">
      <figcaption>{label}</figcaption>
      <svg viewBox="0 0 100 40" role="img" aria-label={label} preserveAspectRatio="none">
        <polyline points={points} fill="none" stroke="currentColor" stroke-width="1.5" />
      </svg>
      <div class="analytics-trend-range muted">
        <span>{formatOutcomeMetric(minimum, active)}</span>
        <span>{formatOutcomeMetric(maximum, active)}</span>
      </div>
    </figure>
  );
}

function ProjectionGap({ heading, message }: { readonly heading: string; readonly message: string }) {
  return (
    <section class="analytics-panel outcome-projection-gap">
      <h3>{heading}</h3>
      <UnavailableState message={message} />
    </section>
  );
}

function GuardBoundary({ autonomy }: { readonly autonomy: AutonomyPayload }) {
  if (autonomy.guards.length === 0) {
    return <ProjectionGap heading={t("analytics.outcomes.guardBoundary")} message={t("analytics.outcomes.guardUnavailable")} />;
  }
  const columns: readonly Column<AutonomyPayload["guards"][number]>[] = [
    { key: "guard", header: t("analytics.guard"), render: (row) => t(`overview.guardFull.${row.key}`) },
    { key: "value", header: t("analytics.current"), render: (row) => `${(row.value * 100).toFixed(1)}%`, cellClass: "num" },
    {
      key: "status",
      header: t("analytics.status"),
      render: (row) => autonomy.synthetic
        ? <StatusPill kind="neutral" label={t("analytics.simulatedStatus")} />
        : <StatusPill kind={row.ok ? "success" : "danger"} label={t(row.ok ? "analytics.passing" : "analytics.blocked")} />,
    },
  ];
  return (
    <section class="analytics-panel">
      <h3>{t("analytics.outcomes.guardBoundary")}</h3>
      <DataTable columns={columns} rows={autonomy.guards} keyOf={(row) => row.key} />
    </section>
  );
}

function AutoResolutionBreakdown({ verticals }: { readonly verticals: readonly VerticalSummary[] }) {
  const params = Object.fromEntries(currentRoute().search.entries());
  const columns: readonly Column<VerticalSummary>[] = [
    {
      key: "vertical",
      header: t("analytics.verticalLabel"),
      render: (row) => <a href={routeHref("verticals", {
        segments: [verticalRouteSlug(row.key)],
        params,
      })}>{t(`overview.vertical.${row.key}`)}</a>,
    },
    { key: "events", header: t("analytics.events"), render: (row) => row.events, cellClass: "num" },
    { key: "resolved", header: t("analytics.autoResolved"), render: (row) => row.auto_resolved, cellClass: "num" },
    {
      key: "rate",
      header: t("analytics.resolutionRate"),
      render: (row) => row.events === 0 ? t("analytics.unavailable") : `${Math.round(row.auto_resolved / row.events * 100)}%`,
      cellClass: "num",
    },
    { key: "risks", header: t("analytics.openRisks"), render: (row) => row.open_risks, cellClass: "num" },
  ];
  return (
    <section class="analytics-panel">
      <h3>{t("analytics.outcomes.views.auto-resolution.breakdownTitle")}</h3>
      <DataTable columns={columns} rows={verticals} keyOf={(row) => row.key} />
    </section>
  );
}

function CostReferenceNotice() {
  return (
    <aside class="analytics-reference-note" role="note" aria-label={t("analytics.outcomes.costNoticeLabel")}>
      <span class="analytics-reference-icon" aria-hidden="true">i</span>
      <div>
        <strong>{t("analytics.outcomes.costNoticeTitle")}</strong>
        <p>{t("analytics.outcomes.costNoticeBody")}</p>
      </div>
    </aside>
  );
}

function OutcomeEvidenceLinks({ active, windowDays }: { readonly active: OutcomeKey; readonly windowDays: number }) {
  const audit = routeHref("audit", { params: { window: `${windowDays}d` } });
  const links: readonly (readonly [string, string])[] = active === "human-touchpoints"
    ? [[t("analytics.viewApprovals"), routeHref("hil-queue")], [t("analytics.viewAudit"), audit]]
    : active === "mttr"
      ? [[t("analytics.viewIncidents"), routeHref("incidents", { params: { status: "resolved" } })], [t("analytics.viewReports"), routeHref("reports")]]
      : active === "change-lead-time"
        ? [[t("analytics.viewAudit"), audit], [t("analytics.viewPromotion"), routeHref("promotion-gates")]]
        : active === "cost-per-resolved-event"
          ? [[t("analytics.viewLlmCost"), routeHref("llm-cost")], [t("analytics.viewAudit"), audit]]
          : [[t("analytics.viewAudit"), audit], [t("analytics.viewIncidents"), routeHref("incidents")]];
  return (
    <nav class="analytics-links" aria-label={t("analytics.relatedEvidence")}>
      {links.map(([label, href]) => <a key={href} href={href}>{label}<span aria-hidden="true">&rarr;</span></a>)}
    </nav>
  );
}

function verticalRouteSlug(payloadKey: string): string {
  if (payloadKey === "change_safety") return "change-safety";
  if (payloadKey === "cost") return "cost-governance";
  return payloadKey;
}
