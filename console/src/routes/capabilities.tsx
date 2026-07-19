import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, CopyButton, DataTable, KpiCard, KpiGrid, PageHeader, StatusPill, UnavailableState, type AsyncState, type Column } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, replaceRouteState, routeHref } from "../router";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

interface Capability {
  readonly capability_id: string;
  readonly name: string;
  readonly category: string;
  readonly summary: string;
  readonly side_effect_class: string;
  readonly default_mode: string;
  readonly required_role: string;
  readonly slide_ref: string;
  readonly tags: readonly string[];
}

interface CapabilityResponse {
  readonly source: string;
  readonly execution_eligibility: boolean;
  readonly count: number;
  readonly capabilities: readonly Capability[];
}

export function CapabilitiesRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<CapabilityResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    client.panel<unknown>("/capabilities")
      .then((value) => { if (!cancelled) setState({ status: "ready", data: decodeCapabilities(value) }); })
      .catch((error: unknown) => { if (!cancelled) setState({ status: "error", message: error instanceof Error ? error.message : String(error) }); });
    return () => { cancelled = true; };
  }, [client]);
  return <div class="stack"><PageHeader title={t("route.capabilities")} subtitle={t("nav.panelSub.capabilities")} /><AsyncBoundary state={state} resourceLabel="capabilities">{(data) => <CapabilitiesBody data={data} />}</AsyncBoundary></div>;
}

export function decodeCapabilities(value: unknown): CapabilityResponse {
  const root = panelRecord(value, "capabilities");
  const capabilities = panelArray(root["capabilities"], "capabilities.items").map((raw, index) => {
      const item = panelRecord(raw, `capabilities.items[${index}]`);
      return {
        capability_id: panelNonEmptyString(item, "capability_id", "capability"),
        name: panelNonEmptyString(item, "name", "capability"),
        category: panelNonEmptyString(item, "category", "capability"),
        summary: panelNonEmptyString(item, "summary", "capability"),
        side_effect_class: panelNonEmptyString(item, "side_effect_class", "capability"),
        default_mode: panelNonEmptyString(item, "default_mode", "capability"),
        required_role: panelNonEmptyString(item, "required_role", "capability"),
        slide_ref: panelNonEmptyString(item, "slide_ref", "capability"),
        tags: panelStringArray(item["tags"], "capability.tags"),
      };
    });
  const count = panelNonNegativeInteger(root, "count", "capabilities");
  if (count !== capabilities.length) throw new Error("invalid read API response: capabilities.count MUST match items");
  const ids = capabilities.map((item) => item.capability_id);
  if (new Set(ids).size !== ids.length) throw new Error("invalid read API response: capability ids MUST be unique");
  return {
    source: panelNonEmptyString(root, "source", "capabilities"),
    execution_eligibility: panelBoolean(root, "execution_eligibility", "capabilities"),
    count,
    capabilities,
  };
}

export interface CapabilityRouteState {
  readonly query: string;
  readonly category: string;
  readonly effect: string;
  readonly role: string;
  readonly selectedId: string | null;
}

export function capabilityRouteStateFromSearch(search: URLSearchParams): CapabilityRouteState {
  return {
    query: search.get("q") ?? "",
    category: search.get("category") ?? "all",
    effect: search.get("effect") ?? "all",
    role: search.get("role") ?? "all",
    selectedId: search.get("capability"),
  };
}

const columns: readonly Column<Capability>[] = [
  { key: "id", header: "Capability id", render: (row) => <code>{row.capability_id}</code> },
  { key: "name", header: "Name", render: (row) => row.name },
  { key: "category", header: "Category", render: (row) => row.category },
  { key: "effect", header: "Side-effect class", render: (row) => <StatusPill kind={row.side_effect_class === "read" ? "info" : "warning"} label={row.side_effect_class} /> },
  { key: "mode", header: "Default mode", render: (row) => <StatusPill kind={row.default_mode === "shadow" ? "shadow" : "enforce"} label={row.default_mode} /> },
  { key: "role", header: "Required role", render: (row) => row.required_role },
  { key: "summary", header: "Summary", render: (row) => row.summary },
];

export function isMutatingCapability(sideEffectClass: string): boolean {
  return sideEffectClass === "execute" || sideEffectClass === "breakglass";
}

function CapabilitiesBody({ data }: { readonly data: CapabilityResponse }) {
  const initial = capabilityRouteStateFromSearch(currentRoute().search);
  const [query, setQuery] = useState(initial.query);
  const [category, setCategory] = useState(initial.category);
  const [effect, setEffect] = useState(initial.effect);
  const [role, setRole] = useState(initial.role);
  const [selectedId, setSelectedId] = useState(initial.selectedId);
  useEffect(() => {
    const sync = () => {
      const route = capabilityRouteStateFromSearch(currentRoute().search);
      setQuery(route.query);
      setCategory(route.category);
      setEffect(route.effect);
      setRole(route.role);
      setSelectedId(route.selectedId);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
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
  const visible = data.capabilities.filter((item) => {
    if (category !== "all" && item.category !== category) return false;
    if (effect !== "all" && item.side_effect_class !== effect) return false;
    if (role !== "all" && item.required_role !== role) return false;
    return !normalized || [item.capability_id, item.name, item.summary, ...item.tags]
      .join(" ").toLocaleLowerCase().includes(normalized);
  });
  const selected = selectedId
    ? data.capabilities.find((item) => item.capability_id === selectedId) ?? null
    : null;
  const updateRoute = (next: {
    readonly query?: string;
    readonly category?: string;
    readonly effect?: string;
    readonly role?: string;
    readonly selectedId?: string | null;
  }): void => {
    const nextQuery = next.query ?? query;
    const nextCategory = next.category ?? category;
    const nextEffect = next.effect ?? effect;
    const nextRole = next.role ?? role;
    const nextSelected = next.selectedId === undefined ? selectedId : next.selectedId;
    setQuery(nextQuery);
    setCategory(nextCategory);
    setEffect(nextEffect);
    setRole(nextRole);
    setSelectedId(nextSelected);
    replaceRouteState(routeHref("capabilities", {
      params: {
        q: nextQuery || null,
        category: nextCategory === "all" ? null : nextCategory,
        effect: nextEffect === "all" ? null : nextEffect,
        role: nextRole === "all" ? null : nextRole,
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
        capability: capabilityId,
      },
    }));
  };
  usePublishViewContext(
    () => ({
      routeId: "capabilities",
      routeLabel: "Capabilities",
      purpose: "Directory of declared operator capability contracts, required roles, side-effect classes, and default safety modes. Catalog presence does not grant execution eligibility.",
      glossary: composeGlossary([TERMS.actionType, TERMS.shadowMode, TERMS.humanRbac]),
      headline: `${data.count} declarations across ${categories} categories; ${mutatingDeclarations} declare a mutating side-effect class`,
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
        <strong>Catalog declarations only.</strong>
        <span>
          Source: {data.source}. Entries describe governed contracts; they do not prove provider
          binding, runtime health, or execution eligibility.
        </span>
      </div>
      <KpiGrid>
        <KpiCard label="Declarations" value={data.count.toLocaleString()} />
        <KpiCard label="Categories" value={categories.toLocaleString()} />
        <KpiCard label="Mutating declarations" value={mutatingDeclarations.toLocaleString()} />
        <KpiCard label="Shown" value={visible.length.toLocaleString()} />
      </KpiGrid>
      <section class="capabilities-filterbar" aria-label="Capability filters">
        <input id="capability-search" type="search" aria-label="Filter capabilities" value={query} placeholder="Filter capability id, name, tag, or summary" onInput={(event) => updateRoute({ query: event.currentTarget.value, selectedId: null })} />
        <CapabilitySelect label="Category" value={category} options={optionValues("category")} onChange={(value) => updateRoute({ category: value, selectedId: null })} />
        <CapabilitySelect label="Side effect" value={effect} options={optionValues("side_effect_class")} onChange={(value) => updateRoute({ effect: value, selectedId: null })} />
        <CapabilitySelect label="Role" value={role} options={optionValues("required_role")} onChange={(value) => updateRoute({ role: value, selectedId: null })} />
      </section>
      <DataTable
        rows={visible}
        columns={columns}
        keyOf={(row) => row.capability_id}
        empty="No capabilities match these filters"
        onRowClick={(row) => selectCapability(row.capability_id)}
        isRowActive={(row) => row.capability_id === selectedId}
        rowActionLabel={(row) => `Open ${row.name}`}
        rowActionControls="capability-detail"
      />
      {selectedId && !selected ? (
        <UnavailableState message={`Capability ${selectedId} is not registered.`} />
      ) : selected ? (
        <section id="capability-detail" class="capability-detail stack-section">
          <header class="section-header">
            <div><h3>{selected.name}</h3><code>{selected.capability_id}</code></div>
            <div class="cluster">
              <CopyButton text={selected.capability_id} label="Copy id" />
              <button type="button" onClick={() => selectCapability(null)}>Close</button>
            </div>
          </header>
          <p>{selected.summary}</p>
          <dl>
            <div><dt>Category</dt><dd>{selected.category}</dd></div>
            <div><dt>Side effect</dt><dd>{selected.side_effect_class}</dd></div>
            <div><dt>Default mode</dt><dd>{selected.default_mode}</dd></div>
            <div><dt>Required role</dt><dd>{selected.required_role}</dd></div>
            <div><dt>Tags</dt><dd>{selected.tags.join(", ") || "-"}</dd></div>
          </dl>
          <a href={routeHref(capabilityPanel(selected.category))}>Open related surface</a>
        </section>
      ) : null}
    </div>
  );
}

function CapabilitySelect({ label, value, options, onChange }: {
  readonly label: string;
  readonly value: string;
  readonly options: readonly string[];
  readonly onChange: (value: string) => void;
}) {
  return <label><span>{label}</span><select value={value} onChange={(event) => onChange(event.currentTarget.value)}><option value="all">All</option>{options.map((option) => <option key={option} value={option}>{option}</option>)}</select></label>;
}

function capabilityPanel(category: string): string {
  if (category === "cost") return "llm-cost";
  if (category === "incident") return "incidents";
  if (category === "investigation") return "rca";
  if (category === "knowledge") return "documents";
  if (category === "reporting") return "reports";
  return "workflow-builder";
}
