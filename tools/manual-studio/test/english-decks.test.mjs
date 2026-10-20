import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { executiveBriefingSlides } from "../executive-briefing.en.js";
import { l100PitchDeckSlides } from "../l100-pitch-deck.en.js";
import { l100PitchDeckSlides as koreanL100PitchDeckSlides } from "../l100-pitch-deck.js";
import { additionalManualSlides as englishAdditionalManualSlides } from "../manual-content.en.js";
import { additionalManualSlides as koreanAdditionalManualSlides } from "../manual-content.js";

const root = new URL("../", import.meta.url);
const hangulPattern = /[가-힣]/;

function normalizedStructure(slide) {
  return {
    layout: slide.layout,
    architecture: slide.architecture?.id,
    ontology: slide.ontology?.id,
    priority: slide.priority?.id,
    readiness: slide.readiness?.id,
  };
}

test("English content covers all catalog manuals and declared slides", async () => {
  const catalog = JSON.parse(await readFile(new URL("catalog.json", root), "utf8"));
  const englishDecks = {
    "executive-briefing": executiveBriefingSlides,
    "l100-pitch-deck": l100PitchDeckSlides,
    ...englishAdditionalManualSlides,
  };

  assert.deepEqual(Object.keys(englishDecks), catalog.manuals.map((manual) => manual.id));
  for (const manual of catalog.manuals) {
    assert.equal(englishDecks[manual.id].length, manual.slideCount, manual.id);
  }
  assert.equal(
    Object.values(englishDecks).reduce((total, slides) => total + slides.length, 0),
    322,
  );
});

test("English decks contain no Korean fallback text", () => {
  const englishDecks = {
    "executive-briefing": executiveBriefingSlides,
    "l100-pitch-deck": l100PitchDeckSlides,
    ...englishAdditionalManualSlides,
  };

  for (const [manualId, slides] of Object.entries(englishDecks)) {
    assert.doesNotMatch(JSON.stringify(slides), hangulPattern, manualId);
    for (const [index, slide] of slides.entries()) {
      assert.equal(typeof slide.title, "string", `${manualId} slide ${index + 1} title`);
      assert.equal(typeof slide.lead, "string", `${manualId} slide ${index + 1} lead`);
      assert.ok(slide.title.replace(/<[^>]+>/g, "").trim(), `${manualId} slide ${index + 1}`);
    }
  }
});

test("L100 pitch cover identifies its internal-development status in both locales", () => {
  const koreanSlide = koreanL100PitchDeckSlides[0];
  const englishSlide = l100PitchDeckSlides[0];

  assert.equal(koreanSlide.eyebrow, "MICROSOFT KOREA CSU · INTERNAL DEVELOPMENT");
  assert.equal(englishSlide.eyebrow, koreanSlide.eyebrow);
  assert.match(koreanSlide.lead, /현재 상태에 대한 정보를 바탕으로/);
  assert.match(koreanSlide.lead, /목표와 실행 권한을 정하고/);
  assert.match(koreanSlide.lead, /별도의 관측을 통해 작업 결과를 검증합니다/);
  assert.match(koreanSlide.lead, /Microsoft의 공식 제품이나 Azure 서비스가 아닙니다/);
  assert.match(englishSlide.lead, /not an official Microsoft product or Azure service/);
  assert.match(englishSlide.lead, /developed and validated internally by Microsoft Korea CSU/);
});

test("L100 operating challenge names the context-connection bottleneck directly", () => {
  assert.equal(
    koreanL100PitchDeckSlides[2].title,
    "운영 대응은 흩어진 정보를 하나의 판단으로 연결하는 과정에서 지연됩니다",
  );
  assert.match(koreanL100PitchDeckSlides[2].lead, /로그와 메트릭, 최근 변경, 서비스 관계/);
  assert.match(koreanL100PitchDeckSlides[2].content, /운영자가 단계 사이의 맥락을 매번 직접 연결합니다/);
  assert.match(l100PitchDeckSlides[2].title, /scattered information is connected into one decision/);
  assert.match(l100PitchDeckSlides[2].content, /Operators reconnect context at every handoff/);
});

test("L100 product identity separates product value from delivery status", () => {
  assert.equal(
    koreanL100PitchDeckSlides[1].title,
    "FDAI는 운영 신호를 판단, 실행, 결과 검증으로 연결합니다",
  );
  assert.match(koreanL100PitchDeckSlides[1].lead, /자율 클라우드 운영 컨트롤 플레인/);
  assert.match(koreanL100PitchDeckSlides[1].content, /WHAT FDAI DOES/);
  assert.match(koreanL100PitchDeckSlides[1].content, /PRODUCT STATUS/);
  assert.match(koreanL100PitchDeckSlides[1].content, /사람이 목표와 실행 권한을 정하고/);
  assert.match(l100PitchDeckSlides[1].title, /decisions, execution, and outcome verification/);
  assert.match(l100PitchDeckSlides[1].content, /internal solution developed/);
});

test("L100 remaining story uses direct actor-action language", () => {
  const korean = koreanL100PitchDeckSlides;
  assert.match(korean[3].title, /대체하지 않고/);
  assert.match(korean[5].title, /실행 권한을 함께 확인해야 합니다/);
  assert.match(korean[6].title, /대상, 관계, 시간, 근거, 권한과 예상 효과/);
  assert.match(korean[7].title, /근거 있는 판단과 검증된 작업/);
  assert.match(korean[8].title, /^시멘틱 검색은/);
  assert.match(korean[9].title, /^FDAI는 필요한 판단 수준/);
  assert.match(korean[10].title, /LLM을 사용하지 않고/);
  assert.match(korean[11].title, /^에이전트는 하나의 지식베이스/);
  assert.match(korean[12].lead, /문자열을 단순 비교하지 않고/);
  assert.match(korean[13].lead, /고객이 선택한 Azure 리전과 정책 경계/);
  assert.equal(korean[14].title, "첫 검증 워크플로와 운영 책임자를 정합니다");
  assert.match(l100PitchDeckSlides[7].title, /grounded decision and verified work/);
  assert.match(l100PitchDeckSlides[8].title, /^Semantic search connects/);
  assert.match(l100PitchDeckSlides[14].lead, /does not approve adoption or autonomous execution/);
});

test("L100 pitch deck uses diagram-led operating explanations in both locales", () => {
  assert.equal(koreanL100PitchDeckSlides.length, 15);
  assert.equal(l100PitchDeckSlides.length, 15);
  assert.equal(new Set(koreanL100PitchDeckSlides.map((slide) => slide.title)).size, 15);
  assert.deepEqual(
    l100PitchDeckSlides.map((slide) => slide.layout),
    koreanL100PitchDeckSlides.map((slide) => slide.layout),
  );

  const koreanContent = koreanL100PitchDeckSlides
    .map((slide) => `${slide.eyebrow}\n${slide.title}\n${slide.content}`)
    .join("\n");
  assert.match(koreanContent, /QUESTION DECOMPOSITION/);
  assert.match(koreanContent, /FDAI OPERATING ENGINE/);
  assert.match(koreanContent, /시멘틱 검색/);
  assert.match(koreanContent, /T0/);
  assert.match(koreanContent, /결정론적 엔진/);
  assert.match(koreanContent, /AGENT KNOWLEDGE BASE/);
  assert.match(koreanContent, /depends on/);
  assert.match(koreanContent, /Azure Kubernetes Service/);
  assert.ok(koreanL100PitchDeckSlides.slice(1).every((slide) => slide.content.includes("l100-source")));
});

test("L100 operating diagrams preserve direction, boundaries, and one ontology coordinate system", async () => {
  const engine = koreanL100PitchDeckSlides[7].content;
  const semantic = koreanL100PitchDeckSlides[8].content;
  const ontology = koreanL100PitchDeckSlides[12].content;
  const css = await readFile(new URL("l100-pitch-deck.css", root), "utf8");

  assert.match(engine, /class="l100-visual l100-engine-v2"/);
  assert.match(engine, /근거화[\s\S]*판단[\s\S]*권한[\s\S]*실행/);
  assert.match(engine, /독립 효과 검증[\s\S]*완료 또는 롤백/);
  assert.match(semantic, /class="l100-visual l100-semantic-v2"/);
  assert.match(semantic, /ACCOUNTABLE[\s\S]*SEMANTIC SEARCH[\s\S]*운영 온톨로지/);
  assert.match(semantic, /CONTEXT[\s\S]*DECISION[\s\S]*ACTION/);
  assert.match(ontology, /<svg class="l100-ontology-svg" viewBox="0 0 920 350" role="img"/);
  assert.equal([...ontology.matchAll(/<path d=/g)].length, 7);
  assert.equal([...ontology.matchAll(/class="ontology-node /g)].length, 7);
  assert.equal([...ontology.matchAll(/class="ontology-edge-label"/g)].length, 6);
  assert.equal([...ontology.matchAll(/class="ontology-legend /g)].length, 3);
  assert.doesNotMatch(ontology, /<text\b/);
  assert.match(ontology, /marker-end="url\(#ontology-arrow-ko\)"/);
  assert.match(ontology, /M 700 122 V 135 H 797 V 145/);
  assert.match(ontology, /class="ontology-edge-label" x="735" y="92" width="135"/);
  assert.match(css, /\.l100-ontology-svg \.ontology-links/);
  assert.match(css, /\.l100-ontology-svg \.ontology-node div/);
  assert.match(css, /\.l100-ontology-svg \.ontology-edge-label div/);
  assert.match(css, /\.l100-ontology-svg \.ontology-edge-label div \{[\s\S]+background: #1b1e23/);
  assert.match(css, /\.l100-engine-v2 \.engine-arrow::after/);
  assert.match(css, /\.l100-semantic-v2 \.semantic-arrow::after/);
});

test("English and Korean modular decks preserve the same structural contracts", () => {
  assert.deepEqual(Object.keys(englishAdditionalManualSlides), Object.keys(koreanAdditionalManualSlides));
  for (const manualId of Object.keys(englishAdditionalManualSlides)) {
    const englishSlides = englishAdditionalManualSlides[manualId];
    const koreanSlides = koreanAdditionalManualSlides[manualId];
    assert.equal(englishSlides.length, koreanSlides.length, manualId);
    assert.deepEqual(
      englishSlides.map(normalizedStructure),
      koreanSlides.map(normalizedStructure),
      manualId,
    );
  }
});

test("English SRE signal labels remain outside variable-width bars", () => {
  const content = englishAdditionalManualSlides["sre-incident-response"][1].content;
  for (const label of ["Telemetry", "Normalized events", "Correlated episodes", "Response candidates"]) {
    assert.ok(content.includes(`<div><b>${label}</b><span style="--signal-width:`), label);
  }
});

test("English SRE authority layout preserves all seven safeguards", () => {
  const content = englishAdditionalManualSlides["sre-incident-response"][5].content;
  for (const safeguard of ["Stop condition", "Tested rollback", "Blast-radius limit", "Successful dry run",
    "Logical-target lock", "Stable idempotency key", "Two-phase audit"]) {
    assert.ok(content.includes(`<li>${safeguard}</li>`), safeguard);
  }
});

test("English safeguard summary uses a short label without losing independent verification", () => {
  const content = englishAdditionalManualSlides["enterprise-scale-roadmap"][27].content;
  assert.match(content, /<strong>Separate<\/strong>/);
  assert.match(content, /<span>Independent effect observation and review<\/span>/);
  assert.doesNotMatch(content, /<strong>Independent<\/strong>/);
});

test("publication EOF normalizations preserve every previously validated byte", async () => {
  const evidence = JSON.parse(await readFile(new URL("validation-evidence.json", root), "utf8"));
  const record = evidence.publicationNormalizations.at(-1);
  assert.equal(record.change, "append-one-final-lf");
  assert.equal(record.files.length, 6);
  for (const entry of record.files) {
    const bytes = await readFile(new URL(entry.path, root));
    assert.equal(bytes.at(-1), 10, entry.path);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.afterSha256, entry.path);
    assert.equal(createHash("sha256").update(bytes.subarray(0, -1)).digest("hex"), entry.beforeSha256, entry.path);
  }
});

test("English layout overrides remain locale-scoped and load in the viewer", async () => {
  const css = await readFile(new URL("english-layout.css", root), "utf8");
  assert.match(css, /html\[lang="en"\] \.manual-slide/);
  assert.match(css, /"Ubuntu", "Arial", sans-serif/);
  assert.match(css, /font-size: 24px/);
  for (const file of ["index.html", "library.html"]) {
    assert.match(await readFile(new URL(file, root), "utf8"), /href="english-layout\.css"/);
  }
});
