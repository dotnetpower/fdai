import { afterEach, describe, expect, it, vi } from "vitest";
import { setWorkflowAuth } from "../workflow/validate";
import type { ProcessTransition } from "./processes.model";
import { requestProcessTransition } from "./processes.transitions";

const transition: ProcessTransition = {
  id: "resume",
  method: "POST",
  path: "/workflows/process-1/resume",
  expected_revision: 3,
  requires_confirmation: false,
  runtime_recheck: true,
};

afterEach(() => {
  vi.unstubAllGlobals();
  setWorkflowAuth(null);
});

describe("Process transition request client", () => {
  it("sends revision and stable idempotency headers without claiming success", async () => {
    const fetchMock = vi.fn(async (_input: string, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      expect(init?.body).toBeUndefined();
      expect(init?.headers).toMatchObject({
        "if-match": "3",
        "idempotency-key": "process:process-1:resume:revision:3",
      });
      return new Response(JSON.stringify({
        accepted: true,
        proposal_id: "proposal-1",
        operation: "workflow.resume-request",
        duplicate: false,
      }), { status: 202, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(requestProcessTransition("process-1", transition)).resolves.toEqual({
      proposalId: "proposal-1",
      operation: "workflow.resume-request",
      duplicate: false,
    });
  });

  it("surfaces stale and invalid-transition denial without optimistic fallback", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "Process revision is stale; refresh before retrying" }),
      { status: 409, headers: { "content-type": "application/json" } },
    )));

    await expect(requestProcessTransition("process-1", transition)).rejects.toThrow(
      "Process revision is stale",
    );
  });

  it("rejects malformed acceptance and non-POST transition descriptors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ accepted: true, operational_success: true }),
      { status: 202, headers: { "content-type": "application/json" } },
    )));
    await expect(requestProcessTransition("process-1", transition)).rejects.toThrow(
      "invalid acceptance receipt",
    );
    await expect(requestProcessTransition("process-1", {
      ...transition,
      path: "/workflows/other/resume",
    })).rejects.toThrow("does not match the selected Process");
  });

  it("rejects an acceptance receipt for a different operation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({
        accepted: true,
        proposal_id: "proposal-1",
        operation: "workflow.cancel-request",
        duplicate: false,
      }),
      { status: 202, headers: { "content-type": "application/json" } },
    )));

    await expect(requestProcessTransition("process-1", transition)).rejects.toThrow(
      "does not match the request",
    );
  });
});
