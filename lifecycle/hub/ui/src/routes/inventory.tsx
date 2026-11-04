import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { CatalogSourceBoundary } from "../components/catalog-source-boundary";
import { Link } from "../components/link";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { installationPath } from "../router";

function InventoryHeader({ title, reload, loading }: {
  title: string; reload: () => void; loading: boolean;
}) {
  const [locale] = useHubLocale();
  return <div class="m-head">
    <h1>{title}</h1>
    <button type="button" class="btn" disabled={loading} onClick={reload}>
      {tr(locale, "Refresh", "새로 고침")}
    </button>
  </div>;
}

export function ReleasesPage() {
  const [locale] = useHubLocale();
  return (
    <CatalogSourceBoundary title={tr(locale, "Available releases", "사용 가능한 릴리스")}>
      <TrustedReleasesPage />
    </CatalogSourceBoundary>
  );
}

function TrustedReleasesPage() {
  const [locale] = useHubLocale();
  const inventory = useAsync(() => hubApi.listReleases(), []);
  return <div class="inventory-page">
    <InventoryHeader title={tr(locale, "Available releases", "사용 가능한 릴리스")} reload={inventory.reload}
      loading={inventory.status === "loading"} />
    <div class="callout">
      <strong>{tr(locale, "Accepted catalog metadata only", "수락된 카탈로그 메타데이터 전용")}</strong>
      <p>{tr(
        locale,
        "Reads the already imported catalog and rechecks its pin, signature and expiry. This does not import, publish or apply anything. Catalog membership does not prove artifact availability, installation eligibility or readiness to deploy.",
        "이미 가져온 카탈로그를 읽어 고정값, 서명 및 만료 여부를 재확인합니다. 가져오기, 게시 또는 적용은 수행하지 않습니다. 카탈로그에 포함되어 있다는 사실만으로 아티팩트 가용성, 설치 적격성 또는 배포 준비 상태가 입증되지는 않습니다.",
      )}</p>
    </div>
    <AsyncBoundary state={inventory}>
      {({ releases }) => releases.length === 0
        ? <p class="empty">{tr(locale, "The verified catalog contains no releases.", "검증된 카탈로그에 릴리스가 없습니다.")}</p>
        : releases.map(release => <section class="catalog-panel" key={release.release_id}
          aria-label={`${tr(locale, "Release", "릴리스")} ${release.release_id}`}>
          <h2 class="panel-title">{tr(locale, "Release", "릴리스")} {release.release_id}</h2>
          <dl class="catalog-trust">
            <dt>{tr(locale, "Channels", "채널")}</dt><dd>{release.channels.join(", ") || tr(locale, "No channel membership", "채널 소속 없음")}</dd>
            <dt>{tr(locale, "Manifest digest", "매니페스트 다이제스트")}</dt><dd class="mono inventory-value">{release.digest}</dd>
            <dt>{tr(locale, "Source commit", "소스 커밋")}</dt><dd class="mono inventory-value">{release.source_commit}</dd>
            <dt>{tr(locale, "Platform", "플랫폼")}</dt><dd>{release.platform_tag}</dd>
            <dt>{tr(locale, "Schema target", "대상 스키마")}</dt><dd>{release.schema_target ?? tr(locale, "Not declared", "선언되지 않음")}</dd>
            <dt>{tr(locale, "Tolerated schema", "허용 스키마 범위")}</dt><dd>{release.schema_range
              ? tr(
                  locale,
                  `${release.schema_range.minimum} to ${release.schema_range.maximum}`,
                  `${release.schema_range.minimum} ~ ${release.schema_range.maximum}`,
                )
              : tr(locale, "Not declared", "선언되지 않음")}</dd>
          </dl>
          <details>
            <summary>{tr(
              locale,
              `Inspect component images and recall notices for ${release.release_id}`,
              `${release.release_id}의 컴포넌트 이미지 및 회수 공지 확인`,
            )}</summary>
            <div class="table-scroll"><table class="t">
              <caption>{tr(locale, `Image digests for ${release.release_id}`, `${release.release_id} 이미지 다이제스트`)}</caption>
              <thead><tr>
                <th>{tr(locale, "Section", "영역")}</th>
                <th>{tr(locale, "Component", "컴포넌트")}</th>
                <th>{tr(locale, "Image digest", "이미지 다이제스트")}</th>
              </tr></thead>
              <tbody>{release.images.map(image => <tr key={`${image.section}/${image.component}`}>
                <td>{image.section}</td><td>{image.component}</td>
                <td class="mono inventory-value">{image.image_digest}</td>
              </tr>)}</tbody>
            </table></div>
            <p class="note">{tr(
              locale,
              "Release recall notices are historical facts, not an eligibility decision. The planner also checks capability recalls and installation constraints.",
              "릴리스 회수 공지는 이력 사실이며 그 자체로 적격성 판정이 아닙니다. 플래너는 기능 회수와 설치 제약 조건도 함께 검사합니다.",
            )}</p>
            {release.recall_notices.length === 0
              ? <p class="note">{tr(locale, "No release-scoped recall notices in this catalog.", "이 카탈로그에 릴리스 단위 회수 공지가 없습니다.")}</p>
              : <ul>{release.recall_notices.map(notice => <li key={notice.sequence}>
                {tr(locale, "Sequence", "시퀀스")} {notice.sequence}: {notice.action}
                <div class="mono inventory-value">{notice.notice_digest}</div>
              </li>)}</ul>}
          </details>
        </section>)}
    </AsyncBoundary>
  </div>;
}

export function ConfigurationsPage() {
  const [locale] = useHubLocale();
  const inventory = useAsync(() => hubApi.listConfigurations(), []);
  return <div class="inventory-page">
    <InventoryHeader title={tr(locale, "Configuration packages", "구성 패키지")} reload={inventory.reload}
      loading={inventory.status === "loading"} />
    <div class="callout">
      <strong>{tr(
        locale,
        "Stored configuration revisions, not verified signed packages",
        "검증된 서명 패키지가 아닌 저장된 구성 개정본",
      )}</strong>
      <p>{tr(
        locale,
        "These revisions may originate from enrollment. Independent package signature provenance is not recorded. This view cannot establish signed-input readiness. Configuration values, sealed identifiers and signatures are not exposed.",
        "이 개정본들은 등록 과정에서 생성되었을 수 있으며 독립적인 패키지 서명 출처는 기록되지 않습니다. 이 화면만으로는 서명된 입력 준비 상태를 입증할 수 없습니다. 구성 값, 봉인된 식별자 및 서명은 노출되지 않습니다.",
      )}</p>
    </div>
    <AsyncBoundary state={inventory} layout="table">
      {({ configurations }) => configurations.length === 0
        ? <p class="empty">{tr(locale, "No configuration revisions stored.", "저장된 구성 개정본이 없습니다.")}</p>
        : <div class="table-scroll"><table class="t">
          <caption>{tr(locale, "Stored configuration revision metadata", "저장된 구성 개정 메타데이터")}</caption>
          <thead><tr>
            <th>{tr(locale, "Digest", "다이제스트")}</th>
            <th>{tr(locale, "Stored at", "저장 시각")}</th>
            <th>{tr(locale, "Schema keys", "스키마 키 수")}</th>
            <th>{tr(locale, "Override blocks", "재정의 블록 수")}</th>
            <th>{tr(locale, "Referenced by", "참조 설치 환경")}</th>
            <th>{tr(locale, "Package signature", "패키지 서명")}</th>
          </tr></thead>
          <tbody>{configurations.map(configuration => <tr key={configuration.digest}>
            <td class="mono inventory-value">{configuration.digest}</td>
            <td>{formatTimestamp(configuration.imported_at, undefined, locale)}</td>
            <td>{configuration.schema_key_count}</td><td>{configuration.override_count}</td>
            <td>{configuration.installation_ids.length === 0 ? tr(locale, "No current references", "현재 참조 없음")
              : <ul>{configuration.installation_ids.map(id => <li key={id}>
                <Link href={installationPath(id)}>{id}</Link>
              </li>)}</ul>}</td>
            <td>{tr(locale, "Not recorded", "미기록")}</td>
          </tr>)}</tbody>
        </table></div>}
    </AsyncBoundary>
  </div>;
}
