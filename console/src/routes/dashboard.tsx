import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { DetailDrawer, type DetailDrawerProps } from "../components/detail-drawer";
import {
  LiveDecisionTicker,
  LiveScatterTimeline,
  SignalRail,
  SparkMetricCard,
  type DomainBreakdownRow,
  type EvidenceState,
  type LiveScatterTimelineProps,
  type SignalRailItem,
  type TelemetryCategory,
  type TimelineBucket,
  type TimelinePoint,
  type TimelineView,
  type TimelineWindow,
} from "../components/overview-telemetry";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  type AsyncState,
  type Column,
} from "../components/ui";
import { type ViewFact, usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { getLocale, t } from "../i18n";
import { isPanelRegistered, navigate, routeHref } from "../router";
import { formatConsoleCompactTimestamp } from "../time-format";
import type { AutonomyPayload, DashboardKpi } from "../types";
import {
  auditSampleParams,
  formatShare,
  formatUsd,
  overviewAttentionCount,
  overviewCostEvidence,
  overviewHealth,
  overviewT0Share,
  type GatesSummary,
} from "./dashboard.model";
import { RequiredAttention, RoutingControl } from "./dashboard.distributions";
import {
  ExecutiveStatus,
  MeasurementUnavailable,
  SuccessMetrics,
} from "./dashboard.executive";
import { LivingRules, VerticalCards } from "./dashboard.signals";
import { CohortComparison, useCohortExpiry } from "./dashboard.comparison";
import { DashboardSkeleton } from "./dashboard.skeleton";
import {
  loadDashboardOverviewForMode,
  type DashboardOverviewData,
} from "./dashboard.loading";
import type { ConsoleDataMode } from "../console-data-mode";
import { CurrentPosture } from "./dashboard.posture";
import {
  useChaosResultSummary,
  type ChaosResultSummary,
} from "./chaos-results-summary";
import { tDashboard } from "./i18n/dashboard-essential";
import "./dashboard.css";

interface Props {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}

/**
 * Aggregate promotion-gate signal behind the release guard row. `null`
 * when the gate route is not wired on this deployment (404/501). A
 * `policy_escapes` sum > 0 blocks release per goals-and-metrics (escapes
 * MUST be exactly 0), so it also fails the health axis.
 */
export function resourceDashboardHref(dataMode: ConsoleDataMode): string {
  return routeHref("dashboard-v2", {
    params: { data: dataMode === "sample" ? "sample" : null },
  });
}

export function DashboardRoute({ client, dataMode }: Props) {
  const [state, setState] = useState<AsyncState<DashboardOverviewData>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const chaosResults = useChaosResultSummary(
    client,
    dataMode,
    tDashboard("chaosUnavailable"),
  );

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const data = await loadDashboardOverviewForMode(dataMode, client, (backbone) => {
          if (!cancelled) setState({ status: "ready", data: backbone });
        });
        if (!cancelled) setState({ status: "ready", data });
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
  }, [client, dataMode, attempt]);

  return (
    <div class="stack overview-page overview-essential">
      <PageHeader
        title={t("route.dashboard")}
        subtitle={tDashboard("subtitle")}
        actions={
          isPanelRegistered("dashboard-v2") ? (
            <a
              class="cs-control-button overview-resource-dashboard-link"
              href={resourceDashboardHref(dataMode)}
            >
              <ResourceDashboardIcon />
              <span>{tDashboard("resources")}</span>
            </a>
          ) : undefined
        }
      />
      <AsyncBoundary state={state} resourceLabel="overview" loading={<DashboardSkeleton />}>
        {(data) => (
          <OverviewBody
            chaosResults={dataMode === "live" ? chaosResults : null}
            data={data}
            dataMode={dataMode}
          />
        )}
      </AsyncBoundary>
      {state.status === "error" && (
        <div class="overview-error-actions">
          <button class="btn" type="button" onClick={() => {
            setState({ status: "loading" });
            setAttempt((value) => value + 1);
          }}>{tDashboard("retry")}</button>
          <a
            href={routeHref(
              isPanelRegistered("settings-diagnostics")
                ? "settings-diagnostics"
                : "settings-general",
            )}
          >
            {tDashboard("diagnostics")}
          </a>
        </div>
      )}
    </div>
  );
}

function ResourceDashboardIcon() {
  return (
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" focusable="false">
      <rect x="2.5" y="2.5" width="6" height="6" rx="1" />
      <rect x="11.5" y="2.5" width="6" height="6" rx="1" />
      <rect x="2.5" y="11.5" width="6" height="6" rx="1" />
      <rect x="11.5" y="11.5" width="6" height="6" rx="1" />
    </svg>
  );
}

type OverviewDrawerKind = "events" | "risks" | "human" | "governance";

export interface DashboardTelemetryModel {
  readonly points: readonly TimelinePoint[];
  readonly buckets: readonly TimelineBucket[];
  readonly domains: readonly DomainBreakdownRow[];
  readonly signals: readonly SignalRailItem[];
  readonly totals: Readonly<Record<TelemetryCategory, number>>;
  readonly tickerCategory: TelemetryCategory;
  readonly tickerMessage: string;
  readonly tickerTime: string;
}

function classifyOutcome(outcome: string): TelemetryCategory {
  const key = outcome.toLowerCase();
  if (
    key.includes("den")
    || key.includes("block")
    || key.includes("fail")
    || key.includes("escape")
    || key.includes("sec")
    || key.includes("reject")
    || key.includes("violat")
  ) {
    return "sec";
  }
  if (
    key.includes("approval")
    || key.includes("hil")
    || key.includes("human")
    || key.includes("escalat")
    || key.includes("pending")
  ) {
    return "human";
  }
  if (
    key.includes("degrad")
    || key.includes("held")
    || key.includes("retain")
    || key.includes("retry")
    || key.includes("timeout")
    || key.includes("warn")
    || key.includes("stall")
  ) {
    return "sre";
  }
  return "auto";
}

export function buildDashboardTelemetry(
  kpi: DashboardKpi,
  autonomy: AutonomyPayload | null,
  gates: GatesSummary | null,
  policyEscapes: number | null,
  onSelectSignal?: (kind: OverviewDrawerKind) => void,
): DashboardTelemetryModel {
  const autoTrend = autonomy?.trend?.auto_resolution_rate ?? [];
  const touchTrend = autonomy?.trend?.human_touchpoints ?? [];
  const bucketCount = Math.max(autoTrend.length, touchTrend.length);
  const failedGuards = autonomy && !autonomy.synthetic
    ? autonomy.guards.filter((guard) => !guard.ok).length
    : 0;
  const openRisks = autonomy
    ? autonomy.verticals.reduce((sum, vertical) => sum + vertical.open_risks, 0)
    : 0;
  const secCount = (policyEscapes ?? 0) + failedGuards;

  const buckets: TimelineBucket[] = bucketCount > 0
    ? Array.from({ length: bucketCount }, (_, index) => {
      const autoVal = Math.round((autoTrend[index] ?? 0) * 100);
      const humanVal = Math.round(touchTrend[index] ?? 0);
      const isLast = index === bucketCount - 1;
      return {
        label: `T-${bucketCount - index}`,
        auto: autoVal,
        sre: isLast ? openRisks : Math.max(0, Math.round(openRisks / Math.max(bucketCount, 1))),
        sec: isLast ? secCount : 0,
        human: humanVal,
      };
    })
    : Object.entries(kpi.by_outcome)
      .filter(([, count]) => count > 0)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 8)
      .map(([outcome, count]) => {
        const category = classifyOutcome(outcome);
        return {
          label: outcome,
          auto: category === "auto" ? count : 0,
          sre: category === "sre" ? count : 0,
          sec: category === "sec" ? count : 0,
          human: category === "human" ? count : 0,
        };
      });

  const totals = buckets.reduce(
    (acc, bucket) => ({
      auto: acc.auto + bucket.auto,
      sre: acc.sre + bucket.sre,
      sec: acc.sec + bucket.sec,
      human: acc.human + bucket.human,
    }),
    { auto: 0, sre: 0, sec: 0, human: 0 },
  );

  const points: TimelinePoint[] = buckets.map((bucket, index) => {
    const category: TelemetryCategory = bucket.sec > 0
      ? "sec"
      : bucket.sre > 0
      ? "sre"
      : bucket.human > 0
      ? "human"
      : "auto";
    const total = Math.max(bucket.auto + bucket.sre + bucket.sec + bucket.human, 1);
    const riskScore = category === "sec"
      ? Math.min(94, 70 + Math.min(24, bucket.sec * 4))
      : category === "sre"
      ? Math.min(82, 52 + Math.min(30, Math.round(Math.log10(bucket.sre + 1) * 10)))
      : category === "human"
      ? Math.min(72, 42 + Math.min(30, Math.round(Math.log10(bucket.human + 1) * 10)))
      : Math.max(12, Math.min(36, 14 + Math.round((bucket.auto / total) * 18)));
    return {
      id: `pt-${index}`,
      timeLabel: bucket.label,
      riskScore,
      category,
      summary: tDashboard("timelinePointSummary", {
        auto: bucket.auto,
        sre: bucket.sre,
        sec: bucket.sec,
        human: bucket.human,
      }),
    };
  });

  const domains: DomainBreakdownRow[] = autonomy
    ? autonomy.verticals.map((vertical) => ({
      id: vertical.key,
      label: vertical.key,
      auto: vertical.auto_resolved,
      sre: vertical.open_risks,
      sec: 0,
      human: Math.max(0, vertical.events - vertical.auto_resolved - vertical.open_risks),
    }))
    : [];

  const signals: SignalRailItem[] = [
    ...(kpi.hil_pending > 0 ? [{
      id: "sig-hil",
      category: "human" as const,
      label: tDashboard("pendingCount", { count: kpi.hil_pending }),
      ...(onSelectSignal ? { onSelect: () => onSelectSignal("human") } : {}),
    }] : []),
    ...(policyEscapes !== null && policyEscapes > 0 ? [{
      id: "sig-escapes",
      category: "sec" as const,
      label: tDashboard("kpiRisksDeltaEscapes", { count: policyEscapes }),
      ...(onSelectSignal ? { onSelect: () => onSelectSignal("risks") } : {}),
    }] : []),
    ...(gates && gates.blocked_count > 0 ? [{
      id: "sig-gates",
      category: "sre" as const,
      label: tDashboard("kpiRisksFooterRight", { count: gates.blocked_count }),
      ...(onSelectSignal ? { onSelect: () => onSelectSignal("governance") } : {}),
    }] : []),
    ...(kpi.event_count > 0 ? [{
      id: "sig-events",
      category: "auto" as const,
      label: tDashboard("kpiEventsFooterLeft", { count: kpi.audit_sample?.row_count ?? kpi.event_count }),
      ...(onSelectSignal ? { onSelect: () => onSelectSignal("events") } : {}),
    }] : []),
  ];

  const tickerCategory: TelemetryCategory = policyEscapes !== null && policyEscapes > 0
    ? "sec"
    : kpi.hil_pending > 0
    ? "human"
    : openRisks > 0 || totals.sre > 0
    ? "sre"
    : "auto";
  const tickerMessage = policyEscapes !== null && policyEscapes > 0
    ? `${tDashboard("escapes")}: ${policyEscapes}`
    : kpi.hil_pending > 0
    ? `${tDashboard("kpiHumanLabel")}: ${tDashboard("pendingCount", { count: kpi.hil_pending })}`
    : kpi.event_count > 0
    ? `${tDashboard("kpiEventsLabel")}: ${kpi.event_count} (${tDashboard("kpiEventsFooterRight", { share: formatShare(kpi.shadow_share) })})`
    : tDashboard("tickerFallbackMessage");
  const tickerTime = kpi.last_recorded_at
    ? formatConsoleCompactTimestamp(kpi.last_recorded_at)
    : "-";

  return { points, buckets, domains, signals, totals, tickerCategory, tickerMessage, tickerTime };
}

function OverviewBody({
  chaosResults,
  data,
  dataMode,
}: {
  readonly chaosResults: AsyncState<ChaosResultSummary> | null;
  readonly data: DashboardOverviewData;
  readonly dataMode: ConsoleDataMode;
}) {
  const { kpi, cost, gates, autonomy, optionalPending = false } = data;
  const [drawerKind, setDrawerKind] = useState<OverviewDrawerKind | null>(null);
  const [timelineView, setTimelineView] = useState<TimelineView>("scatter");
  const [timelineWindow, setTimelineWindow] = useState<TimelineWindow>("15m");
  const [paused, setPaused] = useState(false);
  const [visibleSeries, setVisibleSeries] = useState<Record<TelemetryCategory, boolean>>({
    auto: true,
    sre: true,
    sec: true,
    human: true,
  });
  const comparisonExpired = useCohortExpiry(autonomy?.comparison?.valid_until);
  const sampleParams = auditSampleParams(kpi);
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";

  const t0Share = overviewT0Share(kpi.by_tier);
  const policyEscapes = gates ? gates.rows.reduce((sum, r) => sum + r.policy_escapes, 0) : null;
  const readyCount = gates ? gates.ready_count : null;
  const gateTotal = gates ? gates.rows.length : null;
  // A policy escape blocks release (goals-and-metrics: escapes MUST be 0),
  // so it fails the health axis just like a pending human approval does.
  const health = overviewHealth(kpi, policyEscapes, autonomy);
  const attentionCount = overviewAttentionCount(kpi, policyEscapes, autonomy);
  const costEvidence = overviewCostEvidence(cost);
  const savings = costEvidence.monthlySavings;
  const failedGuards = autonomy && !autonomy.synthetic
    ? autonomy.guards.filter((guard) => !guard.ok).length
    : null;
  const openRisks = autonomy
    ? autonomy.verticals.reduce((sum, vertical) => sum + vertical.open_risks, 0)
    : null;
  const autoResolvedTotal = autonomy
    ? autonomy.verticals.reduce((sum, vertical) => sum + vertical.auto_resolved, 0)
    : null;
  const autoResRate = autonomy?.success.auto_resolution_rate.value ?? null;
  const riskEvidenceState: EvidenceState = policyEscapes === null && openRisks === null
    ? "unavailable"
    : autonomy?.synthetic
    ? "simulated"
    : "measured";
  const riskCount = riskEvidenceState === "unavailable"
    ? "-"
    : (policyEscapes ?? 0) + (failedGuards ?? 0) + (openRisks ?? 0);
  const govEvidenceState: EvidenceState = health === "unknown"
    ? "unavailable"
    : autonomy?.synthetic
    ? "simulated"
    : "measured";
  const govValue = health === "healthy"
    ? tDashboard("kpiGovStatusHealthy")
    : health === "attention"
    ? tDashboard("kpiGovStatusAttention")
    : tDashboard("kpiGovStatusUnknown");
  const telemetry = buildDashboardTelemetry(kpi, autonomy, gates, policyEscapes, setDrawerKind);
  const timelineStreamState: LiveScatterTimelineProps["streamState"] =
    telemetry.points.length === 0 && telemetry.domains.length === 0
      ? "unavailable"
      : paused
      ? "paused"
      : dataMode === "sample"
      ? "static"
      : "live";
  const timelineTotal =
    telemetry.totals.auto + telemetry.totals.sre + telemetry.totals.sec + telemetry.totals.human;
  const timelineSummary = timelineTotal > 0
    ? tDashboard("timelineSummary", {
      window: timelineWindow,
      total: timelineTotal.toLocaleString(locale),
      auto: telemetry.totals.auto.toLocaleString(locale),
      sre: telemetry.totals.sre.toLocaleString(locale),
      sec: telemetry.totals.sec.toLocaleString(locale),
      human: telemetry.totals.human.toLocaleString(locale),
    })
    : undefined;
  const timelineProps: LiveScatterTimelineProps = {
    title: tDashboard("timelineTitle"),
    subtitle: tDashboard("timelineSubtitle"),
    streamState: timelineStreamState,
    view: timelineView,
    onViewChange: setTimelineView,
    window: timelineWindow,
    onWindowChange: setTimelineWindow,
    ...(timelineStreamState !== "unavailable"
      ? { onTogglePause: () => setPaused((value) => !value) }
      : {}),
    points: telemetry.points,
    buckets: telemetry.buckets,
    domains: telemetry.domains,
    visibleSeries,
    onToggleSeries: (category) => setVisibleSeries((current) => ({
      ...current,
      [category]: !current[category],
    })),
    ...(timelineSummary ? { summaryText: timelineSummary } : {}),
    labels: {
      scatter: tDashboard("timelineScatter"),
      stacked: tDashboard("timelineStacked"),
      domain: tDashboard("timelineDomain"),
      auto: tDashboard("timelineSeriesAuto"),
      sre: tDashboard("timelineSeriesSre"),
      sec: tDashboard("timelineSeriesSec"),
      human: tDashboard("timelineSeriesHuman"),
      now: tDashboard("timelineNow"),
      unavailable: tDashboard("timelineUnavailable"),
      pause: tDashboard("timelinePause"),
      resume: tDashboard("timelineResume"),
      timeWindowAria: tDashboard("timelineWindowAria"),
      seriesFiltersAria: tDashboard("timelineSeriesAria"),
      riskAxis: tDashboard("timelineRiskAxis"),
      forecastZone: tDashboard("timelineForecastZone"),
      streamLive: tDashboard("timelineStreamLive"),
      streamPaused: tDashboard("timelineStreamPaused"),
      streamStatic: tDashboard("timelineStreamStatic"),
      streamUnavailable: tDashboard("timelineStreamUnavailable"),
    },
  };
  const tickerCategoryLabel = telemetry.tickerCategory === "sec"
    ? tDashboard("timelineSeriesSec")
    : telemetry.tickerCategory === "sre"
    ? tDashboard("timelineSeriesSre")
    : telemetry.tickerCategory === "human"
    ? tDashboard("timelineSeriesHuman")
    : tDashboard("timelineSeriesAuto");
  const drawerConfig = drawerKind === "events"
    ? {
      title: tDashboard("drawerEventsTitle"),
      subtitle: tDashboard("drawerEventsSubtitle"),
      href: routeHref("audit", { params: sampleParams }),
      actionLabel: tDashboard("drawerOpenAudit"),
      facts: [
        { label: tDashboard("drawerMetricSample"), value: (kpi.audit_sample?.row_count ?? kpi.event_count).toLocaleString(locale) },
        { label: tDashboard("drawerMetricT0"), value: t0Share === "unavailable" ? tDashboard("kpiUnmeasured") : t0Share },
        { label: tDashboard("observation"), value: formatShare(kpi.shadow_share) },
        { label: tDashboard("drawerMetricEnforce"), value: formatShare(kpi.enforce_share) },
      ],
    }
    : drawerKind === "risks"
    ? {
      title: tDashboard("drawerRisksTitle"),
      subtitle: tDashboard("drawerRisksSubtitle"),
      href: routeHref("promotion-gates", { params: { status: "blocked" } }),
      actionLabel: tDashboard("drawerOpenGates"),
      facts: [
        { label: tDashboard("drawerMetricEscapes"), value: policyEscapes === null ? tDashboard("kpiUnmeasured") : String(policyEscapes) },
        { label: tDashboard("drawerMetricGuards"), value: failedGuards === null ? tDashboard("kpiUnmeasured") : String(failedGuards) },
        { label: tDashboard("drawerMetricGates"), value: readyCount !== null && gateTotal !== null ? `${readyCount}/${gateTotal}` : tDashboard("kpiUnmeasured") },
      ],
    }
    : drawerKind === "human"
    ? {
      title: tDashboard("drawerHumanTitle"),
      subtitle: tDashboard("drawerHumanSubtitle"),
      href: routeHref("hil-queue"),
      actionLabel: tDashboard("drawerOpenApprovals"),
      facts: [
        { label: tDashboard("drawerMetricPending"), value: kpi.hil_pending.toLocaleString(locale) },
        { label: tDashboard("drawerMetricAutoRate"), value: autoResRate === null ? tDashboard("kpiUnmeasured") : formatShare(autoResRate) },
        { label: tDashboard("drawerMetricSavings"), value: savings === null ? tDashboard("kpiUnmeasured") : formatUsd(savings) },
      ],
    }
    : drawerKind === "governance"
    ? {
      title: tDashboard("drawerGovTitle"),
      subtitle: tDashboard("drawerGovSubtitle"),
      href: routeHref("operating-outcomes"),
      actionLabel: tDashboard("drawerOpenOutcomes"),
      facts: [
        { label: tDashboard("kpiGovLabel"), value: govValue },
        { label: tDashboard("drawerMetricEscapes"), value: policyEscapes === null ? tDashboard("kpiUnmeasured") : String(policyEscapes) },
        { label: tDashboard("drawerMetricRules"), value: autonomy && autonomy.rules_evidence !== "unavailable" ? String(autonomy.rules.active) : tDashboard("kpiUnmeasured") },
        { label: tDashboard("drawerMetricEnforce"), value: formatShare(kpi.enforce_share) },
      ],
    }
    : null;
  const drawerProps: DetailDrawerProps = {
    open: drawerConfig !== null,
    title: drawerConfig?.title ?? "",
    ...(drawerConfig?.subtitle !== undefined ? { subtitle: drawerConfig.subtitle } : {}),
    onClose: () => setDrawerKind(null),
    closeLabel: tDashboard("drawerClose"),
    ...(drawerConfig ? {
      footer: (
        <div class="overview-drawer-actions">
          <a class="cs-control-button" href={drawerConfig.href}>
            {drawerConfig.actionLabel}
          </a>
          {isPanelRegistered("verticals") ? (
            <a class="cs-control-button" href={routeHref("verticals")}>
              {tDashboard("drawerOpenVerticals")}
            </a>
          ) : null}
        </div>
      ),
    } : {}),
    children: drawerConfig ? (
      <dl class="overview-drawer-facts">
        {drawerConfig.facts.map((fact) => (
          <div key={fact.label} class="overview-drawer-fact">
            <dt>{fact.label}</dt>
            <dd>{fact.value}</dd>
          </div>
        ))}
      </dl>
    ) : null,
  };

  usePublishViewContext(
    () => {
      const comparison = autonomy?.comparison && !comparisonExpired ? autonomy.comparison : null;
      // The Overview renders an autonomy hero, success-metrics-vs-baseline,
      // per-vertical cards, and guard bands from the /kpi/autonomy panel.
      // Publish that surface (not just the audit KPIs) so the deck can answer
      // "what is the auto-resolution rate / savings per vertical / are the
      // guards ok?". `synthetic` is surfaced so the deck can flag dev values.
      const autonomyFacts: ViewFact[] = autonomy
        ? [
            { key: "measurement_synthetic", value: autonomy.synthetic, group: "autonomy" },
            {
              key: "auto_resolution_rate",
              label: t("overview.metric.autoRes"),
              aliases: ["auto-resolution", "automatic resolution", "자동 해결", "자율 해결"],
              value: autonomy.success.auto_resolution_rate.value,
              group: "autonomy",
            },
            { key: "auto_resolution_baseline", value: autonomy.success.auto_resolution_rate.baseline, group: "autonomy" },
            {
              key: "human_touchpoints_per_100",
              label: t("overview.metric.touchpoints"),
              aliases: ["human touchpoints", "사람 개입", "사람 검토"],
              value: autonomy.success.human_touchpoints_per_100.value,
              group: "autonomy",
            },
            {
              key: "mttr_seconds",
              label: t("overview.metric.mttr"),
              aliases: ["mean time to recovery", "평균 복구시간"],
              value: autonomy.success.mttr_seconds.value,
              group: "autonomy",
            },
            {
              key: "change_lead_time_seconds",
              label: t("overview.metric.leadTime"),
              aliases: ["change lead time", "변경 리드타임"],
              value: autonomy.success.change_lead_time_seconds.value,
              group: "autonomy",
            },
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
        routeLabel: t("route.dashboard"),
        purpose:
          "The at-a-glance health of the control plane: event volume, the " +
          "shadow/enforce split, T0 deterministic share, approval backlog, and " +
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
          `${kpi.hil_pending} approvals pending - ` +
          (savings !== null ? `${formatUsd(savings)}/mo saved` : "cost n/a"),
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "health", value: health, group: "overview" },
          { key: "measurements_pending", value: optionalPending, group: "autonomy" },
          {
            key: "section_count",
            aliases: ["primary sections", "주요 영역"],
            value: 4,
            group: "page",
          },
          {
            key: "event_count",
            label: t("overview.detailMetric.events"),
            aliases: ["audit events", "event count", "감사 이벤트", "이벤트 수"],
            value: kpi.event_count,
            group: "overview",
          },
          {
            key: "shadow_share",
            label: t("overview.detailMetric.shadow"),
            aliases: ["shadow coverage", "shadow share", "Shadow 비율", "관찰 모드 비율"],
            value: formatShare(kpi.shadow_share),
            group: "overview",
          },
          {
            key: "t0_share",
            label: t("overview.tier.label"),
            aliases: ["T0 share", "deterministic share", "T0 비율", "결정론 비율"],
            value: t0Share,
            group: "overview",
          },
          {
            key: "hil_pending",
            label: t("overview.detailMetric.approvals"),
            aliases: ["approvals pending", "pending approvals", "승인 대기", "대기 승인"],
            value: kpi.hil_pending,
            group: "overview",
          },
          {
            key: "measurement_state",
            value: autonomy === null ? "unavailable" : autonomy.synthetic ? "simulated" : "measured",
            group: "autonomy",
          },
          {
            key: "measurement_source",
            value: autonomy?.source.name ?? "not connected",
            group: "autonomy",
          },
          {
            key: "monthly_savings",
            value: savings !== null ? formatUsd(savings) : "n/a",
            group: "cost",
          },
          {
            key: "cost_recommendations",
            value: costEvidence.recommendationCount,
            group: "cost",
          },
          { key: "policy_escapes", value: policyEscapes ?? "n/a", group: "guards" },
          {
            key: "promotion_ready",
            value: gateTotal !== null ? `${readyCount}/${gateTotal}` : "n/a",
            group: "guards",
          },
          ...(chaosResults?.status === "ready" ? [
            { key: "chaos_experiments", value: chaosResults.data.experiments, group: "chaos_validation" },
            { key: "chaos_validated", value: chaosResults.data.validated, group: "chaos_validation" },
            { key: "chaos_detection_gaps", value: chaosResults.data.detectionGaps, group: "chaos_validation" },
            { key: "chaos_rollback_failures", value: chaosResults.data.rollbackFailures, group: "chaos_validation" },
          ] : []),
          ...autonomyFacts,
        ],
        records: {
          cohort_comparison_context: comparison ? [{
            scope: "separate_admitted_cohort",
            revision: comparison.fdai_revision,
            protocol_version: comparison.measurement_protocol_version,
            published_at: comparison.published_at,
            valid_until: comparison.valid_until,
          }] : [],
          cohort_comparison_metrics: comparison ? comparison.baseline.metrics.map((metric, index) => ({
            metric: metric.metric_id,
            baseline: metric.absolute_value,
            treatment: comparison.treatment.metrics[index]!.absolute_value,
            baseline_sample_size: metric.sample_size,
            treatment_sample_size: comparison.treatment.metrics[index]!.sample_size,
          })) : [],
          sections: [
            {
              position: 1,
              label: tDashboard("attention"),
              detail: tDashboard("attentionHint"),
              evidence_state: "available",
            },
            {
              position: 2,
              label: tDashboard("posture"),
              detail: tDashboard("postureHint"),
              evidence_state: optionalPending ? "loading" : autonomy === null ? "unavailable" : "available",
            },
            {
              position: 3,
              label: t("overview.section.routing"),
              detail: t("overview.section.routingHint"),
              evidence_state: "available",
            },
            {
              position: 4,
              label: t("overview.section.outcomes"),
              detail: t("overview.section.outcomesHint"),
              evidence_state: optionalPending ? "loading" : autonomy === null ? "unavailable" : "available",
            },
          ],
          controls: [
            {
              control: "open_audit_events",
              label: t("overview.detailMetric.events"),
              detail: t("overview.detailMetric.eventsHint"),
              enabled: true,
            },
            {
              control: "open_pending_approvals",
              label: t("overview.detailMetric.approvals"),
              detail: kpi.hil_pending > 0
                ? t("overview.detailMetric.approvalHint")
                : t("overview.detailMetric.approvalClear"),
              enabled: true,
            },
          ],
          constraints: autonomy === null
            ? [{
                constraint: "autonomy_evidence_required",
                label: t("overview.evidence.unavailable"),
                detail: t("overview.evidence.unavailableHint"),
              }]
            : [],
          by_action_kind: Object.entries(kpi.by_action_kind)
            .sort(([, a], [, b]) => b - a)
            .map(([key, count]) => ({ key, count })),
          by_outcome: Object.entries(kpi.by_outcome)
            .sort(([, a], [, b]) => b - a)
            .map(([key, count]) => ({ key, count })),
          ...autonomyRecords,
          chaos_validation: chaosResults?.status === "ready" ? [{ ...chaosResults.data }] : [],
        },
      };
    },
    [kpi, cost, gates, autonomy, health, savings, t0Share, optionalPending, comparisonExpired, chaosResults],
  );

  return (
    <div class="stack overview-report">
      <section class="overview-kpi-grid" aria-label={t("route.dashboard")}>
        <SparkMetricCard
          id="overview-kpi-events"
          label={tDashboard("kpiEventsLabel")}
          value={kpi.event_count.toLocaleString(locale)}
          unit={tDashboard("kpiEventsUnit")}
          {...(t0Share !== "unavailable" ? { delta: tDashboard("kpiEventsDelta", { share: t0Share }) } : {})}
          deltaTone="live"
          evidenceState={autonomy?.synthetic ? "simulated" : "measured"}
          unmeasuredLabel={tDashboard("kpiUnmeasured")}
          {...(Object.values(kpi.by_action_kind).length > 0 ? {
            spark: {
              kind: "area" as const,
              values: Object.values(kpi.by_action_kind),
              ariaLabel: tDashboard("kpiEventsSpark"),
            },
          } : {})}
          footerLeft={tDashboard("kpiEventsFooterLeft", {
            count: (kpi.audit_sample?.row_count ?? kpi.event_count).toLocaleString(locale),
          })}
          footerRight={tDashboard("kpiEventsFooterRight", { share: formatShare(kpi.shadow_share) })}
          onOpenDetail={() => setDrawerKind("events")}
        />
        <SparkMetricCard
          id="overview-kpi-risks"
          label={tDashboard("kpiRisksLabel")}
          value={riskCount}
          {...(riskEvidenceState !== "unavailable" ? { unit: tDashboard("kpiRisksUnit") } : {})}
          {...(policyEscapes !== null ? {
            delta: policyEscapes > 0
              ? tDashboard("kpiRisksDeltaEscapes", { count: policyEscapes })
              : tDashboard("kpiRisksDeltaClear"),
          } : {})}
          deltaTone={policyEscapes !== null && policyEscapes > 0 ? "sec" : "sre"}
          evidenceState={riskEvidenceState}
          unmeasuredLabel={tDashboard("kpiUnmeasured")}
          {...(autonomy && autonomy.verticals.length > 0 ? {
            spark: {
              kind: "dual-bar" as const,
              values: autonomy.verticals.map((vertical) => vertical.open_risks),
              secondaryValues: autonomy.verticals.map(() => policyEscapes ?? 0),
              color: "var(--sig-sre, #c86d18)",
              secondaryColor: "var(--sig-sec, #a63446)",
              ariaLabel: tDashboard("kpiRisksSpark"),
            },
          } : {})}
          footerLeft={tDashboard("kpiRisksFooterLeft", {
            count: failedGuards === null ? "-" : failedGuards,
          })}
          footerRight={tDashboard("kpiRisksFooterRight", {
            count: gates ? gates.blocked_count : "-",
          })}
          onOpenDetail={() => setDrawerKind("risks")}
        />
        <SparkMetricCard
          id="overview-kpi-human"
          label={tDashboard("kpiHumanLabel")}
          value={kpi.hil_pending.toLocaleString(locale)}
          unit={tDashboard("kpiHumanUnit")}
          {...(autoResRate !== null ? { delta: tDashboard("kpiHumanDelta", { share: formatShare(autoResRate) }) } : {})}
          deltaTone={kpi.hil_pending > 0 ? "human" : "live"}
          evidenceState={autonomy?.synthetic ? "simulated" : "measured"}
          unmeasuredLabel={tDashboard("kpiUnmeasured")}
          {...(autonomy?.trend?.human_touchpoints && autonomy.trend.human_touchpoints.length > 0 ? {
            spark: {
              kind: "line" as const,
              values: autonomy.trend.human_touchpoints,
              color: "var(--sig-human, #4a2574)",
              ariaLabel: tDashboard("kpiHumanSpark"),
            },
          } : {})}
          footerLeft={tDashboard("kpiHumanFooterLeft", { count: kpi.hil_pending })}
          footerRight={tDashboard("kpiHumanFooterRight", {
            count: autoResolvedTotal === null ? "-" : autoResolvedTotal.toLocaleString(locale),
          })}
          onOpenDetail={() => setDrawerKind("human")}
        />
        <SparkMetricCard
          id="overview-kpi-governance"
          label={tDashboard("kpiGovLabel")}
          value={govValue}
          {...(policyEscapes !== null ? {
            delta: policyEscapes > 0
              ? tDashboard("kpiRisksDeltaEscapes", { count: policyEscapes })
              : tDashboard("kpiRisksDeltaClear"),
          } : {})}
          deltaTone={health === "healthy" ? "live" : health === "attention" ? "sre" : "neutral"}
          evidenceState={govEvidenceState}
          unmeasuredLabel={tDashboard("kpiUnmeasured")}
          {...(autonomy?.trend?.auto_resolution_rate && autonomy.trend.auto_resolution_rate.length > 0 ? {
            spark: {
              kind: "step" as const,
              values: autonomy.trend.auto_resolution_rate.map((value) => Math.round(value * 100)),
              color: "var(--sig-live, #0f766e)",
              ariaLabel: tDashboard("kpiGovSpark"),
            },
          } : {})}
          footerLeft={tDashboard("kpiGovFooterLeft", {
            count: autonomy && autonomy.rules_evidence !== "unavailable" ? autonomy.rules.active : "-",
          })}
          footerRight={tDashboard("kpiGovFooterRight", { share: formatShare(kpi.enforce_share) })}
          onOpenDetail={() => setDrawerKind("governance")}
        />
      </section>

      <div class="overview-timeline-section">
        <LiveScatterTimeline {...timelineProps}>
          {telemetry.signals.length > 0 ? (
            <SignalRail caption={tDashboard("signalRailCaption")} items={telemetry.signals} />
          ) : null}
          <LiveDecisionTicker
            timestamp={telemetry.tickerTime}
            category={telemetry.tickerCategory}
            categoryLabel={tickerCategoryLabel}
            message={telemetry.tickerMessage}
            actionLabel={tDashboard("tickerHistory")}
            onOpenHistory={() => navigate(routeHref("audit", { params: sampleParams }))}
          />
        </LiveScatterTimeline>
      </div>

      <div class="overview-principle-strip" role="note">
        <span>{tDashboard("principleNote")}</span>
      </div>

      <details class="advanced-details overview-details">
        <summary>
          <h3 class="section-title">{t("overview.detail")}</h3>
          <span class="muted">{tDashboard("evidenceHint")}</span>
        </summary>
        <div class="stack overview-details-body">
          <OverviewSection
            id="attention"
            title={tDashboard("attention")}
            description={tDashboard("attentionHint")}
          >
            <RequiredAttention kpi={kpi} gates={gates} autonomy={autonomy} policyEscapes={policyEscapes} optionalPending={optionalPending} compact />
          </OverviewSection>

          <OverviewSection
            id="posture"
            title={tDashboard("posture")}
            description={tDashboard("postureHint")}
          >
            <CurrentPosture kpi={kpi} autonomy={autonomy} policyEscapes={policyEscapes} pending={optionalPending} />
          </OverviewSection>

          <OverviewSection
            id="routing"
            title={t("overview.section.routing")}
            description={tDashboard("routingHint")}
          >
            <RoutingControl kpi={kpi} compact />
          </OverviewSection>

          <OverviewSection
            id="outcomes"
            title={t("overview.section.outcomes")}
            description={tDashboard("outcomesHint")}
          >
            <SuccessMetrics success={autonomy?.success ?? null} pending={optionalPending} />
          </OverviewSection>

          <CohortComparison comparison={autonomy?.comparison} />
          <ExecutiveStatus
            health={health}
            kpi={kpi}
            autonomy={autonomy}
            attentionCount={attentionCount}
            policyEscapes={policyEscapes}
          />
          {chaosResults ? (
            <OverviewSection
              id="chaos-validation"
              title={tDashboard("chaosTitle")}
              description={tDashboard("chaosDescription")}
            >
              <AsyncBoundary state={chaosResults} resourceLabel={tDashboard("chaosResourceLabel")}>
                {(summary) => (
                  <KpiGrid>
                    <KpiCard href={routeHref("reports", { segments: ["chaos-enforce-results"] })} label={tDashboard("chaosExperiments")} value={summary.experiments} hint={tDashboard("chaosMeasuredHint")} />
                    <KpiCard href={routeHref("reports", { segments: ["chaos-enforce-results"] })} label={tDashboard("chaosValidated")} value={summary.validated} hint={tDashboard("chaosMeasuredHint")} tone="positive" />
                    <KpiCard href={routeHref("reports", { segments: ["chaos-enforce-results"] })} label={tDashboard("chaosDetectionGaps")} value={summary.detectionGaps} hint={tDashboard("chaosMeasuredHint")} tone={summary.detectionGaps > 0 ? "warning" : "positive"} />
                    <KpiCard href={routeHref("reports", { segments: ["chaos-enforce-results"] })} label={tDashboard("chaosRollbackFailures")} value={summary.rollbackFailures} hint={tDashboard("chaosMeasuredHint")} tone={summary.rollbackFailures > 0 ? "warning" : "positive"} />
                  </KpiGrid>
                )}
              </AsyncBoundary>
            </OverviewSection>
          ) : null}
          <OverviewSection id="verticals" title={t("overview.section.verticals")} description={t("overview.section.verticalsHint")}>
            {autonomy ? (
              <VerticalCards verticals={autonomy.verticals} />
            ) : (
              <a class="overview-unavailable-link" href={routeHref("verticals")}><MeasurementUnavailable /></a>
            )}
          </OverviewSection>
          <KpiGrid>
            <KpiCard href={routeHref("audit", { params: sampleParams })} label={t("overview.detailMetric.events")} value={kpi.event_count} hint={t("overview.detailMetric.eventsHint")} />
            <KpiCard href={routeHref("audit", { params: { ...sampleParams, mode: "shadow" } })} label={t("overview.detailMetric.shadow")} value={formatShare(kpi.shadow_share)} hint={t("overview.detailMetric.shadowHint")} tone={kpi.shadow_share > 0.95 ? "positive" : "default"} />
            <KpiCard href={routeHref("audit", { params: { ...sampleParams, mode: "enforce" } })} label={t("overview.detailMetric.enforce")} value={formatShare(kpi.enforce_share)} hint={t("overview.detailMetric.enforceHint")} />
            <KpiCard href={routeHref("hil-queue")} label={t("overview.detailMetric.approvals")} value={kpi.hil_pending} tone={kpi.hil_pending > 0 ? "warning" : "positive"} hint={kpi.hil_pending > 0 ? t("overview.detailMetric.approvalHint") : t("overview.detailMetric.approvalClear")} />
          </KpiGrid>

          {autonomy && autonomy.rules_evidence !== "unavailable" ? (
            <LivingRules rules={autonomy.rules} provenance={autonomy} />
          ) : (
            <a class="overview-unavailable-link" href={routeHref("rules")}>
              <MeasurementUnavailable />
            </a>
          )}

          <div class="two-col">
            <section class="stack-section">
              <h3 class="section-title">{t("overview.detailMetric.actionsByKind")}</h3>
              <CountTable data={kpi.by_action_kind} keyLabel={t("overview.detailMetric.actionKind")} filterKey="action" sampleParams={sampleParams} />
            </section>
            <section class="stack-section">
              <h3 class="section-title">{t("overview.detailMetric.outcomes")}</h3>
              <CountTable data={kpi.by_outcome} keyLabel={t("overview.detailMetric.outcome")} filterKey="outcome" sampleParams={sampleParams} />
            </section>
          </div>
        </div>
      </details>
      <DetailDrawer {...drawerProps} />
    </div>
  );
}

function OverviewSection({
  id,
  title,
  description,
  children,
}: {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly children: preact.ComponentChildren;
}) {
  return (
    <section class={`overview-section overview-section-${id}`} aria-labelledby={`overview-section-${id}`}>
      <header class="overview-section-head">
        <div>
          <h3 id={`overview-section-${id}`}>{title}</h3>
          <p>{description}</p>
        </div>
      </header>
      {children}
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
  filterKey,
  sampleParams,
}: {
  readonly data: Record<string, number>;
  readonly keyLabel: string;
  readonly filterKey: "action" | "outcome";
  readonly sampleParams: Readonly<Record<string, number>>;
}) {
  const rows: readonly KeyCount[] = Object.entries(data)
    .sort(([, a], [, b]) => b - a)
    .map(([key, count]) => ({ key, count }));

  const columns: readonly Column<KeyCount>[] = [
    { key: "k", header: keyLabel, render: (r) => <a href={routeHref("audit", { params: { ...sampleParams, [filterKey]: r.key } })}>{r.key}</a>, cellClass: "mono" },
    {
      key: "c",
      header: t("overview.detailMetric.count"),
      render: (r) => (
        <a href={routeHref("audit", { params: { ...sampleParams, [filterKey]: r.key } })}>
          {r.count}
        </a>
      ),
      cellClass: "num",
      headerClass: "num",
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={rows}
      keyOf={(r) => r.key}
      empty={t("overview.detailMetric.empty")}
    />
  );
}
