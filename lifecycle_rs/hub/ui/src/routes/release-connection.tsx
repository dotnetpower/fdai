import { useEffect, useState } from "preact/hooks";
import { request } from "../api";
import { connectionSourceLabel, releaseStateLabel, tr, useHubLocale } from "../locale";

export type ReleaseConnection = {
  endpoint: string;
  configured_endpoint: string | null;
  revision: number;
  source: "saved" | "environment" | "local-default" | "deployment";
  editable: boolean;
  requires_migration: boolean;
};
export type ReleaseDetailSummary = {
  channels: string[];
  stencil_id: string | null;
  title: string | null;
  title_ko: string | null;
  enabled_workloads: string[];
  enabled_panel_count: number;
  component_digests: Record<string, string>;
  digest_verified: boolean;
};

export type ReleaseProvisionReceipt = {
  installation_id: string;
  release_id: string;
  plan_id: string | null;
  outcome: string;
  endpoint: string;
  stencil_id: string | null;
  enabled_workloads: string[];
  enabled_panel_count: number;
  component_digests: Record<string, string>;
  digest_verified: boolean;
  plan_issued_at: string;
  apply_required: boolean;
  effect_verified: false;
};

export type ReleaseCatalogPreview = {
  endpoint: string;
  revision: number;
  mode: string;
  expired: boolean;
  releases: { id: string; state: "draft" | "published" | "recalled" }[];
  release_count: number;
  build_verification: "not-performed";
  trusted: false;
  release_details?: Record<string, ReleaseDetailSummary>;
  enrolled_installations?: string[];
};

export async function provisionFromReleaseHub(
  installationId: string,
  releaseId: string | null = null,
): Promise<ReleaseProvisionReceipt> {
  return request<ReleaseProvisionReceipt>("/v1/release-hub/provision", {
    method: "POST",
    body: JSON.stringify({
      installation_id: installationId,
      release_id: releaseId,
      apply_state: false,
    }),
  });
}

export function releaseHubConfirmation(endpoint: string | null, revision: number): string {
  return `connect release hub ${endpoint?.replace(/\/$/, "") ?? "local-default"} ${revision}`;
}

export function connectionChange(endpoint: string | null, revision: number, reason: string) {
  const parsed = endpoint === null ? null : new URL(endpoint);
  if (parsed && (parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash)) {
    throw new Error("Release Hub endpoint must be an origin without credentials or a path.");
  }
  const normalized = parsed?.origin ?? null;
  return {
    endpoint: normalized, revision, reason,
    confirmation: releaseHubConfirmation(normalized, revision),
  };
}

export function hasCatalogTrustSource(connection: ReleaseConnection): boolean {
  return connection.source === "deployment";
}

export function ReleaseConnectionPanel(
  { onConnection }: { onConnection: (connection: ReleaseConnection) => void },
) {
  const [locale] = useHubLocale();
  const [connection, setConnection] = useState<ReleaseConnection | null>(null);
  const [endpoint, setEndpoint] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<ReleaseCatalogPreview | null>(null);
  const [error, setError] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saved, setSaved] = useState(false);
  const [selectedReleaseId, setSelectedReleaseId] = useState("");
  const [selectedInstallationId, setSelectedInstallationId] = useState("");
  const [provisionBusy, setProvisionBusy] = useState(false);
  const [provisionReceipt, setProvisionReceipt] = useState<ReleaseProvisionReceipt | null>(null);

  async function loadPreview() {
    setPreview(null);
    setPreviewError("");
    try {
      const data = await request<ReleaseCatalogPreview>("/v1/release-hub/catalog");
      setPreview(data);
      const firstPublished = data.releases.find((item) => item.state === "published")?.id ?? "";
      setSelectedReleaseId((current) => current || firstPublished);
      const firstInst = data.enrolled_installations?.[0] ?? "";
      setSelectedInstallationId((current) => current || firstInst);
    } catch (failure) {
      setPreviewError(failure instanceof Error ? failure.message : "Catalog read failed.");
    }
  }

  async function handleProvision() {
    if (!selectedInstallationId || !selectedReleaseId) return;
    setProvisionBusy(true);
    setError("");
    setProvisionReceipt(null);
    try {
      const receipt = await provisionFromReleaseHub(selectedInstallationId, selectedReleaseId);
      setProvisionReceipt(receipt);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Provisioning failed.");
    } finally {
      setProvisionBusy(false);
    }
  }

  async function load() {
    setLoading(true);
    setError("");
    try {
      const state = await request<ReleaseConnection>("/v1/release-hub/connection");
      setConnection(state);
      setEndpoint(state.endpoint);
      onConnection(state);
      if (!hasCatalogTrustSource(state)) await loadPreview();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Connection settings read failed.");
    } finally { setLoading(false); }
  }

  useEffect(() => { void load(); }, []);

  async function save(target: string | null) {
    if (!connection) return;
    setBusy(true);
    setError("");
    setSaved(false);
    setPreview(null);
    setPreviewError("");
    try {
      const state = await request<ReleaseConnection>("/v1/release-hub/connection", {
        method: "POST",
        body: JSON.stringify(connectionChange(target, connection.revision, reason)),
      });
      setConnection(state);
      setEndpoint(state.endpoint);
      onConnection(state);
      setReason("");
      setSaved(true);
      if (!hasCatalogTrustSource(state)) await loadPreview();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Connection settings update failed.");
    } finally { setBusy(false); }
  }

  return <section class="catalog-panel" aria-labelledby="release-connection-title">
    <h2 id="release-connection-title" class="panel-title">
      {tr(locale, "Release Hub connection", "Release Hub 연결")}
    </h2>
    <p class="note">{tr(locale,
      "Without a configured endpoint, this Hub reads the local Release Hub at http://127.0.0.1:8091. Previewing registrations does not verify builds or approve catalog trust.",
      "엔드포인트를 설정하지 않으면 로컬 Release Hub(http://127.0.0.1:8091)를 조회합니다. 등록 목록 조회는 빌드 검증이나 카탈로그 신뢰 승인이 아닙니다.")}</p>
    {loading && <p role="status">{tr(locale, "Loading Release Hub connection...", "Release Hub 연결을 확인하는 중...")}</p>}
    {error && <p class="banner fail" role="alert">{error}</p>}
    {connection && <>
      <p class="note">{tr(locale, "Current endpoint", "현재 엔드포인트")}:{" "}
        <code style={{ overflowWrap: "anywhere" }}>{connection.endpoint}</code>{" "}
        ({tr(locale, "source", "설정 출처")}: {connectionSourceLabel(connection.source, locale)}){" "}
        <button class="btn" type="button" disabled={busy || loading}
          onClick={() => void load()}>{tr(locale, "Refresh connection", "연결 새로고침")}</button></p>
      {connection.requires_migration && <p class="banner fail" role="alert">
        {tr(locale, "Run the Lifecycle Hub migrate command before saving connection settings.",
          "연결 설정을 저장하려면 Lifecycle Hub의 migrate 명령을 먼저 실행하세요.")}
      </p>}
      {!connection.editable && !connection.requires_migration && <p class="note">
        {tr(locale, "The remote catalog endpoint is managed by deployment configuration. Use the authenticated trust and Updates views below or in the navigation; an anonymous preview is not requested.",
          "원격 카탈로그 엔드포인트는 배포 구성에서 관리합니다. 아래 신뢰 설정과 탐색 메뉴의 업데이트 화면을 이용하세요. 익명 조회는 요청하지 않습니다.")}
      </p>}
      {connection.editable && <details open={Boolean(error || connection.source === "saved")}>
        <summary>{tr(locale, "Configure Release Hub endpoint", "Release Hub 엔드포인트 설정 변경")}</summary>
        <form onSubmit={(event) => { event.preventDefault(); void save(endpoint); }}>
          <label>{tr(locale, "Release Hub endpoint", "Release Hub 엔드포인트")}
            <input class="input" type="url" required value={endpoint}
              disabled={busy || loading || !connection.editable}
              onInput={(event) => setEndpoint(event.currentTarget.value)} />
          </label>
          <label>{tr(locale, "Connection change reason", "연결 변경 사유")}
            <input class="input" required minLength={3} maxLength={500} value={reason}
              disabled={busy || loading || !connection.editable}
              onInput={(event) => setReason(event.currentTarget.value)} />
          </label>
          <button class="btn primary" type="submit" disabled={busy || loading || !connection.editable}>
            {tr(locale, "Save endpoint", "엔드포인트 저장")}
          </button>{" "}
          <button class="btn" type="button" disabled={busy || loading || !connection.editable || reason.trim().length < 3}
            onClick={() => void save(null)}>{tr(locale, "Reset endpoint", "엔드포인트 초기화")}</button>
        </form>
      </details>}
    </>}
    {!connection && error && <button type="button" class="btn" disabled={loading} onClick={() => void load()}>
      {tr(locale, "Try again", "다시 시도")}
    </button>}
    {saved && <p role="status">{tr(locale,
      "Connection settings saved. Catalog trust is unchanged.",
      "연결 설정을 저장했습니다. 카탈로그 신뢰 설정은 변경하지 않았습니다.")}</p>}
    {previewError && <p class="banner fail" role="alert">
      {tr(locale, "Release Hub catalog unavailable", "Release Hub 카탈로그를 조회할 수 없습니다")}: {previewError}
    </p>}
    {preview && <section aria-label={tr(locale, "Registered catalog preview", "등록된 카탈로그 조회 결과")}>
      <p>{tr(locale, "Registered releases", "등록된 릴리스")}: {preview.release_count}</p>
      {preview.expired && <p class="note">{tr(locale,
        "The catalog export is expired. This preview does not make it eligible for import.",
        "카탈로그 내보내기 데이터의 유효기간이 만료되었습니다. 이 조회 결과로 가져오기가 허용되지는 않습니다.")}</p>}
      {preview.releases.length === 0
        ? <p>{tr(locale, "No registered releases. No sample releases are substituted.",
          "등록된 릴리스가 없습니다. 샘플 릴리스로 대체하지 않습니다.")}</p>
        : <ul class="release-preview-list">{preview.releases.map((release) => {
          const detail = preview.release_details?.[release.id];
          return <li key={release.id}>
            <code>{release.id}</code> ({releaseStateLabel(release.state, locale)})
            {detail?.stencil_id && <span class="soft">
              {" · "}{detail.stencil_id} · {detail.enabled_workloads.length} {tr(locale, "workloads", "워크로드")} · {detail.enabled_panel_count} {tr(locale, "menus", "메뉴")}
              {detail.digest_verified ? ` · ✓ ${tr(locale, "OCI digests verified", "OCI 다이제스트 검증됨")}` : ""}
            </span>}
          </li>;
        })}</ul>}
      {preview.releases.some((r) => r.state === "published") && (preview.enrolled_installations?.length ?? 0) > 0 && (
        <div class="quick-provision-box">
          <div class="quick-provision-header">
            <strong>{tr(locale, "Console Web deployment Plan", "콘솔 웹 배포 계획")}</strong>
            <span class="soft">{tr(
              locale,
              "Issue a signed upgrade Plan from the Release Hub Stencil manifest. The installation agent applies it and reports independently verified effects.",
              "Release Hub의 Stencil 매니페스트로 서명된 업그레이드 계획을 발급합니다. 설치 에이전트가 계획을 적용하고 독립적으로 검증한 효과를 보고합니다.",
            )}</span>
          </div>
          <div class="quick-provision-controls">
            <select
              class="input"
              aria-label={tr(locale, "Target installation", "대상 설치 환경")}
              value={selectedInstallationId}
              onChange={(event) => setSelectedInstallationId(event.currentTarget.value)}
            >
              {(preview.enrolled_installations ?? []).map((instId) => (
                <option key={instId} value={instId}>{instId}</option>
              ))}
            </select>
            <select
              class="input"
              aria-label={tr(locale, "Published release", "게시된 릴리스")}
              value={selectedReleaseId}
              onChange={(event) => setSelectedReleaseId(event.currentTarget.value)}
            >
              {preview.releases.filter((r) => r.state === "published").map((r) => (
                <option key={r.id} value={r.id}>
                  v{r.id}{preview.release_details?.[r.id]?.stencil_id ? ` (${preview.release_details[r.id]?.stencil_id})` : ""}
                </option>
              ))}
            </select>
            <button
              type="button"
              class="btn primary"
              disabled={provisionBusy || !selectedInstallationId || !selectedReleaseId}
              onClick={() => void handleProvision()}
            >
              {provisionBusy
                ? tr(locale, "Issuing Plan...", "계획 발급 중...")
                : tr(
                    locale,
                    `Issue Plan v${selectedReleaseId} -> ${selectedInstallationId}`,
                    `계획 발급 v${selectedReleaseId} -> ${selectedInstallationId}`,
                  )}
            </button>
          </div>
          {provisionReceipt && (
            <div class="banner ok" role="status">
              <strong>
                ✓ {tr(
                  locale,
                  `Plan issued for ${provisionReceipt.installation_id} to deploy v${provisionReceipt.release_id}.`,
                  `${provisionReceipt.installation_id} 환경에 v${provisionReceipt.release_id} 배포 계획을 발급했습니다.`,
                )}
              </strong>
              <div>
                Plan: {provisionReceipt.plan_id ?? "issued"} · {provisionReceipt.stencil_id ?? "stencil"} · {Object.keys(provisionReceipt.component_digests).length} OCI images
              </div>
              <div>
                {tr(
                  locale,
                  "Current and health remain unchanged until the installation agent reports independently verified effects.",
                  "설치 에이전트가 독립적으로 검증한 효과를 보고할 때까지 현재 릴리스와 상태는 변경되지 않습니다.",
                )}
              </div>
            </div>
          )}
        </div>
      )}
      <p class="note">{tr(locale, "Read-only preview. Build verification and catalog trust remain separate.",
        "읽기 전용 조회 결과입니다. 빌드 검증과 카탈로그 신뢰 승인은 별도로 수행합니다.")}</p>
    </section>}
  </section>;
}
