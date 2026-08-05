import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable } from "../api";
import type { OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  UnavailableState,
  kpiEvidenceLabel,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { getLocale } from "../i18n";
import { t } from "./i18n/llm-cost";
import "./llm-cost-alignment.css";
import { currentRoute, replaceRouteState, routeHref } from "../router";
import { LlmCostRangeControl } from "./llm-cost-range-control";
import {
  llmUsageRangeApiParams,
  llmUsageRangeDays,
  llmUsageRangeFromSearch,
  llmUsageRangeLabel,
  llmUsageRangeSearchParams,
  type LlmUsageRange,
} from "./llm-cost-range";
import { LlmCostTrend } from "./llm-cost-trend";
import {
  panelArray,
  panelBoolean,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelString,
} from "./panel-decode";

/**
 * LLM usage panel. Fetches ``GET /kpi/llm-cost`` and renders measured
 * provider tokens by workload, model, call, day, and month.
 *
 * Read-only: every number comes from the metering stream (recorded from
 * real provider ``usage``). Pricing remains internal and is not exposed.
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

export interface InvocationRecord {
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

const INVOCATION_CSV_FIELDS: readonly (keyof InvocationRecord)[] = [
  "occurred_at",
  "correlation_id",
  "capability_id",
  "model_key",
  "tier",
  "mode",
  "usage_scope",
  "prompt_tokens",
  "completion_tokens",
  "total_tokens",
];

export function invocationCsv(records: readonly InvocationRecord[]): string {
  const rows = [
    INVOCATION_CSV_FIELDS,
    ...records.map((record) => INVOCATION_CSV_FIELDS.map((field) => record[field])),
  ];
  return `${rows.map((row) => row.map(csvCell).join(",")).join("\r\n")}\r\n`;
}

export function downloadInvocationCsv(records: readonly InvocationRecord[]): void {
  const url = URL.createObjectURL(new Blob([invocationCsv(records)], {
    type: "text/csv;charset=utf-8",
  }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "fdai-llm-invocations.csv";
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function csvCell(value: string | number): string {
  const raw = String(value);
  const formulaCandidate = raw.replace(/^[\s\uFEFF]+/u, "");
  const safe = /^[=+\-@]/.test(formulaCandidate) ? `'${raw}` : raw;
  return `"${safe.replaceAll('"', '""')}"`;
}

interface Response {
  readonly source: string;
  readonly range_start: string | null;
  readonly range_end: string | null;
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
  readonly by_hour: readonly Summary[];
  readonly by_day: readonly Summary[];
  readonly by_month: readonly Summary[];
  readonly records: readonly InvocationRecord[];
  readonly records_truncated: boolean;
  readonly record_count: number;
}

interface Props {
  readonly client: OperatorApiClient;
}

export function tokenShare(part: number, total: number): number | null {
  return total > 0 ? part / total : null;
}

export function usageTrendPoints(rows: readonly Summary[]): string | null {
  if (rows.length < 2) return null;
  const values = [...rows]
    .sort((left, right) => left.key.localeCompare(right.key))
    .map((row) => row.total_tokens);
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const range = maximum - minimum;
  return values.map((value, index) => {
    const x = (index / (values.length - 1)) * 100;
    const y = range === 0 ? 18 : 34 - ((value - minimum) / range) * 30;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

export function LlmCostRoute({ client }: Props) {
  const [range, setRange] = useState<LlmUsageRange>(() =>
    llmUsageRangeFromSearch(currentRoute().search, new Date())
  );
  const [state, setState] = useState<AsyncState<Response>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const data = decodeLlmCost(await client.panel<unknown>(
          "/kpi/llm-cost",
          { ...llmUsageRangeApiParams(range) },
        ));
        if (!cancelled) setState({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (isOptionalOperatorApiUnavailable(err)) {
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
  }, [client, range.from, range.to]);

  const changeRange = (next: LlmUsageRange) => {
    setRange(next);
    replaceRouteState(routeHref("llm-cost", { params: llmUsageRangeSearchParams(next) }));
  };

  return (
    <div class="stack analytics-route">
      <PageHeader title={t("llmCost.title")} subtitle={t("llmCost.subtitle")} />
      <div class="llm-cost-boundary">
        <strong>{t("llmCost.boundaryTitle")}</strong>
        <span>{t("llmCost.boundaryBody")}</span>
      </div>
      <LlmCostRangeControl range={range} onChange={changeRange} />
      <AsyncBoundary state={state} resourceLabel={t("llmCost.title")}>
        {(data) => <LlmCostBody data={data} range={range} />}
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
      invocations: panelNonNegativeInteger(summary, "invocations", label),
      prompt_tokens: panelNonNegativeInteger(summary, "prompt_tokens", label),
      completion_tokens: panelNonNegativeInteger(summary, "completion_tokens", label),
      total_tokens: panelNonNegativeInteger(summary, "total_tokens", label),
    };
  };
  const summaries = (key: string) => panelArray(root[key], `LLM cost.${key}`)
    .map((item, index) => decodeSummary(item, `LLM cost.${key}[${index}]`));
  return {
    source: panelString(root, "source", "LLM cost"),
    range_start: panelNullableString(root, "range_start", "LLM cost"),
    range_end: panelNullableString(root, "range_end", "LLM cost"),
    latest_occurred_at: panelNullableString(root, "latest_occurred_at", "LLM cost"),
    invocations: panelNonNegativeInteger(root, "invocations", "LLM cost"),
    total: decodeSummary(root["total"], "LLM cost.total"),
    chat: decodeSummary(root["chat"], "LLM cost.chat"),
    by_scope: summaries("by_scope"),
    by_model: summaries("by_model"),
    chat_by_model: summaries("chat_by_model"),
    by_mode: summaries("by_mode"),
    by_conversation: summaries("by_conversation"),
    by_conversation_truncated: panelBoolean(root, "by_conversation_truncated", "LLM cost"),
    conversation_count: panelNonNegativeInteger(root, "conversation_count", "LLM cost"),
    by_hour: summaries("by_hour"),
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
        prompt_tokens: panelNonNegativeInteger(record, "prompt_tokens", `LLM cost.records[${index}]`),
        completion_tokens: panelNonNegativeInteger(record, "completion_tokens", `LLM cost.records[${index}]`),
        total_tokens: panelNonNegativeInteger(record, "total_tokens", `LLM cost.records[${index}]`),
      };
    }),
    records_truncated: panelBoolean(root, "records_truncated", "LLM cost"),
    record_count: panelNonNegativeInteger(root, "record_count", "LLM cost"),
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
    { key: "inv", header: t("llmCost.column.calls"), render: (r) => r.invocations, cellClass: "num" },
    { key: "pt", header: t("llmCost.column.input"), render: (r) => r.prompt_tokens.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US"), cellClass: "num" },
    { key: "ct", header: t("llmCost.column.output"), render: (r) => r.completion_tokens.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US"), cellClass: "num" },
    { key: "tt", header: t("llmCost.totalTokens"), render: (r) => r.total_tokens.toLocaleString(getLocale() === "ko" ? "ko-KR" : "en-US"), cellClass: "num" },
  ];
}

function _recordColumns(locale: string): readonly Column<InvocationRecord>[] {
  const tokens = (value: number) => value.toLocaleString(locale);
  return [
    { key: "when", header: t("llmCost.column.timestamp"), render: (r) => new Date(r.occurred_at).toLocaleString(locale) },
    { key: "scope", header: t("llmCost.column.scope"), render: (r) => <span class={`llm-cost-scope${r.usage_scope === "operator_chat" ? " is-chat" : ""}`}>{t(`llmCost.scope.${r.usage_scope}`)}</span>, cellClass: "mono" },
    { key: "model", header: t("llmCost.column.model"), render: (r) => r.model_key, cellClass: "mono" },
    { key: "cap", header: t("llmCost.column.capability"), render: (r) => r.capability_id, cellClass: "mono" },
    { key: "tier", header: t("llmCost.column.tierMode"), render: (r) => <><span class={`llm-cost-tier is-${r.tier.toLowerCase()}`}>{r.tier}</span> / {r.mode}</>, cellClass: "mono" },
    { key: "input", header: t("llmCost.column.input"), render: (r) => tokens(r.prompt_tokens), cellClass: "num" },
    { key: "output", header: t("llmCost.column.output"), render: (r) => tokens(r.completion_tokens), cellClass: "num" },
    { key: "total", header: t("llmCost.totalTokens"), render: (r) => tokens(r.total_tokens), cellClass: "num" },
    { key: "corr", header: t("llmCost.column.correlationId"), render: (r) => <a href={llmUsageCorrelationHref(r.correlation_id)}>{r.correlation_id}</a>, cellClass: "mono" },
  ];
}

function LlmCostBody({ data, range }: { readonly data: Response; readonly range: LlmUsageRange }) {
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  const compact = new Intl.NumberFormat(locale, { notation: "compact", maximumFractionDigits: 2 });
  const auditContext = Object.fromEntries(currentRoute().search.entries());
  const auditHref = routeHref("audit", { params: auditContext });
  const latestRecord = data.records[0];
  const latestHref = latestRecord
    ? routeHref("audit", {
        params: { ...auditContext, correlation: latestRecord.correlation_id },
      })
    : auditHref;
  const chatShare = tokenShare(data.chat.total_tokens, data.total.total_tokens);
  const rangeLabel = llmUsageRangeLabel(range, locale);
  const windowLabel = range.preset === "24h"
    ? t("llmCost.rangeHours", { count: 24 })
    : t("llmCost.rangeDays", { count: llmUsageRangeDays(range) });
  usePublishViewContext(
    () => ({
      routeId: "llm-cost",
      routeLabel: t("llmCost.title"),
      purpose:
        "Measured provider token usage by workload, model, invocation, day, and month. " +
        "Cost amounts are not exposed.",
      glossary: composeGlossary([
        TERMS.tier,
        TERMS.mode,
        TERMS.hil,
      ]),
      headline: `${data.total.total_tokens.toLocaleString(locale)} tokens - ${data.chat.total_tokens.toLocaleString(locale)} chat tokens (${data.source})`,
      capturedAt: data.latest_occurred_at ?? new Date().toISOString(),
      facts: [
        { key: "source", value: data.source, group: "summary" },
        { key: "range_start", value: data.range_start, group: "summary" },
        { key: "range_end", value: data.range_end, group: "summary" },
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
    [data, range.from, range.to],
  );

  return (
    <div class="stack llm-cost-view">
      <div class="analytics-evidence llm-cost-evidence">
        <strong>{t("llmCost.measuredUsage")}</strong>
        <span>{t("llmCost.rangeEvidence", { range: rangeLabel })}</span>
        <span>{t("llmCost.source")}: {data.source}</span>
        <span>{t("llmCost.measuredCalls", { count: data.record_count.toLocaleString(locale) })}</span>
        <span>{data.latest_occurred_at ? t("llmCost.asOf", { time: new Date(data.latest_occurred_at).toLocaleString(locale) }) : t("llmCost.noInvocationEvidence")}</span>
      </div>
      <div class="llm-cost-kpis">
        <KpiGrid>
          <KpiCard href={auditHref} label={t("llmCost.calls")} value={data.invocations.toLocaleString(locale)} hint={`${t("llmCost.source")}: ${data.source}`} />
          <KpiCard href={auditHref} label={t("llmCost.totalTokens")} value={compact.format(data.total.total_tokens)} hint={data.total.total_tokens.toLocaleString(locale)} />
          <KpiCard href={auditHref} label={t("llmCost.chatShare")} value={chatShare === null ? kpiEvidenceLabel("not-measured") : `${Math.round(chatShare * 100)}%`} evidenceState={chatShare === null ? "not-measured" : "measured"} hint={chatShare === null ? t("llmCost.noInvocationEvidence") : t("llmCost.chatTokensValue", { count: compact.format(data.chat.total_tokens) })} />
          <KpiCard
            evidenceState={data.latest_occurred_at ? "measured" : "not-measured"}
            href={latestHref}
            label={t("llmCost.latestInvocation")}
            value={data.latest_occurred_at ? <time class="llm-cost-timestamp" dateTime={data.latest_occurred_at}>{new Date(data.latest_occurred_at).toLocaleString(locale)}</time> : kpiEvidenceLabel("not-measured")}
          />
                  <KpiCard
                    evidenceState="not-connected"
                    href={routeHref("operating-outcomes", { segments: ["cost-per-resolved-event"] })}
                    label={t("llmCost.fixedCost")}
                    value={kpiEvidenceLabel("not-connected")}
                    hint={t("llmCost.fixedCostHint")}
                  />
        </KpiGrid>
      </div>

      <div class="llm-cost-analysis">
        <TokenComposition data={data} auditHref={auditHref} locale={locale} />
        <LlmCostTrend
          rows={range.preset === "24h" ? data.by_hour : data.by_day}
          auditHref={auditHref}
          locale={locale}
          windowLabel={windowLabel}
          hourly={range.preset === "24h"}
        />
      </div>

      <section class="stack llm-cost-section" id="usage-by-model">
        <div class="llm-cost-section-head">
          <div><h3>{t("llmCost.byModel")}</h3><p>{t("llmCost.byModelSubtitle")}</p></div>
          <a href={auditHref}>{t("llmCost.viewUsageAudit")}</a>
        </div>
        <DataTable
          rows={data.by_model}
          columns={_summaryColumns(t("llmCost.column.model"), () => auditHref)}
          keyOf={(r) => r.key}
          empty={t("llmCost.empty")}
        />
      </section>

      <section class="stack llm-cost-section" id="invocation-ledger">
        <div class="llm-cost-section-head">
          <div><h3>{t("llmCost.invocationLedger")}</h3><p>{t("llmCost.invocationLedgerSubtitle")}</p></div>
                  <button type="button" class="btn" disabled={data.records.length === 0} onClick={() => downloadInvocationCsv(data.records)}>{t("llmCost.exportCsv")}</button>
        </div>
        {data.records_truncated ? <p class="muted">{t("llmCost.recordsTruncated", { shown: data.records.length, total: data.record_count })}</p> : null}
        <DataTable
          rows={data.records}
          columns={_recordColumns(locale)}
          keyOf={(r) => `${r.occurred_at}:${r.correlation_id}:${r.capability_id}:${r.model_key}`}
          empty={t("llmCost.empty")}
        />
      </section>

      <details class="llm-cost-rollups">
        <summary>{t("llmCost.additionalRollups")}</summary>
        <div class="stack llm-cost-rollups-body">
          <RollupTable heading={t("llmCost.chatUsage")} rows={data.chat_by_model} keyHeader={t("llmCost.column.model")} empty={t("llmCost.empty")} href={() => auditHref} />
          <RollupTable heading={t("llmCost.byConversation")} rows={data.by_conversation} keyHeader={t("llmCost.column.correlationId")} empty={t("llmCost.empty")} href={llmUsageCorrelationHref} />
          <RollupTable heading={t("llmCost.byScope")} rows={data.by_scope} keyHeader={t("llmCost.column.scope")} empty={t("llmCost.empty")} href={() => auditHref} />
          <RollupTable heading={t("llmCost.byMode")} rows={data.by_mode} keyHeader={t("llmCost.column.mode")} empty={t("llmCost.empty")} href={(key) => routeHref("audit", { params: { ...auditContext, mode: key } })} />
          <RollupTable heading={t("llmCost.byDay")} rows={data.by_day} keyHeader={t("llmCost.column.day")} empty={t("llmCost.empty")} href={() => auditHref} />
          <RollupTable heading={t("llmCost.byMonth")} rows={data.by_month} keyHeader={t("llmCost.column.month")} empty={t("llmCost.empty")} href={() => auditHref} />
        </div>
      </details>
    </div>
  );
}

function TokenComposition({ data, auditHref, locale }: { readonly data: Response; readonly auditHref: string; readonly locale: string }) {
  const inputShare = tokenShare(data.total.prompt_tokens, data.total.total_tokens);
  const outputShare = tokenShare(data.total.completion_tokens, data.total.total_tokens);
  return (
    <section class="llm-cost-panel" aria-labelledby="llm-token-composition-title">
      <div class="llm-cost-panel-head">
        <div><h3 id="llm-token-composition-title">{t("llmCost.tokenComposition")}</h3><p>{t("llmCost.tokenCompositionSubtitle")}</p></div>
        <a href={auditHref}>{t("llmCost.viewEvidence")}</a>
      </div>
      {inputShare === null || outputShare === null ? <UnavailableState message={t("llmCost.noInvocationEvidence")} /> : (
        <>
          <div class="llm-token-mix" aria-hidden="true">
            <span class="is-input" style={{ flexGrow: inputShare }} />
            <span class="is-output" style={{ flexGrow: outputShare }} />
          </div>
          <div class="llm-token-legend">
            <span>
              <span class="llm-token-kind"><i class="is-input" />{t("llmCost.inputTokens")}</span>
              <strong>{data.total.prompt_tokens.toLocaleString(locale)}</strong>
              <small>{Math.round(inputShare * 100)}%</small>
            </span>
            <span>
              <span class="llm-token-kind"><i class="is-output" />{t("llmCost.outputTokens")}</span>
              <strong>{data.total.completion_tokens.toLocaleString(locale)}</strong>
              <small>{Math.round(outputShare * 100)}%</small>
            </span>
          </div>
        </>
      )}
    </section>
  );
}

function RollupTable({ heading, rows, keyHeader, empty, href }: { readonly heading: string; readonly rows: readonly Summary[]; readonly keyHeader: string; readonly empty: string; readonly href: (key: string) => string }) {
  return (
    <section class="stack">
      <h3>{heading}</h3>
      <DataTable rows={rows} columns={_summaryColumns(keyHeader, href)} keyOf={(row) => row.key} empty={empty} />
    </section>
  );
}
