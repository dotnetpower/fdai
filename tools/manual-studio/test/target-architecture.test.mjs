import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { access, readFile } from "node:fs/promises";
import { test } from "node:test";

import { buildTargetArchitectureDeck } from "../target-architecture.js";

const root = new URL("../", import.meta.url);
const repositoryRoot = new URL("../../", root);

function content(slides) {
  return slides.map((slide) => `${slide.title}\n${slide.lead}\n${slide.content}`).join("\n");
}

function count(source, pattern) {
  return [...source.matchAll(pattern)].length;
}

test("target architecture is a complete five-chapter L200 architecture deck", async () => {
  const slides = buildTargetArchitectureDeck();

  assert.equal(slides.length, 25);
  assert.equal(new Set(slides.map((slide) => slide.title)).size, 25);
  assert.equal(new Set(slides.map((slide) => slide.layout.split(" ")[0])).size, 25);
  assert.ok(slides.every((slide) => slide.layout.includes("deck-target-architecture")));
  assert.deepEqual(
    Object.fromEntries([1, 2, 3, 4, 5].map((chapter) => [
      chapter,
      slides.filter((slide) => slide.architecture.chapter === chapter).length,
    ])),
    { 1: 5, 2: 5, 3: 5, 4: 5, 5: 5 },
  );

  for (const slide of slides) {
    assert.ok(slide.architecture.sources.length >= 1);
    for (const source of slide.architecture.sources) await access(new URL(source, repositoryRoot));
  }
});

test("target architecture cover stays sparse and title-led", () => {
  const [cover] = buildTargetArchitectureDeck();
  const plainText = `${cover.title} ${cover.lead} ${cover.content}`
    .replace(/<[^>]*>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  assert.equal(cover.title, "FDAI Target<br>Architecture");
  assert.equal(cover.lead, "에이전트 기반 운영 제어 영역과 Azure 배치");
  assert.equal(cover.showDate, true);
  assert.equal(cover.layout, "briefing-target-cover deck-target-architecture");
  assert.equal(cover.architecture.diagramKind, "cover");
  assert.ok(plainText.length < 200);
  assert.match(cover.content, /ta-cover-field/);
  assert.doesNotMatch(cover.content, /<(?:img|article|ol|ul|table|figure)\b/);
  assert.doesNotMatch(cover.content, /목차|AGENDA|CURRENT|TARGET/);
});

test("all twenty-four body slides are architecture diagrams rather than generic card pages", () => {
  const [, ...slides] = buildTargetArchitectureDeck();

  assert.equal(new Set(slides.map((slide) => slide.architecture.id)).size, 24);
  assert.ok(new Set(slides.map((slide) => slide.architecture.diagramKind)).size >= 20);
  for (const slide of slides) {
    assert.equal(count(slide.content, /data-ta-diagram=/g), 1, slide.architecture.id);
    assert.equal(count(slide.content, /<section class="ta-visual/g), 1, slide.architecture.id);
    assert.ok(count(slide.content, /data-ta-node=/g) >= 4, slide.architecture.id);
    assert.ok(count(slide.content, /class="ta-arch-link/g) >= 2, slide.architecture.id);
    assert.equal(
      count(slide.content, /class="ta-arch-link/g),
      count(slide.content, /data-ta-link data-ta-from=/g),
      `${slide.architecture.id}: every drawn connection must be measured`,
    );
    assert.match(slide.content, /data-diagram-kind=/);
    assert.match(slide.content, /role="img"/);
    assert.equal(count(slide.content, /<p class="ta-takeaway"/g), 1, slide.architecture.id);
    assert.equal(count(slide.content, /<small class="ta-source"/g), 1, slide.architecture.id);
    assert.match(slide.content, /class="ta-state" data-state=/);
    assert.match(slide.content, /title="(?:docs\/|\.github\/|config\/)/);
  }

  const all = content(slides);
  assert.ok(count(all, /data-ta-node=/g) >= 220);
  assert.ok(count(all, /data-ta-link data-ta-from=/g) >= 120);
});

test("RiskGate simplification preserves every input and authority outcome", () => {
  const risk = buildTargetArchitectureDeck().find((slide) => slide.architecture.id === "risk-gate-architecture");
  for (const field of [
    "policy violation", "destructive", "irreversible", "data plane", "cost", "confidence",
    "Tier", "registered ceiling", "static blast", "live blast", "principal role", "environment",
    "system health", "global kill switch", "promotion state",
    "AUTO", "HUMAN APPROVAL", "OBSERVATION ONLY", "DENY",
  ]) assert.ok(risk.content.includes(`<span>${field}</span>`), field);
  assert.match(risk.content, /enforce_auto > enforce_hil > shadow_only > deny/);
  assert.match(risk.content, /shadow_only면 승인 여부와 무관하게 변경하지 않습니다/);
});

test("architecture views progress from context through runtime, decision, execution, and Azure", () => {
  const slides = buildTargetArchitectureDeck();
  assert.deepEqual(slides.slice(1).map((slide) => slide.architecture.id), [
    "reference-architecture",
    "system-context",
    "layer-architecture",
    "closed-control-loop",
    "service-topology",
    "service-event-topology",
    "core-component-architecture",
    "agent-runtime-topology",
    "data-ownership-architecture",
    "evidence-admission",
    "semantic-architecture",
    "temporal-architecture",
    "tier-routing-architecture",
    "risk-gate-architecture",
    "execution-dispatch",
    "isolated-executor-architecture",
    "trust-zone-architecture",
    "effect-verification-architecture",
    "degradation-architecture",
    "ports-adapters-architecture",
    "azure-deployment-topology",
    "azure-network-flow",
    "release-promotion-architecture",
    "architecture-decision-map",
  ]);
});

test("cross-slide architecture names and authority boundaries stay consistent", () => {
  const text = content(buildTargetArchitectureDeck());

  for (const service of [
    "Core Control Plane",
    "Operator Service",
    "Document Ingestion API",
    "Document Processing Worker",
    "Isolated Executor",
  ]) assert.match(text, new RegExp(service));

  for (const agent of [
    "Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Vidar", "Var", "Bragi",
    "Saga", "Mimir", "Muninn", "Norns", "Njord", "Freyr", "Loki",
  ]) assert.match(text, new RegExp(`>${agent}<`));

  assert.match(text, /15개 에이전트.*Azure 서비스 수가 아닙니다/s);
  assert.match(text, /Core.*관리 대상 효과 신원은 갖지 않습니다/s);
  assert.match(text, /sole eligible effect identity/);
  assert.match(text, /승인도 typed event로 Core에 돌아가며 Executor를 직접 호출하지 않습니다/);
  assert.match(text, /T2만 품질 검증을 추가로 통과하고.*모든 Tier는 공통 RiskGate/s);
  assert.match(text, /그래프 밖에 남습니다/);
  assert.match(text, /provider 2xx, broker acceptance, PR merge는 dispatch 증거/);
  assert.match(text, /Azure가 유일한 구현 대상/);
  assert.match(text, /production gate.*별도/s);
});

test("implementation, validation, target, and production-blocked states remain explicit", () => {
  const text = content(buildTargetArchitectureDeck());

  assert.match(text, /5개 서비스와 독립 identity 경계는 검증됐습니다/);
  assert.match(text, /Workflow와 격리 실행 경로.*진행 중/s);
  assert.match(text, /자동 dev-to-staging-to-prod 승격.*목표 상태/s);
  assert.match(text, /PRODUCTION BLOCKED/);
  assert.match(text, /DESIGN CONDITIONAL/);
  assert.match(text, /운영 측정값 아님/);
  assert.match(text, /OPTIONAL PROFILE/);
});

test("architecture plan defines the story, diagrams, consistency, and validation before implementation", async () => {
  const plan = await readFile(new URL("target-architecture-plan.md", root), "utf8");

  assert.match(plan, /## Audience and decision/);
  assert.match(plan, /## Architecture story/);
  assert.match(plan, /## Slide plan/);
  assert.match(plan, /## Diagram rules/);
  assert.match(plan, /## Consistency contract/);
  assert.match(plan, /## Critique and validation/);
  assert.match(plan, /최소 18장은 구성 요소, 시스템 또는 신뢰 경계/);
  for (let slide = 1; slide <= 25; slide += 1) assert.match(plan, new RegExp(`\\| ${slide} \\|`));
});

test("target architecture styles preserve presentation typography and diagram grammar", async () => {
  const commonCss = await readFile(new URL("target-architecture.css", root), "utf8");
  const visualCss = await readFile(new URL("target-architecture-visuals.css", root), "utf8");
  const deploymentCss = await readFile(new URL("target-architecture-deployment.css", root), "utf8");

  assert.match(commonCss, /slide-copy h2[\s\S]{0,220}font-size: 43px/);
  assert.match(commonCss, /slide-copy p[\s\S]{0,220}font-size: 24px/);
  assert.match(commonCss, /\[data-ta-primary\][\s\S]{0,100}font-size: 24px/);
  assert.match(commonCss, /\.ta-source[\s\S]{0,180}font-size: 13px/);
  assert.match(commonCss, /slide-copy h2[\s\S]{0,220}font-size: 82px/);
  assert.match(commonCss, /\.ta-arch-node/);
  assert.match(commonCss, /\.ta-arch-boundary/);
  assert.match(commonCss, /\.ta-arch-link/);
  assert.match(commonCss, /data-ta-direction="down"/);
  assert.match(commonCss, /repeating-linear-gradient/);
  assert.match(visualCss, /\.ta-reference-architecture/);
  assert.match(visualCss, /\.ta-agent-runtime/);
  assert.match(visualCss, /\.ta-semantic-architecture/);
  assert.match(deploymentCss, /\.ta-isolated-executor/);
  assert.match(deploymentCss, /\.ta-azure-deployment/);
  assert.match(deploymentCss, /\.ta-release-promotion/);
  assert.match(deploymentCss, /print-color-adjust: exact/);

  for (const entry of ["index.html", "library.html"]) {
    const html = await readFile(new URL(entry, root), "utf8");
    assert.match(html, /href="target-architecture\.css"/);
    assert.match(html, /href="target-architecture-visuals\.css"/);
    assert.match(html, /href="target-architecture-deployment\.css"/);
  }
});

test("target architecture review records current digest-bound architecture hardening", async () => {
  const evidence = JSON.parse(await readFile(new URL("validation-evidence.json", root), "utf8"));
  const manual = evidence.manuals.find((item) => item.id === "target-architecture");
  const review = manual.slideReviews.at(-1);
  const currentSlides = buildTargetArchitectureDeck();

  assert.equal(review.reviewId, "target-architecture-nested-clipping-2026-09-11");
  assert.ok(review.critiqueRoundCount >= 4);
  assert.equal(review.critiqueRounds.length, review.critiqueRoundCount);
  assert.ok(review.critiqueRounds.every((round) => round.finding && round.correction && round.verified === "passed"));
  assert.equal(createHash("sha256").update(JSON.stringify(currentSlides)).digest("hex"), review.deckDigest);
  for (const [file, digest] of Object.entries(review.sourceDigests)) {
    const bytes = await readFile(new URL(file, root));
    const normalization = evidence.publicationNormalizations?.find((record) =>
      record.change === "append-one-final-lf" && record.files.some((entry) =>
        entry.path === file && entry.beforeSha256 === digest));
    const entry = normalization?.files.find((item) => item.path === file);
    if (entry) {
      // Keep the historical hash strict: only the one recorded final LF may differ.
      assert.equal(bytes.at(-1), 10, file);
      assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.afterSha256, file);
      assert.equal(createHash("sha256").update(bytes.subarray(0, -1)).digest("hex"), digest, file);
    } else {
      assert.equal(createHash("sha256").update(bytes).digest("hex"), digest, file);
    }
  }
  assert.deepEqual(review.modesPassed, ["desktop", "tablet", "mobile", "fullscreen", "print"]);
  assert.equal(review.slideModeChecks, 125);
  assert.equal(review.primaryBodyFontFloorPx, 24);
  assert.ok(review.minimumTextContrastRatio >= 4.5);
  assert.ok(review.diagramNodeCount >= 220);
  assert.ok(review.diagramConnectorsPerPass >= 100);
  assert.equal(review.clippedTextFindings, 0);
  assert.equal(review.nodeTextOverflowFindings, 0);
  assert.equal(review.ancestorClippingFindings, 0);
  assert.equal(review.paintedTextOverlapFindings, 0);
  assert.equal(review.directDesktopSlidesReviewed, 25);
  assert.equal(review.sharedBrowser.slidesChecked, 25);
  assert.equal(review.sharedBrowser.findings, 0);
  assert.deepEqual(review.riskGateRegression.rejectedBoundaries, ["risk-table", "risk-ceilings"]);
  assert.deepEqual(review.textGeometrySelfTests.map((result) => result.scale), [1, .65, .22]);
  assert.ok(review.textGeometrySelfTests.every((result) => result.detectedFailures === 4 && result.cleanFindings === 0));
  assert.equal(review.regionOverlapFindings, 0);
  assert.equal(review.failedRequests, 0);
  assert.equal(review.pageErrors, 0);
  assert.equal(review.pdf.pages, 25);
  assert.equal(review.pdf.mediaBoxesChecked, 25);
  assert.deepEqual(review.pdf.mediaBoxPoints, [1152, 648]);
});
