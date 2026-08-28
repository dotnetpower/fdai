import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import type {
  CostGovernanceProjection,
  CostGovernanceSurface,
} from "../api-cost-governance";
import {
  AsyncBoundary,
  EmptyState,
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { currentRoute, routeHref } from "../router";
import { t } from "./i18n/cost-governance";
import {
  isCostGovernanceProjection,
  loadCostGovernance,
} from "./cost-governance.model";

const TABS: readonly {
  readonly surface: CostGovernanceSurface;
  readonly label: string;
}[] = [
  { surface: "overview", label: t("costGovernance.tabs.overview") },
  { surface: "resource-efficiency", label: t("costGovernance.tabs.resourceEfficiency") },
  { surface: "optimization-cases", label: t("costGovernance.tabs.optimizationCases") },
  { surface: "outcomes", label: t("costGovernance.tabs.outcomes") },
];

function activeSurface(): CostGovernanceSurface {
  const candidate = currentRoute().segments[0] ?? "overview";
  return TABS.some((tab) => tab.surface === candidate)
    ? candidate as CostGovernanceSurface
    : "overview";
}

export function CostGovernanceRoute({ client }: { readonly client: OperatorApiClient }) {
  const surface = activeSurface();
  const [state, setState] = useState<AsyncState<CostGovernanceProjection>>({
    status: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    loadCostGovernance(client, surface).then((result) => {
      if (cancelled) return;
      if (isCostGovernanceProjection(result)) {
        setState({ status: "ready", data: result });
      } else {
        setState({
          status: "unavailable",
          message: result.access_allowed
            ? t("costGovernance.unavailable")
            : t("costGovernance.accessRequired"),
        });
      }
    }).catch((error: unknown) => {
      if (cancelled) return;
      if (error instanceof OperatorApiError && error.status === 403) {
        setState({ status: "unavailable", message: t("costGovernance.accessRequired") });
      } else if (isOptionalOperatorApiUnavailable(error)) {
        setState({ status: "unavailable", message: t("costGovernance.unavailable") });
      } else {
        setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      }
    });
    return () => { cancelled = true; };
  }, [client, surface]);

  return (
    <div class="stack">
      <PageHeader title={t("costGovernance.title")} subtitle={t("costGovernance.subtitle")} />
      <nav class="tabs" aria-label={t("costGovernance.title")}>
        {TABS.map((tab) => (
          <a
            href={routeHref("cost-governance", { segments: [tab.surface] })}
            aria-current={tab.surface === surface ? "page" : undefined}
            class={tab.surface === surface ? "active" : ""}
          >
            {tab.label}
          </a>
        ))}
      </nav>
      <AsyncBoundary state={state} resourceLabel={t("costGovernance.loading")}>
        {(projection) => projection.items.length === 0 ? (
          <EmptyState title={t("costGovernance.empty")} />
        ) : (
          <section aria-live="polite">
            {!projection.complete ? <p class="muted">{t("costGovernance.incomplete")}</p> : null}
            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>{t("costGovernance.columns.identity")}</th>
                    <th>{t("costGovernance.columns.service")}</th>
                    <th>{t("costGovernance.columns.amount")}</th>
                    <th>{t("costGovernance.columns.status")}</th>
                    <th>{t("costGovernance.columns.observed")}</th>
                  </tr>
                </thead>
                <tbody>
                  {projection.items.map((item, index) => (
                    <tr key={String(item["record_id"] ?? item["group_id"] ?? index)}>
                      <td>{String(item["resource"] ?? item["group_id"] ?? "-")}</td>
                      <td>{String(item["service_id"] ?? "-")}</td>
                      <td>{String(
                        item["amount_exact"]
                        ?? item["amount_rounded"]
                        ?? item["amount_band"]
                        ?? (item["suppressed"] ? "suppressed" : "-"),
                      )}</td>
                      <td>{String(item["status"] ?? "-")}</td>
                      <td>{String(item["observed_at"] ?? "-")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </AsyncBoundary>
    </div>
  );
}
