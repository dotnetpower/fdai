import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
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

export function ConversationDeliveryRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<ConversationDeliveryResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    client.panel<unknown>("/conversation-delivery")
      .then((value) => {
        if (!cancelled) setState({ status: "ready", data: decodeConversationDelivery(value) });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });
    return () => { cancelled = true; };
  }, [client]);
  return <div class="stack"><PageHeader title={t("route.conversationDelivery")} subtitle={t("nav.panelSub.conversationDelivery")} /><AsyncBoundary state={state} resourceLabel="conversation delivery">{(data) => <DeliveryBody data={data} />}</AsyncBoundary></div>;
}

export function decodeConversationDelivery(value: unknown): ConversationDeliveryResponse {
  const root = panelRecord(value, "conversation delivery");
  const readOnly = panelBoolean(root, "read_only", "conversation delivery");
  const mutationsAvailable = panelBoolean(root, "mutations_available", "conversation delivery");
  if (!readOnly || mutationsAvailable) {
    throw new Error("invalid read API response: conversation delivery MUST be read-only");
  }
  const latency = panelRecord(root["delivery_latency_ms"], "conversation delivery.delivery_latency_ms");
  return {
    source: panelNonEmptyString(root, "source", "conversation delivery"),
    read_only: true,
    mutations_available: false,
    delivery_count: panelNonNegativeInteger(root, "delivery_count", "conversation delivery"),
    states: decodeCounts(root["states"], "conversation delivery.states"),
    delivery_latency_ms: {
      count: panelNonNegativeInteger(latency, "count", "conversation delivery.delivery_latency_ms"),
      average: nullableMetric(latency, "average"),
      p95: nullableMetric(latency, "p95"),
    },
    duplicate_risk_count: panelNonNegativeInteger(root, "duplicate_risk_count", "conversation delivery"),
    retry_count: panelNonNegativeInteger(root, "retry_count", "conversation delivery"),
    abandonment_count: panelNonNegativeInteger(root, "abandonment_count", "conversation delivery"),
    breaker_states: decodeCounts(root["breaker_states"], "conversation delivery.breaker_states"),
    attempt_count: panelNonNegativeInteger(root, "attempt_count", "conversation delivery"),
    acknowledgement_count: panelNonNegativeInteger(root, "acknowledgement_count", "conversation delivery"),
  };
}

function decodeCounts(value: unknown, label: string): Readonly<Record<string, number>> {
  const record = panelRecord(value, label);
  return Object.fromEntries(Object.entries(record).map(([key, count]) => {
    if (!Number.isInteger(count) || (count as number) < 0) {
      throw new Error(`invalid read API response: ${label}.${key} MUST be a non-negative integer`);
    }
    return [key, count as number];
  }));
}

function nullableMetric(value: Readonly<Record<string, unknown>>, key: string): number | null {
  if (value[key] === null) return null;
  return panelNonNegativeNumber(value, key, "conversation delivery.delivery_latency_ms");
}

function DeliveryBody({ data }: { readonly data: ConversationDeliveryResponse }) {
  usePublishViewContext(
    () => ({
      routeId: "conversation-delivery",
      routeLabel: "Conversation delivery",
      purpose: "Read-only reliability metrics for durable operator-channel replies.",
      glossary: composeGlossary([], [{ term: "ambiguous delivery", plain: "a reply that may have reached the provider without a confirmed acknowledgement", tech: "OutboundDeliveryState.AMBIGUOUS" }]),
      headline: `${data.delivery_count} deliveries; ${data.duplicate_risk_count} duplicate risks`,
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
  const breakerEntries = Object.entries(data.breaker_states);
  return <div class="stack"><div class="governance-readonly-banner"><strong>Delivery evidence only.</strong><span>Pause, resume, retry, and resend remain authenticated channel commands.</span></div><KpiGrid><KpiCard label="Deliveries" value={data.delivery_count.toLocaleString()} /><KpiCard label="p95 latency" value={data.delivery_latency_ms.p95 === null ? "Unavailable" : `${data.delivery_latency_ms.p95.toLocaleString()} ms`} /><KpiCard label="Duplicate risk" value={data.duplicate_risk_count.toLocaleString()} /><KpiCard label="Retries" value={data.retry_count.toLocaleString()} /><KpiCard label="Abandoned" value={data.abandonment_count.toLocaleString()} /><KpiCard label="Acknowledged" value={data.acknowledgement_count.toLocaleString()} /></KpiGrid><section class="stack"><h2>Delivery states</h2><div class="status-list">{Object.entries(data.states).map(([name, count]) => <div key={name}><StatusPill kind={name === "delivered" ? "success" : name === "ambiguous" || name === "abandoned" ? "warning" : "neutral"} label={name} /><strong>{count.toLocaleString()}</strong></div>)}</div></section><section class="stack"><h2>Adapter breakers</h2>{breakerEntries.length === 0 ? <p>No adapter breaker records.</p> : <div class="status-list">{breakerEntries.map(([name, count]) => <div key={name}><StatusPill kind={name === "closed" ? "success" : "warning"} label={name} /><strong>{count.toLocaleString()}</strong></div>)}</div>}</section></div>;
}
