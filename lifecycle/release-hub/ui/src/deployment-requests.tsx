import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  extractReleaseStencil,
  latestEligibleChannelHead,
  releaseStateIndex,
  requestDeploymentRequests,
  type Catalog,
  type DeploymentRequestPage,
} from "./api";
import { editionReleasePath } from "./operational-edition";

const SUBSCRIPTION = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const LIMIT = 25;

export function nextRequestOffset(page: DeploymentRequestPage): number | null {
  return page.has_more ? page.offset + page.limit : null;
}

export function DeploymentRequests({ catalog, locale = "en", refreshGeneration = 0 }: {
  catalog?: Catalog | null; locale?: "en" | "ko"; refreshGeneration?: number;
}) {
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);
  const stencilByRelease = useMemo(
    () => new Map((catalog?.releases ?? []).map((r) => [r.id, extractReleaseStencil(r)] as const)),
    [catalog],
  );
  const releaseStates = useMemo(
    () => releaseStateIndex(catalog?.releases ?? []),
    [catalog],
  );
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<DeploymentRequestPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    const current = ++generation.current;
    setLoading(true); setPage(null); setError("");
    void requestDeploymentRequests(filter, offset, LIMIT).then((result) => {
      if (generation.current === current) setPage(result);
    }).catch(() => {
      if (generation.current === current) setError(locale === "ko" ? "배포 요청 내역을 불러올 수 없습니다. 운영자 권한을 확인한 뒤 새로고침하세요." : "Deployment requests unavailable. Check operator access, then refresh requests.");
    }).finally(() => {
      if (generation.current === current) setLoading(false);
    });
    return () => { generation.current++; };
  }, [filter, offset, refresh, refreshGeneration]);
  return <>
    <div class="page-head"><div><p class="eyebrow">{t("Clone deployment intake", "구독별 설치 요청 관제")}</p><h1>{t("Deployment requests", "구독 배포 요청 현황")}</h1>
      <p>{t("Subscriptions that self-reported a deployment request, newest first.", "각 Azure 구독에서 보고된 배포 요청 내역과 요청된 릴리스의 Stencil 에디션·최신 정합성을 확인합니다.")}</p></div>
      <button disabled={loading} onClick={() => { setOffset(0); setRefresh((value) => value + 1); }}>{t("Refresh requests", "요청 새로고침")}</button>
    </div>
    <p class="warning">{t("Self-reported / ownership unverified. A request is not verified subscription ownership, approval, or a successful deployment.", "자체 보고된 요청 기록입니다. 요청 기록만으로 구독 소유권이나 실제 클러스터 배포 완료를 보장하지 않습니다.")}</p>
    <form class="request-filter" onSubmit={(event) => {
      event.preventDefault(); setFilter(draft.trim().toLowerCase()); setOffset(0); setRefresh((value) => value + 1);
    }}>
      <label>{t("Subscription ID", "Azure 구독 ID 필터")}<input value={draft} maxLength={36} pattern={SUBSCRIPTION}
        placeholder={t("Canonical lowercase UUID", "구독 UUID 입력 (예: 00000000-0000-0000-0000-000000000000)")} autoComplete="off"
        onInput={(event) => setDraft(event.currentTarget.value.trim().toLowerCase())} /></label>
      <button disabled={loading}>{t("Filter requests", "필터 적용")}</button>
      <button type="button" disabled={loading || (!draft && !filter)}
        onClick={() => { setDraft(""); setFilter(""); setOffset(0); }}>{t("Clear filter", "필터 초기화")}</button>
    </form>
    {filter && <p>{t("Filtered subscription:", "적용된 구독 필터:")} <code class="request-subscription">{filter}</code></p>}
    {loading && <p role="status" class="empty">{t("Loading deployment requests...", "배포 요청 내역을 불러오는 중...")}</p>}
    {error && <p role="alert" class="error">{error}</p>}
    {page && <>
      {!page.requests.length ? <p class="empty">{t("No deployment requests match this view.", "아직 접수된 배포 요청이 없습니다.")}</p>
        : <div class="request-table" role="region" aria-label="Deployment request records" tabIndex={0}>
          <table>
            <caption>{t("Self-reported requests / requested only / ownership unverified", "구독별 배포 요청 목록 (최신순)")}</caption>
            <thead><tr><th scope="col">{t("Recorded (UTC)", "기록 시각 (UTC)")}</th><th scope="col">{t("Subscription", "구독 ID")}</th>
              <th scope="col">{t("Release / channel", "요청 릴리스 / 채널 / 에디션")}</th><th scope="col">{t("Region", "리전")}</th><th scope="col">{t("Request evidence", "상세 증적")}</th></tr></thead>
            <tbody>{page.requests.map((record) => {
              const st = stencilByRelease.get(record.release_id);
              const chanHead = latestEligibleChannelHead(catalog?.channels[record.channel] ?? [], releaseStates);
              const fleetStatus = releaseStates.get(record.release_id) === "recalled"
                ? t("Recalled release", "회수된 릴리스")
                : chanHead === record.release_id
                  ? t("Latest channel head", "채널 최신 버전")
                  : chanHead
                    ? t(`Behind head (${chanHead})`, `이전 버전 (최신: ${chanHead})`)
                    : null;
              return <tr key={record.request_id}>
              <td><time dateTime={record.recorded_at}>{new Date(record.recorded_at).toISOString().replace("T", " ").replace("Z", "")}</time>
                <small>{t("Requested / self-reported", "요청됨 / 자체 보고")}</small></td>
              <td><code>{record.subscription_id}</code><small>{t("Ownership unverified", "소유권 미검증")}</small></td>
              <td><a href={editionReleasePath(record.release_id)}>{record.release_id}</a><small>{record.channel}</small>{st && <span class="stencil-chip">stencil:{st.stencil_id} · {st.azure_rbac_posture}</span>}{fleetStatus && <span class="stencil-chip">{fleetStatus}</span>}</td>
              <td>{record.region}</td>
              <td><details><summary>{t("Metadata", "상세 메타데이터")}</summary><dl>
                <dt>{t("Request id", "요청 ID")}</dt><dd><code class="digest">{record.request_id}</code></dd>
                <dt>{t("Source commit", "소스 커밋")}</dt><dd><code class="digest">{record.source_commit}</code></dd>
                <dt>{t("Catalog digest", "카탈로그 다이제스트")}</dt><dd><code class="digest">{record.catalog_digest}</code></dd>
                {st && <><dt>Stencil</dt><dd><code>{st.stencil_id}</code> (<code class="digest">{st.stencil_digest}</code>)</dd></>}
              </dl></details></td>
            </tr>;
            })}</tbody>
          </table>
        </div>}
      <div class="request-pagination" aria-label="Deployment request pagination">
        <button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>{t("Previous", "이전")}</button>
        <span role="status">{page.requests.length ? `${offset + 1} - ${offset + page.requests.length}` : "0"} {t("requests in this view", "건 표시 중")}</span>
        <button disabled={loading || nextRequestOffset(page) === null} onClick={() => {
          const next = nextRequestOffset(page);
          if (next !== null) setOffset(next);
        }}>{t("Next", "다음")}</button>
      </div>
    </>}
  </>;
}
