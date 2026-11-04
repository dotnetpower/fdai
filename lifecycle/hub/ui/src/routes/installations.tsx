import { useEffect, useMemo, useState } from "preact/hooks";
import type { InstallationSummary } from "../api";
import { hubApi, request } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { HealthBadge, OutcomeBadge } from "../components/badge";
import { Link } from "../components/link";
import { formatRelative } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { installationPath } from "../router";
import {
  provisionFromReleaseHub,
  type ReleaseCatalogPreview,
  type ReleaseProvisionReceipt,
} from "./release-connection";

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
  const [releasePreview, setReleasePreview] = useState<ReleaseCatalogPreview | null>(null);
  const [selectedReleaseId, setSelectedReleaseId] = useState("");
  const [selectedInstallationId, setSelectedInstallationId] = useState("");
  const [provisionBusy, setProvisionBusy] = useState(false);
  const [provisionError, setProvisionError] = useState("");
  const [provisionReceipt, setProvisionReceipt] = useState<ReleaseProvisionReceipt | null>(null);

  useEffect(() => {
    let active = true;
    void request<ReleaseCatalogPreview>("/v1/release-hub/catalog")
      .then((data) => {
        if (!active) return;
        setReleasePreview(data);
        const firstPublished = data.releases.find((item) => item.state === "published")?.id ?? "";
        setSelectedReleaseId((current) => current || firstPublished);
      })
      .catch(() => {
        /* Optional local Release Hub preview; ignore when unconfigured in isolated tests. */
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (installations.status === "ready" && installations.data.installations.length > 0) {
      const firstId = installations.data.installations[0]?.installation_id ?? "";
      setSelectedInstallationId((current) => current || firstId);
    }
  }, [installations.status]);

  const publishedReleases = useMemo(
    () => (releasePreview?.releases ?? []).filter((item) => item.state === "published"),
    [releasePreview],
  );
  const selectedDetail = selectedReleaseId
    ? releasePreview?.release_details?.[selectedReleaseId]
    : undefined;

  async function runProvision(targetInstallationId: string, releaseId: string) {
    if (!targetInstallationId || !releaseId) return;
    setProvisionBusy(true);
    setProvisionError("");
    setProvisionReceipt(null);
    try {
      const receipt = await provisionFromReleaseHub(targetInstallationId, releaseId, true);
      setProvisionReceipt(receipt);
      installations.reload();
    } catch (failure) {
      setProvisionError(failure instanceof Error ? failure.message : "Provisioning failed.");
    } finally {
      setProvisionBusy(false);
    }
  }

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
        <div>
          <h1>{tr(locale, "Installations", "설치 환경")}</h1>
          <p class="sub">
            {tr(
              locale,
              "Provision and monitor enrolled Console Web installations from verified Release Hub Stencil releases.",
              "검증된 Release Hub Stencil 릴리스를 기반으로 등록된 콘솔 웹 설치 환경을 원클릭 프로비저닝하고 상태를 모니터링합니다.",
            )}
          </p>
        </div>
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
      {publishedReleases.length > 0 && installations.status === "ready" && installations.data.installations.length > 0 && (
        <section class="quick-provision-card" aria-label={tr(locale, "Console Web 1-Click Provisioning", "콘솔 웹 원클릭 프로비저닝")}>
          <div class="quick-provision-top">
            <div>
              <h2 class="panel-title">
                {tr(locale, "Console Web 1-Click Provisioning", "콘솔 웹 원클릭 프로비저닝")}
              </h2>
              <p class="note">
                {tr(
                  locale,
                  `Connected to Release Hub (${releasePreview?.endpoint ?? "http://127.0.0.1:8091"}) · ${publishedReleases.length} published Stencil release(s) ready.`,
                  `Release Hub(${releasePreview?.endpoint ?? "http://127.0.0.1:8091"}) 연결됨 · 즉시 배포 가능한 게시 릴리스 ${publishedReleases.length}개 준비됨.`,
                )}
              </p>
            </div>
            {selectedDetail && (
              <div class="quick-provision-badges">
                {selectedDetail.stencil_id && <span class="badge">{selectedDetail.stencil_id}</span>}
                <span class="badge">
                  {selectedDetail.enabled_workloads.length} {tr(locale, "workloads", "워크로드")} · {selectedDetail.enabled_panel_count} {tr(locale, "menus", "콘솔 메뉴")}
                </span>
                {selectedDetail.digest_verified && (
                  <span class="badge ok">
                    ✓ {tr(locale, "OCI Digests Verified", "OCI 다이제스트 검증됨")}
                  </span>
                )}
              </div>
            )}
          </div>
          <div class="quick-provision-controls">
            <select
              class="input"
              aria-label={tr(locale, "Target installation", "대상 설치 환경")}
              value={selectedInstallationId}
              onChange={(event) => setSelectedInstallationId(event.currentTarget.value)}
            >
              {installations.data.installations.map((inst) => (
                <option key={inst.installation_id} value={inst.installation_id}>
                  {inst.installation_id} ({tr(locale, "current", "현재")}: {inst.current_release ?? "\u2013"})
                </option>
              ))}
            </select>
            <select
              class="input"
              aria-label={tr(locale, "Published release", "게시된 릴리스")}
              value={selectedReleaseId}
              onChange={(event) => setSelectedReleaseId(event.currentTarget.value)}
            >
              {publishedReleases.map((rel) => {
                const detail = releasePreview?.release_details?.[rel.id];
                return (
                  <option key={rel.id} value={rel.id}>
                    v{rel.id}{detail?.stencil_id ? ` · ${detail.stencil_id} (${detail.enabled_workloads.length}W/${detail.enabled_panel_count}M)` : ""}
                  </option>
                );
              })}
            </select>
            <button
              type="button"
              class="btn primary"
              disabled={provisionBusy || !selectedInstallationId || !selectedReleaseId}
              onClick={() => void runProvision(selectedInstallationId, selectedReleaseId)}
            >
              {provisionBusy
                ? tr(locale, "Provisioning...", "프로비저닝 중...")
                : tr(
                    locale,
                    `1-Click Provision v${selectedReleaseId} -> ${selectedInstallationId}`,
                    `원클릭 프로비저닝 v${selectedReleaseId} -> ${selectedInstallationId}`,
                  )}
            </button>
          </div>
          {provisionError && <p class="banner fail" role="alert">{provisionError}</p>}
          {provisionReceipt && (
            <div class="banner ok" role="status">
              <strong>
                ✓ {tr(
                  locale,
                  `Provisioned ${provisionReceipt.installation_id} to v${provisionReceipt.release_id}`,
                  `${provisionReceipt.installation_id} 환경을 v${provisionReceipt.release_id} 릴리스로 프로비저닝 완료`,
                )}
              </strong>
              <div class="soft mono" style={{ marginTop: "4px" }}>
                Plan: {provisionReceipt.plan_id ?? "issued"} · Stencil: {provisionReceipt.stencil_id ?? "custom"} · Workloads: {provisionReceipt.enabled_workloads.join(", ")} ({provisionReceipt.enabled_panel_count} menus)
              </div>
            </div>
          )}
        </section>
      )}
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
                        {selectedReleaseId && installation.current_release !== selectedReleaseId && (
                          <div style={{ marginTop: "4px" }}>
                            <button
                              type="button"
                              class="btn"
                              disabled={provisionBusy}
                              onClick={() => void runProvision(installation.installation_id, selectedReleaseId)}
                            >
                              {tr(locale, `Provision v${selectedReleaseId}`, `v${selectedReleaseId} 적용`)}
                            </button>
                          </div>
                        )}
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
