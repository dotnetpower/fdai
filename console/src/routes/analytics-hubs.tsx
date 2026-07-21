import type { ReadApiClient } from "../api";
import type { AutonomyPayload, MetricVsBaseline, VerticalSummary } from "../types";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  UnavailableState,
  type Column,
} from "../components/ui";
import { getLocale } from "../i18n";
import { t } from "./i18n/analytics";
import { currentRoute, routeHref } from "../router";
import { formatShare, formatUsd, overviewHealth } from "./dashboard.model";
import { useAnalyticsData, type AnalyticsData } from "./analytics-data";

interface Props { readonly client: ReadApiClient }

const OUTCOME_KEYS = [
  "auto-resolution",
  "human-touchpoints",
  "mttr",
  "change-lead-time",
  "cost-per-resolved-event",
] as const;
type OutcomeKey = (typeof OUTCOME_KEYS)[number];

export function measuredTierValue(
  values: Readonly<Record<string, number>>,
  tier: string,
): number | null {
  return Object.prototype.hasOwnProperty.call(values, tier) ? values[tier] ?? null : null;
}

export function formatMeasuredSavings(value: number): string {
  return formatUsd(value);
}

export function searchParamsRecord(search: URLSearchParams): Readonly<Record<string, string>> {
  return Object.fromEntries(search.entries());
}

export function routingParamsForTier(
  tier: string,
  search: URLSearchParams,
): Readonly<Record<string, string>> {
  const params = searchParamsRecord(search);
  if (tier === "t2") return params;
  const { indicator: _indicator, ...shared } = params;
  return shared;
}

export function verticalResolutionRate(vertical: VerticalSummary): number | null {
  return vertical.events > 0 ? vertical.auto_resolved / vertical.events : null;
}

export function guardDisplayState(
  synthetic: boolean,
  ok: boolean,
): "simulated" | "passing" | "blocked" {
  if (synthetic) return "simulated";
  return ok ? "passing" : "blocked";
}

function outcomeMetric(data: AutonomyPayload, key: OutcomeKey): MetricVsBaseline {
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

function metricValue(metric: MetricVsBaseline, key: OutcomeKey): string {
  if (metric.value === null) return t("analytics.unavailable");
  if (key === "auto-resolution") return `${Math.round(metric.value * 100)}%`;
  if (key === "human-touchpoints") return metric.value.toFixed(1);
  if (key === "cost-per-resolved-event") return `$${metric.value.toFixed(2)}`;
  return duration(metric.value);
}

function baselineValue(metric: MetricVsBaseline, key: OutcomeKey): string {
  if (metric.baseline === null) return t("analytics.unavailable");
  return metricValue({ ...metric, value: metric.baseline }, key);
}

function HubTabs({
  panelId,
  values,
  active,
  label,
  paramsForValue,
}: {
  readonly panelId: string;
  readonly values: readonly string[];
  readonly active: string;
  readonly label: (value: string) => string;
  readonly paramsForValue?: (value: string, search: URLSearchParams) => Readonly<Record<string, string>>;
}) {
  const search = currentRoute().search;
  return (
    <nav class="analytics-tabs" aria-label={t("analytics.detailViews")}>
      {values.map((value) => (
        <a
          key={value}
          href={routeHref(panelId, {
            segments: [value],
            params: paramsForValue?.(value, search) ?? searchParamsRecord(search),
          })}
          class={value === active ? "active" : undefined}
          aria-current={value === active ? "page" : undefined}
        >
          {label(value)}
        </a>
      ))}
    </nav>
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
      {autonomy.source.as_of ? (
        <span>{t("overview.evidence.asOf", { time: autonomy.source.as_of })}</span>
      ) : null}
    </div>
  );
}

function TrendChart({ values, label }: { readonly values: readonly number[]; readonly label: string }) {
  if (values.length < 2) return <UnavailableState message={t("analytics.trendUnavailable")} />;
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
        <span>{minimum.toFixed(2)}</span><span>{maximum.toFixed(2)}</span>
      </div>
    </figure>
  );
}

export function OperatingOutcomesRoute({ client }: Props) {
  const state = useAnalyticsData(client);
  const segment = currentRoute().segments[0];
  const active: OutcomeKey | null = segment === undefined
    ? "auto-resolution"
    : OUTCOME_KEYS.includes(segment as OutcomeKey) ? segment as OutcomeKey : null;
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.outcomes.title")} subtitle={t("analytics.outcomes.subtitle")} />
      <HubTabs panelId="operating-outcomes" values={OUTCOME_KEYS} active={active ?? ""} label={(key) => t(`analytics.metric.${key}`)} />
      {active === null ? <UnavailableState message={t("analytics.invalidDetail")} /> : (
        <AsyncBoundary state={state} resourceLabel={t("analytics.outcomes.title")}>
          {(data) => data.autonomy ? <OutcomeBody data={data} active={active} /> : <UnavailableState message={t("analytics.autonomyUnavailable")} />}
        </AsyncBoundary>
      )}
    </div>
  );
}

function OutcomeBody({ data, active }: { readonly data: AnalyticsData; readonly active: OutcomeKey }) {
  const autonomy = data.autonomy!;
  const metric = outcomeMetric(autonomy, active);
  const trend = autonomy.trend[active.replaceAll("-", "_")] ??
    (active === "auto-resolution" ? autonomy.trend.auto_resolution_rate : undefined);
  return (
    <div class="stack">
      <EvidenceStrip autonomy={autonomy} />
      <KpiGrid>
        <KpiCard label={t("analytics.current")} value={metricValue(metric, active)} />
        <KpiCard label={t("analytics.baseline")} value={baselineValue(metric, active)} />
        <KpiCard label={t("analytics.direction")} value={t(`analytics.${metric.direction}Better`)} />
        <KpiCard label={t("analytics.sampleSize")} value={autonomy.sample_size.toLocaleString("en-US")} />
      </KpiGrid>
      <TrendChart values={trend ?? []} label={t("analytics.outcomes.trend", { metric: t(`analytics.metric.${active}`) })} />
      <section class="analytics-panel">
        <h3>{t("analytics.outcomes.breakdown")}</h3>
        <VerticalTable verticals={autonomy.verticals} />
      </section>
      <EvidenceLinks links={[
        [t("analytics.viewAudit"), routeHref("audit", { params: { window: `${autonomy.window_days}d` } })],
        [t("analytics.viewIncidents"), routeHref("incidents")],
      ]} />
    </div>
  );
}

export function ControlAssuranceRoute({ client }: Props) {
  const state = useAnalyticsData(client, { includeGates: true });
  const guardKey = currentRoute().search.get("guard");
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.assurance.title")} subtitle={t("analytics.assurance.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("analytics.assurance.title")}>
        {(data) => <AssuranceBody data={data} guardKey={guardKey} />}
      </AsyncBoundary>
    </div>
  );
}

function AssuranceBody({
  data,
  guardKey,
}: {
  readonly data: AnalyticsData;
  readonly guardKey: string | null;
}) {
  const escapes = data.gates?.rows.reduce((sum, row) => sum + row.policy_escapes, 0) ?? null;
  const health = overviewHealth(data.kpi, escapes, data.autonomy);
  return (
    <div class="stack">
      {data.autonomy ? <EvidenceStrip autonomy={data.autonomy} /> : null}
      <KpiGrid>
        <KpiCard label={t("analytics.assurance.posture")} value={t(`analytics.health.${health}`)} tone={health === "healthy" ? "positive" : health === "attention" ? "warning" : "default"} />
        <KpiCard label={t("analytics.assurance.escapes")} value={escapes ?? t("analytics.unavailable")} tone={escapes === null ? "default" : escapes === 0 ? "positive" : "warning"} />
        <KpiCard label={t("analytics.assurance.shadow")} value={formatShare(data.kpi.shadow_share)} />
        <KpiCard label={t("analytics.assurance.ready")} value={data.gates ? `${data.gates.ready_count}/${data.gates.rows.length}` : t("analytics.unavailable")} />
      </KpiGrid>
      {data.autonomy ? (
        <GuardTable autonomy={data.autonomy} guardKey={guardKey} />
      ) : <UnavailableState message={t("analytics.autonomyUnavailable")} />}
      <EvidenceLinks links={[
        [t("analytics.viewPromotion"), routeHref("promotion-gates", { params: { status: "blocked" } })],
        [t("analytics.viewApprovals"), routeHref("hil-queue")],
        [t("analytics.viewShadowAudit"), routeHref("audit", { params: { mode: "shadow" } })],
      ]} />
    </div>
  );
}

function GuardTable({
  autonomy,
  guardKey,
}: {
  readonly autonomy: AutonomyPayload;
  readonly guardKey: string | null;
}) {
  const rows = guardKey === null
    ? autonomy.guards
    : autonomy.guards.filter((row) => row.key === guardKey);
  if (rows.length === 0) return <UnavailableState message={t("analytics.invalidGuard")} />;
  const columns: readonly Column<AutonomyPayload["guards"][number]>[] = [
    { key: "guard", header: t("analytics.guard"), render: (row) => t(`overview.guardFull.${row.key}`) },
    { key: "value", header: t("analytics.current"), render: (row) => `${(row.value * 100).toFixed(1)}%`, cellClass: "num" },
    { key: "threshold", header: t("analytics.threshold"), render: (row) => `${(row.threshold * 100).toFixed(1)}%`, cellClass: "num" },
    {
      key: "status",
      header: t("analytics.status"),
      render: (row) => {
        const state = guardDisplayState(autonomy.synthetic, row.ok);
        return state === "simulated"
          ? <StatusPill kind="neutral" label={t("analytics.simulatedStatus")} />
          : <StatusPill kind={state === "passing" ? "success" : "danger"} label={t(`analytics.${state}`)} />;
      },
    },
  ];
  return <DataTable columns={columns} rows={rows} keyOf={(row) => row.key} />;
}

const VERTICAL_KEYS = ["resilience", "change-safety", "cost-governance"] as const;

function verticalPayloadKey(slug: string): string {
  if (slug === "change-safety") return "change_safety";
  if (slug === "cost-governance") return "cost";
  return slug;
}

function verticalRouteSlug(payloadKey: string): string {
  if (payloadKey === "change_safety") return "change-safety";
  if (payloadKey === "cost") return "cost-governance";
  return payloadKey;
}

export function VerticalOutcomesRoute({ client }: Props) {
  const state = useAnalyticsData(client);
  const segment = currentRoute().segments[0];
  const active = segment === undefined
    ? "resilience"
    : VERTICAL_KEYS.includes(segment as (typeof VERTICAL_KEYS)[number]) ? segment : null;
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.verticals.title")} subtitle={t("analytics.verticals.subtitle")} />
      <HubTabs panelId="verticals" values={VERTICAL_KEYS} active={active ?? ""} label={(key) => t(`analytics.vertical.${key}`)} />
      {active === null ? <UnavailableState message={t("analytics.invalidDetail")} /> : (
        <AsyncBoundary state={state} resourceLabel={t("analytics.verticals.title")}>
          {(data) => data.autonomy ? <VerticalBody data={data} active={active} /> : <UnavailableState message={t("analytics.autonomyUnavailable")} />}
        </AsyncBoundary>
      )}
    </div>
  );
}

function VerticalBody({ data, active }: { readonly data: AnalyticsData; readonly active: string }) {
  const vertical = data.autonomy!.verticals.find((item) => item.key === verticalPayloadKey(active));
  if (!vertical) return <UnavailableState message={t("analytics.verticals.unavailable")} />;
  const resolution = verticalResolutionRate(vertical);
  return (
    <div class="stack">
      <EvidenceStrip autonomy={data.autonomy!} />
      <KpiGrid>
        <KpiCard label={t("analytics.events")} value={vertical.events} />
        <KpiCard label={t("analytics.autoResolved")} value={vertical.auto_resolved} />
        <KpiCard label={t("analytics.resolutionRate")} value={resolution === null ? t("analytics.unavailable") : formatShare(resolution)} />
        <KpiCard label={t("analytics.openRisks")} value={vertical.open_risks} tone={vertical.open_risks > 0 ? "warning" : "positive"} />
        <KpiCard label={t("analytics.monthlySavings")} value={formatMeasuredSavings(vertical.monthly_savings)} />
      </KpiGrid>
      <section class="analytics-panel">
        <h3>{t("analytics.verticals.comparison")}</h3>
        <VerticalTable verticals={data.autonomy!.verticals} />
      </section>
      {data.autonomy!.synthetic ? (
        <p class="muted footnote">{t("analytics.simulatedEvidenceBoundary")}</p>
      ) : null}
      <EvidenceLinks links={[
        [t("analytics.viewIncidents"), routeHref("incidents", {
          params: { vertical: data.autonomy!.synthetic ? null : verticalPayloadKey(active) },
        })],
        [t("analytics.viewAudit"), routeHref("audit", {
          params: { vertical: data.autonomy!.synthetic ? null : verticalPayloadKey(active) },
        })],
      ]} />
    </div>
  );
}

function VerticalTable({ verticals }: { readonly verticals: readonly VerticalSummary[] }) {
  const params = searchParamsRecord(currentRoute().search);
  const columns: readonly Column<VerticalSummary>[] = [
    {
      key: "vertical",
      header: t("analytics.verticalLabel"),
      render: (row) => (
        <a href={routeHref("verticals", { segments: [verticalRouteSlug(row.key)], params })}>
          {t(`overview.vertical.${row.key}`)}
        </a>
      ),
    },
    { key: "events", header: t("analytics.events"), render: (row) => row.events, cellClass: "num" },
    { key: "resolved", header: t("analytics.autoResolved"), render: (row) => row.auto_resolved, cellClass: "num" },
    { key: "risks", header: t("analytics.openRisks"), render: (row) => row.open_risks, cellClass: "num" },
  ];
  return <DataTable columns={columns} rows={verticals} keyOf={(row) => row.key} />;
}

const TIER_KEYS = ["t0", "t1", "t2"] as const;
const LEADING_INDICATOR_KEYS = ["disagreement", "verifier", "divergence"] as const;
type LeadingIndicatorKey = (typeof LEADING_INDICATOR_KEYS)[number];

export function TrustRoutingRoute({ client }: Props) {
  const state = useAnalyticsData(client);
  const segment = currentRoute().segments[0]?.toLowerCase();
  const indicatorParam = currentRoute().search.get("indicator");
  const indicator = indicatorParam === null
    ? null
    : LEADING_INDICATOR_KEYS.includes(indicatorParam as LeadingIndicatorKey)
      ? indicatorParam as LeadingIndicatorKey
      : undefined;
  const active = segment === undefined
    ? "t0"
    : TIER_KEYS.includes(segment as (typeof TIER_KEYS)[number]) ? segment : null;
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.routing.title")} subtitle={t("analytics.routing.subtitle")} />
      <HubTabs
        panelId="trust-routing"
        values={TIER_KEYS}
        active={active ?? ""}
        label={(key) => key.toUpperCase()}
        paramsForValue={routingParamsForTier}
      />
      {active === null ? <UnavailableState message={t("analytics.invalidDetail")} /> : (
        <AsyncBoundary state={state} resourceLabel={t("analytics.routing.title")}>
          {(data) => data.autonomy ? (
            <RoutingBody data={data} active={active} indicator={indicator} />
          ) : <UnavailableState message={t("analytics.autonomyUnavailable")} />}
        </AsyncBoundary>
      )}
    </div>
  );
}

function RoutingBody({
  data,
  active,
  indicator,
}: {
  readonly data: AnalyticsData;
  readonly active: string;
  readonly indicator: LeadingIndicatorKey | null | undefined;
}) {
  const share = measuredTierValue(data.autonomy!.tier.mix, active);
  const band = data.autonomy!.tier.bands[active];
  const count = measuredTierValue(data.kpi.by_tier, active);
  const inBand = band && share !== null ? share >= band[0] && share <= band[1] : null;
  return (
    <div class="stack">
      <EvidenceStrip autonomy={data.autonomy!} />
      <KpiGrid>
        <KpiCard label={t("analytics.routing.share")} value={share === null ? t("analytics.unavailable") : formatShare(share)} />
        <KpiCard label={t("analytics.routing.targetBand")} value={band ? `${Math.round(band[0] * 100)}-${Math.round(band[1] * 100)}%` : t("analytics.unavailable")} />
        <KpiCard label={t("analytics.events")} value={count ?? t("analytics.unavailable")} />
        <KpiCard label={t("analytics.status")} value={inBand === null ? t("analytics.unavailable") : inBand ? t("analytics.inBand") : t("analytics.outOfBand")} tone={inBand === null ? "default" : inBand ? "positive" : "warning"} />
      </KpiGrid>
      <TierTable data={data} />
      {active === "t2" ? (
        <LeadingIndicatorTable autonomy={data.autonomy!} indicator={indicator} />
      ) : indicator !== null ? (
        <UnavailableState message={t("analytics.routing.indicatorT2Only")} />
      ) : null}
      <EvidenceLinks links={[
        [t("analytics.viewAudit"), routeHref("audit", { params: { tier: active } })],
        [t("analytics.viewRules"), routeHref("rules")],
        [t("analytics.viewLlmCost"), routeHref("llm-cost")],
      ]} />
    </div>
  );
}

function LeadingIndicatorTable({
  autonomy,
  indicator,
}: {
  readonly autonomy: AutonomyPayload;
  readonly indicator: LeadingIndicatorKey | null | undefined;
}) {
  if (indicator === undefined) return <UnavailableState message={t("analytics.routing.invalidIndicator")} />;
  const allRows = [
    { key: "disagreement" as const, metric: autonomy.leading.mixed_model_disagreement_rate },
    { key: "verifier" as const, metric: autonomy.leading.verifier_failure_rate },
    { key: "divergence" as const, metric: autonomy.leading.shadow_divergence_rate },
  ];
  const rows = indicator === null ? allRows : allRows.filter((row) => row.key === indicator);
  const columns: readonly Column<(typeof allRows)[number]>[] = [
    { key: "indicator", header: t("analytics.routing.indicator"), render: (row) => t(`overview.leading.${row.key}`) },
    { key: "current", header: t("analytics.current"), render: (row) => row.metric.value === null ? t("analytics.unavailable") : formatShare(row.metric.value), cellClass: "num" },
    { key: "baseline", header: t("analytics.baseline"), render: (row) => row.metric.baseline === null ? t("analytics.unavailable") : formatShare(row.metric.baseline), cellClass: "num" },
    {
      key: "status",
      header: t("analytics.status"),
      render: (row) => autonomy.synthetic
        ? <StatusPill kind="neutral" label={t("analytics.simulatedStatus")} />
        : row.metric.value === null || row.metric.baseline === null
          ? <StatusPill kind="neutral" label={t("analytics.unavailable")} />
          : <StatusPill
              kind={row.metric.value <= row.metric.baseline ? "success" : "warning"}
              label={row.metric.value <= row.metric.baseline ? t("analytics.passing") : t("analytics.outOfBand")}
            />,
    },
  ];
  return (
    <section class="analytics-panel">
      <h3>{t("analytics.routing.leadingIndicators")}</h3>
      <DataTable columns={columns} rows={rows} keyOf={(row) => row.key} />
    </section>
  );
}

function TierTable({ data }: { readonly data: AnalyticsData }) {
  const search = currentRoute().search;
  const rows = TIER_KEYS.map((key) => ({
    key,
    share: measuredTierValue(data.autonomy!.tier.mix, key),
    band: data.autonomy!.tier.bands[key],
    count: measuredTierValue(data.kpi.by_tier, key),
  }));
  const columns: readonly Column<(typeof rows)[number]>[] = [
    {
      key: "tier",
      header: t("analytics.tier"),
      render: (row) => <a href={routeHref("trust-routing", {
        segments: [row.key],
        params: routingParamsForTier(row.key, search),
      })}>{row.key.toUpperCase()}</a>,
    },
    { key: "share", header: t("analytics.routing.share"), render: (row) => row.share === null ? t("analytics.unavailable") : formatShare(row.share), cellClass: "num" },
    { key: "band", header: t("analytics.routing.targetBand"), render: (row) => row.band ? `${Math.round(row.band[0] * 100)}-${Math.round(row.band[1] * 100)}%` : "-", cellClass: "num" },
    { key: "events", header: t("analytics.events"), render: (row) => row.count ?? t("analytics.unavailable"), cellClass: "num" },
  ];
  return <DataTable columns={columns} rows={rows} keyOf={(row) => row.key} />;
}

function EvidenceLinks({ links }: { readonly links: readonly (readonly [string, string])[] }) {
  return (
    <nav class="analytics-links" aria-label={t("analytics.relatedEvidence")}>
      {links.map(([label, href]) => <a key={href} href={href}>{label}<span aria-hidden="true">&rarr;</span></a>)}
    </nav>
  );
}
