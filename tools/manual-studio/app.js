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
      lead: "FDAI 에이전트는 정책과 승인 범위 안에서 운영 전 과정을 이어갑니다.<strong>사람은 목표와 경계를 정하고, 중요한 결정을 승인하며, 결과를 책임집니다.</strong>",
      layout: "cover",
      content: `
        <figure class="cover-photo">
          <img src="assets/executive-briefing.jpeg" alt="다양한 형태가 연결된 흐름을 따라 움직이는 추상 이미지">
        </figure>`,
    },
    {
      eyebrow: "01 / EXECUTIVE DECISION",
      title: "핵심은 도구를 추가하는 것이 아니라 운영 모델을 전환하는 것입니다",
      lead: "FDAI는 기존 도구를 그대로 활용해 클라우드 환경의 변화를 감지하고, 판단과 승인을 거쳐 안전하게 실행한 뒤 실제 운영 효과까지 확인합니다.",
      layout: "executive-choice",
      content: `
        <div class="executive-model-visual">
          <div class="executive-model-shift">
            <article class="executive-model-panel" data-state="AS-IS">
              <small>현재 · 도구 중심</small>
              <strong>사람이 도구 사이의<br>판단을 연결합니다</strong>
              <div class="executive-model-route"><span>신호</span><i></i><span>사람</span><i></i><span>티켓</span></div>
              <p>맥락 재구성, 승인 연결, 결과 확인이 운영자에게 반복됩니다.</p>
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
              <p>반복 업무는 에이전트가 처리하고, 중요한 승인과 예외만 사람에게 요청합니다.</p>
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
      title: "FDAI는 15개 에이전트가 함께 일하는 디지털 조직입니다",
      lead: "클라우드가 복잡해질수록 운영자가 확인하고 판단해야 할 변화도 늘어납니다. FDAI는 이 과정을 하나의 운영 흐름으로 연결합니다.",
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
            <div><b>04</b><strong>실행</strong><small>권한·안전 계약</small></div><i></i>
            <div><b>05</b><strong>검증</strong><small>실제 효과·감사</small></div>
          </div>
          <div class="executive-blueprint-foundations">
            <span><b>15</b><strong>책임이 분리된 에이전트</strong><small>판단·승인·실행을 한 주체가 소유하지 않음</small></span>
            <span><b>1</b><strong>공유 운영 온톨로지</strong><small>대상·관계·근거의 의미를 동일하게 해석</small></span>
            <span><b>T0-T2</b><strong>가장 낮은 충분한 판단</strong><small>결정론 우선, 모호성만 제한적으로 추론</small></span>
          </div>
        </div>
        <p class="executive-bottom-line">FDAI는 숙련된 운영자처럼 검증된 규칙과 지식을 먼저 적용하고, LLM은 정해진 방법으로 풀 수 없는 예외에만 사용합니다.</p>`,
    },
    {
      eyebrow: "03 / AGENT ORGANIZATION",
      title: "온톨로지가 의미를 정렬하고, 15개 에이전트가 책임을 나눕니다",
      lead: "온톨로지는 공통 의미를 제공하지만 판단하거나 실행하지 않습니다. 에이전트는 직접 호출이 아닌 타입이 지정된 이벤트로 협업합니다.",
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
                <span><b>Odin</b><small>목표 조정</small></span><span><b>Saga</b><small>감사</small></span>
                <span><b>Mimir</b><small>규칙 관리</small></span><span><b>Muninn</b><small>기억</small></span>
                <span><b>Norns</b><small>학습 후보</small></span>
              </div>
            </article>
            <article class="pipeline">
              <header><span>CONTROL PIPELINE</span><b>7</b></header>
              <div>
                <span><b>Huginn</b><small>이벤트 수집</small></span><span><b>Heimdall</b><small>관찰·예측</small></span>
                <span><b>Forseti</b><small>판단</small></span><span><b>Var</b><small>승인 전달</small></span>
                <span><b>Thor</b><small>실행</small></span><span><b>Vidar</b><small>복구</small></span>
                <span><b>Bragi</b><small>대화·설명</small></span>
              </div>
            </article>
            <article class="specialists">
              <header><span>DOMAIN SPECIALISTS</span><b>3</b></header>
              <div>
                <span><b>Njord</b><small>비용</small></span><span><b>Freyr</b><small>용량</small></span>
                <span><b>Loki</b><small>복원력 실험</small></span>
              </div>
            </article>
          </section>
        </div>
        <div class="executive-event-fabric"><span>AGENT</span><i></i><strong>타입 이벤트 · 스키마 검증 · 단일 소유자 · 재현 가능한 감사</strong><i></i><span>AGENT</span><b>직접 호출 없음</b></div>`,
    },
    {
      eyebrow: "04 / SOVEREIGN OPERATIONS",
      title: "FDAI는 고객의 데이터 주권 안에서 운영됩니다",
      lead: "데이터가 머무는 곳과 이동 경로, 접근 권한과 키, AI 모델의 사용 범위를 고객 정책으로 통제합니다.",
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
              <article><b>02</b><strong>이동 경로</strong><span>수집·처리·모델 호출은 승인된 사설 연결 안에서만 이뤄집니다.</span></article>
              <article><b>03</b><strong>접근 통제</strong><span>접근은 관리 ID와 최소 권한으로 나누고, 암호화 키는 고객이 관리합니다.</span></article>
              <article><b>04</b><strong>AI 사용</strong><span>AI는 승인된 리전과 모델 범위 안에서 필요한 경우에만 사용합니다.</span></article>
            </div>
            <div class="executive-sovereign-assurances" aria-label="소버린 운영의 핵심 보장">
              <span><b>DATA RESIDENCY</b><strong>데이터 위치를 고객이 결정</strong></span>
              <span><b>ACCESS CONTROL</b><strong>접근 권한과 키를 고객이 통제</strong></span>
              <span><b>BOUNDED AUTHORITY</b><strong>검증한 범위에만 운영 권한 부여</strong></span>
            </div>
          </section>
        </div>
        <p class="executive-bottom-line">위 구성은 FDAI가 지향하는 배포 형태입니다. 실제 운영은 선택한 리전과 규제 요건에 맞춰 데이터 이동·격리·복구가 검증된 범위에서만 시작합니다.</p>`,
    },
    {
      eyebrow: "05 / DETERMINISTIC SCALE",
      title: "수천 개로 늘어나는 운영 조건은 규칙으로 먼저 판단해야 합니다",
      lead: "FDAI는 정책과 규칙으로 반복 가능한 다수를 처리하고, 검증된 재사용과 제한된 추론은 필요한 경우에만 단계적으로 사용합니다.",
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
      title: "사람의 업무는 검증된 운영 지식이 되고, 예측은 별도로 검증됩니다",
      lead: "사례와 런북은 곧바로 권한이 되지 않습니다. 근거가 있는 후보로 기록되고 독립 검토와 관찰 모드를 통과해야 재사용됩니다.",
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
            <article><b>02</b><small>PROPOSE</small><strong>검증 전 지식 후보</strong><span>Norns가 패턴과 규칙 후보를 제안하지만 활성화하지 않음</span></article>
            <i></i>
            <article><b>03</b><small>REVIEW</small><strong>독립 검토와 승격</strong><span>Mimir와 사람이 품질·범위·복구 근거를 검토</span></article>
            <i></i>
            <article><b>04</b><small>REUSE</small><strong>규칙 또는 검증된 재사용</strong><span>이후 같은 사건을 T0 또는 T1에서 더 빠르게 처리</span></article>
          </section>
        </div>
        <aside class="executive-forecast-lane"><small>SEPARATE FORECAST CAPABILITY</small><strong>운영 이력 + 시간 + 의존 관계</strong><i></i><span>용량 고갈 · 인증서 만료 · 예산 추세 · 복구 위험을 제한된 기간 안에서 예측</span><b>불확실하면 보류 · 관찰 모드에서 정확도 검증 · 권한 자동 확대 없음</b></aside>`,
    },
    {
      eyebrow: "07 / ADOPTION DECISION TREE",
      title: "FDAI 도입은 네 가지 준비 조건을 충족한 범위에서 시작합니다",
      lead: "IaC·운영 데이터·표준 절차·안전 통제가 순서대로 준비되어야 합니다. 하나라도 충족하지 못하면 현행 운영을 유지하고 도입을 보류합니다.",
      layout: "executive-readiness",
      content: `
        <div class="executive-readiness-tree" role="img" aria-label="IaC, 신뢰 가능한 운영 데이터, 표준 절차와 완료 기준, 실행 안전 조건을 순서대로 확인하며 하나라도 미충족하면 현재 도입 불가, 모두 충족하면 관찰 모드 검토 가능으로 판단하는 의사결정 트리">
          <article><small>CONDITION 01</small><strong>대상 변경 경로가<br>IaC·GitOps로 관리되는가?</strong><span>검토 가능한 desired state</span><b>예 · 다음 조건</b><em>아니요 · 현재 도입 불가<br>IaC와 표준화부터</em></article>
          <i></i>
          <article><small>CONDITION 02</small><strong>상태·관계·관측 데이터가<br>신뢰 가능한가?</strong><span>범위·시간·출처·완전성</span><b>예 · 다음 조건</b><em>아니요 · 현재 도입 불가<br>관측성과 온톨로지부터</em></article>
          <i></i>
          <article><small>CONDITION 03</small><strong>반복 절차와 실제 효과의<br>완료 기준이 있는가?</strong><span>런북·담당자·측정 지표</span><b>예 · 다음 조건</b><em>아니요 · 현재 도입 불가<br>절차와 기준선부터</em></article>
          <i></i>
          <article><small>CONDITION 04</small><strong>권한·드라이런·복구·감사가<br>준비됐는가?</strong><span>일곱 안전 조건과 효과 검증</span><b>예 · 조건 충족</b><em>아니요 · 현재 도입 불가<br>안전 계약부터</em></article>
          <i></i>
          <div class="executive-ready-outcome"><small>ALL CONDITIONS MET</small><strong>관찰 모드 검토 가능</strong><span>아직 도입 승인·운영 권한 없음</span></div>
        </div>
        <div class="executive-readiness-no-go">
          <strong>하나라도 미충족이면 FDAI 도입 대상이 아닙니다</strong>
          <span>현행 운영을 유지하고 부족한 기반을 먼저 보완한 뒤, 조건이 충족되면 다시 평가합니다.</span>
          <b>CURRENT DECISION · NO-GO</b>
        </div>`,
    },
    {
      eyebrow: "08 / EVIDENCE-LED ADOPTION",
      title: "준비된 결정 유형 하나를 관찰 모드에서 시작합니다",
      lead: "새 규칙·할당·ActionType·워크플로 버전은 실제 변경 없이 판단 품질을 측정하고, 별도의 거버넌스 검토를 통과해야만 실행 대상이 됩니다.",
      layout: "executive-adoption",
      content: `
        <div class="executive-pilot-criteria">
          <span><b>01</b><strong>IaC 범위</strong><small>변경 경로가 검토·재현 가능</small></span>
          <span><b>02</b><strong>반복 사건</strong><small>현재 런북과 담당자가 존재</small></span>
          <span><b>03</b><strong>측정 효과</strong><small>실행 결과를 독립 관찰 가능</small></span>
          <span><b>04</b><strong>안전한 복구</strong><small>중지·롤백·영향 범위가 명확</small></span>
        </div>
        <div class="executive-adoption-path">
          <article><span>01</span><small>REGISTER</small><strong>범위·소유자·안전 계약</strong><p>결정 유형과 권한 상한을 고정합니다.</p></article><i></i>
          <article><span>02</span><small>OBSERVE</small><strong>변경 없이 판단</strong><p>사람의 실제 결정과 비교합니다.</p></article><i></i>
          <article><span>03</span><small>COMPARE</small><strong>품질·안전성 비교</strong><p>정확도와 검토 부하를 동일한 사건 집합으로 측정합니다.</p></article><i></i>
          <article><span>04</span><small>REVIEW</small><strong>독립 승격 결정</strong><p>준비되지 않으면 관찰을 계속합니다.</p></article><i></i>
          <article class="enforce"><span>05</span><small>BOUNDED ENFORCEMENT</small><strong>승인된 범위만 실행</strong><p>회귀하면 즉시 관찰 모드로 돌아갑니다.</p></article>
        </div>
        <div class="executive-measures"><span>판단 정확도</span><span>사람 검토율</span><span>정책 위반 0</span><span>롤백 준비도</span><span>독립 효과 검증</span></div>`,
    },
    {
      eyebrow: "09 / NEXT DECISION",
      title: "오늘 결정은 도입 승인이 아니라, 도입 가능성 검토를 시작하는 것입니다",
      lead: "한 가지 운영 결정 유형을 선택해 IaC, 데이터, 권한, 안전 계약과 현재 기준선을 확인한 뒤 진행 또는 보류를 판단합니다.",
      layout: "executive-decision",
      content: `
        <div class="executive-decision-layout">
          <div class="executive-decision-list">
            <div><span>01</span><strong>경영 스폰서와 책임자 지정</strong><p>가치, 위험, 데이터와 운영 결과의 최종 책임자를 정합니다.</p></div>
            <div><span>02</span><strong>결정 유형 1개 선택</strong><p>IaC로 관리되고 반복 가능하며 실제 효과를 측정할 수 있는 업무를 선택합니다.</p></div>
            <div><span>03</span><strong>Readiness & Baseline 워크숍</strong><p>도입 조건과 현재 판단 시간, 검토 부하, 품질 기준선을 함께 확인합니다.</p></div>
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
