import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuditItem, AuditPage } from "../types";

interface Props {
  readonly client: ReadApiClient;
}

interface State {
  readonly items: readonly AuditItem[];
  readonly nextCursor: string | null;
  readonly status: "loading" | "ready" | "error";
  readonly error?: string;
}

const PAGE_SIZE = 25;

export function AuditRoute({ client }: Props) {
  const [state, setState] = useState<State>({
    items: [],
    nextCursor: null,
    status: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await client.listAudit({ limit: PAGE_SIZE });
        if (!cancelled) {
          setState({
            items: page.items,
            nextCursor: page.next_cursor,
            status: "ready",
          });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            items: [],
            nextCursor: null,
            status: "error",
            error: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  const loadMore = async (cursor: string): Promise<void> => {
    try {
      const page: AuditPage = await client.listAudit({
        limit: PAGE_SIZE,
        cursor,
      });
      setState((prev) => ({
        ...prev,
        items: [...prev.items, ...page.items],
        nextCursor: page.next_cursor,
      }));
    } catch (err) {
      setState((prev) => ({
        ...prev,
        status: "error",
        error: err instanceof Error ? err.message : String(err),
      }));
    }
  };

  if (state.status === "loading") return <div class="empty">Loading…</div>;
  if (state.status === "error" && state.items.length === 0) {
    return (
      <div class="empty error">Failed to load audit log: {state.error}</div>
    );
  }
  if (state.items.length === 0) {
    return <div class="empty">Audit log is empty.</div>;
  }

  return (
    <div class="stack">
      <section class="card">
        <h2>Audit log</h2>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Recorded at</th>
              <th>Actor</th>
              <th>Action kind</th>
              <th>Mode</th>
              <th>Event id</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {state.items.map((row) => (
              <tr key={row.seq}>
                <td class="mono">{row.seq}</td>
                <td class="mono">{row.recorded_at}</td>
                <td>{row.actor}</td>
                <td class="mono">{row.action_kind}</td>
                <td>
                  <span class={`badge ${row.mode}`}>{row.mode}</span>
                </td>
                <td class="mono">{row.event_id}</td>
                <td>
                  <details>
                    <summary>view</summary>
                    <pre class="mono">{JSON.stringify(row.entry, null, 2)}</pre>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {state.nextCursor !== null ? (
        <button
          type="button"
          class="primary"
          onClick={() => {
            void loadMore(state.nextCursor!);
          }}
        >
          Load more
        </button>
      ) : (
        <p class="muted">End of log.</p>
      )}
    </div>
  );
}
