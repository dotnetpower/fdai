import { useEffect, useState } from "preact/hooks";
import { request } from "../api";
import { tr, useHubLocale } from "../locale";

export type ReleaseConnection = {
  endpoint: string;
  configured_endpoint: string | null;
  revision: number;
  source: "saved" | "environment" | "local-default" | "deployment";
  editable: boolean;
  requires_migration: boolean;
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
};

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

  async function loadPreview() {
    setPreview(null);
    setPreviewError("");
    try {
      setPreview(await request<ReleaseCatalogPreview>("/v1/release-hub/catalog"));
    } catch (failure) {
      setPreviewError(failure instanceof Error ? failure.message : "Catalog read failed.");
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
      await loadPreview();
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
      await loadPreview();
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
        ({tr(locale, "source", "설정 출처")}: {connection.source})</p>
      {connection.requires_migration && <p class="banner fail" role="alert">
        {tr(locale, "Run the Lifecycle Hub migrate command before saving connection settings.",
          "연결 설정을 저장하려면 Lifecycle Hub의 migrate 명령을 먼저 실행하세요.")}
      </p>}
      {!connection.editable && !connection.requires_migration && <p class="note">
        {tr(locale, "The remote catalog endpoint is managed by deployment configuration.",
          "원격 카탈로그 엔드포인트는 배포 구성에서 관리합니다.")}
      </p>}
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
          onClick={() => void save(null)}>{tr(locale, "Reset endpoint", "엔드포인트 초기화")}</button>{" "}
        <button class="btn" type="button" disabled={busy || loading}
          onClick={() => void load()}>{tr(locale, "Refresh connection", "연결 새로고침")}</button>
      </form>
    </>}
    {!connection && error && <button class="btn" disabled={loading} onClick={() => void load()}>
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
        : <ul>{preview.releases.map((release) => <li key={release.id}>
          <code>{release.id}</code> ({release.state})
        </li>)}</ul>}
      <p class="note">{tr(locale, "Read-only preview. Build verification and catalog trust remain separate.",
        "읽기 전용 조회 결과입니다. 빌드 검증과 카탈로그 신뢰 승인은 별도로 수행합니다.")}</p>
    </section>}
  </section>;
}
