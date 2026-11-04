import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { OutcomeBadge } from "../components/badge";
import { Link } from "../components/link";
import { ConstraintResults } from "../components/constraint-results";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
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
  const [locale] = useHubLocale();
  const plan = useAsync(() => hubApi.getPlan(installationId, planId), [installationId, planId]);

  return (
    <AsyncBoundary state={plan}>
      {(record) => {
        const status = planDisplayStatus(record, Date.now(), locale);
        const eligibility = planDispatchEligibility(record, Date.now(), locale);
        return (
          <>
            <div class="crumb">
              <Link href={installationsPath()}>{tr(locale, "Installations", "설치 환경")}</Link> ›{" "}
              <Link href={installationPath(installationId)}>{installationId}</Link> ›{" "}
              {record.plan_id}
            </div>
            <div class="m-head">
              <div>
                <h1>{record.plan_id}</h1>
                <div class="sub">
                  {tr(locale, "Sequence", "시퀀스")} {record.sequence} ·{" "}
                  {tr(locale, "installation", "설치 환경")} {installationId} ·{" "}
                  <span>{eligibility.label}</span>
                </div>
              </div>
              <div class="acts">
                <span class={`badge ${status.variant}`}>
                  {status.label}
                </span>
                <button type="button" class="btn" onClick={plan.reload}>
                  {tr(locale, "Refresh", "새로 고침")}
                </button>
              </div>
            </div>

            <div class="kv">
              <div>
                <div class="k">{tr(locale, "Target release", "대상 릴리스")}</div>
                <div class="v">{record.target_release_id}</div>
              </div>
              <div>
                <div class="k">{tr(locale, "Plan type", "계획 유형")}</div>
                <div class="v small">{record.plan_type}</div>
              </div>
              <div>
                <div class="k">{tr(locale, "Entities", "엔티티")}</div>
                <div class="v small">{record.entity_ids.join(", ")}</div>
              </div>
              <div>
                <div class="k">{tr(locale, "Expires", "만료 시각")}</div>
                <div class="v small">{formatTimestamp(record.expires_at, undefined, locale)}</div>
              </div>
            </div>

            <section aria-label={tr(locale, "Constraint evaluations", "제약 조건 평가")} class="constraint-section">
              <h2 class="panel-title">{tr(locale, "Constraint evaluations", "제약 조건 평가")}</h2>
              {record.evaluations.length === 0 ? (
                <p class="note">
                  {tr(locale, "No evaluations recorded for this Plan.", "이 계획에 대해 기록된 평가가 없습니다.")}
                </p>
              ) : (
                record.evaluations.map((evaluation, index) => (
                  <details key={index} open={index === record.evaluations.length - 1}>
                    <summary>
                      <span>{formatTimestamp(evaluation.evaluated_at, undefined, locale)}</span>{" "}
                      <OutcomeBadge outcome={evaluation.outcome} />
                    </summary>
                    <ConstraintResults checks={evaluation.checks} />
                  </details>
                ))
              )}
            </section>

            <div class="cols">
              <section aria-label={tr(locale, "Plan events", "계획 이벤트")}>
                <h2 class="panel-title">
                  {tr(locale, "Events", "이벤트")}{" "}
                  <span class="hint">
                    {tr(
                      locale,
                      "Recorded as the Hub and the agent exchanged them",
                      "Hub와 에이전트 간 교환된 순서대로 기록됨",
                    )}
                  </span>
                </h2>
                <ol class="timeline">
                  {record.events.map((event, index) => (
                    <li key={index} class={EVENT_CLASS[event.kind] ?? ""}>
                      <div class="when">{formatTimestamp(event.recorded_at, undefined, locale)}</div>
                      {event.kind}
                    </li>
                  ))}
                </ol>
              </section>
              <section aria-label={tr(locale, "Execution reports", "실행 보고서")}>
                <h2 class="panel-title">{tr(locale, "Execution reports", "실행 보고서")}</h2>
                {record.reports.length === 0 ? (
                  <p class="note">{tr(locale, "No execution report yet.", "아직 실행 보고서가 없습니다.")}</p>
                ) : (
                  <ul class="list">
                    {record.reports.map((report) => (
                      <li key={report.attempt}>
                        <span class={`ic ${reportSeverityClass(reportSeverity(report.outcome))}`}>
                          {reportSeverityIcon(report.outcome)}
                        </span>
                        <span>
                          {tr(locale, "attempt", "시도")} {report.attempt}: {report.outcome} ({report.reason_code})
                          <div class="soft">{report.summary}</div>
                        </span>
                        <span class="soft">{formatTimestamp(report.received_at, undefined, locale)}</span>
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
