import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createServer, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test, type Page } from "@playwright/test";

// Renders the production Command Deck from typed fixture frames so the portable conversation layer
// (ui/calm-slate-deck-conversation.css) can be checked on the real components. Every value is
// synthetic, the Operator API is routed in-process, and nothing runs against a live service.

const GOLDEN = JSON.parse(readFileSync(new URL(
  "../../../services/operator-service/tests/fixtures/semantic_work_progress_trajectory.json",
  import.meta.url,
), "utf8")) as { readonly trajectory_detail: Record<string, unknown> };

const OBSERVED_AT = "2026-09-28T10:41:04Z";

function readinessSource(key: string, route: string, availability: "available" | "unavailable") {
  return {
    key,
    source: `${key}-store`,
    routes: [route],
    availability,
    configured: true,
    reachable: availability === "available",
    authoritative: true,
    durable: true,
    synthetic: false,
    reason: availability === "available" ? null : "The source did not respond.",
    last_observed_at: OBSERVED_AT,
  };
}

const READINESS = {
  surface: "read-data-sources",
  sources: [
    readinessSource("inventory", "/inventory/graph", "available"),
    readinessSource("incidents", "/incidents", "available"),
    readinessSource("audit", "/audit", "unavailable"),
    readinessSource("knowledge", "/rules", "available"),
    readinessSource("automation", "/scheduler-runs", "available"),
  ],
};

const ANSWER = "example-postgres is flagged because its backup retention is 3 days, below the "
  + "7-day minimum that the point-in-time restore rule requires. The policy check denies this "
  + "configuration.\n\nIt can't be fixed automatically: remediate.enable-backup-protection is in "
  + "shadow mode, so the finding was judged and logged without executing a change.";

const CODE_ANSWER = `${ANSWER}\n\nThe rule reads this setting:\n\n\`\`\`yaml\nbackup:\n  retention_days: 3\n  `
  + "point_in_time_restore: true\n```";

function claim(id: string, text: string, start: number, ref: string) {
  return {
    claim_id: id,
    kind: "number",
    text,
    span: { start, end: start + text.length },
    raw_value: text,
    normalized_value: text,
    unit: null,
    anchors: [ref],
    status: "supported",
    evidence_refs: [ref],
    reason_code: null,
  };
}

function verification(answer: string) {
  const retention = "3 days";
  const minimum = "7-day";
  return {
    status: "verified",
    authority: "server_read_model",
    checks_completed: 2,
    checks_total: 2,
    evidence_refs: ["e-retention", "e-minimum"],
    reason_code: null,
    claims: [
      claim("c-retention", retention, answer.indexOf(retention), "e-retention"),
      claim("c-minimum", minimum, answer.indexOf(minimum), "e-minimum"),
    ],
    failed_claim_ids: [],
    evidence_manifest: {
      schema_version: 1,
      manifest_id: "sha256:deck-layer-fixture",
      authority: "server_read_model",
      route_id: "inventory",
      captured_at: OBSERVED_AT,
      complete: true,
      source_entry_count: 2,
      entries: [
        {
          ref: "e-retention",
          path: "/resource/example-postgres/backup_retention_days",
          field: "backup_retention_days",
          kind: "number",
          raw_value: retention,
          normalized_value: retention,
          anchors: ["e-retention"],
        },
        {
          ref: "e-minimum",
          path: "/rule/postgresql-server.point-in-time-restore/min_retention_days",
          field: "min_retention_days",
          kind: "number",
          raw_value: minimum,
          normalized_value: minimum,
          anchors: ["e-minimum"],
        },
      ],
    },
  };
}

const SHA = (fill: string) => fill.repeat(64);

// Two captured provider calls: a planner call with a prompt manifest, then the answer stream.
const MODEL_TRACE = {
  schema_version: 1,
  redacted: true,
  omitted_calls: 0,
  calls: [
    {
      call_id: "call-plan",
      kind: "semantic-plan",
      model: "gpt-4.1-mini",
      status: "completed",
      started_at: "2026-09-28T10:41:00.100Z",
      completed_at: "2026-09-28T10:41:00.420Z",
      duration_ms: 320,
      request: {
        messages: [
          { role: "system", content: "You plan read-only evidence queries." },
          { role: "user", content: JSON.stringify({ question: "Why is example-postgres flagged?" }) },
        ],
        sha256: SHA("a"),
      },
      response: { role: "assistant", content: JSON.stringify({ goals: [{ read: "backup_retention_days" }] }), sha256: SHA("b") },
      usage: { prompt_tokens: 640, completion_tokens: 48, total_tokens: 688 },
      redactions: [{ rule: "subscription_id", replacements: 1 }],
      prompt_manifest: {
        system_text_sha256: SHA("c"),
        token_estimate: 412,
        layers: [
          { id: "bragi.planner", version: 3, layer: "role", token_estimate: 220 },
          { id: "fdai.safety", version: 7, layer: "policy", token_estimate: 192 },
        ],
        profile_id: "semantic-planner",
        profile_version: 2,
        profile_digest: `sha256:${SHA("d")}`,
        system_token_budget: 1200,
        request_token_budget: 6000,
        reserved_output_tokens: 800,
      },
    },
    {
      call_id: "call-answer",
      kind: "answer-stream",
      model: "gpt-4.1-mini",
      status: "completed",
      started_at: "2026-09-28T10:41:00.480Z",
      completed_at: "2026-09-28T10:41:00.896Z",
      duration_ms: 416,
      request: { messages: [{ role: "user", content: "Compose the grounded answer." }], sha256: SHA("e") },
      response: { role: "assistant", content: "example-postgres is flagged because ...", sha256: SHA("f") },
      usage: { prompt_tokens: 720, completion_tokens: 94, total_tokens: 814 },
      redactions: [],
    },
  ],
};

const RECORDED_START = Date.parse("2026-09-28T10:40:58.296Z");
const RECORDED_SPAN_MS = 8_000;
const REPLAY_SPAN_MS = 400;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

// Recorded fixtures carry fixed dates; replay them inside the live turn so the run record's time
// axis spans one realistic turn instead of the days between the recording and the test.
function replayTimes<T>(value: T, startedAt: number): T {
  return JSON.parse(JSON.stringify(value), (_key, item: unknown) => {
    if (typeof item !== "string" || !TIMESTAMP.test(item)) return item;
    // Six fractional digits are trimmed to milliseconds so every engine parses the instant.
    const recorded = Date.parse(item.replace(/(\.\d{3})\d+/, "$1"));
    const offset = ((recorded - RECORDED_START) / RECORDED_SPAN_MS) * REPLAY_SPAN_MS;
    return new Date(startedAt + Math.round(offset)).toISOString();
  }) as T;
}

const REF = "e-retention";

// An operational brief built from typed presentation blocks, plus a verified document artifact.
const STRUCTURED_REPLY = {
  presentation_artifact: {
    schema_version: 3,
    layout: "operational_brief",
    evidence_refs: [REF],
    assembly: {
      mode: "dynamic",
      label: "Operational brief",
      section_count: 5,
      input_kinds: ["verified_semantic_result", "presentation_context"],
      digest: `sha256:${"7d4c2a1f".repeat(8)}`,
    },
    blocks: [
      {
        slot_id: "root_cause", kind: "summary", title: "Recorded state", emphasis: "primary",
        collapsed: false, evidence_refs: [REF],
        data: { items: [
          { label: "Resource", value: "example-postgres", tone: "neutral" },
          { label: "Backup retention", value: "3 days", tone: "attention" },
          { label: "Required minimum", value: "7 days", tone: "neutral" },
          { label: "Remediation mode", value: "shadow", tone: "neutral" },
        ] },
      },
      {
        slot_id: "limitations", kind: "callout", title: "Limits", emphasis: "secondary",
        collapsed: false, evidence_refs: [REF],
        data: { tone: "warning", lines: [
          "Backup history before the last policy evaluation is unavailable.",
          "No restore was attempted, so recovery time is not claimed.",
        ] },
      },
      {
        slot_id: "evidence", kind: "evidence", title: "Evidence", emphasis: "supporting",
        collapsed: false, evidence_refs: [REF],
        data: { items: [
          { label: "Rule", value: "postgresql-server.point-in-time-restore" },
          { label: "Evaluation", value: "Denied by policy check" },
        ] },
      },
      {
        slot_id: "timeline", kind: "timeline", title: "Recorded timeline", emphasis: "supporting",
        collapsed: true, evidence_refs: [REF],
        data: {
          description: "Two recorded policy evaluations, oldest first.",
          items: [
            { timestamp: "2026-09-28T10:36:00Z", label: "Retention changed to 3 days" },
            { timestamp: "2026-09-28T10:41:00Z", label: "Policy check denied the configuration" },
          ],
          exact_table: {
            columns: [{ key: "c0", label: "timestamp" }, { key: "c1", label: "event" }],
            rows: [
              { c0: "2026-09-28T10:36:00Z", c1: "Retention changed to 3 days" },
              { c0: "2026-09-28T10:41:00Z", c1: "Policy check denied the configuration" },
            ],
            status_key: null,
          },
        },
      },
      {
        slot_id: "findings", kind: "table", title: "Findings", emphasis: "secondary",
        collapsed: false, evidence_refs: [REF],
        data: {
          columns: [{ key: "setting", label: "setting" }, { key: "state", label: "state" }],
          rows: [
            { setting: "backup_retention_days", state: "3 days" },
            { setting: "point_in_time_restore", state: "available" },
          ],
          status_key: "state",
        },
      },
    ],
  },
};

function documentArtifact(requestId: string) {
  return {
    document_artifact: {
      source_request_id: requestId,
      expected_rows: 12,
      included_rows: 12,
      complete: true,
      sha256: "b".repeat(64),
      preview_markdown: "# Backup posture\n\n- example-postgres keeps 3 days of backups.",
      markdown_url: `/chat/documents/${requestId}/markdown`,
    },
  };
}

// A semantic direct response is the main path; a model-routed answer also carries the run record.
function frames(
  requestId: string,
  runRecord: boolean,
  answer: string,
  extra: Record<string, unknown> = {},
): string {
  const startedAt = Date.now();
  const body: [string, Record<string, unknown>][] = [
    ["status", {
      seq: 1, revision: 1, phase: "retrieve", label: "Reading sources", completed: 1, total: 3,
      sources: [{
        kind: "inventory", label: "example-postgres", detail: "backup_retention_days 3", side_effect_class: "read",
      }],
    }],
    ["token", { seq: 2, revision: 1, delta: answer }],
    ["done", {
      seq: 3,
      revision: 1,
      request_id: requestId,
      answer,
      ...(runRecord ? {} : { source: "semantic-direct-response" }),
      model: "gpt-4.1-mini",
      latency_ms: 736,
      usage: { prompt_tokens: 1360, completion_tokens: 142, total_tokens: 1502 },
      verification: verification(answer),
      ...(runRecord ? { model_trace: replayTimes(MODEL_TRACE, startedAt) } : {}),
      trajectory_detail: replayTimes(GOLDEN.trajectory_detail, startedAt),
      ...extra,
    }],
  ];
  return body.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

async function openDeckWithAnswer(
  page: Page,
  runRecord = false,
  answer = ANSWER,
  extra: Record<string, unknown> = {},
) {
  // The insights client reads readiness outside the /api conversation prefix.
  await page.route("**/system/data-sources", (route) => route.fulfill({ json: READINESS }));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/chat/stream")) {
      const request = route.request().postDataJSON() as { readonly request_id: string };
      const body = frames(request.request_id, runRecord, answer, extra);
      // The terminal frame arrives after the replayed work, as it does from the server.
      await new Promise((resolve) => setTimeout(resolve, REPLAY_SPAN_MS + 50));
      await route.fulfill({ contentType: "text/event-stream", body });
    } else if (path.endsWith("/chat/health")) {
      await route.fulfill({ json: { available: true, mode: "test", model: "test" } });
    } else {
      await route.fulfill({ status: 404, json: { detail: "Unavailable in the conversation layer fixture" } });
    }
  });
  await page.goto("/overview?locale=en");
  await page.locator(".deck-invoke").click();
  const deck = page.locator(".deck-overlay");
  await expect(deck).toBeVisible();
  await page.locator(".deck-input").fill("Why is example-postgres flagged?");
  await page.locator(".deck-input").press("Enter");
  await expect(deck.locator(".cs-deck-agent-turn").last()).toContainText("can't be fixed automatically");
  await expect(deck.locator(".deck-turn.is-streaming")).toHaveCount(0);
  return deck;
}

interface LiveStream {
  /** Resolves with the request id once the deck opens the stream. */
  readonly opened: Promise<string>;
  readonly write: (event: string, data: Record<string, unknown>) => void;
  readonly end: (body?: string) => void;
  readonly close: () => Promise<void>;
}

// A local event stream keeps the turn open between frames, as the server does while it reads and
// answers, so the deck can be inspected mid-turn. Playwright redirects the chat stream to it.
async function liveStream(page: Page): Promise<LiveStream> {
  let response: ServerResponse | null = null;
  let resolveOpened: (requestId: string) => void = () => undefined;
  const opened = new Promise<string>((resolve) => { resolveOpened = resolve; });
  const server = createServer((request, reply) => {
    let body = "";
    request.on("data", (chunk) => { body += String(chunk); });
    request.on("end", () => {
      reply.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
      response = reply;
      resolveOpened((JSON.parse(body) as { readonly request_id: string }).request_id);
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as AddressInfo).port;
  await page.route("**/system/data-sources", (route) => route.fulfill({ json: READINESS }));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/chat/stream")) await route.continue({ url: `http://127.0.0.1:${port}/stream` });
    else if (path.endsWith("/chat/health")) {
      await route.fulfill({ json: { available: true, mode: "test", model: "gpt-4.1-mini" } });
    } else await route.fulfill({ status: 404, json: { detail: "Unavailable in the conversation layer fixture" } });
  });
  return {
    opened,
    write: (event, data) => { (response as ServerResponse | null)?.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`); },
    end: (body) => { (response as ServerResponse | null)?.end(body); },
    close: async () => {
      (response as ServerResponse | null)?.destroy();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    },
  };
}

// A read that is still running reports its execution without an end, an output, or a duration.
function runningRead(read: Record<string, unknown>): Record<string, unknown> {
  const { completed_at: _end, duration_ms: _duration, output: _output, ...execution } =
    read.execution as Record<string, unknown>;
  const { detail: _detail, ...pending } = read;
  return { ...pending, status: "running", execution: { ...execution, status: "running" } };
}

async function askInWorkspace(page: Page) {
  await page.goto("/overview?locale=en");
  await page.locator(".deck-invoke").click();
  const deck = page.locator(".deck-overlay");
  await deck.getByRole("button", { name: "Full workspace", exact: true }).click();
  await page.locator(".deck-input").fill("Why is example-postgres flagged?");
  await page.locator(".deck-input").press("Enter");
  return deck;
}

test.describe("Command Deck conversation layer", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Each test sets its own viewport.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  test("renders a settled grounded answer on the shared conversation roles", async ({ page }, testInfo) => {
    const deck = await openDeckWithAnswer(page);
    await page.screenshot({ path: testInfo.outputPath("deck-layer-dock.png") });
    await deck.getByRole("button", { name: "Full workspace", exact: true }).click();
    await page.screenshot({ path: testInfo.outputPath("deck-layer-workspace.png") });
    const layout = await deck.evaluate((root) => {
      const visible = (element: Element) => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && box.height > 0 && getComputedStyle(element).visibility !== "hidden";
      };
      // Readable conversation text only: the header chrome is outside the layer, and aria-hidden
      // status marks are glyphs inside a sized circle rather than text.
      const text = [...root.querySelectorAll("*")].filter((element) =>
        visible(element) && !element.closest(".deck-header, [aria-hidden='true']")
        && [...element.childNodes].some((node) => node.nodeType === 3 && node.textContent?.trim()));
      const transcript = root.querySelector(".deck-transcript")!;
      return {
        small: text.filter((element) => parseFloat(getComputedStyle(element).fontSize) < 12)
          .map((element) => `${element.className}: ${element.textContent?.trim().slice(0, 40)}`),
        transcriptFits: transcript.scrollWidth <= transcript.clientWidth,
        documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    });
    expect(layout.transcriptFits).toBe(true);
    expect(layout.documentFits).toBe(true);
    expect(layout.small).toEqual([]);
    await testInfo.attach("layout", { body: JSON.stringify(layout, null, 2), contentType: "application/json" });

    const reply = deck.locator(".cs-deck-agent-turn").last();
    const verdict = reply.locator(".cs-deck-action-row .cs-deck-verification.is-verified");
    await expect(verdict).toContainText("2/2 claims supported");
    await expect(reply.locator(".cs-deck-answer .cs-deck-cite")).toHaveCount(2);
    const pill = reply.locator(".cs-deck-action-row .cs-deck-pill");
    await expect(pill).toHaveAttribute("aria-expanded", "false");
    await pill.click();
    await expect(pill).toHaveAttribute("aria-expanded", "true");
    const sources = reply.locator(`[id="${await pill.getAttribute("aria-controls")}"]`);
    // Answer evidence lists each source as the layer's source disclosure.
    await expect(sources.getByRole("heading", { name: "Answer evidence" })).toBeVisible();
    await expect(sources.locator("summary.cs-deck-source")).toHaveCount(2);
    await sources.locator("summary.cs-deck-source").first().click();
    await expect(sources.locator(".cs-deck-source-path").first()).toBeVisible();
    await expect(sources.locator(".cs-deck-source-path").first()).toContainText("backup_retention_days");
    await page.screenshot({ path: testInfo.outputPath("deck-layer-sources.png") });
    // A numbered citation opens its source, and Back to answer returns focus to that citation.
    await sources.getByRole("button", { name: "Back to answer" }).click();
    await expect(sources).toHaveCount(0);
    const cite = reply.locator(".cs-deck-answer button.cs-deck-cite").first();
    await cite.click();
    await expect(reply.locator(".deck-src-detail").first()).toHaveAttribute("open", "");
    await expect(reply.locator(".deck-src-detail summary").first()).toBeFocused();
    await reply.getByRole("button", { name: "Back to answer" }).click();
    await expect(cite).toBeFocused();
  });

  test("keeps the grounded answer footer operable on a narrow screen", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const deck = await openDeckWithAnswer(page);
    const reply = deck.locator(".cs-deck-agent-turn").last();
    await reply.locator(".cs-deck-pill").click();
    await reply.locator(".cs-deck-sources").scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath("deck-layer-narrow.png") });
    const footer = await reply.locator(".cs-deck-action-row").evaluate((row) => {
      const box = row.getBoundingClientRect();
      const verdict = row.querySelector(".cs-deck-verification")!.parentElement!.getBoundingClientRect();
      const controls = [...row.querySelectorAll("button, a")].map((control) => control.getBoundingClientRect());
      return {
        verdictFillsLine: Math.abs(verdict.width - box.width) <= 1,
        smallestControl: Math.min(...controls.map((control) => Math.min(control.width, control.height))),
        documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      };
    });
    expect(footer.verdictFillsLine).toBe(true);
    expect(footer.smallestControl).toBeGreaterThanOrEqual(44);
    expect(footer.documentFits).toBe(true);
  });

  test("renders the live grounding trace while the answer is prepared", async ({ page }, testInfo) => {
    const stream = await liveStream(page);
    try {
      const deck = await askInWorkspace(page);
      const requestId = await stream.opened;
      const sources = ["backup_retention_days 3", "min_retention_days 7", "rule shadow mode", "policy deny"]
        .map((detail, index) => ({
          kind: index < 2 ? "inventory" : "rule",
          label: `source-${index + 1}`,
          detail,
          side_effect_class: "read",
        }));
      stream.write("status", {
        seq: 1, revision: 1, phase: "retrieve", label: "Reading sources", completed: 1, total: 3, sources,
      });

      const trace = deck.locator(".deck-rt-turn");
      const panel = trace.locator(".cs-grounding-panel");
      await expect(panel).toBeVisible();
      await expect(panel.locator(".cs-grounding-authority")).toHaveText("Read-only");
      // The head counts steps; the active row alone names the current step.
      await expect(panel.locator(".cs-grounding-status")).toHaveText(/^Step \d+ of \d+$/);
      await expect(panel.locator(".cs-grounding-stage.is-active .cs-grounding-stage-label"))
        .toHaveText("Reading sources");
      await expect(panel.locator(".cs-grounding-stage.is-active .cs-grounding-spinner")).toHaveCount(1);
      await expect(panel.locator(".cs-grounding-sources-head")).toContainText("4/4");
      await expect(panel.locator(".cs-grounding-source")).toHaveCount(3);
      await expect(trace.locator(".cs-deck-answer-skeleton > .cs-deck-skeleton")).toHaveCount(3);
      await page.screenshot({ path: testInfo.outputPath("deck-layer-preparing.png") });
      const small = await trace.evaluate((root) => [...root.querySelectorAll("*")]
        .filter((element) => {
          const box = element.getBoundingClientRect();
          return box.width > 0 && box.height > 0 && !element.closest("[aria-hidden='true'], .sr-only")
            && [...element.childNodes].some((node) => node.nodeType === 3 && node.textContent?.trim())
            && parseFloat(getComputedStyle(element).fontSize) < 12;
        })
        .map((element) => `${element.className || element.tagName}: ${element.textContent?.trim().slice(0, 40)}`));
      expect(small).toEqual([]);

      stream.end(frames(requestId, false, ANSWER).split("\n\n").slice(1).join("\n\n"));
      await expect(deck.locator(".cs-deck-agent-turn").last()).toContainText("can't be fixed automatically");
      await expect(trace).toHaveCount(0);
    } finally {
      await stream.close();
    }
  });

  test("reveals the verdict, stops for a reader, and follows the bottom on request", async ({ page }) => {
    const paragraphs = Array.from({ length: 40 }, (_, index) =>
      `Paragraph ${index + 1}: the read-only evidence for this finding stays attached to the turn.`)
      .join("\n\n");
    const deck = await openDeckWithAnswer(page, false, `${ANSWER}\n\n${paragraphs}`);
    await deck.getByRole("button", { name: "Full workspace", exact: true }).click();
    const transcript = deck.locator(".deck-transcript");
    const reply = deck.locator(".cs-deck-agent-turn").last();
    const jump = deck.getByRole("button", { name: "Jump to latest message" });
    const position = () => transcript.evaluate((element) => ({
      scrollTop: element.scrollTop,
      fromBottom: element.scrollHeight - element.clientHeight - element.scrollTop,
    }));
    // New content lands at the end of the transcript, as an arriving turn would.
    const append = (height: number) => transcript.evaluate((element, size) => {
      const block = document.createElement("div");
      block.className = "deck-layer-fixture-growth";
      block.style.height = `${size}px`;
      element.firstElementChild!.append(block);
    }, height);

    // Verdict reveal: the settled answer shows its verification row instead of only its start.
    await expect(reply.locator(".cs-deck-action-row")).toBeInViewport();
    await expect(jump).toBeHidden();

    // Reader-scrolled: a reader who scrolls away is never moved by arriving content.
    await transcript.hover();
    await page.mouse.wheel(0, -600);
    await expect(jump).toBeVisible();
    const reading = (await position()).scrollTop;
    await append(500);
    await page.waitForTimeout(150);
    expect(Math.abs((await position()).scrollTop - reading)).toBeLessThanOrEqual(1);

    // Bottom follow: Jump to latest follows the newest content as it arrives.
    await jump.click();
    await expect(jump).toBeHidden();
    await append(500);
    await expect.poll(async () => (await position()).fromBottom).toBeLessThanOrEqual(32);
    await expect(jump).toBeHidden();
  });

  test("renders structured answer blocks and documents on the layer's roles", async ({ page }, testInfo) => {
    // A tall viewport keeps the whole reply inside the transcript for one element screenshot.
    await page.setViewportSize({ width: 1440, height: 2400 });
    // The document contract requires a request UUID; generating it keeps GUID literals out of source.
    const documentRequest = randomUUID();
    const deck = await openDeckWithAnswer(page, false, ANSWER, {
      ...STRUCTURED_REPLY,
      ...documentArtifact(documentRequest),
    });
    await deck.getByRole("button", { name: "Full workspace", exact: true }).click();
    const reply = deck.locator(".cs-deck-agent-turn").last();
    const brief = reply.locator('.deck-presentation[data-layout="operational_brief"]');
    await expect(brief.locator(".cs-deck-document-assembly")).toContainText("Operational brief");
    await expect(brief.locator(".cs-deck-answer-facts > div")).toHaveCount(4);
    // An attention value takes the layer's attention color; neutral values keep the text color.
    const toneColors = await brief.locator(".cs-deck-answer-facts > div").evaluateAll((items) =>
      items.map((item) => `${item.getAttribute("data-tone")}:${getComputedStyle(item.querySelector("dd")!).color}`));
    expect(new Set(toneColors.filter((entry) => entry.startsWith("neutral:"))).size).toBe(1);
    expect(toneColors.find((entry) => entry.startsWith("attention:"))?.split(":")[1])
      .not.toBe(toneColors.find((entry) => entry.startsWith("neutral:"))?.split(":")[1]);
    await expect(brief.locator(".cs-deck-evidence-note[role='note'] li")).toHaveCount(2);
    await expect(brief.locator(".deck-presentation-evidence.cs-run-facts dt")).toHaveText(["Rule", "Evaluation"]);
    const timeline = brief.locator("details.deck-presentation-block.cs-deck-disclosure");
    await expect(timeline).not.toHaveAttribute("open", "");
    await timeline.locator(":scope > .cs-deck-disclosure-summary").click();
    await expect(timeline.locator(".deck-presentation-timeline > li")).toHaveCount(2);
    await expect(timeline.locator(".deck-presentation-exact-values .cs-deck-disclosure-meta")).toHaveText("2 rows");

    const documentCard = reply.locator("article.deck-document-artifact.cs-deck-document");
    await expect(documentCard.locator(".cs-deck-document-title")).toHaveText("Verified document");
    await expect(documentCard.locator(".cs-deck-document-meta dd").first()).toHaveText("12");
    await documentCard.locator(":scope > details > .cs-deck-disclosure-summary").click();
    await expect(documentCard.locator(".deck-document-artifact-preview")).toContainText("Backup posture");
    await expect(documentCard.getByRole("button", { name: "Download Markdown" })).toHaveClass(/cs-deck-affordance/);

    await reply.screenshot({ path: testInfo.outputPath("deck-layer-blocks.png") });
    const layout = await reply.evaluate((root) => ({
      small: [...root.querySelectorAll("*")].filter((element) => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && box.height > 0 && !element.closest("[aria-hidden='true'], .sr-only, svg")
          && [...element.childNodes].some((node) => node.nodeType === 3 && node.textContent?.trim())
          && parseFloat(getComputedStyle(element).fontSize) < 12;
      }).map((element) => `${element.className || element.tagName}: ${element.textContent?.trim().slice(0, 30)}`),
      uppercase: [...root.querySelectorAll(".deck-presentation *")]
        .filter((element) => getComputedStyle(element).textTransform === "uppercase").length,
      overflow: root.scrollWidth - root.clientWidth,
    }));
    expect(layout).toEqual({ small: [], uppercase: 0, overflow: 0 });
  });

  test("renders answer code on the shared code surface", async ({ page }, testInfo) => {
    const deck = await openDeckWithAnswer(page, false, CODE_ANSWER);
    await deck.getByRole("button", { name: "Full workspace", exact: true }).click();
    const code = deck.locator(".cs-deck-agent-turn").last().locator(".cs-deck-code");
    await expect(code.locator(".cs-deck-code-lang")).toHaveText("yaml");
    const copy = code.getByRole("button", { name: "Copy yaml" });
    await expect(copy).toHaveText("Copy");
    const colors = await code.evaluate((figure) => ({
      surface: getComputedStyle(figure).backgroundColor,
      block: getComputedStyle(figure.querySelector("pre")!).backgroundColor,
      key: getComputedStyle(figure.querySelector(".hljs-attr")!).color,
      wraps: getComputedStyle(figure.querySelector(".cs-deck-code-text")!).whiteSpace,
    }));
    // The Console's bare pre styling must not paint a second, light field inside the code surface.
    expect(colors).toEqual({
      surface: "rgb(34, 42, 49)",
      block: "rgba(0, 0, 0, 0)",
      key: "rgb(142, 182, 217)",
      wraps: "pre-wrap",
    });
    await code.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath("deck-layer-code.png") });
  });

  test("asks before a deck link leaves the conversation", async ({ page }, testInfo) => {
    const deck = await openDeckWithAnswer(page);
    await deck.getByRole("button", { name: "Full workspace", exact: true }).click();
    const review = deck.locator(".cs-deck-agent-turn").last().locator(".deck-gr-review");
    const dialog = page.getByRole("dialog", { name: "Open Conversation assurance?" });

    await review.click();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Stay here" })).toBeFocused();
    await page.screenshot({ path: testInfo.outputPath("deck-layer-leave.png") });
    await dialog.getByRole("button", { name: "Stay here" }).click();
    await expect(dialog).toBeHidden();
    await expect(page).toHaveURL(/\/overview\?locale=en$/);
    await expect(deck).toBeVisible();

    await review.click();
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await expect(deck).toBeVisible();

    await review.click();
    await dialog.getByRole("button", { name: "Open Conversation assurance" }).click();
    await expect(page).toHaveURL(/\/conversation-assurance\?turn=/);
    await expect(deck).toBeHidden();
  });

  test("renders the investigation plan, settled limits, and context receipt", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 1400 });
    const stream = await liveStream(page);
    try {
      const deck = await askInWorkspace(page);
      const requestId = await stream.opened;
      const detail = replayTimes(GOLDEN.trajectory_detail, Date.now());
      const reads = detail.activities as readonly Record<string, unknown>[];
      let seq = 0;
      const send = (event: string, data: Record<string, unknown>) =>
        stream.write(event, { seq: ++seq, revision: 0, ...data });
      // The pin precedes the first read; a milestone closes the first wave before the second runs.
      send("work_progress", { work_progress_shape: detail.work_progress_shape });
      send("activity", reads[0]!);
      send("activity", reads[1]!);
      send("milestone", {
        message_id: "wave-1",
        text: "The first wave finished with 2 completed reads.",
        recorded_at: new Date().toISOString(),
      });
      const panels = deck.locator(".deck-investigation");
      const answerTurn = deck.locator(".deck-turn-deck .cs-deck-answer");
      // Wave gating: the pinned plan has a third read, so the pause between waves starts no answer.
      const milestone = deck.locator(".cs-deck-milestone");
      await expect(milestone.locator(".cs-deck-milestone-text")).toHaveText(
        "The first wave finished with 2 completed reads.",
      );
      await expect(milestone.locator(".cs-deck-milestone-label")).toHaveText("Progress update");
      await page.waitForTimeout(300);
      await expect(answerTurn).toHaveCount(0);
      await expect(panels).toHaveCount(1);
      send("activity", runningRead(reads[2]!));

      await expect(panels).toHaveCount(2);
      await expect(panels.last()).toHaveClass(/is-running/);
      await page.screenshot({ path: testInfo.outputPath("deck-layer-investigation-running.png") });
      const lead = panels.first();
      await expect(lead.locator(".cs-deck-investigation-status")).toHaveText("Planned: 2 waves, 3 reads");
      // The derived start note is one quiet lead line that starts where the panel titles do.
      const startLine = deck.locator(".deck-start-note.cs-deck-plan-lead");
      await expect(startLine.locator(".cs-deck-plan-label")).toHaveText("Starting work");
      await expect(startLine).toContainText("Querying Ontology query with read-only authority.");
      const startAlignment = await startLine.evaluate((line) => {
        const title = line.closest(".deck-turn")!.querySelector(".cs-work-summary-title")!;
        return Math.abs(line.getBoundingClientRect().left - title.getBoundingClientRect().left);
      });
      expect(startAlignment).toBeLessThanOrEqual(2);
      // Limits are end-of-turn telemetry, so nothing claims a used amount while the turn runs.
      await expect(deck.locator(".cs-deck-investigation-limits")).toHaveCount(0);
      await expect(deck.locator(".cs-deck-context-receipt")).toHaveCount(0);

      send("activity", reads[2]!);
      const answer = "The resources and their health were read, and the comparison found no drift.";
      send("token", { delta: answer });
      stream.end(`event: done\ndata: ${JSON.stringify({
        seq: ++seq,
        revision: 0,
        request_id: requestId,
        answer,
        model: "gpt-4.1-mini",
        latency_ms: 736,
        usage: { prompt_tokens: 1360, completion_tokens: 142, total_tokens: 1502 },
        verification: verification(answer),
        trajectory_detail: detail,
      })}\n\n`);
      await expect(deck.locator(".deck-turn.is-streaming")).toHaveCount(0);
      await expect(lead).toHaveClass(/is-answer-settled/);
      await expect(startLine).toHaveCount(0);
      await page.screenshot({ path: testInfo.outputPath("deck-layer-investigation-settled.png") });

      await expect(lead.locator(".cs-deck-investigation-limits")).toHaveText(
        "Used: 3 of 5 model calls, 4.4k of 48k tokens, 3.1 s of 60 s",
      );
      await expect(deck.locator(".cs-deck-investigation-limits")).toHaveCount(1);
      await expect(deck.locator(".cs-deck-investigation-status")).toHaveCount(1);
      const receipt = deck.locator("details.cs-deck-context-receipt");
      await expect(receipt).toHaveCount(1);
      await expect(receipt.locator(".cs-deck-context-receipt-label")).toHaveText("Context applied");
      await expect(receipt.locator(".cs-deck-context-receipt-value")).toHaveText("Conversation model: T2");
      await receipt.locator(".cs-deck-context-receipt-summary").click();
      await expect(receipt.locator(".cs-deck-context-receipt-note")).toHaveText(
        "Context only: it shapes the presentation and is not evidence or instructions.",
      );
      const entry = receipt.locator(".cs-deck-context-receipt-list > li");
      await expect(entry).toHaveAttribute("data-freshness", "fresh");
      await expect(entry.locator(".cs-deck-context-receipt-freshness")).toHaveText("Current");
      await expect(entry.locator("code")).toHaveText("60f41d18b86b");
      await page.screenshot({ path: testInfo.outputPath("deck-layer-investigation-receipt.png") });

      const layout = await deck.evaluate((root) => {
        const text = [...root.querySelectorAll(".deck-investigation, .cs-deck-context-receipt")]
          .flatMap((scope) => [scope, ...scope.querySelectorAll("*")])
          .filter((element) => {
            const box = element.getBoundingClientRect();
            return box.width > 0 && box.height > 0 && !element.closest("[aria-hidden='true'], .sr-only")
              && [...element.childNodes].some((node) => node.nodeType === 3 && node.textContent?.trim());
          });
        const transcript = root.querySelector(".deck-transcript")!;
        return {
          small: text.filter((element) => parseFloat(getComputedStyle(element).fontSize) < 12)
            .map((element) => `${element.className}: ${element.textContent?.trim().slice(0, 40)}`),
          transcriptFits: transcript.scrollWidth <= transcript.clientWidth,
        };
      });
      expect(layout.small).toEqual([]);
      expect(layout.transcriptFits).toBe(true);

      // On a phone the turn-wide facts wrap inside the head instead of widening the transcript.
      await page.setViewportSize({ width: 390, height: 844 });
      await lead.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath("deck-layer-investigation-narrow.png") });
      const narrow = await lead.evaluate((panel) => {
        const head = panel.querySelector(":scope > summary")!.getBoundingClientRect();
        const facts = panel.querySelector(".deck-investigation-turn-facts")!.getBoundingClientRect();
        const transcript = panel.closest(".deck-transcript")!;
        return {
          factsInsideHead: facts.left >= head.left - 0.5 && facts.right <= head.right + 0.5,
          factsBelowTitle: facts.top >= panel.querySelector(".cs-work-summary-title")!.getBoundingClientRect().bottom - 0.5,
          transcriptFits: transcript.scrollWidth <= transcript.clientWidth,
        };
      });
      expect(narrow).toEqual({ factsInsideHead: true, factsBelowTitle: true, transcriptFits: true });
    } finally {
      await stream.close();
    }
  });

  test("renders the investigation roles from the Korean catalog on a phone", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const stream = await liveStream(page);
    try {
      await page.goto("/overview?locale=ko");
      await page.locator(".deck-invoke").click();
      const deck = page.locator(".deck-overlay");
      await page.locator(".deck-input").fill("example-postgres가 표시된 이유는 무엇인가요?");
      await page.locator(".deck-input").press("Enter");
      const requestId = await stream.opened;
      const detail = replayTimes(GOLDEN.trajectory_detail, Date.now());
      let seq = 0;
      const send = (event: string, data: Record<string, unknown>) =>
        stream.write(event, { seq: ++seq, revision: 0, ...data });
      send("work_progress", { work_progress_shape: detail.work_progress_shape });
      for (const read of detail.activities as readonly Record<string, unknown>[]) send("activity", read);
      const answer = "The resources and their health were read, and the comparison found no drift.";
      send("token", { delta: answer });
      stream.end(`event: done\ndata: ${JSON.stringify({
        seq: ++seq,
        revision: 0,
        request_id: requestId,
        answer,
        model: "gpt-4.1-mini",
        latency_ms: 736,
        usage: { prompt_tokens: 1360, completion_tokens: 142, total_tokens: 1502 },
        verification: verification(answer),
        trajectory_detail: detail,
      })}\n\n`);
      await expect(deck.locator(".deck-turn.is-streaming")).toHaveCount(0);

      const lead = deck.locator(".deck-investigation").first();
      await expect(lead.locator(".cs-deck-investigation-status")).toHaveText("계획: 웨이브 2개, 조회 3건");
      await expect(lead.locator(".cs-deck-investigation-limits")).toHaveText(
        "사용량: 모델 호출 3/5회, 토큰 4.4k/48k, 시간 3.1 s/60 s",
      );
      const receipt = deck.locator("details.cs-deck-context-receipt");
      await expect(receipt.locator(".cs-deck-context-receipt-label")).toHaveText("적용된 맥락");
      await receipt.locator(".cs-deck-context-receipt-summary").click();
      await expect(receipt.locator(".cs-deck-context-receipt-note")).toHaveText(
        "맥락일 뿐입니다. 표현 방식에만 영향을 주며 근거나 지시가 아닙니다.",
      );
      await expect(receipt.locator(".cs-deck-context-receipt-freshness")).toHaveText("현재");
      await lead.scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath("deck-layer-investigation-ko.png") });
      const layout = await lead.evaluate((panel) => {
        const head = panel.querySelector(":scope > summary")!.getBoundingClientRect();
        const facts = panel.querySelector(".deck-investigation-turn-facts")!.getBoundingClientRect();
        const transcript = panel.closest(".deck-transcript")!;
        return {
          factsInsideHead: facts.left >= head.left - 0.5 && facts.right <= head.right + 0.5,
          transcriptFits: transcript.scrollWidth <= transcript.clientWidth,
          documentFits: document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        };
      });
      expect(layout).toEqual({ factsInsideHead: true, transcriptFits: true, documentFits: true });
    } finally {
      await stream.close();
    }
  });

  test("marks reads that a stop interrupted as stopped", async ({ page }, testInfo) => {
    const stream = await liveStream(page);
    try {
      const deck = await askInWorkspace(page);
      await stream.opened;
      const detail = replayTimes(GOLDEN.trajectory_detail, Date.now());
      const reads = detail.activities as readonly Record<string, unknown>[];
      let seq = 0;
      const send = (event: string, data: Record<string, unknown>) =>
        stream.write(event, { seq: ++seq, revision: 0, ...data });
      send("work_progress", { work_progress_shape: detail.work_progress_shape });
      send("activity", reads[0]!);
      send("activity", runningRead(reads[1]!));
      const panel = deck.locator(".deck-investigation");
      await expect(panel).toHaveClass(/is-running/);
      await deck.getByRole("button", { name: "Stop", exact: true }).click();
      await expect(panel).not.toHaveClass(/is-running/);
      await panel.locator(":scope > summary").click();
      await page.screenshot({ path: testInfo.outputPath("deck-layer-investigation-stopped.png") });
      const items = panel.locator(".deck-investigation-item");
      await expect(items).toHaveCount(2);
      await expect(items.first()).toHaveClass(/is-completed/);
      await expect(items.last()).toHaveClass(/is-stopped/);
      await expect(items.last()).toContainText("Stopped");
      await expect(items.last()).not.toContainText("In progress");
      // A stopped turn reports no budget: only a settled answer carries the server's telemetry.
      await expect(panel.locator(".cs-deck-investigation-status")).toHaveText("Planned: 2 waves, 3 reads");
      await expect(deck.locator(".cs-deck-investigation-limits")).toHaveCount(0);
    } finally {
      await stream.close();
    }
  });

  test("renders the run record of a model-routed answer", async ({ page }, testInfo) => {
    // A tall viewport keeps the whole open record inside the transcript for one element screenshot.
    await page.setViewportSize({ width: 1440, height: 3200 });
    await page.addInitScript(() => localStorage.setItem("fdai:console:show-model-trace", "true"));
    const deck = await openDeckWithAnswer(page, true);
    await deck.getByRole("button", { name: "Full workspace", exact: true }).click();
    await expect(deck.locator(".cs-run-record")).toBeVisible();
    await deck.locator(".cs-run-record > summary").click();
    // The processing disclosure; the original Markdown disclosure sits inside the answer body.
    const disclosure = deck.locator(".cs-deck-agent-turn").last()
      .locator("details.cs-deck-disclosure:not(.deck-answer-original)");
    await disclosure.locator(".cs-deck-disclosure-summary").click();
    await expect(disclosure.locator(".cs-deck-disclosure-body")).toContainText("gpt-4.1-mini");

    const record = deck.locator(".cs-run-record");
    const timeline = record.locator(".cs-run-timeline");
    await expect(timeline.locator(".cs-run-event")).not.toHaveCount(0);
    await timeline.locator(".cs-run-event-summary").first().click();
    await expect(timeline.locator(".cs-run-event-detail .cs-run-facts").first()).toBeVisible();
    const trace = record.locator(".cs-model-trace");
    await expect(trace.locator(".cs-model-trace-lane")).toHaveCount(2);
    await trace.locator(".cs-model-trace-lane-summary").first().click();
    const lane = trace.locator(".cs-model-trace-lane").first();
    await expect(lane.locator(".cs-model-trace-layers > li")).toHaveCount(2);
    await expect(lane.locator(".cs-model-trace-role")).toHaveText(["system", "user"]);
    await expect(lane.locator(".cs-deck-code").first()).toBeVisible();
    // The Console-only execution details keep the same readable scale as the layer roles.
    await record.locator(".deck-trajectory-records > summary").click();
    await expect(record.locator(".deck-trajectory-events")).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath("deck-layer-run-record.png") });
    await record.screenshot({ path: testInfo.outputPath("deck-layer-run-record-body.png") });

    const small = await record.evaluate((root) => [...root.querySelectorAll("*")]
      .filter((element) => {
        const box = element.getBoundingClientRect();
        return box.width > 0 && box.height > 0 && !element.closest("[aria-hidden='true'], .sr-only")
          && [...element.childNodes].some((node) => node.nodeType === 3 && node.textContent?.trim())
          && parseFloat(getComputedStyle(element).fontSize) < 12;
      })
      .map((element) => `${element.className || element.tagName} ${getComputedStyle(element).fontSize}: ${element.textContent?.trim().slice(0, 40)}`));
    expect(small).toEqual([]);
  });
});
