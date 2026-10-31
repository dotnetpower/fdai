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
import { currentRoute, navigate, routeHref } from "../router";
import { CostGovernanceWorkspace } from "./cost-governance-workspace";
import { t } from "./i18n/cost-governance";
import {
  isCostGovernanceProjection,
  loadCostGovernance,
} from "./cost-governance.model";
import type { ConsoleDataMode } from "../console-data-mode";
import { sampleCostGovernance } from "./cost-governance.sample";

const SURFACES: readonly CostGovernanceSurface[] = [
  "overview",
  "resource-efficiency",
  "optimization-cases",
  "outcomes",
];

export function costGovernanceTabs(): readonly {
  readonly surface: CostGovernanceSurface;
  readonly label: string;
}[] {
  return [
    { surface: "overview", label: t("costGovernance.tabs.overview") },
    { surface: "resource-efficiency", label: t("costGovernance.tabs.resourceEfficiency") },
    { surface: "optimization-cases", label: t("costGovernance.tabs.optimizationCases") },
    { surface: "outcomes", label: t("costGovernance.tabs.outcomes") },
  ];
}

export function resolveCostGovernanceSurface(
  segments: readonly string[],
): { readonly surface: CostGovernanceSurface; readonly canonical: boolean } {
  if (segments.length === 0) return { surface: "overview", canonical: true };
  const candidate = segments[0];
  if (
    segments.length === 1 &&
    candidate !== undefined &&
    SURFACES.includes(candidate as CostGovernanceSurface)
  ) {
    return { surface: candidate as CostGovernanceSurface, canonical: true };
  }
  return { surface: "overview", canonical: false };
}

export function CostGovernanceRoute({
  client,
  dataMode,
}: {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}) {
  const { surface, canonical } = resolveCostGovernanceSurface(currentRoute().segments);
  const tabs = costGovernanceTabs();
  const [state, setState] = useState<AsyncState<CostGovernanceProjection>>({
    status: "loading",
  });

  useEffect(() => {
    if (!canonical) {
      navigate(
        routeHref("cost-governance", {
          segments: ["overview"],
          params: Object.fromEntries(currentRoute().search.entries()),
        }),
        true,
      );
    }
  }, [canonical]);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    if (dataMode === "sample") {
      setState({ status: "ready", data: sampleCostGovernance(surface) });
      return () => {
        cancelled = true;
      };
    }
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
  }, [client, dataMode, surface]);

  return (
    <div class="stack cost-governance-route">
      <PageHeader title={t("costGovernance.title")} subtitle={t("costGovernance.subtitle")} />
      <nav class="cost-governance-tabs" aria-label={t("costGovernance.title")}>
        {tabs.map((tab) => (
          <a
            key={tab.surface}
            href={routeHref("cost-governance", {
              segments: [tab.surface],
              params: Object.fromEntries(currentRoute().search.entries()),
            })}
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
        {(projection) => (
          projection.items.length === 0
          && projection.analytics == null
          && projection.evidence == null
        ) ? (
          <EmptyState title={t("costGovernance.empty")} body={t("costGovernance.emptyHint")} />
        ) : (
          <CostGovernanceWorkspace projection={projection} />
        )}
      </AsyncBoundary>
    </div>
  );
}
