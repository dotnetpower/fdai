import { useState } from "preact/hooks";
import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Badge } from "../components/badge";
import { Link } from "../components/link";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { installationPath } from "../router";

export function AuditPage() {
  const [locale] = useHubLocale();
  const [installationFilter, setInstallationFilter] = useState("");
  const [appliedFilter, setAppliedFilter] = useState("");
  const auditState = useAsync(
    () => hubApi.listAudit(appliedFilter, 100),
    [appliedFilter],
  );

  return (
    <div class="inventory-page" lang={locale}>
      <div class="m-head">
        <div>
          <h1>{tr(locale, "Hash-chained audit", "해시 체인 감사 기록")}</h1>
          <div class="sub">
            {tr(
              locale,
              "Append-only Hub lifecycle audit records with cryptographic chain verification.",
              "암호화 해시 체인으로 무결성을 검증하는 추가 전용 Hub 수명 주기 감사 기록입니다.",
            )}
          </div>
        </div>
        <div class="acts">
          <button
            type="button"
            class="btn"
            disabled={auditState.status === "loading"}
            onClick={auditState.reload}
          >
            {tr(locale, "Refresh", "새로 고침")}
          </button>
        </div>
      </div>

      <form
        class="table-toolbar"
        onSubmit={(event) => {
          event.preventDefault();
          setAppliedFilter(installationFilter.trim());
        }}
      >
        <label for="audit-installation-filter">
          {tr(locale, "Filter by installation", "설치 ID 필터")}
        </label>
        <input
          id="audit-installation-filter"
          class="input"
          value={installationFilter}
          placeholder="e.g. prod-korea"
          onInput={(event) => setInstallationFilter(event.currentTarget.value)}
        />
        <button type="submit" class="btn">
          {tr(locale, "Apply filter", "필터 적용")}
        </button>
        {appliedFilter && (
          <button
            type="button"
            class="btn"
            onClick={() => {
              setInstallationFilter("");
              setAppliedFilter("");
            }}
          >
            {tr(locale, "Clear", "초기화")}
          </button>
        )}
      </form>

      <AsyncBoundary state={auditState} layout="table">
        {(data) => (
          <>
            <div class="callout">
              <strong>
                {tr(locale, "Chain integrity:", "체인 무결성:")}{" "}
                <Badge variant={data.chain_intact ? "ok" : "fail"}>
                  {data.chain_intact
                    ? tr(locale, "Verified intact", "무결성 검증됨")
                    : tr(locale, "Chain mismatch detected", "체인 불일치 감지됨")}
                </Badge>
              </strong>
              <p>
                {tr(
                  locale,
                  "Every record hashes its sequence, timestamp, action, installation, subject, and previous record hash. Secret values and customer operational payloads never enter this store.",
                  "모든 레코드는 순번, 타임스탬프, 작업, 설치 ID, 대상 및 이전 레코드 해시를 함께 해시합니다. 비밀 값과 운영 데이터는 이 저장소에 기록되지 않습니다.",
                )}
              </p>
            </div>
            {data.records.length === 0 ? (
              <p class="empty">
                {tr(locale, "No audit records match this view.", "조건에 맞는 감사 기록이 없습니다.")}
              </p>
            ) : (
              <div class="table-scroll">
                <table class="t">
                  <thead>
                    <tr>
                      <th>{tr(locale, "Seq", "순번")}</th>
                      <th>{tr(locale, "Recorded", "기록 시각")}</th>
                      <th>{tr(locale, "Action", "작업")}</th>
                      <th>{tr(locale, "Installation", "설치")}</th>
                      <th>{tr(locale, "Subject", "대상")}</th>
                      <th>{tr(locale, "Record hash", "레코드 해시")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.records.map((record) => (
                      <tr key={record.sequence}>
                        <td class="mono">#{record.sequence}</td>
                        <td>{formatTimestamp(record.recorded_at)}</td>
                        <td class="mono">{record.action}</td>
                        <td>
                          <Link href={installationPath(record.installation_id)}>
                            {record.installation_id}
                          </Link>
                        </td>
                        <td class="mono inventory-value">{record.subject}</td>
                        <td class="mono inventory-value" title={record.record_hash}>
                          {record.record_hash.slice(0, 16)}...
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </AsyncBoundary>
    </div>
  );
}
