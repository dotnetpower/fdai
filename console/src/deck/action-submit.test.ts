import { afterEach, describe, expect, test, vi } from "vitest";
import { renderActionResult, submitAction, type ActionSubmitResult } from "./backend";

/** A minimal fake Response with just the fields submitAction reads. */
function fakeResponse(status: number, body: unknown): Response {
  return {
    status,
    json: async () => body,
  } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("submitAction", () => {
  test("submitted proposal surfaces action_type + correlation_id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        fakeResponse(200, {
          submitted: true,
          action_type: "ops.restart-service",
          correlation_id: "conv-abc",
        }),
      ),
    );
    const r = await submitAction("restart svc-1", "s1");
    expect(r.submitted).toBe(true);
    expect(r.status).toBe(200);
    expect(r.actionType).toBe("ops.restart-service");
    expect(r.correlationId).toBe("conv-abc");
  });

  test("403 capability refusal is surfaced, not thrown", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        fakeResponse(403, {
          submitted: false,
          reason: "rbac_capability",
          required_capability: "author-draft-pr",
        }),
      ),
    );
    const r = await submitAction("restart svc-1", null);
    expect(r.submitted).toBe(false);
    expect(r.status).toBe(403);
    expect(r.reason).toBe("rbac_capability");
    expect(r.requiredCapability).toBe("author-draft-pr");
  });

  test("unmapped command is a non-submitted 200", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        fakeResponse(200, { submitted: false, reason: "unmapped_action_intent" }),
      ),
    );
    const r = await submitAction("provision a cluster", null);
    expect(r.submitted).toBe(false);
    expect(r.reason).toBe("unmapped_action_intent");
  });

  test("404 means the action route is not wired", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => fakeResponse(404, {})));
    const r = await submitAction("restart svc-1", null);
    expect(r.submitted).toBe(false);
    expect(r.reason).toBe("not_wired");
  });

  test("a transport error resolves to a graceful error result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );
    const r = await submitAction("restart svc-1", null);
    expect(r.submitted).toBe(false);
    expect(r.status).toBe(0);
    expect(r.reason).toBe("error");
  });
});

describe("renderActionResult", () => {
  test("submitted message names the action and points to Trace", () => {
    const r: ActionSubmitResult = {
      submitted: true,
      status: 200,
      actionType: "ops.restart-service",
      correlationId: "conv-abc",
    };
    const msg = renderActionResult(r);
    expect(msg).toMatch(/ops.restart-service/);
    expect(msg).toMatch(/conv-abc/);
    expect(msg).toMatch(/Forseti/);
  });

  test("capability refusal explains the missing role", () => {
    const msg = renderActionResult({
      submitted: false,
      status: 403,
      reason: "rbac_capability",
      requiredCapability: "author-draft-pr",
    });
    expect(msg).toMatch(/Contributor/);
    expect(msg).toMatch(/read-only/);
  });

  test("unmapped and not_wired have distinct messages", () => {
    expect(renderActionResult({ submitted: false, status: 200, reason: "unmapped_action_intent" })).toMatch(
      /maps to no known action/,
    );
    expect(renderActionResult({ submitted: false, status: 404, reason: "not_wired" })).toMatch(
      /not enabled/,
    );
  });
});
