import { createHash } from "node:crypto";
import { chmod, readFile, stat, writeFile } from "node:fs/promises";
import { chromium } from "@playwright/test";

const MAX_PRIVATE_BYTES = 2 * 1024 * 1024;
const SHA256 = /^(?:sha256:)?[a-f0-9]{64}$/;

function argument(name, fallback = undefined) {
  const index = process.argv.indexOf(name);
  if (index < 0) return fallback;
  const value = process.argv[index + 1];
  if (!value || value.startsWith("--")) throw new Error(`missing ${name}`);
  return value;
}

async function privateJson(path) {
  const metadata = await stat(path);
  if (!metadata.isFile() || (metadata.mode & 0o077) !== 0 || metadata.size > MAX_PRIVATE_BYTES) {
    throw new Error("private input is unavailable");
  }
  return JSON.parse(await readFile(path, "utf8"));
}

export function terminalPayload(stream) {
  let terminal = null;
  let event = "message";
  let data = [];
  const flush = () => {
    if (data.length === 0) return;
    if (event === "done") {
      if (terminal !== null) throw new Error("duplicate terminal event");
      terminal = JSON.parse(data.join("\n"));
    } else if (terminal !== null) {
      throw new Error("frame after terminal event");
    }
    event = "message";
    data = [];
  };
  for (const line of stream.replaceAll("\r\n", "\n").split("\n")) {
    if (line === "") {
      flush();
    } else if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data.push(line.slice(5).trimStart());
    }
  }
  flush();
  if (terminal === null) throw new Error("terminal event is unavailable");
  return terminal;
}

export function validateChatResponse(status, contentType) {
  if (status !== 200) throw new Error(`chat_http_${status}`);
  if (typeof contentType !== "string" ||
      !contentType.toLowerCase().startsWith("text/event-stream")) {
    throw new Error("chat_content_type_invalid");
  }
}

export function profileEvidence(terminal) {
  const profiles = terminal.pantheon_prompt_profiles;
  const participants = Array.isArray(profiles?.answer_participants)
    ? profiles.answer_participants
    : [];
  const evaluators = Array.isArray(profiles?.evaluator_profiles)
    ? profiles.evaluator_profiles
    : [];
  const participantValid = participants.every((item) =>
    typeof item?.agent === "string" && item.agent.length > 0 &&
    typeof item?.prompt_version === "string" && item.prompt_version.length > 0 &&
    typeof item?.situation === "string" && item.situation.length > 0 &&
    typeof item?.system_text_sha256 === "string" && SHA256.test(item.system_text_sha256)
  );
  const evaluatorValid = evaluators.every((item) =>
    typeof item?.profile_id === "string" && item.profile_id.length > 0 &&
    Number.isInteger(item?.profile_version) && item.profile_version > 0 &&
    typeof item?.profile_digest === "string" && SHA256.test(item.profile_digest) &&
    typeof item?.system_text_sha256 === "string" && SHA256.test(item.system_text_sha256) &&
    Number.isInteger(item?.system_token_budget) && item.system_token_budget >= 0 &&
    Number.isInteger(item?.request_token_budget) && item.request_token_budget >= 0 &&
    Number.isInteger(item?.reserved_output_tokens) && item.reserved_output_tokens >= 0
  );
  const availableEvaluators = Array.isArray(terminal.pantheon_evaluator_models)
    ? terminal.pantheon_evaluator_models.filter((item) => item?.output_available === true).length
    : 0;
  const expected = [
    ...participants.map((_item, index) => `answer-participant-${index + 1}`),
    ...Array.from({ length: availableEvaluators }, (_item, index) => `evaluator-profile-${index + 1}`),
  ];
  const observed = [
    ...(participantValid ? participants.map((_item, index) => `answer-participant-${index + 1}`) : []),
    ...(evaluatorValid ? evaluators.map((_item, index) => `evaluator-profile-${index + 1}`) : []),
  ];
  return {
    expected,
    observed,
    valid: participants.length > 0 && participantValid && evaluatorValid &&
      evaluators.length === availableEvaluators,
  };
}

function sensitiveTerminal(terminal) {
  const violations = terminal.pantheon_diagnostic?.hard_zero_violations;
  return Array.isArray(violations) && violations.some((value) =>
    value === "sensitive_output" || value === "hidden_scope_leak"
  );
}

async function run() {
  const corpusPath = argument("--corpus");
  const runStatePath = argument("--run-state");
  const outputPath = argument("--output");
  const origin = argument("--origin", "http://localhost:5273");
  if (!corpusPath || !runStatePath || !outputPath) throw new Error("required arguments are missing");
  const corpus = await privateJson(corpusPath);
  const runState = await privateJson(runStatePath);
  if (!Array.isArray(corpus.cases) || corpus.cases.length !== 1) {
    throw new Error("browser worker requires one private case");
  }
  const campaignCase = corpus.cases[0];
  if (campaignCase.case_id !== runState.case_id || typeof campaignCase.question !== "string") {
    throw new Error("private case does not match the armed run");
  }
  if (runState.state !== "browser_armed" || runState.measurement_reserved !== true) {
    throw new Error("browser run is not armed");
  }

  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext();
    await context.addInitScript(() => {
      localStorage.setItem("fdai:console:show-model-trace", "true");
    });
    const page = await context.newPage();
    let requestCount = 0;
    let requestSha256 = null;
    let responsePromiseResolve;
    let responsePromiseReject;
    const responsePromise = new Promise((resolve, reject) => {
      responsePromiseResolve = resolve;
      responsePromiseReject = reject;
    });
    const sessionId = `pantheon-assurance:${runState.run_id}`;
    const purpose = `conversation-assurance:${campaignCase.case_id}`;
    await page.route("**/chat/stream", async (route) => {
      requestCount += 1;
      if (requestCount !== 1) {
        await route.abort("blockedbyclient");
        return;
      }
      const body = route.request().postDataJSON();
      if (body.prompt !== campaignCase.question) throw new Error("browser prompt drift");
      const modified = JSON.stringify({
        ...body,
        session_id: sessionId,
        purpose,
        include_model_trace: true,
      });
      requestSha256 = createHash("sha256").update(modified).digest("hex");
      await route.continue({
        postData: modified,
        headers: { ...route.request().headers(), "content-type": "application/json" },
      });
    });
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (url.pathname !== "/chat/stream" || response.request().method() !== "POST") return;
      try {
        validateChatResponse(response.status(), response.headers()["content-type"]);
      } catch (error) {
        responsePromiseReject(error);
        return;
      }
      response.text().then(responsePromiseResolve, responsePromiseReject);
    });
    await page.goto(origin, { waitUntil: "domcontentloaded", timeout: 30_000 });
    const input = page.getByPlaceholder(/Ask anything/i);
    await input.waitFor({ state: "visible", timeout: 30_000 });
    await page.evaluate(() => {
      const state = {
        preparingSeen: false,
        earlyAnswer: false,
        overlap: false,
      };
      window.__fdaiConversationAssurance = state;
      const observe = () => {
        const preparing = document.querySelector(".deck-rt") !== null;
        const answer = document.querySelector(".deck-gr .cs-deck-answer") !== null;
        if (preparing) state.preparingSeen = true;
        if (preparing && answer) {
          state.earlyAnswer = true;
          state.overlap = true;
        }
      };
      new MutationObserver(observe).observe(document.body, { childList: true, subtree: true });
      observe();
    });
    await input.fill(campaignCase.question);
    await page.locator(".cs-deck-composer-send").click();
    const stream = await Promise.race([
      responsePromise,
      new Promise((_resolve, reject) => setTimeout(() => reject(new Error("chat deadline")), 120_000)),
    ]);
    const terminal = terminalPayload(stream);
    if (!SHA256.test(requestSha256 ?? "")) throw new Error("request_digest_unavailable");
    await page.locator(".cs-run-record").last().waitFor({ state: "visible", timeout: 15_000 }).catch(() => {});
    const runRecord = page.locator(".cs-run-record").last();
    const runRecordPresent = await runRecord.count() === 1;
    if (runRecordPresent) {
      const summary = runRecord.locator(":scope > summary");
      if (await summary.getAttribute("aria-expanded") !== "true") await summary.click();
    }
    const phaseStates = {};
    if (runRecordPresent) {
      const phases = runRecord.locator(".deck-trajectory-phase-details > li[data-phase]");
      for (let index = 0; index < await phases.count(); index += 1) {
        const phase = phases.nth(index);
        const name = await phase.getAttribute("data-phase");
        const state = await phase.getAttribute("data-state");
        if (name && state) phaseStates[name] = state;
      }
    }
    const browserState = await page.evaluate(() => window.__fdaiConversationAssurance);
    const promptEvidence = profileEvidence(terminal);
    const promptProfiles = runRecord.locator(".deck-pantheon-prompt-profiles");
    const promptProfilesVisible = runRecordPresent && await promptProfiles.count() === 1 &&
      await promptProfiles.locator("li").count() === promptEvidence.expected.length;
    const assessmentCompleted = terminal.assessment_state === "completed";
    const diagnostic = terminal.pantheon_diagnostic;
    const evidence = {
      request_count: requestCount,
      endpoint_contract: "/chat/stream",
      run_id: runState.run_id,
      case_id: runState.case_id,
      question_fingerprint: runState.question_fingerprint,
      session_id: sessionId,
      purpose,
      request_sequence: 1,
      request_sha256: requestSha256,
      trace_receipt_digest: terminal.trace_receipt_id,
      run_record_present: runRecordPresent,
      phase_states: phaseStates,
      model_trace_enabled: true,
      omitted_model_calls: 0,
      expected_call_kinds: promptEvidence.expected,
      observed_call_kinds: promptEvidence.observed,
      prompt_manifests_match: promptEvidence.valid,
      prompt_profiles_visible: promptProfilesVisible,
      system_layer_order_valid: promptEvidence.valid,
      untrusted_data_separated: promptEvidence.valid,
      preparing_answer_seen: browserState?.preparingSeen === true,
      early_answer_exposed: browserState?.earlyAnswer === true,
      preparing_answer_overlapped_terminal: browserState?.overlap === true,
      terminal_transition_completed: await page.locator(".deck-rt").count() === 0,
      sensitive_output_detected: sensitiveTerminal(terminal),
      terminal: {
        terminal_state: terminal.status,
        answer_generation_state: typeof terminal.answer === "string" && terminal.answer.length > 0
          ? "completed"
          : "unavailable",
        assessment_state: terminal.assessment_state,
        assessment_reasons: terminal.assessment_reasons ?? [],
        score: assessmentCompleted && Number.isInteger(diagnostic?.score) ? diagnostic.score : null,
        verdict: assessmentCompleted && typeof diagnostic?.verdict === "string"
          ? diagnostic.verdict
          : null,
      },
    };
    if (!SHA256.test(evidence.trace_receipt_digest ?? "")) {
      throw new Error("browser evidence digest unavailable");
    }
    await writeFile(outputPath, `${JSON.stringify(evidence)}\n`, { encoding: "utf8", mode: 0o600, flag: "wx" });
    await chmod(outputPath, 0o600);
  } finally {
    await browser.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  run().catch(() => {
    process.exitCode = 1;
  });
}
