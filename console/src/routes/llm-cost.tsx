import { useEffect, useState } from "preact/hooks";
import { ReadApiError } from "../api";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { panelArray, panelBoolean, panelNumber, panelRecord, panelString } from "./panel-decode";

/**
 * LLM cost panel. Fetches ``GET /kpi/llm-cost`` and renders measured
 * token usage + spend grouped per conversation, per day, and per month.
 *
 * Read-only: every number comes from the metering stream (recorded from
 * real provider ``usage``); there is no action button. The ``source``
 * field is surfaced honestly - ``metering`` for a real store, or
 * ``synthetic-dev`` in the dev harness where LLM calls are faked.
 */

interface Summary {
  readonly key: string;
  readonly invocations: number;
  readonly priced_invocations: number;
  readonly prompt_tokens: number;
  readonly completion_tokens: number;
  readonly total_tokens: number;
  readonly cost: string;
  readonly currency: string;
  readonly has_unpriced: boolean;
  readonly has_mixed_currency: boolean;
}

interface Response {
  readonly source: string;
  readonly currency: string;
  readonly invocations: number;
  readonly total: Summary;
  readonly by_mode: readonly Summary[];
  readonly by_conversation: readonly Summary[];
  readonly by_conversation_truncated: boolean;
  readonly conversation_count: number;
  readonly by_day: readonly Summary[];
  readonly by_month: readonly Summary[];
}

interface Props {
  readonly client: ReadApiClient;
}

function _fmtCost(s: Summary): string {
  return `${s.cost} ${s.currency}`;
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
          if (err instanceof ReadApiError && err.status === 404) {
            setState({
              status: "unavailable",
              message:
                "LLM cost route is not wired on this deployment. Register " +
                "LlmCostPanel with a MeteringReader in the composition root " +
                "(ReadApiConfig.extra_panels) to enable it.",
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
    <div class="stack">
      <PageHeader title={t("route.llmCost")} subtitle={t("nav.panelSub.llmCost")} />
      <AsyncBoundary state={state} resourceLabel="LLM cost">
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
      priced_invocations: panelNumber(summary, "priced_invocations", label),
      prompt_tokens: panelNumber(summary, "prompt_tokens", label),
      completion_tokens: panelNumber(summary, "completion_tokens", label),
      total_tokens: panelNumber(summary, "total_tokens", label),
      cost: panelString(summary, "cost", label),
      currency: panelString(summary, "currency", label),
      has_unpriced: panelBoolean(summary, "has_unpriced", label),
      has_mixed_currency: panelBoolean(summary, "has_mixed_currency", label),
    };
  };
  const summaries = (key: string) => panelArray(root[key], `LLM cost.${key}`)
    .map((item, index) => decodeSummary(item, `LLM cost.${key}[${index}]`));
  return {
    source: panelString(root, "source", "LLM cost"),
    currency: panelString(root, "currency", "LLM cost"),
    invocations: panelNumber(root, "invocations", "LLM cost"),
    total: decodeSummary(root["total"], "LLM cost.total"),
    by_mode: summaries("by_mode"),
    by_conversation: summaries("by_conversation"),
    by_conversation_truncated: panelBoolean(root, "by_conversation_truncated", "LLM cost"),
    conversation_count: panelNumber(root, "conversation_count", "LLM cost"),
    by_day: summaries("by_day"),
    by_month: summaries("by_month"),
  };
}

function _summaryColumns(keyHeader: string): readonly Column<Summary>[] {
  return [
    { key: "k", header: keyHeader, render: (r) => r.key, cellClass: "mono" },
    { key: "inv", header: "Calls", render: (r) => r.invocations },
    { key: "pt", header: "Prompt", render: (r) => r.prompt_tokens.toLocaleString() },
    { key: "ct", header: "Completion", render: (r) => r.completion_tokens.toLocaleString() },
    { key: "tt", header: "Total tokens", render: (r) => r.total_tokens.toLocaleString() },
    {
      key: "cost",
      header: "Cost",
      render: (r) =>
        r.has_unpriced ? (
          <span>
            {_fmtCost(r)} <StatusPill kind="warning" label="partial" />
          </span>
        ) : (
          _fmtCost(r)
        ),
    },
  ];
}

function LlmCostBody({ data }: { readonly data: Response }) {
  usePublishViewContext(
    () => ({
      routeId: "llm-cost",
      routeLabel: "LLM cost",
      purpose:
        "Measured LLM token usage and spend, rolled up per conversation, per " +
        "day, and per month. Read-only: it reports recorded usage, it does not " +
        "cap spend (the model budget cap does that upstream).",
      glossary: composeGlossary([
        TERMS.tier,
        TERMS.correlationId,
        TERMS.mode,
        TERMS.hil,
      ]),
      headline: `${data.total.total_tokens.toLocaleString()} tokens - ${_fmtCost(data.total)} (${data.source})`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "source", value: data.source, group: "summary" },
        { key: "invocations", value: data.invocations, group: "summary" },
        { key: "total_tokens", value: data.total.total_tokens, group: "summary" },
        { key: "total_cost", value: _fmtCost(data.total), group: "summary" },
      ],
      records: {
        by_month: data.by_month.map((r) => ({ ...r })),
        by_day: data.by_day.map((r) => ({ ...r })),
        by_conversation: data.by_conversation.map((r) => ({ ...r })),
      },
    }),
    [data],
  );

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard label="Source" value={data.source} />
        <KpiCard label="LLM calls" value={data.invocations.toLocaleString()} />
        <KpiCard label="Total tokens" value={data.total.total_tokens.toLocaleString()} />
        <KpiCard label="Total cost" value={_fmtCost(data.total)} />
      </KpiGrid>

      <section class="stack">
        <h3>Shadow vs enforce</h3>
        <DataTable
          rows={data.by_mode}
          columns={_summaryColumns("Mode")}
          keyOf={(r) => r.key}
          empty="No LLM usage recorded yet"
        />
      </section>

      <section class="stack">
        <h3>Per month</h3>
        <DataTable
          rows={data.by_month}
          columns={_summaryColumns("Month")}
          keyOf={(r) => r.key}
          empty="No LLM usage recorded yet"
        />
      </section>

      <section class="stack">
        <h3>Per day</h3>
        <DataTable
          rows={data.by_day}
          columns={_summaryColumns("Day")}
          keyOf={(r) => r.key}
          empty="No LLM usage recorded yet"
        />
      </section>

      <section class="stack">
        <h3>Per conversation</h3>
        {data.by_conversation_truncated ? (
          <p class="muted">
            Showing the costliest {data.by_conversation.length} of {data.conversation_count}{" "}
            conversations.
          </p>
        ) : null}
        <DataTable
          rows={data.by_conversation}
          columns={_summaryColumns("Correlation id")}
          keyOf={(r) => r.key}
          empty="No LLM usage recorded yet"
        />
      </section>
    </div>
  );
}
