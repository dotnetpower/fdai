const source = (...paths) =>
  `<small class="l100-source" title="${paths.join(" · ")}">근거: ${paths.join(" · ")}</small>`;

export const l100PitchDeckSlides = [
  {
    eyebrow: "MICROSOFT KOREA CSU · INTERNAL DEVELOPMENT",
    brandLogo: "assets/microsoft-logo.png",
    deckTitle: "FDAI L100 Pitch Deck",
    title: "운영 신호에서<br><em>검증된 결과까지</em>",
    lead: `FDAI는 조직의 운영 규칙과 현재 상태에 대한 정보를 바탕으로 반복적인 운영 업무를 수행합니다. 사람은 목표와 실행 권한을 정하고, FDAI는 별도의 관측을 통해 작업 결과를 검증합니다.
      <span class="l100-pitch-disclaimer">FDAI는 Microsoft의 공식 제품이나 Azure 서비스가 아닙니다. Microsoft Korea CSU에서 내부적으로 개발하고 검증 중인 솔루션입니다.</span>`,
    layout: "cover deck-l100-pitch",
    content: `<figure class="l100-pitch-photo">
      <img src="assets/l100-pitch-deck.jpeg" alt="분홍색과 파란색 데이터 입자가 여러 경로를 따라 흐르는 추상 장면">
      <figcaption><span>RESILIENCE</span><span>CHANGE SAFETY</span><span>COST GOVERNANCE</span></figcaption>
    </figure>`,
  },
  {
    eyebrow: "01 / PRODUCT IDENTITY",
    title: "FDAI는 운영 신호를 판단, 실행, 결과 검증으로 연결합니다",
    lead: "조직의 운영 규칙과 현재 상태를 바탕으로 반복 업무를 처리하는 자율 클라우드 운영 컨트롤 플레인입니다.",
    layout: "l100-pitch-body slide-l100-identity",
    content: `<section class="l100-visual l100-identity" aria-label="FDAI의 역할과 제품 경계">
      <article class="is"><span>WHAT FDAI DOES</span><strong>운영 신호를<br>검증 가능한 결과로 연결</strong>
        <div><b>현재 상태와 서비스 관계를 함께 파악</b><b>조직의 규칙과 정책을 우선 적용</b><b>승인된 작업을 실행한 뒤 실제 효과 확인</b></div>
      </article>
      <article class="is-not"><span>PRODUCT STATUS</span><strong>Microsoft Korea CSU<br>내부 개발 솔루션</strong>
        <div><b>Microsoft 공식 제품이나 Azure 서비스가 아님</b><b>Microsoft 제품 지원 및 SLA 대상이 아님</b><b>지원 방식과 업데이트 책임은 도입 전에 별도 합의</b></div>
      </article>
      <p>사람이 목표와 실행 권한을 정하고, FDAI는 허용된 범위에서만 작업합니다</p>
    </section>${source("docs/roadmap/architecture/fdai-constitution.md")}`,
  },
  {
    eyebrow: "02 / OPERATING CHALLENGE",
    title: "운영 대응은 흩어진 정보를 하나의 판단으로 연결하는 과정에서 지연됩니다",
    lead: "운영자는 로그와 메트릭, 최근 변경, 서비스 관계, 운영 정책과 승인 상태를 여러 도구에서 직접 찾아 함께 판단해야 합니다.",
    layout: "l100-pitch-body slide-l100-challenge",
    content: `<section class="l100-visual l100-challenge" aria-label="운영자가 수동으로 연결하는 다섯 단계">
      <article><b>01</b><strong>신호</strong><span>로그 · 메트릭 · 경보</span></article><i></i>
      <article><b>02</b><strong>영향</strong><span>관계 · SLO · 최근 배포</span></article><i></i>
      <article><b>03</b><strong>결정</strong><span>절차 · 위험 · 승인</span></article><i></i>
      <article><b>04</b><strong>실행</strong><span>변경 · 복구 · 롤백</span></article><i></i>
      <article><b>05</b><strong>검증</strong><span>실제 상태 · 재발 · 감사</span></article>
      <div class="human"><span>OPERATOR</span><strong>운영자가 단계 사이의 맥락을 매번 직접 연결합니다</strong></div>
    </section>${source("docs/roadmap/architecture/goals-and-metrics.md")}`,
  },
  {
    eyebrow: "03 / CONNECTED OPERATIONS",
    title: "FDAI는 기존 도구를 대체하지 않고, 도구 사이의 반복 업무를 연결합니다",
    lead: "각 시스템은 계속 자신의 데이터를 관리하며, FDAI는 접근이 허용된 정보만 사용합니다.",
    layout: "l100-pitch-body slide-l100-connected",
    content: `<section class="l100-visual l100-connected" aria-label="정보 원천에서 FDAI를 거쳐 운영 결과로 이어지는 흐름">
      <article class="sources"><small>AUTHORITATIVE SOURCES</small><strong>운영 정보</strong>
        <span>Azure 상태</span><span>로그와 메트릭</span><span>서비스 관계</span><span>규칙과 Git 변경</span>
      </article><i></i>
      <article class="control"><small>FDAI CONTROL PLANE</small><strong>판단과 작업 연결</strong>
        <span>대상 확인</span><span>규칙 평가</span><span>계획 수립</span><span>권한 확인</span>
      </article><i></i>
      <article class="outcomes"><small>GOVERNED OUTCOMES</small><strong>운영 결과</strong>
        <span>제안</span><span>사람 승인</span><span>허용된 실행</span><span>효과 검증과 복구</span>
      </article>
      <p>FDAI Console은 고객 리소스를 직접 변경하지 않습니다. 격리된 Executor만 승인된 작업을 수행합니다.</p>
    </section>${source(".github/instructions/app-shape.instructions.md", "docs/roadmap/deployment/deployment.md")}`,
  },
  {
    eyebrow: "04 / OPERATING DOMAINS",
    title: "복원력, 변경 안전, 비용 관리를 하나의 SRE 운영 모델로 연결합니다",
    lead: "세 영역은 동일한 서비스 목표, 운영 정보와 권한 경계를 공유합니다.",
    layout: "l100-pitch-body slide-l100-domains",
    content: `<section class="l100-visual l100-domains" aria-label="FDAI의 세 운영 영역">
      <div class="sre-core"><small>OPERATING MODEL</small><strong>SRE</strong><span>목표 · 위험 · 근거 · 효과</span></div>
      <article class="resilience"><b>01</b><strong>RESILIENCE</strong><span>감지 · 복구 · 회복 확인</span></article>
      <article class="change"><b>02</b><strong>CHANGE SAFETY</strong><span>영향 · 승인 · 롤백</span></article>
      <article class="cost"><b>03</b><strong>COST GOVERNANCE</strong><span>비용 · 용량 · 안전한 최적화</span></article>
      <p>FDAI의 목표는 자동화 자체가 아니라 안전성과 책임성을 지키면서 사람의 반복 개입을 줄이는 것입니다.</p>
    </section>${source("docs/roadmap/architecture/goals-and-metrics.md")}`,
  },
  {
    eyebrow: "05 / A TYPICAL OPERATING QUESTION",
    title: "하나의 운영 질문에 답하려면 여러 정보 원천과 실행 권한을 함께 확인해야 합니다",
    lead: "오류율 증가만으로는 최근 배포를 롤백해도 되는지 판단할 수 없습니다.",
    layout: "l100-pitch-body slide-l100-question",
    content: `<section class="l100-visual l100-question" aria-label="최근 배포 롤백 여부를 묻는 운영 질문">
      <div class="question-icon" aria-hidden="true">?</div>
      <blockquote>서비스 오류율이 급증했습니다.<br>최근 배포를 롤백해도 될까요?</blockquote>
      <div class="question-sources"><span>서비스 관계</span><span>변경 이력</span><span>운영 규칙</span><span>실행 권한</span></div>
      <p>대상, 관계, 시간, 근거, 권한과 예상 효과를 함께 확인해야 합니다.</p>
    </section>${source("docs/roadmap/decisioning/execution-model.md")}`,
  },
  {
    eyebrow: "06 / QUESTION DECOMPOSITION",
    title: "FDAI는 운영 질문을 대상, 관계, 시간, 근거, 권한과 예상 효과로 나눕니다",
    lead: "자연어는 의도를 전달하지만 실행 권한을 만들지 않습니다.",
    layout: "l100-pitch-body slide-l100-decomposition",
    content: `<section class="l100-visual l100-decomposition" aria-label="운영 질문을 여섯 판단 정보로 분해한 예시">
      <div class="callout target"><b>대상</b><span>어느 서비스와 배포 리비전인가?</span></div>
      <div class="callout relation"><b>관계</b><span>어떤 서비스가 영향을 받는가?</span></div>
      <div class="callout time"><b>시간</b><span>배포 전후 언제 시작되었는가?</span></div>
      <p class="annotated"><mark>서비스</mark> <mark>오류율이 급증</mark>했습니다.<br><mark>최근 배포</mark>를 <mark>롤백</mark>해도 될까요?</p>
      <div class="callout evidence"><b>근거</b><span>로그와 변경 기록은 최신인가?</span></div>
      <div class="callout authority"><b>권한</b><span>롤백이 등록되고 승인되었는가?</span></div>
      <div class="callout effect"><b>예상 효과</b><span>어떤 지표가 회복되어야 하는가?</span></div>
      <p class="example-note">예시이며 실제 고객 운영 결과가 아닙니다.</p>
    </section>${source("docs/roadmap/architecture/fdai-constitution.md", "docs/roadmap/decisioning/execution-model.md")}`,
  },
  {
    eyebrow: "07 / FDAI OPERATING ENGINE",
    title: "FDAI는 운영 질문을 근거 있는 판단과 검증된 작업으로 연결합니다",
    lead: "각 단계는 앞선 단계에서 확보한 근거와 권한을 확인하며, 조건을 충족하지 못하면 다음 단계로 진행하지 않습니다.",
    layout: "l100-pitch-body slide-l100-engine",
    content: `<section class="l100-visual l100-engine-v2" aria-label="운영 질문을 근거화하고 판단, 권한 확인, 실행, 독립 효과 검증으로 연결하는 FDAI 운영 엔진">
      <div class="engine-sources"><span>운영 온톨로지</span><span>현재 관측</span><span>Rule Catalog</span><span>검증된 사례</span></div>
      <div class="engine-grounding" aria-hidden="true"><i></i><b>GROUNDED CONTEXT</b><i></i></div>
      <div class="engine-flow">
        <article class="engine-input"><small>INPUT</small><strong>오류율 급증</strong><span>최근 배포 롤백?</span></article>
        <i class="engine-arrow" aria-hidden="true"></i>
        <div class="engine-core">
          <header><small>FDAI OPERATING ENGINE</small><strong>근거와 권한을 단계별로 고정</strong></header>
          <ol>
            <li><b>01</b><strong>근거화</strong><span>대상 · 관계 · 시간</span></li>
            <li><b>02</b><strong>판단</strong><span>규칙 · Tier · 위험</span></li>
            <li><b>03</b><strong>권한</strong><span>승인 · 범위 · 안전장치</span></li>
            <li><b>04</b><strong>실행</strong><span>잠금 · 멱등성 · 감사</span></li>
          </ol>
        </div>
        <i class="engine-arrow" aria-hidden="true"></i>
        <article class="engine-output"><small>GOVERNED OUTCOME</small><strong>승인된 롤백</strong><span>또는 보류 · 거부 · 사람 검토</span></article>
      </div>
      <div class="engine-verification"><strong>독립 효과 검증</strong><span>실행 전 기준 상태</span><i></i><span>별도 관측</span><i></i><span>오류율 회복 확인</span><i></i><b>완료 또는 롤백</b></div>
    </section>${source("docs/roadmap/architecture/fdai-constitution.md", "docs/roadmap/agents/agent-pantheon.md")}`,
  },
  {
    eyebrow: "08 / SEMANTIC OPERATING CONTEXT",
    title: "시멘틱 검색은 질문을 운영 온톨로지의 대상과 관계에 연결합니다",
    lead: "에이전트는 구조화된 대상과 관계를 사용해 필요한 운영 정보만 조회합니다.",
    layout: "l100-pitch-body slide-l100-semantic",
    content: `<section class="l100-visual l100-semantic-v2" aria-label="에이전트 질문을 시멘틱 검색으로 타입 매핑한 뒤 운영 온톨로지와 규칙, 사례에서 필요한 운영 맥락을 구성하는 흐름">
      <article class="semantic-agents"><small>ACCOUNTABLE</small><b>15</b><strong>AGENTS</strong><span>질문 · 관찰 · 판단 · 실행</span></article>
      <i class="semantic-arrow" aria-hidden="true"></i>
      <div class="semantic-mapper"><small>SEMANTIC SEARCH</small><strong>자연어를 타입으로 매핑</strong><div><span>Intent</span><span>Target</span><span>Relation</span><span>Time</span><span>Evidence</span><span>ActionType</span></div></div>
      <i class="semantic-arrow" aria-hidden="true"></i>
      <div class="semantic-knowledge">
        <div class="ontology-hub"><small>SHARED MEANING</small><strong>운영 온톨로지</strong><span>리소스 · 서비스 · 목표 · 의존성</span></div>
        <div class="knowledge-pair"><span>Rule Catalog</span><span>검증된 사례</span></div>
      </div>
      <i class="semantic-arrow" aria-hidden="true"></i>
      <div class="semantic-outputs">
        <article><small>CONTEXT</small><strong>현재 상태</strong><span>관계 · 시간 · 최신성</span></article>
        <article><small>DECISION</small><strong>허용 범위</strong><span>규칙 · 위험 · 승인</span></article>
        <article><small>ACTION</small><strong>작업 계약</strong><span>효과 · 복구 · 검증</span></article>
      </div>
      <p>시멘틱 검색은 질문의 의미를 구조화합니다. 온톨로지는 권한을 만들지 않습니다.</p>
    </section>${source("docs/roadmap/architecture/operating-ontology-platform.md", "docs/roadmap/agents/agent-pantheon.md")}`,
  },
  {
    eyebrow: "09 / DECISION EFFORT",
    title: "FDAI는 필요한 판단 수준에 따라 T0, T1, T2를 선택합니다",
    lead: "충분한 판단이 가능한 가장 낮은 Tier를 선택해 비용과 지연을 줄입니다.",
    layout: "l100-pitch-body slide-l100-tier-selector",
    content: `<section class="l100-visual l100-tier-selector" aria-label="T0, T1, T2 판단 수준 선택">
      <aside><strong>Decision<br>Reasoning<br>Effort</strong><p>결정론적 규칙에서 시작해 남은 모호성에만 AI 추론을 사용합니다.</p></aside>
      <div class="levels">
        <article class="t0"><b>T0</b><strong>규칙과 정책</strong><span>가장 낮은 비용 · 예측 가능한 결과 · 모델 없음</span></article>
        <article class="t1"><b>T1</b><strong>검증된 사례 재사용</strong><span>유사 상황 · 낮은 비용 · 근거와 결과 일치</span></article>
        <article class="t2"><b>T2</b><strong>근거 기반 추론</strong><span>새로운 상황 · 여러 모델 · 결정론적 검증</span></article>
      </div>
      <p>모델의 답변만으로 실행할 수 없으며 Tier별 비율은 현재 성과가 아닌 측정 목표입니다.</p>
    </section>${source("docs/roadmap/architecture/llm-strategy.md", "docs/roadmap/architecture/goals-and-metrics.md")}`,
  },
  {
    eyebrow: "10 / DETERMINISTIC OPERATION",
    title: "반복 가능한 상황은 LLM을 사용하지 않고 결정론적으로 처리합니다",
    lead: "같은 구조화 이벤트와 정책에는 같은 판단 결과를 적용합니다.",
    layout: "l100-pitch-body slide-l100-deterministic",
    content: `<section class="l100-visual l100-deterministic" aria-label="T0 결정론적 판단 흐름">
      <div class="intent"><small>STRUCTURED EVENT</small><strong>오류율 임계값 초과</strong><span>대상 · 리비전 · 시간 · 지표</span></div>
      <div class="definitions"><small>GOVERNED DEFINITIONS</small><article><b>Rule</b><span>판단 조건</span></article><article><b>Policy</b><span>위험과 승인</span></article><article><b>ActionType</b><span>작업과 안전장치</span></article></div>
      <i aria-hidden="true"></i>
      <div class="engine"><small>T0</small><strong>결정론적 엔진</strong><span>스키마 검증 · 정책 평가 · 예행 실행 확인</span></div>
      <i aria-hidden="true"></i>
      <div class="receipt"><small>TYPED OUTCOME</small><strong>동일 입력 = 동일 판단</strong><span>Verdict · resolved ceiling · 감사 증적</span></div>
      <p>정보가 부족하거나 조건이 맞지 않으면 추측하지 않고 보류, 거부 또는 다음 Tier로 전환합니다.</p>
    </section>${source("docs/roadmap/decisioning/execution-model.md", "docs/roadmap/architecture/llm-strategy.md")}`,
  },
  {
    eyebrow: "11 / AGENT KNOWLEDGE BASE",
    title: "에이전트는 하나의 지식베이스에서 정책, 온톨로지와 검증된 사례를 함께 조회합니다",
    lead: "지식베이스는 운영 도메인별 검색 범위, 정보 원천과 결과 합성 방식을 고정합니다.",
    layout: "l100-pitch-body slide-l100-knowledge",
    content: `<section class="l100-visual l100-knowledge" aria-label="에이전트 지식베이스의 구성">
      <aside><small>KNOWLEDGE DOMAIN</small><strong>하나의 설정으로 관리</strong><span>검색 범위</span><span>사용할 정보 원천</span><span>결과 합성 방식</span><span>근거와 인용</span></aside>
      <div class="kb"><header><strong>AGENT KNOWLEDGE BASE</strong></header>
        <div class="sources"><article><b>INDEXED</b><span>Rule Catalog</span><span>사례 이력</span><span>문서 인덱스</span></article><article><b>FEDERATED</b><span>운영 온톨로지</span><span>현재 관측</span><span>외부 권위 원천</span></article></div>
        <div class="indexes"><span>Vector index</span><span>Lexical index</span><span>Typed query</span></div>
        <div class="guard"><b>정책 · 출처 · 최신성 · 권한</b></div>
      </div>
      <div class="agent-output"><strong>AGENTS</strong><span>필요한 정보만 조회</span></div>
      <p>검색 결과는 판단 자료이며 승인이나 실행 권한을 부여하지 않습니다.</p>
    </section>${source("docs/roadmap/architecture/operating-ontology-platform.md", "docs/roadmap/rules-and-detection/prediction-learning-and-case-history.md")}`,
  },
  {
    eyebrow: "12 / OPERATING ONTOLOGY",
    title: "운영 온톨로지는 리소스, 서비스, 목표와 작업의 관계를 연결합니다",
    lead: "에이전트는 문자열을 단순 비교하지 않고, 타입으로 정의된 운영 관계를 조회합니다.",
    layout: "l100-pitch-body slide-l100-ontology-graph",
    content: `<section class="l100-visual l100-ontology-graph-v2" aria-label="서비스를 중심으로 변경, 리소스, 관측 근거, SLO, ActionType과 예상 효과를 연결한 운영 온톨로지 관계 그래프">
      <aside><small>SEMANTIC QUERY</small><strong>최근 배포가<br>오류 증가에 영향을 주었는가?</strong><span>대상과 시간 범위를 타입으로 고정</span></aside>
      <i class="ontology-query-arrow" aria-hidden="true"></i>
      <svg class="l100-ontology-svg" viewBox="0 0 920 350" role="img" aria-label="Change가 Service에 영향을 주고, Service는 Resource에 의존하며 SLO로 측정됩니다. Resource는 Evidence로 관찰되고, ActionType은 Resource를 대상으로 Expected Effect를 정의합니다.">
        <defs><marker id="ontology-arrow-ko" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>
        <g class="ontology-links" marker-end="url(#ontology-arrow-ko)">
          <path d="M 190 92 H 300"></path><path d="M 490 92 H 590"></path><path d="M 700 122 V 135 H 797 V 145"></path>
          <path d="M 300 115 C 250 160 230 258 190 258"></path><path d="M 395 230 C 450 175 540 150 590 105"></path><path d="M 490 258 H 590"></path>
        </g>
        <foreignObject class="ontology-edge-label" x="200" y="50" width="90" height="28"><div xmlns="http://www.w3.org/1999/xhtml">affects</div></foreignObject>
        <foreignObject class="ontology-edge-label" x="490" y="50" width="110" height="28"><div xmlns="http://www.w3.org/1999/xhtml">depends on</div></foreignObject>
        <foreignObject class="ontology-edge-label" x="735" y="92" width="135" height="28"><div xmlns="http://www.w3.org/1999/xhtml">observed by</div></foreignObject>
        <foreignObject class="ontology-edge-label" x="172" y="165" width="118" height="28"><div xmlns="http://www.w3.org/1999/xhtml">measured by</div></foreignObject>
        <foreignObject class="ontology-edge-label" x="440" y="138" width="90" height="28"><div xmlns="http://www.w3.org/1999/xhtml">targets</div></foreignObject>
        <foreignObject class="ontology-edge-label" x="500" y="218" width="80" height="28"><div xmlns="http://www.w3.org/1999/xhtml">expects</div></foreignObject>
        <foreignObject class="ontology-node change-node" x="40" y="62" width="150" height="60"><div xmlns="http://www.w3.org/1999/xhtml">Change</div></foreignObject>
        <foreignObject class="ontology-node service-node" x="300" y="62" width="190" height="60"><div xmlns="http://www.w3.org/1999/xhtml">Service</div></foreignObject>
        <foreignObject class="ontology-node resource-node" x="590" y="62" width="140" height="60"><div xmlns="http://www.w3.org/1999/xhtml">Resource</div></foreignObject>
        <foreignObject class="ontology-node evidence-node" x="700" y="145" width="194" height="55"><div xmlns="http://www.w3.org/1999/xhtml">Evidence</div></foreignObject>
        <foreignObject class="ontology-node slo-node" x="40" y="230" width="150" height="55"><div xmlns="http://www.w3.org/1999/xhtml">SLO</div></foreignObject>
        <foreignObject class="ontology-node action-node" x="300" y="230" width="190" height="55"><div xmlns="http://www.w3.org/1999/xhtml">ActionType</div></foreignObject>
        <foreignObject class="ontology-node effect-node" x="590" y="230" width="230" height="55"><div xmlns="http://www.w3.org/1999/xhtml">Expected Effect</div></foreignObject>
        <foreignObject class="ontology-legend observed" x="55" y="305" width="160" height="34"><div xmlns="http://www.w3.org/1999/xhtml"><i></i><span>관측된 상태</span></div></foreignObject>
        <foreignObject class="ontology-legend governed" x="215" y="305" width="160" height="34"><div xmlns="http://www.w3.org/1999/xhtml"><i></i><span>정책과 작업</span></div></foreignObject>
        <foreignObject class="ontology-legend desired" x="375" y="305" width="160" height="34"><div xmlns="http://www.w3.org/1999/xhtml"><i></i><span>목표와 효과</span></div></foreignObject>
      </svg>
      <p>관계의 방향, 기준 시점, 출처와 최신성을 함께 확인합니다. 온톨로지는 권한을 부여하지 않습니다.</p>
    </section>${source("docs/roadmap/architecture/operating-ontology-platform.md", "docs/roadmap/architecture/fdai-constitution.md")}`,
  },
  {
    eyebrow: "13 / AZURE DEPLOYMENT",
    title: "FDAI는 고객의 Azure 구독 내에 운영 컨트롤 플레인을 배포합니다",
    lead: "운영 데이터, 네트워크 경로, 서비스 신원과 감사 기록은 고객이 선택한 Azure 리전과 정책 경계 안에 배치합니다.",
    layout: "l100-pitch-body slide-l100-azure",
    content: `<section class="l100-visual l100-azure" aria-label="FDAI가 사용하는 기본 및 선택 Azure 리소스">
      <header><small>CUSTOMER AZURE SUBSCRIPTION</small><strong>고객이 소유하고 통제하는 Azure 경계</strong></header>
      <div class="layers">
        <article><small>COMPUTE</small><strong>Azure Kubernetes Service</strong><span>Core · Operator · Ingestion · Worker · Executor</span></article>
        <article><small>CONTROL DATA</small><strong>Event Hubs + PostgreSQL</strong><span>이벤트 · 상태 · 감사 · KPI · pgvector</span></article>
        <article><small>TRUST + OBSERVABILITY</small><strong>Key Vault + Managed Identity</strong><span>ACR · Log Analytics · Application Insights · VNet</span></article>
      </div>
      <div class="optional"><small>OPTIONAL</small><span>Static Web Apps + Entra ID</span><span>Azure OpenAI + Foundry</span><span>ADLS Gen2 + Document Intelligence</span><span>Blob Storage</span><span>Private Endpoints</span><span>Teams 또는 Bot</span></div>
      <p>위 항목은 FDAI가 사용하는 Azure 서비스입니다. FDAI 자체는 Microsoft의 공식 제품이나 Azure 서비스가 아닙니다.</p>
    </section>${source("docs/roadmap/deployment/deploy-and-onboard.md", "docs/roadmap/deployment/deployment.md")}`,
  },
  {
    eyebrow: "14 / ADOPTION DECISION",
    title: "첫 검증 워크플로와 운영 책임자를 정합니다",
    lead: "첫 단계에서는 도입이나 자율 실행을 승인하지 않습니다. 관찰 모드에서 검증할 문제와 종료 기준을 먼저 합의합니다.",
    layout: "l100-pitch-body slide-l100-adoption",
    content: `<section class="l100-visual l100-adoption" aria-label="FDAI 도입 준비와 첫 검증 경로">
      <ol><li><b>01</b><strong>범위</strong><span>워크플로 · 대상 · 제외 범위</span></li><li><b>02</b><strong>책임</strong><span>서비스 · 운영 · 승인 · 검토</span></li><li><b>03</b><strong>정보</strong><span>인벤토리 · 관측 · 변경 · 정책</span></li><li><b>04</b><strong>기준선</strong><span>측정 기간 · 성공 · 안전 지표</span></li><li><b>05</b><strong>Azure</strong><span>리전 · 할당량 · 네트워크 · 비용</span></li><li><b>06</b><strong>종료 기준</strong><span>관찰 결과 · 다음 검토 일정</span></li></ol>
      <div class="path"><span>범위 합의</span><i></i><span>Azure 사전 점검</span><i></i><span>배포</span><i></i><span>관찰 모드</span><i></i><span>기준선 비교</span><i></i><span>승격 검토</span></div>
      <aside><small>FIRST DELIVERABLE</small><strong>검증 범위 1장</strong><span>책임자 · 기준선 · 정보 원천 · 제외 범위 · 종료 기준</span></aside>
      <p>FDAI는 Microsoft Korea CSU 내부 개발 솔루션이며 공식 Microsoft 제품이나 Azure 서비스가 아닙니다.</p>
    </section>${source("docs/roadmap/deployment/deploy-and-onboard.md", "docs/roadmap/architecture/goals-and-metrics.md")}`,
  },
];
