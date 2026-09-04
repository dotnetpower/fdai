import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import { test } from "node:test";

const root = new URL("../", import.meta.url);

test("catalog records stable creation metadata for every manual", async () => {
  const catalog = JSON.parse(await readFile(new URL("catalog.json", root), "utf8"));

  assert.equal(catalog.schemaVersion, 2);
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
  assert.equal(catalog.manuals.find((manual) => manual.id === "executive-briefing").status, "complete");
  assert.ok(catalog.manuals.every((manual) => manual.status === "complete"));
});

test("completed manuals provide the catalog slide count and source evidence", async () => {
  const catalog = JSON.parse(await readFile(new URL("catalog.json", root), "utf8"));
  const { additionalManualSlides } = await import(new URL("manual-content.js", root));
  const expectedSlides = {
    "readiness-maturity": 25,
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
    assert.ok(slides.every((slide) => slide.content.includes("근거: docs/roadmap/")));
  }
});

test("ontology foundation connects LLM, RAG, ontology, and current FDAI implementation", async () => {
  const { additionalManualSlides } = await import(new URL("manual-content.js", root));
  const slides = additionalManualSlides["ontology-foundation"];
  const titles = slides.map((slide) => slide.title).join("\n");
  const content = slides.map((slide) => `${slide.lead}\n${slide.content}`).join("\n");

  assert.equal(slides.length, 40);
  assert.ok(slides.every((slide) => slide.layout.startsWith("ontology-")));
  assert.match(titles, /LLM은 다음 토큰의 확률을 계산합니다/);
  assert.match(titles, /RAG는 생성 전에 외부 근거를 회수합니다/);
  assert.match(titles, /다섯 운영 렌즈와 다섯 선언 종류는 다릅니다/);
  assert.match(content, /3,405/);
  assert.match(content, /80<\/strong><span>검토된 클래스 멤버십/);
  assert.match(content, /17<\/strong><span>지원하는 QueryNodeKind/);
  assert.match(content, /current_state_only/);
  assert.match(content, /384차원<\/strong><span>구현된 메모리 내 의미 검색/);
  assert.match(content, /OntologyChangeProposal/);
  assert.doesNotMatch(content, /77:검토된 클래스 멤버십/);
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
  assert.match(contentFor("value-prioritization"), /근거 준비도는 가중치가 아니라 적격성 기준/);
  assert.match(contentFor("target-architecture"), /문서 처리 Worker/);
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
  assert.match(script, /searchParams\.get\("slide"\)/);
  assert.match(script, /openViewer\(catalog\.manuals\[requestedIndex\], requestedSlide\)/);
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

test("Cover Flow supports pointer-capture dragging", async () => {
  const script = await readFile(new URL("app.js", root), "utf8");
  const css = await readFile(new URL("styles.css", root), "utf8");

  assert.match(script, /setPointerCapture\(event\.pointerId\)/);
  assert.match(script, /applyCoverflowDrag\(flow, drag\.deltaX\)/);
  assert.match(script, /manual\.status === "wip"/);
  assert.match(script, /manual-wip-overlay/);
  assert.match(css, /\.manual-wip-overlay \{/);
  assert.match(css, /\.coverflow\.dragging \.coverflow-item \{ transition: none; \}/);
});

test("viewer fullscreen control tracks browser fullscreen state", async () => {
  const script = await readFile(new URL("app.js", root), "utf8");
  const css = await readFile(new URL("styles.css", root), "utf8");
  const library = await readFile(new URL("library.html", root), "utf8");

  assert.match(library, /id="fullscreen-manual"[^>]+aria-pressed="false"/);
  assert.match(script, /const fullscreenRoot = stage/);
  assert.doesNotMatch(script, /const fullscreenRoot = document\.documentElement/);
  assert.match(script, /await fullscreenRoot\.requestFullscreen\(\)/);
  assert.match(script, /document\.addEventListener\("fullscreenchange", syncFullscreenButton\)/);
  assert.match(script, /fullscreenButton\.setAttribute\("aria-pressed", String\(active\)\)/);
  assert.match(script, /전체 화면 종료/);
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
