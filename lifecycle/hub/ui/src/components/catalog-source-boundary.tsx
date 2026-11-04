import type { ComponentChildren } from "preact";
import { request } from "../api";
import { useAsync } from "../hooks/use-async";
import { releaseStateLabel, tr, useHubLocale } from "../locale";
import {
  hasCatalogTrustSource, type ReleaseCatalogPreview, type ReleaseConnection,
} from "../routes/release-connection";
import { AsyncBoundary } from "./async-boundary";
import { Link } from "./link";

function LocalCatalogStatus({ title, connection }: {
  title: string; connection: ReleaseConnection;
}) {
  const [locale] = useHubLocale();
  const preview = useAsync(() => request<ReleaseCatalogPreview>(
    "/v1/release-hub/catalog", { signal: AbortSignal.timeout(10_000) },
  ), [connection.endpoint]);
  return <div class="catalog-page">
    <div class="m-head">
      <h1>{title}</h1>
      <button class="btn" type="button" disabled={preview.status === "loading"}
        onClick={preview.reload}>{tr(locale, "Refresh preview", "조회 결과 새로고침")}</button>
    </div>
    <section class="callout" aria-label={tr(locale, "Catalog setup required", "카탈로그 구성 필요")}>
      <strong>{tr(locale, "Trusted catalog is not configured", "신뢰된 카탈로그가 구성되지 않았습니다")}</strong>
      <p>{tr(locale,
        "The Release Hub connection supports read-only registration previews. Updates and available releases require an independently configured catalog trust profile; an endpoint alone does not grant trust.",
        "Release Hub 연결로 등록 목록을 읽기 전용으로 조회할 수 있습니다. 업데이트와 사용 가능한 릴리스를 확인하려면 카탈로그 신뢰 프로필을 별도로 구성해야 합니다. 주소만 설정해도 신뢰가 부여되지는 않습니다.")}</p>
      <p><Link href="/catalog">{tr(locale, "Review Release Hub connection and trust setup",
        "Release Hub 연결 및 신뢰 구성 확인")}</Link></p>
    </section>
    <p>{tr(locale, "Current source", "현재 조회 대상")}:{" "}
      <code style={{ overflowWrap: "anywhere" }}>{connection.endpoint}</code></p>
    <AsyncBoundary state={preview}>
      {data => <section aria-label={tr(locale, "Unverified catalog preview", "검증되지 않은 카탈로그 조회 결과")}>
        <h2 class="panel-title">{tr(locale, "Registered releases, not approved updates",
          "등록된 릴리스 목록이며 승인된 업데이트가 아닙니다")}</h2>
        <p>{tr(locale, "Registered releases", "등록된 릴리스")}: {data.release_count}</p>
        {data.releases.length === 0
          ? <p class="empty">{tr(locale, "No releases registered in the selected Release Hub.",
            "선택한 Release Hub에 등록된 릴리스가 없습니다.")}</p>
          : <ul>{data.releases.map(release => <li key={release.id}>
            <code>{release.id}</code> ({releaseStateLabel(release.state, locale)})
          </li>)}</ul>}
        {data.expired && <p class="note">{tr(locale,
          "The export metadata is expired. A preview never renews it or makes it eligible for import.",
          "내보내기 메타데이터의 유효기간이 만료되었습니다. 조회만으로 갱신되거나 가져오기가 허용되지는 않습니다.")}</p>}
        <p class="note">{tr(locale,
          "No signature, build, update eligibility, or deployment is verified by this preview.",
          "이 조회 결과는 서명, 빌드, 업데이트 적격성이나 배포 완료를 검증하지 않습니다.")}</p>
      </section>}
    </AsyncBoundary>
  </div>;
}

export function CatalogSourceBoundary({ title, children }: {
  title: string; children: ComponentChildren;
}) {
  const connection = useAsync(() => request<ReleaseConnection>(
    "/v1/release-hub/connection", { signal: AbortSignal.timeout(10_000) },
  ), []);
  return <AsyncBoundary state={connection}>
    {state => hasCatalogTrustSource(state)
      ? children
      : <LocalCatalogStatus title={title} connection={state} />}
  </AsyncBoundary>;
}
