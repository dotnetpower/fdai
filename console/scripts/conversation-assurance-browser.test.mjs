import assert from "node:assert/strict";
import { test } from "vitest";

import {
  profileEvidence,
  terminalPayload,
  validateChatResponse,
} from "./conversation-assurance-browser.mjs";

const SHA = "a".repeat(64);

test("terminal parser accepts exactly one final done event", () => {
  const terminal = terminalPayload(
    `event: progress\ndata: {"status":"running"}\n\n` +
    `event: done\ndata: {"status":"answered","assessment_state":"completed"}\n\n`,
  );
  assert.equal(terminal.status, "answered");
  assert.throws(
    () => terminalPayload(
      `event: done\ndata: {"status":"answered"}\n\n` +
      `event: done\ndata: {"status":"answered"}\n\n`,
    ),
    /duplicate terminal/,
  );
});

test("prompt evidence requires every available evaluator profile", () => {
  const terminal = {
    pantheon_prompt_profiles: {
      answer_participants: [{
        agent: "Heimdall",
        prompt_version: "heimdall-v1",
        system_text_sha256: SHA,
        situation: "audience=operator;phase=direct;tier=T1;locale=en",
      }],
      evaluator_profiles: [{
        profile_id: "conversation-assurance-reviewer",
        profile_version: 1,
        profile_digest: `sha256:${SHA}`,
        system_text_sha256: SHA,
        system_token_budget: 100,
        request_token_budget: 200,
        reserved_output_tokens: 50,
      }],
    },
    pantheon_evaluator_models: [{ output_available: true }],
  };

  const complete = profileEvidence(terminal);
  assert.equal(complete.valid, true);
  assert.deepEqual(complete.expected, ["answer-participant-1", "evaluator-profile-1"]);
  assert.equal(profileEvidence({
    ...terminal,
    pantheon_prompt_profiles: {
      ...terminal.pantheon_prompt_profiles,
      evaluator_profiles: [],
    },
  }).valid, false);
});

test("chat response contract rejects errors and non-SSE bodies", () => {
  assert.doesNotThrow(() => validateChatResponse(200, "text/event-stream; charset=utf-8"));
  assert.throws(() => validateChatResponse(503, "text/event-stream"), /chat_http_503/);
  assert.throws(() => validateChatResponse(200, "application/json"), /content_type/);
});
