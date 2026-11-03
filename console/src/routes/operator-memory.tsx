import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { AsyncBoundary, DataTable, KpiCard, KpiGrid, PageHeader, StatusPill, type AsyncState, type Column } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import { t } from "../i18n";
import { formatConsoleTimestamp } from "../time-format";
import {
  decodeOperatorMemory, nextOperatorMemoryExpiryDelay, operatorMemoryDisplayState,
  operatorMemoryFilterHref, operatorMemoryFiltersEqual, operatorMemoryQuery, parseOperatorMemoryFilters,
  type MemoryCompactionReviewItem, type OperatorMemoryFilters, type OperatorMemoryReviewItem, type OperatorMemoryReviewView,
} from "./operator-memory.model";
import { memoryScopeLabel, memoryStateLabel, memoryUxText } from "./operator-memory.i18n";

const EMPTY_FILTERS: OperatorMemoryFilters = { scopeKind: "", scopeRef: "" };
const readFilters = () => parseOperatorMemoryFilters(new URLSearchParams(window.location.search));

export function OperatorMemoryRoute({ client }: { readonly client: OperatorApiClient }) {
  const [initial] = useState(readFilters);
  const [filters, setFilters] = useState<OperatorMemoryFilters>(initial);
  const [applied, setApplied] = useState<OperatorMemoryFilters>(initial);
  const [state, setState] = useState<AsyncState<OperatorMemoryReviewView>>({ status: "loading" });
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const generation = useRef(0);

  const load = async (next: OperatorMemoryFilters, refresh = false): Promise<void> => {
    const request = ++generation.current;
    if (refresh) setRefreshing(true);
    else setState({ status: "loading" });
    try {
      const payload = await client.panel<unknown>("/operator-memory", operatorMemoryQuery(next));
      if (request === generation.current) {
        setState({ status: "ready", data: decodeOperatorMemory(payload) });
        setCheckedAt(new Date().toISOString());
      }
    } catch (error) {
      if (request === generation.current) {
        setState(isOptionalOperatorApiUnavailable(error)
          ? { status: "unavailable", message: t("settings.operatorMemory.unavailable") }
          : { status: "error", message: error instanceof Error ? error.message : String(error) });
      }
    } finally {
      if (request === generation.current) setRefreshing(false);
    }
  };
  const applyFilters = (next: OperatorMemoryFilters) => {
    const normalized = { ...next, scopeRef: next.scopeRef.trim() };
    setFilters(normalized);
    setApplied(normalized);
    const href = operatorMemoryFilterHref(window.location.href, normalized);
    if (href !== `${window.location.pathname}${window.location.search}${window.location.hash}`) {
      window.history.pushState(window.history.state, "", href);
    }
    void load(normalized);
  };
  useEffect(() => {
    const next = readFilters();
    setFilters(next);
    setApplied(next);
    void load(next);
    const onPopState = () => {
      if (window.location.pathname !== "/settings/memory") return;
      const restored = readFilters();
      setFilters(restored);
      setApplied(restored);
      void load(restored);
    };
    window.addEventListener("popstate", onPopState);
    return () => { generation.current += 1; window.removeEventListener("popstate", onPopState); };
  }, [client]);

  const loading = state.status === "loading" || refreshing;
  return <div class="stack settings-route operator-memory-route">
    <PageHeader title={t("route.operatorMemory")} subtitle={t("settings.operatorMemory.subtitle")} />
    {initial.invalid ? <p role="note">{memoryUxText("invalidFilters")}</p> : null}
    <form class="settings-filter-bar" onSubmit={(event) => { event.preventDefault(); applyFilters(filters); }}>
      <label><span>{t("settings.operatorMemory.scopeKind")}</span>
        <select class="form-input" value={filters.scopeKind}
          onChange={(event) => setFilters({ ...filters, scopeKind: event.currentTarget.value as OperatorMemoryFilters["scopeKind"] })}>
          <option value="">{t("settings.operatorMemory.allScopes")}</option>
          <option value="resource-group">{memoryScopeLabel("resource-group")}</option>
          <option value="resource">{memoryScopeLabel("resource")}</option>
        </select>
      </label>
      <label><span>{t("settings.operatorMemory.scopeRef")}</span>
        <input class="form-input" maxLength={256} value={filters.scopeRef}
          onInput={(event) => setFilters({ ...filters, scopeRef: event.currentTarget.value })} />
      </label>
      <button type="submit" class="btn" disabled={loading}>{t("settings.operatorMemory.filter")}</button>
      <button type="button" class="btn secondary" disabled={loading || (operatorMemoryFiltersEqual(filters, EMPTY_FILTERS)
        && operatorMemoryFiltersEqual(applied, EMPTY_FILTERS))}
        onClick={() => applyFilters(EMPTY_FILTERS)}>{memoryUxText("clear")}</button>
      <button type="button" class="btn secondary" aria-busy={loading} disabled={loading}
        onClick={() => void load(applied, state.status === "ready")}>
        {memoryUxText(state.status === "error" || state.status === "unavailable" ? "retry" : "refresh")}
      </button>
    </form>
    <div class="settings-filter-summary" aria-live="polite">
      <p>{memoryUxText("applied", { scope: `${memoryScopeLabel(applied.scopeKind)}${applied.scopeRef ? `: ${applied.scopeRef}` : ""}` })}</p>
      {!operatorMemoryFiltersEqual(filters, applied) ? <p>{memoryUxText("pending")}</p> : null}
      <small>{checkedAt ? memoryUxText("lastChecked", { time: formatConsoleTimestamp(checkedAt) }) : memoryUxText("neverChecked")}</small>
    </div>
    <AsyncBoundary state={state} resourceLabel={t("settings.operatorMemory.resourceLabel")}>
      {(view) => <OperatorMemoryBody view={view} applied={applied} checkedAt={checkedAt} />}
    </AsyncBoundary>
  </div>;
}

function OperatorMemoryBody({ view, applied, checkedAt }: {
  readonly view: OperatorMemoryReviewView; readonly applied: OperatorMemoryFilters; readonly checkedAt: string | null;
}) {
  const [now, setNow] = useState(Date.now);
  usePublishViewContext(() => ({
    routeId: "settings-memory", routeLabel: t("route.operatorMemory"),
    purpose: t("settings.operatorMemory.subtitle"), glossary: composeGlossary([TERMS.userPreference]),
    headline: memoryUxText("count", { entries: view.items.length, compactions: view.compactions.length }),
    capturedAt: checkedAt ?? new Date().toISOString(),
    facts: [
      { key: "entry_count", value: view.items.length, group: "memory" },
      { key: "compaction_count", value: view.compactions.length, group: "memory" },
      { key: "requested_entry_limit", value: 100, group: "memory" },
      { key: "scope_kind", value: applied.scopeKind, group: "memory" },
      { key: "scope_ref", value: applied.scopeRef, group: "memory" },
    ],
    records: { entries: view.items.slice(0, 25).map((item) => ({
      id: item.id, category: item.category, scope_kind: item.scopeKind, scope_ref: item.scopeRef,
      state: operatorMemoryDisplayState(item, now),
    })) },
  }), [now, view, applied, checkedAt]);
  useEffect(() => {
    const delay = nextOperatorMemoryExpiryDelay(view.items, now);
    if (delay === null) return undefined;
    const timer = window.setTimeout(() => setNow(Date.now()), delay);
    return () => window.clearTimeout(timer);
  }, [now, view.items]);
  return <div class="stack">
    <KpiGrid>
      <KpiCard href="#memory-compactions" label={t("settings.operatorMemory.compactions")} value={view.compactions.length} />
      <KpiCard href="#memory-entries" label={t("settings.operatorMemory.entries")} value={view.items.length} />
    </KpiGrid>
    <p role="status">{memoryUxText("count", { entries: view.items.length, compactions: view.compactions.length })}</p>
    <p class="muted">{memoryUxText("coverage")}</p>
    <section id="memory-compactions" class="stack-section settings-section">
      <h3>{t("settings.operatorMemory.compactions")}</h3>
      <DataTable columns={compactionColumns()} rows={view.compactions}
        keyOf={(item) => item.candidateId} empty={t("settings.operatorMemory.noCompactions")} />
    </section>
    <section id="memory-entries" class="stack-section settings-section">
      <h3>{t("settings.operatorMemory.entries")}</h3>
      <DataTable columns={columns(now, new Set(view.items.map((item) => item.id)))} rows={view.items}
        keyOf={(item) => item.id} empty={t("settings.operatorMemory.empty")} />
    </section>
  </div>;
}

function Reference({ value }: { readonly value: string }) {
  const [notice, setNotice] = useState<string | null>(null);
  return <span class="settings-memory-reference"><code>{value}</code>
    <button type="button" class="btn subtle" aria-label={`${memoryUxText("copy")}: ${value}`}
      onClick={async () => {
        try { await navigator.clipboard.writeText(value); setNotice(memoryUxText("copied")); }
        catch { setNotice(memoryUxText("copyFailed")); }
      }}>{memoryUxText("copy")}</button>
    {notice ? <small role="status">{notice}</small> : null}
  </span>;
}

function Timestamp({ value }: { readonly value: string | null }) {
  return value !== null && Number.isFinite(Date.parse(value))
    ? <time dateTime={value}>{formatConsoleTimestamp(value)}</time>
    : <span>{memoryUxText("unavailable")}</span>;
}

function compactionColumns(): readonly Column<MemoryCompactionReviewItem>[] {
  return [
    { key: "candidate", header: t("settings.operatorMemory.candidate"), render: (item) => <div>
      <strong>{item.category}</strong><small>{item.body.slice(0, 120)}{item.body.length > 120 ? "..." : ""}</small>
      <details class="settings-memory-details"><summary>{memoryUxText("details")}</summary>
        <dl><dt>{memoryUxText("id")}</dt><dd><Reference value={item.candidateId} /></dd>
          <dt>{memoryUxText("body")}</dt><dd>{item.body}</dd>
          <dt>{memoryUxText("sources")}</dt><dd><ul>{item.sourceRefs.map((ref, index) =>
            <li key={`${ref}-${index}`}><Reference value={ref} /></li>)}</ul></dd>
          <dt>{memoryUxText("reviewReason")}</dt><dd>{item.reviewReason?.trim()
            || memoryUxText(item.reviewedBy === null ? "noReview" : "noReason")}</dd>
        </dl>
      </details>
    </div> },
    { key: "scope", header: t("settings.operatorMemory.scope"), render: (item) =>
      <span><strong>{memoryScopeLabel(item.scopeKind)}</strong><small>{item.scopeRef}</small></span> },
    { key: "sources", header: t("settings.operatorMemory.sources"), render: (item) => item.sourceRefs.length },
    { key: "review", header: t("settings.operatorMemory.review"), render: (item) =>
      <span><strong>{item.proposedByAgent}</strong><small>{item.reviewedBy ?? memoryUxText("noReview")}</small></span> },
    { key: "state", header: t("settings.operatorMemory.state"), render: (item) =>
      <StatusPill kind="neutral" label={memoryStateLabel(item.state)} /> },
  ];
}

function columns(now: number, loadedIds: ReadonlySet<string>): readonly Column<OperatorMemoryReviewItem>[] {
  return [
    { key: "memory", header: t("settings.operatorMemory.memory"), render: (item) =>
      <div id={`memory-${encodeURIComponent(item.id)}`}>
        <strong>{item.category}</strong><small>{item.body.slice(0, 120)}{item.body.length > 120 ? "..." : ""}</small>
        <details class="settings-memory-details"><summary>{memoryUxText("details")}</summary>
          <dl><dt>{memoryUxText("id")}</dt><dd><Reference value={item.id} /></dd>
            <dt>{memoryUxText("body")}</dt><dd>{item.body}</dd>
            <dt>{memoryUxText("sources")}</dt><dd><Reference value={item.sourceRef} /><code>{item.sourceEvent}</code></dd>
            <dt>{memoryUxText("created")}</dt><dd><Timestamp value={item.createdAt} /></dd>
            <dt>{memoryUxText("expires")}</dt><dd>{item.expiresAt === null ? memoryUxText("noExpiry") : <Timestamp value={item.expiresAt} />}</dd>
            <dt>{memoryUxText("replacement")}</dt><dd>{item.supersededBy
              ? <><Reference value={item.supersededBy} />{loadedIds.has(item.supersededBy)
                ? <a href={`#memory-${encodeURIComponent(item.supersededBy)}`}>{item.supersededBy}</a> : null}</>
              : memoryUxText("noReplacement")}</dd>
          </dl>
        </details>
      </div> },
    { key: "scope", header: t("settings.operatorMemory.scope"), render: (item) =>
      <span><strong>{memoryScopeLabel(item.scopeKind)}</strong><small>{item.scopeRef}</small></span> },
    { key: "provenance", header: t("settings.operatorMemory.provenance"), render: (item) =>
      <span><strong>{item.sourceEvent}</strong><small>{item.sourceRef}</small></span> },
    { key: "approval", header: t("settings.operatorMemory.approval"), render: (item) =>
      <span><strong>{item.author}</strong><small>{item.approvedBy}</small></span> },
    { key: "state", header: t("settings.operatorMemory.state"), render: (item) => {
      const state = operatorMemoryDisplayState(item, now);
      return <StatusPill kind={state === "active" ? "success" : state === "expired" ? "warning" : "neutral"}
        label={memoryStateLabel(state)} />;
    } },
  ];
}
