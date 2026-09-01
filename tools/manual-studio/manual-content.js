const docs = {
  constitution: "docs/roadmap/architecture/fdai-constitution.md",
  security: "docs/roadmap/architecture/security-and-identity.md",
  ontology: "docs/roadmap/architecture/operating-ontology.md",
  ontologyPlatform: "docs/roadmap/architecture/operating-ontology-platform.md",
  pantheon: "docs/roadmap/agents/agent-pantheon.md",
  operator: "docs/roadmap/operations/operator-initiated-sre-and-arb.md",
  deployment: "docs/roadmap/deployment/deployment.md",
  hardening: "docs/roadmap/deployment/production-deployment-hardening.md",
  execution: "docs/roadmap/decisioning/execution-model.md",
  metrics: "docs/roadmap/architecture/goals-and-metrics.md",
  dataGovernance: "docs/roadmap/architecture/data-governance.md",
  standingAuthority: "docs/roadmap/decisioning/escalation-and-standing-authority.md",
  runtimeAxes: "docs/roadmap/architecture/decisions/0002-independent-runtime-axes.md",
};

const deckAssets = {
  "readiness-maturity": "assets/readiness-maturity.jpeg",
  "art-of-possible": "assets/art-possible.jpeg",
  "value-prioritization": "assets/value-prioritization.jpeg",
  "target-architecture": "assets/target-architecture.jpeg",
  "ontology-foundation": "assets/ontology-foundation.jpeg",
  "responsible-ai-security": "assets/responsible-ai.jpeg",
  "pilot-production": "assets/pilot-production.jpeg",
  "ai-operating-model": "assets/operating-model.jpeg",
  "enterprise-scale-roadmap": "assets/scale-roadmap.jpeg",
};

const statusLabels = {
  ASSESS: "진단",
  BOUNDARY: "경계",
  CURRENT: "현재 구현",
  DECISION: "결정",
  DEPLOYMENT: "배포",
  ENVISION: "구상",
  FINOPS: "비용 운영",
  FOUNDATION: "기반",
  FRAME: "판단 틀",
  GAP: "현재 미비점",
  GATE: "검증 기준",
  GOVERN: "거버넌스",
  HANDOVER: "인계",
  HOLD: "보류",
  INSPECT: "점검",
  LLMOPS: "LLM 운영",
  METRIC: "측정",
  NEXT: "다음 단계",
  OPERATE: "운영",
  PLAYBOOK: "실행 지침",
  PRINCIPLE: "원칙",
  PROPOSAL: "제안",
  ROADMAP: "로드맵",
  SCORE: "평가",
  TARGET: "목표",
  TRACE: "추적",
};

function sourceLabel(path) {
  return `<small class="evidence-source">근거: ${path}</small>`;
}

function statusLabel(state) {
  const [group, sequence] = state.split(" ", 2);
  if (group === "GATE") return sequence ? `검증 기준 ${sequence}` : statusLabels.GATE;
  if (group === "PHASE") return `단계 ${sequence}`;
  if (group === "WAVE") return `확산 단계 ${sequence}`;
  return statusLabels[state] ?? state;
}

function splitPoint(point) {
  const separator = point.indexOf(":");
  if (separator < 0) return [point, "확인할 근거와 완료 조건을 함께 기록합니다."];
  return [point.slice(0, separator), point.slice(separator + 1)];
}

function cards(points, label) {
  return `
    <section class="agent-constellation" aria-label="${label}">
      ${points.map((point) => {
        const [name, detail] = splitPoint(point);
        return `<div><article><strong>${name}</strong><span>${detail}</span></article></div>`;
      }).join("")}
    </section>`;
}

function flow(points, label) {
  return `
    <figure aria-label="${label}">
      <div class="architecture-map">
        ${points.map((point, index) => {
          const [name, detail] = splitPoint(point);
          const connector = index < points.length - 1 ? "<i aria-hidden=\"true\"></i>" : "";
          return `<div class="arch-node"><span>${String(index + 1).padStart(2, "0")}</span><strong>${name}</strong><small>${detail}</small></div>${connector}`;
        }).join("")}
      </div>
    </figure>`;
}

function matrix(points, label) {
  return `
    <table class="manual-matrix" aria-label="${label}">
      <thead><tr><th scope="col">검토 축</th><th scope="col">판단 근거</th></tr></thead>
      <tbody>${points.map((point) => {
        const [name, detail] = splitPoint(point);
        return `<tr><th scope="row">${name}</th><td>${detail}</td></tr>`;
      }).join("")}</tbody>
    </table>`;
}

function decisionTree(points, label) {
  return `
    <nav class="manual-decision-tree" aria-label="${label}">
      <ol class="safety-list">${points.map((point) => {
        const [question, outcome] = splitPoint(point);
        return `<li><span><strong>${question}</strong><small>${outcome}</small></span></li>`;
      }).join("")}</ol>
    </nav>`;
}

function timeline(points, label) {
  return `
    <ol class="manual-timeline journey" aria-label="${label}">
      ${points.map((point, index) => {
        const [phase, gate] = splitPoint(point);
        const connector = index < points.length - 1 ? "<i aria-hidden=\"true\"></i>" : "";
        return `<li><span><strong>${phase}</strong><small>${gate}</small></span></li>${connector}`;
      }).join("")}
    </ol>`;
}

function responsibilityMap(points, label) {
  return `
    <section class="identity-flow" aria-label="${label}">
      ${points.map((point, index) => {
        const [owner, duty] = splitPoint(point);
        const connector = index < points.length - 1 ? "<i aria-hidden=\"true\"></i>" : "";
        return `<div><small>최종 책임</small><strong>${owner}</strong><span>${duty}</span></div>${connector}`;
      }).join("")}
    </section>`;
}

function evidenceChain(points, label) {
  return `
    <figure class="manual-evidence-chain" aria-label="${label}">
      <figcaption>근거가 다음 판단으로 이어지는 조건</figcaption>
      <div class="journey">${points.map((point, index) => {
        const [evidence, use] = splitPoint(point);
        const connector = index < points.length - 1 ? "<i aria-hidden=\"true\"></i>" : "";
        return `<span><strong>${evidence}</strong><small>${use}</small></span>${connector}`;
      }).join("")}</div>
    </figure>`;
}

const visualBuilders = {
  cards,
  flow,
  matrix,
  tree: decisionTree,
  timeline,
  responsibility: responsibilityMap,
  evidence: evidenceChain,
};

function topic(state, title, lead, points, source, visual = "cards") {
  return { state, title, lead, points: points.split("|"), source, visual };
}

function buildDeck(id, eyebrow, topics) {
  return topics.map((item, index) => {
    const number = String(index + 1).padStart(2, "0");
    if (index === 0) {
      return {
        eyebrow: `FDAI / ${eyebrow}`,
        title: item.title,
        lead: item.lead,
        layout: "cover",
        content: `
          <figure class="cover-photo">
            <img src="${deckAssets[id]}" alt="">
          </figure>
          ${sourceLabel(item.source)}`,
      };
    }
    const builder = visualBuilders[item.visual] ?? cards;
    return {
      eyebrow: `${number} / ${statusLabel(item.state)}`,
      title: item.title,
      lead: item.lead,
      layout: item.visual,
      content: `
        <div class="manual-status" data-state="${item.state}" aria-label="설계 상태: ${statusLabel(item.state)}">${statusLabel(item.state)}</div>
        ${builder(item.points, item.title)}
        ${sourceLabel(item.source)}`,
    };
  });
}

const readinessMaturity = buildDeck("readiness-maturity", "READINESS AND MATURITY", [
  topic("ASSESS", "자동화보다 먼저 운영 준비도를 확인합니다", "전환 리더는 기술 구매가 아니라 의사결정 기반의 준비 상태를 평가합니다.", "대상:결정 유형 하나|기준선:현재 사람 업무|종료 조건:관찰 모드 진입 판단", docs.constitution),
  topic("CURRENT", "현재 운영 목표가 측정 가능한지 확인합니다", "SLO, 복구, 비용, 변경 안전 목표가 없으면 결과를 검증할 수 없습니다.", "목표:단위와 기간|소유자:최종 책임|근거:측정 출처", docs.ontology, "matrix"),
  topic("CURRENT", "반복 사건과 예외를 분리합니다", "반복 가능한 결정은 규칙 후보이고 새롭거나 모호한 사건은 사람 검토 대상입니다.", "반복:동일 입력과 절차|예외:근거 부족 또는 충돌|경계:판단 보류 기준", docs.constitution, "tree"),
  topic("CURRENT", "IaC가 변경의 기준선인지 점검합니다", "검토하고 재현할 수 있는 목표 상태가 파일럿 대상의 전제입니다.", "현재 상태:권위 있는 관측|목표 상태:IaC 또는 GitOps|차이:추측이 아닌 근거", docs.deployment, "evidence"),
  topic("CURRENT", "운영 데이터의 출처를 먼저 등록합니다", "누락과 접근 불가를 정상으로 해석하지 않도록 출처와 범위를 명시합니다.", "출처:인증된 시스템|범위:관측 대상|완전성:보지 못한 영역", docs.constitution, "cards"),
  topic("CURRENT", "시간 정보로 판단을 재현할 수 있는지 봅니다", "사건 시각, 기록 시각, 최신성 기준이 없으면 과거 판단을 정확히 재생할 수 없습니다.", "사건 시각:무엇이 언제 발생했는지|기록 시각:언제 수집했는지|유효 구간:언제까지 쓸 수 있는지", docs.constitution, "timeline"),
  topic("CURRENT", "서비스와 리소스 연결 상태를 평가합니다", "BusinessService, Workload, Resource 매핑은 운영 영향의 최소 척추입니다.", "서비스:가치와 소유권|워크로드:운영 단위|리소스:관측된 대상", docs.ontology, "flow"),
  topic("CURRENT", "미분류 리소스를 숨기지 않습니다", "검토된 매핑이 없으면 unclassified-resource와 unknown_service로 남겨야 합니다.", "분류됨:검토된 타입|미분류:원본 타입 보존|미매핑:서비스 추정 금지", docs.ontology, "matrix"),
  topic("CURRENT", "책임 분리가 조직도에 있는지 확인합니다", "판단, 승인, 실행, 감사, 복구를 한 주체에 모으지 않습니다.", "Forseti:판단|Var:승인 전달|Thor, Saga, Vidar:실행, 감사, 복구", docs.pantheon, "responsibility"),
  topic("CURRENT", "사람 승인 품질도 준비도에 포함합니다", "승인은 특정 행동과 중복 억제 키에 묶이고 침묵은 승인이 아닙니다.", "승인자:실행자와 분리|승인 범위:행동과 대상|만료:시간 초과는 no-op", docs.security, "evidence"),
  topic("CURRENT", "실행 신원의 최소 권한을 검토합니다", "현재 Azure 구현은 관리 ID 참조를 분리하고 알 수 없는 신원을 거부합니다. 실제 작업 권한과 행동 허용 목록은 배포별 확장 구현이 연결합니다.", "상위 구현:관리 ID 참조 분리|배포 책임:리소스 범위와 허용 목록|거부:알 수 없는 신원 참조", docs.security, "cards"),
  topic("CURRENT", "일곱 가지 안전장치의 증적을 찾습니다", "하나라도 빠지면 자율 상태 변경을 시작할 준비가 끝난 것이 아닙니다.", "사전:중지 조건, dry-run, 영향 범위|실행 중:대상 잠금, 중복 억제|사후:rollback, 감사 종료", docs.security, "tree"),
  topic("CURRENT", "독립적으로 효과를 관측할 수 있는지 확인합니다", "API 성공이나 메시지 브로커 수락만으로 운영 성공을 판단할 수 없습니다.", "예상 효과:실행 전에 정의|관측자:실행기와 분리|관측 구간:종료 시점 명시", docs.constitution, "evidence"),
  topic("CURRENT", "관찰 모드 기준선을 수집합니다", "사람의 실제 결정과 시스템 판단을 같은 사건 집합에서 비교합니다.", "품질:정확도와 보류|부하:사람 검토율|안전:정책 위반 유출", docs.security, "timeline"),
  topic("CURRENT", "배포 경계를 다섯 서비스와 권한 전환으로 확인합니다", "Azure 구성은 다섯 서비스로 분리되지만 격리 실행자의 효과 권한은 SD-08 전환 게이트 뒤에 있습니다.", "현재:Core 경로와 관찰 모드 격리 실행기|전환:SD-08 뒤 격리 실행기|되돌림:Core 내부 실행 경로", docs.deployment, "flow"),
  topic("CURRENT", "사설 연결과 내구성 입력을 점검합니다", "프로덕션 배포 계획은 네트워크, 이미지, 모니터링, 비용 입력이 없으면 차단됩니다.", "네트워크:사설 데이터 서비스|공급망:고정되고 서명된 이미지|운영:경고와 예산", docs.hardening, "matrix"),
  topic("GAP", "A3-E 상시 권한은 준비 완료로 계산하지 않습니다", "스키마, 검증기, 수명 주기 저장소, 차단 장치는 구현됐지만 판단과 실행 경로에 연결되지 않았고 관찰 모드 전용입니다.", "구현됨:스키마, 검증기, 수명 주기, 차단 장치|미연결:판단과 실행 경로|미확보:승격 경로와 운영 증적", docs.standingAuthority, "cards"),
  topic("GAP", "Workflow 적용 모드의 증적 공백을 표시합니다", "Operator API는 제안 전용이며 로컬과 배포 환경의 권한 경로 증적은 아직 진행 중입니다.", "현재:관찰 모드 제안 수락|진행 중:제어된 적용 모드|필요:동일 경로의 런타임 증적", docs.operator, "evidence"),
  topic("GAP", "점진적 배포는 목표로 분리합니다", "환경 자동 승격, 트래픽 분할 카나리, SLO rollback, Console의 두 환경 교대 배포는 구현되지 않았습니다.", "현재:보호된 계획과 적용|목표:환경 자동 승격|목표:카나리와 SLO rollback", docs.deployment, "timeline"),
  topic("TARGET", "준비도 등급은 권한이 아니라 다음 행동을 정합니다", "낮은 등급은 보완 계획으로, 높은 등급은 관찰 모드 검토로 이어집니다.", "기초:목표와 책임자 보완|관찰 가능:데이터 품질 보완|파일럿 가능:관찰 모드 진입 검토", docs.constitution, "tree"),
  topic("PROPOSAL", "격차 목록을 의사결정 유형에 묶습니다", "플랫폼 전체가 아니라 선택한 판단에 필요한 격차부터 닫습니다.", "필수:파일럿 차단 요소|후속:확장 전 강화|제외:가치와 무관한 범위", docs.execution, "cards"),
  topic("PROPOSAL", "준비도 워크숍의 책임자를 지정합니다", "전환 리더가 결과를 책임지고 운영, 데이터, 보안 담당자가 근거를 제공합니다.", "전환 리더:진행 또는 보류 결정|운영 책임자:현재 기준선|플랫폼과 보안:근거와 권한 경계", docs.pantheon, "responsibility"),
  topic("PROPOSAL", "30일 보완 계획에 검증 지점을 둡니다", "각 격차는 산출물 제출이 아니라 관측 가능한 종료 조건으로 닫습니다.", "1주:대상과 기준선|2주:데이터와 권한|4주:관찰 모드 준비도 검토", docs.operator, "timeline"),
  topic("DECISION", "파일럿 진입은 조건부 판정입니다", "모든 전제가 충족되어도 실행 승인이 아니라 관찰 모드 검토 자격만 얻습니다.", "진행:관찰 모드 비교 시작|보류:근거 보완|중단:현행 운영 유지", docs.security, "tree"),
  topic("NEXT", "다음 회의는 격차 소유권을 확정합니다", "결정 유형 하나, 책임자, 기준선, 차단 격차와 재검토 날짜를 남깁니다.", "선택:결정 유형|배정:격차 책임자|예약:재평가 시점", docs.constitution, "responsibility"),
]);

const artOfPossible = buildDeck("art-of-possible", "ART OF THE POSSIBLE", [
  topic("ENVISION", "통제된 자율 운영의 미래 장면을 살펴봅니다", "경영진은 무제한 자동화가 아니라 책임과 근거가 유지되는 운영 경험을 탐색합니다.", "장면:반복 판단 자동화|경계:사람 승인 유지|성과:효과로 완료", docs.constitution),
  topic("TARGET", "아침에는 예외와 목표 충돌만 검토합니다", "반복 가능한 다수는 결정론으로 처리하고 경영진은 정책과 예외에 집중합니다.", "자동:검증된 반복 판단|사람:목표 충돌|보류:근거 부족", docs.constitution, "cards"),
  topic("TARGET", "장애 대응 과정은 하나의 추적으로 이어집니다", "Incident, 추적, Process, 승인 링크가 같은 상관관계 ID로 이어지는 운영 장면입니다.", "요청:문제 대응 확인|추적:공통 상관관계 ID|복구:독립 결과 확인", docs.operator, "flow"),
  topic("TARGET", "변경 회의는 그래프 영향과 근거를 먼저 봅니다", "ARB는 브라우저의 판단이 아니라 선언된 제약과 지속되는 Process 기록을 검토합니다.", "변경:정확한 리비전|영향:관계 기반 범위|결정:승인 조건 기록", docs.operator, "matrix"),
  topic("TARGET", "비용 절감은 신뢰성 목표를 지킨 뒤 비교합니다", "안전, 데이터 무결성, SLO, 변경 안전을 모두 충족한 선택지 안에서만 비용을 최적화합니다.", "먼저:상위 제약 위반 제거|그다음:적격 선택지 비교|마지막:실현된 절감 검증", docs.constitution, "tree"),
  topic("TARGET", "대화는 실행 버튼이 아니라 의도 번역 창구입니다", "Bragi는 자연어를 형식화된 의도로 옮기지만 판단, 승인, 실행 권한은 갖지 않습니다.", "사람:목표와 질문|Bragi:의도 형식화|에이전트:책임에 따라 처리", docs.pantheon, "responsibility"),
  topic("TARGET", "학습은 즉시 자동화가 아니라 후보를 만듭니다", "Norns의 패턴은 Mimir 검토와 코드로 관리하는 카탈로그 승격 전까지 비활성 상태입니다.", "사례:결과와 근거 봉인|후보:권한 없음|승격:독립 검토", docs.pantheon, "timeline"),
  topic("TARGET", "운영 성공은 독립 관측으로 마감됩니다", "실행 채널과 다른 권위 있는 출처가 기대 효과를 확인해야 완료를 말할 수 있습니다.", "계획:기대 효과 정의|실행:전달 증적|관측:ObservedOutcome", docs.ontology, "evidence"),
  topic("BOUNDARY", "미래 장면과 현재 구현을 혼합하지 않습니다", "현재 Azure 기반의 일부 경로는 검증됐지만 점진적 배포와 A3-E는 아직 목표입니다.", "현재:분리된 신원과 보호 배포|목표:자동 점진적 배포|미구현:A3-E 실행 권한", docs.security, "matrix"),
  topic("DECISION", "탐색의 결론은 작은 미래 장면 하나입니다", "가치가 크고 경계가 선명한 운영 장면을 선택해 우선순위 평가로 넘깁니다.", "선택:한 결정 유형|조건:측정과 복구|다음:가치 우선순위화", docs.execution, "tree"),
]);

const valuePrioritization = buildDeck("value-prioritization", "VALUE PRIORITIZATION", [
  topic("FRAME", "사용 사례가 아니라 의사결정 유형 하나를 고릅니다", "포트폴리오 책임자는 반복 빈도, 기대 효과, 근거, 위험이 분명한 판단부터 검토합니다.", "단위:의사결정 유형|범위:한 대상군|완료:독립 효과 검증", docs.constitution),
  topic("CURRENT", "후보를 운영 문제와 연결합니다", "SRE, Change Safety, Resilience, FinOps 범위에서 실제 판단과 무조치 기준선을 함께 적습니다.", "문제:현재 손실|판단:선택 가능한 행동|기준선:아무것도 하지 않을 때", docs.ontology, "cards"),
  topic("CURRENT", "가치 기준선을 같은 구간에서 측정합니다", "처리 시간, 검토 부하, 재발, 비용을 같은 사건 집합과 기간으로 비교합니다.", "속도:의사결정 소요 시간|품질:재작업과 재발|경제성:의사결정당 비용", docs.metrics, "matrix"),
  topic("CURRENT", "의사결정 빈도와 변동성을 분리합니다", "빈번해도 매번 맥락이 다르면 첫 파일럿으로 적합하지 않을 수 있습니다.", "빈도:충분한 관찰 모드 표본|변동성:입력 형태 안정성|예외율:사람 검토 예상", docs.execution, "matrix"),
  topic("CURRENT", "근거 준비도를 가치와 같은 무게로 봅니다", "인증된 출처, 최신성, 관측 범위가 부족하면 기대 가치가 높아도 실행 후보로 삼기 어렵습니다.", "출처:권위 있는 시스템|시간:최신성 기준 충족|완전성:부재를 입증할 범위", docs.constitution, "evidence"),
  topic("CURRENT", "대상 정체성과 관계 품질을 평가합니다", "정확한 Resource와 의존 관계를 찾지 못하면 영향 범위를 계산할 수 없습니다.", "정체성:정확한 대상|관계:depends_on과 contains|범위:제한된 탐색", docs.ontology, "flow"),
  topic("CURRENT", "목표 충돌 가능성을 먼저 찾습니다", "비용 절감이 SLO나 복구 목표를 침해하면 점수로 상쇄할 수 없습니다.", "안전:상위 제약|신뢰성:SLO, RTO, RPO|비용:적격 선택지 안에서", docs.constitution, "tree"),
  topic("CURRENT", "ActionType 안전 계약의 존재를 봅니다", "중지 조건, rollback, 영향 범위, dry-run, 대상 잠금, 중복 억제, 감사가 모두 필요합니다.", "사전 통제:중지 조건과 dry-run|실행 통제:대상 잠금과 중복 억제|복구:rollback과 감사", docs.security, "cards"),
  topic("CURRENT", "실행 경로를 후보마다 명시합니다", "PR-native, direct API, PR-manual, 도구 호출은 같은 위험 경계를 공유합니다.", "PR-native:Git 검토와 복구|직접 API:별도 rollback 계약|도구 호출:허용 기능에 한정", docs.execution, "matrix"),
  topic("CURRENT", "권한 요구를 가치 점수와 분리합니다", "높은 가치가 승인 또는 실행 권한을 만들지 않습니다.", "판단:RiskGate|승인:Var와 사람|실행:Thor와 실행기 신원", docs.pantheon, "responsibility"),
  topic("CURRENT", "환경과 영향 범위를 보수적으로 분류합니다", "알 수 없는 환경은 프로덕션으로, 넓은 영향은 더 낮은 자율성으로 취급합니다.", "환경:unknown은 prod|영향:resource에서 subscription|결과:auto, approval, shadow, deny", docs.execution, "tree"),
  topic("CURRENT", "T2 의존도를 비용에 반영합니다", "모호한 판단에 모델을 쓰면 품질 통과 기준, 응답 지연, 사람 검토 비용이 함께 늘어납니다.", "T0:규칙과 정책|T1:검증된 유사 사례|T2:근거 기반 추론과 검증", docs.execution, "flow"),
  topic("CURRENT", "사람 검토 부하를 별도 가치 항목으로 둡니다", "승인 요청만 늘리는 자동화는 오히려 운영 성과를 낮출 수 있습니다.", "검토율:예상 HIL 비율|대기:승인 소요 시간|품질:불필요한 상향 검토", docs.pantheon, "matrix"),
  topic("CURRENT", "복구 가능성이 낮으면 우선순위를 낮춥니다", "비가역 작업은 quorum이 필요하며 자동 실행 대상이 아닙니다.", "가역:시험된 rollback|제한적 복구:state_forward_only|비가역:사람 quorum", docs.execution, "tree"),
  topic("CURRENT", "독립 관측 비용을 계산합니다", "효과 출처와 관측 구간이 없으면 절감이나 복구 성공을 입증할 수 없습니다.", "기대 효과:지표 범위|관측:권위 있는 출처|종료:관측 구간 마감", docs.ontology, "evidence"),
  topic("SCORE", "가치는 필수 제약을 통과한 뒤 점수화합니다", "헌법상 부적격인 후보를 높은 가중치로 되살리지 않습니다.", "1단계:필수 제약|2단계:근거 준비도|3단계:가치 순위", docs.constitution, "flow"),
  topic("SCORE", "실행 가능성은 네 가지 증적으로 채점합니다", "준비 상태를 기대감이 아니라 지금 보유한 산출물로 평가합니다.", "데이터:출처 증적|변경:IaC 경로|안전:ActionType 계약|운영:책임자와 실행 절차", docs.deployment, "matrix"),
  topic("SCORE", "위험은 최종 점수의 감점이 아닙니다", "정책 위반은 deny이고 subscription 범위는 자동화 대상에서 제외됩니다.", "deny:정책 위반|approval:파괴적 작업 또는 데이터 영역 변경|shadow:시스템 성능 저하", docs.execution, "tree"),
  topic("SCORE", "전략 적합성은 운영 도메인으로 확인합니다", "후보는 SRE 운영 모델과 초기 세 도메인 중 하나의 성과에 기여해야 합니다.", "Resilience:복구와 연속성|Change Safety:변경 위험|Cost Governance:검증된 효율", docs.constitution, "cards"),
  topic("PROPOSAL", "우선 후보는 좁고 반복 가능해야 합니다", "한 리소스 범위에서 기준선과 효과를 측정할 수 있는 후보를 권장합니다.", "좁은 범위:대상 잠금 가능|반복성:관찰 모드 표본 확보|효과:독립 측정 가능", docs.security, "cards"),
  topic("PROPOSAL", "두 번째 후보는 첫 학습을 재사용해야 합니다", "새 플랫폼을 추가하기보다 같은 근거와 권한 경계를 활용합니다.", "재사용:온톨로지 매핑|재사용:승인 경로|재사용:효과 관측자", docs.ontologyPlatform, "flow"),
  topic("HOLD", "고가치라도 근거가 없으면 보류합니다", "추정 절감, 합성 데이터, 미확인 성공은 프로덕션 준비도 근거가 아닙니다.", "합성:동작 시험 전용|누락:unknown 유지|보류:근거 보완 후 재평가", docs.constitution, "tree"),
  topic("DECISION", "포트폴리오 문서에 한 줄 판정을 남깁니다", "선정 이유와 제외 이유가 같은 기준으로 설명되어야 합니다.", "선정:가치와 준비 충족|보류:보완 가능|제외:경계 또는 가치 부적합", docs.execution, "matrix"),
  topic("GATE", "파일럿 자금은 관찰 모드 성과에 단계적으로 연결합니다", "초기 투자는 관찰, 비교, 안전 증적에 사용하고 적용 모드 전환은 별도 결정으로 둡니다.", "1단계:기준선|2단계:관찰 모드 품질|3단계:승격 검토", docs.security, "timeline"),
  topic("NEXT", "다음 산출물은 선택된 판단의 실행 헌장입니다", "목표, 대상, 기준선, 책임자, 안전 계약, 효과 관측을 한 장에 고정합니다.", "이유:측정할 가치|대상:정확한 범위|책임:운영과 승인", docs.operator, "responsibility"),
]);

const targetArchitecture = buildDeck("target-architecture", "TARGET ARCHITECTURE", [
  topic("TRACE", "현재 구현과 목표 아키텍처를 층별로 추적합니다", "아키텍트는 계약, 런타임, 권한, 데이터, 배포 근거를 같은 그림에서 구분합니다.", "현재:검증된 구성|목표:헌법상 요구|제안:후속 전달", docs.constitution),
  topic("TARGET", "최상위 계약은 FDAI Constitution입니다", "상세 설계와 구현은 안전, 권한, 근거, 효과 검증 원칙을 약화할 수 없습니다.", "목적:안전한 자율 운영|경계:형식화되고 승인된 처리|종료:재현 가능한 결과", docs.constitution, "cards"),
  topic("CURRENT", "Azure가 유일하게 구현된 공급자입니다", "Core 계약은 공급자 중립을 유지하지만 현재 배포 증적은 Azure에 한정됩니다.", "계약:공급자 어댑터|구현:Azure|미구현:Azure 외 공급자", docs.deployment, "matrix"),
  topic("CURRENT", "런타임은 다섯 서비스로 분리됩니다", "각 서비스는 독립 패키지와 신원을 사용합니다. 격리 실행기는 기본 관찰 모드이며 SD-08 뒤에만 효과 권한을 넘겨받습니다.", "Core:현재 실행 경로와 전환 rollback|Operator와 수집 계층:요청과 수집|격리 실행기:SD-08 뒤 권한 전환", docs.deployment, "flow"),
  topic("CURRENT", "Core는 UI 없는 이벤트 기반 계층입니다", "Console은 얇은 표시 계층이며 브라우저가 권한이나 운영 사실을 계산하지 않습니다.", "수신:이벤트 버스|Core:형식화된 제어 영역|Console:조회 화면과 범위가 제한된 요청", docs.constitution, "flow"),
  topic("CURRENT", "에이전트 협업은 형식화된 pub/sub만 사용합니다", "직접 호출, RPC 연결, 에이전트 간 구현 코드 가져오기는 권한 경로가 아닙니다.", "발행자:객체별 단일 작성자|버스:스키마 검증|구독자:독립 실행 일정", docs.pantheon, "responsibility"),
  topic("CURRENT", "판단과 실행 역할이 고정돼 있습니다", "Forseti, Var, Thor, Saga, Vidar의 분리는 설정으로 바꿀 수 없습니다.", "Forseti:판정|Var:승인 전달|Thor, Saga, Vidar:실행, 감사, 복구", docs.pantheon, "responsibility"),
  topic("CURRENT", "운영 온톨로지는 공유 읽기 모델입니다", "그래프는 의미와 관계를 제공하지만 외부 상태나 실행 권한을 만들지 않습니다.", "선언:타입의 의미|투영:관측된 맥락|권한:그래프 밖에서 결정", docs.ontology, "matrix"),
  topic("CURRENT", "정확한 OntologyRelease를 고정합니다", "의사결정 기록은 스키마 버전과 릴리스 요약값을 유지해 의미가 나중에 바뀌는 일을 막습니다.", "타입 참조:이름과 버전|릴리스:카탈로그 요약값|호환성:명시적 판정", docs.ontologyPlatform, "evidence"),
  topic("CURRENT", "ObjectSet 조회는 범위가 제한됩니다", "자유 형식 그래프 질의 대신 목적, 기준 시점, 최신성, 결과 한도를 선언한 정의를 사용합니다.", "입력:타입 또는 인터페이스|경계:조건과 결과 한도|증적:완전성과 비식별 처리", docs.ontologyPlatform, "matrix"),
  topic("CURRENT", "T0 정책은 카탈로그 의미와 연결됩니다", "Rule, SignalType, Property, PolicyArtifact가 같은 결정론적 deny 경로를 참조합니다.", "Rule:의미 선언|PolicyArtifact:Rego 구현|영수증:입력과 결과 요약값", docs.ontology, "evidence"),
  topic("CURRENT", "RiskGate는 두 입력 중 더 낮은 권한을 택합니다", "권위 있는 위험 표와 ActionType 상한 중 어느 쪽도 다른 쪽보다 권한을 높이지 못합니다.", "위험 표:첫 일치 규칙|상한:여섯 축과 안전 저하 조건|결정:더 낮은 자율성", docs.execution, "flow"),
  topic("CURRENT", "실행 경로는 네 종류입니다", "pr_native, direct_api, pr_manual, tool_call은 동일한 승인, 복구, 감사 경계를 통과합니다.", "Git:pr_native와 pr_manual|공급자:direct_api|허용 기능:tool_call", docs.execution, "cards"),
  topic("CURRENT", "모든 상태 변경에는 안전장치 증적이 필요합니다", "실행 전 계약은 일곱 안전 조건을 한 묶음으로 증명해야 합니다.", "준비:dry-run과 영향 범위|실행:대상 잠금과 중복 억제|종료:감사와 복구", docs.security, "evidence"),
  topic("CURRENT", "Terraform 상태 소유권은 서비스별로 분리됩니다", "배포는 독립 백엔드 키와 동료 격리 영수증으로 인프라 상태 소유권을 검증합니다.", "플랫폼 상태:공유 기반|서비스 상태:독립 백엔드 키|동료 확인:요약값과 계보", docs.deployment, "matrix"),
  topic("CURRENT", "이벤트 전송은 Kafka 전송 계약을 따릅니다", "Azure에서는 두 Event Hubs 네임스페이스 조각이 정해진 토픽 소유권을 나눕니다.", "주요 경로:수신, 사람 승인, 단계|운영 경로:실행기와 자산 목록|프로토콜:Kafka 9093", docs.deployment, "flow"),
  topic("CURRENT", "공급망과 배포 계획은 보호됩니다", "서명된 이미지, 계획 변경 제한, 마이그레이션 순서, 기동 점검 근거가 배포 경계를 구성합니다.", "산출물:고정된 요약값|계획:허용 범위 안의 변경|적용:마이그레이션 후 상태 점검", docs.deployment, "timeline"),
  topic("CURRENT", "프로덕션 데이터 영역은 사설 연결이 기본입니다", "프로덕션 통과 기준은 PostgreSQL 사설망, 내구성, 모니터링, 예산 입력을 요구합니다.", "네트워크:공용 접근 차단|내구성:HA와 백업|운영:경고와 예산", docs.hardening, "matrix"),
  topic("CURRENT", "Operator API는 제안 전용 경계를 유지합니다", "워크플로 시작은 관찰 모드 요청을 받지만 적용 모드 요청을 직접 전달하지 않습니다.", "요청자:형식화된 제안|Operator:RBAC와 영속 발신함|Core:권한 판단 경로", docs.operator, "flow"),
  topic("GAP", "Workflow 적용 경로의 환경 동등성은 진행 중입니다", "단계 실행기가 구현됐어도 로컬과 배포 환경을 잇는 전체 경로 근거는 아직 없습니다.", "현재:제어된 코드 경로|열림:런타임 근거|경계:Operator의 직접 적용 없음", docs.operator, "evidence"),
  topic("GAP", "실행 안전장치의 종단 검증은 일부 진행 중입니다", "PR-native, direct API, tool-call 계약은 있으나 Workflow와 격리 실행기의 동등한 근거가 남아 있습니다.", "검증됨:일부 실행 전 경로|진행 중:공통 종단 검증|필요:독립 효과 증적", docs.security, "matrix"),
  topic("TARGET", "효과 검증은 별도 관측자가 마감합니다", "실행기 명령 채널과 다른 권위 있는 출처가 관측 구간을 종료합니다.", "계획:기대 효과|실행:시도 증적|관측:독립 종료", docs.constitution, "evidence"),
  topic("TARGET", "점진적 배포는 동일 산출물의 승격으로 이어집니다", "같은 서명 이미지를 dev, staging, prod로 승격하고 카나리와 SLO rollback을 결합하는 목표입니다.", "dev:통합 근거|staging:관찰 모드와 카나리|prod:범위가 제한된 승격", docs.deployment, "timeline"),
  topic("PROPOSAL", "아키텍처 검토에는 상태 구분을 겹쳐 표시합니다", "각 계층에 CURRENT, TARGET, GAP을 붙여 설계 목표와 배포 근거를 혼합하지 않습니다.", "현재:코드와 보존된 근거|목표:준수할 계약|차이:책임자와 종료 기준", docs.constitution, "matrix"),
  topic("NEXT", "다음 검토에서 열린 권한 경로를 닫습니다", "Workflow 적용, 격리 실행기 종단 검증, 프로덕션 적용 증적을 각각 독립 통과 기준으로 추적합니다.", "1단계:공통 안전장치|2단계:런타임 환경 동등성|3단계:보호된 프로덕션 증적", docs.security, "timeline"),
]);

const ontologyFoundation = buildDeck("ontology-foundation", "ONTOLOGY FOUNDATION", [
  topic("FOUNDATION", "온톨로지는 형식화된 운영 사실의 읽기 기반입니다", "데이터와 플랫폼 엔지니어는 의미, 관측, 권한, 릴리스 경계를 분리해 신뢰할 수 있는 운영 사실을 제공합니다.", "의미:버전이 있는 선언|현실:권위 있는 투영|권한:그래프 밖에서 결정", docs.ontology),
  topic("BOUNDARY", "그래프는 행위자가 아닙니다", "에이전트가 상태 전이를 책임집니다. 온톨로지 기록은 감지, 판단, 승인, 실행을 대신하지 않습니다.", "에이전트:능동적 책임자|그래프:의미와 관계의 제약|효과:독립 관측으로 확인", docs.ontology, "matrix"),
  topic("CURRENT", "운영 범위의 최소 연결축을 구성합니다", "BusinessService, Workload, Resource 연결이 서비스 영향 분석의 출발점입니다.", "BusinessService:안정된 서비스 ID|Workload:운영 가능한 단위|Resource:관측된 객체", docs.ontology, "flow"),
  topic("CURRENT", "비즈니스 역량은 선택적 상위 맥락입니다", "초기 SRE 배포는 BusinessCapability 없이도 최소 연결축을 만들 수 있습니다.", "필수:서비스와 작업 단위|선택:비즈니스 역량|금지:인위적 할당", docs.ontology, "tree"),
  topic("CURRENT", "매핑되지 않은 상태를 명시적으로 보존합니다", "서비스 매핑이 없으면 unknown_service로 남기고 임의의 서비스에 붙이지 않습니다.", "관측:리소스 정체성|알 수 없음:서비스 관계 없음|검토:매핑 제안", docs.ontology, "evidence"),
  topic("CURRENT", "공급자 타입과 중립 타입을 분리합니다", "검토된 매핑이 없으면 공급자 고유 타입을 비활성 근거로 유지합니다.", "공급자 고유:공급자 근거|중립:검토된 ResourceType|대체값:unclassified-resource", docs.ontology, "matrix"),
  topic("CURRENT", "운영 목표는 단위와 적용 구간을 가집니다", "자유 형식 이름 대신 측정 출처, 범위, 책임자, 유효 구간을 기록합니다.", "ServiceObjective:SLI와 측정 구간|RecoveryObjective:RTO와 RPO|CostObjective:통화와 기간", docs.ontology, "cards"),
  topic("CURRENT", "ArchitectureConstraint도 형식이 정해진 의도입니다", "ARB 조건은 검토된 의미와 적용 범위를 가지며 브라우저 상태가 아닙니다.", "제약:검토된 조건|범위:서비스 또는 작업 단위|근거:버전과 출처", docs.ontology, "evidence"),
  topic("CURRENT", "Observation은 기준 시점에 묶인 측정입니다", "측정값은 근거 참조와 사건 기준 시점 없이 현재 사실로 사용하지 않습니다.", "값:정규화된 측정|시간:사건 기준 시점|출처:권위 증적", docs.ontology, "evidence"),
  topic("CURRENT", "Change는 계획과 관측 상태를 구분합니다", "proposed, active, drift-observed, completed 상태를 같은 개방형 속성 모음에 섞지 않습니다.", "계획:원하는 상태의 근거|관측:공급자 이벤트|완료:결과 확인", docs.ontology, "timeline"),
  topic("CURRENT", "Forecast는 불확실성을 함께 기록합니다", "예측 범위, 구간, 신뢰도, 입력 기준 시점이 없으면 의사결정 근거로 쓸 수 없습니다.", "입력:특성 기준 시점|출력:예측 구간과 범위|평가:종료된 실제 결과", docs.ontology, "matrix"),
  topic("CURRENT", "DecisionCase는 변경되지 않는 판단 맥락입니다", "목표, 제약, 근거, 무조치 기준선을 같은 기준 시점에 고정합니다.", "맥락:정확한 리비전|대안:ActionOption|기준선:아무 행동도 하지 않음", docs.ontology, "cards"),
  topic("CURRENT", "ExpectedEffect는 실행 전에 정의합니다", "예상 지표 범위와 관측 구간이 있어야 실행 전후 결과를 비교할 수 있습니다.", "예측:지표 범위|구간:시작과 종료|버전:예측기 ID", docs.ontology, "evidence"),
  topic("CURRENT", "ObservedOutcome이 효과 사슬을 닫습니다", "ActionRun 성공만으로는 SLO 회복이나 절감 실현을 주장하지 않습니다.", "ActionOption:선택된 대응|ActionRun:실행 영수증|ObservedOutcome:독립적으로 관측한 효과", docs.ontology, "flow"),
  topic("CURRENT", "관계는 질문을 위해서만 추가합니다", "시각화만을 위한 연결이 아니라 운영 질문에 답하는 방향성과 연결 수를 선언합니다.", "정체성:허용된 양 끝점|방향:저장된 의미|용도:범위가 제한된 질문", docs.ontology, "tree"),
  topic("CURRENT", "depends_on은 영향 전파의 근거입니다", "인과를 자동으로 증명하지 않고 검토된 의존 관계만 보존합니다.", "출발점:작업 단위 또는 리소스|도착점:필수 의존 대상|주장:관계일 뿐 인과는 아님", docs.ontology, "flow"),
  topic("CURRENT", "contains와 attached_to를 혼동하지 않습니다", "소유 계층과 부착 관계는 탐색 방향과 영향 계산이 다릅니다.", "contains:상위 소유 관계|attached_to:기준점 연결|탐색:선언된 역방향만", docs.ontology, "matrix"),
  topic("CURRENT", "관측과 실행 관계를 분리합니다", "observes는 측정 대상이고 executed_as는 승인된 실행 연결입니다.", "observes:근거 대상|executed_as:통제된 실행|resulted_in:효과 확인", docs.ontology, "matrix"),
  topic("CURRENT", "정확한 타입 참조를 유지합니다", "이름, 버전, 카탈로그 요약값이 런타임 기록의 해석을 고정합니다.", "선언:이름과 버전|릴리스:요약값|기록:정확한 type_ref", docs.ontologyPlatform, "evidence"),
  topic("CURRENT", "OntologyRelease는 변경할 수 없습니다", "기존 기록을 재해석하는 선언의 제자리 교체를 허용하지 않습니다.", "compatible:재사용 허용|migration_required:명시적 변환|incompatible:수락하지 않음", docs.ontologyPlatform, "tree"),
  topic("CURRENT", "서비스 간 기록은 릴리스 봉투를 가집니다", "판단에 중요한 evaluate와 action_draft 소비자는 정확한 릴리스가 다르면 I/O 전에 거부합니다.", "봉투:schema_version|참조:릴리스 요약값|통과 기준:불일치 거부", docs.ontologyPlatform, "flow"),
  topic("CURRENT", "의미 해석 후보는 제안일 뿐입니다", "어휘 일치, 임베딩, 모델 출력은 candidate_only 권한으로 시작합니다.", "입력:정규화된 용어|후보:미해결 용어 허용|권한:없음", docs.ontologyPlatform, "cards"),
  topic("CURRENT", "VerifiedSemanticPlan도 실행 권한이 없습니다", "정확한 카탈로그와 작업 종류를 검증해도 일반 판단 경로로 다시 들어갑니다.", "해결:모든 용어|검증:활성 릴리스|재진입:판단과 승인", docs.ontologyPlatform, "flow"),
  topic("CURRENT", "ObjectSet은 자유 형식 질의를 받지 않습니다", "형식화된 조건, 이름이 있는 관계, 명시적 한도로 그래프 접근을 제한합니다.", "선택:타입 또는 인터페이스|필터:허용된 연산자|탐색:이름이 있는 관계만", docs.ontologyPlatform, "matrix"),
  topic("CURRENT", "조회 증적은 불완전한 이유까지 설명합니다", "result_limit, candidate_limit, traversal_limit은 서로 다른 조회 한계를 뜻합니다.", "result_limit:필요한 결과 수에 도달|candidate_limit:후보 일부만 확인|traversal_limit:그래프 탐색 한도 도달", docs.ontologyPlatform, "cards"),
  topic("CURRENT", "빈 결과도 관측 범위가 없으면 부재가 아닙니다", "잘리거나 불완전한 그래프에서 누락 상태를 정상으로 바꾸지 않습니다.", "완전한 빈 결과:부재 근거|불완전한 빈 결과:알 수 없음|사용 불가:이전 사실을 덮어쓰지 않음", docs.ontologyPlatform, "tree"),
  topic("CURRENT", "비식별 처리 내역은 조회 증적에 남습니다", "보호된 투영은 역할과 목적을 적용하고 제거한 필드의 요약을 보존합니다.", "주체:승인된 역할|목적:단일 사용 목적|증적:비식별 처리 요약", docs.ontologyPlatform, "evidence"),
  topic("CURRENT", "연결 속성 ACL의 공백을 안전하게 처리합니다", "현재 LinkType 속성 ACL이 없으므로 보호된 투영은 연결 속성을 제거합니다.", "현재:연결 속성 ACL 없음|제어:속성 제거|근거:제거한 필드 수", docs.ontologyPlatform, "matrix"),
  topic("CURRENT", "Property 의미 규칙은 정규값을 만듭니다", "값 종류, 단위, 경계, 정규화 규칙을 내용 기반 정체성으로 고정합니다.", "의미:의미 ID|값:정규화|경계:범위와 열거값", docs.ontology, "cards"),
  topic("CURRENT", "숫자는 이진 부동소수점으로 재해석하지 않습니다", "Decimal 기반 정규화가 작성된 경계와 요약값을 안정적으로 유지합니다.", "해석:작성된 문자열|검증:유한한 정확한 값|직렬화:정규 십진수 문자열", docs.ontology, "evidence"),
  topic("CURRENT", "시간 값은 RFC 3339 경계를 따릅니다", "시간대가 없거나 범위를 벗어난 시간은 의미 입력으로 수락하지 않습니다.", "형식:T 구분자|시간대:명시된 시간대|정밀도:제한된 소수 자릿수", docs.ontology, "matrix"),
  topic("CURRENT", "PolicyArtifact는 작성된 Rego를 연결합니다", "Rule 메타데이터와 실제 정책 속성 읽기가 어긋나면 카탈로그 게이트가 차단합니다.", "Rule:의미 선언|정책:결정론적 구현|게이트:AST 요약값 일치", docs.ontology, "evidence"),
  topic("CURRENT", "Framework 기록은 참고 정보입니다", "CAF, WAF 매핑은 탐색 범위를 좁힐 수 있지만 승인이나 위험 판정이 될 수 없습니다.", "Framework:참조 계층|매핑:검토된 목표 연결|권한:참고 전용", docs.ontology, "tree"),
  topic("CURRENT", "진단 지식은 검증 증적으로 축적됩니다", "검토된 진단 방식과 독립 검증을 추가 전용 기록으로 보존하며 거부된 결과도 지우지 않습니다.", "진단 방식:검토된 절차|검증:내용 기반 ID|거부:명시적 부정 근거", docs.ontology, "timeline"),
  topic("CURRENT", "Pod 원격 측정 경로는 읽기 전용 검증 기능입니다", "보호된 ObjectSet과 StateFactMetadata만 사용하며 공급자 I/O나 상태 정상 판정을 만들지 않습니다.", "그래프:Pod, Service, Endpoints|표본:Observation|출력:검증됨 또는 미검증 구간", docs.ontologyPlatform, "flow"),
  topic("GAP", "과거 시점의 인스턴스 조회는 지원되지 않습니다", "보호된 게이트웨이는 신뢰할 수 있는 평가 기준 시점 주변의 current_state_only 조회만 허용합니다.", "현재:현재 기준 시점|한계:설정된 시각 오차 안|목표:별도 과거 조회 API 필요", docs.ontologyPlatform, "matrix"),
  topic("GAP", "일부 릴리스 어휘는 아직 투영되지 않습니다", "ControlObjective 연결 선언은 있지만 기동 투영기와 동등성 실행은 남아 있습니다.", "선언됨:목표와 연결|미투영:런타임 하위 그래프|열림:검토된 근거 발행", docs.ontologyPlatform, "cards"),
  topic("TARGET", "MutationPlan은 변경되지 않는 제안입니다", "대상 리비전, 쓰기 집합, 영향, 복구, 기대 효과와 요약값을 고정합니다.", "계획:정확한 대상|안전:rollback과 영향 범위|재검사:승인과 실행 직전", docs.ontologyPlatform, "evidence"),
  topic("TARGET", "형식화된 함수는 네 종류로 제한됩니다", "query, derive, validate, plan은 공급자 상태 변경을 직접 호출하지 않습니다.", "query와 derive:읽기 전용|validate:적격성을 낮출 수만 있음|plan:제안 전용", docs.ontologyPlatform, "matrix"),
  topic("NEXT", "플랫폼 팀은 릴리스와 근거 품질 목표를 책임집니다", "새 타입을 늘리기 전에 정확한 릴리스, 투영 최신성, 완전성, 마이그레이션 통과 기준을 운영합니다.", "릴리스:변경되지 않는 요약값|투영:최신성 근거|마이그레이션:호환성 결정", docs.ontologyPlatform, "responsibility"),
]);

const responsibleAiSecurity = buildDeck("responsible-ai-security", "RESPONSIBLE AI AND SECURITY", [
  topic("INSPECT", "자율성의 보안 경계는 신원과 근거에서 시작합니다", "보안과 책임 있는 AI 리더는 모델 기능보다 권한 분리와 실패 시 차단 조건을 먼저 검토합니다.", "신원:누가 행동할 수 있는가|권한:무엇을 실행할 수 있는가|근거:왜 실행했고 결과는 무엇인가", docs.security),
  topic("CURRENT", "사람 승인과 실행 신원은 다릅니다", "사람은 실행기 신원을 보유하지 않으며 한 주체가 승인과 실행을 겸하지 않습니다.", "사람:인증된 승인자|실행기:비대화형 작업 신원|원칙:자기 승인 금지", docs.security, "responsibility"),
  topic("CURRENT", "Azure 실행자는 관리 ID 경계를 사용합니다", "상위 구현은 사용 대상이 제한된 토큰과 관리 ID 참조를 분리합니다. 작업별 허용 목록과 리소스 역할은 배포별 확장 구현이 제공합니다.", "상위 구현:대상이 제한된 토큰|신원:사용자 할당 관리 ID 참조|배포 책임:허용 목록과 역할", docs.security, "flow"),
  topic("CURRENT", "도메인별 실행 신원을 분리합니다", "Change Safety, Resilience, FinOps의 신원 참조는 다른 도메인 권한으로 대체되지 않습니다.", "identity/change:변경 배포|identity/resilience:복구 범위|identity/finops:비용 작업", docs.security, "matrix"),
  topic("CURRENT", "알 수 없는 신원 참조는 거부됩니다", "통합 실행기 신원으로 자동 대체하지 않으므로 잘못된 연결이 권한 확대로 이어지지 않습니다.", "확인됨:정확한 연결|알 수 없음:거부|누락:작업 보류", docs.security, "tree"),
  topic("DEPLOYMENT", "작업 권한은 배포에서 최소 범위로 연결합니다", "상위 저장소는 신원 경계를 제공하고, 각 배포별 확장 구현이 리소스 범위의 역할과 행동 허용 목록을 운영합니다.", "상위 구현:신원 분리와 알 수 없는 참조 거부|배포 책임:리소스 범위와 허용 목록|후속:측정 기반 사용자 지정 역할", docs.security, "matrix"),
  topic("CURRENT", "권한 부족은 별도 요청으로 처리합니다", "원래 작업의 승인이 실행기 접근 권한을 만들지 않으며 AccessGrantRequest는 독립 경로를 따릅니다.", "작업:현재 상태로 보류|권한 요청:정확한 계획에 한정|재검사:최신 유효 권한", docs.security, "evidence"),
  topic("CURRENT", "비밀값은 런타임에 주입됩니다", "애플리케이션은 환경 변수나 탑재 경로를 읽고 Core에서 클라우드 비밀값 SDK를 호출하지 않습니다.", "출처:Key Vault 참조|런타임:환경 변수 연결|실패:기동 단계에서 차단", docs.security, "flow"),
  topic("CURRENT", "민감 정보는 모델 입력 전에 줄입니다", "비밀값과 PII를 비식별 처리할 수 없으면 T2로 보내지 않고 사람 검토로 전환합니다.", "분류:데이터 종류|최소화:원문 대신 포인터|경로:비식별 불가 시 사람 검토", docs.security, "tree"),
  topic("CURRENT", "네트워크 수신과 송신을 제한합니다", "실행기와 Core에는 공용 수신 지점이 없고 송신은 필요한 제어 영역과 모델 엔드포인트로 제한합니다.", "수신:이벤트 버스만 허용|관리:사설망|송신:기본 차단 허용 목록", docs.security, "matrix"),
  topic("CURRENT", "공급망은 요약값과 출처 증명으로 고정합니다", "검증된 이미지만 실행하고 내용이 바뀔 수 있는 최신 태그를 사용하지 않습니다.", "의존성:고정된 잠금 파일|산출물:서명 이미지와 SBOM|런타임:고정된 요약값", docs.security, "evidence"),
  topic("CURRENT", "일곱 안전장치가 상태 변경 자격을 정합니다", "단순 체크리스트가 아니라 각 ActionType과 실행 증적이 입증해야 하는 계약입니다.", "실행 전:중지, 범위, dry-run|실행 중:잠금, 중복 억제|실행 후:rollback, 감사 종료", docs.security, "flow"),
  topic("CURRENT", "중지 조건은 기계가 평가할 수 있어야 합니다", "중단 기준은 사람의 기억이 아니라 실행 중과 적용 후에도 확인할 수 있는 조건입니다.", "선언:ActionType stop_conditions|관측:실행 중 계속 확인|결과:중단과 감사", docs.security, "evidence"),
  topic("CURRENT", "rollback은 열거값 계약으로 선언됩니다", "none은 유효하지 않으며 irreversible 작업도 가능한 범위의 복구와 사람 quorum을 가집니다.", "pr_revert/scripted:코드 경로|pitr/snapshot:상태 복구|irreversible:사람 승인과 quorum", docs.security, "matrix"),
  topic("CURRENT", "영향 범위는 그래프로 계산할 수 있습니다", "contains와 역방향 depends_on을 제한된 깊이로 탐색해 실제 영향 대상을 구합니다.", "대상:정확한 리소스|탐색:범위가 제한된 그래프|통과 기준:최대 영향 리소스 수", docs.security, "flow"),
  topic("CURRENT", "dry-run 근거는 계획 버전에 묶입니다", "현재 계획과 다른 가상 실행 결과를 재사용하지 않습니다.", "입력:계획 요약값|예측:기대 변경|통과 기준:성공 근거", docs.security, "evidence"),
  topic("CURRENT", "중복 억제와 대상 잠금이 이중 실행을 막습니다", "재전송과 동시 실행이 같은 리소스에 두 번 적용되지 않도록 합니다.", "키:안정된 작업 ID|잠금:논리 대상|재생:중복은 no-op", docs.security, "flow"),
  topic("CURRENT", "감사는 의도부터 결과까지 이어집니다", "부수 효과 전에 추가 전용 의도 기록을 저장하고 최종 결과로 마감합니다.", "실행 전:감사 의도|실행 중:실행 증적|실행 후:결과 또는 rollback", docs.security, "timeline"),
  topic("CURRENT", "RiskGate는 권한을 높이지 않습니다", "위험 표와 ActionType 축의 최소값이 auto, approval, shadow, deny를 정합니다.", "기준선:첫 일치 위험|상한:계층, 영향 범위, 역할, 환경|안전 우선:상태 점검과 긴급 중지", docs.execution, "matrix"),
  topic("CURRENT", "긴급 중지는 실행 신원 없이 작동합니다", "활성화되면 자동 실행을 관찰 모드나 사람 승인 경로로 낮추며 상태 읽기 실패도 활성 상태로 봅니다.", "작동:승인된 운영자|상태:리비전 충돌 방지|효과:관찰 모드 상한", docs.security, "tree"),
  topic("CURRENT", "새 기능은 관찰 모드에서 시작합니다", "정확도, 표본, 기간, 정책 위반 유출 0을 충족한 작업만 별도 승격 검토를 받습니다.", "관찰:상태 변경 없음|측정:품질과 안전|승격:명시적 등록부 변경", docs.security, "timeline"),
  topic("GAP", "A3-E 상시 권한은 실행 경로에 연결되지 않았습니다", "스키마, 평가기, 수명 주기 저장소와 차단막은 구현됐지만 shadow 전용이며 판단과 실행 경로가 이를 소비하지 않습니다.", "구현:스키마, 평가기, 수명 주기, 차단막|미연결:판단과 전달|열림:통제된 집단과 승격 경로", docs.standingAuthority, "cards"),
  topic("GAP", "프로덕션 개인정보 보호 통과 기준은 진행 중입니다", "비식별 처리와 보존 경로가 있어도 배포 개인정보 보호 승인과 보존된 근거가 남아 있습니다.", "현재:공통 데이터 최소화|열림:프로덕션 승인|열림:보존된 근거", docs.security, "evidence"),
  topic("TARGET", "책임 있는 AI 검토는 모델보다 전체 판단 사슬을 봅니다", "형식화된 의도, 근거 확인, 검증기, 위험, 승인, 효과 검증이 함께 닫혀야 합니다.", "입력:범위 제한과 비식별 처리|판단:결정론적 실행 자격|결과:독립 관측", docs.constitution, "flow"),
  topic("NEXT", "다음 보안 회의에서 열린 통과 기준의 책임자를 정합니다", "A3-E, 개인정보 보호, 공통 실행 종단 검증, 실운영 훈련을 서로 독립된 승인 항목으로 유지합니다.", "보안:A3-E와 신원 훈련|개인정보:프로덕션 통과 기준|런타임:안전장치 종단 검증", docs.security, "responsibility"),
]);

const pilotProduction = buildDeck("pilot-production", "PILOT TO PRODUCTION", [
  topic("PLAYBOOK", "한 의사결정 유형을 관찰 모드에서 적용 모드까지 이동합니다", "배포 책임자는 기능 수가 아니라 측정 가능한 통과 기준과 되돌릴 수 있는 범위를 관리합니다.", "시작:범위가 명확한 실행 헌장|학습:관찰 모드 근거|진전:독립 승격 심사", docs.security),
  topic("PHASE 0", "파일럿 실행 헌장을 한 장으로 고정합니다", "대상, 목표, 기준선, 책임자, 권한 상한, 효과 출처를 시작 전에 합의합니다.", "대상:정확한 리소스 집합|가치:기준 지표|안전:ActionType 계약", docs.operator, "cards"),
  topic("PHASE 0", "사람의 현재 판단을 기준선으로 측정합니다", "같은 사건 집합에서 판단 시간, 결과, 상향 검토, 재작업을 측정합니다.", "속도:판단 소요 시간|품질:올바른 결과|부하:사람 검토율", docs.metrics, "matrix"),
  topic("PHASE 0", "권위 있는 근거 출처를 등록합니다", "합성 데이터는 동작 시험에 쓸 수 있지만 실운영 준비도를 증명하지 못합니다.", "인벤토리:대상 ID|텔레메트리:효과 지표|감사:판단 계보", docs.constitution, "evidence"),
  topic("PHASE 0", "서비스 관계와 운영 목표를 연결합니다", "Resource만 고르면 비즈니스 영향과 상위 제약을 판단할 수 없습니다.", "Resource:runs_on 대상|서비스:책임자와 중요도|목표:SLO, 복구, 비용", docs.ontology, "flow"),
  topic("PHASE 0", "ActionType의 안전 계약을 검토합니다", "실행 코드보다 중지 조건, rollback, 영향 범위, dry-run, 대상 잠금, 중복 억제, 감사를 먼저 봅니다.", "사전 조건:범위와 가상 실행|실행:대상 잠금과 중복 억제|복구:시험과 종료", docs.security, "tree"),
  topic("PHASE 0", "실행자와 승인자를 분리합니다", "파일럿 환경에서도 사람 신원과 작업 신원을 합치지 않습니다.", "승인자:인증된 사람|실행기:비대화형 신원|감사자:독립된 근거", docs.security, "responsibility"),
  topic("GATE 0", "준비되지 않으면 현행 운영을 유지합니다", "IaC, 근거, 책임 체계, 복구 중 하나라도 없으면 관찰 모드 시작을 보류합니다.", "진행:필수 조건 충족|보류:범위가 정해진 보완|중단:안전하지 않거나 측정 불가", docs.constitution, "tree"),
  topic("PHASE 1", "관찰 모드는 실제 변경 없이 판단합니다", "새 작업은 판단과 기록만 수행하고 사람의 실제 결과와 비교합니다.", "입력:실제 사건|판단:형식화된 판정|상태 변경:없음", docs.security, "flow"),
  topic("PHASE 1", "같은 시나리오 집합을 고정합니다", "비교 중 입력 집합을 바꾸면 정확도와 정책 위반 유출 여부를 신뢰할 수 없습니다.", "시나리오:버전이 있는 사례|기준 시점:고정된 근거|재생:결정론적 결과", docs.constitution, "evidence"),
  topic("PHASE 1", "T0 적용 범위를 먼저 높입니다", "반복 판단은 정책과 규칙으로 해결하고 T2는 모호한 소수에 제한합니다.", "T0:결정론적 규칙|T1:검증된 사례 재사용|T2:근거 기반 잔여 모호성 판단", docs.constitution, "flow"),
  topic("PHASE 1", "보류 사유를 학습 데이터와 분리합니다", "근거 누락, 오래된 정보, 충돌, 권한 없음 상태를 모델 실패 하나로 합치지 않습니다.", "근거:누락 또는 최신성 부족|정책:거부 또는 승인 필요|시스템:의존성 사용 불가", docs.constitution, "matrix"),
  topic("PHASE 1", "사람 검토 대기열의 품질을 측정합니다", "필수 승인과 불필요한 상향 검토를 분리해 승인 알림 과다를 줄입니다.", "필수:위험 정책|잔여:모호성|회피 가능:근거 복구 차이", docs.pantheon, "matrix"),
  topic("PHASE 1", "관찰 모드 감사를 완전한 추적으로 남깁니다", "사건, 계층, 판정, 작업 버전, 근거 기준 시점을 재생할 수 있어야 합니다.", "사건:상관관계 ID|판정:결정된 권한 상한|근거:출처별 증적", docs.execution, "evidence"),
  topic("GATE 1", "정책 위반 유출은 0이어야 합니다", "정확도 평균이 높아도 안전 제약을 통과한 것으로 볼 수 없습니다.", "안전:위반 유출 0|품질:기준 충족|적용 범위:표본과 기간 충족", docs.security, "tree"),
  topic("PHASE 2", "제한된 비운영 범위에서 dry-run을 검증합니다", "예측 근거와 실제 계획 요약값이 일치하는지 확인합니다.", "계획:변경되지 않는 요약값|가상 실행:계획 버전에 종속|결과:부수 효과 없음", docs.security, "evidence"),
  topic("PHASE 2", "rollback 복구 훈련을 별도로 수행합니다", "정상 경로의 성공과 장애 복구 가능성은 서로 다른 근거입니다.", "유발:제어된 실패|복구:선언된 계약|검증:이전 상태 복원", docs.security, "timeline"),
  topic("PHASE 2", "영향 범위 계산을 실제 그래프로 검증합니다", "고정된 등급만 믿지 않고 범위가 제한된 의존 대상과 최대 영향 리소스 수를 비교합니다.", "시작점:정확한 대상|그래프:contains와 depends_on|한도:선언된 상한", docs.security, "flow"),
  topic("PHASE 2", "중복 전달을 의도적으로 재생합니다", "최소 한 번 전달되는 이벤트와 재시도가 두 번째 변경을 만들지 않아야 합니다.", "첫 시도:키 예약|재시도:중복 감지|결과:효과 한 번", docs.constitution, "timeline"),
  topic("PHASE 2", "긴급 중지와 성능 저하 경로를 연습합니다", "의존성 실패나 운영자 중지가 권한을 shadow로 낮추는지 확인합니다.", "정상:일반 상한|성능 저하:shadow만 허용|긴급 중지:즉시 격리", docs.execution, "tree"),
  topic("GATE 2", "안전 훈련 근거를 모두 갖춰야 합니다", "dry-run, rollback, 중복 실행, 긴급 중지 중 빠진 항목이 있으면 적용 모드 검토를 시작하지 않습니다.", "근거:정확한 리비전|책임자:독립 검토자|결과:통과 또는 명시적 보류", docs.security, "matrix"),
  topic("PHASE 3", "승격은 기능별로 요청합니다", "환경이나 enabled 값이 ActionType의 권한을 자동으로 바꾸지 않습니다.", "기능:정확한 작업 버전|모드:관찰에서 적용으로|등록부:검토된 상태", docs.constitution, "evidence"),
  topic("PHASE 3", "RiskGate 결과를 전달 직전에 다시 봅니다", "승격되었어도 실시간 영향, 역할, 환경, 시스템 상태가 자율성을 낮출 수 있습니다.", "고정 조건:ActionType 상한|동적 조건:실시간 점검과 상태|최종:가장 낮은 권한", docs.execution, "flow"),
  topic("PHASE 3", "첫 적용은 작은 묶음으로 제한합니다", "낮은 영향 범위와 명확한 중지 조건 안에서만 상태 변경을 허용합니다.", "범위:제한된 한 대상군|속도:명시적 상한|중지:기계 평가", docs.security, "cards"),
  topic("PHASE 3", "사람 승인 경로를 실제로 검증합니다", "approval은 작업과 중복 억제 키에 묶이고 시간 초과는 no-op이어야 합니다.", "요청:특정 작업|승인:구분된 주체|시간 초과:종료된 감사", docs.security, "timeline"),
  topic("PHASE 3", "실행 응답 뒤에도 효과 관측 구간을 기다립니다", "공급자 응답 뒤 권위 있는 독립 관측자가 기대 범위를 확인할 때까지 완료가 아닙니다.", "전달:명령 수락|관측:독립 출처|종료:ObservedOutcome", docs.constitution, "evidence"),
  topic("GATE 3", "첫 적용의 종료 조건을 엄격히 적용합니다", "안전하게 실행됐고 기대 효과가 확인되며 감사 사슬이 닫혀야 다음 묶음으로 갑니다.", "실행:안전장치 통과|효과:지표가 범위 안|감사:최종 종료", docs.ontology, "tree"),
  topic("PHASE 4", "운영 진행 주기마다 성능과 안전을 함께 봅니다", "정확도, 자동 처리율, rollback, 검토율, 효과 검증 성공률을 정기 검토합니다.", "판단:품질과 적용 범위|안전:위반 유출과 rollback|결과:검증된 효과", docs.pantheon, "matrix"),
  topic("PHASE 4", "품질 저하는 자동 강등으로 이어집니다", "권한을 유지한 채 수정하지 않고 관찰 모드로 돌아가 원인을 분석합니다.", "감지:통과 기준 저하|강등:즉시 관찰 모드|복구:새 근거 뒤 재승격", docs.security, "timeline"),
  topic("PHASE 4", "새 규칙은 비활성 후보로 시작합니다", "파일럿 학습이 즉시 카탈로그와 권한을 변경하지 않습니다.", "Norns:후보 제안|Mimir:규칙 검토|등록부:별도 승격", docs.pantheon, "responsibility"),
  topic("PHASE 4", "운영 인수인계에는 책임자와 실행 절차가 필요합니다", "배포 팀이 빠져도 승인, 복구, 경고, 근거 출처를 운영할 수 있어야 합니다.", "서비스 책임자:운영 결과|플랫폼 책임자:런타임|보안 책임자:권한", docs.pantheon, "responsibility"),
  topic("CURRENT", "Operator 워크플로 시작은 제안 전용입니다", "POST /workflows/run은 중복 실행에 안전한 shadow 요청을 받고 mode=enforce를 거부합니다.", "요청자:shadow 제안|Operator:내구 발신함|Core:일반 권한 경로", docs.operator, "flow"),
  topic("GAP", "Workflow 적용 경로의 런타임 근거는 남아 있습니다", "문서화된 책임자 통제 로컬 및 배포 경로가 아직 보존된 근거로 닫히지 않았습니다.", "현재:단계 실행기 코드|열림:제어된 근거|경계:환경 동등성 주장 없음", docs.operator, "evidence"),
  topic("CURRENT", "보호 배포는 정확한 산출물을 사용합니다", "서명 이미지와 봉인된 계획이 신원, 명령, 다른 서비스 상태의 변경을 제한합니다.", "산출물:고정되고 증명됨|계획:허용된 차이만 포함|적용:상태와 다른 서비스 점검", docs.deployment, "timeline"),
  topic("GAP", "자동 점진적 배포는 아직 목표입니다", "dev, staging, prod 자동 승격, 트래픽 분할 카나리, SLO rollback은 구현되지 않았습니다.", "현재:보호된 수동 흐름|목표:산출물 승격|목표:카나리 rollback", docs.deployment, "matrix"),
  topic("PROPOSAL", "프로덕션 준비도는 별도 회의에서 검토합니다", "파일럿 성과가 좋다는 이유만으로 보안, 배포, 운영 통과 기준을 합치지 않습니다.", "배포:결과 근거|보안:신원과 안전장치|운영:당직과 복구", docs.hardening, "responsibility"),
  topic("PROPOSAL", "확장 전에 비용 상한을 검토합니다", "모니터링과 월별 예산은 프로덕션 계획의 필수 입력입니다.", "용량:리소스 특성|모니터링:경고 대상|비용:예산과 책임자", docs.hardening, "matrix"),
  topic("DECISION", "프로덕션 전환은 네 가지 결과 중 하나입니다", "승격, 관찰 모드 유지, 범위 축소, 중지를 근거와 함께 결정합니다.", "승격:모든 게이트 종료|관찰:근거 추가 필요|중지:안전하지 않거나 가치 없음", docs.security, "tree"),
  topic("HANDOVER", "운영 팀은 정확한 리비전의 근거를 받습니다", "코드 링크만 넘기지 않고 배포, 신원, 안전장치, 효과, rollback 근거 묶음을 인수합니다.", "빌드:산출물 출처|운영:권한과 감사|복구:시험을 마친 근거", docs.deployment, "evidence"),
  topic("NEXT", "다음 사용 사례는 검증된 경계를 재사용합니다", "새 권한을 넓히기보다 기존 온톨로지, 관측자, 승인 경로 안의 인접 판단을 선택합니다.", "재사용:타입과 매핑|재사용:근거 출처|재사용:안전 운영 절차", docs.ontologyPlatform, "flow"),
]);

const aiOperatingModel = buildDeck("ai-operating-model", "AI OPERATING MODEL", [
  topic("OPERATE", "운영 모델은 책임과 진행 주기를 연결합니다", "리더는 15개 고정 역할, 플랫폼 책임, 거버넌스, FinOps, LLMOps 의사결정을 하나의 체계로 운영합니다.", "책임:최종 책임자 한 명|거버넌스:분리된 권한|진행 주기:측정된 근거", docs.pantheon),
  topic("CURRENT", "15개 에이전트 역할은 고정돼 있습니다", "확장 구현과 배포는 연결 설정을 제공하지만 에이전트를 추가하거나 이름을 바꾸지 않습니다.", "거버넌스 담당:5|제어 처리 담당:7|도메인 전문가:3", docs.pantheon, "cards"),
  topic("CURRENT", "각 객체 타입에는 작성 책임자가 한 명입니다", "여러 구독자가 같은 투영을 읽어도 권위 있는 발행자는 하나입니다.", "책임자:발행자 한 명|소비자:여러 구독자|전송:형식화된 이벤트", docs.pantheon, "matrix"),
  topic("CURRENT", "Odin은 적격한 목표 절충안만 조정합니다", "안전과 정책을 위반한 선택지는 포트폴리오 점수 계산 전에 제외됩니다.", "Forseti:중재 요청 발행|Odin:적격 선택지 순위화|Saga:판단 감사", docs.pantheon, "responsibility"),
  topic("CURRENT", "Forseti와 Thor의 경계를 지킵니다", "판단자가 실행하지 않고 실행기는 새로운 판정을 만들지 않습니다.", "Forseti:근거 판단|Thor:적격 작업 전달|Vidar:실패 복구", docs.pantheon, "responsibility"),
  topic("CURRENT", "Var는 승인 권한을 전달합니다", "승인 요청, 거부, 만료를 처리하지만 스스로 작업을 실행하지 않습니다.", "사람:현재 승인|Var:검증된 승인 기록|Thor:효과 발생 전 재검사", docs.pantheon, "flow"),
  topic("CURRENT", "Saga는 추가 전용 감사 책임을 맡습니다", "모든 최종 경로와 관찰 모드 결과를 상관관계 ID와 함께 보존합니다.", "의도:효과 발생 전|판단:통과 기준과 권한|결과:최종 마감", docs.pantheon, "evidence"),
  topic("CURRENT", "Mimir와 Norns는 학습과 활성화를 분리합니다", "Norns 후보는 비활성 상태이며 Mimir 검토 뒤 코드로 관리하는 카탈로그 PR을 거칩니다.", "Norns:후보 제안|Mimir:검토와 관리|사람 등록부:승격", docs.pantheon, "responsibility"),
  topic("CURRENT", "Bragi는 대화의 의도 변환만 담당합니다", "자연어를 형식화된 도구 요청으로 옮기지만 판단, 승인, 실행은 하지 않습니다.", "운영자:목표와 범위|Bragi:형식화된 의도|처리 경로:권한 판정", docs.pantheon, "flow"),
  topic("CURRENT", "Njord, Freyr, Loki는 도메인 후보를 만듭니다", "비용, 용량, 복원력 전문성은 별도 상위 에이전트가 아니라 같은 제어 경계로 들어갑니다.", "Njord:비용 제안|Freyr:용량 예측|Loki:카오스와 복원력", docs.pantheon, "cards"),
  topic("GOVERN", "경영 운영위원회는 목표 우선순위를 관리합니다", "안전, 데이터, SLO, 변경 안전, 효율, 비용 순서를 명시적으로 유지합니다.", "1:보안과 안전|2:데이터와 신뢰성|3:성능과 비용", docs.constitution, "timeline"),
  topic("GOVERN", "아키텍처 검토는 지속되는 Process로 운영합니다", "구조 적합성, 프로덕션 준비도, 런타임 진행 상태를 하나의 색으로 합치지 않습니다.", "구조:명세 유효|준비도:근거 완전|런타임:Process 진행 중", docs.operator, "matrix"),
  topic("GOVERN", "ActionType 승격 위원회를 별도로 둡니다", "기능 사용 여부, 환경, 확장 구현 상태, 권한 모드를 서로 독립적으로 검토합니다.", "사용 가능:필수 조건 충족|사용 설정:운영자 선택|모드:관찰 또는 적용", docs.constitution, "tree"),
  topic("GOVERN", "보안 검토는 신원 매핑을 책임집니다", "작업 허용 목록, 역할 할당, 권한 재인증, 비상 접근을 정해진 진행 주기로 관리합니다.", "매월:접근 검토|분기:신원 재인증|발생 시:비상 접근 사후 검토", docs.security, "timeline"),
  topic("GOVERN", "데이터 거버넌스는 근거 품질을 책임집니다", "출처 신원, 목적, 최신성, 관측 범위, 비식별 처리를 프로덕션 통과 기준으로 봅니다.", "출처:인증됨|품질:최신이고 완전함|개인정보:최소화하고 비식별 처리", docs.dataGovernance, "matrix"),
  topic("FINOPS", "FinOps는 모델과 인프라 비용을 함께 봅니다", "결정론적 처리 범위와 T2 호출 비용을 검증된 운영 결과에 연결합니다.", "런타임:플랫폼 지출|추론:T2 비율과 단가|결과:검증된 절감", docs.execution, "matrix"),
  topic("FINOPS", "비용이 늘어나는 작업은 별도 기준을 통과합니다", "월 비용 추정치가 없거나 기준 이상인 수평 확장은 자동 실행하지 않습니다.", "추정:월 비용 영향|통과 기준:위험 표|판정:승인 또는 보류", docs.execution, "tree"),
  topic("FINOPS", "예산은 프로덕션 배포 계획의 입력입니다", "월 예산과 경고 수신처 없이 프로덕션 강화 기준을 통과하지 않습니다.", "예산:금액과 책임자|경고:수신자|검토:편차와 후속 작업", docs.hardening, "evidence"),
  topic("LLMOPS", "LLMOps는 T2를 잔여 모호성에 제한합니다", "모델 성능이 아니라 필요한 경우에만 사용되는 비율과 검증 결과를 관리합니다.", "수요:T0과 T1로 판단 불가|품질:복수 모델과 검증기|안전:근거 확인 또는 보류", docs.constitution, "flow"),
  topic("LLMOPS", "프롬프트와 모델 버전을 재생 기록에 남깁니다", "판단 맥락은 근거 기준 시점과 정확한 알고리즘 또는 모델 버전을 고정합니다.", "입력:비식별 처리된 맥락|모델:정확한 버전|출력:검증된 제안", docs.constitution, "evidence"),
  topic("LLMOPS", "모델 간 불일치는 사람 검토로 보냅니다", "한 모델의 자신감이 다른 모델과 검증기의 확인을 대체하지 않습니다.", "생성:서로 다른 두 모델|비교:일치 여부 확인|상향 검토:해결되지 않은 충돌", docs.constitution, "tree"),
  topic("LLMOPS", "모델은 실행 자격을 부여하지 않습니다", "결정론적 검증기, 정책, 가상 실행이 작업 실행 가능 여부를 결정합니다.", "LLM:제안|검증기:계약 확인|RiskGate:권한 상한", docs.execution, "flow"),
  topic("OPERATE", "일일 진행 주기는 예외와 시스템 상태를 봅니다", "사람은 전체 사건이 아니라 보류, 충돌, 성능 저하, rollback 상태에 집중합니다.", "매일:예외와 의존성|책임자:다음 작업|근거:추적 링크", docs.pantheon, "cards"),
  topic("OPERATE", "주간 진행 주기는 결과와 검토 부하를 봅니다", "정확도, 승인율, rollback, 효과 검증을 같은 시나리오 기준으로 비교합니다.", "품질:판단 정확도|부하:사람 검토율|결과:검증된 성공", docs.metrics, "matrix"),
  topic("OPERATE", "월간 진행 주기는 승격과 비용을 봅니다", "관찰 기간, 정책 위반 유출, 추론 지출, 플랫폼 예산을 독립 기준으로 검토합니다.", "승격:근거 임계값|LLMOps:모델과 검증기|FinOps:예산 편차", docs.security, "timeline"),
  topic("OPERATE", "분기 진행 주기는 권한과 복원력을 재검증합니다", "역할 재인증, rollback, 긴급 중지, 복구 훈련을 정확한 리비전에 남깁니다.", "신원:최소 권한|복구:시험 근거|제어:긴급 중지 훈련", docs.security, "timeline"),
  topic("METRIC", "에이전트별 KPI보다 제어 결과를 우선합니다", "개별 활동량이 아니라 SLO 회복, 재발 방지, 변경 안전, 실현된 절감을 봅니다.", "SRE:복구와 재발 방지|변경:검증된 안전 결과|FinOps:실현된 절감", docs.metrics, "cards"),
  topic("METRIC", "처리 범위와 지연 시간은 보장값이 아닙니다", "같은 시나리오 집합의 기준선과 변경 결과가 없으면 개선 배수를 주장하지 않습니다.", "처리 범위:계층별 비율|지연:의사결정 구간|비교:같은 사례", docs.metrics, "matrix"),
  topic("METRIC", "사람 승인율을 무조건 낮추지 않습니다", "정책상 필요한 승인과 불필요한 상향 검토를 구분합니다.", "필수:위험과 권한|잔여:모호성|회피 가능:근거 차이", docs.pantheon, "tree"),
  topic("METRIC", "효과 없는 성공을 제거합니다", "전달 성공 대신 독립 관측으로 결과 KPI를 닫습니다.", "시도:실행기 영수증|관측:권위 있는 출처|평가:예상과 실제 비교", docs.ontology, "evidence"),
  topic("CURRENT", "로컬과 배포는 같은 계약을 사용합니다", "공급자와 자격 증명만 다르고 카탈로그, 게이트, Process 이벤트를 임의로 바꾸지 않습니다.", "같음:규칙과 승격|같음:위험과 승인|다름:어댑터와 신원", docs.operator, "matrix"),
  topic("GAP", "Workflow 적용 동등성은 운영 항목으로 남습니다", "제안 전용 Operator 경계는 구현됐지만 통제된 런타임 영수증이 아직 필요합니다.", "현재:내구 제안 연결|열림:적용 영수증|책임자:플랫폼과 거버넌스", docs.operator, "responsibility"),
  topic("GAP", "프로덕션 개인정보 보호 근거를 완료로 표시하지 않습니다", "공통 비식별 처리 구현과 배포 개인정보 보호 승인은 다른 상태입니다.", "구현:최소화 경로|진행:프로덕션 게이트|열림:보존된 근거", docs.security, "matrix"),
  topic("GAP", "점진적 배포는 로드맵 항목입니다", "자동 산출물 승격과 카나리 rollback은 현재 운영 진행 주기에 없는 목표입니다.", "현재:보호된 워크플로|목표:자동 승격|목표:SLO rollback", docs.deployment, "timeline"),
  topic("PROPOSAL", "RACI는 고정된 Pantheon과 사람 책임자를 연결합니다", "에이전트 역할을 바꾸지 않고 정책, 서비스, 보안, 플랫폼의 최종 책임자를 배정합니다.", "서비스 책임자:비즈니스 결과|플랫폼 책임자:런타임 SLO|보안 책임자:권한 정책", docs.pantheon, "responsibility"),
  topic("PROPOSAL", "운영 회의는 근거 링크로 시작합니다", "슬라이드 색이나 구두 보고가 아니라 정확한 추적, 릴리스, 근거를 검토합니다.", "추적:상관관계 ID|릴리스:요약값|근거:출처와 기준 시점", docs.ontologyPlatform, "evidence"),
  topic("PROPOSAL", "예외에는 만료와 재검토를 붙입니다", "정책 예외와 비상 접근은 기한을 두며 자동 상시 권한으로 남지 않습니다.", "범위:제한된 대상|시간:명시적 만료|종료:사후 검토 감사", docs.security, "timeline"),
  topic("PROPOSAL", "업무 인수인계는 권한이 아니라 운영 근거를 전달합니다", "새 담당자는 실행 절차, 판단 계보, rollback 근거를 받고 권한은 별도 절차로 부여받습니다.", "지식:실행 절차와 사례|근거:추적과 결과|권한:별도 재인증", docs.pantheon, "responsibility"),
  topic("DECISION", "운영 모델 승인에는 열린 항목도 포함합니다", "CURRENT와 TARGET 사이의 책임자, 기한, 종료 기준을 명시해야 합니다.", "수락:구현된 경계|추적:진행 중인 근거|거부:근거 없는 주장", docs.constitution, "tree"),
  topic("NEXT", "운영 달력에 네 가지 진행 주기를 예약합니다", "일일 운영, 주간 결과, 월간 승격과 비용, 분기별 권한 훈련의 책임자를 배정합니다.", "매일:예외 검토|매월:승격과 FinOps|분기:신원과 복구", docs.security, "timeline"),
]);

const enterpriseScaleRoadmap = buildDeck("enterprise-scale-roadmap", "ENTERPRISE SCALE ROADMAP", [
  topic("ROADMAP", "전사 확장은 기능 수가 아니라 의존성과 종료 기준으로 진행합니다", "플랫폼과 거버넌스 리더는 한 의사결정 유형의 근거를 공통 기반으로 삼아 확장합니다.", "순서:기반부터 구축|통과 기준:권한보다 근거가 먼저|확장:범위를 넓히기 전 재사용", docs.constitution),
  topic("PRINCIPLE", "확장은 자율성을 자동으로 높이지 않습니다", "조직, 환경, 확장 구현, 사용 설정, 승격 상태는 서로 독립된 축입니다.", "조직:참여 팀 확대|환경:실행 장소 확대|권한:별도 승격 심사", docs.runtimeAxes, "matrix"),
  topic("PRINCIPLE", "Azure 구현 사실과 공급자 목표를 분리합니다", "현재 확장 계획은 Azure 근거를 사용하며 Azure 외 공급자는 계약 확장 가능성일 뿐입니다.", "현재:Azure 어댑터|목표:공급자 중립 계약|미구현:Azure 외 공급자", docs.deployment, "tree"),
  topic("PRINCIPLE", "하나의 제어 영역이 여러 도메인을 지원합니다", "SRE 운영 모델 아래 Resilience, Change Safety, Cost Governance를 같은 안전 경계로 확장합니다.", "SRE:전체 운영 모델|도메인:초기 세 영역|ARB:도메인 간 거버넌스", docs.constitution, "cards"),
  topic("WAVE 0", "전사 목표의 우선순위를 승인합니다", "안전과 신뢰성보다 비용을 앞세우지 않는 공통 순서를 먼저 고정합니다.", "1:보안과 데이터 무결성|2:SLO와 변경 안전|3:효율과 비용", docs.constitution, "timeline"),
  topic("WAVE 0", "의사결정 유형 목록을 만듭니다", "팀별 도구 목록 대신 누가 어떤 근거로 어떤 판단을 하는지 수집합니다.", "판단:반복 가능한 선택|근거:권위 있는 출처|책임자:최종 책임을 지는 사람", docs.ontology, "cards"),
  topic("WAVE 0", "공통 결과 분류 체계를 정합니다", "auto, approval, shadow, deny, rollback, unknown 값을 보고 화면의 공통 언어로 풀이합니다.", "판단:실행 자격 상태|실행:시도 상태|결과:관측된 효과 상태", docs.execution, "matrix"),
  topic("GATE 0", "후원자와 책임자가 없으면 시작하지 않습니다", "가치와 위험, 데이터, 플랫폼 결과의 최종 책임을 문서화합니다.", "후원자:우선순위와 예산|서비스 책임자:운영 결과|플랫폼 책임자:런타임", docs.pantheon, "responsibility"),
  topic("WAVE 1", "운영 OntologyRelease 기반을 배포합니다", "안정된 타입과 정확한 요약값이 팀마다 의미를 다르게 해석하는 일을 막습니다.", "카탈로그:변경되지 않는 릴리스|런타임:정확한 참조|호환성:마이그레이션 판정", docs.ontologyPlatform, "evidence"),
  topic("WAVE 1", "BusinessService와 Workload 연결축을 채웁니다", "모든 리소스를 한 번에 분류하기보다 우선 서비스의 정확한 매핑부터 시작합니다.", "서비스:중요도와 책임자|Workload:배포 가능한 단위|Resource:관측된 배치 위치", docs.ontology, "flow"),
  topic("WAVE 1", "미분류 작업 목록을 가시화합니다", "unknown_service와 unclassified-resource를 숨기지 않고 매핑 작업으로 관리합니다.", "알 수 없음:보이는 상태로 유지|책임자:분류 담당자|종료:검토된 매핑", docs.ontology, "timeline"),
  topic("WAVE 1", "근거 출처 등록부를 표준화합니다", "출처 신원, 목적, 범위, 최신성, 완전성, 출처 계보를 공통 근거로 만듭니다.", "신원:인증된 출처|시간:사건 시각과 기록 시각|범위:완전성 확인", docs.constitution, "matrix"),
  topic("WAVE 1", "데이터 최소화 경계를 적용합니다", "원문 데이터보다 포인터와 요약값을 보존하고 비식별 처리 정보를 남깁니다.", "수집:최소 필드|저장:포인터와 요약값|표시:역할별 비식별 처리", docs.security, "flow"),
  topic("GATE 1", "형식화된 운영 사실의 검증 역량을 확인합니다", "정확한 ID, 관계, 최신성, 관측 범위를 제한된 질의로 답해야 합니다.", "C1:ID와 접근|C2:관계와 영향|C3:근거 상태", docs.ontologyPlatform, "tree"),
  topic("WAVE 2", "고정된 15개 에이전트 구성을 활성화합니다", "팀마다 새 에이전트를 만들지 않고 설정과 공급자 연결로 범위를 확장합니다.", "고정:역할과 객체 책임자|설정:범위와 정책|어댑터:공급자 구현", docs.pantheon, "cards"),
  topic("WAVE 2", "토픽 소유권과 스키마 통과 기준을 배포합니다", "단일 작성자, 다중 독자, 최소 한 번 전달 재생이 확장 시 권위 충돌을 막습니다.", "발행자:책임자 한 명|전송:스키마 검증|소비자:중복을 억제하는 재생", docs.pantheon, "flow"),
  topic("WAVE 2", "신원을 서비스와 도메인별로 분리합니다", "Console, Core, 수집 계층, 실행기, 도메인별 배포 주체가 신원을 공유하지 않습니다.", "서비스:서로 다른 작업 신원|도메인:변경, 복원력, FinOps|사람:분리된 승인", docs.security, "matrix"),
  topic("WAVE 2", "전역 긴급 중지를 운영 체계에 연결합니다", "전사 확장 전에 실행 신원 없이 중단하고 감사, 호출, 만료까지 이어지는 절차를 연습합니다.", "작동:책임자 또는 비상 접근|효과:관찰 모드 상한|근거:훈련 근거", docs.security, "timeline"),
  topic("GATE 2", "분리된 의존성의 실패를 검증합니다", "Saga, Vidar, 관측자, 승인 경로 중 하나가 없을 때 상태 변경이 차단되어야 합니다.", "감사 중단:상태 변경 없음|복구 중단:상태 변경 없음|관측 중단:성공 주장 없음", docs.constitution, "tree"),
  topic("WAVE 3", "첫 도메인은 한 의사결정 유형으로 시작합니다", "가치, 반복성, 근거, rollback이 가장 준비된 범위를 선택합니다.", "범위:한 대상 유형|모드:관찰|측정:기준선과 효과", docs.security, "cards"),
  topic("WAVE 3", "시나리오 묶음을 고정합니다", "성공, 거부, 충돌, 부분 실패, 재생을 포함한 같은 사건 집합을 사용합니다.", "정상 경로:전체 과정|부정 경로:알 수 없음 또는 거부|복구:부분 실패", docs.constitution, "matrix"),
  topic("WAVE 3", "관찰 기간과 검토 결과를 수집합니다", "판단 품질과 정책 위반 유출 여부를 실제 검토자 결과로 마감합니다.", "관찰:상태 변경 없음|검토:분리된 사람|근거:안정된 관측 ID", docs.pantheon, "timeline"),
  topic("WAVE 3", "안전장치 훈련을 완료합니다", "dry-run, rollback, 영향 범위, 잠금, 중복 억제, 감사를 정확한 리비전에서 검증합니다.", "실행 전:가상 실행과 범위|실행 중:잠금과 중복 억제|실행 후:rollback과 종료", docs.security, "evidence"),
  topic("GATE 3", "첫 승격은 독립 심사를 받습니다", "파일럿 팀이 자기 결과만으로 적용 모드 권한을 부여하지 않습니다.", "배포:근거 묶음|보안:권한 검토|거버넌스:등록부 변경", docs.security, "responsibility"),
  topic("WAVE 4", "인접 의사결정 유형에 검증된 기반을 재사용합니다", "같은 서비스 매핑, 근거 출처, 승인 경로, 관측자를 활용해 확장합니다.", "재사용:온톨로지 연결축|재사용:출처 근거|재사용:안전 운영 절차", docs.ontology, "flow"),
  topic("WAVE 4", "SRE 도메인의 전체 경로를 닫습니다", "감지부터 검증된 복구와 재발 종료까지 시나리오 근거를 만듭니다.", "감지:SLO 또는 Incident|복구:제어된 작업|종료:효과와 재발 확인", docs.constitution, "evidence"),
  topic("WAVE 4", "Change Safety의 전체 경로를 닫습니다", "그래프 차이와 제약 검토가 승인 조건과 변경 후 검증으로 이어져야 합니다.", "변경:정확한 리비전|평가:영향과 제약|검증:변경 후 결과", docs.constitution, "flow"),
  topic("WAVE 4", "FinOps의 전체 경로를 닫습니다", "Finding이나 Forecast가 실제 절감으로 이어져도 신뢰성 목표는 유지되어야 합니다.", "기회:비용 근거|작업:적격 선택지|결과:절감과 SLO 유지", docs.constitution, "evidence"),
  topic("WAVE 4", "복원력 적용 범위를 분리합니다", "DR과 카오스 시험은 서로 다른 기능이며 각각 복구와 안전한 실험 근거가 필요합니다.", "DR:RTO와 RPO 근거|카오스:사람이 승인한 장애 주입|공통:검증된 복구", docs.constitution, "matrix"),
  topic("GATE 4", "도메인별 전체 경로를 확인합니다", "한 성공 사례가 아니라 거부, 충돌, 복구, 재생 사례까지 필요합니다.", "성공:기대 결과|경계:거부와 충돌|복원력:복구와 재생", docs.constitution, "tree"),
  topic("WAVE 5", "플랫폼을 프로덕션 구성으로 강화합니다", "사설망, 내구성 있는 PostgreSQL, 모니터링, 예산, 신뢰할 수 있는 이미지를 배포 통과 기준으로 만듭니다.", "네트워크:사설 데이터 서비스|내구성:HA와 백업|운영:경고와 예산", docs.hardening, "cards"),
  topic("WAVE 5", "서비스별 상태 소유권을 유지합니다", "서비스별 백엔드와 상호 격리 근거가 대규모 배포의 영향 범위를 제한합니다.", "상태:서비스별 키|계획:다른 서비스 상태 점검|근거:요약값과 계보", docs.deployment, "evidence"),
  topic("WAVE 5", "마이그레이션과 초기 구성을 순서대로 실행합니다", "Operator 스키마 마이그레이션 뒤 변경되지 않는 Rule과 Ontology 투영을 작성합니다.", "먼저:스키마 마이그레이션|다음:카탈로그 초기 구성|마지막:준비도와 상태 점검", docs.deployment, "timeline"),
  topic("WAVE 5", "rollback 기준선을 보호합니다", "정상인 활성 리비전을 캡처하고 비활성 리비전 하나를 복구용으로 남깁니다.", "캡처:정상 활성 리비전|보존:비활성 리비전 하나|복구:보호된 워크플로", docs.deployment, "evidence"),
  topic("GATE 5", "보호된 적용 근거를 보존합니다", "코드와 계획 변경 제한만으로 프로덕션 검증을 주장하지 않습니다.", "계획:정확한 리비전|적용:무관한 삭제 0|관측:상태와 rollback 경계", docs.hardening, "tree"),
  topic("WAVE 6", "조직별 범위를 정책과 설정으로 나눕니다", "상위 Core를 수정하지 않고 배포가 소유한 매핑과 목표를 공급합니다.", "상위 저장소:안정된 개념|배포:인스턴스와 의도|확장 구현:주입된 구현", docs.ontology, "matrix"),
  topic("WAVE 6", "공통 승격 위원회를 운영합니다", "팀별 속도는 달라도 권한 근거 기준은 같아야 합니다.", "현장 팀:관찰 모드 근거|위원회:독립 검토|등록부:정확한 기능 상태", docs.security, "responsibility"),
  topic("WAVE 6", "접근 권한 재인증을 정기 일정에 넣습니다", "사용하지 않거나 지나치게 넓은 권한을 정기적으로 찾아 회수하고 감사합니다.", "목록:역할 할당|검토:책임자 확인|조치:회수와 기록", docs.security, "timeline"),
  topic("WAVE 6", "FinOps와 LLMOps를 같은 포트폴리오에서 봅니다", "모델 호출과 플랫폼 비용을 검증된 운영 결과와 연결합니다.", "추론:T2 비율과 지출|플랫폼:서비스 비용|결과:가치 실현", docs.execution, "matrix"),
  topic("GATE 6", "확장 단위의 경제성을 입증합니다", "팀 수나 사건 수가 아니라 의사결정당 비용과 검증된 편익을 비교합니다.", "비용:의사결정당 비용|편익:검증된 효과|제약:신뢰성 유지", docs.constitution, "tree"),
  topic("WAVE 7", "여러 목표의 충돌을 중재합니다", "헌법상 적격한 후보만 Odin이 순위를 정하고 Saga가 충돌 판단을 감사합니다.", "Forseti:중재 요청 구성|Odin:선택, 보류, HIL|Saga:판단 계보 보존", docs.pantheon, "responsibility"),
  topic("WAVE 7", "도메인 간 근거 기준 시점을 통일합니다", "비용, 용량, 복원력 후보가 같은 대상과 기준 시점을 공유해야 합니다.", "대상:정확한 리소스|시간:공통 기준 시점|계보:책임자가 인증한 후보", docs.pantheon, "evidence"),
  topic("WAVE 7", "학습 사례군을 균형 있게 봉인합니다", "합성 실운영 기록이나 중복 리비전은 승격 증적이 아닙니다.", "사례군:균형 잡힌 사례|리비전:FDAI와 시나리오 고정|검토:최신이며 충돌 없음", docs.pantheon, "matrix"),
  topic("GATE 7", "학습이 권한을 높이지 않는지 검증합니다", "Pattern, RuleCandidate, 의미 계획은 검토 전까지 비활성 상태여야 합니다.", "후보:실행 권한 없음|검토:독립 수행|승격:카탈로그와 등록부", docs.ontologyPlatform, "tree"),
  topic("TARGET", "같은 산출물을 승격해 환경을 연결합니다", "동일한 서명 이미지가 dev, staging, prod를 이동하는 목표를 유지합니다.", "dev:빌드와 통합|staging:대표성 있는 관찰|prod:승인된 산출물", docs.deployment, "timeline"),
  topic("GAP", "자동 점진적 배포는 아직 구현되지 않았습니다", "트래픽 분할 카나리, SLO rollback, Console의 두 환경 교대 배포를 현재 기능으로 표시하지 않습니다.", "현재:보호된 배포|목표:자동 승격|열림:제어된 런타임 근거", docs.deployment, "matrix"),
  topic("GAP", "A3-E를 전사 확장의 전제로 두지 않습니다", "스키마와 검증기는 구현됐지만 관찰 모드 전용으로 미연결이며 운영 승격 경로와 사례군 근거가 없습니다.", "구현:카탈로그와 검증기|미연결:판단과 실행 전달|경계:상시 실행 권한 없음", docs.standingAuthority, "cards"),
  topic("PROPOSAL", "로드맵 현황표는 종료 기준만 집계합니다", "활동 완료율 대신 정확한 근거로 닫힌 의존성을 표시합니다.", "완료:보존된 근거|진행 중:구현됐으나 근거 미완료|미착수:구현되지 않음", docs.hardening, "matrix"),
  topic("PROPOSAL", "단계 간 의존성 변경은 ARB에서 재검토합니다", "새 서비스, 신원, 상태 책임자가 이전 통과 기준의 안전 가정을 바꾸면 다음 단계를 멈추고 영향 근거를 갱신합니다.", "변경:정확한 아키텍처 리비전|검토:제약과 영향|재개:갱신된 종료 근거", docs.operator, "evidence"),
  topic("NEXT", "다음 분기는 확산 0단계부터 2단계까지 닫습니다", "목표, 의사결정 목록, 온톨로지 연결축, 근거 등록부, 신원 분리를 먼저 완료합니다.", "분기 시작:책임자와 우선순위|중간 점검:형식화된 운영 사실|종료:실패 시 차단되는 구성", docs.constitution, "timeline"),
]);

export const additionalManualSlides = {
  "readiness-maturity": readinessMaturity,
  "art-of-possible": artOfPossible,
  "value-prioritization": valuePrioritization,
  "target-architecture": targetArchitecture,
  "ontology-foundation": ontologyFoundation,
  "responsible-ai-security": responsibleAiSecurity,
  "pilot-production": pilotProduction,
  "ai-operating-model": aiOperatingModel,
  "enterprise-scale-roadmap": enterpriseScaleRoadmap,
};
