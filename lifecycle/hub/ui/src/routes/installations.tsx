import { useMemo, useState } from "preact/hooks";
import type { InstallationSummary } from "../api";
import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { HealthBadge, OutcomeBadge } from "../components/badge";
import { Link } from "../components/link";
import { formatRelative } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { installationPath } from "../router";

/** "Open now" vs "Opens in ..." - a past `starts_at` alone can't tell a currently open daily
 * window from one that hasn't started, so the backend tells us explicitly which one this is. */
function WindowCell({ installation }: { installation: InstallationSummary }) {
  const [locale] = useHubLocale();
  if (installation.next_window_open) {
    return (
      <>
        {tr(locale, "Open now", "현재 열림")}
        <div class="soft">
          {locale === "ko"
            ? `${formatRelative(installation.next_window_ends_at, new Date(), locale)} 종료`
            : `closes ${formatRelative(installation.next_window_ends_at)}`}
        </div>
      </>
    );
  }
  if (installation.next_window_starts_at === null) return <>{"\u2013"}</>;
  return (
    <>
      {locale === "ko"
        ? `${formatRelative(installation.next_window_starts_at, new Date(), locale)} 시작`
        : `opens ${formatRelative(installation.next_window_starts_at)}`}
    </>
  );
}

export function filterAndSortInstallations(
  rows: readonly InstallationSummary[],
  query: string,
  sortBy: "id" | "channel" | "outcome" = "id",
): InstallationSummary[] {
  const needle = query.trim().toLowerCase();
  return [...rows]
    .filter((row) => needle === "" || row.installation_id.toLowerCase().includes(needle))
    .sort((a, b) => {
      if (sortBy === "channel") {
        return (
          a.channel.localeCompare(b.channel) ||
          a.installation_id.localeCompare(b.installation_id)
        );
      }
      if (sortBy === "outcome") {
        return (
          (a.outcome ?? "").localeCompare(b.outcome ?? "") ||
          a.installation_id.localeCompare(b.installation_id)
        );
      }
      return a.installation_id.localeCompare(b.installation_id);
    });
}

export function InstallationsPage() {
  const [locale] = useHubLocale();
  const installations = useAsync(() => hubApi.listInstallations(), []);
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState<"id" | "channel" | "outcome">("id");
  const visible = useMemo(
    () =>
      installations.status === "ready"
        ? filterAndSortInstallations(installations.data.installations, query, sortBy)
        : [],
    [installations, query, sortBy],
  );

  return (
    <>
      <div class="m-head">
        <h1>{tr(locale, "Installations", "설치 환경")}</h1>
        <div class="acts">
          <button
            type="button"
            class="btn"
            onClick={installations.reload}
            disabled={installations.status === "loading"}
          >
            {tr(locale, "Refresh", "새로 고침")}
          </button>
        </div>
      </div>
      <div class="table-toolbar">
        <label for="installation-search">{tr(locale, "Find installation", "설치 환경 검색")}</label>
        <input
          id="installation-search"
          class="input"
          type="search"
          value={query}
          placeholder={tr(locale, "Filter by installation ID", "설치 ID로 필터링")}
          onInput={(event) => setQuery(event.currentTarget.value)}
        />
        <label for="installation-sort">{tr(locale, "Sort by", "정렬 기준")}</label>
        <select
          id="installation-sort"
          class="input"
          value={sortBy}
          onChange={(event) => setSortBy(event.currentTarget.value as "id" | "channel" | "outcome")}
        >
          <option value="id">{tr(locale, "Installation ID", "설치 ID")}</option>
          <option value="channel">{tr(locale, "Channel", "채널")}</option>
          <option value="outcome">{tr(locale, "Update status", "업데이트 상태")}</option>
        </select>
      </div>
      <AsyncBoundary state={installations} layout="table">
        {({ installations: rows }) => {
          return rows.length === 0 ? (
            <p class="empty">{tr(locale, "No installations enrolled.", "등록된 설치 환경이 없습니다.")}</p>
          ) : visible.length === 0 ? (
            <p class="empty">{tr(locale, "No installations match this filter.", "필터 조건에 맞는 설치 환경이 없습니다.")}</p>
          ) : (
            <div class="table-scroll">
              <table class="t">
                <thead>
                  <tr>
                    <th>{tr(locale, "Installation", "설치 환경")}</th>
                    <th>{tr(locale, "Channel · range", "채널 · 버전 범위")}</th>
                    <th>{tr(locale, "Current", "현재 버전")}</th>
                    <th>{tr(locale, "Target", "대상 버전")}</th>
                    <th>{tr(locale, "Next window", "다음 유지보수 구간")}</th>
                    <th>{tr(locale, "Update status", "업데이트 상태")}</th>
                    <th>{tr(locale, "Reported health", "보고된 상태")}</th>
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
