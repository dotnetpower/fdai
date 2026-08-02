import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { ErrorState, LoadingState, UnavailableState } from "../components/ui";
import { currentRoute, navigate, replaceRouteState } from "../router";
import { t } from "./i18n/governance";
import { McsbControlsBody } from "./mcsb-controls-body";
import { McsbControlDrawer } from "./mcsb-controls-detail";
import {
  decodeMcsbControlDetail,
  decodeMcsbControlResponse,
  mcsbControlsHref,
  mcsbStateFromSearch,
  type McsbControlDetail,
  type McsbControlResponse,
  type McsbFilters,
} from "./mcsb-controls.model";

const PAGE_SIZE = 100;

export type McsbDetailState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: McsbControlDetail }
  | { readonly status: "error"; readonly message: string };

export function McsbControlsRoute({ client }: { readonly client: OperatorApiClient }) {
  const initial = mcsbStateFromSearch(currentRoute().search);
  const [version, setVersion] = useState(initial.version);
  const [filters, setFilters] = useState(initial.filters);
  const [searchInput, setSearchInput] = useState(initial.filters.q);
  const [selected, setSelected] = useState(initial.selected);
  const [data, setData] = useState<McsbControlResponse | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error" | "unavailable">("loading");
  const [message, setMessage] = useState("");
  const [detail, setDetail] = useState<McsbDetailState>({ status: "loading" });
  const debounceRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      if (searchInput === filters.q) return;
      const next = { ...filters, q: searchInput };
      setFilters(next);
      replaceRouteState(mcsbControlsHref(version, next, selected));
    }, 250);
    return () => window.clearTimeout(debounceRef.current);
  }, [filters, searchInput, selected, version]);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    (async () => {
      try {
        const params: Record<string, string> = {
          version,
          limit: String(PAGE_SIZE),
          offset: "0",
        };
        if (filters.domain) params.domain = filters.domain;
        if (filters.coverage) params.coverage = filters.coverage;
        if (filters.q) params.q = filters.q;
        const response = decodeMcsbControlResponse(
          await client.panel<unknown>("/mcsb-controls", params),
        );
        if (!cancelled) {
          setData(response);
          setStatus("ready");
        }
      } catch (error) {
        if (!cancelled) {
          setMessage(error instanceof Error ? error.message : String(error));
          setStatus(isOptionalOperatorApiUnavailable(error) ? "unavailable" : "error");
        }
      }
    })();
    return () => { cancelled = true; };
  }, [client, filters, version]);

  useEffect(() => {
    const onRouteChange = () => {
      const next = mcsbStateFromSearch(currentRoute().search);
      setVersion(next.version);
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
        const result = decodeMcsbControlDetail(
          await client.panel<unknown>(
            `/mcsb-controls/${encodeURIComponent(version)}/${encodeURIComponent(selected)}`,
          ),
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
  }, [client, selected, version]);

  useEffect(() => {
    if (selected === null) return;
    document.body.classList.add("scroll-locked");
    return () => document.body.classList.remove("scroll-locked");
  }, [selected]);

  function updateFilter(patch: Partial<McsbFilters>): void {
    navigate(mcsbControlsHref(version, { ...filters, ...patch }, selected));
  }

  function selectControl(controlId: string | null): void {
    navigate(mcsbControlsHref(version, filters, controlId));
  }

  const currentData = data?.benchmark.benchmark_version === version ? data : null;
  if (currentData === null) {
    return status === "error" ? (
      <ErrorState message={t("governance.rules.mcsb.loadFailed", { message })} />
    ) : status === "unavailable" ? (
      <UnavailableState evidenceState="not-connected" message={t("governance.rules.mcsb.routeUnavailable")} />
    ) : (
      <LoadingState label={t("governance.rules.mcsb.loading")} />
    );
  }

  return (
    <div class="stack mcsb-controls-view">
      {status === "error" ? <ErrorState message={t("governance.rules.mcsb.loadFailed", { message })} /> : null}
      <McsbControlsBody
        data={currentData}
        filters={filters}
        searchInput={searchInput}
        loading={status === "loading" || searchInput !== filters.q}
        selected={selected}
        onFilter={updateFilter}
        onSearch={setSearchInput}
        onSelect={selectControl}
      />
      {selected !== null ? <McsbControlDrawer detail={detail} onClose={() => selectControl(null)} /> : null}
    </div>
  );
}
