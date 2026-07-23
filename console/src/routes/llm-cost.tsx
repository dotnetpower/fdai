import { useEffect, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable } from "../api";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  kpiEvidenceLabel,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { getLocale } from "../i18n";
import { t } from "./i18n/llm-cost";
import { currentRoute, routeHref } from "../router";
import {
  panelArray,
  panelBoolean,
  panelNullableString,
  panelNumber,
  panelRecord,
  panelString,
} from "./panel-decode";

/**
 * LLM usage panel. Fetches ``GET /kpi/llm-cost`` and renders measured
 * provider tokens by workload, model, call, day, and month.
 *
 * Read-only: every number comes from the metering stream (recorded from
 * real provider ``usage``); derived price is intentionally not exposed.
 * The ``source``
 * field is surfaced honestly - ``metering`` for a real store, or
 * ``synthetic-dev`` in the dev harness where LLM calls are faked.
 */

interface Summary {
  readonly key: string;
  readonly invocations: number;
  readonly prompt_tokens: number;
  readonly completion_tokens: number;
  readonly total_tokens: number;
}

interface InvocationRecord {
  readonly occurred_at: string;
  readonly correlation_id: string;
  readonly capability_id: string;
  readonly model_key: string;
  readonly tier: string;
  readonly mode: string;
  readonly usage_scope: string;
  readonly prompt_tokens: number;
  readonly completion_tokens: number;
  readonly total_tokens: number;
}

interface Response {
  readonly source: string;
  readonly latest_occurred_at: string | null;
  readonly invocations: number;
  readonly total: Summary;
  readonly chat: Summary;
  readonly by_scope: readonly Summary[];
  readonly by_model: readonly Summary[];
  readonly chat_by_model: readonly Summary[];
  readonly by_mode: readonly Summary[];
  readonly by_conversation: readonly Summary[];
  readonly by_conversation_truncated: boolean;
  readonly conversation_count: number;
  readonly by_day: readonly Summary[];
  readonly by_month: readonly Summary[];
  readonly records: readonly InvocationRecord[];
  readonly records_truncated: boolean;
  readonly record_count: number;
}

interface Props {
  readonly client: ReadApiClient;
}

export function LlmCostRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<Response>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = decodeLlmCost(await client.panel<unknown>("/kpi/llm-cost"));
        if (!cancelled) setState({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalReadApiUnavailable(err)) {
            setState({
              status: "unavailable",
              message: t("llmCost.unavailable"),
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
    <div class="stack analytics-route">
      <PageHeader title={t("llmCost.title")} subtitle={t("llmCost.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("llmCost.title")}>
        {(data) => <LlmCostBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeLlmCost(value: unknown): Response {
  const root = panelRecord(value, "LLM cost");
  const decodeSummary = (value: unknown, label: string): Summary => {
    const summary = panelRecord(value, label);
    return {
      key: panelString(summary, "key", label),
      invocations: panelNumber(summary, "invocations", label),
      prompt_tokens: panelNumber(summary, "prompt_tokens", label),
      completion_tokens: panelNumber(summary, "completion_tokens", label),
      total_tokens: panelNumber(summary, "total_tokens", label),
    };
  };
  const summaries = (key: string) => panelArray(root[key], `LLM cost.${key}`)
    .map((item, index) => decodeSummary(item, `LLM cost.${key}[${index}]`));
  return {
    source: panelString(root, "source", "LLM cost"),
    latest_occurred_at: panelNullableString(root, "latest_occurred_at", "LLM cost"),
    invocations: panelNumber(root, "invocations", "LLM cost"),
    total: decodeSummary(root["total"], "LLM cost.total"),
    chat: decodeSummary(root["chat"], "LLM cost.chat"),
    by_scope: summaries("by_scope"),
    by_model: summaries("by_model"),
    chat_by_model: summaries("chat_by_model"),
    by_mode: summaries("by_mode"),
    by_conversation: summaries("by_conversation"),
    by_conversation_truncated: panelBoolean(root, "by_conversation_truncated", "LLM cost"),
    conversation_count: panelNumber(root, "conversation_count", "LLM cost"),
    by_day: summaries("by_day"),
    by_month: summaries("by_month"),
    records: panelArray(root["records"], "LLM cost.records").map((item, index) => {
      const record = panelRecord(item, `LLM cost.records[${index}]`);
      return {
        occurred_at: panelString(record, "occurred_at", `LLM cost.records[${index}]`),
        correlation_id: panelString(record, "correlation_id", `LLM cost.records[${index}]`),
        capability_id: panelString(record, "capability_id", `LLM cost.records[${index}]`),
        model_key: panelString(record, "model_key", `LLM cost.records[${index}]`),
        tier: panelString(record, "tier", `LLM cost.records[${index}]`),
        mode: panelString(record, "mode", `LLM cost.records[${index}]`),
        usage_scope: panelString(record, "usage_scope", `LLM cost.records[${index}]`),
        prompt_tokens: panelNumber(record, "prompt_tokens", `LLM cost.records[${index}]`),
        completion_tokens: panelNumber(record, "completion_tokens", `LLM cost.records[${index}]`),
        total_tokens: panelNumber(record, "total_tokens", `LLM cost.records[${index}]`),
      };
    }),
    records_truncated: panelBoolean(root, "records_truncated", "LLM cost"),
    record_count: panelNumber(root, "record_count", "LLM cost"),
  };
}

export function llmUsageCorrelationHref(correlationId: string): string {
  return routeHref("audit", { params: { correlation: correlationId } });
}

function _summaryColumns(
  keyHeader: string,
  keyHref?: (key: string) => string,
): readonly Column<Summary>[] {
  return [
    {
      key: "k",
      header: keyHeader,
      render: (r) => keyHref ? <a href={keyHref(r.key)}>{r.key}</a> : r.key,
      cellClass: "mono",
    },
    { key: "inv", header: t("llmCost.column.calls"), render: (r) => r.invocations },
    { key: "pt", header: t("llmCost.column.input"), render: (r) => r.prompt_tokens.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US"), cellClass: "num" },
    { key: "ct", header: t("llmCost.column.output"), render: (r) => r.completion_tokens.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US"), cellClass: "num" },
    { key: "tt", header: t("llmCost.totalTokens"), render: (r) => r.total_tokens.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US") },
  ];
}

function _recordColumns(locale: string): readonly Column<InvocationRecord>[] {
  const tokens = (value: number) => value.toLocaleString(locale);
  return [
    { key: "when", header: t("llmCost.column.timestamp"), render: (r) => new Date(r.occurred_at).toLocaleString(locale) },
    { key: "scope", header: t("llmCost.column.scope"), render: (r) => t(`llmCost.scope.${r.usage_scope}`), cellClass: "mono" },
    { key: "model", header: t("llmCost.column.model"), render: (r) => r.model_key, cellClass: "mono" },
    { key: "cap", header: t("llmCost.column.capability"), render: (r) => r.capability_id, cellClass: "mono" },
    { key: "tier", header: t("llmCost.column.tierMode"), render: (r) => `${r.tier} / ${r.mode}`, cellClass: "mono" },
    { key: "input", header: t("llmCost.column.input"), render: (r) => tokens(r.prompt_tokens), cellClass: "num" },
    { key: "output", header: t("llmCost.column.output"), render: (r) => tokens(r.completion_tokens), cellClass: "num" },
    { key: "total", header: t("llmCost.totalTokens"), render: (r) => tokens(r.total_tokens), cellClass: "num" },
    { key: "corr", header: t("llmCost.column.correlationId"), render: (r) => <a href={llmUsageCorrelationHref(r.correlation_id)}>{r.correlation_id}</a>, cellClass: "mono" },
  ];
}

function LlmCostBody({ data }: { readonly data: Response }) {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  const auditContext = Object.fromEntries(currentRoute().search.entries());
  const auditHref = routeHref("audit", { params: auditContext });
  const latestRecord = data.records[0];
  const latestHref = latestRecord
    ? routeHref("audit", {
        params: { ...auditContext, correlation: latestRecord.correlation_id },
      })
    : auditHref;
  usePublishViewContext(
    () => ({
      routeId: "llm-cost",
      routeLabel: t("llmCost.title"),
      purpose:
        "Measured provider token usage by workload, model, invocation, day, and month. " +
        "Derived price is intentionally not exposed.",
      glossary: composeGlossary([
        TERMS.tier,
        TERMS.mode,
        TERMS.hil,
      ]),
      headline: `${data.total.total_tokens.toLocaleString(locale)} tokens - ${data.chat.total_tokens.toLocaleString(locale)} chat tokens (${data.source})`,
      capturedAt: data.latest_occurred_at ?? new Date().toISOString(),
      facts: [
        { key: "source", value: data.source, group: "summary" },
        { key: "latest_occurred_at", value: data.latest_occurred_at, group: "summary" },
        { key: "invocations", value: data.invocations, group: "summary" },
        { key: "total_tokens", value: data.total.total_tokens, group: "summary" },
        { key: "chat_tokens", value: data.chat.total_tokens, group: "summary" },
      ],
      records: {
        by_month: data.by_month.map((r) => ({ ...r })),
        by_day: data.by_day.map((r) => ({ ...r })),
        by_conversation: data.by_conversation.map((r) => ({ ...r })),
        by_model: data.by_model.map((r) => ({ ...r })),
        invocations: data.records.map((r) => ({ ...r })),
      },
    }),
    [data],
  );

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard href={auditHref} label={t("llmCost.calls")} value={data.invocations.toLocaleString(locale)} hint={`${t("llmCost.source")}: ${data.source}`} />
        <KpiCard href={auditHref} label={t("llmCost.totalTokens")} value={data.total.total_tokens.toLocaleString(locale)} />
        <KpiCard href={auditHref} label={t("llmCost.chatTokens")} value={data.chat.total_tokens.toLocaleString(locale)} />
        <KpiCard href={auditHref} label={t("llmCost.inputTokens")} value={data.total.prompt_tokens.toLocaleString(locale)} />
        <KpiCard href={auditHref} label={t("llmCost.outputTokens")} value={data.total.completion_tokens.toLocaleString(locale)} />
        <KpiCard
          evidenceState={data.latest_occurred_at ? "measured" : "not-measured"}
          href={latestHref}
          label={t("llmCost.latestInvocation")}
          value={data.latest_occurred_at ? new Date(data.latest_occurred_at).toLocaleString(locale) : kpiEvidenceLabel("not-measured")}
        />
      </KpiGrid>

      <section class="stack">
        <h3>{t("llmCost.chatUsage")}</h3>
        <DataTable
          rows={data.chat_by_model}
          columns={_summaryColumns(t("llmCost.column.model"))}
          keyOf={(r) => r.key}
          empty={t("llmCost.empty")}
        />
      </section>

      <section class="stack">
        <h3>{t("llmCost.byModel")}</h3>
        <DataTable
          rows={data.by_model}
          columns={_summaryColumns(t("llmCost.column.model"))}
          keyOf={(r) => r.key}
          empty={t("llmCost.empty")}
        />
      </section>

      <section class="stack">
        <h3>{t("llmCost.invocationLedger")}</h3>
        {data.records_truncated ? <p class="muted">{t("llmCost.recordsTruncated", { shown: data.records.length, total: data.record_count })}</p> : null}
        <DataTable
          rows={data.records}
          columns={_recordColumns(locale)}
          keyOf={(r) => `${r.occurred_at}:${r.correlation_id}:${r.capability_id}:${r.model_key}`}
          empty={t("llmCost.empty")}
        />
      </section>

      <section class="stack">
        <h3>{t("llmCost.byMode")}</h3>
        <DataTable
          rows={data.by_mode}
          columns={_summaryColumns(t("llmCost.column.mode"))}
          keyOf={(r) => r.key}
          empty={t("llmCost.empty")}
        />
      </section>

      <section class="stack">
        <h3>{t("llmCost.byDay")}</h3>
        <DataTable rows={data.by_day} columns={_summaryColumns(t("llmCost.column.day"))} keyOf={(r) => r.key} empty={t("llmCost.empty")} />
      </section>

      <section class="stack">
        <h3>{t("llmCost.byMonth")}</h3>
        <DataTable rows={data.by_month} columns={_summaryColumns(t("llmCost.column.month"))} keyOf={(r) => r.key} empty={t("llmCost.empty")} />
      </section>
    </div>
  );
}
