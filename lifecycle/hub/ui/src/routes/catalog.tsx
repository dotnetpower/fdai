import { useEffect, useState } from "preact/hooks";
import { request } from "../api";
import { tr, useHubLocale } from "../locale";
import { LocalChannelsPanel } from "./local-channels";
import { hasCatalogTrustSource, ReleaseConnectionPanel } from "./release-connection";

type Trust = {
  approved_revision: number; approved_sha256: string | null;
  minimum_revision: number; accepted_sha256: string | null; imported: boolean; mode: string;
};

export function CatalogPage() {
  const [locale] = useHubLocale();
  const [trustAvailable, setTrustAvailable] = useState<boolean | null>(null);
  const [trust, setTrust] = useState<Trust | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState("");
  const [digest, setDigest] = useState("");
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [installation, setInstallation] = useState("");
  const [outcome, setOutcome] = useState("");
  useEffect(() => {
    if (trustAvailable !== true) return;
    void request<Trust>("/v1/catalog/trust").then(setTrust).catch(() => {
      setError(
        tr(
          locale,
          "Catalog import is unavailable. It requires the explicit remote development profile.",
          "카탈로그 가져오기를 사용할 수 없습니다. 명시적 원격 개발 프로필이 필요합니다.",
        ),
      );
    });
  }, [trustAvailable]);

  async function act(path: string, body: object) {
    setBusy(true); setError(""); setOutcome("");
    try {
      const result = await request<Trust & { outcome?: string }>(path, {
        method: "POST", body: JSON.stringify(body),
      });
      if (result.outcome) setOutcome(result.outcome);
      else setTrust(result);
    } catch {
      setError(
        tr(
          locale,
          "Request rejected. Review the approved pin, expiry, revision, and installation constraints.",
          "요청이 거부되었습니다. 승인된 고정값, 만료 시각, 개정 번호 및 설치 제약 조건을 확인하세요.",
        ),
      );
    } finally { setBusy(false); }
  }

  return <div class="catalog-page">
    <div class="m-head"><div>
      <h1>{tr(locale, "Release Catalog import", "릴리스 카탈로그 가져오기")}</h1>
      <p class="sub">{tr(
        locale,
        "For unsigned or offline exports: approve trust, import once, then compute a Plan. Signed vendor catalogs are kept current on the Updates page.",
        "미서명 또는 오프라인 내보내기 파일의 신뢰를 승인하고 한 번 가져온 뒤 계획을 계산합니다. 서명된 공급자 카탈로그는 업데이트 화면에서 최신 상태로 유지합니다.",
      )}</p>
    </div><span class="badge warn">{tr(locale, "Development only", "개발 전용")}</span></div>
    <ReleaseConnectionPanel onConnection={(state) => setTrustAvailable(hasCatalogTrustSource(state))} />
    {trustAvailable !== false && <div class="callout">
      <strong>{tr(locale, "Independent approval is required", "독립적인 신뢰 승인이 필요합니다")}</strong>
      <p>{tr(
        locale,
        "Obtain the exact export digest and revision through your separately approved trust channel. Do not copy a digest supplied by the download response as proof of trust.",
        "별도로 승인된 신뢰 채널을 통해 정확한 내보내기 다이제스트와 개정 번호를 확인하세요. 다운로드 응답에 포함된 다이제스트를 신뢰 근거로 복사해 사용하지 마세요.",
      )}</p>
      <p>{tr(
        locale,
        "No registry artifact or installation execution is verified here.",
        "이 화면에서는 레지스트리 아티팩트나 설치 실행을 검증하지 않습니다.",
      )}</p>
    </div>}
    {trustAvailable === false && <p class="note">{tr(locale,
      "Trusted catalog import requires an independently configured remote catalog profile. The connection preview does not grant import authority.",
      "신뢰 검증 후 카탈로그를 가져오려면 원격 카탈로그 프로필을 별도로 구성해야 합니다. 연결 조회 결과는 가져오기 권한을 부여하지 않습니다.")}</p>}
    {error && <p class="banner fail" role="alert">{error}</p>}
    {trustAvailable === true && !trust && !error && <section class="skeleton" role="status" aria-busy="true" aria-label={tr(locale, "Loading catalog trust", "카탈로그 신뢰 설정 불러오는 중")} />}
    {trust && <>
      {trust.mode === "tuf-catalog-roles" && trust.imported && (
        <div class="banner ok" role="status">
          <strong>
            ✓ {tr(
              locale,
              `TUF signed role catalog verified and active (Revision ${trust.minimum_revision})`,
              `TUF 서명 역할 기반 카탈로그 검증 및 동기화 완료 (개정 번호 ${trust.minimum_revision})`,
            )}
          </strong>
        </div>
      )}
      <dl class="catalog-trust">
        <dt>{tr(locale, "Accepted revision floor", "수락된 최소 개정 번호")}</dt><dd>{trust.minimum_revision}</dd>
        <dt>{tr(locale, "Accepted digest", "수락된 다이제스트")}</dt><dd style={{ overflowWrap: "anywhere" }}>{trust.accepted_sha256 ?? tr(locale, "No catalog imported", "가져온 카탈로그 없음")}</dd>
        <dt>{tr(locale, "Approved revision", "승인된 개정 번호")}</dt><dd>{trust.approved_revision}</dd>
        <dt>{tr(locale, "Approved digest", "승인된 다이제스트")}</dt><dd style={{ overflowWrap: "anywhere" }}>{trust.approved_sha256 ?? tr(locale, "Not approved", "미승인")}</dd>
      </dl>
      <form class="catalog-panel" onSubmit={(event) => {
        event.preventDefault();
        void act("/v1/catalog/trust/approve", {
          revision: Number(revision), sha256: digest, reason, confirmation,
        });
      }}>
        <h2 class="panel-title">{tr(locale, "1. Approve independently reviewed pin", "1. 독립 검토된 고정값(Pin) 승인")}</h2>
        <label>{tr(locale, "Revision", "개정 번호")} <input class="input" required type="number" min="0" step="1" value={revision}
          onInput={(e) => setRevision(e.currentTarget.value)} /></label>
        <label>SHA-256 <input class="input mono" required pattern="[0-9a-f]{64}" value={digest}
          onInput={(e) => setDigest(e.currentTarget.value)} /></label>
        <label>{tr(locale, "Approval reason", "승인 사유")} <input class="input" required minLength={3} maxLength={500} value={reason}
          onInput={(e) => setReason(e.currentTarget.value)} /></label>
        <label>{tr(
          locale,
          "Type approve, revision and digest separated by spaces",
          "공백으로 구분하여 approve, 개정 번호, 다이제스트 입력",
        )}
          <input class="input mono" required value={confirmation} onInput={(e) => setConfirmation(e.currentTarget.value)} /></label>
        <button class="btn primary" disabled={busy} type="submit">{tr(locale, "Approve exact pin", "정확한 고정값 승인")}</button>
      </form>
      <section class="catalog-panel">
        <h2 class="panel-title">{tr(locale, "2. Bounded outbound import", "2. 제한된 아웃바운드 가져오기")}</h2>
        <p class="note">{tr(
          locale,
          "One configured HTTPS source, one request, no redirects, no polling.",
          "구성된 단일 HTTPS 원본에 대해 리디렉션이나 폴링 없이 단일 요청으로 가져옵니다.",
        )}</p>
        <button type="button" class="btn" disabled={busy || !trust.approved_sha256}
          onClick={() => void act("/v1/catalog/import", {})}>{tr(locale, "Import approved catalog", "승인된 카탈로그 가져오기")}</button>
      </section>
      {trust.imported && trust.accepted_sha256 && <LocalChannelsPanel acceptedDigest={trust.accepted_sha256} />}
      <form class="catalog-panel" onSubmit={(event) => {
        event.preventDefault();
        void act(`/v1/installations/${encodeURIComponent(installation)}/recompute`, {});
      }}>
        <h2 class="panel-title">{tr(locale, "3. Compute a Lifecycle Plan", "3. 수명 주기 계획 계산")}</h2>
        <p class="note">{tr(
          locale,
          "Uses the persisted catalog and existing installation constraints. This does not apply a Plan.",
          "저장된 카탈로그와 기존 설치 제약 조건을 사용합니다. 계획을 직접 적용하지는 않습니다.",
        )}</p>
        <label>{tr(locale, "Installation ID", "설치 ID")} <input class="input" required value={installation}
          onInput={(e) => setInstallation(e.currentTarget.value)} /></label>
        <button type="submit" class="btn" disabled={busy || !trust.imported}>{tr(locale, "Compute Plan", "계획 계산")}</button>
      </form>
      {outcome && <p class="banner" role="status">{tr(locale, "Planner outcome:", "플래너 결과:")} {outcome}</p>}
    </>}
  </div>;
}
