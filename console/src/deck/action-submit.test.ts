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

  test("sends a stable idempotency key so retries dedup server-side", async () => {
    const spy = vi.fn(async (_url: string, _init: RequestInit) =>
      fakeResponse(200, { submitted: true, action_type: "ops.restart-service" }),
    );
    vi.stubGlobal("fetch", spy);
    await submitAction("restart svc-1", "s1");
    const body = JSON.parse(spy.mock.calls[0]![1]!.body as string);
    expect(typeof body.idempotency_key).toBe("string");
    expect(body.idempotency_key.length).toBeGreaterThan(0);
    expect(body.prompt).toBe("restart svc-1");
  });

  test("preserves incident confirmation and lifecycle fields", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        fakeResponse(200, {
          submitted: false,
          reason: "incident_confirmation_required",
          action_type: "incident.create",
          correlation_id: "conv-incident",
          message: "SEV2 Incident를 생성할게. 확인하면 생성해.",
          incident_id: "incident-1",
          incident_state: "open",
          created: false,
        }),
      ),
    );

    const result = await submitAction("SEV2 장애 케이스 열어줘", "s1");

    expect(result.actionType).toBe("incident.create");
    expect(result.message).toMatch(/확인하면 생성/);
    expect(result.incidentId).toBe("incident-1");
    expect(result.incidentState).toBe("open");
    expect(result.created).toBe(false);
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

  test("deny-override refusal has its own message, not the generic fallback", () => {
    // Regression (critique #20): a 403 deny-override used to fall through to the
    // "endpoint did not respond" default, misleading the operator.
    const msg = renderActionResult({
      submitted: false,
      status: 403,
      reason: "deny_override_forbidden",
    });
    expect(msg).toMatch(/already denied/);
    expect(msg).not.toMatch(/did not respond/);
  });

  test("invalid principal has its own message", () => {
    const msg = renderActionResult({
      submitted: false,
      status: 200,
      reason: "invalid_principal",
    });
    expect(msg).toMatch(/couldn't identify your account/);
    expect(msg).not.toMatch(/did not respond/);
  });

  test("incident prepare and create use the server communication", () => {
    const prepared = renderActionResult({
      submitted: false,
      status: 200,
      actionType: "incident.create",
      reason: "incident_confirmation_required",
      message: "SEV2 Incident를 생성할게. 확인하면 생성해.",
    });
    const created = renderActionResult({
      submitted: true,
      status: 200,
      actionType: "incident.create",
      correlationId: "incident-1",
      message: "Incident incident-1 created in open state.",
    });

    expect(prepared).toMatch(/확인하면 생성/);
    expect(prepared).not.toMatch(/did not respond/);
    expect(created).toMatch(/created in open state/);
    expect(created).not.toMatch(/Forseti/);
  });
});
