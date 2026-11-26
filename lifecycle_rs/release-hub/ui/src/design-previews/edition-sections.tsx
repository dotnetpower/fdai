import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import { COMPONENTS, RELEASE_EXAMPLES, type ReleaseExample } from "./data";
import { Status } from "../../../../hub/ui/src/design-previews/shell";
import "./edition-sections.css";

export const EDITION_AREAS = [
  { id: "stencils", label: "스텐실 빌더" },
  { id: "releases", label: "릴리스" },
  { id: "channels", label: "배포 채널" },
  { id: "deployment-requests", label: "배포 요청" },
  { id: "activity", label: "활동 이력" },
  { id: "trust", label: "서명·리콜" },
] as const;
export type EditionArea = typeof EDITION_AREAS[number]["id"];

const PRESETS = [
  { id: "lite-observe-alert", label: "Lite Observe", profile: "관측 중심", workloadCount: 2, menuCount: 14 },
  { id: "standard-sre", label: "Standard SRE", profile: "운영·판단", workloadCount: 3, menuCount: 32 },
  { id: "full-enterprise", label: "Full Enterprise", profile: "확장된 거버넌스", workloadCount: 5, menuCount: 60 },
] as const;

const MENU_EXAMPLES = [
  { id: "dashboard", label: "Dashboard" }, { id: "live", label: "Live" },
  { id: "alerts", label: "Alerts" }, { id: "agents", label: "Agents" },
  { id: "audit", label: "Audit" }, { id: "reports", label: "Reports" },
  { id: "settings-general", label: "Settings" }, { id: "topology", label: "Topology" },
] as const;

const RINGS = [
  { id: "DEV", name: "개발 검증", rule: "서명·발행 이후 검토. 실제 서명이나 발행 여부는 프리뷰에서 검증하지 않습니다." },
  { id: "RELEASE_CANDIDATE", name: "카나리 / 스테이징", rule: "DEV 소속, 리콜, 레이블과 검토 증거를 서버에서 독립 평가합니다." },
  { id: "RELEASE", name: "운영 배포 자격", rule: "RC 관찰 시간과 정상 카나리 증거를 확인한 뒤 진입합니다." },
] as const;

type ReviewIntent = { label: string; target: string; boundary: string };
const SAMPLE_REQUESTS = [
  { id: "example-request-01", releaseId: "0.5.3", channel: "RELEASE_CANDIDATE", region: "example-region", subscription: "00000000-0000-0000-0000-000000000001" },
  { id: "example-request-02", releaseId: "0.5.2", channel: "RELEASE", region: "example-region", subscription: "00000000-0000-0000-0000-000000000002" },
] as const;

const SAMPLE_ACTIVITY = [
  { id: "example-event-04", releaseId: "0.5.4", label: "초안 준비", note: "등록 전 검토 단계. 감사 이벤트가 아닙니다." },
  { id: "example-event-03", releaseId: "0.5.3", label: "RC 단계 검토", note: "카나리 검사 결과는 제공되지 않았습니다." },
  { id: "example-event-02", releaseId: "0.5.2", label: "RELEASE 소속 예시", note: "실제 승격이나 설치 완료의 증거는 아닙니다." },
  { id: "example-event-01", releaseId: "0.5.1", label: "출처 미확인", note: "서명과 아티팩트 관측이 없습니다." },
] as const;

export function EditionSections({ area, release, selectRelease, children }: {
  area: EditionArea;
  release: ReleaseExample;
  selectRelease: (item: ReleaseExample) => void;
  children: ComponentChildren;
}) {
  const [presetId, setPresetId] = useState<(typeof PRESETS)[number]["id"]>("standard-sre");
  const [included, setIncluded] = useState<string[]>(COMPONENTS.slice(0, 3).map((item) => item.id));
  const [menus, setMenus] = useState<string[]>(MENU_EXAMPLES.slice(0, 4).map((item) => item.id));
  const [baseId, setBaseId] = useState("0.5.2");
  const [requestQuery, setRequestQuery] = useState("");
  const [activityFilter, setActivityFilter] = useState("all");
  const [intent, setIntent] = useState<ReviewIntent | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [reason, setReason] = useState("");
  useEffect(() => setIntent(null), [area]);
  const current = EDITION_AREAS.find((item) => item.id === area)!;
  const preset = PRESETS.find((item) => item.id === presetId)!;
  const base = RELEASE_EXAMPLES.records.find((item) => item.id === baseId);
  if (!base) throw new Error(`Unknown example release: ${baseId}`);
  const requests = SAMPLE_REQUESTS.filter((item) =>
    `${item.id} ${item.releaseId} ${item.subscription}`.includes(requestQuery.trim().toLowerCase()));
  const activity = SAMPLE_ACTIVITY.filter((item) =>
    activityFilter === "all" || item.releaseId === activityFilter);

  const review = (label: string, target: string, boundary: string) => {
    setIntent({ label, target, boundary });
    setConfirmation("");
    setReason("");
  };
  const selectExample = (id: string) => {
    const item = RELEASE_EXAMPLES.records.find((candidate) => candidate.id === id);
    if (!item) throw new Error(`Unknown example release: ${id}`);
    selectRelease(item);
  };

  return <>
    {area !== "stencils" && <header class="dp-edition-section-title">
      <h2>{current.label}</h2><a href="#edition-navigation">↑ 메뉴</a>
    </header>}
    {area === "stencils" && <>
      <div class="dp-edition-choice" role="group" aria-label="예시 스텐실 프리셋">
        {PRESETS.map((item) => <button key={item.id} type="button" aria-pressed={presetId === item.id}
          onClick={() => {
            setPresetId(item.id);
            setIncluded(COMPONENTS.slice(0, item.workloadCount).map((part) => part.id));
            setMenus(MENU_EXAMPLES.slice(0, item.id === "lite-observe-alert" ? 2 : item.id === "standard-sre" ? 4 : 8).map((part) => part.id));
          }}>
          <strong>{item.label}</strong><span>{item.profile} · {item.workloadCount} workloads</span>
        </button>)}
      </div>
      <div class="dp-edition-info-grid">
        <section class="dp-edition-paper"><h3>Blueprint / {preset.label}</h3>
          <dl class="dp-edition-facts"><div><dt>Topology profile</dt><dd>{preset.id}</dd></div>
            <div><dt>프리셋 메뉴 규모</dt><dd>{preset.menuCount}개 · 운영 화면 기준</dd></div>
            <div><dt>화면용 메뉴 선택</dt><dd>대표 {menus.length}개 · 전체 카탈로그 아님</dd></div>
            <div><dt>화면용 구성 범주</dt><dd>{included.length}개 · 미선택 {COMPONENTS.length - included.length}개</dd></div>
            <div><dt>Azure 권한 / Feature Flag</dt><dd>운영 매니페스트에서 확인 필요</dd></div></dl>
          <button type="button" onClick={() => review("구성 검토 및 릴리스 등록", preset.label, "실제 Stencil 합성, 의존성 검사, 서명 및 revision 확인은 운영 화면에서만 수행합니다.")}>릴리스 등록 흐름 검토</button>
        </section>
        <section class="dp-edition-paper"><h3>구성 역할 선택</h3><p>화면용 선택 상태입니다. 정식 Stencil의 메뉴·루프·작업 의존성을 계산하지 않습니다.</p>
          <div class="dp-edition-checks">
            {COMPONENTS.map((part) => <label key={part.id}><input type="checkbox" checked={included.includes(part.id)}
              onChange={(event) => setIncluded(event.currentTarget.checked
                ? [...included, part.id] : included.filter((id) => id !== part.id))} />{part.name}</label>)}
          </div>
          <details class="dp-edition-disclosure"><summary>대표 메뉴 선택 보기</summary>
            <p>8개 대표 메뉴만 보여줍니다. 운영 메뉴 카탈로그와 Feature Flag는 기존 빌더에서 확인합니다.</p>
            <div class="dp-edition-checks">{MENU_EXAMPLES.map((item) => <label key={item.id}>
              <input type="checkbox" checked={menus.includes(item.id)} onChange={(event) => setMenus(event.currentTarget.checked
                ? [...menus, item.id] : menus.filter((id) => id !== item.id))} />{item.label}
            </label>)}</div>
          </details>
        </section>
      </div>
    </>}
    {area === "releases" && <>
      <div class="dp-edition-stage" role="group" aria-label="릴리스 승격 단계">
        {RINGS.map((ring, index) => <section key={ring.id} class="dp-edition-paper">
          <span class="dp-kicker">0{index + 1} / {ring.id}</span><h3>{ring.name}</h3>
          <p>{release.channel === ring.id ? `v${release.id} · 이 링의 예시` : "선택한 릴리스의 이 링 소속 증거 없음"}</p>
          <p class="dp-edition-small">{ring.rule}</p>
        </section>)}
      </div>
      <div class="dp-edition-actions">
        <button type="button" onClick={() => review("신규 릴리스 등록", "새 릴리스", "정확한 버전·매니페스트, 사유, 리비전 및 대상 확인이 필요합니다.")}>신규 등록 흐름</button>
        <button type="button" onClick={() => review("DEV 서명·발행", release.id, "서명·발행은 운영 서버가 매니페스트를 검증한 뒤 수행합니다.")}>DEV 발행 검토</button>
        <button type="button" onClick={() => review("다음 채널 승격", release.id, "출발 링, 레이블, 리콜·카나리·관찰 시간 검사가 필요합니다.")}>승격 근거 검토</button>
        <button type="button" onClick={() => review("릴리스 회수", release.id, "회수에는 정확한 대상과 별도 확인·사유가 필요합니다.")}>회수 절차 검토</button>
      </div>
      <div class="dp-edition-info-grid">
        <section class="dp-edition-paper"><h3>승격 근거 / {release.id}</h3>
          <ul class="dp-edition-evidence"><li>서명·매니페스트: 이 예시에 검증 자료 없음</li>
            <li>레이블·리콜: 서버 검증 결과 없음</li><li>카나리 정상 수 / 관찰 시간: 기록 없음</li>
            <li>발행·배포 작업 상태: 이 프리뷰에서 제공하지 않음</li></ul></section>
        <section class="dp-edition-paper dp-edition-compare" aria-label="버전 비교">
          <div class="dp-edition-compare-head">
            <h3>버전 비교</h3>
            <label>기준<select aria-label="기준 버전" value={baseId} onChange={(event) => setBaseId(event.currentTarget.value)}>
              {RELEASE_EXAMPLES.records.map((item) => <option key={item.id} value={item.id}>v{item.id}</option>)}
            </select></label>
          </div>
          <table class="dp-edition-compare-table">
            <thead><tr><th scope="col">항목</th><th scope="col">기준 v{base.id}</th><th scope="col">선택 v{release.id}</th></tr></thead>
            <tbody><tr><th scope="row">에디션</th><td>{base.edition}</td><td>{release.edition}</td></tr>
              <tr><th scope="row">구성 범주</th><td>{base.components}개</td><td>{release.components}개</td></tr>
              <tr><th scope="row">채널</th><td>{base.channel}</td><td>{release.channel}</td></tr></tbody>
          </table>
          <p class="dp-edition-compare-note">매니페스트 차이는 예시에서 제공하지 않습니다.</p>
        </section>
      </div>
      <div class="dp-edition-library"><h3>릴리스 목록</h3>{children}</div>
    </>}
    {area === "channels" && <>
      <div class="dp-edition-stage">
        {RINGS.map((ring, index) => <section key={ring.id} class="dp-edition-paper">
          <span class="dp-kicker">0{index + 1} / DEPLOYMENT RING</span><h3>{ring.id}</h3><p>{ring.name}</p>
          <p class="dp-edition-small">{ring.rule}</p>
          {RELEASE_EXAMPLES.records.filter((item) => item.channel === ring.id).map((item) =>
            <button type="button" key={item.id} class="dp-edition-link-button" onClick={() => selectRelease(item)}>v{item.id} · {item.edition}</button>)}
        </section>)}
      </div>
      <p class="dp-edition-small">채널 소속은 배포 자격의 예시일 뿐, 설치본 적용이나 승인·성공을 뜻하지 않습니다.</p>
      <button type="button" onClick={() => review("수동 채널 추가", release.id, "별도의 대상 채널·사유·리비전 확인이 필요합니다. 수동 편집은 검증된 단계 승격이 아닙니다.")}>수동 채널 편집 검토</button>
    </>}
    {area === "deployment-requests" && <>
      <label class="dp-edition-filter">요청 검색<input type="search" value={requestQuery}
        onInput={(event) => setRequestQuery(event.currentTarget.value)} placeholder="ID · 구독 · 버전" /></label>
      <div class="dp-table-wrap" role="region" aria-label="예시 배포 요청 목록" tabIndex={0}>
        <table class="dp-table"><caption>자체 보고 요청 · 소유권·배포 결과 미확인</caption>
          <thead><tr><th scope="col">요청 ID</th><th scope="col">구독 (예시)</th><th scope="col">릴리스 / 채널</th><th scope="col">리전</th><th scope="col">상태</th></tr></thead>
          <tbody>{requests.map((item) => <tr key={item.id}>
            <td>{item.id}</td><td class="dp-mono">{item.subscription}</td><td><button type="button" onClick={() => selectExample(item.releaseId)}>v{item.releaseId}</button><small>{item.channel}</small></td>
            <td>{item.region}</td><td>요청됨 · 효과 미확인</td>
          </tr>)}</tbody>
        </table>{requests.length === 0 && <p class="dp-empty">일치하는 예시 요청이 없습니다.</p>}
      </div><p class="dp-edition-small" role="status">{requests.length}건 표시</p>
    </>}
    {area === "activity" && <>
      <label class="dp-edition-filter">릴리스별 예시 활동<select value={activityFilter} onChange={(event) => setActivityFilter(event.currentTarget.value)}>
        <option value="all">전체 예시</option>{RELEASE_EXAMPLES.records.map((item) => <option key={item.id} value={item.id}>v{item.id}</option>)}
      </select></label>
      <ol class="dp-edition-activity">{activity.map((item) => <li key={item.id}>
        <span class="dp-kicker">{item.id} / SAMPLE</span><h3>{item.label}</h3>
        <button type="button" class="dp-edition-link-button" onClick={() => selectExample(item.releaseId)}>릴리스 v{item.releaseId} 살펴보기</button>
        <p>{item.note}</p></li>)}</ol>
      <p class="dp-edition-small">실제 이벤트의 리비전·시각·행위자 증거는 이 프리뷰에 없습니다. 운영 감사 이력과 혼동하지 마세요.</p>
    </>}
    {area === "trust" && <>
      <div class="dp-edition-info-grid">
        <section class="dp-edition-paper"><h3>카탈로그 Export</h3>
          <dl class="dp-edition-facts"><div><dt>서명 키 ID</dt><dd>제공되지 않음</dd></div>
            <div><dt>리비전 / SHA-256 핀</dt><dd>제공되지 않음</dd></div>
            <div><dt>만료·유효 시간</dt><dd>검증할 수 없음</dd></div>
            <div><dt>서명 검증 결과</dt><dd>없음 · 서명된 카탈로그 아님</dd></div></dl>
          <button type="button" onClick={() => review("카탈로그 갱신", "Export", "현재 리비전, 정확한 확인 문자열, 서명 키와 유효기간 확인이 필요합니다.")}>유효기간 갱신 절차</button>
        </section>
        <section class="dp-edition-paper"><h3>기능별 회수 · Surgical Recall</h3>
          <p>어떤 릴리스의 어느 기능을 차단할지 정확히 지정합니다. 예시에는 활성 기능 리콜 기록이 없습니다.</p>
          <ul class="dp-edition-evidence"><li>회수 범위: 미선택</li><li>서명 및 릴리스 영향: 검증 자료 없음</li>
            <li>해제는 별도의 신뢰 검사를 거쳐야 합니다.</li></ul>
          <button type="button" onClick={() => review("기능 회수 또는 해제", release.id, "정확한 기능 ID, 사유, 리비전·확인 및 카탈로그 재조회가 필요합니다.")}>회수·해제 절차</button>
        </section>
      </div>
    </>}
    {intent && <section class="dp-edition-review" role="region" aria-label="운영 절차 미리보기">
      <button type="button" class="dp-edition-review-close" onClick={() => setIntent(null)}>닫기</button>
      <span class="dp-kicker" role="status">REVIEW ONLY / 작업은 실행되지 않았습니다</span>
      <h3>{intent.label} · {intent.target}</h3><p>{intent.boundary}</p>
      <div class="dp-edition-review-fields">
        <label>현재 카탈로그 리비전<input disabled value="프리뷰에서 제공되지 않음" /></label>
        <label>정확한 대상 확인<input value={confirmation} autoComplete="off" placeholder={intent.target}
          onInput={(event) => setConfirmation(event.currentTarget.value)} /></label>
        <label>작업 사유<textarea value={reason} rows={2} placeholder="검토 사유 예시"
          onInput={(event) => setReason(event.currentTarget.value)} /></label>
      </div>
      <p>입력한 내용은 이 페이지의 임시 화면 상태일 뿐입니다. 인증·실제 리비전·서명·권한 없이 결과를 저장하거나 API에 전송하지 않습니다.</p>
      <button type="button" disabled>프리뷰에서 실행할 수 없음</button>
      <a href="/">인증된 운영 화면에서 확인하기 ↗</a>
    </section>}
  </>;
}
