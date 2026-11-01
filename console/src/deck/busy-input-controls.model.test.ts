import { describe, expect, it } from "vitest";
import {
  buildBusyCancelRequest,
  buildBusyInputControlViewModel,
  buildBusyModeChangeRequest,
  buildBusySubmitRequest,
  decodeBusySessionProjection,
} from "./busy-input-controls.model";

describe("busy-input-controls.model", () => {
  it("decodes authoritative projection and builds EN/KO accessible view models", () => {
    const projection = decodeBusySessionProjection({
      session_id: "sess-42",
      mode: "steer",
      revision: 3,
      active_turn_id: "turn-9",
      pending_count: 1,
      pending: [
        {
          input_id: "in-1",
          idempotency_key: "idem-1",
          sequence: 1,
          content: "focus on koreacentral",
          disposition: "steered",
          status: "pending",
        },
      ],
    });

    const enView = buildBusyInputControlViewModel(projection, "en");
    expect(enView.isTurnActive).toBe(true);
    expect(enView.canCancelTurn).toBe(true);
    expect(enView.submitLabel).toBe("Steer turn");
    expect(enView.ariaLiveStatus).toContain("Active turn in progress");

    const koView = buildBusyInputControlViewModel(projection, "ko");
    expect(koView.submitLabel).toBe("응답 조향 전송");
    expect(koView.cancelLabel).toBe("현재 응답 취소");
    expect(koView.pendingBadgeText).toBe("대기 중 1건");
  });

  it("builds submit, mode-change, and cancel request payloads and rejects blank input", () => {
    const submit = buildBusySubmitRequest({
      sessionId: "sess-42",
      inputId: "in-2",
      idempotencyKey: "idem-2",
      content: "  stop current check  ",
      kind: "emergency_stop",
    });
    expect(submit).toEqual({
      session_id: "sess-42",
      input_id: "in-2",
      idempotency_key: "idem-2",
      content: "stop current check",
      kind: "emergency_stop",
    });

    expect(() =>
      buildBusySubmitRequest({
        sessionId: "sess-42",
        inputId: "in-3",
        idempotencyKey: "idem-3",
        content: "   ",
      }),
    ).toThrow(/must not be empty/);

    expect(
      buildBusyModeChangeRequest({
        sessionId: "sess-42",
        mode: "interrupt",
        expectedRevision: 3,
      }),
    ).toEqual({
      session_id: "sess-42",
      mode: "interrupt",
      expected_revision: 3,
    });

    expect(
      buildBusyCancelRequest({
        sessionId: "sess-42",
        expectedRevision: 3,
      }),
    ).toEqual({
      session_id: "sess-42",
      expected_revision: 3,
    });
  });

  it("rejects turn_busy=true without active_turn_id and queued_count > 1000", () => {
    expect(() =>
      decodeBusySessionProjection({
        session_id: "sess-42",
        mode: "queue",
        revision: 1,
        turn_busy: true,
        active_turn_id: null,
        pending: [],
      }),
    ).toThrow(/turn_busy=true without active_turn_id/);

    expect(() =>
      decodeBusySessionProjection({
        session_id: "sess-42",
        mode: "queue",
        revision: 1,
        turn_busy: true,
        active_turn_id: "   ",
        pending: [],
      }),
    ).toThrow(/turn_busy=true without active_turn_id/);

    expect(() =>
      decodeBusySessionProjection({
        session_id: "sess-42",
        mode: "queue",
        revision: 1,
        active_turn_id: "turn-1",
        queued_count: 1001,
        pending: [],
      }),
    ).toThrow(/queued_count/);
  });
});
