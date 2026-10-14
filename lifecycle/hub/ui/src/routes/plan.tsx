import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Link } from "../components/link";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { installationPath, installationsPath } from "../router";

const FAILED_OUTCOMES = new Set(["rejected", "rolled-back"]);

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
      {(record) => (
        <>
          <div class="crumb">
            <Link href={installationsPath()}>Installations</Link> ›{" "}
            <Link href={installationPath(installationId)}>{installationId}</Link> ›{" "}
            {record.plan_id}
          </div>
          <div class="m-head">
            <div>
              <h1>
                {record.plan_id} · target {record.target_release_id}
              </h1>
              <div class="sub">
                Sequence {record.sequence} · {record.plan_type} · expires{" "}
                {formatTimestamp(record.expires_at)}
              </div>
            </div>
            <div class="acts">
              <span class={`badge ${record.status === "open" ? "info" : "mute"}`}>
                {record.status}
              </span>
            </div>
          </div>

          <div class="cols">
            <section aria-label="Events and reports">
              <div class="panel-title">
                Events <span class="hint">Recorded as the Hub and the agent exchanged them</span>
              </div>
              <ol class="timeline">
                {record.events.map((event, index) => (
                  <li key={index} class="ok">
                    <div class="when">{formatTimestamp(event.recorded_at)}</div>
                    {event.kind}
                  </li>
                ))}
              </ol>

              <div class="panel-title">Reports</div>
              {record.reports.length === 0 ? (
                <p class="note">No execution report yet.</p>
              ) : (
                <ul class="list">
                  {record.reports.map((report) => (
                    <li key={report.attempt}>
                      <span class={`ic ${FAILED_OUTCOMES.has(report.outcome) ? "fail" : "ok"}`}>
                        {FAILED_OUTCOMES.has(report.outcome) ? "✕" : "✓"}
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

            <section aria-label="Recomputes">
              <div class="panel-title">
                Recomputes <span class="hint">Every time the Hub re-evaluated this Plan</span>
              </div>
              <ul class="list">
                {record.evaluations.map((evaluation, index) => (
                  <li key={index}>
                    <span class="ic ok">{index + 1}</span>
                    <span>{evaluation.outcome}</span>
                    <span class="soft">{formatTimestamp(evaluation.evaluated_at)}</span>
                  </li>
                ))}
              </ul>
              <div class="panel-title">Entities in this Plan</div>
              <p class="note">{record.entity_ids.join(", ")}</p>
            </section>
          </div>
        </>
      )}
    </AsyncBoundary>
  );
}
