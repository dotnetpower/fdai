import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { extractReleaseStencil, type Catalog, type Release } from "./api";
import { buildConnectorGeometry, CARD_HEIGHT, CARD_WIDTH, BADGE_HEIGHT } from "./release-lineage.geometry";
import { buildReleaseLineageGraph, compareSemVer } from "./release-lineage.model";
import "./operational-edition.css";

export function editionReleasePath(id: string): string {
  return `#/edition/releases/${encodeURIComponent(id)}`;
}

export function editionOverviewPath(id: string): string {
  return `#/edition/selected/${encodeURIComponent(id)}`;
}

export function editionStage(release: Release, blocked = false): string {
  if (release.state === "recalled") return "RECALLED";
  if (blocked) return "BLOCKED";
  if (release.state === "draft") return "DRAFT";
  if (release.channels.includes("RELEASE")) return "RELEASE";
  if (release.channels.includes("RELEASE_CANDIDATE")) return "RC";
  if (release.channels.includes("DEV")) return "DEV";
  return release.channels.join(", ") || "UNASSIGNED";
}

export function filterEditionReleases(releases: readonly Release[], query: string, channel: string): Release[] {
  const search = query.trim().toLocaleLowerCase();
  return releases.filter((release) =>
    (channel === "all" || (channel === "draft" ? release.state === "draft" : release.channels.includes(channel)))
    && `${release.id} ${release.label} ${extractReleaseStencil(release)?.stencil_id ?? ""}`.toLocaleLowerCase().includes(search),
  ).sort((a, b) => compareSemVer(b.id, a.id));
}

export function OperationalEdition({ catalog, locale, selectedReleaseId }: {
  catalog: Catalog; locale: "en" | "ko"; selectedReleaseId?: string | null | undefined;
}) {
  const t = (en: string, ko: string) => locale === "ko" ? ko : en;
  const [highlightedId, setHighlightedId] = useState<string | null>(selectedReleaseId ?? null);
  const [query, setQuery] = useState("");
  const [channel, setChannel] = useState("all");
  const graph = useMemo(() => buildReleaseLineageGraph(catalog), [catalog]);
  const records = filterEditionReleases(catalog.releases, query, channel);
  const channels = [...new Set(catalog.releases.flatMap((release) => release.channels))].sort();
  const canvas = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setHighlightedId(selectedReleaseId ?? null);
    if (!selectedReleaseId) return;
    const index = graph.nodes.findIndex((node) => node.id === selectedReleaseId);
    const node = canvas.current?.querySelectorAll<HTMLAnchorElement>(".rh-edition-node")[index];
    node?.scrollIntoView({ block: "nearest", inline: "center" });
    node?.focus({ preventScroll: true });
  }, [graph, selectedReleaseId]);

  function navigate(event: KeyboardEvent, index: number) {
    const next = event.key === "Home" ? 0
      : event.key === "End" ? graph.nodes.length - 1
      : event.key === "ArrowRight" || event.key === "ArrowDown" ? index + 1
      : event.key === "ArrowLeft" || event.key === "ArrowUp" ? index - 1 : null;
    if (next === null) return;
    event.preventDefault();
    const target = canvas.current?.querySelectorAll<HTMLAnchorElement>(".rh-edition-node")[Math.max(0, Math.min(graph.nodes.length - 1, next))];
    target?.focus();
  }

  function rememberSelection(event: MouseEvent, id: string) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    history.replaceState(history.state, "", editionOverviewPath(id));
  }

  return <div class="rh-edition" lang={locale}>
    <header class="rh-edition-header">
      <div><span class="rh-edition-kicker">RELEASE HUB / EDITION</span><h1>{t("Releases", "릴리스")}</h1></div>
    </header>
    <a class="rh-edition-builder-entry" href="#/edition/new">
      <strong>+ {t("Stencil builder", "스텐실 빌더")}</strong><span>{t("Create release", "새 릴리스 만들기")} ↗</span>
    </a>
    <section class="rh-edition-canvas" aria-label={t("Release lineage", "릴리스 계통")}>
      <div class="rh-edition-canvas-head"><h2>{t("Release lineage", "릴리스 계통")}</h2><span>{t(`${catalog.releases.length} releases`, `${catalog.releases.length}개`)}</span></div>
      {graph.nodes.length > 0
        ? <div class="rh-edition-scroll" role="region" aria-label={t("Scrollable release lineage", "릴리스 계통 캔버스, 가로 스크롤 가능")} tabIndex={0}>
          <div class="rh-edition-map" ref={canvas} style={{ width: graph.width, height: graph.height }}>
            <svg width={graph.width} height={graph.height} viewBox={`0 0 ${graph.width} ${graph.height}`} aria-hidden="true">
              {graph.edges.map((edge) => {
                const { pathD, arrowD, portCx, portCy } = buildConnectorGeometry(edge);
                return <g key={edge.id} class={edge.kind === "recall-lift" ? "rh-edition-recall-edge" : ""}>
                  <path d={pathD} /><circle cx={portCx} cy={portCy} r="3.5" /><path d={arrowD} />
                </g>;
              })}
            </svg>
            {graph.nodes.map((node, index) => {
              const release = node.release;
              if (!release) return null;
              return <a key={node.id} class="rh-edition-node" href={editionReleasePath(release.id)}
                style={{ left: node.x, top: node.y + BADGE_HEIGHT, width: CARD_WIDTH, height: CARD_HEIGHT }}
                aria-label={`${t("Release", "릴리스")} ${release.id}, ${editionStage(release, node.status === "recalled")}`}
                aria-current={highlightedId === release.id ? "true" : undefined}
                onFocus={() => setHighlightedId(release.id)}
                onClick={(event) => rememberSelection(event, release.id)}
                onKeyDown={(event) => navigate(event, index)}>
                <span class="rh-edition-node-stage">{editionStage(release, node.status === "recalled")}</span>
                <strong>v{release.id}</strong>
                <span class="rh-edition-node-title">{extractReleaseStencil(release)?.stencil_id || release.label || t("No label", "설명 없음")}</span>
              </a>;
            })}
          </div>
        </div>
        : <p class="rh-edition-empty">{t("No registered releases. Use the Stencil builder or original workspace to register one.", "등록된 릴리스가 없습니다. 스텐실 빌더 또는 기존 작업 화면에서 등록하세요.")}</p>}
    </section>
    <section class="rh-edition-library" aria-labelledby="rh-edition-library-title">
      <div class="rh-edition-library-head"><h2 id="rh-edition-library-title">{t("Release list", "릴리스 목록")}</h2>
        <div class="rh-edition-filters">
          <label>{t("Search", "검색")}<input type="search" value={query} onInput={(event) => setQuery(event.currentTarget.value)} placeholder={t("Version or Stencil", "버전 또는 스텐실")} /></label>
          <label>{t("Channel", "채널")}<select value={channel} onChange={(event) => setChannel(event.currentTarget.value)}>
            <option value="all">{t("All", "전체")}</option><option value="draft">{t("Draft", "초안")}</option>
            {channels.map((name) => <option key={name} value={name}>{name}</option>)}
          </select></label>
        </div>
      </div>
      <div class="rh-edition-table-wrap" role="region" aria-label={t("Release list table", "릴리스 목록 표")} tabIndex={0}>
        <table><caption>{t(`${records.length} releases`, `릴리스 ${records.length}개`)}</caption>
          <thead><tr><th scope="col">{t("Version / label", "버전 / 이름")}</th><th scope="col">{t("Channel", "채널")}</th><th scope="col">{t("Status", "상태")}</th></tr></thead>
          <tbody>{records.map((release) => {
            const node = graph.nodes.find((item) => item.id === release.id);
            return <tr key={release.id} data-selected={highlightedId === release.id}>
              <td><a href={editionReleasePath(release.id)} onFocus={() => setHighlightedId(release.id)}
                onClick={(event) => rememberSelection(event, release.id)}>v{release.id}</a><span>{release.label || t("No label", "설명 없음")}</span></td>
              <td>{release.channels.join(" · ") || "-"}</td><td>{editionStage(release, node?.status === "recalled")}</td>
            </tr>;
          })}</tbody>
        </table>
        {records.length === 0 && <p class="rh-edition-empty">{t("No matching releases.", "일치하는 릴리스가 없습니다.")}</p>}
      </div>
    </section>
  </div>;
}
