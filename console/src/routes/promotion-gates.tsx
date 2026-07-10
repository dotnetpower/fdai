import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";

/**
 * Promotion-gate dashboard panel. Fetches ``GET /kpi/promotion-gates``
 * and renders per-ActionType progress against the shipped
 * ``promotion_gate`` block.
 */

interface Row {
  readonly action_type_name: string;
  readonly shadow_days_elapsed: number;
  readonly sample_count: number;
  readonly reviewed_count: number;
  readonly agreed_count: number;
  readonly policy_escapes: number;
  readonly accuracy: number;
  readonly ready: boolean;
  readonly gaps: readonly string[];
}

interface Response {
  readonly window_days: number | null;
  readonly rows: readonly Row[];
  readonly ready_count: number;
  readonly blocked_count: number;
}

interface Props {
  readonly client: ReadApiClient;
}

export function PromotionGatesRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Response>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await client.panel<Response>("/kpi/promotion-gates");
        if (!cancelled) setState({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.includes("404")) {
            setState({
              status: "unavailable",
              message:
                "Promotion-gate dashboard route is not wired on this deployment. " +
                "Set ReadApiConfig.promotion_gate_source in the composition root to enable it.",
            });
          } else {
            setState({ status: "error", message });
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div class="stack">
      <PageHeader
        title={t("route.promotionGates")}
        subtitle="Per-ActionType readiness against each shipped promotion_gate. Actions promote from shadow to enforce only when every gap is closed."
      />
      <AsyncBoundary state={state} resourceLabel="promotion gates">
        {(data) => <PromotionBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

function PromotionBody({ data }: { readonly data: Response }) {
  usePublishViewContext(
    () => ({
      routeId: "promotion-gates",
      routeLabel: "Promotion gates",
      purpose:
        "Which ActionTypes running in shadow mode have met their promotion gate " +
        "(measured accuracy with zero policy escapes) and are ready to enforce, " +
        "and which are still blocked and why. Read-only: promotion itself is a " +
        "separately reviewed change.",
      glossary: composeGlossary([
        TERMS.actionType,
        TERMS.shadowMode,
        TERMS.mode,
        TERMS.gateDecision,
      ]),
      headline: `${data.ready_count} ready - ${data.blocked_count} blocked${data.window_days !== null ? ` (window ${data.window_days}d)` : ""}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "ready_count", value: data.ready_count, group: "summary" },
        { key: "blocked_count", value: data.blocked_count, group: "summary" },
        { key: "window_days", value: data.window_days, group: "summary" },
      ],
      records: {
        rows: data.rows.map((r) => ({
          action_type_name: r.action_type_name,
          ready: r.ready,
          shadow_days_elapsed: r.shadow_days_elapsed,
          sample_count: r.sample_count,
          reviewed_count: r.reviewed_count,
          agreed_count: r.agreed_count,
          accuracy: r.accuracy,
          policy_escapes: r.policy_escapes,
          gaps: r.gaps,
        })),
      },
    }),
    [data],
  );

  const columns: readonly Column<Row>[] = [
    { key: "at", header: "ActionType", render: (r) => r.action_type_name, cellClass: "mono" },
    {
      key: "rd",
      header: "Status",
      render: (r) => (
        <StatusPill
          kind={r.ready ? "success" : "warning"}
          label={r.ready ? "ready" : "blocked"}
        />
      ),
    },
    {
      key: "days",
      header: "Shadow days",
      render: (r) => r.shadow_days_elapsed.toFixed(2),
      cellClass: "num", headerClass: "num",
    },
    { key: "samp", header: "Samples", render: (r) => r.sample_count, cellClass: "num", headerClass: "num" },
    {
      key: "rev",
      header: "Reviewed / agreed",
      render: (r) => `${r.reviewed_count} / ${r.agreed_count}`,
      cellClass: "num", headerClass: "num",
    },
    {
      key: "acc",
      header: "Accuracy",
      render: (r) => `${(r.accuracy * 100).toFixed(1)}%`,
      cellClass: "num", headerClass: "num",
    },
    {
      key: "esc",
      header: "Policy escapes",
      render: (r) => (
        r.policy_escapes > 0
          ? <StatusPill kind="danger" label={String(r.policy_escapes)} />
          : <span class="muted">0</span>
      ),
      cellClass: "num", headerClass: "num",
    },
    {
      key: "gaps",
      header: "Gaps",
      render: (r) =>
        r.gaps.length === 0
          ? <span class="muted">-</span>
          : (
            <ul class="mini-list">
              {r.gaps.map((gap) => <li key={gap} class="mono">{gap}</li>)}
            </ul>
          ),
    },
  ];

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard
          label="Ready for promotion"
          value={data.ready_count}
          tone={data.ready_count > 0 ? "positive" : "default"}
          hint="every gate cleared"
        />
        <KpiCard
          label="Blocked"
          value={data.blocked_count}
          tone={data.blocked_count > 0 ? "warning" : "positive"}
          hint="still in shadow"
        />
        <KpiCard
          label="Measurement window"
          value={data.window_days !== null ? `${data.window_days}d` : "-"}
        />
      </KpiGrid>
      <section class="stack-section">
        <h3 class="section-title">ActionTypes ({data.rows.length})</h3>
        <DataTable
          columns={columns}
          rows={data.rows}
          keyOf={(r) => r.action_type_name}
          empty="No ActionTypes declared a promotion gate."
        />
      </section>
    </div>
  );
}
