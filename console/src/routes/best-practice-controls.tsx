import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable } from "../api";
import type { ReadApiClient } from "../api";
import { ErrorState, LoadingState, UnavailableState } from "../components/ui";
import { currentRoute, navigate, replaceRouteState } from "../router";
import { BestPracticeControlsBody } from "./best-practice-controls-body";
import { BestPracticeDrawer } from "./best-practice-controls-detail";
import {
  bestPracticeHref,
  bestPracticeStateFromSearch,
  decodeBestPracticeDetail,
  decodeBestPracticeResponse,
  type BestPracticeDetail,
  type BestPracticeFilters,
  type BestPracticeResponse,
} from "./best-practice-controls.model";
import { t } from "./i18n/governance";

const PAGE_SIZE = 100;

type DetailState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: BestPracticeDetail }
  | { readonly status: "error"; readonly message: string };

export function BestPracticeControlsRoute({ client }: { readonly client: ReadApiClient }) {
  const initial = bestPracticeStateFromSearch(currentRoute().search);
  const [filters, setFilters] = useState(initial.filters);
  const [searchInput, setSearchInput] = useState(initial.filters.q);
  const [selected, setSelected] = useState(initial.selected);
  const [data, setData] = useState<BestPracticeResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "unavailable">(
    "loading",
  );
  const [message, setMessage] = useState("");
  const [detail, setDetail] = useState<DetailState>({ status: "loading" });
  const debounceRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      if (searchInput === filters.q) return;
      const next = { ...filters, q: searchInput };
      setFilters(next);
      replaceRouteState(bestPracticeHref(next, selected));
    }, 250);
    return () => window.clearTimeout(debounceRef.current);
  }, [filters, searchInput, selected]);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    (async () => {
      try {
        const params: Record<string, string> = { limit: String(PAGE_SIZE), offset: "0" };
        if (filters.pillar) params.pillar = filters.pillar;
        if (filters.status) params.status = filters.status;
        if (filters.q) params.q = filters.q;
        const response = decodeBestPracticeResponse(
          await client.panel<unknown>("/best-practices", params),
        );
        if (!cancelled) {
          setData(response);
          setStatus("ready");
        }
      } catch (error) {
        if (!cancelled) {
          setMessage(error instanceof Error ? error.message : String(error));
          setStatus(isOptionalReadApiUnavailable(error) ? "unavailable" : "error");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client, filters]);

  useEffect(() => {
    const onRouteChange = () => {
      const next = bestPracticeStateFromSearch(currentRoute().search);
      setFilters(next.filters);
      setSearchInput(next.filters.q);
      setSelected(next.selected);
    };
    window.addEventListener("popstate", onRouteChange);
    window.addEventListener("fdai:route-changed", onRouteChange);
    return () => {
      window.removeEventListener("popstate", onRouteChange);
      window.removeEventListener("fdai:route-changed", onRouteChange);
    };
  }, []);

  useEffect(() => {
    if (selected === null) return;
    let cancelled = false;
    setDetail({ status: "loading" });
    (async () => {
      try {
        const result = decodeBestPracticeDetail(
          await client.panel<unknown>(`/best-practices/${encodeURIComponent(selected)}`),
        );
        if (!cancelled) setDetail({ status: "ready", data: result });
      } catch (error) {
        if (!cancelled) {
          setDetail({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client, selected]);

  useEffect(() => {
    if (selected === null) return;
    document.body.classList.add("scroll-locked");
    return () => document.body.classList.remove("scroll-locked");
  }, [selected]);

  function updateFilter(patch: Partial<BestPracticeFilters>): void {
    navigate(bestPracticeHref({ ...filters, ...patch }, selected));
  }

  function selectControl(id: string | null): void {
    navigate(bestPracticeHref(filters, id));
  }

  if (data === null) {
    return status === "error" ? (
      <ErrorState message={t("governance.rules.controls.loadFailed", { message })} />
    ) : status === "unavailable" ? (
      <UnavailableState
        evidenceState="not-connected"
        message={t("governance.rules.controls.routeUnavailable")}
      />
    ) : (
      <LoadingState label={t("governance.rules.controls.loading")} />
    );
  }

  return (
    <div class="stack controls-catalog-view">
      {status === "error" ? (
        <ErrorState message={t("governance.rules.controls.loadFailed", { message })} />
      ) : null}
      <BestPracticeControlsBody
        data={data}
        filters={filters}
        searchInput={searchInput}
        loading={status === "loading" || searchInput !== filters.q}
        selected={selected}
        onFilter={updateFilter}
        onSearch={setSearchInput}
        onSelect={selectControl}
      />
      {selected !== null ? (
        <BestPracticeDrawer detail={detail} onClose={() => selectControl(null)} />
      ) : null}
    </div>
  );
}

export type BestPracticeDetailState = DetailState;
