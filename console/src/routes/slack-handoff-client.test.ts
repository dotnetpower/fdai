import { afterEach, expect, test, vi } from "vitest";
import type { OperatorApiClient } from "../api";
import { handoffRequest } from "./slack-handoff-client";

const client = {
  operatorApiBaseUrl: "http://localhost:8010",
  authorizationHeader: async () => "Bearer synthetic",
} as OperatorApiClient;

afterEach(() => vi.unstubAllGlobals());

test("sends only justification and bearer, never browser actor or authority", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
    approval_id: "approval-1",
    idempotency_key: "idem-1",
    correlation_id: "correlation-1",
    decision: "approve",
    already_recorded: false,
    receipt_ref: "receipt-1",
    decided_at: "2026-09-26T12:00:00Z",
    delivered: false,
  }), { status: 202 }));
  vi.stubGlobal("fetch", fetchMock);
  const result = await handoffRequest(client, "n".repeat(43), "independent review");
  expect(result).toMatchObject({ approval_id: "approval-1", delivered: false });
  expect(fetchMock).toHaveBeenCalledWith(
    new URL(`http://localhost:8010/hil/slack/handoff/${"n".repeat(43)}`),
    expect.objectContaining({
      method: "POST",
      credentials: "omit",
      cache: "no-store",
      body: '{"justification":"independent review"}',
      headers: expect.objectContaining({ authorization: "Bearer synthetic" }),
    }),
  );
});

test("malformed preview is unavailable rather than a selectable decision", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    approval_id: "approval-1", decision: "execute",
  }))));
  await expect(handoffRequest(client, "n".repeat(43))).rejects.toThrow("malformed");
});
