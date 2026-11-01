/**
 * FDAI Console client controls and localized accessibility state model
 * for busy conversation input modes (queue, interrupt, steer, cancel).
 */

export type BusyInputMode = "queue" | "interrupt" | "steer";
export type BusyControlLocale = "en" | "ko";

export interface PendingBusyInputItem {
  readonly inputId: string;
  readonly idempotencyKey: string;
  readonly sequence: number;
  readonly content: string;
  readonly disposition: "queued" | "interrupting" | "steered" | "rejected";
  readonly status: "pending" | "consumed" | "expired" | "rejected";
}

export interface BusySessionProjection {
  readonly sessionId: string;
  readonly mode: BusyInputMode;
  readonly revision: number;
  readonly activeTurnId: string | null;
  readonly pendingCount: number;
  readonly pending: readonly PendingBusyInputItem[];
}

export interface BusyInputControlViewModel {
  readonly sessionId: string;
  readonly isTurnActive: boolean;
  readonly turnBusy: boolean;
  readonly controlsDisabled: boolean;
  readonly mode: BusyInputMode;
  readonly modeLabel: string;
  readonly submitLabel: string;
  readonly cancelLabel: string;
  readonly canCancelTurn: boolean;
  readonly ariaLiveStatus: string;
  readonly pendingBadgeText: string;
  readonly pendingItems: readonly PendingBusyInputItem[];
}

const MODE_LABELS: Record<BusyControlLocale, Record<BusyInputMode, string>> = {
  en: {
    queue: "Queue after current turn",
    interrupt: "Interrupt current turn",
    steer: "Steer active turn",
  },
  ko: {
    queue: "현재 응답 후 대기열 추가",
    interrupt: "현재 응답 중단 후 전환",
    steer: "진행 중인 응답 방향 조정",
  },
};

const SUBMIT_LABELS: Record<BusyControlLocale, Record<BusyInputMode, string>> = {
  en: {
    queue: "Queue follow-up",
    interrupt: "Interrupt & send",
    steer: "Steer turn",
  },
  ko: {
    queue: "대기열에 추가",
    interrupt: "중단 후 전송",
    steer: "응답 조향 전송",
  },
};

export function decodeBusySessionProjection(raw: unknown): BusySessionProjection {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("busy session projection must be an object");
  }
  const obj = raw as Record<string, unknown>;
  const sessionId = typeof obj.session_id === "string" ? obj.session_id.trim() : "";
  if (!sessionId) {
    throw new Error("busy session projection requires session_id");
  }
  const mode = obj.mode;
  if (mode !== "queue" && mode !== "interrupt" && mode !== "steer") {
    throw new Error("busy session projection has invalid mode");
  }
  const revision = typeof obj.revision === "number" && Number.isInteger(obj.revision) ? obj.revision : -1;
  if (revision < 0) {
    throw new Error("busy session projection requires non-negative integer revision");
  }
  const activeTurnId = typeof obj.active_turn_id === "string" && obj.active_turn_id.trim()
    ? obj.active_turn_id.trim()
    : null;
  if (obj.turn_busy === true && activeTurnId === null) {
    throw new Error("busy session projection cannot have turn_busy=true without active_turn_id");
  }
  if (
    typeof obj.queued_count === "number" &&
    (!Number.isInteger(obj.queued_count) || obj.queued_count < 0 || obj.queued_count > 1000)
  ) {
    throw new Error("busy session projection queued_count must be between 0 and 1000");
  }
  if (
    typeof obj.pending_count === "number" &&
    (!Number.isInteger(obj.pending_count) || obj.pending_count < 0 || obj.pending_count > 1000)
  ) {
    throw new Error("busy session projection pending_count must be between 0 and 1000");
  }
  const rawPending = Array.isArray(obj.pending) ? obj.pending : [];
  if (rawPending.length > 1000) {
    throw new Error("busy session projection pending items must not exceed 1000");
  }
  const pending: PendingBusyInputItem[] = rawPending.map((entry) => {
    if (typeof entry !== "object" || entry === null) {
      throw new Error("pending busy input item must be an object");
    }
    const item = entry as Record<string, unknown>;
    const disposition = String(item.disposition ?? "queued");
    if (
      disposition !== "queued" &&
      disposition !== "interrupting" &&
      disposition !== "steered" &&
      disposition !== "rejected"
    ) {
      throw new Error("pending busy input item has invalid disposition");
    }
    const status = String(item.status ?? "pending");
    if (
      status !== "pending" &&
      status !== "consumed" &&
      status !== "expired" &&
      status !== "rejected"
    ) {
      throw new Error("pending busy input item has invalid status");
    }
    return {
      inputId: String(item.input_id ?? ""),
      idempotencyKey: String(item.idempotency_key ?? ""),
      sequence: Number(item.sequence ?? 0),
      content: String(item.content ?? ""),
      disposition,
      status,
    };
  });
  return {
    sessionId,
    mode,
    revision,
    activeTurnId,
    pendingCount: pending.length,
    pending,
  };
}

export function buildBusyInputControlViewModel(
  projection: BusySessionProjection,
  locale: BusyControlLocale = "en",
  options?: { readonly controlsDisabled?: boolean },
): BusyInputControlViewModel {
  const isTurnActive = projection.activeTurnId !== null;
  const modeLabel = MODE_LABELS[locale][projection.mode];
  const submitLabel = isTurnActive
    ? SUBMIT_LABELS[locale][projection.mode]
    : locale === "ko"
      ? "메시지 전송"
      : "Send message";
  const cancelLabel = locale === "ko" ? "현재 응답 취소" : "Cancel active turn";
  const pendingBadgeText = locale === "ko"
    ? `대기 중 ${projection.pendingCount}건`
    : `${projection.pendingCount} pending`;
  const ariaLiveStatus = isTurnActive
    ? locale === "ko"
      ? `진행 중인 응답 있음 (${modeLabel}, ${pendingBadgeText})`
      : `Active turn in progress (${modeLabel}, ${pendingBadgeText})`
    : locale === "ko"
      ? "대기 상태"
      : "Idle";

  return {
    sessionId: projection.sessionId,
    isTurnActive,
    turnBusy: isTurnActive,
    controlsDisabled: Boolean(options?.controlsDisabled),
    mode: projection.mode,
    modeLabel,
    submitLabel,
    cancelLabel,
    canCancelTurn: isTurnActive,
    ariaLiveStatus,
    pendingBadgeText,
    pendingItems: projection.pending,
  };
}

export function buildBusySubmitRequest(params: {
  readonly sessionId: string;
  readonly inputId: string;
  readonly idempotencyKey: string;
  readonly content: string;
  readonly kind?: "prose" | "approval" | "denial" | "emergency_stop";
}): Record<string, unknown> {
  const trimmed = params.content.trim();
  if (!trimmed) {
    throw new Error("busy input content must not be empty");
  }
  return {
    session_id: params.sessionId.trim(),
    input_id: params.inputId.trim(),
    idempotency_key: params.idempotencyKey.trim(),
    content: trimmed,
    kind: params.kind ?? "prose",
  };
}

export function buildBusyModeChangeRequest(params: {
  readonly sessionId: string;
  readonly mode: BusyInputMode;
  readonly expectedRevision: number;
}): Record<string, unknown> {
  return {
    session_id: params.sessionId.trim(),
    mode: params.mode,
    expected_revision: params.expectedRevision,
  };
}

export function buildBusyCancelRequest(params: {
  readonly sessionId: string;
  readonly expectedRevision: number;
}): Record<string, unknown> {
  return {
    session_id: params.sessionId.trim(),
    expected_revision: params.expectedRevision,
  };
}
