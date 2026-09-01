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
  structuralModel: "docs/roadmap/architecture/ontology-structural-model.md",
  metamodel: "docs/roadmap/architecture/operating-ontology-metamodel.md",
  llmStrategy: "docs/roadmap/architecture/llm-strategy.md",
  semanticRetrieval: "docs/roadmap/rules-and-detection/rule-semantic-retrieval.md",
  documentIngestion: "docs/roadmap/interfaces/document-ingestion.md",
  ontologyDistillation: "docs/roadmap/rules-and-detection/document-ontology-distillation.md",
  operationalLearning: "docs/roadmap/rules-and-detection/operational-learning-ontology.md",
  behaviorKnowledge: "docs/roadmap/interfaces/behavior-knowledge.md",
  ontologyAgentLoop: "docs/roadmap/architecture/architecture-review/ontology-agent-loop.md",
  actionOntology: "docs/roadmap/decisioning/action-ontology.md",
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

const deckProfiles = {
  "readiness-maturity": {
    label: "READINESS",
    sections: ["운영 기준선", "근거와 권한", "파일럿 진입"],
    segments: [[1, "운영 기준선"], [9, "근거와 권한"], [19, "파일럿 진입"]],
  },
  "art-of-possible": {
    label: "POSSIBILITIES",
    sections: ["미래 운영 경험", "안전 경계", "가치 장면"],
    segments: [[1, "목표 운영 경험"], [5, "안전 경계"], [8, "가치 장면"]],
  },
  "value-prioritization": {
    label: "PRIORITIZE",
    sections: ["후보 정의", "근거 기반 평가", "포트폴리오 결정"],
    segments: [[1, "후보와 적격성"], [8, "가치와 안전 평가"], [19, "포트폴리오 결정"]],
  },
  "target-architecture": {
    label: "ARCHITECT",
    sections: ["의미와 계약", "판단과 권한", "배포와 검증"],
    segments: [[1, "시스템과 의미"], [8, "판단과 권한"], [15, "배포와 검증"]],
  },
  "responsible-ai-security": {
    label: "GUARDRAILS",
    sections: ["신원과 데이터", "실행 안전", "운영 통제"],
    segments: [[1, "신원과 데이터"], [10, "실행 안전"], [18, "운영 통제"]],
  },
  "pilot-production": {
    label: "ACTIVATE",
    sections: ["기준선", "관찰 모드", "승격과 운영"],
    segments: [[1, "기준선과 현재 경계"], [10, "관찰 모드 검증"], [27, "승격과 운영"]],
  },
  "ai-operating-model": {
    label: "OPERATE",
    sections: ["책임 체계", "거버넌스", "측정과 개선"],
    segments: [[1, "책임 체계"], [10, "거버넌스와 운영"], [27, "측정과 개선"]],
  },
  "enterprise-scale-roadmap": {
    label: "EVOLVE",
    sections: ["확장 의존성", "확산 단계", "종료 기준"],
    segments: [[1, "현재 위치와 의존성"], [14, "확산 단계"], [38, "종료 기준과 다음 결정"]],
  },
};

const statusLabels = {
  ASSESS: "진단",
  BOUNDARY: "경계",
  CRITERIA: "평가 기준",
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
  IMPLEMENTED: "구현됨",
  IN_PROGRESS: "진행 중",
  ILLUSTRATIVE: "예시",
  LLMOPS: "LLM 운영",
  METRIC: "측정",
  NEXT: "다음 단계",
  NOT_STARTED: "시작 전",
  OPERATE: "운영",
  PLAYBOOK: "실행 지침",
  PRINCIPLE: "원칙",
  PROPOSAL: "제안",
  ROADMAP: "로드맵",
  SCORE: "평가",
  TARGET: "목표",
  TRACE: "추적",
  VALIDATED: "검증됨",
};

function sourceLabel(source) {
  const paths = Array.isArray(source) ? source : [source];
  return `<small class="evidence-source">근거: ${paths.join(" · ")}</small>`;
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

function briefingNumbers(points, label) {
  return `
    <section class="briefing-number-grid" aria-label="${label}">
      ${points.map((point) => {
        const [value, detail] = splitPoint(point);
        return `<article><strong>${value}</strong><span>${detail}</span></article>`;
      }).join("")}
    </section>`;
}

function briefingComparison(points, label) {
  return `
    <section class="briefing-comparison" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<article><small>${String(index + 1).padStart(2, "0")}</small><strong>${name}</strong><span>${detail}</span></article>`;
      }).join("")}
    </section>`;
}

function briefingLayers(points, label) {
  return `
    <figure class="briefing-layers" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<div style="--layer:${index}"><strong>${name}</strong><span>${detail}</span></div>`;
      }).join("")}
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
  numbers: briefingNumbers,
  comparison: briefingComparison,
  layers: briefingLayers,
};

function topic(state, title, lead, points, source, visual = "cards") {
  return { state, title, lead, points: points.split("|"), source, visual };
}

function buildDeck(id, eyebrow, topics) {
  const profile = deckProfiles[id];
  return topics.map((item, index) => {
    const number = String(index + 1).padStart(2, "0");
    const chapter = profile.segments
      .filter(([start]) => index >= start)
      .at(-1)?.[1] ?? profile.sections[0];
    if (index === 0) {
      return {
        eyebrow: `FDAI / ${eyebrow}`,
        title: item.title,
        lead: item.lead,
        layout: `briefing-cover deck-${id}`,
        content: `
          <figure class="briefing-cover-art">
            <img src="${deckAssets[id]}" alt="">
            <figcaption>${profile.label}</figcaption>
          </figure>
          <ol class="briefing-cover-index" aria-label="${item.title}의 주요 구성">
            ${profile.sections.map((section, sectionIndex) => `<li><small>0${sectionIndex + 1}</small><span>${section}</span></li>`).join("")}
          </ol>
          ${sourceLabel(item.source)}`,
      };
    }
    const builder = visualBuilders[item.visual] ?? cards;
    return {
      eyebrow: `${number} / ${statusLabel(item.state)}`,
      title: item.title,
      lead: item.lead,
      layout: `briefing-${item.visual} deck-${id}`,
      content: `
        <div class="briefing-status-row">
          <span class="manual-status" data-state="${item.state}" aria-label="설계 상태: ${statusLabel(item.state)}">${statusLabel(item.state)}</span>
          <span>${chapter} · ${number} / ${String(topics.length).padStart(2, "0")}</span>
        </div>
        ${builder(item.points, item.title)}
        ${sourceLabel(item.source)}`,
    };
  });
}

function ontologyPanels(points, label) {
  return `
    <section class="ontology-panel-grid" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<article><small>${String(index + 1).padStart(2, "0")}</small><strong>${name}</strong><span>${detail}</span></article>`;
      }).join("")}
    </section>`;
}

function ontologyNumbers(points, label) {
  return `
    <section class="ontology-number-grid" aria-label="${label}">
      ${points.map((point) => {
        const [value, detail] = splitPoint(point);
        return `<article><strong>${value}</strong><span>${detail}</span></article>`;
      }).join("")}
    </section>`;
}

function ontologyFlow(points, label) {
  return `
    <ol class="ontology-flow" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<li><small>${String(index + 1).padStart(2, "0")}</small><strong>${name}</strong><span>${detail}</span></li>`;
      }).join("")}
    </ol>`;
}

function ontologyStack(points, label) {
  return `
    <figure class="ontology-stack" aria-label="${label}">
      ${points.map((point, index) => {
        const [name, detail] = splitPoint(point);
        return `<div style="--stack-step:${index}"><strong>${name}</strong><span>${detail}</span></div>`;
      }).join("")}
    </figure>`;
}

function ontologyTable(points, label) {
  return `
    <table class="ontology-table" aria-label="${label}">
      <thead><tr><th scope="col">구분</th><th scope="col">기술적 의미와 경계</th></tr></thead>
      <tbody>${points.map((point) => {
        const [name, detail] = splitPoint(point);
        return `<tr><th scope="row">${name}</th><td>${detail}</td></tr>`;
      }).join("")}</tbody>
    </table>`;
}

function ontologyGraph(points, label) {
  const [center, ...satellites] = points;
  const [centerName, centerDetail] = splitPoint(center);
  return `
    <figure class="ontology-graph" aria-label="${label}">
      <div class="ontology-graph-center"><strong>${centerName}</strong><span>${centerDetail}</span></div>
      <div class="ontology-graph-orbit">
        ${satellites.map((point) => {
          const [name, detail] = splitPoint(point);
          return `<article><strong>${name}</strong><span>${detail}</span></article>`;
        }).join("")}
      </div>
    </figure>`;
}

const ontologyBuilders = {
  panels: ontologyPanels,
  numbers: ontologyNumbers,
  flow: ontologyFlow,
  stack: ontologyStack,
  table: ontologyTable,
  graph: ontologyGraph,
};

function ontologyTopic(state, chapter, title, lead, points, source, visual = "panels") {
  return { state, chapter, title, lead, points: points.split("|"), source, visual };
}

function buildOntologyDeck(topics) {
  return topics.map((item, index) => {
    const number = String(index + 1).padStart(2, "0");
    if (index === 0) {
      return {
        eyebrow: "FDAI / DATA & ONTOLOGY FOUNDATION",
        title: item.title,
        lead: item.lead,
        layout: "ontology-cover",
        content: `
          <figure class="ontology-cover-art" aria-label="LLM, RAG, 온톨로지와 FDAI의 연결 구조">
            <img src="${deckAssets["ontology-foundation"]}" alt="">
            <figcaption><strong>LLM</strong><i></i><strong>RAG</strong><i></i><strong>Ontology</strong><i></i><strong>FDAI</strong></figcaption>
          </figure>
          ${sourceLabel(item.source)}`,
      };
    }
    const builder = ontologyBuilders[item.visual] ?? ontologyPanels;
    return {
      eyebrow: `${number} / ${item.chapter}`,
      title: item.title,
      lead: item.lead,
      layout: `ontology-${item.visual}`,
      content: `
        <div class="ontology-status-row">
          <span class="manual-status" data-state="${item.state}" aria-label="설계 상태: ${statusLabel(item.state)}">${statusLabel(item.state)}</span>
          <span>${item.chapter}</span>
        </div>
        ${builder(item.points, item.title)}
        ${sourceLabel(item.source)}`,
    };
  });
}

const readinessMaturity = buildDeck("readiness-maturity", "준비도와 성숙도", [
  topic("ASSESS", "자동화보다 먼저 운영 준비도를 확인합니다", "전환 리더는 기술 구매가 아니라 의사결정 기반의 준비 상태를 평가합니다.", "대상:의사결정 유형 하나|기준선:현재 사람이 수행하는 업무|종료 조건:관찰 모드 진입 판단", docs.constitution),
  topic("CRITERIA", "현재 운영 목표가 측정 가능한지 확인합니다", "SLO, 복구, 비용, 변경 안전 목표가 없으면 결과를 검증할 수 없습니다.", "목표:단위, 기준선, 측정 구간|책임:최종 책임자와 보호 목표|근거:권위 있는 측정 출처", [docs.metrics, docs.ontology], "matrix"),
  topic("CRITERIA", "반복 사건과 예외를 분리합니다", "반복 가능한 결정은 규칙 후보이고 새롭거나 모호한 사건은 사람 검토 대상입니다.", "반복:동일 입력과 절차|예외:근거 부족 또는 충돌|경계:판단 보류 기준", docs.constitution, "tree"),
  topic("CRITERIA", "IaC가 변경의 기준선인지 점검합니다", "검토하고 재현할 수 있는 목표 상태가 파일럿 대상의 중요한 도입 조건입니다.", "현재 상태:권위 있는 관측|목표 상태:IaC 또는 GitOps|차이:추측이 아닌 근거", docs.deployment, "evidence"),
  topic("CRITERIA", "운영 데이터의 출처를 먼저 등록합니다", "누락과 접근 불가를 정상으로 해석하지 않도록 출처, 목적, 범위, 완전성을 명시합니다.", "출처:인증된 시스템과 생산자|목적:이 판단에 허용된 사용|범위:관측 대상과 제외 영역|완전성:보지 못한 영역", docs.constitution, "comparison"),
  topic("CRITERIA", "판단에 사용한 시간 기준을 함께 보존합니다", "변화 시점과 기록 시점만으로는 부족합니다. 사실의 유효 기간, 근거 마감 시점, 최신성 기준, 기준 시계를 함께 남깁니다.", "유효 시간:사실이 외부에서 참이었던 구간|사건 시각:변화가 발생한 시점|기록 시각:FDAI가 수집한 시점|기준 시점:판단이 사용한 관측 마감|최신성:근거가 허용되는 기간|신뢰 시계:재생에 사용한 시간 권위", [docs.constitution, docs.ontology], "comparison"),
  topic("CRITERIA", "서비스와 리소스 연결 상태를 평가합니다", "비즈니스 서비스(BusinessService), 워크로드(Workload), 리소스(Resource)의 연결은 운영 영향과 책임자를 찾는 최소 구조입니다.", "서비스:가치, 목표, 소유권|워크로드:배포와 운영 단위|리소스:관측된 실제 대상", docs.ontology, "flow"),
  topic("CRITERIA", "미분류 리소스를 숨기지 않습니다", "검토된 매핑이 없으면 unclassified-resource와 unknown_service로 남기고 추정으로 빈칸을 채우지 않습니다.", "분류됨:검토된 타입|미분류:원본 타입 보존|미매핑:서비스 추정 금지", docs.ontology, "matrix"),
  topic("CRITERIA", "책임과 실행 경로가 분리되어 있는지 확인합니다", "판단, 승인, 실행, 감사, 복구를 한 주체에 모으지 않습니다.", "Forseti:근거에 따른 판단|Var:사람 승인 기록 전달|Thor:적격 작업 전달|Saga와 Vidar:감사와 복구", docs.pantheon, "responsibility"),
  topic("CRITERIA", "사람 승인도 재현 가능한 근거로 관리합니다", "승인은 인증된 승인자, 정확한 ActionType과 대상, 중복 억제 키, 정족수, 만료 시각에 묶입니다. 침묵은 승인이 아닙니다.", "승인자:실행자와 분리된 인증 주체|범위:행동, 대상, 계획 리비전|정족수:위험에 필요한 승인 인원|만료:시간 초과 시 실행하지 않음", [docs.security, docs.standingAuthority], "evidence"),
  topic("CRITERIA", "실행 신원의 최소 권한을 검토합니다", "현재 Azure 구현은 Managed Identity 참조를 분리하고 알 수 없는 참조를 거부합니다. 작업별 허용 목록과 리소스 역할은 배포가 연결합니다.", "공통 구현:Managed Identity 참조 분리|배포 책임:리소스 범위와 행동 허용 목록|거부:알 수 없거나 누락된 신원 참조", docs.security, "cards"),
  topic("CRITERIA", "일곱 안전장치는 실행 전에 모두 증명합니다", "하나라도 빠지면 자율 상태 변경을 시작할 준비가 끝난 것이 아닙니다. 복구 계약과 감사 시작도 부수 효과 전에 준비합니다.", "중지 조건:실행 중 평가 가능한 중단 기준|검증된 복구:시험된 되돌리기 또는 전진 복구|영향 범위:최대 변경 대상 제한|가상 실행:현재 계획 리비전에 결합|대상 잠금:논리 대상의 동시 실행 차단|중복 억제:재전송을 변경 없음으로 처리|2단계 감사:의도 선기록과 결과 마감", [docs.constitution, docs.security], "comparison"),
  topic("CRITERIA", "독립적으로 효과를 관측할 수 있는지 확인합니다", "API 성공이나 메시지 브로커 수락만으로 운영 성공을 판단할 수 없습니다.", "예상 효과:실행 전에 지표와 방향 정의|관측자:실행기와 다른 책임 주체|출처:권위 있는 효과 데이터|관측 구간:종료와 충돌 처리 명시", docs.constitution, "evidence"),
  topic("CRITERIA", "관찰 모드 기준선은 같은 시나리오로 비교합니다", "사람 기준선과 FDAI 처리 결과를 같은 고정 시나리오, 기간, 표본, 리비전에서 비교해야 개선을 말할 수 있습니다.", "5:성공 지표 묶음|4:정확히 0이어야 하는 안전 지표|30+:각 기준선과 처리군의 최소 표본|동일:시나리오, 기간, 리비전", docs.metrics, "numbers"),
  topic("VALIDATED", "다섯 독립 서비스와 실행 권한 전환을 확인합니다", "보존된 배포 근거는 격리 실행기가 SD-08 전환 뒤 실제 변경 권한을 보유할 수 있는 유일한 서비스임을 검증했습니다. 모든 실행 경로의 종단 증적은 아직 진행 중입니다.", "Core:판단과 기존 전환 복구 경계|Operator API:제안과 조회|수집 API:문서 수신|수집 Worker:검사와 처리|격리 실행기:전환 뒤 유일한 변경 권한 후보", [docs.deployment, docs.security], "comparison"),
  topic("IMPLEMENTED", "프로덕션 계획의 보안·내구성 입력을 점검합니다", "사설 네트워크, 서명 이미지, 내구성, 모니터링, 비용 입력이 없으면 프로덕션 계획이 차단됩니다. 정확한 리비전의 운영 적용 증적은 별도 과제입니다.", "네트워크:사설 데이터 서비스|공급망:고정되고 서명된 이미지|내구성:HA, 백업, 복구 기준|운영:경고, 수신처, 예산", docs.hardening, "matrix"),
  topic("IN_PROGRESS", "A3-E 사전 조건부 승인은 아직 실행에 사용할 수 없습니다", "관련 계약과 저장 기능은 구현되어 있지만 판단·실행 경로에는 연결되지 않았습니다. 현재는 관찰 모드에서만 검증합니다.", "구현됨:평가기, 불변 리비전, PostgreSQL 저장소, 차단 장치|의도적 미연결:위험 게이트, 제어 루프, 실행기|열린 설계:효과가 끝날 때까지 유지되는 잠금 또는 임대|미확보:실운영 집단과 독립 승격 검토", [docs.standingAuthority, docs.security], "comparison"),
  topic("IN_PROGRESS", "워크플로 변경 적용 경로의 운영 증적이 부족합니다", "Operator API는 관찰 모드 제안만 받습니다. Core의 적용 경로는 존재하지만 소유자 승인, 모든 안전장치, 로컬·배포 동등성을 입증한 보존 증적이 남아 있습니다.", "현재:리비전에 묶인 관찰 모드 제안|구현:Core의 통제된 단계 실행|필요:소유자 승인과 종단 안전장치|필요:로컬·배포의 동일 권한 경로 증적", docs.operator, "evidence"),
  topic("NOT_STARTED", "자동 점진적 배포는 목표로 분리합니다", "환경 자동 승격, 트래픽 분할 카나리, SLO 기반 되돌리기, Console 블루/그린 배포는 아직 구현되지 않았습니다.", "현재:보호된 계획과 독립 서비스 배포|목표:동일 서명 산출물의 환경 승격|목표:카나리와 SLO 기반 되돌리기|목표:Console 블루/그린 배포", docs.deployment, "timeline"),
  topic("PROPOSAL", "준비도 등급은 권한이 아니라 다음 행동을 정합니다", "이 설명서의 등급은 도입 논의를 위한 제안 모델입니다. 낮은 등급은 보완 계획으로, 높은 등급은 관찰 모드 검토로 이어지며 실행 권한을 만들지 않습니다.", "기초:목표와 책임자 보완|관찰 가능:데이터와 시간 품질 보완|파일럿 가능:관찰 모드 진입 검토|승격 준비:별도 운영 근거 심사", docs.constitution, "tree"),
  topic("PROPOSAL", "격차 목록을 의사결정 유형에 묶습니다", "플랫폼 전체가 아니라 선택한 판단에 필요한 격차부터 닫습니다.", "필수:파일럿 차단 요소|후속:확장 전 강화|제외:가치와 무관한 범위", docs.execution, "cards"),
  topic("PROPOSAL", "준비도 워크숍의 책임자를 지정합니다", "전환 리더가 결과를 책임지고 운영, 데이터, 보안 담당자가 근거를 제공합니다.", "전환 리더:진행 또는 보류 결정|운영 책임자:현재 기준선|플랫폼과 보안:근거와 권한 경계", docs.pantheon, "responsibility"),
  topic("PROPOSAL", "30일 보완 계획에 검증 지점을 둡니다", "각 격차는 산출물 제출이 아니라 관측 가능한 종료 조건으로 닫습니다.", "1주:대상과 기준선|2주:데이터와 권한|4주:관찰 모드 준비도 검토", docs.operator, "timeline"),
  topic("DECISION", "파일럿 진입은 조건부 판정입니다", "모든 전제가 충족되어도 실행 승인이 아니라 관찰 모드 검토 자격만 얻습니다.", "진행:관찰 모드 비교 시작|보류:근거 보완|중단:현행 운영 유지", docs.security, "tree"),
  topic("NEXT", "다음 회의는 격차 소유권을 확정합니다", "의사결정 유형 하나, 책임자, 기준선, 차단 격차와 재검토 날짜를 남깁니다.", "선택:의사결정 유형|배정:격차 책임자|증적:완료를 입증할 자료|예약:재평가 시점", docs.constitution, "responsibility"),
]);

const artOfPossible = buildDeck("art-of-possible", "가능성 탐색", [
  topic("ENVISION", "통제된 자율 운영의 목표 모습을 살펴봅니다", "경영진은 무제한 자동화가 아니라 책임과 근거가 유지되는 운영 경험을 탐색합니다.", "경험:반복 판단은 검증된 규칙으로 처리|경계:고위험 작업은 사람 승인 유지|성과:독립 관측으로 완료|실패:보류, 변경 없음, 복구를 명시", docs.constitution),
  topic("TARGET", "운영 책임자는 중요한 예외에 집중합니다", "반복 가능한 판단은 검증된 규칙과 정책으로 처리하고, 사람은 근거 충돌, 목표 충돌, 승인 요청, 정책 변경을 검토합니다.", "자동화:검증된 반복 판단|사람 검토:근거와 목표 충돌|사람 승인:권한이 필요한 작업|정책 책임:위험과 위임 범위", docs.constitution, "comparison"),
  topic("TARGET", "장애 대응 전 과정을 하나의 추적으로 연결합니다", "각 단계는 고유 식별자를 유지하며, 공통 상관관계 ID(correlation_id)로 요청부터 복구 확인까지 연결됩니다.", "이벤트:개별 수신 단위|상관관계:작업 전체를 연결|프로세스와 인시던트:장기 작업과 문제 대응|승인과 효과:별도 권한·결과 기록", docs.operator, "flow"),
  topic("TARGET", "변경 회의는 그래프 영향과 근거를 먼저 봅니다", "아키텍처 검토 승인 자체는 리소스 변경 권한이 아닙니다. 승인된 변경도 일반 ActionType 경로에서 정책, 위험, 승인, 안전장치를 다시 통과합니다.", "변경:정확한 리비전|영향:관계 기반 범위|검토:조건과 책임 기록|실행:일반 ActionType 경로로 재진입", docs.operator, "layers"),
  topic("TARGET", "비용 절감은 신뢰성 목표를 지킨 뒤 비교합니다", "안전, 데이터 무결성, SLO, 변경 안전을 모두 충족한 선택지 안에서만 비용을 최적화합니다.", "먼저:상위 제약 위반 제거|그다음:적격 선택지 비교|마지막:실현된 절감 검증", docs.constitution, "tree"),
  topic("TARGET", "대화는 명령이 아니라 요청을 구조화하는 창구입니다", "대화 변환 에이전트 Bragi는 자연어 요청을 구조화하지만 판단하거나 승인하거나 실행하지 않습니다.", "사람:목표와 질문|Bragi:의도 형식화|에이전트:책임에 따라 처리", docs.pantheon, "responsibility"),
  topic("TARGET", "학습 결과는 바로 실행하지 않고 검토 후보로 남깁니다", "학습 에이전트 Norns가 규칙 후보를 만들면 Mimir가 독립적으로 검토합니다. 카탈로그 반영과 실행 권한 승격은 각각 별도 심사를 거칩니다.", "사례:결과와 근거 봉인|후보:실행 권한 없는 제안|카탈로그:검토된 PR 병합|실행 승격:별도 관찰 근거 심사", docs.pantheon, "timeline"),
  topic("TARGET", "운영 성공은 독립 관측으로 마감됩니다", "실행기와 다른 관측자가 권위 있는 효과 출처를 정해진 관측 구간에 확인합니다. 출처가 충돌하면 성공으로 평균 내지 않고 검토가 필요한 상태로 남깁니다.", "계획:기대 효과와 관측 구간 정의|실행:시도와 전달 증적|관측:독립 ObservedOutcome|충돌:명시적 충돌 상태와 권한 하향", [docs.constitution, docs.ontology], "evidence"),
  topic("BOUNDARY", "목표 운영 모습과 현재 구현을 혼합하지 않습니다", "현재 Azure 기반의 일부 경로는 검증됐지만 점진적 배포와 A3-E는 아직 목표입니다.", "현재:분리된 신원과 보호 배포|목표:자동 점진적 배포|미구현:A3-E 실행 권한", docs.security, "matrix"),
  topic("DECISION", "탐색의 결론은 범위가 좁고 측정 가능한 시나리오 하나입니다", "가치가 크고 경계가 선명한 운영 시나리오를 선택해 우선순위 평가로 넘깁니다.", "선택:의사결정 유형 하나|조건:기준선, 안전, 복구, 효과 측정|경계:현재와 목표 상태 구분|다음:가치 우선순위화", docs.execution, "tree"),
]);

const valuePrioritization = buildDeck("value-prioritization", "가치 우선순위", [
  topic("FRAME", "사용 사례가 아니라 의사결정 유형 하나를 고릅니다", "포트폴리오 책임자는 반복 빈도, 기대 효과, 근거, 위험이 분명한 판단부터 검토합니다.", "단위:의사결정 유형|범위:한 대상군|완료:독립 효과 검증", docs.constitution),
  topic("CRITERIA", "후보를 운영 문제와 연결합니다", "SRE 운영 모델 아래 복원력, 변경 안전성, 비용 거버넌스에서 실제 판단과 무조치 기준선을 함께 적습니다.", "문제:현재 손실 또는 위험|판단:선택 가능한 행동|기준선:아무것도 하지 않을 때|도메인:복원력, 변경 안전성, 비용", [docs.constitution, docs.ontology], "cards"),
  topic("CRITERIA", "다섯 가치 지표를 같은 구간에서 측정합니다", "기준선과 FDAI 처리군은 같은 시나리오, 기간, 표본 수, 리비전으로 비교합니다. 실제 운영에서 수집한 두 비교군의 근거는 아직 완성되지 않았습니다.", "사건·변경·최적화당 비용:업무 단위별 총비용|자동 해결 비율:사람 승인 없이 닫힌 비율|MTTR·변경 리드 타임:중앙값과 p90|사람 접점:이벤트 100건당 검토 횟수|안전 지표:정확히 0이어야 하는 위반", docs.metrics, "comparison"),
  topic("CRITERIA", "의사결정 빈도와 변동성을 분리합니다", "빈번해도 매번 맥락이 다르면 첫 파일럿으로 적합하지 않을 수 있습니다.", "빈도:각 비교군 30개 이상의 표본 가능성|변동성:입력 형태와 판단 절차의 안정성|예외율:사람 검토 예상 비율|기간:대표 계절성과 업무 주기", [docs.metrics, docs.execution], "matrix"),
  topic("CRITERIA", "근거 준비도는 가중치가 아니라 적격성 기준입니다", "인증된 출처, 최신성, 목적, 관측 범위가 부족하면 기대 가치가 높아도 점수화 단계로 넘기지 않습니다.", "출처:권위 있는 시스템과 인증된 생산자|시간:기준 시점과 최신성 정책 충족|목적:해당 판단에 허용된 근거|완전성:데이터가 없다고 판단할 수 있는 관측 범위", docs.constitution, "evidence"),
  topic("CRITERIA", "대상 정체성과 관계 품질을 평가합니다", "정확한 Resource와 의존 관계를 찾지 못하면 영향 범위를 계산할 수 없습니다.", "정체성:정확한 객체와 리비전|관계:depends_on과 contains의 방향|범위:깊이와 결과 수가 제한된 탐색|미분류:추정하지 않고 unknown 유지", docs.ontology, "flow"),
  topic("CRITERIA", "목표 충돌 가능성을 먼저 찾습니다", "비용 절감이 SLO나 복구 목표를 침해하면 점수로 상쇄할 수 없습니다.", "안전과 보안:항상 우선하는 적격성 조건|신뢰성:SLO, RTO, RPO 보호|변경 안전:검증과 복구 가능성|비용:적격 선택지 안에서만 비교", docs.constitution, "tree"),
  topic("CRITERIA", "ActionType 안전 계약의 존재를 봅니다", "중지 조건, 검증된 복구, 영향 범위, 가상 실행, 대상 잠금, 중복 억제, 2단계 감사가 모두 필요합니다.", "실행 전:중지, 복구, 영향 범위, 가상 실행|실행 중:대상 잠금과 중복 억제|실행 전후:감사 의도와 결과 마감", docs.security, "cards"),
  topic("CRITERIA", "네 가지 실행 경로를 후보마다 명시합니다", "모든 경로는 같은 위험, 승인, 복구, 감사 경계를 공유하며 경로 자체가 권한을 높이지 않습니다.", "pr_native:PR 기반 자동 또는 정책 병합|direct_api:공급자 API 직접 호출|pr_manual:사람이 병합하는 PR|tool_call:등록된 기능 범위의 도구 호출", docs.execution, "comparison"),
  topic("CRITERIA", "권한 요구를 가치 점수와 분리합니다", "높은 가치가 승인 또는 실행 권한을 만들지 않습니다.", "판단:위험 게이트(RiskGate)|승인:Var가 전달하는 사람 결정|실행:Thor와 비대화형 실행 신원|감사:Saga의 추가만 가능한 원장", docs.pantheon, "responsibility"),
  topic("CRITERIA", "환경과 영향 범위를 보수적으로 분류합니다", "알 수 없는 환경은 프로덕션으로 취급하고 영향 범위가 넓을수록 자율성 상한을 낮춥니다. 구독 전체의 자율 변경은 차단됩니다.", "환경:unknown은 prod로 처리|리소스:다른 축이 허용하면 자동 가능|리소스 그룹:사람 승인 상한|구독 전체:차단", docs.execution, "tree"),
  topic("CRITERIA", "T2 사용이 늘면 비용은 커지고 자동 실행 범위는 줄어듭니다", "모델 사용은 검증 비용과 응답 시간을 늘리고 사람 검토를 요구합니다. T2 결과는 관찰 모드로 제한됩니다.", "T0:규칙과 정책으로 자동 실행 가능|T1:검증된 유사 사례와 보수적 상한|T2:근거 기반 추론, 복수 모델, 검증기|권한:T2는 shadow_only 상한", docs.execution, "flow"),
  topic("CRITERIA", "사람 검토 부하를 별도 가치 항목으로 둡니다", "승인 요청만 늘리는 자동화는 운영 성과를 낮출 수 있습니다.", "검토율:사람 승인 또는 검토 비율|대기:승인까지 걸린 시간|재요청:근거 부족으로 되돌아온 비율|품질:불필요한 사람 검토", [docs.metrics, docs.pantheon], "matrix"),
  topic("CRITERIA", "복구 불가능성은 감점이 아니라 안전 기준입니다", "비가역 작업은 정족수가 필요한 사람 승인 경로이며 자동 실행 후보가 아닙니다. state_forward_only는 별도의 전진 복구 계약입니다.", "가역:시험된 되돌리기 또는 복원|전진 복구:state_forward_only 계약|비가역:사람 승인과 정족수|공통:실행 전 최선의 복구 계획", [docs.execution, docs.security], "tree"),
  topic("CRITERIA", "독립 관측 비용을 계산합니다", "효과 출처와 관측 구간이 없으면 절감이나 복구 성공을 입증할 수 없습니다.", "기대 효과:지표, 방향, 허용 범위|관측자:실행기와 다른 주체|출처:권위 있고 목적에 맞는 데이터|종료:관측 구간 마감과 충돌 처리", docs.ontology, "evidence"),
  topic("SCORE", "가치는 필수 제약을 통과한 뒤 점수화합니다", "헌법상 부적격인 후보를 높은 가중치로 되살리지 않습니다.", "1단계:필수 제약|2단계:근거 준비도|3단계:가치 순위", docs.constitution, "flow"),
  topic("PROPOSAL", "실행 가능성은 네 가지 통과 기준으로 봅니다", "이 설명서는 준비 상태를 기대감이 아니라 보유한 근거로 판정하는 제안형 포트폴리오 기준을 사용합니다.", "데이터:출처·시간·목적·완전성 증적|변경:IaC 또는 재현 가능한 전달 경로|안전:완전한 ActionType 계약|운영:책임자, 실행 절차, 독립 관측", [docs.deployment, docs.constitution], "matrix"),
  topic("SCORE", "위험은 최종 점수의 감점이 아닙니다", "정책 위반은 차단되고 구독 전체 범위는 자율 변경 대상에서 제외됩니다.", "차단:정책 위반 또는 구독 전체 변경|사람 승인:파괴적·비가역·데이터 영역 변경|관찰 모드:근거 또는 시스템 상태 부족|자동 실행:모든 독립 상한 통과", docs.execution, "tree"),
  topic("SCORE", "전략 적합성은 운영 도메인으로 확인합니다", "후보는 SRE 운영 모델과 초기 세 도메인 중 하나의 성과에 기여해야 합니다.", "Resilience:복구와 연속성|Change Safety:변경 위험|Cost Governance:검증된 효율", docs.constitution, "cards"),
  topic("PROPOSAL", "우선 후보는 좁고 반복 가능해야 합니다", "한 리소스 범위에서 기준선과 효과를 측정할 수 있는 후보를 권장합니다.", "좁은 범위:대상 잠금 가능|반복성:관찰 모드 표본 확보|효과:독립 측정 가능", docs.security, "cards"),
  topic("PROPOSAL", "두 번째 후보는 첫 학습을 재사용해야 합니다", "새 플랫폼을 추가하기보다 같은 근거와 권한 경계를 활용합니다.", "재사용:온톨로지 매핑|재사용:승인 경로|재사용:효과 관측자", docs.ontologyPlatform, "flow"),
  topic("HOLD", "고가치라도 근거가 없으면 보류합니다", "추정 절감, 합성 데이터, 미확인 성공은 프로덕션 준비도 근거가 아닙니다.", "합성:동작 시험 전용|누락:unknown 유지|보류:근거 보완 후 재평가", docs.constitution, "tree"),
  topic("DECISION", "포트폴리오 문서에 한 줄 판정을 남깁니다", "선정 이유와 제외 이유가 같은 기준으로 설명되어야 합니다.", "선정:가치와 준비 충족|보류:보완 가능|제외:경계 또는 가치 부적합", docs.execution, "matrix"),
  topic("PROPOSAL", "파일럿 투자는 관찰 모드 성과에 단계적으로 연결합니다", "이는 포트폴리오 운영을 위한 제안입니다. 초기 투자는 기준선, 비교, 안전 증적에 사용하고 적용 모드 전환은 별도 권한 결정으로 둡니다.", "1단계:기준선과 고정 시나리오|2단계:관찰 모드 품질과 안전|3단계:독립 승격 검토|중단:차단 지표 발생 시 추가 투자 보류", [docs.metrics, docs.security], "timeline"),
  topic("NEXT", "다음 산출물은 선택된 의사결정의 실행 헌장입니다", "실행 헌장은 한 리비전으로 관리합니다. 목표, 범위, 시작 조건, 기한을 먼저 정하고 기대 효과, 실패 대응, 보상, 완료 기준을 함께 기록합니다.", "목적:측정할 가치와 무조치 기준선|범위:정확한 대상과 하지 않을 일|통제:권한, 안전장치, 실패·보상|완료:독립 효과 관측과 책임자", [docs.constitution, docs.operator], "responsibility"),
]);

const targetArchitecture = buildDeck("target-architecture", "목표 아키텍처", [
  topic("TRACE", "현재 구현과 목표 아키텍처를 층별로 추적합니다", "아키텍트는 계약, 런타임, 권한, 데이터, 배포 근거를 같은 그림에서 구분합니다.", "현재:검증된 구성|목표:헌법상 요구|제안:후속 전달", docs.constitution),
  topic("TARGET", "최상위 계약은 FDAI Constitution입니다", "상세 설계와 구현은 안전, 권한, 근거, 효과 검증 원칙을 약화할 수 없습니다.", "목적:안전한 자율 운영|경계:형식화되고 승인된 처리|종료:재현 가능한 결과", docs.constitution, "cards"),
  topic("CURRENT", "Azure가 유일하게 구현된 공급자입니다", "Core 계약은 공급자 중립을 유지하지만 현재 배포 증적은 Azure에 한정됩니다.", "계약:공급자 어댑터|구현:Azure|미구현:Azure 외 공급자", docs.deployment, "matrix"),
  topic("VALIDATED", "런타임은 다섯 독립 서비스로 분리됩니다", "보존된 배포 근거는 서비스별 패키지, 상태, 신원과 SD-08 이후 격리 실행기의 변경 권한 경계를 검증했습니다.", "Core:판단, 오케스트레이션, 기존 전환 복구 경계|Operator API:조회와 리비전 기반 제안|문서 수집 API:파일 수신과 검증|문서 처리 Worker:검사, 추출, 이벤트 발행|격리 실행기:전환 뒤 유일한 변경 권한 후보", [docs.deployment, docs.security], "comparison"),
  topic("CURRENT", "Core는 UI 없는 이벤트 기반 계층입니다", "Console은 얇은 표시 계층이며 브라우저가 권한이나 운영 사실을 계산하지 않습니다.", "수신:이벤트 버스|Core:형식화된 제어 영역|Console:조회 화면과 범위가 제한된 요청", docs.constitution, "flow"),
  topic("CURRENT", "에이전트는 스키마로 검증된 게시·구독으로만 협업합니다", "에이전트 사이의 직접 호출, RPC, 구현 코드 공유는 권한이 있는 처리 경로로 사용하지 않습니다.", "발행자:객체별 단일 작성자|이벤트 버스:스키마와 계보 검증|구독자:독립적으로 스케줄되고 병렬 실행|전달:최소 1회와 중복 안전 재생", docs.pantheon, "responsibility"),
  topic("CURRENT", "판단과 실행 역할이 고정되어 있습니다", "Forseti, Var, Thor, Saga, Vidar의 분리는 설정으로 바꿀 수 없습니다.", "Forseti:판정|Var:사람 승인 기록 전달|Thor:적격 작업 전달과 실행 조정|Saga와 Vidar:감사와 복구", docs.pantheon, "responsibility"),
  topic("CURRENT", "운영 온톨로지는 공유 읽기 모델입니다", "그래프는 의미와 관계를 제공하지만 외부 상태나 실행 권한을 만들지 않습니다.", "선언:타입의 의미|투영:관측된 맥락|권한:그래프 밖에서 결정", docs.ontology, "matrix"),
  topic("CURRENT", "의사결정에 사용한 온톨로지 릴리스를 고정합니다", "의사결정 기록은 온톨로지 릴리스(OntologyRelease)의 버전과 다이제스트를 보존해 과거 의미가 달라지지 않게 합니다.", "타입 참조:이름과 버전|릴리스:카탈로그 다이제스트|호환성:명시적 판정", docs.ontologyPlatform, "evidence"),
  topic("CURRENT", "ObjectSet 조회는 목적과 범위가 제한됩니다", "자유 형식 그래프 질의 대신 목적, 기준 시점, 최신성, 결과 한도를 선언합니다. 현재 인스턴스 저장소에는 일반 과거 관측 API가 없어 as_of는 신뢰할 수 있는 현재 기준 시점 부근으로 제한됩니다.", "입력:타입 또는 인터페이스|경계:조건, 깊이, 결과 한도|시간:현재 기준 시점 중심의 제한|증적:완전성, 비식별 처리, 잘림 이유", docs.ontologyPlatform, "matrix"),
  topic("CURRENT", "T0 정책은 카탈로그 의미와 연결됩니다", "Rule, SignalType, Property, PolicyArtifact가 같은 결정론적 차단(deny) 경로를 참조합니다.", "Rule:의미 선언|PolicyArtifact:Rego 구현|증적:입력, 정책 버전, 결과 다이제스트|경계:정책이 온톨로지나 LLM에서 즉석 생성되지 않음", docs.ontology, "evidence"),
  topic("CURRENT", "위험 게이트는 독립 상한 중 가장 낮은 권한을 택합니다", "첫 일치 위험 표와 ActionType의 여섯 축은 서로 권한을 높일 수 없습니다.", "위험 표:정책, 파괴성, 비가역성, 데이터, 비용, 신뢰도|계층:T0, T1, T2 상한|ActionType:등록된 실행 상한|영향 범위:정적·실시간 범위|역할:현재 주체의 RBAC|환경:프로덕션 하향 조건", docs.execution, "layers"),
  topic("CURRENT", "실행 경로는 네 종류입니다", "네 경로는 PR 자동 병합(pr_native), 직접 API 호출(direct_api), 사람 병합 PR(pr_manual), 등록된 도구 호출(tool_call)입니다. 모든 경로에 같은 위험, 승인, 복구, 감사 기준을 적용합니다.", "pr_native:PR 기반 자동 또는 정책 병합|direct_api:공급자 API 직접 호출|pr_manual:사람이 병합하는 PR|tool_call:등록된 기능 범위의 도구 호출", docs.execution, "comparison"),
  topic("IN_PROGRESS", "모든 자율 상태 변경에는 같은 안전장치가 필요합니다", "PR 기반, 직접 API, 도구 호출 경로는 공통 사전 증적 계약을 사용합니다. 워크플로와 격리 실행기 경로의 동등한 종단 증적과 독립 효과 마감은 진행 중입니다.", "7:중지, 복구, 영향, 가상 실행, 잠금, 중복 억제, 2단계 감사|3:공통 계약을 쓰는 실행 경로|2:동등한 종단 증적이 열린 경로|1:독립 관측으로 닫아야 할 효과", [docs.security, docs.constitution], "numbers"),
  topic("VALIDATED", "Terraform 상태 소유권은 서비스별로 분리됩니다", "배포는 독립 백엔드 키와 서비스 간 상태 격리 증적으로 인프라 상태 소유권을 검증합니다.", "플랫폼 상태:공유 기반|서비스 상태:독립 백엔드 키|서비스 간 확인:다이제스트와 계보", docs.deployment, "matrix"),
  topic("CURRENT", "이벤트 전송은 Kafka 전송 계약을 따릅니다", "Azure에서는 두 Event Hubs 네임스페이스가 정해진 토픽 소유권을 나눕니다.", "주요 경로:수신, 사람 승인, 단계 이벤트|운영 경로:실행기와 자산 목록|프로토콜:Kafka 9093|전달:최소 1회와 구독자별 재시도", docs.deployment, "flow"),
  topic("IMPLEMENTED", "공급망과 배포 계획은 보호됩니다", "서명된 이미지, 다이제스트 검증, 계획 변경 제한, 마이그레이션 순서, 기동 점검이 배포 경계를 구성합니다.", "산출물:SBOM, 서명, 고정 다이제스트|계획:허용 범위 안의 변경|적용:스키마 마이그레이션 뒤 서비스 기동|증적:리비전과 결과 연결", docs.deployment, "timeline"),
  topic("IN_PROGRESS", "프로덕션 데이터 서비스는 사설 연결을 요구합니다", "프로덕션 계획 게이트는 PostgreSQL 사설망, 내구성, 모니터링, 예산 입력을 검사합니다. 모든 통제를 함께 입증한 정확한 리비전의 프로덕션 적용 증적은 남아 있습니다.", "구현됨:공용 접근 차단 계획 게이트|구현됨:HA, 백업, 경고, 예산 입력|진행 중:보호된 프로덕션 계획·적용 증적|진행 중:운영 복구 훈련과 보존 영수증", docs.hardening, "matrix"),
  topic("CURRENT", "Operator API는 제안 전용 경계를 유지합니다", "워크플로 시작은 관찰 모드 요청을 받지만 적용 모드 요청을 직접 전달하지 않습니다.", "요청자:형식화된 제안|Operator:RBAC와 영속 발신함|Core:권한 판단 경로", docs.operator, "flow"),
  topic("GAP", "Workflow 적용 경로의 환경 동등성은 진행 중입니다", "단계 실행기가 구현됐어도 로컬과 배포 환경을 잇는 전체 경로 근거는 아직 없습니다.", "현재:제어된 코드 경로|열림:런타임 근거|경계:Operator의 직접 적용 없음", docs.operator, "evidence"),
  topic("GAP", "실행 안전장치의 종단 검증은 일부 진행 중입니다", "PR-native, direct API, tool-call 계약은 있으나 Workflow와 격리 실행기의 동등한 근거가 남아 있습니다.", "검증됨:일부 실행 전 경로|진행 중:공통 종단 검증|필요:독립 효과 증적", docs.security, "matrix"),
  topic("TARGET", "효과 검증은 별도 관측자가 마감합니다", "실행기 명령 채널과 다른 권위 있는 출처가 관측 구간을 종료합니다.", "계획:기대 효과|실행:시도 증적|관측:독립 종료", docs.constitution, "evidence"),
  topic("NOT_STARTED", "점진적 배포는 동일 산출물의 승격으로 이어집니다", "같은 서명 이미지를 dev, staging, prod로 승격하고 트래픽 카나리, SLO 기반 되돌리기, Console 블루/그린을 결합하는 목표입니다.", "dev:통합과 공급망 근거|staging:관찰 모드와 트래픽 카나리|prod:범위가 제한된 승격|자동 중단:SLO 위반 시 이전 리비전 복구", docs.deployment, "timeline"),
  topic("PROPOSAL", "아키텍처 검토에는 상태 구분을 겹쳐 표시합니다", "각 계층에 현재 구현, 검증됨, 진행 중, 목표를 함께 표시해 설계 목표와 배포 근거를 혼합하지 않습니다.", "현재 구현:실행 가능한 코드와 계약|검증됨:보존된 정확한 리비전 증적|진행 중:일부 구현 또는 미완결 운영 근거|목표:헌법상 준수할 최종 경계", docs.constitution, "matrix"),
  topic("NEXT", "다음 검토에서 열린 권한 경로를 닫습니다", "워크플로 변경 적용, 격리 실행기 종단 검증, 프로덕션 적용 증적을 각각 독립 통과 기준으로 추적합니다.", "1단계:모든 실행 경로의 공통 안전장치|2단계:로컬·배포 런타임 동등성|3단계:보호된 프로덕션 계획·적용 증적|4단계:독립 효과 마감과 복구 훈련", docs.security, "timeline"),
]);

const ontologyFoundation = buildOntologyDeck([
  ontologyTopic("FOUNDATION", "FOUNDATION", "Data & Ontology Foundation", "LLM과 RAG의 확률적 탐색을 온톨로지의 형식화된 의미, FDAI의 결정론적 검증과 연결합니다.", "LLM:언어 후보 생성|RAG:근거 후보 검색|Ontology:공유 의미와 제약|FDAI:권한이 분리된 결정", [docs.constitution, docs.llmStrategy, docs.ontology]),
  ontologyTopic("PRINCIPLE", "PART 1 · LLM", "LLM은 다음 토큰의 확률을 계산합니다", "문맥에서 그럴듯한 다음 토큰을 반복 선택하지만, 사실성·최신성·권한을 스스로 보장하지 않습니다.", "입력 토큰:문장을 모델이 다루는 단위로 분해|문맥 표현:앞선 토큰의 관계를 계산|확률 분포:가능한 다음 토큰마다 점수 부여|생성:선택한 토큰을 다시 입력에 추가", docs.llmStrategy, "flow"),
  ontologyTopic("PRINCIPLE", "PART 1 · LLM", "Transformer는 문맥 관계를 병렬로 계산합니다", "임베딩, 위치 정보, self-attention, 순방향 신경망을 거쳐 각 토큰의 문맥 표현을 갱신합니다.", "Embedding:토큰을 연속 벡터로 변환|Position:순서 정보를 벡터에 더함|Attention:질의·키·값으로 관련도를 계산|Logits:어휘 전체의 다음 토큰 점수", docs.llmStrategy, "stack"),
  ontologyTopic("BOUNDARY", "PART 1 · LLM", "모델의 문맥과 운영 사실은 같은 것이 아닙니다", "학습된 패턴, 현재 대화, 권위 있는 운영 관측을 구분해야 답변의 출처와 유효 시간을 설명할 수 있습니다.", "모델 파라미터:학습 시점의 통계적 패턴이며 현재 사실이 아님|문맥 구간:요청과 첨부 근거를 일시적으로 보유|운영 관측:출처·기준 시점·완전성이 있는 외부 사실", [docs.llmStrategy, docs.dataGovernance], "table"),
  ontologyTopic("BOUNDARY", "PART 1 · LLM", "환각은 말투가 아니라 검증되지 않은 생성입니다", "근거가 없거나 충돌해도 문장을 완성하려는 생성 특성 때문에, 유창함을 신뢰도의 대리값으로 사용할 수 없습니다.", "근거 있음:인용과 주장 범위가 일치하는가|근거 충돌:차이를 숨기지 않고 보류하는가|근거 없음:추측 대신 unknown 또는 명확화를 내는가|권한 요청:언어가 실행 권한으로 오인되지 않는가", [docs.constitution, docs.llmStrategy], "panels"),
  ontologyTopic("TARGET", "PART 1 · FDAI ROUTING", "FDAI는 결정론을 먼저 사용합니다", "설계 목표 비율은 업무 분류를 위한 검증 대상이며 실제 처리율이나 성과 보장값이 아닙니다.", "70-80%:T0 규칙·정책·상태 기계 목표|15-20%:T1 유사도·경량 분류 목표|5-10%:T2 근거 기반 추론 목표", docs.llmStrategy, "numbers"),
  ontologyTopic("PRINCIPLE", "PART 1 · EMBEDDING", "임베딩은 의미 유사성을 좌표로 표현합니다", "텍스트나 구조화된 대상을 고정 길이 벡터로 바꾸면 가까운 후보를 빠르게 찾을 수 있습니다.", "벡터화:입력을 수치 좌표로 압축|거리 계산:코사인 유사도 등으로 가까운 후보 탐색|후보 회수:상위 k개를 후속 검증으로 전달|경계:가까움은 동일성·사실성·인과가 아님", [docs.llmStrategy, docs.behaviorKnowledge], "flow"),
  ontologyTopic("BOUNDARY", "PART 1 · EMBEDDING", "유사도 점수는 판결이 아닙니다", "벡터 검색은 후보 순서를 정할 뿐, 정책 적합성·권한·운영 효과를 결정하지 않습니다.", "유사함:표현 또는 문맥이 가깝다는 신호|동일함:정확한 식별자와 버전 검증이 필요|관련 있음:관계 유형과 방향 검증이 필요|행동 가능:정책·위험·승인·복구 검증이 추가로 필요", [docs.constitution, docs.semanticRetrieval], "table"),
  ontologyTopic("PRINCIPLE", "PART 1 · RAG", "RAG는 생성 전에 외부 근거를 회수합니다", "질문을 검색 표현으로 바꾸고, 허용된 자료에서 후보를 찾고, 순위를 조정해 생성 문맥으로 전달합니다.", "질문 정규화:의도와 검색어 분리|후보 집합:접근 가능한 자료만 선택|혼합 검색:어휘와 의미 점수를 결합|재순위:목적과 최신성 반영|생성·인용:주장과 근거 위치 연결", [docs.semanticRetrieval, docs.documentIngestion], "flow"),
  ontologyTopic("BOUNDARY", "PART 1 · SECURE RAG", "RAG는 권한과 프롬프트 주입을 먼저 차단합니다", "허용 후보를 먼저 만들고 검색 문서를 신뢰할 수 없는 데이터로 취급해야 누출과 간접 프롬프트 주입을 함께 막을 수 있습니다.", "1. 주체와 목적:역할·범위·사용 목적을 고정|2. 허용 후보:접근 가능한 문서 ID만 구성|3. 신뢰 경계:문서 속 지시를 명령이 아닌 데이터로 취급|4. 순위 계산:허용 후보 안에서 어휘·의미 점수 계산|5. 생성 문맥:인용 가능한 조각만 전달", [docs.llmStrategy, docs.dataGovernance, docs.documentIngestion], "stack"),
  ontologyTopic("CURRENT", "PART 1 · FDAI RETRIEVAL", "활성 규칙과 발견 문서를 다른 세대로 관리합니다", "검증된 실행 카탈로그와 탐색용 자료를 분리해, 발견 결과가 곧바로 판정 근거가 되는 것을 막습니다.", "62:활성 규칙 카탈로그|8,487:발견 문서 투영|1-20:한 번의 검색 결과 한도|5초:카탈로그 검색 함수 제한 시간", [docs.semanticRetrieval, "services/core-control-plane/src/fdai/core/ontology_platform/catalog_queries.py"], "numbers"),
  ontologyTopic("FOUNDATION", "PART 2 · ONTOLOGY", "온톨로지는 데이터에 공유 의미와 제약을 더합니다", "저장 형식이 아니라 객체·관계·속성·행동이 무엇을 뜻하는지 버전이 있는 선언으로 합의합니다.", "데이터:관측된 값과 기록|스키마:필드와 자료형의 구조|온톨로지:공유 의미·관계·제약|지식 그래프:온톨로지에 맞춰 연결된 인스턴스", [docs.ontology, docs.metamodel], "table"),
  ontologyTopic("GAP", "PART 2 · METAMODEL", "다섯 운영 렌즈와 다섯 선언 종류는 다릅니다", "Object, Relationship, State, Context, Action으로 질문을 읽습니다. Object, Link, Function, Action은 활성 릴리스에 있고 Interface는 계약 지원 뒤 카탈로그 통합이 남아 있습니다.", "Object:정체성과 속성을 Object로 선언|Link:Relationship의 양 끝점과 방향을 제한|State:독립 선언이 아니라 관측에서 계산|Context:목표·제약·근거의 런타임 묶음|Action:Function·Action은 활성, Interface는 통합 진행 중", [docs.ontology, docs.metamodel, docs.structuralModel], "panels"),
  ontologyTopic("CURRENT", "PART 2 · IDENTITY", "표시 이름이 바뀌어도 객체 정체성은 유지됩니다", "ObjectRef와 정확한 type_ref가 이름 변경, 공급자 표현 변경, 릴리스 변경에도 같은 대상을 추적하게 합니다.", "ObjectRef:안정된 객체 참조|type_ref:선언 이름과 버전|release_digest:해석에 사용한 릴리스|display_name:사람을 위한 변경 가능한 표기", [docs.ontology, docs.ontologyPlatform], "table"),
  ontologyTopic("CURRENT", "PART 2 · LINKS", "LinkType은 방향과 인과를 분리합니다", "저장된 간선의 방향, 허용된 탐색 방향, 인과 주장을 각각 검증하며 역방향을 자동으로 만들지 않습니다.", "저장 방향:source에서 target으로 기록된 의미|탐색 방향:질의가 따라갈 수 있는 방향|역방향:별도 선언과 근거가 있을 때만 사용|인과 의미:관계만으로 원인·결과를 주장하지 않음", [docs.structuralModel, docs.ontology], "flow"),
  ontologyTopic("BOUNDARY", "PART 2 · STATE", "State는 새 객체가 아니라 관측에서 계산된 값입니다", "상태를 새 객체처럼 무제한 추가하지 않고, 버전이 있는 의미 규칙과 시간에 묶인 관측으로 재현합니다.", "선언:속성 의미와 허용 범위|관측:값·출처·사건 시각|상태:기준 시점의 계산 결과|맥락:목표·제약·목적·근거의 묶음", [docs.metamodel, docs.dataGovernance], "stack"),
  ontologyTopic("CURRENT", "PART 2 · TIME", "운영 사실에는 하나 이상의 시간이 필요합니다", "언제 발생했는지, 언제 유효했는지, 언제 기록했는지를 분리해야 늦게 도착한 근거와 과거 재현을 다룰 수 있습니다.", "event_time:사건이 발생한 시각|effective_time:사실이 유효한 구간|recorded_time:시스템이 기록한 시각|fresh_until:판단에 재사용할 수 있는 상한", [docs.dataGovernance, docs.ontology], "table"),
  ontologyTopic("CURRENT", "PART 2 · PROVENANCE", "내용 요약값은 해석과 재현을 고정합니다", "계획, 후보, 조회 결과, 함수 입력·출력은 정규 JSON의 SHA-256 요약값으로 연결됩니다.", "sha256:64자리 16진수 내용 주소|canonical JSON:같은 의미를 같은 바이트로 직렬화|lineage:출처 ID·리비전·기준 시점 보존|replay:동일 입력과 릴리스 조합 확인", [docs.dataGovernance, docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/semantic_plans.py"], "panels"),
  ontologyTopic("CURRENT", "PART 2 · PROPERTY SEMANTICS", "속성 값은 자료형만 맞으면 끝나지 않습니다", "단위, 범위, 열거값, 시간대, 숫자 정밀도까지 검증해 공급자별 표현을 비교 가능한 정규값으로 만듭니다.", "64 KiB:정규 JSON 단일 값 상한|Decimal:작성된 십진수 의미 보존|RFC 3339:시간대가 있는 시간 경계|유한값:NaN과 무한대 거부", [docs.structuralModel, docs.ontology], "numbers"),
  ontologyTopic("CURRENT", "PART 2 · RELEASE", "OntologyRelease는 제자리에서 바꾸지 않습니다", "기존 기록의 의미가 뒤늦게 달라지지 않도록 새 선언 집합은 새 요약값과 호환성 결정을 가집니다.", "compatible:기존 소비자가 그대로 읽을 수 있음|migration_required:명시적 변환 뒤 사용|incompatible:자동 수락 금지|release envelope:서비스 간 정확한 릴리스 고정", [docs.ontologyPlatform, docs.structuralModel], "table"),
  ontologyTopic("CURRENT", "PART 2 · UNKNOWN", "매핑되지 않은 사실은 알 수 없음으로 남깁니다", "서비스 관계나 중립 타입을 추정해 채우지 않고 공급자 근거, 누락 이유, 검토 제안을 분리합니다.", "서비스 관계:unknown_service - 연결이 입증되지 않음|중립 타입:unclassified-resource - 매핑이 검토되지 않음|사용 불가:unavailable - 권위 있는 출처를 읽지 못함|변경 제안:proposal - 검토 전 후보이며 사실이 아님", [docs.ontology, docs.dataGovernance], "panels"),
  ontologyTopic("CURRENT", "PART 2 · INTENT", "목표와 제약도 형식화된 운영 객체입니다", "SLO, 복구, 비용, 통제, 아키텍처 조건을 단위·범위·소유자·유효 구간과 함께 연결합니다.", "ServiceObjective:SLI·측정 구간·목표값|RecoveryObjective:RTO·RPO와 적용 범위|CostObjective:통화·기간·예산 경계|ControlObjective:정책과 통제가 달성해야 할 목표|ArchitectureConstraint:검토된 조건과 적용 대상", [docs.ontology, docs.actionOntology], "table"),
  ontologyTopic("CURRENT", "PART 2 · EFFECTS", "행동과 효과는 하나의 성공 상태가 아닙니다", "선택, 실행 시도, 독립 관측을 분리해 API 성공을 운영 성과로 오인하지 않습니다.", "DecisionCase:목표·제약·무조치 기준선|ActionOption:비교 가능한 대응 후보|ActionRun:실행 시도와 증적|ExpectedEffect:사전 지표 범위|ObservedOutcome:독립 관측한 실제 효과", [docs.operationalLearning, docs.constitution, "services/core-control-plane/src/fdai/core/decision_case/models.py"], "flow"),
  ontologyTopic("CURRENT", "PART 3 · FDAI PLATFORM", "FDAI는 의미 계층과 결정 계층을 분리합니다", "공급자 사실을 투영하고, 릴리스에 고정된 의미로 조회한 뒤, 별도 정책·위험·승인 경로에서 행동을 결정합니다.", "Provider evidence:권위 있는 외부 관측|Projection:중립 객체와 관계|Ontology release:버전이 있는 선언|Secured query:역할·목적·완전성 증적|Decision path:규칙·위험·승인·실행", [docs.ontologyPlatform, docs.constitution], "stack"),
  ontologyTopic("CURRENT", "PART 3 · CATALOG SCALE", "원시 공급자 타입을 그대로 온톨로지로 만들지 않습니다", "Azure 타입 전부를 복제하지 않고 운영 질문에 필요한 중립 분류와 검토된 매핑만 정식 카탈로그로 승격합니다.", "3,405:발견된 Azure 원시 리소스 타입|11:정규 상위 클래스|80:검토된 클래스 멤버십|80:중립 ResourceType", [docs.structuralModel, docs.ontology], "numbers"),
  ontologyTopic("CURRENT", "PART 3 · RULE SEMANTICS", "규칙이 읽는 속성과 의미 선언을 대조합니다", "활성 규칙의 Property 참조를 카탈로그와 맞추고, 의미 검토가 끝나지 않은 속성은 완료로 간주하지 않습니다.", "62 / 62:활성 규칙 Property 참조 연결|45:검토된 속성 의미|Rule:의미와 입력 계약|PolicyArtifact:작성된 Rego와 AST 요약값", [docs.structuralModel, docs.semanticRetrieval], "numbers"),
  ontologyTopic("CURRENT", "PART 3 · KNOWLEDGE PROJECTIONS", "외부 지식은 실행 권한이 없는 읽기 전용 투영입니다", "프레임워크와 진단 자료는 탐색과 검증을 돕지만 승인, 정책 판정, 실행 권한을 만들지 않습니다.", "456:WARA·APRL FrameworkControl|61:진단 메커니즘|427:독립 검증 증적|참고 전용:승인·위험 판정·실행 권한 없음", [docs.ontology, docs.semanticRetrieval], "numbers"),
  ontologyTopic("CURRENT", "PART 3 · OBJECTSET", "ObjectSet은 자유 형식 그래프 질의가 아닙니다", "타입, 조건식, 명명된 관계, 결과·후보·탐색 한도를 요청에 명시해 비용과 의미 범위를 함께 제한합니다.", "32:질의당 최대 조건식|1,000:IN 값·후보·루트 ID 상한|64:탐색할 LinkType 상한|1-5:관계 탐색 깊이|100-1,000:결과 한도", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/models.py"], "numbers"),
  ontologyTopic("CURRENT", "PART 3 · COMPLETENESS", "조회 한도와 빈 결과를 함께 해석합니다", "결과가 없다는 사실은 범위를 완전히 확인했다는 증적이 있을 때만 부재 근거가 됩니다.", "RESULT_LIMIT:요청한 결과 수에서 중단|CANDIDATE_LIMIT:필터 전 후보 일부만 확인|TRAVERSAL_LIMIT:관계 탐색 범위를 모두 확인하지 못함|complete empty:완전성이 입증된 빈 결과만 부재 근거", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/object_sets.py"], "table"),
  ontologyTopic("CURRENT", "PART 3 · QUERY EXECUTION", "질의 계획은 실행 가능한 노드 묶음별로 진행됩니다", "노드 의존성을 DAG로 고정하고 같은 시점에 준비된 노드만 병렬 실행해 시간·동시성·실패 전파를 통제합니다.", "8:동시 실행 노드 상한|30초:노드별 제한 시간|32:계획 DAG 노드 상한|17:지원하는 QueryNodeKind|묶음 실행:실패 의존성은 명시적 상태로 전파", [docs.ontologyPlatform, "packages/service-contracts/src/fdai_service_contracts/ontology_query.py"], "numbers"),
  ontologyTopic("CURRENT", "PART 3 · SECURED QUERY", "보호된 조회 증적은 권한과 손실을 드러냅니다", "결과와 함께 역할 범위, 사용 목적, 비식별 처리, 관측 기준 시점, 투영 요약값을 반환합니다.", "시간 모드:현재는 current_state_only만 지원|0-5초:허용하는 기준 시점 오차|비식별 처리:제거된 객체·연결·정체성 수|권한 없음:execution_authority는 false", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/query_gateway.py"], "panels"),
  ontologyTopic("CURRENT", "PART 3 · SEMANTIC PLAN", "의미 해석은 세 후보 출처에서 시작합니다", "어휘 일치, 임베딩, 모델은 모두 비권위 후보를 만들며, 정확한 카탈로그 근거가 없으면 미해결 용어를 보존합니다.", "LEXICAL:정확한 용어와 별칭 일치|EMBEDDING:벡터 유사도 기반 후보|MODEL:LLM이 제안한 구조화 후보|SHA-256:candidate_digest로 입력·릴리스·점수 고정", [docs.ontologyAgentLoop, "services/core-control-plane/src/fdai/core/ontology_platform/semantic_plans.py"], "panels"),
  ontologyTopic("CURRENT", "PART 3 · VERIFICATION", "검증은 신뢰도를 높이지만 결정 경로를 대체하지 않습니다", "후보는 명시된 검증 근거를 얻어야 계획이 되며, 이후에도 일반 판단·정책·승인 경로를 거칩니다.", "EXACT_CATALOG:활성 릴리스의 정확한 선언|PROMOTED_SURFACE:검토 후 승격된 의미 표면|OPERATOR_CONFIRMATION:인증된 사람의 확인|VerifiedSemanticPlan:의미가 고정된 입력이며 실행 명령이 아님", [docs.ontologyAgentLoop, docs.constitution], "table"),
  ontologyTopic("CURRENT", "PART 3 · FUNCTIONS", "온톨로지 함수는 호출 맥락과 릴리스에 고정됩니다", "함수 레지스트리는 정확한 릴리스, 호출 에이전트, 역할 상한, 목적, 근거 참조를 증적에 묶습니다.", "16:호출당 고유 목적 상한|64:근거 참조 상한|7:서버가 부여하는 EvidenceAuthority 종류|0:자격 증명과 네트워크를 허용하지 않는 카탈로그 검색 함수", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/functions.py"], "numbers"),
  ontologyTopic("GAP", "PART 3 · BEHAVIOR KNOWLEDGE", "행동 지식 검색은 핵심 경로 복원이 남아 있습니다", "384차원 혼합 검색을 수행하는 메모리 내 색인은 구현됐지만, 13개 기준 시드와 서버 답변 경로, 영속 저장, 운영 근거는 아직 없습니다.", "384차원:구현된 메모리 내 의미 검색|13개:복원되지 않은 기준 시드|진행 중:구조화 계약과 출처 최신성 검사|미착수:서버 답변·영속 저장·운영 근거", docs.behaviorKnowledge, "numbers"),
  ontologyTopic("CURRENT", "PART 3 · DOCUMENT DISTILLATION", "문서에서 추출한 의미는 변경 제안으로 끝납니다", "모델 출력은 OntologyChangeProposal이며 활성 릴리스나 인스턴스 그래프를 직접 수정하지 않습니다.", "수집:출처·리비전·접근 범위 보존|추출:후보 객체·관계·속성 의미|제안:OntologyChangeProposal 생성|검토:충돌·중복·근거·호환성 확인|승격:별도 릴리스 절차", [docs.documentIngestion, docs.ontologyDistillation], "flow"),
  ontologyTopic("CURRENT", "PART 4 · RECONCILIATION", "변경 효과는 비동기 조정 기록으로 마감합니다", "기대 효과와 권위 있는 후속 관측을 대조합니다. 종료 상태는 MATCHED, MISMATCHED, TIMED_OUT, UNSCORABLE입니다.", "8:효과당 조정 시도 상한|64:상태 저장소 CAS 시도 상한|16 MiB:집계 기록 상한|30초:발신함 전달 임대", [docs.ontologyPlatform, "services/core-control-plane/src/fdai/core/ontology_platform/reconciliation_state_store.py"], "numbers"),
  ontologyTopic("GAP", "PART 4 · CURRENT GAPS", "현재 구현의 빈틈을 목표 아키텍처와 분리합니다", "문서에 선언이 있거나 일부 코드가 존재해도 종단 투영·운영 근거가 없으면 완료로 표시하지 않습니다.", "과거 시점 조회:SecuredObjectSetQueryGateway는 current_state_only|ControlObjective:일부 선언은 있으나 런타임 투영·동등성 실행이 남음|인과 분석:관계와 상관만으로 원인을 확정하지 않음|행동 실행:온톨로지 플랫폼 밖의 정책·승인·격리 실행 경로가 책임", [docs.ontologyPlatform, docs.structuralModel], "table"),
  ontologyTopic("TARGET", "PART 4 · OPERATING MODEL", "품질 목표는 타입 수가 아니라 신뢰 가능한 답변입니다", "플랫폼 팀은 릴리스 정확성, 투영 최신성, 조회 완전성, 접근 통제, 재현 가능한 마이그레이션을 함께 운영해야 합니다.", "의미 관리:선언·호환성·릴리스 요약값|데이터 관리:출처·최신성·완전성·비식별 처리|검색 관리:세대·평가 집합·재현율·오탐|운영 관리:지연·잘림·충돌·조정 실패|거버넌스:승격·폐기·책임자·증적", [docs.dataGovernance, docs.ontologyPlatform], "panels"),
  ontologyTopic("NEXT", "PART 4 · DELIVERY SEQUENCE", "확장은 읽기 품질에서 행동 검증 순서로 진행합니다", "새 모델이나 타입을 먼저 늘리지 않고, 권위 있는 투영과 측정 가능한 검색 품질을 확보한 뒤 범위가 제한된 행동 제안으로 확장합니다.", "1. 관측 기반선:정체성·시간·출처·완전성|2. 의미 릴리스:검토된 타입·관계·속성|3. 보안 검색:허용 후보·혼합 순위·평가 집합|4. 의미 계획:후보·검증 근거·미해결 용어|5. 행동 제안:정책·위험·승인·복구·독립 효과 검증", [docs.constitution, docs.ontologyPlatform, docs.actionOntology], "flow"),
]);

const responsibleAiSecurity = buildDeck("responsible-ai-security", "책임 있는 AI와 보안", [
  topic("INSPECT", "자율성의 보안 경계는 신원과 근거에서 시작합니다", "보안과 책임 있는 AI 리더는 모델 기능보다 권한 분리와 실패 시 차단 조건을 먼저 검토합니다.", "신원:누가 행동할 수 있는가|권한:무엇을 실행할 수 있는가|근거:왜 실행했고 결과는 무엇인가", docs.security),
  topic("CURRENT", "사람 승인과 실행 신원은 다릅니다", "사람은 실행기 신원을 보유하지 않으며 한 주체가 승인과 실행을 겸하지 않습니다.", "사람:인증된 승인자|실행기:비대화형 작업 신원|원칙:자기 승인 금지", docs.security, "responsibility"),
  topic("VALIDATED", "Azure 실행자는 Managed Identity 경계를 사용합니다", "공통 구현은 대상(audience)이 지정된 단기 OIDC 토큰과 사용자 할당 Managed Identity 참조를 분리합니다. 작업별 허용 목록과 리소스 역할은 배포가 제공합니다.", "공통 계약:단기 OIDC 토큰만 요청|신원:사용자 할당 Managed Identity 참조|배포 책임:행동 허용 목록과 역할|금지:사람 자격 증명과 장기 비밀값", docs.security, "flow"),
  topic("CURRENT", "도메인별 실행 신원을 분리합니다", "Change Safety, Resilience, FinOps의 신원 참조는 다른 도메인 권한으로 대체되지 않습니다.", "identity/change:변경 배포|identity/resilience:복구 범위|identity/finops:비용 작업", docs.security, "matrix"),
  topic("CURRENT", "알 수 없는 신원 참조는 거부됩니다", "통합 실행기 신원으로 자동 대체하지 않으므로 잘못된 연결이 권한 확대로 이어지지 않습니다.", "확인됨:정확한 신원과 도메인 연결|알 수 없음:명시적 거부|누락:작업 보류|교차 도메인:권한 대체 금지", docs.security, "tree"),
  topic("DEPLOYMENT", "작업 권한은 배포에서 최소 범위로 연결합니다", "공통 저장소는 신원 경계를 제공하고, 각 배포가 리소스 범위의 역할과 행동 허용 목록을 운영합니다.", "공통 구현:신원 분리와 알 수 없는 참조 거부|배포 책임:리소스 범위와 허용 목록|운영:실효 권한 관측과 재인증|후속:측정 기반 사용자 지정 역할", docs.security, "matrix"),
  topic("IN_PROGRESS", "권한 부족은 독립 요청으로 처리합니다", "원래 작업의 승인이 실행기 접근 권한을 만들지 않습니다. AccessGrantRequest 수명 주기는 구현됐지만 배포 정책, 신원 매핑, 실효 권한 탐침이 연결되기 전에는 비활성 상태입니다.", "원래 작업:현재 권한으로 보류|권한 요청:정확한 계획과 리비전에 한정|배포 연결:정책, 신원, 매핑, 탐침|재검사:실행 직전 최신 실효 권한", docs.security, "evidence"),
  topic("CURRENT", "비밀값은 런타임에 주입됩니다", "애플리케이션은 환경 변수나 탑재 경로를 읽고 Core에서 클라우드 비밀값 SDK를 호출하지 않습니다.", "출처:Key Vault 참조|런타임:환경 변수 연결|실패:기동 단계에서 차단", docs.security, "flow"),
  topic("IN_PROGRESS", "모델 입력은 모두 검증 대상 데이터로 다룹니다", "외부 문서와 도구 출력은 실행 지시가 아닙니다. 민감 정보를 충분히 제거하지 못하면 모델로 보내지 않으며, 배포 전에는 데이터 지역과 보존 조건을 확인합니다.", "데이터 최소화:원문 대신 필요한 필드와 포인터|프롬프트 주입:외부 콘텐츠의 지시를 실행 명령으로 해석하지 않음|공급자 경계:지역, 보존, 학습 사용 약관 확인|실패:전송하지 않고 사람 검토", [docs.dataGovernance, docs.security], "comparison"),
  topic("CURRENT", "네트워크 수신과 송신을 제한합니다", "실행기와 Core에는 공용 수신 지점이 없고 송신은 필요한 제어 영역과 모델 엔드포인트로 제한합니다.", "수신:이벤트 버스만 허용|관리:사설망|송신:기본 차단 허용 목록", docs.security, "matrix"),
  topic("IMPLEMENTED", "공급망은 이미지 다이제스트와 증명으로 고정합니다", "검증된 이미지만 실행하고 내용이 바뀔 수 있는 최신 태그를 사용하지 않습니다.", "의존성:고정된 잠금 파일|산출물:SBOM, 서명 이미지, 공급망 증명|런타임:고정된 이미지 다이제스트|계획:허용된 변경만 적용", docs.security, "evidence"),
  topic("IN_PROGRESS", "일곱 안전장치가 자율 상태 변경 자격을 정합니다", "PR 기반, 직접 API, 도구 호출은 공통 사전 증적 계약을 사용합니다. 워크플로와 격리 실행기 경로의 동등한 종단 증적은 진행 중입니다.", "중지 조건:기계 평가 가능한 중단 기준|검증된 복구:되돌리기 또는 전진 복구|영향 범위:최대 대상 수 제한|가상 실행:현재 계획 리비전에 결합|대상 잠금:동시 효과 차단|중복 억제:재전송을 변경 없음으로 처리|2단계 감사:의도와 결과를 분리 기록", docs.security, "comparison"),
  topic("CURRENT", "중지 조건은 기계가 평가할 수 있어야 합니다", "중단 기준은 사람의 기억이 아니라 실행 중과 적용 후에도 확인할 수 있는 조건입니다.", "선언:ActionType stop_conditions|관측:실행 중 지속 확인|위반:효과 중단과 복구 전환|결과:이유와 시각을 감사에 기록", docs.security, "evidence"),
  topic("CURRENT", "복구 방식은 실행 전에 계약으로 정합니다", "각 작업은 되돌리기, 상태 복원 또는 안전한 전진 복구 방식을 선언합니다. 비가역 작업에는 여러 사람의 승인과 가능한 최선의 복구 계획이 필요합니다.", "pr_revert·scripted:코드 또는 스크립트 기반 되돌리기|snapshot_restore·pitr:상태 복원|state_forward_only:이전 상태 대신 안전한 다음 상태로 전진|irreversible:별도 비가역 표시와 사람 정족수", docs.security, "matrix"),
  topic("CURRENT", "영향 범위는 그래프로 계산할 수 있습니다", "contains와 역방향 depends_on을 제한된 깊이로 탐색해 실제 영향 대상을 구합니다.", "대상:정확한 리소스와 리비전|탐색:깊이와 결과 수가 제한된 그래프|상태:실시간 부하와 충돌|통과 기준:최대 영향 리소스 수", docs.security, "flow"),
  topic("CURRENT", "가상 실행 근거는 현재 계획 리비전에 묶입니다", "다른 계획이나 오래된 상태에서 만든 예측 결과를 재사용하지 않습니다.", "입력:계획 다이제스트와 대상 리비전|예측:기대 변경과 보호 목표 영향|실패:불완전하거나 오래된 근거는 보류|통과:성공한 사전 검증 증적", docs.security, "evidence"),
  topic("CURRENT", "중복 억제와 대상 잠금이 이중 실행을 막습니다", "재전송과 동시 실행이 같은 리소스에 두 번 적용되지 않도록 합니다.", "키:안정된 idempotency 식별자|잠금:논리 대상과 소유자 울타리|재시작:실행 불명 상태를 보수적으로 유지|재생:중복은 변경 없음", docs.security, "flow"),
  topic("CURRENT", "감사는 의도부터 결과까지 이어집니다", "부수 효과 전에 추가만 가능한 감사 의도를 저장하고 실행 증적, 독립 효과, 복구 또는 최종 결과로 마감합니다.", "실행 전:감사 의도와 계획|실행 중:시도와 공급자 증적|관측:독립 효과 상태|종료:성공, 실패, 복구, 판단 보류", docs.security, "timeline"),
  topic("CURRENT", "위험 게이트는 권한을 높이지 않습니다", "첫 일치 위험 표와 ActionType의 계층, 영향 범위, 역할, 환경 상한 중 가장 낮은 결과를 선택합니다.", "자동 실행:enforce_auto|사람 승인:enforce_hil|관찰 모드:shadow_only|차단:deny", docs.execution, "matrix"),
  topic("IMPLEMENTED", "긴급 중지는 실행 신원 없이 작동합니다", "활성화되면 모든 변경 실행을 관찰 모드 상한으로 낮춥니다. 승인 요청을 볼 수는 있어도 중지가 해제되기 전에는 어떤 변경도 실행되지 않으며, 상태 읽기 실패도 활성 상태로 취급합니다.", "작동:인증된 운영자와 리비전 검사|권한:실행기 신원 없이 변경|효과:모든 변경을 shadow_only로 제한|실패:상태를 읽지 못해도 차단 유지", docs.security, "tree"),
  topic("CURRENT", "새 기능은 관찰 모드에서 시작합니다", "같은 시나리오와 리비전에서 충분한 표본, 계약 적합성, 모든 안전 지표를 검증한 작업만 별도 승격 검토를 받습니다.", "관찰:상태 변경 없음|측정:성공 지표와 안전 지표|차단:잘못된 대상, 무권한 실행, 정책 유출, 미검증 성공은 0|승격:독립 검토와 명시적 등록부 변경", [docs.metrics, docs.security], "timeline"),
  topic("IN_PROGRESS", "A3-E는 아직 실제 실행 권한으로 사용할 수 없습니다", "평가기와 저장소는 관찰 모드로 구현되어 있지만 판단·실행 경로에는 연결되지 않았습니다. 실제 적용 전에는 실행 전 기간의 권한 보장과 운영 관찰 근거가 필요합니다.", "구현:평가기, 저장소, 스냅샷, 차단 장치|미연결:위험 게이트와 실행기|열린 설계:효과 전 기간 잠금 또는 임대|열린 근거:실운영 관찰 집단과 승격 심사", [docs.standingAuthority, docs.security], "comparison"),
  topic("IN_PROGRESS", "프로덕션 개인정보 보호 통과 기준은 진행 중입니다", "공통 데이터 최소화, 비식별 처리, 보존 계약은 구현됐습니다. 배포별 데이터 책임자, 보존 일정, 모델 공급자 약관, 개인정보 영향 평가와 운영 증적은 남아 있습니다.", "구현됨:모델 전 최소화 증적과 주요 비식별 처리|배포 책임:데이터·개인정보 책임자와 보존 값|승인 필요:공급자 약관, 지역, 영향 평가|운영 증적:삭제, 법적 보존, 접근 검토, 감사 앵커", docs.dataGovernance, "evidence"),
  topic("TARGET", "책임 있는 AI 검토는 모델보다 전체 판단 사슬을 봅니다", "형식화된 의도, 근거 확인, 검증기, 위험, 승인, 효과 검증이 함께 닫혀야 합니다.", "입력:범위 제한과 비식별 처리|판단:결정론적 실행 자격|결과:독립 관측", docs.constitution, "flow"),
  topic("NEXT", "다음 보안 회의에서 열린 통과 기준의 책임자를 정합니다", "A3-E, 개인정보 보호, 공통 실행 종단 검증, 실운영 훈련을 서로 독립된 승인 항목으로 유지합니다.", "보안:A3-E와 신원 훈련|개인정보:프로덕션 통과 기준|런타임:안전장치 종단 검증", docs.security, "responsibility"),
]);

const pilotProduction = buildDeck("pilot-production", "파일럿에서 프로덕션까지", [
  topic("PLAYBOOK", "한 의사결정 유형을 관찰 모드에서 적용 모드까지 이동합니다", "배포 책임자는 기능 수가 아니라 측정 가능한 통과 기준과 되돌릴 수 있는 범위를 관리합니다.", "시작:범위가 명확한 실행 헌장|학습:관찰 모드 근거|진전:독립 승격 심사", docs.security),
  topic("PHASE 0", "파일럿 실행 헌장을 한 장으로 고정합니다", "대상, 목표, 기준선, 책임자, 권한 상한, 효과 출처를 시작 전에 합의합니다.", "대상:정확한 리소스 집합|가치:기준 지표|안전:ActionType 계약", docs.operator, "cards"),
  topic("PHASE 0", "현재 사람 중심 운영을 기준선으로 측정합니다", "현재 운영과 FDAI 처리 결과를 같은 시나리오, 기간, 표본, 리비전에서 비교합니다. 각 비교군에는 최소 30개 표본과 신뢰 구간을 사용합니다.", "비용:사건·변경·최적화 단위별 비용|자율성:자동 해결 비율|속도:MTTR과 변경 리드 타임의 중앙값·p90|부하:이벤트 100건당 사람 접점|안전:정확히 0이어야 하는 네 가지 위반", docs.metrics, "comparison"),
  topic("PHASE 0", "권위 있는 근거 출처를 등록합니다", "합성 데이터는 동작 시험에 쓸 수 있지만 실운영 준비도를 증명하지 못합니다.", "인벤토리:대상 ID|텔레메트리:효과 지표|감사:판단 계보", docs.constitution, "evidence"),
  topic("PHASE 0", "서비스 관계와 운영 목표를 연결합니다", "Resource만 고르면 비즈니스 영향과 상위 제약을 판단할 수 없습니다.", "Resource:runs_on 대상|서비스:책임자와 중요도|목표:SLO, 복구, 비용", docs.ontology, "flow"),
  topic("PHASE 0", "ActionType의 안전 계약을 검토합니다", "실행 코드보다 중지 조건, 검증된 복구, 영향 범위, 가상 실행, 대상 잠금, 중복 억제, 2단계 감사를 먼저 봅니다.", "사전 조건:중지, 복구, 범위, 가상 실행|실행:대상 잠금과 중복 억제|감사:의도 선기록과 결과 마감", docs.security, "tree"),
  topic("PHASE 0", "실행자와 승인자를 분리합니다", "파일럿 환경에서도 사람 신원과 작업 신원을 합치지 않습니다.", "승인자:인증된 사람|실행기:비대화형 신원|감사자:독립된 근거", docs.security, "responsibility"),
  topic("GATE 0", "준비가 부족하면 현행 운영을 유지합니다", "근거, 책임자, 측정 기준선, 복구 경로가 준비된 뒤 관찰 모드를 시작합니다. IaC 또는 GitOps는 재현 가능한 변경을 위한 권장 조건입니다.", "진행:필수 근거와 책임 충족|보류:범위가 정해진 보완|중단:안전하지 않거나 측정 불가|권장:IaC 또는 GitOps 기준선", [docs.constitution, docs.deployment], "tree"),
  topic("PHASE 1", "관찰 모드는 실제 변경 없이 판단합니다", "새 작업은 판단과 기록만 수행하고 사람의 실제 결과와 비교합니다.", "입력:실제 사건|판단:형식화된 판정|상태 변경:없음", docs.security, "flow"),
  topic("PHASE 1", "성공과 실패를 아우르는 여섯 가지 시나리오를 고정합니다", "성공 사례만으로는 충분하지 않습니다. 입력 집합과 기대 결과를 리비전에 고정해 같은 조건에서 재생합니다.", "정상 완료:기대 효과까지 닫힌 경로|판단 보류 또는 차단:unknown 또는 deny|목표 충돌:도메인 간 절충|부분 실패와 복구:보상과 recovery_incomplete|A3-E 적용 여부:사례 또는 명시적 비적용|결정론적 재생:동일 입력과 결과", docs.constitution, "comparison"),
  topic("PHASE 1", "T0 적용 범위를 먼저 높입니다", "반복 판단은 정책과 규칙으로 해결하고 T2는 모호한 소수에 제한합니다.", "T0:결정론적 규칙|T1:검증된 사례 재사용|T2:근거 기반 잔여 모호성 판단", docs.constitution, "flow"),
  topic("PHASE 1", "보류 사유를 학습 데이터와 분리합니다", "근거 누락, 오래된 정보, 충돌, 권한 없음 상태를 모델 실패 하나로 합치지 않습니다.", "근거:누락 또는 최신성 부족|정책:거부 또는 승인 필요|시스템:의존성 사용 불가", docs.constitution, "matrix"),
  topic("PHASE 1", "사람 검토 대기열의 품질을 측정합니다", "필수 승인과 불필요한 상향 검토를 분리해 승인 알림 과다를 줄입니다.", "필수:위험 정책|잔여:모호성|회피 가능:근거 복구 차이", docs.pantheon, "matrix"),
  topic("PHASE 1", "관찰 모드 감사를 완전한 추적으로 남깁니다", "사건, 계층, 판정, 작업 버전, 근거 기준 시점을 재생할 수 있어야 합니다.", "사건:상관관계 ID|판정:결정된 권한 상한|근거:출처별 증적", docs.execution, "evidence"),
  topic("GATE 1", "네 가지 안전 지표는 정확히 0이어야 합니다", "평균 계약 적합성이 높아도 잘못된 대상, 무권한 실행, 정책 위반 유출, 독립 검증 없는 성공 주장이 한 건이라도 있으면 승격할 수 없습니다.", "0:잘못된 대상 또는 오래된 리비전 실행|0:등록되지 않은 권한·신원·영향 범위 실행|0:정책 위반의 적용 모드 유출|0:독립 효과 확인 없는 성공 주장", [docs.constitution, docs.metrics], "numbers"),
  topic("PHASE 2", "현재 계획에 묶인 가상 실행을 검증합니다", "비운영 환경의 연습은 유용하지만, 프로덕션 변경 직전에도 현재 대상과 계획 다이제스트에 결합된 가상 실행이 필요합니다.", "계획:불변 다이제스트와 대상 리비전|비운영 연습:기계적 경로 검증|실행 직전:현재 근거로 다시 검증|결과:부수 효과 없는 예측 증적", docs.security, "evidence"),
  topic("PHASE 2", "선언된 복구 결과를 별도로 훈련합니다", "정상 경로의 성공과 장애 복구 가능성은 서로 다른 근거입니다. 복구는 이전 상태 복원뿐 아니라 안전한 다음 상태로의 전진이나 비가역 작업의 최선 복구일 수 있습니다.", "유발:제어된 실패|계약:되돌리기, 복원, 전진 복구|비가역:사람 정족수와 최선 복구|검증:선언된 최종 상태와 효과", docs.security, "timeline"),
  topic("PHASE 2", "영향 범위 계산을 실제 그래프로 검증합니다", "고정된 등급만 믿지 않고 범위가 제한된 의존 대상과 최대 영향 리소스 수를 비교합니다.", "시작점:정확한 대상|그래프:contains와 depends_on|한도:선언된 상한", docs.security, "flow"),
  topic("PHASE 2", "중복 전달을 의도적으로 재생합니다", "최소 한 번 전달되는 이벤트와 재시도가 두 번째 변경을 만들지 않아야 합니다.", "첫 시도:키 예약|재시도:중복 감지|결과:효과 한 번", docs.constitution, "timeline"),
  topic("PHASE 2", "긴급 중지와 성능 저하 경로를 연습합니다", "의존성 실패나 운영자 중지가 권한을 shadow로 낮추는지 확인합니다.", "정상:일반 상한|성능 저하:shadow만 허용|긴급 중지:즉시 격리", docs.execution, "tree"),
  topic("GATE 2", "안전 훈련과 운영 통제를 모두 입증합니다", "일곱 안전장치, 독립 효과 관측, 신원 재인증, 긴급 중지, 비상 접근, 감사 앵커 중 빠진 항목이 있으면 적용 모드 검토를 시작하지 않습니다.", "실행 계약:일곱 안전장치와 독립 효과 마감|신원:최소 권한과 재인증|비상 통제:긴급 중지와 break-glass 훈련|감사:정확한 리비전과 앵커 증적", docs.security, "matrix"),
  topic("PHASE 3", "승격은 기능별로 요청합니다", "환경이나 enabled 값이 ActionType의 권한을 자동으로 바꾸지 않습니다.", "기능:정확한 작업 버전|모드:관찰에서 적용으로|등록부:검토된 상태", docs.constitution, "evidence"),
  topic("PHASE 3", "RiskGate 결과를 전달 직전에 다시 봅니다", "승격되었어도 실시간 영향, 역할, 환경, 시스템 상태가 자율성을 낮출 수 있습니다.", "고정 조건:ActionType 상한|동적 조건:실시간 점검과 상태|최종:가장 낮은 권한", docs.execution, "flow"),
  topic("PHASE 3", "첫 적용은 작은 묶음으로 제한합니다", "낮은 영향 범위와 명확한 중지 조건 안에서만 상태 변경을 허용합니다.", "범위:제한된 한 대상군|속도:명시적 상한|중지:기계 평가", docs.security, "cards"),
  topic("PHASE 3", "사람 승인 경로를 실제로 검증합니다", "승인은 정확한 작업, 대상, 계획 리비전, 중복 억제 키에 묶입니다. 시간 초과나 정족수 미달은 실행하지 않는 종료 상태가 됩니다.", "요청:특정 작업과 영향 범위|승인:실행자와 분리된 인증 주체|정족수:위험 정책이 요구한 인원|시간 초과:변경 없음과 감사 마감", docs.security, "timeline"),
  topic("PHASE 3", "실행 응답 뒤에도 효과 관측 구간을 기다립니다", "공급자 응답 뒤 권위 있는 독립 관측자가 기대 범위를 확인할 때까지 완료가 아닙니다.", "전달:명령 수락|관측:독립 출처|종료:ObservedOutcome", docs.constitution, "evidence"),
  topic("GATE 3", "첫 적용의 종료 조건을 엄격히 적용합니다", "안전하게 실행됐고 기대 효과가 확인되며 감사 사슬이 닫혀야 다음 묶음으로 갑니다.", "실행:안전장치 통과|효과:지표가 범위 안|감사:최종 종료", docs.ontology, "tree"),
  topic("PHASE 4", "운영 주기마다 성과와 안전을 함께 봅니다", "비용, 자동 해결, MTTR, 변경 리드 타임, 사람 접점을 같은 비교 집단에서 보고 네 가지 0 기준과 복구·효과 지표를 함께 검토합니다.", "성과:다섯 성공 지표와 신뢰 구간|안전:네 가지 정확한 0 기준|운영:복구, 효과 검증, 사람 검토|근거:고정 시나리오와 정확한 리비전", docs.metrics, "matrix"),
  topic("PHASE 4", "품질 저하는 자동 강등으로 이어집니다", "권한을 유지한 채 수정하지 않고 관찰 모드로 돌아가 원인을 분석합니다.", "감지:통과 기준 저하|강등:즉시 관찰 모드|복구:새 근거 뒤 재승격", docs.security, "timeline"),
  topic("PHASE 4", "새 규칙은 비활성 후보로 시작합니다", "파일럿 학습이 즉시 카탈로그와 권한을 변경하지 않습니다.", "Norns:후보 제안|Mimir:규칙 검토|등록부:별도 승격", docs.pantheon, "responsibility"),
  topic("PHASE 4", "운영 인수인계에는 책임자와 실행 절차가 필요합니다", "배포 팀이 빠져도 승인, 복구, 경고, 근거 출처를 운영할 수 있어야 합니다.", "서비스 책임자:운영 결과|플랫폼 책임자:런타임|보안 책임자:권한", docs.pantheon, "responsibility"),
  topic("IMPLEMENTED", "Operator 워크플로 시작은 제안 전용입니다", "POST /workflows/run은 중복 실행에 안전하고 리비전에 묶인 관찰 모드 요청만 받으며 mode=enforce를 거부합니다.", "요청자:관찰 모드 제안|Operator:영속 발신함|이벤트 버스:독립 서비스 전달|Core:일반 권한 경로", docs.operator, "flow"),
  topic("IN_PROGRESS", "워크플로 적용 경로의 운영 증적은 남아 있습니다", "Core 단계 실행기에는 통제된 경로가 있지만, 소유자 승인과 모든 안전장치를 거친 로컬·배포 경로가 보존된 런타임 증적으로 입증되지 않았습니다.", "현재:Core 단계 실행기 코드|열림:소유자 승인과 종단 안전장치|열림:로컬·배포 동등성 증적|경계:Operator API는 제안 전용", docs.operator, "evidence"),
  topic("IMPLEMENTED", "보호 배포는 정확한 산출물을 사용합니다", "서명 이미지, SBOM, 증명, 봉인된 계획이 신원, 명령, 다른 서비스 상태의 변경을 제한합니다.", "산출물:서명되고 고정된 이미지 다이제스트|계획:허용된 차이만 포함|적용:마이그레이션 뒤 상태 점검|복구:이전 정상 리비전 보존", docs.deployment, "timeline"),
  topic("NOT_STARTED", "자동 점진적 배포는 아직 목표입니다", "dev, staging, prod 자동 승격, 트래픽 분할 카나리, SLO 기반 되돌리기, Console 블루/그린은 구현되지 않았습니다.", "현재:보호된 계획·적용 흐름|목표:동일 산출물의 환경 승격|목표:카나리와 SLO 기반 되돌리기|목표:Console 블루/그린", docs.deployment, "matrix"),
  topic("IN_PROGRESS", "프로덕션 준비는 구현된 게이트와 운영 증적을 함께 봅니다", "사설망, 내구성, 서명 이미지, 모니터링, 비용 입력을 검사하는 계획 게이트는 구현됐습니다. 정확한 리비전의 프로덕션 적용과 복구 증적은 남아 있습니다.", "구현됨:프로덕션 계획 차단 조건|진행 중:보호된 계획·적용 증적|보안:신원과 모든 실행 경로의 안전장치|운영:당직, DR, 복구 훈련", docs.hardening, "responsibility"),
  topic("PROPOSAL", "확장 전에 비용 상한을 검토합니다", "모니터링과 월별 예산은 프로덕션 계획의 필수 입력입니다.", "용량:리소스 특성|모니터링:경고 대상|비용:예산과 책임자", docs.hardening, "matrix"),
  topic("DECISION", "프로덕션 전환은 네 가지 결과 중 하나입니다", "승격, 관찰 모드 유지, 범위 축소, 중지를 근거와 함께 결정합니다.", "승격:모든 게이트와 운영 증적 충족|관찰 유지:근거 추가 필요|범위 축소:더 작은 대상과 권한으로 재설계|중지:안전하지 않거나 가치 없음", docs.security, "tree"),
  topic("HANDOVER", "운영 팀은 정확한 리비전의 근거를 받습니다", "코드 링크만 넘기지 않고 배포, 신원, 안전장치, 효과, 복구, DR 근거 묶음을 인수합니다.", "빌드:산출물 출처와 공급망 증명|운영:권한, 경고, 감사, 예산|복구:RPO·RTO, 이전 리비전, failover·failback 훈련|효과:독립 관측과 미해결 충돌", docs.deployment, "evidence"),
  topic("NEXT", "다음 사용 사례는 검증된 경계를 재사용합니다", "새 권한을 넓히기보다 기존 온톨로지, 관측자, 승인 경로 안의 인접 판단을 선택합니다.", "재사용:타입과 매핑|재사용:근거 출처|재사용:안전 운영 절차", docs.ontologyPlatform, "flow"),
]);

const aiOperatingModel = buildDeck("ai-operating-model", "AI 운영 모델", [
  topic("OPERATE", "운영 모델은 책임과 운영 주기를 연결합니다", "리더는 15개 고정 역할, 플랫폼 책임, 거버넌스, FinOps, LLMOps 의사결정을 하나의 체계로 운영합니다.", "책임:최종 책임자 한 명|거버넌스:분리된 권한|운영 주기:측정된 근거|결과:독립 관측과 감사", docs.pantheon),
  topic("CURRENT", "15개 에이전트 역할은 고정되어 있습니다", "배포판과 하위 확장 구현은 연결 설정만 제공하며, 에이전트를 추가하거나 이름을 바꾸지 않습니다.", "5:거버넌스·기억·학습 담당|7:수집·관측·판단·실행 담당|3:비용·용량·복원력 전문가|15:고정된 전체 에이전트", docs.pantheon, "numbers"),
  topic("CURRENT", "단일 소유 에이전트만 권위 있는 객체를 발행합니다", "여러 구독자가 같은 투영을 읽어도 권위 있는 발행자는 하나이며, 모든 상태 변경은 스키마가 있는 이벤트 버스를 지납니다.", "소유자:객체별 단일 발행 에이전트|소비자:독립적인 여러 구독자|전송:스키마와 계보가 있는 이벤트|복구:최소 1회 전달과 중복 안전 재생", docs.pantheon, "matrix"),
  topic("CURRENT", "Odin은 적격한 목표 절충안만 조정합니다", "안전과 정책을 위반한 선택지는 포트폴리오 점수 계산 전에 제외됩니다.", "Forseti:중재 요청 발행|Odin:적격 선택지 순위화|Saga:판단 감사", docs.pantheon, "responsibility"),
  topic("CURRENT", "Forseti와 Thor의 경계를 지킵니다", "판단자가 실행하지 않고 실행기는 새로운 판정을 만들지 않습니다.", "Forseti:근거 판단|Thor:적격 작업 전달|Vidar:실패 복구", docs.pantheon, "responsibility"),
  topic("CURRENT", "Var는 사람의 승인 결정을 검증된 기록으로 전달합니다", "승인 요청, 거부, 정족수, 만료를 처리하지만 스스로 작업을 실행하지 않습니다.", "사람:현재 요청에 대한 인증된 결정|Var:범위와 만료를 검증한 승인 기록|Thor:효과 발생 전 권한 재검사|Saga:승인 계보 감사", docs.pantheon, "flow"),
  topic("CURRENT", "Saga는 추가만 가능한 감사 원장을 책임집니다", "모든 최종 경로와 관찰 모드 결과를 상관관계 ID와 함께 보존합니다.", "의도:효과 발생 전 선기록|판단:통과 기준과 권한|실행:시도와 공급자 증적|결과:효과, 복구, 최종 마감", docs.pantheon, "evidence"),
  topic("CURRENT", "규칙 학습과 실행 승격은 서로 다른 경로입니다", "Norns는 비활성 규칙 후보를 만들고 Mimir가 독립 검토한 뒤 카탈로그 PR로 관리합니다. ActionType과 Workflow의 실행 승격은 별도 관찰 근거와 등록부를 사용합니다.", "Norns:근거가 있는 비활성 후보|Mimir:규칙 품질과 출처 검토|카탈로그:검토된 PR 병합|실행 승격:별도 근거와 권한 등록부", docs.pantheon, "responsibility"),
  topic("CURRENT", "Bragi는 대화 수명 주기와 형식화된 의도를 소유합니다", "Bragi는 대화, 턴, 사용자 선호, 인수인계, 사후 검토를 관리하고 자연어를 형식화된 도구 요청으로 옮깁니다. 판단, 승인, 실행은 하지 않습니다.", "운영자:목표, 범위, 제약|Bragi:대화와 의도 형식화|읽기 포트:근거가 있는 설명|권한 포트:일반 에이전트 경로로 전달", docs.pantheon, "flow"),
  topic("CURRENT", "Njord, Freyr, Loki는 도메인 후보를 만듭니다", "비용, 용량, 복원력 전문성은 별도 상위 에이전트가 아니라 같은 제어 경계로 들어갑니다.", "Njord:비용 제안|Freyr:용량 예측|Loki:카오스와 복원력", docs.pantheon, "cards"),
  topic("PROPOSAL", "목표 운영 협의체는 우선순위와 예외를 관리합니다", "이는 권장 운영 모델입니다. 협의체는 헌법상 우선순위를 바꾸지 않고 적격한 목표 사이의 절충, 예산, 예외 만료를 결정합니다.", "입력:SLO, 위험, 비용, 미해결 충돌|결정:적격 선택지의 우선순위|권한:정책·안전 경계보다 높지 않음|기록:결정, 책임자, 만료, 재검토", docs.constitution, "timeline"),
  topic("GOVERN", "아키텍처 검토는 지속형 프로세스로 운영합니다", "구조 적합성, 운영 준비도, 실행 진행 상태를 각각 확인하며 하나의 상태로 합치지 않습니다.", "구조:명세와 계약 유효성|준비도:근거 완전성과 소유자|실행:Process 단계와 차단 사유|변경:ActionType 경로로 재진입", docs.operator, "matrix"),
  topic("PROPOSAL", "승격 심의는 기능 사용과 실행 권한을 분리합니다", "조직이 정한 심의체는 사용 가능성, 사용 설정, 환경, 실행 모드, 배포 근거를 독립적으로 검토해야 합니다. 심의체 이름과 정족수는 배포가 정합니다.", "사용 가능:필수 조건 충족|사용 설정:운영자 선택|실행 모드:관찰 또는 적용|증적:고정 시나리오와 정확한 리비전", [docs.constitution, docs.runtimeAxes], "tree"),
  topic("PROPOSAL", "보안 검토 주기는 배포 위험에 맞춰 정합니다", "작업 허용 목록, 역할 할당, 권한 재인증, 비상 접근을 정기적으로 검토해야 하지만 월간·분기 주기는 고정된 제품 사실이 아니라 배포 정책입니다.", "정기:실효 권한과 허용 목록 검토|변경 시:신원·역할 재인증|발생 시:비상 접근 사후 검토|증적:책임자와 다음 검토일", docs.security, "timeline"),
  topic("GOVERN", "데이터 거버넌스는 근거 품질을 책임집니다", "출처 신원, 목적, 최신성, 관측 범위, 비식별 처리를 프로덕션 통과 기준으로 봅니다.", "출처:인증됨|품질:최신이고 완전함|개인정보:최소화하고 비식별 처리", docs.dataGovernance, "matrix"),
  topic("FINOPS", "FinOps는 모델과 인프라 비용을 함께 봅니다", "결정론적 처리 범위와 T2 호출 비용을 검증된 운영 결과에 연결합니다.", "런타임:플랫폼 지출|추론:T2 비율과 단가|결과:검증된 절감", docs.execution, "matrix"),
  topic("FINOPS", "비용이 늘어나는 작업은 별도 기준을 통과합니다", "월 비용 추정치가 없거나 기준 이상인 수평 확장은 자동 실행하지 않습니다.", "추정:월 비용 영향|통과 기준:위험 표|판정:승인 또는 보류", docs.execution, "tree"),
  topic("FINOPS", "예산은 프로덕션 배포 계획의 입력입니다", "월 예산과 경고 수신처 없이 프로덕션 강화 기준을 통과하지 않습니다.", "예산:금액과 책임자|경고:수신자|검토:편차와 후속 작업", docs.hardening, "evidence"),
  topic("LLMOPS", "LLMOps는 T2를 잔여 모호성에 제한합니다", "모델 성능만 보지 않고 T0과 T1이 판단하지 못한 비율, 복수 모델 불일치, 검증기 결과, 비용과 지연을 함께 관리합니다.", "수요:T0과 T1로 판단 불가|생성:서로 다른 두 모델|검증:근거, 계약, 정책 확인|경계:T2는 실행 권한을 만들지 않음", docs.constitution, "flow"),
  topic("LLMOPS", "프롬프트와 모델 버전을 재생 기록에 남깁니다", "판단 맥락은 근거 기준 시점과 정확한 알고리즘 또는 모델 버전을 고정합니다.", "입력:비식별 처리된 맥락|모델:정확한 버전|출력:검증된 제안", docs.constitution, "evidence"),
  topic("LLMOPS", "모델 간 불일치는 사람 검토로 보냅니다", "한 모델의 자신감이 다른 모델과 검증기의 확인을 대체하지 않습니다.", "생성:서로 다른 두 모델|비교:일치 여부 확인|상향 검토:해결되지 않은 충돌", docs.constitution, "tree"),
  topic("LLMOPS", "모델은 실행 자격을 부여하지 않습니다", "결정론적 검증기, 정책, 가상 실행이 작업 실행 가능 여부를 결정합니다.", "LLM:제안|검증기:계약 확인|RiskGate:권한 상한", docs.execution, "flow"),
  topic("PROPOSAL", "일일 운영 주기는 예외와 시스템 상태를 봅니다", "권장 운영 달력에서 사람은 전체 사건보다 판단 보류, 근거 충돌, 성능 저하, 복구 상태에 집중합니다.", "예외:판단 보류와 승인 만료|의존성:감사·복구·관측 상태|책임자:다음 작업과 기한|근거:추적과 정확한 리비전", docs.pantheon, "cards"),
  topic("PROPOSAL", "주간 운영 주기는 결과와 사람 검토 부하를 봅니다", "계약 적합성, 사람 승인, 복구, 독립 효과를 같은 시나리오 기준으로 비교합니다.", "품질:계약에 맞는 최종 결과|부하:이벤트 100건당 사람 접점|복구:실패와 완료 시간|결과:독립 관측으로 검증된 성공", docs.metrics, "matrix"),
  topic("PROPOSAL", "월간 운영 주기는 승격과 비용을 봅니다", "관찰 기간, 안전 지표, 추론 지출, 플랫폼 예산을 독립 기준으로 검토합니다.", "승격:표본, 기간, 신뢰 구간|LLMOps:모델, 검증기, T2 비율|FinOps:업무 단위 비용과 예산 편차|결정:유지, 강등, 재검토", [docs.metrics, docs.security], "timeline"),
  topic("PROPOSAL", "분기 운영 주기는 권한과 복원력을 재검증합니다", "권장 주기는 역할 재인증, 복구, 긴급 중지, DR 훈련을 정확한 리비전에 남깁니다. 실제 빈도는 배포 위험 정책이 정합니다.", "신원:최소 권한과 실효 접근|복구:선언된 계약의 훈련|제어:긴급 중지와 비상 접근|DR:RPO·RTO와 failover·failback", docs.security, "timeline"),
  topic("METRIC", "에이전트별 KPI보다 제어 결과를 우선합니다", "개별 활동량이 아니라 SLO 회복, 재발 방지, 변경 안전, 실현된 절감을 봅니다.", "SRE:복구와 재발 방지|변경:검증된 안전 결과|FinOps:실현된 절감", docs.metrics, "cards"),
  topic("METRIC", "운영 성과는 다섯 지표와 안전 기준을 함께 봅니다", "동일한 시나리오와 리비전으로 기준 집단과 적용 집단을 측정하기 전에는 개선 효과를 주장하지 않습니다. 현재 지표 집계는 구현됐지만 실운영 비교 근거는 아직 완성되지 않았습니다.", "5:업무 단위 비용, 자동 해결, MTTR, 변경 리드 타임, 사람 접점|4:정확히 0이어야 하는 핵심 안전 위반|30+:각 비교군의 최소 표본|1:고정 시나리오와 정확한 리비전", docs.metrics, "numbers"),
  topic("METRIC", "사람 승인율을 무조건 낮추지 않습니다", "정책상 필요한 승인과 불필요한 상향 검토를 구분합니다.", "필수:위험과 권한|잔여:모호성|회피 가능:근거 차이", docs.pantheon, "tree"),
  topic("METRIC", "효과 없는 성공을 제거합니다", "전달 성공 대신 독립 관측으로 결과 KPI를 닫습니다.", "시도:실행기 영수증|관측:권위 있는 출처|평가:예상과 실제 비교", docs.ontology, "evidence"),
  topic("CURRENT", "로컬과 배포는 같은 계약을 사용합니다", "공급자와 자격 증명만 다르고 카탈로그, 게이트, Process 이벤트를 임의로 바꾸지 않습니다.", "같음:규칙과 승격|같음:위험과 승인|다름:어댑터와 신원", docs.operator, "matrix"),
  topic("IN_PROGRESS", "워크플로 적용 동등성은 운영 항목으로 남습니다", "제안 전용 Operator 경계와 영속 발신함은 구현됐지만, 소유자 승인과 모든 안전장치를 통과한 로컬·배포 런타임 증적이 필요합니다.", "현재:영속 제안 연결|열림:적용 경로의 종단 증적|열림:환경 동등성|책임자:플랫폼과 거버넌스", docs.operator, "responsibility"),
  topic("GAP", "프로덕션 개인정보 보호 근거를 완료로 표시하지 않습니다", "공통 비식별 처리 구현과 배포 개인정보 보호 승인은 다른 상태입니다.", "구현:최소화 경로|진행:프로덕션 게이트|열림:보존된 근거", docs.security, "matrix"),
  topic("NOT_STARTED", "점진적 배포는 로드맵 항목입니다", "자동 산출물 승격과 카나리 기반 되돌리기는 현재 운영 기능이 아닌 목표입니다.", "현재:보호된 워크플로|목표:자동 승격|목표:SLO 기반 되돌리기", docs.deployment, "timeline"),
  topic("PROPOSAL", "RACI는 고정된 Pantheon과 사람 책임자를 연결합니다", "에이전트 역할을 바꾸지 않고 정책, 서비스, 보안, 플랫폼의 최종 책임자를 배정합니다.", "서비스 책임자:비즈니스 결과|플랫폼 책임자:런타임 SLO|보안 책임자:권한 정책", docs.pantheon, "responsibility"),
  topic("PROPOSAL", "운영 회의는 근거 링크로 시작합니다", "슬라이드 색이나 구두 보고가 아니라 정확한 추적, 릴리스, 근거를 검토합니다.", "추적:상관관계 ID|릴리스:요약값|근거:출처와 기준 시점", docs.ontologyPlatform, "evidence"),
  topic("PROPOSAL", "예외에는 만료와 재검토를 붙입니다", "정책 예외와 비상 접근은 기한을 두며 자동 상시 권한으로 남지 않습니다.", "범위:제한된 대상|시간:명시적 만료|종료:사후 검토 감사", docs.security, "timeline"),
  topic("PROPOSAL", "업무 인수인계는 권한이 아니라 운영 근거를 전달합니다", "새 담당자는 실행 절차, 판단 계보, 복구 근거를 받고 권한은 별도 절차로 부여받습니다.", "지식:실행 절차와 사례|근거:추적과 결과|권한:별도 재인증", docs.pantheon, "responsibility"),
  topic("DECISION", "운영 모델 승인에는 열린 항목도 포함합니다", "CURRENT와 TARGET 사이의 책임자, 기한, 종료 기준을 명시해야 합니다.", "수락:구현된 경계|추적:진행 중인 근거|거부:근거 없는 주장", docs.constitution, "tree"),
  topic("NEXT", "운영 달력의 네 가지 주기를 배포 정책으로 확정합니다", "일일 운영, 주간 결과, 월간 승격과 비용, 분기형 권한·복구 훈련을 시작점으로 책임자와 실제 빈도를 정합니다.", "일일:예외와 의존성|주간:결과와 사람 접점|월간:승격과 FinOps|분기형:신원, 복구, DR", docs.security, "timeline"),
]);

const enterpriseScaleRoadmap = buildDeck("enterprise-scale-roadmap", "전사 확장 로드맵", [
  topic("ROADMAP", "전사 확장은 기능 수가 아니라 의존성과 종료 기준으로 진행합니다", "플랫폼과 거버넌스 리더는 한 의사결정 유형의 근거를 공통 기반으로 삼아 확장합니다.", "순서:기반부터 구축|통과 기준:권한보다 근거가 먼저|확장:범위를 넓히기 전 재사용", docs.constitution),
  topic("PRINCIPLE", "확장은 자율성을 자동으로 높이지 않습니다", "실행 위치, 배포 단계, 근거, 실행 모드, 신원, 배포판은 서로 독립된 축입니다. 한 축의 변화가 다른 축의 권한을 올리지 않습니다.", "실행 위치:로컬 또는 배포 환경|배포 단계:개발, 사전 운영, 운영|근거:권위 있는 자료 또는 시험 자료|실행 모드:관찰 또는 적용|신원과 권한:사람과 실행기 분리|배포판:업스트림 또는 하위 배포판", docs.runtimeAxes, "layers"),
  topic("PRINCIPLE", "Azure 구현 사실과 공급자 목표를 분리합니다", "현재 확장 계획은 Azure 근거를 사용하며 Azure 외 공급자는 계약 확장 가능성일 뿐입니다.", "현재:Azure 어댑터|목표:공급자 중립 계약|미구현:Azure 외 공급자", docs.deployment, "tree"),
  topic("PRINCIPLE", "하나의 제어 영역이 여러 도메인을 지원합니다", "SRE 운영 모델 아래 Resilience, Change Safety, Cost Governance를 같은 안전 경계로 확장합니다.", "SRE:전체 운영 모델|도메인:초기 세 영역|ARB:도메인 간 거버넌스", docs.constitution, "cards"),
  topic("WAVE 0", "전사 목표의 우선순위를 승인합니다", "안전과 신뢰성보다 비용을 앞세우지 않는 공통 순서를 먼저 고정합니다.", "1:보안과 데이터 무결성|2:SLO와 변경 안전|3:효율과 비용", docs.constitution, "timeline"),
  topic("WAVE 0", "의사결정 유형 목록을 만듭니다", "팀별 도구 목록 대신 누가 어떤 근거로 어떤 판단을 하는지 수집합니다.", "판단:반복 가능한 선택|근거:권위 있는 출처|책임자:최종 책임을 지는 사람", docs.ontology, "cards"),
  topic("WAVE 0", "서로 다른 상태 축을 하나의 열거값으로 합치지 않습니다", "판정, 행동 수명 주기, 실행 상태, 복구 상태, 효과 관측은 별도 축입니다. 화면에서는 쉬운 한국어로 보이되 감사 기록의 계약 값은 유지합니다.", "판정:자동 실행, 사람 승인, 판단 보류, 차단|수명 주기:관찰 모드 또는 적용 모드|실행:대기, 진행, 완료, 실패, 실행 불명|복구:불필요, 진행, 완료, 미완료|효과:관측 전, 확인, 불일치, 충돌", [docs.execution, docs.runtimeAxes], "comparison"),
  topic("GATE 0", "후원자와 책임자가 없으면 시작하지 않습니다", "가치와 위험, 데이터, 플랫폼 결과의 최종 책임을 문서화합니다.", "후원자:우선순위와 예산|서비스 책임자:운영 결과|플랫폼 책임자:런타임", docs.pantheon, "responsibility"),
  topic("WAVE 1", "운영 온톨로지 릴리스 기반을 배포합니다", "변경되지 않는 온톨로지 릴리스와 정확한 다이제스트를 사용해 팀마다 같은 개념을 다르게 해석하는 문제를 막습니다.", "카탈로그:변경되지 않는 릴리스|런타임:정확한 참조|호환성:마이그레이션 판정", docs.ontologyPlatform, "evidence"),
  topic("WAVE 1", "BusinessService와 Workload 연결축을 채웁니다", "모든 리소스를 한 번에 분류하기보다 우선 서비스의 정확한 매핑부터 시작합니다.", "서비스:중요도와 책임자|Workload:배포 가능한 단위|Resource:관측된 배치 위치", docs.ontology, "flow"),
  topic("WAVE 1", "미분류 리소스 작업 목록을 가시화합니다", "unknown_service와 unclassified-resource를 숨기지 않고 매핑 작업으로 관리합니다.", "알 수 없음:보이는 상태로 유지|책임자:분류 담당자|종료:검토된 매핑", docs.ontology, "timeline"),
  topic("WAVE 1", "근거 출처 등록부를 표준화합니다", "출처 신원, 목적, 범위, 최신성, 완전성, 출처 계보를 공통 근거로 만듭니다.", "신원:인증된 출처|시간:사건 시각과 기록 시각|범위:완전성 확인", docs.constitution, "matrix"),
  topic("WAVE 1", "데이터 최소화 경계를 적용합니다", "원문 데이터보다 포인터와 요약값을 보존하고 비식별 처리 정보를 남깁니다.", "수집:최소 필드|저장:포인터와 요약값|표시:역할별 비식별 처리", docs.security, "flow"),
  topic("GATE 1", "형식화된 운영 사실의 다섯 역량을 확인합니다", "정확한 ID부터 근거 건전성까지 단계별로 답할 수 있어야 다음 확산 단계로 갑니다.", "C1 정체성:정확한 ID와 접근 제어|C2 관계:방향과 종류가 있는 연결|C3 의존 대상:상위·하위 영향 탐색|C4 영향 범위:깊이와 결과 수가 제한된 계산|C5 근거 건전성:최신성, 완전성, 충돌, 출처", docs.ontologyPlatform, "comparison"),
  topic("WAVE 2", "고정된 15개 에이전트 구성을 활성화합니다", "팀마다 새 에이전트를 만들지 않고 설정과 공급자 연결로 범위를 확장합니다.", "고정:역할과 객체 책임자|설정:범위와 정책|어댑터:공급자 구현", docs.pantheon, "cards"),
  topic("WAVE 2", "토픽 소유권과 스키마 통과 기준을 배포합니다", "단일 작성자, 다중 독자, 최소 1회 전달을 전제로 한 중복 안전 재생이 확장 시 권위 충돌을 막습니다.", "발행자:책임자 한 명|전송:스키마와 계보 검증|소비자:독립적인 재시도와 backpressure|재생:중복과 순서 변경에 안전", docs.pantheon, "flow"),
  topic("WAVE 2", "신원을 서비스와 도메인별로 분리합니다", "Console, Core, 수집 계층, 실행기, 도메인별 배포 주체가 신원을 공유하지 않습니다.", "서비스:서로 다른 작업 신원|도메인:변경, 복원력, FinOps|사람:분리된 승인", docs.security, "matrix"),
  topic("WAVE 2", "전역 긴급 중지를 운영 체계에 연결합니다", "전사 확장 전에 실행 신원 없이 중단하고 감사, 호출, 만료까지 이어지는 절차를 연습합니다.", "작동:책임자 또는 비상 접근|효과:관찰 모드 상한|근거:훈련 근거", docs.security, "timeline"),
  topic("GATE 2", "필수 의존성의 실패를 역할별로 검증합니다", "Saga와 Vidar 손실은 모든 상태 변경을 막습니다. 관측자와 Var 손실은 해당 행동이 그 의존성을 요구할 때만 변경을 차단합니다.", "감사 중단:모든 상태 변경 없음|복구 중단:모든 상태 변경 없음|관측 중단:해당 효과의 성공 주장과 후속 변경 없음|승인 경로 중단:사람 승인이 필요한 행동만 실행 없음", [docs.constitution, docs.pantheon], "tree"),
  topic("WAVE 3", "프로덕션 기반을 첫 적용 전에 강화합니다", "사설망, 내구성 있는 PostgreSQL, 모니터링, 예산, 신뢰할 수 있는 이미지를 배포 통과 기준으로 만듭니다.", "네트워크:사설 데이터 서비스|내구성:HA, 백업, RPO·RTO|공급망:SBOM, 서명, 고정 다이제스트|운영:경고, 수신처, 예산", docs.hardening, "cards"),
  topic("WAVE 3", "서비스별 상태 소유권을 유지합니다", "서비스별 백엔드 키와 상호 격리 근거가 대규모 배포의 영향 범위를 제한합니다.", "상태:서비스별 백엔드 키|계획:다른 서비스 상태 변경 차단|근거:다이제스트와 계보|복구:서비스별 이전 정상 리비전", docs.deployment, "evidence"),
  topic("WAVE 3", "마이그레이션과 초기 구성을 순서대로 실행합니다", "Operator 스키마 마이그레이션 뒤 불변 Rule과 온톨로지 참조 투영을 작성하고 서비스 준비도를 확인합니다.", "먼저:스키마 마이그레이션|다음:카탈로그 초기 구성|마지막:준비도와 상태 점검", docs.deployment, "timeline"),
  topic("WAVE 3", "복구 기준선을 보호합니다", "정상인 활성 리비전을 캡처하고 비활성 리비전 하나를 복구용으로 남깁니다.", "캡처:정상 활성 리비전|보존:비활성 리비전 하나|복구:보호된 워크플로|검증:failover와 failback 결과", docs.deployment, "evidence"),
  topic("GATE 3", "보호된 적용 근거를 보존합니다", "코드와 계획 차단 조건만으로 프로덕션 검증을 주장하지 않습니다. 정확한 리비전의 계획, 적용, 상태, 복구 경계를 함께 보존합니다.", "계획:정확한 리비전과 무관한 삭제 0|적용:서명 산출물과 마이그레이션|관측:서비스 상태와 독립 효과|복구:이전 리비전과 RPO·RTO", docs.hardening, "tree"),
  topic("WAVE 4", "첫 도메인은 한 의사결정 유형으로 시작합니다", "가치, 반복성, 근거, 검증된 복구가 가장 준비된 범위를 선택합니다.", "범위:한 대상 유형|모드:관찰|측정:기준선과 효과|권한:별도 승격 전까지 변경 없음", docs.security, "cards"),
  topic("WAVE 4", "여섯 차원의 시나리오 묶음을 고정합니다", "성공 사례만이 아니라 판단 보류, 목표 충돌, 부분 실패, A3-E 적용성, 재생을 포함한 같은 사건 집합을 사용합니다.", "성공:기대 효과까지 닫힌 전체 경로|부정:알 수 없음 또는 차단|충돌:도메인 간 목표 절충|복구:부분 실패와 보상|A3-E:사례 또는 명시적 비적용|재생:동일 입력의 결정론적 결과", docs.constitution, "comparison"),
  topic("WAVE 3", "관찰 기간과 검토 결과를 수집합니다", "판단 품질과 정책 위반 유출 여부를 실제 검토자 결과로 마감합니다.", "관찰:상태 변경 없음|검토:분리된 사람|근거:안정된 관측 ID", docs.pantheon, "timeline"),
  topic("WAVE 4", "일곱 안전장치 훈련을 완료합니다", "중지, 검증된 복구, 영향 범위, 가상 실행, 대상 잠금, 중복 억제, 2단계 감사를 정확한 리비전에서 검증합니다.", "7:필수 안전장치|1:정확한 ActionType과 리비전|0:중복 효과와 권한 이탈|독립:효과 관측과 검토자", docs.security, "numbers"),
  topic("GATE 4", "첫 승격은 독립 심사를 받습니다", "파일럿 팀이 자기 결과만으로 적용 모드 권한을 부여하지 않습니다.", "배포:고정 시나리오와 정확한 리비전|보안:권한과 안전 지표 검토|거버넌스:승격 등록부 변경|운영:자동 강등과 긴급 중지 준비", docs.security, "responsibility"),
  topic("WAVE 5", "인접 의사결정 유형에 검증된 기반을 재사용합니다", "같은 서비스 매핑, 근거 출처, 승인 경로, 관측자를 활용해 확장합니다.", "재사용:온톨로지 연결축|재사용:출처 근거|재사용:안전 운영 절차|재검증:새 대상과 영향 범위", docs.ontology, "flow"),
  topic("WAVE 5", "SRE 운영 경로를 종단까지 닫습니다", "감지부터 검증된 복구와 재발 종료까지 시나리오 근거를 만듭니다.", "감지:SLO 또는 Incident|복구:제어된 작업|효과:독립 관측|종료:재발과 보호 목표 확인", docs.constitution, "evidence"),
  topic("WAVE 5", "Change Safety의 전체 경로를 닫습니다", "그래프 차이와 제약 검토가 승인 조건과 변경 후 검증으로 이어져야 합니다.", "변경:정확한 리비전|평가:영향과 제약|승인:조건과 정족수|검증:변경 후 결과", docs.constitution, "flow"),
  topic("WAVE 5", "FinOps의 전체 경로를 닫습니다", "비용 이상 징후(Finding)나 예측(Forecast)이 실제 절감으로 이어져도 신뢰성 목표는 유지되어야 합니다.", "기회:비용 근거|작업:헌법상 적격 선택지|결과:실현된 절감|보호:SLO와 복구 목표 유지", docs.constitution, "evidence"),
  topic("WAVE 5", "복원력 적용 범위를 분리합니다", "DR과 카오스 시험은 서로 다른 기능이며 각각 복구와 안전한 실험 근거가 필요합니다.", "DR:RTO, RPO, failover, failback 근거|카오스:사람이 승인한 장애 주입|공통:영향 범위와 검증된 복구", docs.constitution, "matrix"),
  topic("GATE 5", "도메인별 전체 경로를 확인합니다", "한 성공 사례가 아니라 여섯 차원의 시나리오와 모든 안전 지표가 필요합니다.", "성공:기대 효과|경계:보류와 차단|충돌:도메인 간 목표|복원력:부분 실패, 복구, 재생", docs.constitution, "tree"),
  topic("WAVE 6", "조직별 범위를 정책과 설정으로 나눕니다", "공통 Core를 수정하지 않고 배포가 소유한 매핑과 목표를 공급합니다.", "공통 저장소:안정된 개념과 계약|배포:인스턴스와 운영 목표|downstream 배포판:주입된 구현", docs.ontology, "matrix"),
  topic("PROPOSAL", "조직 공통 승격 심의체를 운영합니다", "심의체 이름과 정족수는 배포가 정하지만, 현장 팀이 자기 결과만으로 권한을 올릴 수 없다는 원칙은 같습니다.", "현장 팀:관찰 모드 근거 제출|독립 검토:품질, 안전, 권한, 운영 준비|결정:승격, 보류, 범위 축소, 중지|등록부:정확한 기능과 리비전 상태", docs.security, "responsibility"),
  topic("PROPOSAL", "접근 권한 재인증 주기를 배포 정책에 넣습니다", "사용하지 않거나 지나치게 넓은 권한을 정기적으로 찾아 회수하고 감사합니다. 실제 빈도는 위험과 규제 요구에 맞춰 정합니다.", "목록:역할 할당과 실효 권한|검토:책임자와 사용 근거|조치:회수, 축소, 예외 만료|증적:다음 검토일과 감사 기록", docs.security, "timeline"),
  topic("WAVE 6", "FinOps와 LLMOps를 같은 포트폴리오에서 봅니다", "모델 호출과 플랫폼 비용을 검증된 운영 결과와 연결합니다.", "추론:T2 비율과 지출|플랫폼:서비스 비용|결과:가치 실현", docs.execution, "matrix"),
  topic("GATE 6", "확장 단위의 경제성을 업무별로 입증합니다", "팀 수나 사건 수만 세지 않고 사건, 변경, 최적화 단위의 비용과 검증된 편익을 분리해 비교합니다.", "사건당 비용:탐지부터 독립 효과 마감|변경당 비용:검토, 실행, 복구 포함|최적화당 비용:분석과 실현 확인 포함|제약:안전과 신뢰성 목표 유지", [docs.metrics, docs.constitution], "tree"),
  topic("WAVE 7", "여러 목표의 충돌을 중재합니다", "헌법상 적격한 후보만 Odin이 순위를 정하고 Saga가 충돌 판단을 감사합니다.", "Forseti:중재 요청 구성|Odin:선택, 보류, HIL|Saga:판단 계보 보존", docs.pantheon, "responsibility"),
  topic("WAVE 7", "도메인 간 근거 기준 시점을 통일합니다", "비용, 용량, 복원력 후보가 같은 대상과 기준 시점을 공유해야 합니다.", "대상:정확한 리소스|시간:공통 기준 시점|계보:책임자가 인증한 후보", docs.pantheon, "evidence"),
  topic("WAVE 7", "학습 사례군을 균형 있게 봉인합니다", "합성으로 표시된 운영 기록이나 중복 리비전은 실운영 승격 증적이 아닙니다.", "사례군:성공과 실패가 균형 잡힌 집단|리비전:FDAI와 시나리오 고정|근거:비합성, 최신, 완전, 충돌 없음|검토:생성자와 분리된 평가", docs.pantheon, "matrix"),
  topic("GATE 7", "학습이 권한을 높이지 않는지 검증합니다", "Pattern, RuleCandidate, 의미 계획은 검토 전까지 비활성 상태여야 합니다.", "후보:실행 권한 없음|검토:독립 수행|승격:카탈로그와 등록부", docs.ontologyPlatform, "tree"),
  topic("NOT_STARTED", "같은 산출물을 승격해 환경을 연결합니다", "동일한 서명 이미지가 dev, staging, prod를 이동하고 트래픽 카나리와 SLO 기반 되돌리기를 결합하는 목표입니다.", "dev:빌드, 공급망 증명, 통합|staging:대표성 있는 관찰과 카나리|prod:승인된 동일 산출물|되돌리기:SLO 위반 시 이전 리비전", docs.deployment, "timeline"),
  topic("NOT_STARTED", "자동 점진적 배포는 아직 구현되지 않았습니다", "트래픽 분할 카나리, SLO 기반 되돌리기, Console 블루/그린을 현재 기능으로 표시하지 않습니다.", "현재:보호된 계획과 적용|목표:자동 환경 승격|목표:트래픽 카나리와 SLO 되돌리기|목표:Console 블루/그린", docs.deployment, "matrix"),
  topic("IN_PROGRESS", "A3-E를 전사 확장의 전제로 두지 않습니다", "A3-E의 핵심 구성 요소는 구현됐지만 실행 경로에는 연결되지 않았습니다. 실운영 근거와 실행 중 권한을 유지하는 방식이 마련되기 전에는 사용할 수 없습니다.", "구현:평가기, 저장소, 스냅샷, 차단 장치|미연결:판단과 실행 경로|열린 설계:효과 전 기간 잠금 또는 임대|경계:실행 가능한 A3-E 권한 없음", docs.standingAuthority, "cards"),
  topic("PROPOSAL", "로드맵 현황표는 종료 기준만 집계합니다", "활동 완료율 대신 정확한 근거로 닫힌 의존성을 표시합니다.", "완료:보존된 근거|진행 중:구현됐으나 근거 미완료|미착수:구현되지 않음", docs.hardening, "matrix"),
  topic("PROPOSAL", "단계 간 의존성 변경은 ARB에서 재검토합니다", "새 서비스, 신원, 상태 책임자가 이전 통과 기준의 안전 가정을 바꾸면 다음 단계를 멈추고 영향 근거를 갱신합니다.", "변경:정확한 아키텍처 리비전|검토:제약과 영향|재개:갱신된 종료 근거", docs.operator, "evidence"),
  topic("PROPOSAL", "다음 계획 구간은 확산 0단계부터 2단계까지를 우선합니다", "기간, 책임자, 인력, 예산이 승인된 뒤 목표, 의사결정 목록, 온톨로지 연결축, 근거 등록부, 신원 분리를 순서대로 닫습니다.", "계획 시작:책임자, 기간, 우선순위, 가용 역량|중간 점검:형식화된 운영 사실과 근거 건전성|종료:의존성 실패 시 안전하게 차단되는 구성|다음 결정:첫 도메인 관찰 모드 승인", docs.constitution, "timeline"),
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
