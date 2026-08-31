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
import { CostGovernanceWorkspace } from "./cost-governance-workspace";
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
    <div class="stack cost-governance-route">
      <PageHeader title={t("costGovernance.title")} subtitle={t("costGovernance.subtitle")} />
      <nav class="cost-governance-tabs" aria-label={t("costGovernance.title")}>
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
      {state.status === "unavailable" ? (
        <p><a href={routeHref("settings-runtime")}>{t("costGovernance.configure")}</a></p>
      ) : null}
      <AsyncBoundary state={state} resourceLabel={t("costGovernance.loading")}>
        {(projection) => projection.items.length === 0 && projection.analytics == null ? (
          <EmptyState title={t("costGovernance.empty")} body={t("costGovernance.emptyHint")} />
        ) : (
          <CostGovernanceWorkspace projection={projection} />
        )}
      </AsyncBoundary>
    </div>
  );
}
