import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  CopyButton,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  UnavailableState,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import {
  currentRoute,
  navigate,
  replaceRouteState,
  ROUTE_STATE_EVENT,
  routeHref,
} from "../router";
import {
  CAPABILITY_PAGE_SIZE,
  capabilityRoleMatch,
  capabilityRouteStateFromSearch,
  decodeCapabilities,
  isMutatingCapability,
  sortCapabilities,
  type Capability,
  type CapabilityResponse,
  type CapabilityRoleMatch,
  type CapabilitySort,
} from "./capabilities.model";
import { CapabilityDetail } from "./capabilities.detail";
import { t } from "./i18n/capabilities";
import type { IamOverview } from "./settings-iam.model";

export async function loadCapabilitiesState(
  client: Pick<OperatorApiClient, "panel">,
): Promise<AsyncState<CapabilityResponse>> {
  try {
    return {
      status: "ready",
      data: decodeCapabilities(await client.panel<unknown>("/capabilities")),
    };
  } catch (error) {
    return isOptionalOperatorApiUnavailable(error)
      ? { status: "unavailable", message: t("governance.capabilities.unavailable") }
      : { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

export function CapabilitiesRoute({ client }: { readonly client: OperatorApiClient }) {
  const [state, setState] = useState<AsyncState<CapabilityResponse>>({ status: "loading" });
  const [iamState, setIamState] = useState<AsyncState<IamOverview>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    void loadCapabilitiesState(client).then((nextState) => {
      if (!cancelled) setState(nextState);
    });
    void client.iamOverview().then(
      (data) => {
        if (!cancelled) setIamState({ status: "ready", data });
      },
      (error) => {
        if (!cancelled) {
          setIamState({
            status: "unavailable",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      },
    );
    return () => { cancelled = true; };
  }, [client]);
  return (
    <div class="stack">
      <PageHeader title={t("route.capabilities")} subtitle={t("nav.panelSub.capabilities")} />
      <AsyncBoundary state={state} resourceLabel={t("governance.capabilities.resourceLabel")}>
        {(data) => <CapabilitiesBody data={data} iamState={iamState} />}
      </AsyncBoundary>
    </div>
  );
}

export function capabilityColumns(): readonly Column<Capability>[] {
  return [
    { key: "id", header: t("governance.capabilities.column.id"), render: (row) => <code>{row.capability_id}</code> },
    { key: "name", header: t("governance.capabilities.column.name"), render: (row) => row.name },
    { key: "category", header: t("governance.capabilities.column.category"), render: (row) => row.category },
    { key: "effect", header: t("governance.capabilities.column.sideEffectClass"), render: (row) => <StatusPill kind={row.side_effect_class === "read" ? "info" : "warning"} label={row.side_effect_class} /> },
    { key: "role", header: t("governance.capabilities.column.requiredRole"), render: (row) => row.required_role },
  ];
}

function CapabilitiesBody({
  data,
  iamState,
}: {
  readonly data: CapabilityResponse;
  readonly iamState: AsyncState<IamOverview>;
}) {
  const columns = capabilityColumns();
  const initial = capabilityRouteStateFromSearch(currentRoute().search);
  const [query, setQuery] = useState(initial.query);
  const [category, setCategory] = useState(initial.category);
  const [effect, setEffect] = useState(initial.effect);
  const [role, setRole] = useState(initial.role);
  const [sort, setSort] = useState(initial.sort);
  const [page, setPage] = useState(initial.page);
  const [selectedId, setSelectedId] = useState(initial.selectedId);
  useEffect(() => {
    const sync = () => {
      const route = capabilityRouteStateFromSearch(currentRoute().search);
      setQuery(route.query);
      setCategory(route.category);
      setEffect(route.effect);
      setRole(route.role);
      setSort(route.sort);
      setPage(route.page);
      setSelectedId(route.selectedId);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
    };
  }, []);
  const categories = new Set(data.capabilities.map((item) => item.category)).size;
  const mutatingDeclarations = data.capabilities.filter(
    (item) => isMutatingCapability(item.side_effect_class),
  ).length;
  const optionValues = (key: "category" | "side_effect_class" | "required_role") => [
    ...new Set(data.capabilities.map((item) => item[key])),
  ].sort();
  const normalized = query.trim().toLocaleLowerCase();
  const filtered = sortCapabilities(data.capabilities.filter((item) => {
    if (category !== "all" && item.category !== category) return false;
    if (effect !== "all" && item.side_effect_class !== effect) return false;
    if (role !== "all" && item.required_role !== role) return false;
    return !normalized || [item.capability_id, item.name, item.summary, ...item.tags]
      .join(" ").toLocaleLowerCase().includes(normalized);
  }), sort);
  const pageCount = Math.max(1, Math.ceil(filtered.length / CAPABILITY_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageStart = (currentPage - 1) * CAPABILITY_PAGE_SIZE;
  const pageRows = filtered.slice(pageStart, pageStart + CAPABILITY_PAGE_SIZE);
  const selected = selectedId
    ? data.capabilities.find((item) => item.capability_id === selectedId) ?? null
    : null;
  const allCapabilitiesHref = `${routeHref("capabilities")}#capabilities-table`;
  const visibleCapabilitiesHref = `${routeHref("capabilities", {
    params: {
      q: query || null,
      category: category === "all" ? null : category,
      effect: effect === "all" ? null : effect,
      role: role === "all" ? null : role,
      sort: sort === "category" ? null : sort,
      page: currentPage === 1 ? null : currentPage,
    },
  })}#capabilities-table`;
  const updateRoute = (next: {
    readonly query?: string;
    readonly category?: string;
    readonly effect?: string;
    readonly role?: string;
    readonly sort?: CapabilitySort;
    readonly page?: number;
    readonly selectedId?: string | null;
  }): void => {
    const nextQuery = next.query ?? query;
    const nextCategory = next.category ?? category;
    const nextEffect = next.effect ?? effect;
    const nextRole = next.role ?? role;
    const nextSort = next.sort ?? sort;
    const nextPage = next.page ?? page;
    const nextSelected = next.selectedId === undefined ? selectedId : next.selectedId;
    setQuery(nextQuery);
    setCategory(nextCategory);
    setEffect(nextEffect);
    setRole(nextRole);
    setSort(nextSort);
    setPage(nextPage);
    setSelectedId(nextSelected);
    replaceRouteState(routeHref("capabilities", {
      params: {
        q: nextQuery || null,
        category: nextCategory === "all" ? null : nextCategory,
        effect: nextEffect === "all" ? null : nextEffect,
        role: nextRole === "all" ? null : nextRole,
        sort: nextSort === "category" ? null : nextSort,
        page: nextPage === 1 ? null : nextPage,
        capability: nextSelected,
      },
    }));
  };
  const selectCapability = (capabilityId: string | null): void => {
    navigate(routeHref("capabilities", {
      params: {
        q: query || null,
        category: category === "all" ? null : category,
        effect: effect === "all" ? null : effect,
        role: role === "all" ? null : role,
        sort: sort === "category" ? null : sort,
        page: currentPage === 1 ? null : currentPage,
        capability: capabilityId,
      },
    }));
  };
  const resetFilters = (): void => {
    updateRoute({
      query: "",
      category: "all",
      effect: "all",
      role: "all",
      sort: "category",
      page: 1,
      selectedId: null,
    });
  };
  const shareHref = new URL(
    routeHref("capabilities", {
      params: {
        q: query || null,
        category: category === "all" ? null : category,
        effect: effect === "all" ? null : effect,
        role: role === "all" ? null : role,
        sort: sort === "category" ? null : sort,
        page: currentPage === 1 ? null : currentPage,
        capability: selectedId,
      },
    }),
    window.location.origin,
  ).toString();
  const roleMatch: CapabilityRoleMatch | "loading" = selected === null
    ? "unavailable"
    : iamState.status === "loading"
      ? "loading"
      : capabilityRoleMatch(
          selected.required_role,
          iamState.status === "ready" ? iamState.data.principal.roles : null,
        );
  usePublishViewContext(
    () => ({
      routeId: "capabilities",
      routeLabel: t("governance.capabilities.context.routeLabel"),
      purpose: t("governance.capabilities.context.purpose"),
      glossary: composeGlossary([TERMS.actionType, TERMS.shadowMode, TERMS.humanRbac]),
      headline: t("governance.capabilities.context.headline", {
        count: data.count,
        categories,
        mutating: mutatingDeclarations,
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "capability_count", value: data.count, group: "directory" },
        { key: "category_count", value: categories, group: "directory" },
        { key: "source", value: data.source, group: "directory" },
        { key: "execution_eligibility", value: data.execution_eligibility, group: "directory" },
        { key: "mutating_declaration_count", value: mutatingDeclarations, group: "directory" },
      ],
      records: {
        capabilities: data.capabilities.map((item) => ({ ...item, tags: item.tags.join(", ") })),
        selected_capability: selected ? [{ ...selected, tags: selected.tags.join(", ") }] : [],
      },
    }),
    [categories, data, mutatingDeclarations, selected],
  );
  return (
    <div class="stack capabilities-directory">
      <div class="governance-readonly-banner">
        <strong>{t("governance.capabilities.banner.title")}</strong>
        <span>{t("governance.capabilities.banner.body", { source: data.source })}</span>
      </div>
      <KpiGrid>
        <KpiCard href={allCapabilitiesHref} label={t("governance.capabilities.kpi.declarations")} value={data.count.toLocaleString()} />
        <KpiCard href={allCapabilitiesHref} label={t("governance.capabilities.kpi.categories")} value={categories.toLocaleString()} />
        <KpiCard href={allCapabilitiesHref} label={t("governance.capabilities.kpi.mutating")} value={mutatingDeclarations.toLocaleString()} />
        <KpiCard href={visibleCapabilitiesHref} label={t("governance.capabilities.kpi.shown")} value={filtered.length.toLocaleString()} />
      </KpiGrid>
      <section class="capabilities-filterbar" aria-label={t("governance.capabilities.filter.aria")}>
        <input id="capability-search" type="search" aria-label={t("governance.capabilities.filter.searchAria")} value={query} placeholder={t("governance.capabilities.filter.searchPlaceholder")} onInput={(event) => updateRoute({ query: event.currentTarget.value, page: 1, selectedId: null })} />
        <CapabilitySelect label={t("governance.capabilities.filter.category")} value={category} options={optionValues("category")} onChange={(value) => updateRoute({ category: value, page: 1, selectedId: null })} />
        <CapabilitySelect label={t("governance.capabilities.filter.sideEffect")} value={effect} options={optionValues("side_effect_class")} onChange={(value) => updateRoute({ effect: value, page: 1, selectedId: null })} />
        <CapabilitySelect label={t("governance.capabilities.filter.role")} value={role} options={optionValues("required_role")} onChange={(value) => updateRoute({ role: value, page: 1, selectedId: null })} />
      </section>
      <div class="capabilities-results-toolbar">
        <p aria-live="polite">
          {t("governance.capabilities.result.count", {
            start: filtered.length === 0 ? 0 : pageStart + 1,
            end: Math.min(pageStart + CAPABILITY_PAGE_SIZE, filtered.length),
            count: filtered.length,
          })}
        </p>
        <div class="cluster">
          <CapabilitySortSelect value={sort} onChange={(value) =>
            updateRoute({ sort: value, page: 1, selectedId: null })} />
          <button type="button" onClick={resetFilters}>
            {t("governance.capabilities.filter.reset")}
          </button>
          <CopyButton text={shareHref} label={t("governance.capabilities.copyView")} />
        </div>
      </div>
      <div class={`capabilities-workspace${selectedId ? " has-selection" : ""}`}>
        <div id="capabilities-table">
          <DataTable
            rows={pageRows}
            columns={columns}
            keyOf={(row) => row.capability_id}
            empty={t("governance.capabilities.empty")}
            onRowClick={(row) => selectCapability(row.capability_id)}
            isRowActive={(row) => row.capability_id === selectedId}
            rowActionLabel={(row) => t("governance.capabilities.openRow", { name: row.name })}
            rowActionControls="capability-detail"
            scrollRegionLabel={t("governance.capabilities.tableAria")}
          />
          {filtered.length > CAPABILITY_PAGE_SIZE ? (
            <nav class="capabilities-pagination" aria-label={t("governance.capabilities.pagination.aria")}>
              <button
                type="button"
                disabled={currentPage === 1}
                onClick={() => updateRoute({ page: currentPage - 1, selectedId: null })}
              >
                {t("governance.capabilities.pagination.previous")}
              </button>
              <span>{t("governance.capabilities.pagination.page", {
                page: currentPage,
                pages: pageCount,
              })}</span>
              <button
                type="button"
                disabled={currentPage === pageCount}
                onClick={() => updateRoute({ page: currentPage + 1, selectedId: null })}
              >
                {t("governance.capabilities.pagination.next")}
              </button>
            </nav>
          ) : null}
        </div>
        {selectedId ? (
          <div class="capability-detail-pane">
            {!selected ? (
              <UnavailableState message={t("governance.capabilities.unregistered", { id: selectedId })} />
            ) : (
              <CapabilityDetail
                capability={selected}
                roleMatch={roleMatch}
                onClose={() => selectCapability(null)}
              />
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function CapabilitySelect({ label, value, options, onChange }: {
  readonly label: string;
  readonly value: string;
  readonly options: readonly string[];
  readonly onChange: (value: string) => void;
}) {
  return <label><span>{label}</span><select value={value} onChange={(event) => onChange(event.currentTarget.value)}><option value="all">{t("governance.common.all")}</option>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>;
}

function CapabilitySortSelect({
  value,
  onChange,
}: {
  readonly value: CapabilitySort;
  readonly onChange: (value: CapabilitySort) => void;
}) {
  const options: readonly CapabilitySort[] = ["category", "name", "effect", "role"];
  return (
    <label class="capabilities-sort">
      <span>{t("governance.capabilities.sort.label")}</span>
      <select value={value} onChange={(event) => onChange(event.currentTarget.value as CapabilitySort)}>
        {options.map((option) => (
          <option key={option} value={option}>
            {t(`governance.capabilities.sort.${option}`)}
          </option>
        ))}
      </select>
    </label>
  );
}
