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
  assert.equal(catalog.manuals.length, 10);
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
    assert.match(manual.coverImage, /^assets\/[a-z0-9-]+\.jpeg$/);
    await access(new URL(manual.coverImage, root));
  }
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

test("completed manuals retain three verified hardening rounds", async () => {
  const evidence = JSON.parse(
    await readFile(new URL("validation-evidence.json", root), "utf8"),
  );
  const catalog = JSON.parse(await readFile(new URL("catalog.json", root), "utf8"));
  const completedIds = catalog.manuals
    .filter((manual) => manual.id !== "executive-briefing")
    .map((manual) => manual.id);

  assert.deepEqual(evidence.viewports, ["1440x900", "993x641", "390x844"]);
  assert.deepEqual(evidence.manuals.map((manual) => manual.id), completedIds);
  for (const manual of evidence.manuals) {
    assert.equal(manual.hardening.length, 3);
    assert.ok(manual.hardening.every((round) =>
      round.finding && round.correction && round.rerendered === "passed"));
    assert.equal(manual.validation.responsiveRoundsPassed, 3);
    assert.equal(manual.validation.fullscreenRoundsPassed, 3);
    assert.equal(manual.validation.pdfRoundsPassed, 3);
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

  assert.equal(provenance.assets.length, 12);
  assert.equal(provenance.layoutReference.source, "Microsoft_Brand_Template_May2023.potx");
  assert.equal(provenance.layoutReference.logoInches.height, 0.32);
  assert.equal(provenance.layoutReference.contentTitleInches.y, 0.64);
  assert.equal(provenance.layoutReference.contentBodyInches.y, 1.74);
  assert.ok(provenance.processing.includes("Source metadata removed from published derivatives"));
  assert.ok(provenance.assets.some((asset) => asset.path === "microsoft-logo.png"));
  assert.ok(provenance.assets.some((asset) => asset.path === "fdai-console-sign-in.png"));
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
    assert.match(script, new RegExp(`<b>${name}</b>`));
  }
  assert.match(script, /FDAI는 15개 에이전트가 함께 일하는 디지털 조직입니다/);
  assert.doesNotMatch(script, /작은 결정을 사람보다 빠르게 늘립니다/);
  assert.match(script, /FDAI는 숙련된 운영자처럼 검증된 규칙과 지식을 먼저 적용하고/);
  assert.match(script, /SOVEREIGN-BY-DESIGN/);
  assert.match(script, /FDAI는 고객의 데이터 주권 안에서 운영됩니다/);
  assert.match(script, /데이터 위치를 고객이 결정/);
  assert.match(script, /접근 권한과 키를 고객이 통제/);
  assert.doesNotMatch(script, /executive-sovereign-loop/);
  assert.match(script, /수천 개로 늘어나는 운영 조건은 규칙으로 먼저 판단해야 합니다/);
  assert.match(script, /FDAI 도입은 네 가지 준비 조건을 충족한 범위에서 시작합니다/);
  assert.match(script, /하나라도 미충족이면 FDAI 도입 대상이 아닙니다/);
  assert.doesNotMatch(script, /만병통치약이 아닙니다/);
  assert.match(script, /관찰 모드 검토 가능/);
  assert.match(script, /assets\/fdai-console-sign-in\.png/);
  assert.match(script, /도입 검토를 시작하세요/);
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
  const library = await readFile(new URL("library.html", root), "utf8");

  assert.match(library, /id="fullscreen-manual"[^>]+aria-pressed="false"/);
  assert.match(script, /const fullscreenRoot = document\.documentElement/);
  assert.match(script, /await fullscreenRoot\.requestFullscreen\(\)/);
  assert.match(script, /document\.addEventListener\("fullscreenchange", syncFullscreenButton\)/);
  assert.match(script, /fullscreenButton\.setAttribute\("aria-pressed", String\(active\)\)/);
  assert.match(script, /전체 화면 종료/);
  assert.match(script, /manual_studio_fullscreen_failed/);
});
