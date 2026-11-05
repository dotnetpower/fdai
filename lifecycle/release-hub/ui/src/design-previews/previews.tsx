import { useEffect, useRef, useState } from "preact/hooks";
import { EvidenceNote, Status, StudioShell } from "../../../../hub/ui/src/design-previews/shell";
import { releaseInstallationsPreviewPath, type DesignId, type Channel } from "../../../../hub/ui/src/design-previews/model";
import { COMPONENTS, filterReleases, RELEASE_EXAMPLES, type ReleaseExample } from "./data";
import { EditionCanvas } from "./edition-canvas";
import { EDITION_AREAS, EditionSections, type EditionArea } from "./edition-sections";
import { InstallationMonitor } from "./installation-monitor";

function ReleaseDetail({ release }: { release: ReleaseExample }) {
  return <section class="dp-edition-dossier" aria-label="선택한 릴리스" id="release-detail">
    <div class="dp-kicker">RELEASE DOSSIER / 예시</div><Status value={release.status} />
    <h2>{release.id} / {release.title}</h2><p>{release.note}</p>
    <dl class="dp-dossier">
      <div><dt>에디션</dt><dd>{release.edition}</dd></div>
      <div><dt>채널</dt><dd class="dp-mono">{release.channel}</dd></div>
      <div><dt>구성 요소</dt><dd>{release.components}개</dd></div>
      <div><dt>서명 · 출처 검증</dt><dd>예시에서 제공하지 않음</dd></div>
    </dl>
    <details><summary>구성 보기 ({release.components})</summary>
      <ul class="dp-edition-component-list">{COMPONENTS.slice(0, release.components).map((part) =>
        <li key={part.id}><strong>{part.name}</strong><span>{part.role}</span></li>)}</ul>
      <p>구성 범주는 고정 예시입니다. 실제 매니페스트의 워크로드 목록이 아닙니다.</p>
    </details>
    <details><summary>변경 내역 보기</summary><p>구성 경계와 운영자 탐색 흐름을 개선하는 예시입니다. 실제 커밋이나 릴리스 매니페스트를 표현하지 않습니다.</p></details>
    <EvidenceNote />
  </section>;
}

function ReleaseTable({ records, selected, select }: {
  records: readonly ReleaseExample[]; selected: string; select: (item: ReleaseExample) => void;
}) {
  return <div class="dp-table-wrap" role="region" aria-label="릴리스 목록 표" tabIndex={0}>
    <table class="dp-table dp-edition-release-table"><caption>{records.length}개 릴리스</caption>
      <thead><tr><th scope="col">버전 / 에디션</th><th scope="col">채널</th><th scope="col">검토 상태</th><th scope="col">구성</th></tr></thead>
      <tbody>{records.map((item) => <tr key={item.id} data-selected={selected === item.id}>
        <td><button class="dp-edition-version" type="button" aria-pressed={selected === item.id} aria-controls="release-detail" onClick={() => select(item)}>{item.id}</button><small>{item.edition}</small></td>
        <td>{item.channel}</td><td><Status value={item.status} /></td><td>{item.components}개</td>
      </tr>)}</tbody>
    </table>{records.length === 0 && <p class="dp-empty">일치하는 예시가 없습니다. 검색어나 채널을 변경해 주세요.</p>}
  </div>;
}

function Edition() {
  const [selected, setSelected] = useState(RELEASE_EXAMPLES.records[0]!);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [channel, setChannel] = useState<Channel | "all">("all");
  const [query, setQuery] = useState("");
  const [area, setArea] = useState<EditionArea>("releases");
  const records = filterReleases(query, channel);
  const dialog = useRef<HTMLDialogElement>(null);
  const lastFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (drawerOpen && !dialog.current?.open) {
      dialog.current?.showModal();
      dialog.current?.querySelector<HTMLButtonElement>(".dp-edition-drawer-close")?.focus();
    } else if (!drawerOpen && dialog.current?.open) {
      dialog.current.close();
    }
  }, [drawerOpen]);

  function showRelease(release: ReleaseExample) {
    lastFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setSelected(release);
    setDrawerOpen(true);
  }

  function closeRelease() {
    const trigger = lastFocus.current;
    dialog.current?.close();
    setDrawerOpen(false);
    if (trigger?.isConnected) trigger.focus();
  }

  return <div class="dp-page dp-edition">
    <div class="dp-edition-lead">
      <header class="dp-heading"><span class="dp-kicker">RELEASE HUB / EDITION</span><h1>Change, carefully composed.</h1></header>
    </div>
    <details class="dp-edition-builder" id="edition-builder">
      <summary><span>스텐실 빌더</span></summary>
      <div class="dp-edition-builder-body">
        <EditionSections area="stencils" release={selected} selectRelease={showRelease} children={null} />
      </div>
    </details>
    <nav class="dp-edition-nav" id="edition-navigation" aria-label="Edition 기능 탐색">
      {EDITION_AREAS.filter((item) => item.id !== "stencils").map((item) => <button key={item.id} type="button"
        aria-pressed={area === item.id} aria-controls="edition-workspace"
        onClick={() => {
          setArea(item.id);
          requestAnimationFrame(() => document.getElementById("edition-workspace")?.focus());
        }}>
        {item.label}
      </button>)}
      <a href={releaseInstallationsPreviewPath}>설치 현황 <span aria-hidden="true">↗</span></a>
    </nav>
    <div class="dp-edition-layout">
      <EditionCanvas release={selected} onRelease={showRelease} onHighlight={setSelected} />
    </div>
    <dialog ref={dialog} class="dp-edition-drawer" aria-labelledby="edition-drawer-title"
      onCancel={(event) => { event.preventDefault(); closeRelease(); }}>
      <header class="dp-edition-drawer-head">
        <span id="edition-drawer-title">릴리스 상세 · 예시</span>
        <button class="dp-edition-drawer-close" type="button" onClick={closeRelease}>닫기</button>
      </header>
      <ReleaseDetail release={selected} />
    </dialog>
    <section class="dp-section dp-edition-workspace" id="edition-workspace" aria-label="Edition 기능 상세" tabIndex={-1}>
      <EditionSections area={area} release={selected} selectRelease={showRelease}>
        <div class="dp-toolbar"><label>릴리스 검색<input type="search" value={query} onInput={(event) => setQuery(event.currentTarget.value)} placeholder="버전 또는 에디션" /></label>
          <label>채널<select aria-label="채널" value={channel} onChange={(event) => setChannel(event.currentTarget.value as Channel | "all")}>
            <option value="all">모든 채널</option><option value="DEV">DEV</option><option value="RELEASE_CANDIDATE">RELEASE_CANDIDATE</option><option value="RELEASE">RELEASE</option>
          </select></label><output aria-live="polite">{records.length}개 표시 · 선택: {selected.id}</output>
        </div>
        <ReleaseTable records={records} selected={selected.id} select={showRelease} />
      </EditionSections>
    </section>
  </div>;
}

export function ReleasePreview({ design, page }: { design: DesignId<"release">; page?: "installations" | undefined }) {
  return <StudioShell hub="release" design={design}>{page === "installations" ? <InstallationMonitor /> : <Edition />}</StudioShell>;
}
