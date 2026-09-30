import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function loadEnKo() {
  const [english, korean] = await Promise.all([
    readFile(new URL("../docs/roadmap/agents/agent-workflows.md", root), "utf8"),
    readFile(new URL("../docs/roadmap/agents/agent-workflows-ko.md", root), "utf8"),
  ]);
  return { english, korean };
}

async function loadManifest(name) {
  const source = await readFile(
    new URL(`public/diagrams/generated/${name}.manifest.json`, root),
    "utf8",
  );
  return JSON.parse(source);
}

test("agent-workflows page embeds all 12 workflow diagrams with matching manifest alt text", async () => {
  const { english, korean } = await loadEnKo();
  for (let i = 1; i <= 12; i += 1) {
    const id = `fdai-agent-workflows-${String(i).padStart(2, "0")}`;
    const manifest = await loadManifest(id);
    const enAltMatch = english.match(new RegExp(`!\\[([^\\]]+)\\]\\([^\\n)]*${id}\\.en\\.svg\\)`, "u"));
    const koAltMatch = korean.match(new RegExp(`!\\[([^\\]]+)\\]\\([^\\n)]*${id}\\.ko\\.svg\\)`, "u"));
    assert.ok(enAltMatch, `expected an English markdown embed for ${id}`);
    assert.ok(koAltMatch, `expected a Korean markdown embed for ${id}`);
    assert.equal(enAltMatch[1], manifest.locales.en.alt);
    assert.equal(koAltMatch[1], manifest.locales.ko.alt);
  }
});

test("Round 12 regression: diagram-04 references the real RuleCandidateHint.pattern field, not override_pattern", async () => {
  const { english, korean } = await loadEnKo();
  const diagramSource = await readFile(
    new URL("../docs/diagrams/fdai-agent-workflows-04.diagram.yaml", root),
    "utf8",
  );
  assert.ok(
    !diagramSource.includes("override_pattern"),
    "diagram-04 source must not re-introduce the non-existent override_pattern field name",
  );
  assert.ok(!english.includes("override_pattern"));
  assert.ok(!korean.includes("override_pattern"));
});

test("Round 12 regression: workflow 1 exit criteria cite real object.action-run fields, not the non-existent cost_actual", async () => {
  const { english, korean } = await loadEnKo();
  assert.ok(
    !english.includes("cost_actual"),
    "English page must not re-introduce the non-existent cost_actual field name",
  );
  assert.ok(
    !korean.includes("cost_actual"),
    "Korean page must not re-introduce the non-existent cost_actual field name",
  );
  assert.ok(
    english.includes("execution_audit_receipt"),
    "English exit criteria must cite the real execution_audit_receipt field from thor.py",
  );
  assert.ok(
    korean.includes("execution_audit_receipt"),
    "Korean exit criteria must cite the real execution_audit_receipt field from thor.py",
  );
});

test("Round 12 regression: workflow 1 heading uses the display name and the table keeps the registry name", async () => {
  const { english, korean } = await loadEnKo();
  // A heading is reader-facing, so check-display-terminology.py requires the display
  // vocabulary there; the summary table keeps the WorkflowSpec registry name
  // 'Cost-aware remediation' so the two stay traceable.
  assert.ok(
    english.includes("## 1. Cost-aware fix"),
    "English section header must use the display name that the terminology gate requires",
  );
  assert.ok(
    !english.includes("## 1. Cost-aware remediation"),
    "English section header must not re-introduce the technical term the terminology gate rejects",
  );
  assert.ok(
    english.includes("| 1 | Cost-aware remediation |"),
    "English summary table must keep the WorkflowSpec registry name for workflow 1",
  );
  assert.ok(
    korean.includes("Cost-aware 교정"),
    "Korean section must use '교정', matching the doc's own summary-table naming for workflow 1",
  );
  assert.ok(
    !korean.includes("Cost-aware 수정"),
    "Korean page must not re-introduce the inconsistent 'Cost-aware 수정' naming",
  );
});

test("Round 12 regression: workflow 5 exit criteria separate the rate-limit window from the counter-based dedup", async () => {
  const { english, korean } = await loadEnKo();
  // Regression guard: heimdall.py's 1-hour _ALERT_WINDOW_SECONDS belongs to
  // _reserve_alert_slot (rate-limiting), not _maybe_send_admin_card (which
  // dedupes by (initiator, action) with an incrementing counter and no
  // time-based reset). The exit criteria must not conflate the two.
  assert.ok(
    !/1.?h(our)? dedup/iu.test(english),
    "English exit criteria must not claim a false '1h dedup' window",
  );
  assert.ok(
    !korean.includes("1시간") || !korean.includes("중복 제거"),
    "Korean exit criteria must not conflate the 1-hour rate-limit window with dedup",
  );
});

test("Round 12 regression: diagram-10 and its embeds carry a real Korean translation, not a byte-identical English copy", async () => {
  const { korean } = await loadEnKo();
  const diagramSource = await readFile(
    new URL("../docs/diagrams/fdai-agent-workflows-10.diagram.yaml", root),
    "utf8",
  );
  assert.ok(
    korean.includes("회고적 가정 분석"),
    "Korean page must translate 'Retrospective what-if' as '회고적 가정 분석'",
  );
  const koBlock = diagramSource.slice(diagramSource.indexOf("\n  ko:\n"));
  assert.ok(
    koBlock.includes("회고적 가정 분석"),
    "diagram-10 source's ko: locale block must carry the real Korean translation",
  );
  assert.ok(
    !koBlock.includes("Retrospective what-if"),
    "diagram-10 source's Korean locale block must not remain a byte-identical copy of the English title",
  );
});

test("Round 12 regression: the KO agent-pantheon anchor resolves to the real slugified Korean heading", async () => {
  const { korean } = await loadEnKo();
  assert.ok(
    !korean.includes("agent-pantheon-ko.md#61-typed-port"),
    "Korean page must not link to the broken English-slug anchor",
  );
  assert.ok(
    korean.includes("agent-pantheon-ko.md#61-타입이-지정된-포트"),
    "Korean page must link to the real github-slugger anchor for '### 6.1 타입이 지정된 포트'",
  );
});

test("Round 12 regression: Section 0 describes the diagrams as static SVG, not stale 'mermaid diagram' terminology", async () => {
  const { english, korean } = await loadEnKo();
  assert.ok(
    !english.includes("mermaid diagram"),
    "English page must not re-introduce stale 'mermaid diagram' terminology",
  );
  assert.ok(
    !korean.includes("mermaid diagram") && !korean.includes("mermaid 다이어그램"),
    "Korean page must not re-introduce stale mermaid-diagram terminology",
  );
});

test("Round 12 regression: workflow 13 'Detection readiness assurance' has its own prose section on both locales", async () => {
  const { english, korean } = await loadEnKo();
  assert.ok(
    english.includes("## 13. Detection readiness assurance"),
    "English page must document workflow 13 from the registry, not only list it in the summary table",
  );
  assert.ok(
    korean.includes("## 13. Detection 준비 상태 assurance"),
    "Korean page must document workflow 13 from the registry, not only list it in the summary table",
  );
  assert.ok(
    english.includes("## 14. Workflow catalog summary"),
    "English catalog summary must be renumbered to 14 after inserting the workflow 13 section",
  );
  assert.ok(
    korean.includes("## 14. 워크플로우 카탈로그 요약"),
    "Korean catalog summary must be renumbered to 14 after inserting the workflow 13 section",
  );
});

test("Korean page has no particle-spacing errors (noun + detached grammatical particle)", async () => {
  const { korean } = await loadEnKo();
  const particles = ["가", "은", "는", "을", "를", "로", "의", "와", "과", "도", "만", "에서", "에"];
  const pattern = new RegExp(
    `([\`가-힣A-Za-z0-9]+) (${particles.join("|")})(?=[\\s.,)\\]:]|$)`,
    "gu",
  );
  const matches = [...korean.matchAll(pattern)];
  assert.equal(
    matches.length,
    0,
    `Korean page must not contain space-detached particles; found: ${matches.slice(0, 5).map((m) => m[0]).join(", ")}`,
  );
});
