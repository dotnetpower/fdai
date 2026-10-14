import { useState } from "preact/hooks";
import { hubApi, type CandidateCheck } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { HealthBadge, OutcomeBadge } from "../components/badge";
import { Link } from "../components/link";
import { formatDurationMinutes, formatRelative, formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { installationPath, installationsPath, planPath } from "../router";

type Tab = "constraints" | "entities";

function ConstraintRow({ check }: { check: CandidateCheck }) {
  const passed = check.blocks.length === 0;
  return (
    <li>
      <span class={`ic ${passed ? "ok" : "warn"}`}>{passed ? "✓" : "◷"}</span>
      <span>
        <b>{check.release_id}</b>
        {passed ? " passed every constraint" : ` blocked by ${check.blocks[0]!.reason_code}`}
      </span>
      <span class="soft">{passed ? "Passed" : "Blocked"}</span>
    </li>
  );
}

export function InstallationPage({ installationId }: { installationId: string }) {
  const detail = useAsync(() => hubApi.getInstallation(installationId), [installationId]);
  const [tab, setTab] = useState<Tab>("constraints");

  return (
    <AsyncBoundary state={detail}>
      {(installation) => {
        const evaluation = installation.last_evaluation;
        const window = installation.settings.windows[0];

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
              </div>
            </div>

            <div class="kv">
              <div>
                <div class="k">Current release</div>
                <div class="v">{installation.current_release ?? "\u2013"}</div>
              </div>
              <div>
                <div class="k">Health</div>
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
                  {window
                    ? `${window.start} ${window.timezone} · ${formatDurationMinutes(window.duration_minutes)}`
                    : "\u2013"}
                </div>
              </div>
            </div>

            <nav class="tabs" aria-label="Installation sections">
              <button
                type="button"
                class={tab === "constraints" ? "on" : ""}
                onClick={() => setTab("constraints")}
              >
                Constraints and next Plan
              </button>
              <button
                type="button"
                class={tab === "entities" ? "on" : ""}
                onClick={() => setTab("entities")}
              >
                Entities
              </button>
              <span class="soft" title="Not built in this scope">
                Configuration
              </span>
            </nav>

            {tab === "constraints" && (
              <section aria-label="Constraints">
                <div class="panel-title">
                  {evaluation ? `Target ${evaluation.target_release_id}` : "No recompute yet"}
                  {evaluation && <OutcomeBadge outcome={evaluation.outcome} />}
                </div>
                {!evaluation && (
                  <p class="note">This installation hasn't been recomputed yet.</p>
                )}
                {evaluation && (
                  <ul class="list">
                    {evaluation.checks.map((check) => (
                      <ConstraintRow key={check.release_id} check={check} />
                    ))}
                  </ul>
                )}
                {installation.suppressions.length > 0 && (
                  <>
                    <div class="panel-title">Active suppressions</div>
                    <ul class="list">
                      {installation.suppressions.map((suppression) => (
                        <li key={`${suppression.scope}-${suppression.starts_at}`}>
                          <span class="ic wait">■</span>
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
                <div class="panel-title">
                  Entities <span class="hint">Reported by the installation agent</span>
                </div>
                <table class="t">
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
                          {!entity.managed && <div class="soft">Unmanaged</div>}
                        </td>
                        <td>{entity.kind}</td>
                        <td>{entity.release_id}</td>
                        <td>
                          <HealthBadge health={entity.health} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            )}

            {installation.reports.length > 0 && (
              <section aria-label="Reports">
                <div class="panel-title">Reports</div>
                <ol class="timeline">
                  {installation.reports.map((report) => (
                    <li
                      key={`${report.plan_id}-${report.attempt}`}
                      class={report.outcome === "rejected" || report.outcome === "rolled-back"
                        ? "fail"
                        : "ok"}
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
