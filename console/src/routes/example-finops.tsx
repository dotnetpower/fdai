/**
 * Reference fork panel - a minimal FinOps cost summary.
 *
 * This is the frontend twin of `ExampleFinOpsPanel` in
 * `src/aiopspilot/delivery/read_api/panels.py`. It is intentionally NOT
 * listed in `EXTRA_PANELS` (see `../panels.tsx`) so the upstream console
 * stays minimal. A fork opts in by:
 *
 *   1. registering `ExampleFinOpsPanel` (or its own `ReadPanel`) on the
 *      API via `ReadApiConfig.extra_panels`, and
 *   2. adding this component to `EXTRA_PANELS`:
 *
 *      ```ts
 *      import { ExampleFinOpsPanel } from "./routes/example-finops";
 *      export const EXTRA_PANELS = [
 *        { id: "finops", label: "Cost", component: ExampleFinOpsPanel },
 *      ];
 *      ```
 *
 * Read-only: it renders data fetched over the GET-only client and exposes
 * no action button (app-shape.instructions.md § Operator console).
 */

import { useEffect, useState } from "preact/hooks";
import type { PanelProps } from "../panels";

interface FinOpsPayload {
  readonly vertical: string;
  readonly total_actions: number;
  readonly by_kind: Record<string, number>;
  readonly estimated_monthly_savings: number;
  readonly sampled_events: number;
}

type State =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: FinOpsPayload }
  | { readonly status: "error"; readonly message: string };

export function ExampleFinOpsPanel({ client }: PanelProps) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await client.panel<FinOpsPayload>("/finops");
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
  }, [client]);

  if (state.status === "loading") return <div class="empty">Loading...</div>;
  if (state.status === "error")
    return <div class="empty error">Failed to load FinOps panel: {state.message}</div>;

  const { data } = state;
  return (
    <div class="stack">
      <section class="grid">
        <div class="card kpi">
          <span class="label">Cost actions</span>
          <span class="value">{data.total_actions}</span>
        </div>
        <div class="card kpi">
          <span class="label">Est. monthly savings</span>
          <span class="value">${data.estimated_monthly_savings.toFixed(2)}</span>
        </div>
        <div class="card kpi">
          <span class="label">Sampled events</span>
          <span class="value">{data.sampled_events}</span>
        </div>
      </section>

      <section class="card">
        <h2>Actions by kind</h2>
        <table>
          <tbody>
            {Object.entries(data.by_kind).map(([kind, count]) => (
              <tr key={kind}>
                <td>{kind}</td>
                <td>{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
