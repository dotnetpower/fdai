import assert from "node:assert/strict";
import { test } from "vitest";

import {
  contentDigest,
  modelCallCount,
  profileEvidence,
  terminalPayload,
  validateChatResponse,
} from "./conversation-assurance-browser.mjs";

const SHA = "a".repeat(64);

test("content digest is stable across object key order", () => {
  assert.equal(
    contentDigest({ b: 2, a: { d: 4, c: 3 } }),
    contentDigest({ a: { c: 3, d: 4 }, b: 2 }),
  );
});

test("model call count requires authoritative usage, complete budget, or trace", () => {
  assert.equal(modelCallCount({ model_usage: { model_calls: 4 } }), 4);
  assert.equal(modelCallCount({
    turn_budget: { complete: true, model_calls: { used: 3 } },
  }), 3);
  assert.equal(modelCallCount({
    model_trace: { calls: [{}, {}], omitted_calls: 1 },
  }), 3);
  assert.equal(modelCallCount({
    turn_budget: { complete: false, model_calls: { used: 3 } },
  }), null);
});

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
