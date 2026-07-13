import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { ReadApiError } from "../api";
import type {
  AutonomyPayload,
  DashboardKpi,
  FinOpsPayload,
  MetricVsBaseline,
  VerticalSummary,
} from "../types";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { overviewHealth } from "./dashboard.model";

interface Props {
  readonly client: ReadApiClient;
}

/**
 * The three axes an approver reads first - is it healthy, is there risk,
 * is it saving money - composed from the required `/kpi` backbone and the
 * opt-in `/finops` panel. `finops` is null when the panel is not served
 * (production, or a fork that has not registered it); the cost axis then
 * renders "not enabled" instead of failing the whole page.
 */
/**
 * Aggregate promotion-gate signal behind the release guard row. `null`
 * when the gate route is not wired on this deployment (404/501). A
 * `policy_escapes` sum > 0 blocks release per goals-and-metrics (escapes
 * MUST be exactly 0), so it also fails the health axis.
 */
interface GateRow {
  readonly policy_escapes: number;
  readonly ready: boolean;
}
interface GatesSummary {
  readonly rows: readonly GateRow[];
  readonly ready_count: number;
  readonly blocked_count: number;
}

interface OverviewData {
  readonly kpi: DashboardKpi;
  readonly finops: FinOpsPayload | null;
  readonly gates: GatesSummary | null;
  readonly autonomy: AutonomyPayload | null;
}

function formatShare(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

function formatUsd(x: number): string {
  return x.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export function DashboardRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<OverviewData>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // `/kpi` is the required backbone; `/finops` is a fork opt-in panel,
        // so a 404 degrades to a null cost axis instead of failing the page.
        const kpi = await client.dashboardMetrics();
        let finops: FinOpsPayload | null = null;
        try {
          finops = await client.finops();
        } catch (err) {
          if (!(err instanceof ReadApiError && err.status === 404)) throw err;
        }
        // Promotion-gate summary powers the release guard (policy escapes
        // MUST be 0). Opt-in like finops: 404/501 degrades to no guard row.
        let gates: GatesSummary | null = null;
        try {
          gates = await client.panel<GatesSummary>("/kpi/promotion-gates");
        } catch (err) {
          if (!(err instanceof ReadApiError && (err.status === 404 || err.status === 501)))
            throw err;
        }
        // Autonomy measurement summary (success vs baseline, guards,
        // verticals, tier, trend). Opt-in: 404/501 => audit-only fallback.
        let autonomy: AutonomyPayload | null = null;
        try {
          autonomy = await client.autonomy();
        } catch (err) {
          if (!(err instanceof ReadApiError && (err.status === 404 || err.status === 501)))
            throw err;
        }
        if (!cancelled) setState({ status: "ready", data: { kpi, finops, gates, autonomy } });
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div class="stack">
      <PageHeader title={t("route.dashboard")} subtitle={<>{t("overview.subtitle")}</>} />
      <AsyncBoundary state={state} resourceLabel="overview">
        {(data) => <OverviewBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

function OverviewBody({ data }: { readonly data: OverviewData }) {
  const { kpi, finops, gates, autonomy } = data;

  const tierTotal = Object.values(kpi.by_tier).reduce((a, b) => a + b, 0);
  const t0Share = tierTotal > 0 ? Math.round(((kpi.by_tier.t0 ?? 0) / tierTotal) * 100) : 0;
  const policyEscapes = gates ? gates.rows.reduce((sum, r) => sum + r.policy_escapes, 0) : null;
  const readyCount = gates ? gates.ready_count : null;
  const gateTotal = gates ? gates.rows.length : null;
  // A policy escape blocks release (goals-and-metrics: escapes MUST be 0),
  // so it fails the health axis just like a pending human approval does.
  const health = overviewHealth(kpi, policyEscapes, autonomy);
  const healthy = health === "healthy";
  const savings = finops ? finops.estimated_monthly_savings : null;

  usePublishViewContext(
    () => {
      // The Overview renders an autonomy hero, success-metrics-vs-baseline,
      // per-vertical cards, and guard bands from the /kpi/autonomy panel.
      // Publish that surface (not just the audit KPIs) so the deck can answer
      // "what is the auto-resolution rate / savings per vertical / are the
      // guards ok?". `synthetic` is surfaced so the deck can flag dev values.
      const autonomyFacts: {
        key: string;
        value: string | number | boolean | null;
        group?: string;
      }[] = autonomy
        ? [
            { key: "measurement_synthetic", value: autonomy.synthetic, group: "autonomy" },
            { key: "auto_resolution_rate", value: autonomy.success.auto_resolution_rate.value, group: "autonomy" },
            { key: "auto_resolution_baseline", value: autonomy.success.auto_resolution_rate.baseline, group: "autonomy" },
            { key: "human_touchpoints_per_100", value: autonomy.success.human_touchpoints_per_100.value, group: "autonomy" },
            { key: "mttr_seconds", value: autonomy.success.mttr_seconds.value, group: "autonomy" },
            { key: "change_lead_time_seconds", value: autonomy.success.change_lead_time_seconds.value, group: "autonomy" },
          ]
        : [];
      const autonomyRecords: Record<string, readonly Record<string, unknown>[]> = autonomy
        ? {
            success_metrics: (
              [
                ["auto_resolution_rate", autonomy.success.auto_resolution_rate],
                ["human_touchpoints_per_100", autonomy.success.human_touchpoints_per_100],
                ["mttr_seconds", autonomy.success.mttr_seconds],
                ["change_lead_time_seconds", autonomy.success.change_lead_time_seconds],
              ] as const
            ).map(([metric, m]) => ({
              metric,
              value: m.value,
              baseline: m.baseline,
              better_when: m.direction,
            })),
            verticals: autonomy.verticals.map((v) => ({
              vertical: v.key,
              events: v.events,
              auto_resolved: v.auto_resolved,
              open_risks: v.open_risks,
              monthly_savings: v.monthly_savings,
            })),
            guards: autonomy.guards.map((g) => ({
              key: g.key,
              value: g.value,
              baseline: g.baseline,
              threshold: g.threshold,
              ok: g.ok,
            })),
          }
        : {};
      return {
        routeId: "dashboard",
        routeLabel: "Overview",
        purpose:
          "The at-a-glance health of the control plane: event volume, the " +
          "shadow/enforce split, T0 deterministic share, HIL backlog, and " +
          "estimated monthly savings across the verticals. Read-only summary.",
        glossary: composeGlossary([
          TERMS.tier,
          TERMS.shadowMode,
          TERMS.mode,
          TERMS.hil,
          TERMS.gateDecision,
        ]),
        headline:
          `health ${health} - ` +
          `${kpi.hil_pending} HIL pending - ` +
          (savings !== null ? `${formatUsd(savings)}/mo saved` : "cost n/a"),
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "health", value: health, group: "overview" },
          { key: "event_count", value: kpi.event_count, group: "overview" },
          { key: "shadow_share", value: formatShare(kpi.shadow_share), group: "overview" },
          { key: "t0_share", value: `${t0Share}%`, group: "overview" },
          { key: "hil_pending", value: kpi.hil_pending, group: "overview" },
          {
            key: "monthly_savings",
            value: savings !== null ? formatUsd(savings) : "n/a",
            group: "cost",
          },
          { key: "cost_actions", value: finops ? finops.total_actions : 0, group: "cost" },
          { key: "policy_escapes", value: policyEscapes ?? "n/a", group: "guards" },
          {
            key: "promotion_ready",
            value: gateTotal !== null ? `${readyCount}/${gateTotal}` : "n/a",
            group: "guards",
          },
          ...autonomyFacts,
        ],
        records: {
          by_action_kind: Object.entries(kpi.by_action_kind)
            .sort(([, a], [, b]) => b - a)
            .map(([key, count]) => ({ key, count })),
          by_outcome: Object.entries(kpi.by_outcome)
            .sort(([, a], [, b]) => b - a)
            .map(([key, count]) => ({ key, count })),
          ...autonomyRecords,
        },
      };
    },
    [kpi, finops, gates, autonomy, health, savings, t0Share],
  );

  return (
    <div class="stack">
      {autonomy ? <AutonomyHero autonomy={autonomy} /> : null}
      {autonomy ? <SuccessMetrics success={autonomy.success} /> : null}
      {autonomy ? <VerticalCards verticals={autonomy.verticals} /> : null}
      <section class="overview-triad" aria-label="health, risk and cost summary">
        <KpiCard
          label={t("overview.health.label")}
          value={health === "healthy" ? t("overview.health.healthy") : health === "attention" ? t("overview.health.attention") : t("overview.health.unknown")}
          tone={healthy ? "positive" : "warning"}
          hint={`${kpi.event_count} events - T0 ${t0Share}% - shadow ${formatShare(kpi.shadow_share)}`}
        />
        <KpiCard
          label={t("overview.risk.label")}
          value={kpi.hil_pending}
          tone={kpi.hil_pending > 0 ? "warning" : "positive"}
          hint={kpi.hil_pending > 0 ? t("overview.risk.pending") : t("overview.risk.clear")}
        />
        <KpiCard
          label={t("overview.cost.label")}
          value={savings !== null ? formatUsd(savings) : "-"}
          tone={savings !== null && savings > 0 ? "positive" : "default"}
          hint={
            savings !== null
              ? `${t("overview.cost.annualized", { amount: formatUsd(savings * 12) })} - ${t("overview.cost.actions", { count: finops ? finops.total_actions : 0 })}`
              : t("overview.cost.unavailable")
          }
        />
      </section>

      {gates || autonomy ? (
        <section class="overview-guards" aria-label="release guards">
          <span class="overview-guards-label">{t("overview.guards.label")}</span>
          {policyEscapes !== null ? (
            <GuardChip
              label={t("overview.guards.escapes", { count: policyEscapes })}
              title={t("overview.guardFull.policy_escapes")}
              ok={policyEscapes === 0}
            />
          ) : null}
          {autonomy
            ? autonomy.guards.map((g) => (
                <GuardChip
                  key={g.key}
                  label={`${t(`overview.guard.${g.key}`)} ${(g.value * 100).toFixed(1)}%`}
                  title={t(`overview.guardFull.${g.key}`)}
                  ok={g.ok}
                />
              ))
            : null}
          {gates ? (
            <a class="overview-guards-note overview-drill" href="#/promotion-gates">
              {t("overview.guards.ready", { ready: readyCount ?? 0, total: gateTotal ?? 0 })}
            </a>
          ) : null}
        </section>
      ) : null}

      {autonomy ? <TierBands tier={autonomy.tier} /> : null}

      {autonomy ? <LivingRules rules={autonomy.rules} /> : null}

      <h3 class="section-title">{t("overview.detail")}</h3>
      <KpiGrid>
        <KpiCard label="Events (audit)" value={kpi.event_count} hint="terminal audit entries" />
        <KpiCard
          label="Shadow share"
          value={formatShare(kpi.shadow_share)}
          hint="judge-only, no mutation"
          tone={kpi.shadow_share > 0.95 ? "positive" : "default"}
        />
        <KpiCard
          label="Enforce share"
          value={formatShare(kpi.enforce_share)}
          hint="promoted to production"
        />
        <KpiCard
          label="HIL pending"
          value={kpi.hil_pending}
          tone={kpi.hil_pending > 0 ? "warning" : "positive"}
          hint={kpi.hil_pending > 0 ? "needs a human approver" : "no waiting approvals"}
        />
      </KpiGrid>

      <div class="two-col">
        <section class="stack-section">
          <h3 class="section-title">Actions by kind</h3>
          <CountTable data={kpi.by_action_kind} keyLabel="Action kind" />
        </section>
        <section class="stack-section">
          <h3 class="section-title">Outcomes</h3>
          <CountTable data={kpi.by_outcome} keyLabel="Outcome" />
        </section>
      </div>

      {kpi.last_recorded_at !== null ? (
        <p class="muted footnote">Last audit entry: {kpi.last_recorded_at}</p>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Autonomy summary sub-components (success metrics vs baseline)
// ---------------------------------------------------------------------------

function fmtDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  return `${(minutes / 60).toFixed(1)}h`;
}

/** Improvement factor vs baseline, oriented by the metric's direction
 * (higher-is-better -> value/baseline; lower-is-better -> baseline/value).
 * `null` when either side is non-positive (avoid a meaningless ratio). */
function improvementFactor(m: MetricVsBaseline): number | null {
  if (m.baseline <= 0 || m.value <= 0) return null;
  return m.direction === "higher" ? m.value / m.baseline : m.baseline / m.value;
}

/** A compact auto-resolution trend line drawn from the measurement series.
 * Rendered in the hero so "is autonomy improving" reads at a glance. */
function TrendSpark({
  series,
  label,
}: {
  readonly series: readonly number[];
  readonly label: string;
}) {
  const w = 128;
  const h = 30;
  const max = Math.max(...series);
  const min = Math.min(...series);
  const range = max - min || 1;
  const points = series
    .map((v, i) => {
      const x = (i / (series.length - 1)) * w;
      const y = h - ((v - min) / range) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const first = series[0] ?? 0;
  const last = series[series.length - 1] ?? 0;
  const deltaPp = Math.round((last - first) * 100);
  return (
    <div class="overview-trend">
      <span class="overview-trend-label muted">{label}</span>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        width={w}
        height={h}
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

function AutonomyHero({ autonomy }: { readonly autonomy: AutonomyPayload }) {
  const trend = autonomy.trend.auto_resolution_rate;
  return (
    <section class="overview-hero" aria-label="autonomy summary">
      <div>
        <h3 class="overview-hero-title">{t("overview.hero.title")}</h3>
        <p class="overview-hero-sub muted">
          {t("overview.hero.window", {
            days: autonomy.window_days,
            samples: autonomy.sample_size.toLocaleString("en-US"),
          })}
          {autonomy.confidence !== null
            ? ` - ${t("overview.hero.confidence", { pct: Math.round(autonomy.confidence * 100) })}`
            : ""}
        </p>
      </div>
      {trend && trend.length >= 2 ? (
        <TrendSpark series={trend} label={t("overview.trend.autoRes")} />
      ) : null}
      {autonomy.synthetic ? (
        <span class="overview-synthetic" title={t("overview.hero.syntheticHint")}>
          {t("overview.hero.synthetic")}
        </span>
      ) : null}
    </section>
  );
}

function SuccessMetrics({ success }: { readonly success: AutonomyPayload["success"] }) {
  const auto = success.auto_resolution_rate;
  const touch = success.human_touchpoints_per_100;
  const mttr = success.mttr_seconds;
  const lead = success.change_lead_time_seconds;
  return (
    <section class="overview-metrics" aria-label="success metrics vs baseline">
      <SuccessMetric
        label={t("overview.metric.autoRes")}
        value={`${Math.round(auto.value * 100)}%`}
        metric={auto}
        baselineText={`${Math.round(auto.baseline * 100)}%`}
      />
      <SuccessMetric
        label={t("overview.metric.touchpoints")}
        value={touch.value.toFixed(1)}
        metric={touch}
        baselineText={touch.baseline.toFixed(1)}
      />
      <SuccessMetric
        label={t("overview.metric.mttr")}
        value={fmtDuration(mttr.value)}
        metric={mttr}
        baselineText={fmtDuration(mttr.baseline)}
      />
      <SuccessMetric
        label={t("overview.metric.leadTime")}
        value={fmtDuration(lead.value)}
        metric={lead}
        baselineText={fmtDuration(lead.baseline)}
      />
    </section>
  );
}

function SuccessMetric({
  label,
  value,
  metric,
  baselineText,
}: {
  readonly label: string;
  readonly value: string;
  readonly metric: MetricVsBaseline;
  readonly baselineText: string;
}) {
  const factor = improvementFactor(metric);
  return (
    <div class="card overview-metric">
      <span class="overview-metric-label">{label}</span>
      <span class="overview-metric-value">{value}</span>
      <span class="overview-metric-sub muted">
        {t("overview.metric.vsBaseline", { baseline: baselineText })}
        {factor !== null ? (
          <span class="overview-metric-factor"> {factor.toFixed(1)}x</span>
        ) : null}
      </span>
    </div>
  );
}

/** Per-vertical activity: which of the three verticals is doing what, and
 * where a human still needs to look (open risks). */
function VerticalCards({ verticals }: { readonly verticals: readonly VerticalSummary[] }) {
  return (
    <section class="overview-verticals" aria-label="per-vertical activity">
      {verticals.map((v) => (
        <VerticalCard key={v.key} v={v} />
      ))}
    </section>
  );
}

function VerticalCard({ v }: { readonly v: VerticalSummary }) {
  const hasRisk = v.open_risks > 0;
  return (
    <div class={`card overview-vertical overview-vertical-${v.key}`}>
      <div class="overview-vertical-head">
        <span class="overview-vertical-name">{t(`overview.vertical.${v.key}`)}</span>
        {hasRisk ? (
          <span class="overview-vertical-risk">
            {t("overview.vertical.risks", { count: v.open_risks })}
          </span>
        ) : (
          <span class="overview-vertical-clear muted">{t("overview.vertical.clear")}</span>
        )}
      </div>
      <div class="overview-vertical-stats">
        <span>
          <b>{v.events}</b> {t("overview.vertical.events")}
        </span>
        <span>
          <b>{v.auto_resolved}</b> {t("overview.vertical.auto")}
        </span>
        {v.monthly_savings > 0 ? (
          <span class="overview-vertical-savings">{formatUsd(v.monthly_savings)}/mo</span>
        ) : null}
      </div>
    </div>
  );
}

function GuardChip({
  label,
  title,
  ok,
}: {
  readonly label: string;
  readonly title: string;
  readonly ok: boolean;
}) {
  return (
    <span class={`overview-guard ${ok ? "ok" : "bad"}`} title={title}>
      {label}
    </span>
  );
}

/** Trust-tier mix against the target band (leading indicator): a tier
 * drifting out of its band is an early warning, so it is flagged. */
function TierBands({ tier }: { readonly tier: AutonomyPayload["tier"] }) {
  const keys = ["t0", "t1", "t2"] as const;
  return (
    <section class="overview-tiers" aria-label="trust tier mix vs target band">
      <span class="overview-guards-label">{t("overview.tier.label")}</span>
      {keys.map((k) => {
        const share = tier.mix[k] ?? 0;
        const band = tier.bands[k];
        const inBand = band ? share >= band[0] && share <= band[1] : true;
        const bandText = band
          ? `${Math.round(band[0] * 100)}-${Math.round(band[1] * 100)}%`
          : "";
        return (
          <span
            key={k}
            class={`overview-tier ${inBand ? "ok" : "warn"}`}
            title={bandText ? t("overview.tier.band", { range: bandText }) : ""}
          >
            {k.toUpperCase()} {Math.round(share * 100)}%
          </span>
        );
      })}
    </section>
  );
}

/** Living rule catalog: how many rules are active, promoted recently, and
 * proposed by the discovery loop - the product's "rules stay fresh" story. */
function LivingRules({ rules }: { readonly rules: AutonomyPayload["rules"] }) {
  return (
    <section class="overview-rules" aria-label="living rule catalog">
      <span class="overview-guards-label">{t("overview.rules.label")}</span>
      <span class="overview-rules-stat">
        <b>{rules.active}</b> {t("overview.rules.active")}
      </span>
      <span class="overview-rules-stat">
        <b>{rules.promoted_30d}</b> {t("overview.rules.promoted")}
      </span>
      <span class="overview-rules-stat muted">
        <b>{rules.candidates_30d}</b> {t("overview.rules.candidates")}
      </span>
      <a class="overview-drill" href="#/rules">
        {t("overview.drill.browse")}
      </a>
    </section>
  );
}

interface KeyCount {
  readonly key: string;
  readonly count: number;
}

function CountTable({
  data,
  keyLabel,
}: {
  readonly data: Record<string, number>;
  readonly keyLabel: string;
}) {
  const rows: readonly KeyCount[] = Object.entries(data)
    .sort(([, a], [, b]) => b - a)
    .map(([key, count]) => ({ key, count }));

  const columns: readonly Column<KeyCount>[] = [
    { key: "k", header: keyLabel, render: (r) => r.key, cellClass: "mono" },
    { key: "c", header: "Count", render: (r) => r.count, cellClass: "num", headerClass: "num" },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      keyOf={(r) => r.key}
      empty="No data yet."
    />
  );
}
