import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { ReadApiError } from "../api";
import type { DashboardKpi, FinOpsPayload } from "../types";
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
import { t } from "../i18n";

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
interface OverviewData {
  readonly kpi: DashboardKpi;
  readonly finops: FinOpsPayload | null;
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
        if (!cancelled) setState({ status: "ready", data: { kpi, finops } });
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
  const { kpi, finops } = data;

  const tierTotal = Object.values(kpi.by_tier).reduce((a, b) => a + b, 0);
  const t0Share = tierTotal > 0 ? Math.round(((kpi.by_tier.t0 ?? 0) / tierTotal) * 100) : 0;
  const healthy = kpi.shadow_share >= 0.95 && kpi.hil_pending === 0;
  const savings = finops ? finops.estimated_monthly_savings : null;

  usePublishViewContext(
    () => ({
      routeId: "dashboard",
      routeLabel: "Overview",
      headline:
        `health ${healthy ? "healthy" : "attention"} - ` +
        `${kpi.hil_pending} HIL pending - ` +
        (savings !== null ? `${formatUsd(savings)}/mo saved` : "cost n/a"),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "health", value: healthy ? "healthy" : "attention", group: "overview" },
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
      ],
      records: {
        by_action_kind: Object.entries(kpi.by_action_kind)
          .sort(([, a], [, b]) => b - a)
          .map(([key, count]) => ({ key, count })),
        by_outcome: Object.entries(kpi.by_outcome)
          .sort(([, a], [, b]) => b - a)
          .map(([key, count]) => ({ key, count })),
      },
    }),
    [kpi, finops, healthy, savings, t0Share],
  );

  return (
    <div class="stack">
      <section class="overview-triad" aria-label="health, risk and cost summary">
        <KpiCard
          label={t("overview.health.label")}
          value={healthy ? t("overview.health.healthy") : t("overview.health.attention")}
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
