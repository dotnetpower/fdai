import { useState } from "preact/hooks";
import type { InstallationSummary } from "../api";
import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { HealthBadge, OutcomeBadge } from "../components/badge";
import { Link } from "../components/link";
import { formatRelative } from "../format";
import { useAsync } from "../hooks/use-async";
import { installationPath } from "../router";

/** "Open now" vs "Opens in ..." - a past `starts_at` alone can't tell a currently open daily
 * window from one that hasn't started, so the backend tells us explicitly which one this is. */
function WindowCell({ installation }: { installation: InstallationSummary }) {
  if (installation.next_window_open) {
    return (
      <>
        Open now
        <div class="soft">closes {formatRelative(installation.next_window_ends_at)}</div>
      </>
    );
  }
  if (installation.next_window_starts_at === null) return <>{"\u2013"}</>;
  return <>opens {formatRelative(installation.next_window_starts_at)}</>;
}

export function InstallationsPage() {
  const installations = useAsync(() => hubApi.listInstallations(), []);
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState<"id" | "channel" | "outcome">("id");

  return (
    <>
      <div class="m-head">
        <h1>Installations</h1>
        <div class="acts">
          <button
            type="button"
            class="btn"
            onClick={installations.reload}
            disabled={installations.status === "loading"}
          >
            Refresh
          </button>
        </div>
      </div>
      <div class="table-toolbar">
        <label for="installation-search">Find installation</label>
        <input
          id="installation-search"
          class="input"
          type="search"
          value={query}
          placeholder="Filter by installation ID"
          onInput={(event) => setQuery(event.currentTarget.value)}
        />
        <label for="installation-sort">Sort by</label>
        <select
          id="installation-sort"
          class="input"
          value={sortBy}
          onChange={(event) => setSortBy(event.currentTarget.value as "id" | "channel" | "outcome")}
        >
          <option value="id">Installation ID</option>
          <option value="channel">Channel</option>
          <option value="outcome">Update status</option>
        </select>
      </div>
      <AsyncBoundary state={installations} layout="table">
        {({ installations: rows }) => {
          const visible = [...rows]
            .filter((row) =>
              row.installation_id.toLowerCase().includes(query.trim().toLowerCase()),
            )
            .sort((a, b) => {
              if (sortBy === "channel") {
                return a.channel.localeCompare(b.channel) || a.installation_id.localeCompare(b.installation_id);
              }
              if (sortBy === "outcome") {
                return (
                  (a.outcome ?? "").localeCompare(b.outcome ?? "") ||
                  a.installation_id.localeCompare(b.installation_id)
                );
              }
              return a.installation_id.localeCompare(b.installation_id);
            });
          return rows.length === 0 ? (
            <p class="empty">No installations enrolled.</p>
          ) : visible.length === 0 ? (
            <p class="empty">No installations match this filter.</p>
          ) : (
            <div class="table-scroll">
              <table class="t">
                <thead>
                  <tr>
                    <th>Installation</th>
                    <th>Channel · range</th>
                    <th>Current</th>
                    <th>Target</th>
                    <th>Next window</th>
                    <th>Update status</th>
                    <th>Reported health</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((installation) => (
                    <tr key={installation.installation_id}>
                      <td>
                        <Link href={installationPath(installation.installation_id)}>
                          {installation.installation_id}
                        </Link>
                      </td>
                      <td class="mono">
                        {installation.channel}
                        <div class="soft">{installation.version_range}</div>
                      </td>
                      <td>{installation.current_release ?? "\u2013"}</td>
                      <td>
                        <b>{installation.target_release_id ?? "\u2013"}</b>
                      </td>
                      <td>
                        <WindowCell installation={installation} />
                      </td>
                      <td>
                        <OutcomeBadge outcome={installation.outcome} />
                      </td>
                      <td>
                        <HealthBadge health={installation.health} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }}
      </AsyncBoundary>
    </>
  );
}
