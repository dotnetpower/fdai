import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function loadManifest(name) {
  const source = await readFile(
    new URL(`public/diagrams/generated/${name}.manifest.json`, root),
    "utf8",
  );
  return JSON.parse(source);
}

async function loadSvg(name, locale) {
  return readFile(
    new URL(`public/diagrams/generated/${name}.${locale}.svg`, root),
    "utf8",
  );
}

function wrapperAlts(source, name, locale) {
  const pattern = new RegExp(
    `${name}\\.${locale}\\.svg" alt="([^"]+)"`,
    "gu",
  );
  return [...source.matchAll(pattern)].map((match) => match[1]);
}

function markdownImageAlts(source, name, locale) {
  const pattern = new RegExp(
    `!\\[([^\\]]+)\\]\\([^\\n)]*${name}\\.${locale}\\.svg\\)`,
    "gu",
  );
  return [...source.matchAll(pattern)].map((match) => match[1]);
}

function allAlts(source, name, locale) {
  return [
    ...wrapperAlts(source, name, locale),
    ...markdownImageAlts(source, name, locale),
  ];
}

test("architecture pages preserve bilingual diagram parity and alt-text consistency", async () => {
  const [english, korean] = await Promise.all([
    readFile(new URL("src/content/docs/architecture.md", root), "utf8"),
    readFile(new URL("src/content/docs/ko/architecture.md", root), "utf8"),
  ]);

  // Seven diagrams are embedded; two of them (fdai-system-overview and
  // fdai-reference-architecture) are additionally re-embedded later on the
  // page via plain markdown image syntax, which the fdai-diagrams remark
  // plugin transforms into the identical interactive wrapper at build time.
  assert.equal(
    [...english.matchAll(/<fdai-architecture-diagram /gu)].length,
    7,
  );
  assert.equal(
    [...korean.matchAll(/<fdai-architecture-diagram /gu)].length,
    7,
  );
  assert.equal(english.match(/^!\[/gmu)?.length, 2);
  assert.equal(korean.match(/^!\[/gmu)?.length, 2);

  // Every embed of a diagram (primary wrapper and any markdown duplicate)
  // must carry alt text that matches the diagram's own canonical alt for
  // that locale exactly - drifted paraphrases are an accessibility bug.
  for (const name of [
    "fdai-reference-architecture",
    "fdai-system-overview",
    "fdai-azure-resource-network-flow",
    "fdai-azure-aks-deployment",
  ]) {
    const manifest = await loadManifest(name);
    for (const locale of ["en", "ko"]) {
      const canonical = manifest.locales[locale].alt;
      const pageSource = locale === "en" ? english : korean;
      const embeds = allAlts(pageSource, name, locale);
      assert.ok(embeds.length >= 1, `expected at least one ${locale} embed for ${name}`);
      for (const alt of embeds) {
        assert.equal(
          alt,
          canonical,
          `${name} (${locale}) embed alt must match the diagram's canonical alt`,
        );
      }
    }
  }
});

test("fdai-reference-architecture uses the page's dominant Korean control-plane and pull-request terminology", async () => {
  const koSvg = await loadSvg("fdai-reference-architecture", "ko");

  // "컨트롤 플레인" is the page's own dominant, established rendering of
  // "control plane" (9+ occurrences in architecture-ko.md body prose) and
  // matches the sibling fdai-system-overview diagram's own translation.
  assert.match(koSvg, /헤드리스 FDAI 컨트롤 플레인/u);
  assert.doesNotMatch(koSvg, /FDAI 자동 운영 판단 엔진/u);

  // "수정 pull request" is the established Korean rendering of "remediation
  // pull request" used consistently by the sibling fdai-system-overview and
  // fdai-azure-deployment-topology diagrams.
  assert.match(koSvg, /수정 pull request/u);
  assert.doesNotMatch(koSvg, /remediation pull request/u);
  assert.doesNotMatch(koSvg, /복구 pull request/u);
});

test("architecture page duplicate embeds use consistent remediation pull-request wording", async () => {
  const [english, korean] = await Promise.all([
    readFile(new URL("src/content/docs/architecture.md", root), "utf8"),
    readFile(new URL("src/content/docs/ko/architecture.md", root), "utf8"),
  ]);

  assert.doesNotMatch(english, /recovery pull request/u);
  assert.doesNotMatch(korean, /복구 pull request/u);
  assert.match(english, /remediation pull requests?/u);
});

test("fdai-agent-driven-runtime translates its descriptive Korean labels without adding tone", async () => {
  const manifest = await loadManifest("fdai-agent-driven-runtime");

  // This diagram is shared with the already-completed
  // /concepts/agents-and-self-healing/ page (issue #509). It is a
  // `data-flow`-kind diagram, and no `data-flow`-kind diagram anywhere in
  // the repository has ever received `tone` - tone is a campaign-introduced
  // enhancement applied only to a round's sole-primary-subject diagrams, so
  // it deliberately stays untoned here.
  for (const node of manifest.nodes) {
    assert.ok(!node.tone, `node ${node.id} must stay untoned (shared diagram)`);
  }

  // Ordinary descriptive node/edge/legend text must be translated. Bare
  // agent proper names (Huginn, Forseti, Odin, Thor, Var, Vidar, Saga,
  // Norns, Bragi, Heimdall, Njord, Freyr, Loki, Mimir, Muninn) and a small
  // set of established English-retained technical terms
  // ("Schema-validated event(-bus) choreography", "arbitration",
  // "Typed event", "Rollback") legitimately stay identical across locales,
  // matching precedent already established by the sibling
  // fdai-reference-architecture diagram on this same page.
  const expectedIdentical = new Set([
    "Schema-validated event-bus choreography",
    "arbitration",
    "Typed event",
    "Rollback",
  ]);
  const identicalFound = [];
  for (const node of manifest.nodes) {
    if (node.label.en === node.label.ko) identicalFound.push(node.label.en);
  }
  for (const edge of manifest.edges) {
    if (edge.label && edge.label.en === edge.label.ko) identicalFound.push(edge.label.en);
  }
  for (const text of identicalFound) {
    assert.ok(
      expectedIdentical.has(text),
      `unexpected untranslated Korean text: ${text}`,
    );
  }

  // Spot-check a handful of the actually-translated labels.
  const bySpecificEnglish = (collection, en) =>
    collection.find((item) => item.label?.en === en);
  assert.equal(
    bySpecificEnglish(manifest.nodes, "Huginn - event owner")?.label.ko,
    "Huginn - event 소유자",
  );
  assert.equal(
    bySpecificEnglish(manifest.nodes, "Forseti - decision owner")?.label.ko,
    "Forseti - 결정 소유자",
  );
  assert.equal(
    bySpecificEnglish(manifest.edges, "inert candidate")?.label.ko,
    "비활성 후보",
  );

  // The legend is rendered directly into the SVG (not exposed on the
  // manifest); "Audit" must render as its established Korean translation.
  const legendSvg = await loadSvg("fdai-agent-driven-runtime", "ko");
  assert.match(legendSvg, /<text[^>]*>감사<\/text>/u);
  assert.doesNotMatch(legendSvg, /<text[^>]*>Audit<\/text>/u);

  for (const locale of ["en", "ko"]) {
    const svg = await loadSvg("fdai-agent-driven-runtime", locale);
    assert.equal([...svg.matchAll(/data-node-id=/g)].length, manifest.nodes.length);
    assert.equal([...svg.matchAll(/data-edge-id=/g)].length, manifest.edges.length);
  }
});

test("fdai-system-overview English and Korean canonical alt describe the same outcome path", async () => {
  const manifest = await loadManifest("fdai-system-overview");
  const enAlt = manifest.locales.en.alt;
  const koAlt = manifest.locales.ko.alt;

  // Structural alt-text length/embed-count parity does not guarantee the two
  // locales describe the same diagram content. The English alt states the
  // outcome path explicitly (remediation pull requests recorded for the
  // read-only console); the Korean translation must state the same outcome,
  // not a different one (a prior bug had it describe a failure/rollback
  // outcome instead, dropping both concepts below).
  assert.match(enAlt, /remediation pull requests?/u);
  assert.match(enAlt, /read-only console/u);
  assert.match(koAlt, /수정 pull request/u);
  assert.match(koAlt, /읽기 전용 콘솔/u);
});

test("architecture-ko page prose does not contain known corrected typos", async () => {
  const korean = await readFile(
    new URL("src/content/docs/ko/architecture.md", root),
    "utf8",
  );

  // "끕" is not a Korean word; the corrected line 219 reads "끌 수 없습니다"
  // ("cannot turn off/disable"), matching the parallel English sentence.
  assert.doesNotMatch(korean, /끕/u);

  // "요청나" is ungrammatical (요청 ends in a batchim, so the disjunctive
  // particle must be "이나", not "나" alone); the corrected five-layers
  // table cell reads "수정 pull 요청이나 등록된 프로바이더 호출".
  assert.doesNotMatch(korean, /요청나/u);
  assert.match(korean, /수정 pull 요청이나/u);
});
