import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { AsyncBoundary, EmptyState, PageHeader, type AsyncState } from "../components/ui";
import { SearchableSelect, type SearchableSelectOption } from "../components/searchable-select";
import { RecordedStateFacts } from "../components/recorded-state-facts";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import { currentRoute, routeHref } from "../router";
import { DashboardResourceMap } from "./dashboard-v2-map";
import {
  dashboardCounts, dashboardMapColumns, dashboardResourceState, dashboardScope, dashboardStatusFilter, dashboardTypeKeywords, dashboardTypeLabel, dashboardUnknownReason,
  EMPTY_DASHBOARD_FILTERS, STATE_STYLE, dashboardStateFact,
  type DashboardFilters, type DashboardLens, type DashboardResource, type DashboardSnapshot, type DashboardState, type DashboardView,
} from "./dashboard-v2.model";
import { date, number, t } from "./i18n/dashboard-v2";
import { loadDashboardRecordedStates } from "./dashboard-v2.loading";
import "./dashboard-v2.css";

/** Additive read-only resource view; refresh replaces the entire projection, never merges generations. */
export default function DashboardV2Route({ client }: { readonly client: OperatorApiClient }) {
  const [state, setState] = useState<AsyncState<DashboardSnapshot>>({ status: "loading" });
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    void loadDashboardRecordedStates(client, () => cancelled).then((snapshot) => {
      if (!cancelled && snapshot) setState({ status: "ready", data: snapshot });
    }).catch((error: unknown) => {
      if (!cancelled) setState(isOptionalOperatorApiUnavailable(error)
        ? { status: "unavailable", message: t("unavailable") }
        : { status: "error", message: error instanceof Error ? error.message : String(error) });
    });
    return () => { cancelled = true; };
  }, [client, revision]);
  return <div class="stack dashboard-v2-page">
    <PageHeader title={t("title")} subtitle={t("subtitle")} actions={<>
      <a class="cs-control-button" href={routeHref("dashboard")}>{t("original")}</a>
      <button type="button" class="cs-control-button" onClick={() => setRevision((value) => value + 1)} disabled={state.status === "loading"}>{t("refresh")}</button>
    </>} />
    {state.status !== "ready" && <DashboardPendingContext status={state.status} />}
    <AsyncBoundary state={state} resourceLabel={t("title")}>
      {(snapshot) => <DashboardBody key={revision} snapshot={snapshot} />}
    </AsyncBoundary>
  </div>;
}

function DashboardPendingContext({ status }: { readonly status: string }) {
  usePublishViewContext(() => ({
    routeId: "dashboard-v2", routeLabel: t("title"), purpose: t("subtitle"),
    headline: t(status === "loading" ? "loading" : "unavailable"),
    capturedAt: new Date().toISOString(), glossary: composeGlossary([TERMS.resource]),
    facts: [{ key: "inventory_state", value: status }, { key: "execution_authority", value: false }],
    records: {},
  }), [status]);
  return null;
}

function stateText(key: DashboardState): string { return t(`state.${key}`); }

function StateBadge({ value, text }: { readonly value: DashboardState; readonly text?: string | null | undefined }) {
  const style = STATE_STYLE[value];
  return <span class="dv2-state" data-tone={style.tone}>{style.symbol} {text ?? stateText(value)}</span>;
}

function resourceHref(resource?: DashboardResource): string {
  return routeHref("ontology", { params: { view: "instances", instance: resource?.id } });
}

function DashboardBody({ snapshot }: { readonly snapshot: DashboardSnapshot }) {
  const [filters, setFilters] = useState<DashboardFilters>(() => ({ ...EMPTY_DASHBOARD_FILTERS, status: dashboardStatusFilter(currentRoute().search.get("state")) }));
  const [lens, setLens] = useState<DashboardLens>(() => currentRoute().search.get("lens") === "provisioning" ? "provisioning" : "operation");
  const [view, setView] = useState<DashboardView>("honeycomb");
  const [density, setDensity] = useState<"dense" | "comfortable">(snapshot.resources.length > 48 ? "dense" : "comfortable");
  const [width, setWidth] = useState(0);
  const [touch, setTouch] = useState(false);
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const panel = panelRef.current;
    if (panel === null) return;
    const media = matchMedia("(max-width: 700px), (pointer: coarse)");
    const measure = () => {
      const style = getComputedStyle(panel);
      setWidth(panel.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight));
      setTouch(media.matches);
    };
    const observer = new ResizeObserver(measure);
    observer.observe(panel);
    media.addEventListener("change", measure);
    measure();
    return () => { observer.disconnect(); media.removeEventListener("change", measure); };
  }, []);
  const effectiveDensity = touch ? "comfortable" : density;
  const columns = dashboardMapColumns(width, effectiveDensity);
  const scoped = useMemo(() => dashboardScope(snapshot.resources, filters), [snapshot, filters]);
  const matches = useMemo(() => scoped.filter((resource) => {
    const state = dashboardResourceState(resource, snapshot, lens);
    return !filters.status || (filters.status === "known" ? state !== "unknown" && state !== "not-applicable" : state === filters.status);
  }), [scoped, filters.status, snapshot, lens]);
  const counts = useMemo(() => dashboardCounts(scoped, snapshot, lens), [scoped, snapshot, lens]);
  const groups = useMemo(() => {
    const result = new Map<string, { label: string; items: DashboardResource[] }>();
    for (const resource of matches) {
      const key = resource.group ?? "";
      const entry = result.get(key) ?? { label: resource.groupLabel ?? t("missing"), items: [] };
      entry.items.push(resource);
      result.set(key, entry);
    }
    return [...result.entries()];
  }, [matches]);
  const total = view === "groups" ? groups.length : matches.length;
  const limit = view === "groups" ? 6 : view === "honeycomb" && effectiveDensity === "dense" ? columns * 14 : 48;
  const pages = Math.max(1, Math.ceil(total / limit));
  const currentPage = Math.min(page, pages - 1);
  const displayed = useMemo(() => view === "groups" ? [] : matches.slice(currentPage * limit, (currentPage + 1) * limit), [view, matches, currentPage, limit]);
  const selected = snapshot.resources.find((resource) => resource.id === selectedId) ?? null;
  const unknownReason = selected ? dashboardUnknownReason(selected, snapshot) : null;
  const update = <K extends keyof DashboardFilters>(key: K, value: DashboardFilters[K]) => {
    setFilters((current) => ({ ...current, [key]: value, ...(key === "subscription" ? { group: "" } : {}) }));
    setPage(0);
  };
  const types = useMemo(() => {
    const available = dashboardScope(snapshot.resources, filters, false);
    const result = new Map<string, SearchableSelectOption>();
    for (const resource of available) {
      const previous = result.get(resource.type);
      result.set(resource.type, { value: resource.type, label: dashboardTypeLabel(resource), description: resource.type, keywords: dashboardTypeKeywords(resource.type), count: (previous?.count ?? 0) + 1 });
    }
    if (filters.type && !result.has(filters.type)) {
      const original = snapshot.resources.find((resource) => resource.type === filters.type);
      result.set(filters.type, { value: filters.type, label: original ? dashboardTypeLabel(original) : filters.type, description: filters.type, keywords: dashboardTypeKeywords(filters.type), count: 0 });
    }
    return [{ value: "", label: t("allTypes"), count: available.length }, ...result.values()];
  }, [snapshot, filters]);
  const operations = dashboardCounts(snapshot.resources, snapshot, "operation");
  const known = snapshot.resources.length - (operations.get("unknown") ?? 0) - (operations.get("not-applicable") ?? 0);
  const provisioningRecorded = snapshot.resources.filter((resource) => resource.states?.provisioning.value != null).length;
  const highlights = snapshot.resources.filter((resource) => ["unknown", "transitioning"].includes(dashboardResourceState(resource, snapshot, "operation"))).slice(0, 3);
  const options = (axis: "subscription" | "group") => [...new Map(snapshot.resources
    .filter((resource) => axis !== "group" || !filters.subscription || resource.subscription === filters.subscription)
    .filter((resource) => resource[axis] !== null)
    .map((resource) => [resource[axis]!, (axis === "group" ? resource.groupLabel : resource.subscriptionLabel) ?? resource[axis]!])).entries()];
  usePublishViewContext(() => ({
    routeId: "dashboard-v2", routeLabel: t("title"), purpose: t("subtitle"), headline: t("boundary"),
    capturedAt: new Date().toISOString(),
    glossary: composeGlossary([TERMS.resource]),
    facts: [
      { key: "received_resources", value: snapshot.resources.length, observedAt: snapshot.at },
      { key: "matched_resources", value: matches.length },
      { key: "inventory_truncated", value: snapshot.truncated },
      { key: "snapshot_freshness", value: snapshot.freshness },
      { key: "query_total", value: snapshot.totalCount ?? null },
      { key: "recorded_availability_count", value: snapshot.resources.filter((resource) => resource.states?.availability.value != null).length },
      { key: "execution_authority", value: false },
    ],
    records: { selected_resource: selected ? [{ id: selected.id, name: selected.name, type: selected.type, reported_status: selected.status, recorded_states: selected.states ?? null, snapshot_id: snapshot.id }] : [] },
  }), [snapshot, matches.length, selected]);
  return <>
    <section class="dv2-scope">
      <div><strong>{t("scope")}</strong><p>{snapshot.recordedStates ? t("ontologyScope") : snapshot.scope ?? t("missing")}</p><p>{t("boundary")}</p></div>
      <div><strong>{t("snapshotAt")}</strong><p>{date(snapshot.at)}</p>{!snapshot.recordedStates && <StateBadge value={snapshot.freshness} />}</div>
    </section>
    {(snapshot.truncated || snapshot.limitations.length > 0) && <p class="dv2-notice" role="status">{t("partial")}</p>}
    {!snapshot.recordedStates && (snapshot.observationKind !== "OBSERVED" || !snapshot.id || !snapshot.source) && <p class="dv2-notice">{t("unverified")}</p>}
    {snapshot.freshness === "stale" && <p class="dv2-notice">{t("stale")}</p>}
    <div class="dv2-summary">
      {([
        ["received", snapshot.resources.length, ""],
        ["known", known, "known"],
        ["unknown", operations.get("unknown") ?? 0, "unknown"],
        ["provisioningRecorded", provisioningRecorded, "known"],
      ] as const).map(([label, value, status]) =>
        <a href={routeHref("dashboard-v2", { params: { state: status, lens: label === "provisioningRecorded" ? "provisioning" : null } })} key={label} onClick={(event) => {
          if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
          event.preventDefault();
          setFilters({ ...EMPTY_DASHBOARD_FILTERS, status }); setLens(label === "provisioningRecorded" ? "provisioning" : "operation"); setView("list"); setPage(0);
        }}><strong>{number(value)}</strong><span>{t(label)}</span></a>)}
    </div>
    <div class="dv2-workspace">
      <section class="dv2-resource-panel" ref={panelRef}>
        <header class="dv2-panel-head"><div><h3>{t("landscape")}</h3><p>{t("mapHelp")}</p></div>
          <div class="dv2-controls" role="group" aria-label={t("landscape")}>{(["honeycomb", "list", "groups"] as const).map((key) =>
            <button type="button" class="cs-control-button" key={key} aria-pressed={view === key} onClick={() => { setView(key); setPage(0); }}>{t(key)}</button>)}</div></header>
        <div class="dv2-lenses"><div class="dv2-controls" role="group" aria-label={t("observation")}>
          {(["operation", "provisioning", "availability", "observation"] as const).map((key) => <button type="button" class="cs-control-button" key={key} aria-pressed={lens === key} onClick={() => { setLens(key); update("status", ""); }}>{t(key)}</button>)}
        </div>{view === "honeycomb" && <div class="dv2-controls" role="group" aria-label={t("dense")}>{(["dense", "comfortable"] as const).map((key) =>
          <button type="button" class="cs-control-button" key={key} aria-pressed={effectiveDensity === key} disabled={key === "dense" && touch} onClick={() => { setDensity(key); setPage(0); }}>{t(key)}</button>)}</div>}</div>
        <div class="dv2-filters">
          <label>{t("subscription")}<select class="cs-control-select" value={filters.subscription} onChange={(event) => update("subscription", event.currentTarget.value)}><option value="">{t("allSubscriptions")}</option>{options("subscription").map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label>{t("group")}<select class="cs-control-select" value={filters.group === null ? "missing" : `group:${filters.group}`} onChange={(event) => update("group", event.currentTarget.value === "missing" ? null : event.currentTarget.value.slice(6))}><option value="group:">{t("allGroups")}</option><option value="missing">{t("missing")}</option>{options("group").map(([value, label]) => <option key={value} value={`group:${value}`}>{label}</option>)}</select></label>
          <SearchableSelect label={t("type")} value={filters.type} options={types} onChange={(value) => update("type", value)} placeholder={t("typePlaceholder")} emptyLabel={t("typeEmpty")} helpText={t("typeHelp")} resultsLabel={(shown, total) => t("typeResults", { shown, total })} />
          <label>{t("find")}<input type="search" class="cs-control-input" value={filters.query} maxLength={256} placeholder={t("searchPlaceholder")} onInput={(event) => update("query", event.currentTarget.value)} /></label>
        </div>
        <div class="dv2-meta"><span role="status">{view === "groups" ? t("groupShown", { shown: Math.min(6, Math.max(0, groups.length - currentPage * 6)), matches: number(matches.length) }) : t("shown", { shown: number(displayed.length), matches: number(matches.length), received: number(snapshot.resources.length) })}</span><button type="button" class="cs-control-button is-quiet" onClick={() => { setFilters(EMPTY_DASHBOARD_FILTERS); setPage(0); }}>{t("clear")}</button></div>
        <div class="dv2-legend" role="group" aria-label={t("allStates")}><button type="button" class="cs-control-button" aria-pressed={!filters.status} onClick={() => update("status", "")}>{t("allStates")} {number(scoped.length)}</button>
          {[...counts].map(([key, count]) => <button type="button" class="cs-control-button" key={key} aria-pressed={filters.status === key} onClick={() => update("status", key)}><StateBadge value={key} /> {number(count)}</button>)}</div>
        {matches.length === 0 ? <EmptyState title={t("empty")} body={t("emptyBody")} /> : view === "honeycomb"
          ? <DashboardResourceMap resources={displayed} snapshot={snapshot} lens={lens} density={effectiveDensity} columns={columns} selectedId={selectedId} onSelect={setSelectedId} labels={{ operation: t("operation"), provisioning: t("provisioning"), availability: t("availability"), observation: t("observation"), observedAt: t("observedAt"), snapshotAt: t("snapshotAt"), missing: t("missing"), state: stateText }} />
          : view === "list" ? <div class="dv2-table-wrap"><table><thead><tr><th>{t("find")}</th><th>{t("type")}</th><th>{t(lens)}</th><th>{t("group")}</th></tr></thead><tbody>{displayed.map((resource) =>
            <tr key={resource.id}><td><button type="button" class="dv2-link" aria-pressed={selectedId === resource.id} onClick={() => setSelectedId(resource.id)}>{resource.name}</button></td><td>{resource.type}</td><td><StateBadge value={dashboardResourceState(resource, snapshot, lens)} text={lens === "observation" ? null : dashboardStateFact(resource, lens)?.value} /></td><td>{resource.groupLabel ?? t("missing")}</td></tr>)}</tbody></table></div>
          : <div class="dv2-groups">{groups.slice(currentPage * 6, (currentPage + 1) * 6).map(([key, group]) =>
            <section key={key}><button type="button" class="dv2-link" onClick={() => { update("group", key || null); setView("honeycomb"); }}>{group.label} / {number(group.items.length)}</button><div>{[...dashboardCounts(group.items, snapshot, lens)].map(([key, count]) => <span key={key}><StateBadge value={key} /> {number(count)}</span>)}</div></section>)}</div>}
        {pages > 1 && <nav class="dv2-pagination" aria-label={t("page", { page: currentPage + 1, pages })}><button type="button" class="cs-control-button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{t("previous")}</button><span>{t("page", { page: currentPage + 1, pages })}</span><button type="button" class="cs-control-button" disabled={currentPage + 1 >= pages} onClick={() => setPage(currentPage + 1)}>{t("next")}</button></nav>}
        <p class="dv2-note">{t(lens === "operation" ? "operationHelp" : lens === "provisioning" ? "provisioningHelp" : lens === "availability" ? "availabilityHelp" : "observationHelp")}</p>
        <p class="dv2-note">{t("pageBoundary")}</p>
      </section>
      <aside class={`dv2-side${selected ? " has-selection" : ""}`}>
        {selected ? <section class="dv2-inspector" aria-label={t("selected")}>
          <header><h3>{selected.name}</h3><button type="button" class="cs-control-button" onClick={() => setSelectedId(null)}>{t("clearSelection")}</button></header>
          <p>{selected.type}</p><p class="dv2-note">{selected.subscriptionLabel ?? t("missing")} / {selected.groupLabel ?? t("missing")}</p>
          {(view === "groups" || !displayed.some((resource) => resource.id === selected.id)) && <p class="dv2-notice">{t("outside")}</p>}
          {selected.states && <RecordedStateFacts states={selected.states} />}
          {!selected.states && <dl>{(["operation", "availability", "observation"] as const).map((key) => <div><dt>{t(key)}</dt><dd><StateBadge value={dashboardResourceState(selected, snapshot, key)} /></dd></div>)}
            <div><dt>{t("reported")}</dt><dd>{selected.status || t("missing")}</dd></div><div><dt>{t("observedAt")}</dt><dd>{date(selected.observedAt)}</dd></div></dl>}
          {unknownReason && <p class="dv2-note">{t(unknownReason)}</p>}
          <a href={resourceHref(selected)}>{t("inspectOntology")}</a>
          <details><summary>{t("evidence")}</summary><pre>{JSON.stringify({ snapshot_id: snapshot.id, snapshot_at: snapshot.at, source: snapshot.source, observation_kind: snapshot.observationKind, resource: selected, execution_authority: false }, null, 2)}</pre></details>
        </section> : <section class="dv2-attention"><h3>{t("checkFirst")}</h3><p class="dv2-note">{t("checkHelp")}</p>
          {highlights.length === 0 ? <p>{t("noHighlights")}</p> : highlights.map((resource) => <div key={resource.id}><StateBadge value={dashboardResourceState(resource, snapshot, "operation")} /><button type="button" class="dv2-link" onClick={() => setSelectedId(resource.id)}>{resource.name}</button><p class="dv2-note">{resource.type}</p></div>)}
          <a href={resourceHref()}>{t("browseOntology")}</a></section>}
      </aside>
    </div>
    <span class="sr-only" role="status">{selected ? t("pinned", { name: selected.name }) : ""}</span>
    <section class="dv2-coverage"><h3>{t("coverage")}</h3><dl>
      <div><dt>{t("inventoryCoverage")}</dt><dd>{t(snapshot.truncated || snapshot.limitations.length ? "partialProjection" : "completeProjection")}<p>{snapshot.recordedStates ? t("queryTotal", { total: number(snapshot.totalCount ?? snapshot.resources.length) }) : t("excluded", { count: snapshot.excludedContainers })}</p><p>{snapshot.recordedStates ? t("operationalOnly") : t("excludedAuthorization", { count: snapshot.excludedAuthorization })}</p></dd></div>
      <div><dt>{t("source")}</dt><dd>{snapshot.source ?? t("missing")}<p>{snapshot.id ?? t("missing")}</p></dd></div>
      <div><dt>{t("availabilityCoverage")}</dt><dd>{t("availabilityHelp")}</dd></div>
      <div><dt>{t("historyCoverage")}</dt><dd>{t("historyUnavailable")} <a href={resourceHref(selected ?? undefined)}>{t("inspectOntology")}</a></dd></div>
    </dl>{snapshot.pendingChanges !== null && <p>{t("pending", { count: snapshot.pendingChanges })}</p>}
      {snapshot.limitations.length > 0 && <details><summary>{t("evidence")}</summary><ul>{snapshot.limitations.map((reason) => <li key={reason}>{reason}</li>)}</ul></details>}
      <p class="dv2-note">{t("readOnly")}</p>
    </section>
  </>;
}
