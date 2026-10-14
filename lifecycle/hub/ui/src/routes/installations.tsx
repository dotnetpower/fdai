import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { HealthBadge, OutcomeBadge } from "../components/badge";
import { Link } from "../components/link";
import { formatRelative } from "../format";
import { useAsync } from "../hooks/use-async";
import { installationPath } from "../router";

export function InstallationsPage() {
  const installations = useAsync(() => hubApi.listInstallations(), []);

  return (
    <>
      <div class="crumb">Installations</div>
      <div class="m-head">
        <div>
          <h1>Installations</h1>
          <div class="sub">Enrolled installations this Hub cell plans for</div>
        </div>
      </div>
      <AsyncBoundary state={installations}>
        {({ installations: rows }) =>
          rows.length === 0 ? (
            <p class="empty">No installation is enrolled yet.</p>
          ) : (
            <table class="t">
              <thead>
                <tr>
                  <th>Installation</th>
                  <th>Channel · range</th>
                  <th>Current</th>
                  <th>Target</th>
                  <th>Next window</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((installation) => (
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
                      {installation.next_window_starts_at
                        ? formatRelative(installation.next_window_starts_at)
                        : "\u2013"}
                    </td>
                    <td>
                      <OutcomeBadge outcome={installation.outcome} />{" "}
                      <HealthBadge health={installation.health} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </AsyncBoundary>
    </>
  );
}
