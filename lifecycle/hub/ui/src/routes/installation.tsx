import { useState } from "preact/hooks";
import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { HealthBadge, OutcomeBadge } from "../components/badge";
import { Link } from "../components/link";
import { ConstraintResults } from "../components/constraint-results";
import { ExecutionSettingsPanel } from "../components/execution-settings";
import { formatDurationMinutes, formatRelative, formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { reportSeverity, reportSeverityClass } from "../report-status";
import { installationsPath, planPath } from "../router";

type Tab = "constraints" | "entities" | "schedule";

export function InstallationPage({ installationId }: { installationId: string }) {
  const detail = useAsync(() => hubApi.getInstallation(installationId), [installationId]);
  const [tab, setTab] = useState<Tab>("constraints");
  const [notice, setNotice] = useState("");

  return (
    <AsyncBoundary state={detail}>
      {(installation) => {
        const evaluation = installation.last_evaluation;

        return (
          <>
            <div class="crumb">
              <Link href={installationsPath()}>Installations</Link> ›{" "}
              {installation.installation_id}
            </div>
            <div class="m-head">
              <div>
                <h1>{installation.installation_id}</h1>
                <div class="sub">
                  Channel {installation.settings.channel} · last report{" "}
                  {formatTimestamp(installation.reported_at)} (
                  {formatRelative(installation.reported_at)})
                </div>
                <div class="acts">
                  <button type="button" class="btn" onClick={detail.reload}>Refresh</button>
                </div>
              </div>
            </div>

            {notice && <p class="banner" role="status">{notice}</p>}
            <div class="kv">
              <div>
                <div class="k">Current release</div>
                <div class="v">{installation.current_release ?? "\u2013"}</div>
              </div>
              <div>
                <div class="k">Reported health</div>
                <div class="v">
                  <HealthBadge health={installation.health} />
                </div>
              </div>
              <div>
                <div class="k">Open Plan</div>
                <div class="v small">
                  {installation.open_plan ? (
                    <Link
                      href={planPath(installation.installation_id, installation.open_plan.plan_id)}
                    >
                      {installation.open_plan.plan_id}
                    </Link>
                  ) : (
                    "\u2013"
                  )}
                </div>
              </div>
              <div>
                <div class="k">Maintenance window</div>
                <div class="v small">
                  {installation.settings.windows.length > 0 ? (
                    installation.settings.windows.map((window, index) => (
                      <div key={index} class="maintenance-window">
                        {window.start} {window.timezone}
                        <div class="soft">{formatDurationMinutes(window.duration_minutes)} window</div>
                      </div>
                    ))
                  ) : (
                    "\u2013"
                  )}
                </div>
              </div>
            </div>

            <nav class="tabs" aria-label="Installation sections">
              <button
                type="button"
                class={tab === "constraints" ? "on" : ""}
                aria-pressed={tab === "constraints"}
                onClick={() => setTab("constraints")}
              >
                Constraints and next Plan
              </button>
              <button
                type="button"
                class={tab === "entities" ? "on" : ""}
                aria-pressed={tab === "entities"}
                onClick={() => setTab("entities")}
              >
                Entities
              </button>
              <button type="button" class={tab === "schedule" ? "on" : ""}
                aria-pressed={tab === "schedule"} onClick={() => setTab("schedule")}>
                Execution schedule
              </button>
              <button type="button" disabled title="Not available yet">
                Configuration
              </button>
            </nav>

            {tab === "schedule" && <ExecutionSettingsPanel
              installationId={installationId} blocked={installation.open_plan !== null}
              onSaved={() => {
                setNotice("Execution settings saved. No Plan was computed or applied.");
                detail.reload();
              }}
            />}

            {tab === "constraints" && (
              <section aria-label="Constraints">
                <h2 class="panel-title">
                  {evaluation?.target_release_id ? `Target ${evaluation.target_release_id}` : "Latest evaluation"}
                  {evaluation && <OutcomeBadge outcome={evaluation.outcome} />}
                </h2>
                {evaluation ? (
                  <>
                    <p class="note">Evaluated {formatTimestamp(evaluation.evaluated_at)}</p>
                    <ConstraintResults checks={evaluation.checks} />
                  </>
                ) : <p class="note">The Hub has not evaluated this installation yet.</p>}
                {installation.suppressions.length > 0 && (
                  <>
                    <h2 class="panel-title">Active suppressions</h2>
                    <ul class="list">
                      {installation.suppressions.map((suppression) => (
                        <li key={`${suppression.scope}-${suppression.starts_at}`}>
                          <span class={`ic ${suppression.origin === "failure" ? "fail" : "warn"}`}>
                            ■
                          </span>
                          <span>
                            {suppression.scope} ({suppression.origin})
                          </span>
                          <span class="soft">until {formatTimestamp(suppression.ends_at)}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </section>
            )}

            {tab === "entities" && (
              <section aria-label="Entities">
                <h2 class="panel-title">
                  Entities <span class="hint">Reported by the installation agent</span>
                </h2>
                <div class="table-scroll"><table class="t">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Kind</th>
                      <th>Version</th>
                      <th>State</th>
                    </tr>
                  </thead>
                  <tbody>
                    {installation.entities.map((entity) => (
                      <tr key={entity.entity_id}>
                        <td>
                          {entity.entity_id}
                          {!entity.managed && (
                            <div class="soft">Unmanaged{entity.ownership_gap && <> - <code>{entity.ownership_gap}</code></>}</div>
                          )}
                        </td>
                        <td>{entity.kind}</td>
                        <td>{entity.release_id ?? "Not reported"}</td>
                        <td>
                          {entity.health === null ? "Not reported" : <HealthBadge health={entity.health} />}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table></div>
              </section>
            )}

            {installation.reports.length > 0 && (
              <section aria-label="Reports">
                <h2 class="panel-title">Reports</h2>
                <ol class="timeline">
                  {installation.reports.map((report) => (
                    <li
                      key={`${report.plan_id}-${report.attempt}`}
                      class={reportSeverityClass(reportSeverity(report.outcome))}
                    >
                      <div class="when">{formatTimestamp(report.received_at)}</div>
                      <Link href={planPath(installationId, report.plan_id)}>
                        {report.plan_id}
                      </Link>{" "}
                      attempt {report.attempt}: {report.outcome} ({report.reason_code})
                    </li>
                  ))}
                </ol>
              </section>
            )}
          </>
        );
      }}
    </AsyncBoundary>
  );
}
