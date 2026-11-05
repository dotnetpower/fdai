import type { ComponentChildren } from "preact";
import { DESIGNS, previewPath, STATUS_LABELS, type HubId, type SampleStatus } from "./model";
import "./studio.css";

export function StudioShell({ hub, design, dark = false, children }: {
  hub: HubId; design: string; dark?: boolean; children: ComponentChildren;
}) {
  const current = DESIGNS[hub].find((item) => item.id === design);
  return <div class={`dp-studio dp-${design}${dark ? " dp-dark" : ""}`} lang="ko">
    <a class="dp-skip" href="#preview-content">본문으로 건너뛰기</a>
    <header class="dp-masthead">
      <a class="dp-brand" href="/" aria-label={`FDAI ${hub === "release" ? "Release" : "Lifecycle"} Hub 운영 화면`}>
        <img src="/brand/fdai-logo.png" alt="FDAI" />
        <span>{hub === "release" ? "Release Hub" : "Lifecycle Hub"}<small>{hub === "release" ? "Edition preview" : "Design collection / 2026"}</small></span>
      </a>
      {DESIGNS[hub].length > 1 && <nav class="dp-switcher" aria-label="시안 선택">
          {DESIGNS[hub].map((item, index) => <a key={item.id} href={`/design-previews/${item.id}`}
            aria-current={item.id === design ? "page" : undefined}>
            <span aria-hidden="true">0{index + 1}</span> {item.name}
          </a>)}
        </nav>}
      <a class="dp-exit" href="/">운영 화면으로 <span aria-hidden="true">↗</span></a>
    </header>
    <div class="dp-notice"><strong>예시 데이터 · SAMPLE</strong><span>디자인 검토 전용. 실제 운영 상태가 아니며 서명·승격·배포를 실행하지 않습니다.</span></div>
    <main id="preview-content" tabIndex={-1}>{children}</main>
    <footer class="dp-footer"><span>{current?.name} / {current?.subtitle}</span><span>고정 예시 · 운영 API 연결 없음</span></footer>
  </div>;
}

export function PreviewNotFound({ hub }: { hub: HubId }) {
  const first = hub === "release" ? previewPath("release", "edition") : previewPath("lifecycle", "atlas");
  return <StudioShell hub={hub} design=""><div class="dp-page"><h1>시안을 찾을 수 없습니다</h1>
    <p>이 Hub에 등록된 시안을 선택해 주세요.</p><a href={first}>시안 열기</a></div></StudioShell>;
}

export function Status({ value }: { value: SampleStatus }) {
  return <span class={`dp-status dp-status-${value}`}>{STATUS_LABELS[value]}</span>;
}

export function Heading({ index, eyebrow, title, description }: {
  index: string; eyebrow: string; title: string; description: string;
}) {
  return <header class="dp-heading"><div class="dp-kicker">{index} / {eyebrow}</div>
    <h1>{title}</h1><p>{description}</p></header>;
}

export function EvidenceNote() {
  return <details class="dp-provenance"><summary>데이터 출처와 검토 범위</summary>
    <p>모든 항목은 이 시안을 위해 만든 고정 예시입니다. 관측 시각과 실제 서명·소유권·건강 상태 증거는 없습니다.
      선택과 필터는 이 페이지의 메모리에서만 바뀌며 새로고침하면 초기화됩니다.</p>
  </details>;
}
