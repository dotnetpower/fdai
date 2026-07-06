import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { DashboardKpi } from "../types";

interface Props {
  readonly client: ReadApiClient;
}

type State =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly kpi: DashboardKpi }
  | { readonly status: "error"; readonly message: string };

function formatShare(x: number): string {
  return `${(x * 100).toFixed(1)}%`;
}

export function DashboardRoute({ client }: Props) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const kpi = await client.dashboardMetrics();
        if (!cancelled) setState({ status: "ready", kpi });
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

  if (state.status === "loading") return <div class="empty">Loading…</div>;
  if (state.status === "error")
    return <div class="empty error">Failed to load KPIs: {state.message}</div>;

  const kpi = state.kpi;
  return (
    <div class="stack">
      <section class="grid">
        <div class="card kpi">
          <span class="label">Events (audit)</span>
          <span class="value">{kpi.event_count}</span>
        </div>
        <div class="card kpi">
          <span class="label">Shadow share</span>
          <span class="value">{formatShare(kpi.shadow_share)}</span>
        </div>
        <div class="card kpi">
          <span class="label">Enforce share</span>
          <span class="value">{formatShare(kpi.enforce_share)}</span>
        </div>
        <div class="card kpi">
          <span class="label">HIL pending</span>
          <span class="value">{kpi.hil_pending}</span>
        </div>
      </section>

      <section class="card">
        <h2>Actions by kind</h2>
        <KeyValueTable data={kpi.by_action_kind} />
      </section>

      <section class="card">
        <h2>Outcomes</h2>
        <KeyValueTable data={kpi.by_outcome} />
      </section>

      {kpi.last_recorded_at !== null ? (
        <p class="muted">Last audit entry: {kpi.last_recorded_at}</p>
      ) : null}
    </div>
  );
}

function KeyValueTable({ data }: { readonly data: Record<string, number> }) {
  const entries = Object.entries(data).sort(([, a], [, b]) => b - a);
  if (entries.length === 0) return <div class="muted">No data yet.</div>;
  return (
    <table>
      <thead>
        <tr>
          <th>Key</th>
          <th>Count</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key}>
            <td class="mono">{key}</td>
            <td>{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
