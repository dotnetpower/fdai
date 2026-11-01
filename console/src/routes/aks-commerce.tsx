import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type {
  AksCommerceEvidenceState,
  AksCommerceProjection,
  AksCommerceStatus,
} from "../api-aks-commerce";
import { isOptionalOperatorApiUnavailable } from "../api";
import {
  AsyncBoundary,
  PageHeader,
  StatusPill,
  type AsyncState,
} from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import {
  currentRoute,
  replaceRouteState,
  ROUTE_STATE_EVENT,
  routeHref,
} from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/aks-commerce";
import { sampleAksCommerce } from "./aks-commerce.sample";
import "./aks-commerce.css";

export type ServiceId = "catalog-browse" | "order-fulfillment";

export function aksCommerceServiceFromSearch(search: URLSearchParams): ServiceId {
  return search.get("service") === "catalog-browse"
    ? "catalog-browse"
    : "order-fulfillment";
}

export function aksCommerceServiceHref(
  serviceId: ServiceId,
  search: URLSearchParams,
): string {
  const params = Object.fromEntries(search.entries());
  return routeHref("aks-commerce", {
    params: {
      ...params,
      service: serviceId === "order-fulfillment" ? null : serviceId,
    },
  });
}

export function AksCommerceRoute({
  client,
  dataMode,
}: {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}) {
  const [serviceId, setServiceId] = useState<ServiceId>(() =>
    aksCommerceServiceFromSearch(currentRoute().search),
  );
  const [state, setState] = useState<AsyncState<AksCommerceProjection>>({
    status: "loading",
  });

  useEffect(() => {
    const syncService = () => {
      setServiceId(aksCommerceServiceFromSearch(currentRoute().search));
    };
    window.addEventListener("popstate", syncService);
    window.addEventListener("fdai:route-changed", syncService);
    window.addEventListener(ROUTE_STATE_EVENT, syncService);
    return () => {
      window.removeEventListener("popstate", syncService);
      window.removeEventListener("fdai:route-changed", syncService);
      window.removeEventListener(ROUTE_STATE_EVENT, syncService);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    if (dataMode === "sample") {
      setState({ status: "ready", data: sampleAksCommerce(serviceId) });
      return () => {
        cancelled = true;
      };
    }
    client.aksCommerce(serviceId).then((projection) => {
      if (!cancelled) setState({ status: "ready", data: projection });
    }).catch((error: unknown) => {
      if (cancelled) return;
      setState(
        isOptionalOperatorApiUnavailable(error)
          ? { status: "unavailable", message: t("aksCommerce.unavailable") }
          : {
              status: "error",
              message: error instanceof Error ? error.message : String(error),
            },
      );
    });
    return () => {
      cancelled = true;
    };
  }, [client, dataMode, serviceId]);

  return (
    <div class="stack aks-commerce-route">
      <PageHeader title={t("aksCommerce.title")} subtitle={t("aksCommerce.subtitle")} />
      <div class="aks-commerce-service-picker" role="group" aria-label={t("aksCommerce.serviceLabel")}>
        {(["order-fulfillment", "catalog-browse"] as const).map((candidate) => (
          <button
            key={candidate}
            type="button"
            class={candidate === serviceId ? "active" : ""}
            aria-pressed={candidate === serviceId}
            onClick={() => {
              setServiceId(candidate);
              replaceRouteState(aksCommerceServiceHref(candidate, currentRoute().search));
            }}
          >
            {t(`aksCommerce.services.${candidate}`)}
          </button>
        ))}
      </div>
      <AsyncBoundary state={state} resourceLabel={t("aksCommerce.loading")}>
        {(projection) => <AksCommerceWorkspace projection={projection} />}
      </AsyncBoundary>
    </div>
  );
}

function AksCommerceWorkspace({ projection }: { readonly projection: AksCommerceProjection }) {
  return (
    <div class="aks-commerce-workspace">
      <section class="aks-commerce-hero" aria-labelledby="aks-commerce-state">
        <div>
          <span class="eyebrow">{t(`aksCommerce.services.${projection.service_id}`)}</span>
          <h2 id="aks-commerce-state">{t(`aksCommerce.state.${projection.status}`)}</h2>
          <p>{projection.summary}</p>
        </div>
        <div class="aks-commerce-hero-state">
          <StatusPill kind={statusTone(projection.status)} label={t(`aksCommerce.state.${projection.status}`)} />
          <span>{t(projection.complete ? "aksCommerce.complete" : "aksCommerce.incomplete")}</span>
          {projection.synthetic ? <span>{t("aksCommerce.synthetic")}</span> : null}
        </div>
      </section>

      <section class="aks-commerce-section">
        <h3>{t("aksCommerce.sloTitle")}</h3>
        <div class="aks-commerce-slo-grid">
          {projection.slos.map((slo) => (
            <article key={slo.slo_id}>
              <header>
                <strong>{slo.slo_id}</strong>
                <StatusPill kind={slo.breached === true ? "danger" : slo.state === "complete" ? "success" : "warning"} label={evidenceLabel(slo.state)} />
              </header>
              <dl>
                <div><dt>{t("aksCommerce.sloTarget")}</dt><dd>{ratio(slo.objective_ratio)}</dd></div>
                <div><dt>{t("aksCommerce.sloObserved")}</dt><dd>{ratio(slo.observed_ratio)}</dd></div>
                <div><dt>{t("aksCommerce.sloBudget")}</dt><dd>{ratio(slo.budget_remaining_ratio)}</dd></div>
              </dl>
            </article>
          ))}
        </div>
      </section>

      <section class="aks-commerce-section">
        <h3>{t("aksCommerce.dependencyTitle")}</h3>
        <p>{t("aksCommerce.dependencySubtitle")}</p>
        <ol class="aks-commerce-path">
          {projection.dependency_path.map((workloadId) => {
            const workload = projection.workloads.find((item) => item.workload_id === workloadId);
            return (
              <li key={workloadId}>
                <span>{workload?.display_name ?? workloadId}</span>
                <StatusPill
                  kind={workload?.ready === true ? "success" : workload?.ready === false ? "danger" : "neutral"}
                  label={workload?.ready === true ? t("aksCommerce.ready") : workload?.ready === false ? t("aksCommerce.notReady") : t("aksCommerce.unknown")}
                />
                {workload?.resource_ref ? <code>{workload.resource_ref}</code> : null}
              </li>
            );
          })}
        </ol>
      </section>

      <section class="aks-commerce-section">
        <h3>{t("aksCommerce.signalsTitle")}</h3>
        <div class="aks-commerce-table-wrap">
          <table>
            <thead>
              <tr><th>{t("aksCommerce.signal")}</th><th>{t("aksCommerce.current")}</th><th>{t("aksCommerce.previous")}</th><th>{t("aksCommerce.source")}</th></tr>
            </thead>
            <tbody>
              {projection.metrics.map((metric) => (
                <tr key={`${metric.name}:${metric.source_ref}`}>
                  <td><strong>{metric.name}</strong><small>{evidenceLabel(metric.state)}</small></td>
                  <td>{metricValue(metric.current, metric.unit)}</td>
                  <td>{metricValue(metric.previous, metric.unit)}</td>
                  <td><code>{metric.source_ref}</code></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section class="aks-commerce-split">
        <article>
          <h3>{t("aksCommerce.gapsTitle")}</h3>
          {projection.evidence_gaps.length === 0
            ? <p>{t("aksCommerce.noGaps")}</p>
            : <ul>{projection.evidence_gaps.map((gap) => <li key={gap}><code>{gap}</code></li>)}</ul>}
        </article>
        <article>
          <h3>{t("aksCommerce.actionTitle")}</h3>
          {projection.proposed_action === null ? (
            <p>{t("aksCommerce.noAction")}</p>
          ) : (
            <>
              <strong>{projection.proposed_action.action_type}</strong>
              <p>{projection.proposed_action.state}</p>
              <StatusPill
                kind={projection.proposed_action.effect_verified === true ? "success" : "warning"}
                label={t(projection.proposed_action.effect_verified === true ? "aksCommerce.effectVerified" : "aksCommerce.effectPending")}
              />
            </>
          )}
        </article>
      </section>

      <details class="aks-commerce-technical">
        <summary>{t("aksCommerce.technicalTitle")}</summary>
        <dl>
          <div><dt>{t("aksCommerce.owner")}</dt><dd>{projection.owner_agent}</dd></div>
          <div><dt>{t("aksCommerce.observer")}</dt><dd>{projection.observer_agent}</dd></div>
          <div><dt>{t("aksCommerce.window")}</dt><dd>{formatConsoleTimestamp(projection.window_start)} - {formatConsoleTimestamp(projection.window_end)}</dd></div>
        </dl>
        <ul>{projection.evidence_refs.map((reference) => <li><code>{reference}</code></li>)}</ul>
      </details>
    </div>
  );
}

function statusTone(status: AksCommerceStatus): "success" | "warning" | "danger" | "neutral" {
  if (status === "healthy" || status === "recovered") return "success";
  if (status === "held") return "warning";
  if (status === "order_backlog" || status === "dependency_pressure") return "warning";
  return "danger";
}

function evidenceLabel(state: AksCommerceEvidenceState): string {
  return state.replaceAll("_", " ");
}

function ratio(value: number | null): string {
  return value === null ? "-" : `${(value * 100).toFixed(1)}%`;
}

function metricValue(value: number | null, unit: string): string {
  return value === null ? "-" : `${value.toLocaleString()} ${unit}`;
}
