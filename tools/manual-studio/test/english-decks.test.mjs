import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { executiveBriefingSlides } from "../executive-briefing.en.js";
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
    ...englishAdditionalManualSlides,
  };

  assert.deepEqual(Object.keys(englishDecks), catalog.manuals.map((manual) => manual.id));
  for (const manual of catalog.manuals) {
    assert.equal(englishDecks[manual.id].length, manual.slideCount, manual.id);
  }
  assert.equal(
    Object.values(englishDecks).reduce((total, slides) => total + slides.length, 0),
    307,
  );
});

test("English decks contain no Korean fallback text", () => {
  const englishDecks = {
    "executive-briefing": executiveBriefingSlides,
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
