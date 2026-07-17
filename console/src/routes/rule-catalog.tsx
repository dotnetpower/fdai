import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable } from "../api";
import type { ReadApiClient } from "../api";
import {
  ErrorState,
  LoadingState,
  PageHeader,
  UnavailableState,
} from "../components/ui";
import { t } from "../i18n";
import { currentRoute, navigate, replaceRouteState, routeHref } from "../router";
import { RuleCatalogBody } from "./rule-catalog-body";
import { RuleDetailDrawer } from "./rule-catalog-detail";
import { isRuleListUpdating } from "./rule-catalog.model";
import {
  ruleCatalogHref,
  ruleDetailFailure,
  ruleLifecycleStatusFromSearch,
  ruleListStateFromSearch,
  ruleSelectionFromSearch,
  type RuleFilters as Filters,
  type RuleSelection as Selection,
} from "./rule-catalog-state";
import {
  type DetailState,
  type FindingsResponse,
  type FindingsState,
  type RuleCatalogResponse,
  type RuleDetailDto,
} from "./rule-catalog-types";
export {
  ruleCatalogHref,
  ruleDetailFailure,
  ruleLifecycleStatusFromSearch,
  ruleListStateFromSearch,
  ruleSelectionFromSearch,
} from "./rule-catalog-state";

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

const EMPTY_FILTERS: Filters = { origin: "", category: "", severity: "", source: "", q: "" };

function ruleListStateFromRoute(): { readonly filters: Filters; readonly offset: number } {
  return ruleListStateFromSearch(currentRoute().search);
}

function selectionFromHash(): Selection | null {
  return ruleSelectionFromSearch(currentRoute().search);
}

interface Props {
  readonly client: ReadApiClient;
}

export function RuleCatalogRoute({ client }: Props) {
  const initialListState = ruleListStateFromRoute();
  const [lifecycleStatus, setLifecycleStatus] = useState(ruleLifecycleStatusFromSearch(
    currentRoute().search,
  ));
  const [filters, setFilters] = useState<Filters>(initialListState.filters);
  const [offset, setOffset] = useState(initialListState.offset);
  const [selected, setSelected] = useState<Selection | null>(selectionFromHash);
  // Keep the last successful response so the controls + table stay
  // mounted across refetches (stale-while-revalidate). If we swapped the
  // whole body for a loading block on every fetch, the search <input>
  // would unmount and lose focus after a single keystroke.
  const [data, setData] = useState<RuleCatalogResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "unavailable">("loading");
  const [errorMsg, setErrorMsg] = useState("");

  // Debounce the free-text box so a keystroke does not fire a request
  // per character.
  const [searchInput, setSearchInput] = useState(initialListState.filters.q);
  const debounceRef = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      if (searchInput === filters.q) return;
      const next = { ...filters, q: searchInput };
      setFilters(next);
      setOffset(0);
      replaceRouteState(ruleCatalogHref(next, 0, selected));
    }, 250);
    return () => window.clearTimeout(debounceRef.current);
  }, [filters, searchInput, selected]);

  useEffect(() => {
    let cancelled = false;
    if (lifecycleStatus === "promoted" || lifecycleStatus === "candidate" || lifecycleStatus === "invalid") {
      setData(null);
      setStatus("unavailable");
      setErrorMsg(
        lifecycleStatus === "invalid"
          ? "The requested rule lifecycle status is not registered."
          : `Rule ${lifecycleStatus} lifecycle evidence is not exposed by this deployment.`,
      );
      return () => { cancelled = true; };
    }
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
          if (isOptionalReadApiUnavailable(err)) {
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
  }, [client, filters, lifecycleStatus, offset]);

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
    navigate(ruleCatalogHref({ ...filters, ...patch }, 0, selected));
  }

  // Row selection -> detail drawer. Fetches GET /rules/{id} with the
  // row origin so an id shared across tiers resolves unambiguously.
  // Selection is mirrored into the URL query (deep-link / shareable).
  function selectRule(sel: Selection | null): void {
    navigate(ruleCatalogHref(filters, offset, sel));
  }

  // React to back/forward + external route edits (open or close the drawer).
  // Preserve the previous object reference when the selection content is
  // unchanged so writing the hash after a click does not trigger a refetch.
  useEffect(() => {
    const onRouteChange = () => {
      const listState = ruleListStateFromRoute();
      setLifecycleStatus(ruleLifecycleStatusFromSearch(currentRoute().search));
      setFilters(listState.filters);
      setSearchInput(listState.filters.q);
      setOffset(listState.offset);
      setSelected((prev) => {
        const next = selectionFromHash();
        if (prev?.id === next?.id && prev?.origin === next?.origin) return prev;
        return next;
      });
    };
    window.addEventListener("popstate", onRouteChange);
    window.addEventListener("fdai:route-changed", onRouteChange);
    return () => {
      window.removeEventListener("popstate", onRouteChange);
      window.removeEventListener("fdai:route-changed", onRouteChange);
    };
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
          setDetail(ruleDetailFailure(err, selected.id));
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
      <div class="stack governance-route rules-route">
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
  const listUpdating = isRuleListUpdating(searchInput, filters.q, status === "loading");
  return (
    <div class="stack governance-route rules-route">
      {header}
      {status === "error" ? (
        <ErrorState message={`Failed to refresh rule catalog: ${errorMsg}`} />
      ) : null}
      <RuleCatalogBody
        data={data}
        filters={filters}
        searchInput={searchInput}
        loading={listUpdating}
        selected={selected}
        detail={detail}
        findings={findings}
        affectedCounts={affectedCounts}
        onSelect={selectRule}
        onFilter={updateFilter}
        onSearch={setSearchInput}
        onPage={(nextOffset) => navigate(ruleCatalogHref(filters, nextOffset, selected))}
      />
      {selected !== null ? (
        <RuleDetailDrawer detail={detail} findings={findings} onClose={() => selectRule(null)} />
      ) : null}
    </div>
  );
}
