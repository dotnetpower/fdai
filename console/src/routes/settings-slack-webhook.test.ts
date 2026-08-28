import { describe, expect, test, vi } from "vitest";
import {
  decodeSlackWebhookTestResult,
  newSlackWebhookTestRequestId,
} from "./settings-slack-webhook.model";

describe("Slack webhook diagnostic model", () => {
  test("decodes only an accepted Slack response", () => {
    expect(decodeSlackWebhookTestResult({
      request_id: "slack-webhook-test-1",
      accepted: true,
      provider_status: 200,
      tested_at: "2026-08-27T13:00:00+00:00",
    })).toEqual({
      requestId: "slack-webhook-test-1",
      accepted: true,
      providerStatus: 200,
      testedAt: "2026-08-27T13:00:00+00:00",
    });
  });

  test.each([
    null,
    { accepted: false, provider_status: 200, request_id: "r", tested_at: "2026-08-27T13:00:00Z" },
    { accepted: true, provider_status: 202, request_id: "r", tested_at: "2026-08-27T13:00:00Z" },
    { accepted: true, provider_status: 200, request_id: "r", tested_at: "not-a-time" },
  ])("rejects malformed result %#", (value) => {
    expect(() => decodeSlackWebhookTestResult(value)).toThrow();
  });

  test("generates a fresh namespaced request id", () => {
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      "00000000-0000-0000-0000-000000000000",
    );
    expect(newSlackWebhookTestRequestId()).toBe(
      "slack-webhook-test-00000000-0000-0000-0000-000000000000",
    );
  });
});
