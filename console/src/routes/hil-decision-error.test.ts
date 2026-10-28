import { afterEach, describe, expect, test, vi } from "vitest";
import { decideHilApproval } from "../api-hil-decision";
import { GovernedCommandError } from "../governed-command";
import { decisionFailureMessage } from "./hil-decision-error";

afterEach(() => vi.unstubAllGlobals());

describe("approval decision failures", () => {
  test.each([
    [410, "expired"],
    [409, "already decided"],
    [500, "could not record"],
    [503, "could not record"],
  ])("explains HTTP %i without leaking the transport status", (status, phrase) => {
    const message = decisionFailureMessage(new GovernedCommandError("HTTP raw", status));

    expect(message).toContain(phrase);
    expect(message).not.toContain("HTTP");
  });

  test("keeps the server's own message for other refusals", () => {
    expect(decisionFailureMessage(new GovernedCommandError("not an approver", 403))).toBe(
      "not an approver",
    );
    expect(decisionFailureMessage(new Error("offline"))).toBe("offline");
  });
});

describe("approval decision request", () => {
  test("sends a decision with no reason as an empty reason", async () => {
    const calls: { body: unknown }[] = [];
    vi.stubGlobal("fetch", async (_url: unknown, init: { body: string }) => {
      calls.push({ body: JSON.parse(init.body) });
      return new Response(
        JSON.stringify({
          approval_id: "a1",
          idempotency_key: "k1",
          correlation_id: "c1",
          decision: "reject",
          already_recorded: false,
          receipt_ref: "r1",
          decided_at: "2026-01-01T00:00:00Z",
          delivered: true,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });

    const receipt = await decideHilApproval(
      async () => null,
      "http://localhost:8010",
      "a1",
      "reject",
      "",
      "k1",
    );

    expect(receipt.decision).toBe("reject");
    expect(calls[0]?.body).toEqual({ decision: "reject", justification: "" });
  });
});
