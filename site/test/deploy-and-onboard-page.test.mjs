import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function loadEnKo() {
  const [english, korean] = await Promise.all([
    readFile(
      new URL("../docs/roadmap/deployment/deploy-and-onboard.md", root),
      "utf8",
    ),
    readFile(
      new URL("../docs/roadmap/deployment/deploy-and-onboard-ko.md", root),
      "utf8",
    ),
  ]);
  return { english, korean };
}

async function loadDiagramSource(id) {
  return readFile(new URL(`../docs/diagrams/${id}.diagram.yaml`, root), "utf8");
}

async function loadManifest(id) {
  const source = await readFile(
    new URL(`public/diagrams/generated/${id}.manifest.json`, root),
    "utf8",
  );
  return JSON.parse(source);
}

test("deploy-and-onboard page embeds its diagram with matching manifest alt text", async () => {
  const { english, korean } = await loadEnKo();
  const id = "fdai-deploy-and-onboard-01";
  const manifest = await loadManifest(id);
  const enAltMatch = english.match(
    new RegExp(`!\\[([^\\]]+)\\]\\([^\\n)]*${id}\\.en\\.svg\\)`, "u"),
  );
  const koAltMatch = korean.match(
    new RegExp(`!\\[([^\\]]+)\\]\\([^\\n)]*${id}\\.ko\\.svg\\)`, "u"),
  );
  assert.ok(enAltMatch, `expected an English markdown embed for ${id}`);
  assert.ok(koAltMatch, `expected a Korean markdown embed for ${id}`);
  assert.equal(enAltMatch[1], manifest.locales.en.alt);
  assert.equal(koAltMatch[1], manifest.locales.ko.alt);
});

test("Round 14 regression: diagram source has fully translated, non-English-identical Korean node labels", async () => {
  const source = await loadDiagramSource("fdai-deploy-and-onboard-01");
  assert.ok(
    !source.includes("ko: Prerequisites resolved"),
    "diagram must not leave the 'Prerequisites resolved' node label untranslated in ko:",
  );
  assert.ok(
    !source.includes("ko: System is warm; first real event may arrive"),
    "diagram must not leave the final node label untranslated in ko:",
  );
  assert.ok(source.includes("전제조건 해결됨"));
  assert.ok(source.includes("시스템이 준비됨; 첫 실제 이벤트 도착 가능"));
});

test("Round 14 regression: fictional CI runner version floor and stale line-count budget are removed", async () => {
  const { english, korean } = await loadEnKo();
  for (const stale of ["2.327.1", "2,300-line", "2,300줄"]) {
    assert.ok(!english.includes(stale), `English page must not re-introduce "${stale}"`);
    assert.ok(!korean.includes(stale), `Korean page must not re-introduce "${stale}"`);
  }
  assert.ok(english.includes("resolves the latest published GitHub Actions runner release"));
  assert.ok(korean.includes("항상 GitHub Actions 실행기의 최신 공개 릴리스를 해석해 설치합니다"));
});

test("Round 14 regression: Korean page has no space-detached particles at the previously broken locations", async () => {
  const { korean } = await loadEnKo();
  for (const broken of [
    "구성 는",
    "VNet 을",
    "허브 에",
    "영역 을",
    "경계 으로",
    "VNet 에",
    "laptop 에서",
    "`apply` 는",
    "엔드포인트 에",
    "비공개 로",
    "엔드포인트 로",
    "Officer` 로",
    "저장소 를",
    "private-everything 를",
    "출력 에서",
    "Secrets 를",
  ]) {
    assert.ok(
      !korean.includes(broken),
      `Korean page must not re-introduce the broken particle usage "${broken}"`,
    );
  }
});

test("Round 14 regression: deployment guidance keeps the formal register", async () => {
  const { korean } = await loadEnKo();
  assert.ok(!korean.includes("비공개로 강제한다"));
  assert.ok(!korean.includes("도달 불가능하다"));
  assert.ok(!korean.includes("`Key Vault Secrets Officer`로 만든다"));
  assert.ok(korean.includes("비공개로 유지하기"));
  assert.ok(korean.includes("접근할 수 없습니다"));
  assert.ok(korean.includes("`Key Vault Secrets Officer`로 만듭니다"));
});

test("Round 14 regression: garbled bilingual gloss and invalid conjugation are fixed", async () => {
  const { korean } = await loadEnKo();
  assert.ok(!korean.includes("출처 of truth"));
  assert.ok(korean.includes("기준 원본"));
  assert.ok(!korean.includes("활성화된이면"));
  assert.ok(korean.includes("비공개 networking이 활성화되면"));
});
