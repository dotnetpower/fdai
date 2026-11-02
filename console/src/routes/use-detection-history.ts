import { useEffect, useMemo, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { DetectionHistoryCache, type DetectionHistoryPage, type HistoryFilters } from "./detection-history";

type HistoryState =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly page: DetectionHistoryPage };

export function useDetectionHistory(
  client: OperatorApiClient | undefined,
  enabled: boolean,
  filters: HistoryFilters,
) {
  const cache = useMemo(() => client ? new DetectionHistoryCache(client) : null, [client]);
  const [state, setState] = useState<HistoryState>({ status: "loading" });
  const [cursors, setCursors] = useState<readonly (string | null)[]>([null]);
  const [index, setIndex] = useState(0);
  const [pageSize, setPageSize] = useState(50);
  const [revision, setRevision] = useState(0);
  const filterKey = JSON.stringify(filters);
  const [applied, setApplied] = useState(filterKey);
  useEffect(() => {
    if (!cache || !enabled) return;
    let active = true;
    setState({ status: "loading" });
    const changed = applied !== filterKey;
    const timer = setTimeout(() => {
      if (changed) {
        setApplied(filterKey);
        setIndex(0);
        setCursors([null]);
        return;
      }
      void cache.load(JSON.parse(filterKey) as HistoryFilters, cursors[index] ?? null, pageSize).then(
        page => { if (active) setState({ status: "ready", page }); },
        error => { if (active) setState({ status: "error", message: error instanceof Error ? error.message : String(error) }); },
      );
    }, changed ? 250 : 0);
    return () => { active = false; clearTimeout(timer); };
  }, [cache, enabled, filterKey, applied, index, cursors, pageSize, revision]);
  const refresh = () => {
    setState({ status: "loading" });
    cache?.clear();
    setCursors([null]);
    setIndex(0);
    setRevision(value => value + 1);
  };
  return {
    state: filterKey !== applied ? { status: "loading" } as const : state,
    index, pageSize, refresh,
    setPageSize: (size: number) => { setPageSize(size); refresh(); },
    previous: () => {
      setState({ status: "loading" });
      setIndex(value => Math.max(0, value - 1));
    },
    next: () => {
      if (state.status !== "ready" || !state.page.nextCursor) return;
      setCursors(value => [...value.slice(0, index + 1), state.page.nextCursor]);
      setState({ status: "loading" });
      setIndex(value => value + 1);
    },
  };
}
