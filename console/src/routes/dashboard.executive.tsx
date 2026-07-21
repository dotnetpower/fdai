import type { AutonomyPayload, DashboardKpi, MetricVsBaseline } from "../types";
import { KpiCard, KpiGrid } from "../components/ui";
import { getLocale, t } from "../i18n";
import { routeHref } from "../router";
import type { OverviewHealth } from "./dashboard.model";

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

function improvementFactor(metric: MetricVsBaseline): number | null {
  if (metric.baseline === null || metric.value === null || metric.baseline <= 0 || metric.value <= 0) return null;
  return metric.direction === "higher"
    ? metric.value / metric.baseline
    : metric.baseline / metric.value;
}

function formatTimestamp(value: string): string {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

function TrendSpark({
  series,
  label,
}: {
  readonly series: readonly number[];
  readonly label: string;
}) {
  const width = 128;
  const height = 30;
  const maximum = Math.max(...series);
  const minimum = Math.min(...series);
  const range = maximum - minimum || 1;
  const points = series
    .map((value, index) => {
      const x = (index / (series.length - 1)) * width;
      const y = height - ((value - minimum) / range) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const first = series[0] ?? 0;
  const last = series[series.length - 1] ?? 0;
  const deltaPp = Math.round((last - first) * 100);
  const summary = t("overview.trend.summary", {
    start: `${(first * 100).toFixed(1)}%`,
    end: `${(last * 100).toFixed(1)}%`,
    delta: `${deltaPp >= 0 ? "+" : ""}${deltaPp}pp`,
  });
  return (
    <div class="overview-trend">
      <span class="overview-trend-label muted">{label}</span>
      <span class="sr-only">{summary}</span>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width={width}
        height={height}
        class="overview-trend-svg"
        aria-hidden="true"
        preserveAspectRatio="none"
      >
        <polyline
          points={points}
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linejoin="round"
          stroke-linecap="round"
        />
      </svg>
      <span class={`overview-trend-delta ${deltaPp >= 0 ? "up" : "down"}`}>
        {deltaPp >= 0 ? "+" : ""}
        {deltaPp}pp
      </span>
    </div>
  );
}

export function ExecutiveStatus({
  health,
  kpi,
  autonomy,
  attentionCount,
  policyEscapes,
}: {
  readonly health: OverviewHealth;
  readonly kpi: DashboardKpi;
  readonly autonomy: AutonomyPayload | null;
  readonly attentionCount: number;
  readonly policyEscapes: number | null;
}) {
  const trend = autonomy?.trend.auto_resolution_rate;
  const statusTitle =
    health === "healthy"
      ? t("overview.status.healthy")
      : health === "attention"
        ? t("overview.status.attention")
        : t("overview.status.unknown");
  const sampleLocale = getLocale() === "ko" ? "ko-KR" : "en-US";
  return (
    <a
      href={routeHref("control-assurance")}
      class={`overview-status overview-status-${health}`}
      aria-label={t("overview.status.linkLabel", {
        state: statusTitle,
        count: attentionCount,
      })}
    >
      <div class="overview-status-copy">
        <span class="overview-status-kicker">{t("overview.status.label")}</span>
        <div class="overview-status-heading">
          <h3>{statusTitle}</h3>
          {attentionCount > 0 ? (
            <span class="overview-attention-count">
              {t("overview.status.signals", { count: attentionCount })}
            </span>
          ) : null}
        </div>
        <p class="overview-status-summary">
          {autonomy
            ? t(autonomy.synthetic ? "overview.status.simulatedSummary" : "overview.status.summary", {
                rate: autonomy.success.auto_resolution_rate.value === null
                  ? t("overview.evidence.unavailable")
                  : Math.round(autonomy.success.auto_resolution_rate.value * 100),
                hil: kpi.hil_pending,
                escapes: policyEscapes ?? t("overview.evidence.unavailable"),
              })
            : t("overview.status.fallback", {
                events: kpi.event_count,
                hil: kpi.hil_pending,
              })}
        </p>
        <div class="overview-status-meta">
          {autonomy ? (
            <span class="overview-evidence-badge">
              {t(
                autonomy.synthetic
                  ? "overview.evidence.simulatedWindow"
                  : "overview.evidence.measuredWindow",
                {
                  days: autonomy.window_days,
                  samples: autonomy.sample_size.toLocaleString(sampleLocale),
                },
              )}
            </span>
          ) : (
            <span class="overview-evidence-badge">{t("overview.evidence.unavailable")}</span>
          )}
          {autonomy?.confidence !== null && autonomy?.confidence !== undefined ? (
            <span>{t("overview.hero.confidence", { pct: Math.round(autonomy.confidence * 100) })}</span>
          ) : null}
          {kpi.last_recorded_at ? (
            <span>{t("overview.status.auditCurrent", { time: formatTimestamp(kpi.last_recorded_at) })}</span>
          ) : null}
        </div>
      </div>
      {trend && trend.length >= 2 ? (
        <TrendSpark series={trend} label={t("overview.trend.autoRes")} />
      ) : null}
    </a>
  );
}

export function SuccessMetrics({
  success,
  synthetic,
  windowDays,
  sourceName,
}: {
  readonly success: AutonomyPayload["success"];
  readonly synthetic: boolean;
  readonly windowDays: number;
  readonly sourceName: string;
}) {
  const evidence = t(
    synthetic ? "overview.evidence.simulated" : "overview.evidence.measured",
  );
  const metrics = [
    ["autoRes", "auto-resolution", percentageMetric(success.auto_resolution_rate.value), success.auto_resolution_rate, percentageMetric(success.auto_resolution_rate.baseline)],
    ["touchpoints", "human-touchpoints", decimalMetric(success.human_touchpoints_per_100.value), success.human_touchpoints_per_100, decimalMetric(success.human_touchpoints_per_100.baseline)],
    ["mttr", "mttr", durationMetric(success.mttr_seconds.value), success.mttr_seconds, durationMetric(success.mttr_seconds.baseline)],
    ["leadTime", "change-lead-time", durationMetric(success.change_lead_time_seconds.value), success.change_lead_time_seconds, durationMetric(success.change_lead_time_seconds.baseline)],
    ["cost", "cost-per-resolved-event", currencyMetric(success.cost_per_resolved_event_usd.value), success.cost_per_resolved_event_usd, currencyMetric(success.cost_per_resolved_event_usd.baseline)],
  ] as const;
  return (
    <section class="overview-metrics" aria-label={t("overview.metric.groupLabel")}>
      {metrics.map(([key, slug, value, metric, baseline]) => (
        <SuccessMetric
          key={key}
          href={routeHref("operating-outcomes", { segments: [slug] })}
          label={t(`overview.metric.${key}`)}
          value={value}
          metric={metric}
          baselineText={baseline}
          evidence={evidence}
          windowDays={windowDays}
          sourceName={sourceName}
        />
      ))}
    </section>
  );
}

function SuccessMetric({
  label,
  value,
  metric,
  baselineText,
  evidence,
  windowDays,
  sourceName,
  href,
}: {
  readonly label: string;
  readonly value: string;
  readonly metric: MetricVsBaseline;
  readonly baselineText: string;
  readonly evidence: string;
  readonly windowDays: number;
  readonly sourceName: string;
  readonly href: string;
}) {
  const factor = improvementFactor(metric);
  return (
    <a href={href} class="card overview-metric overview-drill-card">
      <span class="overview-metric-label">{label}</span>
      <span class="overview-metric-value">{value}</span>
      <span class="overview-metric-evidence">
        {evidence} - {t("overview.evidence.window", { days: windowDays })} - {t("overview.evidence.source", { source: sourceName })}
      </span>
      <span class="overview-metric-sub muted">
        {t("overview.metric.vsBaseline", { baseline: baselineText })}
        {factor !== null ? (
          <span class="overview-metric-factor"> {factor.toFixed(1)}x</span>
        ) : null}
      </span>
    </a>
  );
}

export function LeadingIndicators({
  leading,
  sourceName,
}: {
  readonly leading: AutonomyPayload["leading"];
  readonly sourceName: string;
}) {
  const indicators = [
    ["disagreement", leading.mixed_model_disagreement_rate],
    ["verifier", leading.verifier_failure_rate],
    ["divergence", leading.shadow_divergence_rate],
  ] as const;
  return (
    <section class="stack-section" aria-labelledby="overview-leading-title">
      <h3 id="overview-leading-title" class="section-title">{t("overview.leading.title")}</h3>
      <KpiGrid>
        {indicators.map(([key, metric]) => (
          <a
            key={key}
            class="overview-kpi-link"
            href={routeHref("trust-routing", { segments: ["t2"], params: { indicator: key } })}
          >
            <KpiCard
              label={t(`overview.leading.${key}`)}
              value={percentageMetric(metric.value)}
              hint={`${t("overview.metric.vsBaseline", { baseline: percentageMetric(metric.baseline) })} - ${t("overview.evidence.source", { source: sourceName })}`}
              tone={metric.value === null || metric.baseline === null ? "default" : metric.value <= metric.baseline ? "positive" : "warning"}
            />
          </a>
        ))}
      </KpiGrid>
    </section>
  );
}

export function MeasurementUnavailable() {
  return (
    <div class="state-block state-unavailable" role="status">
      <strong>{t("overview.evidence.unavailable")}</strong>
      <span>{t("overview.evidence.unavailableHint")}</span>
    </div>
  );
}

export function AgentOrganization({
  autonomy,
  hilPending,
}: {
  readonly autonomy: AutonomyPayload;
  readonly hilPending: number;
}) {
  const roles = [
    ["sense", "Huginn"],
    ["advise", t("overview.organization.specialists")],
    ["arbitrate", "Odin"],
    ["judge", "Forseti"],
    ["approve", "Var"],
    ["execute", "Thor"],
    ["audit", "Saga"],
  ] as const;
  return (
    <section class="overview-organization" aria-labelledby="overview-organization-title">
      <div class="overview-organization-copy">
        <span class="overview-panel-kicker">{t("overview.organization.label")}</span>
        <a href={routeHref("agents")} class="overview-organization-summary">
          <h3 id="overview-organization-title">{t("overview.organization.title")}</h3>
          <p>
            {t(autonomy.synthetic ? "overview.organization.simulatedSummary" : "overview.organization.summary", {
              rate: autonomy.success.auto_resolution_rate.value === null
                ? t("overview.evidence.unavailable")
                : Math.round(autonomy.success.auto_resolution_rate.value * 100),
              hil: hilPending,
            })}
          </p>
        </a>
        <span class="muted overview-organization-evidence">
          {t(
            autonomy.synthetic
              ? "overview.organization.simulated"
              : "overview.organization.measured",
            { days: autonomy.window_days },
          )}
        </span>
      </div>
      <ol class="overview-role-chain" aria-label={t("overview.organization.roleChain")}>
        {roles.map(([role, agent]) => (
          <li key={role}>
            <a
              href={agent === t("overview.organization.specialists")
                ? routeHref("agents")
                : routeHref("agent-activity", { params: { agent } })}
            >
              <span>{t(`overview.organization.role.${role}`)}</span>
              <strong>{agent}</strong>
            </a>
          </li>
        ))}
      </ol>
    </section>
  );
}

function percentageMetric(value: number | null): string {
  return value === null ? t("overview.evidence.unavailable") : `${Math.round(value * 100)}%`;
}

function decimalMetric(value: number | null): string {
  return value === null ? t("overview.evidence.unavailable") : value.toFixed(1);
}

function durationMetric(value: number | null): string {
  return value === null ? t("overview.evidence.unavailable") : fmtDuration(value);
}

function currencyMetric(value: number | null): string {
  return value === null ? t("overview.evidence.unavailable") : `$${value.toFixed(2)}`;
}
