import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  createTranslator,
  resolveLocale,
  urlWithLocale,
} from "../localization.js";

const root = new URL("../", import.meta.url);

async function catalogs() {
  const [english, korean] = await Promise.all([
    readFile(new URL("messages.en.json", root), "utf8").then(JSON.parse),
    readFile(new URL("messages.ko.json", root), "utf8").then(JSON.parse),
  ]);
  return { en: english, ko: korean };
}

test("locale resolution honors URL, saved preference, browser language, then English", () => {
  assert.equal(resolveLocale({
    url: "https://manuals.example.com/library?locale=ko",
    storedLocale: "en",
    browserLocales: ["en-US"],
  }), "ko");
  assert.equal(resolveLocale({
    url: "https://manuals.example.com/library",
    storedLocale: "ko-KR",
    browserLocales: ["en-US"],
  }), "ko");
  assert.equal(resolveLocale({
    url: "https://manuals.example.com/library",
    browserLocales: ["fr-FR", "ko-KR"],
  }), "ko");
  assert.equal(resolveLocale({
    url: "https://manuals.example.com/library?locale=unsupported",
    browserLocales: ["fr-FR"],
  }), "en");
});

test("translator interpolates values and falls back to the English source", async () => {
  const source = await catalogs();
  const koreanWithoutCount = structuredClone(source.ko);
  delete koreanWithoutCount.library.guideCount;
  const translate = createTranslator({ en: source.en, ko: koreanWithoutCount }, "ko");

  assert.equal(translate("language.korean"), "한국어");
  assert.equal(translate("library.guideCount", { count: 11 }), "11 guides");
  assert.equal(translate("missing.key"), "missing.key");
});

test("every catalog stage and manual has complete English and Korean presentation fields", async () => {
  const source = await catalogs();
  const catalog = JSON.parse(await readFile(new URL("catalog.json", root), "utf8"));
  const english = createTranslator(source, "en");
  const korean = createTranslator(source, "ko");

  for (const stage of catalog.journey.stages) {
    for (const field of ["title", "question"]) {
      const key = `journey.${field}s.${stage.id}`;
      assert.notEqual(english(key), key);
      assert.notEqual(korean(key), key);
    }
  }
  for (const manual of catalog.manuals) {
    for (const field of ["title", "eyebrow", "coverLabel", "description"]) {
      const key = `manuals.${manual.id}.${field}`;
      assert.notEqual(english(key), key);
      assert.notEqual(korean(key), key);
    }
  }
  assert.equal(english("manuals.target-architecture.title"), "FDAI Target Architecture");
  assert.equal(korean("manuals.target-architecture.title"), "FDAI 목표 아키텍처");
});

test("locale URL updates preserve manual and slide state", () => {
  const url = urlWithLocale(
    "https://manuals.example.com/target-architecture.html?slide=7&source=teams",
    "ko",
  );

  assert.equal(url.pathname, "/target-architecture.html");
  assert.equal(url.searchParams.get("slide"), "7");
  assert.equal(url.searchParams.get("source"), "teams");
  assert.equal(url.searchParams.get("locale"), "ko");
  assert.throws(() => urlWithLocale(url, "fr"), /Unsupported Manual Studio locale/);
});

test("console, library, and viewer headers expose the same language choices", async () => {
  for (const entry of ["index.html", "library.html"]) {
    const html = await readFile(new URL(entry, root), "utf8");
    assert.match(html, /<html lang="en">/);
    assert.match(html, /data-locale-choice="en"/);
    assert.match(html, /data-locale-choice="ko"/);
    assert.match(html, /data-i18n-aria-label="language\.control"/);
  }
  const library = await readFile(new URL("library.html", root), "utf8");
  assert.equal([...library.matchAll(/data-locale-choice="en"/g)].length, 2);
  assert.equal([...library.matchAll(/data-locale-choice="ko"/g)].length, 2);
});
