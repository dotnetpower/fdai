/**
 * Reference fork panel - a minimal FinOps cost summary.
 *
 * This is the frontend twin of `ExampleFinOpsPanel` in
 * `src/fdai/delivery/read_api/panels.py`. It is intentionally NOT
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
import { getLocale, t } from "../i18n";
import type { PanelProps } from "../panels";
import { routeHref } from "../router";

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

  if (state.status === "loading") return <div class="empty">{t("shared.loading")}</div>;
  if (state.status === "error")
    return <div class="empty error">{t("finops.loadFailed", { message: state.message })}</div>;

  const { data } = state;
  return (
    <div class="stack">
      <section class="grid">
        <a class="card kpi" href={routeHref("audit", { params: { vertical: "cost" } })}>
          <span class="label">{t("finops.costActions")}</span>
          <span class="value">{data.total_actions.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US")}</span>
        </a>
        <a class="card kpi" href={routeHref("verticals", { segments: ["cost-governance"] })}>
          <span class="label">{t("finops.monthlySavings")}</span>
          <span class="value">{new Intl.NumberFormat(getLocale() === "ko" ? "ko-KR" : "en-US", {
            style: "currency",
            currency: "USD",
          }).format(data.estimated_monthly_savings)}</span>
        </a>
        <a class="card kpi" href={routeHref("audit", { params: { vertical: "cost" } })}>
          <span class="label">{t("finops.sampledEvents")}</span>
          <span class="value">{data.sampled_events.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US")}</span>
        </a>
      </section>

      <section class="card">
        <h2><a href={routeHref("audit", { params: { vertical: "cost" } })}>{t("finops.actionsByKind")}</a></h2>
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
