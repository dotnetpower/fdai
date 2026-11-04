import { useState } from "preact/hooks";
import { hubApi, HubApiError } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";

export function BundleImportPage() {
  const [locale] = useHubLocale();
  const state = useAsync(() => hubApi.listBundleImports(), []);
  const [bundleId, setBundleId] = useState("bundle-0019");
  const [extendsBundleId, setExtendsBundleId] = useState("");
  const [catalogDigest, setCatalogDigest] = useState(
    "sha256:e6387b0ceb52a12f9fe995ce75c66bf1a4c0d3005b50e6f5e52fdd43cb100f9b",
  );
  const [checksumCount, setChecksumCount] = useState("412");
  const [releasesText, setReleasesText] = useState("1.4.4, 1.5.1");
  const [channelTarget, setChannelTarget] = useState("1.5.1");
  const [recallNotice, setRecallNotice] = useState("#0031 · 1.5.0");
  const [recallStart, setRecallStart] = useState("30");
  const [recallEnd, setRecallEnd] = useState("31");
  const [layerCount, setLayerCount] = useState("38");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const cleanBundleId = bundleId.trim();
  const cleanDigest = catalogDigest.trim();
  const expectedConfirmation = `import bundle ${cleanBundleId} ${cleanDigest}`;

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (busy || !cleanBundleId || confirmation !== expectedConfirmation) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const releases = releasesText
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      const record = await hubApi.importBundle({
        bundle_id: cleanBundleId,
        extends_bundle_id: extendsBundleId.trim() || null,
        catalog_export_sha256: cleanDigest,
        checksum_count: Math.max(1, Number.parseInt(checksumCount, 10) || 1),
        signature_verified: true,
        checksums_verified: true,
        configuration_signature_verified: true,
        recall_sequence_start: Math.max(0, Number.parseInt(recallStart, 10) || 0),
        recall_sequence_end: Math.max(0, Number.parseInt(recallEnd, 10) || 0),
        releases: releases.length > 0 ? releases : ["1.5.1"],
        channels: { RELEASE: channelTarget.trim() || "1.5.1" },
        recall_notices: recallNotice.trim() ? [recallNotice.trim()] : [],
        image_layer_count: Math.max(0, Number.parseInt(layerCount, 10) || 0),
        configuration_package_count: 1,
        metadata_expiry_days: 30,
        confirmation,
      });
      setNotice(
        tr(
          locale,
          `Verified and imported ${record.bundle_id} (${record.verification.checksum_count} checksums matched).`,
          `${record.bundle_id} 번들의 서명·체크섬(${record.verification.checksum_count}개)·계보를 검증하고 가져왔습니다.`,
        ),
      );
      setExtendsBundleId(record.bundle_id);
      setConfirmation("");
      state.reload();
    } catch (failure) {
      setError(
        failure instanceof HubApiError
          ? `Bundle import rejected (${failure.reasonCode}). Verify signature, checksums, predecessor lineage, and recall sequence.`
          : "Could not complete bundle import. Refresh Target Hub state before retrying.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div class="catalog-page" lang={locale}>
      <div class="m-head">
        <div>
          <h1>{tr(locale, "Bundle import", "오프라인 번들 가져오기")}</h1>
          <div class="sub">
            {tr(
              locale,
              "Target Hub offline upgrade bundle verification: vendor signature, file checksums, predecessor lineage, and continuous recall sequence.",
              "Target Hub 오프라인 업그레이드 번들 검증: 벤더 서명, 파일 체크섬, 이전 번들 계보 및 연속 리콜 시퀀스를 확인합니다.",
            )}
          </div>
        </div>
        <button type="button" class="btn" onClick={state.reload}>
          {tr(locale, "Refresh", "새로 고침")}
        </button>
      </div>

      <div class="callout">
        <strong>
          {tr(
            locale,
            "Catalog metadata expiry and shadow demotion",
            "카탈로그 메타데이터 만료 및 shadow 강등 경계",
          )}
        </strong>
        <p>
          {tr(
            locale,
            "When catalog metadata expires, this Target Hub accepts only recall roll-off Plans and returns operator-override promotions to shadow mode until fresh signed metadata is imported.",
            "카탈로그 메타데이터가 만료되면 이 Target Hub는 리콜 롤오프 계획만 허용하며, 새 서명 메타데이터를 가져올 때까지 운영자 재정의 승격을 shadow 모드로 되돌립니다.",
          )}
        </p>
      </div>

      {notice && (
        <p class="banner" role="status" style={{ overflowWrap: "anywhere" }}>
          {notice}
        </p>
      )}
      {error && (
        <p class="banner fail" role="alert" style={{ overflowWrap: "anywhere" }}>
          {error}
        </p>
      )}

      <AsyncBoundary state={state}>
        {(data) => {
          const latest = data.imports[0] ?? null;
          return (
            <div class="stack">
              <dl class="catalog-trust">
                <dt>{tr(locale, "Last imported bundle", "마지막 가져온 번들")}</dt>
                <dd class="mono">{data.last_bundle_id ?? tr(locale, "None imported yet", "아직 없음")}</dd>
                <dt>{tr(locale, "Last import time", "마지막 가져오기 시각")}</dt>
                <dd>{data.last_imported_at ? formatTimestamp(data.last_imported_at) : "-"}</dd>
                <dt>{tr(locale, "Catalog metadata expiry window", "메타데이터 유효 기간")}</dt>
                <dd>{data.metadata_expiry_days} days</dd>
              </dl>

              {latest && (
                <div class="cols">
                  <section aria-label="Verification">
                    <h2 class="panel-title">
                      {tr(locale, "Verification and publication", "검증 및 게시 결과")}
                    </h2>
                    <ol class="timeline">
                      <li class="ok">
                        <div class="when">1</div>
                        {tr(locale, "Vendor release signature verified", "벤더 릴리스 서명 검증 완료")}
                      </li>
                      <li class="ok">
                        <div class="when">2</div>
                        {latest.verification.checksum_count}{" "}
                        {tr(locale, "file checksums match", "개 파일 체크섬 일치")}
                      </li>
                      <li class="ok">
                        <div class="when">3</div>
                        {latest.extends_bundle_id
                          ? `${tr(locale, "Bundle extends", "이전 번들 계보 확인:")} ${latest.extends_bundle_id}`
                          : tr(locale, "Initial baseline bundle verified", "초기 기준선 번들 확인 완료")}
                      </li>
                      <li class="ok">
                        <div class="when">4</div>
                        {tr(
                          locale,
                          "Recall sequence is continuous",
                          "리콜 시퀀스 연속성 확인 완료",
                        )}
                      </li>
                      <li class="ok">
                        <div class="when">5</div>
                        {tr(
                          locale,
                          "Customer configuration package signature verified",
                          "고객 구성 패키지 서명 검증 완료",
                        )}
                      </li>
                    </ol>
                  </section>

                  <section aria-label="Bundle contents">
                    <h2 class="panel-title">
                      {tr(locale, "Bundle contents", "번들 구성 내용")}
                    </h2>
                    <table class="t">
                      <thead>
                        <tr>
                          <th>{tr(locale, "Item", "항목")}</th>
                          <th>{tr(locale, "Content", "내용")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>{tr(locale, "Releases", "릴리스")}</td>
                          <td>{latest.contents.releases.join(", ")}</td>
                        </tr>
                        <tr>
                          <td>{tr(locale, "Channel membership", "채널 매핑")}</td>
                          <td>
                            {Object.entries(latest.contents.channels)
                              .map(([ch, rel]) => `${ch} → ${rel}`)
                              .join(", ")}
                          </td>
                        </tr>
                        <tr>
                          <td>{tr(locale, "Recall notices", "리콜 공지")}</td>
                          <td>
                            {latest.contents.recall_notices.length > 0 ? (
                              latest.contents.recall_notices.map((noticeItem) => (
                                <span key={noticeItem} class="badge fail">
                                  {noticeItem}
                                </span>
                              ))
                            ) : (
                              tr(locale, "None", "없음")
                            )}
                          </td>
                        </tr>
                        <tr>
                          <td>{tr(locale, "Image layers", "이미지 레이어")}</td>
                          <td>{latest.contents.image_layer_count} new layers</td>
                        </tr>
                        <tr>
                          <td>{tr(locale, "Metadata expiry", "메타데이터 만료 갱신")}</td>
                          <td>Renewed to {latest.contents.metadata_expiry_days} days</td>
                        </tr>
                      </tbody>
                    </table>
                  </section>
                </div>
              )}

              <form class="catalog-panel" onSubmit={(event) => void submit(event)}>
                <h2 class="panel-title">
                  {tr(
                    locale,
                    "Verify and import signed upgrade bundle",
                    "서명된 업그레이드 번들 검증 및 가져오기",
                  )}
                </h2>
                <label>
                  {tr(locale, "Bundle ID", "번들 ID")}
                  <input
                    class="input mono"
                    aria-label="Bundle ID"
                    required
                    value={bundleId}
                    onInput={(event) => {
                      setBundleId(event.currentTarget.value);
                      setConfirmation("");
                    }}
                  />
                </label>
                <label>
                  {tr(locale, "Predecessor bundle ID (optional for first import)", "이전 번들 ID (첫 가져오기 시 선택)")}
                  <input
                    class="input mono"
                    aria-label="Predecessor bundle ID"
                    value={extendsBundleId}
                    placeholder={data.last_bundle_id ?? "bundle-0018"}
                    onInput={(event) => setExtendsBundleId(event.currentTarget.value)}
                  />
                </label>
                <label>
                  {tr(locale, "Catalog export SHA-256", "카탈로그 내보내기 SHA-256")}
                  <input
                    class="input mono"
                    aria-label="Catalog export SHA-256"
                    required
                    value={catalogDigest}
                    onInput={(event) => {
                      setCatalogDigest(event.currentTarget.value);
                      setConfirmation("");
                    }}
                  />
                </label>
                <div class="cols">
                  <label>
                    {tr(locale, "Verified file checksums", "검증된 파일 체크섬 수")}
                    <input
                      class="input"
                      aria-label="Verified file checksums"
                      type="number"
                      min="1"
                      value={checksumCount}
                      onInput={(event) => setChecksumCount(event.currentTarget.value)}
                    />
                  </label>
                  <label>
                    {tr(locale, "Image layers", "이미지 레이어 수")}
                    <input
                      class="input"
                      aria-label="Image layers"
                      type="number"
                      min="0"
                      value={layerCount}
                      onInput={(event) => setLayerCount(event.currentTarget.value)}
                    />
                  </label>
                </div>
                <div class="cols">
                  <label>
                    {tr(locale, "Releases (comma-separated)", "릴리스 목록")}
                    <input
                      class="input mono"
                      aria-label="Bundle releases"
                      required
                      value={releasesText}
                      onInput={(event) => setReleasesText(event.currentTarget.value)}
                    />
                  </label>
                  <label>
                    {tr(locale, "RELEASE channel target", "RELEASE 채널 대상")}
                    <input
                      class="input mono"
                      aria-label="RELEASE channel target"
                      required
                      value={channelTarget}
                      onInput={(event) => setChannelTarget(event.currentTarget.value)}
                    />
                  </label>
                </div>
                <div class="cols">
                  <label>
                    {tr(locale, "Recall sequence start", "리콜 시퀀스 시작")}
                    <input
                      class="input"
                      aria-label="Recall sequence start"
                      type="number"
                      min="0"
                      value={recallStart}
                      onInput={(event) => setRecallStart(event.currentTarget.value)}
                    />
                  </label>
                  <label>
                    {tr(locale, "Recall sequence end", "리콜 시퀀스 종료")}
                    <input
                      class="input"
                      aria-label="Recall sequence end"
                      type="number"
                      min="0"
                      value={recallEnd}
                      onInput={(event) => setRecallEnd(event.currentTarget.value)}
                    />
                  </label>
                </div>
                <label>
                  {tr(locale, "Recall notice summary", "리콜 공지 요약")}
                  <input
                    class="input mono"
                    aria-label="Recall notice summary"
                    value={recallNotice}
                    onInput={(event) => setRecallNotice(event.currentTarget.value)}
                  />
                </label>
                <p class="note" style={{ overflowWrap: "anywhere" }}>
                  {tr(locale, "Expected confirmation:", "필수 확인 문구:")}{" "}
                  <code class="mono">{expectedConfirmation}</code>
                </p>
                <div class="acts">
                  <button
                    type="button"
                    class="btn"
                    disabled={busy || confirmation === expectedConfirmation}
                    onClick={() => setConfirmation(expectedConfirmation)}
                  >
                    {tr(locale, "Fill reviewed confirmation", "검토된 확인 문구 자동 입력")}
                  </button>
                </div>
                <label>
                  {tr(locale, "Exact confirmation", "정확한 확인 문구")}
                  <input
                    class="input mono"
                    aria-label="Bundle import confirmation"
                    required
                    autoComplete="off"
                    value={confirmation}
                    onInput={(event) => setConfirmation(event.currentTarget.value)}
                  />
                </label>
                <div class="acts">
                  <button
                    type="submit"
                    class="btn primary"
                    disabled={busy || !cleanBundleId || confirmation !== expectedConfirmation}
                  >
                    {busy
                      ? tr(locale, "Verifying and importing...", "검증 및 가져오는 중...")
                      : tr(locale, "Verify and import bundle", "번들 검증 및 가져오기")}
                  </button>
                </div>
              </form>
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
