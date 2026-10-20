const references = {
  constitution: ["architecture/fdai-constitution.md", "안전 원칙", "Safety principles"],
  ontology: ["architecture/operating-ontology-platform.md", "운영 온톨로지", "Operating ontology"],
  graph: ["architecture/continuous-operational-instance-graph.md", "현재 운영 그래프", "Current operating graph"],
  documents: ["rules-and-detection/document-ontology-distillation.md", "문서 변경 제안", "Document proposals"],
  causality: ["rules-and-detection/causal-incident-graph.md", "원인 가설 검증", "Causal verification"],
  llm: ["architecture/llm-strategy.md", "판단 수준", "Decision tiers"],
  agents: ["agents/agent-pantheon.md", "에이전트 책임", "Agent ownership"],
  execution: ["decisioning/execution-model.md", "실행 조건", "Execution conditions"],
  deployment: ["deployment/deploy-and-onboard.md", "Azure 배포 구성", "Azure deployment"],
  indexRuntime: ["services/core-control-plane/src/fdai/runtime/ontology_index_runtime.py", "후보 검색 기본 설정", "Candidate search defaults"],
};

export function pitchSlide(locale, { id, chapter, title, lead, visual, takeaway, sources, kind, example = false, cover = false }) {
  const korean = locale === "ko";
  const paths = sources.map(key => {
    if (!Object.hasOwn(references, key)) throw new Error(`Unknown L100 source: ${key}`);
    const path = references[key][0];
    return path.startsWith("services/") ? path : `docs/roadmap/${path}`;
  });
  const links = sources.map((key, index) =>
    `<a href="https://github.com/dotnetpower/fdai/blob/main/${paths[index]}" target="_blank" rel="noreferrer">${references[key][korean ? 1 : 2]}</a>`,
  ).join("<span aria-hidden=\"true\"> / </span>");
  return {
    eyebrow: cover ? "MICROSOFT KOREA CSU · INTERNAL DEVELOPMENT" : chapter,
    ...(cover ? { brandLogo: "assets/microsoft-logo.png", deckTitle: "FDAI L100 Pitch Deck" } : {}),
    title,
    lead,
    layout: `l100-calm deck-l100-calm lp-${id}`,
    pitch: { id, kind, example, sources: paths },
    content: `<div class="lp-layout">
      <div class="lp-visual">${example ? `<span class="lp-example">${korean ? "설명용 예시 · 실제 운영 결과 아님" : "Illustrative example · not an operational result"}</span>` : ""}${visual}</div>
      <p class="lp-takeaway">${takeaway}</p>
      <small class="l100-source">${korean ? "근거" : "Sources"}: ${links}</small>
    </div>`,
  };
}

export function resourceGraph(locale) {
  const korean = locale === "ko";
  return `<svg class="lp-resource-graph" viewBox="0 0 1240 320" role="img" aria-label="${korean ? "API가 사용하는 DB와 그 관계의 확인 시점·출처를 살펴보는 예시" : "Example: identify the database used by an API and check the relation's reference time and source"}">
    <defs><marker id="lp-arrow-${locale}" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="10" markerHeight="10" orient="auto"><path d="M0 0L10 5L0 10Z"></path></marker></defs>
    <rect class="lp-graph-node" data-lp-node="api" x="60" y="64" width="380" height="144" rx="8"></rect>
    <rect class="lp-graph-node" data-lp-node="db" x="800" y="64" width="380" height="144" rx="8"></rect>
    <line data-lp-from="api" data-lp-to="db" data-lp-relation="depends_on" x1="440" y1="136" x2="800" y2="136" marker-end="url(#lp-arrow-${locale})"></line>
    <foreignObject x="76" y="89" width="348" height="100"><div xmlns="http://www.w3.org/1999/xhtml" class="lp-node-label"><strong>API</strong><span>${korean ? "사용자 요청 처리" : "Handles user requests"}</span></div></foreignObject>
    <foreignObject x="816" y="89" width="348" height="100"><div xmlns="http://www.w3.org/1999/xhtml" class="lp-node-label"><strong>DB</strong><span>${korean ? "API가 사용하는 데이터베이스" : "Database used by the API"}</span></div></foreignObject>
    <foreignObject x="465" y="80" width="310" height="44"><div xmlns="http://www.w3.org/1999/xhtml" class="lp-edge-label">${korean ? "DB 사용" : "Uses database"}</div></foreignObject>
    <foreignObject x="60" y="236" width="1120" height="76"><div xmlns="http://www.w3.org/1999/xhtml" class="lp-graph-caption">${korean ? "화살표는 API가 DB를 사용하는 관계를 나타냅니다.<br>그 관계를 확인한 시점과 출처도 함께 살펴봅니다." : "The arrow shows which database the API uses.<br>Check when and from which source the relation was confirmed."}</div></foreignObject>
  </svg>`;
}
