import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { test } from "node:test";

const root = new URL("../", import.meta.url);

test("catalog records stable creation and review metadata for every manual", async () => {
  const catalog = JSON.parse(await readFile(new URL("catalog.json", root), "utf8"));

  assert.equal(catalog.schemaVersion, 3);
  assert.match(catalog.generatedAt, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
  assert.deepEqual(catalog.minimumSlidesByLevel, {
    L100: 10,
    L200: 25,
    L300: 40,
    L400: 50,
  });
  assert.equal(catalog.journey.stages.length, 5);
  assert.equal(catalog.manuals.length, 11);
  assert.equal(catalog.journey.stages[2].differentiator, true);
  for (const manual of catalog.manuals) {
    assert.match(manual.id, /^[a-z0-9-]+$/);
    assert.match(manual.createdAt, /^\d{4}-\d{2}-\d{2}$/);
    assert.match(manual.lastEditedAt, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(manual.lastEditedAt >= manual.createdAt);
    assert.ok(manual.reviewedAt === null || /^\d{4}-\d{2}-\d{2}$/.test(manual.reviewedAt));
    assert.match(manual.level ?? "L100", /^L[1-4]00$/);
    assert.match(manual.status, /^(complete|wip)$/);
    assert.ok(manual.slideCount > 0);
    if (manual.status === "complete") {
      assert.ok(manual.slideCount >= catalog.minimumSlidesByLevel[manual.level]);
    }
    assert.match(manual.coverImage, /^assets\/[a-z0-9-]+\.(?:jpeg|png)$/);
    await access(new URL(manual.coverImage, root));
  }
  assert.equal(
    new Set(catalog.manuals.map((manual) => manual.coverImage)).size,
    catalog.manuals.length,
  );
  const executiveBriefing = catalog.manuals.find((manual) => manual.id === "executive-briefing");
  assert.equal(executiveBriefing.status, "complete");
  assert.ok(catalog.manuals.every((manual) => manual.lastEditedAt === "2026-09-12"));
  assert.deepEqual(
    catalog.manuals.filter((manual) => manual.reviewedAt === null).map((manual) => manual.id),
    [
      "responsible-ai-security",
      "pilot-production",
      "ai-operating-model",
      "enterprise-scale-roadmap",
    ],
  );
  assert.ok(catalog.manuals
    .filter((manual) => manual.reviewedAt !== null)
    .every((manual) => manual.reviewedAt === "2026-09-13"));
  assert.ok(catalog.manuals.every((manual) => manual.status === "complete"));
});

test("unreviewed or changed manuals render DRAFT only on their covers", async () => {
  const script = await readFile(new URL("app.js", root), "utf8");
  const css = await readFile(new URL("styles.css", root), "utf8");

  assert.match(script, /!manual\.reviewedAt \|\| manual\.reviewedAt < manual\.lastEditedAt/);
  assert.match(script, /index === 0 \? draftOverlay\(manual\) : ""/);
  assert.match(script, /datetime="\$\{manual\.lastEditedAt\}"/);
  assert.match(css, /\.manual-draft-overlay \{[\s\S]+rotate\(-28deg\)/);
  assert.match(css, /\.manual-slide > \.manual-draft-overlay/);
});

test("completed manuals provide the catalog slide count and source evidence", async () => {
  const catalog = JSON.parse(await readFile(new URL("catalog.json", root), "utf8"));
  const { additionalManualSlides } = await import(new URL("manual-content.js", root));
  const expectedSlides = {
    "readiness-maturity": 32,
    "art-of-possible": 10,
    "value-prioritization": 25,
    "target-architecture": 25,
    "ontology-foundation": 40,
    "responsible-ai-security": 25,
    "pilot-production": 40,
    "sre-incident-response": 10,
    "ai-operating-model": 40,
    "enterprise-scale-roadmap": 50,
  };

  assert.deepEqual(
    Object.fromEntries(catalog.manuals
      .filter((manual) => manual.id !== "executive-briefing")
      .map((manual) => [manual.id, manual.slideCount])),
    expectedSlides,
  );
  for (const [id, expected] of Object.entries(expectedSlides)) {
    const slides = additionalManualSlides[id];
    assert.equal(slides.length, expected);
    assert.equal(new Set(slides.map((slide) => slide.title)).size, expected);
    assert.ok(slides.every((slide) => slide.content.includes("근거: docs/roadmap/") ||
      /class="(?:ontology-evidence-source|rm-source|vp-source|ta-source)" title="(?:docs|\.github|config)\/[^\"]+">근거: [^<]+<\/small>/.test(slide.content)));
  }
});

test("ontology foundation connects history, LLM limits, FDAI semantics, and worked scenarios", async () => {
  const { additionalManualSlides } = await import(new URL("manual-content.js", root));
  const slides = additionalManualSlides["ontology-foundation"];
  const titles = slides.map((slide) => slide.title).join("\n");
  const content = slides.map((slide) => `${slide.lead}\n${slide.content}`).join("\n");

  assert.equal(slides.length, 40);
  assert.ok(slides.every((slide) => slide.layout.startsWith("ontology-")));
  assert.equal(new Set(slides.map((slide) => slide.layout)).size, 40);
  assert.match(content, /아리스토텔레스는 기원전 4세기에 존재와 범주를 탐구했습니다/);
  assert.match(content, /ontology라는 용어를 쓰지는 않았습니다/);
  assert.match(titles, /여섯 가지 오류/);
  assert.match(titles, /RDF는 연결을, OWL은 형식 의미를 표현합니다/);
  assert.match(titles, /ObjectSet은 질문의 범위와 한도를 명시합니다/);
  assert.match(content, /존재자로서의(?:<br>|\s)존재/);
  assert.match(content.replace(/<[^>]+>/g, " "), /explicit specification\s+of a conceptualization/);
  assert.match(content, /OBSERVED/);
  assert.match(content, /DERIVED/);
  assert.match(content, /DESIRED/);
  assert.match(content, /EXECUTION/);
  assert.match(content, /SemanticInterpretationCandidate/);
  assert.match(content, /VerifiedSemanticPlan/);
  assert.match(content, /RESULT_LIMIT/);
  assert.match(content, /CANDIDATE_LIMIT/);
  assert.match(content, /TRAVERSAL_LIMIT/);
  assert.match(content, /oe-agent-system/);
  assert.match(content, /oe-category-grid/);
  assert.match(content, /oe-timeline/);
  assert.match(content, /oe-change-graph/);
  assert.match(content, /oe-incident-timeline/);
  assert.match(content, /oe-cost-options/);
  assert.match(content, /oe-learning-paths/);
  assert.match(content, /oe-adoption-steps/);
  assert.match(titles, /변경의 영향은 서비스의 관계를 따라 읽습니다/);
  assert.match(titles, /같은 시간의 이상이 같은 원인은 아닙니다/);
  assert.match(titles, /절감과 SLO 보호를 같은 결정에서 비교합니다/);
  assert.match(content, /OntologyChangeProposal/);
  assert.match(content, /실행 권한을 자동으로 높이지 않습니다/);
});

test("ontology foundation preserves the presentation font floor", async () => {
  const css = await readFile(new URL("ontology-foundation.css", root), "utf8");

  assert.match(css, /@container slide \(min-width: 1101px\)/);
  assert.match(css, /\.slide-copy h2 \{ font-size: 43px;/);
  assert.match(css, /\.slide-copy p \{ font-size: 24px;/);
  assert.match(css, /> strong \{ font-size: 24px;/);
  assert.match(css, /> span \{ font-size: 20px;/);
  assert.match(css, /> small \{ font-size: 17px;/);
  assert.match(css, /\.ontology-evidence-source \{ font-size: 13px;/);
});

test("ontology body uses one visual and takeaway without crowding the approved cover", async () => {
  const { buildOntologyFoundationDeck } = await import(new URL("ontology-foundation.js", root));
  const [cover, ...slides] = buildOntologyFoundationDeck();
  const css = await readFile(new URL("ontology-editorial.css", root), "utf8");
  assert.equal(slides.length, 39);
  assert.ok(!cover.layout.includes("ontology-editorial"));
  for (const slide of slides) {
    assert.match(slide.layout, /ontology-editorial$/);
    assert.equal([...slide.content.matchAll(/<section class="oe-visual/g)].length, 1);
    assert.equal([...slide.content.matchAll(/<p class="oe-takeaway"/g)].length, 1);
    assert.match(slide.content, /class="oe-state" data-state=/);
    assert.match(slide.content, /title="docs\/roadmap\//);
    assert.doesNotMatch(slide.content, /result_truncated|candidate_truncated|traversal_truncated/);
  }
  assert.match(css, /--oe-paper: #f5f3ee/);
  assert.match(css, /font-size: 43px/);
  assert.match(css, /font-size: 24px/);
  assert.match(css, /\.oe-visual::before \{ content: none/);
  assert.match(css, /box-shadow: none/);
  assert.match(css, /print-color-adjust: exact/);
  for (const entry of ["index.html", "library.html"]) {
    assert.match(await readFile(new URL(entry, root), "utf8"), /href="ontology-editorial\.css"/);
  }
});

test("ontology opening remains a sparse title page rather than a teaching slide", async () => {
  const { buildOntologyFoundationDeck } = await import(new URL("ontology-foundation.js", root));
  const [cover] = buildOntologyFoundationDeck();
  const text = cover.content.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ");

  assert.equal(cover.layout, "ontology-cover");
  assert.equal(cover.title, "온톨로지");
  assert.equal(cover.lead, "AI의 언어를 운영의 의미로");
  assert.equal(cover.deckTitle, undefined);
  assert.ok(`${cover.title}${cover.lead}${text}`.replace(/\s/g, "").length < 120);
  assert.match(cover.content, /class="ontology-opening-art"[^>]+aria-hidden="true"/);
  assert.match(cover.content, /title="docs\/roadmap\/architecture\/operating-ontology\.md \| docs\/roadmap\/architecture\/fdai-constitution\.md"/);
  assert.doesNotMatch(cover.content, /<(?:article|figcaption|li|p|text)\b/);
  assert.doesNotMatch(cover.content, /data-semantic-node|data-semantic-edge|<img|https?:\/\//);
});

test("ontology opening styles stay cover-scoped and ship in both viewers", async () => {
  const css = await readFile(new URL("ontology-opening.css", root), "utf8");
  const rules = css.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{/g);
  for (const [, selector] of rules) {
    if (selector.trim().startsWith("@")) continue;
    for (const part of selector.split(",")) {
      assert.ok(part.trim().startsWith(".manual-slide.slide-ontology-cover"), part.trim());
    }
  }
  assert.match(css, /font-size: 92px/);
  assert.match(css, /font-size: 28px/);
  assert.doesNotMatch(css, /ontology-opening-(?:map|journey|thesis|boundary)/);
  assert.match(css, /print-color-adjust: exact/);
  for (const entry of ["index.html", "library.html"]) {
    const html = await readFile(new URL(entry, root), "utf8");
    assert.match(html, /href="ontology-opening\.css"/);
    assert.ok(html.indexOf('href="ontology-opening.css"') > html.indexOf('href="ontology-foundation.css"'));
  }
});

test("non-ontology manuals use briefing layouts and preserve architecture boundaries", async () => {
  const { additionalManualSlides } = await import(new URL("manual-content.js", root));
  const briefingIds = [
    "readiness-maturity",
    "art-of-possible",
    "value-prioritization",
    "target-architecture",
    "responsible-ai-security",
    "pilot-production",
    "sre-incident-response",
    "ai-operating-model",
    "enterprise-scale-roadmap",
  ];

  for (const id of briefingIds) {
    const slides = additionalManualSlides[id];
    assert.ok(slides.every((slide) => slide.layout.startsWith("briefing-")));
    assert.ok(new Set(slides.map((slide) => slide.layout.split(" ")[0])).size >= 8);
  }

  const contentFor = (id) => additionalManualSlides[id]
    .map((slide) => `${slide.title}\n${slide.lead}\n${slide.content}`)
    .join("\n");
  assert.match(contentFor("readiness-maturity"), /각 기준선과 처리군의 최소 표본/);
  assert.match(contentFor("value-prioritization"), /근거 준비도는 가중치가 아니라 포트폴리오의 입장 조건/);
  assert.match(contentFor("target-architecture"), /Document Processing Worker/);
  assert.match(contentFor("responsible-ai-security"), /snapshot_restore/);
  assert.match(contentFor("responsible-ai-security"), /프롬프트 주입/);
  assert.match(contentFor("pilot-production"), /A3-E 적용 여부/);
  assert.match(contentFor("sre-incident-response"), /SRE 운영을 알림 처리에서 검증된 서비스 회복으로 전환할 수 있습니다/);
  assert.match(contentFor("sre-incident-response"), /장애 조치는 전환부터 복귀까지 하나의 계획으로 관리합니다/);
  assert.match(contentFor("sre-incident-response"), /0초로 계산하지 않음/);
  assert.match(contentFor("sre-incident-response"), /assets\/sre-incident-response\.png/);
  assert.match(contentFor("ai-operating-model"), /고정된 전체 에이전트/);
  assert.match(contentFor("enterprise-scale-roadmap"), /C5 근거 건전성/);
});

test("SRE incident response deck uses decision-ready non-repeating visuals", async () => {
  const { additionalManualSlides } = await import(new URL("manual-content.js", root));
  const slides = additionalManualSlides["sre-incident-response"];
  const content = slides.map((slide) => `${slide.title}\n${slide.lead}\n${slide.content}`).join("\n");

  assert.equal(slides.length, 10);
  assert.equal(new Set(slides.map((slide) => slide.layout.split(" ")[0])).size, 10);
  for (const marker of [
    "sre-signal-board",
    "sre-service-map",
    "sre-decision-system",
    "sre-option-board",
    "sre-authority-map",
    "sre-failover-plan",
    "sre-verification-board",
    "sre-mttr-view",
    "sre-outcome-contract",
  ]) {
    assert.match(content, new RegExp(marker));
  }
  assert.match(content, /Heimdall\(관찰·예측 담당\) 에이전트/);
  assert.match(content, /Thor\(실행 담당\) 에이전트/);
  assert.match(content, /customer-link/);
  assert.match(content, /vertical-link/);
  assert.match(content, /MTTR.*중앙값.*p90/s);
  assert.match(content, /첫 검증 시나리오 1개 선택/);
});

test("Art of the Possible deck contrasts today with the target operating day", async () => {
  const { additionalManualSlides } = await import(new URL("manual-content.js", root));
  const slides = additionalManualSlides["art-of-possible"];
  const content = slides.map((slide) => `${slide.title}\n${slide.lead}\n${slide.content}`).join("\n");
  const css = await readFile(new URL("art-of-possible.css", root), "utf8");

  assert.equal(slides.length, 10);
  assert.equal(new Set(slides.map((slide) => slide.layout.split(" ")[0])).size, 10);
  assert.ok(slides.every((slide) => slide.layout.includes("deck-art-of-possible")));
  for (const marker of [
    "aop-today-board",
    "aop-day-compare",
    "aop-scene-grid",
    "aop-impact-map",
    "aop-cost-ladder",
    "aop-lane-row",
    "aop-ceiling-chart",
    "aop-closure-chain",
    "aop-status-band",
  ]) {
    assert.match(content, new RegExp(marker));
  }
  assert.match(content, /Huginn\(이벤트 수집 담당\) 에이전트/);
  assert.match(content, /Forseti\(판정 담당\) 에이전트/);
  assert.match(content, /Njord\(비용 담당\) 에이전트/);
  assert.match(content, /Bragi\(대화 변환 담당\) 에이전트/);
  assert.match(content, /Saga\(감사 담당\) 에이전트/);
  assert.match(content, /Vidar\(복구 담당\) 에이전트/);
  assert.match(content, /검토 승인은 리소스 변경 권한이 아닙니다/);
  assert.match(content, /침묵은 승인이 아님/);
  assert.match(content, /가장 낮은 상한 하나가 전체 권한을 정합니다/);
  assert.match(content, /ExpectedEffect/);
  assert.match(content, /ObservedOutcome/);
  assert.match(content, /A3-E 실행 연결과 자동 환경 승격은 아직 사용할 수 없습니다/);
  for (const example of ["예시 시나리오", "예시 토폴로지", "표시된 비율은 설명을 위한 예시입니다"]) {
    assert.ok(content.includes(example), example);
  }
  assert.match(css, /\.slide-copy h2 \{[\s\S]{0,220}font-size: 43px;/);
  assert.match(css, /\.slide-copy p \{[\s\S]{0,180}font-size: 24px;/);
  assert.match(css, /--aop-human: #a8480c/);
  assert.match(css, /--aop-evidence: #0f6cbd/);
  assert.match(css, /--aop-verify: #0e6f61/);
  assert.match(css, /repeating-linear-gradient/);
  assert.match(css, /print-color-adjust: exact/);
  for (const entry of ["index.html", "library.html"]) {
    const html = await readFile(new URL(entry, root), "utf8");
    assert.match(html, /href="art-of-possible\.css"/);
  }
});

test("completed manuals retain verified hardening rounds", async () => {
  const evidence = JSON.parse(
    await readFile(new URL("validation-evidence.json", root), "utf8"),
  );
  const catalog = JSON.parse(await readFile(new URL("catalog.json", root), "utf8"));
  const completedIds = catalog.manuals.map((manual) => manual.id);

  assert.deepEqual(evidence.viewports, ["1440x900", "993x641", "390x844"]);
  assert.deepEqual(evidence.manuals.map((manual) => manual.id), completedIds);
  for (const manual of evidence.manuals) {
    assert.ok(manual.hardening.length >= 1);
    assert.ok(manual.hardening.every((round) =>
      round.finding && round.correction && round.rerendered === "passed"));
    assert.equal(manual.validation.responsiveRoundsPassed, manual.hardening.length);
    assert.equal(manual.validation.fullscreenRoundsPassed, manual.hardening.length);
    assert.equal(manual.validation.pdfRoundsPassed, manual.hardening.length);
    assert.equal(manual.validation.pdfPages, manual.slideCount);
    assert.equal(manual.validation.aspectRatio, "16:9");
    assert.equal(manual.validation.clippedTextFindings, 0);
    assert.ok(manual.references.length >= 2);
  }
});

test("selected PPT artwork keeps repository-safe provenance", async () => {
  const provenance = JSON.parse(
    await readFile(new URL("assets/provenance.json", root), "utf8"),
  );

  assert.equal(provenance.assets.length, 13);
  assert.equal(provenance.layoutReference.source, "Microsoft_Brand_Template_May2023.potx");
  assert.equal(provenance.layoutReference.logoInches.height, 0.32);
  assert.equal(provenance.layoutReference.contentTitleInches.y, 0.64);
  assert.equal(provenance.layoutReference.contentBodyInches.y, 1.74);
  assert.ok(provenance.processing.includes("Source metadata removed from published derivatives"));
  assert.ok(provenance.assets.some((asset) => asset.path === "microsoft-logo.png"));
  assert.ok(provenance.assets.some((asset) => asset.path === "fdai-console-sign-in.png"));
  assert.ok(provenance.assets.some((asset) => asset.path === "sre-incident-response.png"));
  for (const asset of provenance.assets) {
    await access(new URL(`assets/${asset.path}`, root));
  }
});

test("console prototype exposes the help drawer accessibility contract", async () => {
  const html = await readFile(new URL("index.html", root), "utf8");

  assert.match(html, /id="help-trigger"[\s\S]+aria-controls="help-drawer"/);
  assert.match(html, /id="help-drawer"[\s\S]+role="dialog"[\s\S]+aria-modal="true"/);
  assert.match(html, /id="slide-announcement"[\s\S]+role="status"[\s\S]+aria-live="polite"/);
});

test("print stylesheet emits one 16:9 page per slide", async () => {
  const css = await readFile(new URL("styles.css", root), "utf8");

  assert.match(css, /@page\s*\{\s*size:\s*16in 9in;\s*margin:\s*0;/);
  assert.match(css, /break-after:\s*page;/);
});

test("library deep links preserve the requested manual and slide", async () => {
  const script = await readFile(new URL("app.js", root), "utf8");

  assert.match(script, /searchParams\.get\("manual"\)/);
  assert.match(script, /document\.body\.dataset\.manualId/);
  assert.match(script, /searchParams\.get\("slide"\)/);
  assert.match(script, /openViewer\(catalog\.manuals\[requestedIndex\], requestedSlide\)/);
  assert.match(script, /new URL\(`\$\{manual\.id\}\.html`, window\.location\.href\)/);
  assert.match(script, /url\.searchParams\.set\("slide", String\(slideIndex \+ 1\)\)/);
  assert.match(script, /window\.history\.replaceState\(null, "", url\)/);
});

test("executive briefing presents the FDAI architecture and adoption gates", async () => {
  const script = await readFile(new URL("app.js", root), "utf8");
  const agentNames = [
    "Odin", "Thor", "Forseti", "Huginn", "Heimdall",
    "Vidar", "Var", "Bragi", "Saga", "Mimir",
    "Muninn", "Norns", "Njord", "Freyr", "Loki",
  ];

  for (const name of agentNames) {
    assert.match(script, new RegExp(`<b>${name} 에이전트</b>`));
  }
  assert.match(script, /15개 에이전트가 하나의 운영 흐름에서 책임을 나눕니다/);
  assert.doesNotMatch(script, /작은 결정을 사람보다 빠르게 늘립니다/);
  assert.match(script, /FDAI는 조직에 축적된 운영 규칙과 표준 절차를 먼저 적용합니다/);
  assert.match(script, /SOVEREIGN-BY-DESIGN/);
  assert.match(script, /데이터 위치, 접속 경로, 신원, AI 사용 범위를 직접 통제할 수 있습니다/);
  assert.match(script, /데이터 위치를 고객이 결정/);
  assert.match(script, /접근 권한과 키를 고객이 통제/);
  assert.doesNotMatch(script, /executive-sovereign-loop/);
  assert.match(script, /운영 규모가 커져도 충분한 판단이 가능한 최소 Tier에서 처리합니다/);
  assert.match(script, /네 가지 준비 영역을 확인하면 시작 범위와 보완 계획을 정할 수 있습니다/);
  assert.doesNotMatch(script, /하나라도 미충족이면 FDAI 도입 대상이 아닙니다/);
  assert.doesNotMatch(script, /만병통치약이 아닙니다/);
  assert.match(script, /관찰 모드 시작 범위/);
  assert.match(script, /Norns\(학습 후보 제안 담당\) 에이전트/);
  assert.match(script, /Mimir\(규칙 검토 담당\) 에이전트/);
  assert.match(script, /첫 검증 시나리오 1개 선택/);
  assert.match(script, /assets\/fdai-console-sign-in\.png/);
  assert.match(script, /도입 검토를 시작하세요/);
});

test("Executive and SRE decks load the presentation font standard", async () => {
  const library = await readFile(new URL("library.html", root), "utf8");
  const css = await readFile(new URL("presentation-standard.css", root), "utf8");

  assert.match(library, /href="presentation-standard\.css"/);
  assert.match(css, /slide-executive-/);
  assert.match(css, /deck-sre-incident-response/);
  assert.match(css, /slide-copy p[\s\S]+font-size: 24px/);
  assert.match(css, /evidence-source[\s\S]+font-size: 13px/);
});

test("Cover Flow preserves card clicks and captures only dragging pointers", async () => {
  const script = await readFile(new URL("app.js", root), "utf8");
  const css = await readFile(new URL("styles.css", root), "utf8");
  const pointerDownStart = script.indexOf('flow.addEventListener("pointerdown"');
  const pointerMoveStart = script.indexOf('flow.addEventListener("pointermove"');
  const pointerUpStart = script.indexOf('flow.addEventListener("pointerup"');
  const pointerDownSource = script.slice(pointerDownStart, pointerMoveStart);
  const pointerMoveSource = script.slice(pointerMoveStart, pointerUpStart);

  assert.match(script, /setPointerCapture\(event\.pointerId\)/);
  assert.match(script, /applyCoverflowDrag\(flow, drag\.deltaX\)/);
  assert.doesNotMatch(pointerDownSource, /setPointerCapture/);
  assert.match(pointerMoveSource, /Math\.abs\(rawDeltaX\) > 8/);
  assert.match(pointerMoveSource, /setPointerCapture\(event\.pointerId\)/);
  assert.match(script, /manual\.status === "wip"/);
  assert.match(script, /manual-wip-overlay/);
  assert.match(css, /\.manual-wip-overlay \{/);
  assert.match(css, /\.coverflow\.dragging \.coverflow-item \{ transition: none; \}/);
});

test("viewer fullscreen control tracks browser fullscreen state", async () => {
  const script = await readFile(new URL("app.js", root), "utf8");
  const css = await readFile(new URL("styles.css", root), "utf8");
  const library = await readFile(new URL("library.html", root), "utf8");
  const koreanMessages = await readFile(new URL("messages.ko.json", root), "utf8");

  assert.match(library, /id="fullscreen-manual"[^>]+aria-pressed="false"/);
  assert.match(script, /const fullscreenRoot = stage/);
  assert.doesNotMatch(script, /const fullscreenRoot = document\.documentElement/);
  assert.match(script, /await fullscreenRoot\.requestFullscreen\(\)/);
  assert.match(script, /document\.addEventListener\("fullscreenchange", syncFullscreenButton\)/);
  assert.match(script, /fullscreenButton\.setAttribute\("aria-pressed", String\(active\)\)/);
  assert.match(script, /t\("viewer\.exitFullscreen"\)/);
  assert.match(koreanMessages, /"exitFullscreen": "전체 화면 종료"/);
  assert.match(script, /manual_studio_fullscreen_failed/);
  assert.match(css, /\.slide-stage:fullscreen \{/);
  assert.match(css, /\.slide-stage:fullscreen \.manual-slide \{/);
});

test("viewer uniformly scales one fixed presentation canvas", async () => {
  const script = await readFile(new URL("app.js", root), "utf8");
  const css = await readFile(new URL("styles.css", root), "utf8");
  const slideStyles = await Promise.all([
    "manual-decks.css",
    "executive-deck.css",
    "executive-story.css",
    "sre-incident-response.css",
    "art-of-possible.css",
  ].map((path) => readFile(new URL(path, root), "utf8")));

  assert.match(script, /slideCanvas = Object\.freeze\(\{ width: 1536, height: 864 \}\)/);
  assert.match(script, /Math\.min\([\s\S]+availableWidth \/ slideCanvas\.width/);
  assert.match(script, /slideResizeObserver = new ResizeObserver\(updateSlideScale\)/);
  assert.match(script, /slideResizeObserver\.observe\(stage\)/);
  assert.match(script, /window\.addEventListener\("resize", updateSlideScale\)/);
  assert.match(script, /requestAnimationFrame\(updateSlideScale\)/);
  assert.match(script, /document\.fonts\.ready\.then\(updateSlideScale\)/);
  assert.match(css, /--slide-width: 1536px/);
  assert.match(css, /--slide-height: 864px/);
  assert.match(css, /scale\(var\(--slide-scale\)\)/);
  assert.match(css, /container-name: slide/);
  assert.doesNotMatch(css, /--slide-width:\s*min\(/);
  const evidence = JSON.parse(
    await readFile(new URL("validation-evidence.json", root), "utf8"),
  );
  assert.match(evidence.method.fixedCanvas, /All 300 slides/);
  assert.match(evidence.method.pdf, /All 300 pages/);
  for (const slideStyle of slideStyles) {
    assert.doesNotMatch(slideStyle, /\d(?:\.\d+)?vw\b/);
  }
});
