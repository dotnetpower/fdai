import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { ReadApiError } from "../api";
import type {
  AutonomyPayload,
  DashboardKpi,
  FinOpsPayload,
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
import { type ViewFact, usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import {
  auditSampleParams,
  formatShare,
  formatUsd,
  overviewAttentionCount,
  overviewCostActions,
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
import { DashboardSkeleton } from "./dashboard.skeleton";

interface Props {
  readonly client: ReadApiClient;
}

/**
 * Aggregate promotion-gate signal behind the release guard row. `null`
 * when the gate route is not wired on this deployment (404/501). A
 * `policy_escapes` sum > 0 blocks release per goals-and-metrics (escapes
 * MUST be exactly 0), so it also fails the health axis.
 */
interface OverviewData {
  readonly kpi: DashboardKpi;
  readonly finops: FinOpsPayload | null;
  readonly gates: GatesSummary | null;
  readonly autonomy: AutonomyPayload | null;
}

export function DashboardRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<OverviewData>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // `/kpi` is the required backbone. Independent optional projections
        // load concurrently and degrade only for their documented statuses.
        const [kpi, finops, gates, autonomy] = await Promise.all([
          client.dashboardMetrics(),
          optionalOverview(() => client.finops(), [404]),
          optionalOverview(() => client.panel<GatesSummary>("/kpi/promotion-gates"), [404, 501]),
          optionalOverview(() => client.autonomy(), [404, 501, 502]),
        ]);
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
    <div class="stack overview-page">
      <PageHeader title={t("route.dashboard")} subtitle={<>{t("overview.subtitle")}</>} />
      <AsyncBoundary state={state} resourceLabel="overview" loading={<DashboardSkeleton />}>
        {(data) => <OverviewBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

async function optionalOverview<T>(
  load: () => Promise<T>,
  unavailableStatuses: readonly number[],
): Promise<T | null> {
  try {
    return await load();
  } catch (error) {
    if (error instanceof ReadApiError && unavailableStatuses.includes(error.status)) return null;
    throw error;
  }
}

function OverviewBody({ data }: { readonly data: OverviewData }) {
  const { kpi, finops, gates, autonomy } = data;
  const sampleParams = auditSampleParams(kpi);

  const t0Share = overviewT0Share(kpi.by_tier);
  const policyEscapes = gates ? gates.rows.reduce((sum, r) => sum + r.policy_escapes, 0) : null;
  const readyCount = gates ? gates.ready_count : null;
  const gateTotal = gates ? gates.rows.length : null;
  // A policy escape blocks release (goals-and-metrics: escapes MUST be 0),
  // so it fails the health axis just like a pending human approval does.
  const health = overviewHealth(kpi, policyEscapes, autonomy);
  const attentionCount = overviewAttentionCount(kpi, policyEscapes, autonomy);
  const savings = finops ? finops.estimated_monthly_savings : null;

  usePublishViewContext(
    () => {
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
          {
            key: "section_count",
            aliases: ["primary sections", "numbered sections", "주요 영역", "번호 섹션"],
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
          { key: "cost_actions", value: overviewCostActions(finops), group: "cost" },
          { key: "policy_escapes", value: policyEscapes ?? "n/a", group: "guards" },
          {
            key: "promotion_ready",
            value: gateTotal !== null ? `${readyCount}/${gateTotal}` : "n/a",
            group: "guards",
          },
          ...autonomyFacts,
        ],
        records: {
          sections: [
            {
              position: 1,
              label: t("overview.section.outcomes"),
              detail: t("overview.section.outcomesHint"),
              evidence_state: autonomy === null ? "unavailable" : "available",
            },
            {
              position: 2,
              label: t("overview.section.routing"),
              detail: t("overview.section.routingHint"),
              evidence_state: "available",
            },
            {
              position: 3,
              label: t("overview.section.attention"),
              detail: t("overview.section.attentionHint"),
              evidence_state: "available",
            },
            {
              position: 4,
              label: t("overview.section.verticals"),
              detail: t("overview.section.verticalsHint"),
              evidence_state: autonomy === null ? "unavailable" : "available",
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
        },
      };
    },
    [kpi, finops, gates, autonomy, health, savings, t0Share],
  );

  return (
    <div class="stack overview-report">
      <ExecutiveStatus
        health={health}
        kpi={kpi}
        autonomy={autonomy}
        attentionCount={attentionCount}
        policyEscapes={policyEscapes}
      />

      <OverviewSection
        number="1"
        title={t("overview.section.outcomes")}
        description={t("overview.section.outcomesHint")}
      >
        {autonomy ? (
          <SuccessMetrics
            success={autonomy.success}
            synthetic={autonomy.synthetic}
            windowDays={autonomy.window_days}
            sourceName={autonomy.source.name}
          />
        ) : (
          <a class="overview-unavailable-link" href={routeHref("operating-outcomes")}>
            <MeasurementUnavailable />
          </a>
        )}
      </OverviewSection>

      <OverviewSection
        number="2"
        title={t("overview.section.routing")}
        description={t("overview.section.routingHint")}
      >
        <RoutingControl kpi={kpi} />
      </OverviewSection>

      <OverviewSection
        number="3"
        title={t("overview.section.attention")}
        description={t("overview.section.attentionHint")}
      >
        <RequiredAttention
          kpi={kpi}
          gates={gates}
          autonomy={autonomy}
          policyEscapes={policyEscapes}
        />
      </OverviewSection>

      <OverviewSection
        number="4"
        title={t("overview.section.verticals")}
        description={t("overview.section.verticalsHint")}
      >
        {autonomy ? (
          <VerticalCards verticals={autonomy.verticals} />
        ) : (
          <a class="overview-unavailable-link" href={routeHref("verticals")}>
            <MeasurementUnavailable />
          </a>
        )}
      </OverviewSection>

      <details class="advanced-details overview-details">
        <summary>
          <h3 class="section-title">{t("overview.detail")}</h3>
          <span class="muted">{t("overview.detailHint")}</span>
        </summary>
        <div class="stack overview-details-body">
          <KpiGrid>
            <KpiCard href={routeHref("audit", { params: sampleParams })} label={t("overview.detailMetric.events")} value={kpi.event_count} hint={t("overview.detailMetric.eventsHint")} />
            <KpiCard href={routeHref("audit", { params: { ...sampleParams, mode: "shadow" } })} label={t("overview.detailMetric.shadow")} value={formatShare(kpi.shadow_share)} hint={t("overview.detailMetric.shadowHint")} tone={kpi.shadow_share > 0.95 ? "positive" : "default"} />
            <KpiCard href={routeHref("audit", { params: { ...sampleParams, mode: "enforce" } })} label={t("overview.detailMetric.enforce")} value={formatShare(kpi.enforce_share)} hint={t("overview.detailMetric.enforceHint")} />
            <KpiCard href={routeHref("hil-queue")} label={t("overview.detailMetric.approvals")} value={kpi.hil_pending} tone={kpi.hil_pending > 0 ? "warning" : "positive"} hint={kpi.hil_pending > 0 ? t("overview.detailMetric.approvalHint") : t("overview.detailMetric.approvalClear")} />
          </KpiGrid>

          {autonomy ? (
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
  number,
  title,
  description,
  children,
}: {
  readonly number: string;
  readonly title: string;
  readonly description: string;
  readonly children: preact.ComponentChildren;
}) {
  return (
    <section class="overview-section" aria-labelledby={`overview-section-${number}`}>
      <header class="overview-section-head">
        <span class="overview-section-number" aria-hidden="true">{number}</span>
        <div>
          <h3 id={`overview-section-${number}`}>{title}</h3>
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
