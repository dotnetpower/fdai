import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
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
import { t } from "../i18n";
import { routeHref } from "../router";
import {
  auditSampleParams,
  formatShare,
  formatUsd,
  overviewAttentionCount,
  overviewCostEvidence,
  overviewHealth,
  overviewT0Share,
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
          <a class="cs-control-button overview-resource-dashboard-link" href={routeHref("dashboard-v2")}>
            <ResourceDashboardIcon />
            <span>{tDashboard("resources")}</span>
          </a>
        }
      />
      <AsyncBoundary state={state} resourceLabel="overview" loading={<DashboardSkeleton />}>
        {(data) => (
          <OverviewBody
            chaosResults={dataMode === "live" ? chaosResults : null}
            data={data}
          />
        )}
      </AsyncBoundary>
      {state.status === "error" && (
        <div class="overview-error-actions">
          <button class="btn" type="button" onClick={() => {
            setState({ status: "loading" });
            setAttempt((value) => value + 1);
          }}>{tDashboard("retry")}</button>
          <a href={routeHref("settings-diagnostics")}>{tDashboard("diagnostics")}</a>
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

function OverviewBody({
  chaosResults,
  data,
}: {
  readonly chaosResults: AsyncState<ChaosResultSummary> | null;
  readonly data: DashboardOverviewData;
}) {
  const { kpi, cost, gates, autonomy, optionalPending = false } = data;
  const comparisonExpired = useCohortExpiry(autonomy?.comparison?.valid_until);
  const sampleParams = auditSampleParams(kpi);

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

      <details class="advanced-details overview-details">
        <summary>
          <h3 class="section-title">{t("overview.detail")}</h3>
          <span class="muted">{tDashboard("evidenceHint")}</span>
        </summary>
        <div class="stack overview-details-body">
          <CohortComparison comparison={autonomy?.comparison} />
          <ExecutiveStatus
            health={health}
            kpi={kpi}
            autonomy={autonomy}
            attentionCount={attentionCount}
            policyEscapes={policyEscapes}
          />
          <OverviewSection id="controls" title={t("overview.section.attention")} description={t("overview.section.attentionHint")}>
            <RequiredAttention kpi={kpi} gates={gates} autonomy={autonomy} policyEscapes={policyEscapes} optionalPending={optionalPending} />
          </OverviewSection>
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
