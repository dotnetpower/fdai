import { useEffect, useRef, useState } from "preact/hooks";
import type { AsyncState } from "../components/ui";

export function useAdministrationRead<T>(
  owner: object,
  read: () => Promise<T>,
  epoch = 0,
) {
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<AsyncState<T>>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [observedAt, setObservedAt] = useState<string | null>(null);
  const currentOwner = useRef(owner);
  const pending = useRef(false);
  useEffect(() => {
    let active = true;
    if (currentOwner.current !== owner) {
      currentOwner.current = owner;
      setState({ status: "loading" });
      setObservedAt(null);
    }
    pending.current = true;
    setRefreshing(true);
    setError(null);
    setState((previous) => previous.status === "ready" ? previous : { status: "loading" });
    void read().then((data) => {
      if (!active) return;
      setState({ status: "ready", data });
      setObservedAt(new Date().toISOString());
    }).catch(() => {
      if (!active) return;
      // Arbitrary provider errors can contain private endpoint or identity data.
      setError("read-unavailable");
      setState((previous) => previous.status === "ready"
        ? previous : { status: "unavailable", message: "" });
    }).finally(() => {
      if (!active) return;
      pending.current = false;
      setRefreshing(false);
    });
    return () => { active = false; };
  }, [owner, epoch, revision]);
  return {
    state: currentOwner.current === owner ? state : { status: "loading" } as AsyncState<T>,
    refreshing: currentOwner.current !== owner || refreshing,
    error: currentOwner.current === owner ? error : null,
    observedAt: currentOwner.current === owner ? observedAt : null,
    refresh: () => {
      if (pending.current) return;
      pending.current = true;
      setRevision((value) => value + 1);
    },
  };
}
