import { useEffect, useMemo, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import { EvidenceRefresh } from "../components/evidence-refresh";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  kpiEvidenceLabel,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import { getLocale } from "../i18n";
import { currentRoute, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/evidence";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

interface ComparisonRow {
  readonly evaluation_id: string;
  readonly baseline_policy_ref: string;
  readonly candidate_policy_ref: string;
  readonly baseline_tokens: number;
  readonly candidate_tokens: number | null;
  readonly evidence_overlap: number | null;
  readonly omissions: readonly string[];
  readonly pinned_preserved: boolean;
  readonly latency_ms: number;
  readonly failure_reason: string | null;
  readonly created_at: string;
}

interface ComparisonResponse {
  readonly read_only: boolean;
  readonly count: number;
  readonly invariant_failures: number;
  readonly mutation_controls: boolean;
  readonly comparisons: readonly ComparisonRow[];
}

export function ContextSelectionComparisonsRoute({ client }: { readonly client: OperatorApiClient }) {
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [state, setState] = useState<AsyncState<ComparisonResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const data = decodeContextSelectionComparisons(
          await client.panel<unknown>("/context-selection-comparisons"),
        );
        if (!cancelled) setState({ status: "ready", data });
      } catch (error) {
        if (cancelled) return;
        if (isOptionalOperatorApiUnavailable(error)) {
          setState({ status: "unavailable", message: t("evidence.contextSelection.unavailable") });
        } else {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client, refreshRevision]);

  return (
    <div class="stack governance-route cs-workspace-route">
      <PageHeader
        title={t("route.contextSelectionComparisons")}
        subtitle={t("evidence.contextSelection.subtitle")}
        actions={
          <EvidenceRefresh
            loading={state.status === "loading"}
            onRefresh={() => {
              setState({ status: "loading" });
              setRefreshRevision((revision) => revision + 1);
            }}
          />
        }
      />
      <AsyncBoundary state={state} resourceLabel={t("evidence.contextSelection.resource")}>
        {(data) => <ComparisonBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

export function decodeContextSelectionComparisons(value: unknown): ComparisonResponse {
  const root = panelRecord(value, "context policy comparisons");
  const readOnly = panelBoolean(root, "read_only", "context policy comparisons");
  const mutationControls = panelBoolean(root, "mutation_controls", "context policy comparisons");
  if (!readOnly || mutationControls) {
    throw new OperatorApiError(502, "invalid Operator API response: context policy panel MUST be read-only");
  }
  const comparisons = panelArray(root["comparisons"], "context policy comparisons.comparisons")
    .map((value, index) => decodeRow(value, index));
  const seenIds = new Set<string>();
  for (const row of comparisons) {
    if (seenIds.has(row.evaluation_id)) {
      throw new OperatorApiError(502, "invalid Operator API response: evaluation_id MUST be unique");
    }
    seenIds.add(row.evaluation_id);
  }
  const count = panelNonNegativeInteger(root, "count", "context policy comparisons");
  const failures = panelNonNegativeInteger(root, "invariant_failures", "context policy comparisons");
  if (count !== comparisons.length || failures !== comparisons.filter((row) => row.failure_reason !== null).length) {
    throw new OperatorApiError(502, "invalid Operator API response: context policy summary counts MUST match rows");
  }
  return { read_only: readOnly, mutation_controls: mutationControls, count, invariant_failures: failures, comparisons };
}

function decodeRow(value: unknown, index: number): ComparisonRow {
  const row = panelRecord(value, `context policy comparisons[${index}]`);
  return {
    evaluation_id: panelNonEmptyString(row, "evaluation_id", "context policy comparison"),
    baseline_policy_ref: panelNonEmptyString(row, "baseline_policy_ref", "context policy comparison"),
    candidate_policy_ref: panelNonEmptyString(row, "candidate_policy_ref", "context policy comparison"),
    baseline_tokens: panelNonNegativeInteger(row, "baseline_tokens", "context policy comparison"),
    candidate_tokens: nullableNonNegativeInteger(row["candidate_tokens"], "candidate_tokens"),
    evidence_overlap: nullableRatio(row["evidence_overlap"], "evidence_overlap"),
    omissions: panelStringArray(row["omissions"], "context policy comparison.omissions"),
    pinned_preserved: panelBoolean(row, "pinned_preserved", "context policy comparison"),
    latency_ms: panelNonNegativeNumber(row, "latency_ms", "context policy comparison"),
    failure_reason: nullableString(row["failure_reason"], "failure_reason"),
    created_at: panelNonEmptyString(row, "created_at", "context policy comparison"),
  };
}

function nullableNonNegativeInteger(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} MUST be a non-negative integer or null`);
  }
  return value;
}

function nullableRatio(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} MUST be between 0 and 1 or null`);
  }
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string") {
    throw new OperatorApiError(502, `invalid Operator API response: ${label} MUST be a string or null`);
  }
  return value;
}

function ComparisonBody({ data }: { readonly data: ComparisonResponse }) {
  const [query, setQuery] = useState("");
  const [resultFilter, setResultFilter] = useState<"all" | "passed" | "failed">("all");
  const [selectedId, setSelectedId] = useState<string | null>(
    () => data.comparisons[0]?.evaluation_id ?? null,
  );
  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return data.comparisons.filter((row) => {
      if (resultFilter === "passed" && row.failure_reason !== null) return false;
      if (resultFilter === "failed" && row.failure_reason === null) return false;
      if (!needle) return true;
      return [
        row.evaluation_id,
        row.baseline_policy_ref,
        row.candidate_policy_ref,
        row.failure_reason ?? "",
        ...row.omissions,
      ].join(" ").toLocaleLowerCase().includes(needle);
    });
  }, [data.comparisons, query, resultFilter]);
  const selected = filtered.find((row) => row.evaluation_id === selectedId) ?? filtered[0] ?? null;
  const pinnedPreservedCount = data.comparisons.filter((row) => row.pinned_preserved).length;
  const averageLatencyMs = data.comparisons.length > 0
    ? data.comparisons.reduce((sum, row) => sum + row.latency_ms, 0) / data.comparisons.length
    : null;

  usePublishViewContext(
    () => ({
      routeId: "context-selection-comparisons",
      routeLabel: t("route.contextSelectionComparisons"),
      purpose: t("evidence.contextSelection.subtitle"),
      glossary: composeGlossary([TERMS.shadowMode]),
      headline: `${data.count} comparisons - ${data.invariant_failures} invariant failures`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "comparison_count", value: data.count, group: "context-selection" },
        { key: "invariant_failures", value: data.invariant_failures, group: "context-selection" },
        { key: "selected_evaluation", value: selected?.evaluation_id ?? "-", group: "context-selection" },
        { key: "read_only", value: data.read_only, group: "safety" },
        { key: "mutation_controls", value: data.mutation_controls, group: "safety" },
      ],
      records: {
        comparisons: data.comparisons.slice(0, 25).map((row) => ({ ...row })),
      },
    }),
    [data, selected],
  );
  const comparisonsHref = `${routeHref("context-selection-comparisons", {
    params: { data: currentRoute().search.get("data") === "sample" ? "sample" : null },
  })}#context-selection-comparisons`;
  const columns: readonly Column<ComparisonRow>[] = [
    { key: "candidate", header: t("evidence.contextSelection.column.candidate"), render: (row) => <div><strong>{row.candidate_policy_ref}</strong><small class="muted">{row.baseline_policy_ref}</small></div>, cellClass: "mono" },
    { key: "tokens", header: t("evidence.contextSelection.column.tokens"), render: (row) => `${row.baseline_tokens} / ${row.candidate_tokens ?? "-"}` },
    { key: "overlap", header: t("evidence.contextSelection.column.overlap"), render: (row) => row.evidence_overlap === null ? "-" : `${(row.evidence_overlap * 100).toFixed(1)}%` },
    { key: "omissions", header: t("evidence.contextSelection.column.omissions"), render: (row) => row.omissions.length ? row.omissions.join(", ") : "-" },
    { key: "pinned", header: t("evidence.contextSelection.column.pinned"), render: (row) => <StatusPill kind={row.pinned_preserved ? "success" : "danger"} label={t(row.pinned_preserved ? "evidence.status.preserved" : "evidence.status.missing")} /> },
    { key: "latency", header: t("evidence.contextSelection.column.latency"), render: (row) => `${row.latency_ms.toFixed(1)} ms`, cellClass: "num" },
    { key: "failure", header: t("evidence.contextSelection.column.invariantResult"), render: (row) => row.failure_reason ? <StatusPill kind="danger" label={row.failure_reason} /> : <StatusPill kind="success" label={t("evidence.status.passed")} /> },
    { key: "recorded", header: t("evidence.contextSelection.column.recorded"), render: (row) => formatConsoleTimestamp(row.created_at) },
  ];
  return (
    <div class="stack">
      <div class="governance-readonly-banner">
        <strong>{t("evidence.contextSelection.bannerTitle")}</strong>
        <span>{t("evidence.contextSelection.bannerBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={comparisonsHref} label={t("evidence.contextSelection.comparisons")} value={data.count} />
        <KpiCard href={comparisonsHref} label={t("evidence.contextSelection.invariantFailures")} value={data.invariant_failures} tone={data.invariant_failures ? "warning" : "positive"} />
        <KpiCard
          evidenceState={data.count === 0 ? "insufficient-sample" : "measured"}
          href={comparisonsHref}
          label={t("evidence.contextSelection.column.pinned")}
          value={data.count === 0 ? kpiEvidenceLabel("insufficient-sample") : `${pinnedPreservedCount} / ${data.count}`}
        />
        <KpiCard
          evidenceState={averageLatencyMs === null ? "not-measured" : "measured"}
          href={comparisonsHref}
          label={t("evidence.contextSelection.column.latency")}
          value={averageLatencyMs === null ? kpiEvidenceLabel("not-measured") : `${averageLatencyMs.toFixed(1)} ms`}
        />
      </KpiGrid>
      <div class="cs-filter-toolbar" role="search">
        <label class="is-wide">
          <span>{t("evidence.contextSelection.column.candidate")}</span>
          <input
            type="search"
            value={query}
            placeholder={getLocale() === "ko" ? "평가 ID, 기준 정책, 후보 정책, 누락 항목..." : "evaluation, baseline, candidate, omission..."}
            onInput={(event) => setQuery(event.currentTarget.value)}
          />
        </label>
        <label>
          <span>{t("evidence.contextSelection.column.invariantResult")}</span>
          <select value={resultFilter} onChange={(event) => setResultFilter(event.currentTarget.value as "all" | "passed" | "failed")}>
            <option value="all">{getLocale() === "ko" ? "전체" : "All"}</option>
            <option value="passed">{t("evidence.status.passed")}</option>
            <option value="failed">{t("evidence.status.failed")}</option>
          </select>
        </label>
        <span class="cs-filter-count" role="status" aria-live="polite">
          {filtered.length} / {data.comparisons.length}
        </span>
      </div>
      <div id="context-selection-comparisons" class={`cs-workspace-split${selected ? " has-selection" : ""}`}>
        <div class="cs-workspace-main">
          <DataTable
            columns={columns}
            rows={filtered}
            keyOf={(row) => row.evaluation_id}
            onRowClick={(row) => setSelectedId(row.evaluation_id)}
            isRowActive={(row) => row.evaluation_id === selected?.evaluation_id}
            rowActionLabel={(row) => `${t("evidence.contextSelection.column.candidate")}: ${row.evaluation_id}`}
            rowActionControls="context-comparison-detail"
            scrollRegionLabel={t("route.contextSelectionComparisons")}
            empty={t("evidence.contextSelection.empty")}
          />
        </div>
        {selected ? (
          <aside id="context-comparison-detail" class="cs-inspector-pane" aria-label={selected.evaluation_id}>
            <header class="cs-inspector-head">
              <div>
                <span class="cs-inspector-kicker">{selected.evaluation_id}</span>
                <h3>{selected.candidate_policy_ref}</h3>
                <p>{getLocale() === "ko" ? "기준 정책" : "Baseline"}: {selected.baseline_policy_ref}</p>
              </div>
              {selected.failure_reason ? (
                <StatusPill kind="danger" label={selected.failure_reason} />
              ) : (
                <StatusPill kind="success" label={t("evidence.status.passed")} />
              )}
            </header>
            <dl class="cs-facts-grid">
              <div><dt>{t("evidence.contextSelection.column.tokens")}</dt><dd>{selected.baseline_tokens} {"->"} {selected.candidate_tokens ?? "-"}</dd></div>
              <div><dt>{t("evidence.contextSelection.column.overlap")}</dt><dd>{selected.evidence_overlap === null ? "-" : `${(selected.evidence_overlap * 100).toFixed(1)}%`}</dd></div>
              <div><dt>{t("evidence.contextSelection.column.pinned")}</dt><dd>{t(selected.pinned_preserved ? "evidence.status.preserved" : "evidence.status.missing")}</dd></div>
              <div><dt>{t("evidence.contextSelection.column.latency")}</dt><dd>{`${selected.latency_ms.toFixed(1)} ms`}</dd></div>
              <div><dt>{t("evidence.contextSelection.column.recorded")}</dt><dd>{formatConsoleTimestamp(selected.created_at)}</dd></div>
              <div><dt>{t("evidence.contextSelection.column.omissions")}</dt><dd>{selected.omissions.length ? selected.omissions.join(", ") : t("evidence.common.none")}</dd></div>
            </dl>
          </aside>
        ) : null}
      </div>
    </div>
  );
}
