import { additionalManualSlides } from "./manual-content.js";

const manualSlides = {
  "executive-briefing": [
    {
      eyebrow: "FDAI / EXECUTIVE BRIEFING",
      brandLogo: "assets/microsoft-logo.png",
      deckTitle: "FDAI Executive Briefing",
      overline: "Forward Deployed Agents",
      showDate: true,
      title: "<span class=\"executive-title-line\">에이전트가 <em>자율적으로 운영</em>하고,</span><span class=\"executive-title-line\">사람은 <em>판단하고 책임집니다</em></span>",
      lead: "FDAI는 운영 신호와 조직의 표준 절차를 연결해 반복 업무를 처리합니다.<strong>사람은 목표와 경계를 정하고, 중요한 결정을 승인하며, 결과를 책임집니다.</strong>",
      layout: "cover deck-executive-briefing",
      content: `
        <figure class="cover-photo">
          <img src="assets/executive-briefing.jpeg" alt="다양한 형태가 연결된 흐름을 따라 움직이는 추상 이미지">
        </figure>`,
    },
    {
      eyebrow: "01 / EXECUTIVE DECISION",
      title: "기존 도구를 연결해 운영 방식 자체를 바꿀 수 있습니다",
      lead: "FDAI는 이미 사용하는 관측, 티켓, 실행 도구를 연결합니다. 운영 신호를 판단과 승인으로 이어 실제 효과까지 확인할 수 있습니다.",
      layout: "executive-choice",
      content: `
        <div class="executive-model-visual">
          <div class="executive-model-shift">
            <article class="executive-model-panel" data-state="AS-IS">
              <small>현재 · 도구 중심</small>
              <strong>사람이 도구 사이의<br>판단을 연결합니다</strong>
              <div class="executive-model-route"><span>신호</span><i></i><span>사람</span><i></i><span>티켓</span></div>
              <p>운영자가 매번 맥락을 모으고 승인과 결과를 직접 연결합니다.</p>
            </article>
            <div class="executive-model-pivot">
              <small>OPERATING MODEL SHIFT</small>
              <span aria-hidden="true">→</span>
              <strong>반복 가능한 판단을<br>디지털 운영 조직에 배정</strong>
            </div>
            <article class="executive-model-panel target" data-state="TO-BE">
              <small>목표 · 운영 모델 중심</small>
              <strong>에이전트가 운영하고<br>사람은 경계를 결정합니다</strong>
              <div class="executive-model-route detailed" role="img" aria-label="클라우드 변화 감지, 근거 기반 판단과 승인, 안전한 실행과 운영 효과 검증">
                <span><strong>변화 감지</strong><small>상태·이벤트</small></span><i></i>
                <span><strong>판단·승인</strong><small>근거·정책</small></span><i></i>
                <span><strong>실행·검증</strong><small>조치·효과</small></span>
              </div>
              <p>에이전트가 반복 흐름을 연결하고, 사람은 중요한 승인과 예외를 판단합니다.</p>
            </article>
          </div>
          <div class="executive-shift-principles">
            <span><b>01</b><strong>기존 도구 활용</strong><small>관측·티켓·실행 체계를 연결</small></span>
            <span><b>02</b><strong>사람의 판단 집중</strong><small>목표·승인·예외에 집중</small></span>
            <span><b>03</b><strong>효과로 완료</strong><small>실행 후 독립적으로 검증</small></span>
          </div>
        </div>`,
    },
    {
      eyebrow: "02 / FDAI AT A GLANCE",
      title: "15개 에이전트가 하나의 운영 흐름에서 책임을 나눕니다",
      lead: "클라우드가 복잡해져도 관찰, 이해, 판단, 실행, 검증을 하나의 흐름으로 연결할 수 있습니다.",
      layout: "executive-blueprint",
      content: `
        <div class="executive-blueprint-layout">
          <figure class="executive-blueprint-core">
            <img src="assets/target-architecture.jpeg" alt="">
            <figcaption>
              <small>EVIDENCE-GOVERNED CONTROL PLANE</small>
              <strong>디지털 운영 조직</strong>
              <span>반복 업무는 자율적으로, 중요한 결정은 책임 있게</span>
            </figcaption>
          </figure>
          <div class="executive-closed-loop" role="img" aria-label="클라우드 변화 관찰, 온톨로지로 의미 해석, 규칙과 정책으로 판단, 권한에 따른 실행, 독립적인 효과 검증으로 이어지는 폐쇄 루프">
            <div><b>01</b><strong>관찰</strong><small>상태·변화·이상</small></div><i></i>
            <div><b>02</b><strong>이해</strong><small>온톨로지·관계·시간</small></div><i></i>
            <div><b>03</b><strong>판단</strong><small>규칙·정책·근거</small></div><i></i>
            <div><b>04</b><strong>실행</strong><small>권한·안전장치</small></div><i></i>
            <div><b>05</b><strong>검증</strong><small>실제 효과·감사</small></div>
          </div>
          <div class="executive-blueprint-foundations">
            <span><b>15</b><strong>책임이 분리된 에이전트</strong><small>판단·승인·실행을 한 주체가 소유하지 않음</small></span>
            <span><b>1</b><strong>공유 운영 온톨로지</strong><small>대상·관계·근거의 의미를 동일하게 해석</small></span>
            <span><b>T0-T2</b><strong>충분한 판단이 가능한 최소 Tier</strong><small>규칙, 재사용, 근거 기반 추론을 단계적으로 적용</small></span>
          </div>
        </div>
        <p class="executive-bottom-line">FDAI는 조직에 축적된 운영 규칙과 표준 절차를 먼저 적용합니다. 새로운 상황에는 현재 근거를 연결해 운영자가 판단할 수 있는 선택지를 제시합니다.</p>`,
    },
    {
      eyebrow: "03 / AGENT ORGANIZATION",
      title: "운영 온톨로지가 공통 맥락을 만들고, 에이전트가 역할별로 처리합니다",
      lead: "온톨로지는 대상, 관계, 시간, 근거의 의미를 연결합니다. 각 에이전트는 스키마로 검증된 이벤트를 통해 협업합니다.",
      layout: "executive-pantheon",
      content: `
        <div class="executive-pantheon-layout">
          <aside class="executive-ontology-core">
            <small>SHARED SEMANTIC READ MODEL</small>
            <strong>운영 온톨로지</strong>
            <p>리소스·서비스·목표·의존성·근거·허용된 행동을 하나의 의미 체계로 연결합니다.</p>
            <div><span>대상</span><span>관계</span><span>시간</span><span>근거</span><span>권한 경계</span></div>
            <b>의미는 권한을 부여하지 않습니다</b>
          </aside>
          <section class="executive-agent-groups" aria-label="FDAI의 고정된 15개 에이전트">
            <article class="governance">
              <header><span>GOVERNANCE STAFF</span><b>5</b></header>
              <div>
                <span><b>Odin 에이전트</b><small>목표 조정</small></span><span><b>Saga 에이전트</b><small>감사</small></span>
                <span><b>Mimir 에이전트</b><small>규칙 관리</small></span><span><b>Muninn 에이전트</b><small>기억</small></span>
                <span><b>Norns 에이전트</b><small>학습 후보</small></span>
              </div>
            </article>
            <article class="pipeline">
              <header><span>CONTROL PIPELINE</span><b>7</b></header>
              <div>
                <span><b>Huginn 에이전트</b><small>이벤트 수집</small></span><span><b>Heimdall 에이전트</b><small>관찰·예측</small></span>
                <span><b>Forseti 에이전트</b><small>판단</small></span><span><b>Var 에이전트</b><small>승인 전달</small></span>
                <span><b>Thor 에이전트</b><small>실행</small></span><span><b>Vidar 에이전트</b><small>복구</small></span>
                <span><b>Bragi 에이전트</b><small>대화·설명</small></span>
              </div>
            </article>
            <article class="specialists">
              <header><span>DOMAIN SPECIALISTS</span><b>3</b></header>
              <div>
                <span><b>Njord 에이전트</b><small>비용</small></span><span><b>Freyr 에이전트</b><small>용량</small></span>
                <span><b>Loki 에이전트</b><small>복원력 실험</small></span>
              </div>
            </article>
          </section>
        </div>
        <div class="executive-event-fabric"><span>AGENT</span><i></i><strong>타입 이벤트 · 스키마 검증 · 단일 소유자 · 재현 가능한 감사</strong><i></i><span>AGENT</span><b>직접 호출 없음</b></div>`,
    },
    {
      eyebrow: "04 / SOVEREIGN OPERATIONS",
      title: "데이터 위치, 접속 경로, 신원, AI 사용 범위를 직접 통제할 수 있습니다",
      lead: "FDAI는 고객이 승인한 리전, 사설 연결, 신원, 모델 범위 안에서 운영되도록 구성할 수 있습니다.",
      layout: "executive-sovereign",
      content: `
        <div class="executive-sovereign-layout">
          <figure class="executive-sovereign-art">
            <img src="assets/operating-model.jpeg" alt="">
            <figcaption><small>SOVEREIGN-BY-DESIGN</small><strong>데이터의 위치와<br>사용 권한을<br>고객이 결정합니다</strong><span>데이터·연결·신원·AI 사용 범위를 정책으로 고정</span></figcaption>
          </figure>
          <section class="executive-sovereign-boundary">
            <header><span>SOVEREIGN OPERATING ENVELOPE</span><strong>고객 정책이 운영 경계가 됩니다</strong><small>검증된 배포 조건만 실제 운영에 적용합니다</small></header>
            <div class="executive-sovereign-controls">
              <article><b>01</b><strong>저장 위치</strong><span>운영 데이터와 감사 기록은 고객이 승인한 리전과 저장소에만 남습니다.</span></article>
              <article><b>02</b><strong>접속 경로</strong><span>수집, 처리, 모델 호출은 승인된 사설 연결을 통해 이루어집니다.</span></article>
              <article><b>03</b><strong>접근 통제</strong><span>Managed Identity와 최소 권한을 사용하고, 암호화 키는 고객이 관리합니다.</span></article>
              <article><b>04</b><strong>AI 운영</strong><span>승인된 리전과 모델 범위에서 규칙, 예측, 학습, LLM 추론을 조합합니다.</span></article>
            </div>
            <div class="executive-sovereign-assurances" aria-label="소버린 운영의 핵심 보장">
              <span><b>DATA RESIDENCY</b><strong>데이터 위치를 고객이 결정</strong></span>
              <span><b>ACCESS CONTROL</b><strong>접근 권한과 키를 고객이 통제</strong></span>
              <span><b>BOUNDED AUTHORITY</b><strong>검증한 범위에만 운영 권한 부여</strong></span>
            </div>
          </section>
        </div>
        <p class="executive-bottom-line">이 구성은 FDAI의 목표 배포 형태입니다. 준비도를 진단한 뒤 데이터 이동, 격리, 복구를 검증한 범위부터 시작할 수 있습니다.</p>`,
    },
    {
      eyebrow: "05 / DETERMINISTIC SCALE",
      title: "운영 규모가 커져도 충분한 판단이 가능한 최소 Tier에서 처리합니다",
      lead: "FDAI는 규칙, 검증된 재사용, 예측, LLM 추론을 하나의 AIOps 경로에서 단계적으로 적용합니다.",
      layout: "executive-rules",
      content: `
        <div class="executive-rules-layout">
          <section class="executive-tier-stack" aria-label="T0 규칙과 정책, T1 검증된 재사용, T2 제한된 추론으로 구성된 판단 단계">
            <header><small>EVENT VOLUME</small><strong>클라우드 운영 사건</strong><span>상태·변경·이상·비용·용량</span></header>
            <div class="t0"><b>T0</b><strong>규칙·정책 카탈로그</strong><span>반복 가능한 다수 · 동일 입력은 동일 판단</span></div>
            <div class="t1"><b>T1</b><strong>검증된 해결 재사용</strong><span>과거 사건·근거·결과가 함께 일치할 때만</span></div>
            <div class="t2"><b>T2</b><strong>근거 기반 제한 추론</strong><span>새롭고 모호한 소수 · 검증기와 정책을 다시 통과</span></div>
          </section>
          <section class="executive-decision-outcomes">
            <header><small>RISK + AUTHORITY GATE</small><strong>판단 결과는 세 갈래입니다</strong></header>
            <article class="automatic"><b>자동 처리</b><span>낮은 영향 · 완전한 근거 · 승격된 기능</span></article>
            <article class="human"><b>사람 판단</b><span>중요한 영향 · 정책상 승인 · 목표 충돌</span></article>
            <article class="hold"><b>보류·거부</b><span>근거 부족 · 오래된 맥락 · 검증 실패 · 권한 없음</span></article>
            <p><strong>승인 요청도 운영 부하입니다.</strong> FDAI는 재확인·규칙 처리·안전한 축소를 먼저 수행하고, 사람이 꼭 필요한 사안만 전달합니다.</p>
          </section>
        </div>
        <div class="executive-rule-principle"><span>사람의 역할</span><strong>모든 티켓을 승인하는 사람이 아니라 목표·정책·예외를 책임지는 운영자</strong><b>NO APPROVAL SPAM</b></div>`,
    },
    {
      eyebrow: "06 / HANDOVER AND LEARNING",
      title: "반복되는 대응은 검토 가능한 운영 지식으로 축적됩니다",
      lead: "FDAI는 사례, 런북, 판단 근거, 실제 결과를 함께 보존합니다. 검토를 통과한 지식만 다음 대응에 재사용합니다.",
      layout: "executive-handover",
      content: `
        <div class="executive-handover-layout">
          <figure>
            <img src="assets/pilot-production.jpeg" alt="노트북 앞에서 협업하는 운영 책임자">
            <figcaption><small>HUMAN-TO-AGENT HANDOVER</small><strong>업무와 판단 근거를<br>함께 인수인계</strong></figcaption>
          </figure>
          <section class="executive-knowledge-path">
            <article><b>01</b><small>CAPTURE</small><strong>사람이 처리한 사례</strong><span>런북·근거·결정·실제 결과를 하나의 사례로 보존</span></article>
            <i></i>
            <article><b>02</b><small>PROPOSE</small><strong>검증 전 지식 후보</strong><span>Norns(학습 후보 제안 담당) 에이전트가 후보를 제안</span></article>
            <i></i>
            <article><b>03</b><small>REVIEW</small><strong>규칙 품질 검토</strong><span>Mimir(규칙 검토 담당) 에이전트와 사람이 근거를 검토</span></article>
            <i></i>
            <article><b>04</b><small>REUSE</small><strong>규칙 또는 검증된 재사용</strong><span>이후 같은 사건을 T0 또는 T1에서 더 빠르게 처리</span></article>
          </section>
        </div>
        <aside class="executive-forecast-lane"><small>FORECAST</small><strong>운영 이력 + 시간 + 의존 관계</strong><i></i><span>용량, 인증서, 예산, 복구 위험을 미리 살펴볼 수 있습니다.</span><b>근거가 부족하면 보류하고 결과와 제안을 운영자에게 보고합니다.</b></aside>`,
    },
    {
      eyebrow: "07 / ADOPTION DECISION TREE",
      title: "네 가지 준비 영역을 확인하면 시작 범위와 보완 계획을 정할 수 있습니다",
      lead: "IaC, 운영 데이터, 표준 절차, 실행 안전장치를 함께 진단합니다. 준비된 영역은 관찰 모드로 시작하고 나머지는 실행 계획으로 정리합니다.",
      layout: "executive-readiness",
      content: `
        <div class="executive-readiness-tree" role="img" aria-label="IaC, 신뢰 가능한 운영 데이터, 표준 절차와 완료 기준, 실행 안전장치를 확인해 관찰 모드 시작 범위와 준비 계획을 정하는 흐름">
          <article><small>CONDITION 01</small><strong>변경 경로를 검토하고<br>재현할 수 있는가?</strong><span>IaC 또는 GitOps 기준선</span><b>준비됨 · 다음 조건</b><em>준비 필요<br>FDAI로 IaC 전환 계획 수립</em></article>
          <i></i>
          <article><small>CONDITION 02</small><strong>상태, 관계, 관측 데이터를<br>신뢰할 수 있는가?</strong><span>범위, 시간, 출처, 완전성</span><b>준비됨 · 다음 조건</b><em>준비 필요<br>관측성과 온톨로지 진단</em></article>
          <i></i>
          <article><small>CONDITION 03</small><strong>반복 절차와 완료 기준을<br>설명할 수 있는가?</strong><span>런북, 담당자, 측정 지표</span><b>준비됨 · 다음 조건</b><em>준비 필요<br>절차와 기준선 수립</em></article>
          <i></i>
          <article><small>CONDITION 04</small><strong>실행 권한과 복구 경로를<br>검증할 수 있는가?</strong><span>권한, 가상 실행, 복구, 감사</span><b>준비됨 · 관찰 모드 검토</b><em>준비 필요<br>실행 안전장치 설계</em></article>
          <i></i>
          <div class="executive-ready-outcome"><small>STARTING POINT</small><strong>관찰 모드 시작 범위</strong><span>운영자 검토 후 파일럿 계획 수립</span></div>
        </div>
        <div class="executive-readiness-no-go">
          <strong>준비되지 않은 영역도 FDAI로 진단하고 보완 계획을 만들 수 있습니다</strong>
          <span>실제 변경은 필수 안전장치를 검증한 범위에서만 검토합니다.</span>
          <b>DIAGNOSE · PREPARE · VALIDATE</b>
        </div>`,
    },
    {
      eyebrow: "08 / EVIDENCE-LED ADOPTION",
      title: "첫 검증 시나리오 하나를 관찰 모드에서 시작합니다",
      lead: "반복 가능하고 효과를 측정할 수 있는 운영 판단 하나를 선택합니다. 실제 변경 없이 FDAI의 판단을 현재 운영 결과와 비교합니다.",
      layout: "executive-adoption",
      content: `
        <div class="executive-pilot-criteria">
          <span><b>01</b><strong>IaC 범위</strong><small>변경 경로가 검토·재현 가능</small></span>
          <span><b>02</b><strong>반복 사건</strong><small>현재 런북과 담당자가 존재</small></span>
          <span><b>03</b><strong>측정 효과</strong><small>실행 결과를 독립 관찰 가능</small></span>
          <span><b>04</b><strong>안전한 복구</strong><small>중지·롤백·영향 범위가 명확</small></span>
        </div>
        <div class="executive-adoption-path">
          <article><span>01</span><small>REGISTER</small><strong>범위, 책임자, 안전장치</strong><p>시나리오와 권한 상한을 정합니다.</p></article><i></i>
          <article><span>02</span><small>OBSERVE</small><strong>판단</strong><p>사람의 실제 결정과 비교합니다.</p></article><i></i>
          <article><span>03</span><small>COMPARE</small><strong>품질·안전성 비교</strong><p>정확도와 검토 부하를 동일한 사건 집합으로 측정합니다.</p></article><i></i>
          <article><span>04</span><small>REVIEW</small><strong>운영자 승격 검토</strong><p>관찰 근거를 보고 실행 여부를 결정합니다.</p></article><i></i>
          <article class="enforce"><span>05</span><small>BOUNDED ENFORCEMENT</small><strong>승인된 범위만 실행</strong><p>회귀하면 즉시 관찰 모드로 돌아갑니다.</p></article>
        </div>
        <div class="executive-measures"><span>판단 정확도</span><span>사람에 의한 검토 비율</span><span>정책 위반 건수</span><span>복구 절차 검증률</span><span>별도 관측을 통한 효과 확인률</span></div>`,
    },
    {
      eyebrow: "09 / NEXT DECISION",
      title: "오늘은 도입 승인보다 첫 검증 범위를 정하는 것으로 시작합니다",
      lead: "첫 시나리오의 현재 기준선, 데이터, 권한, 실행 안전장치를 함께 확인하면 다음 투자 결정을 위한 근거를 만들 수 있습니다.",
      layout: "executive-decision",
      content: `
        <div class="executive-decision-layout">
          <div class="executive-decision-list">
            <div><span>01</span><strong>스폰서와 R&R 지정</strong><p>가치, 위험, 데이터, 운영 결과의 책임자를 정합니다.</p></div>
            <div><span>02</span><strong>첫 검증 시나리오 1개 선택</strong><p>반복 가능하고 현재 효과를 측정할 수 있는 운영 판단을 선택합니다.</p></div>
            <div><span>03</span><strong>준비도와 기준선 워크숍</strong><p>현재 시간, 검토 부하, 품질, 복구 경로를 함께 확인합니다.</p></div>
          </div>
          <figure class="executive-decision-visual console-sign-in">
            <img src="assets/fdai-console-sign-in.png" alt="우주 배경 중앙에 FDAI Console의 Entra ID 로그인 화면이 표시된 모습">
            <figcaption class="console-sign-in-invitation"><strong>도입 검토를 시작하세요</strong></figcaption>
          </figure>
        </div>`,
    },
  ],
  ...additionalManualSlides,
};

const dateFormatter = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "short",
  day: "numeric",
});

const page = document.body.dataset.page;
const viewer = document.querySelector("#viewer");
const stage = document.querySelector("#slide-stage");
const fullscreenRoot = stage;
const viewerTitle = document.querySelector("#viewer-title");
const progressBar = document.querySelector("#progress-bar");
const progressLabel = document.querySelector("#progress-label");
const announcement = document.querySelector("#slide-announcement");
const slideCanvas = Object.freeze({ width: 1536, height: 864 });
const slideResizeObserver = new ResizeObserver(updateSlideScale);
let catalog;
let activeManual;
let currentSlide = 0;
let drawerTrigger = null;
let selectedManualIndex = 0;
let suppressCoverflowClick = false;

function formatDate(value) {
  return dateFormatter.format(new Date(`${value}T00:00:00Z`));
}

function requestedSlideIndex(value) {
  if (value === null) return 0;
  const slideNumber = Number(value);
  return Number.isSafeInteger(slideNumber) && slideNumber > 0 ? slideNumber - 1 : 0;
}

function replaceViewerUrl(manual, slideIndex) {
  if (page !== "library") return;
  const url = new URL(window.location.href);
  url.searchParams.set("manual", manual.id);
  url.searchParams.set("slide", String(slideIndex + 1));
  window.history.replaceState(null, "", url);
}

function updateSlideScale() {
  const stageStyle = getComputedStyle(stage);
  const horizontalInset =
    Number.parseFloat(stageStyle.paddingLeft) + Number.parseFloat(stageStyle.paddingRight);
  const verticalInset =
    Number.parseFloat(stageStyle.paddingTop) + Number.parseFloat(stageStyle.paddingBottom);
  const availableWidth = Math.max(1, stage.clientWidth - horizontalInset);
  const availableHeight = Math.max(1, stage.clientHeight - verticalInset);
  const scale = Math.min(
    availableWidth / slideCanvas.width,
    availableHeight / slideCanvas.height,
  );
  stage.style.setProperty("--slide-scale", String(scale));
}

function clearViewerUrl() {
  if (page !== "library") return;
  const url = new URL(window.location.href);
  url.searchParams.delete("manual");
  url.searchParams.delete("slide");
  window.history.replaceState(null, "", url);
}

function coverArtwork(manual) {
  const wipOverlay = manual.status === "wip"
    ? '<span class="manual-wip-overlay" aria-label="작업 중">WIP</span>'
    : "";
  return `
    <div class="album-art">
      <img src="${manual.coverImage}" alt="" draggable="false">
      ${wipOverlay}
      <span class="album-art-label">
        <small>${manual.kind === "core" ? "CORE DECK" : "DEEP DIVE"}</small>
        <strong>${manual.coverLabel}</strong>
      </span>
    </div>`;
}

function bookCoverMarkup(manual, reflection = false) {
  const stage = catalog.journey.stages.find((candidate) => candidate.id === manual.stageId);
  const kind = manual.kind === "core" ? "CORE DECK" : "DEEP DIVE";
  const wipOverlay = manual.status === "wip"
    ? '<span class="manual-wip-overlay" aria-label="작업 중">WIP</span>'
    : "";
  return `
    <span class="coverflow-book${reflection ? " coverflow-book-reflection" : ""}"${reflection ? " aria-hidden=\"true\"" : ""}>
      <span class="coverflow-book-image">
        <img src="${manual.coverImage}" alt="" draggable="false">
        <b>${manual.coverLabel}</b>
      </span>
      <span class="coverflow-book-copy">
        <small>${kind} · ${manual.level ?? "L100"} · ${String(stage.number).padStart(2, "0")}</small>
        <strong>${manual.title}</strong>
        <span>${manual.duration} · ${manual.slideCount} SLIDES</span>
      </span>
      ${wipOverlay}
    </span>`;
}

function albumCard(manual) {
  const article = document.createElement("article");
  article.className = `album-card${manual.featured ? " featured" : ""}`;
  const statusLabel = manual.status === "wip" ? " (작업 중)" : "";
  article.innerHTML = `
    <button type="button" aria-label="${manual.title}${statusLabel} 슬라이드 열기">
      ${coverArtwork(manual)}
      <span class="album-copy">
        <small>${manual.eyebrow}</small>
        <strong>${manual.title}</strong>
        <span>${manual.description}</span>
        <span class="album-meta"><time datetime="${manual.createdAt}">${formatDate(manual.createdAt)}</time><i></i>${manual.slideCount}장</span>
      </span>
    </button>`;
  article.querySelector("button").addEventListener("click", () => openViewer(manual));
  return article;
}

function renderAlbums(container) {
  container.replaceChildren(...catalog.manuals.map(albumCard));
}

function renderSlides(manual) {
  const slides = manualSlides[manual.id] ?? journeySlides(manual);
  if (!slides || slides.length !== manual.slideCount) {
    throw new Error(`Slide content does not match catalog entry: ${manual.id}`);
  }

  function journeySlides(manual) {
    const stage = catalog.journey.stages.find((candidate) => candidate.id === manual.stageId);
    return [
      {
        eyebrow: `FDAI / ${manual.eyebrow}`,
        title: manual.title,
        lead: manual.description,
        layout: "cover",
        content: `
          <figure class="cover-photo">
            <img src="${manual.coverImage}" alt="">
          </figure>`,
      },
      {
        eyebrow: `${String(stage.number).padStart(2, "0")} / ${stage.title}`,
        title: stage.question,
        lead: "고객의 현재 상태와 목표를 연결해 다음 의사결정과 산출물을 명확하게 정의합니다.",
        layout: "takeaway",
        content: `<blockquote>${manual.coverLabel}<br>from value to scale.</blockquote>`,
      },
      {
        eyebrow: "NEXT CONVERSATION",
        title: "다음 단계로 이어지는 의사결정을 준비합니다",
        lead: "Core Deck으로 공통 방향을 맞추고 필요한 Deep Dive를 선택해 근거와 설계를 구체화합니다.",
        layout: "journey",
        content: `<div class="journey"><span>Understand</span><i></i><span>Decide</span><i></i><span>Validate</span><i></i><span>Advance</span></div>`,
      },
    ];
  }
  stage.replaceChildren(...slides.map((slide, index) => {
    const section = document.createElement("section");
    section.className = `manual-slide slide-${slide.layout}`;
    section.dataset.index = String(index);
    section.innerHTML = `
      <header>
        <span class="slide-brand">${slide.brandLogo ? `<img src="${slide.brandLogo}" alt="Microsoft">` : "FDAI"}</span>
        <span>${slide.eyebrow}</span>
      </header>
      <div class="slide-copy">
        ${slide.deckTitle ? `<strong class="slide-deck-title">${slide.deckTitle}</strong>` : ""}
        ${slide.overline ? `<span class="slide-overline"><b>FDAI</b><i aria-hidden="true"></i>${slide.overline}</span>` : ""}
        <h2>${slide.title}</h2><p>${slide.lead}</p>
        ${slide.showDate ? `<time class="slide-date" datetime="${manual.createdAt}">${formatDate(manual.createdAt)}</time>` : ""}
      </div>
      <div class="slide-content">${slide.content}</div>
      <footer><span>${manual.title}</span><span>${String(index + 1).padStart(2, "0")}</span></footer>`;
    section.setAttribute("aria-label", `${index + 1}. ${section.querySelector("h2").textContent}`);
    return section;
  }));
}

function showSlide(index) {
  const slides = [...stage.querySelectorAll(".manual-slide")];
  currentSlide = Math.max(0, Math.min(slides.length - 1, index));
  slides.forEach((slide, slideIndex) => slide.classList.toggle("active", slideIndex === currentSlide));
  progressBar.style.width = `${((currentSlide + 1) / slides.length) * 100}%`;
  progressLabel.textContent = `${currentSlide + 1} / ${slides.length}`;
  const title = slides[currentSlide].querySelector("h2")?.textContent ?? "";
  announcement.textContent = `${activeManual.title}, ${currentSlide + 1} / ${slides.length}, ${title}`;
  document.querySelector("#previous-slide").disabled = currentSlide === 0;
  document.querySelector("#next-slide").disabled = currentSlide === slides.length - 1;
  replaceViewerUrl(activeManual, currentSlide);
}

function openViewer(manual, initialSlide = 0) {
  activeManual = manual;
  viewerTitle.textContent = manual.title;
  renderSlides(manual);
  viewer.showModal();
  updateSlideScale();
  showSlide(initialSlide);
}

function closeViewer() {
  if (document.fullscreenElement === fullscreenRoot) {
    void document.exitFullscreen().catch(reportFullscreenFailure);
  }
  viewer.close();
  clearViewerUrl();
}

function reportFullscreenFailure(error) {
  console.error("manual_studio_fullscreen_failed", error);
  const message = document.querySelector("#app-error");
  message.hidden = false;
  message.textContent = "전체 화면으로 전환하지 못했습니다. 브라우저 권한과 설정을 확인하세요.";
  announcement.textContent = message.textContent;
}

function bindViewer() {
  const fullscreenButton = document.querySelector("#fullscreen-manual");
  const fullscreenLabel = fullscreenButton.querySelector("span");
  const fullscreenPath = fullscreenButton.querySelector("path");
  const fullscreenSupported =
    document.fullscreenEnabled &&
    typeof fullscreenRoot.requestFullscreen === "function" &&
    typeof document.exitFullscreen === "function";

  function syncFullscreenButton() {
    const active = document.fullscreenElement === fullscreenRoot;
    const label = active ? "전체 화면 종료" : "전체 화면";
    const accessibleLabel = active ? "전체 화면 종료" : "전체 화면으로 보기";
    fullscreenButton.setAttribute("aria-pressed", String(active));
    fullscreenButton.setAttribute("aria-label", accessibleLabel);
    fullscreenButton.title = accessibleLabel;
    fullscreenLabel.textContent = label;
    fullscreenPath.setAttribute(
      "d",
      active
        ? "M9 3v6H3m12-6v6h6M9 21v-6H3m12 6v-6h6"
        : "M8 3H3v5m13-5h5v5M8 21H3v-5m13 5h5v-5",
    );
    updateSlideScale();
    requestAnimationFrame(updateSlideScale);
  }

  if (!fullscreenSupported) {
    fullscreenButton.disabled = true;
    fullscreenButton.setAttribute("aria-label", "전체 화면을 지원하지 않는 브라우저입니다");
    fullscreenButton.title = "전체 화면을 지원하지 않는 브라우저입니다";
  }

  document.querySelector("#viewer-close").addEventListener("click", closeViewer);
  document.querySelector("#previous-slide").addEventListener("click", () => showSlide(currentSlide - 1));
  document.querySelector("#next-slide").addEventListener("click", () => showSlide(currentSlide + 1));
  fullscreenButton.addEventListener("click", async () => {
    try {
      if (document.fullscreenElement === fullscreenRoot) {
        await document.exitFullscreen();
      } else {
        await fullscreenRoot.requestFullscreen();
      }
    } catch (error) {
      reportFullscreenFailure(error);
    }
  });
  document.addEventListener("fullscreenchange", syncFullscreenButton);
  slideResizeObserver.observe(stage);
  window.addEventListener("resize", updateSlideScale);
  document.fonts.ready.then(updateSlideScale).catch((error) => {
    console.error("manual_studio_font_readiness_failed", error);
  });
  syncFullscreenButton();
  document.querySelector("#print-manual").addEventListener("click", () => {
    document.body.classList.add("printing");
    window.print();
  });
  window.addEventListener("afterprint", () => document.body.classList.remove("printing"));
  viewer.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeViewer();
  });
  document.addEventListener("keydown", (event) => {
    if (!viewer.open) return;
    if (["ArrowRight", "PageDown", " "].includes(event.key)) {
      event.preventDefault();
      showSlide(currentSlide + 1);
    } else if (["ArrowLeft", "PageUp"].includes(event.key)) {
      event.preventDefault();
      showSlide(currentSlide - 1);
    } else if (event.key === "Home") {
      showSlide(0);
    } else if (event.key === "End") {
      showSlide(activeManual.slideCount - 1);
    }
  });
}

function focusableElements(container) {
  return [...container.querySelectorAll("a[href], button:not(:disabled), [tabindex]:not([tabindex='-1'])")];
}

function setupDrawer() {
  const trigger = document.querySelector("#help-trigger");
  const drawer = document.querySelector("#help-drawer");
  const scrim = document.querySelector("#drawer-scrim");
  const closeButton = document.querySelector("#drawer-close");
  const prototypeShell = document.querySelector(".prototype-shell");
  drawerTrigger = trigger;

  function setDrawerOpen(open) {
    prototypeShell.inert = open;
    drawer.classList.toggle("open", open);
    scrim.classList.toggle("open", open);
    drawer.setAttribute("aria-hidden", String(!open));
    trigger.setAttribute("aria-expanded", String(open));
    document.body.classList.toggle("drawer-open", open);
    if (open) {
      window.requestAnimationFrame(() => closeButton.focus());
    } else {
      trigger.focus();
    }
  }

  trigger.addEventListener("click", () => setDrawerOpen(trigger.getAttribute("aria-expanded") !== "true"));
  closeButton.addEventListener("click", () => setDrawerOpen(false));
  scrim.addEventListener("click", () => setDrawerOpen(false));
  drawer.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setDrawerOpen(false);
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = focusableElements(drawer);
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  });

  renderAlbums(document.querySelector("#drawer-library"));
  document.querySelector("#drawer-count").textContent = `${catalog.manuals.length}개 설명서`;
  document.querySelector("#catalog-date").textContent = `생성 ${formatDate(catalog.generatedAt.slice(0, 10))}`;
}

function setupLibrary() {
  document.querySelector("#library-count").textContent = `${catalog.manuals.length}개 설명서`;
  document.querySelector("#library-generated").textContent =
    `카탈로그 생성 ${formatDate(catalog.generatedAt.slice(0, 10))}`;
  const searchParams = new URL(window.location.href).searchParams;
  const requestedManualId = searchParams.get("manual");
  const requestedSlide = requestedSlideIndex(searchParams.get("slide"));
  const requestedIndex = requestedManualId === null
    ? -1
    : catalog.manuals.findIndex((manual) => manual.id === requestedManualId);
  selectedManualIndex = requestedIndex >= 0
    ? requestedIndex
    : catalog.manuals.findIndex((manual) => manual.id === "ontology-foundation");
  if (selectedManualIndex < 0) selectedManualIndex = 0;

  const stages = document.querySelector("#journey-stages");
  stages.replaceChildren(...catalog.journey.stages.map((stage) => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.stageId = stage.id;
    button.innerHTML = `
      <span>${String(stage.number).padStart(2, "0")}</span>
      <strong>${stage.title}</strong>`;
    button.addEventListener("click", () => {
      const preferred = catalog.manuals.findIndex((manual) =>
        manual.stageId === stage.id && (manual.featured || manual.kind === "core"));
      if (preferred >= 0) selectManual(preferred);
    });
    return button;
  }));

  document.querySelector("#previous-manual").addEventListener("click", () => {
    selectManual(selectedManualIndex - 1);
  });
  document.querySelector("#next-manual").addEventListener("click", () => {
    selectManual(selectedManualIndex + 1);
  });
  bindCoverflowDrag(document.querySelector("#library-coverflow"));
  document.addEventListener("keydown", (event) => {
    if (viewer.open || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      selectManual(selectedManualIndex - 1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      selectManual(selectedManualIndex + 1);
    }
  });
  renderCoverflow();

  if (requestedIndex >= 0) {
    openViewer(catalog.manuals[requestedIndex], requestedSlide);
  } else if (requestedManualId !== null) {
    console.warn("manual_studio_requested_manual_not_found", {
      manual_id: requestedManualId,
    });
    const message = document.querySelector("#app-error");
    message.hidden = false;
    message.textContent = "요청한 설명서를 이 카탈로그에서 찾을 수 없습니다.";
  }
}

function selectManual(index) {
  selectedManualIndex = Math.max(0, Math.min(catalog.manuals.length - 1, index));
  renderCoverflow();
}

function renderCoverflow() {
  const selected = catalog.manuals[selectedManualIndex];
  const activeStage = catalog.journey.stages.find((stage) => stage.id === selected.stageId);
  document.querySelector("#active-stage-number").textContent =
    String(activeStage.number).padStart(2, "0");
  document.querySelector("#active-stage-title").textContent = activeStage.title;
  document.querySelector("#active-stage-question").textContent = activeStage.question;
  document.querySelector("#active-stage-badge").hidden = !activeStage.differentiator;
  document.querySelectorAll("#journey-stages button").forEach((button) => {
    const current = button.dataset.stageId === activeStage.id;
    button.classList.toggle("active", current);
    button.setAttribute("aria-current", current ? "step" : "false");
  });

  const flow = document.querySelector("#library-coverflow");
  if (flow.children.length !== catalog.manuals.length) {
    flow.replaceChildren(...catalog.manuals.map((manual, index) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "coverflow-item";
      item.dataset.index = String(index);
      item.innerHTML = `${bookCoverMarkup(manual)}${bookCoverMarkup(manual, true)}`;
      item.addEventListener("click", () => {
        if (suppressCoverflowClick) {
          suppressCoverflowClick = false;
          return;
        }
        if (index === selectedManualIndex) {
          openViewer(manual);
        } else {
          selectManual(index);
        }
      });
      return item;
    }));
  }
  [...flow.children].forEach((item, index) => {
    const manual = catalog.manuals[index];
    const distance = index - selectedManualIndex;
    item.dataset.distance = String(Math.max(-3, Math.min(3, distance)));
    item.dataset.active = String(distance === 0);
    item.setAttribute("aria-hidden", String(Math.abs(distance) > 1));
    item.tabIndex = Math.abs(distance) > 1 ? -1 : 0;
    const statusLabel = manual.status === "wip" ? " (작업 중)" : "";
    item.setAttribute(
      "aria-label",
      distance === 0
        ? `${manual.title}${statusLabel} 슬라이드 열기`
        : `${manual.title}${statusLabel} 선택`,
    );
    item.setAttribute("aria-pressed", String(distance === 0));
  });

  document.querySelector("#previous-manual").disabled = selectedManualIndex === 0;
  document.querySelector("#next-manual").disabled = selectedManualIndex === catalog.manuals.length - 1;
}

function bindCoverflowDrag(flow) {
  const drag = { pointerId: null, startX: 0, deltaX: 0, targetIndex: null };
  const end = (event) => {
    if (drag.pointerId !== event.pointerId) return;
    if (flow.hasPointerCapture(event.pointerId)) {
      flow.releasePointerCapture(event.pointerId);
    }
    const moved = Math.abs(drag.deltaX) > 8;
    const { spacing } = coverflowMetrics();
    const movedCovers = Math.abs(drag.deltaX) >= 42
      ? Math.max(1, Math.round(Math.abs(drag.deltaX) / spacing))
      : 0;
    const nextIndex = movedCovers > 0
      ? Math.max(
          0,
          Math.min(
            catalog.manuals.length - 1,
            selectedManualIndex + (drag.deltaX < 0 ? movedCovers : -movedCovers),
          ),
        )
      : selectedManualIndex;
    flow.classList.remove("dragging");
    if (nextIndex !== selectedManualIndex) {
      selectManual(nextIndex);
      window.requestAnimationFrame(() => clearCoverflowDrag(flow));
    } else {
      clearCoverflowDrag(flow);
    }
    const clickedActiveCover = drag.targetIndex === selectedManualIndex;
    if (!moved && clickedActiveCover) {
      openViewer(catalog.manuals[selectedManualIndex]);
    }
    suppressCoverflowClick = moved || Boolean(clickedActiveCover);
    window.setTimeout(() => { suppressCoverflowClick = false; }, 0);
    drag.pointerId = null;
    drag.deltaX = 0;
    drag.targetIndex = null;
  };
  flow.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || viewer.open) return;
    drag.pointerId = event.pointerId;
    drag.startX = event.clientX;
    drag.deltaX = 0;
    const pointerTarget = event.target instanceof Element
      ? event.target.closest(".coverflow-item")
      : null;
    drag.targetIndex = pointerTarget === null ? null : Number(pointerTarget.dataset.index);
    flow.setPointerCapture(event.pointerId);
    flow.classList.add("dragging");
  });
  flow.addEventListener("pointermove", (event) => {
    if (drag.pointerId !== event.pointerId) return;
    const { spacing } = coverflowMetrics();
    const minimum = -(catalog.manuals.length - 1 - selectedManualIndex) * spacing;
    const maximum = selectedManualIndex * spacing;
    drag.deltaX = Math.max(minimum, Math.min(maximum, event.clientX - drag.startX));
    applyCoverflowDrag(flow, drag.deltaX);
  });
  flow.addEventListener("pointerup", end);
  flow.addEventListener("pointercancel", end);
}

function applyCoverflowDrag(flow, deltaX) {
  const { spacing, sideScale } = coverflowMetrics();
  [...flow.children].forEach((item, index) => {
    const position = index - selectedManualIndex + deltaX / spacing;
    const distance = Math.abs(position);
    const x = position * spacing;
    const rotation = Math.max(-30, Math.min(30, -position * 22));
    const scale = distance <= 1
      ? 1 - distance * (1 - sideScale)
      : Math.max(0.46, sideScale - (distance - 1) * 0.2);
    const brightness = Math.max(0.34, 1 - distance * 0.34);
    item.style.transform =
      `translateX(calc(-50% + ${x}px)) rotateY(${rotation}deg) scale(${scale})`;
    item.style.filter = `brightness(${brightness}) saturate(${Math.max(0.5, 1 - distance * 0.28)})`;
    item.style.opacity = distance >= 2.7 ? "0" : "1";
    item.style.zIndex = String(Math.max(1, 10 - Math.round(distance * 2)));
  });
}

function coverflowMetrics() {
  return window.innerWidth <= 480
    ? { spacing: 150, sideScale: 0.56 }
    : window.innerWidth <= 760
      ? { spacing: 200, sideScale: 0.66 }
      : { spacing: 280, sideScale: 0.7 };
}

function clearCoverflowDrag(flow) {
  [...flow.children].forEach((item) => {
    item.style.removeProperty("transform");
    item.style.removeProperty("filter");
    item.style.removeProperty("opacity");
    item.style.removeProperty("z-index");
  });
}

async function start() {
  const response = await fetch("catalog.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`Catalog request failed with HTTP ${response.status}.`);
  catalog = await response.json();
  bindViewer();
  if (page === "console") setupDrawer();
  if (page === "library") setupLibrary();
}

start().catch((error) => {
  console.error("manual_studio_start_failed", error);
  const message = document.querySelector("#app-error");
  message.hidden = false;
  message.textContent = "설명서 시안을 불러오지 못했습니다. 로컬 서버 상태를 확인하세요.";
  drawerTrigger?.setAttribute("disabled", "");
});
