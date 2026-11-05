import { useState } from "preact/hooks";
import { EvidenceNote, Heading, Status, StudioShell } from "./shell";
import type { DesignId } from "./model";
import { filterInstallations, INSTALLATION_EXAMPLES, scheduledInstallations, type FleetFilter, type InstallationExample, type ScheduleDay } from "./data";

function InstallationDetail({ item, focus = false }: { item: InstallationExample; focus?: boolean }) {
  return <section class={`dp-detail${focus ? " dp-focus" : ""}`} id="installation-detail" aria-label="선택한 설치 상세">
    <div class="dp-kicker">INSTALLATION DOSSIER / 예시</div><Status value={item.status} />
    <h2>{item.name}</h2><p>{item.note}</p>
    <dl class="dp-dossier"><div><dt>예시 설치 ID</dt><dd class="dp-mono">{item.id}</dd></div>
      <div><dt>현재 → 대상 버전</dt><dd>{item.currentRelease ?? "알 수 없음"} → {item.targetRelease ?? "알 수 없음"}</dd></div>
      <div><dt>채널</dt><dd class="dp-mono">{item.channel}</dd></div>
      <div><dt>유지보수 창</dt><dd>{item.window}</dd></div>
      <div><dt>Entity</dt><dd>{item.entities}개</dd></div>
      <div><dt>최근 관측</dt><dd>관측 데이터 없음</dd></div>
    </dl>
    <details><summary>계획과 실행 경계 보기</summary><p>Hub는 계획을 제시합니다. 설치 Agent는 서명, 소유권과 독립적인 효과 범위를 확인해야 합니다. 이 프리뷰에는 승인·실행 기능이 없습니다.</p></details>
    <EvidenceNote />
  </section>;
}

function FleetToolbar({ query, setQuery, filter, setFilter, count }: {
  query: string; setQuery: (value: string) => void; filter: FleetFilter;
  setFilter: (value: FleetFilter) => void; count: number;
}) {
  return <div class="dp-toolbar"><label>설치 검색<input type="search" value={query} placeholder="이름 또는 예시 ID" onInput={(event) => setQuery(event.currentTarget.value)} /></label>
    <label>검토 범위<select value={filter} onChange={(event) => setFilter(event.currentTarget.value as FleetFilter)}>
      <option value="all">모든 설치</option><option value="attention">검토 필요</option><option value="unknown">근거 없음</option>
    </select></label><output aria-live="polite">{count}개 표시</output>
  </div>;
}

function Atlas() {
  const [selected, setSelected] = useState(INSTALLATION_EXAMPLES.records[0]!);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FleetFilter>("all");
  const records = filterInstallations(query, filter);
  return <div class="dp-page"><Heading index="01" eyebrow="INSTALLATION ATLAS" title="A clear view of every environment." description="설치 환경의 차이를 한눈에 읽고, 다음 검토가 필요한 곳을 선택하세요." />
    <FleetToolbar query={query} setQuery={setQuery} filter={filter} setFilter={setFilter} count={records.length} />
    <div class="dp-atlas-layout"><section aria-label="설치 환경 카드"><div class="dp-fleet">{records.map((item, index) => <button type="button" key={item.id} class="dp-card-button"
      aria-pressed={selected.id === item.id} aria-controls="installation-detail" onClick={() => setSelected(item)}>
      <div class="dp-meta"><span>ENV / 0{index + 1}</span><Status value={item.status} /></div><strong>{item.name}</strong>
      <span class="dp-mono">{item.currentRelease ?? "알 수 없음"} → {item.targetRelease ?? "알 수 없음"}</span>
      <div class="dp-meta"><span>{item.entities} Entities</span><span>상세 검토 ↗</span></div>
    </button>)}</div>{records.length === 0 && <p class="dp-empty">일치하는 설치 예시가 없습니다. 필터를 변경해 주세요.</p>}
      <p class="dp-live-region" role="status">선택한 예시: {selected.name}</p>
      <EvidenceNote />
    </section><InstallationDetail item={selected} focus /></div>
  </div>;
}

function Timeline() {
  const [day, setDay] = useState<ScheduleDay>("first");
  const records = scheduledInstallations(day);
  return <div class="dp-page"><Heading index="02" eyebrow="MAINTENANCE TIMELINE" title="Make room for the next change." description="유지보수 창을 중심으로 검토 순서를 정리합니다. 시간은 모두 고정된 예시이며 UTC 기준입니다." />
    <div class="dp-section-head"><div><h2>Window planner</h2><p>시작 전 확인 → 독립 실행 → 결과 관측</p></div>
      <div class="dp-day-nav" role="group" aria-label="예시 일정 선택"><button type="button" aria-pressed={day === "first"} onClick={() => setDay("first")}>11월 06일</button>
        <button type="button" aria-pressed={day === "next"} onClick={() => setDay("next")}>11월 07일</button></div>
    </div><p class="dp-live-region" role="status">2026년 {day === "first" ? "11월 06일" : "11월 07일"} · 예시 창 {records.length}개</p>
    <section class="dp-schedule" aria-label="유지보수 창 목록">{records.map((item) => <article class="dp-window" key={`${day}-${item.id}`}>
      <div class="dp-time">{item.window.slice(0, 5)}<small>UTC / 60분 창</small></div>
      <details><summary><strong>{item.name}</strong><Status value={item.status} /></summary>
        <div class="dp-window-body"><p>{item.note}</p>
          <dl class="dp-facts"><div><dt>현재 버전</dt><dd>{item.currentRelease}</dd></div><div><dt>대상 버전</dt><dd>{item.targetRelease}</dd></div><div><dt>Entity</dt><dd>{item.entities}</dd></div></dl>
          <ol class="dp-steps"><li><strong>01 / 입력</strong><small>서명·구성 검토</small></li><li><strong>02 / 제약</strong><small>소유권·시간 창</small></li><li><strong>03 / 실행</strong><small>이 프리뷰에서 불가</small></li><li><strong>04 / 관측</strong><small>실제 결과 없음</small></li></ol>
          <p>일정을 펼쳐도 계획은 발급되지 않습니다. 승인과 실행은 독립적인 운영 흐름입니다.</p>
        </div>
      </details>
    </article>)}</section>
    <section class="dp-section"><h2>아직 일정에 놓을 수 없는 항목</h2><details class="dp-provenance"><summary>Offline / 최신 보고 없음</summary><p>유지보수 창과 현재 버전을 알 수 없어 일정에 배치하지 않았습니다. 누락된 보고를 정상으로 간주하지 않습니다.</p></details></section>
    <EvidenceNote />
  </div>;
}

function Ledger() {
  const [selected, setSelected] = useState(INSTALLATION_EXAMPLES.records[2]!);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<FleetFilter>("all");
  const records = filterInstallations(query, filter);
  return <div class="dp-workspace"><aside class="dp-rail"><h2>Review ledger</h2><nav aria-label="검토 영역"><a href="#fleet-ledger">설치 원장</a><a href="#installation-detail">선택한 계획</a><a href="#ledger-evidence">출처와 범위</a></nav><p>비교가 먼저,<br />실행은 별도 경계에서.</p></aside>
    <div class="dp-page"><Heading index="03" eyebrow="INSTALLATION LEDGER" title="Details that make the difference." description="버전, 채널과 보류 이유를 정밀하게 비교하는 마스터·상세 작업대입니다." />
      <FleetToolbar query={query} setQuery={setQuery} filter={filter} setFilter={setFilter} count={records.length} />
      <div class="dp-split"><section id="fleet-ledger"><div class="dp-table-wrap" role="region" aria-label="설치 원장 표" tabIndex={0}>
        <table class="dp-table"><caption>고정 예시 / 설치를 선택하여 제약 검토</caption><thead><tr><th scope="col">설치</th><th scope="col">버전</th><th scope="col">상태</th></tr></thead>
          <tbody>{records.map((item) => <tr key={item.id} data-selected={selected.id === item.id}>
            <td><button type="button" aria-pressed={selected.id === item.id} aria-controls="installation-detail" onClick={() => setSelected(item)}>{item.name}</button><small class="dp-mono">{item.channel}</small></td>
            <td class="dp-mono">{item.currentRelease ?? "알 수 없음"}<small>대상 {item.targetRelease ?? "알 수 없음"}</small></td><td><Status value={item.status} /></td>
          </tr>)}</tbody>
        </table>{records.length === 0 && <p class="dp-empty">검색 결과가 없습니다. 입력을 지우거나 범위를 넓혀 주세요.</p>}
      </div><p class="dp-live-region" role="status">선택한 예시: {selected.name}</p><div id="ledger-evidence"><EvidenceNote /></div></section>
        <InstallationDetail item={selected} />
      </div>
    </div>
  </div>;
}

export function LifecyclePreview({ design }: { design: DesignId<"lifecycle"> }) {
  return <StudioShell hub="lifecycle" design={design} dark={design === "timeline"}>
    {design === "atlas" ? <Atlas /> : design === "timeline" ? <Timeline /> : <Ledger />}
  </StudioShell>;
}
