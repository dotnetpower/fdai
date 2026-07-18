import { afterEach, describe, expect, it, vi } from "vitest";
import { createWorkflowDefinition } from "./validate";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("workflow definition creation", () => {
  it("sends explicit confirmation and decodes a private draft identity", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      valid: true,
      definition: {
        definition_id: "definition-1",
        workflow_name: "cost-review",
        lifecycle: "draft",
      },
    }), { status: 201, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(createWorkflowDefinition({ name: "cost-review" })).resolves.toEqual({
      definitionId: "definition-1",
      workflowName: "cost-review",
      lifecycle: "draft",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      workflow: { name: "cost-review" },
      confirmed: true,
    });
  });

  it("fails closed on a malformed success response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      valid: true,
      definition: { workflow_name: "cost-review", lifecycle: "draft" },
    }), { status: 201, headers: { "content-type": "application/json" } })));

    await expect(createWorkflowDefinition({ name: "cost-review" })).rejects.toThrow(
      "invalid response",
    );
  });

  it("preserves structured catalog issues from a rejected save", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      valid: false,
      issues: [{ key: "draft:steps.run.action_type_ref", message: "unknown ActionType" }],
    }), { status: 422, headers: { "content-type": "application/json" } })));

    await expect(createWorkflowDefinition({ name: "cost-review" })).rejects.toThrow(
      "unknown ActionType",
    );
  });
});
