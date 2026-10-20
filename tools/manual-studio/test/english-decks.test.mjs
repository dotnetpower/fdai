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
  assert.match(koreanSlide.lead, /사람이 목표와 권한을 정하고/);
  assert.match(koreanSlide.lead, /실제 효과를 확인/);
  assert.match(koreanSlide.content, /Microsoft 공식 제품이나 Azure 서비스가 아닙니다/);
  assert.match(englishSlide.content, /not an official Microsoft product or Azure service/);
  assert.match(englishSlide.content, /validated internally by Microsoft Korea CSU/);
});

test("L100 operating challenge names the context-connection bottleneck directly", () => {
  assert.equal(
    koreanL100PitchDeckSlides[1].title,
    "운영자는 흩어진 정보를 모으고 대조해야 합니다",
  );
  assert.match(koreanL100PitchDeckSlides[1].content, /최근 배포 때문인지 DB 문제인지/);
  assert.match(koreanL100PitchDeckSlides[1].content, /설명용 예시/);
  assert.match(l100PitchDeckSlides[1].title, /scattered information/);
  assert.match(l100PitchDeckSlides[1].content, /Illustrative example/);
});

test("L100 product identity separates product value from delivery status", () => {
  assert.match(koreanL100PitchDeckSlides[2].lead, /컨트롤 플레인, 즉/);
  assert.match(koreanL100PitchDeckSlides[2].content, /RESILIENCE/);
  assert.match(koreanL100PitchDeckSlides[2].content, /CHANGE SAFETY/);
  assert.match(koreanL100PitchDeckSlides[2].content, /COST GOVERNANCE/);
  assert.match(koreanL100PitchDeckSlides[2].content, /지원 방식과 업데이트 책임/);
  assert.match(l100PitchDeckSlides[2].content, /support and update ownership/);
});

test("L100 remaining story uses direct actor-action language", () => {
  const korean = koreanL100PitchDeckSlides;
  assert.match(korean[3].title, /설계와 현재 관측 사실은 다릅니다/);
  assert.match(korean[5].title, /비슷한 이름만으로/);
  assert.match(korean[7].title, /가설을 비교/);
  assert.match(korean[8].content, /경량 모델/);
  assert.match(korean[10].content, /일곱|기계가 평가할 중단 조건/);
  assert.match(korean[11].content, /등록된 복구 절차/);
  assert.match(korean[12].content, /표준 답변 경로에서 비활성/);
  assert.match(korean[13].content, /모든 연계의 데이터 상주를 보장하지는 않습니다/);
  assert.match(korean[14].lead, /관찰 종료를 실행 허용으로 간주하지 않습니다/);
  assert.match(l100PitchDeckSlides[12].content, /Disabled in the standard answer path/);
  assert.match(l100PitchDeckSlides[14].lead, /does not authorize execution/);
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
  assert.match(koreanContent, /질문 해석/);
  assert.match(koreanContent, /계획 검증/);
  assert.match(koreanContent, /벡터 유사도 후보 검색/);
  assert.match(koreanContent, /T0/);
  assert.match(koreanContent, /결정론적으로 검증/);
  assert.match(koreanContent, /문서·매뉴얼/);
  assert.match(koreanContent, /depends_on/);
  assert.match(koreanContent, /Azure Kubernetes Service/);
  assert.ok(koreanL100PitchDeckSlides.slice(1).every((slide) => slide.content.includes("l100-source")));
});

test("L100 operating diagrams preserve direction, boundaries, and one ontology coordinate system", async () => {
  const semantic = koreanL100PitchDeckSlides[5].content;
  const ontology = koreanL100PitchDeckSlides[4].content;
  const css = await readFile(new URL("l100-pitch-deck.css", root), "utf8");

  assert.match(semantic, /질문 해석[\s\S]*계획 검증[\s\S]*현재 객체 확인/);
  assert.match(semantic, /후보 순위는 사실 확인이나 실행 승인이 아닙니다/);
  assert.match(ontology, /<svg class="lp-resource-graph" viewBox="0 0 1240 320" role="img"/);
  assert.equal([...ontology.matchAll(/data-lp-node=/g)].length, 2);
  assert.equal([...ontology.matchAll(/data-lp-from=/g)].length, 1);
  assert.doesNotMatch(ontology, /<text\b/);
  assert.match(ontology, /marker-end="url\(#lp-arrow-ko\)"/);
  assert.match(ontology, /data-lp-from="api" data-lp-to="db" x1="440" y1="136" x2="800" y2="136"/);
  assert.match(css, /\.deck-l100-calm \.lp-link::after/);
  assert.match(css, /--lp-bg: #fbfaf9/);
  assert.match(css, /font-size: 24px/);
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
