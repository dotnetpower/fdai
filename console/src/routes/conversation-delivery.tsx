import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { EvidenceRefresh } from "../components/evidence-refresh";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  kpiEvidenceLabel,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { currentRoute, routeHref } from "../router";
import { presentationLabel, t } from "./i18n/evidence";
import {
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelRecord,
} from "./panel-decode";

export interface ConversationDeliveryResponse {
  readonly source: string;
  readonly read_only: true;
  readonly mutations_available: false;
  readonly delivery_count: number;
  readonly states: Readonly<Record<string, number>>;
  readonly delivery_latency_ms: {
    readonly count: number;
    readonly average: number | null;
    readonly p95: number | null;
  };
  readonly duplicate_risk_count: number;
  readonly retry_count: number;
  readonly abandonment_count: number;
  readonly breaker_states: Readonly<Record<string, number>>;
  readonly attempt_count: number;
  readonly acknowledgement_count: number;
}

export function ConversationDeliveryRoute({ client }: { readonly client: OperatorApiClient }) {
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [state, setState] = useState<AsyncState<ConversationDeliveryResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    client.panel<unknown>("/conversation-delivery")
      .then((value) => {
        if (!cancelled) setState({ status: "ready", data: decodeConversationDelivery(value) });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({
          status: isOptionalOperatorApiUnavailable(error) ? "unavailable" : "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });
    return () => { cancelled = true; };
  }, [client, refreshRevision]);
  return <div class="stack cs-workspace-route"><PageHeader title={t("route.conversationDelivery")} subtitle={t("nav.panelSub.conversationDelivery")} actions={
    <EvidenceRefresh loading={state.status === "loading"} onRefresh={() => {
      setState({ status: "loading" });
      setRefreshRevision((revision) => revision + 1);
    }} />
  } /><AsyncBoundary state={state} resourceLabel={t("evidence.delivery.resource")}>{(data) => <DeliveryBody data={data} />}</AsyncBoundary></div>;
}

export function decodeConversationDelivery(value: unknown): ConversationDeliveryResponse {
  const root = panelRecord(value, "conversation delivery");
  const readOnly = panelBoolean(root, "read_only", "conversation delivery");
  const mutationsAvailable = panelBoolean(root, "mutations_available", "conversation delivery");
  if (!readOnly || mutationsAvailable) {
    throw new Error("invalid Operator API response: conversation delivery MUST be read-only");
  }
  const latency = panelRecord(root["delivery_latency_ms"], "conversation delivery.delivery_latency_ms");
  const latencyCount = panelNonNegativeInteger(latency, "count", "conversation delivery.delivery_latency_ms");
  const latencyAverage = nullableMetric(latency, "average");
  const latencyP95 = nullableMetric(latency, "p95");
  if (latencyAverage !== null && latencyP95 !== null && latencyP95 < latencyAverage) {
    throw new Error("conversation delivery p95 latency MUST be >= average");
  }
  const deliveryCount = panelNonNegativeInteger(root, "delivery_count", "conversation delivery");
  const attemptCount = panelNonNegativeInteger(root, "attempt_count", "conversation delivery");
  const acknowledgementCount = panelNonNegativeInteger(root, "acknowledgement_count", "conversation delivery");
  if (acknowledgementCount > attemptCount) {
    throw new Error("conversation delivery acknowledgements MUST NOT exceed attempts");
  }
  return {
    source: panelNonEmptyString(root, "source", "conversation delivery"),
    read_only: true,
    mutations_available: false,
    delivery_count: deliveryCount,
    states: decodeCounts(root["states"], "conversation delivery.states"),
    delivery_latency_ms: {
      count: latencyCount,
      average: latencyAverage,
      p95: latencyP95,
    },
    duplicate_risk_count: panelNonNegativeInteger(root, "duplicate_risk_count", "conversation delivery"),
    retry_count: panelNonNegativeInteger(root, "retry_count", "conversation delivery"),
    abandonment_count: panelNonNegativeInteger(root, "abandonment_count", "conversation delivery"),
    breaker_states: decodeCounts(root["breaker_states"], "conversation delivery.breaker_states"),
    attempt_count: attemptCount,
    acknowledgement_count: acknowledgementCount,
  };
}

function decodeCounts(value: unknown, label: string): Readonly<Record<string, number>> {
  const record = panelRecord(value, label);
  return Object.fromEntries(Object.entries(record).map(([key, count]) => {
    if (!Number.isInteger(count) || (count as number) < 0) {
      throw new Error(`invalid Operator API response: ${label}.${key} MUST be a non-negative integer`);
    }
    return [key, count as number];
  }));
}

function nullableMetric(value: Readonly<Record<string, unknown>>, key: string): number | null {
  if (value[key] === null) return null;
  return panelNonNegativeNumber(value, key, "conversation delivery.delivery_latency_ms");
}

export function conversationDeliveryEvidenceHref(
  search: URLSearchParams = currentRoute().search,
): string {
  return `${routeHref("conversation-delivery", {
    params: { data: search.get("data") === "sample" ? "sample" : null },
  })}#conversation-delivery-evidence`;
}

function DeliveryBody({ data }: { readonly data: ConversationDeliveryResponse }) {
  usePublishViewContext(
    () => ({
      routeId: "conversation-delivery",
      routeLabel: t("route.conversationDelivery"),
      purpose: t("evidence.delivery.viewPurpose"),
      glossary: composeGlossary([], [{ term: t("evidence.delivery.glossaryTerm"), plain: t("evidence.delivery.glossaryPlain"), tech: "OutboundDeliveryState.AMBIGUOUS" }]),
      headline: t("evidence.delivery.headline", { deliveries: data.delivery_count, risks: data.duplicate_risk_count }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "source", value: data.source, group: "provenance" },
        { key: "delivery_count", value: data.delivery_count, group: "reliability" },
        { key: "duplicate_risk_count", value: data.duplicate_risk_count, group: "reliability" },
        { key: "retry_count", value: data.retry_count, group: "reliability" },
        { key: "mutations_available", value: data.mutations_available, group: "safety" },
      ],
      records: {
        states: Object.entries(data.states).map(([name, count]) => ({ name, count })),
        breaker_states: Object.entries(data.breaker_states).map(([name, count]) => ({
          name,
          count,
        })),
      },
    }),
    [data],
  );
  const stateEntries = Object.entries(data.states);
  const breakerEntries = Object.entries(data.breaker_states);
  const stateTotal = stateEntries.reduce((sum, [, count]) => sum + count, 0);
  const breakerTotal = breakerEntries.reduce((sum, [, count]) => sum + count, 0);
  const evidenceHref = conversationDeliveryEvidenceHref();
  const breakerColumns: readonly Column<readonly [string, number]>[] = [
    {
      key: "state",
      header: t("evidence.delivery.breakers"),
      render: ([name]) => (
        <StatusPill
          kind={name === "closed" ? "success" : "warning"}
          label={presentationLabel("status", name)}
        />
      ),
    },
    {
      key: "count",
      header: t("evidence.delivery.deliveries"),
      render: ([, count]) => count.toLocaleString(),
      cellClass: "num",
    },
    {
      key: "share",
      header: "%",
      render: ([, count]) => breakerTotal > 0 ? `${Math.round((count / breakerTotal) * 100)}%` : "0%",
      cellClass: "num",
    },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner"><strong>{t("evidence.delivery.bannerTitle")}</strong><span>{t("evidence.delivery.bannerBody")}</span></div>
      <KpiGrid>
        <KpiCard href={evidenceHref} label={t("evidence.delivery.deliveries")} value={data.delivery_count.toLocaleString()} />
        <KpiCard
          evidenceState={data.delivery_latency_ms.p95 === null ? "not-measured" : "measured"}
          href={evidenceHref}
          label={t("evidence.delivery.p95Latency")}
          value={data.delivery_latency_ms.p95 === null ? kpiEvidenceLabel("not-measured") : `${data.delivery_latency_ms.p95.toLocaleString()} ms`}
        />
        <KpiCard href={evidenceHref} label={t("evidence.delivery.duplicateRisk")} value={data.duplicate_risk_count.toLocaleString()} tone={data.duplicate_risk_count > 0 ? "warning" : "default"} />
        <KpiCard href={evidenceHref} label={t("evidence.delivery.retries")} value={data.retry_count.toLocaleString()} />
        <KpiCard href={evidenceHref} label={t("evidence.delivery.abandoned")} value={data.abandonment_count.toLocaleString()} tone={data.abandonment_count > 0 ? "danger" : "default"} />
        <KpiCard href={evidenceHref} label={t("evidence.delivery.acknowledged")} value={data.acknowledgement_count.toLocaleString()} />
      </KpiGrid>
      <div id="conversation-delivery-evidence" class="cs-workspace-split has-selection">
        <section class="cs-workspace-main">
          <h2>{t("evidence.delivery.states")}</h2>
          {stateEntries.length === 0 ? (
            <EmptyState title={t("evidence.common.none")} />
          ) : (
            <div class="cs-ratio-bars">
              {stateEntries.map(([name, count]) => {
                const pct = stateTotal > 0 ? Math.round((count / stateTotal) * 100) : 0;
                const barClass = name === "delivered"
                  ? "is-success"
                  : name === "ambiguous" || name === "abandoned"
                    ? "is-warning"
                    : "";
                return (
                  <div class="cs-ratio-row" key={name}>
                    <StatusPill
                      kind={name === "delivered" ? "success" : name === "ambiguous" || name === "abandoned" ? "warning" : "neutral"}
                      label={presentationLabel("status", name)}
                    />
                    <div class="cs-ratio-track" aria-hidden="true">
                      <span class={barClass} style={`width:${pct}%`} />
                    </div>
                    <strong>{count.toLocaleString()} ({pct}%)</strong>
                  </div>
                );
              })}
            </div>
          )}
          <h2>{t("evidence.delivery.breakers")}</h2>
          <DataTable
            rows={breakerEntries}
            columns={breakerColumns}
            keyOf={([name]) => name}
            scrollRegionLabel={t("evidence.delivery.breakers")}
            empty={<EmptyState title={t("evidence.delivery.noBreakers")} />}
          />
        </section>
        <aside class="cs-inspector-pane" aria-label={t("route.conversationDelivery")}>
          <header class="cs-inspector-head">
            <div>
              <span class="cs-inspector-kicker">{data.source}</span>
              <h3>{t("route.conversationDelivery")}</h3>
              <p>{t("evidence.delivery.viewPurpose")}</p>
            </div>
            <StatusPill kind="neutral" label={t("evidence.common.readOnly")} />
          </header>
          <dl class="cs-facts-grid">
            <div><dt>{t("evidence.delivery.deliveries")}</dt><dd>{data.delivery_count.toLocaleString()}</dd></div>
            <div><dt>{t("evidence.delivery.acknowledged")}</dt><dd>{data.acknowledgement_count.toLocaleString()} / {data.attempt_count.toLocaleString()}</dd></div>
            <div><dt>{t("evidence.delivery.p95Latency")}</dt><dd>{data.delivery_latency_ms.p95 === null ? kpiEvidenceLabel("not-measured") : `${data.delivery_latency_ms.p95.toLocaleString()} ms`} (avg: {data.delivery_latency_ms.average === null ? kpiEvidenceLabel("not-measured") : `${data.delivery_latency_ms.average.toLocaleString()} ms`})</dd></div>
            <div><dt>{t("evidence.delivery.duplicateRisk")}</dt><dd>{data.duplicate_risk_count.toLocaleString()}</dd></div>
            <div><dt>{t("evidence.delivery.retries")}</dt><dd>{data.retry_count.toLocaleString()}</dd></div>
            <div><dt>{t("evidence.delivery.abandoned")}</dt><dd>{data.abandonment_count.toLocaleString()}</dd></div>
          </dl>
        </aside>
      </div>
    </div>
  );
}
