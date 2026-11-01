import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { OutcomeBadge } from "../components/badge";
import { Link } from "../components/link";
import { ConstraintResults } from "../components/constraint-results";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { planDispatchEligibility, planDisplayStatus } from "../plan-status";
import { reportSeverity, reportSeverityClass, reportSeverityIcon } from "../report-status";
import { installationPath, installationsPath } from "../router";

// "issued" is a genuine positive event (the Hub signed a new Plan). "superseded" and "reported"
// are procedural - they don't by themselves say whether the outcome was good, so they stay
// neutral; a report's own severity is already shown in the Reports list below.
const EVENT_CLASS: Partial<Record<string, string>> = { issued: "ok" };

export function PlanPage({
  installationId,
  planId,
}: {
  installationId: string;
  planId: string;
}) {
  const plan = useAsync(() => hubApi.getPlan(installationId, planId), [installationId, planId]);

  return (
    <AsyncBoundary state={plan}>
      {(record) => {
        const status = planDisplayStatus(record);
        const eligibility = planDispatchEligibility(record);
        return (
          <>
            <div class="crumb">
              <Link href={installationsPath()}>Installations</Link> ›{" "}
              <Link href={installationPath(installationId)}>{installationId}</Link> ›{" "}
              {record.plan_id}
            </div>
            <div class="m-head">
              <div>
                <h1>{record.plan_id}</h1>
                <div class="sub">
                  Sequence {record.sequence} · installation {installationId} ·{" "}
                  <span>{eligibility.label}</span>
                </div>
              </div>
              <div class="acts">
                <span class={`badge ${status.variant}`}>
                  {status.label}
                </span>
                <button type="button" class="btn" onClick={plan.reload}>
                  Refresh
                </button>
              </div>
            </div>

            <div class="kv">
              <div>
                <div class="k">Target release</div>
                <div class="v">{record.target_release_id}</div>
              </div>
              <div>
                <div class="k">Plan type</div>
                <div class="v small">{record.plan_type}</div>
              </div>
              <div>
                <div class="k">Entities</div>
                <div class="v small">{record.entity_ids.join(", ")}</div>
              </div>
              <div>
                <div class="k">Expires</div>
                <div class="v small">{formatTimestamp(record.expires_at)}</div>
              </div>
            </div>

            <section aria-label="Constraint evaluations" class="constraint-section">
              <h2 class="panel-title">Constraint evaluations</h2>
              {record.evaluations.length === 0 ? (
                <p class="note">No evaluations recorded for this Plan.</p>
              ) : (
                record.evaluations.map((evaluation, index) => (
                  <details key={index} open={index === record.evaluations.length - 1}>
                    <summary>
                      <span>{formatTimestamp(evaluation.evaluated_at)}</span>{" "}
                      <OutcomeBadge outcome={evaluation.outcome} />
                    </summary>
                    <ConstraintResults checks={evaluation.checks} />
                  </details>
                ))
              )}
            </section>

            <div class="cols">
              <section aria-label="Plan events">
                <h2 class="panel-title">
                  Events <span class="hint">Recorded as the Hub and the agent exchanged them</span>
                </h2>
                <ol class="timeline">
                  {record.events.map((event, index) => (
                    <li key={index} class={EVENT_CLASS[event.kind] ?? ""}>
                      <div class="when">{formatTimestamp(event.recorded_at)}</div>
                      {event.kind}
                    </li>
                  ))}
                </ol>
              </section>
              <section aria-label="Execution reports">
                <h2 class="panel-title">Execution reports</h2>
                {record.reports.length === 0 ? (
                  <p class="note">No execution report yet.</p>
                ) : (
                  <ul class="list">
                    {record.reports.map((report) => (
                      <li key={report.attempt}>
                        <span class={`ic ${reportSeverityClass(reportSeverity(report.outcome))}`}>
                          {reportSeverityIcon(report.outcome)}
                        </span>
                        <span>
                          attempt {report.attempt}: {report.outcome} ({report.reason_code})
                          <div class="soft">{report.summary}</div>
                        </span>
                        <span class="soft">{formatTimestamp(report.received_at)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </>
        );
      }}
    </AsyncBoundary>
  );
}
