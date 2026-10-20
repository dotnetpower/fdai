import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { access, readFile } from "node:fs/promises";
import { test } from "node:test";
import { l100PitchDeckSlides as korean } from "../l100-pitch-deck.js";
import { l100PitchDeckSlides as english } from "../l100-pitch-deck.en.js";
import { pitchSlide } from "../l100-pitch-kit.js";

const repository = new URL("../../../", import.meta.url);

test("L100 locales preserve the same story, scope, evidence, and example boundaries", async () => {
  assert.equal(korean.length, 15);
  assert.deepEqual(english.map(slide => slide.pitch), korean.map(slide => slide.pitch));
  assert.equal(new Set(korean.map(slide => slide.pitch.id)).size, 15);
  for (const slides of [korean, english]) {
    assert.equal(new Set(slides.map(slide => slide.title)).size, 15);
    for (const slide of slides) {
      assert.match(slide.layout, /deck-l100-calm/);
      assert.ok(slide.pitch.sources.length > 0);
      for (const path of slide.pitch.sources) await access(new URL(path, repository));
      assert.match(slide.content, /class="lp-takeaway"/);
      assert.equal(slide.content.includes('class="lp-example"'), slide.pitch.example);
      assert.match(slide.content, /https:\/\/github.com\/dotnetpower\/fdai\/blob\/main\//);
    }
  }
});

test("L100 keeps models, authority, observation, and implementation state separate", async () => {
  assert.match(korean[3].content, /검토 대상이지 현재 사실이 아닙니다/);
  assert.match(english[3].content, /proposal needs review; it is not a current fact/);
  assert.match(korean[8].content, /모델 없이[\s\S]*경량 모델[\s\S]*서로 다른 모델/);
  assert.match(english[8].content, /No model[\s\S]*lightweight models[\s\S]*distinct-model/);
  assert.equal([...korean[10].content.matchAll(/<li>/g)].length, 7);
  assert.equal([...english[10].content.matchAll(/<li>/g)].length, 7);
  assert.match(korean[11].content, /독립된 관측|별도 관측/);
  assert.match(korean[11].content, /원인이 자동으로 확정되는 것은 아닙니다/);
  assert.match(english[11].content, /does not automatically establish the cause/);
  assert.match(korean[12].content, /실환경 동작 검증 결과가 아닙니다/);
  const runtime = await readFile(new URL("services/core-control-plane/src/fdai/runtime/ontology_index_runtime.py", repository), "utf8");
  assert.match(runtime, /semantic_search_available=False/);
});

test("L100 layouts vary without three consecutive card or flow pages", () => {
  const kinds = korean.map(slide => slide.pitch.kind);
  assert.ok(new Set(kinds).size >= 10);
  for (let index = 2; index < kinds.length; index += 1) {
    assert.ok(!(kinds[index] === kinds[index - 1] && kinds[index] === kinds[index - 2]));
  }
});

test("L100 source typos fail explicitly rather than producing a broken citation", () => {
  assert.throws(() => pitchSlide("en", { sources: ["missing-source"] }), /Unknown L100 source/);
});

test("L100 relation copy names concrete usage without claiming the incident cause", () => {
  assert.match(korean[4].content, /class="lp-edge-label">DB 사용</);
  assert.match(english[4].content, /class="lp-edge-label">Uses database</);
  assert.match(korean[4].content, /API가 사용하는 데이터베이스/);
  assert.match(korean[4].content, /확인한 시점과 출처/);
  assert.match(korean[4].content, /원인이 DB라고 단정하지는 않습니다/);
  assert.match(english[4].content, /does not establish the cause/);
  assert.match(korean[4].content, /data-lp-relation="depends_on"/);
  assert.doesNotMatch(korean[4].content, /의존합니다|API가 사용하는 데이터</);
  assert.doesNotMatch(korean[4].content, /<code>depends_on<\/code>/);
});

test("L100 styles are deck-scoped and preserve fixed print geometry", async () => {
  const css = await readFile(new URL("../l100-pitch-deck.css", import.meta.url), "utf8");
  const rules = [...css.matchAll(/([^{}]+)\{/g)].map(match => match[1].trim());
  for (const selector of rules.filter(rule => !rule.startsWith("@"))) {
    assert.ok(selector.split(/,\s*(?=\.)/).every(part => part.trim().includes(".deck-l100-calm")), selector);
  }
  assert.match(css, /@media print[\s\S]*zoom: 1 !important/);
  assert.doesNotMatch(css, /@page/);
  assert.match(css, /\.lp-takeaway \{[^}]*font-size: 24px/);
});

test("latest L100 rendering evidence is bound to the current bilingual deck", async () => {
  const evidence = JSON.parse(await readFile(new URL("../validation-evidence.json", import.meta.url), "utf8"));
  const record = evidence.draftValidations.filter(item => item.id === "l100-pitch-deck").at(-1);
  assert.equal(record.reviewId, "l100-relation-clarity-2026-10-20");
  assert.equal(record.humanReview, false);
  assert.equal(record.slideModeChecks, 150);
  assert.deepEqual(record.locales, ["ko", "en"]);
  assert.equal(record.minimumPrimaryFontPx, 24);
  assert.ok(record.minimumTextContrast >= 4.5);
  assert.equal(record.connectorsChecked, 30);
  assert.ok(record.maximumConnectorGapPx <= 1);
  assert.equal(record.connectorSelfTests, 4);
  for (const key of ["findings", "failedRequests", "pageErrors"]) assert.equal(record[key], 0);
  for (const locale of ["ko", "en"]) {
    assert.equal(record.pdf[locale].pages, 15);
    assert.deepEqual(record.pdf[locale].mediaBoxPoints, [1152, 648]);
  }
  for (const [file, hash] of Object.entries(record.sourceDigests)) {
    const bytes = await readFile(new URL(`../${file}`, import.meta.url));
    assert.equal(createHash("sha256").update(bytes).digest("hex"), hash, file);
  }
  for (const [locale, slides] of [["ko", korean], ["en", english]]) {
    assert.equal(createHash("sha256").update(JSON.stringify(slides)).digest("hex"), record.deckDigests[locale]);
  }
});
