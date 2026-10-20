import { pitchSlide, resourceGraph } from "./l100-pitch-kit.js";

const slide = data => pitchSlide("ko", data);

export const l100PitchDeckSlides = [
  slide({
    id: "cover", chapter: "INTRODUCTION", kind: "cover", cover: true,
    title: "운영 신호에서<br><em>검증된 결과까지</em>",
    lead: "조직의 규칙과 현재 상태를 연결해 반복 업무를 줄입니다.<br>사람이 목표와 권한을 정하고, FDAI는 작업의 실제 효과를 확인합니다.",
    visual: `<div class="lp-cover-composition">
      <div class="lp-cover-message"><span class="lp-kicker">FDAI / 자율 클라우드 운영</span><strong>정보를 모으는 데서<br>안전한 판단과 실행으로</strong><p>복원력 · 변경 안전 · 비용 관리</p></div>
      <figure class="lp-cover-photo"><img src="assets/l100-pitch-deck.jpeg" alt=""><figcaption>규칙 우선 · 근거 기반 · 효과 확인</figcaption></figure>
    </div>`,
    takeaway: "Microsoft Korea CSU에서 내부 개발·검증 중인 솔루션입니다. Microsoft 공식 제품이나 Azure 서비스가 아닙니다.",
    sources: ["constitution"],
  }),
  slide({
    id: "challenge", chapter: "01 / 운영자의 질문", kind: "timeline", example: true,
    title: "운영자는 흩어진 정보를 모으고 대조해야 합니다",
    lead: "오류가 늘면 로그, 최근 변경, 서비스 관계와 승인 상태를 여러 도구에서 확인합니다.",
    visual: `<blockquote class="lp-question">"API 오류가 늘었습니다. 최근 배포 때문인지 DB 문제인지 확인하고,<br>롤백이 가능한 조건을 알려 주세요."</blockquote>
      <ol class="lp-event-line"><li><b>신호</b><span>오류 로그와 메트릭</span></li><li><b>맥락</b><span>최근 변경과 의존관계</span></li><li><b>결정</b><span>영향과 실행 조건</span></li><li><b>확인</b><span>작업 후 실제 상태</span></li></ol>`,
    takeaway: "FDAI는 기존 도구를 대체하기보다, 도구 사이에서 반복하는 확인과 판단을 연결합니다.",
    sources: ["constitution", "execution"],
  }),
  slide({
    id: "domains", chapter: "02 / FDAI의 역할", kind: "operating-map",
    title: "복원력·변경 안전·비용 관리를 함께 봅니다",
    lead: "FDAI는 SRE(서비스 신뢰성 엔지니어링)를 운영 모델로 삼는 컨트롤 플레인, 즉 운영 판단·실행을 조정하는 기반입니다.",
    visual: `<dl class="lp-domain-list">
      <div><dt><span>01 / RESILIENCE</span><strong>복원력</strong></dt><dd>문제를 감지하고, 복구 후 서비스가 회복했는지 확인합니다.</dd></div>
      <div><dt><span>02 / CHANGE SAFETY</span><strong>변경 안전</strong></dt><dd>변경의 영향, 승인 조건과 복구 경로를 함께 검토합니다.</dd></div>
      <div><dt><span>03 / COST GOVERNANCE</span><strong>비용 관리</strong></dt><dd>비용·용량을 검토하되, 서비스 목표를 해치는 최적화는 피합니다.</dd></div>
    </dl><p class="lp-context-note">기존 관측·Git·클라우드 도구와 연결합니다. 도입 전 지원 방식과 업데이트 책임을 별도로 합의합니다.</p>`,
    takeaway: "목표는 자동화 자체가 아니라, 안전성과 책임성을 지키면서 사람의 반복 개입을 줄이는 것입니다.",
    sources: ["constitution", "deployment"],
  }),
  slide({
    id: "knowledge", chapter: "03 / 서로 다른 정보 원천", kind: "evidence-layers",
    title: "문서의 설계와 현재 관측 사실은 다릅니다",
    lead: "FDAI는 자료의 출처와 시점을 보존하고, 각 자료가 어떤 판단을 뒷받침하는지 구분합니다.",
    visual: `<div class="lp-evidence-layers">
      <section><span class="lp-kicker">설계 의도</span><h3>문서·매뉴얼</h3><p>객체와 관계에 대한 주장을 추출합니다.<br>변경 제안은 검토 대상이지 현재 사실이 아닙니다.</p></section>
      <section><span class="lp-kicker">현재 사실</span><h3>인벤토리·관측</h3><p>리소스와 상태를 조회하고 관계를 검증합니다.<br>출처·시간·누락 여부를 함께 확인합니다.</p></section>
      <section><span class="lp-kicker">참고할 경험</span><h3>조사·사례 이력</h3><p>이전 가설과 결과를 참고합니다.<br>이번 대상과 상황에도 적용되는지 다시 확인합니다.</p></section>
    </div>`,
    takeaway: "문서 제안이나 모델이 생성한 설명을 실제로 관측한 사실처럼 사용하지 않습니다.",
    sources: ["documents", "graph"],
  }),
  slide({
    id: "ontology", chapter: "04 / 같은 의미로 연결하기", kind: "relationship", example: true,
    title: "운영 온톨로지는 대상과 관계의 공통 기준입니다",
    lead: "무엇을 다루는지, 무엇에 의존하는지 정의합니다. 객체의 정의와 실제 개별 리소스는 구분합니다.",
    visual: resourceGraph("ko"),
    takeaway: "의존관계는 영향이 전파될 수 있는 경로입니다. 관계가 있다는 사실만으로 장애 원인을 확정하지 않습니다.",
    sources: ["ontology", "causality"],
  }),
  slide({
    id: "target", chapter: "05 / 질문에서 정확한 대상으로", kind: "verified-flow", example: true,
    title: "비슷한 이름만으로 대상을 정하지 않습니다",
    lead: "질문의 의미를 해석한 뒤, 현재 권한으로 읽을 수 있는 실제 객체에서 정확한 식별자를 확인합니다.",
    visual: `<div class="lp-flow">
      <section data-lp-node="intent"><span class="lp-kicker">질문 해석</span><h3>"API 오류 조사"</h3><p>목표 · 대상 · 시간 · 제약</p></section>
      <i class="lp-link" data-lp-from="intent" data-lp-to="plan" aria-hidden="true"></i>
      <section data-lp-node="plan"><span class="lp-kicker">계획 검증</span><h3>허용된 조회만</h3><p>타입 · 인자 · 역할 · 범위</p></section>
      <i class="lp-link" data-lp-from="plan" data-lp-to="object" aria-hidden="true"></i>
      <section data-lp-node="object"><span class="lp-kicker">현재 객체 확인</span><h3>정확한 대상</h3><p>식별자 · 출처 · 최신성</p></section>
    </div><p class="lp-context-note">이름이 같거나 범위가 불명확하면 추가 확인을 요청합니다. 후보 순위는 사실 확인이나 실행 승인이 아닙니다.</p>`,
    takeaway: "자연어는 의도를 전달합니다. 접근 범위와 실행 권한을 넓히지는 않습니다.",
    sources: ["ontology", "constitution"],
  }),
  slide({
    id: "time", chapter: "06 / 같은 시간 구간에서 비교", kind: "incident-timeline", example: true,
    title: "배포 전후의 변화와 영향을 함께 확인합니다",
    lead: "같은 대상과 시간 구간의 기록을 대조합니다. 과거 관계를 확인할 수 없다면 현재 관계로 대신 입증하지 않습니다.",
    visual: `<div class="lp-time-board"><div class="lp-time-head"><span>확인할 기록</span><span>배포 전</span><span>배포 시점</span><span>오류 증가 구간</span></div>
      <div><strong>변경 이력</strong><span>이전 리비전</span><span class="lp-focus">새 리비전 배포</span><span>대상·설정 대조</span></div>
      <div><strong>API 관측</strong><span>기준 상태</span><span>요청 기록</span><span class="lp-focus">오류와 지연 확인</span></div>
      <div><strong>DB 관측</strong><span>기준 상태</span><span>지연 시작점 조사</span><span>지속 여부 확인</span></div>
    </div>`,
    takeaway: "시간이 가깝다는 이유만으로 배포를 원인으로 단정하지 않습니다. 누락된 정보는 누락으로 남깁니다.",
    sources: ["graph", "causality"],
  }),
  slide({
    id: "hypotheses", chapter: "07 / 원인 가설 비교", kind: "hypothesis-board", example: true,
    title: "원인을 단정하지 않고 가설을 비교합니다",
    lead: "각 가설을 지지하거나 반박할 정보를 찾고, 두 가설을 구별할 다음 관측을 정합니다.",
    visual: `<table class="lp-table lp-hypotheses"><thead><tr><th>원인 후보</th><th>확인할 정보</th><th>아직 모르는 점</th></tr></thead><tbody>
      <tr><th>배포로 인한 회귀</th><td>변경 대상과 오류 시작 시점</td><td>변경이 증상을 설명하는가?</td></tr>
      <tr><th>DB 지연</th><td>DB 지연과 API 요청의 시간 관계</td><td>오류보다 먼저 시작되었는가?</td></tr>
      <tr><th>공통 의존성 문제</th><td>같은 의존 대상을 쓰는 서비스</td><td>다른 서비스도 영향을 받는가?</td></tr>
    </tbody></table><div class="lp-answer"><span class="lp-kicker">답변 예시</span><p>"현재 정보만으로 원인을 확정하기 어렵습니다.<br>배포 대상과 DB 지연 시작점을 먼저 대조하겠습니다."</p></div>`,
    takeaway: "관련 사례를 찾는 것과 이번 장애의 원인을 확인하는 것은 다릅니다.",
    sources: ["causality"],
  }),
  slide({
    id: "tiers", chapter: "08 / 필요한 만큼 판단", kind: "tier-comparison",
    title: "규칙을 먼저 적용하고 필요한 만큼 추론합니다",
    lead: "T0·T1·T2는 판단에 드는 수준을 구분합니다. 어느 수준에서도 모델의 제안만으로 실행할 수 없습니다.",
    visual: `<dl class="lp-tier-list">
      <div><dt>T0</dt><dd><h3>규칙과 정책</h3><p>모델 없이 판단합니다. 같은 검증 입력·정책 버전·맥락에는 같은 판정을 적용합니다.</p></dd></div>
      <div><dt>T1</dt><dd><h3>검증된 재사용과 경량 판단</h3><p>사례·패턴과 경량 모델을 활용합니다. 제안된 대상과 의도는 결정론적으로 검증합니다.</p></dd></div>
      <div><dt>T2</dt><dd><h3>남은 모호성에 대한 심층 추론</h3><p>근거 기반 추론에 서로 다른 모델의 교차 확인과 별도 검증을 적용합니다.</p></dd></div>
    </dl>`,
    takeaway: "판단에 충분한 최소 수준을 선택합니다. 근거가 부족하면 추가 확인하거나 판단을 보류합니다.",
    sources: ["llm", "execution"],
  }),
  slide({
    id: "agents", chapter: "09 / 나누어진 책임", kind: "ownership",
    title: "에이전트는 역할을 나누고 이벤트로 협업합니다",
    lead: "고정된 15개 에이전트가 각자의 역할을 맡습니다. 아래는 역할을 이해하기 위한 요약이며 전체 조직도는 아닙니다.",
    visual: `<div class="lp-ownership"><div class="lp-event-bus"><span class="lp-kicker">공통 협업 경로</span><h3>스키마로 검증한 이벤트</h3><p>책임 주체 · 대상 · 근거 · 시점</p></div>
      <dl><div><dt>관측·지식</dt><dd>신호와 관계를 확인하고 검증된 맥락을 제공합니다.</dd></div><div><dt>판단·설명</dt><dd>규칙과 위험을 검토하고 판단 이유를 전달합니다.</dd></div><div><dt>승인 요청·실행</dt><dd>유효한 사람 승인을 확인하며, 실행기는 별도 신원을 사용합니다.</dd></div><div><dt>검증·복구·감사</dt><dd>효과를 별도로 관측하고 결과와 복구 이력을 남깁니다.</dd></div></dl>
    </div>`,
    takeaway: "에이전트가 자신의 제안을 스스로 승인하지 않습니다. 지식 공유가 실행 권한 공유를 뜻하지도 않습니다.",
    sources: ["agents", "constitution"],
  }),
  slide({
    id: "authority", chapter: "10 / 실행 전에 확인", kind: "safeguards",
    title: "실행은 승인과 안전 조건을 충족한 뒤에만 가능합니다",
    lead: "문제의 원인을 확인하는 것과 작업을 허용하는 것은 별개입니다. 등록된 작업마다 필요한 승인과 일곱 안전장치를 확인합니다.",
    visual: `<div class="lp-authority-band"><strong>제안</strong><span>실행 권한 아님</span><strong>유효한 승인</strong><span>안전 조건 재확인</span><strong>격리된 실행기</strong></div>
      <ol class="lp-safeguards"><li>기계가 평가할 중단 조건</li><li>검증된 롤백·복구 경로</li><li>영향 범위와 상한</li><li>성공한 모의 실행</li><li>정확한 대상의 잠금</li><li>중복 실행 방지 키</li><li>실행 전·후 감사 기록</li></ol>`,
    takeaway: "조건을 충족하지 못하면 실행하지 않습니다. 필요한 정보와 준비 사항은 계속 진단할 수 있습니다.",
    sources: ["constitution", "execution"],
  }),
  slide({
    id: "effect", chapter: "11 / 작업의 실제 효과", kind: "effect-verification", example: true,
    title: "실행 응답이 아니라 실제 회복을 확인합니다",
    lead: "롤백 요청이 수락되었다는 응답만으로 완료하지 않습니다. 실행 채널과 독립된 관측으로 기대 효과를 대조합니다.",
    visual: `<div class="lp-effect-stages"><section><span class="lp-kicker">작업 전</span><h3>확인할 기준</h3><p>정확한 대상·리비전<br>오류 상태와 기대 회복 조건</p></section><section><span class="lp-kicker">승인된 작업</span><h3>롤백 수행</h3><p>실행 증적과 감사 기록<br>수락 응답은 효과의 증거가 아님</p></section><section><span class="lp-kicker">별도 관측</span><h3>실제 상태 비교</h3><p>관측 구간·출처·완전성<br>기대한 회복 여부 확인</p></section></div>
      <div class="lp-outcomes"><p><b>회복 확인</b>기대한 효과가 확인되면 완료합니다.</p><p><b>회복 미확인</b>성공으로 표시하지 않습니다. 등록된 복구 절차에 따르거나 사람 검토를 요청합니다.</p></div>`,
    takeaway: "효과가 확인되어도 원인이 자동으로 확정되는 것은 아닙니다. 원인 가설의 검증은 별도로 남깁니다.",
    sources: ["constitution", "causality"],
  }),
  slide({
    id: "status", chapter: "12 / 구현과 검증 상태", kind: "status-comparison",
    title: "구현·활성화·실환경 검증은 각각 확인합니다",
    lead: "코드가 있다는 사실만으로 기본 사용 중이거나 운영 품질까지 검증되었다고 말하지 않습니다. 확인 기준: 2026-10-20.",
    visual: `<table class="lp-table lp-status"><thead><tr><th>기능</th><th>확인한 상태</th><th>도입 전 확인</th></tr></thead><tbody>
      <tr><th>타입 기반 조회·계획 검증</th><td>구현 기반 확인</td><td>실제 데이터·역할·출처 연결</td></tr>
      <tr><th>벡터 유사도 후보 검색</th><td>표준 답변 경로에서 비활성</td><td>별도 활성화·검증 필요</td></tr>
      <tr><th>문서에서 추출한 관계</th><td>검토할 변경 제안</td><td>활성 그래프 반영 경로 확인</td></tr>
      <tr><th>인과 분석·실행 효과</th><td>이 자료로 실환경 검증을 주장하지 않음</td><td>정확한 배포 범위에서 검증</td></tr>
    </tbody></table><p class="lp-context-note">자연어의 의미 해석과 벡터 후보 검색은 다릅니다. 이 자료는 실환경 동작 검증 결과가 아닙니다.</p>`,
    takeaway: "사용할 기능별로 근거와 준비 상태를 확인합니다. 설정이 켜졌다고 실행 권한이 생기지는 않습니다.",
    sources: ["ontology", "indexRuntime", "documents", "causality"],
  }),
  slide({
    id: "azure", chapter: "13 / Azure 배포 경계", kind: "deployment",
    title: "Azure 구성과 데이터 처리 경계를 확인합니다",
    lead: "고객의 Azure 구독에 배포하되, 사용하는 서비스와 외부 연계마다 리전·네트워크·인증 조건을 확인합니다.",
    visual: `<div class="lp-azure-boundary"><span class="lp-kicker">고객이 선택한 Azure 구독 / 기본 구성</span>
      <dl><div><dt>실행 서비스</dt><dd>Azure Kubernetes Service<br>Core · Operator · Ingestion · Worker · Executor</dd></div><div><dt>이벤트·상태</dt><dd>Event Hubs · PostgreSQL<br>이벤트, 서비스별 상태와 감사 기록</dd></div><div><dt>인증·관측</dt><dd>Key Vault · Managed Identity<br>Log Analytics · Application Insights</dd></div></dl>
    </div><p class="lp-context-note"><b>선택 구성</b> Console, 모델, 문서 처리, 비공개 연결과 Teams는 사용 범위에 맞게 구성합니다. Console을 사용할 때는 Entra ID 인증 조건을 확인합니다.</p>`,
    takeaway: "구독 내부 배포가 모든 연계의 데이터 상주를 보장하지는 않습니다. 모델·문서·Git 등 서비스별 처리 위치를 검토합니다.",
    sources: ["deployment", "constitution"],
  }),
  slide({
    id: "adoption", chapter: "14 / 첫 검증의 결정", kind: "adoption-worksheet", example: true,
    title: "첫 관찰 모드 검증의 범위와 책임자를 정합니다",
    lead: "실제 변경을 적용하지 않는 관찰 모드에서 시작합니다. 종료 기준을 합의하되, 관찰 종료를 실행 허용으로 간주하지 않습니다.",
    visual: `<div class="lp-worksheet"><div class="lp-sheet-heading"><span class="lp-kicker">첫 검증 범위 / 작성 예시</span><strong>API 오류 조사와 판단 근거 확인</strong></div>
      <dl><div><dt>대상·제외 범위</dt><dd>담당자가 서비스·시간 구간·제외 대상을 정합니다.</dd></div><div><dt>운영·승인 책임</dt><dd>운영 책임자와 승인·검토 담당자를 지정합니다.</dd></div><div><dt>기준선·관찰 기간</dt><dd>비교할 현재 절차와 측정 기간을 합의합니다.</dd></div><div><dt>안전·종료 기준</dt><dd>변경 미적용, 근거·보류 이유 검토, 다음 결정 일정을 기록합니다.</dd></div></dl>
    </div>`,
    takeaway: "다음 결정은 관찰 지속, 정보 보완, 범위 조정 또는 실행 허용 검토입니다. 승격과 승인은 별도 절차입니다.",
    sources: ["constitution", "deployment"],
  }),
];
