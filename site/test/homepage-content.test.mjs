import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { homeContent, homeCopy } from "../src/data/home-copy.mjs";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");

function shape(value) {
  if (Array.isArray(value)) return value.map(shape);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, child]) => [key, shape(child)]));
  return typeof value;
}

test("English and Korean keep the same homepage information structure", () => {
  assert.deepEqual(shape(homeCopy.en), shape(homeCopy.ko));
  assert.equal(homeContent("fr"), homeCopy.en);
  assert.equal(homeContent("ko-KR"), homeCopy.ko);
  for (const copy of Object.values(homeCopy)) {
    assert.equal(copy.flow.length, 4);
    assert.equal(copy.outcomes.length, 3);
    assert.equal(copy.navigation.length, 3);
    assert.equal(copy.next.length, 3);
    assert.deepEqual(copy.safeguards.map(item => item.id), ["stop", "rollback", "scope", "dry-run", "lock", "idempotency", "audit"]);
    assert.doesNotMatch(JSON.stringify(copy), /\d\s*%|Phase\s*\d|needs_review|policy_guardrail/);
  }
});

test("home journeys use published locale-consistent document routes", async () => {
  const manifest = JSON.parse(await read("src/data/publication-routes.json"));
  const routes = new Set(manifest.map(item => item.route));
  for (const [locale, copy] of Object.entries(homeCopy)) {
    const paths = [...copy.outcomes.map(item => item.link), ...copy.safetyLinks.map(item => item.path), ...copy.next.map(item => item.path), "reference/roadmap/"];
    for (const path of paths) assert.ok(routes.has(`/${locale === "ko" ? "ko/" : ""}${path}`), `${locale}: ${path}`);
  }
});

test("home preserves the authored nebula and exposes safety as native disclosure", async () => {
  const sections = await read("src/components/HomeSections.astro");
  const hero = await read("src/components/HomeHero.astro");
  assert.match(hero, /import NebulaBackground from "\.\/NebulaBackground\.astro"/);
  assert.match(hero, /<NebulaBackground intensity=\{1\.0\} speed=\{1\.0\} attachToBody\s*\/>/);
  for (const page of ["src/content/docs/index.mdx", "src/content/docs/ko/index.mdx"]) {
    const source = await read(page);
    assert.match(source, /<HomeSections locale="(?:en|ko)"/);
    assert.doesNotMatch(source, /ScrollReveal|TrustTierFunnel|ActionOntologyExplorer|CardGrid|phase-timeline/);
    assert.match(source, /link: "#how-it-works"/);
    assert.match(source, /link: \/neural-view\/(?:\?lang=ko)?/);
  }
  assert.match(sections, /<details class="home-safeguards">/);
  assert.match(sections, /data-safeguard=\{item.id\}/);
  assert.equal((sections.match(/<section /g) ?? []).length, 4);
});

test("premium layout keeps art separate from readable unboxed content", async () => {
  const hero = await read("src/components/HomeHero.astro");
  const sections = await read("src/components/HomeSections.astro");
  const header = await read("src/components/HomeHeader.astro");
  assert.doesNotMatch(hero, /class="home-flow"/);
  assert.match(sections, /<figure class="home-flow"/);
  assert.match(header, /<DefaultHeader/);
  for (const component of ["Search", "ThemeSelect", "LanguageSelect"]) {
    assert.match(header, new RegExp(`<${component}\\s*/>`));
  }
});
