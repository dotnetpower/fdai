import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { HilQueueItem } from "../types";

interface Props {
  readonly client: ReadApiClient;
}

type State =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly items: readonly HilQueueItem[] }
  | { readonly status: "error"; readonly message: string };

export function HilQueueRoute({ client }: Props) {
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await client.listHilQueue({ limit: 100 });
        if (!cancelled) setState({ status: "ready", items: page.items });
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  if (state.status === "loading") return <div class="empty">Loading…</div>;
  if (state.status === "error") {
    return (
      <div class="empty error">Failed to load HIL queue: {state.message}</div>
    );
  }
  if (state.items.length === 0) {
    return (
      <div class="notice">
        No pending HIL items. Approvals happen via Teams / Adaptive Cards
        (see docs/roadmap/user-rbac-and-identity.md § 7).
      </div>
    );
  }

  return (
    <section class="card">
      <h2>Pending HIL approvals ({state.items.length})</h2>
      <p class="muted">
        Read-only view. Approve or reject through the ChatOps channel —
        the console does not expose an approval button.
      </p>
      <table>
        <thead>
          <tr>
            <th>Idempotency key</th>
            <th>Action kind</th>
            <th>Reason</th>
            <th>Requested at</th>
            <th>Correlation</th>
          </tr>
        </thead>
        <tbody>
          {state.items.map((item) => (
            <tr key={item.idempotency_key}>
              <td class="mono">{item.idempotency_key}</td>
              <td class="mono">{item.action_kind}</td>
              <td>{item.reason}</td>
              <td class="mono">{item.requested_at}</td>
              <td class="mono muted">{item.correlation_id ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
