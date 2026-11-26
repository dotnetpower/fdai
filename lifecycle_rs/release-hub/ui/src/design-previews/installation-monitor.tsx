import { useState } from "preact/hooks";
import { previewPath } from "../../../../hub/ui/src/design-previews/model";
import { filterRegisteredInstallations, recentlyReportedVersions, REGISTERED_INSTALLATIONS, reportFreshness, type ReportFilter, type ReportFreshness } from "./installation-monitor.data";
import "./installation-monitor.css";

const REPORT_LABELS: Record<ReportFreshness, string> = {
  recent: "최근 보고", stale: "보고 지연", "no-report": "보고 없음",
};

function exampleTime(value: string | null): string {
  return value ? `${value.slice(0, 10)} ${value.slice(11, 16)} UTC` : "보고 없음";
}

export function InstallationMonitor() {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ReportFilter>("all");
  const registrations = REGISTERED_INSTALLATIONS.records;
  const records = filterRegisteredInstallations(query, filter);
  const recent = registrations.filter((item) => reportFreshness(item) === "recent").length;
  const stale = registrations.filter((item) => reportFreshness(item) === "stale").length;
  const missing = registrations.length - recent - stale;
  const versions = recentlyReportedVersions();

  return <div class="dp-page dp-install-monitor">
    <header class="dp-install-monitor-heading">
      <span class="dp-kicker">RELEASE HUB / INSTALLATIONS</span>
      <h1>등록 설치 현황</h1>
      <p>등록된 설치가 자체 보고한 사용 버전을 살펴봅니다. 설치 계획과 실제 사용은 구분합니다.</p>
    </header>
    <nav class="dp-install-monitor-nav" aria-label="Release Hub 페이지">
      <a href={previewPath("release", "edition")}>← 릴리스 계통</a>
      <span aria-current="page">설치 현황</span>
    </nav>
    <section class="dp-install-monitor-boundary" aria-label="조회 범위">
      <div><strong>미등록 설치</strong><p>등록하지 않은 설치의 수와 사용 버전은 알 수 없습니다. 아래 집계에 포함하지 않습니다.</p></div>
      <span>조회 범위 밖</span>
    </section>
    <p class="dp-install-monitor-asof">예시 스냅샷 · {exampleTime(REGISTERED_INSTALLATIONS.exampleSnapshotAt)} · 실시간 데이터 아님</p>
    <dl class="dp-install-monitor-metrics">
      <div><dt>등록 설치</dt><dd>{registrations.length}<small>이 예시의 등록 목록만</small></dd></div>
      <div><dt>최근 보고</dt><dd>{recent}<small>예시 기준 15분 이내</small></dd></div>
      <div><dt>보고 지연</dt><dd>{stale}<small>현재 사용 버전 확인 불가</small></dd></div>
      <div><dt>보고 없음</dt><dd>{missing}<small>사용 버전 알 수 없음</small></dd></div>
    </dl>
    <section class="dp-install-monitor-versions" aria-label="최근 보고된 사용 버전">
      <div><h2>최근 보고된 사용 버전</h2><p>최근 보고 {recent}건만 집계 · 지연·미보고·미등록 제외</p></div>
      <ul>{versions.map(({ version, count }) => <li key={version}>
        <span class="dp-mono">v{version}</span>
        <span class="dp-install-monitor-bar" aria-hidden="true"><span style={{ width: `${count / recent * 100}%` }} /></span>
        <strong>{count}개</strong>
      </li>)}</ul>
    </section>
    <section class="dp-install-monitor-list" aria-labelledby="install-monitor-list-title">
      <div class="dp-install-monitor-list-head">
        <div><h2 id="install-monitor-list-title">등록 설치 목록</h2><p>최신 계획 버전은 실제 사용 버전이 아닙니다.</p></div>
        <div class="dp-toolbar">
          <label>설치 검색<input type="search" value={query} onInput={(event) => setQuery(event.currentTarget.value)} placeholder="이름, ID 또는 버전" /></label>
          <label>보고 상태<select value={filter} onChange={(event) => setFilter(event.currentTarget.value as ReportFilter)}>
            <option value="all">모든 등록 설치</option><option value="recent">최근 보고</option>
            <option value="stale">보고 지연</option><option value="no-report">보고 없음</option>
          </select></label>
        </div>
      </div>
      <div class="dp-table-wrap" role="region" aria-label="등록 설치 표" tabIndex={0}>
        <table class="dp-table">
          <caption>{records.length}개 표시 · 등록된 예시 설치만</caption>
          <thead><tr><th scope="col">설치 / 채널</th><th scope="col">최근 보고된 사용 버전</th><th scope="col">계획 대상</th><th scope="col">마지막 자체 보고</th><th scope="col">보고 상태</th></tr></thead>
          <tbody>{records.map((item) => {
            const freshness = reportFreshness(item);
            return <tr key={item.id}>
              <td><strong>{item.name}</strong><small class="dp-mono">{item.id} · {item.channel}</small></td>
              <td>{freshness === "recent" ? <strong class="dp-mono">v{item.reportedVersion}</strong> : <>확인 불가{item.reportedVersion && <small>이전 보고: v{item.reportedVersion}</small>}</>}</td>
              <td class="dp-mono">{item.targetVersion ? `v${item.targetVersion}` : "계획 없음"}</td>
              <td class="dp-mono">{exampleTime(item.reportedAt)}</td>
              <td><span class={`dp-install-monitor-status dp-install-monitor-status-${freshness}`}>{REPORT_LABELS[freshness]}</span></td>
            </tr>;
          })}</tbody>
        </table>
        {records.length === 0 && <p class="dp-empty">일치하는 등록 설치 예시가 없습니다. 검색어나 필터를 변경해 주세요.</p>}
      </div>
    </section>
    <p class="dp-install-monitor-footnote">모든 등록·보고·시각은 디자인 검토용 가상 데이터입니다. 보고된 버전은 독립적으로 검증한 배포 효과가 아니며 실제 모니터링·등록 기능은 연결되지 않았습니다.</p>
  </div>;
}
