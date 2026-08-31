import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { INITIAL_FORM } from "./workflow-builder.model";
import {
  addDraftListItem,
  addDraftStep,
  coerceDraftParam,
  moveDraftStep,
  removeDraftListItem,
  removeDraftStep,
  setDraftParam,
  setDraftStepAction,
  setDraftStepApprovalRole,
  setDraftStepKind,
  setDraftStepNoSelfApproval,
  setDraftListItem,
  updateDraftStepField,
} from "./workflow-builder.editor";

describe("workflow draft editor", () => {
  it("adds, reorders, and removes steps without mutating the source form", () => {
    const original = structuredClone(INITIAL_FORM);
    const first = setDraftStepAction(original, 0, "ops.restart-service");
    const added = setDraftStepAction(addDraftStep(first), 1, "ops.publish-change-summary");
    const moved = moveDraftStep(added, 1, -1);
    const removed = removeDraftStep(moved, 0);

    expect(original).toEqual(INITIAL_FORM);
    expect(moved.steps.map((step) => step.action_type_ref)).toEqual([
      "ops.publish-change-summary",
      "ops.restart-service",
    ]);
    expect(removed.steps.map((step) => step.id)).toEqual(["publish_change_summary"]);
  });

  it("preserves custom ids while suggesting ids for untouched steps", () => {
    const suggested = setDraftStepAction(INITIAL_FORM, 0, "ops.restart-service");
    suggested.steps[0]!.id = "custom_restart";
    const changed = setDraftStepAction(suggested, 0, "ops.scale-out");

    expect(changed.steps[0]!.id).toBe("custom_restart");
    expect(suggested.steps[0]!.action_type_ref).toBe("ops.restart-service");
  });

  it("edits primitive parameters without converting every value to text", () => {
    const withNumber = setDraftParam(
      INITIAL_FORM,
      0,
      "",
      "retries",
      coerceDraftParam("3", "number"),
    );
    const withBoolean = setDraftParam(
      withNumber,
      0,
      "",
      "urgent",
      coerceDraftParam("true", "boolean"),
    );

    expect(withBoolean.steps[0]!.params).toEqual({ retries: 3, urgent: true });
    expect(INITIAL_FORM.steps[0]!.params).toEqual({});
  });

  it("authors WAIT and APPROVAL requirements without losing hidden kind fields", () => {
    const wait = updateDraftStepField(
      updateDraftStepField(
        updateDraftStepField(setDraftStepKind(INITIAL_FORM, 0, "wait"), 0, "id", "wait_for_evidence"),
        0,
        "wait_for",
        "evidence.updated",
      ),
      0,
      "timeout_seconds",
      "3600",
    );
    const approvalKind = setDraftStepKind(addDraftStep(wait), 1, "approval");
    const withRole = setDraftStepApprovalRole(approvalKind, 1, "approver");
    const withQuorum = updateDraftStepField(withRole, 1, "quorum", "2");
    const approval = setDraftStepNoSelfApproval(
      updateDraftStepField(withQuorum, 1, "timeout_seconds", "1800"),
      1,
      true,
    );

    expect(approval.steps).toMatchObject([
      {
        kind: "wait",
        id: "wait_for_evidence",
        wait_for: "evidence.updated",
        timeout_seconds: "3600",
      },
      {
        kind: "approval",
        approval_role: "approver",
        quorum: "2",
        timeout_seconds: "1800",
        no_self_approval: true,
      },
    ]);
    expect(moveDraftStep(approval, 1, -1).steps.map((step) => step.kind)).toEqual([
      "approval",
      "wait",
    ]);
  });

  it("keeps required control fields and validation feedback accessible", () => {
    const editorSource = readFileSync(
      new URL("./workflow-builder.draft-editor.tsx", import.meta.url),
      "utf8",
    );
    const previewSource = readFileSync(
      new URL("./workflow-builder.chatpanel.tsx", import.meta.url),
      "utf8",
    );

    expect(editorSource).toContain('type="number" min="1" step="1" required');
    expect(editorSource).toContain('type="checkbox"');
    expect(editorSource).toContain('workflow.editor.noSelfApprovalHint');
    expect(editorSource).toContain("<fieldset");
    expect(editorSource).toContain('workflow.editor.joinHint');
    expect(editorSource).toContain('list={`workflow-gate-refs-${step.key}`}');
    expect(previewSource).toContain('class="wf-test-fail" role="alert"');
  });

  it("edits decision outcomes and parallel branches without changing other steps", () => {
    const decision = setDraftStepKind(INITIAL_FORM, 0, "decision");
    const namedDecision = setDraftListItem(decision, 0, "outcomes", 0, "approved");
    const withDecision = setDraftListItem(namedDecision, 0, "outcomes", 1, "held");
    const parallel = setDraftStepKind(addDraftStep(withDecision), 1, "parallel");
    const withFirstBranch = setDraftListItem(parallel, 1, "branches", 0, "security");
    const withSecondBranch = setDraftListItem(
      withFirstBranch,
      1,
      "branches",
      1,
      "reliability",
    );
    const withExtraBranch = addDraftListItem(withSecondBranch, 1, "branches");
    const completed = setDraftListItem(withExtraBranch, 1, "branches", 2, "cost");
    const removed = removeDraftListItem(completed, 1, "branches", 1);

    expect(removed.steps[0]?.outcomes).toEqual(["approved", "held"]);
    expect(removed.steps[1]?.branches).toEqual(["security", "cost"]);
  });
});
