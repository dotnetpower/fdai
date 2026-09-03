const sources = {
  constitution: "docs/roadmap/architecture/fdai-constitution.md",
  metrics: "docs/roadmap/architecture/goals-and-metrics.md",
  observability: "docs/roadmap/rules-and-detection/observability-and-detection.md",
  operator: "docs/roadmap/operations/operator-initiated-sre-and-arb.md",
  recovery: "docs/roadmap/decisioning/recovery-and-chaos-enforcement.md",
};

function sourceList(...items) {
  return items.map((item) => sources[item]);
}

function slide({
  index,
  state,
  chapter,
  title,
  lead,
  layout,
  content,
  source,
  sourceLabel,
  statusLabel,
}) {
  const number = String(index).padStart(2, "0");
  return {
    eyebrow: `${number} / ${statusLabel(state)}`,
    title,
    lead,
    layout: `briefing-${layout} deck-sre-incident-response`,
    content: `
      <div class="briefing-status-row">
        <span class="manual-status" data-state="${state}" aria-label="설계 상태: ${statusLabel(state)}">${statusLabel(state)}</span>
        <span>${chapter} · ${number} / 10</span>
      </div>
      ${content}
      ${sourceLabel(source)}`,
  };
}

export function buildSreIncidentResponseDeck({ sourceLabel, statusLabel }) {
  return [
    {
      eyebrow: "FDAI / SRE INCIDENT RESPONSE & MTTR",
      title: "SRE 운영을 알림 처리에서 검증된 서비스 회복으로 전환할 수 있습니다",
      lead: "FDAI는 운영 신호, 조직의 표준 대응 절차, AI 기반 분석, 통제된 복구를 하나의 인시던트 운영 체계로 연결합니다.",
      layout: "briefing-cover deck-sre-incident-response",
      content: `
        <figure class="briefing-cover-art">
          <img src="assets/sre-incident-response.png" alt="">
          <figcaption>SRE RESPONSE</figcaption>
        </figure>
        <ol class="briefing-cover-index" aria-label="SRE Incident Response & MTTR의 주요 구성">
          <li><small>01</small><span>감지와 영향 판단</span></li>
          <li><small>02</small><span>통제된 복구와 장애 조치</span></li>
          <li><small>03</small><span>MTTR와 운영 성과</span></li>
        </ol>
        <div class="sre-cover-promise" aria-label="설명서가 제공하는 운영 가치">
          <span>INCIDENT TO OUTCOME</span>
          <strong>신호를 줄이고</strong><i></i><strong>복구를 통제하고</strong><i></i><strong>성과를 증명합니다</strong>
        </div>
        ${sourceLabel(sourceList("observability", "operator", "metrics"))}`,
    },
    slide({
      index: 2,
      state: "CURRENT",
      chapter: "감지와 영향 판단",
      title: "수많은 운영 신호를 하나의 대응 가능한 인시던트로 정리할 수 있습니다",
      lead: "FDAI는 정상 관측을 보존하면서 중복 이벤트를 줄이고, 같은 장애 구간의 신호만 근거와 함께 연결합니다.",
      layout: "sre-signal",
      source: sourceList("observability", "operator"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-signal-board" aria-label="운영 신호 상관관계 예시">
          <header><span>예시 대응 구간 · 15분</span><strong>checkout-api 지연 증가</strong><b>P1 후보</b></header>
          <div class="sre-signal-kpis">
            <article><small>원시 신호</small><strong>1,284</strong><span>메트릭 · 로그 · 변경</span></article>
            <article><small>중복 제거</small><strong>92%</strong><span>같은 증상과 대상</span></article>
            <article><small>상관 에피소드</small><strong>7</strong><span>시간과 의존성 기준</span></article>
            <article><small>인시던트 후보</small><strong>1</strong><span>근거 키 18개</span></article>
          </div>
          <div class="sre-signal-detail">
            <figure>
              <figcaption>신호 압축 흐름</figcaption>
              <div><span style="--signal-width:100%"><b>텔레메트리</b><i>1,284</i></span></div>
              <div><span style="--signal-width:68%"><b>정규화 이벤트</b><i>103</i></span></div>
              <div><span style="--signal-width:42%"><b>상관 에피소드</b><i>7</i></span></div>
              <div><span style="--signal-width:22%"><b>대응 후보</b><i>1</i></span></div>
            </figure>
            <aside>
              <small>대응 근거</small>
              <strong>SLO 소진 속도와 배포 직후 오류가 같은 서비스 그래프에서 만났습니다.</strong>
              <dl><div><dt>대상</dt><dd>checkout-api</dd></div><div><dt>변경</dt><dd>revision 1842</dd></div><div><dt>근거 최신성</dt><dd>47초</dd></div></dl>
            </aside>
          </div>
        </section>`,
    }),
    slide({
      index: 3,
      state: "CURRENT",
      chapter: "감지와 영향 판단",
      title: "서비스 그래프로 고객 영향과 대응 우선순위를 확인할 수 있습니다",
      lead: "상관관계를 원인으로 단정하지 않고 서비스, 리소스, 최근 변경, SLO를 같은 시점의 근거로 비교합니다.",
      layout: "sre-impact",
      source: sourceList("constitution", "operator"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-impact-view" aria-label="서비스 영향 분석 예시">
          <div class="sre-impact-legend"><span class="critical">영향 확인</span><span class="warning">위험 증가</span><span>정상</span><b>예시 토폴로지</b></div>
          <figure class="sre-service-map">
            <article class="node customer"><small>고객 여정</small><strong>결제</strong><span>성공률 -8.4%p</span></article>
            <i class="map-link customer-link" aria-hidden="true"></i>
            <article class="node service"><small>서비스</small><strong>checkout-api</strong><span>SLO burn 6.2x</span></article>
            <i class="map-link service-link" aria-hidden="true"></i>
            <article class="node dependency"><small>의존 서비스</small><strong>payment-api</strong><span>p95 1.8s</span></article>
            <i class="map-link data-link" aria-hidden="true"></i>
            <article class="node change"><small>최근 변경</small><strong>revision 1842</strong><span>12분 전 배포</span></article>
            <article class="node healthy"><small>비교 대상</small><strong>catalog-api</strong><span>정상 범위</span></article>
            <article class="node data"><small>데이터 계층</small><strong>orders-db</strong><span>connection +41%</span></article>
            <i class="map-link vertical-link" aria-hidden="true"></i>
          </figure>
          <aside class="sre-impact-summary">
            <header><small>영향 요약</small><strong>운영자가 바로 판단할 수 있는 범위</strong></header>
            <div><span>영향 고객 여정</span><b>결제 1개</b></div>
            <div><span>직접 영향 서비스</span><b>2개</b></div>
            <div><span>변경 후보</span><b>1개</b></div>
            <div><span>확정하지 않은 것</span><b>근본 원인</b></div>
          </aside>
        </section>`,
    }),
    slide({
      index: 4,
      state: "DECISION",
      chapter: "감지와 영향 판단",
      title: "규칙, 검증된 사례, 예측, LLM 분석을 함께 활용할 수 있습니다",
      lead: "조직의 표준 대응 절차를 기본 경로로 삼고, 새로운 모호성에는 근거가 연결된 AI 분석을 추가합니다.",
      layout: "sre-decision",
      source: sourceList("constitution", "observability"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-decision-system" aria-label="AIOps 판단 체계">
          <div class="sre-decision-inputs">
            <article><small>DETECT</small><strong>통계와 예측</strong><span>이상 징후 · 용량 · SLO 소진</span></article>
            <article><small>T0</small><strong>운영 규칙</strong><span>임계값 · 정책 · 표준 절차</span></article>
            <article><small>T1</small><strong>검증된 재사용</strong><span>같은 증상 · 같은 범위 · 같은 결과</span></article>
            <article><small>T2</small><strong>근거 기반 추론</strong><span>새로운 관계와 잔여 모호성</span></article>
          </div>
          <div class="sre-decision-core">
            <small>EXAMPLE DECISION CASE</small>
            <strong>revision 1842 롤백 검토</strong>
            <div><span>근거 완전성</span><b>충족</b></div>
            <div><span>영향 범위</span><b>2 services</b></div>
            <div><span>현재 권한</span><b>사람 승인</b></div>
            <div><span>복구 계획</span><b>검증됨</b></div>
          </div>
          <div class="sre-decision-output">
            <article class="selected"><small>RECOMMEND</small><strong>배포 롤백</strong><span>이전 정상 리비전과 검증 경로 일치</span></article>
            <article><small>ALTERNATIVE</small><strong>트래픽 제한</strong><span>롤백 실패 시 영향 축소</span></article>
            <article><small>HOLD</small><strong>DB 변경</strong><span>인과 근거 부족으로 실행 제외</span></article>
          </div>
          <footer><span>AI가 후보를 확장합니다.</span><b>정책과 권한이 실행 가능성을 결정합니다.</b><span>운영자가 근거와 선택지를 받습니다.</span></footer>
        </section>`,
    }),
    slide({
      index: 5,
      state: "DECISION",
      chapter: "통제된 복구와 장애 조치",
      title: "복구 옵션을 예상 효과, 위험, RTO, 되돌리기 가능성으로 비교할 수 있습니다",
      lead: "FDAI는 빠른 작업이 아니라 현재 장애와 복구 목표에 가장 적합한 검증된 경로를 제안합니다.",
      layout: "sre-options",
      source: sourceList("recovery", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-option-board" aria-label="복구 옵션 비교 예시">
          <header><span>예시 인시던트 · checkout-api</span><strong>목표: 15분 안에 결제 SLO 회복</strong><b>운영자 결정 대기</b></header>
          <div class="sre-option-grid">
            <article class="recommended">
              <small>권장</small><strong>배포 롤백</strong><p>revision 1841로 복귀</p>
              <dl><div><dt>예상 회복</dt><dd>6분</dd></div><div><dt>영향 범위</dt><dd>2 services</dd></div><div><dt>복구 검증</dt><dd>최근 성공</dd></div></dl>
            </article>
            <article>
              <small>영향 제한</small><strong>트래픽 제한</strong><p>결제 재시도율 축소</p>
              <dl><div><dt>예상 회복</dt><dd>4분</dd></div><div><dt>영향 범위</dt><dd>고객 지연</dd></div><div><dt>최종 해결</dt><dd>아님</dd></div></dl>
            </article>
            <article>
              <small>장애 조치</small><strong>보조 계통 전환</strong><p>검증된 대체 리전 사용</p>
              <dl><div><dt>예상 회복</dt><dd>12분</dd></div><div><dt>RPO</dt><dd>5분</dd></div><div><dt>필수 승인</dt><dd>2명</dd></div></dl>
            </article>
            <article class="blocked">
              <small>실행 제외</small><strong>DB 직접 수정</strong><p>검증된 작업 없음</p>
              <dl><div><dt>근거</dt><dd>불충분</dd></div><div><dt>되돌리기</dt><dd>미검증</dd></div><div><dt>결과</dt><dd>실행 제외</dd></div></dl>
            </article>
          </div>
          <footer><span>선택 이유</span><strong>배포 직후 증상 + 이전 정상 리비전 + 최근 롤백 훈련 근거</strong><b>실행 전 현재 계획으로 가상 실행</b></footer>
        </section>`,
    }),
    slide({
      index: 6,
      state: "BOUNDARY",
      chapter: "통제된 복구와 장애 조치",
      title: "역할과 신원을 분리해 긴급 상황에서도 통제를 유지합니다",
      lead: "한 에이전트가 모든 권한을 갖지 않으며, 사람의 승인과 실행기 신원도 서로 분리됩니다.",
      layout: "sre-authority",
      source: sourceList("operator", "recovery", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-authority-map" aria-label="SRE 대응 권한 분리">
          <div class="sre-agent-lane">
            <article><small>OBSERVE</small><strong>Heimdall(관찰·예측 담당) 에이전트</strong><span>신호와 영향 근거 발행</span></article><i></i>
            <article><small>DECIDE</small><strong>Forseti(판단 담당) 에이전트</strong><span>적격 복구 옵션 판정</span></article><i></i>
            <article class="human"><small>AUTHORIZE</small><strong>운영자 + Var(승인 전달 담당) 에이전트</strong><span>정확한 계획과 범위 승인</span></article><i></i>
            <article><small>ACT</small><strong>Thor(실행 담당) 에이전트</strong><span>승인된 작업만 전달</span></article><i></i>
            <article><small>RECOVER</small><strong>Vidar(복구 담당) 에이전트</strong><span>실패 시 복구 계획 통제</span></article>
          </div>
          <div class="sre-safeguards">
            <header><small>실행 통제</small><strong>실행 전 7개 안전장치</strong></header>
            <ol><li>중지 조건</li><li>검증된 복구</li><li>영향 범위</li><li>가상 실행</li><li>대상 잠금</li><li>중복 억제</li><li>2단계 감사</li></ol>
            <footer><span>Saga(감사 담당) 에이전트</span><b>의도 → 승인 → 실행 → 효과 → 종료를 추가만 가능한 기록으로 연결</b></footer>
          </div>
        </section>`,
    }),
    slide({
      index: 7,
      state: "OPERATE",
      chapter: "통제된 복구와 장애 조치",
      title: "장애 조치는 전환부터 복귀까지 하나의 계획으로 관리합니다",
      lead: "대체 계통으로 트래픽을 옮기는 것만으로 끝내지 않고 데이터 무결성과 failback까지 같은 복구 목표로 관리합니다.",
      layout: "sre-failover",
      source: sourceList("recovery", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-failover-plan" aria-label="장애 조치 계획 예시">
          <div class="sre-failover-architecture">
            <header><span>예시 복구 계획</span><strong>결제 서비스 리전 장애 조치</strong><b>승인 대기</b></header>
            <figure>
              <div class="traffic"><small>사용자 트래픽</small><strong>100%</strong></div>
              <i class="failover-link inbound" aria-hidden="true"></i>
              <article class="primary"><small>PRIMARY · unhealthy</small><strong>Region A</strong><span>오류율 18.2%</span></article>
              <i class="failover-link primary-link" aria-hidden="true"></i>
              <article class="secondary"><small>SECONDARY · ready</small><strong>Region B</strong><span>복제 지연 42초</span></article>
              <i class="failover-link secondary-link" aria-hidden="true"></i>
              <article class="gate"><small>TRAFFIC GATE</small><strong>0% → 10% → 50% → 100%</strong><span>각 단계에서 SLO 확인</span></article>
            </figure>
          </div>
          <aside class="sre-recovery-contract">
            <header><small>복구 목표</small><strong>실행 전에 합의된 경계</strong></header>
            <div><span>RTO 목표</span><b>15분</b></div>
            <div><span>RPO 목표</span><b>5분</b></div>
            <div><span>중지 조건</span><b>오류율 &gt; 2%</b></div>
            <div><span>데이터 검사</span><b>주문 정합성</b></div>
            <div><span>failback</span><b>별도 승인</b></div>
            <footer>경계 초과 시 새 전환을 멈추고 이미 승인된 복구 경로로 이동합니다.</footer>
          </aside>
        </section>`,
    }),
    slide({
      index: 8,
      state: "VALIDATED",
      chapter: "통제된 복구와 장애 조치",
      title: "별도의 관측 경로로 서비스 회복을 확인합니다",
      lead: "실행 시스템과 독립된 텔레메트리에서 SLO, 오류율, 지연 시간, 데이터 정합성, 부작용을 확인해야 종료할 수 있습니다.",
      layout: "sre-verification",
      source: sourceList("recovery", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-verification-board" aria-label="서비스 회복 검증 예시">
          <header><span>예시 효과 관측 · 10분</span><strong>rollback-1842 효과 확인</strong><b>검증 통과</b></header>
          <div class="sre-chart-grid">
            <figure><figcaption><span>오류율</span><b>18.2% → 0.7%</b></figcaption><svg viewBox="0 0 300 110"><path class="axis" d="M8 95 H292"/><path class="before" d="M8 20 L60 25 L110 18 L155 70"/><path class="after" d="M155 70 C190 88 230 87 292 90"/></svg><small>목표 &lt; 1%</small></figure>
            <figure><figcaption><span>p95 지연</span><b>1.8s → 320ms</b></figcaption><svg viewBox="0 0 300 110"><path class="axis" d="M8 95 H292"/><path class="before" d="M8 28 L70 18 L120 30 L155 72"/><path class="after" d="M155 72 C200 84 240 81 292 86"/></svg><small>목표 &lt; 500ms</small></figure>
            <figure><figcaption><span>주문 정합성</span><b>100%</b></figcaption><div class="sre-donut" style="--donut-value:100"><i></i></div><small>불일치 0건</small></figure>
          </div>
          <div class="sre-verification-ledger">
            <article><small>실행</small><strong>작업 전달 성공</strong><span>운영 성공의 충분조건 아님</span></article>
            <i></i>
            <article><small>관측</small><strong>SLO와 데이터 확인</strong><span>실행기와 다른 근거 출처</span></article>
            <i></i>
            <article class="closed"><small>결과</small><strong>서비스 회복 확인</strong><span>감사 기록과 인시던트 마감</span></article>
          </div>
        </section>`,
    }),
    slide({
      index: 9,
      state: "METRIC",
      chapter: "MTTR와 운영 성과",
      title: "MTTR을 대응 단계별로 나누면 병목을 확인할 수 있습니다",
      lead: "감지부터 해결까지의 전체 시간을 분해하면 자동화할 구간과 사람 판단이 필요한 구간을 구분할 수 있습니다.",
      layout: "sre-mttr",
      source: sourceList("metrics", "operator"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-mttr-view" aria-label="MTTR 단계 분석 예시">
          <header><span>예시 인시던트 · resolved</span><strong>총 18분 42초</strong><b>감지 → 해결</b></header>
          <div class="sre-mttr-timeline">
            <article style="--segment:12"><small>00:00</small><strong>감지</strong><span>2m 11s</span></article>
            <article style="--segment:18"><small>02:11</small><strong>상관·영향</strong><span>3m 24s</span></article>
            <article class="bottleneck" style="--segment:35"><small>05:35</small><strong>판단·승인</strong><span>6m 36s</span></article>
            <article style="--segment:20"><small>12:11</small><strong>실행</strong><span>3m 47s</span></article>
            <article style="--segment:15"><small>15:58</small><strong>효과 확인</strong><span>2m 44s</span></article>
          </div>
          <div class="sre-mttr-summary">
            <article><small>중앙값</small><strong>21m 08s</strong><span>대표 대응 시간</span></article>
            <article><small>p90</small><strong>54m 12s</strong><span>느린 대응 경계</span></article>
            <article><small>미해결</small><strong>3건</strong><span>0초로 계산하지 않음</span></article>
            <aside><small>주요 병목</small><strong>승인 대기 6m 36s</strong><p>승인 품질을 낮추지 않고 사전 근거 묶음과 정확한 링크로 대기 시간을 줄입니다.</p></aside>
          </div>
        </section>`,
    }),
    slide({
      index: 10,
      state: "NEXT",
      chapter: "MTTR와 운영 성과",
      title: "도입 결과를 측정 가능한 SRE 성과로 검토합니다",
      lead: "한 개의 반복 가능한 인시던트 시나리오에서 현재 기준선과 FDAI 적용 결과를 같은 근거로 비교한 뒤 확장 여부를 결정합니다.",
      layout: "sre-outcomes",
      source: sourceList("metrics", "operator", "constitution"),
      sourceLabel,
      statusLabel,
      content: `
        <section class="sre-outcome-contract" aria-label="SRE 도입 결과와 산출물">
          <div class="sre-outcome-scorecard">
            <header><small>측정 결과</small><strong>계약 종료 시 함께 확인할 결과</strong></header>
            <article><span>MTTR</span><b>중앙값 · p90</b><small>기준선 대비 변화</small></article>
            <article><span>재발</span><b>동일 증상 건수</b><small>관찰 구간 명시</small></article>
            <article><span>사람 검토</span><b>100건당 접점</b><small>승인과 수동 복구</small></article>
            <article><span>자동 해결</span><b>검증 완료 비율</b><small>롤백 없는 종료만</small></article>
            <article><span>SLO 보호</span><b>위반 시간</b><small>오류 예산 영향</small></article>
            <article><span>효과 확인</span><b>독립 검증률</b><small>미검증 성공 0건</small></article>
          </div>
          <div class="sre-delivery-path">
            <header><small>진행 경로</small><strong>첫 검증 시나리오에서 운영 확장까지</strong></header>
            <ol><li><small>01</small><strong>기준선</strong><span>현재 절차와 시간</span></li><li><small>02</small><strong>관찰 모드</strong><span>판단 품질 비교</span></li><li><small>03</small><strong>통제 실행</strong><span>작은 범위와 승인</span></li><li><small>04</small><strong>성과 검토</strong><span>확장 · 유지 · 축소</span></li></ol>
            <aside><small>시작 방법</small><strong>첫 검증 시나리오 1개 선택</strong><p>예: 배포 직후 오류 증가, 인증서 만료, 용량 임계치 대응</p><b>산출물: 기준선 + 통합 설계 + 복구 계획 + 운영 증적 + 결과 보고서</b></aside>
          </div>
        </section>`,
    }),
  ];
}
