import { describe, expect, it } from "vitest";
import { startChat } from "./workflow-builder.chat";
import { loadWorkflowChatSession, saveWorkflowChatSession } from "./workflow-builder.session";

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() { return values.size; },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => { values.delete(key); },
    setItem: (key, value) => { values.set(key, value); },
  };
}

describe("workflow builder session store", () => {
  it("round-trips a bounded chat session", () => {
    const target = storage();
    const turn = startChat([{
      name: "ops.restart-service",
      operation: "apply",
      category: "ops",
      rollback_contract: "pr_revert",
      irreversible: false,
      default_mode: "shadow",
      execution_path: "pr_native",
      env_scope: "any",
      hil_tiers: [],
      description: "Restart a service",
    }]);
    saveWorkflowChatSession(target, {
      slots: turn.slots,
      messages: [{ id: 1, role: "bot", text: turn.text, options: turn.options }],
    });

    expect(loadWorkflowChatSession(target)?.slots.stage).toBe("welcome");
  });

  it("round-trips a ready session with an edited preview", () => {
    const target = storage();
    const opening = startChat([{
      name: "ops.restart-service",
      operation: "apply",
      category: "ops",
      rollback_contract: "pr_revert",
      irreversible: false,
      default_mode: "shadow",
      execution_path: "pr_native",
      env_scope: "any",
      hil_tiers: [],
      description: "Restart a service",
    }]);
    const form = {
      ...opening.slots.form,
      name: "recovered-workflow",
      description: "Recovered workflow",
      steps: [{
        ...opening.slots.form.steps[0]!,
        id: "restart_service",
        action_type_ref: "ops.restart-service",
        params: { retries: 3, urgent: true },
      }],
    };
    const slots = {
      ...opening.slots,
      stage: "ready" as const,
      form,
      triggerConfirmed: true,
      actionsConfirmed: true,
      extraOffered: true,
      nameConfirmed: true,
      planConfirmed: true,
      safetyConfirmed: true,
    };
    saveWorkflowChatSession(target, {
      slots,
      messages: [{
        id: 11,
        role: "bot",
        text: "Ready",
        options: [{ label: "Start over", value: "restart" }],
        preview: form,
      }],
    });

    const recovered = loadWorkflowChatSession(target);
    expect(recovered?.slots.stage).toBe("ready");
    expect(recovered?.messages[0]?.preview?.steps[0]?.params).toEqual({
      retries: 3,
      urgent: true,
    });
  });

  it("drops malformed and oversized state", () => {
    const malformed = storage();
    malformed.setItem("fdai.workflow-builder.chat.v1", JSON.stringify({ slots: { stage: "owned" } }));
    expect(loadWorkflowChatSession(malformed)).toBeNull();

    const oversized = storage();
    oversized.setItem("fdai.workflow-builder.chat.v1", "x".repeat(256 * 1024 + 1));
    expect(loadWorkflowChatSession(oversized)).toBeNull();
  });

  it("restores WAIT and APPROVAL fields losslessly", () => {
    const target = storage();
    const opening = startChat([]);
    const controlSteps = [
      {
        ...opening.slots.form.steps[0]!,
        id: "wait_for_evidence",
        kind: "wait" as const,
        wait_for: "evidence.updated",
        timeout_seconds: "3600",
      },
      {
        ...opening.slots.form.steps[0]!,
        key: 1,
        id: "human_approval",
        kind: "approval" as const,
        approval_role: "owner" as const,
        quorum: "2",
        timeout_seconds: "1800",
        no_self_approval: true,
      },
    ];
    saveWorkflowChatSession(target, {
      slots: { ...opening.slots, form: { ...opening.slots.form, steps: controlSteps } },
      messages: [{ id: 1, role: "bot", text: "Control steps" }],
    });

    expect(loadWorkflowChatSession(target)?.slots.form.steps).toEqual(controlSteps);
  });
});
