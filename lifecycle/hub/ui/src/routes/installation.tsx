import { useState } from "preact/hooks";
import { hubApi, type InstallationDetail } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Badge, HealthBadge, OutcomeBadge } from "../components/badge";
import { Link } from "../components/link";
import { ConstraintResults } from "../components/constraint-results";
import { ExecutionSettingsPanel } from "../components/execution-settings";
import { ApplicationBindingPanel } from "../components/application-binding";
import { formatDurationMinutes, formatRelative, formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { deriveInstallationReadiness } from "../readiness-status";
import { reportSeverity, reportSeverityClass } from "../report-status";
import { commandsPath, configurationPackagesPath, installationsPath, planPath } from "../router";

type Tab = "constraints" | "entities" | "schedule" | "configuration" | "application";

function InstallationConfigurationPanel({ installation }: { installation: InstallationDetail }) {
  const [locale] = useHubLocale();
  const inventory = useAsync(() => hubApi.listConfigurations(), []);
  return (
    <section aria-label="Configuration">
      <h2 class="panel-title">
        {tr(locale, "Configuration", "구성")}
      </h2>
      <p class="note">
        {tr(
          locale,
          "Customer configuration is authored in customer Git and packaged with fdaictl configuration build/publish. The Hub stores only public metadata, ciphertext, and digests - never plaintext secret values.",
          "고객 구성은 고객 Git 저장소에서 작성되며 fdaictl configuration build/publish로 패키징됩니다. Hub는 공개 메타데이터, 암호문, 다이제스트만 보관하며 평문 비밀 값을 저장하지 않습니다.",
        )}
      </p>
      <dl class="catalog-trust">
        <dt>{tr(locale, "Active configuration digest", "활성 구성 다이제스트")}</dt>
        <dd class="mono inventory-value">{installation.configuration_digest}</dd>
        <dt>{tr(locale, "Reported schema revision", "보고된 스키마 개정 번호")}</dt>
        <dd>{installation.schema_revision}</dd>
        <dt>{tr(locale, "Installation region", "설치 리전")}</dt>
        <dd>{installation.settings.region}</dd>
        <dt>{tr(locale, "Allowed residency regions", "허용된 데이터 상주 리전")}</dt>
        <dd>{installation.settings.allowed_regions.join(", ") || "None"}</dd>
      </dl>
      <AsyncBoundary state={inventory}>
        {({ configurations }) => {
          const matched = configurations.find(
            (item) =>
              item.digest === installation.configuration_digest ||
              `sha256:${item.digest}` === installation.configuration_digest ||
              item.digest === installation.configuration_digest.replace(/^sha256:/, ""),
          );
          return matched ? (
            <div class="callout">
              <strong>
                {tr(
                  locale,
                  "Stored revision metadata (signature provenance: not recorded)",
                  "저장된 개정 메타데이터 (서명 출처: 미기록)",
                )}
              </strong>
              <p>
                {tr(
                  locale,
                  `Imported at ${formatTimestamp(matched.imported_at)} · ${matched.schema_key_count} schema key(s) · ${matched.override_count} Entity override block(s). Row presence alone does not establish independent package signature verification.`,
                  `가져온 시각 ${formatTimestamp(matched.imported_at)} · 스키마 키 ${matched.schema_key_count}개 · 엔티티 재정의 블록 ${matched.override_count}개. 레코드 존재만으로 독립적인 패키지 서명 검증이 입증되지는 않습니다.`,
                )}
              </p>
            </div>
          ) : (
            <p class="note">
              {tr(
                locale,
                "Full revision inventory is available on ",
                "전체 구성 개정 인벤토리는 다음 화면에서 확인할 수 있습니다: ",
              )}
              <Link href={configurationPackagesPath()}>Configuration packages</Link>.
            </p>
          );
        }}
      </AsyncBoundary>
    </section>
  );
}

export function InstallationPage({ installationId }: { installationId: string }) {
  const detail = useAsync(() => hubApi.getInstallation(installationId), [installationId]);
  const [tab, setTab] = useState<Tab>("constraints");
  const [notice, setNotice] = useState("");
  const [locale] = useHubLocale();

  return (
    <AsyncBoundary state={detail}>
      {(installation) => {
        const evaluation = installation.last_evaluation;
        const readiness = deriveInstallationReadiness(installation);
        const postureVariant =
          readiness.nextStep.posture === "ready"
            ? "ok"
            : readiness.nextStep.posture === "scheduled" || readiness.nextStep.posture === "in-progress"
            ? "info"
            : readiness.nextStep.posture === "waiting"
            ? "warn"
            : "fail";

        const postureLabel =
          readiness.nextStep.posture === "ready"
            ? tr(locale, "Ready", "준비됨")
            : readiness.nextStep.posture === "scheduled"
            ? tr(locale, "Scheduled", "예약됨")
            : readiness.nextStep.posture === "in-progress"
            ? tr(locale, "In progress", "진행 중")
            : readiness.nextStep.posture === "waiting"
            ? tr(locale, "Waiting", "대기 중")
            : readiness.nextStep.posture === "recovery-needed"
            ? tr(locale, "Recovery needed", "복구 필요")
            : tr(locale, "Blocked", "차단됨");

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

            <section class="catalog-panel" aria-label="Update readiness">
              <h2 class="panel-title">
                {tr(locale, "Update readiness and next step", "업데이트 준비 상태 및 다음 단계")}{" "}
                <Badge variant={postureVariant}>{postureLabel}</Badge>
              </h2>
              <p class="note">
                <strong>
                  {tr(locale, readiness.nextStep.headline, readiness.nextStep.headlineKo)}.
                </strong>{" "}
                {tr(locale, readiness.nextStep.detail, readiness.nextStep.detailKo)}{" "}
                <strong>
                  {tr(locale, "Decision owner:", "담당 주체:")}{" "}
                  {tr(locale, readiness.nextStep.owner, readiness.nextStep.ownerKo)}
                </strong>
              </p>
              <dl class="catalog-trust">
                {readiness.prerequisites.map((facet) => (
                  <div key={facet.id} style={{ display: "contents" }}>
                    <dt>{tr(locale, facet.label, facet.labelKo)}</dt>
                    <dd>
                      <Badge variant={facet.status}>{facet.status.toUpperCase()}</Badge>{" "}
                      {tr(locale, facet.summary, facet.summaryKo)}{" "}
                      <span class="soft">({facet.owner})</span>
                    </dd>
                  </div>
                ))}
              </dl>
              <details>
                <summary>
                  {tr(
                    locale,
                    "Time horizons: retention, execution schedule, and Plan validity",
                    "시간 경계: 환경 보존, 실행 일정 및 계획 유효성",
                  )}
                </summary>
                <dl class="catalog-trust">
                  <dt>{tr(locale, "Environment state anchor", "환경 상태 기준 시각")}</dt>
                  <dd>
                    {formatTimestamp(readiness.timeHorizons.environmentReportedAt)} (schema rev{" "}
                    {readiness.timeHorizons.schemaRevision})
                  </dd>
                  <dt>{tr(locale, "Daily execution schedule", "일일 실행 일정")}</dt>
                  <dd>
                    {tr(
                      locale,
                      readiness.timeHorizons.scheduleSummary,
                      readiness.timeHorizons.scheduleSummaryKo,
                    )}
                  </dd>
                  <dt>{tr(locale, "Current Plan validity", "현재 계획 유효성")}</dt>
                  <dd>
                    {tr(
                      locale,
                      readiness.timeHorizons.planValiditySummary,
                      readiness.timeHorizons.planValiditySummaryKo,
                    )}
                  </dd>
                </dl>
              </details>
            </section>

            {readiness.recovery && (
              <section class="catalog-panel" aria-label="Recovery and hold status">
                <h2 class="panel-title">
                  {tr(locale, "Failure, hold, and recovery timeline", "실패, 보류 및 복구 타임라인")}
                </h2>
                <dl class="catalog-trust">
                  <dt>{tr(locale, "Current cluster workload", "현재 클러스터 워크로드")}</dt>
                  <dd>
                    {tr(
                      locale,
                      readiness.recovery.currentWorkloadSummary,
                      readiness.recovery.currentWorkloadSummaryKo,
                    )}
                  </dd>
                  {readiness.recovery.latestFailedReport && (
                    <>
                      <dt>{tr(locale, "Original failure report", "최초 실패 보고")}</dt>
                      <dd>
                        <Link
                          href={planPath(
                            installation.installation_id,
                            readiness.recovery.latestFailedReport.plan_id,
                          )}
                        >
                          {readiness.recovery.latestFailedReport.plan_id}
                        </Link>{" "}
                        attempt {readiness.recovery.latestFailedReport.attempt}:{" "}
                        {readiness.recovery.latestFailedReport.outcome} (
                        {readiness.recovery.latestFailedReport.reason_code}) -{" "}
                        {readiness.recovery.latestFailedReport.summary}
                      </dd>
                    </>
                  )}
                  {readiness.recovery.activeHolds.length > 0 && (
                    <>
                      <dt>{tr(locale, "Active suppression holds", "활성 억제 보류")}</dt>
                      <dd>
                        {readiness.recovery.activeHolds
                          .map((h) => `${h.scope} (${h.origin}, until ${formatTimestamp(h.ends_at)})`)
                          .join("; ")}{" "}
                        · <Link href={commandsPath()}>{tr(locale, "Manage on Commands", "명령 화면에서 관리")}</Link>
                      </dd>
                    </>
                  )}
                  <dt>{tr(locale, "Safe recovery step", "안전한 복구 절차")}</dt>
                  <dd>
                    {tr(
                      locale,
                      readiness.recovery.nextActionSummary,
                      readiness.recovery.nextActionSummaryKo,
                    )}
                  </dd>
                </dl>
              </section>
            )}

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
              <button
                type="button"
                class={tab === "configuration" ? "on" : ""}
                aria-pressed={tab === "configuration"}
                onClick={() => setTab("configuration")}
              >
                Configuration
              </button>
              <button type="button" class={tab === "application" ? "on" : ""}
                aria-pressed={tab === "application"} onClick={() => setTab("application")}>
                Application
              </button>
            </nav>

            {tab === "schedule" && <ExecutionSettingsPanel
              installationId={installationId} blocked={installation.open_plan !== null}
              onSaved={() => {
                setNotice("Execution settings saved. No Plan was computed or applied.");
                detail.reload();
              }}
            />}

            {tab === "configuration" && (
              <InstallationConfigurationPanel installation={installation} />
            )}

            {tab === "application" && <ApplicationBindingPanel
              installationId={installationId} blocked={installation.open_plan !== null}
              onSaved={() => {
                setNotice("Application bound. No Plan was computed or applied.");
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
