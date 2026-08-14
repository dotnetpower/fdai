import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";
import {
  buildAssuranceRunProvenance,
  judgeSemanticTurn,
  type AssuranceRunConfiguration,
} from "./ontology-query-assurance";

const TEST_TIMEOUT_MS = 4 * 60 * 1_000;
const AUTHENTICATED_EXTERNAL_STACK = Boolean(
  process.env.FDAI_E2E_BASE_URL && process.env.FDAI_E2E_STORAGE_STATE,
);

interface CapturedFrame {
  readonly event: string;
  readonly data: Record<string, unknown>;
}

interface CapturedTerminal {
  readonly frames: readonly CapturedFrame[];
  readonly done: Record<string, unknown>;
}

interface CapturedRequest {
  readonly prompt: string;
  readonly requestId: unknown;
  readonly locale: unknown;
  readonly history: readonly { readonly role: unknown; readonly content: unknown }[];
  readonly conversationContext: unknown;
}

function parseFrames(body: string): CapturedTerminal {
  const frames: CapturedFrame[] = [];
  for (const rawFrame of body.split(/\r?\n\r?\n/)) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of rawFrame.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (dataLines.length === 0) continue;
    const parsed = JSON.parse(dataLines.join("\n")) as unknown;
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) continue;
    frames.push({ event, data: parsed as Record<string, unknown> });
  }
  const done = frames.findLast((frame) => frame.event === "done")?.data;
  if (!done) throw new Error("semantic presentation stream did not contain a done frame");
  return { frames, done };
}

function object(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${field} must be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, field: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error(`${field} must be an array`);
  return value;
}

function text(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${field} must be nonempty text`);
  }
  return value;
}

function digest(value: unknown): string {
  return `sha256:${createHash("sha256").update(JSON.stringify(value)).digest("hex")}`;
}

function incidentContract(terminal: CapturedTerminal) {
  const done = terminal.done;
  if (done.status !== "answered") {
    const semantic = object(done.semantic_result, "semantic_result");
    throw new Error(
      `semantic presentation requires answered terminal: ${String(semantic.reason_code)}`,
    );
  }
  const verification = object(done.verification, "verification");
  const receipt = object(done.semantic_receipt, "semantic_receipt");
  const presentation = object(done.presentation_artifact, "presentation_artifact");
  const trajectory = object(done.trajectory_detail, "trajectory_detail");
  const context = object(done.conversation_context, "conversation_context");
  const activities = array(trajectory.activities, "trajectory_detail.activities");
  const activity = object(activities[0], "trajectory_detail.activities[0]");
  const execution = object(activity.execution, "trajectory activity execution");
  const technical = JSON.parse(text(execution.output, "execution.output")) as unknown;
  const technicalRecord = object(technical, "technical output");
  const outputs = array(technicalRecord.outputs, "technical output outputs");
  const incident = object(outputs[0], "technical incident output");
  const profile = object(incident.incident_profile, "incident profile");
  const nextStep = object(incident.next_safe_step, "next safe step");
  const blocks = array(presentation.blocks, "presentation blocks").map((value, index) =>
    object(value, `presentation blocks[${index}]`)
  );
  const phases = terminal.frames
    .filter((frame) => frame.event === "status" || frame.event === "verification")
    .map((frame) => frame.data.phase)
    .filter((phase): phase is string => typeof phase === "string");
  const answer = text(done.answer, "answer");
  const judgment = judgeSemanticTurn(done.semantic_receipt, done.verification);

  return {
    judgment,
    phases,
    answer,
    receipt,
    verification,
    context,
    profile,
    nextStep,
    technical,
    blocks,
    presentation,
  };
}

async function installStreamCapture(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const target = window as Window & {
      __fdaiSemanticPresentationRequests?: CapturedRequest[];
      __fdaiSemanticPresentationStreams?: Promise<string>[];
    };
    const originalFetch = window.fetch;
    target.__fdaiSemanticPresentationRequests = [];
    target.__fdaiSemanticPresentationStreams = [];
    window.fetch = async (...args) => {
      const input = args[0];
      const requestUrl = typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
      const method = args[1]?.method ?? (input instanceof Request ? input.method : "GET");
      if (
        method.toUpperCase() === "POST" &&
        new URL(requestUrl, window.location.href).pathname.endsWith("/chat/stream")
      ) {
        const body = args[1]?.body;
        if (typeof body === "string") {
          const parsed = JSON.parse(body) as Record<string, unknown>;
          const history = Array.isArray(parsed.history)
            ? parsed.history.filter((turn): turn is { role: unknown; content: unknown } => (
                typeof turn === "object" && turn !== null && !Array.isArray(turn)
              ))
            : [];
          target.__fdaiSemanticPresentationRequests?.push({
            prompt: typeof parsed.prompt === "string" ? parsed.prompt : "",
            requestId: parsed.request_id,
            locale: parsed.locale,
            history,
            conversationContext: parsed.conversation_context,
          });
        }
      }
      const response = await originalFetch.apply(window, args);
      if (
        method.toUpperCase() === "POST" &&
        new URL(requestUrl, window.location.href).pathname.endsWith("/chat/stream")
      ) {
        target.__fdaiSemanticPresentationStreams?.push(response.clone().text());
      }
      return response;
    };
  });
}

async function requestDiagnostics(page: Page) {
  const requests = await page.evaluate(() => (
    (window as Window & { __fdaiSemanticPresentationRequests?: CapturedRequest[] })
      .__fdaiSemanticPresentationRequests ?? []
  ));
  return requests.map((request) => ({
    prompt_digest: digest(request.prompt),
    request_id_digest: digest(request.requestId),
    locale: request.locale,
    history_roles: request.history.map((turn) => turn.role),
    history_content_digests: request.history.map((turn) => digest(turn.content)),
    conversation_context_digest: digest(request.conversationContext),
  }));
}

async function capturedBodies(page: Page): Promise<readonly string[]> {
  return page.evaluate(async () => {
    const streams = (window as Window & {
      __fdaiSemanticPresentationStreams?: Promise<string>[];
    }).__fdaiSemanticPresentationStreams ?? [];
    return Promise.all(streams);
  });
}

async function waitForCaptureCount(page: Page, minimum: number): Promise<void> {
  await page.waitForFunction((expected) => {
    const streams = (window as Window & {
      __fdaiSemanticPresentationStreams?: Promise<string>[];
    }).__fdaiSemanticPresentationStreams ?? [];
    return streams.length >= expected;
  }, minimum);
}

test("authenticated Korean incident answer retains progressive presentation through regeneration", async ({
  page,
}, testInfo) => {
  test.skip(
    !AUTHENTICATED_EXTERNAL_STACK,
    "requires an external Console and Browser Entra storage state",
  );
  test.setTimeout(TEST_TIMEOUT_MS);
  await restoreBrowserEntraSessionStorage(page);
  await installStreamCapture(page);
  await page.goto("/agent-activity?locale=ko", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".shell")).toBeVisible();

  const incidentButton = page.getByRole("button", { name: /활성 인시던트 대화 \d+건 열기/ });
  await expect(incidentButton).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1_000);
  const initialCaptureCount = await page.evaluate(() => (
    (window as Window & { __fdaiSemanticPresentationStreams?: Promise<string>[] })
      .__fdaiSemanticPresentationStreams?.length ?? 0
  ));
  if (initialCaptureCount === 0) await incidentButton.click();

  await waitForCaptureCount(page, 1);
  await expect(page.getByText("다음 안전 단계", { exact: true }).last()).toBeVisible({
    timeout: 120_000,
  });
  const firstBodies = await capturedBodies(page);
  const first = parseFrames(firstBodies.at(-1)!);
  const firstContract = incidentContract(first);

  expect(firstContract.judgment.passed, firstContract.judgment.failure_reason).toBe(true);
  expect(firstContract.phases).toEqual([
    "accepted",
    "planning",
    "evidence",
    "verification",
    "presentation",
  ]);
  expect(firstContract.answer).toContain("검증된 인시던트 근거");
  expect(firstContract.answer).not.toContain("```json");
  expect(firstContract.blocks.map((block) => block.slot_id)).toEqual([
    "overview",
    "limitations",
    "findings",
  ]);
  expect(firstContract.blocks.map((block) => block.title)).toEqual([
    "검증된 인시던트 근거",
    "제한 사항",
    "다음 안전 단계",
  ]);
  expect(firstContract.nextStep).toEqual({
    operation: "collect_evidence",
    authority: "read_only",
    execution_authority: false,
  });
  expect(firstContract.context.kind).toBe("incident");
  expect(firstContract.context.incident_id).toBe(firstContract.profile.incident_id);
  expect(firstContract.context.correlation_id).toBe(firstContract.profile.correlation_id);
  expect(firstContract.verification.status).toBe("verified");
  expect(firstContract.receipt.execution_authority).toBe(false);

  const firstHeading = page.getByRole("heading", { name: "검증된 인시던트 근거" }).last();
  const firstArticle = firstHeading.locator("xpath=ancestor::article[1]");
  expect(await firstArticle.innerText()).not.toContain("semantic_query_outputs");
  await firstArticle.getByRole("button", { name: "다시 생성" }).click();

  await waitForCaptureCount(page, firstBodies.length + 1);
  await expect(page.getByText("다음 안전 단계", { exact: true }).last()).toBeVisible({
    timeout: 120_000,
  });
  const regeneratedBodies = await capturedBodies(page);
  const regenerated = parseFrames(regeneratedBodies.at(-1)!);
  if (regenerated.done.status !== "answered") {
    throw new Error(
      `regenerated request diagnostics: ${JSON.stringify(await requestDiagnostics(page))}`,
    );
  }
  const regeneratedContract = incidentContract(regenerated);
  const requestEvidence = await requestDiagnostics(page);
  const firstRequest = requestEvidence.at(-2);
  const regeneratedRequest = requestEvidence.at(-1);

  expect(regeneratedRequest?.request_id_digest).toBe(firstRequest?.request_id_digest);

  expect(regeneratedContract.judgment.passed, regeneratedContract.judgment.failure_reason).toBe(true);
  expect(regeneratedContract.answer).not.toContain("```json");
  expect(regeneratedContract.phases).toEqual(firstContract.phases);
  expect(regeneratedContract.context).toEqual(firstContract.context);
  expect(regeneratedContract.nextStep).toEqual(firstContract.nextStep);
  expect(regeneratedContract.blocks.map((block) => block.slot_id)).toEqual(
    firstContract.blocks.map((block) => block.slot_id),
  );

  const runConfiguration: AssuranceRunConfiguration = {
    schema_version: "1.1.0",
    seed: 0x0fda1,
    batch_size: 1,
    request_interval_ms: 0,
    timeout_ms: TEST_TIMEOUT_MS,
    authentication: "browser_entra",
    transport_retry_policy: {
      max_attempts: 1,
      retry_delay_ms: 0,
      retryable_sources: [],
    },
    question_ids: ["ko-incident-semantic-presentation-regeneration"],
  };
  const provenance = buildAssuranceRunProvenance(
    process.env.FDAI_E2E_SOURCE_REVISION,
    process.env.FDAI_E2E_WORKSPACE_PATCH_SHA256,
    runConfiguration,
  );
  const artifact = {
    schema_version: "1.0.0",
    evidence_type: "authenticated_semantic_answer_presentation",
    receipt_source: "live_browser_entra",
    run_scope: "focused_incident_presentation",
    ...provenance,
    run_configuration: runConfiguration,
    captured_at: new Date().toISOString(),
    authentication: "browser_entra",
    authentication_attestation: {
      storage_state_restored: true,
      protected_request_count: 2,
    },
    locale: "ko",
    passed: true,
    first_turn: {
      disposition: firstContract.receipt.disposition,
      reason_code: firstContract.receipt.reason_code,
      semantic_route: firstContract.receipt.semantic_route,
      checks_completed: firstContract.verification.checks_completed,
      checks_total: firstContract.verification.checks_total,
      evidence_ref_count: array(firstContract.verification.evidence_refs, "evidence refs").length,
      progress_phases: firstContract.phases,
      presentation_slots: firstContract.blocks.map((block) => block.slot_id),
      primary_json_absent: !firstContract.answer.includes("```json"),
      technical_output_digest: digest(firstContract.technical),
      incident_binding_digest: digest(firstContract.context),
      next_step: firstContract.nextStep.operation,
      authority: firstContract.nextStep.authority,
      execution_authority: firstContract.nextStep.execution_authority,
      exact_output_collapsed: true,
    },
    regenerated_turn: {
      disposition: regeneratedContract.receipt.disposition,
      reason_code: regeneratedContract.receipt.reason_code,
      semantic_route: regeneratedContract.receipt.semantic_route,
      checks_completed: regeneratedContract.verification.checks_completed,
      checks_total: regeneratedContract.verification.checks_total,
      evidence_ref_count: array(
        regeneratedContract.verification.evidence_refs,
        "regenerated evidence refs",
      ).length,
      progress_phases: regeneratedContract.phases,
      presentation_slots: regeneratedContract.blocks.map((block) => block.slot_id),
      primary_json_absent: !regeneratedContract.answer.includes("```json"),
      technical_output_digest: digest(regeneratedContract.technical),
      incident_binding_digest: digest(regeneratedContract.context),
      binding_preserved: digest(regeneratedContract.context) === digest(firstContract.context),
      request_identity_replayed:
        regeneratedRequest?.request_id_digest === firstRequest?.request_id_digest,
      next_step: regeneratedContract.nextStep.operation,
      authority: regeneratedContract.nextStep.authority,
      execution_authority: regeneratedContract.nextStep.execution_authority,
      exact_output_collapsed: true,
    },
  };
  const artifactPath = testInfo.outputPath("semantic-answer-presentation.json");
  await writeFile(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`, "utf8");
  await testInfo.attach("semantic-answer-presentation", {
    path: artifactPath,
    contentType: "application/json",
  });
});
