import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { ComponentChildren } from "preact";
import { ReadApiError } from "../api";
import type { ReadApiClient } from "../api";
import { architectureHref } from "../components/architecture-map.model";
import {
  DataTable,
  ErrorState,
  KpiCard,
  KpiGrid,
  LoadingState,
  PageHeader,
  StatusPill,
  UnavailableState,
  CopyButton,
  ExternalLink,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";

/**
 * Rule-catalog explorer panel. Fetches ``GET /rules`` and renders the
 * rules the system knows, faceted by origin (active catalog vs the
 * imported collected corpus), category, severity, and source.
 *
 * The collected tier is thousands of rules, so paging + filtering run
 * server-side: the panel re-fetches a page on any filter / page change
 * and reads facet counts (computed over the full corpus) for the
 * dropdowns and KPIs. The endpoint is opt-in on the API side
 * (``ReadApiConfig.rule_catalog_rules`` / ``rule_catalog_collected_rules``).
 * Read-only like every console route - it renders the catalog, it never
 * mutates it (rule changes flow through the catalog pipeline as PRs).
 */

const PAGE_SIZE = 100;

interface RuleDto {
  readonly id: string;
  readonly origin: string;
  readonly version: string;
  readonly source: string;
  readonly severity: string;
  readonly category: string;
  readonly resource_type: string;
  readonly check_logic: { readonly kind: string; readonly reference: string };
  readonly remediation: {
    readonly template_ref: string;
    readonly cost_impact_monthly_usd: number | null;
  };
  readonly remediates: string;
  readonly provenance: {
    readonly source_url: string;
    readonly license: string;
    readonly redistribution: string;
  };
}

type FacetMap = Readonly<Record<string, number>>;

interface RuleCatalogResponse {
  readonly total: number;
  readonly filtered_total: number;
  readonly offset: number;
  readonly limit: number;
  readonly resource_type_count: number;
  readonly facets: {
    readonly by_origin: FacetMap;
    readonly by_category: FacetMap;
    readonly by_severity: FacetMap;
    readonly by_source: FacetMap;
  };
  readonly rules: readonly RuleDto[];
}

interface RuleDetailDto extends RuleDto {
  readonly schema_version: string;
  readonly alternatives: readonly string[];
  readonly parameters: Readonly<Record<string, unknown>>;
  readonly applies_to: Readonly<Record<string, unknown>>;
  readonly check_logic_body: string | null;
  readonly remediation_body: string | null;
  readonly explanation: {
    readonly title: string | null;
    readonly description: string | null;
    readonly source: string | null;
    readonly details: Readonly<Record<string, unknown>>;
  };
  readonly provenance: {
    readonly source_url: string;
    readonly source_version: string | null;
    readonly resolved_ref: string;
    readonly content_hash: string;
    readonly license: string;
    readonly redistribution: string;
    readonly retrieved_at: string;
    readonly mapped_by: string | null;
  };
}

interface Selection {
  readonly id: string;
  readonly origin: string;
}

interface FindingDto {
  readonly resource_id: string;
  readonly resource_name?: string | null;
  readonly severity?: string;
  readonly problem?: string;
  readonly context?: Readonly<Record<string, unknown>>;
  readonly observed_at?: string;
}

interface FindingsResponse {
  readonly rule_id: string;
  readonly origin: string;
  readonly evaluated: boolean;
  readonly finding_count?: number;
  readonly findings: readonly FindingDto[];
}

type DetailState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: RuleDetailDto }
  | { readonly status: "error"; readonly message: string };

type FindingsState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: FindingsResponse }
  | { readonly status: "error"; readonly message: string };

interface Filters {
  readonly origin: string;
  readonly category: string;
  readonly severity: string;
  readonly source: string;
  readonly q: string;
}

const EMPTY_FILTERS: Filters = { origin: "", category: "", severity: "", source: "", q: "" };

/** Parse the selected rule from the URL hash query (deep-link support). */
function selectionFromHash(): Selection | null {
  const hash = window.location.hash;
  const qi = hash.indexOf("?");
  if (qi < 0) return null;
  const params = new URLSearchParams(hash.slice(qi + 1));
  const id = params.get("rule");
  if (!id) return null;
  return { id, origin: params.get("origin") ?? "" };
}

/** Reflect the selected rule into the URL hash so it is shareable and
 * the browser back button closes the drawer. */
function writeSelectionToHash(sel: Selection | null): void {
  const base = "#/rules";
  if (sel === null) {
    if (window.location.hash.startsWith(base) && window.location.hash.includes("?")) {
      window.location.hash = base;
    }
    return;
  }
  const q = new URLSearchParams({ rule: sel.id });
  if (sel.origin) q.set("origin", sel.origin);
  window.location.hash = `${base}?${q.toString()}`;
}

const SEVERITY_PILL: Record<string, PillKind> = {
  critical: "danger",
  high: "warning",
  medium: "info",
  low: "neutral",
};

interface Props {
  readonly client: ReadApiClient;
}

export function RuleCatalogRoute({ client }: Props) {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  // Keep the last successful response so the controls + table stay
  // mounted across refetches (stale-while-revalidate). If we swapped the
  // whole body for a loading block on every fetch, the search <input>
  // would unmount and lose focus after a single keystroke.
  const [data, setData] = useState<RuleCatalogResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "unavailable">("loading");
  const [errorMsg, setErrorMsg] = useState("");

  // Debounce the free-text box so a keystroke does not fire a request
  // per character.
  const [searchInput, setSearchInput] = useState("");
  const debounceRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setFilters((f) => ({ ...f, q: searchInput }));
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(debounceRef.current);
  }, [searchInput]);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    (async () => {
      try {
        const params: Record<string, string> = {
          limit: String(PAGE_SIZE),
          offset: String(offset),
        };
        if (filters.origin) params.origin = filters.origin;
        if (filters.category) params.category = filters.category;
        if (filters.severity) params.severity = filters.severity;
        if (filters.source) params.source = filters.source;
        if (filters.q) params.q = filters.q;
        const resp = await client.panel<RuleCatalogResponse>("/rules", params);
        if (!cancelled) {
          setData(resp);
          setStatus("ready");
        }
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (err instanceof ReadApiError && err.status === 404) {
            setStatus("unavailable");
            setErrorMsg(
              "The rule-catalog route is not wired on this deployment. " +
                "Set ReadApiConfig.rule_catalog_rules / rule_catalog_collected_rules " +
                "in the composition root to enable it.",
            );
          } else {
            setStatus("error");
            setErrorMsg(message);
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, filters, offset]);

  // Affected-resource counts per rule (active tier), fetched once after
  // the list renders. Non-blocking: badges fill in when it resolves;
  // upstream (no provider) returns evaluated=false -> no badges.
  const [affectedCounts, setAffectedCounts] = useState<Readonly<Record<string, number>>>({});
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await client.panel<{
          readonly evaluated: boolean;
          readonly counts: Readonly<Record<string, number>>;
        }>("/rules/findings-summary");
        if (!cancelled && data.evaluated) setAffectedCounts(data.counts);
      } catch {
        /* summary is best-effort - the list works without badges */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  function updateFilter(patch: Partial<Filters>): void {
    setFilters((f) => ({ ...f, ...patch }));
    setOffset(0);
  }

  // Row selection -> detail drawer. Fetches GET /rules/{id} with the
  // row origin so an id shared across tiers resolves unambiguously.
  // Selection is mirrored into the URL hash (deep-link / shareable).
  const [selected, setSelected] = useState<Selection | null>(selectionFromHash);

  function selectRule(sel: Selection | null): void {
    setSelected(sel);
    writeSelectionToHash(sel);
  }

  // React to back/forward + external hash edits (open or close the drawer).
  // Preserve the previous object reference when the selection content is
  // unchanged so writing the hash after a click does not trigger a refetch.
  useEffect(() => {
    const onHashChange = () =>
      setSelected((prev) => {
        const next = selectionFromHash();
        if (prev?.id === next?.id && prev?.origin === next?.origin) return prev;
        return next;
      });
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  const [detail, setDetail] = useState<DetailState>({ status: "loading" });
  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    setDetail({ status: "loading" });
    (async () => {
      try {
        const data = await client.panel<RuleDetailDto>(
          `/rules/${encodeURIComponent(selected.id)}`,
          { origin: selected.origin },
        );
        if (!cancelled) setDetail({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          setDetail({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, selected]);

  // Affected resources for the selected rule (which resource, which
  // attribute at fault). Separate request so a slow inventory
  // evaluation never blocks the rule metadata + code.
  const [findings, setFindings] = useState<FindingsState>({ status: "loading" });
  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    setFindings({ status: "loading" });
    (async () => {
      try {
        const data = await client.panel<FindingsResponse>(
          `/rules/${encodeURIComponent(selected.id)}/findings`,
          { origin: selected.origin },
        );
        if (!cancelled) setFindings({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          setFindings({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, selected]);

  // Close the drawer on Escape, and lock background scroll while it is
  // open so the list behind the overlay does not scroll (and wheel
  // events at the drawer's edge do not chain to the document).
  useEffect(() => {
    if (selected === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") selectRule(null);
    };
    window.addEventListener("keydown", onKey);
    document.body.classList.add("scroll-locked");
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.classList.remove("scroll-locked");
    };
  }, [selected]);

  const header = (
    <PageHeader
      title={t("route.rules")}
      subtitle="Every policy the system knows: the active catalog T0 evaluates plus the imported collected corpus. Read-only - rule changes flow through the catalog pipeline as PRs."
    />
  );

  // First load (no data yet): show a single state block.
  if (data === null) {
    return (
      <div class="stack">
        {header}
        {status === "error" ? (
          <ErrorState message={`Failed to load rule catalog: ${errorMsg}`} />
        ) : status === "unavailable" ? (
          <UnavailableState message={errorMsg} />
        ) : (
          <LoadingState label="Loading rule catalog..." />
        )}
      </div>
    );
  }

  // Have data: keep the body mounted; a refetch only dims the table and
  // shows an inline indicator, so the search box never loses focus.
  return (
    <div class="stack">
      {header}
      {status === "error" ? (
        <ErrorState message={`Failed to refresh rule catalog: ${errorMsg}`} />
      ) : null}
      <RuleCatalogBody
        data={data}
        filters={filters}
        searchInput={searchInput}
        loading={status === "loading"}
        selected={selected}
        detail={detail}
        findings={findings}
        affectedCounts={affectedCounts}
        onSelect={selectRule}
        onFilter={updateFilter}
        onSearch={setSearchInput}
        onPage={setOffset}
      />
      {selected !== null ? (
        <RuleDetailDrawer detail={detail} findings={findings} onClose={() => selectRule(null)} />
      ) : null}
    </div>
  );
}

function RuleCatalogBody({
  data,
  filters,
  searchInput,
  loading,
  selected,
  detail,
  findings,
  affectedCounts,
  onSelect,
  onFilter,
  onSearch,
  onPage,
}: {
  readonly data: RuleCatalogResponse;
  readonly filters: Filters;
  readonly searchInput: string;
  readonly loading: boolean;
  readonly selected: Selection | null;
  readonly detail: DetailState;
  readonly findings: FindingsState;
  readonly affectedCounts: Readonly<Record<string, number>>;
  readonly onSelect: (sel: Selection) => void;
  readonly onFilter: (patch: Partial<Filters>) => void;
  readonly onSearch: (next: string) => void;
  readonly onPage: (offset: number) => void;
}) {
  const active = data.facets.by_origin["active"] ?? 0;
  const collected = data.facets.by_origin["collected"] ?? 0;

  usePublishViewContext(
    () => {
      // When a rule is selected the detail drawer is open; surface the
      // selected rule's identity, resolved detail, and its affected
      // resources so the deck can answer "what is this rule / how is it
      // fixed / which resources violate it?" - not just the list summary.
      const selectionFacts: { key: string; value: string | number | boolean | null; group?: string }[] = [];
      const selectionRecords: Record<string, readonly Record<string, unknown>[]> = {};
      if (selected !== null) {
        selectionFacts.push(
          { key: "selected_rule", value: selected.id, group: "selection" },
          { key: "selected_origin", value: selected.origin, group: "selection" },
        );
        if (detail.status === "ready") {
          const d = detail.data;
          selectionFacts.push(
            { key: "selected_severity", value: d.severity, group: "selection" },
            { key: "selected_category", value: d.category, group: "selection" },
            { key: "selected_resource_type", value: d.resource_type, group: "selection" },
            { key: "selected_source", value: d.source, group: "selection" },
            { key: "selected_remediation", value: d.remediation.template_ref, group: "selection" },
            {
              key: "selected_monthly_cost_usd",
              value: d.remediation.cost_impact_monthly_usd,
              group: "selection",
            },
            {
              key: "selected_explanation",
              value: d.explanation.description ?? d.explanation.title ?? "(none)",
              group: "selection",
            },
            { key: "selected_remediates", value: d.remediates, group: "selection" },
          );
        } else {
          selectionFacts.push({
            key: "selected_rule_detail",
            value: detail.status,
            group: "selection",
          });
        }
        if (findings.status === "ready") {
          const f = findings.data;
          selectionFacts.push({
            key: "selected_affected_count",
            value: f.evaluated ? (f.finding_count ?? f.findings.length) : "not evaluated",
            group: "selection",
          });
          if (f.findings.length > 0) {
            selectionRecords["selected_findings"] = f.findings.map((x) => ({
              resource_id: x.resource_id,
              resource_name: x.resource_name ?? "-",
              severity: x.severity ?? "-",
              problem: x.problem ?? "-",
              observed_at: x.observed_at ?? "-",
            }));
          }
        }
      }
      return {
        routeId: "rules",
        routeLabel: "Rules",
        purpose:
          "The versioned rule catalog the deterministic engine (T0) evaluates - " +
          "each rule normalized to id/severity/category/resource-type/check/" +
          "remediation with provenance. Filter by origin, category, severity, " +
          "or source. Read-only reference.",
        glossary: composeGlossary([TERMS.actionType, TERMS.tier, TERMS.mode]),
        headline:
          selected !== null
            ? `Rule ${selected.id} selected - ${data.total} rules (${active} active, ${collected} collected)`
            : `${data.total} rules (${active} active, ${collected} collected)`,
        capturedAt: new Date().toISOString(),
        facts: [
          { key: "total_rules", value: data.total, group: "catalog" },
          { key: "active_rules", value: active, group: "catalog" },
          { key: "collected_rules", value: collected, group: "catalog" },
          { key: "filtered_total", value: data.filtered_total, group: "catalog" },
          { key: "resource_types", value: data.resource_type_count, group: "catalog" },
          {
            key: "categories_available",
            value: Object.keys(data.facets.by_category).join(", ") || "(none)",
            group: "catalog",
          },
          { key: "search_query", value: filters.q || "(none)", group: "filter" },
          { key: "filter_origin", value: filters.origin || "(all)", group: "filter" },
          { key: "filter_category", value: filters.category || "(all)", group: "filter" },
          { key: "filter_severity", value: filters.severity || "(all)", group: "filter" },
          { key: "filter_source", value: filters.source || "(all)", group: "filter" },
          ...selectionFacts,
        ],
        // Include the rule rows currently visible on this page so the deck
        // narrator can ground answers on real catalog content (id, severity,
        // category, resource type, source, remediation reference + cost), not
        // just the aggregate counts. Matches the audit route's `records.items`
        // pattern. The operator narrows to off-page rules via the search box.
        records: {
          rules: data.rules.map((r) => ({
            id: r.id,
            origin: r.origin,
            severity: r.severity,
            category: r.category,
            resource_type: r.resource_type,
            source: r.source,
            remediation: r.remediation.template_ref,
            monthly_cost_usd: r.remediation.cost_impact_monthly_usd,
          })),
          ...selectionRecords,
        },
      };
    },
    [data, active, collected, filters, selected, detail, findings],
  );

  const columns: readonly Column<RuleDto>[] = useMemo(
    () => [
      { key: "id", header: "Rule", render: (r) => r.id, cellClass: "mono" },
      {
        key: "origin",
        header: "Origin",
        render: (r) => (
          <StatusPill kind={r.origin === "active" ? "enforce" : "neutral"} label={r.origin} />
        ),
      },
      {
        key: "severity",
        header: "Severity",
        render: (r) => (
          <StatusPill kind={SEVERITY_PILL[r.severity] ?? "neutral"} label={r.severity} />
        ),
      },
      { key: "category", header: "Category", render: (r) => r.category },
      {
        key: "resource_type",
        header: "Resource",
        render: (r) => r.resource_type,
        cellClass: "mono",
      },
      { key: "source", header: "Source", render: (r) => r.source },
      {
        key: "affected",
        header: "Affected",
        headerClass: "num",
        cellClass: "num",
        render: (r) => {
          const n = affectedCounts[r.id];
          return n ? <span class="affected-badge" title={`${n} resource(s) violate this rule`}>{n}</span> : null;
        },
      },
      {
        key: "chevron",
        header: "",
        headerClass: "chevron-col",
        cellClass: "chevron-col",
        render: () => <span class="row-chevron" aria-hidden="true">›</span>,
      },
    ],
    [affectedCounts],
  );

  const pageStart = data.filtered_total === 0 ? 0 : data.offset + 1;
  const pageEnd = Math.min(data.offset + data.limit, data.filtered_total);
  const hasPrev = data.offset > 0;
  const hasNext = data.offset + data.limit < data.filtered_total;

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard label="Total rules" value={data.total} />
        <KpiCard label="Active catalog" value={active} hint="Curated - T0 evaluates these" />
        <KpiCard label="Collected corpus" value={collected} hint="Imported upstream sources" />
        <KpiCard label="Resource types" value={data.resource_type_count} />
      </KpiGrid>

      <section class="stack-section">
        <div class="form-grid inline">
          <FacetSelect
            label="Origin"
            value={filters.origin}
            counts={data.facets.by_origin}
            onChange={(v) => onFilter({ origin: v })}
          />
          <FacetSelect
            label="Category"
            value={filters.category}
            counts={data.facets.by_category}
            onChange={(v) => onFilter({ category: v })}
          />
          <FacetSelect
            label="Severity"
            value={filters.severity}
            counts={data.facets.by_severity}
            onChange={(v) => onFilter({ severity: v })}
          />
          <FacetSelect
            label="Source"
            value={filters.source}
            counts={data.facets.by_source}
            onChange={(v) => onFilter({ source: v })}
          />
          <label>
            Search id / resource
            <input
              type="search"
              value={searchInput}
              placeholder="e.g. disk.unattached"
              onInput={(e) => onSearch((e.target as HTMLInputElement).value)}
            />
          </label>
        </div>

        <div class="table-toolbar">
          <p class="muted">
            {data.filtered_total === 0
              ? "No rules match the current filters."
              : `Showing ${pageStart}-${pageEnd} of ${data.filtered_total} filtered (${data.total} total)`}
            {loading ? <span class="muted"> - updating...</span> : null}
          </p>
          <div class="pager">
            <button
              type="button"
              class="btn"
              disabled={!hasPrev}
              onClick={() => onPage(Math.max(0, data.offset - data.limit))}
            >
              Prev
            </button>
            <button
              type="button"
              class="btn"
              disabled={!hasNext}
              onClick={() => onPage(data.offset + data.limit)}
            >
              Next
            </button>
          </div>
        </div>

        <div class={loading ? "is-refreshing" : undefined}>
          <DataTable<RuleDto>
            columns={columns}
            rows={data.rules}
            keyOf={(r) => `${r.origin}:${r.id}`}
            empty="No rules match the current filters."
            onRowClick={(r) => onSelect({ id: r.id, origin: r.origin })}
            isRowActive={(r) =>
              selected !== null && selected.id === r.id && selected.origin === r.origin
            }
          />
        </div>
      </section>
    </div>
  );
}

function FacetSelect({
  label,
  value,
  counts,
  onChange,
}: {
  readonly label: string;
  readonly value: string;
  readonly counts: FacetMap;
  readonly onChange: (next: string) => void;
}) {
  const options = Object.entries(counts);
  return (
    <label>
      {label}
      <select value={value} onChange={(e) => onChange((e.target as HTMLSelectElement).value)}>
        <option value="">All ({options.reduce((sum, [, n]) => sum + n, 0)})</option>
        {options.map(([key, count]) => (
          <option key={key} value={key}>
            {key} ({count})
          </option>
        ))}
      </select>
    </label>
  );
}

function RuleDetailDrawer({
  detail,
  findings,
  onClose,
}: {
  readonly detail: DetailState;
  readonly findings: FindingsState;
  readonly onClose: () => void;
}) {
  // WCAG dialog behaviour: move focus into the drawer on open, restore
  // it to the trigger on close, and trap Tab within the drawer.
  const panelRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    return () => previouslyFocused?.focus?.();
  }, []);

  function trapFocus(e: KeyboardEvent): void {
    if (e.key === "Escape") {
      // Handle Escape on the drawer itself so it closes regardless of
      // which focusable inside it currently holds focus.
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key !== "Tab" || panelRef.current === null) return;
    const focusables = panelRef.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!first || !last) return;
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  return (
    <div class="drawer-overlay" onClick={onClose}>
      <aside
        ref={panelRef}
        tabIndex={-1}
        class="rule-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Rule detail"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={trapFocus}
      >
        <header class="rule-drawer-head">
          <h3 class="mono">
            {detail.status === "ready" ? detail.data.id : "Rule detail"}
          </h3>
          <div class="rule-drawer-actions">
            <CopyButton text={window.location.href} label="Copy link" />
            <button type="button" class="btn" onClick={onClose} aria-label="Close">
              Close
            </button>
          </div>
        </header>
        <div class="rule-drawer-body">
          {detail.status === "loading" ? (
            <LoadingState label="Loading rule detail..." />
          ) : detail.status === "error" ? (
            <ErrorState message={`Failed to load rule detail: ${detail.message}`} />
          ) : (
            <RuleDetailContent data={detail.data} findings={findings} />
          )}
        </div>
      </aside>
    </div>
  );
}

function RuleDetailContent({
  data,
  findings,
}: {
  readonly data: RuleDetailDto;
  readonly findings: FindingsState;
}) {
  return (
    <div class="stack">
      <div class="pill-row">
        <StatusPill kind={data.origin === "active" ? "enforce" : "neutral"} label={data.origin} />
        <StatusPill kind={SEVERITY_PILL[data.severity] ?? "neutral"} label={data.severity} />
        <StatusPill kind="info" label={data.category} />
      </div>

      <RuleOverview data={data} />

      <AffectedResources findings={findings} />

      <dl class="detail-grid">
        <DetailRow label="Source" value={data.source} />
        <DetailRow label="Resource type" value={data.resource_type} mono />
        <DetailRow label="Version" value={data.version} mono />
        <DetailRow label="Remediates" value={data.remediates} mono />
        {data.alternatives.length > 0 ? (
          <DetailRow label="Alternatives" value={data.alternatives.join(", ")} mono />
        ) : null}
        <DetailRow
          label="Cost impact / mo"
          value={
            data.remediation.cost_impact_monthly_usd == null
              ? "-"
              : `$${data.remediation.cost_impact_monthly_usd.toFixed(2)}`
          }
        />
      </dl>

      <DetailSection
        title="Check logic"
        subtitle={`${data.check_logic.kind} - ${data.check_logic.reference}`}
        action={
          data.check_logic_body !== null ? <CopyButton text={data.check_logic_body} /> : null
        }
      >
        {data.check_logic_body !== null ? (
          <pre class="mono code-block drawer-code">{data.check_logic_body}</pre>
        ) : (
          <p class="muted footnote">
            No inline body - this check is an external reference ({data.check_logic.kind}).
          </p>
        )}
      </DetailSection>

      <DetailSection
        title="Remediation"
        subtitle={data.remediation.template_ref}
        action={
          data.remediation_body !== null ? <CopyButton text={data.remediation_body} /> : null
        }
      >
        {data.remediation_body !== null ? (
          <pre class="mono code-block drawer-code">{data.remediation_body}</pre>
        ) : (
          <p class="muted footnote">No inline remediation template body available.</p>
        )}
      </DetailSection>

      {Object.keys(data.parameters).length > 0 ? (
        <DetailSection title="Parameters">
          <pre class="mono small entry-json">{JSON.stringify(data.parameters, null, 2)}</pre>
        </DetailSection>
      ) : null}

      <DetailSection title="Provenance">
        <dl class="detail-grid">
          <DetailRow
            label="Source URL"
            value={<ExternalLink href={data.provenance.source_url}>{data.provenance.source_url}</ExternalLink>}
          />
          <DetailRow label="License" value={data.provenance.license} />
          <DetailRow label="Redistribution" value={data.provenance.redistribution} />
          <DetailRow label="Content hash" value={data.provenance.content_hash} mono />
          <DetailRow label="Resolved ref" value={data.provenance.resolved_ref} mono />
          <DetailRow label="Retrieved at" value={data.provenance.retrieved_at} mono />
        </dl>
      </DetailSection>
    </div>
  );
}

const SEVERITY_RISK: Record<string, string> = {
  critical: "Critical - a violation is an immediate, high-impact exposure.",
  high: "High - a violation is a serious risk that should be fixed promptly.",
  medium: "Medium - a violation weakens posture and should be scheduled.",
  low: "Low - a violation is a minor or best-practice gap.",
};

function RuleOverview({ data }: { readonly data: RuleDetailDto }) {
  const { explanation } = data;
  const heading = explanation.title ?? data.id;
  const detailEntries = Object.entries(explanation.details ?? {});
  return (
    <section class="rule-overview">
      <h4 class="rule-overview-title">{heading}</h4>
      <p class={`risk-line risk-${data.severity}`}>
        {SEVERITY_RISK[data.severity] ?? `Severity: ${data.severity}`}
      </p>
      {explanation.description ? (
        <p class="rule-overview-desc">{explanation.description}</p>
      ) : (
        <p class="muted footnote">
          No authored description for this rule. See the check logic and remediation below for
          what it enforces and how to fix it.
        </p>
      )}
      {detailEntries.length > 0 ? (
        <dl class="detail-grid">
          {detailEntries.map(([k, v]) => (
            <DetailRow key={k} label={k.replace(/_/g, " ")} value={String(v)} mono />
          ))}
        </dl>
      ) : null}
    </section>
  );
}

function AffectedResources({ findings }: { readonly findings: FindingsState }) {
  if (findings.status === "loading") {
    return (
      <DetailSection title="Affected resources">
        <LoadingState label="Evaluating affected resources..." />
      </DetailSection>
    );
  }
  if (findings.status === "error") {
    return (
      <DetailSection title="Affected resources">
        <ErrorState message={`Failed to load affected resources: ${findings.message}`} />
      </DetailSection>
    );
  }

  const { data } = findings;
  if (!data.evaluated) {
    return (
      <DetailSection title="Affected resources">
        <p class="muted footnote">
          No inventory evaluation is wired on this deployment. When this rule runs against your
          inventory, each affected resource and the exact attribute at fault (the deny reason)
          appears here.
        </p>
      </DetailSection>
    );
  }
  if (data.findings.length === 0) {
    return (
      <DetailSection title="Affected resources">
        <p class="muted footnote">No resources currently violate this rule.</p>
      </DetailSection>
    );
  }

  return (
    <DetailSection title={`Affected resources (${data.finding_count ?? data.findings.length})`}>
      <ul class="finding-list">
        {data.findings.map((f, i) => (
          <li key={f.resource_id + i} class="finding-item">
            <div class="finding-head">
              <span class="mono finding-res">{f.resource_name ?? f.resource_id}</span>
              <a class="finding-architecture-link" href={architectureHref(f.resource_id)}>
                View on architecture
              </a>
              {f.severity ? (
                <StatusPill kind={SEVERITY_PILL[f.severity] ?? "neutral"} label={f.severity} />
              ) : null}
            </div>
            {f.problem ? <p class="finding-problem">{f.problem}</p> : null}
            {f.resource_name && f.resource_name !== f.resource_id ? (
              <p class="muted footnote mono">{f.resource_id}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </DetailSection>
  );
}

function DetailSection({
  title,
  subtitle,
  action,
  children,
}: {
  readonly title: string;
  readonly subtitle?: string;
  readonly action?: ComponentChildren;
  readonly children: ComponentChildren;
}) {
  return (
    <section class="stack-section">
      <div class="section-header">
        <h4 class="section-title">{title}</h4>
        {action ?? null}
      </div>
      {subtitle ? <p class="muted footnote mono">{subtitle}</p> : null}
      {children}
    </section>
  );
}

function DetailRow({
  label,
  value,
  mono,
}: {
  readonly label: string;
  readonly value: ComponentChildren;
  readonly mono?: boolean;
}) {
  return (
    <>
      <dt class="muted">{label}</dt>
      <dd class={mono ? "mono" : undefined}>{value}</dd>
    </>
  );
}
