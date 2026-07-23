import type { ReadApiClient } from "../api";
import type { AutonomyPayload } from "../types";
import { usePublishViewContext } from "../deck/context";
import {
  AsyncBoundary,
  DataTable,
  PageHeader,
  StatusPill,
  UnavailableState,
  type Column,
} from "../components/ui";
import { getLocale } from "../i18n";
import { t } from "./i18n/analytics";
import { currentRoute, routeHref } from "../router";
import { formatShare } from "./dashboard.model";
import { useAnalyticsData, type AnalyticsData } from "./analytics-data";
import { buildOperatingOutcomeViewSnapshot } from "./analytics-hubs.view";
import { ControlAssuranceBody } from "./control-assurance";
import { VerticalOutcomesBody } from "./vertical-outcomes";
export { formatMeasuredSavings, verticalResolutionRate } from "./vertical-outcomes";
import {
  OperatingOutcomeBody,
  OUTCOME_KEYS,
  outcomeMetric,
  type OutcomeKey,
} from "./operating-outcomes";

interface Props { readonly client: ReadApiClient }

export function measuredTierValue(
  values: Readonly<Record<string, number>>,
  tier: string,
): number | null {
  return Object.prototype.hasOwnProperty.call(values, tier) ? values[tier] ?? null : null;
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
  const routeLabel = t("analytics.outcomes.title");
  const metricLabel = t(`analytics.metric.${active}`);
  const unavailableLabel = t("analytics.unavailable");
  usePublishViewContext(
    () => buildOperatingOutcomeViewSnapshot({
      autonomy,
      metric,
      metricKey: active,
      metricLabel,
      unavailableLabel,
      routeLabel,
    }),
    [active, autonomy, metric, metricLabel, routeLabel, unavailableLabel],
  );
  return <OperatingOutcomeBody data={data} active={active} />;
}

export function ControlAssuranceRoute({ client }: Props) {
  const state = useAnalyticsData(client, { includeGates: true });
  const guardKey = currentRoute().search.get("guard");
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.assurance.title")} subtitle={t("analytics.assurance.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("analytics.assurance.title")}>
        {(data) => (
          <ControlAssuranceBody
            data={data}
            evidence={data.autonomy ? <EvidenceStrip autonomy={data.autonomy} /> : null}
            guardKey={guardKey}
            context={searchParamsRecord(currentRoute().search)}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

export function VerticalOutcomesRoute({ client }: Props) {
  const state = useAnalyticsData(client);
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.verticals.title")} subtitle={t("analytics.verticals.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("analytics.verticals.title")}>
        {(data) => data.autonomy ? (
          <VerticalOutcomesBody autonomy={data.autonomy} context={searchParamsRecord(currentRoute().search)} evidence={<EvidenceStrip autonomy={data.autonomy} />} />
        ) : <UnavailableState message={t("analytics.autonomyUnavailable")} />}
      </AsyncBoundary>
    </div>
  );
}

const TIER_KEYS = ["t0", "t1", "t2"] as const;
const LEADING_INDICATOR_KEYS = ["disagreement", "verifier", "divergence"] as const;
type TierKey = (typeof TIER_KEYS)[number];
type LeadingIndicatorKey = (typeof LEADING_INDICATOR_KEYS)[number];

const T2_FLOW_STEPS = ["models", "verifier", "grounding", "risk", "approval", "audit"] as const;

export function indicatorMeterPercent(value: number | null, baseline: number | null): number | null {
  if (value === null || baseline === null) return null;
  if (baseline <= 0) return value <= 0 ? 0 : 100;
  return Math.min(100, Math.max(0, Math.round((value / baseline) * 100)));
}

export function TrustRoutingRoute({ client }: Props) {
  const state = useAnalyticsData(client);
  const segment = currentRoute().segments[0]?.toLowerCase();
  const indicatorParam = currentRoute().search.get("indicator");
  const indicator = indicatorParam === null
    ? null
    : LEADING_INDICATOR_KEYS.includes(indicatorParam as LeadingIndicatorKey)
      ? indicatorParam as LeadingIndicatorKey
      : undefined;
  const active: TierKey | null = segment === undefined
    ? "t2"
    : TIER_KEYS.includes(segment as TierKey) ? segment as TierKey : null;
  return (
    <div class="stack analytics-route">
      <PageHeader title={t("analytics.routing.title")} subtitle={t("analytics.routing.subtitle")} />
      <HubTabs
        panelId="trust-routing"
        values={TIER_KEYS}
        active={active ?? ""}
        label={(key) => t(`analytics.routing.tier.${key}`)}
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
  readonly active: TierKey;
  readonly indicator: LeadingIndicatorKey | null | undefined;
}) {
  const context = searchParamsRecord(currentRoute().search);
  return (
    <div class="stack trust-routing-view">
      <div class="routing-policy-banner">
        <strong>{t("analytics.routing.policyTitle")}</strong>
        <span>{t("analytics.routing.policyBody")}</span>
      </div>
      <EvidenceStrip autonomy={data.autonomy!} />
      <TierMap data={data} active={active} />
      {active === "t2" ? (
        <>
          <T2ControlFlow />
          <LeadingIndicatorPanel autonomy={data.autonomy!} indicator={indicator} context={context} />
        </>
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

function TierMap({ data, active }: { readonly data: AnalyticsData; readonly active: TierKey }) {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  const search = currentRoute().search;
  return (
    <section class="routing-tier-map" aria-label={t("analytics.routing.distributionLabel")}>
      {TIER_KEYS.map((key) => {
        const share = measuredTierValue(data.autonomy!.tier.mix, key);
        const band = data.autonomy!.tier.bands[key];
        const count = measuredTierValue(data.kpi.by_tier, key);
        return (
          <a
            key={key}
            class={`routing-tier-card card is-${key}${active === key ? " is-active" : ""}`}
            href={routeHref("trust-routing", {
              segments: [key],
              params: routingParamsForTier(key, search),
            })}
            aria-current={active === key ? "page" : undefined}
          >
            <span class="routing-tier-code">{key.toUpperCase()}</span>
            <strong class="routing-tier-share">{share === null ? t("analytics.unavailable") : formatShare(share)}</strong>
            <span class="routing-tier-description">{t(`analytics.routing.description.${key}`)}</span>
            <dl class="routing-tier-facts">
              <div><dt>{t("analytics.events")}</dt><dd>{count === null ? t("analytics.unavailable") : count.toLocaleString(locale)}</dd></div>
              <div><dt>{t("analytics.routing.targetBand")}</dt><dd>{band ? `${Math.round(band[0] * 100)}-${Math.round(band[1] * 100)}%` : t("analytics.notConfigured")}</dd></div>
            </dl>
          </a>
        );
      })}
    </section>
  );
}

function T2ControlFlow() {
  return (
    <section class="routing-control-panel" aria-labelledby="t2-control-flow-title">
      <div class="routing-section-head">
        <div>
          <h3 id="t2-control-flow-title">{t("analytics.routing.controlFlowTitle")}</h3>
          <p>{t("analytics.routing.controlFlowSubtitle")}</p>
        </div>
        <StatusPill kind="neutral" label={t("analytics.routing.mandatoryControls")} />
      </div>
      <div class="routing-control-flow">
        {T2_FLOW_STEPS.map((step, index) => (
          <div class="routing-control-group" key={step}>
            <div class="routing-control-step">
              <strong>{t(`analytics.routing.flow.${step}.title`)}</strong>
              <span>{t(`analytics.routing.flow.${step}.body`)}</span>
            </div>
            {index < T2_FLOW_STEPS.length - 1 ? <span class="routing-control-arrow" aria-hidden="true">&rarr;</span> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function LeadingIndicatorPanel({
  autonomy,
  indicator,
  context,
}: {
  readonly autonomy: AutonomyPayload;
  readonly indicator: LeadingIndicatorKey | null | undefined;
  readonly context: Readonly<Record<string, string>>;
}) {
  if (indicator === undefined) return <UnavailableState message={t("analytics.routing.invalidIndicator")} />;
  const allRows = [
    { key: "disagreement" as const, metric: autonomy.leading.mixed_model_disagreement_rate },
    { key: "verifier" as const, metric: autonomy.leading.verifier_failure_rate },
    { key: "divergence" as const, metric: autonomy.leading.shadow_divergence_rate },
  ];
  const rows = indicator === null ? allRows : allRows.filter((row) => row.key === indicator);
  return (
    <section class="routing-indicators" aria-labelledby="routing-indicators-title">
      <div class="routing-section-head">
        <div>
          <h3 id="routing-indicators-title">{t("analytics.routing.leadingIndicators")}</h3>
          <p>{t("analytics.routing.leadingIndicatorsSubtitle")}</p>
        </div>
      </div>
      <div class="routing-indicator-grid">
        {rows.map((row) => {
          const meter = indicatorMeterPercent(row.metric.value, row.metric.baseline);
          const unavailable = row.metric.value === null || row.metric.baseline === null;
          const passing = !unavailable && row.metric.value! <= row.metric.baseline!;
          return (
            <a
              class={`routing-indicator${unavailable ? " is-unavailable" : ""}`}
              href={routeHref("trust-routing", { segments: ["t2"], params: { ...context, indicator: row.key } })}
              key={row.key}
            >
              <div class="routing-indicator-head">
                <strong>{t(`overview.leading.${row.key}`)}</strong>
                {autonomy.synthetic
                  ? <StatusPill kind="neutral" label={t("analytics.simulatedStatus")} />
                  : unavailable
                    ? <StatusPill kind="neutral" label={t("analytics.unavailable")} />
                    : <StatusPill kind={passing ? "success" : "warning"} label={passing ? t("analytics.passing") : t("analytics.outOfBand")} />}
              </div>
              <div class="routing-indicator-meter" aria-hidden="true"><span style={{ width: `${meter ?? 0}%` }} /></div>
              <div class="routing-indicator-values">
                <span>{t("analytics.current")}: <strong>{row.metric.value === null ? t("analytics.unavailable") : formatShare(row.metric.value)}</strong></span>
                <span>{t("analytics.baseline")}: <strong>{row.metric.baseline === null ? t("analytics.unavailable") : formatShare(row.metric.baseline)}</strong></span>
              </div>
            </a>
          );
        })}
      </div>
    </section>
  );
}

function EvidenceLinks({ links }: { readonly links: readonly (readonly [string, string])[] }) {
  return (
    <nav class="analytics-links" aria-label={t("analytics.relatedEvidence")}>
      {links.map(([label, href]) => <a key={href} href={href}>{label}<span aria-hidden="true">&rarr;</span></a>)}
    </nav>
  );
}
